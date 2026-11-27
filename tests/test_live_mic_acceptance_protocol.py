"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import backend.acceptance_protocol as acc_mod
import backend.db as db_mod
import backend.dialogue as diag_mod
import backend.session as sess_mod
from backend.config import settings
from backend.db import Appointment, Base, Turn, Vehicle
from backend.main import app


@pytest.fixture
def isolated_acceptance_env(tmp_path, monkeypatch):
    """Canlı mikrofon kabul protokolü için tamamen yalıtılmış DB + data_dir + dummy ses ortamı kurar."""
    db_file = tmp_path / "acceptance.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine("sqlite:///" + db_file.as_posix())
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "Session", factory)
    monkeypatch.setattr(sess_mod, "Session", factory)
    monkeypatch.setattr(diag_mod, "Session", factory)
    monkeypatch.setattr(acc_mod.settings, "data_dir", str(data_dir))
    monkeypatch.setattr(settings, "data_dir", str(data_dir))
    monkeypatch.setattr(settings, "demo_mode", False)

    class DummyVad:
        def reset_states(self):
            pass

    async def dummy_synth(text, seed=None):
        sess_mod.models.synth_count += 1
        await asyncio.sleep(0.002)
        return np.ones(4800, np.float32) * 0.08

    monkeypatch.setattr(sess_mod.models, "vad", DummyVad())
    monkeypatch.setattr(sess_mod.models, "synth", dummy_synth)
    monkeypatch.setattr(sess_mod.models, "synth_count", 0)

    yield {
        "factory": factory,
        "db_file": db_file,
        "data_dir": data_dir,
        "engine": engine,
    }
    engine.dispose()


async def _drive_voice_turns(monkeypatch, utterances: list[str], *, channel: str = "web_mic"):
    """VoiceSession.process() üzerinden gerçek F2->F2B->F3->F4->F5 boru hattını sürer."""
    idx = {"i": 0}
    events: list[dict] = []

    async def scripted_transcribe(audio):
        i = idx["i"]
        idx["i"] += 1
        return utterances[i] if i < len(utterances) else ""

    async def emit(ev):
        events.append(ev)

    async def send(frame):
        pass

    monkeypatch.setattr(sess_mod.models, "transcribe", scripted_transcribe)
    monkeypatch.setattr(sess_mod.models, "synth_count", 0)

    session = sess_mod.VoiceSession(channel, emit, send)
    audio_samples = np.ones(16000, dtype=np.float32) * 0.1
    for _ in utterances:
        await session.process(audio_samples)

    await session.close()
    return events


def test_prepare_poc_acceptance_fixtures_is_idempotent(isolated_acceptance_env):
    factory = isolated_acceptance_env["factory"]
    with factory() as db:
        p1 = acc_mod.prepare_poc_acceptance_fixtures(db)
        p2 = acc_mod.prepare_poc_acceptance_fixtures(db, reset_existing=True)

        assert p1["prepared"] is True
        assert p1["vehicle"]["quote_kurus"] == 250000
        assert p2["prepared"] is True

        corollas = db.scalars(select(Vehicle).where(Vehicle.description.ilike("%corolla%"))).all()
        assert len(corollas) == 1

        prereqs = acc_mod.get_prerequisites_status(db)
        assert prereqs["database"]["has_poc_corolla"] is True
        assert prereqs["database"]["has_poc_quote"] is True
        assert prereqs["database"]["occupied_future_slots_count"] >= 1
        assert prereqs["database"]["open_future_slots_count"] >= 1
        assert prereqs["database"]["poc_fixture_ready"] is True


