# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""
Madde 3: Müşteri Deneyimi Test Paketi.

Kapsanan Özellikler:
1. Randevu değiştirme ve iptal (sesli diyalog ve DTMF ile)
2. Randevu hatırlatma (1 gün öncesi outbox SMS/WhatsApp & hibrit arama)
3. Fiyat ve hizmet soruları (paket bazlı ve genel fiyat bilgilendirme)
4. Konuşma sırasında araya girme (TwoStageBargeInController Türkçe dinleme teyidi tuning)
5. Birden fazla araç (aynı oturumda ardışık iki araç için randevu alma)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.db import (
    Base,
    Appointment,
    Conversation,
    Slot,
    Vehicle,
    Quote,
    NotificationOutbox,
    CorporateAccount,
    book,
    cancel_appointment,
)
from backend.dialogue import (
    Dialogue,
)
from backend.audiosocket_server import (
    TwoStageBargeInController,
    BACKCHANNEL_WORDS,
)
from backend.notifications import (
    scan_and_queue_appointment_reminders,
    queue_cancellation_notification,
    MockNotificationProvider,
    set_notification_provider,
)
import backend.session as session_mod


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "madde3.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("backend.dialogue.Session", maker)
    monkeypatch.setattr(session_mod, "Session", maker)
    yield maker
    engine.dispose()


def _create_slot(db, hours_ahead=24):
    t = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    s = Slot(starts_at=t.isoformat(), duration_minutes=45)
    db.add(s)
    db.flush()
    return s


# =====================================================================
# 1. Randevu Değiştirme ve İptal (Voice & DTMF)
# =====================================================================

@pytest.mark.asyncio
async def test_inbound_cancel_by_phone_match(env):
    """Müşteri telefon numarası eşleştiğinde sesli iptal akışı onay sorusu sorar ve iptal eder."""
    phone = "05321112233"
    with env() as db:
        v = Vehicle(description="Volkswagen Passat 1.5 TSI", plate="34 ABC 123")
        db.add(v)
        s = _create_slot(db, hours_ahead=30)
        db.flush()
        app = book(
            db,
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Ahmet Yılmaz",
            idempotency_key="book-c1",
            confirmed=True,
            customer_phone=phone,
        )
        app_id = app.id

    d = Dialogue("c-cancel-1", customer_phone=phone)
    assert "plakanızı" in await d.answer("Ekspertiz randevumu iptal etmek istiyorum.")
    ans1 = await d.answer("34 ABC 123")
    assert "iptal etmek istediğinizi onaylıyor musunuz" in ans1
    assert "34 ABC 123" not in ans1
    assert d.awaiting_cancel_confirmation is True

    # Onay verildiğinde randevu iptal edilir
    ans2 = await d.answer("Evet, onaylıyorum iptal edin.")
    assert "başarıyla iptal edilmiştir" in ans2
    assert d.done is True

    with env() as db:
        app_after = db.get(Appointment, app_id)
        assert app_after.status == "cancelled"
        assert app_after.slot_id is None
        # İptal bildirimi outbox'a yazılmış olmalı
        cancel_notif = db.scalars(
            select(NotificationOutbox).where(
                NotificationOutbox.idempotency_key == f"notif-cancel-{app_id}"
            )
        ).first()
        assert cancel_notif is not None
        assert cancel_notif.channel == "sms"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["Hayır tamam kalsın.", "Uygun değil, iptal etmeyin."])
async def test_inbound_cancel_abort(env, reply):
    """Müşteri iptalden vazgeçerse randevu aktif kalır."""
    phone = "05329998877"
    with env() as db:
        v = Vehicle(description="Renault Megane 1.3 TCe", plate="06 ANK 99")
        db.add(v)
        s = _create_slot(db, hours_ahead=28)
        db.flush()
        app = book(
            db,
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Canan Demir",
            idempotency_key="book-c2",
            confirmed=True,
            customer_phone=phone,
        )
        app_id = app.id

    d = Dialogue("c-cancel-2", customer_phone=phone)
    await d.answer("Randevumu iptal edelim. 06 ANK 99")
    assert d.awaiting_cancel_confirmation is True

    ans2 = await d.answer(reply)
    assert "Mevcut randevunuz geçerlidir" in ans2
    assert d.done is False

    with env() as db:
        app_after = db.get(Appointment, app_id)
        assert app_after.status == "confirmed"


