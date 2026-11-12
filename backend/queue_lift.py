"""Lift and Queue Management Engine for Automotive Inspection Centers.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from backend.db import (
    InspectionLift,
    InspectionQueue,
    Appointment,
    Slot,
    Vehicle,
    now,
)

# Standard inspection package types and durations
PACKAGE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "motor_mekanik": {
        "key": "motor_mekanik",
        "name": "Motor & Mekanik Paketi",
        "duration_minutes": 30,
        "description": "Dyno motor güç testi, şanzıman, alt takım ve sıvı kaçak kontrolleri.",
        "base_price_kurus": 95000,
        "keywords": ["motor", "mekanik", "dyno", "alt takım", "şanzıman", "sadece motor"],
    },
    "standart_ekspertiz": {
        "key": "standart_ekspertiz",
        "name": "Standart Ekspertiz Paketi",
        "duration_minutes": 45,
        "description": "Boya, kaporta mikron testi, motor, mekanik ve OBD elektronik arıza taraması.",
        "base_price_kurus": 145000,
        "keywords": ["standart", "kaporta", "boya", "obd", "orta paket", "genel kontrol"],
    },
    "full_kapsamli": {
        "key": "full_kapsamli",
        "name": "Full Kapsamlı (Tam) Ekspertiz",
        "duration_minutes": 60,
        "description": "500 nokta detaylı kontrol, kaporta, boya, şasi, podye, airbag, dyno motor ve yol testi.",
        "base_price_kurus": 195000,
        "keywords": ["tam", "full", "kapsamlı", "hepsi", "tam ekspertiz", "bütün", "komple"],
    },
    "vip_premium": {
        "key": "vip_premium",
        "name": "VIP Premium & Dijital Ekspertiz",
        "duration_minutes": 75,
        "description": "Full ekspertiz + endoskopi silindir kamera incelemesi, sesli dijital teslimat ve öncelikli sıra.",
        "base_price_kurus": 260000,
        "keywords": ["vip", "premium", "lüks", "endoskopi", "özel paket"],
    },
}


def match_package(text: str) -> dict[str, Any]:
    """Identify requested inspection package from user speech or text."""
    lower = text.lower()
    for pkg_key, pkg_info in PACKAGE_DEFINITIONS.items():
        for kw in pkg_info["keywords"]:
            if kw in lower:
                return pkg_info
    return PACKAGE_DEFINITIONS["standart_ekspertiz"]


def seed_default_lifts(db: Session) -> list[InspectionLift]:
    """Ensure standard inspection lifts exist if none are found."""
    existing = db.scalars(select(InspectionLift).order_by(InspectionLift.lift_number)).all()
    if existing:
        return list(existing)

    defaults = [
        InspectionLift(
            name="Lift-1 (Genel Karoser & Boya)",
            lift_number=1,
            status="idle",
            notes="Standart ekspertiz ve kaporta mikron istasyonu",
        ),
        InspectionLift(
            name="Lift-2 (Dyno & Motor/Mekanik)",
            lift_number=2,
            status="idle",
            notes="Dinamometre ve ağır mekanik alt takım istasyonu",
        ),
    ]
    for lift in defaults:
        db.add(lift)
    db.commit()
    for lift in defaults:
        db.refresh(lift)
    return defaults


def get_all_lifts(db: Session) -> list[InspectionLift]:
    """Retrieve all lifts ordered by lift number."""
    seed_default_lifts(db)
    return list(db.scalars(select(InspectionLift).order_by(InspectionLift.lift_number)).all())


def add_lift(
    db: Session,
    *,
    name: str,
    lift_number: int | None = None,
    notes: str = "",
) -> InspectionLift:
    """Create a new inspection lift in the center."""
    if lift_number is None:
        max_num = db.scalar(select(func.max(InspectionLift.lift_number))) or 0
        lift_number = max_num + 1

    lift = InspectionLift(
        name=name,
        lift_number=lift_number,
        status="idle",
        notes=notes,
    )
    db.add(lift)
    db.commit()
    db.refresh(lift)
    return lift


def set_lift_status(
    db: Session,
    *,
    lift_id: str,
    status: str,
    notes: str = "",
) -> InspectionLift:
    """Set lift status ('idle', 'busy', 'maintenance')."""
    lift = db.get(InspectionLift, lift_id)
    if not lift:
        raise ValueError(f"Lift bulunamadı: {lift_id}")
    if status not in {"idle", "busy", "maintenance"}:
        raise ValueError(f"Geçersiz lift durumu: {status}")

    lift.status = status
    if notes:
        lift.notes = notes
    if status == "idle":
        lift.current_appointment_id = None
        lift.current_vehicle_plate = ""
        lift.started_at = None
    elif status == "maintenance":
        lift.current_appointment_id = None
        lift.current_vehicle_plate = ""
        lift.started_at = None

    db.commit()
    db.refresh(lift)
    return lift


def assign_lift(
    db: Session,
    *,
    lift_id: str,
    appointment_id: str | None = None,
    queue_id: str | None = None,
    plate: str = "",
    package_type: str = "standart_ekspertiz",
) -> InspectionLift:
    """Assign an appointment or queue vehicle to a lift and start inspection."""
    lift = db.get(InspectionLift, lift_id)
    if not lift:
        raise ValueError(f"Lift bulunamadı: {lift_id}")
    if lift.status == "maintenance":
        raise ValueError(f"{lift.name} şu an bakımda olduğu için araç alınamaz.")

    pkg_info = PACKAGE_DEFINITIONS.get(package_type, PACKAGE_DEFINITIONS["standart_ekspertiz"])
    duration = pkg_info["duration_minutes"]

    assigned_plate = plate
    assigned_app_id = appointment_id

    # If linked to appointment, extract vehicle plate
    if appointment_id:
        app = db.get(Appointment, appointment_id)
        if app:
            veh = db.get(Vehicle, app.vehicle_id)
            if veh and veh.plate:
                assigned_plate = veh.plate
            if app.package_type:
                package_type = app.package_type
                duration = PACKAGE_DEFINITIONS.get(package_type, {}).get("duration_minutes", duration)

    # If linked to a queue item
    if queue_id:
        q_item = db.get(InspectionQueue, queue_id)
        if q_item:
            assigned_plate = q_item.plate
            package_type = q_item.package_type
            duration = q_item.duration_minutes
            assigned_app_id = q_item.appointment_id or assigned_app_id
            q_item.status = "in_progress"
            q_item.lift_id = lift.id
            q_item.started_at = now()

    lift.status = "busy"
    lift.current_appointment_id = assigned_app_id
    lift.current_vehicle_plate = assigned_plate
    lift.package_type = package_type
    lift.estimated_duration_min = duration
    lift.started_at = now()

    db.commit()
    db.refresh(lift)
    return lift


def release_lift(db: Session, *, lift_id: str) -> InspectionLift:
    """Complete current inspection on lift and mark it idle."""
    lift = db.get(InspectionLift, lift_id)
    if not lift:
        raise ValueError(f"Lift bulunamadı: {lift_id}")

    # Mark active queue item completed if attached
    active_q = db.scalars(
        select(InspectionQueue)
        .where(
            and_(
                InspectionQueue.lift_id == lift_id,
                InspectionQueue.status == "in_progress",
            )
        )
    ).first()
    if active_q:
        active_q.status = "completed"
        active_q.completed_at = now()

    lift.status = "idle"
    lift.current_appointment_id = None
    lift.current_vehicle_plate = ""
    lift.started_at = None

    db.commit()
    db.refresh(lift)
    return lift


def enqueue_vehicle(
    db: Session,
    *,
    plate: str,
    customer: str,
    package_type: str = "standart_ekspertiz",
    appointment_id: str | None = None,
    vehicle_id: str | None = None,
) -> InspectionQueue:
    """Add a vehicle to the on-site inspection queue."""
    pkg_info = PACKAGE_DEFINITIONS.get(package_type, PACKAGE_DEFINITIONS["standart_ekspertiz"])

    # Determine next queue number (e.g. 101, 102...)
    max_q = db.scalar(select(func.max(InspectionQueue.queue_number))) or 100
    next_q = max_q + 1

    q_item = InspectionQueue(
        queue_number=next_q,
        appointment_id=appointment_id,
        vehicle_id=vehicle_id,
        plate=plate.upper().strip(),
        customer=customer.strip(),
        package_type=package_type,
        duration_minutes=pkg_info["duration_minutes"],
        status="waiting",
        check_in_at=now(),
    )
    db.add(q_item)
    db.commit()
    db.refresh(q_item)
    return q_item


def get_queue(
    db: Session,
    *,
    status: str | None = None,
) -> list[InspectionQueue]:
    """List inspection queue items."""
    stmt = select(InspectionQueue)
    if status:
        stmt = stmt.where(InspectionQueue.status == status)
    stmt = stmt.order_by(InspectionQueue.queue_number.asc())
    return list(db.scalars(stmt).all())


def call_next_queue_item(
    db: Session,
    *,
    lift_id: str,
) -> InspectionQueue | None:
    """Take the next waiting vehicle from queue and assign to lift."""
    next_item = db.scalars(
        select(InspectionQueue)
        .where(InspectionQueue.status == "waiting")
        .order_by(InspectionQueue.queue_number.asc())
    ).first()

    if not next_item:
        return None

    assign_lift(
        db,
        lift_id=lift_id,
        queue_id=next_item.id,
        package_type=next_item.package_type,
    )
    db.refresh(next_item)
    return next_item


def get_lift_capacity_status(db: Session) -> dict[str, Any]:
    """Calculate real-time lift capacity, occupancy, and earliest free time."""
    lifts = get_all_lifts(db)
    total = len(lifts)
    maintenance = sum(1 for l in lifts if l.status == "maintenance")
    busy = sum(1 for l in lifts if l.status == "busy")
    idle = sum(1 for l in lifts if l.status == "idle")
    active = total - maintenance

    # Waiting cars in queue
    waiting_count = db.scalar(
        select(func.count(InspectionQueue.id)).where(InspectionQueue.status == "waiting")
    ) or 0

    all_busy = (busy >= active and active > 0) or active == 0

    # Calculate estimated wait minutes
    now_utc = datetime.now(timezone.utc)
    remaining_minutes_list = []
    unknown_remaining = False  # kalan süresi hesaplanamayan meşgul lift var mı

    for l in lifts:
        if l.status == "busy":
            if not l.started_at:
                unknown_remaining = True
                continue
            try:
                st = datetime.fromisoformat(l.started_at)
                if st.tzinfo is None:
                    st = st.replace(tzinfo=timezone.utc)
                elapsed = (now_utc - st).total_seconds() / 60.0
                rem = max(1.0, float(l.estimated_duration_min) - elapsed)
                remaining_minutes_list.append(rem)
            except Exception:
                unknown_remaining = True  # uydurma 15 dk yok: bilinmiyor

    # Queue waiting durations
    waiting_minutes_sum = db.scalar(
        select(func.sum(InspectionQueue.duration_minutes)).where(
            InspectionQueue.status == "waiting"
        )
    ) or 0

    # Hesaplanamayan değerler None'dır (999 / "--:--" gibi sahte sayı veya yer tutucu yok)
    estimated_wait: Optional[int]
    earliest_time: Optional[str]
    if active <= 0:
        estimated_wait = None
        earliest_time = None
        spoken_msg = "Şu anda tüm liftlerimiz bakımda olduğu için araç alamıyoruz."
    elif not all_busy and waiting_count == 0:
        estimated_wait = 0
        earliest_time = now_utc.astimezone(ZoneInfo("Europe/Istanbul")).strftime("%H:%M")
        spoken_msg = f"Şu an {idle} liftimiz boştur, aracınızı hemen muayeneye alabiliyoruz."
    else:
        # Sum of earliest finish on active lifts + queue backlog divided by active lifts
        # Gerçek lift kalan süreleri + kuyruktaki araçların süreleri; eksik veri varsa None
        if unknown_remaining:
            estimated_wait = None
        else:
            total_backlog = sum(remaining_minutes_list) + waiting_minutes_sum
            estimated_wait = int(round(total_backlog / active))

        # Earliest available completion time (kalan süre bilinmiyorsa None)
        if unknown_remaining or not remaining_minutes_list:
            earliest_time = None
        else:
            earliest_free_min = min(remaining_minutes_list)
            earliest_dt = now_utc + timedelta(minutes=earliest_free_min)
            earliest_time = earliest_dt.astimezone(ZoneInfo("Europe/Istanbul")).strftime("%H:%M")

        # If appointments exist, check earliest available appointment slot
        earliest_slot = db.scalars(
            select(Slot)
            .where(
                and_(
                    Slot.starts_at > now_utc.isoformat(),
                    Slot.id.not_in(
                        select(Appointment.slot_id).where(Appointment.slot_id.is_not(None))
                    ),
                )
            )
            .order_by(Slot.starts_at.asc())
        ).first()

        if earliest_slot:
            try:
                s_dt = datetime.fromisoformat(earliest_slot.starts_at).astimezone(
                    ZoneInfo("Europe/Istanbul")
                )
                earliest_time = s_dt.strftime("%H:%M")
            except Exception:
                pass

        if earliest_time is not None:
            spoken_msg = f"Şu an {busy} liftimiz dolu, en erken saat {earliest_time}'te alabiliyoruz."
        else:
            spoken_msg = f"Şu an {busy} liftimiz dolu; bekleme süresini şu anda hesaplayamıyorum."

    return {
        "total_lifts": total,
        "active_lifts": active,
        "busy_lifts": busy,
        "idle_lifts": idle,
        "maintenance_lifts": maintenance,
        "queue_waiting_count": waiting_count,
        "estimated_wait_minutes": estimated_wait,
        "all_lifts_busy": all_busy,
        "earliest_available_time": earliest_time,
        "spoken_message": spoken_msg,
    }


def check_slot_lift_capacity(
    db: Session,
    slot_start_iso: str,
    duration_minutes: int = 45,
    *,
    exclude_appointment_id: str | None = None,
    seed: bool = True,
) -> bool:
    """Check if center has available lift capacity for the requested timeslot.

    Returns True if slot can be accommodated, False if all lifts are booked.
    """
    lifts = get_all_lifts(db) if seed else db.scalars(select(InspectionLift)).all()
    active_count = sum(1 for l in lifts if l.status != "maintenance")
    if active_count <= 0:
        return False

    try:
        req_start = datetime.fromisoformat(slot_start_iso)
        if req_start.tzinfo is None:
            req_start = req_start.replace(tzinfo=timezone.utc)
    except Exception:
        return True

    req_end = req_start + timedelta(minutes=duration_minutes)

    # Check how many existing appointments overlap with this window
    booked = select(Slot).join(Appointment, Appointment.slot_id == Slot.id).where(
        Appointment.status != "cancelled",
    )
    if exclude_appointment_id is not None:
        booked = booked.where(Appointment.id != exclude_appointment_id)
    boundaries = []
    for s in db.scalars(booked):
        try:
            s_start = datetime.fromisoformat(s.starts_at)
            if s_start.tzinfo is None:
                s_start = s_start.replace(tzinfo=timezone.utc)
            s_dur = getattr(s, "duration_minutes", 30) or 30
            s_end = s_start + timedelta(minutes=s_dur)

            if req_start < s_end and req_end > s_start:
                boundaries.extend(((max(req_start, s_start), 1), (min(req_end, s_end), -1)))
        except (TypeError, ValueError):
            continue
    overlapping_count = 0
    for _, change in sorted(boundaries):
        overlapping_count += change
        if overlapping_count >= active_count:
            return False
    return True

