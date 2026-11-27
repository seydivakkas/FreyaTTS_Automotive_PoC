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
from typing import Any, Iterator

from backend.audio_rendering.input_validator import InputValidationError
from backend.core.contracts.common import ErrorCategory
from backend.core.contracts.synthesis import AudioChunk, ChunkPlan


class ControlStatus(StrEnum):
    APPLIED = "APPLIED"
    ALREADY_APPLIED_UPSTREAM = "ALREADY_APPLIED_UPSTREAM"
    IGNORED_NULL = "IGNORED_NULL"
    UNSUPPORTED = "UNSUPPORTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ControlApplicationRecord:
    """Explicit requested vs effective control record preventing double application."""

    control_name: str
    chunk_id: str | None
    requested_value: Any
    effective_value: Any
    authority: str
    status: ControlStatus
    reason: str
    inserted_output_samples: int = 0


def validate_post_pause_ms(
    post_pause_ms: object,
    *,
    max_pause_ms: int = 10_000,
) -> int:
    """Validate pause duration before allocating silence buffers."""
    if post_pause_ms is None:
        return 0
    if isinstance(post_pause_ms, bool) or not isinstance(post_pause_ms, (int, float)):
        raise InputValidationError("INVALID_PAUSE_TYPE", "post_pause_ms must be numeric or None")
    val = float(post_pause_ms)
    if not math.isfinite(val):
        raise InputValidationError("NON_FINITE_PAUSE", "post_pause_ms must be finite")
    if val < 0.0:
        raise InputValidationError("NEGATIVE_PAUSE", "post_pause_ms cannot be negative")
    if val > float(max_pause_ms):
        raise InputValidationError(
            "EXCESSIVE_PAUSE",
            f"post_pause_ms {val} exceeds bounded max {max_pause_ms}",
            category=ErrorCategory.CAPACITY,
        )
    return int(round(val))


def compute_pause_output_samples(post_pause_ms: int, output_rate_hz: int) -> int:
    """Compute exact output-domain integer sample count via round-half-to-even."""
    if post_pause_ms <= 0:
        return 0
    if output_rate_hz not in (8000, 16000):
        raise ValueError(f"Unsupported output_rate_hz: {output_rate_hz}")
    return int(round((post_pause_ms * output_rate_hz) / 1000.0))


def iter_bounded_pcm_silence(
    total_samples: int,
    *,
    slice_samples: int = 1600,
) -> Iterator[bytes]:
    """Stream zero PCM16 LE silence in bounded slices without huge single allocations."""
    if total_samples <= 0:
        return
    if slice_samples <= 0:
        raise ValueError("slice_samples must be positive")
    remaining = total_samples
    full_slice = b"\x00" * (slice_samples * 2)
    while remaining > 0:
        take = min(remaining, slice_samples)
        yield full_slice if take == slice_samples else (b"\x00" * (take * 2))
        remaining -= take


