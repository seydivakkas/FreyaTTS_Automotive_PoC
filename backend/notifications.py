"""
M10 Outbox Randevu Bildirim Servisi (SMS / WhatsApp).

Randevu olusturuldugunda transactional outbox tablosuna (notifications) musteri
ve kurumsal cari hesap (galeri) icin iletilecek onay bildirimlerini yazar.
Asenkron veya tetiklenen dispatcher ile at-least-once prensibiyle gonderir.
"""

from __future__ import annotations
import logging
import re
import httpx
from datetime import datetime, timezone, timedelta
from typing import Protocol, Optional, List
from sqlalchemy import select
from backend.config import settings
from backend.security_utils import signed_pdf_path
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


def format_phone_e164(phone: str) -> str:
    """Telefon numarasını E.164 uluslararası formatına (+90...) dönüştürür."""
    raw = (phone or "").strip()
    digits = re.sub(r"[^\d+]", "", raw)
    if not digits:
        return ""
    if digits.startswith("+"):
        return digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("05") and len(digits) == 11:
        return "+9" + digits
    if digits.startswith("5") and len(digits) == 10:
        return "+90" + digits
    if digits.startswith("905") and len(digits) == 12:
        return "+" + digits
    return ("+" if not digits.startswith("+") else "") + digits


class NotificationProvider(Protocol):
    def send(self, channel: str, recipient: str, message: str) -> dict:
        """Kanal uzerinden mesaji iletir. Basarili ise receipt doner, hata durumunda istisna firlatir."""
        ...


class MockNotificationProvider:
    """Testler ve yerel calisma icin bellek ici bildirim saglayici."""

    is_real = False

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
            # Gerçek bir iletim yapılmadı; outbox bu kaydı "sent" değil "simulated" işaretler.
            "simulated": True,
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


