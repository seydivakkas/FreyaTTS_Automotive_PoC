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
from typing import Any

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.neural_synthesis.config_adapter import PinnedSynthesisSnapshot
from backend.neural_synthesis.encoder_adapter import EncodedCondition

BASELINE_T_FLOOR = 8
BASELINE_T_CAP = 300
BASELINE_SHORT_CLAUSE_MAX_CHARS = 15
BASELINE_SHORT_CLAUSE_FRAMES_PER_CHAR = 1.8


class DurationEstimationError(ValueError):
    """Typed error raised when duration prediction or units are invalid or unknown."""

    def __init__(self, error_info: ErrorInfo) -> None:
        super().__init__(error_info.safe_message)
        self.error_info = error_info


@dataclass(frozen=True, slots=True)
class DurationEstimate:
    """Explicit unit-annotated duration prediction preserving raw and effective values."""

    token_count: int
    char_count: int
    raw_predicted_frames: float
    raw_predicted_sec: float
    effective_frames: int
    effective_duration_sec: float
    expected_samples: int
    clamped: bool
    clamp_reason: str | None
    units: str
    latent_rate_hz: int | None
    samples_per_frame: int | None
    sample_rate_hz: int
    profile_revision: str


def compute_clause_frame_count(chars: int, predicted_frames: float) -> tuple[int, bool, str | None]:
    """
    Preserve exact FreyaTTS / BatchedODEEngine clause frame count and clamp semantics.

    Returns (effective_frames, clamped, clamp_reason).
    """
    rounded = int(round(predicted_frames))
    clamped = False
    reasons: list[str] = []

    if rounded > BASELINE_T_CAP:
        capped = BASELINE_T_CAP
        clamped = True
        reasons.append("max_cap_300")
    else:
        capped = rounded

    floor_val = max(BASELINE_T_FLOOR, chars + 4)
    frames = max(floor_val, capped)
    if frames != capped:
        clamped = True
        reasons.append("floor_chars_plus_4" if chars + 4 >= BASELINE_T_FLOOR else "floor_8")

    if chars <= BASELINE_SHORT_CLAUSE_MAX_CHARS:
        short_cap = math.ceil(chars * BASELINE_SHORT_CLAUSE_FRAMES_PER_CHAR) + 2
        bounded = max(BASELINE_T_FLOOR, min(frames, short_cap))
        if bounded != frames:
            clamped = True
            reasons.append("short_clause_cap")
        frames = bounded

    return frames, clamped, ",".join(reasons) if reasons else None


class DurationEstimator:
    """Adapter around existing FreyaDiT duration head with explicit units and provenance."""

    def estimate(
        self,
        encoded: EncodedCondition,
        *,
        tts_model: Any,
        snapshot: PinnedSynthesisSnapshot,
        override_units: str = "frames@25Hz",
    ) -> DurationEstimate:
        if override_units not in {"frames@25Hz", "seconds"}:
            raise DurationEstimationError(
                ErrorInfo(
                    code="UNSUPPORTED_DURATION_UNITS",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Unsupported duration units: {override_units!r}",
                    field_name="units",
                )
            )

        if snapshot.latent_rate_hz is None or snapshot.samples_per_frame is None:
            raise DurationEstimationError(
                ErrorInfo(
                    code="UNKNOWN_LATENT_RATE",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Latent frame rate or decoder stride is unknown; strict estimation on HOLD",
                    field_name="latent_rate_hz",
                )
            )

        latent_rate = snapshot.latent_rate_hz
        samples_per_frame = snapshot.samples_per_frame
        sample_rate_hz = snapshot.sample_rate_hz
        if samples_per_frame * latent_rate != sample_rate_hz:
            raise DurationEstimationError(
                ErrorInfo(
                    code="INCONSISTENT_LATENT_STRIDE",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Decoder stride * latent_rate_hz does not equal output sample_rate_hz",
                    field_name="samples_per_frame",
                )
            )

        raw_pred = self._query_model_duration(tts_model, encoded)
        if isinstance(raw_pred, bool) or not isinstance(raw_pred, (int, float)):
            raise DurationEstimationError(
                ErrorInfo(
                    code="INVALID_DURATION_TYPE",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message="Duration predictor returned non-numeric value",
                )
            )
        raw_val = float(raw_pred)
        if not math.isfinite(raw_val):
            raise DurationEstimationError(
                ErrorInfo(
                    code="NONFINITE_DURATION",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message="Duration predictor returned NaN or Inf",
                )
            )

        if override_units == "seconds":
            raw_frames = raw_val * float(latent_rate)
            raw_sec = raw_val
        else:
            raw_frames = raw_val
            raw_sec = raw_val / float(latent_rate)

        if raw_frames <= 0.0 or raw_sec <= 0.0:
            raise DurationEstimationError(
                ErrorInfo(
                    code="NONPOSITIVE_DURATION",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Predicted speech duration must be strictly positive",
                )
            )

        effective_frames, clamped, clamp_reason = compute_clause_frame_count(
            encoded.char_count,
            raw_frames,
        )
        effective_sec = effective_frames / float(latent_rate)
        expected_samples = effective_frames * samples_per_frame

        return DurationEstimate(
            token_count=encoded.token_count,
            char_count=encoded.char_count,
            raw_predicted_frames=raw_frames,
            raw_predicted_sec=raw_sec,
            effective_frames=effective_frames,
            effective_duration_sec=effective_sec,
            expected_samples=expected_samples,
            clamped=clamped,
            clamp_reason=clamp_reason,
            units=override_units,
            latent_rate_hz=latent_rate,
            samples_per_frame=samples_per_frame,
            sample_rate_hz=sample_rate_hz,
            profile_revision=snapshot.config_revision,
        )

    @staticmethod
    def _query_model_duration(tts_model: Any, encoded: EncodedCondition) -> float:
        if hasattr(tts_model, "predict_duration_frames"):
            return tts_model.predict_duration_frames(encoded)
        if hasattr(tts_model, "dur"):
            import torch

            ctx = encoded.context
            cmask = encoded.char_mask
            with torch.inference_mode():
                if cmask is not None:
                    pooled = (ctx * cmask[..., None].float()).sum(1) / (cmask.sum(1, keepdim=True) + 1e-6)
                else:
                    pooled = ctx.mean(1)
                log_frames = float(tts_model.dur(pooled).squeeze(-1).item())
                return math.exp(log_frames)
        raise DurationEstimationError(
            ErrorInfo(
                code="DURATION_HEAD_UNAVAILABLE",
                category=ErrorCategory.PROVIDER,
                retryable=Retryability.NO,
                safe_message="TTS model handle provides neither predict_duration_frames nor dur head",
            )
        )


__all__ = [
    "BASELINE_SHORT_CLAUSE_FRAMES_PER_CHAR",
    "BASELINE_SHORT_CLAUSE_MAX_CHARS",
    "BASELINE_T_CAP",
    "BASELINE_T_FLOOR",
    "DurationEstimate",
    "DurationEstimationError",
    "DurationEstimator",
    "compute_clause_frame_count",
]
