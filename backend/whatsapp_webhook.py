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

from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import (
    Appointment,
    NotificationOutbox,
    OutboundCall,
    Slot,
    Vehicle,
    WhatsAppMessage,
    cancel_appointment,
    now,
)
from backend.notifications import (
    dispatch_pending_notifications,
    format_appointment_datetime,
)

logger = logging.getLogger("whatsapp_webhook")


def normalize_phone(phone_str: str) -> str:
    """Telefon numarasından boşluk, artı ve parantezleri temizler."""
    if not phone_str:
        return ""
    digits = re.sub(r"\D", "", str(phone_str))
    if digits.startswith("90") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits


def extract_intent_and_time(text: str) -> Tuple[str, str]:
    """
    Gelen müşteri mesajından niyet ve saat bilgisi çıkarır.
    Niyetler: 'time_change', 'cancel', 'confirm', 'inquiry', 'unknown'
    """
    if not text:
        return "unknown", ""

    raw = text.strip()
    clean = re.sub(r"[.,!?;:]", " ", raw.lower())

    # 1. Saat Değişikliği Tespiti (Örn: "Saati 16:00 yapalım", "14.30 olsun", "saat 15 yapabilir miyiz")
    time_match = re.search(
        r"(?:saat[iı]?\s*)?([012]?\d)(?:[:.]([0-5]\d))?\s*(?:yapalım|olsun|olarak|alalım|değiştir|uygun\s*mu|mümkün|kaydır|taşı|istiyorum|olsa)",
        raw,
        re.IGNORECASE,
    )
    if not time_match:
        # Genel saat formatı eşleşmesi: "16:00", "15:30", "10.00"
        general_time = re.search(r"\b([012]?\d)[:.]([0-5]\d)\b", raw)
        if general_time:
            time_match = general_time

    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        if 8 <= hour <= 20 and 0 <= minute < 60:
            formatted_time = f"{hour:02d}:{minute:02d}"
            return "time_change", formatted_time

    # 2. İptal Tespiti
    if re.search(
        r"\b(iptal|gelemiyorum|gelemeyeceğim|vazgeçtim|istemiyorum|gelemem|katılamayacağım)\b",
        clean,
    ):
        return "cancel", ""

    # 3. Teyit / Onay Tespiti
    if re.search(
        r"\b(evet|onaylıyorum|onay|geliyorum|oradayım|tamam|uygun|kesinlikle|gelicem|katılacağım)\b",
        clean,
    ):
        return "confirm", ""

    # 4. Bilgi / Konum Talebi
    if re.search(r"\b(konum|nerede|adres|harita|fiyat|ücret|nasıl\s*gelirim)\b", clean):
        return "inquiry", ""

    return "unknown", ""


def find_target_appointment(
    db: Session,
    *,
    from_phone: str = "",
    customer_name: str = "",
    ref_code: str = "",
) -> Optional[Appointment]:
    """
    Telefon numarası, müşteri adı veya referans kodu ile en güncel aktif randevuyu bulur.
    """
    clean_phone = normalize_phone(from_phone)

    # 1. Referans Koduna Göre
    if ref_code:
        for app in db.scalars(
            select(Appointment).order_by(Appointment.created_at.desc())
        ).all():
            if app.id.upper().startswith(ref_code.upper()):
                return app

    # 2. Telefon Numarasına Göre
    if clean_phone:
        all_apps = db.scalars(
            select(Appointment)
            .where(Appointment.status.in_(["confirmed", "pending"]))
            .order_by(Appointment.created_at.desc())
        ).all()
        for app in all_apps:
            # Doğrudan customer_phone sütunu eşleşmesi
            app_phone = normalize_phone(getattr(app, "customer_phone", ""))
            if app_phone and (clean_phone.endswith(app_phone[-10:]) or app_phone.endswith(clean_phone[-10:])):
                return app
            # Customer stringi içinde telefon numarası geçiyorsa
            digits = normalize_phone(app.customer)
            if digits and (clean_phone in digits or digits in clean_phone):
                return app
            # Outbound call kaydında bu telefon eşleşiyor mu
            call = db.scalars(
                select(OutboundCall).where(OutboundCall.appointment_id == app.id)
            ).first()
            if call and clean_phone in normalize_phone(call.phone):
                return app
            # Bildirim kaydında bu telefon eşleşiyor mu
            notif = db.scalars(
                select(NotificationOutbox).where(NotificationOutbox.appointment_id == app.id)
            ).first()
            if notif and clean_phone in normalize_phone(notif.recipient):
                return app

    # 3. Müşteri İsmine Göre
    if customer_name:
        name_clean = customer_name.strip().casefold()
        for app in db.scalars(
            select(Appointment)
            .where(Appointment.status.in_(["confirmed", "pending"]))
            .order_by(Appointment.created_at.desc())
        ).all():
            if name_clean in app.customer.casefold() or app.customer.casefold() in name_clean:
                return app

    # 4. Fallback: En son oluşturulmuş aktif randevu
    latest = db.scalars(
        select(Appointment)
        .where(Appointment.status.in_(["confirmed", "pending"]))
        .order_by(Appointment.created_at.desc())
    ).first()
    return latest


