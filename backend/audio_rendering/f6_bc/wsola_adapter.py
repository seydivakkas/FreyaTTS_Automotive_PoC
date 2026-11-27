"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class RateOwner(StrEnum):
    NONE = "NONE"
    F5 = "F5"
    F6 = "F6"


@dataclass(frozen=True, slots=True)
class RateDisposition:
    control_id: str
    requested_factor: float | None
    support_status: str
    owner: RateOwner
    planned_factor: float
    model_applied_factor: float | None
    renderer_applied_factor: float | None
    observed_duration_ratio: float | None
    reason: str


def resolve_rate_ownership(
    *,
    control_id: str,
    requested_speed: float | None,
    model_applied_speed: float | None,
    wsola_enabled: bool,
    min_factor: float = 0.94,
    max_factor: float = 1.06,
) -> RateDisposition:
    """
    Single-owner rate disposition preventing double application between F5 and F6.
    Never silently clamps an out-of-range requested_speed.
    """
    if requested_speed is None:
        return RateDisposition(
            control_id=control_id,
            requested_factor=None,
            support_status="NO_OP",
            owner=RateOwner.NONE,
            planned_factor=1.0,
            model_applied_factor=model_applied_speed,
            renderer_applied_factor=None,
            observed_duration_ratio=None,
            reason="NO_SPEED_REQUESTED",
        )
    if isinstance(requested_speed, bool) or not isinstance(requested_speed, (int, float)) or not math.isfinite(float(requested_speed)):
        return RateDisposition(
            control_id=control_id,
            requested_factor=None,
            support_status="REJECTED",
            owner=RateOwner.NONE,
            planned_factor=1.0,
            model_applied_factor=model_applied_speed,
            renderer_applied_factor=None,
            observed_duration_ratio=None,
            reason="NON_FINITE_SPEED",
        )

    req = float(requested_speed)
    if model_applied_speed is not None and abs(float(model_applied_speed) - req) <= 1e-6:
        return RateDisposition(
            control_id=control_id,
            requested_factor=req,
            support_status="ALREADY_APPLIED_UPSTREAM",
            owner=RateOwner.F5,
            planned_factor=1.0,
            model_applied_factor=float(model_applied_speed),
            renderer_applied_factor=1.0,
            observed_duration_ratio=None,
            reason="SPEED_OWNED_BY_F5",
        )

    if abs(req - 1.0) <= 1e-6:
        return RateDisposition(
            control_id=control_id,
            requested_factor=1.0,
            support_status="BYPASS",
            owner=RateOwner.NONE,
            planned_factor=1.0,
            model_applied_factor=model_applied_speed,
            renderer_applied_factor=1.0,
            observed_duration_ratio=1.0,
            reason="UNITY_FACTOR_BYPASS",
        )

    if not wsola_enabled:
        return RateDisposition(
            control_id=control_id,
            requested_factor=req,
            support_status="UNSUPPORTED",
            owner=RateOwner.NONE,
            planned_factor=1.0,
            model_applied_factor=model_applied_speed,
            renderer_applied_factor=None,
            observed_duration_ratio=None,
            reason="WSOLA_DISABLED",
        )

    if req < min_factor or req > max_factor:
        return RateDisposition(
            control_id=control_id,
            requested_factor=req,
            support_status="UNSUPPORTED",
            owner=RateOwner.NONE,
            planned_factor=1.0,
            model_applied_factor=model_applied_speed,
            renderer_applied_factor=None,
            observed_duration_ratio=None,
            reason="OUTSIDE_WSOLA_RANGE",
        )

    return RateDisposition(
        control_id=control_id,
        requested_factor=req,
        support_status="SUPPORTED",
        owner=RateOwner.F6,
        planned_factor=req,
        model_applied_factor=model_applied_speed,
        renderer_applied_factor=req,
        observed_duration_ratio=None,
        reason="OWNED_BY_F6_WSOLA",
    )


@dataclass(frozen=True, slots=True)
class WSOLAConfig:
    sample_rate_hz: int = 48000
    window_samples: int = 1200  # 25 ms at 48 kHz
    hop_synth_samples: int = 600  # 50% overlap (12.5 ms)
    search_radius_samples: int = 480  # +-10 ms
    min_factor: float = 0.94
    max_factor: float = 1.06


