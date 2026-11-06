"""Deterministic, per-session M02 reducer built on M01 SessionManager.

Signal receipt is separate from effect delivery. Neither transport ACK nor durable
outbox is implied by queuing an effect. Inputs carry references, never transcript
text/audio/PII. The only source of session state is M01 SessionManager.
"""
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid5, NAMESPACE_URL
from automotive_voice.core.session import State
from automotive_voice.core.session_manager import (SessionManager, SessionOutboxFullError,
                                                   UnknownSessionError)
from automotive_voice.core.event_bus import EventBus
from .signals import ConversationSignal, SignalKind
from .effects import Effect, EffectKind


class Decision(str, Enum):
    APPLIED = "applied"
    IGNORED = "ignored"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AuditRecord:
    event_id: str
    session_id: str
    sequence: int
    kind: SignalKind
    decision: Decision
    reason: str
    state: State | None


@dataclass(frozen=True, slots=True)
class ReductionResult:
    decision: Decision
    reason: str
    state: State | None
    effects: tuple[Effect, ...]
    input_sequence: int


@dataclass(slots=True)
class _Runtime:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    expected_input: int = 0
    last_mono_ns: int = -1
    seen_ids: set[str] = field(default_factory=set)
    seen_order: deque[str] = field(default_factory=deque)
    pending_effects: deque[Effect] = field(default_factory=deque)
    audit: deque[AuditRecord] = field(default_factory=lambda: deque(maxlen=1024))
    pending_flush_id: str | None = None
    flush_deadline_mono_ns: int | None = None
    deferred_transcript_ref: str | None = None
    deferred_handoff: bool = False
    vad_active: bool = False