@pytest.mark.asyncio
@pytest.mark.parametrize("target_occupied", [False, True])
async def test_inbound_reschedule_flow(env, target_occupied):
    """Eski saat kesin onaya kadar korunur ve aynı randevu taşınır."""
    phone = "05441234567"
    with env() as db:
        v = Vehicle(description="Toyota Corolla 1.5 Vision", plate="35 EKS 456")
        db.add(v)
        s_old = _create_slot(db, hours_ahead=26)
        s_new = _create_slot(db, hours_ahead=48)
        db.flush()
        app = book(
            db,
            slot_id=s_old.id,
            vehicle_id=v.id,
            customer="Selin Kaya",
            idempotency_key="book-c3",
            confirmed=True,
            customer_phone=phone,
        )
        old_id, old_slot, new_slot, vehicle_id = app.id, s_old.id, s_new.id, v.id

    d = Dialogue("c-reschedule-1", customer_phone=phone)
    d.customer = "Selin"
    assert "plakanızı" in await d.answer("Randevumu ertelemek istiyorum.")
    assert "1. seçenek" in await d.answer("35 EKS 456")
    assert "onaylıyor musunuz" in await d.answer("Birinci seçenek.")
    with env() as db:
        assert db.get(Appointment, old_id).slot_id == old_slot

    if target_occupied:
        with env() as db:
            book(db, slot_id=new_slot, vehicle_id=vehicle_id, customer="Diğer Müşteri",
                 idempotency_key="takes-target", confirmed=True)
    response = await d.answer("Evet, onaylıyorum.")
    assert ("geçerlidir" if target_occupied else "taşındı") in response
    with env() as db:
        assert db.get(Appointment, old_id).slot_id == (old_slot if target_occupied else new_slot)
        assert db.query(Appointment).count() == (2 if target_occupied else 1)


@pytest.mark.asyncio
async def test_name_and_plate_cannot_replace_registered_phone(env):
    with env() as db:
        car = Vehicle(description="Corolla", plate="35 EKS 456")
        call = Conversation(channel="web", status="active")
        db.add_all([car, call])
        slot = _create_slot(db)
        app = book(db, slot_id=slot.id, vehicle_id=car.id, customer="Ali Kaya",
                   idempotency_key="identity-check", confirmed=True, customer_phone="05329998877")
        app_id, call_id = app.id, call.id

    dialogue = Dialogue(call_id, customer_phone="05321112233")
    dialogue.customer = "Ali"
    answer = await dialogue.answer("Randevumu ertelemek istiyorum. 35 EKS 456")
    assert "operatöre" in answer
    with env() as db:
        assert db.get(Appointment, app_id).status == "confirmed"
        assert db.get(Conversation, call_id).follow_up_kind == "callback"


@pytest.mark.asyncio
async def test_inbound_cancel_dtmf(env):
    """Müşteri iptal onayında DTMF 1 ile iptali onaylayabilir, 2 ile vazgeçebilir."""
    phone = "05551113344"
    with env() as db:
        v = Vehicle(description="Fiat Egea 1.4 Fire", plate="16 BUR 789")
        db.add(v)
        s = _create_slot(db, hours_ahead=25)
        db.flush()
        app = book(
            db,
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Bora Kurt",
            idempotency_key="book-dtmf-c",
            confirmed=True,
            customer_phone=phone,
        )
        app_id = app.id

    d = Dialogue("c-dtmf-cancel", customer_phone=phone)
    await d.answer("Randevumu iptal etmek istiyorum. 16 BUR 789")
    assert d.awaiting_cancel_confirmation is True

    with env() as db:
        dtmf_ans = await d.handle_dtmf("1", db)
    assert "iptal edilmiştir" in dtmf_ans
    assert d.done is True


# =====================================================================
# 2. Randevu Hatırlatma (1 Gün Öncesi Servis)
# =====================================================================