@pytest.mark.asyncio
async def test_run_1_plate_correction_pass_end_to_end(isolated_acceptance_env, monkeypatch):
    factory = isolated_acceptance_env["factory"]
    with factory() as db:
        acc_mod.prepare_poc_acceptance_fixtures(db)
        run = acc_mod.start_acceptance_run(
            db,
            scenario_id="run_1_plate_correction",
            speaker_label="Seydi",
            environment="quiet_room",
            notes="Otomatik Koşu 1 testi",
        )

    events = await _drive_voice_turns(
        monkeypatch,
        [
            "Korola için yarın sabah ekspertiz randevusu istiyorum.",
            "Otuz dört Adana Bursa Ceyhan yüz yirmi üç.",
            "C değil, Denizli'nin D'si.",
            "Evet, onaylıyorum.",
        ],
    )

    dialogue_states = [e["data"] for e in events if e.get("type") == "dialogue_state"]
    assert len(dialogue_states) == 4
    final_state = dialogue_states[-1]
    assert final_state["booking_status"] == "confirmed"
    assert final_state["plate"] == "34 ABD 123"
    assert final_state["vehicle"] == "Toyota Corolla"
    assert final_state["reference_code"] and final_state["reference_code"].startswith("FRY-")
    assert final_state["eos_to_first_audio_ms"] is not None

    with factory() as db:
        report = acc_mod.finish_and_verify_run(db, run["run_id"])

    assert report["status"] == "PASS"
    assert report["checks"]["single_appointment_created"] is True
    assert report["checks"]["final_plate_matches_expected"] is True
    assert report["checks"]["reference_matches_spoken"] is True
    assert report["checks"]["zero_preconfirm_mutations"] is True
    assert report["diff"]["net_new_appointments"] == 1
    assert report["diff"]["new_appointments"][0]["plate"] == "34 ABD 123"
    assert report["diff"]["new_appointments"][0]["reference_code"] == final_state["reference_code"]
    assert report["latency_summary"]["cold_eos_to_first_audio"] is not None
    assert report["latency_summary"]["warm_eos_to_first_audio"] is not None
    for layer in ("F0_F1_AUDIO_VAD", "F2_ASR_STT", "F2B_PLATE_TERMINOLOGY", "F3_DIALOGUE_POLICY", "F4_F5_TTS", "DB_CALENDAR"):
        assert report["layer_diagnostics"][layer]["status"] == "PASS"


@pytest.mark.asyncio
async def test_run_2_early_confirm_and_abort_creates_zero_appointments(isolated_acceptance_env, monkeypatch):
    factory = isolated_acceptance_env["factory"]
    with factory() as db:
        acc_mod.prepare_poc_acceptance_fixtures(db)
        run = acc_mod.start_acceptance_run(
            db,
            scenario_id="run_2_early_confirm_abort",
            speaker_label="Seydi",
            environment="quiet_room",
        )

    await _drive_voice_turns(
        monkeypatch,
        [
            "Corolla için yarın sabah ekspertiz randevusu istiyorum.",
            "Otuz dört Adana Bursa Ceyhan yüz yirmi üç.",
            "Evet, sizi duyuyorum.",
            "Vazgeçtim.",
        ],
    )

    with factory() as db:
        report = acc_mod.finish_and_verify_run(db, run["run_id"])

    assert report["status"] == "PASS"
    assert report["checks"]["zero_appointments_created"] is True
    assert report["checks"]["zero_preconfirm_mutations"] is True
    assert report["checks"]["early_or_abort_uttered"] is True
    assert report["diff"]["net_new_appointments"] == 0
    assert report["layer_diagnostics"]["F3_DIALOGUE_POLICY"]["status"] == "PASS"
    assert report["layer_diagnostics"]["DB_CALENDAR"]["status"] == "PASS"


@pytest.mark.asyncio
async def test_run_3_natural_idempotency_double_confirm_single_booking(isolated_acceptance_env, monkeypatch):
    factory = isolated_acceptance_env["factory"]
    with factory() as db:
        acc_mod.prepare_poc_acceptance_fixtures(db)
        run = acc_mod.start_acceptance_run(
            db,
            scenario_id="run_3_natural_idempotency",
            speaker_label="Seydi",
            environment="in_car_noise",
        )

    await _drive_voice_turns(
        monkeypatch,
        [
            "Selamlar, elimde bir Korola var yarın sabah baksanız olur mu?",
            "Plakam otuz dört ABC yüz yirmi üç.",
            "Evet, onaylıyorum.",
            "Evet, onaylıyorum.",
        ],
    )

    with factory() as db:
        report = acc_mod.finish_and_verify_run(db, run["run_id"])

    assert report["status"] == "PASS"
    assert report["checks"]["single_appointment_created"] is True
    assert report["checks"]["repeated_confirm_idempotent"] is True
    assert report["diff"]["net_new_appointments"] == 1
    assert "34 ABC 123" in report["diff"]["plates_seen"]


