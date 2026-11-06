"""Deterministic state-machine demo. No WAV or external data."""
import asyncio
from automotive_voice.core.session import Session,State
from automotive_voice.adapters.fake import FakeMediaOutput, FakeTTS

async def run():
    s = Session("synthetic-session-001")
    s.move(State.LISTENING)
    gen = s.new_turn()
    s.move(State.SPEAKING)
    out = FakeMediaOutput()
    async for chunk in FakeTTS().synthesize("Yarın müsaitliği kontrol ediyorum",gen):
        if s.accepts_chunk(chunk.generation_id):
            await out.enqueue(chunk)
    before = len(out.items)
    s.interrupt()
    await out.flush()
    stale = s.accepts_chunk(gen)
    s.move(State.LISTENING)
    s.move(State.ENDED)
    print({"simulation":True,"queued_before_interrupt":before,"queue_after_flush":len(out.items),"old_generation_accepted":stale,"final_state":s.state.value})

if __name__ == '__main__':
    asyncio.run(run())
