import asyncio
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base
import backend.session as module


async def test_stale_synthesis_cannot_play(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "session.db"))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(module, "Session", sessionmaker(engine, expire_on_commit=False))

    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(module.models, "vad", Vad())
    started = asyncio.Event()
    release = asyncio.Event()
    audio = []
    events = []

    async def synth(text):
        started.set()
        await release.wait()
        return np.ones(4800, np.float32) * 0.1

    async def emit(event):
        events.append(event)

    async def send(frame):
        audio.append(frame)

    monkeypatch.setattr(module.models, "synth", synth)
    session = module.VoiceSession("test", emit, send)
    task = asyncio.create_task(session.reply("Merhaba, yardımcı olayım."))
    await started.wait()
    session.generation += 1
    release.set()
    await task
    assert not audio
    await session.close()
    engine.dispose()


async def test_next_clause_prefetched_during_playback(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "prefetch.db"))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(module, "Session", sessionmaker(engine, expire_on_commit=False))

    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(module.models, "vad", Vad())
    generated = []
    second = asyncio.Event()

    async def synth(text):
        generated.append(text)
        if len(generated) == 2:
            second.set()
        return np.ones(4800, np.float32) * 0.1

    async def emit(event):
        pass

    async def send(frame):
        pass

    async def play(w, turn):
        await asyncio.wait_for(second.wait(), 1)

    monkeypatch.setattr(module.models, "synth", synth)
    session = module.VoiceSession("test", emit, send)
    monkeypatch.setattr(session, "play_wave", play)
    await session.reply("Merhaba. Nasıl yardımcı olabilirim?")
    assert len(generated) == 2
    await session.close()
    engine.dispose()
