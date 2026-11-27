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

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from backend.audio_frontend.f0_b.double_talk import AdaptationDecision


class AecOutputStatus(StrEnum):
    """Output status of the AEC stage (decoupled from filter weight adaptation)."""

    ACTIVE = "ACTIVE"
    FROZEN_FILTER = "FROZEN_FILTER"
    BYPASS = "BYPASS"
    RESET = "RESET"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class AecProcessResult:
    """Result of executing BoundedNlmsAec on one audio block."""

    samples: np.ndarray
    echo_estimate: np.ndarray
    output_status: AecOutputStatus
    adaptation_decision: AdaptationDecision
    weights_norm: float
    diverged: bool = False
    reason: str = "ok"


class BoundedNlmsAec:
    """
    Bounded CPU-only deterministic Normalized LMS (NLMS) FIR Acoustic Echo Canceller.

    - Separate learning control (`AdaptationDecision`) and output cancellation (`AecOutputStatus`).
    - Enforces finite weights, norm cap, low-energy denominator guard, and divergence reset.
    - Never shares mutable weights/history across stream incarnations or epochs.
    """

    def __init__(
        self,
        *,
        sample_rate_hz: int = 16000,
        filter_len_ms: float = 64.0,
        mu: float = 0.25,
        leakage: float = 1e-4,
        epsilon: float = 1e-4,
        max_weight_norm: float = 4.0,
        divergence_ratio: float = 2.5,
    ) -> None:
        self.sample_rate_hz = int(sample_rate_hz)
        self.filter_taps = max(16, min(4096, int(round(filter_len_ms * self.sample_rate_hz / 1000.0))))
        if not (0.0 < mu < 2.0):
            raise ValueError("NLMS mu must be in (0, 2)")
        self.mu = float(mu)
        self.leakage = float(max(0.0, min(0.05, leakage)))
        self.epsilon = float(max(1e-8, epsilon))
        self.max_weight_norm = float(max(0.1, max_weight_norm))
        self.divergence_ratio = float(max(1.2, divergence_ratio))

        self._weights = np.zeros(self.filter_taps, dtype=np.float64)
        self._ref_hist = np.zeros(self.filter_taps - 1, dtype=np.float64)

    def reset(self) -> None:
        """Reset FIR weights and reference delay line."""
        self._weights.fill(0.0)
        self._ref_hist.fill(0.0)

    @property
    def weights_norm(self) -> float:
        return float(np.linalg.norm(self._weights))

    def process_block(
        self,
        mic_samples: np.ndarray,
        aligned_ref: np.ndarray | None,
        *,
        adaptation: AdaptationDecision = AdaptationDecision.UPDATE,
        bypass: bool = False,
    ) -> AecProcessResult:
        """
        Process one mic block with optional aligned reference at self.sample_rate_hz.

        When bypass=True or aligned_ref is None/mismatched, passes mic_samples through
        unchanged without fabricating silence.
        """
        mic = np.ascontiguousarray(mic_samples, dtype=np.float32)
        n = len(mic)
        if n == 0:
            return AecProcessResult(
                samples=mic.copy(),
                echo_estimate=np.zeros(0, dtype=np.float32),
                output_status=AecOutputStatus.BYPASS,
                adaptation_decision=AdaptationDecision.BYPASS,
                weights_norm=self.weights_norm,
                reason="empty_block",
            )

        if not np.isfinite(mic).all():
            raise ValueError("Non-finite mic samples passed to BoundedNlmsAec")

        if bypass or aligned_ref is None or len(aligned_ref) != n or adaptation == AdaptationDecision.BYPASS:
            return AecProcessResult(
                samples=mic.copy(),
                echo_estimate=np.zeros(n, dtype=np.float32),
                output_status=AecOutputStatus.BYPASS,
                adaptation_decision=AdaptationDecision.BYPASS,
                weights_norm=self.weights_norm,
                reason="aec_bypass_or_no_ref",
            )

        ref = np.ascontiguousarray(aligned_ref, dtype=np.float32)
        if not np.isfinite(ref).all():
            return AecProcessResult(
                samples=mic.copy(),
                echo_estimate=np.zeros(n, dtype=np.float32),
                output_status=AecOutputStatus.BYPASS,
                adaptation_decision=AdaptationDecision.BYPASS,
                weights_norm=self.weights_norm,
                reason="non_finite_reference_bypass",
            )

        if adaptation == AdaptationDecision.RESET:
            self.reset()
            return AecProcessResult(
                samples=mic.copy(),
                echo_estimate=np.zeros(n, dtype=np.float32),
                output_status=AecOutputStatus.RESET,
                adaptation_decision=AdaptationDecision.RESET,
                weights_norm=0.0,
                reason="aec_reset_requested",
            )

        gate = 0.0
        if adaptation == AdaptationDecision.UPDATE:
            gate = 1.0
        elif adaptation == AdaptationDecision.LIMITED_UPDATE:
            gate = 0.25

        taps = self.filter_taps
        padded_ref = np.concatenate((self._ref_hist, ref.astype(np.float64)))
        mic_f64 = mic.astype(np.float64)
        out = np.empty(n, dtype=np.float64)
        e_hat_arr = np.empty(n, dtype=np.float64)

        w = self._weights
        mu_g = self.mu * gate
        leak_factor = 1.0 - self.leakage

        for i in range(n):
            # Reverse slice so r_vec[0] is current sample ref[i], r_vec[taps-1] is oldest
            r_vec = padded_ref[i + taps - 1 : i - 1 if i > 0 else None : -1]
            if len(r_vec) != taps:
                r_vec = padded_ref[i : i + taps][::-1]
            e_hat = float(np.dot(w, r_vec))
            err = mic_f64[i] - e_hat
            e_hat_arr[i] = e_hat
            out[i] = err
            if mu_g > 0.0:
                norm_sq = float(np.dot(r_vec, r_vec))
                if norm_sq > 1e-10:
                    step = (mu_g * err) / (self.epsilon + norm_sq)
                    w = leak_factor * w + step * r_vec

        # Update reference history tail
        self._ref_hist = padded_ref[-(taps - 1) :].copy() if taps > 1 else np.zeros(0, dtype=np.float64)

        # Finite & norm cap & divergence protection
        if not np.isfinite(w).all() or not np.isfinite(out).all():
            self.reset()
            return AecProcessResult(
                samples=mic.copy(),
                echo_estimate=np.zeros(n, dtype=np.float32),
                output_status=AecOutputStatus.RESET,
                adaptation_decision=AdaptationDecision.RESET,
                weights_norm=0.0,
                diverged=True,
                reason="non_finite_divergence_reset",
            )

        w_norm = float(np.linalg.norm(w))
        if w_norm > self.max_weight_norm:
            w = w * (self.max_weight_norm / w_norm)
            w_norm = self.max_weight_norm

        mic_energy = float(np.dot(mic_f64, mic_f64))
        out_energy = float(np.dot(out, out))
        if mic_energy > 1e-8 and out_energy > self.divergence_ratio * mic_energy:
            self.reset()
            return AecProcessResult(
                samples=mic.copy(),
                echo_estimate=np.zeros(n, dtype=np.float32),
                output_status=AecOutputStatus.RESET,
                adaptation_decision=AdaptationDecision.RESET,
                weights_norm=0.0,
                diverged=True,
                reason="energy_divergence_reset",
            )

        self._weights = w
        out_f32 = np.clip(out, -1.0, 1.0).astype(np.float32)
        e_hat_f32 = np.clip(e_hat_arr, -1.0, 1.0).astype(np.float32)
        status = AecOutputStatus.ACTIVE if gate > 0.0 else AecOutputStatus.FROZEN_FILTER
        return AecProcessResult(
            samples=np.ascontiguousarray(out_f32, dtype=np.float32),
            echo_estimate=np.ascontiguousarray(e_hat_f32, dtype=np.float32),
            output_status=status,
            adaptation_decision=adaptation,
            weights_norm=w_norm,
            diverged=False,
            reason="ok",
        )
