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
from typing import Mapping

import numpy as np

from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import ErrorCategory, ErrorInfo, GenerationRef, Retryability
from backend.core.contracts.synthesis import (
    AudioChunk,
    PlanValidationStatus,
    QualityStatus,
    SynthesisPlan,
    validate_plan_chunk_consistency,
)


class InputValidationError(ValueError):
    """Typed rejection for invalid, oversized, non-finite, stale, or guard-failed input."""

    def __init__(self, code: str, message: str, *, category: ErrorCategory = ErrorCategory.VALIDATION) -> None:
        super().__init__(message)
        self.error_info = ErrorInfo(
            code=code,
            category=category,
            retryable=Retryability.NO,
            safe_message=message,
        )


@dataclass(frozen=True, slots=True)
class ValidatedAudioChunk:
    """Validated immutable 48 kHz mono float32 view over an accepted F5 AudioChunk."""

    chunk: AudioChunk
    samples: np.ndarray  # Read-only float32 1D array
    raw_peak_abs: float
    raw_overrange_samples: int
    acoustic_quality_verified: bool


def validate_raw_audio_chunk(
    chunk: object,
    *,
    plan: SynthesisPlan | None = None,
    expected_generation_ref: GenerationRef | None = None,
    expected_plan_revision: int | None = None,
    expected_chunk_index: int | None = None,
    seen_chunks: Mapping[int, str] | None = None,
    max_chunk_samples: int = 48000 * 60,
    strict_quality_gate: bool = True,
) -> ValidatedAudioChunk:
    """
    Validate an incoming F5 AudioChunk without mutating source bytes or allocating oversized buffers.

    Structural rules:
    - Exact 48000 Hz mono FLOAT32_LE
    - Strict int sample_count (bool rejected), positive, <= max_chunk_samples
    - Exact 4 * sample_count immutable bytes
    - Finite numeric samples only (no NaN/Inf)
    - QualityStatus.FAIL blocks strict rendering; UNKNOWN/PENDING is structurally permitted
      without promoting acoustic_quality_verified=True
    - Duplicate or conflicting chunk_id/index or order gap rejected explicitly
    """
    if not isinstance(chunk, AudioChunk):
        raise InputValidationError("INVALID_CHUNK_TYPE", "Expected M01 AudioChunk")

    if type(chunk.sample_count) is not int or chunk.sample_count <= 0:
        raise InputValidationError("INVALID_SAMPLE_COUNT", "sample_count must be positive strict int")
    if chunk.sample_count > max_chunk_samples:
        raise InputValidationError(
            "CHUNK_OVERSIZE",
            f"sample_count {chunk.sample_count} exceeds max {max_chunk_samples}",
            category=ErrorCategory.CAPACITY,
        )

    if not isinstance(chunk.format, AudioFormat):
        raise InputValidationError("INVALID_FORMAT", "chunk.format must be AudioFormat")
    if (
        chunk.format.sample_rate_hz != 48000
        or chunk.format.channels != 1
        or chunk.format.encoding != AudioEncoding.FLOAT32_LE
    ):
        raise InputValidationError("UNSUPPORTED_INPUT_FORMAT", "AudioChunk must be 48000 Hz mono FLOAT32_LE")

    if not isinstance(chunk.payload, bytes):
        raise InputValidationError("MUTABLE_OR_INVALID_PAYLOAD", "AudioChunk payload must be immutable bytes")
    expected_bytes = chunk.sample_count * 4
    if len(chunk.payload) != expected_bytes:
        raise InputValidationError(
            "PAYLOAD_LENGTH_MISMATCH",
            f"payload bytes {len(chunk.payload)} != expected {expected_bytes}",
        )

    if expected_generation_ref is not None and chunk.generation_ref != expected_generation_ref:
        raise InputValidationError(
            "STALE_GENERATION",
            "AudioChunk generation_ref does not match active generation",
            category=ErrorCategory.STALE_SCOPE,
        )

    if expected_plan_revision is not None and chunk.plan_revision != expected_plan_revision:
        raise InputValidationError(
            "STALE_PLAN_REVISION",
            "AudioChunk plan_revision mismatch",
            category=ErrorCategory.STALE_SCOPE,
        )

    if plan is not None:
        if plan.validation_status == PlanValidationStatus.INVALID:
            raise InputValidationError("INVALID_SYNTHESIS_PLAN", "SynthesisPlan validation_status is INVALID")
        try:
            validate_plan_chunk_consistency(plan, chunk)
        except ValueError as exc:
            raise InputValidationError("PLAN_CHUNK_MISMATCH", str(exc), category=ErrorCategory.STALE_SCOPE) from exc

    if seen_chunks is not None and chunk.chunk_index in seen_chunks:
        prev_id = seen_chunks[chunk.chunk_index]
        code = "DUPLICATE_CHUNK" if prev_id == chunk.chunk_id else "CONFLICTING_CHUNK"
        raise InputValidationError(
            code,
            f"Chunk index {chunk.chunk_index} already seen (id={prev_id!r}, new={chunk.chunk_id!r})",
            category=ErrorCategory.STALE_SCOPE,
        )

    if expected_chunk_index is not None and chunk.chunk_index != expected_chunk_index:
        raise InputValidationError(
            "OUT_OF_ORDER_CHUNK",
            f"Expected chunk_index {expected_chunk_index}, got {chunk.chunk_index}",
            category=ErrorCategory.STALE_SCOPE,
        )

    if strict_quality_gate and chunk.quality_status == QualityStatus.FAIL:
        raise InputValidationError(
            "QUALITY_GUARD_FAILED",
            "AudioChunk blocked by explicit F5 quality_status=FAIL",
        )

    arr_view = np.frombuffer(chunk.payload, dtype="<f4")
    if arr_view.ndim != 1 or arr_view.shape[0] != chunk.sample_count:
        raise InputValidationError("MALFORMED_WAVEFORM_SHAPE", "Decoded waveform must be 1D of length sample_count")
    if not bool(np.isfinite(arr_view).all()):
        raise InputValidationError("NON_FINITE_AUDIO", "AudioChunk payload contains NaN or Inf samples")

    # Ensure strictly read-only float32 view so caller/renderer cannot mutate F5 source bytes.
    ro_view = arr_view.astype(np.float32, copy=False)
    ro_view.flags.writeable = False

    abs_view = np.abs(ro_view)
    raw_peak = float(np.max(abs_view)) if ro_view.size else 0.0
    overrange_count = int(np.count_nonzero(abs_view > 1.0))

    return ValidatedAudioChunk(
        chunk=chunk,
        samples=ro_view,
        raw_peak_abs=raw_peak,
        raw_overrange_samples=overrange_count,
        acoustic_quality_verified=(chunk.quality_status == QualityStatus.PASS),
    )
