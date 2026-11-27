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

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.ami import MockAMIClient
from backend.db import Base, Conversation, OperatorTransfer, Session, engine
from backend.dialogue import Dialogue
from backend.main import app
from backend.transfer import (
    FALLBACK_AI_PROMPT,
    TRANSFER_ANNOUNCEMENT,
    accept_operator_transfer,
    check_transfer_timeouts,
    decline_operator_transfer,
    generate_screen_pop_headers,
    generate_whisper_text,
    handle_operator_dtmf,
    initiate_operator_transfer,
    list_transfers,
)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    with Session() as db:
        db.query(OperatorTransfer).delete()
        db.query(Conversation).delete()
        db.commit()


def test_generate_screen_pop_headers():
    headers = generate_screen_pop_headers(
        transfer_id="trf-12345",
        customer_name="Ahmet Yılmaz",
        vehicle_plate="34 ABC 123",
        summary="14:30 randevu teyidi / kaporta kontrol",
        intent="operator_transfer",
    )
    assert headers["X-Freya-Transfer-ID"] == "trf-12345"
    assert headers["X-Freya-Customer"] == "Ahmet Yılmaz"
    assert headers["X-Freya-Plate"] == "34 ABC 123"
    assert "kaporta" in headers["X-Freya-Summary"]
    assert headers["X-Freya-Intent"] == "operator_transfer"
    assert "X-Freya-Timestamp" in headers


def test_generate_whisper_text():
    text = generate_whisper_text(
        customer_name="Ayşe Kaya",
        vehicle_plate="06 DEF 456",
        summary="motor ekspertizi talebi",
    )
    assert "Ayşe Kaya" in text
    assert "06 DEF 456" in text
    assert "1'i" in text
    assert "2'yi" in text
    # 10 saniyelik konuşma için kelime sayısı makul (< 30 kelime) olmalı
    word_count = len(text.split())
    assert word_count <= 25


@pytest.mark.asyncio
async def test_initiate_operator_transfer_with_mock_ami():
    mock_ami = MockAMIClient()
    with Session() as db:
        conv = Conversation(channel="asterisk")
        db.add(conv)
        db.commit()

        transfer = await initiate_operator_transfer(
            db,
            conversation_id=conv.id,
            caller_channel="PJSIP/trunk-0001",
            customer_name="Mehmet Öz",
            vehicle_plate="35 GHI 789",
            summary="Randevu saatini değiştirme",
            operator_extension="6002",
            ami_client=mock_ami,
        )

        assert transfer.id.startswith("trf-")
        assert transfer.status == "whispering"
        assert transfer.operator_extension == "6002"
        assert transfer.customer_name == "Mehmet Öz"
        assert transfer.vehicle_plate == "35 GHI 789"

        # SIP Başlıklarının kanal değişkeni olarak AMI'ye yazıldığını doğrula
        var_names = [v["variable"] for v in mock_ami.variables]
        assert "X_Freya_Customer" in var_names
        assert "X_Freya_Plate" in var_names

        # Operatör dahilisinin arandığını (Originate) doğrula
        assert len(mock_ami.calls) == 1
        call = mock_ami.calls[0]
        assert "6002" in call["channel"]
        assert call["variables"]["TRANSFER_ID"] == transfer.id


@pytest.mark.asyncio
async def test_accept_operator_transfer_bridge():
    mock_ami = MockAMIClient()
    with Session() as db:
        conv = Conversation(channel="asterisk")
        db.add(conv)
        db.commit()

        transfer = await initiate_operator_transfer(
            db,
            conversation_id=conv.id,
            caller_channel="PJSIP/trunk-0002",
            customer_name="Canan Demir",
            vehicle_plate="16 JKL 012",
            summary="Usta ile görüşme talebi",
            ami_client=mock_ami,
        )

        # Uzman 1 tuşlayarak kabul ettiğinde köprüleme yapılır
        accepted = await accept_operator_transfer(
            db,
            transfer.id,
            operator_channel="PJSIP/6002-000abc",
            ami_client=mock_ami,
        )

        assert accepted.status == "accepted"
        assert accepted.completed_at is not None
        assert accepted.duration_seconds is not None
        assert len(mock_ami.bridges) == 1
        assert mock_ami.bridges[0]["channel1"] == "PJSIP/trunk-0002"
        assert mock_ami.bridges[0]["channel2"] == "PJSIP/6002-000abc"

        # Conversation tablosunun güncellendiğini doğrula
        db.refresh(conv)
        assert conv.status == "transferred"
        assert "Uzman (6002) çağrıyı kabul etti" in conv.operator_notes


