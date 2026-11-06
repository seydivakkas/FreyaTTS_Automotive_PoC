"""Planlama uç noktaları: lift, kuyruk, servis yeri (bay) çizelgesi."""

from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
)
from backend.db import (
    InspectionLift,
    InspectionQueue,
)
from backend.lift_bay_capacity_scheduler import (
    cancel_appointment_schedules,
    check_multi_stage_bay_capacity,
    get_bay_station_analytics,
    list_bay_schedules,
    list_bays,
    list_technicians,
    schedule_multi_stage_appointment,
    set_bay_status,
    set_technician_status,
)
from backend.queue_lift import (
    get_all_lifts,
    add_lift,
    set_lift_status,
    assign_lift,
    release_lift,
    enqueue_vehicle,
    get_queue,
    call_next_queue_item,
    get_lift_capacity_status,
)
from backend import db as db_module
from backend.schemas import (
    BayBookingIn,
    BayCapacityCheckIn,
    BayStatusIn,
    LiftAssignIn,
    LiftIn,
    LiftStatusIn,
    QueueEntryIn,
    TechnicianStatusIn,
)
from backend.deps import (
    auth,
    row,
)

router = APIRouter()


@router.get("/api/lifts", dependencies=[Depends(auth)])
def list_lifts():
    with db_module.Session() as db:
        lifts = get_all_lifts(db)
        return [row(l) for l in lifts]


@router.post("/api/lifts", dependencies=[Depends(auth)])
def create_lift(body: LiftIn):
    with db_module.Session() as db:
        lift = add_lift(
            db,
            name=body.name,
            lift_number=body.lift_number,
            notes=body.notes,
        )
        return row(lift)


@router.get("/api/lifts/capacity", dependencies=[Depends(auth)])
def lift_capacity():
    with db_module.Session() as db:
        return get_lift_capacity_status(db)


@router.post("/api/lifts/{id}/status", dependencies=[Depends(auth)])
def update_lift_status(id: str, body: LiftStatusIn):
    with db_module.Session() as db:
        try:
            lift = set_lift_status(db, lift_id=id, status=body.status, notes=body.notes)
            return row(lift)
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.post("/api/lifts/{id}/assign", dependencies=[Depends(auth)])
def assign_vehicle_to_lift(id: str, body: LiftAssignIn):
    with db_module.Session() as db:
        try:
            lift = assign_lift(
                db,
                lift_id=id,
                appointment_id=body.appointment_id,
                queue_id=body.queue_id,
                plate=body.plate,
                package_type=body.package_type,
            )
            return row(lift)
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.post("/api/lifts/{id}/release", dependencies=[Depends(auth)])
def release_vehicle_from_lift(id: str):
    with db_module.Session() as db:
        try:
            lift = release_lift(db, lift_id=id)
            return row(lift)
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.post("/api/lifts/{id}/call-next", dependencies=[Depends(auth)])
def call_next_for_lift(id: str):
    with db_module.Session() as db:
        try:
            q_item = call_next_queue_item(db, lift_id=id)
            if not q_item:
                return {"message": "Sırada bekleyen araç bulunmuyor", "assigned": False}
            lift = db.get(InspectionLift, id)
            return {
                "assigned": True,
                "queue_item": row(q_item),
                "lift": row(lift) if lift else None,
            }
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.get("/api/queue", dependencies=[Depends(auth)])
def list_queue(status: str | None = None):
    with db_module.Session() as db:
        items = get_queue(db, status=status)
        return [row(x) for x in items]


@router.post("/api/queue", dependencies=[Depends(auth)])
def add_to_queue(body: QueueEntryIn):
    with db_module.Session() as db:
        item = enqueue_vehicle(
            db,
            plate=body.plate,
            customer=body.customer,
            package_type=body.package_type,
            appointment_id=body.appointment_id,
            vehicle_id=body.vehicle_id,
        )
        return row(item)


@router.post("/api/queue/{id}/cancel", dependencies=[Depends(auth)])
def cancel_queue(id: str):
    with db_module.Session() as db:
        item = db.get(InspectionQueue, id)
        if not item:
            raise HTTPException(404, "Sıra kaydı bulunamadı")
        item.status = "cancelled"
        db.commit()
        return row(item)


# ============================================================================
# FİZİKSEL LİFT VE TEKNİSYEN KAPASİTE PLANLAYICI (BAY SCHEDULER) ENDPOINTS
# ============================================================================

@router.post("/api/bay-scheduler/check-capacity", dependencies=[Depends(auth)])
def bay_check_capacity_endpoint(body: BayCapacityCheckIn):
    with db_module.Session() as db:
        res = check_multi_stage_bay_capacity(
            db,
            package_type=body.package_type,
            requested_start_iso=body.requested_start_iso,
            exclude_schedule_id=body.exclude_schedule_id,
        )
        return res.to_dict()


@router.post("/api/bay-scheduler/book-stages", dependencies=[Depends(auth)])
def bay_book_stages_endpoint(body: BayBookingIn):
    with db_module.Session() as db:
        try:
            schedules = schedule_multi_stage_appointment(
                db,
                appointment_id=body.appointment_id,
                package_type=body.package_type,
                start_time_iso=body.start_time_iso,
                plate=body.plate or "",
                notes=body.notes or "",
            )
            return [row(s) for s in schedules]
        except ValueError as e:
            raise HTTPException(409, str(e))


@router.get("/api/bay-scheduler/bays", dependencies=[Depends(auth)])
def bay_list_endpoint():
    with db_module.Session() as db:
        bays = list_bays(db)
        return [row(b) for b in bays]


@router.get("/api/bay-scheduler/technicians", dependencies=[Depends(auth)])
def technician_list_endpoint():
    with db_module.Session() as db:
        techs = list_technicians(db)
        return [row(t) for t in techs]


@router.get("/api/bay-scheduler/schedules", dependencies=[Depends(auth)])
def bay_schedules_list_endpoint(date: str | None = None, limit: int = 100):
    with db_module.Session() as db:
        schedules = list_bay_schedules(db, date_str=date, limit=limit)
        return [row(s) for s in schedules]


@router.get("/api/bay-scheduler/analytics", dependencies=[Depends(auth)])
def bay_analytics_endpoint(date: str | None = None):
    with db_module.Session() as db:
        return get_bay_station_analytics(db, date_str=date)


@router.put("/api/bay-scheduler/bays/{bay_id}/status", dependencies=[Depends(auth)])
def bay_set_status_endpoint(bay_id: str, body: BayStatusIn):
    with db_module.Session() as db:
        try:
            updated = set_bay_status(db, bay_id, body.status)
            return row(updated)
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.put("/api/bay-scheduler/technicians/{technician_id}/status", dependencies=[Depends(auth)])
def technician_set_status_endpoint(technician_id: str, body: TechnicianStatusIn):
    with db_module.Session() as db:
        try:
            updated = set_technician_status(db, technician_id, body.is_active)
            return row(updated)
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.delete("/api/bay-scheduler/appointments/{appointment_id}", dependencies=[Depends(auth)])
def cancel_appointment_schedules_endpoint(appointment_id: str):
    with db_module.Session() as db:
        canceled_count = cancel_appointment_schedules(db, appointment_id=appointment_id)
        return {"appointment_id": appointment_id, "cancelled_schedules_count": canceled_count}