class ConversationReducer:
    def __init__(self, manager: SessionManager | None = None, *, effect_capacity: int = 256,
                 dedup_capacity: int = 4096, audit_capacity: int = 1024,
                 flush_timeout_ms: int = 1500):
        for name, value in (("effect_capacity", effect_capacity),
                            ("dedup_capacity", dedup_capacity), ("audit_capacity", audit_capacity),
                            ("flush_timeout_ms", flush_timeout_ms)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.manager = manager or SessionManager(EventBus())
        self.effect_capacity = effect_capacity
        self.dedup_capacity = dedup_capacity
        self.audit_capacity = audit_capacity
        self.flush_timeout_ns = flush_timeout_ms * 1_000_000
        self._runtimes: dict[str, _Runtime] = {}
        self._directory_lock = asyncio.Lock()

    async def _runtime(self, sid: str) -> _Runtime:
        async with self._directory_lock:
            if sid not in self._runtimes:
                r = _Runtime()
                r.audit = deque(maxlen=self.audit_capacity)
                self._runtimes[sid] = r
            return self._runtimes[sid]

    async def _state(self, sid: str):
        try:
            return await self.manager.snapshot(sid)
        except UnknownSessionError:
            return None

    async def handle(self, signal: ConversationSignal) -> ReductionResult:
        if not isinstance(signal, ConversationSignal):
            raise TypeError("ConversationSignal required")
        # Do not allocate a runtime for arbitrary unknown external session IDs.
        if signal.kind != SignalKind.SESSION_OPENED and str(signal.session_id) not in self._runtimes:
            existing = await self._state(str(signal.session_id))
            if existing is None:
                return ReductionResult(Decision.REJECTED, "unknown_session", None, (), -1)
        rt = await self._runtime(str(signal.session_id))
        async with rt.lock:
            snap = await self._state(str(signal.session_id))
            state = snap.state if snap else None

            def result(decision: Decision, reason: str, effects=(), *, consume=False):
                if consume:
                    rt.expected_input += 1
                    rt.last_mono_ns = signal.occurred_mono_ns
                    if signal.event_id not in rt.seen_ids:
                        rt.seen_ids.add(signal.event_id)
                        rt.seen_order.append(signal.event_id)
                        while len(rt.seen_order) > self.dedup_capacity:
                            rt.seen_ids.discard(rt.seen_order.popleft())
                rt.audit.append(AuditRecord(signal.event_id, str(signal.session_id),
                              signal.sequence, signal.kind, decision, reason, state))
                return ReductionResult(decision, reason, state, tuple(effects), signal.sequence)

            if signal.sequence < rt.expected_input:
                return result(Decision.IGNORED, "replayed_sequence")
            if signal.sequence > rt.expected_input:
                return result(Decision.REJECTED, "sequence_gap")
            if signal.event_id in rt.seen_ids:
                return result(Decision.IGNORED, "duplicate_event_id", consume=True)
            if signal.occurred_mono_ns < rt.last_mono_ns:
                return result(Decision.REJECTED, "monotonic_clock_regression")
            if snap is None and signal.kind != SignalKind.SESSION_OPENED:
                return result(Decision.REJECTED, "unknown_session")
            if snap is not None and signal.kind == SignalKind.SESSION_OPENED:
                return result(Decision.IGNORED, "session_already_open", consume=True)
            if snap is None and (signal.turn_id != 0 or signal.generation_id != 0):
                return result(Decision.REJECTED, "invalid_open_identifiers")
            if snap is not None and state in (State.ENDED, State.FAILED):
                return result(Decision.IGNORED, "terminal_session", consume=True)
            if snap is not None and signal.kind not in (SignalKind.HANGUP,) and (
                    int(signal.turn_id) != int(snap.turn_id) or
                    int(signal.generation_id) != int(snap.generation_id)):
                return result(Decision.IGNORED, "stale_turn_or_generation", consume=True)

            def effect(kind: EffectKind, t: int, g: int, ref: str | None = None):
                return Effect.from_signal(signal, kind, t, g, ref)

            # Compute which side effects will be queued before mutating the M01 state.
            planned: list[Effect] = []
            pending_flush_id = rt.pending_flush_id
            ack_followup = None
            deferred_ref = rt.deferred_transcript_ref
            sid = str(signal.session_id)
            t = int(snap.turn_id) if snap else 0
            g = int(snap.generation_id) if snap else 0
            action = "ignore"
            reason = "invalid_state_for_signal"

            if signal.kind == SignalKind.SESSION_OPENED:
                action = "open"
            elif signal.kind == SignalKind.HANGUP:
                action = "end"
                planned = [effect(EffectKind.TERMINATE_CALL, t, g)]
            elif signal.kind == SignalKind.VAD_SPEECH_STARTED:
                if state == State.LISTENING:
                    action = "vad_listen"
                elif state == State.THINKING:
                    action = "abort_thinking"
                    planned = [effect(EffectKind.CANCEL_GENERATION, t, g)]
                elif state == State.SPEAKING:
                    action = "interrupt"
                    planned = [effect(EffectKind.CANCEL_GENERATION, t, g),
                               effect(EffectKind.FLUSH_MEDIA, t, g + 1)]
                else:
                    reason = "vad_not_accepted_in_state"
            elif signal.kind == SignalKind.TRANSCRIPT_FINAL:
                if state == State.LISTENING:
                    action = "turn"
                    planned = [effect(EffectKind.REQUEST_LLM, t + 1, g + 1, signal.reference)]
                elif state == State.INTERRUPTING and rt.pending_flush_id:
                    if rt.deferred_handoff:
                        reason = "handoff_pending_no_transcript"
                    elif rt.deferred_transcript_ref is None:
                        action = "defer_transcript"
                    else:
                        reason = "transcript_already_deferred"
            elif signal.kind == SignalKind.LLM_RESPONSE_READY:
                if state == State.THINKING:
                    action = "speak"
                    planned = [effect(EffectKind.START_TTS, t, g, signal.reference)]
            elif signal.kind == SignalKind.AUDIO_CHUNK_READY:
                if state == State.SPEAKING and await self.manager.accepts_chunk(sid, g):
                    action = "chunk"
                    planned = [effect(EffectKind.QUEUE_AUDIO, t, g, signal.reference)]
            elif signal.kind == SignalKind.PLAYOUT_FINISHED:
                if state == State.SPEAKING:
                    action = "playout"
            elif signal.kind == SignalKind.HANDOFF_REQUESTED:
                if state in (State.LISTENING, State.THINKING):
                    action = "handoff"
                    if state == State.THINKING:
                        planned.append(effect(EffectKind.CANCEL_GENERATION, t, g))
                    planned.append(effect(EffectKind.START_HANDOFF, t, g))
                elif state == State.SPEAKING:
                    action = "interrupt_handoff"
                    planned = [effect(EffectKind.CANCEL_GENERATION, t, g),
                               effect(EffectKind.FLUSH_MEDIA, t, g + 1)]
                elif state == State.INTERRUPTING and not rt.deferred_handoff:
                    action = "defer_handoff"
            elif signal.kind in (SignalKind.MEDIA_FLUSH_ACK, SignalKind.MEDIA_FLUSH_TIMEOUT):
                if state == State.INTERRUPTING and rt.pending_flush_id == signal.flush_request_id:
                    if signal.kind == SignalKind.MEDIA_FLUSH_TIMEOUT:
                        action = "timeout"
                        planned = [effect(EffectKind.TERMINATE_CALL, t, g)]
                    else:
                        action = "ack"
                        ack_followup = "handoff" if rt.deferred_handoff else "turn" if deferred_ref else None
                        if ack_followup == "turn":
                            planned = [effect(EffectKind.REQUEST_LLM, t + 1, g + 1, deferred_ref)]
                        elif ack_followup == "handoff":
                            planned = [effect(EffectKind.START_HANDOFF, t, g)]
                else:
                    reason = "unmatched_flush_request"
            if action == "ignore":
                return result(Decision.IGNORED, reason, consume=True)
            if action not in ("end", "timeout") and len(rt.pending_effects) + len(planned) > self.effect_capacity:
                return result(Decision.REJECTED, "effect_queue_full")
            # No external callbacks or network effects inside this lock. M01 is the
            # authority for state mutation and bounded event-outbox rollback.
            try:
                if action == "open":
                    await self.manager.create(sid)
                    snap = await self.manager.start(sid)
                elif action == "end":
                    snap = await self.manager.end(sid)
                elif action == "turn":
                    snap = await self.manager.begin_turn(sid)
                elif action == "speak":
                    snap = await self.manager.begin_response(sid)
                elif action == "playout":
                    snap = await self.manager.finish_playout(sid)
                elif action in ("interrupt", "interrupt_handoff"):
                    snap = await self.manager.interrupt(sid)
                elif action == "abort_thinking":
                    snap = await self.manager.abort_thinking(sid)
                elif action == "handoff":
                    snap = await self.manager.request_handoff(sid)
                elif action == "timeout":
                    snap = await self.manager.fail(sid, "media_flush_timeout")
                elif action == "ack":
                    snap = await self.manager.complete_interrupt_with_followup(sid, ack_followup)
            except SessionOutboxFullError:
                if action not in ("end", "timeout"):
                    return result(Decision.REJECTED, "state_or_outbox_rejected")
                # The safe end state takes precedence over audit delivery.
                snap = await self.manager.emergency_close(sid, fail=(action == "timeout"))
                action = "emergency_closed_no_m01_event"
            except ValueError:
                return result(Decision.REJECTED, "state_or_outbox_rejected")

            if action in ("interrupt", "interrupt_handoff"):
                rt.pending_flush_id = planned[-1].effect_id
                rt.flush_deadline_mono_ns = signal.occurred_mono_ns + self.flush_timeout_ns
                rt.deferred_transcript_ref = None
                rt.deferred_handoff = action == "interrupt_handoff"
                rt.vad_active = action == "interrupt"
            elif action == "defer_transcript":
                rt.deferred_transcript_ref = signal.reference
            elif action == "defer_handoff":
                rt.deferred_handoff = True
                rt.deferred_transcript_ref = None
            elif action in ("ack", "timeout", "end", "emergency_closed_no_m01_event"):
                rt.pending_flush_id = None
                rt.flush_deadline_mono_ns = None
                rt.deferred_transcript_ref = None
                rt.deferred_handoff = False
                rt.vad_active = False
            elif action in ("vad_listen", "abort_thinking"):
                rt.vad_active = True
            elif action in ("turn", "playout", "handoff"):
                rt.vad_active = False
            # Drop queued stale output commands before placing terminal transport
            # command. This only controls the volatile command queue, not PBX.
            if action in ("end", "timeout", "emergency_closed_no_m01_event"):
                rt.pending_effects.clear()
            rt.pending_effects.extend(planned)
            out = result(Decision.APPLIED, action, planned, consume=True)
            # result() emits an immutable audit log, but state belongs to M01.
            rt.audit[-1] = AuditRecord(signal.event_id, sid, signal.sequence,
                                      signal.kind, Decision.APPLIED, action, snap.state)
            return ReductionResult(Decision.APPLIED, action, snap.state, tuple(planned), signal.sequence)

    async def poll_flush_timeouts(self, now_mono_ns: int) -> dict[str, ReductionResult]:
        """Explicit deterministic watchdog tick (no background timer).

        A scheduler must call this regularly; M02 does not secretly run tasks.
        Passing a synthetic monotonic timestamp makes timeout tests reproducible.
        """
        if type(now_mono_ns) is not int or now_mono_ns < 0:
            raise ValueError("now_mono_ns must be nonnegative integer")
        outcomes: dict[str, ReductionResult] = {}
        for sid in tuple(self._runtimes):
            rt = await self._runtime(sid)
            async with rt.lock:
                flush_id = rt.pending_flush_id
                deadline = rt.flush_deadline_mono_ns
                expected = rt.expected_input
                mono = max(now_mono_ns, rt.last_mono_ns)
            if flush_id is None or deadline is None or now_mono_ns < deadline:
                continue
            snap = await self._state(sid)
            if snap is None or snap.state != State.INTERRUPTING:
                continue
            signal_id = str(uuid5(NAMESPACE_URL, f"freya-m02-timeout:{sid}:{flush_id}"))
            signal = ConversationSignal.create(SignalKind.MEDIA_FLUSH_TIMEOUT, sid,
                        int(snap.turn_id), int(snap.generation_id), expected,
                        flush_request_id=flush_id, event_id=signal_id, mono_ns=mono)
            outcomes[sid] = await self.handle(signal)
        return outcomes

    async def try_snapshot(self, session_id: str):
        """Public read-only snapshot; None until SESSION_OPENED is accepted."""
        return await self._state(str(session_id))

    async def pending_effects(self, session_id: str) -> tuple[Effect, ...]:
        rt = await self._runtime(session_id)
        async with rt.lock:
            return tuple(rt.pending_effects)

    async def drain_effects(self, session_id: str, limit: int | None = None) -> tuple[Effect, ...]:
        """Transfers volatile effects to caller; NOT delivery acknowledgment."""
        rt = await self._runtime(session_id)
        async with rt.lock:
            n = len(rt.pending_effects) if limit is None else limit
            if type(n) is not int or n < 0:
                raise ValueError("limit must be nonnegative integer")
            return tuple(rt.pending_effects.popleft() for _ in range(min(n, len(rt.pending_effects))))

    async def audit_records(self, session_id: str) -> tuple[AuditRecord, ...]:
        rt = await self._runtime(session_id)
        async with rt.lock:
            return tuple(rt.audit)

    async def pending_flush_id(self, session_id: str) -> str | None:
        rt = await self._runtime(session_id)
        async with rt.lock:
            return rt.pending_flush_id

    async def expected_sequence(self, session_id: str) -> int:
        rt = await self._runtime(session_id)
        async with rt.lock:
            return rt.expected_input
