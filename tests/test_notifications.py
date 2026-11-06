from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import (
    Base,
    Vehicle,
    Slot,
    Quote,
    CorporateAccount,
    NotificationOutbox,
    book,
)
from backend import main
from backend.notifications import (
    get_notification_provider,
    set_notification_provider,
    MockNotificationProvider,
    dispatch_pending_notifications,
    retry_notification,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "notif_test.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "Session", sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(main.settings, "admin_password", "test-password")

    provider = MockNotificationProvider()
    set_notification_provider(provider)

    c = TestClient(main.app)
    yield c, engine, provider
    c.close()
    engine.dispose()


def test_customer_appointment_notification(client):
    c, engine, provider = client
    auth = ("admin", "test-password")
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    with SessionLocal() as db:
        v = Vehicle(description="Volkswagen Passat 1.5 TSI", plate="34 ABC 123")
        db.add(v)
        slot_time = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
            hour=14, minute=30, second=0, microsecond=0
        )
        s = Slot(starts_at=slot_time.isoformat(), duration_minutes=45)
        db.add(s)
        db.commit()

        # Book standard appointment
        app = book(
            db,
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Kemal Sunal",
            customer_phone="0532 999 88 77",
            idempotency_key="book-notif-001",
            confirmed=True,
        )

        # Check outbox record created
        notifs = db.query(NotificationOutbox).filter_by(appointment_id=app.id).all()
        assert len(notifs) == 1
        n = notifs[0]
        assert n.recipient_type == "customer"
        assert n.channel == "sms"
        assert n.recipient == "0532 999 88 77"
        assert "Kemal Sunal" in n.message
        assert "Volkswagen Passat" in n.message
        assert "14:30" in n.message
        assert app.id[:8].upper() in n.message
        # Mock sağlayıcı gerçek iletim yapmaz: "sent" değil "simulated".
        assert n.status in ("pending", "simulated")


def test_corporate_dealership_notification(client):
    c, engine, provider = client
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    with SessionLocal() as db:
        v = Vehicle(description="Renault Megane Icon", plate="06 ANK 06")
        db.add(v)
        db.flush()
        slot_time = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
            hour=11, minute=0, second=0, microsecond=0
        )
        s = Slot(starts_at=slot_time.isoformat(), duration_minutes=30)
        db.add(s)
        q = Quote(vehicle_id=v.id, amount_kurus=200000)  # 2.000 TL
        db.add(q)
        acc = CorporateAccount(
            name="Başkent Oto Galeri",
            tax_id="1234567890",
            phone="0542 111 22 33",
            credit_limit_kurus=10000000,
            discount_percent=20,  # 2.000 TL -> 1.600 TL
            balance_kurus=500000,  # 5.000 TL
        )
        db.add(acc)
        db.commit()

        app = book(
            db,
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Caner Erkin",
            customer_phone="0555 444 33 22",
            idempotency_key="corp-notif-001",
            confirmed=True,
            corporate_account_id=acc.id,
        )

        # Check both customer and corporate notifications created in outbox
        notifs = (
            db.query(NotificationOutbox)
            .filter_by(appointment_id=app.id)
            .order_by(NotificationOutbox.recipient_type)
            .all()
        )
        assert len(notifs) == 2

        # Corporate outbox record
        corp_n = next(n for n in notifs if n.recipient_type == "corporate")
        assert corp_n.channel == "whatsapp"
        assert corp_n.recipient == "0542 111 22 33"
        assert "Başkent Oto Galeri" in corp_n.message
        assert "Caner Erkin" in corp_n.message
        assert "1600 TL" in corp_n.message or "1.600 TL" in corp_n.message or "1600" in corp_n.message
        # Balance was 5000 + 1600 = 6600 TL
        assert "6600" in corp_n.message

        # Customer outbox record
        cust_n = next(n for n in notifs if n.recipient_type == "customer")
        assert cust_n.channel == "sms"
        assert cust_n.recipient == "0555 444 33 22"


def test_notification_delivery_and_retry(client):
    c, engine, provider = client
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    with SessionLocal() as db:
        v = Vehicle(description="Fiat Egea", plate="34 FGT 44")
        db.add(v)
        slot_time = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        s = Slot(starts_at=slot_time.isoformat(), duration_minutes=30)
        db.add(s)
        db.commit()

        # Simulate provider failure
        provider.fail_next = True
        provider.fail_reason = "Netgsm SMS Gateway unreachable"

        app = book(
            db,
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Fatma Girik",
            idempotency_key="fail-retry-001",
            confirmed=True,
        )

        n = db.query(NotificationOutbox).filter_by(appointment_id=app.id).first()
        # Should be pending because automatic dispatch failed
        assert n.status == "pending"
        assert n.attempts == 1
        assert "Netgsm SMS Gateway" in n.last_error

        # Now provider recovered, retry
        retried = retry_notification(db, n.id)
        assert retried.status == "simulated"
        assert retried.sent_at is None
        assert retried.last_error is None


def test_notifications_api_endpoints(client):
    c, engine, provider = client
    auth = ("admin", "test-password")

    # 1. Create appointment via API
    v = c.post(
        "/api/vehicles",
        auth=auth,
        json={"description": "Dacia Duster", "plate": "35 DAC 35"},
    ).json()
    slot_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    s = c.post("/api/slots", auth=auth, json={"starts_at": slot_time}).json()

    book_res = c.post(
        "/api/appointments",
        auth=auth,
        json={
            "slot_id": s["id"],
            "vehicle_id": v["id"],
            "customer": "Şener Şen",
            "customer_phone": "0533 111 00 22",
            "idempotency_key": "api-book-notif-99",
            "confirmed": True,
        },
    )
    assert book_res.status_code == 200
    app_id = book_res.json()["id"]

    # 2. Query notifications list
    res = c.get("/api/notifications", auth=auth)
    assert res.status_code == 200
    items = res.json()
    assert len(items) >= 1
    my_notif = next((x for x in items if x["appointment_id"] == app_id), None)
    assert my_notif is not None
    assert my_notif["recipient"] == "0533 111 00 22"
    assert "Dacia Duster" in my_notif["message"]

    # 3. Filter by recipient_type
    res_cust = c.get("/api/notifications?recipient_type=customer", auth=auth)
    assert res_cust.status_code == 200
    assert all(x["recipient_type"] == "customer" for x in res_cust.json())

    # 4. Trigger dispatch API
    disp_res = c.post("/api/notifications/dispatch", auth=auth)
    assert disp_res.status_code == 200
    assert "dispatched_count" in disp_res.json()

    # 5. Retry endpoint
    retry_res = c.post(f"/api/notifications/{my_notif['id']}/retry", auth=auth)
    assert retry_res.status_code == 200
    assert retry_res.json()["status"] == "simulated"