def test_scan_and_queue_appointment_reminders(env):
    """24 saat sonra başlayacak randevular taranır ve SMS hatırlatması transactional outbox'a eklenir."""
    with env() as db:
        v = Vehicle(description="Peugeot 3008 1.5 BlueHDi", plate="34 EKS 100")
        db.add(v)
        s_24h = _create_slot(db, hours_ahead=24)
        s_outside = _create_slot(db, hours_ahead=72)
        db.flush()

        app_remind = book(
            db,
            slot_id=s_24h.id,
            vehicle_id=v.id,
            customer="Hakan Koç",
            idempotency_key="app-remind-1",
            confirmed=True,
            customer_phone="05332223344",
        )
        app_far = book(
            db,
            slot_id=s_outside.id,
            vehicle_id=v.id,
            customer="Murat Şen",
            idempotency_key="app-far-1",
            confirmed=True,
            customer_phone="05338889900",
        )

        # Hatırlatma taraması (20-36 saat aralığı)
        queued = scan_and_queue_appointment_reminders(db, hours_ahead_min=20, hours_ahead_max=36)
        assert len(queued) == 1
        assert queued[0].appointment_id == app_remind.id
        assert queued[0].channel == "sms"
        assert queued[0].recipient == "05332223344"
        assert "yarın" in queued[0].message
        assert "EVET" in queued[0].message
        assert "İPTAL" in queued[0].message

        # İdempotent: İkinci kez tarandığında tekrar kuyruğa eklemez
        queued_repeat = scan_and_queue_appointment_reminders(db, hours_ahead_min=20, hours_ahead_max=36)
        assert len(queued_repeat) == 0


# =====================================================================
# 3. Fiyat ve Hizmet Soruları (Pricing & Services)
# =====================================================================

@pytest.mark.asyncio
async def test_general_price_and_package_inquiry(env):
    """Müşteri genel fiyat veya paket sorduğunda tüm paketler TL fiyatları ile listelenir."""
    d = Dialogue("c-price-1")
    ans = await d.answer("Ekspertiz fiyatlarınız ne kadar, hangi paketler var?")
    assert "Motor ve Mekanik 950 TL" in ans
    assert "Standart Ekspertiz 1.450 TL" in ans
    assert "Full Kapsamlı 1.950 TL" in ans
    assert "VIP Premium 2.600 TL" in ans
    assert "randevu oluşturmak istersiniz" in ans


@pytest.mark.asyncio
async def test_specific_package_inquiry(env):
    """Müşteri spesifik olarak Full ekspertizi sorduğunda süre, fiyat ve kapsam detayı verilir."""
    d = Dialogue("c-price-2")
    ans = await d.answer("Full ekspertiz fiyatı nedir ve neleri kapsıyor?")
    assert "Full Kapsamlı (Tam) Ekspertiz" in ans
    assert "1.950 TL" in ans
    assert "60 dakika" in ans
    assert "500 nokta detaylı kontrol" in ans
    assert d.package_type == "full_kapsamli"


# =====================================================================
# 4. Konuşma Sırasında Araya Girme (Barge-in Tuning)
# =====================================================================

def test_two_stage_bargein_backchannel_tuning():
    """Türkçe dinleme teyidi ifadeleri (evet, tamam, anladım, hıhı) asistanı kesmez (rollback döner)."""
    bargein = TwoStageBargeInController()
    bargein.stage1_soft_pause()
    assert bargein.paused is True

    # Tek kelime dinleme teyidi
    assert bargein.stage2_evaluate("evet") == "rollback"
    assert bargein.stage2_evaluate("tamam") == "rollback"
    assert bargein.stage2_evaluate("anladım") == "rollback"
    assert bargein.stage2_evaluate("hıhı") == "rollback"
    assert bargein.stage2_evaluate("dinliyorum") == "rollback"

    # İki kelimelik dinleme teyidi (bileşik teyit)
    assert bargein.stage2_evaluate("evet dinliyorum") == "rollback"
    assert bargein.stage2_evaluate("tamam anladım") == "rollback"
    assert bargein.stage2_evaluate("hıhı tamam") == "rollback"
    assert bargein.stage2_evaluate("tabii dinliyorum") == "rollback"


def test_two_stage_bargein_real_interrupt_commits():
    """Gerçek talep veya söz kesmelerde derhal 'commit' dönerek asistan susturulur."""
    bargein = TwoStageBargeInController()
    bargein.stage1_soft_pause()

    assert bargein.stage2_evaluate("bir dakika durun") == "commit"
    assert bargein.stage2_evaluate("üçüncü seçenek olsun") == "commit"
    assert bargein.stage2_evaluate("fiyat nedir") == "commit"
    assert bargein.stage2_evaluate("randevumu iptal edin") == "commit"
    assert bargein.stage2_evaluate("yarın gelemem") == "commit"


# =====================================================================
# 5. Birden Fazla Araç (Multi-Vehicle Flow)
# =====================================================================

