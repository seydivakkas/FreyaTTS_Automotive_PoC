"""Genel kaynak listeleme (catch-all GET /api/{resource}); en son kaydedilmelidir."""

from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    Query,
)
from sqlalchemy import select
from backend.db import (
    Vehicle,
    Quote,
    Slot,
    Appointment,
    Conversation,
    CorporateAccount,
    CorporateLedger,
    InspectionReport,
    NotificationOutbox,
    OutboundCall,
    VehicleDiagnostic,
    InspectionLift,
    InspectionQueue,
    ABExperiment,
    ABAssignment,
    OperatorTransfer,
    VehicleValuation,
    InspectionBay,
    Technician,
    BaySchedule,
)
from backend import db as db_module
from backend.deps import (
    auth,
    row,
)

router = APIRouter()


@router.get("/api/{resource}", dependencies=[Depends(auth)])
def listing(resource: str, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
    table = {
        "vehicles": Vehicle,
        "quotes": Quote,
        "slots": Slot,
        "appointments": Appointment,
        "conversations": Conversation,
        "corporate-accounts": CorporateAccount,
        "corporate-ledger": CorporateLedger,
        "inspection-reports": InspectionReport,
        "notifications": NotificationOutbox,
        "outbound-calls": OutboundCall,
        "vehicle-diagnostics": VehicleDiagnostic,
        "inspection-lifts": InspectionLift,
        "inspection-queues": InspectionQueue,
        "ab-experiments": ABExperiment,
        "ab-assignments": ABAssignment,
        "operator-transfers": OperatorTransfer,
        "transfers": OperatorTransfer,
        "vehicle-valuations": VehicleValuation,
        "inspection-bays": InspectionBay,
        "technicians": Technician,
        "bay-schedules": BaySchedule,
    }.get(resource)
    if not table:
        raise HTTPException(404)
    with db_module.Session() as db:
        # Çıktı sırası sabit olsun diye birincil anahtara göre sayfalanır.
        stmt = select(table).order_by(table.id).limit(limit).offset(offset)
        return [row(x) for x in db.scalars(stmt).all()]