class WSOLAAdapter:
    """
    Bounded deterministic 48 kHz WSOLA time-scale adapter.

    - Exact bypass (zero algorithmic delay) when factor == 1.0.
    - Deterministic normalized cross-correlation search with silence fallback.
    - Tracks exact input_samples and output_samples.
    """

    def __init__(self, config: WSOLAConfig | None = None) -> None:
        self.config = config or WSOLAConfig()
        self._hann = np.hanning(self.config.window_samples).astype(np.float32)
        self.input_samples = 0
        self.output_samples = 0
        self._carry = np.zeros(0, dtype=np.float32)

    def reset(self) -> None:
        self._carry = np.zeros(0, dtype=np.float32)
        self.input_samples = 0
        self.output_samples = 0

    def process_chunk(self, samples_48k: np.ndarray, *, factor: float = 1.0) -> np.ndarray:
        arr = np.asarray(samples_48k, dtype=np.float32)
        if arr.ndim != 1:
            raise ValueError("WSOLA input must be 1D float32 array")
        if arr.size == 0:
            return np.zeros(0, dtype=np.float32)
        if not bool(np.isfinite(arr).all()):
            raise ValueError("WSOLA input contains non-finite samples")
        if isinstance(factor, bool) or not math.isfinite(factor):
            raise ValueError("WSOLA factor must be finite")

        self.input_samples += int(arr.size)

        if abs(factor - 1.0) <= 1e-6:
            out = np.array(arr, dtype=np.float32, copy=True)
            self.output_samples += int(out.size)
            return out

        if factor < self.config.min_factor or factor > self.config.max_factor:
            raise ValueError(
                f"WSOLA factor {factor} outside approved range [{self.config.min_factor}, {self.config.max_factor}]"
            )

        wlen = self.config.window_samples
        hs = self.config.hop_synth_samples
        ha = factor * hs
        search = self.config.search_radius_samples

        buf = np.concatenate([self._carry, arr]) if self._carry.size > 0 else arr
        if buf.size < wlen:
            self._carry = buf.copy()
            return np.zeros(0, dtype=np.float32)

        target_len = max(wlen, int(round(buf.size / factor)))
        out = np.zeros(target_len + wlen, dtype=np.float32)
        norm = np.zeros(target_len + wlen, dtype=np.float32)

        # Seed first frame
        out[:wlen] += buf[:wlen] * self._hann
        norm[:wlen] += self._hann

        in_pos = ha
        out_pos = hs
        last_in_end = wlen

        while int(round(in_pos)) + wlen <= buf.size and out_pos + wlen <= out.size:
            nominal = int(round(in_pos))
            lo = max(0, nominal - search)
            hi = min(buf.size - wlen, nominal + search)

            # Reference overlap from already synthesized tail
            ref = out[out_pos : out_pos + hs]
            ref_norm = float(np.sqrt(np.dot(ref, ref)))

            best_idx = nominal
            if ref_norm > 1e-6 and hi > lo:
                best_corr = -2.0
                best_dist = search + 1
                for cand in range(lo, hi + 1):
                    seg = buf[cand : cand + hs]
                    seg_norm = float(np.sqrt(np.dot(seg, seg)))
                    corr = float(np.dot(ref, seg)) / (ref_norm * seg_norm + 1e-12)
                    dist = abs(cand - nominal)
                    if corr > best_corr + 1e-9 or (abs(corr - best_corr) <= 1e-9 and dist < best_dist):
                        best_corr = corr
                        best_idx = cand
                        best_dist = dist

            frame = buf[best_idx : best_idx + wlen] * self._hann
            out[out_pos : out_pos + wlen] += frame
            norm[out_pos : out_pos + wlen] += self._hann
            last_in_end = max(last_in_end, best_idx + wlen)
            in_pos += ha
            out_pos += hs

        valid_end = min(out.size, out_pos + hs)
        mask = norm[:valid_end] > 1e-6
        result = np.zeros(valid_end, dtype=np.float32)
        result[mask] = out[:valid_end][mask] / norm[:valid_end][mask]

        consumed = max(0, min(buf.size, last_in_end))
        self._carry = buf[consumed:].copy() if consumed < buf.size else np.zeros(0, dtype=np.float32)
        self.output_samples += int(result.size)
        return result

    def flush_eos(self) -> np.ndarray:
        if self._carry.size == 0:
            return np.zeros(0, dtype=np.float32)
        tail = self._carry
        self._carry = np.zeros(0, dtype=np.float32)
        self.output_samples += int(tail.size)
        return tail

    def abort_discard(self) -> int:
        discarded = int(self._carry.size)
        self._carry = np.zeros(0, dtype=np.float32)
        return discarded
