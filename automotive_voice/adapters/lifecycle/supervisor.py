"""M07 lightweight adapter supervisor. M02 and M03 remain authoritative.

Does not infer CRM decisions, fabricate flush ACKs or open any network.
"""
from __future__ import annotations
import asyncio
from automotive_voice.conversation.effects import Effect,EffectKind
from automotive_voice.audio.coordinator import MediaCoordinator
from .clock import MockClock
from .runtime import SyntheticAdapter
from .contracts import (AdapterKind,AdapterReceipt,SyntheticCommand,Deadline,RetryPolicy,ResultCode)
from automotive_voice.core.session_manager import SessionManager

EFFECT_ROUTE={EffectKind.REQUEST_LLM:AdapterKind.LLM,EffectKind.START_TTS:AdapterKind.TTS,
              EffectKind.QUEUE_AUDIO:AdapterKind.TELEPHONY}

class AdapterSupervisor:
    def __init__(self,manager:SessionManager,clock:MockClock,*,media:MediaCoordinator|None=None,
                 retry:RetryPolicy|None=None,max_pending:int=32,max_inflight:int=2):
        self.manager=manager;self.clock=clock;self.media=media
        self.adapters={kind:SyntheticAdapter(kind,manager,clock,retry=retry,
                  max_pending=max_pending,max_inflight=max_inflight) for kind in AdapterKind}
        self._lock=asyncio.Lock()
    async def start_all(self):
        for adapter in self.adapters.values():await adapter.start()
    async def stop_all(self):
        for adapter in self.adapters.values():await adapter.stop()
    async def cancel_session(self,sid:str):
        return {kind:await a.cancel_session(sid) for kind,a in self.adapters.items()}
    async def dispatch_effect(self,effect:Effect,*,deadline_ns:int|None=None)->AdapterReceipt:
        if not isinstance(effect,Effect):raise TypeError('Effect required')
        sid=str(effect.session_id)
        if effect.kind in (EffectKind.CANCEL_GENERATION,EffectKind.TERMINATE_CALL,EffectKind.START_HANDOFF):
            await self.cancel_session(sid)
            if effect.kind is EffectKind.TERMINATE_CALL and self.media is not None:
                await self.media.terminate(sid)
            return AdapterReceipt(True,'mock_lifecycle_cancelled',effect.effect_id)
        if effect.kind is EffectKind.FLUSH_MEDIA:
            await self.cancel_session(sid)
            if self.media is None:return AdapterReceipt(False,'media_coordinator_missing',effect.effect_id)
            await self.media.request_flush(effect)
            return AdapterReceipt(True,'mock_flush_requested_ack_not_proven',effect.effect_id)
        kind=EFFECT_ROUTE.get(effect.kind)
        if kind is None:return AdapterReceipt(False,'unsupported_effect',effect.effect_id)
        if not effect.reference:return AdapterReceipt(False,'opaque_reference_required',effect.effect_id)
        async with self._lock:
            seq=await self.adapters[kind].expected_sequence(sid)
            # Duplicate effect should be routed to the runtime for a replay check
            # rather than incrementing the sequence.
            existing=self.adapters[kind]._jobs.get(effect.effect_id)
            term=self.adapters[kind]._terminal.get(effect.effect_id)
            if existing is not None:seq=existing.command.sequence
            elif term is not None:seq=term[0].sequence
            if existing is not None:deadline=existing.command.deadline
            elif term is not None:deadline=term[0].deadline
            else:deadline=Deadline(deadline_ns if deadline_ns is not None else self.clock.now_ns()+5_000_000_000)
            cmd=SyntheticCommand(effect.effect_id,kind,effect.session_id,effect.turn_id,
                                 effect.generation_id,seq,effect.reference,deadline,
                                 idempotent=(kind is not AdapterKind.TELEPHONY))
            receipt=await self.adapters[kind].submit(cmd)
            return receipt
    async def tick_all(self):
        return {kind:await a.tick() for kind,a in self.adapters.items()}
    def health(self):return {kind.value:a.health() for kind,a in self.adapters.items()}
