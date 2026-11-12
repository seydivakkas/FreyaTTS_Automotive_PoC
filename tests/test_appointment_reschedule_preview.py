from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend import db as db_module
from backend.config import settings
from backend.db import Appointment, Base, BaySchedule, InspectionBay, InspectionLift, Slot, Technician, Vehicle
from backend.routers.crm import router


@pytest.fixture
def calendar(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'calendar.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(db_module, "Session", sessions)
    monkeypatch.setattr(settings, "admin_password", "calendar-test")
    app = FastAPI()
    app.include_router(router)
    yield app, sessions, ("admin", "calendar-test")
    engine.dispose()


def seed(sessions):
    source, target, alternative, other_source, appointment = (str(uuid4()) for _ in range(5))
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    with sessions.begin() as db:
        db.add(Vehicle(id="vehicle", description="Test aracı"))
        for index, slot_id in enumerate((source, target, alternative, other_source)):
            db.add(Slot(id=slot_id, starts_at=(start + timedelta(hours=2 * index)).isoformat()))
        db.add(Appointment(
            id=appointment, slot_id=source, vehicle_id="vehicle", customer="synthetic",
            idempotency_key=appointment, status="confirmed", confirmed=True,
        ))
    return source, target, alternative, other_source, appointment


def test_preview_is_read_only_and_conflict_offers_current_alternative(calendar):
    app, sessions, auth = calendar
    source, target, alternative, _, appointment = seed(sessions)
    client = TestClient(app)
    base = f"/api/appointments/{appointment}"
    params = {"target_slot_id": target}
    assert client.get(base + "/reschedule-preview", params=params).status_code == 401
    preview = client.get(base + "/reschedule-preview", params=params, auth=auth).json()
    assert preview["source"]["id"] == source and preview["target"]["id"] == target
    assert preview["status"] == "available" and preview["lift_status"] == "unknown"
    with sessions.begin() as db:
        assert db.get(Appointment, appointment).slot_id == source
        assert db.scalar(select(func.count()).select_from(InspectionLift)) == 0
        assert db.scalar(select(func.count()).select_from(InspectionBay)) == 0
        db.add(Appointment(
            slot_id=target, vehicle_id="vehicle", customer="racing",
            idempotency_key="racing", status="confirmed", confirmed=True,
        ))
    result = client.post(base + "/reschedule", json={**params, "preview_version": preview["preview_version"]}, auth=auth)
    assert result.status_code == 409
    updated = client.get(base + "/reschedule-preview", params=params, auth=auth).json()
    assert updated["status"] == "occupied" and updated["alternatives"][0]["id"] == alternative
    with sessions() as db:
        assert db.get(Appointment, appointment).slot_id == source


def test_confirm_rechecks_capacity_and_rejects_a_stale_source(calendar):
    app, sessions, auth = calendar
    source, target, alternative, _, appointment = seed(sessions)
    client = TestClient(app, auth=auth)
    base = f"/api/appointments/{appointment}"
    params = {"target_slot_id": target}
    with sessions.begin() as db:
        db.add(InspectionLift(id="lift", lift_number=1, name="Test lift", status="idle"))
    preview = client.get(base + "/reschedule-preview", params=params).json()
    body = {**params, "preview_version": preview["preview_version"]}
    assert preview["lift_status"] == "available"
    with sessions.begin() as db:
        db.get(InspectionLift, "lift").status = "maintenance"
    assert client.post(base + "/reschedule", json=body).status_code == 409
    assert client.get(base + "/reschedule-preview", params=params).json()["lift_status"] == "conflict"
    with sessions.begin() as db:
        assert db.get(Appointment, appointment).slot_id == source
        db.get(InspectionLift, "lift").status = "idle"
        db.get(Appointment, appointment).slot_id = alternative
    assert client.post(base + "/reschedule", json=body).status_code == 409
    updated = client.get(base + "/reschedule-preview", params=params).json()
    assert updated["source"]["id"] == alternative
    assert client.post(base + "/reschedule", json={**params, "preview_version": updated["preview_version"]}).status_code == 200


def test_active_station_assignment_prevents_detaching_appointment(calendar):
    app, sessions, auth = calendar
    source, target, _, _, appointment = seed(sessions)
    with sessions.begin() as db:
        bay = InspectionBay(id="station", name="Test station", bay_number=1)
        db.add(bay)
        start = datetime.fromisoformat(db.get(Slot, source).starts_at)
        db.add(BaySchedule(
            appointment_id=appointment, bay_id=bay.id, stage_name="Test stage",
            starts_at=start.isoformat(), ends_at=(start + timedelta(minutes=15)).isoformat(),
        ))
    client = TestClient(app, auth=auth)
    base = f"/api/appointments/{appointment}"
    params = {"target_slot_id": target}
    preview = client.get(base + "/reschedule-preview", params=params).json()
    assert preview["status"] == "assigned" and preview["lift_status"] == "conflict"
    assert client.post(base + "/reschedule", json=params).status_code == 409
    with sessions() as db:
        assert db.get(Appointment, appointment).slot_id == source
        assert db.scalar(select(func.count()).select_from(Technician)) == 0


def test_concurrent_confirmations_admit_one_move(calendar):
    app, sessions, auth = calendar
    _, target, _, other_source, appointment = seed(sessions)
    other = str(uuid4())
    with sessions.begin() as db:
        db.add(Appointment(
            id=other, slot_id=other_source, vehicle_id="vehicle", customer="other",
            idempotency_key=other, status="confirmed", confirmed=True,
        ))

    def confirm(id):
        client = TestClient(app, auth=auth)
        base = f"/api/appointments/{id}"
        params = {"target_slot_id": target}
        version = client.get(base + "/reschedule-preview", params=params).json()["preview_version"]
        return client.post(base + "/reschedule", json={**params, "preview_version": version}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm, (appointment, other))) == [200, 409]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.slot_id == target)) == 1