@pytest.mark.asyncio
async def test_incomplete_and_fail_layer_diagnostics_and_kvkk_masking(isolated_acceptance_env, monkeypatch):
    factory = isolated_acceptance_env["factory"]
    with factory() as db:
        acc_mod.prepare_poc_acceptance_fixtures(db)
        empty_run = acc_mod.start_acceptance_run(db, scenario_id="run_1_plate_correction")
        incomplete_report = acc_mod.finish_and_verify_run(db, empty_run["run_id"])

    assert incomplete_report["status"] == "INCOMPLETE"
    assert incomplete_report["checks"]["has_user_turns"] is False
    assert incomplete_report["layer_diagnostics"]["F2_ASR_STT"]["status"] == "NOT_RUN"

    # Şimdi yanlış plaka (34 ABC 123, düzeltilmemiş) ile bitir -> F2B FAIL raporlanmalı
    with factory() as db:
        fail_run = acc_mod.start_acceptance_run(db, scenario_id="run_1_plate_correction")

    await _drive_voice_turns(
        monkeypatch,
        [
            "Corolla için yarın sabah ekspertiz istiyorum.",
            "Otuz dört Adana Bursa Ceyhan yüz yirmi üç.",
            "Evet, onaylıyorum.",
        ],
    )

    with factory() as db:
        fail_report = acc_mod.finish_and_verify_run(db, fail_run["run_id"])

    assert fail_report["status"] == "FAIL"
    assert fail_report["checks"]["final_plate_matches_expected"] is False
    assert fail_report["layer_diagnostics"]["F2B_PLATE_TERMINOLOGY"]["status"] == "FAIL"

    # KVKK maskeleme kontrolü: plaka maskelenmiş olmalı
    masked = acc_mod.mask_acceptance_report(fail_report)
    assert masked["kvkk_masked"] is True
    assert masked["diff"]["new_appointments"][0]["plate"] == "34 *** 123"
    assert all("34 ABC 123" not in p for p in masked["diff"]["plates_seen"])


def test_acceptance_fastapi_endpoints_and_auth(isolated_acceptance_env):
    client = TestClient(app)

    # Yetkisiz istek reddedilmeli
    unauth = client.get("/api/acceptance/prerequisites")
    assert unauth.status_code == 401

    auth = ("admin", settings.admin_password)

    prep = client.post("/api/acceptance/prepare-fixtures", json={"reset_existing": False}, auth=auth)
    assert prep.status_code == 200
    assert prep.json()["prepared"] is True

    prereqs = client.get("/api/acceptance/prerequisites", auth=auth)
    assert prereqs.status_code == 200
    assert prereqs.json()["database"]["poc_fixture_ready"] is True

    started = client.post(
        "/api/acceptance/runs/start",
        json={"scenario_id": "run_1_plate_correction", "speaker_label": "API Test"},
        auth=auth,
    )
    assert started.status_code == 200
    run_id = started.json()["run_id"]

    verified = client.post(f"/api/acceptance/runs/{run_id}/verify", auth=auth)
    assert verified.status_code == 200
    assert verified.json()["status"] == "INCOMPLETE"

    term_audit = client.get("/api/acceptance/terminology/audit", auth=auth)
    assert term_audit.status_code == 200
    assert term_audit.json()["failed"] == 0

    term_test = client.post(
        "/api/acceptance/terminology/test",
        json={
            "asr_text": "C değil Denizlinin Dsi",
            "base_plate": "34 ABC 123",
            "tts_text": "Nissan Qashqai e-Power",
        },
        auth=auth,
    )
    assert term_test.status_code == 200
    body = term_test.json()
    assert body["inbound_asr"]["plate_correction"]["plate"] == "34 ABD 123"
    assert body["outbound_tts"]["ok"] is True


def test_cli_voice_acceptance_protocol_smoke(isolated_acceptance_env):
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///" + isolated_acceptance_env["db_file"].as_posix()
    env["DATA_DIR"] = str(isolated_acceptance_env["data_dir"])
    env["AUTO_LOAD_MODELS"] = "0"

    res_prereqs = subprocess.run(
        [sys.executable, "-m", "scripts.voice_acceptance_protocol", "prereqs"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    prereqs_json = json.loads(res_prereqs.stdout)
    assert "database" in prereqs_json and "models_ready" in prereqs_json

    res_audit = subprocess.run(
        [sys.executable, "-m", "scripts.voice_acceptance_protocol", "terminology-audit"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    audit_json = json.loads(res_audit.stdout)
    assert audit_json["failed"] == 0
    assert audit_json["pass_rate_pct"] == 100.0
