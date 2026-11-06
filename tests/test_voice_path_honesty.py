"""P2: ses yolu doğruluğu ve dürüstlüğü (SMS/aktarım/giden arama/iptal iadesi/dayanıklılık)."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import backend.main as main
import backend.session as session_mod
from backend.ami import MockAMIClient, get_ami_client, is_real_ami, set_ami_client
from backend.config import settings
from backend.db import (
    Appointment,
    Base,
    CorporateAccount,
    CorporateLedger,
    Conversation,
    OutboundCall,
    Quote,
    Slot,
    Vehicle,
    VehicleDiagnostic,
    book,
    cancel_appointment,
)
from backend.dialogue import Dialogue
from backend.models import models
from backend.notifications import (
    MockNotificationProvider,
    can_send_real_notifications,
    dispatch_pending_notifications,
    get_notification_provider,
    set_notification_provider,
)
from backend.outbound import (
    complete_outbound_call,
    get_outbound_session_context,
    initiate_outbound_call,
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "p2.db"), connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("backend.dialogue.Session", maker)
    monkeypatch.setattr(session_mod, "Session", maker)
    yield maker
    engine.dispose()


@pytest.fixture
def provider_restore():
    previous = get_notification_provider()
    yield
    set_notification_provider(previous)


class FakeRealProvider:
    """Gerçek sağlayıcı gibi davranır (simulated işareti yok)."""

    def __init__(self):
        self.messages = []

    def send(self, channel, recipient, message):
        self.messages.append((channel, recipient))
        return {"provider": "fake-real", "external_id": "x1"}


def _slot(db, days=2, hour=10):
    t = (datetime.now(timezone.utc) + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    s = Slot(starts_at=t.isoformat())
    db.add(s)
    db.flush()
    return s


def _booking_dialogue(db, conv_id="c-p2"):
    v = Vehicle(description="Toyota Corolla 1.5 Vision", plate="34 TYT 55")
    db.add(v)
    db.flush()
    s = _slot(db)
    db.commit()
    d = Dialogue(conversation_id=conv_id)
    d.customer = "Mehmet Bey"
    d.vehicle = v.id
    d.slot = s.id
    d.awaiting = True
    return d


# ---------------------------------------------------------------- Madde 1
async def test_outbound_diagnostic_start_with_appointment_id(env, monkeypatch):
    """session.py: `select` içe aktarılmamıştı; appointment_id'li teşhis dalı NameError veriyordu."""

    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(models, "vad", Vad())
    with env() as db:
        mine = Vehicle(description="Renault Clio", plate="34 AAA 01")
        other = Vehicle(description="Fiat Egea", plate="34 BBB 02")
        db.add_all([mine, other])
        db.flush()
        db.add(
            VehicleDiagnostic(
                vehicle_id=mine.id,
                dtc_code="P0301",
                description_tr="Silindir 1 ateşleme hatası",
                recommended_action="Kontrol",
                owner_name="Ayşe",
            )
        )
        db.add(
            VehicleDiagnostic(
                vehicle_id=other.id,
                dtc_code="P0420",
                description_tr="Katalizör verimi",
                recommended_action="Kontrol",
                owner_name="Başka Müşteri",
                created_at="2999-01-01T00:00:00+00:00",
            )
        )
        app = Appointment(
            vehicle_id=mine.id,
            slot_id=None,
            customer="Ayşe",
            idempotency_key="diag-app-1",
            confirmed=False,
        )
        db.add(app)
        db.commit()
        app_id = app.id

    spoken = []

    async def emit(event):
        pass

    async def send(frame):
        pass

    s = session_mod.VoiceSession(
        "test", emit, send, mode="outbound_diagnostic", appointment_id=app_id
    )

    async def fake_reply(text, start=None):
        spoken.append(text)

    monkeypatch.setattr(s, "reply", fake_reply)
    await s.start()
    await s.close()
    assert "P0301" in spoken[0]
    # En yeni kayıt başka müşterinin aracına ait: okunmamalı.
    assert "P0420" not in spoken[0]


# ---------------------------------------------------------------- Madde 2
def _reminder_setup(db):
    v = Vehicle(description="Opel Astra", plate="34 OPL 11")
    db.add(v)
    db.flush()
    s = _slot(db, days=3)
    app = Appointment(
        vehicle_id=v.id,
        slot_id=s.id,
        customer="Kemal",
        idempotency_key="rem-1",
        confirmed=True,
    )
    db.add(app)
    db.flush()
    call = OutboundCall(
        appointment_id=app.id, phone="05321112233", customer="Kemal", status="in-progress"
    )
    db.add(call)
    db.commit()
    return app.id, call.id


