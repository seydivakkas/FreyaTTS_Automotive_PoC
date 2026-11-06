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

import base64
from pathlib import Path
from unittest.mock import AsyncMock, patch
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.db import Session, Slot, Appointment, Vehicle, OutboundCall, uid, now
from backend.main import app
from backend.outbound_dialer import (
    OutboundCampaignDialer,
    AMDResult,
    detect_turkish_amd,
    detect_voicemail_beep,
    generate_call_file_content,
    write_atomic_call_file,
)
import src.outbound_campaign_dialer as facade


@pytest.fixture
def test_client():
    client = TestClient(app)
    # Admin basic auth
    client.auth = ("admin", settings.admin_password)
    return client


@pytest.fixture
def sample_appointment():
    with Session() as db:
        v = Vehicle(plate=f"34 AMD {uid()[:4]}", description="Audi A3 1.5 TSI")
        db.add(v)
        slot = Slot(starts_at=f"2099-11-05T{uid()}Z")
        db.add(slot)
        db.flush()
        app_rec = Appointment(
            customer="05551234567",
            status="pending",
            confirmed=False,
            idempotency_key=uid(),
            slot_id=slot.id,
            vehicle_id=v.id,
        )
        db.add(app_rec)
        db.commit()
        app_id = app_rec.id
    return app_id


def test_facade_exports():
    """src/outbound_campaign_dialer.py cephesinin tüm bileşenleri doğru dışa aktardığını doğrular."""
    assert hasattr(facade, "OutboundCampaignDialer")
    assert hasattr(facade, "campaign_dialer")
    assert hasattr(facade, "AMDResult")
    assert hasattr(facade, "detect_turkish_amd")
    assert hasattr(facade, "detect_voicemail_beep")
    assert hasattr(facade, "generate_call_file_content")
    assert hasattr(facade, "write_atomic_call_file")
    assert facade.DEFAULT_OUTGOING_DIR is not None


def test_generate_call_file_content():
    """Asterisk .call dosya içeriği formatını doğrular."""
    content = generate_call_file_content(
        channel="SIP/trunk/05551234567",
        callerid="FreyaTTS <08501234567>",
        context="from-internal",
        exten="s",
        priority=1,
        max_retries=2,
        retry_time=180,
        wait_time=45,
        variables={
            "OUTBOUND_UUID": "test-uuid-123",
            "VEHICLE_PLATE": "34 ABC 99",
            "VEHICLE_PRICE": "1.250.000 TL",
        },
    )
    assert "Channel: SIP/trunk/05551234567" in content
    assert "CallerID: FreyaTTS <08501234567>" in content
    assert "MaxRetries: 2" in content
    assert "RetryTime: 180" in content
    assert "WaitTime: 45" in content
    assert "Context: from-internal" in content
    assert "Extension: s" in content
    assert "Priority: 1" in content
    assert "Set: OUTBOUND_UUID=test-uuid-123" in content
    assert "Set: VEHICLE_PLATE=34 ABC 99" in content
    assert "Set: VEHICLE_PRICE=1.250.000 TL" in content


def test_write_atomic_call_file(tmp_path: Path):
    """Atomik dosya yazımının tmp'den outgoing'e sorunsuz taşındığını doğrular."""
    out_dir = tmp_path / "outgoing"
    tmp_dir = tmp_path / "tmp"

    dummy_content = "Channel: SIP/test\nExtension: s\n"
    created_path = write_atomic_call_file(
        dummy_content,
        outgoing_dir=out_dir,
        tmp_dir=tmp_dir,
        filename_prefix="call_test",
    )

    assert created_path.exists()
    assert created_path.parent == out_dir
    assert created_path.name.startswith("call_test-")
    assert created_path.name.endswith(".call")
    # Tmp dizininde dosya kalmamalı
    assert len(list(tmp_dir.glob("*.call.tmp"))) == 0
    # İçerik eşleşmeli
    assert created_path.read_text(encoding="utf-8") == dummy_content