@pytest.mark.asyncio
async def test_accept_operator_transfer_ami_failure():
    mock_ami = MockAMIClient()
    with Session() as db:
        conv = Conversation(channel="asterisk")
        db.add(conv)
        db.commit()

        transfer = await initiate_operator_transfer(
            db,
            conversation_id=conv.id,
            caller_channel="PJSIP/trunk-0002",
            customer_name="Canan Demir",
            vehicle_plate="16 JKL 012",
            summary="Usta ile görüşme talebi",
            ami_client=mock_ami,
        )

        mock_ami.fail_next = True
        with pytest.raises(RuntimeError) as exc_info:
            await accept_operator_transfer(
                db,
                transfer.id,
                operator_channel="PJSIP/6002-000abc",
                ami_client=mock_ami,
            )

        assert "Çağrı köprüleme başarısız oldu" in str(exc_info.value)
        db.refresh(transfer)
        assert transfer.status == "failed"
        assert transfer.completed_at is not None

        db.refresh(conv)
        assert conv.status == "failed"
        assert "Operatör aktarımı AMI hatası nedeniyle başarısız oldu" in conv.operator_notes


@pytest.mark.asyncio
async def test_decline_operator_transfer_and_fallback():
    mock_ami = MockAMIClient()
    with Session() as db:
        conv = Conversation(channel="asterisk")
        db.add(conv)
        db.commit()

        transfer = await initiate_operator_transfer(
            db,
            conversation_id=conv.id,
            caller_channel="PJSIP/trunk-0003",
            customer_name="Ali Veli",
            vehicle_plate="34 MNO 345",
            summary="Ekspertiz usta danışması",
            ami_client=mock_ami,
        )

        # Uzman 2 tuşlayarak reddettiğinde veya meşgul olduğunda
        declined = await decline_operator_transfer(
            db,
            transfer.id,
            reason="declined",
            operator_channel="PJSIP/6002-busy",
            ami_client=mock_ami,
        )

        assert declined.status == "declined"
        assert declined.completed_at is not None
        assert len(mock_ami.hangups) == 1

        db.refresh(conv)
        assert "Uzman aktarımı declined oldu" in conv.operator_notes


@pytest.mark.asyncio
async def test_handle_operator_dtmf():
    mock_ami = MockAMIClient()
    with Session() as db:
        transfer = await initiate_operator_transfer(
            db,
            caller_channel="PJSIP/trunk-0004",
            customer_name="Test DTMF",
            vehicle_plate="34 TST 001",
            summary="DTMF Test",
            ami_client=mock_ami,
        )

        # DTMF '1' -> Accept
        res1 = await handle_operator_dtmf(db, transfer.id, "1", ami_client=mock_ami)
        assert res1["action"] == "accepted"
        assert res1["status"] == "accepted"

        # Tekrar çağrıldığında idempotent olmalı
        res2 = await handle_operator_dtmf(db, transfer.id, "2", ami_client=mock_ami)
        assert res2["action"] == "declined"


def test_check_transfer_timeouts():
    with Session() as db:
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
        tr = OperatorTransfer(
            id="trf-timeout-1",
            caller_channel="PJSIP/trunk-0005",
            operator_extension="6002",
            customer_name="Timeout Müşteri",
            vehicle_plate="34 TIM 001",
            summary="Zaman aşımı testi",
            status="whispering",
            created_at=old_time,
        )
        db.add(tr)
        db.commit()

        timed_out = check_transfer_timeouts(db, timeout_sec=15)
        assert len(timed_out) == 1
        assert timed_out[0].id == "trf-timeout-1"
        assert timed_out[0].status == "timeout"