class TwilioNotificationProvider:
    """Twilio REST API ile gerçek SMS ve WhatsApp gönderim sağlayıcısı."""

    is_real = True

    def __init__(
        self,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
        whatsapp_from: str | None = None,
    ):
        self.account_sid = account_sid or settings.twilio_account_sid
        self.auth_token = auth_token or settings.twilio_auth_token
        self.from_number = from_number or settings.twilio_from_number
        self.whatsapp_from = whatsapp_from or settings.twilio_whatsapp_from
        self.sent_messages: list[dict] = []

    def send(self, channel: str, recipient: str, message: str) -> dict:
        if not self.account_sid or not self.auth_token:
            raise PermissionError(
                "Twilio kimlik bilgileri eksik (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN)"
            )

        recipient_clean = recipient.strip()
        e164_target = format_phone_e164(recipient_clean)
        if not e164_target:
            raise ValueError(f"Geçersiz telefon numarası: {recipient}")

        if channel == "whatsapp":
            from_addr = self.whatsapp_from
            if from_addr and not from_addr.startswith("whatsapp:"):
                from_addr = f"whatsapp:{from_addr}"
            to_addr = (
                recipient_clean
                if recipient_clean.startswith("whatsapp:")
                else f"whatsapp:{e164_target}"
            )
            if not from_addr:
                raise ValueError(
                    "Twilio WhatsApp gönderici numarası ayarlanmamış (TWILIO_WHATSAPP_FROM)"
                )
        elif channel == "sms":
            from_addr = self.from_number
            to_addr = e164_target
            if not from_addr:
                raise ValueError(
                    "Twilio SMS gönderici numarası ayarlanmamış (TWILIO_FROM_NUMBER)"
                )
        else:
            raise ValueError(f"Desteklenmeyen bildirim kanalı: {channel}")

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        payload = {
            "From": from_addr,
            "To": to_addr,
            "Body": message,
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(
                    url,
                    data=payload,
                    auth=(self.account_sid, self.auth_token),
                )
            if res.status_code not in (200, 201):
                err_body = res.text
                logger.error(
                    "Twilio API hatası: HTTP %d: %s (Alıcı: %s)",
                    res.status_code,
                    err_body,
                    to_addr,
                )
                raise RuntimeError(
                    f"Twilio API hatası (HTTP {res.status_code}): {err_body}"
                )

            data = res.json()
            receipt = {
                "provider": "twilio",
                "simulated": False,
                "channel": channel,
                "recipient": recipient,
                "target_e164": to_addr,
                "message": message,
                "external_id": data.get("sid", f"tw-{uid()[:8]}"),
                "status": data.get("status", "queued"),
                "delivered_at": now(),
            }
            self.sent_messages.append(receipt)
            return receipt
        except Exception as exc:
            if not isinstance(exc, (ValueError, PermissionError, RuntimeError)):
                logger.error("Twilio bağlantı hatası: %s", exc)
                raise RuntimeError(f"Twilio bağlantı hatası: {exc}") from exc
            raise

    def clear(self):
        self.sent_messages.clear()


_default_mock = MockNotificationProvider()
_active_provider: NotificationProvider | None = None


def get_notification_provider() -> NotificationProvider:
    global _active_provider
    if _active_provider is not None:
        return _active_provider

    if (settings.notification_provider or "").lower() == "twilio":
        if settings.twilio_account_sid and settings.twilio_auth_token:
            return TwilioNotificationProvider()
        logger.warning(
            "NOTIFICATION_PROVIDER=twilio ayarlandı ancak kimlik bilgileri eksik; MockNotificationProvider kullanılıyor."
        )

    return _default_mock


def can_send_real_notifications() -> bool:
    """Etkin sağlayıcı MockNotificationProvider değilse (veya is_real=True ise) True döner."""
    provider = get_notification_provider()
    if getattr(provider, "is_real", None) is not None:
        return bool(provider.is_real)
    return not isinstance(provider, MockNotificationProvider)


def set_notification_provider(provider: NotificationProvider | None) -> None:
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
    # Gerçek telefon yoksa SMS kuyruğa alınmaz: müşteri ADI alıcı olarak kullanılamaz.
    cust_target = (customer_phone or getattr(appointment, "customer_phone", "") or "").strip()
    cust_msg = (
        f"Sayın {appointment.customer}, {vehicle_name}{plate_info} aracınız için "
        f"{formatted_time} tarihindeki ekspertiz randevunuz onaylanmıştır. "
        f"Randevu Referans No: {ref_code}. "
        f"Adres: {settings.branch_address}. "
        f"📍 Konum / Harita: {settings.branch_maps_url} . "
        f"İptal ve saat değişikliği için bu mesaja yanıt verebilirsiniz."
    )
    if not cust_target:
        logger.warning(
            "Müşteri telefonu yok, randevu SMS'i kuyruğa alınmadı (alıcı olarak ad kullanılmaz): appointment_id=%s",
            appointment.id,
        )
    else:
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
    corp_target = (account.phone or "").strip() if account else ""
    if account and not corp_target:
        logger.warning(
            "Cari hesabın telefonu yok, WhatsApp bildirimi kuyruğa alınmadı: account_id=%s", account.id
        )
    if account and corp_target:
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

    # Müşteriye giden bağlantı imzalı ve süreli olmalıdır.
    report_url = custom_url or signed_pdf_path(report.id)
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
    # Gerçek telefon yoksa SMS kuyruğa alınmaz (sahte numara kullanılmaz).
    cust_phone = ""
    cust_name = "Müşterimiz"
    if appointment:
        cust_name = appointment.customer or "Müşterimiz"
        cust_phone = (getattr(appointment, "customer_phone", "") or "").strip()
        if not cust_phone:
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
    if not cust_phone:
        logger.warning("Müşteri telefonu yok, SMS kuyruğa alınmadı: report_id=%s", report.id)
    elif not existing_cust:
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
    if account and account.phone:
        corp_phone = account.phone
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
            receipt = provider.send(
                channel=item.channel,
                recipient=item.recipient,
                message=item.message,
            )
            if isinstance(receipt, dict) and receipt.get("simulated"):
                # Sağlayıcı yok (mock): mesaj müşteriye ulaşmadı, "sent" denmez.
                item.status = "simulated"
                item.sent_at = None
            else:
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


def queue_cancellation_notification(
    db,
    appointment: Appointment,
) -> Optional[NotificationOutbox]:
    """Randevu iptal edildiğinde müşteriye SMS bilgilendirmesini outbox kuyruğuna ekler."""
    cust_target = (appointment.customer_phone or "").strip()
    if not cust_target:
        return None

    key = f"notif-cancel-{appointment.id}"
    existing = db.scalars(
        select(NotificationOutbox).where(NotificationOutbox.idempotency_key == key)
    ).first()
    if existing:
        return existing

    msg = (
        f"Sayın {appointment.customer}, ekspertiz randevunuz talebiniz üzerine "
        f"başarıyla iptal edilmiştir. Dilediğiniz zaman tekrar randevu oluşturabilirsiniz. "
        f"İyi günler dileriz."
    )
    notif = NotificationOutbox(
        appointment_id=appointment.id,
        recipient_type="customer",
        recipient=cust_target,
        channel="sms",
        message=msg,
        status="pending",
        idempotency_key=key,
    )
    db.add(notif)
    db.commit()
    return notif


def scan_and_queue_appointment_reminders(
    db,
    *,
    hours_ahead_min: int = 20,
    hours_ahead_max: int = 36,
    trigger_voice_call: bool = False,
) -> list[NotificationOutbox]:
    """
    Belirtilen zaman penceresinde (varsayılan: 20 - 36 saat sonra, yaklaşık 1 gün sonra)
    başlayacak olan onaylı randevuları tarar.
    
    1. Henüz hatırlatma gönderilmemiş randevular için SMS/WhatsApp hatırlatmasını outbox kuyruğuna ekler.
    2. İstendiğinde veya hibrit modda Asterisk giden arama (outbound reminder) tetikler.
    """
    now_utc = datetime.now(timezone.utc)
    min_time = now_utc + timedelta(hours=hours_ahead_min)
    max_time = now_utc + timedelta(hours=hours_ahead_max)

    appointments = (
        db.scalars(
            select(Appointment)
            .where(Appointment.status.in_(["confirmed", "pending"]))
            .order_by(Appointment.created_at.desc())
        )
        .all()
    )

    queued: list[NotificationOutbox] = []
    for app in appointments:
        if not app.slot_id:
            continue
        slot = db.get(Slot, app.slot_id)
        if not slot or not slot.starts_at:
            continue
        try:
            slot_dt = datetime.fromisoformat(slot.starts_at)
            if slot_dt.tzinfo is None:
                slot_dt = slot_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if not (min_time <= slot_dt <= max_time):
            continue

        key = f"notif-reminder-{app.id}"
        existing = db.scalars(
            select(NotificationOutbox).where(NotificationOutbox.idempotency_key == key)
        ).first()
        if existing:
            continue

        cust_target = (app.customer_phone or "").strip()
        vehicle = db.get(Vehicle, app.vehicle_id) if app.vehicle_id else None
        vehicle_name = vehicle.description if vehicle else "aracınız"
        formatted_time = format_appointment_datetime(slot.starts_at)

        reminder_msg = (
            f"Sayın {app.customer}, {vehicle_name} için yarın {formatted_time} "
            f"tarihindeki ekspertiz randevunuzu hatırlatırız. "
            f"Teyit etmek için bu mesaja 'EVET', iptal etmek için 'İPTAL' yazarak yanıtlayabilirsiniz. "
            f"📍 İstasyon Konumu: {settings.branch_maps_url}"
        )

        if cust_target:
            notif = NotificationOutbox(
                appointment_id=app.id,
                recipient_type="customer",
                recipient=cust_target,
                channel="sms",
                message=reminder_msg,
                status="pending",
                idempotency_key=key,
            )
            db.add(notif)
            queued.append(notif)

        if trigger_voice_call and cust_target:
            try:
                from backend.outbound import initiate_outbound_call
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        initiate_outbound_call(
                            db,
                            appointment_id=app.id,
                            phone=cust_target,
                            call_type="reminder",
                        )
                    )
                except RuntimeError:
                    asyncio.run(
                        initiate_outbound_call(
                            db,
                            appointment_id=app.id,
                            phone=cust_target,
                            call_type="reminder",
                        )
                    )
            except Exception as e:
                logger.warning("Giden hatırlatma araması tetiklenemedi: %s", e)

    if queued:
        db.commit()

    return queued


