# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Madde 5: KVKK Transkript Saklama Süresi ve Silme Talebi (Unutulma Hakkı) Test Paketi.

Kapsanan Yetenekler:
1. Transkript saklama süresi denetimi (retention audit)
2. Süresi dolmuş transkriptlerin otomatik/manuel anonimleştirilerek imhası (retention purge)
3. KVKK Madde 11 uyarınca Unutulma Hakkı silme talebi kaydı ve etki analizi (erasure impact)
4. Silme talebini bağlı tüm tablolarda icra etme (transcripts, audio files, appointments, whatsapp, analytics, etc.)
5. Kriptografik SHA-256 ve HMAC imzalı resmi KVKK İmha Tutanağı üretimi
6. REST API uç noktalarının (audit, purge, requests, execute, certificate) uçtan uca doğrulanması
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.db import (
    Appointment,
    AudioArchive,
    Base,
    CallAnalytics,
    Conversation,
    KVKKErasureRequest,
    NotificationOutbox,
    OutboundCall,
    RuhsatScan,
    Slot,
    Turn,
    Vehicle,
    WhatsAppMessage,
    now,
)
from backend import db as db_module
from backend.kvkk_compliance import (
    audit_transcript_retention,
    create_erasure_request,
    execute_erasure,
    generate_certificate_text,
    purge_expired_transcripts,
    scan_erasure_impact,
)
from backend.main import app
from backend.schemas import KVKKErasureRequestIn


@pytest.fixture
def test_db_session(monkeypatch, tmp_path):
    """Her test için izole SQLite veritabanı oturumu sağlar."""
    engine = create_engine(
        f"sqlite:///{tmp_path}/test_madde5_kvkk.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "Session", TestingSession)

    with TestingSession() as session:
        yield session

    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db_session):
    c = TestClient(app)
    c.auth = ("admin", settings.admin_password)
    return c


# ============================================================================
# 1. TRANSKRİPT SAKLAMA SÜRESİ DENETİMİ (AUDIT)
# ============================================================================


def test_transcript_retention_audit_calculation(test_db_session):
    """Saklama süresi dolmuş ve aktif konuşmaların doğru hesaplanması."""
    now_dt = datetime.now(timezone.utc)
    old_dt = (now_dt - timedelta(days=45)).isoformat()
    recent_dt = (now_dt - timedelta(days=10)).isoformat()

    # 1. Süresi dolmuş görüşme ve turları
    c1 = Conversation(channel="audiosocket", status="active", created_at=old_dt)
    test_db_session.add(c1)
    test_db_session.flush()
    t1 = Turn(conversation_id=c1.id, role="user", text="Eski görüşme metni 1", created_at=old_dt)
    t2 = Turn(conversation_id=c1.id, role="assistant", text="Eski yanıt 1", created_at=old_dt)
    test_db_session.add_all([t1, t2])

    # 2. Yakın tarihli (geçerli) görüşme
    c2 = Conversation(channel="audiosocket", status="active", created_at=recent_dt)
    test_db_session.add(c2)
    test_db_session.flush()
    t3 = Turn(conversation_id=c2.id, role="user", text="Güncel görüşme", created_at=recent_dt)
    test_db_session.add(t3)

    # 3. Zaten imha edilmiş görüşme
    c3 = Conversation(channel="audiosocket", status="purged", created_at=old_dt)
    test_db_session.add(c3)

    test_db_session.commit()

    # Varsayılan 30 günlük ilke ile denetle
    audit = audit_transcript_retention(test_db_session, retention_days=30)
    assert audit["retention_policy_days"] == 30
    assert audit["total_conversations"] == 3
    assert audit["active_conversations"] == 2
    assert audit["already_purged_conversations"] == 1
    assert audit["expired_conversations_count"] == 1
    assert audit["expired_turns_count"] == 2
    assert audit["compliance_status"] == "action_required"

    # 60 günlük ilke ile denetlendiğinde hiçbir görüşme süresi dolmuş olmamalı
    audit_60 = audit_transcript_retention(test_db_session, retention_days=60)
    assert audit_60["expired_conversations_count"] == 0
    assert audit_60["compliance_status"] == "compliant"


# ============================================================================
# 2. SÜRESİ DOLMUŞ TRANSKRİPTLERİN İMHASI (PURGE)
# ============================================================================