@pytest.mark.asyncio
async def test_dialogue_dtmf_0_operator_trigger(real_ami):
    d = Dialogue("conv-test-dtmf-0")
    with Session() as db:
        ans = await d.handle_dtmf("0", db)
        assert d.done is True
        assert d.transfer_requested is True
        assert "0'ı tuşladınız" in ans
        assert "aktarıyorum" in ans


@pytest.mark.asyncio
async def test_dialogue_speech_operator_trigger(real_ami):
    d = Dialogue("conv-test-speech-op")
    ans = await d.answer("beni bir operatöre bağlar mısınız?")
    assert d.done is True
    assert d.transfer_requested is True
    assert "aktarıyorum" in ans


def test_transfer_rest_api_endpoints():
    client = TestClient(app)
    auth_headers = {"Authorization": "Basic YWRtaW46c2VjcmV0"}

    with patch("backend.main.settings.admin_password", "secret"):
        # 1. Initiate transfer
        init_res = client.post(
            "/api/transfers/initiate",
            json={
                "customer_name": "REST Müşteri",
                "vehicle_plate": "34 RST 999",
                "summary": "REST API Test Aktarımı",
                "operator_extension": "6002",
            },
            headers=auth_headers,
        )
        assert init_res.status_code == 200
        tr_data = init_res.json()
        tr_id = tr_data["id"]
        assert tr_data["customer_name"] == "REST Müşteri"
        assert tr_data["status"] in ("initiated", "whispering")
        assert "sip_headers" in tr_data

        # 2. Get list of transfers
        list_res = client.get("/api/transfers", headers=auth_headers)
        assert list_res.status_code == 200
        items = list_res.json()
        assert any(item["id"] == tr_id for item in items)

        # 3. Get transfer detail
        detail_res = client.get(f"/api/transfers/{tr_id}", headers=auth_headers)
        assert detail_res.status_code == 200
        assert detail_res.json()["vehicle_plate"] == "34 RST 999"

        # 4. Operator DTMF endpoint (Press 1 to accept)
        dtmf_res = client.post(
            f"/api/transfers/{tr_id}/dtmf",
            json={"digit": "1"},
            headers=auth_headers,
        )
        assert dtmf_res.status_code == 200
        assert dtmf_res.json()["action"] == "accepted"

        # 5. Verify transfer is accepted
        check_res = client.get(f"/api/transfers/{tr_id}", headers=auth_headers)
        assert check_res.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_voice_session_operator_transfer_flow(monkeypatch, real_ami):
    import numpy as np
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend import session as session_mod

    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(test_engine)
    sm = sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(session_mod, "Session", sm)

    class MockVad:
        def reset_states(self):
            pass

    monkeypatch.setattr(session_mod.models, "vad", MockVad())

    async def mock_synth(text, seed=9):
        return np.zeros(4800, dtype=np.float32)

    monkeypatch.setattr(session_mod.models, "synth", mock_synth)

    mock_ami = real_ami
    monkeypatch.setattr("backend.transfer.get_ami_client", lambda: mock_ami)

    events = []
    frames = []

    async def emit(ev):
        events.append(ev)

    async def send(fr):
        frames.append(fr)

    sess = session_mod.VoiceSession("web", emit, send)
    sess.dialogue.customer = "Fatma Hanım"

    # DTMF 0 basıldığında transfer tetiklenmeli
    await sess.handle_dtmf("0")

    # Event listesinde operator_transfer olmalı
    trf_ev = next((e for e in events if e.get("type") == "operator_transfer"), None)
    assert trf_ev is not None
    assert trf_ev["status"] in ("initiated", "whispering")
    assert trf_ev["customer_name"] == "Fatma Hanım"
    assert "Fatma Hanım" in trf_ev["whisper_text"]

    # Completed reason "transferred" olmalı
    comp_ev = next((e for e in events if e.get("type") == "completed"), None)
    assert comp_ev is not None
    assert comp_ev["reason"] == "transferred"

    await sess.close()
    test_engine.dispose()
