import json
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.db import (
    Appointment, Base, Conversation, FqiciRun, FqiciScope, OperatorTransfer, Slot,
    SupervisorTrace, Turn, Vehicle,
)
from backend.routers import supervisor


@pytest.fixture
def view_api(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'quality-views.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(supervisor, "Session", sessions)
    monkeypatch.setattr(settings, "admin_password", "view-test")
    app = FastAPI()
    app.include_router(supervisor.router)
    with TestClient(app) as client:
        yield client, sessions, ("admin", "view-test")
    engine.dispose()


def test_conversation_detail_uses_exact_links_and_masks_purged_rows(view_api):
    client, sessions, auth = view_api
    first, second, missing = (str(uuid4()) for _ in range(3))
    with sessions.begin() as db:
        db.add_all([
            Conversation(id=first, channel="web"),
            Conversation(id=second, channel="asterisk"),
            Vehicle(id="vehicle", description="Synthetic vehicle"),
            Slot(id="slot", starts_at="2026-11-13T10:00:00+00:00"),
        ])
        db.flush()
        db.add_all([
            Appointment(id="linked", slot_id="slot", vehicle_id="vehicle",
                        idempotency_key=first, customer="private customer", confirmed=True),
            Appointment(id="unlinked", vehicle_id="vehicle", idempotency_key="other-key",
                        customer="private customer", confirmed=True),
            OperatorTransfer(id="transfer", conversation_id=first, status="accepted", summary="private summary"),
            Turn(conversation_id=first, role="user", text="Randevu istiyorum"),
            SupervisorTrace(id="trace", conversation_id=first, payload=json.dumps({
                "decision": {"route_state": "ROUTED", "candidates": [{"intent_id": "booking_create"}],
                             "reason_codes": ["intent.matched"]},
                "outcome": "legacy_delegated", "transcript": "private trace",
            })),
        ])
    path = f"/api/supervisor/conversations/{first}/detail"
    assert client.get(path).status_code == 401
    response = client.get(path, auth=auth)
    assert response.status_code == 200
    data = response.json()
    assert data["appointment"] == {
        "id": "linked", "status": "confirmed", "starts_at": "2026-11-13T10:00:00+00:00",
    }
    assert [item["id"] for item in data["transfers"]] == ["transfer"]
    assert data["traces"][0]["intents"] == ["booking_create"]
    assert data["turns"][0]["text"] == "Randevu istiyorum"
    assert "private" not in response.text
    other = client.get(f"/api/supervisor/conversations/{second}/detail", auth=auth).json()
    assert other["appointment"] is None and other["transfers"] == [] and other["traces"] == []
    assert client.get(f"/api/supervisor/conversations/{missing}/detail", auth=auth).status_code == 404
    with sessions.begin() as db:
        db.get(Conversation, first).status = "purged"
    purged = client.get(path, auth=auth).json()
    assert purged["turns"] == purged["traces"] == purged["transfers"] == []
    assert purged["appointment"] is None


def test_fqici_queue_includes_deferred_and_expired_work_without_evidence(view_api, monkeypatch):
    from backend.supervisor import views

    client, sessions, auth = view_api
    monkeypatch.setattr(settings, "fqici_enabled", True)
    monkeypatch.setattr(views.time, "time_ns", lambda: 100_000_000_000)
    active, deferred, purged = (str(uuid4()) for _ in range(3))
    with sessions.begin() as db:
        db.add_all([
            Conversation(id=active, channel="web"), Conversation(id=deferred, channel="asterisk"),
            Conversation(id=purged, channel="web", status="purged"),
        ])
        db.flush()
        db.add_all([
            FqiciScope(id=active, transport="WEB", origin="UNKNOWN", terminal_seen=True),
            FqiciScope(id=deferred, transport="AUDIOSOCKET", origin="SYNTHETIC",
                       terminal_seen=True, ready_at_ms=99_000, dirty_since_ms=89_000),
            FqiciScope(id=purged, transport="WEB", origin="DEMO", ready_at_ms=1, dirty_since_ms=1),
        ])
        db.flush()
        db.add(FqiciRun(
            id="expired", scope_id=active, evidence_hash="private hash", rule_version="rules-v1",
            event_ids='["private evidence"]', state="RUNNING", fence=2, lease_until_ms=98_000,
            created_at_ms=95_000, available_at_ms=95_000,
        ))
    path = "/api/supervisor/fqici-queue"
    assert client.get(path).status_code == 401
    response = client.get(path, auth=auth)
    assert response.status_code == 200
    data = response.json()
    assert data["worker_status"] == "NOT_CONNECTED"
    assert data["physical_sip_status"] == "HOLD"
    assert data["counts"] == {"RUNNING": 1}
    assert data["deferred_count"] == 1 and data["oldest_wait_ms"] == 11_000
    assert data["deferred"][0]["origin"] == "SYNTHETIC"
    assert data["runs"][0]["lease_expired"] is True and data["runs"][0]["attempts"] == 2
    assert "private" not in response.text and purged not in response.text

    detail = client.get(f"/api/supervisor/conversations/{active}/detail", auth=auth).json()
    assert detail["fqici"]["runs"][0]["id"] == "expired"
    FqiciRun.__table__.drop(sessions.kw["bind"])
    unavailable = client.get(path, auth=auth).json()
    assert unavailable["store"] == "UNAVAILABLE" and unavailable["deferred_count"] is None
