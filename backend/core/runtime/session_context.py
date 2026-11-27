"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable
from uuid import uuid4

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, EventEnvelope, GenerationRef, SessionIdentity, TurnRef
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.deadlines import Clock, DeadlineBudget, SystemMonotonicClock
from backend.core.runtime.resource_ledger import ResourceLedger, TaskRegistry
from backend.core.runtime.result_admission import AdmissionStatus, BoundedMediaQueue, QueuedMediaItem
from backend.core.runtime.turn_generation import PauseController, PauseRef, PauseState, TurnGenerationManager


class SessionLifecycleState(StrEnum):
    NEW = "NEW"
    OPENING = "OPENING"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class CleanupStatus(StrEnum):
    NOT_CLOSED = "NOT_CLOSED"
    COMPLETE = "COMPLETE"
    PENDING_RECLAIM = "PENDING_RECLAIM"


_TRANSITIONS = {
    SessionLifecycleState.NEW: {SessionLifecycleState.OPENING, SessionLifecycleState.CLOSING},
    SessionLifecycleState.OPENING: {SessionLifecycleState.ACTIVE, SessionLifecycleState.CLOSING},
    SessionLifecycleState.ACTIVE: {SessionLifecycleState.CLOSING},
    SessionLifecycleState.CLOSING: {SessionLifecycleState.CLOSED},
    SessionLifecycleState.CLOSED: set(),
}


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    session_id: str
    incarnation_id: str
    lifecycle_state: SessionLifecycleState
    turn_id: int
    generation_id: int
    pause_state: PauseState
    pause_epoch: int
    queued_media_items: int
    queued_media_bytes: int
    cleanup_status: CleanupStatus
    quarantined_leases: int


