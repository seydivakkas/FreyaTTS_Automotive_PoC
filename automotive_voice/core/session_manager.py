"""M01 in-memory session authority + bounded per-session event outbox.

All mutations are per-session locked and emit exactly one ordered envelope. The
outbox is retained across bus backpressure; delivery is best-effort in-memory,
not durable/exactly-once. M02 may replace the provisional legacy FSM.
"""
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Callable
from automotive_voice.core.session import Session, State
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.core.events import EventEnvelope, EventType
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.cancellation import CancellationController, CancellationToken

class UnknownSessionError(LookupError): pass
class SessionAlreadyExistsError(ValueError): pass
class SessionOutboxFullError(RuntimeError): pass

@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session_id: SessionId
    state: State
    turn_id: TurnId
    generation_id: GenerationId
    last_sequence: int
    pending_events: int

@dataclass(slots=True)
class _ManagedSession:
    value: Session
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    outbox: deque[EventEnvelope] = field(default_factory=deque)
    last_sequence: int = -1
    cancellation: CancellationController = field(default_factory=CancellationController)

class SessionManager:
    def __init__(self, bus: EventBus, max_pending_events: int = 256):
        if type(max_pending_events) is not int or max_pending_events < 1:
            raise ValueError("max_pending_events must be positive")
        self.bus = bus
        self._pending_limit = max_pending_events
        self._sessions: dict[SessionId, _ManagedSession] = {}
        self._directory_lock = asyncio.Lock()

    async def create(self, session_id: str | None = None) -> SessionSnapshot:
        sid = SessionId.new() if session_id is None else SessionId(session_id)
        async with self._directory_lock:
            if sid in self._sessions:
                raise SessionAlreadyExistsError(f"Session already exists: {sid}")
            managed = _ManagedSession(Session(sid))
            self._sessions[sid] = managed
            return self._snapshot(managed)

    def _entry(self, session_id: str) -> _ManagedSession:
        sid = SessionId(session_id)
        try:
            return self._sessions[sid]
        except KeyError as exc:
            raise UnknownSessionError(sid) from exc

    @staticmethod
    def _snapshot(managed: _ManagedSession) -> SessionSnapshot:
        s = managed.value
        return SessionSnapshot(SessionId(s.session_id), s.state, TurnId(s.turn_id),
                               GenerationId(s.generation_id), managed.last_sequence,
                               len(managed.outbox))

    async def snapshot(self, session_id: str) -> SessionSnapshot:
        m = self._entry(session_id)
        async with m.lock:
            return self._snapshot(m)

    async def _apply(self, session_id: str, event_type: EventType,
                     mutation: Callable[[Session], None],
                     payload: dict | None = None,
                     *, idempotent_ended: bool = False) -> SessionSnapshot:
        m = self._entry(session_id)
        async with m.lock:
            if idempotent_ended and m.value.state == State.ENDED:
                return self._snapshot(m)
            if len(m.outbox) >= self._pending_limit:
                raise SessionOutboxFullError("Outbox full; dispatch before more transitions")
            # Apply to a separate copy before committing: validation failures
            # must not mutate the source or assign event sequence IDs.
            new = replace(m.value, history=list(m.value.history))
            old_generation = new.generation_id
            mutation(new)
            event = EventEnvelope.create(event_type, SessionId(new.session_id),
                    TurnId(new.turn_id), GenerationId(new.generation_id),
                    m.last_sequence + 1, payload or {})
            m.value = new
            m.last_sequence += 1
            m.outbox.append(event)
            if new.state in (State.ENDED, State.FAILED, State.HANDOFF):
                m.cancellation.cancel_current()
            elif new.generation_id > old_generation:
                m.cancellation.advance(GenerationId(new.generation_id))
            return self._snapshot(m)

    async def start(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.SESSION_STARTED,
                                 lambda s: s.move(State.LISTENING), {"to": "LISTENING"})

    async def begin_turn(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.TURN_STARTED,
                                 lambda s: s.new_turn(), {"to": "THINKING"})

    async def begin_response(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.RESPONSE_STARTED,
                                 lambda s: s.move(State.SPEAKING), {"to": "SPEAKING"})

    async def finish_playout(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.PLAYOUT_FINISHED,
                                 lambda s: s.move(State.LISTENING), {"to": "LISTENING"})

    async def interrupt(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.INTERRUPTED,
                                 lambda s: s.interrupt(), {"to": "INTERRUPTING", "reason": "barge_in"})

    async def complete_interrupt(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.INTERRUPTION_COMPLETED,
                                 lambda s: s.move(State.LISTENING), {"to": "LISTENING"})

    async def request_handoff(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.HANDOFF_REQUESTED,
                                 lambda s: s.move(State.HANDOFF), {"to": "HANDOFF"})

    async def fail(self, session_id: str, reason_code: str) -> SessionSnapshot:
        if not reason_code or len(reason_code) > 64:
            raise ValueError("reason_code required")
        return await self._apply(session_id, EventType.SESSION_FAILED,
                                 lambda s: s.move(State.FAILED), {"code": reason_code})

    async def end(self, session_id: str, *, closure_reason: str | None = None) -> SessionSnapshot:
        payload = {"to": "ENDED"}
        if closure_reason is not None:
            if closure_reason not in {"normal", "disconnect", "transport_error"}:
                raise ValueError("invalid closure reason")
            payload["closure_reason"] = closure_reason
        return await self._apply(session_id, EventType.SESSION_ENDED,
                                 lambda s: s.move(State.ENDED), payload, idempotent_ended=True)

    async def emergency_close(self, session_id: str, *, fail: bool = False) -> SessionSnapshot:
        """Fail-closed terminal path when RAM outbox is saturated.

        Intentionally emits NO EventEnvelope when the bounded outbox has no room.
        Caller MUST record an independent diagnostic and send a terminate command.
        This is a safety fallback, not a durable or fully audited transaction.
        """
        managed = self._entry(session_id)
        async with managed.lock:
            if managed.value.state in (State.ENDED, State.FAILED):
                return self._snapshot(managed)
            new = replace(managed.value, history=list(managed.value.history))
            new.move(State.FAILED if fail and new.state != State.IDLE else State.ENDED)
            managed.value = new
            managed.cancellation.cancel_current()
            return self._snapshot(managed)

    async def abort_thinking(self, session_id: str) -> SessionSnapshot:
        """Drop an unspoken LLM answer after user speech; invalidate old generation.

        Additive M02-compatible API; leaves the M01 public methods unchanged.
        """
        def mutation(s: Session) -> None:
            if s.state != State.THINKING:
                raise ValueError("abort_thinking only valid in THINKING")
            s.move(State.LISTENING)
            s.generation_id += 1
        return await self._apply(session_id, EventType.STATE_CHANGED, mutation,
                                 {"to": "LISTENING", "reason": "thinking_interrupted"})

    async def complete_interrupt_with_followup(self, session_id: str,
                                                 followup: str | None = None) -> SessionSnapshot:
        """Atomically commit flush completion + optional new turn/handoff.

        Prevents a partially committed LISTENING state if second transition
        fails due to M01 outbox backpressure. The caller MUST validate that a
        matching transport flush ACK was received before invoking this method.
        """
        if followup not in (None, "turn", "handoff"):
            raise ValueError("followup must be None, turn, or handoff")
        managed = self._entry(session_id)
        async with managed.lock:
            count = 1 + int(followup is not None)
            if len(managed.outbox) + count > self._pending_limit:
                raise SessionOutboxFullError("Outbox full; atomic flush completion deferred")
            new = replace(managed.value, history=list(managed.value.history))
            if new.state != State.INTERRUPTING:
                raise ValueError("Must be INTERRUPTING before flush ACK")
            start_gen = new.generation_id
            new.move(State.LISTENING)
            sequence = managed.last_sequence + 1
            events = [EventEnvelope.create(EventType.INTERRUPTION_COMPLETED,
                SessionId(new.session_id), TurnId(new.turn_id), GenerationId(new.generation_id),
                sequence, {"to": "LISTENING", "transport_ack": True})]
            if followup == "turn":
                new.new_turn()
                events.append(EventEnvelope.create(EventType.TURN_STARTED, SessionId(new.session_id),
                    TurnId(new.turn_id), GenerationId(new.generation_id), sequence + 1,
                    {"to": "THINKING", "source": "deferred_transcript"}))
            elif followup == "handoff":
                new.move(State.HANDOFF)
                events.append(EventEnvelope.create(EventType.HANDOFF_REQUESTED, SessionId(new.session_id),
                    TurnId(new.turn_id), GenerationId(new.generation_id), sequence + 1,
                    {"to": "HANDOFF", "source": "deferred_handoff"}))
            managed.value = new
            managed.last_sequence += len(events)
            managed.outbox.extend(events)
            if new.state == State.HANDOFF:
                managed.cancellation.cancel_current()
            elif new.generation_id > start_gen:
                managed.cancellation.advance(GenerationId(new.generation_id))
            return self._snapshot(managed)

    async def accepts_chunk(self, session_id: str, generation_id: int) -> bool:
        m = self._entry(session_id)
        async with m.lock:
            return m.value.accepts_chunk(generation_id) and m.cancellation.is_current(generation_id)

    async def current_token(self, session_id: str) -> CancellationToken:
        m = self._entry(session_id)
        async with m.lock:
            if m.value.state in (State.ENDED, State.FAILED):
                raise ValueError("Terminal session has no active generation")
            return m.cancellation.current

    async def register_task(self, session_id: str, generation_id: int, task: asyncio.Task) -> None:
        m = self._entry(session_id)
        async with m.lock:
            m.cancellation.token_for(generation_id).register_task(task)

    async def dispatch_pending(self, session_id: str) -> int:
        """Drain in order; on subscriber backpressure, preserve unsent items."""
        m = self._entry(session_id)
        count = 0
        async with m.lock:
            while m.outbox:
                event = m.outbox[0]
                await self.bus.publish(event)
                m.outbox.popleft()
                count += 1
        return count
