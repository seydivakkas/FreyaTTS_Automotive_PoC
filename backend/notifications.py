"""
M10 Outbox Randevu Bildirim Servisi (SMS / WhatsApp).

Randevu olusturuldugunda transactional outbox tablosuna (notifications) musteri
ve kurumsal cari hesap (galeri) icin iletilecek onay bildirimlerini yazar.
Asenkron veya tetiklenen dispatcher ile at-least-once prensibiyle gonderir.
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Protocol, Optional, List
from sqlalchemy import select
from backend.config import settings
from backend.db import (
    NotificationOutbox,
    Appointment,
    Slot,
    Vehicle,
    CorporateAccount,
    now,
    uid,
)

logger = logging.getLogger("automotive_voice.notifications")


def format_appointment_datetime(iso_str: str) -> str:
    """ISO formatli tarihi Turkce '05.11.2026 14:30' formatina cevirir."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso_str


class NotificationProvider(Protocol):
    def send(self, channel: str, recipient: str, message: str) -> dict:
        """Kanal uzerinden mesaji iletir. Basarili ise receipt doner, hata durumunda istisna firlatir."""
        ...


class MockNotificationProvider:
    """Testler ve yerel calisma icin bellek ici bildirim saglayici."""

    def __init__(self):
        self.sent_messages: list[dict] = []
        self.fail_next: bool = False
        self.fail_reason: str = "SMS Gateway Timeout"

    def send(self, channel: str, recipient: str, message: str) -> dict:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError(self.fail_reason)
        receipt = {
            "provider": "mock",
            "channel": channel,
            "recipient": recipient,
            "message": message,
            "external_id": f"mock-msg-{uid()[:8]}",
            "delivered_at": now(),
        }
        self.sent_messages.append(receipt)
        return receipt

    def clear(self):
        self.sent_messages.clear()
        self.fail_next = False


_active_provider: NotificationProvider = MockNotificationProvider()


def get_notification_provider() -> NotificationProvider:
    global _active_provider
    return _active_provider


def set_notification_provider(provider: NotificationProvider) -> None:
    global _active_provider
    _active_provider = provider


def queue_appointment_notifications(
    db,
    *,
    appointment: Appointment,
    slot: Slot,
    vehicle: Vehicle,
    account: Optional[CorporateAccount] = None,
    customer_phone: str = "",
) -> list[NotificationOutbox]:
    """
    Randevu olusturuldugunda outbox tablosuna transactional olarak bildirimleri ekler.
    db.commit() oncesinde ayni transaction icinde isletilir.
    """
    notifications: list[NotificationOutbox] = []
    formatted_time = format_appointment_datetime(slot.starts_at)
    vehicle_name = vehicle.description
    plate_info = f" ({vehicle.plate})" if vehicle.plate else ""
    ref_code = appointment.id[:8].upper()

    # 1. Musteri SMS Onay Metni (Adres ve Google Maps Konum Pini Dahil)
    cust_target = customer_phone.strip() or appointment.customer
    cust_msg = (
        f"Sayın {appointment.customer}, {vehicle_name}{plate_info} aracınız için "
        f"{formatted_time} tarihindeki ekspertiz randevunuz onaylanmıştır. "
        f"Randevu Referans No: {ref_code}. "
        f"Adres: {settings.branch_address}. "
        f"📍 Konum / Harita: {settings.branch_maps_url} . "
        f"İptal ve saat değişikliği için bu mesaja yanıt verebilirsiniz."
    )
    cust_notif = NotificationOutbox(
        appointment_id=appointment.id,
        recipient_type="customer",
        recipient=cust_target,
        channel="sms",
        message=cust_msg,
        status="pending",
        idempotency_key=f"notif-cust-{appointment.id}",
    )
    db.add(cust_notif)
    notifications.append(cust_notif)

    # 2. Kurumsal Cari Hesap (Galeri) WhatsApp / SMS Bildirimi
    if account:
        corp_target = account.phone.strip() or account.name
        billed_tl = appointment.billed_amount_kurus // 100
        balance_tl = account.balance_kurus // 100
        corp_msg = (
            f"Sayın {account.name}, {appointment.customer} adına {vehicle_name}{plate_info} "
            f"aracı için {formatted_time} tarihli ekspertiz randevusu oluşturuldu. "
            f"Cari hesap indirimli tutar: {billed_tl} TL. Güncel cari bakiye: {balance_tl} TL. "
            f"Takip No: {ref_code}. "
            f"📍 İstasyon Konumu: {settings.branch_maps_url}"
        )
        corp_notif = NotificationOutbox(
            appointment_id=appointment.id,
            recipient_type="corporate",
            recipient=corp_target,
            channel="whatsapp",
            message=corp_msg,
            status="pending",
            idempotency_key=f"notif-corp-{appointment.id}",
        )
        db.add(corp_notif)
        notifications.append(corp_notif)

    return notifications


