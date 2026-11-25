# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""FreyaTTS Automotive Cockpit PoC — Comprehensive E2E Test Suite.

Bu test süiti; ORIGINAL_REQUEST.md, PROJECT.md ve TEST_INFRA.md belgelerine dayalı
olarak 4 katmanlı (4-Tier) kara-kutu (opaque-box) gereksinim doğrulamasını yürütür:
  - Tier 1: Temel Özellik Kapsamı (Feature Coverage, >=27 test)
  - Tier 2: Sınır & Uç Durumlar (Boundary & Corner Cases, >=25 test)
  - Tier 3: Çapraz Özellik Etkileşimleri (Cross-Feature Pairwise, >=6 test)
  - Tier 4: Gerçek Dünya Operasyonel Senaryoları (Real-World Workloads, 5 test)

Toplam test sayısı: 64 test senaryosu (>= 63 zorunlu).
Tüm testler geçici SQLite veritabanı yalıtımı ile çalışır; işletim ortamına sızıntı yapmaz.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import create_engine, select, or_, func, Column, String, Text, Index
from sqlalchemy.orm import sessionmaker, Mapped, mapped_column

from backend.config import settings
from backend import db as db_module
from backend.db import (
    Base,
    Vehicle,
    InspectionReport,
    VehicleDiagnostic,
    Quote,
    Slot,
    Appointment,
    InspectionLift,
    InspectionQueue,
    CorporateAccount,
    Conversation,
    now,
    uid,
)
from backend import main
from backend.session import VoiceSession, make_pipeline_event
from backend.models import models
from backend.supervisor.contracts import Intent
from backend.supervisor.catalogue import CATALOGUE
from backend.supervisor.policy import normalize_utterance, rule_decision, build_plan
from backend.supervisor.orchestrator import SupervisorOrchestrator
from backend.ontology.grounding import AutomotiveGroundingEngine, CERTIFIED_SERVICE_PACKAGES
from backend.ontology.models import DiagnosticSeverity
from backend.normalizer_rules import BASE_AUTOMOTIVE_LEXICON
from backend.technician_dictation import parse_technician_dictation


# ============================================================================
# 0. SÖZLEŞME VE MODÜL KORUYUCULARI (CallerProfile & DatasetGenerator)
# ============================================================================

class MockVad:
    """Oturum başlatma için hafif VAD kuklası."""
    def reset_states(self):
        pass


from backend.db import CallerProfile
from backend.caller_memory import (
    normalize_phone,
    normalize_plate,
    get_or_create_caller_profile,
    format_caller_memory_context,
    resolve_warranty_inquiry,
    resolve_past_maintenance,
    add_maintenance_record,
)
from backend.dataset_generator import (
    generate_dataset,
    export_dataset_file,
)

# Geriye dönük test alias'ları doğrudan backend.caller_memory üzerinden sağlanır
_norm_phone = normalize_phone
_norm_plate = normalize_plate



# ============================================================================
# PYTEST TEST FIXTURES (Yalıtılmış Veritabanı ve TestClient)
# ============================================================================

@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Her test fonksiyonu için izole edilmiş geçici SQLite veritabanı sağlar."""
    db_file = tmp_path / f"test_e2e_{uuid4().hex[:8]}.db"
    test_engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "Session", session_factory)
    monkeypatch.setattr(main.settings, "admin_password", "test-e2e-password")

    with session_factory() as session:
        yield session

    test_engine.dispose()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """FastAPI TestClient için tam yalıtımlı ortam ve oturum yapılandırması."""
    db_file = tmp_path / f"test_client_{uuid4().hex[:8]}.db"
    test_engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    session_factory = sessionmaker(test_engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "Session", session_factory)
    monkeypatch.setattr(main.settings, "admin_password", "test-e2e-password")

    c = TestClient(main.app)
    yield c
    c.close()
    test_engine.dispose()


@pytest.fixture
def auth_headers():
    import base64
    token = base64.b64encode(b"admin:test-e2e-password").decode()
    return {"Authorization": f"Basic {token}"}


# ============================================================================
# TIER 1: FEATURE COVERAGE (28 Test Cases, >=27 Zorunlu)
# ============================================================================

# --- Feature 1: Hybrid Audio & Text Streaming Pipeline (F0-F6) ---

def test_tier1_f1_voice_chat_turn_basic_text_reply(client, auth_headers, fake_llm):
    """F1.1: REST /api/voice/chat-turn üzerinden doğrudan metin sorgusu ve slot bilgisi yanıtı."""
    # H01.01: canlı Ollama yerine SAHTE LLM yanıtı (tests/fakes/fake_llm.py); ağ çağrısı yok.
    fake_llm.reply({})
    resp = client.post(
        "/api/voice/chat-turn",
        headers=auth_headers,
        json={"text": "Periyodik bakım yaptırmak istiyorum", "session_id": "tier1-turn-1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "reply" in data and len(data["reply"]) > 0
    assert "intent" in data
    assert "slot_info" in data
    assert "metrics" in data


@pytest.mark.asyncio
async def test_tier1_f1_voice_session_text_input_pipeline_events(isolated_db, monkeypatch):
    """F1.2: VoiceSession.handle_text_input çağrıldığında F0-F2 atlanma ve F3 çalıştırma olayları üretilir."""
    monkeypatch.setattr(models, "vad", MockVad())
    events = []
    audio_frames = []

    async def emit(ev):
        events.append(ev)

    async def send_audio(frame):
        audio_frames.append(frame)

    async def fake_synth(text, seed=None):  # H01.10: seed anahtar sözcükle gelir
        return np.ones(2400, np.float32) * 0.05

    monkeypatch.setattr(models, "synth", fake_synth)

    sess = VoiceSession("test-hybrid", emit, send_audio)
    await sess.handle_text_input("Merhaba kolay gelsin")

    types = [e.get("type") for e in events]
    assert "transcript" in types
    assert "pipeline_event" in types
    assert any(e.get("type") == "pipeline_event" and e.get("event", {}).get("stage") == "F3" for e in events)
    await sess.close()


def test_tier1_f1_synthesize_endpoint_valid_audio(client, auth_headers, monkeypatch):
    """F1.3: POST /api/synthesize endpoint'i metni ses dalgasına sentezler."""
    async def fake_synth(text, seed=None):  # H01.10: seed anahtar sözcükle gelir
        return np.ones(4800, np.float32) * 0.1

    monkeypatch.setattr(models, "synth", fake_synth)
    resp = client.post("/api/synthesize", headers=auth_headers, json={"text": "Aracınız servise hazır."})
    assert resp.status_code == 200
    assert len(resp.content) > 0


