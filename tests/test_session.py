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


async def test_call_and_tts_events_feed_dashboard_metrics(tmp_path, monkeypatch):
    """Gerçek çağrı başlangıç/bitişi ve cümle başına TTS ölçümü panel toplayıcısına yazılır."""
    from backend.realtime_dashboard_metrics import RealtimeDashboardMetricsCollector

    engine = create_engine("sqlite:///" + str(tmp_path / "metrics.db"))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(module, "Session", sessionmaker(engine, expire_on_commit=False))

    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(module.models, "vad", Vad())
    collector = RealtimeDashboardMetricsCollector()
    monkeypatch.setattr(module, "_metrics", lambda: collector)

    async def synth(text):
        await asyncio.sleep(0.05)  # ölçülebilir sentez süresi
        return np.ones(4800, np.float32) * 0.1

    async def emit(event):
        pass

    async def send(frame):
        pass

    async def play(w, turn):
        pass

    monkeypatch.setattr(module.models, "synth", synth)
    session = module.VoiceSession("test", emit, send, mode="outbound")
    monkeypatch.setattr(session, "play_wave", play)
    assert collector.active_calls == 1 and collector.total_calls_outbound == 1
    assert collector.get_latency_percentiles()["p95"] is None  # sentez öncesi ölçüm yok

    await session.reply("Merhaba.")
    assert collector.get_latency_percentiles()["p95"] is not None
    assert collector.tts_rtf_ema is not None

    await session.close()
    await session.close()  # ikinci close sayacı bozmaz
    assert collector.active_calls == 0
    assert collector.total_calls_completed == 1
    engine.dispose()
