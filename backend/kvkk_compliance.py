# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""KVKK Transkript Saklama Süresi ve Silme Talebi (Unutulma Hakkı) Yönetim Motoru.

Bu modül:
1. Transkriptlerin belirlenen saklama süresi (settings.transcript_retention_days)
   sonunda otomatik/manuel denetim ve periyodik imhasını yürütür.
2. KVKK Madde 11 (Unutulma Hakkı) kapsamındaki silme taleplerini kaydeder,
   etki analizini hesaplar, ilgili tüm tablolardaki kişisel verileri (transkript,
   ses arşivi, randevu, WhatsApp, arama analitiği, ruhsat vb.) anonimleştirir/imha eder.
3. Uygulanan işlemin SHA-256 özetini ve işlem kaydını üretir.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import func, inspect
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import (
    Appointment,
    AudioArchive,
    CallAnalytics,
    Conversation,
    KVKKErasureRequest,
    NotificationOutbox,
    OutboundCall,
    RuhsatScan,
    SupervisorTrace,
    Turn,
    Vehicle,
    WhatsAppMessage,
    now,
)
from backend.schemas import KVKKErasureRequestIn


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _clean_phone(raw: str) -> str:
    """Telefon numarasını karşılaştırma için rakamlarına normalize eder."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("90") and len(digits) == 12:
        return "0" + digits[2:]
    return "0" + digits if len(digits) == 10 else digits


def _clean_plate(raw: str) -> str:
    """Plakayı boşluksuz büyük harfe normalize eder."""
    return "".join(raw.upper().split())


def audit_transcript_retention(
    db: Session,
    retention_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Transkript saklama süresi uyumluluğunu denetler."""
    days = retention_days if retention_days is not None else settings.transcript_retention_days
    cutoff_dt = _now_utc() - timedelta(days=days)
    cutoff_iso = cutoff_dt.isoformat()

    total_conversations = db.query(Conversation).count()
    purged_conversations = (
        db.query(Conversation).filter(Conversation.status == "purged").count()
    )
    active_conversations = total_conversations - purged_conversations

    expired_query = db.query(Conversation).filter(
        Conversation.status != "purged",
        Conversation.created_at < cutoff_iso,
    )
    expired_conversations_count = expired_query.count()

    expired_conv_ids = [c.id for c in expired_query.all()]
    expired_turns_count = 0
    if expired_conv_ids:
        expired_turns_count = (
            db.query(Turn).filter(Turn.conversation_id.in_(expired_conv_ids)).count()
        )

    oldest_conv = (
        db.query(Conversation).order_by(Conversation.created_at.asc()).first()
    )
    oldest_date = oldest_conv.created_at if oldest_conv else None

    return {
        "retention_policy_days": days,
        "cutoff_date": cutoff_iso,
        "total_conversations": total_conversations,
        "active_conversations": active_conversations,
        "already_purged_conversations": purged_conversations,
        "expired_conversations_count": expired_conversations_count,
        "expired_turns_count": expired_turns_count,
        "oldest_transcript_date": oldest_date,
        "compliance_status": "compliant"
        if expired_conversations_count == 0
        else "action_required",
    }


