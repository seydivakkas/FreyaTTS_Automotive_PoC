"""Tests for Hybrid DTMF Keypad Routing and 8/16 kHz Goertzel DSP.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from datetime import datetime, timezone, timedelta
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.db import (
    Base,
    Vehicle,
    Slot,
    Quote,
    Appointment,
    OutboundCall,
)
from backend import main
from backend.dtmf import (
    DTMF_MATRIX,
    GoertzelDetector,
    generate_dtmf_tone,
    format_stt_fallback_message,
)
from backend.dialogue import Dialogue


@pytest.fixture
def dtmf_setup(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "dtmf_test.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sm = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(main, "Session", sm)
    monkeypatch.setattr("backend.db.Session", sm)
    monkeypatch.setattr("backend.session.Session", sm)
    monkeypatch.setattr("backend.dialogue.Session", sm)
    monkeypatch.setattr(main.settings, "admin_password", "test-pass")

    client = TestClient(main.app)
    yield client, sm, tmp_path
    client.close()
    engine.dispose()


def test_goertzel_detector_all_16_digits():
    """Tüm 16 DTMF tuşunun (0-9, *, #, A-D) Goertzel algoritmasıyla doğru tanındığını test eder."""
    detector = GoertzelDetector(sample_rate=16000)
    all_digits = list("1234567890*#ABCD")

    for digit in all_digits:
        # 60 ms tone (3 frames @ 20ms) followed by 40 ms silence for clean debounce
        tone = generate_dtmf_tone(digit, duration_sec=0.06, sample_rate=16000)
        silence = np.zeros(int(16000 * 0.04), dtype=np.float32)
        stream = np.concatenate([tone, silence])

        detected, cleaned = detector.process_samples(stream)
        assert len(detected) == 1, f"Tuş {digit} için tek tespit bekleniyordu, alınan: {detected}"
        assert detected[0] == digit, f"Beklenen tuş: {digit}, tespit edilen: {detected[0]}"


def test_goertzel_noise_and_silence_rejection():
    """Sessizlik, beyaz gürültü ve tek frekanslı tonların yanlış DTMF tetiklemediğini doğrular."""
    detector = GoertzelDetector(sample_rate=16000)

    # 1. Pure silence
    silence = np.zeros(16000, dtype=np.float32)
    det, _ = detector.process_samples(silence)
    assert len(det) == 0

    # 2. Gaussian random noise
    np.random.seed(42)
    noise = (np.random.randn(16000) * 0.05).astype(np.float32)
    det, _ = detector.process_samples(noise)
    assert len(det) == 0

    # 3. Single tone (1000 Hz pure sine wave - not dual tone)
    t = np.arange(8000) / 16000.0
    single_tone = (0.5 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)
    det, _ = detector.process_samples(single_tone)
    assert len(det) == 0


def test_dtmf_audio_notch_suppression():
    """Algılanan DTMF tonunun Whisper STT'ye gitmeden önce sessizleştirildiğini (notch/mute) doğrular."""
    detector = GoertzelDetector(sample_rate=16000)
    tone = generate_dtmf_tone("1", duration_sec=0.06, sample_rate=16000)

    # Before processing, energy is non-zero
    initial_energy = float(np.sum(tone ** 2))
    assert initial_energy > 1.0

    detected, cleaned = detector.process_samples(tone)
    assert "1" in detected
    # Cleaned audio must have DTMF portions muted to 0
    cleaned_energy = float(np.sum(cleaned ** 2))
    assert cleaned_energy == 0.0


@pytest.mark.asyncio
async def test_dialogue_dtmf_awaiting_confirmation(dtmf_setup):
    client, SessionLocal, tmp_path = dtmf_setup

    now_utc = datetime.now(timezone.utc)
    slot_time = (now_utc + timedelta(days=2)).isoformat()

    with SessionLocal() as db:
        v = Vehicle(description="Toyota Corolla 1.5 Vision", plate="34 TYT 55")
        db.add(v)
        db.flush()
        s = Slot(starts_at=slot_time)
        db.add(s)
        db.commit()

        d = Dialogue(conversation_id="conv-dtmf-confirm")
        d.customer = "Mehmet Bey"
        d.vehicle = v.id
        d.slot = s.id
        d.awaiting = True

        # Tuş 1: Anında Onayla (Zero LLM latency)
        ans1 = await d.handle_dtmf("1", db)
        assert "1'i tuşladınız" in ans1
        assert "onaylandı ve oluşturuldu" in ans1
        assert d.done is True
        assert d.booking_status.value == "confirmed"

        # Verify booked appointment in DB
        app = db.scalars(select(Appointment).where(Appointment.idempotency_key == d.id)).first()
        assert app is not None
        assert app.customer == "Mehmet Bey"

        # Tuş 2: Onaylama / Saati Değiştir
        d2 = Dialogue(conversation_id="conv-dtmf-cancel")
        d2.customer = "Ayşe Hanım"
        d2.vehicle = v.id
        d2.slot = s.id
        d2.awaiting = True

        ans2 = await d2.handle_dtmf("2", db)
        assert "2'yi tuşladınız" in ans2
        assert "Randevu onaylanmadı" in ans2
        assert d2.awaiting is False
        assert d2.slot is None

        # Tuş 0: Operatöre Aktar
        d0 = Dialogue(conversation_id="conv-dtmf-op")
        ans0 = await d0.handle_dtmf("0", db)
        assert "0'ı tuşladınız" in ans0
        assert "danışmanımıza aktarıyorum" in ans0
        assert d0.done is True


@pytest.mark.asyncio
async def test_dialogue_dtmf_slot_selection(dtmf_setup):
    client, SessionLocal, tmp_path = dtmf_setup

    d = Dialogue(conversation_id="conv-dtmf-options")
    d.options = [
        ("slot-uuid-1", "05.11.2026 saat 10:00"),
        ("slot-uuid-2", "05.11.2026 saat 14:00"),
    ]

    with SessionLocal() as db:
        # Tuş 2: 2. Seçeneği Seç
        ans = await d.handle_dtmf("2", db)
        assert "2. seçeneği seçtiniz" in ans
        assert "14:00" in ans
        assert "Onaylamak için 1'i" in ans
        assert d.awaiting is True
        assert d.slot == "slot-uuid-2"


@pytest.mark.asyncio
async def test_dialogue_dtmf_outbound_reminder(dtmf_setup):
    client, SessionLocal, tmp_path = dtmf_setup

    with SessionLocal() as db:
        call = OutboundCall(
            phone="05321112233",
            customer="Ali Bey",
            appointment_id="app-1",
            call_type="reminder",
        )
        db.add(call)
        db.commit()

        d = Dialogue(conversation_id="conv-dtmf-outbound", mode="outbound_reminder", call_id=call.id)
        ans = await d.handle_dtmf("1", db)
        assert "1'i tuşladınız" in ans
        assert "teyit edildi" in ans
        assert d.outbound_outcome == "confirmed"
        assert d.done is True

        db.refresh(call)
        assert call.outcome == "confirmed"


def test_stt_fallback_prompt_on_consecutive_errors():
    d = Dialogue(conversation_id="conv-fallback")
    d.awaiting = True

    msg = format_stt_fallback_message(d)
    assert "onaylamak için 1'i" in msg
    assert "müşteri temsilcimize bağlanmak için 0'ı" in msg

    # Trigger unclear retry
    d.retries = 1
    fallback_response = d.unclear()
    assert "onaylamak için 1'i" in fallback_response
    assert d.retries == 2


@pytest.mark.asyncio
async def test_voice_session_dtmf_handling(tmp_path, monkeypatch):
    from backend import session as session_mod

    engine = create_engine("sqlite:///" + str(tmp_path / "session_dtmf.db"))
    Base.metadata.create_all(engine)
    sm = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_mod, "Session", sm)

    class MockVad:
        def reset_states(self):
            pass

    monkeypatch.setattr(session_mod.models, "vad", MockVad())

    async def mock_synth(text, seed=9):
        return np.zeros(4800, dtype=np.float32)

    monkeypatch.setattr(session_mod.models, "synth", mock_synth)

    events = []
    frames = []

    async def emit(ev):
        events.append(ev)

    async def send(fr):
        frames.append(fr)

    sess = session_mod.VoiceSession("web", emit, send)
    sess.dialogue.awaiting = False

    # Simulate DTMF 0 keypress
    await sess.handle_dtmf("0")

    # Check event emission
    dtmf_ev = next((e for e in events if e.get("type") == "dtmf_received"), None)
    assert dtmf_ev is not None
    assert dtmf_ev["digit"] == "0"

    # Check transcript
    tr_ev = next((e for e in events if e.get("type") == "transcript" and "[DTMF: 0]" in e.get("text", "")), None)
    assert tr_ev is not None

    await sess.close()
    engine.dispose()


def test_dtmf_generate_tone_api(dtmf_setup):
    client, SessionLocal, tmp_path = dtmf_setup
    auth = ("admin", "test-pass")

    resp = client.post("/api/dtmf/generate-tone", auth=auth, json={"digit": "5"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert len(resp.content) > 100
