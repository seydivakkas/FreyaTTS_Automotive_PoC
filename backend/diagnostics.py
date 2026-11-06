"""OBD-II Vehicle Diagnostics, DTC Registry, Maintenance Scheduling, and Proactive Alerts.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from __future__ import annotations

import logging
from typing import Any
from sqlalchemy import select
from backend.db import (
    VehicleDiagnostic,
    Vehicle,
    Appointment,
    NotificationOutbox,
    OutboundCall,
    now,
)
from backend.outbound import initiate_outbound_call

logger = logging.getLogger("automotive_voice.diagnostics")

# Standard SAE J2012 / ISO 15031 OBD-II Fault Codes Knowledge Base
DTC_REGISTRY: dict[str, dict[str, str]] = {
    "P0300": {
        "desc": "Rastgele veya Çoklu Silindir Ateşleme Arızası (Misfire Detected)",
        "cat": "engine",
        "sev": "critical",
        "action": "Ateşleme bujileri, bobinler ve yakıt enjektörleri acilen kontrol edilmeli.",
    },
    "P0301": {
        "desc": "1. Silindir Ateşleme Hatası (Cylinder 1 Misfire)",
        "cat": "engine",
        "sev": "critical",
        "action": "1. silindir buji, bobin ve kompresyon değerleri incelenmelidir.",
    },
    "P0302": {
        "desc": "2. Silindir Ateşleme Hatası (Cylinder 2 Misfire)",
        "cat": "engine",
        "sev": "critical",
        "action": "2. silindir buji ve ateşleme bobini kontrol edilmelidir.",
    },
    "P0303": {
        "desc": "3. Silindir Ateşleme Hatası (Cylinder 3 Misfire)",
        "cat": "engine",
        "sev": "critical",
        "action": "3. silindir buji ve ateşleme bobini kontrol edilmelidir.",
    },
    "P0304": {
        "desc": "4. Silindir Ateşleme Hatası (Cylinder 4 Misfire)",
        "cat": "engine",
        "sev": "critical",
        "action": "4. silindir buji ve ateşleme bobini kontrol edilmelidir.",
    },
    "P0420": {
        "desc": "Katalitik Konvertör Sistemi Verimliliği Eşik Altı (Bank 1)",
        "cat": "emissions",
        "sev": "warning",
        "action": "Oksijen (lambda) sensörü ve egzoz emisyon katalizörü kontrol edilmeli.",
    },
    "P0171": {
        "desc": "Sistem Çok Fakir (Hava/Yakıt Karışımı Bank 1)",
        "cat": "fuel",
        "sev": "warning",
        "action": "Hava akışmetre (MAF) ve emme manifoldu vakum kaçakları incelenmelidir.",
    },
    "P0128": {
        "desc": "Soğutma Sıvısı Termostat Sıcaklığı Eşik Altı",
        "cat": "cooling",
        "sev": "warning",
        "action": "Termostat açma derecesi ve motor soğutma sıvısı seviyesi test edilmeli.",
    },
    "P0700": {
        "desc": "Otomatik Şanzıman Kontrol Sistemi Arızası",
        "cat": "transmission",
        "sev": "critical",
        "action": "Şanzıman elektronik kontrol ünitesi (TCU) ve mekatronik basıncı test edilmeli.",
    },
    "B0001": {
        "desc": "Sürücü Ön Hava Yastığı (Airbag) Devre Direnç Arızası",
        "cat": "airbag",
        "sev": "critical",
        "action": "Direksiyon hava yastığı sargısı ve emniyet kemeri gergisi acilen kontrol edilmelidir.",
    },
    "C0035": {
        "desc": "Sol Ön Tekerlek Hız Sensörü (ABS) Devre Hatası",
        "cat": "brakes",
        "sev": "warning",
        "action": "Fren balataları, ABS hız sensörü ve sinyal kablosu incelenmelidir.",
    },
    "U0100": {
        "desc": "Motor Kontrol Modülü (ECM) ile İletişim Kaybı",
        "cat": "network",
        "sev": "critical",
        "action": "CAN-Bus iletişim hattı, akü voltajı ve beyin soketleri kontrol edilmeli.",
    },
}


def lookup_dtc(code: str) -> dict[str, str]:
    """Looks up DTC information or provides a structured default classification."""
    clean_code = (code or "").strip().upper()
    if clean_code in DTC_REGISTRY:
        info = DTC_REGISTRY[clean_code]
        return {
            "dtc_code": clean_code,
            "description_tr": info["desc"],
            "system_category": info["cat"],
            "severity": info["sev"],
            "recommended_action": info["action"],
        }

    # Generic categorization based on SAE prefix
    prefix = clean_code[:1] if clean_code else "P"
    cat_map = {
        "P": ("engine", "Güç Aktarma / Motor Arıza Kodu"),
        "B": ("body", "Gövde / Karoser Arıza Kodu"),
        "C": ("chassis", "Şasi / Fren Sistemi Arıza Kodu"),
        "U": ("network", "Ağ ve Haberleşme Arıza Kodu"),
    }
    cat, name = cat_map.get(prefix, ("general", "Araç Teşhis Kodu"))

    return {
        "dtc_code": clean_code or "P0000",
        "description_tr": f"Standart OBD-II {name} ({clean_code})",
        "system_category": cat,
        "severity": "warning",
        "recommended_action": "Detaylı arıza tespiti ve OBD taraması için servise danışınız.",
    }


def calculate_maintenance_schedule(
    current_km: int, interval_km: int = 15000
) -> tuple[int, str]:
    """Computes next scheduled maintenance kilometer and status (normal, due_soon, overdue)."""
    if current_km <= 0:
        return interval_km, "normal"

    # Next service milestone
    completed_intervals = current_km // interval_km
    next_service_km = (completed_intervals + 1) * interval_km
    km_left = next_service_km - current_km

    if km_left <= 0:
        return next_service_km, "overdue"
    if km_left <= 1500:
        return next_service_km, "due_soon"
    return next_service_km, "normal"


def ingest_vehicle_telemetry(
    db,
    *,
    vehicle_id: str,
    current_km: int,
    dtc_codes: list[str],
    source: str = "obd_dongle",
    owner_name: str = "",
    owner_phone: str = "",
) -> list[VehicleDiagnostic]:
    """Ingests OBD-II telemetry, resolves DTC definitions, computes maintenance status,

    and saves diagnostic events to the database.
    """
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise ValueError(f"Araç bulunamadı: {vehicle_id}")

    # If owner info is empty, attempt to infer from recent appointment
    if not owner_phone or not owner_name:
        last_app = db.scalars(
            select(Appointment)
            .where(Appointment.vehicle_id == vehicle_id)
            .order_by(Appointment.created_at.desc())
        ).first()
        if last_app:
            if not owner_name:
                owner_name = last_app.customer
            if not owner_phone:
                import re

                digits = re.findall(r"\d+", last_app.customer or "")
                if digits and len("".join(digits)) >= 10:
                    owner_phone = "".join(digits)

    next_service_km, maint_status = calculate_maintenance_schedule(current_km)

    created_diagnostics: list[VehicleDiagnostic] = []

    # If no DTC codes provided, create a periodic maintenance tracking entry if due soon or overdue
    codes_to_process = [c.strip().upper() for c in dtc_codes if c.strip()]
    if not codes_to_process and maint_status in ("due_soon", "overdue"):
        diag = VehicleDiagnostic(
            vehicle_id=vehicle_id,
            dtc_code="SERVICE_DUE",
            severity="warning" if maint_status == "due_soon" else "critical",
            system_category="maintenance",
            description_tr=f"Periyodik Bakım Zamanı ({next_service_km:,} km)".replace(
                ",", "."
            ),
            recommended_action=f"Aracınız {current_km:,} km'ye ulaştı. Yağ, filtre ve periyodik bakım kontrolü önerilir.".replace(
                ",", "."
            ),
            current_mileage_km=current_km,
            next_service_km=next_service_km,
            maintenance_status=maint_status,
            source=source,
            is_resolved=False,
            owner_name=owner_name,
            owner_phone=owner_phone,
        )
        db.add(diag)
        created_diagnostics.append(diag)

    for code in codes_to_process:
        dtc_info = lookup_dtc(code)
        diag = VehicleDiagnostic(
            vehicle_id=vehicle_id,
            dtc_code=dtc_info["dtc_code"],
            severity=dtc_info["severity"],
            system_category=dtc_info["system_category"],
            description_tr=dtc_info["description_tr"],
            recommended_action=dtc_info["recommended_action"],
            current_mileage_km=current_km,
            next_service_km=next_service_km,
            maintenance_status=maint_status,
            source=source,
            is_resolved=False,
            owner_name=owner_name,
            owner_phone=owner_phone,
        )
        db.add(diag)
        created_diagnostics.append(diag)

    db.commit()
    return created_diagnostics


class PhoneMissingError(ValueError):
    """Teşhis için aranacak/mesaj atılacak gerçek bir telefon numarası yok."""


async def trigger_proactive_diagnostic_call(
    db,
    *,
    diagnostic_id: str,
    phone: str = "",
) -> OutboundCall:
    """Initiates an outbound proactive voice call to the vehicle owner

    using Asterisk AMI to offer inspection and service appointment.
    """
    diag = db.get(VehicleDiagnostic, diagnostic_id)
    if not diag:
        raise ValueError("Teşhis kaydı bulunamadı")

    target_phone = phone or diag.owner_phone
    if not target_phone:
        raise PhoneMissingError("Telefon yok: teşhis kaydında ve istekte telefon numarası bulunmuyor")
    vehicle = db.get(Vehicle, diag.vehicle_id)
    veh_desc = (
        vehicle.description
        if vehicle
        else f"{diag.dtc_code} kodlu araç"
    )
    customer_name = diag.owner_name or "Müşterimiz"

    # Create dummy/synthetic appointment ID for FK if needed or find existing appointment
    last_app = db.scalars(
        select(Appointment)
        .where(Appointment.vehicle_id == diag.vehicle_id)
        .order_by(Appointment.created_at.desc())
    ).first()

    app_id = last_app.id if last_app else None
    if not app_id:
        # Create an unconfirmed pending diagnostic appointment record
        placeholder_app = Appointment(
            vehicle_id=diag.vehicle_id,
            slot_id=None,
            customer=customer_name,
            idempotency_key=f"proactive-{diag.id}",
            confirmed=False,
            status="diagnostic_alert",
        )
        db.add(placeholder_app)
        db.flush()
        app_id = placeholder_app.id

    call_obj = await initiate_outbound_call(
        db,
        appointment_id=app_id,
        phone=target_phone,
        call_type="diagnostic_alert",
    )
    diag.last_notified_at = now()
    db.commit()
    return call_obj


def trigger_proactive_diagnostic_sms(
    db,
    *,
    diagnostic_id: str,
    phone: str = "",
) -> NotificationOutbox:
    """Queues a proactive SMS notification regarding the vehicle diagnostic alert."""
    diag = db.get(VehicleDiagnostic, diagnostic_id)
    if not diag:
        raise ValueError("Teşhis kaydı bulunamadı")

    target_phone = phone or diag.owner_phone
    if not target_phone:
        raise PhoneMissingError("Telefon yok: teşhis kaydında ve istekte telefon numarası bulunmuyor")
    vehicle = db.get(Vehicle, diag.vehicle_id)
    veh_desc = (
        vehicle.description
        if vehicle
        else "aracınız"
    )
    plate = getattr(vehicle, "plate", "") or ""
    plate_info = f" ({plate})" if plate else ""

    last_app = db.scalars(
        select(Appointment)
        .where(Appointment.vehicle_id == diag.vehicle_id)
        .order_by(Appointment.created_at.desc())
    ).first()

    app_id = last_app.id if last_app else None
    if not app_id:
        placeholder_app = Appointment(
            vehicle_id=diag.vehicle_id,
            slot_id=None,
            customer=diag.owner_name or "Müşterimiz",
            idempotency_key=f"sms-diag-{diag.id}",
            confirmed=False,
            status="diagnostic_alert",
        )
        db.add(placeholder_app)
        db.flush()
        app_id = placeholder_app.id

    msg = (
        f"Sayın {diag.owner_name or 'Müşterimiz'}, {veh_desc}{plate_info} aracınızda "
        f"{diag.dtc_code} ({diag.description_tr}) arıza uyarısı tespit edilmiştir. "
        f"Önerilen işlem: {diag.recommended_action} "
        f"Randevu için bizi arayabilir veya sisteme giriş yapabilirsiniz."
    )

    notif = NotificationOutbox(
        appointment_id=app_id,
        recipient_type="customer",
        recipient=target_phone,
        channel="sms",
        message=msg,
        status="pending",
        idempotency_key=f"notif-diag-{diag.id}",
    )
    db.add(notif)
    diag.last_notified_at = now()
    db.commit()
    return notif


def resolve_diagnostic(db, diagnostic_id: str) -> VehicleDiagnostic:
    """Marks a diagnostic alert as resolved/fixed."""
    diag = db.get(VehicleDiagnostic, diagnostic_id)
    if not diag:
        raise ValueError("Teşhis kaydı bulunamadı")
    diag.is_resolved = True
    db.commit()
    return diag
