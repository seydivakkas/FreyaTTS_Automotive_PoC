# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Unit and integration tests for Caller & Session Memory System (Milestone 3)."""

import json
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db import Base, CallerProfile, Vehicle, Slot, Appointment
import backend.dialogue as dialogue
from backend.caller_memory import (
    get_or_create_caller_profile,
    format_caller_memory_context,
    resolve_warranty_inquiry,
    resolve_past_maintenance,
    add_maintenance_record,
    seed_default_profiles,
    normalize_phone,
    normalize_plate,
)


@pytest.fixture
def memory_db(tmp_path, monkeypatch):
    """Geçici SQLite veritabanı ve oturum fabrikası sağlar."""
    db_file = tmp_path / "test_memory.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(dialogue, "Session", factory)
    yield factory
    engine.dispose()


def test_phone_and_plate_normalization():
    assert normalize_phone("+905321234567") == "05321234567"
    assert normalize_phone("905321234567") == "05321234567"
    assert normalize_phone("5321234567") == "05321234567"
    assert normalize_phone("0532 123 45 67") == "05321234567"

    assert normalize_plate("61 ts 061") == "61 TS 061"
    assert normalize_plate("34bjk1903") == "34 BJK 1903"
    assert normalize_plate("") == ""


def test_caller_profile_crud_and_persistence(memory_db):
    with memory_db() as db:
        profile = CallerProfile(
            phone="05321234567",
            plate="61 TS 061",
            name="Ahmet Yılmaz",
            vehicle_model="2023 Peugeot 3008 1.5 BlueHDi",
            warranty_expires_at="2027-06-15",
            warranty_status="active",
            maintenance_history_json=json.dumps([
                {"date": "2026-09-12", "km": 45000, "item": "Ön fren balatası değişimi", "notes": "Orijinal"}
            ]),
            inspection_scores_json=json.dumps([{"date": "2026-03-05", "score": 94}]),
            notes="Sadık müşteri",
        )
        db.add(profile)
        db.commit()

        retrieved = db.query(CallerProfile).filter_by(phone="05321234567").first()
        assert retrieved is not None
        assert retrieved.name == "Ahmet Yılmaz"
        assert retrieved.plate == "61 TS 061"
        assert retrieved.vehicle_model == "2023 Peugeot 3008 1.5 BlueHDi"
        assert retrieved.warranty_status == "active"
        history = json.loads(retrieved.maintenance_history_json)
        assert len(history) == 1
        assert "balata" in history[0]["item"].lower()


def test_get_or_create_caller_profile(memory_db):
    with memory_db() as db:
        # 1. Yeni profil oluşturma
        p1 = get_or_create_caller_profile(db, phone="05321112233", name="Can Özkan")
        db.commit()
        assert p1.id is not None
        assert p1.phone == "05321112233"
        assert p1.name == "Can Özkan"

        # 2. Aynı telefonla tekrar çağırma (mevcut profili getirmeli)
        p2 = get_or_create_caller_profile(db, phone="05321112233", plate="34 ABC 123")
        db.commit()
        assert p2.id == p1.id
        assert p2.plate == "34 ABC 123"

        # 3. Plaka ile çağırma
        p3 = get_or_create_caller_profile(db, plate="34 ABC 123")
        assert p3.id == p1.id
        assert p3.name == "Can Özkan"


def test_format_caller_memory_context():
    profile = CallerProfile(
        name="Ahmet Yılmaz",
        phone="05321234567",
        plate="61 TS 061",
        vehicle_model="Peugeot 3008",
        warranty_expires_at="2027-06-15",
        warranty_status="active",
        maintenance_history_json=json.dumps([
            {"date": "2026-09-12", "km": 45000, "item": "Ön fren balatası değişimi", "notes": "Orijinal"}
        ]),
        notes="Öncelikli müşteri",
    )
    context = format_caller_memory_context(profile)
    assert "Ahmet Yılmaz" in context
    assert "61 TS 061" in context
    assert "Peugeot 3008" in context
    assert "Garanti: Aktif" in context
    assert "Ön fren balatası" in context