def purge_expired_transcripts(
    db: Session,
    dry_run: bool = False,
    retention_days: Optional[int] = None,
    target_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Saklama süresi dolmuş konuşma transkriptlerini anonimleştirir/imha eder."""
    days = retention_days if retention_days is not None else settings.transcript_retention_days
    if target_date is not None:
        if target_date.tzinfo is None:
            target_date = target_date.replace(tzinfo=timezone.utc)
        cutoff_dt = target_date
    else:
        cutoff_dt = _now_utc() - timedelta(days=days)

    cutoff_iso = cutoff_dt.isoformat()
    now_iso = now()

    expired_conversations = (
        db.query(Conversation)
        .filter(
            Conversation.status != "purged",
            Conversation.created_at < cutoff_iso,
        )
        .all()
    )

    expired_conv_ids = [c.id for c in expired_conversations]
    expired_turns_count = 0
    if expired_conv_ids:
        expired_turns_count = (
            db.query(Turn).filter(Turn.conversation_id.in_(expired_conv_ids)).count()
        )

    if dry_run or not expired_conv_ids:
        return {
            "dry_run": dry_run,
            "purged_conversations": len(expired_conv_ids),
            "purged_turns": expired_turns_count,
            "cutoff_date": cutoff_iso,
            "executed_at": now_iso,
        }

    # Transkript metinlerini imha et / anonimleştir
    db.query(Turn).filter(Turn.conversation_id.in_(expired_conv_ids)).update(
        {
            "text": "[KVKK_SURESI_DOLDU_SILINDI]",
            "metrics": "{}",
        },
        synchronize_session=False,
    )

    # Konuşmaları 'purged' olarak işaretle ve denetim izi ekle
    for conv in expired_conversations:
        conv.status = "purged"
        note = f"[KVKK Saklama Süresi Doldu ({days} gün) - Transkript {now_iso} tarihinde imha edildi]"
        conv.operator_notes = (
            f"{conv.operator_notes}\n{note}".strip()
            if conv.operator_notes
            else note
        )

    db.commit()

    return {
        "dry_run": False,
        "purged_conversations": len(expired_conv_ids),
        "purged_turns": expired_turns_count,
        "cutoff_date": cutoff_iso,
        "executed_at": now_iso,
    }


def scan_erasure_impact(
    db: Session,
    identifier_type: str,
    identifier_value: str,
) -> Dict[str, Any]:
    """Belirtilen kimlik verisine göre imha edilecek kayıtların etki analizini çıkarır."""
    identity = KVKKErasureRequestIn(identifier_type=identifier_type, identifier_value=identifier_value)
    id_type = identity.identifier_type
    val = identity.identifier_value

    matched_conv_ids: set[str] = set()
    matched_appt_ids: set[str] = set()
    matched_audio_ids: set[str] = set()
    matched_wa_ids: set[str] = set()
    matched_ca_ids: set[str] = set()
    matched_rs_ids: set[str] = set()
    matched_ob_ids: set[str] = set()
    matched_notif_ids: set[str] = set()

    phone_clean = _clean_phone(val)
    plate_clean = _clean_plate(val)

    if id_type == "conversation_id":
        conv = db.get(Conversation, val)
        if conv:
            matched_conv_ids.add(conv.id)

    elif id_type == "phone":
        forms = {val, phone_clean}
        if len(phone_clean) == 11 and phone_clean.startswith("0"):
            local = phone_clean[1:]
            forms.update((local, "90" + local, "+90" + local))
        phone_token = re.compile(r"(?<!\d)(?:\+?90|0)?[ .()-]*(?:[0-9][ .()-]*){9}[0-9](?!\d)")
        for conversation_id, text in db.query(Turn.conversation_id, Turn.text).filter(Turn.role == "user"):
            if any(_clean_phone(token.group()) == phone_clean for token in phone_token.finditer(text or "")):
                matched_conv_ids.add(conversation_id)
        # 1. Randevular
        appts = (
            db.query(Appointment)
            .filter(
                Appointment.customer_phone.in_(forms)
            )
            .all()
        )
        for a in appts:
            matched_appt_ids.add(a.id)

        # 2. Ses Arşivleri
        audios = (
            db.query(AudioArchive)
            .filter(
                AudioArchive.caller_phone.in_(forms)
            )
            .all()
        )
        for aud in audios:
            matched_audio_ids.add(aud.id)
            if aud.conversation_id:
                matched_conv_ids.add(aud.conversation_id)

        # 3. WhatsApp Mesajları
        was = (
            db.query(WhatsAppMessage)
            .filter(
                WhatsAppMessage.from_phone.in_(forms)
            )
            .all()
        )
        for w in was:
            matched_wa_ids.add(w.id)
            if w.appointment_id:
                matched_appt_ids.add(w.appointment_id)

        # 4. Çağrı Analitiği
        cas = (
            db.query(CallAnalytics)
            .filter(
                CallAnalytics.caller_phone.in_(forms)
            )
            .all()
        )
        for c in cas:
            matched_ca_ids.add(c.id)
            if c.conversation_id:
                matched_conv_ids.add(c.conversation_id)
            if c.appointment_id:
                matched_appt_ids.add(c.appointment_id)

        # 5. Ruhsat Taramaları
        rss = (
            db.query(RuhsatScan)
            .filter(
                RuhsatScan.from_phone.in_(forms)
            )
            .all()
        )
        for r in rss:
            matched_rs_ids.add(r.id)

        # 6. Giden Aramalar
        obs = (
            db.query(OutboundCall)
            .filter(
                OutboundCall.phone.in_(forms)
            )
            .all()
        )
        for o in obs:
            matched_ob_ids.add(o.id)
            if o.appointment_id:
                matched_appt_ids.add(o.appointment_id)

        # 7. Bildirimler Outbox
        notifs = (
            db.query(NotificationOutbox)
            .filter(
                NotificationOutbox.recipient.in_(forms)
            )
            .all()
        )
        for n in notifs:
            matched_notif_ids.add(n.id)

    elif id_type == "plate":
        # Plaka ile araç ve randevuları bul
        vehs = db.query(Vehicle).filter(func.upper(func.replace(Vehicle.plate, " ", "")) == plate_clean).all()
        veh_ids = [v.id for v in vehs]
        if veh_ids:
            appts = (
                db.query(Appointment)
                .filter(Appointment.vehicle_id.in_(veh_ids))
                .all()
            )
            for a in appts:
                matched_appt_ids.add(a.id)

        # Ruhsat taramaları
        rss = db.query(RuhsatScan).filter(func.upper(func.replace(RuhsatScan.plate, " ", "")) == plate_clean).all()
        for r in rss:
            matched_rs_ids.add(r.id)
            if r.appointment_id:
                matched_appt_ids.add(r.appointment_id)

    elif id_type == "customer_name":
        appts = (
            db.query(Appointment)
            .filter(func.lower(func.trim(Appointment.customer)) == func.lower(val))
            .all()
        )
        for a in appts:
            matched_appt_ids.add(a.id)

        was = (
            db.query(WhatsAppMessage)
            .filter(func.lower(func.trim(WhatsAppMessage.customer_name)) == func.lower(val))
            .all()
        )
        for w in was:
            matched_wa_ids.add(w.id)

        cas = (
            db.query(CallAnalytics)
            .filter(func.lower(func.trim(CallAnalytics.caller_name)) == func.lower(val))
            .all()
        )
        for c in cas:
            matched_ca_ids.add(c.id)
            if c.conversation_id:
                matched_conv_ids.add(c.conversation_id)

        obs = (
            db.query(OutboundCall)
            .filter(func.lower(func.trim(OutboundCall.customer)) == func.lower(val))
            .all()
        )
        for o in obs:
            matched_ob_ids.add(o.id)

    # İlgili randevulardan konuşmaları ve bildirimleri de bağla
    if matched_appt_ids:
        appts_list = list(matched_appt_ids)
        notifs = (
            db.query(NotificationOutbox)
            .filter(NotificationOutbox.appointment_id.in_(appts_list))
            .all()
        )
        for n in notifs:
            matched_notif_ids.add(n.id)

        cas = (
            db.query(CallAnalytics)
            .filter(CallAnalytics.appointment_id.in_(appts_list))
            .all()
        )
        for c in cas:
            matched_ca_ids.add(c.id)
            if c.conversation_id:
                matched_conv_ids.add(c.conversation_id)

    if matched_conv_ids:
        for archive in db.query(AudioArchive).filter(AudioArchive.conversation_id.in_(matched_conv_ids)):
            matched_audio_ids.add(archive.id)

    recording_root = (settings.data_dir / "recordings").resolve()
    recording_ids = sorted(
        conv_id for conv_id in matched_conv_ids
        if Path(conv_id).name == conv_id
        and (recording_root / f"{conv_id}.wav").is_file()
    )

    # Eşleşen konuşmaların tur sayılarını say
    matched_turns_count = 0
    if matched_conv_ids:
        matched_turns_count = (
            db.query(Turn)
            .filter(Turn.conversation_id.in_(list(matched_conv_ids)))
            .count()
        )

    return {
        "identifier_type": id_type,
        "identifier_value": val,
        "conversations_count": len(matched_conv_ids),
        "turns_count": matched_turns_count,
        "recordings_count": len(recording_ids),
        "appointments_count": len(matched_appt_ids),
        "audio_archives_count": len(matched_audio_ids),
        "whatsapp_messages_count": len(matched_wa_ids),
        "call_analytics_count": len(matched_ca_ids),
        "ruhsat_scans_count": len(matched_rs_ids),
        "outbound_calls_count": len(matched_ob_ids),
        "notifications_count": len(matched_notif_ids),
        "total_records_affected": (
            len(matched_conv_ids)
            + matched_turns_count
            + len(recording_ids)
            + len(matched_appt_ids)
            + len(matched_audio_ids)
            + len(matched_wa_ids)
            + len(matched_ca_ids)
            + len(matched_rs_ids)
            + len(matched_ob_ids)
            + len(matched_notif_ids)
        ),
        "matched_conversation_ids": sorted(list(matched_conv_ids)),
        "matched_appointment_ids": sorted(list(matched_appt_ids)),
        "matched_audio_archive_ids": sorted(list(matched_audio_ids)),
        "matched_whatsapp_ids": sorted(matched_wa_ids),
        "matched_call_analytics_ids": sorted(matched_ca_ids),
        "matched_ruhsat_scan_ids": sorted(matched_rs_ids),
        "matched_outbound_call_ids": sorted(matched_ob_ids),
        "matched_notification_ids": sorted(matched_notif_ids),
        "matched_recording_ids": recording_ids,
    }


def create_erasure_request(
    db: Session,
    payload: KVKKErasureRequestIn,
    requester: str = "admin",
) -> KVKKErasureRequest:
    """Yeni bir KVKK silme talebi oluşturur ve ön etki analizini hesaplar."""
    impact = scan_erasure_impact(
        db,
        identifier_type=payload.identifier_type,
        identifier_value=payload.identifier_value,
    )
    req = KVKKErasureRequest(
        identifier_type=payload.identifier_type,
        identifier_value=payload.identifier_value,
        requester_name=payload.requester_name,
        reason=payload.reason,
        status="pending",
        impact_summary_json=json.dumps(impact, ensure_ascii=False),
        notes=payload.notes,
        executed_by=requester,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def execute_erasure(
    db: Session,
    request: KVKKErasureRequest,
    executed_by: str = "admin",
    *,
    confirmed_record_count: int,
) -> Dict[str, Any]:
    """KVKK silme talebini tüm bağlı tablolarda icra eder ve imha tutanağı üretir."""
    if request.status == "executed":
        raise ValueError("Bu talep daha önce zaten icra edilmiştir (idempotency koruması).")

    impact = scan_erasure_impact(
        db,
        identifier_type=request.identifier_type,
        identifier_value=request.identifier_value,
    )

    conv_ids = impact.get("matched_conversation_ids", [])
    appt_ids = impact.get("matched_appointment_ids", [])
    audio_ids = impact.get("matched_audio_archive_ids", [])
    wa_ids = impact.get("matched_whatsapp_ids", [])

    preview = json.loads(request.impact_summary_json or "{}")
    if confirmed_record_count != impact["total_records_affected"] or preview != impact:
        raise ValueError("Etki önizlemesi değişti. Yeni bir silme talebi ile önizlemeyi doğrulayın.")

    if conv_ids and db.query(Conversation.id).filter(
        Conversation.id.in_(conv_ids), Conversation.status == "active",
    ).first():
        raise ValueError("Eşleşen görüşme sürüyor. Görüşme kapandıktan sonra tekrar deneyin.")

    for conv_id in impact["matched_recording_ids"]:
        (settings.data_dir / "recordings" / f"{conv_id}.wav").unlink(missing_ok=True)

    # 1. Konuşmalar ve Turn'ler
    if conv_ids:
        if inspect(db.connection()).has_table(SupervisorTrace.__tablename__):
            db.query(SupervisorTrace).filter(SupervisorTrace.conversation_id.in_(conv_ids)).delete(
                synchronize_session=False,
            )
        db.query(Turn).filter(Turn.conversation_id.in_(conv_ids)).update(
            {
                "text": "[KVKK_SILINDI - UNUTULMA HAKKI TALEBİ İLE İMHA EDİLDİ]",
                "metrics": "{}",
            },
            synchronize_session=False,
        )
        for c in db.query(Conversation).filter(Conversation.id.in_(conv_ids)).all():
            c.status = "purged"
            c.operator_notes = (
                f"[KVKK Silme Talebi İcra Edildi: {request.id}]"
            )

    # 2. Randevular (PII maskeleme)
    if appt_ids:
        for a in db.query(Appointment).filter(Appointment.id.in_(appt_ids)).all():
            a.customer = "[KVKK SİLİNDİ]"
            a.customer_phone = "[KVKK SİLİNDİ]"

    # 3. Ses Arşivleri (Fiziksel dosya silme ve kayıt maskeleme)
    if audio_ids:
        for aud in db.query(AudioArchive).filter(AudioArchive.id.in_(audio_ids)).all():
            if aud.file_path:
                Path(aud.file_path).unlink(missing_ok=True)
            aud.file_path = ""
            aud.caller_phone = "[KVKK SİLİNDİ]"
            aud.status = "purged"

    # 4. WhatsApp Mesajları
    if wa_ids:
        for w in db.query(WhatsAppMessage).filter(WhatsAppMessage.id.in_(wa_ids)).all():
            w.raw_content = "[KVKK SİLİNDİ]"
            w.transcription = "[KVKK SİLİNDİ]"
            w.reply_text = "[KVKK SİLİNDİ]"
            w.customer_name = "[KVKK SİLİNDİ]"
            w.from_phone = "[KVKK SİLİNDİ]"

    # 5. Çağrı Analitiği
    ca_query = db.query(CallAnalytics).filter(CallAnalytics.id.in_(impact["matched_call_analytics_ids"]))
    for ca in ca_query.all():
        ca.caller_name = "[KVKK SİLİNDİ]"
        ca.caller_phone = "[KVKK SİLİNDİ]"
        ca.executive_summary = "[KVKK SİLİNDİ]"

    # 6. Ruhsat Taramaları
    rs_query = db.query(RuhsatScan).filter(RuhsatScan.id.in_(impact["matched_ruhsat_scan_ids"]))
    for rs in rs_query.all():
        rs.owner_name = "[KVKK SİLİNDİ]"
        rs.from_phone = "[KVKK SİLİNDİ]"
        rs.raw_extracted_text = "[KVKK SİLİNDİ]"

    # 7. Giden Aramalar
    ob_query = db.query(OutboundCall).filter(OutboundCall.id.in_(impact["matched_outbound_call_ids"]))
    for ob in ob_query.all():
        ob.customer = "[KVKK SİLİNDİ]"
        ob.phone = "[KVKK SİLİNDİ]"

    # 8. Bildirimler Outbox
    notif_query = db.query(NotificationOutbox).filter(NotificationOutbox.id.in_(impact["matched_notification_ids"]))
    for notif in notif_query.all():
        notif.recipient = "[KVKK SİLİNDİ]"
        notif.message = "[KVKK SİLİNDİ]"

    impact.pop("identifier_value", None)
    request.identifier_value = "[KVKK SİLİNDİ]"
    request.requester_name = ""
    request.notes = ""
    request.reason = "Kişisel veri silme talebi"

    # İşlem özeti
    executed_at_iso = now()
    canonical_payload = (
        f"KVKK_IMHA_TUTANAGI_v1|"
        f"REQUEST_ID={request.id}|"
        f"IDENTIFIER_TYPE={request.identifier_type}|"
        f"EXECUTED_AT={executed_at_iso}|"
        f"EXECUTED_BY={executed_by}|"
        f"IMPACT={json.dumps(impact, sort_keys=True, ensure_ascii=False)}"
    )
    cert_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    hmac_sig = ""
    if settings.audio_archive_master_key:
        hmac_sig = hmac.new(
            settings.audio_archive_master_key.encode("utf-8"),
            canonical_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    request.status = "executed"
    request.executed_at = executed_at_iso
    request.executed_by = executed_by
    request.certificate_sha256 = cert_hash
    request.impact_summary_json = json.dumps(impact, ensure_ascii=False)

    db.commit()
    db.refresh(request)

    return {
        "request_id": request.id,
        "status": "executed",
        "executed_at": executed_at_iso,
        "executed_by": executed_by,
        "certificate_sha256": cert_hash,
        "certificate_hmac": hmac_sig,
        "impact": impact,
    }


def generate_certificate_text(request: KVKKErasureRequest) -> str:
    """Uygulamanın silme ve anonimleştirme işlem kaydını üretir."""
    try:
        impact = json.loads(request.impact_summary_json)
    except Exception:
        impact = {}

    lines = [
        "================================================================================",
        "          T.C. KİŞİSEL VERİLERİN KORUNMASI KANUNU (KVKK) MADDE 7 & 11           ",
        "                  KİŞİSEL VERİ İMHA VE ANONİMLEŞTİRME TUTANAĞI                  ",
        "================================================================================",
        f"TUTANAK NO         : KVKK-DEL-{request.id}",
        f"TALEP TARİHİ       : {request.created_at}",
        f"İMHA TARİHİ        : {request.executed_at or 'BEKLEMEDE'}",
        f"İŞLEMİ YAPAN       : {request.executed_by}",
        f"KİMLİK TİPİ        : {request.identifier_type.upper()}",
        f"TALEP GEREKÇESİ    : {request.reason}",
        f"DURUM              : {request.status.upper()}",
        "--------------------------------------------------------------------------------",
        "İMHA EDİLEN / ANONİMLEŞTİRİLEN VERİ KALEMLERİ VE KAYIT ADETLERİ:",
        f"  - Görüşme Transkriptleri (Turn)   : {impact.get('turns_count', 0)} adet metin",
        f"  - Sesli Görüşme Kayıtları (Audio) : {impact.get('audio_archives_count', 0) + impact.get('recordings_count', 0)} adet",
        f"  - Randevu ve Müşteri Kayıtları    : {impact.get('appointments_count', 0)} adet",
        f"  - WhatsApp Mesaj İçerikleri       : {impact.get('whatsapp_messages_count', 0)} adet",
        f"  - Arama Analitik & Özetleri       : {impact.get('call_analytics_count', 0)} adet",
        f"  - Ruhsat & Belge Taramaları       : {impact.get('ruhsat_scans_count', 0)} adet",
        f"  - Giden Arama Kayıtları           : {impact.get('outbound_calls_count', 0)} adet",
        f"  - SMS / Bildirim Kayıtları        : {impact.get('notifications_count', 0)} adet",
        f"  TOPLAM ETKİLENEN KAYIT            : {impact.get('total_records_affected', 0)} adet",
        "--------------------------------------------------------------------------------",
        "KRİPTOGRAFİK BÜTÜNLÜK VE DOĞRULAMA:",
        f"SHA-256 SERTİFİKA HASH: {request.certificate_sha256 or 'HENÜZ ÜRETİLMEDİ'}",
        "================================================================================",
    ]
    return "\n".join(lines)