@pytest.mark.parametrize(
    "text",
    ["Saat uygun değil, gelemiyorum", "evet gelemiyorum", "Saat uygun değil"],
)
async def test_reminder_negative_wins_over_confirm(env, text):
    with env() as db:
        app_id, call_id = _reminder_setup(db)
    d = Dialogue("c-rem", mode="outbound_reminder", appointment_id=app_id, call_id=call_id)
    ans = await d.answer(text)
    assert d.outbound_outcome == "cancelled"
    assert "iptal" in ans
    with env() as db:
        assert db.get(Appointment, app_id).status == "cancelled"
        assert db.get(OutboundCall, call_id).outcome == "cancelled"


async def test_reminder_positive_still_confirms(env):
    with env() as db:
        app_id, call_id = _reminder_setup(db)
    d = Dialogue("c-rem2", mode="outbound_reminder", appointment_id=app_id, call_id=call_id)
    ans = await d.answer("Evet geliyorum")
    assert d.outbound_outcome == "confirmed" and d.outbound_persisted is True
    assert "teyit edildi" in ans


async def test_reminder_persist_failure_not_reported_as_success(env, monkeypatch, caplog):
    with env() as db:
        app_id, call_id = _reminder_setup(db)

    def boom(*a, **k):
        raise RuntimeError("db kilitli")

    monkeypatch.setattr("backend.outbound.complete_outbound_call", boom)
    d = Dialogue("c-rem3", mode="outbound_reminder", appointment_id=app_id, call_id=call_id)
    with caplog.at_level(logging.ERROR):
        ans = await d.answer("evet")
    assert d.outbound_persisted is False
    assert "teyit edildi" not in ans
    assert "kaydedemedim" in ans
    assert "kaydedilemedi" in caplog.text


async def test_reminder_without_call_id_persists_on_appointment(env):
    with env() as db:
        app_id, _ = _reminder_setup(db)
    d = Dialogue("c-rem4", mode="outbound_reminder", appointment_id=app_id)
    await d.answer("hayır gelemem")
    assert d.outbound_persisted is True
    with env() as db:
        assert db.get(Appointment, app_id).status == "cancelled"


async def test_reminder_without_any_id_says_so(env):
    d = Dialogue("c-rem5", mode="outbound_reminder")
    ans = await d.answer("evet")
    assert d.outbound_persisted is False
    assert "teyit edildi" not in ans and "kaydedemedim" in ans


# ---------------------------------------------------------------- Madde 3
def test_can_send_real_notifications_follows_provider(provider_restore):
    set_notification_provider(MockNotificationProvider())
    assert can_send_real_notifications() is False
    set_notification_provider(FakeRealProvider())
    assert can_send_real_notifications() is True


async def test_voice_booking_without_provider_makes_no_sms_claim(env, provider_restore):
    set_notification_provider(MockNotificationProvider())
    with env() as db:
        d = _booking_dialogue(db)
    d.customer_phone = "05321112233"  # telefon bilinse bile sağlayıcı yok
    ans = await d.answer("Evet, onaylıyorum.")
    assert ans == "Randevunuz oluşturuldu. İyi günler dilerim."


async def test_voice_booking_real_provider_needs_phone(env, provider_restore):
    set_notification_provider(FakeRealProvider())
    with env() as db:
        d = _booking_dialogue(db)
    ans = await d.answer("Evet, onaylıyorum.")  # telefon yok
    assert "SMS" not in ans and ans.endswith("İyi günler dilerim.")


async def test_voice_booking_real_provider_and_phone_mentions_sms(env, provider_restore):
    set_notification_provider(FakeRealProvider())
    with env() as db:
        d = _booking_dialogue(db)
    d.customer_phone = "05321112233"
    ans = await d.answer("Evet, onaylıyorum.")
    assert "SMS" in ans


async def test_dtmf_booking_without_provider_makes_no_sms_claim(env, provider_restore):
    set_notification_provider(MockNotificationProvider())
    with env() as db:
        d = _booking_dialogue(db, "c-dtmf-sms")
        ans = await d.handle_dtmf("1", db)
    assert "SMS" not in ans and "WhatsApp" not in ans
    assert "onaylandı ve oluşturuldu" in ans


