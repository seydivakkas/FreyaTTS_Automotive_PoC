"""Read-only operator work list from recorded follow-up and transfer states."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, literal, or_, select, union_all

from backend.config import settings
from backend.db import Conversation, OperatorTransfer

PENDING_TRANSFER = ("initiated", "whispering")
OPEN_FOLLOW_UP = ("callback", "booking_pending", "booking_unknown")
LEGACY_CALLBACK = "] Operatör aktarımı yapılamadı (AMI bağlı değil); müşteri geri aranacak."
ISTANBUL = ZoneInfo("Europe/Istanbul")


def today_view(db, *, now: datetime, period: str, category: str, limit: int, offset: int) -> dict:
    cutoff = now - timedelta(seconds=settings.operator_whisper_timeout_sec)
    within_deadline = func.julianday(OperatorTransfer.created_at) > func.julianday(cutoff.isoformat())
    if settings.demo_mode:
        within_deadline = or_(within_deadline, OperatorTransfer.id.startswith("demo_", autoescape=True))
    pending_transfer = and_(OperatorTransfer.status.in_(PENDING_TRANSFER), within_deadline)
    transfer_rows = select(
        OperatorTransfer.id.label("id"),
        OperatorTransfer.conversation_id.label("conversation_id"),
        literal("transfer").label("kind"),
        OperatorTransfer.status.label("status"),
        OperatorTransfer.created_at.label("since"),
        literal("transfer").label("since_source"),
    ).outerjoin(Conversation, OperatorTransfer.conversation_id == Conversation.id).where(
        pending_transfer,
        or_(OperatorTransfer.conversation_id.is_(None), Conversation.status.not_in(("purged", "resolved"))),
    )
    legacy_callback = Conversation.follow_up_kind.is_(None) & Conversation.operator_notes.contains(
        LEGACY_CALLBACK, autoescape=True,
    )
    follow_up_rows = select(
        Conversation.id.label("id"),
        Conversation.id.label("conversation_id"),
        case(
            (Conversation.follow_up_kind.in_(OPEN_FOLLOW_UP), Conversation.follow_up_kind),
            (legacy_callback, "callback"),
            else_="follow_up",
        ).label("kind"),
        Conversation.status.label("status"),
        func.coalesce(Conversation.follow_up_at, Conversation.created_at).label("since"),
        case((Conversation.follow_up_at.is_not(None), "follow_up"), else_="conversation").label("since_source"),
    ).where(
        Conversation.status == "follow_up",
        ~select(OperatorTransfer.id).where(
            OperatorTransfer.conversation_id == Conversation.id, pending_transfer,
        ).exists(),
    )
    items = union_all(transfer_rows, follow_up_rows).subquery()
    local_day = now.astimezone(ISTANBUL).date()
    start = datetime.combine(local_day, time.min, ISTANBUL)
    tomorrow = start + timedelta(days=1)
    since = func.julianday(items.c.since)
    bucket = case(
        (since < func.julianday(start.isoformat()), "carryover"),
        (since < func.julianday(tomorrow.isoformat()), "today"),
        else_="unknown",
    ).label("period")
    priority = case(
        (items.c.kind == "transfer", 0), (items.c.kind == "callback", 1),
        (items.c.kind == "booking_unknown", 2), (items.c.kind == "booking_pending", 3),
        else_=4,
    )
    counts = dict(db.execute(select(items.c.kind, func.count()).group_by(items.c.kind)).all())
    query = select(items, bucket)
    if period != "all":
        query = query.where(bucket == period)
    if category == "booking":
        query = query.where(items.c.kind.in_(("booking_pending", "booking_unknown")))
    elif category != "all":
        query = query.where(items.c.kind == category)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = []
    query = query.order_by(priority, since.asc().nulls_last(), items.c.id).limit(limit).offset(offset)
    for row in db.execute(query).mappings():
        item = dict(row)
        try:
            timestamp = datetime.fromisoformat(item["since"])
            if timestamp.utcoffset() is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            item["age_seconds"] = max(0, int((now - timestamp).total_seconds()))
        except (TypeError, ValueError):
            item["age_seconds"] = None
        rows.append(item)
    return {"local_date": local_day.isoformat(), "counts": counts, "total": total, "items": rows}
