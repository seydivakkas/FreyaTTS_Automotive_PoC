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

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.db import Appointment, BaySchedule, InspectionBay, Session, Slot, Technician, Vehicle
from backend.lift_bay_capacity_scheduler import (
    BAY_TYPES,
    PACKAGE_STAGE_ROUTING,
    cancel_appointment_schedules,
    check_multi_stage_bay_capacity,
    format_iso_datetime,
    get_bay_station_analytics,
    list_bay_schedules,
    list_bays,
    list_technicians,
    parse_iso_datetime,
    schedule_multi_stage_appointment,
    seed_default_bays_and_technicians,
    set_bay_status,
    set_technician_status,
)
from backend.main import app


def uid():
    return uuid4().hex


def make_test_appointment(db, customer="Test Müşteri", plate="34 TST 01"):
    veh_id = f"veh-{uid()[:8]}"
    veh = Vehicle(id=veh_id, description="Test Araç", plate=plate)
    db.add(veh)
    slot_id = f"slot-{uid()[:8]}"
    slot = Slot(
        id=slot_id,
        starts_at=format_iso_datetime(datetime.now(timezone.utc) + timedelta(days=20, minutes=int(uid()[:4], 16) % 1000)),
        duration_minutes=60,
    )
    db.add(slot)
    db.flush()
    app_obj = Appointment(
        id=f"app-{uid()[:8]}",
        slot_id=slot.id,
        vehicle_id=veh.id,
        customer=customer,
        idempotency_key=uid(),
        confirmed=True,
        package_type="standart_ekspertiz",
    )
    db.add(app_obj)
    db.commit()
    db.refresh(app_obj)
    return app_obj


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(monkeypatch):
    import base64
    from backend.config import settings

    monkeypatch.setattr(settings, "admin_password", "secret")
    creds = base64.b64encode(b"admin:secret").decode("ascii")
    return {"Authorization": f"Basic {creds}"}


# 1. Başlangıç Verisi (Seed Data) Testi
def test_seed_default_bays_and_technicians():
    with Session() as db:
        res = seed_default_bays_and_technicians(db)
        bays = list_bays(db)
        techs = list_technicians(db)

        assert len(bays) >= 5
        assert any(b.bay_type == "dyno" for b in bays)
        assert any(b.bay_type == "bodywork_paint" for b in bays)
        assert any(b.bay_type == "mechanic_underbody" for b in bays)
        assert any(b.bay_type == "electronic_diagnostics" for b in bays)

        assert len(techs) >= 4
        assert any("dyno" in t.specialties_json for t in techs)
        assert any("bodywork_paint" in t.specialties_json for t in techs)


# 2. Çok Aşamalı Boş Slot Kapasite Kontrolü Testi
def test_capacity_check_clean_window():
    with Session() as db:
        offset_days = 40 + (int(uid()[:4], 16) % 50)
        start_dt = datetime.now(timezone.utc) + timedelta(days=offset_days, hours=4)
        start_iso = format_iso_datetime(start_dt)

        res = check_multi_stage_bay_capacity(
            db,
            package_type="full_kapsamli",
            requested_start_iso=start_iso,
        )

        assert res.is_available is True
        assert res.package_type == "full_kapsamli"
        assert res.total_duration_minutes == 60  # 25 + 20 + 15
        assert len(res.allocated_stages) == 3

        # Aşamalar: Kaporta -> Alt Mekanik -> Dyno
        assert res.allocated_stages[0].stage_key == "bodywork_paint"
        assert res.allocated_stages[1].stage_key == "mechanic_underbody"
        assert res.allocated_stages[2].stage_key == "dyno"

        assert "dinamometre" in res.spoken_pitch.lower() or "uzman teknisyen" in res.spoken_pitch.lower()