def test_detect_voicemail_beep():
    """1000 Hz telesekreter bip tonu algılama testleri."""
    sr = 8000
    t = np.linspace(0, 0.5, int(sr * 0.5), endpoint=False)  # 500 ms

    # 1. 1000 Hz saf ton (Bip)
    beep_audio = (np.sin(2 * np.pi * 1000.0 * t) * 0.5).astype(np.float32)
    assert detect_voicemail_beep(beep_audio, sample_rate=sr) is True

    # 2. 300 Hz ton (Bip değil, araç veya hat gürültüsü)
    low_freq_audio = (np.sin(2 * np.pi * 300.0 * t) * 0.5).astype(np.float32)
    assert detect_voicemail_beep(low_freq_audio, sample_rate=sr) is False

    # 3. Sessizlik
    silence = np.zeros(int(sr * 0.5), dtype=np.float32)
    assert detect_voicemail_beep(silence, sample_rate=sr) is False


def test_detect_turkish_amd_human():
    """Kısa Türkçe selamlama (0.8s) + sessizlik (0.6s) -> HUMAN sınıflandırması."""
    sr = 8000
    greeting_dur = 0.8
    silence_dur = 0.6
    t_greet = np.linspace(0, greeting_dur, int(sr * greeting_dur), endpoint=False)
    # Ses simülasyonu (insan sesi harmonikleri)
    speech = (
        0.3 * np.sin(2 * np.pi * 220.0 * t_greet)
        + 0.2 * np.sin(2 * np.pi * 440.0 * t_greet)
    ).astype(np.float32)
    silence = np.zeros(int(sr * silence_dur), dtype=np.float32)
    audio = np.concatenate([speech, silence])

    res = detect_turkish_amd(audio, sample_rate=sr)
    assert res.classification == "HUMAN"
    assert res.confidence >= 0.8
    assert res.beep_detected is False


def test_detect_turkish_amd_machine_long_greeting():
    """Uzun kesintisiz anons (2.5s) -> MACHINE sınıflandırması."""
    sr = 8000
    dur = 2.5
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    continuous_speech = (
        0.3 * np.sin(2 * np.pi * 300.0 * t)
        + 0.2 * np.sin(2 * np.pi * 600.0 * t)
    ).astype(np.float32)

    res = detect_turkish_amd(continuous_speech, sample_rate=sr)
    assert res.classification == "MACHINE"
    assert res.greeting_duration_sec >= 2.0


def test_detect_turkish_amd_machine_beep():
    """Anons ardından 1000 Hz bip sesi -> MACHINE sınıflandırması."""
    sr = 8000
    speech_dur = 0.8
    beep_dur = 0.4
    t_speech = np.linspace(0, speech_dur, int(sr * speech_dur), endpoint=False)
    t_beep = np.linspace(0, beep_dur, int(sr * beep_dur), endpoint=False)

    speech = (0.25 * np.sin(2 * np.pi * 250.0 * t_speech)).astype(np.float32)
    beep = (0.5 * np.sin(2 * np.pi * 1000.0 * t_beep)).astype(np.float32)
    audio = np.concatenate([speech, beep])

    res = detect_turkish_amd(audio, sample_rate=sr)
    assert res.classification == "MACHINE"
    assert res.beep_detected is True
    assert res.confidence >= 0.95


def test_detect_turkish_amd_edge_cases():
    """Yetersiz süre veya sessiz hat durumları."""
    sr = 8000
    # 1. 100 ms çok kısa ses
    res_short = detect_turkish_amd(np.zeros(int(sr * 0.1), dtype=np.float32), sample_rate=sr)
    assert res_short.classification == "UNKNOWN"

    # 2. 1 saniye tamamen sessiz
    res_silent = detect_turkish_amd(np.zeros(int(sr * 1.0), dtype=np.float32), sample_rate=sr)
    assert res_silent.classification == "UNKNOWN"
    assert "Sessizlik" in res_silent.reason


