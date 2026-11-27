"""FreyaTTS Automotive Cockpit — F0–F6 Dürüst Telemetri ve Gecikme Ölçüm Testleri.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
"""

import asyncio
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db import Base, Turn
import backend.session as module
from backend.pipeline_telemetry import StageId


@pytest.fixture
def session_env(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "telemetry_honest.db"))
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(module, "Session", session_factory)

    class DummyVad:
        def __init__(self):
            self.count = 0

        def reset_states(self):
            pass

        def __call__(self, samples, sr=16000):
            self.count += 1
            # 2. çağrıdan sonra konuşma tespit edildiğini bildir
            return 0.95 if self.count >= 2 else 0.05

    monkeypatch.setattr(module.models, "vad", DummyVad())
    yield session_factory
    engine.dispose()


@pytest.mark.asyncio
async def test_voice_session_feed_generates_real_f0_and_f1_events(session_env, monkeypatch):
    events = []

    async def emit(ev):
        events.append(ev)

    async def send(frame):
        pass

    session = module.VoiceSession("test-feed-sess", emit, send)

    # 8 kHz SLIN16 ses parçası oluştur (0.1 saniye = 800 örnek = 1600 bayt)
    audio_pcm = (np.sin(np.linspace(0, 440 * 2 * np.pi * 0.1, 800)) * 16000).astype("<i2").tobytes()

    # 1. ve 2. blok besleme (VAD konuşmayı algılayacak)
    await session.input(audio_pcm, 8000)
    await session.input(audio_pcm, 8000)

    pipeline_events = [e["event"] for e in events if e.get("type") == "pipeline_event"]

    f0_events = [pe for pe in pipeline_events if pe["stage"] == "F0" and pe["status"] == "completed"]
    f1_events = [pe for pe in pipeline_events if pe["stage"] == "F1" and pe["status"] == "completed"]

    assert len(f0_events) >= 1
    assert len(f1_events) >= 1

    f0 = f0_events[0]
    assert f0["source"] == "live"
    assert f0["schema_version"] == "3.0"
    assert "duration_ms" in f0
    assert f0["duration_ms"] >= 0.0
    assert "metrics" in f0
    assert "rms" in f0["metrics"]
    assert "dbfs" in f0["metrics"]
    assert f0["metrics"]["resampled_rate"] == 16000

    f1 = f1_events[0]
    assert f1["source"] == "live"
    assert f1["schema_version"] == "3.0"
    assert "duration_ms" in f1
    assert f1["duration_ms"] >= 0.0
    assert f1["metrics"]["speech_detected"] is True

    await session.close()


@pytest.mark.asyncio
async def test_voice_session_process_generates_real_f2_and_f3_events(session_env, monkeypatch):
    events = []

    async def emit(ev):
        events.append(ev)

    async def send(frame):
        pass

    async def mock_transcribe(audio):
        await asyncio.sleep(0.01)  # Gerçek ölçülebilir süre
        return "Corolla için randevu istiyorum"

    async def mock_synth(text, seed=None):
        return np.ones(4800, np.float32) * 0.1

    monkeypatch.setattr(module.models, "transcribe", mock_transcribe)
    monkeypatch.setattr(module.models, "synth", mock_synth)

    session = module.VoiceSession("test-proc-sess", emit, send)

    audio_samples = np.ones(16000, dtype=np.float32) * 0.1
    await session.process(audio_samples)

    pipeline_events = [e["event"] for e in events if e.get("type") == "pipeline_event"]

    # F2: ASR
    f2_running = [pe for pe in pipeline_events if pe["stage"] == "F2" and pe["status"] == "running"]
    f2_completed = [pe for pe in pipeline_events if pe["stage"] == "F2" and pe["status"] == "completed"]
    assert len(f2_running) >= 1
    assert len(f2_completed) >= 1
    assert f2_completed[0]["duration_ms"] > 0
    assert f2_completed[0]["metrics"]["char_count"] == len("Corolla için randevu istiyorum")

    # F3: Supervisor & LLM / Niyet
    f3_running = [pe for pe in pipeline_events if pe["stage"] == "F3" and pe["status"] == "running"]
    f3_completed = [pe for pe in pipeline_events if pe["stage"] == "F3" and pe["status"] == "completed"]
    assert len(f3_running) >= 1
    assert len(f3_completed) >= 1
    assert f3_completed[0]["duration_ms"] > 0
    assert "llm_total_ms" in f3_completed[0]["metrics"]

    # WebSocket metrics mesajı gerçek alanları taşımalı
    metric_messages = [e for e in events if e.get("type") == "metrics"]
    assert len(metric_messages) >= 1
    assert any("stt_ms" in m and "llm_total_ms" in m for m in metric_messages)

    await session.close()