async def test_corporate_voice_booking_without_provider_makes_no_sms_claim(
    env, provider_restore
):
    set_notification_provider(MockNotificationProvider())
    with env() as db:
        acc = CorporateAccount(name="Özdemir Galeri", tax_id="123", discount_percent=10)
        db.add(acc)
        db.flush()
        d = _booking_dialogue(db, "c-corp")
        d.corporate_account_id = acc.id
        d.corporate_account_name = acc.name
    ans = await d.answer("Evet, onaylıyorum.")
    assert "kurumsal cari hesabınıza işlenerek oluşturuldu" in ans
    assert "SMS" not in ans and "WhatsApp" not in ans


def test_mock_provider_marks_outbox_simulated_real_marks_sent(env, provider_restore):
    from backend.db import NotificationOutbox

    with env() as db:
        v = Vehicle(description="Dacia Duster", plate="34 DCA 01")
        db.add(v)
        db.flush()
        s = _slot(db, days=4)
        set_notification_provider(MockNotificationProvider())
        book(db, slot_id=s.id, vehicle_id=v.id, customer="A", idempotency_key="n-1", confirmed=True)
        n = db.scalars(select(NotificationOutbox)).first()
        assert n.status == "simulated" and n.sent_at is None
        n.status = "pending"
        db.commit()
        set_notification_provider(FakeRealProvider())
        dispatch_pending_notifications(db)
        db.refresh(n)
        assert n.status == "sent" and n.sent_at is not None


# ---------------------------------------------------------------- Madde 4
def test_mock_ami_is_not_real_and_flag_is_honored():
    previous = get_ami_client()
    try:
        set_ami_client(MockAMIClient())
        assert is_real_ami() is False
        fake = MockAMIClient()
        fake.is_real = True
        set_ami_client(fake)
        assert is_real_ami() is True
    finally:
        set_ami_client(previous)


async def test_dtmf_zero_with_mock_ami_does_not_claim_transfer(env):
    previous = get_ami_client()
    set_ami_client(MockAMIClient())
    try:
        with env() as db:
            conv = Conversation(channel="web")
            db.add(conv)
            db.commit()
            d = Dialogue(conv.id)
            ans = await d.handle_dtmf("0", db)
            assert d.transfer_requested is False and d.done is True
            assert "aktarıyorum" not in ans
            assert "Şu anda operatöre bağlayamıyorum" in ans
            db.refresh(conv)
            assert conv.status == "follow_up"
            assert "geri aranacak" in conv.operator_notes
    finally:
        set_ami_client(previous)


async def test_speech_transfer_with_mock_ami_does_not_claim_transfer(env):
    previous = get_ami_client()
    set_ami_client(MockAMIClient())
    try:
        d = Dialogue("c-speech-op")
        ans = await d.answer("beni bir operatöre bağlar mısınız?")
        assert d.transfer_requested is False and d.done is True
        assert "aktarıyorum" not in ans and "bağlayamıyorum" in ans
    finally:
        set_ami_client(previous)


async def test_failed_ami_marks_transfer_failed():
    from backend.transfer import initiate_operator_transfer

    class Broken(MockAMIClient):
        async def setvar(self, *a, **k):
            raise ConnectionError("AMI kapalı")

    with sessionmaker(create_engine("sqlite:///:memory:"))() as db:
        Base.metadata.create_all(db.get_bind())
        t = await initiate_operator_transfer(db, caller_channel="PJSIP/x-1", ami_client=Broken())
        assert t.status == "failed"


async def test_outbound_originate_with_mock_ami_is_simulated(env):
    previous = get_ami_client()
    set_ami_client(MockAMIClient())
    try:
        with env() as db:
            app_id, _ = _reminder_setup(db)
            # Önceki testin çağrı kaydı aktif sayılmasın.
            db.query(OutboundCall).delete()
            db.commit()
            call = await initiate_outbound_call(db, appointment_id=app_id, phone="05321112233")
            assert call.status == "simulated"
    finally:
        set_ami_client(previous)


