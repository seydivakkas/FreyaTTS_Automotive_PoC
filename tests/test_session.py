import asyncio
from importlib.resources import files

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base, Turn
import backend.session as module


async def test_silero_state_is_isolated_across_interleaved_sessions(monkeypatch):
    torch = pytest.importorskip("torch")
    pytest.importorskip("silero_vad")
    thread_count = torch.get_num_threads()
    torch.set_num_threads(1)

    async def discard(_):
        pass

    try:
        with files("silero_vad.data").joinpath("silero_vad.jit").open("rb") as artifact:
            template = torch.jit.load(artifact, map_location="cpu").eval()
        monkeypatch.setattr(module.models, "vad", template)
        rng = np.random.default_rng(42)
        for count in (2, 4, 8):
            streams = [
                torch.from_numpy(rng.normal(0, 0.03 * (index + 1), (8, 512)).astype(np.float32))
                for index in range(count)
            ]
            actual = [[] for _ in streams]
            sessions = []
            try:
                with torch.inference_mode():
                    expected = []
                    for blocks in streams:
                        detector = module.models.new_vad()
                        expected.append([float(detector(block, 16000)) for block in blocks])
                    for step in range(8):
                        if step in (0, 4):
                            for _ in range(count // 2):
                                sessions.append(module.VoiceSession("test", discard, discard))
                        for index, session in enumerate(sessions):
                            offset = 0 if index < count // 2 else 4
                            probability = session.endpoint.model(streams[index][step - offset], 16000)
                            actual[index].append(float(probability))
                for observed, isolated in zip(actual, expected):
                    np.testing.assert_allclose(observed, isolated[:len(observed)], atol=1e-6, rtol=0)
            finally:
                for session in sessions:
                    await session.close()
        assert template._state.numel() == 0
    finally:
        torch.set_num_threads(thread_count)


async def test_calibration_keeps_speech_on_transcription_path(monkeypatch):
    class Vad:
        def reset_states(self):
            pass

    class Endpoint:
        active = False
        last_voice_at = None

        def feed(self, samples):
            assert len(samples) > 0
            if not self.active:
                self.active = True
                return True, []
            self.active = False
            return False, [samples]

    async def discard(_):
        pass

    monkeypatch.setattr(module.models, "vad", Vad())
    session = module.VoiceSession("test", discard, discard)
    session.endpoint = Endpoint()
    session.is_calibrating = True
    session.car_denoiser.start_calibration()
    forwarded = []

    async def process(audio, speech_end):
        forwarded.append(audio)

    monkeypatch.setattr(session, "process", process)
    try:
        audio = np.full(1600, 1000, dtype="<i2").tobytes()
        await session.input(audio, 16000)
        await session.input(audio, 16000)
        await asyncio.wait_for(session.task, timeout=1)
        assert len(forwarded) == 1
        assert session.is_calibrating
        assert session.car_denoiser._calib_frames == []
    finally:
        await session.close()


async def test_reply_preserves_transcript_and_speaks_compatible_characters(monkeypatch):
    class Vad:
        def reset_states(self):
            pass

    events = []
    synthesized = []
    frames = []

    async def emit(event):
        events.append(event)

    async def send(frame):
        frames.append(frame)

    async def synth(text, *, seed):
        synthesized.append(text)
        return np.ones(4800, dtype=np.float32) * 0.1

    monkeypatch.setattr(module.models, "vad", Vad())
    monkeypatch.setattr(module.models, "synth", synth)
    session = module.VoiceSession("test", emit, send)
    try:
        text = "Mégane 🚗 için dış sıcaklık −5 °C."
        await session.reply(text)
        assert any(e.get("type") == "transcript" and e.get("text") == text for e in events)
        assert synthesized == ["Megaan için dış sıcaklık eksi beş derece santigrat."]
        assert frames
    finally:
        await session.close()


async def test_completed_sections_merge_while_first_transcription_is_pending(monkeypatch):
    class Vad:
        def reset_states(self):
            pass

    first = np.ones(512, dtype=np.float32)
    second = np.full(512, 2, dtype=np.float32)
    stt_started = asyncio.Event()
    release_stt = asyncio.Event()
    stt_calls = []
    received = []

    async def discard(*args):
        pass

    async def transcribe(audio):
        stt_calls.append(audio.copy())
        if len(stt_calls) == 1:
            stt_started.set()
            await release_stt.wait()
            return "Benim aracım"
        np.testing.assert_array_equal(audio, np.concatenate([first, second]))
        return "Benim aracım 2021 model Passat"

    async def answer(text):
        received.append(text)
        return "Anladım."

    monkeypatch.setattr(module.models, "vad", Vad())
    monkeypatch.setattr(module.models, "transcribe", transcribe)
    session = module.VoiceSession("test", discard, discard)
    monkeypatch.setattr(session.dialogue, "answer", answer)
    monkeypatch.setattr(session, "reply", discard)
    sections = iter((first, second))
    monkeypatch.setattr(session.endpoint, "feed", lambda samples: (False, [next(sections)]))
    pcm = bytes(3200)
    try:
        await session.input(pcm, 16000)
        await asyncio.wait_for(stt_started.wait(), timeout=1)
        task = session.task
        await session.input(pcm, 16000)
        assert session.task is task
        release_stt.set()
        await asyncio.wait_for(task, timeout=1)
        assert len(stt_calls) == 2
        assert received == ["Benim aracım 2021 model Passat"]
    finally:
        release_stt.set()
        await session.close()


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

    async def synth(text, *, seed=None):
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

    async def synth(text, *, seed=None):
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

    async def synth(text, *, seed=None):
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


async def test_handle_text_input_emits_bypassed_and_f3_pipeline_events(tmp_path, monkeypatch):
    """Metin girdisi F0-F2 bypassed telemetrisi ve F3-F6 text_input kaynağı üretir."""
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


async def test_dialogue_state_event_emitted_for_cockpit_card(tmp_path, monkeypatch):
    """Metin girdisi veya sesli dönüşte kokpitteki 5-soruluk işlem kartı için dialogue_state eventi yayılır."""
    engine = create_engine("sqlite:///" + str(tmp_path / "card_state.db"))
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(module, "Session", session_factory)
    import backend.dialogue as diag_mod
    monkeypatch.setattr(diag_mod, "Session", session_factory)

    from backend.db import Vehicle, Slot
    with session_factory() as db:
        v = Vehicle(plate="34 ABC 123", description="Volkswagen Passat")
        db.add(v)
        s = Slot(starts_at="2099-01-01T09:00:00Z")
        db.add(s)
        db.commit()

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
    session = module.VoiceSession("test-card-state", emit, send)

    await session.handle_text_input("34 ABC 123 plakalı Passat için randevu istiyorum")

    card_events = [e for e in events if e.get("type") == "dialogue_state"]
    assert len(card_events) >= 1
    state_payload = card_events[-1]["data"]
    assert "state" in state_payload
    assert "plate" in state_payload
    assert "customer" in state_payload
    assert "vehicle" in state_payload
    assert "slot_id" in state_payload
    assert "appointment_id" in state_payload
    assert "transfer_requested" in state_payload

    await session.close()
    engine.dispose()

