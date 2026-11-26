import hashlib
from pathlib import Path
from uuid import uuid4
import pytest
from backend import milestones
from backend.models import Models
from automotive_voice.core.session import State


async def test_live_state_and_durable_events(tmp_path, monkeypatch):
    monkeypatch.setattr(milestones, "runtime_root", lambda: tmp_path)
    sid = str(uuid4())
    control = milestones.LiveControl(sid)
    first = await control.move("speaking")
    assert await control.accepts(int(first.generation_id))
    next_turn = await control.move("thinking")
    assert next_turn.state == State.THINKING
    assert not await control.accepts(int(first.generation_id))
    await control.move("speaking")
    await control.move("listening")
    await control.close()
    events = milestones.timeline(sid)
    assert [e["sequence"] for e in events] == list(range(len(events)))
    assert events[-1]["event_type"] == "session_ended"
    assert all("transport_ack" not in e["payload"] for e in events)


async def test_unclean_restart_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(milestones, "runtime_root", lambda: tmp_path)
    sid = str(uuid4())
    control = milestones.LiveControl(sid)
    await control.move("thinking")
    control.journal.close()
    assert await milestones.recover_abandoned() == 1
    assert milestones.timeline(sid)[-1]["payload"]["code"] == "unclean_restart"
    assert await milestones.recover_abandoned() == 0


def test_text_contract_does_not_fake_audio():
    result = milestones.inspect_text("Fiyat 1.250.000 TL.")
    assert not result["audio_generated"]
    assert "bir milyon iki yüz elli bin" in result["normalization"]["spoken_text"]
    assert result["plan"]["clause_count"] >= 1


def test_pronunciation_source_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(milestones, "runtime_root", lambda: tmp_path / "sessions")
    path = Path("data/a01yt/a01yt_v05_readonly.sqlite3")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    store = milestones.reviews()
    assert isinstance(store.items(), list)
    with pytest.raises(ValueError):
        store.decide(
            "missing", "approved", reviewer="test", reason_code="verified_evidence"
        )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


async def test_real_adapter_bridge_has_bounded_failure_budget(monkeypatch):
    models = Models()
    models.tts = object()
    calls = []

    # H01.10: _synth artık seed'i anahtar sözcükle alır; TypeError'da seed'siz yeniden deneme yok.
    def fail(text, seed=None):
        calls.append(text)
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(models, "_synth", fail)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await models.synth("Merhaba", seed=9)
    with pytest.raises(RuntimeError, match="beklemede"):
        await models.synth("Merhaba", seed=9)
    assert len(calls) == 3