# 3. Dyno İstasyonu Çakışması ve Darboğaz Tespiti Testi
def test_capacity_check_dyno_bottleneck_and_next_available():
    with Session() as db:
        seed_default_bays_and_technicians(db)
        dyno_bay = db.scalars(
            select(InspectionBay).where(InspectionBay.bay_type == "dyno")
        ).first()
        assert dyno_bay is not None

        offset_days = 90 + (int(uid()[:4], 16) % 50)
        base_dt = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=offset_days)
        dyno_start = base_dt.replace(hour=10, minute=0)
        dyno_end = dyno_start + timedelta(minutes=45)

        # Doğrudan DB'ye bir Dyno rezervasyonu girelim (appointment_id=None)
        dummy_sched = BaySchedule(
            appointment_id=None,
            bay_id=dyno_bay.id,
            technician_id=None,
            package_type="motor_mekanik",
            stage_name="Dinamometre Motor Güç Testi",
            stage_index=1,
            starts_at=format_iso_datetime(dyno_start),
            ends_at=format_iso_datetime(dyno_end),
            duration_minutes=45,
            status="scheduled",
        )
        db.add(dummy_sched)
        db.commit()

        try:
            req_start = dyno_start - timedelta(minutes=45)
            res = check_multi_stage_bay_capacity(
                db,
                package_type="full_kapsamli",
                requested_start_iso=format_iso_datetime(req_start),
            )

            assert res.is_available is False
            assert res.bottleneck_bay_type == "dyno"
            assert res.bottleneck_stage == "dyno"
            assert "dolu" in res.bottleneck_reason.lower()
            # Bir sonraki uygun zaman dilimi Dyno serbest kaldıktan sonra olmalı
            assert res.next_available_start_iso is not None
            assert res.next_available_start_iso > format_iso_datetime(req_start)
            assert "en erken" in res.spoken_pitch.lower()
        finally:
            dummy_sched.status = "cancelled"
            db.commit()


# 4. Çok Aşamalı Randevu Çizelgeleme Testi
def test_schedule_multi_stage_appointment_success():
    with Session() as db:
        app = make_test_appointment(db, customer="Kemal Sunal", plate="34 GLF 22")
        app_id = app.id

        offset_days = 150 + (int(uid()[:4], 16) % 50)
        start_dt = datetime.now(timezone.utc) + timedelta(days=offset_days, hours=2)
        schedules = schedule_multi_stage_appointment(
            db,
            appointment_id=app_id,
            package_type="standart_ekspertiz",
            start_time_iso=format_iso_datetime(start_dt),
            plate="34 GLF 22",
            notes="Müşteri özel mikron raporu istedi.",
        )

        assert len(schedules) == 3
        assert schedules[0].stage_index == 1
        assert schedules[1].stage_index == 2
        assert schedules[2].stage_index == 3
        assert schedules[0].appointment_id == app_id
        assert schedules[0].status == "scheduled"

        # İlk istasyonun durum kontrolü
        first_bay = db.get(InspectionBay, schedules[0].bay_id)
        assert first_bay.current_appointment_id == app_id
        assert first_bay.current_vehicle_plate == "34 GLF 22"


# 5. Kapasite Yetersizken Randevu Çizelgeleme Hatası Testi
def test_schedule_multi_stage_conflict_raises_error():
    with Session() as db:
        seed_default_bays_and_technicians(db)
        # Bütün kaporta liftlerini bakıma alalım
        bays = db.scalars(select(InspectionBay).where(InspectionBay.bay_type == "bodywork_paint")).all()
        for b in bays:
            b.status = "maintenance"
        db.commit()

        offset_days = 210 + (int(uid()[:4], 16) % 50)
        start_dt = datetime.now(timezone.utc) + timedelta(days=offset_days)
        with pytest.raises(ValueError) as exc:
            schedule_multi_stage_appointment(
                db,
                appointment_id=None,
                package_type="standart_ekspertiz",
                start_time_iso=format_iso_datetime(start_dt),
                plate="06 FL 01",
            )
        assert "kapasitesi yetersiz" in str(exc.value).lower()

        # Test sonrası liftleri normale döndür
        for b in bays:
            b.status = "idle"
        db.commit()


# 6. Randevu İptali ve İstasyon Serbest Bırakma Testi
def test_cancel_appointment_schedules():
    with Session() as db:
        app = make_test_appointment(db, customer="Can Yılmaz", plate="35 CAN 01")
        app_id = app.id
        offset_days = 270 + (int(uid()[:4], 16) % 50)
        start_dt = datetime.now(timezone.utc) + timedelta(days=offset_days)
        schedules = schedule_multi_stage_appointment(
            db,
            appointment_id=app_id,
            package_type="motor_mekanik",
            start_time_iso=format_iso_datetime(start_dt),
            plate="35 CAN 01",
        )
        assert len(schedules) == 2

        # İptal et
        count = cancel_appointment_schedules(db, appointment_id=app_id)
        assert count == 2

        # Kayıtların durumu cancelled olmalıdır
        for s in schedules:
            db.refresh(s)
            assert s.status == "cancelled"


