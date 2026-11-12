import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Literal
from uuid import UUID

from sqlalchemy.orm import Session as DbSession

from backend.db import Session, SupervisorWriteReceipt
from backend.supervisor.catalogue import CATALOGUE
from backend.supervisor.contracts import ExecutionPlan, Intent

WRITE_ACTIONS = {
    Intent.BOOKING_CREATE: "create_booking",
    Intent.BOOKING_RESCHEDULE: "reschedule_booking",
    Intent.BOOKING_CANCEL: "cancel_booking",
    Intent.COMPLAINT_CREATE: "create_complaint",
}


def request_digest(action: str, fields: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(
        [action, fields], sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


@dataclass(frozen=True)
class ConfirmedWrite:
    """Issued only by a trusted identity/confirmation workflow, never by ASR or a ranker."""

    idempotency_key: UUID
    trace_id: UUID
    action: str
    request_digest: str
    verified_customer_id: str
    expires_at: datetime


@dataclass(frozen=True)
class WriteTool:
    # Both callbacks use the supplied transaction. No external side effects or commits.
    recheck: Callable[[DbSession, str, dict[str, str]], bool]
    apply: Callable[[DbSession, str, dict[str, str]], None]


WriteOutcome = Literal["applied", "duplicate", "denied", "unavailable", "state_changed", "timeout", "failed"]


class ToolGateway:
    def __init__(
        self, tools: dict[str, WriteTool] | None = None, session_factory=Session,
        timeout: float = 2.0, availability: Callable[[date, datetime], int] | None = None,
    ):
        self.tools = dict(tools or {})
        self.session_factory = session_factory
        self.timeout = timeout
        self.availability = availability

    async def read_availability(self, plan: ExecutionPlan, day: date, now: datetime) -> int:
        if self.availability is None or plan.priority == "emergency" or not any(
            step.intent_id == Intent.BOOKING_CREATE and step.agent == "ServiceBooking"
            and step.action == "clarify_date_and_check_availability"
            for step in plan.steps
        ):
            raise PermissionError("availability read not authorized")
        return await asyncio.wait_for(asyncio.to_thread(self.availability, day, now), self.timeout)

    async def execute_write(
        self, plan: ExecutionPlan, intent: Intent, fields: dict[str, str], grant: ConfirmedWrite | None,
    ) -> WriteOutcome:
        action = WRITE_ACTIONS.get(intent)
        if (
            not action or not plan.requires_confirmation or plan.priority != "normal"
            or not any(step.intent_id == intent and step.agent == CATALOGUE[intent].agent for step in plan.steps)
            or grant is None or grant.trace_id != plan.trace_id or grant.action != action
            or not grant.verified_customer_id or grant.expires_at.utcoffset() is None
            or grant.expires_at <= datetime.now(timezone.utc)
        ):
            return "denied"
        fields = dict(fields)
        required = set(CATALOGUE[intent].minimum_slots) - {"verified_customer"}
        if set(fields) != required or not all(isinstance(value, str) and value.strip() for value in fields.values()):
            return "denied"
        if grant.request_digest != request_digest(action, fields):
            return "denied"
        tool = self.tools.get(action)
        if tool is None:
            return "unavailable"
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._apply, tool, grant, fields), timeout=self.timeout,
            )
        except TimeoutError:
            # The same key can be reconciled/retried; a worker may already be committing.
            return "timeout"
        except Exception:
            return "failed"

    def _apply(self, tool: WriteTool, grant: ConfirmedWrite, fields: dict[str, str]) -> WriteOutcome:
        with self.session_factory.begin() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            key = str(grant.idempotency_key)
            digest = request_digest(grant.action, {**fields, "_verified_customer": grant.verified_customer_id})
            if receipt := db.get(SupervisorWriteReceipt, key):
                return "duplicate" if receipt.request_digest == digest else "denied"
            if grant.expires_at <= datetime.now(timezone.utc):
                return "denied"
            if not tool.recheck(db, grant.verified_customer_id, fields):
                return "state_changed"
            tool.apply(db, grant.verified_customer_id, fields)
            db.add(SupervisorWriteReceipt(key=key, action=grant.action, request_digest=digest))
        return "applied"