class ControlOwnershipResolver:
    """
    Resolves requested vs effective speed/pause/fade/emphasis controls per chunk
    and ensures no control is silently reapplied or faked.
    """

    def __init__(self, *, max_pause_ms: int = 10_000) -> None:
        self.max_pause_ms = max_pause_ms
        self._applied_pause_chunks: set[str] = set()
        self.records: list[ControlApplicationRecord] = []

    def reset(self) -> None:
        self._applied_pause_chunks.clear()
        self.records.clear()

    def evaluate_chunk_controls(
        self,
        chunk: AudioChunk,
        *,
        output_rate_hz: int,
        chunk_plan: ChunkPlan | None = None,
        fade_applied_upstream: bool = True,
    ) -> tuple[int, list[ControlApplicationRecord]]:
        """
        Evaluate speed, fade, emphasis, and post_pause_ms for an admitted AudioChunk.
        Returns `(pause_output_samples_to_render, records)`.
        """
        step_records: list[ControlApplicationRecord] = []

        # 1. Speed control ownership (F5 upstream vs F6-C deferred WSOLA)
        req_speed = chunk.requested_speed
        app_speed = chunk.applied_speed
        if req_speed is None and chunk_plan is not None:
            req_speed = chunk_plan.requested_speed

        if req_speed is not None:
            if isinstance(req_speed, bool) or not isinstance(req_speed, (int, float)) or not math.isfinite(float(req_speed)):
                raise InputValidationError("INVALID_SPEED", "requested_speed must be finite")
            if app_speed is not None and abs(float(app_speed) - float(req_speed)) <= 1e-6:
                step_records.append(
                    ControlApplicationRecord(
                        control_name="speed",
                        chunk_id=chunk.chunk_id,
                        requested_value=float(req_speed),
                        effective_value=float(app_speed),
                        authority="F5_UPSTREAM",
                        status=ControlStatus.ALREADY_APPLIED_UPSTREAM,
                        reason="speed_already_applied_in_f5",
                    )
                )
            elif abs(float(req_speed) - 1.0) <= 1e-6:
                step_records.append(
                    ControlApplicationRecord(
                        control_name="speed",
                        chunk_id=chunk.chunk_id,
                        requested_value=1.0,
                        effective_value=1.0,
                        authority="F6_A_NOOP",
                        status=ControlStatus.IGNORED_NULL,
                        reason="unity_speed",
                    )
                )
            else:
                step_records.append(
                    ControlApplicationRecord(
                        control_name="speed",
                        chunk_id=chunk.chunk_id,
                        requested_value=float(req_speed),
                        effective_value=1.0 if app_speed is None else float(app_speed),
                        authority="F6_C_DEFERRED",
                        status=ControlStatus.UNSUPPORTED,
                        reason="wsola_time_scale_deferred_to_f6_c",
                    )
                )

        # 2. Emphasis / custom requested_controls from ChunkPlan (F6-C deferred)
        if chunk_plan is not None:
            if chunk_plan.requested_emphasis:
                step_records.append(
                    ControlApplicationRecord(
                        control_name="emphasis",
                        chunk_id=chunk.chunk_id,
                        requested_value=chunk_plan.requested_emphasis,
                        effective_value=(),
                        authority="F6_C_DEFERRED",
                        status=ControlStatus.UNSUPPORTED,
                        reason="prosody_emphasis_deferred_to_f6_c",
                    )
                )
            if chunk_plan.requested_controls:
                step_records.append(
                    ControlApplicationRecord(
                        control_name="requested_controls",
                        chunk_id=chunk.chunk_id,
                        requested_value=chunk_plan.requested_controls,
                        effective_value=(),
                        authority="F6_C_DEFERRED",
                        status=ControlStatus.UNSUPPORTED,
                        reason="advanced_controls_not_enabled_in_f6_a",
                    )
                )

        # 3. Fade ownership (upstream F5 `apply_fade_and_comfort_noise`)
        step_records.append(
            ControlApplicationRecord(
                control_name="utterance_fade",
                chunk_id=chunk.chunk_id,
                requested_value=True,
                effective_value=fade_applied_upstream,
                authority="F5_UPSTREAM" if fade_applied_upstream else "NONE",
                status=ControlStatus.ALREADY_APPLIED_UPSTREAM if fade_applied_upstream else ControlStatus.IGNORED_NULL,
                reason="no_double_fade_in_f6_a",
            )
        )

        # 4. Post-pause ownership (render at most once per chunk_id)
        raw_pause = chunk.post_pause_ms
        if raw_pause is None and chunk_plan is not None:
            raw_pause = chunk_plan.post_pause_ms
        validated_pause_ms = validate_post_pause_ms(raw_pause, max_pause_ms=self.max_pause_ms)

        pause_samples = 0
        if raw_pause is None or validated_pause_ms == 0:
            step_records.append(
                ControlApplicationRecord(
                    control_name="post_pause_ms",
                    chunk_id=chunk.chunk_id,
                    requested_value=raw_pause,
                    effective_value=0,
                    authority="F6_A_CONTROL",
                    status=ControlStatus.IGNORED_NULL,
                    reason="null_or_zero_pause",
                    inserted_output_samples=0,
                )
            )
        elif chunk.chunk_id in self._applied_pause_chunks:
            step_records.append(
                ControlApplicationRecord(
                    control_name="post_pause_ms",
                    chunk_id=chunk.chunk_id,
                    requested_value=validated_pause_ms,
                    effective_value=0,
                    authority="F6_A_CONTROL",
                    status=ControlStatus.ALREADY_APPLIED_UPSTREAM,
                    reason="pause_already_rendered_for_chunk",
                    inserted_output_samples=0,
                )
            )
        else:
            pause_samples = compute_pause_output_samples(validated_pause_ms, output_rate_hz)
            self._applied_pause_chunks.add(chunk.chunk_id)
            step_records.append(
                ControlApplicationRecord(
                    control_name="post_pause_ms",
                    chunk_id=chunk.chunk_id,
                    requested_value=validated_pause_ms,
                    effective_value=validated_pause_ms,
                    authority="F6_A_CONTROL",
                    status=ControlStatus.APPLIED,
                    reason="rendered_output_silence_once",
                    inserted_output_samples=pause_samples,
                )
            )

        self.records.extend(step_records)
        return pause_samples, step_records
