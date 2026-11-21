"""M07 metadata-only synthetic stream + barge-in demo; no real WAV, model or PBX."""
from __future__ import annotations
import asyncio
import json
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.core.identifiers import SessionId,TurnId,GenerationId
from automotive_voice.conversation import ConversationReducer,ConversationSignal,SignalKind,Decision
from automotive_voice.conversation.effects import EffectKind
from automotive_voice.prosody import MockTTS
from automotive_voice.prosody.contracts import ClausePlan,Clause,BreakKind,PlanStatus
from automotive_voice.audio import MediaBuffer,MediaCoordinator
from automotive_voice.telephony import FakeTransport
from automotive_voice.adapters.lifecycle import (MockClock,AdapterKind,AdapterSupervisor,SyntheticStreamBridge,ResultCode)

async def main()->dict:
    c=MockClock();manager=SessionManager(EventBus());reducer=ConversationReducer(manager)
    sid='m07-demo'
    async def signal(kind,ref=None):
        snap=await reducer.try_snapshot(sid)
        return await reducer.handle(ConversationSignal.create(kind,sid,
            int(snap.turn_id) if snap else 0,int(snap.generation_id) if snap else 0,
            await reducer.expected_sequence(sid),reference=ref,mono_ns=c.now_ns()))
    await signal(SignalKind.SESSION_OPENED)
    await signal(SignalKind.TRANSCRIPT_FINAL,'ref:customer')
    await signal(SignalKind.LLM_RESPONSE_READY,'ref:policy-approved-reply')
    text='Merhaba dünya'
    plan=ClausePlan(SessionId(sid),TurnId(1),GenerationId(1),text,PlanStatus.READY,(
        Clause(0,0,7,'Merhaba',BreakKind.PAUSE,110,'continuation'),
        Clause(1,8,13,'dünya',BreakKind.FINAL,0,'statement')),(),())
    q=MockTTS(manager);assert (await q.enqueue(plan)).accepted
    b=MediaBuffer(manager);t=FakeTransport(adapter_id='m07-fake-pbx')
    media=MediaCoordinator(reducer,b,t)
    supervisor=AdapterSupervisor(manager,c,media=media)
    await supervisor.start_all()
    bridge=SyntheticStreamBridge(manager,c,supervisor.adapters[AdapterKind.TTS],q,b)
    assert (await bridge.submit_next_clause()).accepted
    await supervisor.tick_all();c.advance(20_000_000)
    first=(await supervisor.tick_all())[AdapterKind.TTS][0]
    first_media=await bridge.materialize_metadata(first)
    dispatched=await media.send_next(sid)
    assert first_media.accepted and dispatched.accepted
    assert (await bridge.submit_next_clause()).accepted
    await supervisor.tick_all() # second TTS generation now in-flight
    interrupted=await signal(SignalKind.VAD_SPEECH_STARTED)
    for e in interrupted.effects:
        if e.kind in (EffectKind.CANCEL_GENERATION,EffectKind.FLUSH_MEDIA):
            assert (await supervisor.dispatch_effect(e)).accepted
    c.advance(20_000_000)
    late=supervisor.adapters[AdapterKind.TTS].read_result('clause:m07-demo:1:1:1')
    assert late is not None and late.code is ResultCode.CANCELLED
    assert (await manager.snapshot(sid)).state.value=='INTERRUPTING'
    request=media._pending[sid]
    assert not t._confirmed
    # Explicit test-only acknowledgement; never auto-confirmed by supervisor.
    ack=await t.confirm_flush(sid,request.flush_request_id)
    ack_result=await media.accept_fake_ack(ack,sequence=await reducer.expected_sequence(sid),mono_ns=c.now_ns())
    assert ack_result.decision is Decision.APPLIED
    return {
        'adapter_states':{key:value.state.value for key,value in supervisor.health().items()},
        'initial_synthetic_metadata_sent':dispatched.accepted,
        'stale_tts_result':late.code.value,
        'flush_state_after_request':'INTERRUPTING',
        'explicit_fake_ack_applied':True,
        'final_state':ack_result.state.value,
        'actual_pbx_ack_proven':ack.real_pbx_proven,
        'audio_bytes_generated':0,
        'network_calls':0
    }

if __name__=='__main__':print(json.dumps(asyncio.run(main()),ensure_ascii=False,indent=2))
