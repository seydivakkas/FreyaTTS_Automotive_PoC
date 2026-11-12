# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""
Madde 4: Operasyon Paneli Test Paketi.

Kapsanan Yetenekler:
1. Takvim görünümü ve sürükle-bırak saat taşıma (Reschedule API & Calendar events)
2. Başarısız görüşmeler ekranı (Anlaşılamayan çağrıların tespiti, ses akışı ve sözlüğe geri besleme)
3. Gerçek KPI panosu (Gecikme, dönüşüm oranı ve randevu iptal oranının gerçek veritabanı kayıtlarından hesaplanması)
4. Raporlama (Haftalık otomatik özet raporu ve çok sayfalı Excel .xlsx çıktısı)
"""

from __future__ import annotations

import io
from datetime import datetime, timezone, timedelta
import pytest
import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.db import (
    Base,
    Vehicle,
    Slot,
    Appointment,
    Conversation,
    Turn,
    book,
    cancel_appointment,
)
from backend.main import app
from backend import db as db_module
from backend.analytics import get_analytics_overview, get_unclear_conversations
from backend.report_generator import (
    generate_weekly_summary_report,
    generate_weekly_excel_report,
)
from backend.normalizer_rules import AUTOMOTIVE_LEXICON


@pytest.fixture
def test_db_session(monkeypatch, tmp_path):
    """In-memory SQLite session isolated for operational panel tests."""
    engine = create_engine(
        f"sqlite:///{tmp_path}/test_madde4.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "Session", TestingSession)

    with TestingSession() as session:
        yield session

    Base.metadata.drop_all(bind=engine)


from backend.config import settings


@pytest.fixture
def client(test_db_session):
    c = TestClient(app)
    c.auth = ("admin", settings.admin_password)
    return c


# ============================================================================
# 1. TAKVİM GÖRÜNÜMÜ VE SÜRÜKLE-BIRAK SAAT TAŞIMA (RESCHEDULE & CALENDAR)
# ============================================================================

def test_reschedule_appointment_to_target_slot(test_db_session, client):
    """Randevunun sürükle-bırak ile başka bir müsait slota taşınması."""
    v = Vehicle(description="Volkswagen Passat 1.5 TSI", plate="34 ABC 101")
    test_db_session.add(v)

    now_utc = datetime.now(timezone.utc)
    slot1_time = (now_utc + timedelta(days=1, hours=2)).isoformat()
    slot2_time = (now_utc + timedelta(days=1, hours=4)).isoformat()

    s1 = Slot(starts_at=slot1_time, duration_minutes=30)
    s2 = Slot(starts_at=slot2_time, duration_minutes=30)
    test_db_session.add_all([s1, s2])
    test_db_session.commit()

    appt = book(
        test_db_session,
        slot_id=s1.id,
        vehicle_id=v.id,
        customer="Ali Veli",
        customer_phone="05551112233",
        idempotency_key="reschedule-test-1",
        confirmed=True,
    )

    # Slot 1 dolu, Slot 2 boş olmalı
    assert appt.slot_id == s1.id

    # API üzerinden Slot 2'ye taşı
    resp = client.post(
        f"/api/appointments/{appt.id}/reschedule",
        json={"target_slot_id": s2.id},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "rescheduled"
    assert data["old_slot_id"] == s1.id
    assert data["new_slot_id"] == s2.id
    assert data["starts_at"] == s2.starts_at

    # DB doğrulaması
    test_db_session.expire_all()
    updated = test_db_session.get(Appointment, appt.id)
    assert updated.slot_id == s2.id
    assert updated.status == "confirmed"


def test_reschedule_appointment_conflict(test_db_session, client):
    """Zaten dolu olan bir slota randevu taşınamaz (409 Conflict)."""
    v1 = Vehicle(description="Renault Megane 1.3 TCe", plate="34 DEF 202")
    v2 = Vehicle(description="Fiat Egea 1.4 Fire", plate="34 GHI 303")
    test_db_session.add_all([v1, v2])

    now_utc = datetime.now(timezone.utc)
    t1 = (now_utc + timedelta(days=2, hours=1)).isoformat()
    t2 = (now_utc + timedelta(days=2, hours=3)).isoformat()

    s1 = Slot(starts_at=t1, duration_minutes=30)
    s2 = Slot(starts_at=t2, duration_minutes=30)
    test_db_session.add_all([s1, s2])
    test_db_session.commit()

    appt1 = book(
        test_db_session,
        slot_id=s1.id,
        vehicle_id=v1.id,
        customer="Müşteri 1",
        idempotency_key="conflict-key-1",
        confirmed=True,
    )
    appt2 = book(
        test_db_session,
        slot_id=s2.id,
        vehicle_id=v2.id,
        customer="Müşteri 2",
        idempotency_key="conflict-key-2",
        confirmed=True,
    )

    # appt1'i appt2'nin dolu olduğu s2 slotuna taşımaya çalış
    resp = client.post(
        f"/api/appointments/{appt1.id}/reschedule",
        json={"target_slot_id": s2.id},
    )
    assert resp.status_code == 409
    assert "dolu" in resp.json()["detail"].lower()


def test_get_calendar_events_endpoint(test_db_session, client):
    """Takvim grid görünümü için slot ve randevu durumlarının doğru listelenmesi."""
    v = Vehicle(description="Toyota Corolla 1.5 Vision", plate="06 ANK 06")
    test_db_session.add(v)

    now_utc = datetime.now(timezone.utc)
    t1 = (now_utc + timedelta(days=3, hours=2)).isoformat()
    t2 = (now_utc + timedelta(days=3, hours=5)).isoformat()

    s1 = Slot(starts_at=t1, duration_minutes=30)
    s2 = Slot(starts_at=t2, duration_minutes=45)
    test_db_session.add_all([s1, s2])
    test_db_session.commit()

    book(
        test_db_session,
        slot_id=s1.id,
        vehicle_id=v.id,
        customer="Ayşe Demir",
        customer_phone="05329998877",
        idempotency_key="cal-test-1",
        confirmed=True,
        package_type="full_ekspertiz",
    )

    resp = client.get("/api/appointments/calendar")
    assert resp.status_code == 200
    events = resp.json()

    # İki slot da dönmeli; biri dolu, biri boş
    assert len(events) >= 2
    ev1 = next(e for e in events if e["slot_id"] == s1.id)
    ev2 = next(e for e in events if e["slot_id"] == s2.id)

    assert ev1["is_occupied"] is True
    assert ev1["appointment"]["customer"] == "Ayşe Demir"
    assert ev1["appointment"]["plate"] == "06 ANK 06"
    assert ev1["appointment"]["package_type"] == "full_ekspertiz"

    assert ev2["is_occupied"] is False
    assert ev2["appointment"] is None


# ============================================================================
# 2. BAŞARISIZ GÖRÜŞMELER EKRANI VE SÖZLÜĞE GERİ BESLEME (FEEDBACK LOOP)
# ============================================================================

def test_unclear_conversations_detection_and_feedback(test_db_session, client):
    """Anlaşılamayan görüşmenin tespiti ve operatör tarafından sözlüğe geri beslenmesi."""
    # 1. Başarısız görüşme simülasyonu
    c = Conversation(channel="voice", status="follow_up")
    test_db_session.add(c)
    test_db_session.commit()

    t1 = Turn(conversation_id=c.id, role="user", text="Kaşkay aracım için randevu istiyorum", metrics="{}")
    t2 = Turn(conversation_id=c.id, role="assistant", text="Tam anlayamadım, aracınızın markasını tekrar edebilir misiniz?", metrics="{}")
    t3 = Turn(conversation_id=c.id, role="user", text="Nissan Kaşkay işte", metrics="{}")
    test_db_session.add_all([t1, t2, t3])
    test_db_session.commit()

    # 2. API listesinde anlaşılamayan görüşme olarak gelmeli
    resp = client.get("/api/conversations/unclear")
    assert resp.status_code == 200
    unclear_list = resp.json()
    assert any(item["id"] == c.id for item in unclear_list)
    call_item = next(item for item in unclear_list if item["id"] == c.id)
    assert call_item["unclear_count"] >= 1
    assert len(call_item["turns"]) == 3

    # 3. Operatör düzeltmeyi sözlüğe geri besler
    fb_resp = client.post(
        f"/api/conversations/{c.id}/feedback-lexicon",
        json={
            "term": "Qashqai",
            "spoken": "kaşkay",
            "category": "model",
        },
    )
    assert fb_resp.status_code == 200
    fb_data = fb_resp.json()
    assert fb_data["status"] == "ok"
    assert "Qashqai" in AUTOMOTIVE_LEXICON or "qashqai" in AUTOMOTIVE_LEXICON

    # 4. Görüşme operatör notuyla birlikte çözüldü olarak güncellenmeli
    test_db_session.expire_all()
    c_updated = test_db_session.get(Conversation, c.id)
    assert c_updated.status == "resolved"
    assert "Sözlük Geri Besleme" in c_updated.operator_notes


def test_conversation_audio_endpoint_returns_404_when_missing(client):
    """Ses dosyası mevcut değilse 404 döner."""
    resp = client.get("/api/conversations/00000000-0000-0000-0000-000000000001/audio")
    assert resp.status_code == 404


# ============================================================================
# 3. GERÇEK KPI PANOSU (REAL KPI CALCULATIONS: CONVERSION & CANCELLATION)
# ============================================================================

def test_real_kpis_cancellation_and_conversion_rates(test_db_session):
    """Gecikme, dönüşüm ve iptal oranlarının gerçek veritabanı satırlarından hesaplanması."""
    v = Vehicle(description="BMW 320i", plate="34 BMW 320")
    test_db_session.add(v)

    now_utc = datetime.now(timezone.utc)

    # 4 adet randevu saati
    slots = [
        Slot(starts_at=(now_utc + timedelta(days=i + 1, hours=2)).isoformat(), duration_minutes=30)
        for i in range(4)
    ]
    test_db_session.add_all(slots)
    test_db_session.commit()

    # 4 Randevu: 2'si onaylı kalacak, 2'si iptal edilecek
    a1 = book(test_db_session, slot_id=slots[0].id, vehicle_id=v.id, customer="Müşteri 1", idempotency_key="kpi-1", confirmed=True)
    a2 = book(test_db_session, slot_id=slots[1].id, vehicle_id=v.id, customer="Müşteri 2", idempotency_key="kpi-2", confirmed=True)
    a3 = book(test_db_session, slot_id=slots[2].id, vehicle_id=v.id, customer="Müşteri 3", idempotency_key="kpi-3", confirmed=True)
    a4 = book(test_db_session, slot_id=slots[3].id, vehicle_id=v.id, customer="Müşteri 4", idempotency_key="kpi-4", confirmed=True)

    # a3 ve a4 iptal ediliyor
    cancel_appointment(test_db_session, a3)
    cancel_appointment(test_db_session, a4)

    # 5 adet görüşme
    for i in range(5):
        test_db_session.add(Conversation(channel="phone", status="completed"))
    test_db_session.commit()

    # Metrikleri hesapla
    overview = get_analytics_overview(test_db_session)
    summ = overview["summary"]

    assert summ["total_conversations"] == 5
    assert summ["total_appointments"] == 4
    assert summ["confirmed_appointments"] == 2
    assert summ["cancelled_appointments"] == 2

    # İptal Oranı: 2 / 4 = %50.0
    assert summ["cancellation_rate_pct"] == 50.0

    # Dönüşüm Oranı: 2 onaylı / 5 görüşme = %40.0
    assert summ["conversion_rate_pct"] == 40.0


def test_real_latency_percentiles_calculation(test_db_session):
    """Turn.metrics JSON alanlarından P50 ve P95 gecikmelerinin hesaplanması."""
    c = Conversation(channel="voice", status="completed")
    test_db_session.add(c)
    test_db_session.commit()

    # 10 adet tur, farklı first_audio_ms değerleri (100, 150, 200, ... 550)
    for i in range(1, 11):
        m_json = f'{{"first_audio_ms": {i * 50}, "llm_total_ms": {i * 40}, "stt_ms": 120}}'
        test_db_session.add(Turn(conversation_id=c.id, role="assistant", text=f"Cevap {i}", metrics=m_json))
    test_db_session.commit()

    overview = get_analytics_overview(test_db_session)
    kpis = overview["latency_kpis"]

    # Örnek sayısı 10 olmalı
    assert kpis["first_audio_ms"]["sample_count"] == 10
    # Medyan (P50) ve P95 doğrulaması
    assert kpis["first_audio_ms"]["p50"] is not None
    assert kpis["first_audio_ms"]["p95"] is not None
    assert kpis["first_audio_ms"]["p95"] >= kpis["first_audio_ms"]["p50"]


# ============================================================================
# 4. HAFTALIK ÖZET VE ÇOK SAYFALI EXCEL (.XLSX) ÇIKTISI
# ============================================================================

def test_generate_weekly_summary_report(test_db_session):
    """Haftalık özet raporunun doğru hesaplanması."""
    v = Vehicle(description="Ford Focus 1.5 EcoBlue", plate="35 EFE 35")
    test_db_session.add(v)

    now_utc = datetime.now(timezone.utc)
    s = Slot(starts_at=(now_utc + timedelta(days=1)).isoformat(), duration_minutes=45)
    test_db_session.add(s)
    test_db_session.commit()

    book(
        test_db_session,
        slot_id=s.id,
        vehicle_id=v.id,
        customer="Murat Şahin",
        customer_phone="05443332211",
        idempotency_key="weekly-sum-1",
        confirmed=True,
        package_type="vip_ekspertiz",
    )

    report = generate_weekly_summary_report(test_db_session, days=7)
    assert report["period_days"] == 7
    assert report["summary"]["total_appointments"] >= 1
    assert report["summary"]["confirmed_appointments"] >= 1
    assert "vip_ekspertiz" in report["package_distribution"]
    assert len(report["daily_breakdown"]) == 7


def test_generate_weekly_excel_report_valid_xlsx(test_db_session):
    """Haftalık Excel (.xlsx) raporunun oluşturulması ve 4 sayfanın doğrulanması."""
    v = Vehicle(description="Honda Civic 1.5 VTEC", plate="16 BUR 16")
    test_db_session.add(v)

    now_utc = datetime.now(timezone.utc)
    s = Slot(starts_at=(now_utc + timedelta(days=1)).isoformat(), duration_minutes=30)
    test_db_session.add(s)
    test_db_session.commit()

    book(
        test_db_session,
        slot_id=s.id,
        vehicle_id=v.id,
        customer="Serkan Kaya",
        customer_phone="05051234567",
        idempotency_key="excel-test-1",
        confirmed=True,
        package_type="motor_mekanik",
    )

    excel_bytes = generate_weekly_excel_report(test_db_session, days=7)
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 2000

    # openpyxl ile Excel dosyasını doğrula
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
    sheet_names = wb.sheetnames

    # 4 Zorunlu Çalışma Sayfası
    assert "Yönetici Özeti" in sheet_names
    assert "Randevular" in sheet_names
    assert "Görüşmeler" in sheet_names
    assert "Günlük Dağılım" in sheet_names

    # Sheet 1: Başlık kontrolü
    ws1 = wb["Yönetici Özeti"]
    assert "FREYATTS AUTOMOTIVE" in str(ws1["A1"].value)

    # Sheet 2: Randevu satırı kontrolü
    ws2 = wb["Randevular"]
    found_customer = False
    for row in ws2.iter_rows(values_only=True):
        if "Serkan Kaya" in row:
            found_customer = True
            break
    assert found_customer is True


def test_weekly_report_api_endpoints(test_db_session, client):
    """FastAPI /api/reports/weekly/summary ve /excel uç noktaları."""
    # JSON Summary endpoint
    res_json = client.get("/api/reports/weekly/summary?days=7")
    assert res_json.status_code == 200
    assert "summary" in res_json.json()

    # Excel Download endpoint
    res_excel = client.get("/api/reports/weekly/excel?days=7")
    assert res_excel.status_code == 200
    assert "openxmlformats-officedocument.spreadsheetml.sheet" in res_excel.headers["content-type"]
    assert "haftalik_operasyon_raporu.xlsx" in res_excel.headers["content-disposition"]
    assert len(res_excel.content) > 1000
