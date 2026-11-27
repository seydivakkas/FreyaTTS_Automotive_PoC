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

from backend.audio_frontend.f0_b.aec_adapter import AecOutputStatus
from backend.audio_frontend.f0_b.delay_estimator import DelayEstimate
from backend.audio_frontend.f0_b.double_talk import DoubleTalkEvidence
from backend.audio_frontend.f0_b.reference_adapter import ClockMappingStatus, DeliveryStatus
from backend.core.contracts.common import MetricStatus
from backend.core.contracts.playback import ObservationScope


class SnrMethod(StrEnum):
    """Distinguishes oracle synthetic fixture SNR from live single-channel estimates."""

    ORACLE_FIXTURE = "ORACLE_FIXTURE"
    ESTIMATED = "ESTIMATED"


class SnrTap(StrEnum):
    """Signal tap where SNR was observed."""

    PRE_AEC = "PRE_AEC"
    POST_AEC = "POST_AEC"
    PRE_NS = "PRE_NS"
    POST_NS = "POST_NS"
    POST_AGC = "POST_AGC"


def compute_oracle_snr_db(clean: np.ndarray, noise: np.ndarray, *, floor: float = 1e-12) -> float | None:
    """Compute exact oracle SNR dB for known isolated fixture clean/noise signals."""
    c = np.asarray(clean, dtype=np.float64)
    n = np.asarray(noise, dtype=np.float64)
    if len(c) == 0 or len(c) != len(n):
        return None
    s_pow = float(np.dot(c, c))
    n_pow = float(np.dot(n, n))
    if n_pow <= floor or s_pow <= floor:
        return None
    return 10.0 * math.log10(s_pow / n_pow)


def compute_erle_db(echo_before: np.ndarray, residual_after: np.ndarray, *, floor: float = 1e-10) -> float | None:
    """Compute ERLE = 10*log10(P_echo_before / P_residual_after) on eligible far-end-only windows."""
    eb = np.asarray(echo_before, dtype=np.float64)
    ra = np.asarray(residual_after, dtype=np.float64)
    if len(eb) == 0 or len(eb) != len(ra):
        return None
    p_before = float(np.mean(eb**2))
    p_after = float(np.mean(ra**2))
    if p_before <= floor or p_after <= floor:
        return None
    return 10.0 * math.log10(p_before / p_after)


@dataclass(frozen=True, slots=True)
class AcousticEvidence:
    """
    Immutable scoped acoustic metadata emitted by F0-B for F1-C / F2 / M04.

    Never contains raw PCM, transcripts, DTMF digits, or PII, and is never a command
    to cancel a generation or commit an interruption.
    """

    session_id: str
    input_stream_id: str
    input_format_epoch: int
    output_start_sample: int
    output_end_exclusive: int
    output_sample_rate_hz: int
    reference_stream_id: str | None
    reference_generation_id: int | None
    observation_scope: ObservationScope
    delivery_status: DeliveryStatus
    reference_coverage_fraction: float | None
    clock_mapping_status: ClockMappingStatus
    delay: DelayEstimate | None
    double_talk: DoubleTalkEvidence | None
    aec_status: AecOutputStatus
    erle_db: float | None
    snr_db: float | None
    snr_status: MetricStatus
    snr_method: SnrMethod
    snr_tap: SnrTap
    snr_reason: str | None
    noise_floor_dbfs: float | None
    noise_calibrated: bool
    clipping_fraction: float
    wind_turbulence_detected: bool
    profile_id: str
    profile_revision: str
    discontinuity: bool = False
