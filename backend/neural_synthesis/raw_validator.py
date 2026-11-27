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

from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.core.contracts.synthesis import QualityStatus
from backend.neural_synthesis.config_adapter import BASELINE_SAMPLE_RATE_HZ
from backend.neural_synthesis.duration_estimator import DurationEstimate

MIN_SPEECH_PEAK_ABS = 1e-5  # Existing FreyaTTS / BatchedODEEngine silent-output threshold
MAX_PHYSICAL_AMPLITUDE_BOUND = 100.0  # Reject extreme numerical blowouts without clamping valid raw waveforms
DEFAULT_DURATION_TOLERANCE_RATIO = 0.25


@dataclass(frozen=True, slots=True)
class RawValidationResult:
    """Structural raw-waveform integrity result (distinct from acoustic quality PASS)."""

    structurally_valid: bool
    collapse_guard_passed: bool | None
    collapse_guard_scope: str
    voiced_score: float | None
    peak_abs: float
    rms: float
    sample_count: int
    byte_length: int
    duration_mismatch_ratio: float | None
    quality_status: QualityStatus
    reason_codes: tuple[str, ...]
    error: ErrorInfo | None = None


class RawAudioValidator:
    """
    Structural validator for raw 48 kHz mono FLOAT32_LE decoder waveforms.

    - Performs ZERO DSP, clamping, fading, comfort-noise injection, or resampling.
    - Integrates existing silent/collapse guards.
    - Never labels structurally finite audio as QualityStatus.PASS without acoustic measurement.
    """

    def __init__(
        self,
        *,
        min_peak_abs: float = MIN_SPEECH_PEAK_ABS,
        max_amplitude_bound: float = MAX_PHYSICAL_AMPLITUDE_BOUND,
        duration_tolerance_ratio: float = DEFAULT_DURATION_TOLERANCE_RATIO,
        max_payload_bytes: int = 48000 * 60 * 4,
    ) -> None:
        self.min_peak_abs = min_peak_abs
        self.max_amplitude_bound = max_amplitude_bound
        self.duration_tolerance_ratio = duration_tolerance_ratio
        self.max_payload_bytes = max_payload_bytes

    def validate(
        self,
        *,
        payload: bytes,
        sample_count: int,
        audio_format: AudioFormat,
        estimate: DurationEstimate | None = None,
        collapse_guard_fn: Callable[[Any, int], bool | float] | None = None,
        collapse_guard_scope: str = "STRUCTURAL_PEAK_AND_FINITE",
    ) -> RawValidationResult:
        reasons: list[str] = []

        if (
            audio_format.sample_rate_hz != BASELINE_SAMPLE_RATE_HZ
            or audio_format.channels != 1
            or audio_format.encoding != AudioEncoding.FLOAT32_LE
        ):
            return self._fail(
                "INVALID_RAW_FORMAT",
                "Raw audio format must be 48000 Hz mono FLOAT32_LE",
                sample_count=sample_count,
                byte_length=len(payload) if isinstance(payload, bytes) else 0,
                collapse_guard_scope=collapse_guard_scope,
            )

        if type(sample_count) is not int or sample_count <= 0:
            return self._fail(
                "INVALID_SAMPLE_COUNT",
                "sample_count must be positive integer",
                sample_count=0,
                byte_length=len(payload) if isinstance(payload, bytes) else 0,
                collapse_guard_scope=collapse_guard_scope,
            )

        if not isinstance(payload, bytes):
            return self._fail(
                "PAYLOAD_NOT_IMMUTABLE_BYTES",
                "Raw audio payload must be immutable bytes",
                sample_count=sample_count,
                byte_length=0,
                collapse_guard_scope=collapse_guard_scope,
            )

        if len(payload) > self.max_payload_bytes or len(payload) != sample_count * 4:
            return self._fail(
                "PAYLOAD_BYTE_MISMATCH",
                f"Payload byte length {len(payload)} != 4 * {sample_count} or exceeds limit",
                sample_count=sample_count,
                byte_length=len(payload),
                collapse_guard_scope=collapse_guard_scope,
            )

        import numpy as np

        samples = np.frombuffer(payload, dtype="<f4")
        if not np.isfinite(samples).all():
            return self._fail(
                "NONFINITE_SAMPLES",
                "Raw FLOAT32_LE waveform contains NaN or Inf",
                sample_count=sample_count,
                byte_length=len(payload),
                collapse_guard_scope=collapse_guard_scope,
            )

        peak_abs = float(np.max(np.abs(samples)))
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))

        if peak_abs < self.min_peak_abs:
            return self._fail(
                "SILENT_MODEL_OUTPUT",
                f"Decoded waveform peak {peak_abs:.3e} below threshold {self.min_peak_abs:.3e}",
                sample_count=sample_count,
                byte_length=len(payload),
                peak_abs=peak_abs,
                rms=rms,
                collapse_guard_passed=False,
                collapse_guard_scope=collapse_guard_scope,
            )

        if peak_abs > self.max_amplitude_bound:
            return self._fail(
                "AMPLITUDE_OUT_OF_BOUNDS",
                f"Decoded waveform peak {peak_abs:.2f} exceeds bound {self.max_amplitude_bound:.2f}",
                sample_count=sample_count,
                byte_length=len(payload),
                peak_abs=peak_abs,
                rms=rms,
                collapse_guard_passed=False,
                collapse_guard_scope=collapse_guard_scope,
            )

        mismatch_ratio: float | None = None
        if estimate is not None and estimate.expected_samples > 0:
            mismatch_ratio = abs(sample_count - estimate.expected_samples) / float(estimate.expected_samples)
            if mismatch_ratio > self.duration_tolerance_ratio:
                return self._fail(
                    "ACTUAL_DURATION_MISMATCH",
                    f"Decoded sample count {sample_count} diverges from expected {estimate.expected_samples} ({mismatch_ratio:.2%})",
                    sample_count=sample_count,
                    byte_length=len(payload),
                    peak_abs=peak_abs,
                    rms=rms,
                    duration_mismatch_ratio=mismatch_ratio,
                    collapse_guard_passed=True,
                    collapse_guard_scope=collapse_guard_scope,
                )

        voiced_score: float | None = None
        collapse_passed: bool = True
        if collapse_guard_fn is not None:
            guard_out = collapse_guard_fn(samples, audio_format.sample_rate_hz)
            if isinstance(guard_out, bool):
                collapse_passed = guard_out
            elif isinstance(guard_out, (int, float)) and not isinstance(guard_out, bool):
                if not math.isfinite(float(guard_out)):
                    collapse_passed = False
                else:
                    voiced_score = float(guard_out)
                    collapse_passed = voiced_score >= 0.06
            else:
                collapse_passed = False

            if not collapse_passed:
                return self._fail(
                    "COLLAPSE_GUARD_REJECTED",
                    "Existing collapse guard rejected synthesized waveform",
                    sample_count=sample_count,
                    byte_length=len(payload),
                    peak_abs=peak_abs,
                    rms=rms,
                    voiced_score=voiced_score,
                    duration_mismatch_ratio=mismatch_ratio,
                    collapse_guard_passed=False,
                    collapse_guard_scope=collapse_guard_scope,
                )

        reasons.append("STRUCTURAL_OK")
        return RawValidationResult(
            structurally_valid=True,
            collapse_guard_passed=collapse_passed,
            collapse_guard_scope=collapse_guard_scope,
            voiced_score=voiced_score,
            peak_abs=peak_abs,
            rms=rms,
            sample_count=sample_count,
            byte_length=len(payload),
            duration_mismatch_ratio=mismatch_ratio,
            # Structural validity is NEVER acoustic quality PASS
            quality_status=QualityStatus.UNKNOWN,
            reason_codes=tuple(reasons),
            error=None,
        )

    @staticmethod
    def _fail(
        code: str,
        message: str,
        *,
        sample_count: int,
        byte_length: int,
        peak_abs: float = 0.0,
        rms: float = 0.0,
        voiced_score: float | None = None,
        duration_mismatch_ratio: float | None = None,
        collapse_guard_passed: bool | None = None,
        collapse_guard_scope: str = "STRUCTURAL_PEAK_AND_FINITE",
    ) -> RawValidationResult:
        return RawValidationResult(
            structurally_valid=False,
            collapse_guard_passed=collapse_guard_passed,
            collapse_guard_scope=collapse_guard_scope,
            voiced_score=voiced_score,
            peak_abs=peak_abs,
            rms=rms,
            sample_count=sample_count,
            byte_length=byte_length,
            duration_mismatch_ratio=duration_mismatch_ratio,
            quality_status=QualityStatus.FAIL,
            reason_codes=(code,),
            error=ErrorInfo(
                code=code,
                category=ErrorCategory.PROVIDER,
                retryable=Retryability.NO,
                safe_message=message,
            ),
        )


__all__ = [
    "DEFAULT_DURATION_TOLERANCE_RATIO",
    "MAX_PHYSICAL_AMPLITUDE_BOUND",
    "MIN_SPEECH_PEAK_ABS",
    "RawAudioValidator",
    "RawValidationResult",
]