def queue_inspection_delivery_notifications(
    db,
    *,
    report,
    vehicle,
    appointment=None,
    custom_url: str | None = None,
) -> list[NotificationOutbox]:
    """Ekspertiz raporu tamamlandığında müşteriye ve varsa kurumsal galeriye
    dijital rapor bağlantısını transactional outbox tablosuna yazar.
    """
    import re

    if not appointment and getattr(report, "appointment_id", None):
        appointment = db.get(Appointment, report.appointment_id)
    if not appointment:
        appointment = db.scalars(
            select(Appointment)
            .where(Appointment.vehicle_id == vehicle.id)
            .order_by(Appointment.created_at.desc())
        ).first()

    report_url = custom_url or f"/api/inspections/{report.id}/pdf"
    score = getattr(report, "score", 100)
    plate = getattr(vehicle, "plate", "") or "Aracınız"
    veh_desc = getattr(vehicle, "description", "") or f"{getattr(vehicle, 'brand', '')} {getattr(vehicle, 'model', '')}"

    notifications: list[NotificationOutbox] = []
    app_id = appointment.id if appointment else None
    if not app_id:
        logger.warning(
            "Rapor bildirimi için randevu kaydı bulunamadı: report_id=%s", report.id
        )
        return notifications

    # 1. Müşteri SMS
    cust_phone = "05550001122"
    cust_name = "Müşterimiz"
    if appointment:
        cust_name = appointment.customer or "Müşterimiz"
        digits = re.findall(r"\d+", appointment.customer or "")
        if digits and len("".join(digits)) >= 10:
            cust_phone = "".join(digits)

    cust_msg = (
        f"Sayın {cust_name}, {plate} plakalı {veh_desc} aracınızın ekspertiz raporu tamamlandı "
        f"(Puan: {score}/100). Dijital raporunuzu incelemek için: {report_url}"
    )
    cust_key = f"notif-insp-cust-{report.id}"
    existing_cust = db.scalars(
        select(NotificationOutbox).where(NotificationOutbox.idempotency_key == cust_key)
    ).first()
    if not existing_cust:
        cust_notif = NotificationOutbox(
            appointment_id=app_id,
            recipient_type="customer",
            recipient=cust_phone,
            channel="sms",
            message=cust_msg,
            status="pending",
            idempotency_key=cust_key,
        )
        db.add(cust_notif)
        notifications.append(cust_notif)

    # 2. Kurumsal Cari Galeri WhatsApp
    account = None
    if appointment and appointment.corporate_account_id:
        account = db.get(CorporateAccount, appointment.corporate_account_id)
    if account:
        corp_phone = account.phone or "05550002233"
        corp_msg = (
            f"Sayın {account.name}, {plate} plakalı {veh_desc} aracın ekspertiz raporu tamamlandı "
            f"(Puan: {score}/100). Dijital rapor PDF: {report_url}"
        )
        corp_key = f"notif-insp-corp-{report.id}"
        existing_corp = db.scalars(
            select(NotificationOutbox).where(NotificationOutbox.idempotency_key == corp_key)
        ).first()
        if not existing_corp:
            corp_notif = NotificationOutbox(
                appointment_id=app_id,
                recipient_type="corporate",
                recipient=corp_phone,
                channel="whatsapp",
                message=corp_msg,
                status="pending",
                idempotency_key=corp_key,
            )
            db.add(corp_notif)
            notifications.append(corp_notif)

    return notifications


def dispatch_pending_notifications(db, limit: int = 50) -> list[NotificationOutbox]:
    """
    Outbox tablosundaki 'pending' durumdaki bildirimleri alip aktif saglayici uzerinden gonderir.
    Hata durumunda retry sayisini artirir ve son hatayi kaydeder.
    """
    pending = (
        db.scalars(
            select(NotificationOutbox)
            .where(NotificationOutbox.status == "pending")
            .order_by(NotificationOutbox.created_at)
            .limit(limit)
        ).all()
    )

    provider = get_notification_provider()
    processed = []

    for item in pending:
        item.attempts += 1
        try:
            provider.send(
                channel=item.channel,
                recipient=item.recipient,
                message=item.message,
            )
            item.status = "sent"
            item.sent_at = now()
            item.last_error = None
        except Exception as e:
            item.last_error = str(e)
            if item.attempts >= 3:
                item.status = "failed"
            logger.warning(
                "Bildirim gonderilemedi: %s (deneme %d): %s",
                item.id,
                item.attempts,
                e,
            )
        processed.append(item)

    if processed:
        db.commit()

    return processed


def retry_notification(db, notification_id: str) -> Optional[NotificationOutbox]:
    """Basarisiz olmus veya bekleyen bir bildirimi yeniden kuyruga alip gonderir."""
    notif = db.get(NotificationOutbox, notification_id)
    if not notif:
        return None
    notif.status = "pending"
    notif.last_error = None
    db.commit()
    dispatched = dispatch_pending_notifications(db, limit=1)
    return dispatched[0] if dispatched else notif