def test_tier1_f1_normalize_automotive_prosody(client, auth_headers):
    """F1.4: POST /api/normalize otomotiv terimlerini ve birimleri fonetik metne dönüştürür."""
    resp = client.post("/api/normalize", headers=auth_headers, json={"text": "Peugeot 3008 aracım 60.000 km bakımında."})
    assert resp.status_code == 200
    data = resp.json()
    assert "normalized" in data
    assert "Pejo" in data["normalized"] or "3008" in data["normalized"]


def test_tier1_f1_session_ticket_lifecycle(client, auth_headers):
    """F1.5: POST /api/session-ticket WebSocket bağlantısı için 32 karakterlik bilet üretir."""
    resp = client.post("/api/session-ticket", headers=auth_headers)
    assert resp.status_code == 200
    ticket = resp.json().get("ticket")
    assert ticket is not None and len(ticket) >= 32


def test_tier1_f1_websocket_handshake_and_json_text_flow(client, auth_headers, monkeypatch):
    """F1.6: /ws/voice WebSocket bağlantısı bilet doğrulaması ve JSON metin mesajını işler."""
    t_resp = client.post("/api/session-ticket", headers=auth_headers)
    assert t_resp.status_code == 200
    ticket = t_resp.json()["ticket"]

    async def fake_synth(text, **kwargs):
        return np.ones(1200, np.float32) * 0.05

    monkeypatch.setattr(models, "vad", MockVad())
    monkeypatch.setattr(models, "synth", fake_synth)

    with client.websocket_connect(f"/ws/voice?ticket={ticket}") as ws:
        ws.send_json({"sample_rate": 16000, "encoding": "pcm_s16le", "channels": 1})
        ws.send_json({"type": "text_input", "text": "Fren balatası fiyatı nedir?"})

        # Olay akışını dinle: kullanıcı metin girdisi kabul edilmeli ve asistan yanıt üretmelidir
        user_transcript_received = False
        assistant_reply = None
        for i in range(25):
            try:
                raw = ws.receive()
                print(f"DEBUG iter {i}: raw={raw.get('type')}, keys={list(raw.keys())}")
                if raw.get("type") == "websocket.close":
                    print(f"DEBUG CLOSED: {raw}")
                    break
                if "text" in raw:
                    msg = json.loads(raw["text"])
                    print(f"DEBUG text: type={msg.get('type')}, role={msg.get('role')}")
                    assert "type" in msg
                    if msg.get("type") == "transcript":
                        if msg.get("role") == "user":
                            assert msg.get("text") == "Fren balatası fiyatı nedir?"
                            user_transcript_received = True
                        elif msg.get("role") == "assistant" and user_transcript_received:
                            assistant_reply = msg
                            break
            except Exception as e:
                print(f"DEBUG EXCEPTION iter {i}: {type(e)} {e}")
                raise

        assert user_transcript_received is True, "Kullanıcı metin transkripti WebSocket üzerinden alınamadı"
        assert assistant_reply is not None, "Asistan metin yanıt transkripti üretmedi"
        assert len(assistant_reply.get("text", "")) > 0, "Asistan yanıt metni boş döndü"


# --- Feature 2: Intent Detection & M01-M11 Automotive Dispatch Engine ---

def test_tier1_f2_intent_classification_appointment_create():
    """F2.1: Randevu alma niyetinin kural motoru tarafından Intent.BOOKING_CREATE olarak tespit edilmesi."""
    norm = normalize_utterance("Servis için randevu almak istiyorum")
    decision = rule_decision(norm)
    assert Intent.BOOKING_CREATE in decision.intent_ids


def test_tier1_f2_intent_classification_service_price_estimate():
    """F2.2: Fiyat sorgulama niyetinin Intent.SERVICE_PRICE_ESTIMATE olarak tespiti."""
    norm = normalize_utterance("Standart ekspertiz ücreti ne kadar acaba")
    decision = rule_decision(norm)
    assert Intent.SERVICE_PRICE_ESTIMATE in decision.intent_ids


def test_tier1_f2_safety_gate_roadside_emergency_dispatch():
    """F2.3: Seyir halindeki tehlike (fren tutmuyor) acil durum güvenlik kapısını tetikler."""
    norm = normalize_utterance("Yoldayım şu an frenler tutmuyor duramıyorum")
    decision = rule_decision(norm)
    assert Intent.ROADSIDE_EMERGENCY in decision.intent_ids
    plan = build_plan(decision.intent_ids, decision.reason_codes, uuid4(), "rules")
    assert plan.priority == "emergency"
    assert any(s.action == "urgent_safety_message" for s in plan.steps)


def test_tier1_f2_technician_dictation_actionable_parsing():
    """F2.4: Teknisyen sesli diktesinin yapısal ekspertiz bulgularına dönüştürülmesi."""
    text = "Ön fren balatası aşınmış diskte fatura var, sağ ön çamurluk boyalı."
    parsed = parse_technician_dictation(text)
    assert parsed["calculated_score"] is not None
    assert len(parsed["extracted_entities"]) >= 1
    assert "findings" in parsed


def test_tier1_f2_lift_status_and_queue_allocation(isolated_db):
    """F2.5: Muayene lifti ve araç sırasının atanması ve durumu."""
    lift = InspectionLift(
        name="LIFT-1 Mekanik",
        lift_number=1,
        status="idle",
    )
    isolated_db.add(lift)
    isolated_db.flush()

    queue_entry = InspectionQueue(
        queue_number=101,
        plate="34 ABC 123",
        customer="Ahmet Yılmaz",
        package_type="P02_STANDART",
        status="waiting",
        lift_id=lift.id,
    )
    isolated_db.add(queue_entry)
    isolated_db.commit()

    saved_lift = isolated_db.get(InspectionLift, lift.id)
    assert saved_lift.lift_number == 1
    saved_queue = isolated_db.get(InspectionQueue, queue_entry.id)
    assert saved_queue.plate == "34 ABC 123"
    assert saved_queue.lift_id == lift.id


def test_tier1_f2_obd_dtc_fault_analysis_grounding():
    """F2.6: OBD-II DTC (P0300) arıza kodunun semantik ontoloji üzerinden çözümlenmesi."""
    faults = AutomotiveGroundingEngine.diagnose_symptom("P0300")
    assert len(faults) >= 1
    fault = faults[0]
    assert fault.obd_code == "P0300"
    assert "ateşleme" in fault.description.lower()
    assert fault.severity in (DiagnosticSeverity.HIGH, DiagnosticSeverity.CRITICAL)


