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


class DoubleTalkCategory(StrEnum):
    """Uncertain acoustic activity classification (never a semantic or F1 interruption decision)."""

    FAR_END_ONLY_LIKELY = "FAR_END_ONLY_LIKELY"
    NEAR_END_ONLY_LIKELY = "NEAR_END_ONLY_LIKELY"
    DOUBLE_TALK_LIKELY = "DOUBLE_TALK_LIKELY"
    NO_RELIABLE_ACTIVITY = "NO_RELIABLE_ACTIVITY"
    UNKNOWN = "UNKNOWN"


class AdaptationDecision(StrEnum):
    """AEC filter learning decision decoupled from cancellation output."""

    UPDATE = "UPDATE"
    LIMITED_UPDATE = "LIMITED_UPDATE"
    FREEZE = "FREEZE"
    RESET = "RESET"
    BYPASS = "BYPASS"


@dataclass(frozen=True, slots=True)
class DoubleTalkEvidence:
    """Immutable per-block double-talk observation for AEC adaptation & F1-C metadata."""

    category: DoubleTalkCategory
    adaptation_decision: AdaptationDecision
    far_end_energy_db: float | None
    near_end_energy_db: float | None
    residual_energy_db: float | None
    coherence: float | None
    delay_stable: bool
    reason: str
    interval_start: int
    interval_end_exclusive: int


def _rms_db(samples: np.ndarray) -> float | None:
    if len(samples) == 0:
        return None
    mean_sq = float(np.mean(samples.astype(np.float64) ** 2))
    if mean_sq <= 1e-12:
        return -120.0
    return 10.0 * math.log10(mean_sq)