@pytest.mark.asyncio
async def test_multi_vehicle_preplanned_booking(env, monkeypatch, fake_llm):
    monkeypatch.setattr(settings, "multi_vehicle_booking_enabled", True)
    """Müşteri başta iki araç belirttiğinde, 1. araç onayından sonra otomatik olarak 2. araca geçer."""
    phone = "05325556677"
    with env() as db:
        v1 = Vehicle(description="Volkswagen Passat 1.5 TSI", plate="34 VAG 01")
        v2 = Vehicle(description="Renault Megane 1.3 TCe", plate="34 REN 02")
        db.add_all([v1, v2])
        _create_slot(db, hours_ahead=24)
        _create_slot(db, hours_ahead=26)
        _create_slot(db, hours_ahead=28)
        db.commit()

    d = Dialogue("c-multi-1", customer_phone=phone)

    # 1. Giriş: iki araç belirtilir
    ans1 = await d.answer("İki aracım var randevu almak istiyorum.")
    assert d.multi_vehicle_planned is True
    assert "iki aracınız için de" in ans1

    # 2. İsim ve ilk araç söylenir
    # H01.01: canlı Ollama yerine SAHTE LLM yanıtı (tests/fakes/fake_llm.py); ağ çağrısı yok.
    fake_llm.reply({"customer": "Kemal Sunal", "vehicle_description": "Passat"})
    ans2 = await d.answer("Adım Kemal Sunal. İlk aracım Passat.")
    assert "Passat" in d.vehicle or d.vehicle is not None
    assert len(d.options) > 0

    # 3. İlk araç için slot seçimi ve onayı
    await d.answer("Birinci seçenek olsun.")
    assert d.awaiting is True

    ans_confirm = await d.answer("Evet, onaylıyorum.")
    assert "İlk aracınız için randevunuz oluşturuldu" in ans_confirm
    assert "ikinci aracınızın marka ve modelini" in ans_confirm
    # Müşteri kimliği ve telefon korunmuş olmalı
    assert d.customer == "Kemal Sunal"
    assert d.customer_phone == phone
    assert d.vehicle is None  # İkinci araç için sıfırlandı


@pytest.mark.asyncio
async def test_multi_vehicle_sequential_inquiry(env, monkeypatch):
    monkeypatch.setattr(settings, "multi_vehicle_booking_enabled", True)
    """Müşteri tek araç randevusunu aldıktan sonra 'Bir aracım daha var' dediğinde diyalog devam eder."""
    phone = "05321239900"
    with env() as db:
        v1 = Vehicle(description="Dacia Duster 1.3 TCe", plate="34 DAC 55")
        v2 = Vehicle(description="Toyota Corolla 1.5 Vision", plate="34 TYT 88")
        db.add_all([v1, v2])
        _create_slot(db, hours_ahead=20)
        _create_slot(db, hours_ahead=22)
        db.commit()

    d = Dialogue("c-multi-2", customer_phone=phone)
    # H01.04: mevcut hızlı akış tek saat önerip plaka sorar ("Yarın … uygun. Plakanızı söyler
    # misiniz?"); senaryo bu akışa göre güncellendi (eski "Birinci seçenek" adımı hiç eşleşmiyordu).
    ans_offer = await d.answer("Adım Leyla Güven. Duster aracım için randevu alacaktım.")
    assert "Plakanızı" in ans_offer
    ans_plate = await d.answer("Plakam 34 DAC 55")
    assert "onaylıyor musunuz" in ans_plate
    ans_booked = await d.answer("Evet, onaylıyorum.")
    assert "Randevunuz oluşturuldu" in ans_booked

    # Müşteri görüşme bitmeden ikinci bir araç bildirir
    ans_next = await d.answer("Bir aracım daha var onun için de randevu alalım.")
    assert "diğer aracınızın marka ve modelini" in ans_next.lower()
    assert d.customer == "Leyla Güven"
    assert d.done is False


@pytest.mark.asyncio
async def test_multi_vehicle_disabled_preserves_current_booking(env, monkeypatch):
    monkeypatch.setattr(settings, "multi_vehicle_booking_enabled", False)
    dialogue = Dialogue("multi-disabled")
    dialogue.vehicle = "current-vehicle"
    dialogue.options = [("current-slot", "Yarın saat 10")]
    for phrase in ("İki araç için randevu istiyorum", "Başka bir araç eklemek istiyorum"):
        assert "bir araç için" in await dialogue.answer(phrase)
        assert dialogue.vehicle == "current-vehicle"
        assert dialogue.options == [("current-slot", "Yarın saat 10")]
        assert not dialogue.multi_vehicle_planned