def test_transcript_retention_purge_dry_run_and_execution(test_db_session):
    """Transkript imhasının dry-run önizleme ve kalıcı çalıştırma davranışı."""
    old_dt = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()

    conv = Conversation(channel="telephony", status="closed", created_at=old_dt)
    test_db_session.add(conv)
    test_db_session.flush()

    t1 = Turn(conversation_id=conv.id, role="user", text="Müşteri hassas verisi: 05321112233", created_at=old_dt)
    t2 = Turn(conversation_id=conv.id, role="assistant", text="Randevunuz onaylandı", created_at=old_dt)
    test_db_session.add_all([t1, t2])
    test_db_session.commit()

    # 1. Dry Run testi: Veritabanı değişmemeli
    dry_res = purge_expired_transcripts(test_db_session, dry_run=True, retention_days=30)
    assert dry_res["dry_run"] is True
    assert dry_res["purged_conversations"] == 1
    assert dry_res["purged_turns"] == 2

    # Orijinal metinlerin korunduğunu doğrula
    re_t1 = test_db_session.get(Turn, t1.id)
    assert "05321112233" in re_t1.text
    re_conv = test_db_session.get(Conversation, conv.id)
    assert re_conv.status == "closed"

    # 2. Kalıcı İmha testi
    purge_res = purge_expired_transcripts(test_db_session, dry_run=False, retention_days=30)
    assert purge_res["dry_run"] is False
    assert purge_res["purged_conversations"] == 1
    assert purge_res["purged_turns"] == 2

    # Metinlerin anonimleştirildiğini ve durumun 'purged' olduğunu doğrula
    test_db_session.refresh(re_t1)
    test_db_session.refresh(re_conv)
    assert re_t1.text == "[KVKK_SURESI_DOLDU_SILINDI]"
    assert re_conv.status == "purged"
    assert "KVKK Saklama Süresi Doldu" in re_conv.operator_notes

    # 3. İkinci çalıştırmada (idempotent) 0 kayıt bulunmalı
    second_res = purge_expired_transcripts(test_db_session, dry_run=False, retention_days=30)
    assert second_res["purged_conversations"] == 0
    assert second_res["purged_turns"] == 0


# ============================================================================
# 3. VERİ SİLME TALEBİ VE ETKİ ANALİZİ (SCAN & CREATE)
# ============================================================================


def test_scan_erasure_impact_phone_identifier(test_db_session, tmp_path):
    """Telefon numarasına bağlı tüm ilişkili kayıtların etki analizi ile tespiti."""
    phone = "05321234567"

    # Araç ve Randevu
    veh = Vehicle(description="Renault Megane 1.3 TCe", plate="34 ABC 77")
    test_db_session.add(veh)
    test_db_session.flush()

    slot = Slot(starts_at="2026-11-20T10:00:00+03:00", duration_minutes=30)
    test_db_session.add(slot)
    test_db_session.flush()

    appt = Appointment(
        slot_id=slot.id,
        vehicle_id=veh.id,
        customer="Mehmet Demir",
        customer_phone=phone,
        idempotency_key="test-key-kvkk-1",
        confirmed=True,
    )
    test_db_session.add(appt)
    test_db_session.flush()

    # Konuşma ve Tur
    conv = Conversation(channel="audiosocket", status="active")
    test_db_session.add(conv)
    test_db_session.flush()

    turn = Turn(conversation_id=conv.id, role="user", text="Mehmet Demir, 05321234567")
    test_db_session.add(turn)

    # Ses Kaydı
    audio_file = tmp_path / "rec_test.opus"
    audio_file.write_bytes(b"dummy_opus_data")
    audio = AudioArchive(
        conversation_id=conv.id,
        caller_phone=phone,
        file_path=str(audio_file),
        sha256_hash="abc123hash",
    )
    test_db_session.add(audio)

    # WhatsApp Mesajı
    wa = WhatsAppMessage(
        from_phone=phone,
        customer_name="Mehmet Demir",
        raw_content="Randevu saatimi değiştirmek istiyorum",
        appointment_id=appt.id,
    )
    test_db_session.add(wa)

    # Çağrı Analitiği
    ca = CallAnalytics(
        conversation_id=conv.id,
        appointment_id=appt.id,
        caller_phone=phone,
        caller_name="Mehmet Demir",
        executive_summary="Müşteri ekspertiz paketi sordu.",
    )
    test_db_session.add(ca)

    # Giden Arama
    ob = OutboundCall(
        appointment_id=appt.id,
        phone=phone,
        customer="Mehmet Demir",
    )
    test_db_session.add(ob)

    # Bildirim
    notif = NotificationOutbox(
        appointment_id=appt.id,
        recipient_type="customer",
        recipient=phone,
        message="Sayın Mehmet Demir randevunuz oluşturuldu.",
        idempotency_key="notif-key-1",
    )
    test_db_session.add(notif)
    test_db_session.commit()

    # Etki analizini çalıştır
    impact = scan_erasure_impact(test_db_session, "phone", phone)
    assert impact["appointments_count"] == 1
    assert impact["conversations_count"] == 1
    assert impact["turns_count"] == 1
    assert impact["audio_archives_count"] == 1
    assert impact["whatsapp_messages_count"] == 1
    assert impact["call_analytics_count"] == 1
    assert impact["outbound_calls_count"] == 1
    assert impact["notifications_count"] == 1
    assert impact["total_records_affected"] == 8