# 7. İstasyon ve Teknisyen Doluluk Analitiği Testi
def test_get_bay_station_analytics():
    with Session() as db:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        analytics = get_bay_station_analytics(db, date_str=today_str)

        assert analytics["total_bays"] >= 5
        assert analytics["total_technicians"] >= 4
        assert "station_type_summary" in analytics
        assert "bays_utilization" in analytics
        assert "technicians_utilization" in analytics
        assert "bottleneck_advice" in analytics


# 8. REST API Uç Noktaları Testi
def test_bay_scheduler_api_endpoints(client, auth_headers):
    # 1. POST /api/bay-scheduler/check-capacity
    start_iso = format_iso_datetime(datetime.now(timezone.utc) + timedelta(days=7))
    check_body = {
        "package_type": "standart_ekspertiz",
        "requested_start_iso": start_iso,
    }
    r1 = client.post("/api/bay-scheduler/check-capacity", json=check_body, headers=auth_headers)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["is_available"] is True
    assert len(d1["allocated_stages"]) == 3
    assert "spoken_pitch" in d1

    # 2. GET /api/bay-scheduler/bays
    r2 = client.get("/api/bay-scheduler/bays", headers=auth_headers)
    assert r2.status_code == 200
    bays = r2.json()
    assert len(bays) >= 5

    # 3. GET /api/bay-scheduler/technicians
    r3 = client.get("/api/bay-scheduler/technicians", headers=auth_headers)
    assert r3.status_code == 200
    techs = r3.json()
    assert len(techs) >= 4

    # 4. POST /api/bay-scheduler/book-stages
    with Session() as db:
        test_app = make_test_appointment(db, customer="API Test", plate="34 API 99")
        test_app_id = test_app.id

    book_body = {
        "appointment_id": test_app_id,
        "package_type": "motor_mekanik",
        "start_time_iso": start_iso,
        "plate": "34 API 99",
        "notes": "API test rezervasyonu",
    }
    r4 = client.post("/api/bay-scheduler/book-stages", json=book_body, headers=auth_headers)
    assert r4.status_code == 200
    stages = r4.json()
    assert len(stages) == 2

    # 5. GET /api/bay-scheduler/schedules
    r5 = client.get("/api/bay-scheduler/schedules", headers=auth_headers)
    assert r5.status_code == 200
    assert len(r5.json()) >= 2

    # 6. GET /api/bay-scheduler/analytics
    r6 = client.get("/api/bay-scheduler/analytics", headers=auth_headers)
    assert r6.status_code == 200
    assert "bays_utilization" in r6.json()

    # 7. PUT /api/bay-scheduler/bays/{bay_id}/status
    test_bay_id = bays[0]["id"]
    r7 = client.put(f"/api/bay-scheduler/bays/{test_bay_id}/status", json={"status": "busy"}, headers=auth_headers)
    assert r7.status_code == 200
    assert r7.json()["status"] == "busy"

    # Reset bay
    client.put(f"/api/bay-scheduler/bays/{test_bay_id}/status", json={"status": "idle"}, headers=auth_headers)

    # 8. PUT /api/bay-scheduler/technicians/{technician_id}/status
    test_tech_id = techs[0]["id"]
    r8 = client.put(f"/api/bay-scheduler/technicians/{test_tech_id}/status", json={"is_active": True}, headers=auth_headers)
    assert r8.status_code == 200
    assert r8.json()["is_active"] is True

    # 9. DELETE /api/bay-scheduler/appointments/{appointment_id}
    r9 = client.delete(f"/api/bay-scheduler/appointments/{test_app_id}", headers=auth_headers)
    assert r9.status_code == 200
    assert r9.json()["cancelled_schedules_count"] == 2

    # 10. Generic listing: GET /api/inspection-bays
    r10 = client.get("/api/inspection-bays", headers=auth_headers)
    assert r10.status_code == 200
    assert len(r10.json()) >= 5
