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

import numpy as np

from backend.audio_rendering.profile_adapter import QuantizationPolicy


@dataclass(frozen=True, slots=True)
class QuantizationResult:
    """Explicit PCM_S16LE quantization output and separate saturation telemetry."""

    pcm_bytes: bytes
    sample_count: int
    saturated_count: int
    overrange_positive_count: int
    overrange_negative_count: int
    peak_abs: float
    rms_dbfs: float | None
    policy: QuantizationPolicy


def quantize_float32_to_pcm16le(
    samples: np.ndarray,
    *,
    policy: QuantizationPolicy = QuantizationPolicy.SATURATING_32768,
) -> QuantizationResult:
    """
    Quantize finite float32 samples to signed little-endian 16-bit PCM (`<i2`).

    - Rejects non-finite samples before conversion (never converts NaN/Inf to zero).
    - SATURATING_32768: `clip(rint(clip(x, -1, 1) * 32768), -32768, 32767)` with IEEE-754
      ties-to-even (`0 -> 0`, `-1 -> -32768`, `+1 -> 32767`).
    - SYMMETRIC_32767: `rint(clip(x, -1, 1) * 32767)` preserving legacy `backend/audio.py`
      and `backend/dsp.py` scale (`0 -> 0`, `-1 -> -32767`, `+1 -> 32767`).
    - Returns `rms_dbfs=None` on exact silence (never `-Inf` JSON).
    """
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim != 1:
        raise ValueError("Quantizer requires 1D float32 sample array")
    if arr.size == 0:
        return QuantizationResult(
            pcm_bytes=b"",
            sample_count=0,
            saturated_count=0,
            overrange_positive_count=0,
            overrange_negative_count=0,
            peak_abs=0.0,
            rms_dbfs=None,
            policy=policy,
        )
    if not bool(np.isfinite(arr).all()):
        raise ValueError("Cannot quantize non-finite (NaN/Inf) samples")

    arr_f64 = arr.astype(np.float64, copy=False)
    over_pos = int(np.count_nonzero(arr_f64 > 1.0))
    over_neg = int(np.count_nonzero(arr_f64 < -1.0))
    peak_abs = float(np.max(np.abs(arr_f64)))
    mean_sq = float(np.mean(arr_f64 * arr_f64))
    rms_dbfs = 10.0 * math.log10(mean_sq) if mean_sq > 0.0 else None

    if policy == QuantizationPolicy.SATURATING_32768:
        scaled = np.rint(np.clip(arr_f64, -1.0, 1.0) * 32768.0)
        # +1.0 * 32768 -> 32768 saturates to 32767 without integer wrap-around
        saturated_positive_limit = int(np.count_nonzero(scaled > 32767.0))
        clipped_int = np.clip(scaled, -32768.0, 32767.0).astype("<i2")
        saturated_count = over_pos + over_neg + saturated_positive_limit
    elif policy == QuantizationPolicy.SYMMETRIC_32767:
        scaled = np.rint(np.clip(arr_f64, -1.0, 1.0) * 32767.0)
        clipped_int = np.clip(scaled, -32767.0, 32767.0).astype("<i2")
        saturated_count = over_pos + over_neg
    else:
        raise ValueError(f"Unsupported QuantizationPolicy: {policy!r}")

    return QuantizationResult(
        pcm_bytes=clipped_int.tobytes(),
        sample_count=int(arr.size),
        saturated_count=saturated_count,
        overrange_positive_count=over_pos,
        overrange_negative_count=over_neg,
        peak_abs=peak_abs,
        rms_dbfs=rms_dbfs,
        policy=policy,
    )