def test_create_erasure_request(test_db_session):
    """Yeni silme talebinin oluşturulması ve etki özetinin kaydedilmesi."""
    payload = KVKKErasureRequestIn(
        identifier_type="phone",
        identifier_value="05329998877",
        requester_name="Ali Veli",
        reason="Kişisel verilerimin silinmesini talep ediyorum.",
        notes="Vekaletname ibraz edildi.",
    )
    req = create_erasure_request(test_db_session, payload=payload, requester="operator_1")
    assert req.id is not None
    assert req.status == "pending"
    assert req.identifier_value == "05329998877"
    assert req.requester_name == "Ali Veli"

    summary = json.loads(req.impact_summary_json)
    assert "total_records_affected" in summary


# ============================================================================
# 4. SİLME TALEBİNİ İCRA ETME VE İMHA TUTANAĞI ÜRETİMİ (EXECUTE)
# ============================================================================


def test_execute_erasure_workflow_and_certificate(test_db_session, tmp_path):
    """Silme talebinin icrası: Dosya silinir, PII maskelenir ve SHA-256 sertifikası üretilir."""
    phone = "05334445566"

    # Fiziksel ses dosyası oluştur
    audio_file = tmp_path / "call_rec_to_delete.opus"
    audio_file.write_bytes(b"very_secret_audio_call")
    assert audio_file.exists()

    conv = Conversation(channel="audiosocket", status="active")
    test_db_session.add(conv)
    test_db_session.flush()

    turn = Turn(conversation_id=conv.id, role="user", text="Ben Canan Korkmaz, telefonum 05334445566")
    test_db_session.add(turn)

    audio = AudioArchive(
        conversation_id=conv.id,
        caller_phone=phone,
        file_path=str(audio_file),
    )
    test_db_session.add(audio)

    veh = Vehicle(description="Toyota Corolla", plate="06 ABC 99")
    test_db_session.add(veh)
    test_db_session.flush()
    slot = Slot(starts_at="2026-11-25T14:00:00+03:00")
    test_db_session.add(slot)
    test_db_session.flush()

    appt = Appointment(
        slot_id=slot.id,
        vehicle_id=veh.id,
        customer="Canan Korkmaz",
        customer_phone=phone,
        idempotency_key="test-key-canan",
        confirmed=True,
    )
    test_db_session.add(appt)
    test_db_session.commit()

    # Talep oluştur
    req = create_erasure_request(
        test_db_session,
        KVKKErasureRequestIn(
            identifier_type="phone",
            identifier_value=phone,
            requester_name="Canan Korkmaz",
        ),
    )

    # Talebi İcra Et
    res = execute_erasure(test_db_session, request=req, executed_by="admin_test")
    assert res["status"] == "executed"
    assert len(res["certificate_sha256"]) == 64

    # 1. Fiziksel ses dosyası silinmiş olmalı
    assert not audio_file.exists()
    test_db_session.refresh(audio)
    assert audio.file_path == ""
    assert audio.caller_phone == "[KVKK SİLİNDİ]"
    assert audio.status == "purged"

    # 2. Transkript anonimleştirilmiş olmalı
    test_db_session.refresh(turn)
    assert "[KVKK_SILINDI" in turn.text
    test_db_session.refresh(conv)
    assert conv.status == "purged"

    # 3. Randevu PII maskelenmiş olmalı
    test_db_session.refresh(appt)
    assert appt.customer == "[KVKK SİLİNDİ]"
    assert appt.customer_phone == "[KVKK SİLİNDİ]"

    # 4. Kriptografik sertifika metnini doğrula
    cert_text = generate_certificate_text(req)
    assert "KİŞİSEL VERİ İMHA VE ANONİMLEŞTİRME TUTANAĞI" in cert_text
    assert req.certificate_sha256 in cert_text
    assert "05334445566" in cert_text


