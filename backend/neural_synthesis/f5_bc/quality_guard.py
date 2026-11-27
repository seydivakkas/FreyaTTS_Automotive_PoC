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
from typing import Any, Callable

from backend.core.contracts.audio import AudioFormat
from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.core.contracts.synthesis import QualityStatus
from backend.neural_synthesis.config_adapter import BASELINE_SAMPLE_RATE_HZ
from backend.neural_synthesis.duration_estimator import DurationEstimate
from backend.neural_synthesis.raw_validator import RawAudioValidator, RawValidationResult

QUALITY_POLICY_REVISION = "f5b-quality-v1"


@dataclass(frozen=True, slots=True)
class QualityAssessment:
    """F5-B typed structural, duration, and collapse quality assessment (zero DSP)."""

    policy_revision: str
    structurally_valid: bool
    quality_status: QualityStatus
    sample_count: int
    actual_duration_ms: float
    peak_abs: float
    rms: float
    rms_dbfs: float | None
    dc_offset: float
    near_zero_fraction: float
    longest_silence_samples: int
    voiced_score: float | None
    duration_mismatch_ratio: float | None
    reason_codes: tuple[str, ...]
    retryable: bool
    error: ErrorInfo | None = None


class QualityGuard:
    """
    F5-B structural, duration, and collapse guard for raw 48 kHz mono FLOAT32_LE audio.

    - Reuses `RawAudioValidator` for hard structural checks.
    - Adds bounded CPU checks: `rms_dbfs` (None on zero energy), DC offset, near-zero fraction,
      longest consecutive silence run, and optional calibrated heuristic thresholds.
    - Never performs DSP, normalization, trimming, or tone replacement.
    """

    def __init__(
        self,
        *,
        raw_validator: RawAudioValidator | None = None,
        policy_revision: str = QUALITY_POLICY_REVISION,
        near_zero_eps: float = 1e-4,
        max_near_zero_fraction: float | None = None,
        max_silence_ms: float | None = None,
        calibrated_thresholds_approved: bool = False,
    ) -> None:
        self.raw_validator = raw_validator or RawAudioValidator()
        self.policy_revision = policy_revision
        self.near_zero_eps = near_zero_eps
        self.max_near_zero_fraction = max_near_zero_fraction
        self.max_silence_ms = max_silence_ms
        self.calibrated_thresholds_approved = calibrated_thresholds_approved

    def assess(
        self,
        *,
        payload: bytes,
        sample_count: int,
        audio_format: AudioFormat,
        estimate: DurationEstimate | None = None,
        collapse_guard_fn: Callable[[Any, int], bool | float] | None = None,
        collapse_guard_scope: str = "STRUCTURAL_PEAK_AND_FINITE",
    ) -> QualityAssessment:
        raw_res: RawValidationResult = self.raw_validator.validate(
            payload=payload,
            sample_count=sample_count,
            audio_format=audio_format,
            estimate=estimate,
            collapse_guard_fn=collapse_guard_fn,
            collapse_guard_scope=collapse_guard_scope,
        )
        actual_dur_ms = (max(0, raw_res.sample_count) * 1000.0) / float(BASELINE_SAMPLE_RATE_HZ)

        if not raw_res.structurally_valid:
            retryable = bool(
                raw_res.reason_codes
                and raw_res.reason_codes[0] in {"SILENT_MODEL_OUTPUT", "COLLAPSE_GUARD_REJECTED"}
            )
            return QualityAssessment(
                policy_revision=self.policy_revision,
                structurally_valid=False,
                quality_status=QualityStatus.FAIL,
                sample_count=raw_res.sample_count,
                actual_duration_ms=actual_dur_ms,
                peak_abs=raw_res.peak_abs,
                rms=raw_res.rms,
                rms_dbfs=(20.0 * math.log10(raw_res.rms)) if raw_res.rms > 0.0 else None,
                dc_offset=0.0,
                near_zero_fraction=1.0 if raw_res.rms == 0.0 else 0.0,
                longest_silence_samples=raw_res.sample_count if raw_res.rms == 0.0 else 0,
                voiced_score=raw_res.voiced_score,
                duration_mismatch_ratio=raw_res.duration_mismatch_ratio,
                reason_codes=raw_res.reason_codes,
                retryable=retryable,
                error=raw_res.error,
            )

        import numpy as np

        samples = np.frombuffer(payload, dtype="<f4")
        dc_offset = float(np.mean(samples.astype(np.float64)))
        near_zero_mask = np.abs(samples) < self.near_zero_eps
        near_zero_fraction = float(np.mean(near_zero_mask))
        longest_silence = self._longest_true_run(near_zero_mask)
        rms_dbfs = (20.0 * math.log10(raw_res.rms)) if raw_res.rms > 0.0 else None

        reasons = list(raw_res.reason_codes)

        if self.max_near_zero_fraction is not None and near_zero_fraction > self.max_near_zero_fraction:
            err = ErrorInfo(
                code="EXCESSIVE_NEAR_ZERO_FRACTION",
                category=ErrorCategory.PROVIDER,
                retryable=Retryability.YES,
                safe_message=f"Near-zero sample fraction {near_zero_fraction:.3f} exceeds {self.max_near_zero_fraction:.3f}",
            )
            return QualityAssessment(
                policy_revision=self.policy_revision,
                structurally_valid=False,
                quality_status=QualityStatus.FAIL,
                sample_count=raw_res.sample_count,
                actual_duration_ms=actual_dur_ms,
                peak_abs=raw_res.peak_abs,
                rms=raw_res.rms,
                rms_dbfs=rms_dbfs,
                dc_offset=dc_offset,
                near_zero_fraction=near_zero_fraction,
                longest_silence_samples=longest_silence,
                voiced_score=raw_res.voiced_score,
                duration_mismatch_ratio=raw_res.duration_mismatch_ratio,
                reason_codes=("EXCESSIVE_NEAR_ZERO_FRACTION",),
                retryable=True,
                error=err,
            )

        if self.max_silence_ms is not None:
            longest_ms = (longest_silence * 1000.0) / float(BASELINE_SAMPLE_RATE_HZ)
            if longest_ms > self.max_silence_ms:
                err = ErrorInfo(
                    code="EXCESSIVE_SILENCE_RUN",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.YES,
                    safe_message=f"Longest silence {longest_ms:.1f}ms exceeds {self.max_silence_ms:.1f}ms",
                )
                return QualityAssessment(
                    policy_revision=self.policy_revision,
                    structurally_valid=False,
                    quality_status=QualityStatus.FAIL,
                    sample_count=raw_res.sample_count,
                    actual_duration_ms=actual_dur_ms,
                    peak_abs=raw_res.peak_abs,
                    rms=raw_res.rms,
                    rms_dbfs=rms_dbfs,
                    dc_offset=dc_offset,
                    near_zero_fraction=near_zero_fraction,
                    longest_silence_samples=longest_silence,
                    voiced_score=raw_res.voiced_score,
                    duration_mismatch_ratio=raw_res.duration_mismatch_ratio,
                    reason_codes=("EXCESSIVE_SILENCE_RUN",),
                    retryable=True,
                    error=err,
                )

        # QualityStatus.PASS requires calibrated thresholds + heuristic evidence
        q_status = (
            QualityStatus.PASS
            if (self.calibrated_thresholds_approved and collapse_guard_fn is not None)
            else QualityStatus.UNKNOWN
        )
        return QualityAssessment(
            policy_revision=self.policy_revision,
            structurally_valid=True,
            quality_status=q_status,
            sample_count=raw_res.sample_count,
            actual_duration_ms=actual_dur_ms,
            peak_abs=raw_res.peak_abs,
            rms=raw_res.rms,
            rms_dbfs=rms_dbfs,
            dc_offset=dc_offset,
            near_zero_fraction=near_zero_fraction,
            longest_silence_samples=longest_silence,
            voiced_score=raw_res.voiced_score,
            duration_mismatch_ratio=raw_res.duration_mismatch_ratio,
            reason_codes=tuple(reasons),
            retryable=False,
            error=None,
        )

    @staticmethod
    def _longest_true_run(mask: Any) -> int:
        import numpy as np

        if mask.size == 0 or not np.any(mask):
            return 0
        padded = np.concatenate(([False], mask, [False]))
        diffs = np.diff(padded.astype(np.int8))
        starts = np.flatnonzero(diffs == 1)
        ends = np.flatnonzero(diffs == -1)
        return int(np.max(ends - starts)) if starts.size > 0 else 0


__all__ = [
    "QUALITY_POLICY_REVISION",
    "QualityAssessment",
    "QualityGuard",
]
