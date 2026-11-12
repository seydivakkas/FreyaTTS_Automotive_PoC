"""Shared read-only appointment move checks for preview and commit."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from backend.db import Appointment, BaySchedule, InspectionBay, InspectionLift, Slot
from backend.lift_bay_capacity_scheduler import check_multi_stage_bay_capacity
from backend.queue_lift import check_slot_lift_capacity


def slot_instant(slot: Slot) -> datetime:
    instant = datetime.fromisoformat(slot.starts_at)
    return instant if instant.utcoffset() is not None else instant.replace(tzinfo=timezone.utc)


def slot_summary(slot: Slot | None) -> dict | None:
    if slot is None:
        return None
    return {"id": slot.id, "starts_at": slot_instant(slot).isoformat(), "duration_minutes": slot.duration_minutes}


def version_for(appointment: Appointment, source: Slot | None, target: Slot) -> str:
    content = [appointment.id, appointment.status, appointment.confirmed, appointment.package_type,
               slot_summary(source), slot_summary(target)]
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


class MoveCheck:
    def __init__(self, db, appointment: Appointment, now: datetime):
        self.db = db
        self.appointment = appointment
        self.now = now
        self.simple_lifts = db.scalar(select(InspectionLift.id).limit(1)) is not None
        self.stations = db.scalar(select(InspectionBay.id).limit(1)) is not None
        self.has_assignment = (
            db.scalar(select(BaySchedule.id).where(
                BaySchedule.appointment_id == appointment.id,
                BaySchedule.status.in_(("scheduled", "in_progress")),
            ).limit(1)) is not None
            or db.scalar(select(InspectionLift.id).where(
                InspectionLift.current_appointment_id == appointment.id,
                InspectionLift.status == "busy",
            ).limit(1)) is not None
        )

    def evaluate(self, target: Slot) -> tuple[str, str, str]:
        if self.appointment.status != "confirmed" or not self.appointment.confirmed:
            return "appointment_inactive", "unchecked", "Yalnız onaylı randevular taşınabilir."
        if target.id is not None and target.id == self.appointment.slot_id:
            return "same_slot", "unchecked", "Randevu zaten bu saatte."
        if slot_instant(target) <= self.now:
            return "past", "unchecked", "Geçmiş saate randevu taşınamaz."
        if target.id is not None and self.db.scalar(select(Appointment.id).where(
            Appointment.slot_id == target.id, Appointment.id != self.appointment.id,
        ).limit(1)) is not None:
            return "occupied", "unchecked", "Hedef saat zaten dolu."
        if self.has_assignment:
            return "assigned", "conflict", "Randevunun aktif lift veya istasyon ataması var. Önce atamayı düzenleyin."
        if self.simple_lifts and not check_slot_lift_capacity(
            self.db, target.starts_at, target.duration_minutes,
            exclude_appointment_id=self.appointment.id, seed=False,
        ):
            return "capacity", "conflict", "Hedef saatte lift kapasitesi dolu veya liftler bakımda."
        if self.stations:
            result = check_multi_stage_bay_capacity(
                self.db, package_type=self.appointment.package_type, requested_start_iso=target.starts_at,
                lookahead_intervals=0, seed=False,
            )
            if not result.is_available:
                return "capacity", "conflict", result.bottleneck_reason or "İstasyon kapasitesi yetersiz."
        if self.simple_lifts or self.stations:
            return "available", "available", "Hedef saat ve tanımlı kapasite uygun."
        return "available", "unknown", "Hedef saat boş. Lift ve istasyon kapasitesi tanımlı değil."

    def alternatives(self, target: Slot) -> list[dict]:
        booked = select(Appointment.slot_id).where(Appointment.slot_id.is_not(None))
        start = func.julianday(Slot.starts_at)
        candidates = self.db.scalars(select(Slot).where(
            start > func.julianday(self.now.isoformat()), Slot.id != target.id, Slot.id.not_in(booked),
        ).order_by(func.abs(start - func.julianday(target.starts_at)), start, Slot.id).limit(32))
        choices = []
        for candidate in candidates:
            if self.evaluate(candidate)[0] == "available":
                choices.append(slot_summary(candidate))
                if len(choices) == 4:
                    break
        return choices