class SessionContext:
    """Single authoritative live session context with linearized admission and cleanup."""

    def __init__(
        self,
        identity: SessionIdentity,
        *,
        incarnation_id: str | None = None,
        clock: Clock | None = None,
        max_queue_items: int = 64,
        max_queue_bytes: int = 256 * 1024,
        event_sink: Callable[[EventEnvelope], None] | None = None,
    ) -> None:
        self.identity = identity
        self.incarnation_id = incarnation_id or uuid4().hex
        self.clock: Clock = clock or SystemMonotonicClock()
        self.lifecycle_state: SessionLifecycleState = SessionLifecycleState.NEW
        self.cleanup_status: CleanupStatus = CleanupStatus.NOT_CLOSED
        self.close_reason: str | None = None
        self.lock = asyncio.Lock()
        self.root_scope = CancellationScope(f"session:{identity.session_id}:{self.incarnation_id}", clock=self.clock)
        self.tg = TurnGenerationManager(identity.session_id, self.root_scope)
        self.pause = PauseController()
        self.queue = BoundedMediaQueue(max_items=max_queue_items, max_bytes=max_queue_bytes)
        self.ledger = ResourceLedger()
        self.tasks = TaskRegistry()
        self._event_sink = event_sink
        self._seq = -1
        self._close_task: asyncio.Task[CleanupStatus] | None = None

    def _emit_safe(self, event_type: str, metadata: dict[str, Any] | None = None) -> None:
        if self._event_sink is None:
            return
        self._seq += 1
        turn_id = self.tg.active_turn.turn_id if self.tg.active_turn else None
        gen_id = self.tg.active_generation.generation_id if self.tg.active_generation else None
        env = EventEnvelope(
            schema_version=CONTRACT_SCHEMA_VERSION,
            event_type=event_type,
            session_id=self.identity.session_id,
            trace_id=self.identity.trace_id,
            turn_id=turn_id,
            generation_id=gen_id,
            sequence=self._seq,
            monotonic_ns=self.clock.monotonic_ns(),
            clock_domain=self.clock.clock_domain,
            producer="m02.runtime",
            metadata=metadata or {},
        )
        try:
            self._event_sink(env)
        except Exception:
            # Observer failure must never corrupt runtime lifecycle.
            pass

    def _move_state(self, target: SessionLifecycleState) -> None:
        if target not in _TRANSITIONS[self.lifecycle_state]:
            raise ValueError(f"Invalid lifecycle transition: {self.lifecycle_state} -> {target}")
        self.lifecycle_state = target

    async def open(self, setup_fn: Callable[[], None] | None = None) -> RuntimeSnapshot:
        async with self.lock:
            self._move_state(SessionLifecycleState.OPENING)
            self._emit_safe("session.opening")
            try:
                if setup_fn is not None:
                    setup_fn()
            except Exception:
                self._move_state(SessionLifecycleState.CLOSING)
                self.root_scope.request_cancel("open_failed")
                self.ledger.close_all()
                self._move_state(SessionLifecycleState.CLOSED)
                self.cleanup_status = CleanupStatus.COMPLETE
                self._emit_safe("session.closed", {"reason": "open_failed"})
                raise
            self._move_state(SessionLifecycleState.ACTIVE)
            self._emit_safe("session.opened")
            return self.snapshot_nowait()

    async def begin_turn(self) -> tuple[TurnRef, CancellationScope]:
        async with self.lock:
            if self.lifecycle_state != SessionLifecycleState.ACTIVE:
                raise RuntimeError(f"Cannot begin turn in state {self.lifecycle_state}")
            tref, tscope = self.tg.begin_turn()
            self._emit_safe("turn.started")
            return tref, tscope

    async def begin_generation(self, turn_ref: TurnRef | None = None) -> tuple[GenerationRef, CancellationScope]:
        async with self.lock:
            if self.lifecycle_state != SessionLifecycleState.ACTIVE:
                raise RuntimeError(f"Cannot begin generation in state {self.lifecycle_state}")
            gref, gscope = self.tg.begin_generation(turn_ref)
            self.pause.reset_for_generation(gref)
            self._emit_safe("generation.started")
            return gref, gscope

    async def admit_media(
        self,
        item: QueuedMediaItem,
        *,
        incarnation_id: str | None = None,
        expected_plan_revision: int | None = None,
        deadline: DeadlineBudget | None = None,
    ) -> AdmissionStatus:
        async with self.lock:
            if incarnation_id is not None and incarnation_id != self.incarnation_id:
                return AdmissionStatus.STALE_SESSION
            if self.lifecycle_state in {SessionLifecycleState.CLOSING, SessionLifecycleState.CLOSED}:
                return AdmissionStatus.CLOSED
            if self.lifecycle_state != SessionLifecycleState.ACTIVE:
                return AdmissionStatus.INVALID
            if self.root_scope.is_cancel_requested:
                return AdmissionStatus.CANCELED
            if deadline is not None and deadline.is_expired(self.clock):
                return AdmissionStatus.DEADLINE_EXCEEDED
            if item.generation_ref.session_id != self.identity.session_id:
                return AdmissionStatus.STALE_SESSION
            active_turn = self.tg.active_turn
            if active_turn is None or item.generation_ref.turn_id != active_turn.turn_id:
                return AdmissionStatus.STALE_TURN
            active_gen = self.tg.active_generation
            if active_gen is None or item.generation_ref.generation_id != active_gen.generation_id:
                return AdmissionStatus.STALE_GENERATION
            if self.tg.generation_scope is None or self.tg.generation_scope.is_cancel_requested:
                return AdmissionStatus.CANCELED
            if expected_plan_revision is not None and item.plan_revision != expected_plan_revision:
                return AdmissionStatus.REVISION_MISMATCH
            status = self.queue.enqueue(item)
            if status == AdmissionStatus.BACKPRESSURE:
                self._emit_safe("buffer.backpressure")
            elif status != AdmissionStatus.ACCEPTED:
                self._emit_safe("result.rejected", {"reason": status.value})
            return status

    async def dequeue_for_submission(self, expected_gen: GenerationRef) -> tuple[AdmissionStatus, QueuedMediaItem | None]:
        async with self.lock:
            if self.lifecycle_state != SessionLifecycleState.ACTIVE:
                return AdmissionStatus.CLOSED, None
            if self.tg.active_generation != expected_gen:
                return AdmissionStatus.STALE_GENERATION, None
            if self.tg.generation_scope is None or self.tg.generation_scope.is_cancel_requested:
                return AdmissionStatus.CANCELED, None
            if self.pause.state == PauseState.SOFT_PAUSED:
                return AdmissionStatus.PAUSED, None
            item = self.queue.pop_next()
            if item is None:
                return AdmissionStatus.INVALID, None
            if item.generation_ref != expected_gen:
                return AdmissionStatus.STALE_GENERATION, None
            return AdmissionStatus.ACCEPTED, item

    async def soft_pause(self) -> PauseRef | None:
        async with self.lock:
            if self.lifecycle_state != SessionLifecycleState.ACTIVE or self.tg.active_generation is None:
                return None
            if self.tg.generation_scope is None or self.tg.generation_scope.is_cancel_requested:
                return None
            pref = self.pause.soft_pause(self.tg.active_generation)
            self._emit_safe("pause.requested", {"pause_epoch": pref.pause_epoch})
            return pref

    async def resume_pause(self, pause_ref: PauseRef) -> bool:
        async with self.lock:
            if self.lifecycle_state != SessionLifecycleState.ACTIVE or self.tg.active_generation is None or self.tg.generation_scope is None:
                return False
            ok = self.pause.resume(pause_ref, self.tg.active_generation, self.tg.generation_scope)
            if ok:
                self._emit_safe("pause.resumed", {"pause_epoch": pause_ref.pause_epoch})
            return ok

    async def commit_interrupt(self, reason: str = "barge_in_commit") -> bool:
        async with self.lock:
            if self.tg.active_generation is None or self.tg.generation_scope is None:
                return False
            gen = self.tg.active_generation
            changed = self.pause.commit_interrupt(gen, self.tg.generation_scope, reason=reason)
            self.queue.purge_generation(gen.generation_id)
            if changed:
                self._emit_safe("generation.revoked", {"reason": reason})
            return changed

    async def close(self, reason: str = "normal_close", *, drain_timeout_sec: float = 0.5) -> CleanupStatus:
        async with self.lock:
            if self.lifecycle_state == SessionLifecycleState.CLOSED:
                return self.cleanup_status
            if self._close_task is None:
                self._close_task = asyncio.shield(asyncio.create_task(self._perform_close(reason, drain_timeout_sec)))
            task = self._close_task
        return await task

    async def _perform_close(self, reason: str, drain_timeout_sec: float) -> CleanupStatus:
        async with self.lock:
            if self.lifecycle_state == SessionLifecycleState.CLOSED:
                return self.cleanup_status
            if self.lifecycle_state != SessionLifecycleState.CLOSING:
                self._move_state(SessionLifecycleState.CLOSING)
                self.close_reason = reason
                self.root_scope.request_cancel(reason)
                self.queue.clear_all()
                self._emit_safe("session.closing", {"reason": reason})
        _, still_pending = await self.tasks.cancel_and_drain(timeout_sec=drain_timeout_sec)
        async with self.lock:
            _, quarantined, _ = self.ledger.close_all()
            self.cleanup_status = CleanupStatus.PENDING_RECLAIM if (still_pending > 0 or quarantined > 0) else CleanupStatus.COMPLETE
            if self.lifecycle_state == SessionLifecycleState.CLOSING:
                self._move_state(SessionLifecycleState.CLOSED)
            self._emit_safe("session.closed", {"cleanup_status": self.cleanup_status.value})
            return self.cleanup_status

    def snapshot_nowait(self) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            session_id=self.identity.session_id,
            incarnation_id=self.incarnation_id,
            lifecycle_state=self.lifecycle_state,
            turn_id=self.tg.active_turn.turn_id if self.tg.active_turn else 0,
            generation_id=self.tg.active_generation.generation_id if self.tg.active_generation else 0,
            pause_state=self.pause.state,
            pause_epoch=self.pause.epoch,
            queued_media_items=self.queue.item_count,
            queued_media_bytes=self.queue.bytes_used,
            cleanup_status=self.cleanup_status,
            quarantined_leases=self.ledger.quarantined_count,
        )
