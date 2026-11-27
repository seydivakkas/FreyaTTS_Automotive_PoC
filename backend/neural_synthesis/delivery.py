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

import asyncio
import threading
from dataclasses import dataclass
from typing import Callable

from backend.core.contracts.common import ErrorCategory, ErrorInfo, GenerationRef, Retryability
from backend.core.contracts.synthesis import AudioChunk
from backend.core.runtime.deadlines import DeadlineBudget
from backend.core.runtime.result_admission import AdmissionStatus, QueuedMediaItem
from backend.core.runtime.session_context import SessionContext, SessionLifecycleState
from backend.core.runtime.turn_generation import PauseState


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """Atomic M02 generation delivery fence outcome (distinct from remote playback)."""

    accepted: bool
    status: AdmissionStatus
    chunk: AudioChunk | None
    reason_code: str
    error: ErrorInfo | None = None


class GenerationDeliveryFence:
    """
    Atomic M02 generation/plan-revision/ordering fence for immutable AudioChunk delivery.

    Guarantees:
    - Enforces active session, active turn, active generation, and matching plan_revision.
    - Enforces contiguous per-generation chunk ordering (rejects duplicates and gaps).
    - Preserves M02 SOFT_PAUSED state distinctly from hard cancellation.
    - Never claims remote audible playback upon server admission.
    """

    def __init__(
        self,
        *,
        max_buffered_chunks: int = 64,
    ) -> None:
        if type(max_buffered_chunks) is not int or max_buffered_chunks < 1:
            raise ValueError("max_buffered_chunks must be positive int")
        self.max_buffered_chunks = max_buffered_chunks
        self._lock = threading.Lock()
        self._active_plan_revisions: dict[tuple[str, int, int], tuple[str, int]] = {}
        self._expected_chunk_index: dict[tuple[str, int, int, str, int], int] = {}
        self._delivered_keys: set[tuple[str, int, int, str, int, int]] = set()

    def register_active_plan(self, generation_ref: GenerationRef, plan_id: str, plan_revision: int) -> None:
        gen_key = (generation_ref.session_id, generation_ref.turn_id, generation_ref.generation_id)
        with self._lock:
            self._active_plan_revisions[gen_key] = (plan_id, plan_revision)

    def purge_generation(self, generation_ref: GenerationRef) -> None:
        gen_key = (generation_ref.session_id, generation_ref.turn_id, generation_ref.generation_id)
        with self._lock:
            self._active_plan_revisions.pop(gen_key, None)
            exp_drop = [
                k
                for k in self._expected_chunk_index
                if k[0] == generation_ref.session_id
                and k[1] == generation_ref.turn_id
                and k[2] == generation_ref.generation_id
            ]
            for k in exp_drop:
                self._expected_chunk_index.pop(k, None)
            del_drop = [
                k
                for k in self._delivered_keys
                if k[0] == generation_ref.session_id
                and k[1] == generation_ref.turn_id
                and k[2] == generation_ref.generation_id
            ]
            for k in del_drop:
                self._delivered_keys.discard(k)

    def purge_session(self, session_id: str) -> None:
        with self._lock:
            for k in [k for k in self._active_plan_revisions if k[0] == session_id]:
                self._active_plan_revisions.pop(k, None)
            for k in [k for k in self._expected_chunk_index if k[0] == session_id]:
                self._expected_chunk_index.pop(k, None)
            for k in [k for k in self._delivered_keys if k[0] == session_id]:
                self._delivered_keys.discard(k)

    def preflight_generation_active(
        self,
        generation_ref: GenerationRef,
        *,
        plan_id: str,
        plan_revision: int,
        session_ctx: SessionContext | None = None,
    ) -> AdmissionStatus:
        gen_key = (generation_ref.session_id, generation_ref.turn_id, generation_ref.generation_id)
        with self._lock:
            pinned = self._active_plan_revisions.get(gen_key)
            if pinned is not None and pinned != (plan_id, plan_revision):
                return AdmissionStatus.REVISION_MISMATCH

        if session_ctx is None:
            return AdmissionStatus.ACCEPTED

        if session_ctx.lifecycle_state in {SessionLifecycleState.CLOSING, SessionLifecycleState.CLOSED}:
            return AdmissionStatus.CLOSED
        if session_ctx.lifecycle_state != SessionLifecycleState.ACTIVE:
            return AdmissionStatus.INVALID
        if session_ctx.root_scope.is_cancel_requested:
            return AdmissionStatus.CANCELED
        if generation_ref.session_id != session_ctx.identity.session_id:
            return AdmissionStatus.STALE_SESSION
        active_turn = session_ctx.tg.active_turn
        if active_turn is None or generation_ref.turn_id != active_turn.turn_id:
            return AdmissionStatus.STALE_TURN
        active_gen = session_ctx.tg.active_generation
        if active_gen is None or generation_ref.generation_id != active_gen.generation_id:
            return AdmissionStatus.STALE_GENERATION
        gen_scope = session_ctx.tg.generation_scope
        if gen_scope is not None and gen_scope.is_cancel_requested:
            return AdmissionStatus.CANCELED
        return AdmissionStatus.ACCEPTED

    async def deliver(
        self,
        chunk: AudioChunk,
        *,
        session_ctx: SessionContext | None = None,
        chunk_sink: Callable[[AudioChunk], None] | None = None,
        expected_plan_revision: int | None = None,
        deadline: DeadlineBudget | None = None,
        admit_media_to_session_queue: bool = True,
    ) -> DeliveryOutcome:
        g = chunk.generation_ref
        rev_expected = chunk.plan_revision if expected_plan_revision is None else expected_plan_revision
        order_key = (g.session_id, g.turn_id, g.generation_id, chunk.plan_id, chunk.plan_revision)
        dedupe_key = (g.session_id, g.turn_id, g.generation_id, chunk.plan_id, chunk.plan_revision, chunk.chunk_index)
        gen_key = (g.session_id, g.turn_id, g.generation_id)

        # Atomic pre-check of ordering, duplicate, and active plan revision
        with self._lock:
            pinned = self._active_plan_revisions.get(gen_key)
            if pinned is not None and pinned != (chunk.plan_id, chunk.plan_revision):
                return self._reject(AdmissionStatus.REVISION_MISMATCH, "Chunk superseded by newer plan or revision")
            if chunk.plan_revision != rev_expected:
                return self._reject(AdmissionStatus.REVISION_MISMATCH, "Chunk plan_revision mismatch")
            if dedupe_key in self._delivered_keys:
                return self._reject(AdmissionStatus.DUPLICATE, "Duplicate AudioChunk delivery rejected")
            expected_idx = self._expected_chunk_index.get(order_key, 0)
            if chunk.chunk_index != expected_idx:
                return self._reject(
                    AdmissionStatus.OUT_OF_ORDER,
                    f"Out-of-order chunk {chunk.chunk_index} != expected {expected_idx}",
                )

        if session_ctx is not None:
            if admit_media_to_session_queue:
                item = QueuedMediaItem(
                    generation_ref=g,
                    sequence=chunk.chunk_index,
                    payload=chunk.payload,
                    plan_revision=chunk.plan_revision,
                    is_control=False,
                )
                status = await session_ctx.admit_media(
                    item,
                    expected_plan_revision=rev_expected,
                    deadline=deadline,
                )
            else:
                status = self.preflight_generation_active(
                    g,
                    plan_id=chunk.plan_id,
                    plan_revision=chunk.plan_revision,
                    session_ctx=session_ctx,
                )
            if status != AdmissionStatus.ACCEPTED:
                return self._reject(status, f"M02 session admission rejected chunk ({status.value})")

        # Re-verify atomically and commit ordering state + sink delivery
        with self._lock:
            pinned = self._active_plan_revisions.get(gen_key)
            if pinned is not None and pinned != (chunk.plan_id, chunk.plan_revision):
                return self._reject(AdmissionStatus.REVISION_MISMATCH, "Chunk superseded right before commit")
            if dedupe_key in self._delivered_keys:
                return self._reject(AdmissionStatus.DUPLICATE, "Duplicate AudioChunk delivery rejected")
            expected_idx = self._expected_chunk_index.get(order_key, 0)
            if chunk.chunk_index != expected_idx:
                return self._reject(AdmissionStatus.OUT_OF_ORDER, "Out-of-order chunk right before commit")

            if chunk_sink is not None:
                try:
                    chunk_sink(chunk)
                except asyncio.QueueFull:
                    return self._reject(AdmissionStatus.BACKPRESSURE, "Consumer sink queue full")
                except Exception as exc:
                    return self._reject(
                        AdmissionStatus.BACKPRESSURE,
                        f"Consumer sink disconnected or backpressured ({type(exc).__name__})",
                    )

            self._delivered_keys.add(dedupe_key)
            self._expected_chunk_index[order_key] = expected_idx + 1

        return DeliveryOutcome(
            accepted=True,
            status=AdmissionStatus.ACCEPTED,
            chunk=chunk,
            reason_code="DELIVERED_TO_SERVER_SINK",
        )

    @staticmethod
    def is_soft_paused(session_ctx: SessionContext | None) -> bool:
        return session_ctx is not None and session_ctx.pause.state == PauseState.SOFT_PAUSED

    @staticmethod
    def _reject(status: AdmissionStatus, message: str) -> DeliveryOutcome:
        cat = (
            ErrorCategory.STALE_SCOPE
            if status
            in {
                AdmissionStatus.STALE_SESSION,
                AdmissionStatus.STALE_TURN,
                AdmissionStatus.STALE_GENERATION,
                AdmissionStatus.CANCELED,
                AdmissionStatus.CLOSED,
                AdmissionStatus.REVISION_MISMATCH,
            }
            else ErrorCategory.CAPACITY
            if status == AdmissionStatus.BACKPRESSURE
            else ErrorCategory.VALIDATION
        )
        return DeliveryOutcome(
            accepted=False,
            status=status,
            chunk=None,
            reason_code=status.value,
            error=ErrorInfo(
                code=f"DELIVERY_{status.value}",
                category=cat,
                retryable=Retryability.NO,
                safe_message=message,
            ),
        )


__all__ = [
    "DeliveryOutcome",
    "GenerationDeliveryFence",
]