def cancel_pending_outbound_calls(db: Session, appointment_id: str) -> int:
    """
    Müşteri WhatsApp üzerinden yanıt verdiği için randevuya bağlı bekleyen veya süren
    tüm giden aramaları (Auto-Retry) derhal iptal eder.
    """
    if not appointment_id:
        return 0

    calls = (
        db.scalars(
            select(OutboundCall)
            .where(OutboundCall.appointment_id == appointment_id)
            .where(OutboundCall.status.in_(["queued", "originating", "in-progress"]))
        )
        .all()
    )

    cancelled_count = 0
    now_str = now()
    for call in calls:
        call.status = "cancelled"
        call.outcome = "cancelled"
        call.completed_at = now_str
        call.last_error = "Müşteri WhatsApp üzerinden yanıt verdi; arama tekrarı iptal edildi."
        cancelled_count += 1

    if cancelled_count > 0:
        logger.info(
            "Randevu (%s) için %d bekleyen giden arama otomatik iptal edildi.",
            appointment_id,
            cancelled_count,
        )
        db.commit()

    return cancelled_count


def update_appointment_time(
    db: Session,
    appointment: Appointment,
    target_time_hhmm: str,
) -> Tuple[bool, str]:
    """
    Randevu saatini müşterinin WhatsApp talebine göre günceller.
    Gerektiğinde hedef saat için yeni Slot oluşturur veya mevcut müsait slota bağlar.
    """
    hour_str, min_str = target_time_hhmm.split(":")
    target_hour, target_min = int(hour_str), int(min_str)

    current_slot = db.get(Slot, appointment.slot_id) if appointment.slot_id else None
    if current_slot:
        try:
            curr_dt = datetime.fromisoformat(current_slot.starts_at)
            new_dt = curr_dt.replace(
                hour=target_hour, minute=target_min, second=0, microsecond=0
            )
        except Exception:
            new_dt = datetime.now(timezone.utc).replace(
                hour=target_hour, minute=target_min, second=0, microsecond=0
            )
    else:
        new_dt = datetime.now(timezone.utc).replace(
            hour=target_hour, minute=target_min, second=0, microsecond=0
        )

    new_iso = new_dt.isoformat()

    # Aynı zamanda mevcut boş slot ara
    target_slot = db.scalars(
        select(Slot).where(Slot.starts_at == new_iso)
    ).first()

    if not target_slot:
        # Yeni slot aç
        target_slot = Slot(
            id=f"slot-{uuid4().hex[:8]}",
            starts_at=new_iso,
            duration_minutes=getattr(current_slot, "duration_minutes", 30) or 30,
        )
        db.add(target_slot)
        db.flush()

    appointment.slot_id = target_slot.id
    appointment.status = "confirmed"
    db.commit()

    formatted_time = format_appointment_datetime(new_iso)
    return True, formatted_time


