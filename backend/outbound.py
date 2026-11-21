"""
Giden Cagri (Outbound Call) Servisi.

Asterisk AMI uzerinden randevu teyit ve hatirlatma aramalari baslatir,
sonuclari (teyit, iptal, ulasilamadi) OutboundCall tablosunda ve randevu
kaydinda atomik olarak gunceller.
"""

from __future__ import annotations
import logging
from sqlalchemy import select
from backend.config import settings
from backend.db import OutboundCall, Appointment, cancel_appointment, now
from backend.ami import get_ami_client, is_real_ami

logger = logging.getLogger("automotive_voice.outbound")


async def initiate_outbound_call(
    db,
    *,
    appointment_id: str,
    phone: str | None = None,
    call_type: str = "reminder",
) -> OutboundCall:
    """
    Belirtilen randevu icin Asterisk AMI uzerinden giden arama baslatir.
    Arama kaydini olusturur ve durumu 'in-progress' olarak gunceller.
    """
    app = db.get(Appointment, appointment_id)
    if not app:
        raise ValueError("Randevu bulunamadı")
    if app.status == "cancelled":
        raise ValueError("İptal edilmiş randevu için teyit araması başlatılamaz")

    # Hedef telefon numarasi
    target_phone = (phone or "").strip()
    if not target_phone:
        target_phone = app.customer.strip()
    if not target_phone:
        raise ValueError("Arama için geçerli bir telefon numarası gerekli")

    # Ayni randevu icin aktif arama kontrolu
    existing_active = (
        db.scalars(
            select(OutboundCall)
            .where(OutboundCall.appointment_id == appointment_id)
            .where(OutboundCall.status.in_(("originating", "in-progress")))
        )
        .first()
    )
    if existing_active:
        raise ValueError("Bu randevu için halihazırda devam eden bir arama mevcut")

    # Asterisk Kanal formatı (örn: PJSIP/05321234567@trunk veya Local/9092@from-internal)
    clean_digits = "".join(c for c in target_phone if c.isdigit())
    dial_str = clean_digits if len(clean_digits) >= 7 else target_phone
    channel = f"{settings.ami_channel_prefix}/{dial_str}@{settings.ami_trunk}"

    call_record = OutboundCall(
        appointment_id=appointment_id,
        phone=target_phone,
        customer=app.customer,
        call_type=call_type,
        status="originating",
        outcome="pending",
    )
    db.add(call_record)
    db.flush()

    ami = get_ami_client()
    variables = {
        "APPOINTMENT_ID": str(app.id),
        "CALL_ID": str(call_record.id),
        "OUTBOUND_UUID": str(call_record.id),
        "CALL_TYPE": call_type,
        "CUSTOMER": app.customer,
    }

    try:
        call_record.attempts += 1
        res = await ami.originate(
            channel=channel,
            context=settings.ami_context,
            exten=settings.ami_exten,
            callerid=settings.ami_callerid,
            variables=variables,
            timeout_ms=30000,
        )
        call_record.action_id = res.get("action_id", "")
        # Mock AMI gerçek arama başlatmaz; "in-progress" denirse operatör yanılır.
        call_record.status = "in-progress" if is_real_ami() else "simulated"
        call_record.last_error = None
    except Exception as e:
        logger.error("AMI Originate basarisiz: %s", e)
        call_record.status = "failed"
        call_record.last_error = str(e)
        db.commit()
        raise RuntimeError(f"Giden arama başlatılamadı: {e}")

    db.commit()
    return call_record


def get_outbound_session_context(db, call_uuid: str) -> dict | None:
    """AudioSocket UUID'si bir OutboundCall.id ile eşleşiyorsa oturum bağlamını döner.

    Eşleşme için Asterisk giden diyaloğu AudioSocket'i `${OUTBOUND_UUID}` ile açmalıdır
    (backend `OUTBOUND_UUID` değişkenini AMI/call-file ile zaten gönderir). Gelen çağrıların
    rastgele UUID'si hiçbir kayda uymaz ve None döner.
    """
    call = db.get(OutboundCall, str(call_uuid))
    if not call:
        return None
    mode = "outbound_diagnostic" if call.call_type == "diagnostic_alert" else "outbound_reminder"
    return {"mode": mode, "appointment_id": call.appointment_id, "call_id": call.id}


def complete_outbound_call(
    db,
    *,
    call_id: str,
    outcome: str,
    notes: str = "",
) -> OutboundCall:
    """
    Arama sonucunu ('confirmed', 'cancelled', 'unreachable') kaydeder.
    Musteri iptal ettiyse randevuyu otomatik iptal eder ve saati bosa cikarir.
    """
    valid_outcomes = ("confirmed", "cancelled", "unreachable")
    if outcome not in valid_outcomes:
        raise ValueError(f"Geçersiz arama sonucu. Beklenen: {valid_outcomes}")

    call = db.get(OutboundCall, call_id)
    if not call:
        raise ValueError("Arama kaydı bulunamadı")

    call.outcome = outcome
    call.status = "completed"
    call.completed_at = now()

    app = db.get(Appointment, call.appointment_id)
    if app:
        if outcome == "cancelled":
            # Kurumsal ücret varsa iade de burada (tek paylaşımlı işlev) yapılır.
            cancel_appointment(db, app, commit=False)
            logger.info("Randevu (%s) giden arama teyidinde iptal edildi.", app.id)
        elif outcome == "confirmed":
            app.status = "confirmed"
            logger.info("Randevu (%s) giden arama teyidinde onaylandi.", app.id)

    db.commit()
    return call


def cancel_outbound_call(db, call_id: str) -> OutboundCall:
    """Bekleyen veya baslatilmakta olan aramayi iptal eder."""
    call = db.get(OutboundCall, call_id)
    if not call:
        raise ValueError("Arama kaydı bulunamadı")
    if call.status in ("completed", "cancelled"):
        return call
    call.status = "cancelled"
    call.outcome = "cancelled"
    call.completed_at = now()
    db.commit()
    return call


def get_outbound_stats(db) -> dict:
    """Giden arama istatistiklerini doner."""
    calls = db.scalars(select(OutboundCall)).all()
    return {
        "total": len(calls),
        "in_progress": len([c for c in calls if c.status == "in-progress"]),
        "simulated": len([c for c in calls if c.status == "simulated"]),
        "confirmed": len([c for c in calls if c.outcome == "confirmed"]),
        "cancelled": len([c for c in calls if c.outcome == "cancelled"]),
        "unreachable": len([c for c in calls if c.outcome == "unreachable"]),
        "failed": len([c for c in calls if c.status == "failed"]),
    }