@pytest.mark.asyncio
async def test_voice_session_reply_generates_real_f4_f5_f6_events(session_env, monkeypatch):
    events = []

    async def emit(ev):
        events.append(ev)

    async def send(frame):
        pass

    async def mock_synth(text, seed=None):
        await asyncio.sleep(0.01)  # Gerçek ölçülebilir süre
        return np.ones(9600, np.float32) * 0.1

    monkeypatch.setattr(module.models, "synth", mock_synth)

    session = module.VoiceSession("test-reply-sess", emit, send)

    await session.reply("Randevunuz Maslak Merkezimizde oluşturuldu. Teşekkür ederiz.")

    pipeline_events = [e["event"] for e in events if e.get("type") == "pipeline_event"]

    # F4: Normalizasyon ve Cümlecik Bölme
    f4_comp = [pe for pe in pipeline_events if pe["stage"] == "F4" and pe["status"] == "completed"]
    assert len(f4_comp) >= 1
    assert f4_comp[0]["duration_ms"] >= 0.0
    assert f4_comp[0]["metrics"]["chunks_count"] >= 1

    # F5: FreyaTTS Akustik Sentez
    f5_comp = [pe for pe in pipeline_events if pe["stage"] == "F5" and pe["status"] == "completed"]
    assert len(f5_comp) >= 1
    assert f5_comp[0]["duration_ms"] >= 0.0
    assert f5_comp[0]["metrics"]["ttfa_ms"] >= 0.0
    assert "persona" in f5_comp[0]["metrics"]

    # F6: Ses İletimi
    f6_comp = [pe for pe in pipeline_events if pe["stage"] == "F6" and pe["status"] == "completed"]
    assert len(f6_comp) >= 1
    assert f6_comp[0]["duration_ms"] >= 0.0
    assert f6_comp[0]["metrics"]["audio_bytes"] > 0

    await session.close()


@pytest.mark.asyncio
async def test_handle_text_input_honesty_no_fake_defaults(session_env, monkeypatch):
    events = []

    async def emit(ev):
        events.append(ev)

    async def send(frame):
        pass

    async def mock_synth(text, seed=None):
        return np.ones(4800, np.float32) * 0.1

    monkeypatch.setattr(module.models, "synth", mock_synth)

    session = module.VoiceSession("test-text-honesty-sess", emit, send)

    await session.handle_text_input("Bakım randevusu almak istiyorum")

    pipeline_events = [e["event"] for e in events if e.get("type") == "pipeline_event"]

    # F0-F2 bypassed
    for stage in ("F0", "F1", "F2"):
        pe = next(p for p in pipeline_events if p["stage"] == stage)
        assert pe["status"] == "bypassed"
        assert pe["duration_ms"] == 0.0
        assert pe["source"] == "text_input"

    # F3 completed
    f3_pe = next(p for p in pipeline_events if p["stage"] == "F3" and p["status"] == "completed")
    assert f3_pe["source"] == "text_input"
    assert f3_pe["duration_ms"] >= 0.0

    # Metrik mesajı
    metrics_msg = next(e for e in events if e.get("type") == "metrics")
    assert metrics_msg["stt_ms"] == 0
    if "llm_total_ms" in metrics_msg:
        assert metrics_msg["llm_total_ms"] >= 0.0
    if "llm_first_token_ms" in metrics_msg:
        assert metrics_msg["llm_first_token_ms"] >= 0.0

    # F4-F6 completed with text_input source
    for stage in ("F4", "F5", "F6"):
        pe = next(p for p in pipeline_events if p["stage"] == stage and p["status"] == "completed")
        assert pe["source"] == "text_input"
        assert pe["duration_ms"] >= 0.0

    await session.close()