def process_inbound_text(
    db: Session,
    *,
    from_phone: str,
    text: str,
    customer_name: str = "",
    message_sid: str = "",
) -> Dict[str, Any]:
    """
    Müşteriden gelen yazılı WhatsApp mesajını işler:
    1. Niyet ve saat çıkarır.
    2. Randevuyu bulup günceller veya iptal eder.
    3. Giden arama tekrarlarını otomatik iptal eder.
    4. Yanıt metnine şube konum pini ve harita bağlantısını ekler.
    5. Kaydı veritabanına yazar.
    """
    intent, extracted_time = extract_intent_and_time(text)
    appointment = find_target_appointment(
        db, from_phone=from_phone, customer_name=customer_name
    )

    cancelled_calls_count = 0
    reply_msg = ""
    app_id = appointment.id if appointment else None

    if appointment:
        cancelled_calls_count = cancel_pending_outbound_calls(db, appointment.id)
        cust_label = appointment.customer or customer_name or "Müşterimiz"

        if intent == "time_change" and extracted_time:
            success, formatted = update_appointment_time(db, appointment, extracted_time)
            reply_msg = (
                f"Sayın {cust_label}, randevu saatiniz {formatted} olarak güncellenmiştir. "
                f"Randevu No: {appointment.id[:8].upper()}. "
                f"Adres: {settings.branch_address}. "
                f"📍 İstasyon Konumu: {settings.branch_maps_url} . "
                f"Görüşmek üzere iyi günler dileriz."
            )
        elif intent == "cancel":
            cancel_appointment(db, appointment)
            reply_msg = (
                f"Sayın {cust_label}, ekspertiz randevunuz talebiniz üzerine iptal edilmiştir. "
                f"Dilediğiniz zaman tekrar randevu oluşturabilirsiniz. İyi günler dileriz."
            )
        elif intent == "confirm":
            appointment.status = "confirmed"
            db.commit()
            reply_msg = (
                f"Sayın {cust_label}, randevu katılım teyidiniz alınmıştır. "
                f"Adres: {settings.branch_address}. "
                f"📍 İstasyon Konumu: {settings.branch_maps_url} . "
                f"Zamanında görüşmek üzere iyi günler dileriz."
            )
        elif intent == "inquiry":
            reply_msg = (
                f"Sayın {cust_label}, merkezimiz Maslak Atatürk Oto Sanayi'dedir. "
                f"Adres: {settings.branch_address}. "
                f"📍 Canlı Yol Tarifi: {settings.branch_maps_url} . "
                f"Herhangi bir sorunuz için bize bu numaradan ulaşabilirsiniz."
            )
        else:
            reply_msg = (
                f"Mesajınız alındı Sayın {cust_label}. "
                f"Randevu saat değişikliği için örneğin 'Saati 16:00 yapalım', iptal için 'İptal etmek istiyorum' yazabilirsiniz. "
                f"📍 İstasyon Konumu: {settings.branch_maps_url}"
            )
    else:
        # Randevu bulunamadı
        if intent == "time_change" or intent == "confirm":
            reply_msg = (
                "Aktif bir randevu kaydınız bulunamadı. Yeni bir randevu oluşturmak için "
                "merkezimizi arayabilir veya plaka ve isim bilginizi iletebilirsiniz. "
                f"📍 İstasyon Konumu: {settings.branch_maps_url}"
            )
        else:
            reply_msg = (
                "Maslak Ekspertiz Merkezine hoş geldiniz. Randevu oluşturmak, iptal veya saat değişikliği "
                f"için bize yazabilirsiniz. 📍 Adres ve Konum: {settings.branch_maps_url}"
            )

    # WhatsApp mesaj kaydı oluştur
    msg_record = WhatsAppMessage(
        id=f"wmsg-{uuid4().hex[:12]}",
        message_sid=message_sid or f"sid-{uuid4().hex[:8]}",
        from_phone=from_phone,
        customer_name=customer_name or (appointment.customer if appointment else ""),
        message_type="text",
        raw_content=text,
        transcription="",
        extracted_intent=intent,
        extracted_time=extracted_time,
        appointment_id=app_id,
        reply_text=reply_msg,
        outbound_calls_cancelled=cancelled_calls_count,
        processed=True,
        created_at=now(),
    )
    db.add(msg_record)

    # Yanıtı ayrıca Outbox tablosuna da kaydet (asenkron iletim için)
    if app_id:
        outbox_notif = NotificationOutbox(
            appointment_id=app_id,
            recipient_type="customer",
            recipient=from_phone,
            channel="whatsapp",
            message=reply_msg,
            status="pending",
            idempotency_key=f"reply-{msg_record.id}",
        )
        db.add(outbox_notif)

    db.commit()
    db.refresh(msg_record)

    # Outbox gönderimini arka planda tetikle
    try:
        dispatch_pending_notifications(db, limit=2)
    except Exception:
        pass

    return {
        "status": "success",
        "message_id": msg_record.id,
        "intent": intent,
        "extracted_time": extracted_time,
        "appointment_id": app_id,
        "reply": reply_msg,
        "outbound_calls_cancelled": cancelled_calls_count,
    }


