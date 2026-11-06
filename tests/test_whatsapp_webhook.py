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

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.db import (
    Appointment,
    Base,
    NotificationOutbox,
    OutboundCall,
    Slot,
    Vehicle,
    WhatsAppMessage,
    book,
)
from backend.main import app
from backend.notifications import (
    MockNotificationProvider,
    set_notification_provider,
)
from backend.whatsapp_webhook import (
    extract_intent_and_time,
    process_inbound_text,
    process_inbound_voice,
)


def future_slot(days: int, hour: int, minute: int = 0) -> str:
    """Testin çalıştığı tarihten bağımsız, her zaman gelecekte kalan slot zamanı."""
    day = datetime.now(timezone.utc) + timedelta(days=days)
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


@pytest.fixture
def wa_env(tmp_path, monkeypatch):
    test_db = str(tmp_path / "wa_test.db")
    test_engine = create_engine(
        f"sqlite:///{test_db}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)

    monkeypatch.setattr("backend.db.engine", test_engine)
    monkeypatch.setattr("backend.db.Session", TestSession)
    monkeypatch.setattr("backend.whatsapp_webhook.Session", TestSession)
    monkeypatch.setattr("backend.main.Session", TestSession)
    monkeypatch.setattr("backend.main.settings.admin_password", "secret")

    provider = MockNotificationProvider()
    set_notification_provider(provider)

    c = TestClient(app)
    yield TestSession, c, test_engine, provider

    c.close()
    test_engine.dispose()


def test_extract_intent_and_time():
    # 1. Saat değişikliği
    intent1, t1 = extract_intent_and_time("Saati 16:00 yapalım lütfen")
    assert intent1 == "time_change"
    assert t1 == "16:00"

    intent2, t2 = extract_intent_and_time("14.30 olsun uygun mudur")
    assert intent2 == "time_change"
    assert t2 == "14:30"

    # 2. İptal
    intent3, _ = extract_intent_and_time("Yarın gelemiyorum randevuyu iptal edebilir misiniz")
    assert intent3 == "cancel"

    # 3. Onay
    intent4, _ = extract_intent_and_time("Tamam randevuyu onaylıyorum o saatte oradayım")
    assert intent4 == "confirm"

    # 4. Bilgi / Konum
    intent5, _ = extract_intent_and_time("İstasyon konumu ve adresi nerede")
    assert intent5 == "inquiry"


def test_branch_location_pin_in_notifications(wa_env):
    SessionLocal, _, _, _ = wa_env
    with SessionLocal() as db:
        slt = Slot(
            id="slot-pin-1",
            starts_at=future_slot(days=7, hour=14, minute=30),
            duration_minutes=30,
        )
        veh = Vehicle(id="veh-pin-1", description="Toyota Corolla", plate="34 PIN 01")
        db.add(slt)
        db.add(veh)
        db.commit()

        app_obj = book(
            db,
            slot_id=slt.id,
            vehicle_id=veh.id,
            customer="05321112233",
            customer_phone="05321112233",
            idempotency_key="idemp-pin-1",
            confirmed=True,
        )

        notifs = (
            db.scalars(
                select(NotificationOutbox).where(
                    NotificationOutbox.appointment_id == app_obj.id
                )
            ).all()
        )
        assert len(notifs) >= 1
        msg = notifs[0].message
        # Konum pini ve Google Maps URL'sinin mesajda bulunduğunu doğrula
        assert settings.branch_maps_url in msg
        assert "📍" in msg
        assert settings.branch_address in msg


def test_whatsapp_inbound_time_change_and_call_cancellation(wa_env):
    SessionLocal, _, _, _ = wa_env
    with SessionLocal() as db:
        slt = Slot(
            id="slot-wa-1",
            starts_at=future_slot(days=7, hour=10),
            duration_minutes=30,
        )
        veh = Vehicle(id="veh-wa-1", description="Renault Clio", plate="34 WA 123")
        db.add(slt)
        db.add(veh)
        db.commit()

        app_obj = book(
            db,
            slot_id=slt.id,
            vehicle_id=veh.id,
            customer="Mehmet Bey",
            customer_phone="05329998877",
            idempotency_key="idemp-wa-1",
            confirmed=True,
        )

        # Bu randevu için bekleyen giden hatırlatma araması oluştur
        out_call = OutboundCall(
            id="call-retry-1",
            appointment_id=app_obj.id,
            phone="05329998877",
            customer="Mehmet Bey",
            status="queued",
            outcome="pending",
        )
        db.add(out_call)
        db.commit()

        # Müşteri WhatsApp'tan "Saati 16:00 yapalım" mesajı gönderiyor
        res = process_inbound_text(
            db,
            from_phone="05329998877",
            text="Merhaba, saati 16:00 yapalım lütfen",
            customer_name="Mehmet Bey",
        )

        assert res["status"] == "success"
        assert res["intent"] == "time_change"
        assert res["extracted_time"] == "16:00"
        assert res["outbound_calls_cancelled"] == 1
        assert settings.branch_maps_url in res["reply"]
        assert "16:00" in res["reply"]

        # Giden arama kaydının otomatik iptal edildiğini doğrula
        db.refresh(out_call)
        assert out_call.status == "cancelled"
        assert out_call.outcome == "cancelled"
        assert "WhatsApp üzerinden yanıt verdi" in out_call.last_error

        # Randevu saatinin güncellendiğini doğrula
        db.refresh(app_obj)
        new_slot = db.get(Slot, app_obj.slot_id)
        assert new_slot is not None
        assert "16:00" in new_slot.starts_at


def test_whatsapp_inbound_cancellation(wa_env):
    SessionLocal, _, _, _ = wa_env
    with SessionLocal() as db:
        slt = Slot(
            id="slot-wa-cancel",
            starts_at=future_slot(days=8, hour=11),
            duration_minutes=30,
        )
        veh = Vehicle(id="veh-wa-cancel", description="Honda Civic", plate="06 CAN 01")
        db.add(slt)
        db.add(veh)
        db.commit()

        app_obj = book(
            db,
            slot_id=slt.id,
            vehicle_id=veh.id,
            customer="Kemal Sunal",
            customer_phone="05423334455",
            idempotency_key="idemp-wa-cancel",
            confirmed=True,
        )

        # Müşteri iptal mesajı yazıyor
        res = process_inbound_text(
            db,
            from_phone="05423334455",
            text="Gelemiyorum randevumu iptal edin lütfen",
        )

        assert res["intent"] == "cancel"
        assert "iptal edilmiştir" in res["reply"]

        db.refresh(app_obj)
        assert app_obj.status == "cancelled"
        assert app_obj.slot_id is None


@pytest.mark.asyncio
async def test_whatsapp_inbound_voice_transcription(wa_env, monkeypatch):
    SessionLocal, _, _, _ = wa_env
    with SessionLocal() as db:
        slt = Slot(
            id="slot-wa-voice",
            starts_at=future_slot(days=9, hour=9),
            duration_minutes=30,
        )
        veh = Vehicle(id="veh-wa-voice", description="Ford Focus", plate="35 VCS 99")
        db.add(slt)
        db.add(veh)
        db.commit()

        app_obj = book(
            db,
            slot_id=slt.id,
            vehicle_id=veh.id,
            customer="Selin Yılmaz",
            customer_phone="05334445566",
            idempotency_key="idemp-wa-voice",
            confirmed=True,
        )

        # Faster-Whisper ASR mocklama
        async def mock_transcribe(audio_data):
            return "Saati 15:30 yapalım geleceğim"

        monkeypatch.setattr("backend.models.models.transcribe", mock_transcribe)
        monkeypatch.setattr("backend.models.models.stt", True)

        dummy_audio = np.zeros(16000, dtype=np.float32)
        res = await process_inbound_voice(
            db,
            from_phone="05334445566",
            audio_data=dummy_audio,
            customer_name="Selin Yılmaz",
        )

        assert res["status"] == "success"
        assert res["message_type"] == "audio"
        assert res["transcription"] == "Saati 15:30 yapalım geleceğim"
        assert res["intent"] == "time_change"
        assert res["extracted_time"] == "15:30"
        assert "15:30" in res["reply"]

        db.refresh(app_obj)
        updated_slot = db.get(Slot, app_obj.slot_id)
        assert "15:30" in updated_slot.starts_at


def test_whatsapp_rest_api_endpoints(wa_env):
    SessionLocal, client, _, _ = wa_env
    auth_headers = {"Authorization": "Basic YWRtaW46c2VjcmV0"}

    with SessionLocal() as db:
        slt = Slot(id="slot-api-wa", starts_at=future_slot(days=10, hour=10), duration_minutes=30)
        veh = Vehicle(id="veh-api-wa", description="Audi A4", plate="34 AUD 04")
        db.add(slt)
        db.add(veh)
        db.commit()

        app_obj = book(
            db,
            slot_id=slt.id,
            vehicle_id=veh.id,
            customer="Deniz Kaya",
            customer_phone="05351112244",
            idempotency_key="idemp-api-wa",
            confirmed=True,
        )

    # 1. Text inbound endpoint
    post_res = client.post(
        "/api/whatsapp/inbound",
        json={
            "phone": "05351112244",
            "text": "Saati 17:00 yapalım",
            "customer_name": "Deniz Kaya",
        },
        headers=auth_headers,
    )
    assert post_res.status_code == 200
    data = post_res.json()
    assert data["intent"] == "time_change"
    assert data["extracted_time"] == "17:00"
    assert settings.branch_maps_url in data["reply"]

    # 2. List WhatsApp messages
    list_res = client.get("/api/whatsapp/messages", headers=auth_headers)
    assert list_res.status_code == 200
    msgs = list_res.json()
    assert len(msgs) >= 1
    assert msgs[0]["from_phone"] == "05351112244"
    assert msgs[0]["extracted_intent"] == "time_change"

    # 3. Webhook endpoint (Twilio form simulation)
    hook_res = client.post(
        "/api/webhooks/whatsapp",
        data={
            "From": "whatsapp:+905351112244",
            "Body": "Onaylıyorum geliyorum",
            "MessageSid": "SM12345678",
        },
    )
    assert hook_res.status_code == 200
    hook_data = hook_res.json()
    assert hook_data["intent"] == "confirm"
