"""Mock M02 demonstration. No microphone, video, Freya model, SIP or remote calls."""
import asyncio
from automotive_voice.conversation import ConversationReducer, ConversationSignal, SignalKind
from automotive_voice.core.session import State


async def main():
    reducer = ConversationReducer(flush_timeout_ms=1500)
    session_id = 'm02-local-demo'

    async def send(kind, ref=None, flush=None):
        snap = await reducer.try_snapshot(session_id)
        event = ConversationSignal.create(
            kind, session_id, int(snap.turn_id) if snap else 0,
            int(snap.generation_id) if snap else 0,
            await reducer.expected_sequence(session_id),
            reference=ref, flush_request_id=flush)
        out = await reducer.handle(event)
        print(f'{kind.value:22s} => {out.state.value if out.state else None:14s}'
              f' / {out.reason:24s} / effects={[e.kind.value for e in out.effects]}')
        return out

    await send(SignalKind.SESSION_OPENED)
    await send(SignalKind.VAD_SPEECH_STARTED)
    await send(SignalKind.TRANSCRIPT_FINAL,'transcript:001')
    await send(SignalKind.LLM_RESPONSE_READY,'response:001')
    await send(SignalKind.AUDIO_CHUNK_READY,'audio:001')
    interrupted = await send(SignalKind.VAD_SPEECH_STARTED)
    await send(SignalKind.TRANSCRIPT_FINAL,'transcript:002')
    await send(SignalKind.MEDIA_FLUSH_ACK,flush=interrupted.effects[-1].effect_id)
    await send(SignalKind.LLM_RESPONSE_READY,'response:002')
    await send(SignalKind.PLAYOUT_FINISHED)
    await send(SignalKind.HANGUP)
    final = await reducer.manager.snapshot(session_id)
    assert final.state == State.ENDED
    events = await reducer.manager.dispatch_pending(session_id)
    print(f'M01 published: {events}; audit entries: {len(await reducer.audit_records(session_id))}')
    print('Demo uses only synthetic references; no real audio or customer data.')

if __name__ == '__main__':
    asyncio.run(main())
