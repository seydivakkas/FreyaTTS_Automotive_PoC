"""M06 glue between M02 effects and a *fake* media transport.

No fabricated PBX acknowledgments. Caller supplies M02 monotonic sequence.
"""
from __future__ import annotations
from dataclasses import dataclass
from automotive_voice.audio.contracts import FlushRequest, FlushAck
from automotive_voice.audio.queue import MediaBuffer
from automotive_voice.core.session import State
from automotive_voice.conversation.effects import Effect, EffectKind
from automotive_voice.conversation.signals import ConversationSignal,SignalKind
from automotive_voice.conversation.reducer import ConversationReducer,ReductionResult,Decision
from automotive_voice.telephony.transport import FakeTransport

@dataclass(frozen=True,slots=True)
class DispatchResult:
    accepted: bool
    reason: str

class MediaCoordinator:
    def __init__(self,reducer:ConversationReducer,buffer:MediaBuffer,transport:FakeTransport):
        self.reducer=reducer;self.buffer=buffer;self.transport=transport
        self._pending:dict[str,FlushRequest]={}

    async def send_next(self,sid:str)->DispatchResult:
        if not self.transport.can_send(sid):return DispatchResult(False,'transport_backpressure')
        chunk=await self.buffer.pop_next(sid)
        if chunk is None:return DispatchResult(False,'no_active_chunk')
        # Revalidate current M01 state immediately before fake transport delivery.
        snap=await self.reducer.manager.snapshot(sid)
        if snap.state is not State.SPEAKING or snap.turn_id != chunk.turn_id or snap.generation_id != chunk.generation_id or not await self.reducer.manager.accepts_chunk(sid,int(chunk.generation_id)):
            return DispatchResult(False,'became_stale')
        ok=await self.transport.send_metadata(chunk)
        if not ok:
            await self.buffer.return_front(chunk)
        return DispatchResult(ok,'sent_mock_metadata' if ok else 'transport_backpressure_after_dequeue')

    async def request_flush(self,effect:Effect)->FlushRequest:
        if not isinstance(effect,Effect) or effect.kind != EffectKind.FLUSH_MEDIA:
            raise ValueError('FLUSH_MEDIA effect required')
        sid=str(effect.session_id)
        snap=await self.reducer.manager.snapshot(sid)
        if snap.state is not State.INTERRUPTING or snap.turn_id!=effect.turn_id or snap.generation_id!=effect.generation_id:
            raise ValueError('flush effect no longer matches M02 state')
        request=FlushRequest(effect.effect_id,effect.session_id,effect.turn_id,effect.generation_id)
        old=self._pending.get(sid)
        if old is not None:
            if old != request:raise ValueError('conflicting pending flush')
            return old
        await self.buffer.begin_flush(sid)
        await self.transport.request_flush(request)
        self._pending[sid]=request
        return request

    async def accept_fake_ack(self,ack:FlushAck,*,sequence:int,mono_ns:int)->ReductionResult:
        """Only accepts explicit fake adapter receipt; never claims actual PBX success."""
        if not isinstance(ack,FlushAck) or not ack.confirmed_by_adapter or ack.adapter_kind!='fake':
            raise ValueError('not a verified fake adapter receipt')
        sid=str(ack.session_id)
        pending=self._pending.get(sid)
        if pending is None or (pending.flush_request_id,pending.session_id,pending.turn_id,pending.generation_id)!=(ack.flush_request_id,ack.session_id,ack.turn_id,ack.generation_id):
            raise ValueError('wrong or replayed flush ACK')
        if ack.adapter_id!=self.transport.adapter_id:raise ValueError('wrong transport adapter')
        if not self.transport.has_confirmed(ack):raise ValueError('unissued or forged fake ACK')
        snap=await self.reducer.manager.snapshot(sid)
        if snap.state!=State.INTERRUPTING or snap.turn_id!=ack.turn_id or snap.generation_id!=ack.generation_id:
            raise ValueError('ACK after state changed')
        signal=ConversationSignal.create(SignalKind.MEDIA_FLUSH_ACK,sid,int(ack.turn_id),int(ack.generation_id),sequence,
                     flush_request_id=ack.flush_request_id,mono_ns=mono_ns)
        result=await self.reducer.handle(signal)
        if result.decision == Decision.APPLIED:
            self.transport.consume_confirmation(ack)
            self._pending.pop(sid,None)
            await self.buffer.end_flush(sid)
        return result

    async def terminate(self,sid:str):
        self._pending.pop(sid,None)
        await self.buffer.close(sid)
        await self.transport.terminate(sid)
