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

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.db import Base, Vehicle, Slot, Appointment, book
from backend.notifications import (
    TwilioNotificationProvider,
    MockNotificationProvider,
    format_phone_e164,
    get_notification_provider,
    set_notification_provider,
    can_send_real_notifications,
)
from backend.telephony import register_inbound_metadata, get_inbound_metadata
from backend.dialogue import Dialogue, extract_phone_number
from backend.ami import set_ami_client, MockAMIClient, AsteriskAMIClient, is_real_ami
from backend import main


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path}/madde2_test.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("backend.db.Session", session_factory)
    monkeypatch.setattr(main.settings, "admin_password", "test-pass-123")

    mock_prov = MockNotificationProvider()
    set_notification_provider(mock_prov)
    set_ami_client(MockAMIClient())

    client = TestClient(main.app)
    yield client, session_factory, engine
    client.close()
    engine.dispose()
    set_notification_provider(None)
    set_ami_client(None)


# -----------------------------------------------------------------------------
# 1. Telefon Numarası Formatlama & Çıkarma Testleri
# -----------------------------------------------------------------------------

def test_format_phone_e164():
    # Yerel Türkiye formatları
    assert format_phone_e164("05321234567") == "+905321234567"
    assert format_phone_e164("0532 123 45 67") == "+905321234567"
    assert format_phone_e164("5321234567") == "+905321234567"
    assert format_phone_e164("905321234567") == "+905321234567"
    assert format_phone_e164("+905321234567") == "+905321234567"
    assert format_phone_e164("00905321234567") == "+905321234567"
    # Boş durum
    assert format_phone_e164("") == ""


def test_extract_phone_number():
    # Rakamla belirtilen
    assert extract_phone_number("Numaram 0544 123 45 67") == "05441234567"
    assert extract_phone_number("Telefonum 5339998877 lütfen kaydedin") == "05339998877"
    # Türkçe sözlü rakamlar
    spoken = "Numaram sıfır beş yüz kırk iki yüz yirmi üç kırk beş altmış yedi"
    assert extract_phone_number(spoken) is not None
    assert extract_phone_number(spoken).startswith("05")


# -----------------------------------------------------------------------------
# 2. TwilioNotificationProvider Testleri
# -----------------------------------------------------------------------------

def test_twilio_provider_sms_and_whatsapp(monkeypatch):
    recorded_requests = []

    class DummyResponse:
        def __init__(self, status_code, json_data):
            self.status_code = status_code
            self._json = json_data
            self.text = "OK"

        def json(self):
            return self._json

    class DummyHttpClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def post(self, url, data=None, auth=None, **kwargs):
            recorded_requests.append({"url": url, "data": data, "auth": auth})
            return DummyResponse(201, {"sid": "SM_TEST_12345", "status": "queued"})

    import httpx
    monkeypatch.setattr(httpx, "Client", DummyHttpClient)

    provider = TwilioNotificationProvider(
        account_sid="AC_MOCK_ACCOUNT",
        auth_token="MOCK_AUTH_TOKEN",
        from_number="+15551234567",
        whatsapp_from="whatsapp:+14155238886",
    )

    # SMS gönderimi
    receipt_sms = provider.send("sms", "0532 111 22 33", "Ekspertiz randevu onayınız.")
    assert receipt_sms["provider"] == "twilio"
    assert receipt_sms["external_id"] == "SM_TEST_12345"
    assert receipt_sms["target_e164"] == "+905321112233"
    assert receipt_sms["simulated"] is False

    # WhatsApp gönderimi
    receipt_wa = provider.send("whatsapp", "0532 111 22 33", "Ekspertiz raporunuz hazır.")
    assert receipt_wa["provider"] == "twilio"
    assert receipt_wa["target_e164"] == "whatsapp:+905321112233"
    assert len(recorded_requests) == 2
    assert recorded_requests[0]["auth"] == ("AC_MOCK_ACCOUNT", "MOCK_AUTH_TOKEN")
    assert recorded_requests[1]["data"]["From"] == "whatsapp:+14155238886"


def test_twilio_provider_fallback_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "notification_provider", "twilio")
    monkeypatch.setattr(settings, "twilio_account_sid", "")
    monkeypatch.setattr(settings, "twilio_auth_token", "")
    set_notification_provider(None)

    # Kimlik bilgisi boşken güvenli fallback
    prov = get_notification_provider()
    assert isinstance(prov, MockNotificationProvider)
    assert can_send_real_notifications() is False


# -----------------------------------------------------------------------------
# 3. Randevu Tablosuna customer_phone Eklenmesi Testi
# -----------------------------------------------------------------------------

def test_appointment_persists_customer_phone(test_env):
    client, SessionLocal, engine = test_env
    with SessionLocal() as db:
        v = Vehicle(description="BMW 320i", plate="34 B 320")
        db.add(v)
        slot_time = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        s = Slot(starts_at=slot_time.isoformat(), duration_minutes=30)
        db.add(s)
        db.commit()

        app = book(
            db,
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Ahmet Yılmaz",
            customer_phone="0532 555 44 33",
            idempotency_key="book-phone-persisted",
            confirmed=True,
        )

        db_app = db.get(Appointment, app.id)
        assert db_app is not None
        assert db_app.customer_phone == "0532 555 44 33"


# -----------------------------------------------------------------------------
# 4. Asterisk/SIP Inbound Metadata Webhook Testi
# -----------------------------------------------------------------------------

def test_inbound_metadata_webhook_and_retrieval(test_env):
    client, _, _ = test_env
    auth = ("admin", "test-pass-123")

    call_uuid = "call-uuid-test-9999"
    payload = {
        "call_uuid": call_uuid,
        "caller_id": "+905329876543",
        "caller_channel": "PJSIP/trunk-000000a1",
        "did": "02129998877",
    }
    resp = client.post("/api/telephony/inbound-metadata", json=payload)
    assert resp.status_code == 200
    assert resp.json()["registered"] is True

    # Kaydedilen üstveri okunabilmeli
    meta = get_inbound_metadata(call_uuid)
    assert meta is not None
    assert meta["caller_id"] == "+905329876543"
    assert meta["caller_channel"] == "PJSIP/trunk-000000a1"


# -----------------------------------------------------------------------------
# 5. Operatöre Devretme (Asistan Anlamadığında) Testi
# -----------------------------------------------------------------------------

def test_dialogue_unclear_triggers_operator_transfer(monkeypatch):
    class RealAmiStub:
        is_real = True

        async def setvar(self, *args, **kwargs):
            return {"response": "Success"}

        async def originate(self, *args, **kwargs):
            return {"response": "Success"}

    set_ami_client(RealAmiStub())

    d = Dialogue("conv-unclear-test")
    # 1. deneme
    ans1 = d.unclear()
    assert "Tekrar söyler misiniz" in ans1
    assert d.retries == 1
    assert d.transfer_requested is False

    # 2. deneme (STT fallback)
    ans2 = d.unclear()
    assert d.retries == 2
    assert d.transfer_requested is False

    # 3. deneme: Asistan anlayamadı -> Operatöre canlı devretme
    ans3 = d.unclear()
    assert d.retries == 3
    assert d.transfer_requested is True
    assert "yetkili danışmanımıza aktarıyorum" in ans3


def test_dialogue_unclear_fallback_when_ami_offline(monkeypatch):
    # AMI bağlı değil (Mock client)
    set_ami_client(MockAMIClient())

    d = Dialogue("conv-unclear-mock")
    d.retries = 2
    ans = d.unclear()
    assert d.retries == 3
    assert d.transfer_requested is False
    assert "talebinizi kaydettim, sizi arayacağız" in ans
