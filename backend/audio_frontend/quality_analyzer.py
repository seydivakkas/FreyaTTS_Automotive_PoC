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

from backend.core.contracts.common import MetricStatus


@dataclass(frozen=True, slots=True)
class AudioQualityMetrics:
    """Finite signal metrics (RMS, dBFS, peak, clipping). Never infers SNR or WER."""

    sample_count: int
    valid_sample_count: int
    linear_rms: float
    rms_dbfs: float | None
    rms_dbfs_status: MetricStatus
    rms_dbfs_reason: str | None
    peak: float
    clipped_samples: int
    clip_stage: str
    clip_denominator: int


def analyze_float32_quality(
    samples: np.ndarray,
    *,
    valid_sample_count: int | None = None,
    stage: str = "output",
    clip_threshold: float = 1.0 - 1e-6,
) -> AudioQualityMetrics:
    """
    Compute linear RMS, dBFS (None for exact silence), peak, and clipping count.

    Analyzes only valid samples (excluding terminal padding).
    """
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim != 1:
        raise ValueError("analyze_float32_quality expects 1D mono array")
    total_n = int(arr.shape[0])
    if valid_sample_count is None:
        valid_n = total_n
    else:
        if type(valid_sample_count) is not int or valid_sample_count < 0 or valid_sample_count > total_n:
            raise ValueError("valid_sample_count out of range")
        valid_n = valid_sample_count

    if valid_n == 0:
        return AudioQualityMetrics(
            sample_count=total_n,
            valid_sample_count=0,
            linear_rms=0.0,
            rms_dbfs=None,
            rms_dbfs_status=MetricStatus.UNAVAILABLE,
            rms_dbfs_reason="no_valid_samples",
            peak=0.0,
            clipped_samples=0,
            clip_stage=stage,
            clip_denominator=0,
        )

    valid_view = arr[:valid_n]
    if not np.isfinite(valid_view).all():
        raise ValueError("Non-finite samples cannot be analyzed")

    abs_vals = np.abs(valid_view)
    peak = float(np.max(abs_vals))
    mean_sq = float(np.mean(valid_view.astype(np.float64) ** 2))
    linear_rms = math.sqrt(max(mean_sq, 0.0))
    clipped = int(np.count_nonzero(abs_vals >= clip_threshold))

    if linear_rms <= 0.0:
        return AudioQualityMetrics(
            sample_count=total_n,
            valid_sample_count=valid_n,
            linear_rms=0.0,
            rms_dbfs=None,
            rms_dbfs_status=MetricStatus.UNAVAILABLE,
            rms_dbfs_reason="silence_zero_rms",
            peak=0.0,
            clipped_samples=clipped,
            clip_stage=stage,
            clip_denominator=valid_n,
        )

    dbfs = 20.0 * math.log10(linear_rms)
    return AudioQualityMetrics(
        sample_count=total_n,
        valid_sample_count=valid_n,
        linear_rms=linear_rms,
        rms_dbfs=dbfs,
        rms_dbfs_status=MetricStatus.MEASURED,
        rms_dbfs_reason=None,
        peak=peak,
        clipped_samples=clipped,
        clip_stage=stage,
        clip_denominator=valid_n,
    )
