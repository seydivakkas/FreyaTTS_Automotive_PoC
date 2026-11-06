"""Tests for vehicle inspection reports, template findings, photo upload, PDF generation, and digital delivery.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

import io
import json
from datetime import datetime, timezone, timedelta
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
    CorporateAccount,
    InspectionReport,
    NotificationOutbox,
    book,
)
from backend import main
from backend.notifications import (
    set_notification_provider,
    MockNotificationProvider,
)
from backend.report_generator import generate_inspection_pdf


@pytest.fixture
def test_setup(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "inspection_test.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sm = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(main, "Session", sm)
    monkeypatch.setattr("backend.db.Session", sm)
    monkeypatch.setattr(main.settings, "admin_password", "test-pass")

    provider = MockNotificationProvider()
    set_notification_provider(provider)

    c = TestClient(main.app)
    yield c, sm, provider, tmp_path
    c.close()
    engine.dispose()


def test_create_inspection_with_findings_and_pdf(test_setup):
    client, SessionLocal, provider, tmp_path = test_setup
    auth = ("admin", "test-pass")

    with SessionLocal() as db:
        v = Vehicle(
            description="Renault Megane 1.3 TCe",
            plate="34 RM 2021",
            vin="VF1RFB00865432109",
        )
        db.add(v)
        db.commit()
        vehicle_id = v.id

    findings = {
        "paint_body": {
            "kaput": "Orijinal",
            "tavan": "Orijinal",
            "bagaj": "Orijinal",
            "sag_on_camurluk": "Lokal Boyalı",
            "notlar": "Sağ ön çamurluk ucunda 10 cm lokal boya mevcut, mikron 160.",
        },
        "engine_mechanical": {
            "motor_performansi_yuzde": "96%",
            "turbo_durumu": "Mükemmel",
            "sanziman_vites": "Sarsıntısız",
        },
        "chassis_frame": {
            "on_podyeler": "İşlemsiz / Orijinal",
            "marspiyeller": "Kusursuz",
        },
        "tires_wheels": {
            "on_sol_dis_mm": "7.0 mm",
            "dot_yili": "2024",
        },
        "interior_electronics": {
            "airbag_guvenlik": "Orijinal",
            "obd_ariza_taramasi": "DTC Kodu Yok",
        },
    }

    payload = {
        "summary": "Araç genel kondisyonu oldukça yüksek. Tek parça lokal boya haricinde hatasız.",
        "mileage_km": 45200,
        "score": 93,
        "technician_name": "Murat Usta",
        "findings": findings,
        "photos": [],
    }

    res = client.post(f"/api/vehicles/{vehicle_id}/inspections", json=payload, auth=auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["vehicle_id"] == vehicle_id
    assert data["score"] == 93
    assert data["technician_name"] == "Murat Usta"
    assert data["pdf_path"] is not None

    report_id = data["id"]

    # Verify database persistence
    with SessionLocal() as db:
        rep = db.get(InspectionReport, report_id)
        assert rep is not None
        assert rep.mileage_km == 45200
        saved_findings = json.loads(rep.findings_json)
        assert saved_findings["paint_body"]["sag_on_camurluk"] == "Lokal Boyalı"

    # Verify PDF download endpoint
    pdf_res = client.get(f"/api/inspections/{report_id}/pdf", auth=auth)
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"] == "application/pdf"
    assert pdf_res.content.startswith(b"%PDF-1.")


def test_photo_upload_and_preview(test_setup):
    client, SessionLocal, provider, tmp_path = test_setup
    auth = ("admin", "test-pass")

    # Upload dummy image
    image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
    files = {"file": ("motor_ekspertiz.jpg", image_bytes, "image/jpeg")}
    data = {"caption": "Motor Bölmesi Kontrolü", "category": "Motor"}

    res = client.post("/api/inspections/photos", files=files, data=data, auth=auth)
    assert res.status_code == 200, res.text
    photo_info = res.json()
    assert "url" in photo_info
    assert photo_info["caption"] == "Motor Bölmesi Kontrolü"
    assert photo_info["category"] == "Motor"

    # Fetch photo via GET
    fname = photo_info["filename"]
    get_res = client.get(f"/api/inspections/photos/{fname}")
    assert get_res.status_code == 200
    assert get_res.content == image_bytes


def test_digital_delivery_send_link(test_setup):
    client, SessionLocal, provider, tmp_path = test_setup
    auth = ("admin", "test-pass")

    # Setup corporate appointment and vehicle
    with SessionLocal() as db:
        account = CorporateAccount(
            name="Yıldız Premium Galeri",
            tax_id="TR-GALERI-9988",
            phone="05321112233",
            credit_limit_kurus=50_000_000,
            discount_percent=15,
        )
        v = Vehicle(
            description="BMW 320i Sedan",
            plate="34 BMW 320",
            vin="WBA3R1C55EP123456",
        )
        db.add_all([account, v])
        db.flush()

        q = Quote(vehicle_id=v.id, amount_kurus=300000)
        s = Slot(
            starts_at=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            duration_minutes=45,
        )
        db.add_all([q, s])
        db.flush()

        app = book(
            db,
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Kemal Öztürk (05423334455)",
            idempotency_key="book-kemal-320",
            confirmed=True,
            corporate_account_id=account.id,
            customer_phone="05423334455",
        )
        db.commit()

        vehicle_id = v.id
        app_id = app.id

    # Create inspection for this vehicle
    res = client.post(
        f"/api/vehicles/{vehicle_id}/inspections",
        json={
            "summary": "Ekspertiz tamamlandı. Araç hatasız ve boyasızdır.",
            "mileage_km": 32000,
            "score": 98,
            "appointment_id": app_id,
            "technician_name": "Can Usta",
            "findings": {"paint_body": {"kaput": "Orijinal"}},
            "photos": [],
        },
        auth=auth,
    )
    assert res.status_code == 200
    report_id = res.json()["id"]

    # Send digital delivery link
    send_res = client.post(f"/api/inspections/{report_id}/send-link", auth=auth)
    assert send_res.status_code == 200, send_res.text
    data = send_res.json()
    # Mock sağlayıcı: mesaj gönderilmedi, "delivered" denmemeli.
    assert data["status"] == "simulated"
    assert data["delivered_at"] is None
    assert f"/api/inspections/{report_id}/pdf" in data["url"]
    assert data["notifications_queued"] == 2  # Customer SMS + Dealership WhatsApp

    # Verify notifications delivered via MockNotificationProvider
    assert len(provider.sent_messages) >= 2
    channels = {m["channel"] for m in provider.sent_messages}
    assert "sms" in channels
    assert "whatsapp" in channels

    # Check recipient and messages for the inspection report
    insp_sms = [m for m in provider.sent_messages if m["channel"] == "sms" and report_id in m["message"]]
    assert len(insp_sms) == 1
    assert "34 BMW 320" in insp_sms[0]["message"]

    insp_wa = [m for m in provider.sent_messages if m["channel"] == "whatsapp" and report_id in m["message"]]
    assert len(insp_wa) == 1
    assert "Yıldız Premium Galeri" in insp_wa[0]["message"]
    assert "34 BMW 320" in insp_wa[0]["message"]


def test_list_and_get_inspections(test_setup):
    client, SessionLocal, provider, tmp_path = test_setup
    auth = ("admin", "test-pass")

    with SessionLocal() as db:
        v = Vehicle(description="Fiat Egea 1.4", plate="06 ANK 06")
        db.add(v)
        db.commit()
        vid = v.id

    # Add 2 inspections
    client.post(
        f"/api/vehicles/{vid}/inspections",
        json={"summary": "İlk kontrol yapıldı", "mileage_km": 10000, "score": 90},
        auth=auth,
    )
    client.post(
        f"/api/vehicles/{vid}/inspections",
        json={"summary": "İkinci kontrol yapıldı", "mileage_km": 20000, "score": 85},
        auth=auth,
    )

    # List inspections
    res = client.get("/api/inspections", auth=auth)
    assert res.status_code == 200
    items = res.json()
    assert len(items) >= 2
    assert items[0]["vehicle_plate"] == "06 ANK 06"

    # Get single inspection
    rep_id = items[0]["id"]
    get_res = client.get(f"/api/inspections/{rep_id}", auth=auth)
    assert get_res.status_code == 200
    detail = get_res.json()
    assert detail["id"] == rep_id
    assert detail["vehicle"]["plate"] == "06 ANK 06"