def test_ami_status_endpoint_reports_simulated(monkeypatch):
    previous = get_ami_client()
    set_ami_client(MockAMIClient())
    monkeypatch.setattr(main.settings, "admin_password", "test-password")
    try:
        c = TestClient(main.app)
        body = c.get("/api/outbound/ami-status", auth=("admin", "test-password")).json()
        assert body["connected"] is False and body["simulated"] is True
    finally:
        set_ami_client(previous)


# ---------------------------------------------------------------- Madde 5
def test_outbound_session_context_lookup(env):
    with env() as db:
        app_id, call_id = _reminder_setup(db)
        ctx = get_outbound_session_context(db, call_id)
        assert ctx == {"mode": "outbound_reminder", "appointment_id": app_id, "call_id": call_id}
        assert get_outbound_session_context(db, "00000000-0000-0000-0000-000000000000") is None


# ---------------------------------------------------------------- Madde 6
def _corporate_appointment(db, key="corp-1"):
    acc = CorporateAccount(name="Galeri X", tax_id=key, discount_percent=10)
    v = Vehicle(description="BMW 320i " + key, plate="34 BMW 01")
    db.add_all([acc, v])
    db.flush()
    db.add(Quote(vehicle_id=v.id, amount_kurus=100000))
    s = _slot(db, days=5, hour=11)
    db.commit()
    app = book(
        db,
        slot_id=s.id,
        vehicle_id=v.id,
        customer="Müşteri",
        idempotency_key=key,
        confirmed=True,
        corporate_account_id=acc.id,
    )
    return acc.id, app


def test_cancel_reverses_corporate_charge_once(env):
    with env() as db:
        acc_id, app = _corporate_appointment(db)
        assert app.billed_amount_kurus == 90000
        assert db.get(CorporateAccount, acc_id).balance_kurus == 90000
        cancel_appointment(db, app)
        cancel_appointment(db, app)  # ikinci çağrı iade tekrarlamaz
        acc = db.get(CorporateAccount, acc_id)
        assert acc.balance_kurus == 0
        rows = db.scalars(
            select(CorporateLedger).where(
                CorporateLedger.appointment_id == app.id,
                CorporateLedger.entry_type == "reversal",
            )
        ).all()
        assert len(rows) == 1 and rows[0].amount_kurus == -90000
        assert rows[0].balance_after_kurus == 0
        assert app.status == "cancelled" and app.slot_id is None


def test_outbound_cancel_and_dialogue_cancel_use_reversal(env):
    with env() as db:
        acc_id, app = _corporate_appointment(db, "corp-2")
        call = OutboundCall(appointment_id=app.id, phone="0532", customer="x", status="in-progress")
        db.add(call)
        db.commit()
        complete_outbound_call(db, call_id=call.id, outcome="cancelled")
        assert db.get(CorporateAccount, acc_id).balance_kurus == 0
        # Aynı randevu tekrar iptal edilirse bakiye eksiye düşmez.
        d = Dialogue("c-x", mode="outbound_reminder", appointment_id=app.id)
        assert d._persist_outbound(db, "cancelled") is True
        assert db.get(CorporateAccount, acc_id).balance_kurus == 0


def test_cancel_api_reverses_corporate_charge(env, monkeypatch):
    monkeypatch.setattr(main, "Session", env)
    monkeypatch.setattr(main.settings, "admin_password", "test-password")
    with env() as db:
        acc_id, app = _corporate_appointment(db, "corp-3")
        app_id = app.id
    c = TestClient(main.app)
    r = c.post(f"/api/appointments/{app_id}/cancel", auth=("admin", "test-password"))
    assert r.status_code == 200
    c.post(f"/api/appointments/{app_id}/cancel", auth=("admin", "test-password"))
    with env() as db:
        assert db.get(CorporateAccount, acc_id).balance_kurus == 0


# ---------------------------------------------------------------- Madde 8
async def test_dtmf_tasks_keep_reference_log_errors_and_serialize(env, monkeypatch, caplog):
    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(models, "vad", Vad())

    async def emit(e):
        pass

    async def send(f):
        pass

    s = session_mod.VoiceSession("test", emit, send)
    order = []

    async def slow(digit):
        order.append(("start", digit))
        await asyncio.sleep(0.02)
        order.append(("end", digit))
        if digit == "9":
            raise RuntimeError("dtmf hata")

    monkeypatch.setattr(s, "_handle_dtmf_locked", slow)
    with caplog.at_level(logging.ERROR):
        t1 = s.schedule_dtmf("1")
        t2 = s.schedule_dtmf("9")
        assert t1 in s._dtmf_tasks and t2 in s._dtmf_tasks
        await asyncio.gather(t1, t2, return_exceptions=True)
        await asyncio.sleep(0)
    assert order == [("start", "1"), ("end", "1"), ("start", "9"), ("end", "9")]
    assert not s._dtmf_tasks
    assert "DTMF işlenemedi" in caplog.text
    await s.close()