def test_resolve_warranty_inquiry():
    future_date = (datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%d")
    past_date = (datetime.now(timezone.utc) - timedelta(days=100)).strftime("%Y-%m-%d")

    active_profile = CallerProfile(
        name="Ahmet Yılmaz",
        vehicle_model="Peugeot 3008",
        warranty_expires_at=future_date,
        warranty_status="active",
    )
    res_active = resolve_warranty_inquiry(active_profile)
    assert res_active["is_valid"] is True
    assert "aktif olarak devam etmektedir" in res_active["message"]

    expired_profile = CallerProfile(
        name="Mehmet Demir",
        vehicle_model="Volkswagen Passat",
        warranty_expires_at=past_date,
        warranty_status="expired",
    )
    res_expired = resolve_warranty_inquiry(expired_profile)
    assert res_expired["is_valid"] is False
    assert "sona ermiştir" in res_expired["message"]

    void_profile = CallerProfile(
        name="Ali Vural",
        vehicle_model="Fiat Egea",
        warranty_expires_at=future_date,
        warranty_status="void",
    )
    res_void = resolve_warranty_inquiry(void_profile)
    assert res_void["is_valid"] is False
    assert "geçersiz" in res_void["message"]


def test_resolve_past_maintenance():
    profile = CallerProfile(
        name="Ahmet Yılmaz",
        maintenance_history_json=json.dumps([
            {
                "date": "2026-09-12",
                "km": 45000,
                "item": "Ön fren balatası ve disk değişimi",
                "notes": "Orijinal Bosch balata takıldı",
            },
            {
                "date": "2026-03-05",
                "km": 30000,
                "item": "30.000 km periyodik yağ bakımı",
                "notes": "Motor yağı yenilendi",
            },
        ]),
    )

    brake_res = resolve_past_maintenance(profile, "balata")
    assert brake_res is not None
    assert "balata" in brake_res.lower()
    assert "45000 km" in brake_res or "45.000" in brake_res or "2026-09-12" in brake_res

    oil_res = resolve_past_maintenance(profile, "yağ")
    assert oil_res is not None
    assert "yağ" in oil_res.lower()

    unknown_res = resolve_past_maintenance(profile, "akü")
    assert unknown_res is None


def test_add_maintenance_record():
    profile = CallerProfile(
        maintenance_history_json="[]",
    )
    add_maintenance_record(profile, date="2026-11-01", item="Silecek değişimi", km=50000, cost_tl=800)
    history = json.loads(profile.maintenance_history_json)
    assert len(history) == 1
    assert history[0]["item"] == "Silecek değişimi"


def test_seed_default_profiles(memory_db):
    with memory_db() as db:
        created = seed_default_profiles(db)
        assert len(created) >= 2
        # Tekrar çağrıldığında çoğaltmamalı (idempotent)
        again = seed_default_profiles(db)
        assert len(again) == 0
        total = db.query(CallerProfile).count()
        assert total >= 2


@pytest.mark.asyncio
async def test_dialogue_state_message_contains_memory_context(memory_db):
    with memory_db() as db:
        p = CallerProfile(
            name="Ahmet Yılmaz",
            phone="05321234567",
            plate="61 TS 061",
            vehicle_model="Peugeot 3008",
            warranty_expires_at="2027-06-15",
            warranty_status="active",
            maintenance_history_json=json.dumps([
                {"date": "2026-09-12", "km": 45000, "item": "Ön fren balatası değişimi"}
            ]),
        )
        db.add(p)
        db.commit()

    d = dialogue.Dialogue("mem-test-state", customer_phone="05321234567")
    d.caller_profile = p
    state_msg = d.build_state_message() or ""
    # H01.03 (kural 10, ADR-F3-01): arayan profili LLM durum mesajına girmez.
    assert "Ahmet Yılmaz" not in state_msg
    assert "Peugeot 3008" not in state_msg
    assert "61 TS 061" not in state_msg
    assert "balata" not in state_msg.lower()


@pytest.mark.asyncio
async def test_dialogue_multi_turn_warranty_resolution(memory_db):
    with memory_db() as db:
        p = CallerProfile(
            name="Ahmet Yılmaz",
            phone="05321234567",
            plate="61 TS 061",
            vehicle_model="Peugeot 3008",
            warranty_expires_at=(datetime.now(timezone.utc) + timedelta(days=300)).strftime("%Y-%m-%d"),
            warranty_status="active",
        )
        db.add(p)
        db.commit()

    d = dialogue.Dialogue("mem-test-warranty", customer_phone="05321234567")
    # H01.03 (ADR-F3-01): numara eşleşmesi yetmez; plaka son 3 hanesiyle doğrulama sonrası okunur.
    challenge = await d.answer("Aracımın garantisi devam ediyor mu?")
    assert "plaka" in challenge.lower()
    ans = await d.answer("061")
    assert "garanti" in ans.lower()
    assert "devam etmektedir" in ans or "aktif" in ans.lower()


@pytest.mark.asyncio
async def test_dialogue_multi_turn_past_brake_pad_resolution(memory_db):
    with memory_db() as db:
        p = CallerProfile(
            name="Ahmet Yılmaz",
            phone="05321234567",
            plate="61 TS 061",
            vehicle_model="Peugeot 3008",
            maintenance_history_json=json.dumps([
                {
                    "date": "2026-09-12",
                    "km": 45000,
                    "item": "Ön fren balatası ve disk değişimi",
                    "notes": "Orijinal parça takıldı",
                }
            ]),
        )
        db.add(p)
        db.commit()

    d = dialogue.Dialogue("mem-test-brake", customer_phone="05321234567")
    # H01.03 (ADR-F3-01): numara eşleşmesi yetmez; plaka son 3 hanesiyle doğrulama sonrası okunur.
    challenge = await d.answer("Geçen sefer konuştuğumuz balata değişimi yapılmış mıydı?")
    assert "plaka" in challenge.lower()
    ans = await d.answer("061")
    assert "balata" in ans.lower()
    assert "2026-09-12" in ans or "45000" in ans or "yapılmıştır" in ans
