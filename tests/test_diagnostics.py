"""Tests for OBD-II vehicle diagnostics, DTC registry, maintenance scheduling, and proactive alerts.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import (
    Base,
    Vehicle,
    Appointment,
    VehicleDiagnostic,
    OutboundCall,
    NotificationOutbox,
)
from backend import main
from backend.diagnostics import (
    lookup_dtc,
    calculate_maintenance_schedule,
    ingest_vehicle_telemetry,
    trigger_proactive_diagnostic_call,
    trigger_proactive_diagnostic_sms,
    resolve_diagnostic,
    DTC_REGISTRY,
)
from backend.dialogue import Dialogue
from backend.notifications import (
    set_notification_provider,
    MockNotificationProvider,
)
from backend.ami import set_ami_client, MockAMIClient


@pytest.fixture
def diag_setup(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "diag_test.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sm = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("backend.db.Session", sm)
    monkeypatch.setattr("backend.dialogue.Session", sm)
    monkeypatch.setattr(main.settings, "admin_password", "test-pass")

    ami_mock = MockAMIClient()
    set_ami_client(ami_mock)

    notif_mock = MockNotificationProvider()
    set_notification_provider(notif_mock)

    client = TestClient(main.app)
    yield client, sm, ami_mock, notif_mock
    client.close()
    engine.dispose()


def test_lookup_dtc():
    # Known critical code
    p301 = lookup_dtc("P0301")
    assert p301["dtc_code"] == "P0301"
    assert p301["severity"] == "critical"
    assert "1. Silindir" in p301["description_tr"]
    assert p301["system_category"] == "engine"

    # Known emissions warning
    p420 = lookup_dtc("p0420")
    assert p420["dtc_code"] == "P0420"
    assert p420["severity"] == "warning"
    assert "Katalitik" in p420["description_tr"]

    # Unknown code with valid prefix
    u999 = lookup_dtc("U0999")
    assert u999["dtc_code"] == "U0999"
    assert u999["system_category"] == "network"


def test_maintenance_schedule_calculation():
    # Normal mileage
    next_km, status = calculate_maintenance_schedule(10000, interval_km=15000)
    assert next_km == 15000
    assert status == "normal"

    # Due soon (<= 1500 km remaining)
    next_km, status = calculate_maintenance_schedule(29200, interval_km=15000)
    assert next_km == 30000
    assert status == "due_soon"

    # Overdue
    next_km, status = calculate_maintenance_schedule(30050, interval_km=15000)
    assert next_km == 45000 or status in ("due_soon", "overdue")


def test_telemetry_ingestion_api(diag_setup):
    client, SessionLocal, ami_mock, notif_mock = diag_setup
    auth = ("admin", "test-pass")

    with SessionLocal() as db:
        v = Vehicle(
            description="Volkswagen Golf 1.5 eTSI",
            plate="34 VWG 15",
            vin="WVWZZZCDZMW123456",
        )
        db.add(v)
        db.commit()
        vid = v.id

    # Ingest telemetry with P0301 and P0420
    payload = {
        "current_km": 44100,
        "dtc_codes": ["P0301", "P0420"],
        "source": "obd_dongle",
        "owner_name": "Serkan Yılmaz",
        "owner_phone": "05332221100",
    }
    res = client.post(f"/api/vehicles/{vid}/diagnostics", json=payload, auth=auth)
    assert res.status_code == 200, res.text
    records = res.json()
    assert len(records) == 2
    codes = {r["dtc_code"] for r in records}
    assert "P0301" in codes
    assert "P0420" in codes

    # List diagnostics via API
    list_res = client.get(f"/api/vehicles/{vid}/diagnostics", auth=auth)
    assert list_res.status_code == 200
    assert len(list_res.json()) == 2

    # Global diagnostics list with plate enrichment
    all_res = client.get("/api/diagnostics", auth=auth)
    assert all_res.status_code == 200
    all_items = all_res.json()
    assert len(all_items) >= 2
    assert all_items[0]["vehicle_plate"] == "34 VWG 15"


def test_proactive_outbound_call_and_sms(diag_setup):
    client, SessionLocal, ami_mock, notif_mock = diag_setup
    auth = ("admin", "test-pass")

    with SessionLocal() as db:
        v = Vehicle(description="Renault Megane 1.3 TCe", plate="34 RN 13")
        db.add(v)
        db.commit()
        vid = v.id

    # Ingest critical diagnostic code
    ingest_res = client.post(
        f"/api/vehicles/{vid}/diagnostics",
        json={
            "current_km": 88000,
            "dtc_codes": ["B0001"],  # Airbag fault
            "owner_name": "Deniz Kaya",
            "owner_phone": "05445556677",
        },
        auth=auth,
    )
    assert ingest_res.status_code == 200
    diag_id = ingest_res.json()[0]["id"]

    # 1. Trigger Proactive Outbound Voice Call
    call_res = client.post(
        f"/api/diagnostics/{diag_id}/call",
        json={"phone": "05445556677"},
        auth=auth,
    )
    assert call_res.status_code == 200, call_res.text
    call_data = call_res.json()
    assert call_data["call_type"] == "diagnostic_alert"
    assert call_data["phone"] == "05445556677"
    assert len(ami_mock.calls) >= 1
    assert "05445556677" in ami_mock.calls[0]["channel"]

    # 2. Trigger Proactive SMS Alert
    sms_res = client.post(
        f"/api/diagnostics/{diag_id}/sms",
        json={"phone": "05445556677"},
        auth=auth,
    )
    assert sms_res.status_code == 200, sms_res.text
    sms_data = sms_res.json()
    assert sms_data["dispatched_count"] >= 1
    assert len(notif_mock.sent_messages) >= 1
    sent_sms = notif_mock.sent_messages[0]
    assert "B0001" in sent_sms["message"]
    assert "Airbag" in sent_sms["message"] or "Hava Yastığı" in sent_sms["message"]

    # 3. Resolve diagnostic
    resolve_res = client.post(f"/api/diagnostics/{diag_id}/resolve", auth=auth)
    assert resolve_res.status_code == 200
    assert resolve_res.json()["is_resolved"] is True


@pytest.mark.asyncio
async def test_proactive_voice_dialogue_flow(diag_setup):
    client, SessionLocal, ami_mock, notif_mock = diag_setup

    # Test 1: Customer accepts diagnostic appointment recommendation
    d1 = Dialogue("test-conv-diag-1", mode="outbound_diagnostic")
    ans1 = await d1.answer("Evet, randevu oluşturalım, müsait saatler ne zaman?")
    assert "Harika" in ans1 or "randevu" in ans1.lower()
    assert d1.mode == "inbound"  # Transitioned to booking
    assert d1.done is False

    # Test 2: Customer declines
    d2 = Dialogue("test-conv-diag-2", mode="outbound_diagnostic")
    ans2 = await d2.answer("Hayır, şu an gerek yok daha sonra yaptırırım.")
    assert "not aldım" in ans2 or "saklıyoruz" in ans2 or "dilediğiniz zaman" in ans2.lower()
    assert d2.done is True
