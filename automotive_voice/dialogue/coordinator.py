"""Bridge REQUEST_LLM -> deterministic business policy -> M02 safe response ref.

No actual LLM is called. A future NLG adapter may paraphrase approved semantic
results; it must not change prices, booking status or booking confirmation.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Callable
from automotive_voice.conversation import ConversationReducer, ConversationSignal, SignalKind, Decision
from automotive_voice.conversation.effects import Effect, EffectKind
from automotive_voice.core.session import State
from .models import AccessContext
from .policy import DialoguePolicy
from .storage import ReferenceStore, MissingReferenceError

@dataclass(frozen=True, slots=True)
class CoordinationResult:
    status: str
    action: str
    response_ref: str | None = None

class DialogueCoordinator:
    def __init__(self, reducer: ConversationReducer, policy: DialoguePolicy, store: ReferenceStore,
                 *, clock_ns: Callable[[], int] | None = None):
        self.reducer, self.policy, self.store = reducer, policy, store
        self.clock_ns = clock_ns
        self._locks: dict[str, asyncio.Lock] = {}

    async def process(self, effect: Effect, access: AccessContext) -> CoordinationResult:
        if effect.kind != EffectKind.REQUEST_LLM:
            raise ValueError('only REQUEST_LLM effect accepted')
        sid = str(effect.session_id)
        lock = self._locks.setdefault(sid, asyncio.Lock())
        async with lock:
            async def current() -> bool:
                snap = await self.reducer.try_snapshot(sid)
                return bool(snap and snap.state == State.THINKING and
                            int(snap.turn_id) == int(effect.turn_id) and
                            int(snap.generation_id) == int(effect.generation_id))
            if not await current():
                return CoordinationResult('stale', 'stale_generation')
            try:
                inp = self.store.get_input(sid, effect.reference or '')
            except MissingReferenceError:
                # No text is invented when an opaque reference is missing.
                return CoordinationResult('missing_reference', 'missing_transcript')
            try:
                decision = await self.policy.handle(sid, inp, access, is_current=current)
            except Exception:
                if not await current():
                    return CoordinationResult('stale', 'stale_generation')
                safe_ref = self.store.put_response(sid, 'İşlemi şu anda doğrulayamıyorum. Temsilciye aktarılabilirsiniz.', 'business_unknown')
                from .models import PolicyDecision, BookingStatus
                decision = PolicyDecision(safe_ref, BookingStatus.UNKNOWN, 'business_unknown')
            if decision.action == 'stale_generation' or not await current():
                return CoordinationResult('stale', 'stale_generation')
            kind = SignalKind.HANDOFF_REQUESTED if decision.handoff_requested else SignalKind.LLM_RESPONSE_READY
            signal = ConversationSignal.create(kind, sid, int(effect.turn_id), int(effect.generation_id),
                await self.reducer.expected_sequence(sid), reference=decision.response_ref,
                mono_ns=self.clock_ns() if self.clock_ns is not None else None)
            result = await self.reducer.handle(signal)
            return CoordinationResult('applied' if result.decision == Decision.APPLIED else result.decision.value,
                                      decision.action, decision.response_ref if result.decision == Decision.APPLIED else None)
