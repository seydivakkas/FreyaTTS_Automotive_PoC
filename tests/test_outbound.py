import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base, Vehicle, Slot, Appointment, OutboundCall, book
from backend import main
from backend.ami import set_ami_client, MockAMIClient, get_ami_client
from backend.outbound import (
    initiate_outbound_call,
    complete_outbound_call,
    cancel_outbound_call,
    get_outbound_stats,
)
from backend.dialogue import Dialogue


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "outbound_test.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(main, "Session", SessionLocal)
    monkeypatch.setattr("backend.dialogue.Session", SessionLocal)
    monkeypatch.setattr(main.settings, "admin_password", "test-password")

    mock_ami = MockAMIClient()
    set_ami_client(mock_ami)

    c = TestClient(main.app)
    yield c, engine, mock_ami
    c.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_initiate_outbound_call_via_ami(client):
    c, engine, ami = client
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    with SessionLocal() as db:
        v = Vehicle(description="Toyota Corolla Hybrid", plate="34 TYT 99")
        db.add(v)
        slot_time = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
            hour=15, minute=0, second=0, microsecond=0
        )
        s = Slot(starts_at=slot_time.isoformat(), duration_minutes=30)
        db.add(s)
        db.commit()

        app = book(
            db,
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Metin Akpınar",
            customer_phone="0532 555 44 33",
            idempotency_key="outbound-book-01",
            confirmed=True,
        )

        # 1. Initiate outbound reminder call
        call = await initiate_outbound_call(
            db,
            appointment_id=app.id,
            phone="0532 555 44 33",
            call_type="reminder",
        )

        assert call.status == "in-progress"
        assert call.phone == "0532 555 44 33"
        assert call.call_type == "reminder"
        assert call.action_id.startswith("ami-act-")
        assert len(ami.calls) == 1
        ami_call = ami.calls[0]
        assert "05325554433" in ami_call["channel"]
        assert ami_call["variables"]["APPOINTMENT_ID"] == app.id
        assert ami_call["variables"]["CALL_TYPE"] == "reminder"

        # 2. Prevent duplicate active call
        with pytest.raises(ValueError, match="devam eden bir arama mevcut"):
            await initiate_outbound_call(
                db,
                appointment_id=app.id,
                phone="0532 555 44 33",
            )


@pytest.mark.asyncio
async def test_outbound_dialogue_customer_confirms(client):
    c, engine, ami = client
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    with SessionLocal() as db:
        v = Vehicle(description="Honda Civic", plate="06 HND 06")
        db.add(v)
        slot_time = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
            hour=10, minute=30, second=0, microsecond=0
        )
        s = Slot(starts_at=slot_time.isoformat(), duration_minutes=30)
        db.add(s)
        db.commit()

        app = book(
            db,
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Zeki Alasya",
            idempotency_key="outbound-book-02",
            confirmed=True,
        )

        call = await initiate_outbound_call(
            db,
            appointment_id=app.id,
            phone="0535 000 11 22",
        )

        # Simulate voice dialogue in outbound_reminder mode
        dlg = Dialogue(
            conversation_id="conv-outbound-01",
            mode="outbound_reminder",
            appointment_id=app.id,
            call_id=call.id,
        )

        # Customer confirms
        resp = await dlg.answer("Evet randevuma kesinlikle geliyorum, teşekkürler")
        assert "teyit edildi" in resp.lower()
        assert dlg.outbound_outcome == "confirmed"
        assert dlg.done is True

        # Check DB outcome updated
        db.expire_all()
        updated_call = db.get(OutboundCall, call.id)
        assert updated_call.status == "completed"
        assert updated_call.outcome == "confirmed"
        assert db.get(Appointment, app.id).status == "confirmed"


@pytest.mark.asyncio
async def test_outbound_dialogue_customer_cancels(client):
    c, engine, ami = client
    SessionLocal = sessionmaker(engine, expire_on_commit=False)

    with SessionLocal() as db:
        v = Vehicle(description="BMW 320i", plate="34 BMW 34")
        db.add(v)
        slot_time = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
            hour=16, minute=0, second=0, microsecond=0
        )
        s = Slot(starts_at=slot_time.isoformat(), duration_minutes=30)
        db.add(s)
        db.commit()

        app = book(
            db,
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Halit Akçatepe",
            idempotency_key="outbound-book-03",
            confirmed=True,
        )

        call = await initiate_outbound_call(
            db,
            appointment_id=app.id,
            phone="0532 111 22 33",
        )

        # Simulate voice dialogue in outbound_reminder mode
        dlg = Dialogue(
            conversation_id="conv-outbound-02",
            mode="outbound_reminder",
            appointment_id=app.id,
            call_id=call.id,
        )

        # Customer cancels
        resp = await dlg.answer("Maalesef şehir dışındayım, gelemeyeceğim, randevuyu iptal edelim")
        assert "iptal edilmiştir" in resp.lower()
        assert dlg.outbound_outcome == "cancelled"
        assert dlg.done is True

        # Check DB: Call completed with outcome=cancelled, Appointment status=cancelled, Slot released!
        db.expire_all()
        updated_call = db.get(OutboundCall, call.id)
        assert updated_call.status == "completed"
        assert updated_call.outcome == "cancelled"
        updated_app = db.get(Appointment, app.id)
        assert updated_app.status == "cancelled"
        assert updated_app.slot_id is None


def test_outbound_api_endpoints(client):
    c, engine, ami = client
    auth = ("admin", "test-password")

    # 1. Setup vehicle, slot, appointment
    v = c.post(
        "/api/vehicles", auth=auth, json={"description": "Peugeot 3008", "plate": "34 PGT 08"}
    ).json()
    slot_time = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    s = c.post("/api/slots", auth=auth, json={"starts_at": slot_time}).json()
    app = c.post(
        "/api/appointments",
        auth=auth,
        json={
            "slot_id": s["id"],
            "vehicle_id": v["id"],
            "customer": "Münir Özkul",
            "customer_phone": "0544 333 22 11",
            "idempotency_key": "api-outbound-99",
            "confirmed": True,
        },
    ).json()

    # 2. Check AMI status endpoint
    ami_st = c.get("/api/outbound/ami-status", auth=auth)
    assert ami_st.status_code == 200
    assert ami_st.json()["connected"] is True

    # 3. Trigger Outbound Call API
    call_res = c.post(
        "/api/outbound/call",
        auth=auth,
        json={
            "appointment_id": app["id"],
            "phone": "0544 333 22 11",
            "call_type": "reminder",
        },
    )
    assert call_res.status_code == 200
    call_data = call_res.json()
    assert call_data["appointment_id"] == app["id"]
    assert call_data["status"] == "in-progress"
    call_id = call_data["id"]

    # 4. List outbound calls API
    list_res = c.get("/api/outbound/calls", auth=auth)
    assert list_res.status_code == 200
    assert any(x["id"] == call_id for x in list_res.json())

    # 5. Complete call API (customer confirmed)
    complete_res = c.post(
        f"/api/outbound/calls/{call_id}/complete",
        auth=auth,
        json={"outcome": "confirmed", "notes": "Müşteri sözlü olarak onayladı"},
    )
    assert complete_res.status_code == 200
    assert complete_res.json()["status"] == "completed"
    assert complete_res.json()["outcome"] == "confirmed"

    # 6. Verify stats
    stats_res = c.get("/api/outbound/ami-status", auth=auth).json()["stats"]
    assert stats_res["confirmed"] >= 1