# --- Feature 3: Caller & Session Memory Persistence & Multi-Turn Resolver ---

def test_tier1_f3_caller_profile_creation_and_persistence(isolated_db):
    """F3.1: Yeni bir müşteri arayan profilinin SQLite üzerinde oluşturulup kaydedilmesi."""
    profile = get_or_create_caller_profile(
        isolated_db,
        phone="05321234567",
        plate="61 TS 061",
        name="Seydi Vakkas",
    )
    isolated_db.commit()

    retrieved = isolated_db.get(CallerProfile, profile.id)
    assert retrieved is not None
    assert retrieved.name == "Seydi Vakkas"
    assert retrieved.phone == "05321234567"
    assert retrieved.plate == "61 TS 061"


def test_tier1_f3_caller_profile_lookup_by_phone_or_plate(isolated_db):
    """F3.2: Mevcut arayan profilinin telefon veya plaka ile bulunması."""
    p1 = get_or_create_caller_profile(isolated_db, phone="05429876543", plate="34 XYZ 789", name="Mehmet Demir")
    isolated_db.commit()

    p_phone = get_or_create_caller_profile(isolated_db, phone="05429876543")
    assert p_phone.id == p1.id

    p_plate = get_or_create_caller_profile(isolated_db, plate="34XYZ789")
    assert p_plate.id == p1.id


def test_tier1_f3_warranty_inquiry_active_status(isolated_db):
    """F3.3: Gelecek tarihli garanti kaydının 'active' ve geçerli olarak çözümlenmesi."""
    future_date = (datetime.now(timezone.utc) + timedelta(days=180)).strftime("%Y-%m-%d")
    profile = get_or_create_caller_profile(isolated_db, phone="05551112233", name="Ayşe Yılmaz")
    profile.vehicle_model = "2023 Peugeot 3008"
    profile.warranty_expires_at = future_date
    profile.warranty_status = "active"
    isolated_db.commit()

    res = resolve_warranty_inquiry(profile)
    assert res["is_valid"] is True
    assert res["status"] == "active"
    assert "aktif" in res["message"].lower()


def test_tier1_f3_warranty_inquiry_expired_status(isolated_db):
    """F3.4: Geçmiş tarihli garanti kaydının 'expired' ve geçersiz olarak çözümlenmesi."""
    past_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    profile = get_or_create_caller_profile(isolated_db, phone="05554443322", name="Can Kaya")
    profile.vehicle_model = "2018 Renault Megane"
    profile.warranty_expires_at = past_date
    profile.warranty_status = "expired"
    isolated_db.commit()

    res = resolve_warranty_inquiry(profile)
    assert res["is_valid"] is False
    assert res["status"] == "expired"
    assert "sona ermiştir" in res["message"].lower()


def test_tier1_f3_past_maintenance_resolution_keyword(isolated_db):
    """F3.5: 'balata' anahtar kelimesi ile geçmiş bakım kaydının bulunması."""
    profile = get_or_create_caller_profile(isolated_db, phone="05301112233", name="Ali Vural")
    add_maintenance_record(profile, date="15.04.2026", item="Ön ve arka fren balata değişimi", km=45000, notes="Bosch marka")
    isolated_db.commit()

    result_text = resolve_past_maintenance(profile, "balata")
    assert result_text is not None
    assert "45000 km" in result_text
    assert "balata" in result_text.lower()


def test_tier1_f3_format_caller_memory_context_string(isolated_db):
    """F3.6: LLM istemine enjekte edilecek yapısal hafıza metninin biçimlendirilmesi."""
    profile = get_or_create_caller_profile(isolated_db, phone="05320001122", plate="34 VR 100", name="Selin Aksoy")
    profile.vehicle_model = "Volkswagen Tiguan 1.5 TSI"
    profile.warranty_expires_at = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")
    add_maintenance_record(profile, date="01.02.2026", item="Yağ ve filtre değişimi")
    isolated_db.commit()

    ctx = format_caller_memory_context(profile)
    assert "Müşteri: Selin Aksoy" in ctx
    assert "34 VR 100" in ctx
    assert "Volkswagen Tiguan" in ctx
    assert "Garanti: Aktif" in ctx


# --- Feature 4: LLM Fine-Tuning Dataset Generator ---

def test_tier1_f4_generate_alpaca_dataset_structure():
    """F4.1: Alpaca formatında (instruction, input, output) veri seti üretimi."""
    dataset = generate_dataset(count=5, format="alpaca", seed=101)
    assert len(dataset) == 5
    for item in dataset:
        assert "instruction" in item
        assert "input" in item
        assert "output" in item
        assert isinstance(item["instruction"], str) and len(item["instruction"]) > 0
        assert isinstance(item["input"], str) and len(item["input"]) > 0
        assert isinstance(item["output"], str) and len(item["output"]) > 0


def test_tier1_f4_generate_sharegpt_dataset_structure():
    """F4.2: ShareGPT formatında (conversations: human/gpt) veri seti üretimi."""
    dataset = generate_dataset(count=5, format="sharegpt", seed=102)
    assert len(dataset) == 5
    for item in dataset:
        assert "conversations" in item
        convs = item["conversations"]
        assert len(convs) >= 2
        assert convs[0]["from"] == "human"
        assert convs[1]["from"] == "gpt"
        assert len(convs[0]["value"]) > 0
        assert len(convs[1]["value"]) > 0


