"""Tests for lift and queue management engine, capacity calculations, and speech assistant integration.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.db import (
    Base,
    Vehicle,
    Slot,
    Quote,
    Appointment,
    InspectionLift,
    InspectionQueue,
    book,
)
from backend import main
from backend.queue_lift import (
    PACKAGE_DEFINITIONS,
    match_package,
    seed_default_lifts,
    get_all_lifts,
    add_lift,
    set_lift_status,
    assign_lift,
    release_lift,
    enqueue_vehicle,
    get_queue,
    call_next_queue_item,
    get_lift_capacity_status,
    check_slot_lift_capacity,
)
from backend.dialogue import Dialogue


@pytest.fixture
def queue_lift_setup(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "queue_lift_test.db"),
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


def test_package_definitions_and_matching():
    # Verify standard durations
    assert PACKAGE_DEFINITIONS["motor_mekanik"]["duration_minutes"] == 30
    assert PACKAGE_DEFINITIONS["standart_ekspertiz"]["duration_minutes"] == 45
    assert PACKAGE_DEFINITIONS["full_kapsamli"]["duration_minutes"] == 60
    assert PACKAGE_DEFINITIONS["vip_premium"]["duration_minutes"] == 75

    # Test phrase matching
    m1 = match_package("Sadece motor mekanik ve dyno testi istiyorum")
    assert m1["key"] == "motor_mekanik"

    m2 = match_package("Full kapsamlı tam ekspertiz paketi olsun")
    assert m2["key"] == "full_kapsamli"

    m3 = match_package("VIP premium paket rica ediyorum")
    assert m3["key"] == "vip_premium"

    m_default = match_package("Genel bir kontrol randevusu")
    assert m_default["key"] == "standart_ekspertiz"


def test_lift_management_lifecycle(queue_lift_setup):
    client, SessionLocal, tmp_path = queue_lift_setup

    with SessionLocal() as db:
        # 1. Default seed lifts
        lifts = seed_default_lifts(db)
        assert len(lifts) == 2
        assert lifts[0].lift_number == 1
        assert lifts[0].status == "idle"

        # 2. Add custom 3rd lift
        lift3 = add_lift(db, name="Lift-3 (Yanal Kayma & Amortisör)", notes="Test istasyonu")
        assert lift3.lift_number == 3

        all_lifts = get_all_lifts(db)
        assert len(all_lifts) == 3

        # 3. Assign vehicle to Lift-1
        assigned = assign_lift(
            db,
            lift_id=lifts[0].id,
            plate="34 ABC 789",
            package_type="full_kapsamli",
        )
        assert assigned.status == "busy"
        assert assigned.current_vehicle_plate == "34 ABC 789"
        assert assigned.estimated_duration_min == 60

        # 4. Toggle maintenance on Lift-2
        maint = set_lift_status(db, lift_id=lifts[1].id, status="maintenance")
        assert maint.status == "maintenance"

        # 5. Release Lift-1
        released = release_lift(db, lift_id=lifts[0].id)
        assert released.status == "idle"
        assert released.current_vehicle_plate == ""


def test_queue_enqueue_and_call_next(queue_lift_setup):
    client, SessionLocal, tmp_path = queue_lift_setup

    with SessionLocal() as db:
        seed_default_lifts(db)
        lift1 = db.scalars(select(InspectionLift).where(InspectionLift.lift_number == 1)).first()

        # Enqueue 2 vehicles
        q1 = enqueue_vehicle(
            db,
            plate="06 ANK 01",
            customer="Ali Kaya",
            package_type="motor_mekanik",
        )
        q2 = enqueue_vehicle(
            db,
            plate="35 IZM 35",
            customer="Veli Can",
            package_type="full_kapsamli",
        )

        assert q1.queue_number == 101
        assert q2.queue_number == 102
        assert q1.status == "waiting"

        # Call next vehicle onto Lift-1
        called = call_next_queue_item(db, lift_id=lift1.id)
        assert called is not None
        assert called.id == q1.id
        assert called.status == "in_progress"
        assert called.lift_id == lift1.id

        # Verify Lift-1 is now busy with q1
        db.refresh(lift1)
        assert lift1.status == "busy"
        assert lift1.current_vehicle_plate == "06 ANK 01"

        # Release lift completes q1
        release_lift(db, lift_id=lift1.id)
        db.refresh(q1)
        assert q1.status == "completed"

        # Next call takes q2
        called2 = call_next_queue_item(db, lift_id=lift1.id)
        assert called2 is not None
        assert called2.id == q2.id


def test_lift_capacity_and_speech_announcement(queue_lift_setup):
    client, SessionLocal, tmp_path = queue_lift_setup

    with SessionLocal() as db:
        seed_default_lifts(db)
        lifts = db.scalars(select(InspectionLift).order_by(InspectionLift.lift_number)).all()
        lift1, lift2 = lifts[0], lifts[1]

        # Scenario 1: All lifts idle
        cap_idle = get_lift_capacity_status(db)
        assert cap_idle["all_lifts_busy"] is False
        assert cap_idle["idle_lifts"] == 2
        assert cap_idle["busy_lifts"] == 0
        assert cap_idle["estimated_wait_minutes"] == 0

        # Scenario 2: Make all active lifts busy
        assign_lift(db, lift_id=lift1.id, plate="34 DOL 01", package_type="standart_ekspertiz")
        assign_lift(db, lift_id=lift2.id, plate="34 DOL 02", package_type="full_kapsamli")

        cap_busy = get_lift_capacity_status(db)
        assert cap_busy["all_lifts_busy"] is True
        assert cap_busy["busy_lifts"] == 2
        assert cap_busy["idle_lifts"] == 0
        # Spoken assistant phrase requirement
        assert "Şu an 2 liftimiz dolu, en erken saat" in cap_busy["spoken_message"]
        assert cap_busy["estimated_wait_minutes"] > 0


def test_dialogue_speech_assistant_lift_announcement(queue_lift_setup):
    client, SessionLocal, tmp_path = queue_lift_setup

    now_utc = datetime.now(timezone.utc)
    future_1 = (now_utc + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    future_2 = (now_utc + timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)

    with SessionLocal() as db:
        seed_default_lifts(db)
        v = Vehicle(description="Volkswagen Golf 1.5 eTSI", plate="34 GLF 2023")
        db.add(v)
        db.flush()
        q = Quote(vehicle_id=v.id, amount_kurus=145000)
        db.add(q)
        s1 = Slot(starts_at=future_1.isoformat())
        s2 = Slot(starts_at=future_2.isoformat())
        db.add_all([s1, s2])
        db.commit()

        # Occupy both lifts in the center
        lifts = db.scalars(select(InspectionLift)).all()
        for l in lifts:
            assign_lift(db, lift_id=l.id, plate="34 MEV 99", package_type="full_kapsamli")

        state = Dialogue(conversation_id="conv-lift-test")
        state.customer = "Selin Hanım"
        state.vehicle = v.id
        state.options = [
            (s1.id, future_1.astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y saat %H:%M")),
            (s2.id, future_2.astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y saat %H:%M")),
        ]

        text_response = state.format_options(db)
        # Verify voice assistant informs customer about busy lifts
        assert "Şu an 2 liftimiz dolu, en erken saat" in text_response
        assert "1. seçenek" in text_response


def test_slot_lift_capacity_constraint(queue_lift_setup):
    client, SessionLocal, tmp_path = queue_lift_setup

    now_utc = datetime.now(timezone.utc)
    slot_time = (now_utc + timedelta(days=1, hours=10)).isoformat()

    with SessionLocal() as db:
        seed_default_lifts(db)  # 2 active lifts
        v = Vehicle(description="BMW 320i")
        db.add(v)
        db.commit()

        s1 = Slot(starts_at=slot_time, duration_minutes=30)
        db.add(s1)
        db.commit()

        # Slot capacity is initially open
        assert check_slot_lift_capacity(db, slot_time, 30) is True

        # Book 1st appointment
        book(
            db,
            slot_id=s1.id,
            vehicle_id=v.id,
            customer="Ahmet",
            idempotency_key="idemp_1",
            confirmed=True,
        )

        # Still have 1 active lift available
        assert check_slot_lift_capacity(db, slot_time, 30) is True


def test_api_lifts_and_queue(queue_lift_setup):
    client, SessionLocal, tmp_path = queue_lift_setup
    auth = ("admin", "test-pass")

    # 1. GET /api/packages
    r_pkgs = client.get("/api/packages", auth=auth)
    assert r_pkgs.status_code == 200
    pkgs = r_pkgs.json()
    assert len(pkgs) >= 4
    assert any(p["key"] == "motor_mekanik" for p in pkgs)

    # 2. GET /api/lifts
    r_lifts = client.get("/api/lifts", auth=auth)
    assert r_lifts.status_code == 200
    lifts = r_lifts.json()
    assert len(lifts) >= 2
    lift1_id = lifts[0]["id"]

    # 3. GET /api/lifts/capacity
    r_cap = client.get("/api/lifts/capacity", auth=auth)
    assert r_cap.status_code == 200
    assert "total_lifts" in r_cap.json()

    # 4. POST /api/queue (Add car to queue)
    r_q = client.post(
        "/api/queue",
        json={
            "plate": "34 QUE 100",
            "customer": "Mehmet Demir",
            "package_type": "motor_mekanik",
        },
        auth=auth,
    )
    assert r_q.status_code == 200
    q_data = r_q.json()
    assert q_data["plate"] == "34 QUE 100"
    assert q_data["status"] == "waiting"

    # 5. POST /api/lifts/{id}/call-next (Take from queue)
    r_call = client.post(f"/api/lifts/{lift1_id}/call-next", auth=auth)
    assert r_call.status_code == 200
    assert r_call.json()["assigned"] is True

    # 6. POST /api/lifts/{id}/release (Release lift)
    r_rel = client.post(f"/api/lifts/{lift1_id}/release", auth=auth)
    assert r_rel.status_code == 200
    assert r_rel.json()["status"] == "idle"

    # 7. POST /api/lifts/{id}/status (Put into maintenance)
    r_maint = client.post(
        f"/api/lifts/{lift1_id}/status",
        json={"status": "maintenance", "notes": "Yağ değişimi"},
        auth=auth,
    )
    assert r_maint.status_code == 200
    assert r_maint.json()["status"] == "maintenance"


def test_capacity_wait_is_null_when_no_active_lifts(queue_lift_setup):
    """Aktif lift yokken bekleme 999 değil None; hiç gerçek veri yoksa 18 dk gibi sabit değer de yok."""
    client, SessionLocal, tmp_path = queue_lift_setup
    with SessionLocal() as db:
        seed_default_lifts(db)
        for l in db.scalars(select(InspectionLift)).all():
            l.status = "maintenance"
        db.commit()
        cap = get_lift_capacity_status(db)
        assert cap["estimated_wait_minutes"] is None
        assert cap["earliest_available_time"] is None


def test_capacity_wait_computed_from_real_durations(queue_lift_setup):
    """Bekleme süresi gerçek lift/kuyruk sürelerinden hesaplanır (2 araç kuyruğunda sabit 18 yok)."""
    client, SessionLocal, tmp_path = queue_lift_setup
    with SessionLocal() as db:
        seed_default_lifts(db)
        lifts = db.scalars(select(InspectionLift).order_by(InspectionLift.lift_number)).all()
        assign_lift(db, lift_id=lifts[0].id, plate="34 AAA 01", package_type="standart_ekspertiz")
        assign_lift(db, lift_id=lifts[1].id, plate="34 AAA 02", package_type="standart_ekspertiz")
        # Kuyruğa 2 araç: süreleri DB'deki duration_minutes'tan gelir
        for n, mins in ((1, 30), (2, 30)):
            db.add(InspectionQueue(queue_number=n, plate=f"06 Q{n}", customer="X", duration_minutes=mins, status="waiting"))
        db.commit()
        cap = get_lift_capacity_status(db)
        assert cap["queue_waiting_count"] == 2
        assert cap["estimated_wait_minutes"] is not None
        assert cap["estimated_wait_minutes"] != 18
