"""Read models for the operator's conversation and analysis queue views."""

import json
import time

from sqlalchemy import and_, case, func, inspect, or_, select

from backend.config import settings
from backend.db import (
    Appointment, Conversation, FqiciRun, FqiciScope, OperatorTransfer, Slot, SupervisorTrace, Turn,
)
from backend.fqici.queue import PENDING


def fqici_store_ready(tables: set[str]) -> bool:
    return {FqiciScope.__tablename__, FqiciRun.__tablename__} <= tables


def run_summary(run: FqiciRun, now_ms: int) -> dict:
    return {
        "id": run.id,
        "state": run.state,
        "rule_version": run.rule_version,
        "created_at_ms": run.created_at_ms,
        "attempts": run.fence,
        "lease_expired": run.state == "RUNNING"
        and run.lease_until_ms is not None and run.lease_until_ms <= now_ms,
    }


def queue_view(db, limit: int) -> dict:
    tables = set(inspect(db.connection()).get_table_names())
    result = {
        "intake_enabled": settings.fqici_enabled,
        "worker_status": "NOT_CONNECTED",
        "store": "READY" if fqici_store_ready(tables) else "UNAVAILABLE",
        "counts": {},
        "deferred_count": None,
        "oldest_wait_ms": None,
        "runs": [],
        "deferred": [],
    }
    if result["store"] != "READY":
        return result
    now_ms = time.time_ns() // 1_000_000
    visible = Conversation.status != "purged"
    by_run = FqiciRun.__table__.join(FqiciScope.__table__, FqiciRun.scope_id == FqiciScope.id).join(
        Conversation.__table__, FqiciScope.id == Conversation.id,
    )
    by_scope = FqiciScope.__table__.join(Conversation.__table__, FqiciScope.id == Conversation.id)
    deferred = and_(visible, FqiciScope.ready_at_ms.is_not(None))
    result["counts"] = dict(db.execute(select(FqiciRun.state, func.count()).select_from(by_run).where(
        visible,
    ).group_by(FqiciRun.state)).all())
    result["deferred_count"], oldest_scope = db.execute(
        select(func.count(), func.min(FqiciScope.dirty_since_ms)).select_from(by_scope).where(deferred),
    ).one()
    oldest_run = db.scalar(select(func.min(FqiciRun.created_at_ms)).select_from(by_run).where(
        visible,
        or_(
            FqiciRun.state.in_(("QUEUED", "FAILED_RETRYABLE")),
            and_(FqiciRun.state == "RUNNING", FqiciRun.lease_until_ms <= now_ms),
        ),
    ))
    waiting = [value for value in (oldest_scope, oldest_run) if value is not None]
    result["oldest_wait_ms"] = max(0, now_ms - min(waiting)) if waiting else None
    result["runs"] = [
        {**run_summary(run, now_ms), "conversation_id": scope.id,
         "transport": scope.transport, "origin": scope.origin}
        for run, scope in db.execute(select(FqiciRun, FqiciScope).select_from(by_run).where(visible).order_by(
            case((FqiciRun.state.in_(PENDING), 0), else_=1),
            FqiciRun.created_at_ms.desc(), FqiciRun.id,
        ).limit(limit))
    ]
    result["deferred"] = [
        {"conversation_id": scope.id, "transport": scope.transport, "origin": scope.origin,
         "ready_at_ms": scope.ready_at_ms}
        for scope in db.scalars(select(FqiciScope).select_from(by_scope).where(deferred).order_by(
            FqiciScope.ready_at_ms, FqiciScope.id,
        ).limit(limit))
    ]
    return result


def conversation_view(db, conversation_id: str) -> dict | None:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        return None
    result = {
        "conversation": {"id": conversation.id, "channel": conversation.channel,
                         "status": conversation.status, "created_at": conversation.created_at},
        "turns": [], "traces": [], "transfers": [], "appointment": None,
        "fqici": {"store": "UNAVAILABLE", "scope": None, "runs": []},
    }
    if conversation.status == "purged":
        return result
    tables = set(inspect(db.connection()).get_table_names())
    result["turns"] = [dict(row) for row in db.execute(select(
        Turn.id, Turn.conversation_id, Turn.role, Turn.text, Turn.metrics, Turn.created_at,
    ).where(Turn.conversation_id == conversation_id).order_by(Turn.created_at, Turn.id)).mappings()]
    if SupervisorTrace.__tablename__ in tables:
        for trace in db.scalars(select(SupervisorTrace).where(
            SupervisorTrace.conversation_id == conversation_id,
        ).order_by(SupervisorTrace.created_at.desc(), SupervisorTrace.id).limit(50)):
            payload = json.loads(trace.payload)
            decision = payload["decision"]
            result["traces"].append({
                "id": trace.id, "created_at": trace.created_at, "review_status": trace.review_status,
                "route_state": decision["route_state"], "outcome": payload["outcome"],
                "intents": [item["intent_id"] for item in decision["candidates"]],
                "reason_codes": decision["reason_codes"],
            })
    if OperatorTransfer.__tablename__ in tables:
        result["transfers"] = [dict(row) for row in db.execute(select(
            OperatorTransfer.id, OperatorTransfer.status, OperatorTransfer.created_at,
            OperatorTransfer.completed_at,
        ).where(OperatorTransfer.conversation_id == conversation_id).order_by(
            OperatorTransfer.created_at.desc(), OperatorTransfer.id,
        ).limit(50)).mappings()]
    # The live booking flow uses the exact session ID as its booking idempotency key.
    booking = db.execute(select(Appointment.id, Appointment.status, Slot.starts_at).outerjoin(
        Slot, Appointment.slot_id == Slot.id,
    ).where(Appointment.idempotency_key == conversation_id)).mappings().one_or_none()
    if booking is not None:
        result["appointment"] = dict(booking)
    if fqici_store_ready(tables):
        result["fqici"]["store"] = "READY"
        scope = db.get(FqiciScope, conversation_id)
        if scope is not None:
            result["fqici"]["scope"] = {
                "transport": scope.transport, "origin": scope.origin, "terminal_seen": scope.terminal_seen,
                "ready_at_ms": scope.ready_at_ms,
            }
            now_ms = time.time_ns() // 1_000_000
            result["fqici"]["runs"] = [run_summary(run, now_ms) for run in db.scalars(
                select(FqiciRun).where(FqiciRun.scope_id == conversation_id).order_by(
                    FqiciRun.created_at_ms.desc(), FqiciRun.id,
                ).limit(50),
            )]
    return result
