import asyncio
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base, Turn
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

    async def synth(text, seed=None):  # H01.10: seed anahtar sözcükle gelir
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

    async def synth(text, seed=None):  # H01.10: seed anahtar sözcükle gelir
        generated.append(text)
        if len(generated) == 2:
            second.set()
        return np.ones(4800, np.float32) * 0.1

    async def emit(event):
        pass

    async def send(frame):
        pass

    async def play(w, turn, source="live"):  # H01.10: TypeError yedek çalma kaldırıldı
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

    async def synth(text, seed=None):  # H01.10: seed anahtar sözcükle gelir
        await asyncio.sleep(0.05)  # ölçülebilir sentez süresi
        return np.ones(4800, np.float32) * 0.1

    async def emit(event):
        pass

    async def send(frame):
        pass

    async def play(w, turn, source="live"):  # H01.10: TypeError yedek çalma kaldırıldı
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


async def test_handle_text_input_emits_bypassed_and_f3_pipeline_events(tmp_path, monkeypatch, fake_llm):
    """Metin girdisi F0-F2 bypassed telemetrisi ve F3-F6 text_input kaynağı üretir."""
    # H01.01: canlı Ollama yerine SAHTE LLM yanıtı (tests/fakes/fake_llm.py); ağ çağrısı yok.
    fake_llm.reply({})
    engine = create_engine("sqlite:///" + str(tmp_path / "text_telemetry.db"))
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(module, "Session", session_factory)

    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(module.models, "vad", Vad())
    events = []

    async def emit(event):
        events.append(event)

    async def send(frame):
        pass

    async def synth(text, seed=None):
        return np.ones(4800, np.float32) * 0.1

    monkeypatch.setattr(module.models, "synth", synth)
    session = module.VoiceSession("test-text-session", emit, send)

    # Text input
    await session.handle_text_input("Bakım randevusu almak istiyorum")

    # Pipeline events kontrolü
    pipeline_events = [e["event"] for e in events if e.get("type") == "pipeline_event"]
    assert any(pe["stage"] == "F0" and pe["status"] == "bypassed" and pe["source"] == "text_input" for pe in pipeline_events)
    assert any(pe["stage"] == "F1" and pe["status"] == "bypassed" and pe["source"] == "text_input" for pe in pipeline_events)
    assert any(pe["stage"] == "F2" and pe["status"] == "bypassed" and pe["source"] == "text_input" for pe in pipeline_events)
    assert any(pe["stage"] == "F3" and pe["status"] == "completed" and pe["source"] == "text_input" for pe in pipeline_events)
    assert any(pe["stage"] == "F4" and pe["status"] == "completed" and pe["source"] == "text_input" for pe in pipeline_events)
    assert any(pe["stage"] == "F5" and pe["status"] == "completed" and pe["source"] == "text_input" for pe in pipeline_events)
    assert any(pe["stage"] == "F6" and pe["status"] == "completed" and pe["source"] == "text_input" for pe in pipeline_events)

    # Veritabanı Turn kontrolü
    with session_factory() as db:
        user_turn = db.query(Turn).filter_by(role="user").first()
        assert user_turn is not None
        assert "text_input" in user_turn.metrics

    await session.close()
    engine.dispose()


async def test_handle_text_input_barge_in_and_task_cancellation(tmp_path, monkeypatch):
    """Metin girdisi devam eden ses çalmayı flush eder ve arka plan görevini iptal eder."""
    engine = create_engine("sqlite:///" + str(tmp_path / "barge_in.db"))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(module, "Session", sessionmaker(engine, expire_on_commit=False))

    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(module.models, "vad", Vad())
    events = []

    async def emit(event):
        events.append(event)

    async def send(frame):
        pass

    session = module.VoiceSession("test-barge-session", emit, send)
    session.playing = True

    # Simüle edilmiş arka plan görevi
    async def dummy_bg():
        await asyncio.sleep(10)

    bg_task = asyncio.create_task(dummy_bg())
    session.task = bg_task

    await session.handle_text_input("Durun bir dakika")

    # Flush eventi kontrolü
    assert any(e.get("type") == "playback" and e.get("action") == "flush" for e in events)
    # Arka plan görevi iptal edilmiş olmalı
    assert bg_task.cancelled() or bg_task.done()

    await session.close()
    engine.dispose()
