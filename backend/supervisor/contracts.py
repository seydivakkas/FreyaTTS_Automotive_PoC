from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CATALOGUE_VERSION = "intent-v1"
POLICY_VERSION = "policy-v1"


class Intent(StrEnum):
    GREETING = "greeting"
    GOODBYE = "goodbye"
    REPEAT_REQUEST = "repeat_request"
    CLARIFICATION_REQUEST = "clarification_request"
    HUMAN_HANDOFF_REQUEST = "human_handoff_request"
    BOOKING_CREATE = "booking_create"
    BOOKING_RESCHEDULE = "booking_reschedule"
    BOOKING_CANCEL = "booking_cancel"
    BOOKING_STATUS = "booking_status"
    SERVICE_PRICE_ESTIMATE = "service_price_estimate"
    WARNING_LIGHT_QUESTION = "warning_light_question"
    SYMPTOM_QUESTION = "symptom_question"
    MAINTENANCE_SCHEDULE_QUESTION = "maintenance_schedule_question"
    VEHICLE_SPEC_QUESTION = "vehicle_spec_question"
    MODEL_COMPARISON = "model_comparison"
    VEHICLE_PRICE_QUOTE = "vehicle_price_quote"
    TEST_DRIVE_REQUEST = "test_drive_request"
    PART_COMPATIBILITY = "part_compatibility"
    PART_AVAILABILITY = "part_availability"
    CUSTOMER_RECORD_QUESTION = "customer_record_question"
    COMPLAINT_CREATE = "complaint_create"
    ROADSIDE_EMERGENCY = "roadside_emergency"


class RouteState(StrEnum):
    ROUTED = "ROUTED"
    UNKNOWN = "UNKNOWN"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IntentCandidate(Contract):
    intent_id: Intent
    score: float | None = Field(default=None, ge=0, le=1)
    evidence: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.:-]+$")


class IntentDecision(Contract):
    candidates: tuple[IntentCandidate, ...] = ()
    route_state: RouteState
    source: Literal["rule", "classifier", "hybrid", "llm", "none"]
    needs_clarification: bool = False
    reason_codes: tuple[str, ...] = ()

    @property
    def intent_ids(self) -> tuple[Intent, ...]:
        return tuple(candidate.intent_id for candidate in self.candidates)

    @property
    def scores(self) -> dict[Intent, float | None]:
        return {candidate.intent_id: candidate.score for candidate in self.candidates}

    @model_validator(mode="after")
    def validate_routing(self):
        if bool(self.candidates) != (self.route_state == RouteState.ROUTED):
            raise ValueError("ROUTED requires candidates; abstentions cannot contain candidates")
        if len(set(self.intent_ids)) != len(self.intent_ids):
            raise ValueError("duplicate intents")
        return self


class Slot(Contract):
    name: str = Field(min_length=1, max_length=64)
    value: str | int
    evidence: Literal["asr_final", "confirmed_context", "relative_date"]
    verified: bool = False

    @model_validator(mode="after")
    def verify_provenance(self):
        if self.verified and self.evidence != "confirmed_context":
            raise ValueError("verified slots require confirmed context")
        return self


class ConversationContext(Contract):
    session_id: UUID
    turn_at: datetime
    active_task: Intent | None = None
    last_confirmed_intents: tuple[Intent, ...] = ()
    verified_vehicle: tuple[Slot, ...] = ()
    pending_slots: tuple[Slot, ...] = ()

    @model_validator(mode="after")
    def validate_context(self):
        if self.turn_at.utcoffset() is None:
            raise ValueError("turn_at must include a timezone")
        vehicle_fields = {"vehicle_brand", "vehicle_model", "vehicle_year"}
        if any(not slot.verified or slot.name not in vehicle_fields for slot in self.verified_vehicle):
            raise ValueError("vehicle context requires verified vehicle fields")
        return self


class PlanStep(Contract):
    step_id: str
    agent: str
    action: str
    intent_id: Intent | None = None
    depends_on: tuple[str, ...] = ()
    writes: bool = False
    guardrails: tuple[str, ...] = ()


class ExecutionPlan(Contract):
    steps: tuple[PlanStep, ...]
    priority: Literal["normal", "handoff", "emergency"]
    requires_confirmation: bool
    guardrails: tuple[str, ...] = ()
    model_version: str
    policy_version: Literal["policy-v1"] = POLICY_VERSION
    catalogue_version: Literal["intent-v1"] = CATALOGUE_VERSION
    trace_id: UUID

    @model_validator(mode="after")
    def validate_order(self):
        seen = set()
        for step in self.steps:
            if step.step_id in seen or not set(step.depends_on) <= seen:
                raise ValueError("duplicate step or dependency outside earlier steps")
            if step.writes and not self.requires_confirmation:
                raise ValueError("write requires confirmation")
            seen.add(step.step_id)
        return self
