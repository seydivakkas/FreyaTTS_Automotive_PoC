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

import hashlib
import json
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from backend.core.contracts.common import (
    ContractVersion,
    ErrorCategory,
    ErrorInfo,
    GenerationRef,
    Retryability,
)
from backend.core.contracts.synthesis import ChunkPlan, PlanValidationStatus, SynthesisPlan
from backend.core.runtime.session_context import SessionContext, SessionLifecycleState
from backend.neural_synthesis.config_adapter import (
    ALLOWED_STRICT_CONTROLS,
    PinnedSynthesisSnapshot,
    SnapshotPinningError,
    pin_synthesis_snapshot,
)

MAX_PLAN_CHUNKS = 64
MAX_CHARS_PER_CHUNK = 512
MAX_TOTAL_CHARS = 4000
NO_SPEECH_ACTS = frozenset({"NO_SPEECH", "SILENCE", "NONE"})


@dataclass(frozen=True, slots=True)
class PlanAdmission:
    """Immutable strict admission outcome for a prepared M01 SynthesisPlan."""

    accepted: bool
    plan_id: str | None
    plan_revision: int | None
    generation_ref: GenerationRef | None
    response_id: str | None
    is_no_speech: bool
    reason_code: str
    pinned_snapshot: PinnedSynthesisSnapshot | None = None
    error: ErrorInfo | None = None
    chunk_fingerprints: tuple[str, ...] = ()