class DoubleTalkClassifier:
    """
    Conservative causal double-talk detector using local mic, aligned reference,
    and residual energies + normalized coherence.
    """

    def __init__(
        self,
        *,
        activity_floor_db: float = -50.0,
        far_end_coherence_min: float = 0.50,
        double_talk_residual_ratio_db: float = -6.0,
    ) -> None:
        self.activity_floor_db = float(activity_floor_db)
        self.far_end_coherence_min = float(far_end_coherence_min)
        self.double_talk_residual_ratio_db = float(double_talk_residual_ratio_db)

    def classify(
        self,
        *,
        mic_samples: np.ndarray,
        aligned_ref_samples: np.ndarray | None,
        residual_samples: np.ndarray | None = None,
        delay_confident: bool = False,
        interval_start: int = 0,
        interval_end_exclusive: int = 0,
    ) -> DoubleTalkEvidence:
        mic_db = _rms_db(mic_samples)

        if aligned_ref_samples is None or len(aligned_ref_samples) != len(mic_samples) or len(mic_samples) == 0:
            return DoubleTalkEvidence(
                category=DoubleTalkCategory.UNKNOWN,
                adaptation_decision=AdaptationDecision.BYPASS,
                far_end_energy_db=None,
                near_end_energy_db=mic_db,
                residual_energy_db=None,
                coherence=None,
                delay_stable=False,
                reason="reference_unavailable_or_unaligned",
                interval_start=interval_start,
                interval_end_exclusive=interval_end_exclusive,
            )

        ref_db = _rms_db(aligned_ref_samples)
        res = residual_samples if residual_samples is not None else mic_samples
        res_db = _rms_db(res)

        mic_active = mic_db is not None and mic_db > self.activity_floor_db
        ref_active = ref_db is not None and ref_db > self.activity_floor_db

        # Compute zero-lag normalized coherence on aligned block
        x = mic_samples.astype(np.float64)
        r = aligned_ref_samples.astype(np.float64)
        denom = math.sqrt(float(np.dot(x, x)) * float(np.dot(r, r))) + 1e-12
        coherence = float(abs(np.dot(x, r)) / denom) if (mic_active and ref_active) else 0.0

        if not mic_active and not ref_active:
            return DoubleTalkEvidence(
                category=DoubleTalkCategory.NO_RELIABLE_ACTIVITY,
                adaptation_decision=AdaptationDecision.FREEZE,
                far_end_energy_db=ref_db,
                near_end_energy_db=mic_db,
                residual_energy_db=res_db,
                coherence=coherence,
                delay_stable=delay_confident,
                reason="both_below_activity_floor",
                interval_start=interval_start,
                interval_end_exclusive=interval_end_exclusive,
            )

        if mic_active and not ref_active:
            return DoubleTalkEvidence(
                category=DoubleTalkCategory.NEAR_END_ONLY_LIKELY,
                adaptation_decision=AdaptationDecision.FREEZE,
                far_end_energy_db=ref_db,
                near_end_energy_db=mic_db,
                residual_energy_db=res_db,
                coherence=coherence,
                delay_stable=delay_confident,
                reason="near_end_active_far_end_silent",
                interval_start=interval_start,
                interval_end_exclusive=interval_end_exclusive,
            )

        if not mic_active and ref_active:
            return DoubleTalkEvidence(
                category=DoubleTalkCategory.FAR_END_ONLY_LIKELY,
                adaptation_decision=AdaptationDecision.LIMITED_UPDATE if delay_confident else AdaptationDecision.FREEZE,
                far_end_energy_db=ref_db,
                near_end_energy_db=mic_db,
                residual_energy_db=res_db,
                coherence=coherence,
                delay_stable=delay_confident,
                reason="far_end_active_mic_quiet",
                interval_start=interval_start,
                interval_end_exclusive=interval_end_exclusive,
            )

        # Both mic and ref active: distinguish FAR_END_ONLY vs DOUBLE_TALK
        if not delay_confident:
            return DoubleTalkEvidence(
                category=DoubleTalkCategory.UNKNOWN,
                adaptation_decision=AdaptationDecision.FREEZE,
                far_end_energy_db=ref_db,
                near_end_energy_db=mic_db,
                residual_energy_db=res_db,
                coherence=coherence,
                delay_stable=False,
                reason="delay_unverified",
                interval_start=interval_start,
                interval_end_exclusive=interval_end_exclusive,
            )

        # If coherence is high and residual dropped significantly below mic, far-end echo dominates
        residual_drop_db = (res_db - mic_db) if (res_db is not None and mic_db is not None) else 0.0
        if coherence >= self.far_end_coherence_min and residual_drop_db <= self.double_talk_residual_ratio_db:
            return DoubleTalkEvidence(
                category=DoubleTalkCategory.FAR_END_ONLY_LIKELY,
                adaptation_decision=AdaptationDecision.UPDATE,
                far_end_energy_db=ref_db,
                near_end_energy_db=mic_db,
                residual_energy_db=res_db,
                coherence=coherence,
                delay_stable=True,
                reason="high_coherence_echo_dominated",
                interval_start=interval_start,
                interval_end_exclusive=interval_end_exclusive,
            )

        if coherence >= self.far_end_coherence_min and residual_samples is None:
            return DoubleTalkEvidence(
                category=DoubleTalkCategory.FAR_END_ONLY_LIKELY,
                adaptation_decision=AdaptationDecision.UPDATE,
                far_end_energy_db=ref_db,
                near_end_energy_db=mic_db,
                residual_energy_db=res_db,
                coherence=coherence,
                delay_stable=True,
                reason="high_coherence_far_end_only",
                interval_start=interval_start,
                interval_end_exclusive=interval_end_exclusive,
            )

        # Low coherence or strong uncorrelated residual => double-talk likely -> FREEZE adaptation!
        return DoubleTalkEvidence(
            category=DoubleTalkCategory.DOUBLE_TALK_LIKELY,
            adaptation_decision=AdaptationDecision.FREEZE,
            far_end_energy_db=ref_db,
            near_end_energy_db=mic_db,
            residual_energy_db=res_db,
            coherence=coherence,
            delay_stable=True,
            reason="uncorrelated_near_end_energy_present",
            interval_start=interval_start,
            interval_end_exclusive=interval_end_exclusive,
        )
