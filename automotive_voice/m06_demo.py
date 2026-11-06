"""M06 deterministic metadata-only barge-in demonstration."""
import asyncio
import json
from automotive_voice.audio import (AudioChunkMetadata, Codec, MediaFormat,
                                     MediaBuffer, MediaCoordinator)
from automotive_voice.telephony import FakeTransport
from automotive_voice.conversation import (ConversationReducer, ConversationSignal,
                                            SignalKind, Decision)
from automotive_voice.core.identifiers import SessionId,TurnId,GenerationId

async def main():
    r=ConversationReducer();sid='m06-demo'
    async def step(kind,ref=None):
        snap=await r.try_snapshot(sid)
        signal=ConversationSignal.create(kind,sid,int(snap.turn_id) if snap else 0,int(snap.generation_id) if snap else 0,
                        await r.expected_sequence(sid),reference=ref)
        return await r.handle(signal)
    await step(SignalKind.SESSION_OPENED)
    await step(SignalKind.TRANSCRIPT_FINAL,ref='transcript:1')
    await step(SignalKind.LLM_RESPONSE_READY,ref='response:1')
    q=MediaBuffer(r.manager);t=FakeTransport()
    coordinator=MediaCoordinator(r,q,t)
    frame=AudioChunkMetadata(SessionId(sid),TurnId(1),GenerationId(1),'tts-out',0,320,20,0,MediaFormat(Codec.PCM_S16LE,16000),0)
    assert (await q.enqueue(frame)).accepted
    delivered=await coordinator.send_next(sid)
    interrupted=await step(SignalKind.VAD_SPEECH_STARTED)
    request=await coordinator.request_flush(interrupted.effects[-1])
    stale=await q.enqueue(frame)
    ack=await t.confirm_flush(sid,request.flush_request_id)
    result=await coordinator.accept_fake_ack(ack,sequence=await r.expected_sequence(sid),mono_ns=10**20//1000)
    print(json.dumps({'accepted_mock_chunk':delivered.accepted,'stale_chunk_reason':stale.reason,
                      'flush_id':request.flush_request_id,'fake_ack_applied':result.decision==Decision.APPLIED,
                      'end_state':result.state.value,'real_audio_generated':False,
                      'actual_pbx_flush_proven':ack.real_pbx_proven},ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