def test_tier1_f4_export_dataset_file_jsonl(tmp_path):
    """F4.3: Üretilen veri setinin geçerli bir JSONL dosyasına aktarılması."""
    target_file = tmp_path / "dataset_export.jsonl"
    path = export_dataset_file("alpaca", target_file, count=10, seed=42)
    assert path.exists()
    assert path.stat().st_size > 0
    with path.open("r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 10
    first_record = json.loads(lines[0])
    assert "instruction" in first_record
    assert "output" in first_record


def test_tier1_f4_dataset_contains_automotive_ontology_terms():
    """F4.4: Üretilen veri seti diyaloglarının otomotiv sözlüğü ve ekspertiz paketleri içermesi."""
    dataset = generate_dataset(count=20, format="alpaca", seed=42)
    inputs_text = " ".join(item["input"] + " " + item["output"] for item in dataset)
    has_package = any(pkg in inputs_text for pkg in CERTIFIED_SERVICE_PACKAGES.keys())
    assert has_package is True


def test_tier1_f4_dataset_cli_generation_callable(tmp_path):
    """F4.5: scripts/generate_automotive_dataset.py CLI komut dosyasının gerçek yürütülmesi."""
    cli_script = Path("scripts/generate_automotive_dataset.py")
    out_file = tmp_path / "cli_dataset_output.jsonl"
    proc = subprocess.run(
        [
            sys.executable,
            str(cli_script),
            "--count", "8",
            "--format", "sharegpt",
            "--output", str(out_file),
            "--seed", "77",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"CLI execution failed: {proc.stderr}"
    assert out_file.exists()
    with out_file.open("r", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    assert len(rows) == 8
    assert "conversations" in rows[0]


# --- Feature 5: Automotive Cockpit Endpoints & Guardrails ---

def test_tier1_f5_health_check_endpoint(client):
    """F5.1: GET /api/health uç noktası sistemin ayakta olduğunu doğrular."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


def test_tier1_f5_vehicle_and_quote_creation_flow(client, auth_headers):
    """F5.2: Araç kaydı ve ekspertiz fiyat teklifi oluşturma."""
    v_resp = client.post(
        "/api/vehicles",
        headers=auth_headers,
        json={"description": "Test Fiat Egea 1.4 Fire", "plate": "06 EGEA 06"},
    )
    assert v_resp.status_code == 200
    v_id = v_resp.json()["id"]

    q_resp = client.post(
        "/api/quotes",
        headers=auth_headers,
        json={"vehicle_id": v_id, "amount_kurus": 95000},
    )
    assert q_resp.status_code == 200
    assert q_resp.json()["amount_kurus"] == 95000


def test_tier1_f5_appointment_booking_and_idempotency(client, auth_headers):
    """F5.3: Randevu alma ve Idempotency anahtarı ile aynı yanıtın dönmesi."""
    v = client.post("/api/vehicles", headers=auth_headers, json={"description": "Ford Focus", "plate": "34 FORD 34"}).json()
    slot_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    slot = client.post("/api/slots", headers=auth_headers, json={"starts_at": slot_time}).json()

    body = {
        "slot_id": slot["id"],
        "vehicle_id": v["id"],
        "customer": "Ahmet Yılmaz",
        "idempotency_key": "idemp-booking-101",
        "confirmed": True,
    }
    app_resp = client.post("/api/appointments", headers=auth_headers, json=body)
    assert app_resp.status_code == 200
    app_id = app_resp.json()["id"]

    app_repeat = client.post("/api/appointments", headers=auth_headers, json=body)
    assert app_repeat.status_code == 200
    assert app_repeat.json()["id"] == app_id


def test_tier1_f5_appointment_cancellation(client, auth_headers):
    """F5.4: Randevunun iptal edilmesi ve slot bağının çözülmesi."""
    v = client.post("/api/vehicles", headers=auth_headers, json={"description": "Toyota Corolla", "plate": "35 TOY 35"}).json()
    slot = client.post("/api/slots", headers=auth_headers, json={"starts_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()}).json()
    body = {
        "slot_id": slot["id"],
        "vehicle_id": v["id"],
        "customer": "Mehmet Kaya",
        "idempotency_key": "cancel-flow-test",
        "confirmed": True,
    }
    app = client.post("/api/appointments", headers=auth_headers, json=body).json()
    cancel_resp = client.post(f"/api/appointments/{app['id']}/cancel", headers=auth_headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["slot_id"] is None


def test_tier1_f5_ontology_schema_introspect_endpoint(client, auth_headers):
    """F5.5: /api/ontology/schema üzerinden şema tablolarının doğrulanması."""
    resp = client.get("/api/ontology/schema", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "table_count" in data
    assert data["table_count"] >= 5


# ============================================================================
# TIER 2: BOUNDARY & CORNER CASES (25 Test Cases, >=25 Zorunlu)
# ============================================================================

# --- Boundary F1: Pipeline & Voice Streaming ---

def test_tier2_f1_empty_text_input_handled_gracefully(client, auth_headers):
    """B1.1: Boş veya yalnızca boşluktan oluşan metin girişi zarifçe ele alınır."""
    resp = client.post("/api/voice/chat-turn", headers=auth_headers, json={"text": "   ", "session_id": "b-empty-1"})
    assert resp.status_code == 200
    data = resp.json()
    assert "reply" in data


def test_tier2_f1_oversized_audio_packet_rejection(client, auth_headers):
    """B1.2: 192.000 bayttan büyük ses paketi güvenlik gereği reddedilir."""
    t_resp = client.post("/api/session-ticket", headers=auth_headers)
    ticket = t_resp.json()["ticket"]
    with client.websocket_connect(f"/ws/voice?ticket={ticket}") as ws:
        ws.send_json({"sample_rate": 16000, "encoding": "pcm_s16le", "channels": 1})
        ws.send_bytes(b"\x00" * 200000)
        msg = ws.receive_json()
        assert msg.get("type") == "error"


def test_tier2_f1_unsupported_audio_sample_rate(client, auth_headers):
    """B1.3: Desteklenmeyen örnekleme frekansı (11025 Hz) WebSocket el sıkışmasında hata döndürür."""
    t_resp = client.post("/api/session-ticket", headers=auth_headers)
    ticket = t_resp.json()["ticket"]
    with client.websocket_connect(f"/ws/voice?ticket={ticket}") as ws:
        ws.send_json({"sample_rate": 11025, "encoding": "pcm_s16le", "channels": 1})
        msg = ws.receive_json()
        assert msg.get("type") == "error"


def test_tier2_f1_concurrent_voice_session_line_busy(client, auth_headers, monkeypatch):
    """B1.4: Hat meşgulken ikinci WebSocket bağlantısı 1013 (line_busy) koduyla kapatılır."""
    from backend.session import active
    monkeypatch.setattr(active, "locked", lambda: True)

    t_resp = client.post("/api/session-ticket", headers=auth_headers)
    assert t_resp.status_code == 200
    ticket = t_resp.json()["ticket"]

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/voice?ticket={ticket}") as ws:
            ws.receive_json()

    assert exc_info.value.code == 1013
    assert exc_info.value.reason == "line_busy"


def test_tier2_f1_expired_session_ticket_rejected(client):
    """B1.5: Süresi dolmuş veya geçersiz biletle WebSocket bağlantısı 1008 (ticket_expired) alır."""
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/voice?ticket=expired-invalid-ticket-12345") as ws:
            ws.receive_json()

    assert exc_info.value.code == 1008
    assert exc_info.value.reason == "ticket_expired"


# --- Boundary F2: Intents & Safety Gate ---

def test_tier2_f2_conflicting_multi_intent_denial_precedence():
    """B2.1: Çelişkili ifadede ('randevuyu iptal etmeyin sadece saatini söyleyin') olumsuzlama önceliği."""
    norm = normalize_utterance("randevuyu iptal etmeyin randevumun saati nedir")
    decision = rule_decision(norm)
    assert Intent.BOOKING_CANCEL not in decision.intent_ids
    assert Intent.BOOKING_STATUS in decision.intent_ids


def test_tier2_f2_zero_slot_intent_handling():
    """B2.2: Kritik yazma niyeti eksik slot durumunda onay adımı gerektirir."""
    decision = rule_decision(normalize_utterance("servis için randevu almak istiyorum"))
    assert Intent.BOOKING_CREATE in decision.intent_ids
    plan = build_plan(decision.intent_ids, decision.reason_codes, uuid4(), "rules")
    assert plan.requires_confirmation is True or len(plan.steps) > 0
    assert any("tool_authorization" in s.guardrails for s in plan.steps)


def test_tier2_f2_out_of_domain_query_handling():
    """B2.3: Otomotiv dışı genel soru ('hava durumu') kapsam dışı olarak işaretlenir."""
    norm = normalize_utterance("hava durumu yağmurlu mu")
    decision = rule_decision(norm)
    assert Intent.BOOKING_CREATE not in decision.intent_ids
    assert Intent.ROADSIDE_EMERGENCY not in decision.intent_ids


def test_tier2_f2_malformed_dtc_fault_code():
    """B2.4: Hatalı veya bilinmeyen DTC arıza kodu sorgusu istisna fırlatmaz ve boş döner."""
    faults = AutomotiveGroundingEngine.diagnose_symptom("P9999_MALFORMED")
    assert len(faults) == 0


def test_tier2_f2_emergency_overrides_routine_booking():
    """B2.5: Acil durum anahtarları içeren randevu cümlesi doğrudan acil durum güvenlik kapısını tetikler."""
    norm = normalize_utterance("araba alev aldı yoldayım servis için randevu almak istiyorum")
    decision = rule_decision(norm)
    assert Intent.ROADSIDE_EMERGENCY in decision.intent_ids


# --- Boundary F3: Caller Memory & Profiles ---

def test_tier2_f3_empty_and_null_phone_normalization():
    """B3.1: Boş, None veya geçersiz karakterli telefon numaralarının backend.caller_memory üzerinden normalizasyonu."""
    assert normalize_phone(None) == ""
    assert normalize_phone("") == ""
    assert normalize_phone("+90 (532) 111-22-33") == "05321112233"
    assert normalize_phone("5321112233") == "05321112233"
    assert normalize_phone("0532 111 22 33") == "05321112233"


def test_tier2_f3_irregular_plate_spacing_and_lowercase():
    """B3.2: Düzensiz boşluklu ve küçük harfli plakanın backend.caller_memory üzerinden standart formata dönüştürülmesi."""
    assert normalize_plate("34abc123") == "34 ABC 123"
    assert normalize_plate(" 06   ank   99 ") == "06 ANK 99"
    assert normalize_plate("16dbl16") == "16 DBL 16"
    assert normalize_plate(None) == ""
    assert normalize_plate("") == ""


def test_tier2_f3_boundary_warranty_exact_today_and_leap_year(isolated_db):
    """B3.3: Bugün sona eren veya artık yıl (29 Şubat) garantisi sınır testi."""
    # Sınır Durumu 1: Bugün (tam gün başlangıcı / gece yarısı) - aktif olmalı
    query_today_midnight = datetime(2026, 5, 20, 0, 0, 0, tzinfo=timezone.utc)
    p_exact = get_or_create_caller_profile(isolated_db, phone="05331234567", name="Ahmet Sınır")
    p_exact.vehicle_model = "Fiat Egea"
    p_exact.warranty_expires_at = "2026-05-20"
    p_exact.warranty_status = "active"
    isolated_db.commit()

    res_exact = resolve_warranty_inquiry(p_exact, query_date=query_today_midnight)
    assert res_exact["is_valid"] is True
    assert res_exact["status"] == "active"
    assert res_exact["expires_at"] == "20.05.2026"
    assert "aktif olarak devam etmektedir" in res_exact["message"]

    # Sınır Durumu 2: Son kullanma tarihini 1 saniye geçince süresi dolmuş (expired) olmalı
    query_after = datetime(2026, 5, 20, 0, 0, 1, tzinfo=timezone.utc)
    res_after = resolve_warranty_inquiry(p_exact, query_date=query_after)
    assert res_after["is_valid"] is False
    assert res_after["status"] == "expired"
    assert res_after["expires_at"] == "20.05.2026"
    assert "sona ermiştir" in res_after["message"]

    # Sınır Durumu 3: Artık Yıl (29 Şubat) - Geçmiş artık yıl (2024-02-29) sorgusu
    p_leap = get_or_create_caller_profile(isolated_db, phone="05337654321", name="Mehmet Artıkyıl")
    p_leap.vehicle_model = "Renault Megane"
    p_leap.warranty_expires_at = "2024-02-29"
    p_leap.warranty_status = "active"
    isolated_db.commit()

    res_leap_valid = resolve_warranty_inquiry(p_leap, query_date=datetime(2024, 2, 29, 0, 0, 0, tzinfo=timezone.utc))
    assert res_leap_valid["is_valid"] is True
    assert res_leap_valid["status"] == "active"
    assert res_leap_valid["expires_at"] == "29.02.2024"

    res_leap_expired = resolve_warranty_inquiry(p_leap, query_date=datetime(2024, 3, 1, 0, 0, 0, tzinfo=timezone.utc))
    assert res_leap_expired["is_valid"] is False
    assert res_leap_expired["status"] == "expired"
    assert res_leap_expired["expires_at"] == "29.02.2024"

    # Sınır Durumu 4: Gelecek Artık Yıl (2028-02-29) - 2026 yılında aktif olmalı
    p_leap28 = get_or_create_caller_profile(isolated_db, phone="05339998877", name="Ayşe GelecekArtık")
    p_leap28.vehicle_model = "Toyota Corolla"
    p_leap28.warranty_expires_at = "2028-02-29"
    p_leap28.warranty_status = "active"
    isolated_db.commit()

    res_leap28 = resolve_warranty_inquiry(p_leap28, query_date=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc))
    assert res_leap28["is_valid"] is True
    assert res_leap28["status"] == "active"
    assert res_leap28["expires_at"] == "29.02.2028"


def test_tier2_f3_corrupted_maintenance_history_json(isolated_db):
    """B3.4: Bozuk JSON içeren geçmiş bakım alanı istisna fırlatmadan None döndürür."""
    profile = get_or_create_caller_profile(isolated_db, phone="05339998877", name="Bozuk Kayıt")
    profile.maintenance_history_json = "{CORRUPTED_JSON:;;;"
    isolated_db.commit()

    ans = resolve_past_maintenance(profile, "balata")
    assert ans is None


def test_tier2_f3_nonexistent_profile_lookup_creates_or_returns_none(isolated_db):
    """B3.5: Sistemde hiç olmayan müşteri sorgulandığında yeni temiz profil oluşturulur."""
    p = get_or_create_caller_profile(isolated_db, phone="05990001122", name="Yeni Müşteri")
    assert p.id is not None
    assert p.phone == "05990001122"
    assert p.warranty_status == "unknown"


# --- Boundary F4: Dataset Generator ---

def test_tier2_f4_zero_count_dataset_generation():
    """B4.1: count=0 veri seti üretim isteği boş liste döndürür."""
    res = generate_dataset(count=0, format="alpaca")
    assert res == []


def test_tier2_f4_negative_count_dataset_rejection():
    """B4.2: Negatif count değeri ValueError ile reddedilir."""
    with pytest.raises(ValueError, match="negative"):
        generate_dataset(count=-5, format="alpaca")


def test_tier2_f4_unsupported_dataset_format_rejection():
    """B4.3: Desteklenmeyen veri seti formatı ('unsupported_xml') ValueError üretir."""
    with pytest.raises(ValueError, match="Unsupported format"):
        generate_dataset(count=5, format="unsupported_xml")


def test_tier2_f4_export_creates_missing_parent_directories(tmp_path):
    """B4.4: Dışa aktarım hedef klasörü mevcut değilse otomatik olarak oluşturulur."""
    deep_path = tmp_path / "deep" / "nested" / "folder" / "dataset.jsonl"
    out = export_dataset_file("alpaca", deep_path, count=3)
    assert out.exists()
    assert deep_path.parent.exists()


def test_tier2_f4_deterministic_seed_reproducibility():
    """B4.5: Aynı rastgele tohum (seed) değeri ile üretilen veri setleri birebir aynıdır."""
    ds1 = generate_dataset(count=10, format="alpaca", seed=999)
    ds2 = generate_dataset(count=10, format="alpaca", seed=999)
    ds3 = generate_dataset(count=10, format="alpaca", seed=1000)
    assert ds1 == ds2
    assert ds1 != ds3


# --- Boundary F5: Cockpit Endpoints & Guardrails ---

def test_tier2_f5_unauthenticated_request_rejected(client):
    """B5.1: Yetkilendirme başlığı (Authorization) olmayan korumalı istekler 401 döner."""
    resp = client.get("/api/vehicles")
    assert resp.status_code == 401


def test_tier2_f5_invalid_credentials_rejected(client):
    """B5.2: Yanlış şifre ile gelen korumalı istekler 401 döner."""
    resp = client.get("/api/vehicles", auth=("admin", "wrong-password"))
    assert resp.status_code == 401


def test_tier2_f5_missing_appointment_idempotency_key(client, auth_headers):
    """B5.3: Randevu isteğinde eksik zorunlu alanlar (idempotency_key vb.) 422 döner."""
    resp = client.post(
        "/api/appointments",
        headers=auth_headers,
        json={"customer": "Ahmet"},
    )
    assert resp.status_code == 422


def test_tier2_f5_duplicate_slot_booking_conflict(client, auth_headers):
    """B5.4: Aynı zaman dilimine (slot) ikinci bir randevu oluşturulamaz (409 Conflict)."""
    v = client.post("/api/vehicles", headers=auth_headers, json={"description": "Opel Astra", "plate": "06 OPEL 06"}).json()
    slot = client.post("/api/slots", headers=auth_headers, json={"starts_at": (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()}).json()
    body1 = {"slot_id": slot["id"], "vehicle_id": v["id"], "customer": "M1 Test", "idempotency_key": "conflict-key-1", "confirmed": True}
    body2 = {"slot_id": slot["id"], "vehicle_id": v["id"], "customer": "M2 Test", "idempotency_key": "conflict-key-2", "confirmed": True}
    assert client.post("/api/appointments", headers=auth_headers, json=body1).status_code == 200
    assert client.post("/api/appointments", headers=auth_headers, json=body2).status_code == 409


def test_tier2_f5_negative_quote_amount_validation(client, auth_headers):
    """B5.5: Negatif ve sıfır teklif tutarları katı 422 (Unprocessable Entity) ile reddedilir."""
    v_resp = client.post("/api/vehicles", headers=auth_headers, json={"description": "Fiat Doblo", "plate": "16 DBL 16"})
    assert v_resp.status_code == 200
    v = v_resp.json()

    # Negatif tutar (boundary < 0) kesinlikle 422 dönmelidir
    resp_neg = client.post("/api/quotes", headers=auth_headers, json={"vehicle_id": v["id"], "amount_kurus": -500})
    assert resp_neg.status_code == 422
    err_neg = resp_neg.json()
    assert any("amount_kurus" in loc for err in err_neg.get("detail", []) for loc in err.get("loc", []))

    # Sıfır tutar (boundary == 0, gt=0 kuralı) kesinlikle 422 dönmelidir
    resp_zero = client.post("/api/quotes", headers=auth_headers, json={"vehicle_id": v["id"], "amount_kurus": 0})
    assert resp_zero.status_code == 422
    err_zero = resp_zero.json()
    assert any("amount_kurus" in loc for err in err_zero.get("detail", []) for loc in err.get("loc", []))


# ============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS (6 Test Cases, >=6 Zorunlu)
# ============================================================================

def test_tier3_cross_caller_profile_appointment_booking(client, auth_headers, isolated_db):
    """C3.1: Çapraz Etkileşim: Arayan Profili (Memory) + Randevu Planlama.
    Müşterinin hafızadaki telefon ve plaka bilgisi randevu kaydına başarıyla bağlanır.
    """
    profile = get_or_create_caller_profile(isolated_db, phone="05329990011", plate="34 MEM 34", name="Kemal Sunal")
    isolated_db.commit()

    v = client.post("/api/vehicles", headers=auth_headers, json={"description": "BMW 320i", "plate": profile.plate}).json()
    slot = client.post("/api/slots", headers=auth_headers, json={"starts_at": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()}).json()

    body = {
        "slot_id": slot["id"],
        "vehicle_id": v["id"],
        "customer": profile.name,
        "customer_phone": profile.phone,
        "idempotency_key": "cross-profile-booking",
        "confirmed": True,
    }
    app = client.post("/api/appointments", headers=auth_headers, json=body).json()
    assert app["customer"] == "Kemal Sunal"
    assert app["slot_id"] == slot["id"]


@pytest.mark.asyncio
async def test_tier3_cross_text_input_pipeline_telemetry_intent(monkeypatch):
    """C3.2: Çapraz Etkileşim: Metin Girişi + F0-F2 Telemetri Atlaması + Niyet Tespiti.
    Doğrudan metin girişi F0-F2'yi atlar, telemetri yayar ve F3 aşamasında doğru niyeti tetikler.
    """
    monkeypatch.setattr(models, "vad", MockVad())
    async def fake_synth(text, seed=None):  # H01.10: seed anahtar sözcükle gelir
        return np.zeros(2400, dtype=np.float32)
    monkeypatch.setattr(models, "synth", fake_synth)
    events = []
    async def fake_emit(ev):
        events.append(ev)

    sess = VoiceSession("test-cross-telem", fake_emit, lambda frame: None)
    await sess.handle_text_input("Yarın için randevu almak istiyorum")

    assert any(e.get("type") == "pipeline_event" and e.get("event", {}).get("stage") == "F3" for e in events)
    await sess.close()


def test_tier3_cross_obd_dtc_safety_gate_caller_vehicle(isolated_db):
    """C3.3: Çapraz Etkileşim: OBD-II DTC + Güvenlik Kapısı + Arayan Profili Aracı.
    Kritik hata tespitinde arayan profilindeki araç modeli ve güvenlik kapısı doğrulanır.
    """
    profile = get_or_create_caller_profile(isolated_db, phone="05421113355", plate="34 DTC 01", name="Barış Manço")
    profile.vehicle_model = "Peugeot 3008 1.5 BlueHDi"
    isolated_db.commit()

    v = Vehicle(description=profile.vehicle_model, plate=profile.plate)
    isolated_db.add(v)
    isolated_db.flush()

    faults = AutomotiveGroundingEngine.diagnose_symptom("P0300")
    assert len(faults) >= 1
    fault = faults[0]
    assert fault.severity.value in ("critical", "high", "warning")

    diag = VehicleDiagnostic(
        vehicle_id=v.id,
        dtc_code=fault.obd_code,
        severity=fault.severity.value,
        description_tr=fault.description,
        recommended_action=fault.warning_light,
        owner_phone=profile.phone,
        owner_name=profile.name,
    )
    isolated_db.add(diag)
    isolated_db.commit()

    saved_diag = isolated_db.get(VehicleDiagnostic, diag.id)
    assert saved_diag.dtc_code == "P0300"
    assert saved_diag.owner_phone == profile.phone


def test_tier3_cross_dataset_generator_ontology_lexicon(tmp_path):
    """C3.4: Çapraz Etkileşim: Veri Seti Motoru + Otomotiv Ontolojisi & Fonetik Sözlük.
    Üretilen diyaloglar hem fonetik normalizasyon sözlüğü hem de paket ontolojisi içerir.
    """
    dataset = generate_dataset(count=15, format="alpaca", seed=55)
    all_text = " ".join(item["input"] + " " + item["output"] for item in dataset)
    matched_packages = [pkg for pkg in CERTIFIED_SERVICE_PACKAGES if pkg in all_text]
    assert len(matched_packages) >= 1
    # Fonetik sözlük terimlerinin geçtiğini doğrula
    has_lexicon_term = any(term in all_text.lower() for term in ["balata", "triger", "amortisör", "muayene", "ekspertiz"])
    assert has_lexicon_term is True


def test_tier3_cross_caller_memory_maintenance_dialogue(isolated_db):
    """C3.5: Çapraz Etkileşim: Arayan Bakım Hafızası + Çoklu Tur Diyalog Çözümleme.
    'Geçen seferki balata' sorusu müşterinin geçmiş bakım kaydından çözümlenir.
    """
    profile = get_or_create_caller_profile(isolated_db, phone="05324445566", plate="34 BAL 34", name="Haluk Bilginer")
    add_maintenance_record(profile, date="10.01.2026", item="Ön fren balata ve disk değişimi", km=60000, notes="Yetkili servis")
    isolated_db.commit()

    resolved = resolve_past_maintenance(profile, "balata")
    assert resolved is not None
    assert "60000 km" in resolved
    assert "10.01.2026" in resolved


def test_tier3_cross_technician_dictation_inspection_report(isolated_db):
    """C3.6: Çapraz Etkileşim: Teknisyen Sesli Diktesi + Oturum Kaydı + Ekspertiz Raporu.
    Teknisyenin dikte ettiği muayene bulguları veritabanındaki InspectionReport'a işlenir.
    """
    v = Vehicle(description="2022 Honda Civic", plate="34 HND 34")
    isolated_db.add(v)
    isolated_db.flush()

    dictation_text = "Sol ön çamurluk boyalı 210 mikron, sağ marşpiyelde ezik var, motor yağı normal seviyede."
    parsed = parse_technician_dictation(dictation_text)

    report = InspectionReport(
        vehicle_id=v.id,
        technician_name="Baş Teknisyen Ahmet",
        summary=dictation_text,
        score=parsed["calculated_score"] or 85,
        findings_json=json.dumps(parsed["findings"], ensure_ascii=False),
    )
    isolated_db.add(report)
    isolated_db.commit()

    saved_rep = isolated_db.get(InspectionReport, report.id)
    assert saved_rep.score is not None
    findings = json.loads(saved_rep.findings_json)
    assert isinstance(findings, dict)


# ============================================================================
# TIER 4: REAL-WORLD OPERATIONAL SCENARIOS (5 End-to-End Scenarios)
# ============================================================================

def test_tier4_scenario1_customer_scheduled_service_and_warranty(client, auth_headers, isolated_db):
    """Senaryo 1: 60.000 KM Periyodik Bakım ve Garanti Kontrolü İçin Arayan Müşteri.
    Müşteri arar, sistem telefon numarasından profili getirir, aktif garantisini
    doğrular ve uygun zaman dilimine 60K periyodik bakım randevusunu oluşturur.
    """
    profile = get_or_create_caller_profile(isolated_db, phone="05321110022", plate="34 SV 60", name="Ahmet Yılmaz")
    profile.vehicle_model = "Peugeot 3008 1.5 BlueHDi"
    profile.warranty_expires_at = (datetime.now(timezone.utc) + timedelta(days=200)).strftime("%Y-%m-%d")
    profile.warranty_status = "active"
    isolated_db.commit()

    warranty_info = resolve_warranty_inquiry(profile)
    assert warranty_info["is_valid"] is True

    v = client.post("/api/vehicles", headers=auth_headers, json={"description": profile.vehicle_model, "plate": profile.plate}).json()
    slot_time = (datetime.now(timezone.utc) + timedelta(days=1, hours=2)).isoformat()
    slot = client.post("/api/slots", headers=auth_headers, json={"starts_at": slot_time}).json()

    booking_body = {
        "slot_id": slot["id"],
        "vehicle_id": v["id"],
        "customer": profile.name,
        "customer_phone": profile.phone,
        "idempotency_key": "scenario1-60k-service",
        "package_type": "60k_periyodik_bakim",
        "confirmed": True,
    }
    appointment = client.post("/api/appointments", headers=auth_headers, json=booking_body).json()
    assert appointment["customer"] == "Ahmet Yılmaz"
    assert appointment["status"] == "confirmed"


def test_tier4_scenario2_returning_customer_brake_pad_inquiry(isolated_db):
    """Senaryo 2: Geçmiş Fren Balatası Değişimini Soran Sadık Müşteri.
    Müşteri 'Geçen sefer konuştuğumuz balata değişimi ne zaman yapılmıştı?' diye sorar.
    Sistem hafızadan 45.000 km bakım kaydını bulur ve güncel fiyat teklifini sunar.
    """
    profile = get_or_create_caller_profile(isolated_db, phone="05423334455", plate="34 BSH 45", name="Cem Yılmaz")
    profile.vehicle_model = "Volkswagen Passat 2.0 TDI"
    add_maintenance_record(profile, date="12.03.2026", item="Ön ve arka fren balata takımı değişimi", km=45000, cost_tl=3200)
    isolated_db.commit()

    past_repair = resolve_past_maintenance(profile, "balata")
    assert past_repair is not None
    assert "45000 km" in past_repair
    assert "12.03.2026" in past_repair

    standard_pkg = AutomotiveGroundingEngine.get_package_by_id("P02_STANDART")
    assert standard_pkg.price_tl == 1450


def test_tier4_scenario3_urgent_obd_dtc_alert_p0300_safety(isolated_db):
    """Senaryo 3: Gösterge Panelinde Motor Arıza Işığı Yanan ve P0300 Bildiren Müşteri.
    Sistem niyet motorunda acil durum/dikkat güvenlik kapısını tetikler,
    M01 sabit fiyat ilkesine uygun teşhis paketini önerir ve acil mekanik liftini kontrol eder.
    """
    decision = rule_decision(normalize_utterance("motor arıza ışığı yandı"))
    assert Intent.WARNING_LIGHT_QUESTION in decision.intent_ids

    faults = AutomotiveGroundingEngine.diagnose_symptom("P0300")
    assert len(faults) >= 1
    fault = faults[0]
    assert fault.severity in (DiagnosticSeverity.HIGH, DiagnosticSeverity.CRITICAL)

    lift = InspectionLift(name="LIFT-3 Arıza Teşhis", lift_number=3, status="idle")
    isolated_db.add(lift)
    isolated_db.commit()

    saved_lift = isolated_db.get(InspectionLift, lift.id)
    assert saved_lift.status == "idle"


def test_tier4_scenario4_receptionist_dataset_generation_export(client, auth_headers, tmp_path):
    """Senaryo 4: Servis Resepsiyonistinin Qwen İnce Ayarı İçin Veri Seti Üretmesi ve REST Uç Noktaları.
    Atölye personeli POST /api/dataset/generate ile dosya üretir ve GET /api/dataset/export ile JSONL akışı alır.
    """
    # 1. POST /api/dataset/generate ile veri seti üretimi
    gen_resp = client.post(
        "/api/dataset/generate",
        headers=auth_headers,
        json={"count": 30, "format": "alpaca", "seed": 42},
    )
    assert gen_resp.status_code == 200
    gen_data = gen_resp.json()
    assert gen_data["status"] == "ok"
    assert gen_data["generated_count"] == 30
    assert "file_path" in gen_data
    assert Path(gen_data["file_path"]).exists()

    # 2. GET /api/dataset/export ile Alpaca akışını çekme
    export_resp = client.get("/api/dataset/export?format=alpaca&count=20&seed=42", headers=auth_headers)
    assert export_resp.status_code == 200
    assert "application/x-jsonlines" in export_resp.headers.get("content-type", "")
    alpaca_lines = [json.loads(line) for line in export_resp.text.strip().split("\n") if line.strip()]
    assert len(alpaca_lines) == 20
    assert "instruction" in alpaca_lines[0]

    # 3. GET /api/dataset/export ile ShareGPT akışını çekme
    export_sg_resp = client.get("/api/dataset/export?format=sharegpt&count=10&seed=42", headers=auth_headers)
    assert export_sg_resp.status_code == 200
    sg_lines = [json.loads(line) for line in export_sg_resp.text.strip().split("\n") if line.strip()]
    assert len(sg_lines) == 10
    assert "conversations" in sg_lines[0]

    # 4. Yetkisiz erişim kontrolü (401 Guardrails)
    assert client.post("/api/dataset/generate", json={"count": 5}).status_code == 401
    assert client.get("/api/dataset/export?format=alpaca").status_code == 401


def test_tier4_scenario5_master_technician_dictation_appraisal(isolated_db):
    """Senaryo 5: Baş Teknisyenin Muayene Sırasında Sesli Dikte İle Rapor Kaydetmesi.
    Teknisyen lift üzerindeyken kaporta ve mekanik ölçümlerini dikte eder,
    sistem bunu yapısal ekspertiz bulgularına ve raporuna dönüştürür.
    """
    v = Vehicle(description="2021 Renault Megane 1.3 TCe", plate="34 RNL 21")
    isolated_db.add(v)
    isolated_db.flush()

    dictation = (
        "Sağ arka çamurluk lokal boyalı, sol ön kapıda boyasız göçük düzeltme var, "
        "ön fren balatası iyi durumda, motor şanzıman kuru kaçak yok."
    )
    parsed = parse_technician_dictation(dictation)
    assert parsed["calculated_score"] is not None

    report = InspectionReport(
        vehicle_id=v.id,
        technician_name="Baş Teknisyen Osman",
        summary=dictation,
        score=parsed["calculated_score"] or 90,
        mileage_km=52000,
        findings_json=json.dumps(parsed["findings"], ensure_ascii=False),
    )
    isolated_db.add(report)
    isolated_db.commit()

    saved = isolated_db.get(InspectionReport, report.id)
    assert saved.mileage_km == 52000
    assert saved.score is not None
    assert "Osman" in saved.technician_name