async def process_inbound_voice(
    db: Session,
    *,
    from_phone: str,
    audio_data: Any,
    customer_name: str = "",
    message_sid: str = "",
) -> Dict[str, Any]:
    """
    Müşteriden gelen WhatsApp sesli notunu (Voice Note) Faster-Whisper STT ile deşifre eder
    ve randevu güncelleme / teyit akışını çalıştırır.
    """
    from backend.models import models

    transcribed_text = ""
    try:
        if models.stt:
            transcribed_text = await models.transcribe(audio_data)
        else:
            logger.warning("STT motoru hazır değil, sesli not transkripsiyonu yapılamadı")
    except Exception as e:
        logger.error("Sesli not deşifre hatası: %s", e)

    # Transkripsiyon sonrası metin işleme akışına yönlendir
    result = process_inbound_text(
        db,
        from_phone=from_phone,
        text=transcribed_text,
        customer_name=customer_name,
        message_sid=message_sid,
    )

    # Mesaj kaydını güncelle: type='audio', transcription ekle
    msg_id = result.get("message_id")
    if msg_id:
        msg = db.get(WhatsAppMessage, msg_id)
        if msg:
            msg.message_type = "audio"
            msg.transcription = transcribed_text
            msg.raw_content = "[WhatsApp Sesli Mesaj]"
            db.commit()

    result["transcription"] = transcribed_text
    result["message_type"] = "audio"
    return result


def process_inbound_image(
    db: Session,
    *,
    from_phone: str,
    image_bytes: bytes,
    customer_name: str = "",
    message_sid: str = "",
    filename: str = "",
) -> Dict[str, Any]:
    """
    Müşteriden gelen araç ruhsat fotoğrafını OCR ile okur,
    plaka, şasi no (VIN) ve araç bilgilerini randevuya ve CRM'e kaydeder.
    """
    from backend.vin_ruhsat_decoder import process_inbound_ruhsat_image

    scan_record, parsed = process_inbound_ruhsat_image(
        db,
        from_phone=from_phone,
        image_bytes=image_bytes,
        filename=filename,
    )

    plate_str = parsed.get("plate") or "Belirtilmedi"
    vin_str = parsed.get("vin") or "Belirtilmedi"
    vehicle_info = parsed.get("brand_model") or ""
    year_str = str(parsed.get("model_year")) if parsed.get("model_year") else ""
    full_model = f"{year_str} {vehicle_info}".strip()

    if parsed.get("confidence", 0) >= 0.3:
        reply_msg = (
            f"Sayın müşterimiz, araç ruhsatınız başarıyla doğrulandı. 📋\n"
            f"Plaka: {plate_str}\n"
            f"Şasi (VIN): {vin_str}\n"
        )
        if full_model:
            reply_msg += f"Araç: {full_model}\n"
        reply_msg += "Bilgiler ekspertiz kaydınıza işlendi. Teşekkür ederiz!"
    else:
        reply_msg = (
            "Gönderdiğiniz görsel alındı ancak ruhsat bilgileri net okunamadı. "
            "Lütfen görselin net ve aydınlık olduğundan emin olup tekrar iletiniz."
        )

    # WhatsApp mesaj kaydını oluştur
    msg_record = WhatsAppMessage(
        id=f"wmsg-{uuid4().hex[:12]}",
        message_sid=message_sid or f"sid-{uuid4().hex[:8]}",
        from_phone=from_phone,
        customer_name=customer_name or scan_record.owner_name or "",
        message_type="image",
        raw_content=f"[WhatsApp Ruhsat Görseli: {filename or 'ruhsat.jpg'}]",
        transcription=f"Plaka: {plate_str}, VIN: {vin_str}, Model: {full_model}",
        extracted_intent="ruhsat_scan",
        extracted_time="",
        appointment_id=scan_record.appointment_id,
        reply_text=reply_msg,
        outbound_calls_cancelled=0,
        processed=True,
        created_at=now(),
    )
    db.add(msg_record)

    if scan_record.appointment_id:
        outbox_notif = NotificationOutbox(
            appointment_id=scan_record.appointment_id,
            recipient_type="customer",
            recipient=from_phone,
            channel="whatsapp",
            message=reply_msg,
            status="pending",
            idempotency_key=f"reply-ruhsat-{msg_record.id}",
        )
        db.add(outbox_notif)

    db.commit()
    db.refresh(msg_record)

    try:
        dispatch_pending_notifications(db, limit=2)
    except Exception:
        pass

    return {
        "status": "success",
        "message_id": msg_record.id,
        "scan_id": scan_record.id,
        "plate": parsed.get("plate"),
        "vin": parsed.get("vin"),
        "brand_model": parsed.get("brand_model"),
        "model_year": parsed.get("model_year"),
        "confidence": parsed.get("confidence"),
        "reply": reply_msg,
    }


def list_whatsapp_messages(
    db: Session,
    *,
    limit: int = 50,
) -> list[WhatsAppMessage]:
    """Gelen ve işlenen WhatsApp mesajlarını listeler."""
    return list(
        db.scalars(
            select(WhatsAppMessage)
            .order_by(WhatsAppMessage.created_at.desc())
            .limit(limit)
        ).all()
    )
