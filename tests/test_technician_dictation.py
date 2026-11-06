"""Tests for technician voice dictation and entity extraction engine.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

import io
import json
from pathlib import Path
import pytest
import soundfile as sf
import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.db import Base, Vehicle, InspectionReport
from backend import main
from backend.technician_dictation import (
    parse_technician_dictation,
    apply_dictation_to_report,
)


@pytest.fixture
def dictation_setup(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "dictation_test.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sm = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(main, "Session", sm)
    monkeypatch.setattr("backend.db.Session", sm)
    monkeypatch.setattr(main.settings, "admin_password", "test-pass")

    client = TestClient(main.app)
    yield client, sm, tmp_path
    client.close()
    engine.dispose()


def test_parse_body_parts_and_microns():
    text = (
        "Sol ön çamurluk boyalı 180 mikron, sağ arka kapı değişen, "
        "ön kaput orijinal, tavan boyasız 105 mikron, bagaj kapağı lokal boyalı 160 mikron."
    )
    res = parse_technician_dictation(text)
    findings = res["findings"]["paint_body"]

    assert findings["sol_on_camurluk"] == "Boyalı (180 µm)"
    assert findings["sag_arka_kapi"] == "Değişen"
    assert findings["kaput"] == "Orijinal"
    assert findings["tavan"] == "Orijinal (105 µm)"
    assert findings["bagaj"] == "Lokal Boyalı (160 µm)"
    assert len(res["extracted_entities"]) >= 5
    assert res["calculated_score"] < 100  # penalized for boyalı + değişen + lokal
    assert "Gövde ve karoser kontrolünde" in res["generated_summary"]


def test_parse_mechanical_chassis_and_safety():
    text = (
        "Motor performansı yüzde 94 dyno, şanzıman kusursuz vuruntu yok. "
        "Karterde yağ kaçağı görülmedi. Şasi ve podyeler işlemsiz orijinal. "
        "Lastikler 6.5 mm dot 2024. Airbagler orijinal ve aktif, obd aktif arıza kodu yok."
    )
    res = parse_technician_dictation(text)
    findings = res["findings"]

    assert findings["engine_mechanical"]["motor_performansi_yuzde"] == "%94"
    assert findings["engine_mechanical"]["sanziman_vites"] == "Kusursuz / Vuruntu yok"
    assert findings["engine_mechanical"]["yag_sivi_kacaklari"] == "Kaçak görülmedi / Kuru"
    assert findings["chassis_frame"]["on_podyeler"] == "İşlemsiz / Orijinal"
    assert findings["tires_wheels"]["on_sol_dis_mm"] == "6.5 mm"
    assert findings["tires_wheels"]["dot_yili"] == "2024"
    assert findings["interior_electronics"]["airbag_guvenlik"] == "Orijinal ve aktif"
    assert findings["interior_electronics"]["obd_ariza_taramasi"] == "Aktif DTC arıza kodu yok"

    # Perfect conditions should keep score high
    assert res["calculated_score"] >= 95
    assert "Dyno motor test performansı %94" in res["generated_summary"]


def test_parse_group_parts_and_heavy_defects():
    text = (
        "Ön çamurluklar boyalı, arka kapılar değişen. "
        "Podye hasarlı kaynaklı ağır kusur. "
        "Airbagler dirençli işlemli. Motor yüzde 70, şanzımanda vuruntu var."
    )
    res = parse_technician_dictation(text)
    findings = res["findings"]

    # Both front fenders painted
    assert findings["paint_body"]["sol_on_camurluk"] == "Boyalı"
    assert findings["paint_body"]["sag_on_camurluk"] == "Boyalı"

    # Both rear doors replaced
    assert findings["paint_body"]["sol_arka_kapi"] == "Değişen"
    assert findings["paint_body"]["sag_arka_kapi"] == "Değişen"

    # Heavy structural/safety defects
    assert "Hasarlı" in findings["chassis_frame"]["on_podyeler"]
    assert "Dirençli" in findings["interior_electronics"]["airbag_guvenlik"]
    assert "Vuruntu" in findings["engine_mechanical"]["sanziman_vites"]

    # Heavy penalties drop score significantly
    assert res["calculated_score"] <= 40


def test_parse_blanket_hatasiz():
    text = "Araç tamamen hatasız boyasız. Motor ve yürüyen aksam kusursuz."
    res = parse_technician_dictation(text)
    findings = res["findings"]["paint_body"]

    assert findings["kaput"] == "Orijinal"
    assert findings["tavan"] == "Orijinal"
    assert findings["sag_on_camurluk"] == "Orijinal"
    assert findings["sol_arka_kapi"] == "Orijinal"
    assert res["calculated_score"] == 100


def test_apply_dictation_to_report(dictation_setup):
    client, SessionLocal, tmp_path = dictation_setup

    with SessionLocal() as db:
        v = Vehicle(
            description="Toyota Corolla 1.5 Vision",
            plate="06 TYT 2022",
            vin="NMTBZ3BE40R123456",
        )
        db.add(v)
        db.commit()

        pdf_path = str(tmp_path / "test_report.pdf")
        rep = InspectionReport(
            vehicle_id=v.id,
            technician_name="Ali Usta",
            summary="Ön muayene tamamlandı.",
            score=100,
            findings_json=json.dumps({"paint_body": {"kaput": "Orijinal"}}),
            pdf_path=pdf_path,
        )
        db.add(rep)
        db.commit()
        report_id = rep.id

    parsed = parse_technician_dictation(
        "Sol ön çamurluk boyalı 170 mikron, sağ ön kapı değişen, motor performansı yüzde 91 dyno."
    )

    with SessionLocal() as db:
        updated = apply_dictation_to_report(
            db,
            report_id=report_id,
            findings=parsed["findings"],
            summary=parsed["generated_summary"],
            score=parsed["calculated_score"],
        )

        assert updated.score == parsed["calculated_score"]
        assert "Teknisyen Dikte" in updated.summary
        f_json = json.loads(updated.findings_json)
        # Original kaput preserved
        assert f_json["paint_body"]["kaput"] == "Orijinal"
        # Newly dictated items merged
        assert f_json["paint_body"]["sol_on_camurluk"] == "Boyalı (170 µm)"
        assert f_json["paint_body"]["sag_on_kapi"] == "Değişen"
        assert f_json["engine_mechanical"]["motor_performansi_yuzde"] == "%91"
        # PDF file regenerated on disk
        assert Path(pdf_path).exists()
        assert Path(pdf_path).stat().st_size > 0


def test_dictate_text_api_preview_and_apply(dictation_setup):
    client, SessionLocal, tmp_path = dictation_setup
    auth = ("admin", "test-pass")

    # 1. Preview mode (no report_id or vehicle_id)
    r_prev = client.post(
        "/api/technician/dictate-text",
        json={"text": "Sol ön çamurluk boyalı 185 mikron, sağ arka kapı değişen."},
        auth=auth,
    )
    assert r_prev.status_code == 200
    data_prev = r_prev.json()
    assert data_prev["report"] is None
    assert data_prev["findings"]["paint_body"]["sol_on_camurluk"] == "Boyalı (185 µm)"
    assert data_prev["findings"]["paint_body"]["sag_arka_kapi"] == "Değişen"
    assert data_prev["calculated_score"] == 90

    # 2. Direct create report for vehicle
    with SessionLocal() as db:
        v = Vehicle(description="Ford Focus 1.5 EcoBlue", plate="34 FCD 100")
        db.add(v)
        db.commit()
        vehicle_id = v.id

    r_create = client.post(
        "/api/technician/dictate-text",
        json={
            "text": "Ön kaput değişen, tavan orijinal 110 mikron, motor performansı yüzde 93 dyno.",
            "vehicle_id": vehicle_id,
            "technician_name": "Kemal Usta",
        },
        auth=auth,
    )
    assert r_create.status_code == 200
    data_create = r_create.json()
    assert data_create["report"] is not None
    assert data_create["report"]["vehicle_id"] == vehicle_id
    assert data_create["report"]["technician_name"] == "Kemal Usta"
    assert Path(data_create["report"]["pdf_path"]).exists()

    # 3. Update existing report via report_id
    rep_id = data_create["report"]["id"]
    r_update = client.post(
        "/api/technician/dictate-text",
        json={
            "text": "Sol arka çamurluk lokal boyalı 150 mikron, lastikler 6.2 mm dot 2024.",
            "report_id": rep_id,
        },
        auth=auth,
    )
    assert r_update.status_code == 200
    data_update = r_update.json()
    assert data_update["report"]["id"] == rep_id
    findings = json.loads(data_update["report"]["findings_json"])
    # Previously created items preserved
    assert findings["paint_body"]["kaput"] == "Değişen"
    # New items merged
    assert findings["paint_body"]["sol_arka_camurluk"] == "Lokal Boyalı (150 µm)"
    assert findings["tires_wheels"]["on_sol_dis_mm"] == "6.2 mm"


def test_dictate_audio_api(dictation_setup, monkeypatch):
    client, SessionLocal, tmp_path = dictation_setup
    auth = ("admin", "test-pass")

    with SessionLocal() as db:
        v = Vehicle(description="Honda Civic 1.5 VTEC", plate="06 HND 06")
        db.add(v)
        db.commit()
        vehicle_id = v.id

    # Create dummy 1-second 16kHz audio WAV in memory
    sample_rate = 16000
    samples = np.sin(2 * np.pi * 440 * np.linspace(0, 1, sample_rate, dtype=np.float32))
    audio_buf = io.BytesIO()
    sf.write(audio_buf, samples, sample_rate, format="WAV")
    audio_bytes = audio_buf.getvalue()

    # Mock models.transcribe to return Turkish automotive dictation
    async def mock_transcribe(audio):
        return (
            "Sol ön çamurluk boyalı 180 mikron, sağ arka kapı değişen. "
            "Motor performansı yüzde 95 dyno, şanzıman kusursuz."
        )

    monkeypatch.setattr(main.models, "stt", True)
    monkeypatch.setattr(main.models, "transcribe", mock_transcribe)

    files = {"file": ("dictation.wav", audio_bytes, "audio/wav")}
    data = {
        "vehicle_id": vehicle_id,
        "technician_name": "Serkan Usta",
    }

    resp = client.post(
        "/api/technician/dictate-audio",
        files=files,
        data=data,
        auth=auth,
    )
    assert resp.status_code == 200
    res_json = resp.json()

    assert "Sol ön çamurluk boyalı" in res_json["transcribed_text"]
    assert res_json["findings"]["paint_body"]["sol_on_camurluk"] == "Boyalı (180 µm)"
    assert res_json["findings"]["paint_body"]["sag_arka_kapi"] == "Değişen"
    assert res_json["findings"]["engine_mechanical"]["motor_performansi_yuzde"] == "%95"
    assert res_json["report"] is not None
    assert res_json["report"]["vehicle_id"] == vehicle_id
    assert Path(res_json["report"]["pdf_path"]).exists()