@pytest.mark.asyncio
async def test_originate_call_ami(sample_appointment):
    """AMI Originate dış aramasının OutboundCall kaydı oluşturması ve değişkenleri bağlaması."""
    dialer = OutboundCampaignDialer()

    mock_ami = AsyncMock()
    mock_ami.is_real = True  # gerçek AMI davranışı: in-progress
    mock_ami.originate.return_value = {"response": "Success", "action_id": "ami-act-999"}

    with patch("backend.outbound_dialer.get_ami_client", return_value=mock_ami):
        with Session() as db:
            call_rec = await dialer.originate_call_ami(
                db,
                appointment_id=sample_appointment,
                call_type="pricing_update",
                quote_price="1.450.000 TL",
            )
            assert call_rec.id is not None
            assert call_rec.status == "in-progress"
            assert call_rec.attempts == 1
            assert call_rec.action_id == "ami-act-999"

            # AMI originate çağrıldı mı?
            mock_ami.originate.assert_called_once()
            call_args = mock_ami.originate.call_args[1]
            vars_sent = call_args["variables"]
            assert vars_sent["OUTBOUND_UUID"] == call_rec.id
            assert "34 AMD" in vars_sent["VEHICLE_PLATE"]
            assert vars_sent["VEHICLE_PRICE"] == "1.450.000 TL"
            assert vars_sent["CALL_TYPE"] == "pricing_update"


@pytest.mark.asyncio
async def test_originate_call_ami_mock_is_simulated(sample_appointment):
    """Mock AMI altında durum 'in-progress' DEĞİL 'simulated' olmalı; gerçek sayaç artmaz."""
    dialer = OutboundCampaignDialer()
    mock_ami = AsyncMock()
    mock_ami.is_real = False
    mock_ami.originate.return_value = {"response": "Success", "action_id": "mock-1"}

    with patch("backend.outbound_dialer.get_ami_client", return_value=mock_ami):
        with Session() as db:
            call_rec = await dialer.originate_call_ami(
                db, appointment_id=sample_appointment, call_type="reminder"
            )
            assert call_rec.status == "simulated"
    m = dialer.get_metrics()
    assert m["total_originated_ami"] == 0
    assert m["total_simulated_ami"] == 1


def test_originate_call_file(sample_appointment, tmp_path: Path):
    """Atomik .call dosyası ile arama başlatma."""
    dialer = OutboundCampaignDialer(
        outgoing_spool_dir=tmp_path / "outgoing",
        tmp_spool_dir=tmp_path / "tmp",
    )

    with Session() as db:
        call_rec, fpath = dialer.originate_call_file(
            db,
            appointment_id=sample_appointment,
            call_type="reminder",
        )
        assert call_rec.id is not None
        assert call_rec.status == "in-progress"
        assert fpath.exists()
        content = fpath.read_text(encoding="utf-8")
        assert f"OUTBOUND_UUID={call_rec.id}" in content
        assert "VEHICLE_PLATE=34 AMD" in content


def test_process_amd_result(sample_appointment):
    """AMD analiz sonuçlarına göre çağrı durumlarının güncellenmesi."""
    dialer = OutboundCampaignDialer()

    with Session() as db:
        call = OutboundCall(
            appointment_id=sample_appointment,
            phone="05551234567",
            customer="Ahmet Bey",
            status="originating",
        )
        db.add(call)
        db.commit()
        call_id = call.id

        # 1. HUMAN
        human_res = AMDResult(
            classification="HUMAN",
            confidence=0.96,
            greeting_duration_sec=0.8,
            silence_duration_sec=0.5,
            beep_detected=False,
            reason="Human detected",
        )
        dialer.process_amd_result(db, call_id, human_res)
        updated = db.get(OutboundCall, call_id)
        assert updated.outcome == "human_connected"
        assert updated.status == "in-progress"

        # 2. MACHINE (Voicemail Drop)
        machine_res = AMDResult(
            classification="MACHINE",
            confidence=0.99,
            greeting_duration_sec=2.2,
            silence_duration_sec=0.2,
            beep_detected=True,
            reason="Voicemail beep detected",
        )
        dialer.process_amd_result(db, call_id, machine_res)
        updated2 = db.get(OutboundCall, call_id)
        assert updated2.outcome == "voicemail_dropped"
        assert updated2.status == "completed"
        assert updated2.completed_at is not None


