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

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.neural_synthesis.config_adapter import PinnedSynthesisSnapshot
from backend.neural_synthesis.duration_estimator import DurationEstimate
from backend.runtime_resources.memory_budget import MemoryBudget

DEFAULT_MAX_FRAMES = 300
DEFAULT_MAX_RAW_PREDICTED_FRAMES = 2400.0  # Reject runaway > 96s predictions before clamping/allocation
DEFAULT_MAX_SHAPE_PRODUCT = 1 * 300 * 64
DEFAULT_MAX_WAVEFORM_BYTES = 48000 * 60 * 4  # M01 AudioChunk ceiling (60s float32 mono)
DEFAULT_FIXED_RUNTIME_OVERHEAD_BYTES = 8 * 1024 * 1024  # 8 MiB conservative activation estimate


@dataclass(frozen=True, slots=True)
class DurationDecision:
    """Pre-allocation duration, shape product, and M06 budget guard outcome."""

    allowed: bool
    reason_code: str
    estimate: DurationEstimate | None
    estimated_latent_bytes: int
    estimated_waveform_bytes: int
    estimated_vram_bytes: int
    is_measured_vram: bool = False
    error: ErrorInfo | None = None


class DurationGuard:
    """
    Pre-allocation duration & tensor budget guard.

    Runs strictly BEFORE latent noise creation or GPU job submission.
    """

    def __init__(
        self,
        *,
        max_frames: int = DEFAULT_MAX_FRAMES,
        max_raw_predicted_frames: float = DEFAULT_MAX_RAW_PREDICTED_FRAMES,
        max_shape_product: int = DEFAULT_MAX_SHAPE_PRODUCT,
        max_waveform_bytes: int = DEFAULT_MAX_WAVEFORM_BYTES,
        activation_overhead_bytes: int = DEFAULT_FIXED_RUNTIME_OVERHEAD_BYTES,
    ) -> None:
        self.max_frames = max_frames
        self.max_raw_predicted_frames = max_raw_predicted_frames
        self.max_shape_product = max_shape_product
        self.max_waveform_bytes = max_waveform_bytes
        self.activation_overhead_bytes = activation_overhead_bytes

    def evaluate(
        self,
        estimate: DurationEstimate,
        snapshot: PinnedSynthesisSnapshot,
        *,
        batch_size: int = 1,
        memory_budget: MemoryBudget | None = None,
    ) -> DurationDecision:
        if type(batch_size) is not int or batch_size != 1:
            return self._deny(
                estimate,
                "UNSUPPORTED_STRICT_BATCH_SIZE",
                "Strict F5-A pre-allocation guard allows batch_size == 1 only",
            )

        if estimate.token_count <= 0 or estimate.char_count <= 0:
            return self._deny(
                estimate,
                "EMPTY_TOKENS",
                "Speech chunk must have positive token and character counts",
            )

        if (
            not math.isfinite(estimate.raw_predicted_frames)
            or not math.isfinite(estimate.raw_predicted_sec)
            or not math.isfinite(estimate.effective_duration_sec)
        ):
            return self._deny(
                estimate,
                "NONFINITE_DURATION",
                "Duration estimate contains non-finite values",
            )

        if estimate.raw_predicted_frames <= 0.0 or estimate.raw_predicted_sec <= 0.0:
            return self._deny(
                estimate,
                "NONPOSITIVE_DURATION",
                "Predicted duration must be strictly positive",
            )

        if estimate.raw_predicted_frames > self.max_raw_predicted_frames:
            return self._deny(
                estimate,
                "EXTREME_DURATION_PREDICTION",
                f"Raw predicted frames {estimate.raw_predicted_frames:.1f} exceeds pre-allocation limit {self.max_raw_predicted_frames:.1f}",
            )

        if type(estimate.effective_frames) is not int or estimate.effective_frames <= 0:
            return self._deny(
                estimate,
                "INVALID_FRAME_COUNT",
                "Effective latent frame count must be a positive integer",
            )

        if estimate.effective_frames > self.max_frames:
            return self._deny(
                estimate,
                "FRAME_LIMIT_EXCEEDED",
                f"Effective frames {estimate.effective_frames} exceeds max_frames {self.max_frames}",
            )

        shape_product = batch_size * estimate.effective_frames * snapshot.latent_dim
        if shape_product <= 0 or shape_product > self.max_shape_product:
            return self._deny(
                estimate,
                "SHAPE_PRODUCT_EXCEEDED",
                f"Latent shape product {shape_product} exceeds bounded ceiling {self.max_shape_product}",
            )

        latent_bytes = shape_product * 4  # float32
        waveform_bytes = estimate.expected_samples * 4  # 48kHz mono float32
        if waveform_bytes <= 0 or waveform_bytes > self.max_waveform_bytes:
            return self._deny(
                estimate,
                "WAVEFORM_BYTE_BUDGET_EXCEEDED",
                f"Expected waveform bytes {waveform_bytes} exceeds ceiling {self.max_waveform_bytes}",
            )

        # Conservative estimate for M06 admission (explicitly NOT measured VRAM)
        estimated_vram = self.activation_overhead_bytes + (latent_bytes * 16) + (waveform_bytes * 2)

        if memory_budget is not None:
            check = memory_budget.check_admission(estimated_vram)
            if not check.admitted:
                return DurationDecision(
                    allowed=False,
                    reason_code=f"BUDGET_{check.reason.upper()}",
                    estimate=estimate,
                    estimated_latent_bytes=latent_bytes,
                    estimated_waveform_bytes=waveform_bytes,
                    estimated_vram_bytes=estimated_vram,
                    is_measured_vram=False,
                    error=ErrorInfo(
                        code="INSUFFICIENT_GPU_BUDGET",
                        category=ErrorCategory.CAPACITY,
                        retryable=Retryability.YES,
                        safe_message=f"Estimated VRAM budget rejected by M06 ({check.reason})",
                    ),
                )

        return DurationDecision(
            allowed=True,
            reason_code="OK_CLAMPED" if estimate.clamped else "OK",
            estimate=estimate,
            estimated_latent_bytes=latent_bytes,
            estimated_waveform_bytes=waveform_bytes,
            estimated_vram_bytes=estimated_vram,
            is_measured_vram=False,
        )

    @staticmethod
    def _deny(estimate: DurationEstimate, code: str, message: str) -> DurationDecision:
        return DurationDecision(
            allowed=False,
            reason_code=code,
            estimate=estimate,
            estimated_latent_bytes=0,
            estimated_waveform_bytes=0,
            estimated_vram_bytes=0,
            is_measured_vram=False,
            error=ErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message=message,
            ),
        )


__all__ = [
    "DEFAULT_FIXED_RUNTIME_OVERHEAD_BYTES",
    "DEFAULT_MAX_FRAMES",
    "DEFAULT_MAX_RAW_PREDICTED_FRAMES",
    "DEFAULT_MAX_SHAPE_PRODUCT",
    "DEFAULT_MAX_WAVEFORM_BYTES",
    "DurationDecision",
    "DurationGuard",
]