def _chunk_payload_digest(plan: SynthesisPlan, chunk: ChunkPlan) -> str:
    payload = {
        "plan_id": plan.plan_id,
        "plan_revision": plan.plan_revision,
        "response_id": plan.response_id,
        "voice_profile": plan.voice_profile,
        "seed": plan.seed,
        "model_revision": plan.model_revision,
        "lexicon_revision": plan.lexicon_revision,
        "capability_revision": plan.capability_revision,
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "model_text": chunk.model_text,
        "requested_speed": chunk.requested_speed,
        "post_pause_ms": chunk.post_pause_ms,
        "requested_controls": list(chunk.requested_controls),
        "protected_entity_refs": list(chunk.protected_entity_refs),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class ScopedPlanClaimRegistry:
    """Bounded deduplication & conflict detector keyed by full scoped chunk identity."""

    def __init__(self, *, max_entries: int = 2048) -> None:
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("max_entries must be positive int")
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._claims: OrderedDict[tuple[str, int, int, str, int, str, int], str] = OrderedDict()

    @staticmethod
    def _key(plan: SynthesisPlan, chunk: ChunkPlan) -> tuple[str, int, int, str, int, str, int]:
        g = plan.generation_ref
        return (
            g.session_id,
            g.turn_id,
            g.generation_id,
            plan.plan_id,
            plan.plan_revision,
            chunk.chunk_id,
            chunk.chunk_index,
        )

    def claim(self, plan: SynthesisPlan, chunk: ChunkPlan) -> tuple[str, str]:
        """
        Atomically claim a scoped chunk identity.

        Returns (status, digest) where status is one of:
          - 'CLAIMED': newly claimed
          - 'DUPLICATE': identical payload already claimed under this scoped identity
          - 'CONFLICT': different payload attempted under the same scoped identity
        """
        key = self._key(plan, chunk)
        digest = _chunk_payload_digest(plan, chunk)
        with self._lock:
            existing = self._claims.get(key)
            if existing is not None:
                if existing == digest:
                    return "DUPLICATE", digest
                return "CONFLICT", digest
            if len(self._claims) >= self._max_entries:
                self._claims.popitem(last=False)
            self._claims[key] = digest
            return "CLAIMED", digest

    def purge_generation(self, generation_ref: GenerationRef) -> int:
        with self._lock:
            to_drop = [
                k
                for k in self._claims
                if k[0] == generation_ref.session_id
                and k[1] == generation_ref.turn_id
                and k[2] == generation_ref.generation_id
            ]
            for k in to_drop:
                self._claims.pop(k, None)
            return len(to_drop)

    def purge_session(self, session_id: str) -> int:
        with self._lock:
            to_drop = [k for k in self._claims if k[0] == session_id]
            for k in to_drop:
                self._claims.pop(k, None)
            return len(to_drop)

    @property
    def active_claims(self) -> int:
        with self._lock:
            return len(self._claims)


def _reject(
    plan: Any,
    code: str,
    safe_message: str,
    *,
    category: ErrorCategory = ErrorCategory.VALIDATION,
    field_name: str | None = None,
) -> PlanAdmission:
    return PlanAdmission(
        accepted=False,
        plan_id=getattr(plan, "plan_id", None) if isinstance(getattr(plan, "plan_id", None), str) else None,
        plan_revision=getattr(plan, "plan_revision", None) if type(getattr(plan, "plan_revision", None)) is int else None,
        generation_ref=getattr(plan, "generation_ref", None) if isinstance(getattr(plan, "generation_ref", None), GenerationRef) else None,
        response_id=getattr(plan, "response_id", None) if isinstance(getattr(plan, "response_id", None), str) else None,
        is_no_speech=False,
        reason_code=code,
        error=ErrorInfo(
            code=code,
            category=category,
            retryable=Retryability.NO,
            safe_message=safe_message,
            field_name=field_name,
        ),
    )


def validate_and_admit_plan(
    plan: Any,
    *,
    session_ctx: SessionContext | None = None,
    expected_generation_ref: GenerationRef | None = None,
    untrusted_already_normalized_flag: bool | None = None,
    max_chunks: int = MAX_PLAN_CHUNKS,
    max_chars_per_chunk: int = MAX_CHARS_PER_CHUNK,
    max_total_chars: int = MAX_TOTAL_CHARS,
    allowed_controls: frozenset[str] = ALLOWED_STRICT_CONTROLS,
    pin_kwargs: dict[str, Any] | None = None,
) -> PlanAdmission:
    """Validate an immutable M01 SynthesisPlan for strict F5-A execution."""
    if untrusted_already_normalized_flag is not None:
        return _reject(
            plan,
            "UNTRUSTED_BYPASS_FLAG",
            "Public already_normalized flag is not accepted on strict synthesis path",
            field_name="already_normalized",
        )

    if not isinstance(plan, SynthesisPlan):
        return _reject(
            plan,
            "INVALID_PLAN_SCHEMA",
            "Strict synthesis requires an immutable M01 SynthesisPlan instance",
        )

    try:
        ContractVersion.parse(plan.schema_version)
    except Exception:
        return _reject(
            plan,
            "INVALID_SCHEMA_VERSION",
            "SynthesisPlan schema_version is incompatible",
            field_name="schema_version",
        )

    if plan.validation_status != PlanValidationStatus.VALID:
        return _reject(
            plan,
            "PLAN_NOT_VALIDATED",
            f"Strict synthesis requires validation_status=VALID (got {plan.validation_status.value})",
            field_name="validation_status",
        )

    if type(plan.normalization_passes) is not int or plan.normalization_passes != 1:
        return _reject(
            plan,
            "INVALID_NORMALIZATION_PASSES",
            "Strict synthesis requires normalization_passes == 1 from F4",
            field_name="normalization_passes",
        )

    if expected_generation_ref is not None and plan.generation_ref != expected_generation_ref:
        return _reject(
            plan,
            "STALE_GENERATION_SCOPE",
            "SynthesisPlan generation_ref does not match active generation",
            category=ErrorCategory.STALE_SCOPE,
            field_name="generation_ref",
        )

    if session_ctx is not None:
        if session_ctx.lifecycle_state != SessionLifecycleState.ACTIVE:
            return _reject(
                plan,
                "SESSION_NOT_ACTIVE",
                "Target M02 SessionContext is not active",
                category=ErrorCategory.STALE_SCOPE,
            )
        if session_ctx.root_scope.is_cancel_requested:
            return _reject(
                plan,
                "SESSION_CANCELLED",
                "Target session cancellation scope is cancelled",
                category=ErrorCategory.STALE_SCOPE,
            )
        if plan.generation_ref.session_id != session_ctx.identity.session_id:
            return _reject(
                plan,
                "SESSION_MISMATCH",
                "SynthesisPlan session_id does not match SessionContext",
                category=ErrorCategory.STALE_SCOPE,
                field_name="generation_ref",
            )
        active_turn = session_ctx.tg.active_turn
        active_gen = session_ctx.tg.active_generation
        if active_turn is None or active_gen is None or plan.generation_ref != active_gen:
            return _reject(
                plan,
                "STALE_GENERATION_SCOPE",
                "SynthesisPlan generation_ref does not match SessionContext active generation",
                category=ErrorCategory.STALE_SCOPE,
                field_name="generation_ref",
            )
        gen_scope = session_ctx.tg.generation_scope
        if gen_scope is not None and gen_scope.is_cancel_requested:
            return _reject(
                plan,
                "GENERATION_CANCELLED",
                "Active generation scope is cancelled",
                category=ErrorCategory.STALE_SCOPE,
            )

    try:
        pinned = pin_synthesis_snapshot(plan, **(pin_kwargs or {}))
    except SnapshotPinningError as exc:
        return _reject(
            plan,
            exc.error_info.code,
            exc.error_info.safe_message,
            category=exc.error_info.category,
            field_name=exc.error_info.field_name,
        )

    is_explicit_no_speech = plan.speech_act.upper() in NO_SPEECH_ACTS and len(plan.chunks) == 0
    if is_explicit_no_speech:
        return PlanAdmission(
            accepted=True,
            plan_id=plan.plan_id,
            plan_revision=plan.plan_revision,
            generation_ref=plan.generation_ref,
            response_id=plan.response_id,
            is_no_speech=True,
            reason_code="EXPLICIT_NO_SPEECH",
            pinned_snapshot=pinned,
        )

    if len(plan.chunks) == 0:
        return _reject(
            plan,
            "EMPTY_SPEECH_PLAN",
            "Speech plan has zero chunks without explicit NO_SPEECH speech_act",
            field_name="chunks",
        )

    if len(plan.chunks) > max_chunks:
        return _reject(
            plan,
            "PLAN_CHUNK_LIMIT_EXCEEDED",
            f"Plan chunk count {len(plan.chunks)} exceeds bounded maximum {max_chunks}",
            field_name="chunks",
        )

    seen_ids: set[str] = set()
    total_chars = 0
    fingerprints: list[str] = []
    for expected_idx, chunk in enumerate(plan.chunks):
        if not isinstance(chunk, ChunkPlan):
            return _reject(plan, "INVALID_CHUNK_TYPE", "Plan contains non-ChunkPlan entry", field_name="chunks")
        if chunk.chunk_index != expected_idx:
            return _reject(
                plan,
                "NONCONTIGUOUS_CHUNK_INDEX",
                "Chunk indices must be contiguous starting at 0",
                field_name="chunks",
            )
        if chunk.chunk_id in seen_ids:
            return _reject(
                plan,
                "DUPLICATE_CHUNK_ID",
                "Duplicate chunk_id in SynthesisPlan",
                field_name="chunks",
            )
        seen_ids.add(chunk.chunk_id)

        if not isinstance(chunk.model_text, str) or not chunk.model_text.strip():
            return _reject(
                plan,
                "BLANK_MODEL_TEXT",
                "Speech chunk model_text must be non-blank",
                field_name="model_text",
            )
        if len(chunk.model_text) > max_chars_per_chunk:
            return _reject(
                plan,
                "CHUNK_TEXT_TOO_LONG",
                f"Chunk text length {len(chunk.model_text)} exceeds bounded limit {max_chars_per_chunk}",
                field_name="model_text",
            )
        total_chars += len(chunk.model_text)
        if total_chars > max_total_chars:
            return _reject(
                plan,
                "PLAN_TEXT_LIMIT_EXCEEDED",
                f"Total plan model_text length exceeds bounded limit {max_total_chars}",
                field_name="chunks",
            )
        if chunk.requested_speed is not None and not math.isfinite(chunk.requested_speed):
            return _reject(
                plan,
                "NONFINITE_REQUESTED_SPEED",
                "requested_speed must be finite",
                field_name="requested_speed",
            )
        for ctrl in chunk.requested_controls:
            if ctrl not in allowed_controls:
                return _reject(
                    plan,
                    "UNSUPPORTED_CONTROL",
                    f"Unsupported chunk control requested: {ctrl!r}",
                    field_name="requested_controls",
                )
        fingerprints.append(_chunk_payload_digest(plan, chunk))

    return PlanAdmission(
        accepted=True,
        plan_id=plan.plan_id,
        plan_revision=plan.plan_revision,
        generation_ref=plan.generation_ref,
        response_id=plan.response_id,
        is_no_speech=False,
        reason_code="ADMITTED",
        pinned_snapshot=pinned,
        chunk_fingerprints=tuple(fingerprints),
    )


__all__ = [
    "MAX_CHARS_PER_CHUNK",
    "MAX_PLAN_CHUNKS",
    "MAX_TOTAL_CHARS",
    "NO_SPEECH_ACTS",
    "PlanAdmission",
    "ScopedPlanClaimRegistry",
    "validate_and_admit_plan",
]