@pytest.mark.asyncio
async def test_schedule_auto_retry_and_process_queue(sample_appointment):
    """Meşgul / cevapsız hatların yeniden aranması ve kuyruk işleme."""
    dialer = OutboundCampaignDialer(max_retries=2)

    with Session() as db:
        call = OutboundCall(
            appointment_id=sample_appointment,
            phone="05559876543",
            customer="Mehmet Bey",
            status="in-progress",
            attempts=1,
        )
        db.add(call)
        db.commit()
        call_id = call.id

        # 1. Deneme meşgul -> retry_scheduled
        updated, will_retry = dialer.schedule_auto_retry(db, call_id, reason="busy")
        assert will_retry is True
        assert updated.status == "retry_scheduled"
        assert updated.outcome == "busy"

        # Kuyruk işleme (mock AMI ile)
        mock_ami = AsyncMock()
        mock_ami.originate.return_value = {"response": "Success", "action_id": "retry-1"}
        with patch("backend.outbound_dialer.get_ami_client", return_value=mock_ami):
            retried = await dialer.process_retry_queue(db, limit=5)
            assert len(retried) == 1
            assert retried[0].attempts == 2

        # 2. Deneme cevapsız -> max_retries aşıldı, unreachable olarak kapanmalı
        updated2, will_retry2 = dialer.schedule_auto_retry(db, call_id, reason="no_answer")
        assert will_retry2 is False
        assert updated2.status == "completed"
        assert updated2.outcome == "unreachable"


def test_rest_api_outbound_endpoints(test_client, sample_appointment):
    """FastAPI REST API giden arama ve AMD endpoint'lerinin entegrasyon testleri."""
    # 1. /api/outbound/campaign-dial (callfile mode)
    resp = test_client.post(
        "/api/outbound/campaign-dial",
        json={
            "appointment_ids": [sample_appointment],
            "dial_mode": "callfile",
            "call_type": "reminder",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "callfile"
    assert data["total"] == 1
    assert data["successful_count"] == 1
    created_call_id = data["calls"][0]["id"]

    # 2. /api/outbound/amd-analyze
    # 16-bit PCM 1000 Hz beep sesi oluşturup base64 olarak gönder
    sr = 8000
    t = np.linspace(0, 0.4, int(sr * 0.4), endpoint=False)
    beep_int16 = (np.sin(2 * np.pi * 1000.0 * t) * 16000).astype("<i2")
    b64_audio = base64.b64encode(beep_int16.tobytes()).decode("utf-8")

    resp_amd = test_client.post(
        "/api/outbound/amd-analyze",
        json={"audio_base64": b64_audio, "sample_rate": 8000},
    )
    assert resp_amd.status_code == 200
    amd_data = resp_amd.json()
    assert amd_data["classification"] == "MACHINE"
    assert amd_data["beep_detected"] is True

    # 3. /api/outbound/amd-evaluate-call
    resp_eval = test_client.post(
        "/api/outbound/amd-evaluate-call",
        json={
            "call_id": created_call_id,
            "classification": "HUMAN",
            "reason": "Test human connected",
        },
    )
    assert resp_eval.status_code == 200
    assert resp_eval.json()["outcome"] == "human_connected"

    # 4. /api/outbound/campaign-stats
    resp_stats = test_client.get("/api/outbound/campaign-stats")
    assert resp_stats.status_code == 200
    stats = resp_stats.json()
    assert "total_originated_callfile" in stats
    assert "total_amd_human" in stats