async def test_llm_timeout_returns_unclear_answer(env, monkeypatch):
    async def slow_chat(messages):
        await asyncio.sleep(5)
        yield "{}"

    monkeypatch.setattr(models, "chat", slow_chat)
    monkeypatch.setattr(settings, "llm_timeout_sec", 0.05)
    d = Dialogue("c-llm")
    ans = await d.answer("Toyota Corolla için randevu")
    assert "anlayamadım" in ans
    assert d.retries == 1


async def test_turn_emits_stt_and_llm_metrics(env, monkeypatch):
    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(models, "vad", Vad())
    events = []

    async def emit(e):
        events.append(e)

    async def send(f):
        pass

    s = session_mod.VoiceSession("test", emit, send)

    async def transcribe(audio):
        return "merhaba"

    async def answer(text):
        models.last_llm_metrics = {"llm_first_token_ms": 12.0, "llm_total_ms": 34.0}
        return "Merhaba"

    async def reply(text, start=None):
        pass

    monkeypatch.setattr(models, "transcribe", transcribe)
    monkeypatch.setattr(s.dialogue, "answer", answer)
    monkeypatch.setattr(s, "reply", reply)
    await s.process(np.ones(1600, np.float32) * 0.1)
    m = [e for e in events if e.get("type") == "metrics"]
    assert len(m) == 1
    assert m[0]["llm_first_token_ms"] == 12.0 and m[0]["llm_total_ms"] == 34.0
    assert m[0]["stt_ms"] >= 0
    await s.close()


def test_models_load_blocked_by_active_session_not_only_full_capacity(monkeypatch):
    monkeypatch.setattr(main.settings, "admin_password", "test-password")
    main.active._active_sessions.add("test-call")
    try:
        assert main.active.locked() is False
        c = TestClient(main.app)
        r = c.post("/api/models/load", auth=("admin", "test-password"))
        assert r.status_code == 409
    finally:
        main.active._active_sessions.discard("test-call")


# ---------------------------------------------------------------- Madde 9
async def test_vehicle_match_ignores_empty_candidate(env, monkeypatch):
    with env() as db:
        db.add(Vehicle(description="Toyota Corolla 1.5 Vision", plate="34 TYT 55"))
        db.add(Vehicle(description=" . ", plate="34 BOS 00"))  # normalize sonrası boş kalır
        db.commit()

    async def chat(messages):
        yield json.dumps({"customer": "Ali Veli", "vehicle_description": "Toyota Corolla"})

    monkeypatch.setattr(models, "chat", chat)
    d = Dialogue("c-veh")
    ans = await d.answer("Ali Veli, Toyota Corolla")
    # Boş açıklamalı araç her şeyle eşleşmemeli: tek eşleşme kalır ve seçenekler sunulur.
    assert "Araç kaydınızı bulamadım" not in ans
    assert d.vehicle is not None


async def test_vehicle_match_empty_needle_matches_nothing(env, monkeypatch):
    with env() as db:
        db.add(Vehicle(description="Toyota Corolla 1.5 Vision", plate="34 TYT 55"))
        db.commit()

    async def chat(messages):
        yield json.dumps({"customer": "Ali Veli", "vehicle_description": " . "})

    monkeypatch.setattr(models, "chat", chat)
    d = Dialogue("c-veh2")
    ans = await d.answer("Ali Veli")
    assert "Araç kaydınızı bulamadım" in ans
    assert d.vehicle is None


# ---------------------------------------------------------------- Madde 10
def test_operator_register_call_defaults_are_none(monkeypatch):
    monkeypatch.setattr(main.settings, "admin_password", "test-password")
    c = TestClient(main.app)
    r = c.post(
        "/api/operator/register-call",
        auth=("admin", "test-password"),
        json={"session_id": "s-none", "caller_id": "0532"},
    )
    sess = r.json()["session"]
    assert sess["mos_score"] is None and sess["rtf"] is None