def test_execute_erasure_idempotency_raises(test_db_session):
    """Zaten icra edilmiş bir talebin ikinci kez icrası reddedilir."""
    req = create_erasure_request(
        test_db_session,
        KVKKErasureRequestIn(identifier_type="plate", identifier_value="34 XYZ 12"),
    )
    execute_erasure(test_db_session, request=req, executed_by="admin")

    with pytest.raises(ValueError, match="zaten icra edilmiştir"):
        execute_erasure(test_db_session, request=req, executed_by="admin")


# ============================================================================
# 5. REST API UÇ NOKTALARI ENTEGRASYONU
# ============================================================================


def test_api_transcript_retention_endpoints(client, test_db_session):
    """Retention audit ve purge API uç noktalarının testi."""
    # Audit çağrısı
    r_audit = client.get("/api/kvkk/transcript-retention-audit")
    assert r_audit.status_code == 200
    data = r_audit.json()
    assert "retention_policy_days" in data
    assert "total_conversations" in data

    # Purge dry-run çağrısı
    r_purge = client.post(
        "/api/kvkk/transcript-retention-purge",
        json={"dry_run": True, "retention_days": 30},
    )
    assert r_purge.status_code == 200
    p_data = r_purge.json()
    assert p_data["dry_run"] is True

    # Gelecek tarihli purge reddedilmeli (400)
    future_date = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    r_bad = client.post(
        "/api/kvkk/transcript-retention-purge",
        json={"dry_run": True, "target_date": future_date},
    )
    assert r_bad.status_code == 400


def test_api_erasure_request_full_lifecycle(client, test_db_session):
    """Silme talebinin API üzerinden oluşturulması, icrası ve tutanak görüntülenmesi."""
    phone = "05398887766"

    # 1. Talep Oluştur
    r_create = client.post(
        "/api/kvkk/erasure-requests",
        json={
            "identifier_type": "phone",
            "identifier_value": phone,
            "requester_name": "Deneme Müşteri",
            "reason": "KVKK Madde 11",
        },
    )
    assert r_create.status_code == 200
    created = r_create.json()
    req_id = created["id"]
    assert created["status"] == "pending"

    # 2. Listele
    r_list = client.get("/api/kvkk/erasure-requests")
    assert r_list.status_code == 200
    items = r_list.json()
    assert any(it["id"] == req_id for it in items)

    # 3. Detay Al
    r_get = client.get(f"/api/kvkk/erasure-requests/{req_id}")
    assert r_get.status_code == 200
    assert r_get.json()["identifier_value"] == phone

    # 4. Henüz icra edilmeden sertifika alınamaz (400)
    r_cert_early = client.get(f"/api/kvkk/erasure-requests/{req_id}/certificate")
    assert r_cert_early.status_code == 400

    # 5. Talebi İcra Et
    r_exec = client.post(f"/api/kvkk/erasure-requests/{req_id}/execute")
    assert r_exec.status_code == 200
    exec_data = r_exec.json()
    assert exec_data["status"] == "executed"
    assert "certificate_sha256" in exec_data

    # 6. Tekrar icra etmeye çalışma 409 dönmeli
    r_exec_dup = client.post(f"/api/kvkk/erasure-requests/{req_id}/execute")
    assert r_exec_dup.status_code == 409

    # 7. Resmi İmha Tutanağını JSON formatında al
    r_cert_json = client.get(f"/api/kvkk/erasure-requests/{req_id}/certificate?format=json")
    assert r_cert_json.status_code == 200
    cert_json = r_cert_json.json()
    assert cert_json["certificate_sha256"] == exec_data["certificate_sha256"]

    # 8. Resmi İmha Tutanağını Metin formatında al
    r_cert_text = client.get(f"/api/kvkk/erasure-requests/{req_id}/certificate?format=text")
    assert r_cert_text.status_code == 200
    assert "KİŞİSEL VERİ İMHA VE ANONİMLEŞTİRME TUTANAĞI" in r_cert_text.text
    assert "text/plain" in r_cert_text.headers["content-type"]
