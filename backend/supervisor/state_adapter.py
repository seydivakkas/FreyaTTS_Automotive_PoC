"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from backend.core.contracts.dialogue import ToolReceiptStatus
from backend.supervisor.catalogue import CATALOGUE
from backend.supervisor.context_manager import DialogueContextSnapshot, ProtectedRefs
from backend.supervisor.contracts import Intent, RouteState
from backend.supervisor.orchestrator import RoutingResult
from backend.supervisor.slot_manager import SlotStatus, SlotValue


class WorkflowStage(StrEnum):
    """Conceptual dialogue workflow traceability stages (wraps legacy state machine)."""

    WAITING_INPUT = "WAITING_INPUT"
    COLLECTING_SLOTS = "COLLECTING_SLOTS"
    CHECKING_PRECONDITIONS = "CHECKING_PRECONDITIONS"
    PRESENTING_OPTIONS = "PRESENTING_OPTIONS"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    EXECUTION_PENDING = "EXECUTION_PENDING"
    VERIFYING_RECEIPT = "VERIFYING_RECEIPT"
    COMPLETE = "COMPLETE"
    SAFE_RECOVERY = "SAFE_RECOVERY"


_INTENT_TO_TOOL_ID: Mapping[Intent, str] = MappingProxyType({
    Intent.BOOKING_CREATE: "booking.create",
    Intent.BOOKING_RESCHEDULE: "booking.reschedule",
    Intent.BOOKING_CANCEL: "booking.cancel",
    Intent.BOOKING_STATUS: "booking.read_status",
    Intent.CUSTOMER_RECORD_QUESTION: "customer.read_record",
    Intent.COMPLAINT_CREATE: "complaint.create",
    Intent.VEHICLE_SPEC_QUESTION: "vehicle.read_specs",
    Intent.SERVICE_PRICE_ESTIMATE: "vehicle.read_specs",
    Intent.MAINTENANCE_SCHEDULE_QUESTION: "vehicle.read_specs",
    Intent.MODEL_COMPARISON: "vehicle.read_specs",
    Intent.VEHICLE_PRICE_QUOTE: "vehicle.read_specs",
})

_NO_TOOL_INTENTS: frozenset[Intent] = frozenset({
    Intent.GREETING,
    Intent.GOODBYE,
    Intent.REPEAT_REQUEST,
    Intent.CLARIFICATION_REQUEST,
})

_REQUIRED_DIALOGUE_SLOTS: Mapping[Intent, tuple[str, ...]] = MappingProxyType({
    Intent.BOOKING_CREATE: ("preferred_date", "selected_slot_id"),
    Intent.BOOKING_RESCHEDULE: ("booking_id", "selected_slot_id"),
    Intent.BOOKING_CANCEL: ("booking_id",),
    Intent.BOOKING_STATUS: ("booking_id",),
    Intent.COMPLAINT_CREATE: ("complaint_text",),
    Intent.SERVICE_PRICE_ESTIMATE: ("service_type",),
    Intent.VEHICLE_SPEC_QUESTION: ("vehicle_model",),
    Intent.MAINTENANCE_SCHEDULE_QUESTION: ("vehicle_model",),
    Intent.PART_COMPATIBILITY: ("part", "vehicle_model"),
    Intent.PART_AVAILABILITY: ("part",),
    Intent.TEST_DRIVE_REQUEST: ("vehicle_model",),
})


@dataclass(frozen=True, slots=True)
class DialogueDecision:
    """
    Structured routing & workflow decision; carries ZERO authority on its own.

    Protected reads and writes remain blocked until M07 PolicyEngine + ConfirmationManager
    verify trusted context and active challenge.
    """

    intent: Intent | None
    route_state: RouteState
    workflow_stage: WorkflowStage
    required_slots: tuple[str, ...]
    missing_slots: tuple[str, ...]
    proposed_tool: str | None
    proposed_action: str | None
    no_tool_response: bool
    needs_clarification: bool
    reason_codes: tuple[str, ...]
    has_authority: bool = False

    def __post_init__(self) -> None:
        if self.has_authority:
            raise ValueError("DialogueDecision cannot embed execution authority")


def _slot_is_populated(slot: SlotValue | None) -> bool:
    return (
        slot is not None
        and slot.value is not None
        and slot.status not in {SlotStatus.EMPTY, SlotStatus.REJECTED}
    )


class StateAdapter:
    """Bridges existing SupervisorOrchestrator / BookingStatus transitions to F3-A stages."""

    def resolve_stage(
        self,
        *,
        intent: Intent | None,
        slots: Mapping[str, SlotValue],
        protected_refs: ProtectedRefs,
        missing_slots: tuple[str, ...] = (),
        has_options: bool = False,
        receipt_status: ToolReceiptStatus | None = None,
        correction_detected: bool = False,
        needs_clarification: bool = False,
    ) -> WorkflowStage:
        if intent == Intent.ROADSIDE_EMERGENCY:
            return WorkflowStage.SAFE_RECOVERY
        if correction_detected:
            return WorkflowStage.COLLECTING_SLOTS if missing_slots else WorkflowStage.SAFE_RECOVERY
        if receipt_status == ToolReceiptStatus.COMMITTED:
            return WorkflowStage.COMPLETE
        if receipt_status in {ToolReceiptStatus.PENDING, ToolReceiptStatus.UNKNOWN}:
            return WorkflowStage.VERIFYING_RECEIPT
        if receipt_status in {ToolReceiptStatus.FAILED, ToolReceiptStatus.BLOCKED}:
            return WorkflowStage.SAFE_RECOVERY
        if protected_refs.pending_challenge_id is not None:
            return WorkflowStage.AWAITING_CONFIRMATION
        if has_options:
            return WorkflowStage.PRESENTING_OPTIONS
        if intent in _NO_TOOL_INTENTS:
            return WorkflowStage.COMPLETE
        if missing_slots or needs_clarification:
            return WorkflowStage.COLLECTING_SLOTS
        if intent is not None and CATALOGUE[intent].critical_write:
            return WorkflowStage.CHECKING_PRECONDITIONS
        if intent is not None:
            return WorkflowStage.CHECKING_PRECONDITIONS
        return WorkflowStage.WAITING_INPUT

    def decide(
        self,
        routing_result: RoutingResult,
        snapshot: DialogueContextSnapshot,
        *,
        has_options: bool = False,
        is_confirmation_affirmative: bool = False,
        is_confirmation_negative: bool = False,
    ) -> DialogueDecision:
        """Compute deterministic WorkflowStage and required/missing slots from RoutingResult + snapshot."""
        reasons = list(routing_result.decision.reason_codes)
        correction = "dialogue.customer_correction" in reasons
        negated_write = "policy.negated_write" in reasons

        primary_intent = routing_result.decision.intent_ids[0] if routing_result.decision.intent_ids else None
        if primary_intent is None and snapshot.active_workflow is not None:
            try:
                candidate = Intent(snapshot.active_workflow)
            except ValueError:
                candidate = None
            if candidate is not None and (
                snapshot.protected_refs.pending_challenge_id is not None
                or is_confirmation_affirmative
                or is_confirmation_negative
                or has_options
            ):
                primary_intent = candidate

        if is_confirmation_negative or negated_write:
            return DialogueDecision(
                intent=primary_intent,
                route_state=routing_result.decision.route_state,
                workflow_stage=WorkflowStage.SAFE_RECOVERY,
                required_slots=(),
                missing_slots=(),
                proposed_tool=None,
                proposed_action="revoke_pending_confirmation",
                no_tool_response=True,
                needs_clarification=False,
                reason_codes=tuple(dict.fromkeys([*reasons, "dialogue.confirmation_declined"])),
                has_authority=False,
            )

        if primary_intent == Intent.ROADSIDE_EMERGENCY:
            return DialogueDecision(
                intent=primary_intent,
                route_state=RouteState.ROUTED,
                workflow_stage=WorkflowStage.SAFE_RECOVERY,
                required_slots=(),
                missing_slots=(),
                proposed_tool=None,
                proposed_action="urgent_safety_message",
                no_tool_response=True,
                needs_clarification=False,
                reason_codes=tuple(reasons),
                has_authority=False,
            )

        if primary_intent == Intent.HUMAN_HANDOFF_REQUEST:
            return DialogueDecision(
                intent=primary_intent,
                route_state=RouteState.ROUTED,
                workflow_stage=WorkflowStage.EXECUTION_PENDING,
                required_slots=(),
                missing_slots=(),
                proposed_tool="operator.transfer_request",
                proposed_action="request_handoff",
                no_tool_response=False,
                needs_clarification=False,
                reason_codes=tuple(reasons),
                has_authority=False,
            )

        if primary_intent in _NO_TOOL_INTENTS:
            return DialogueDecision(
                intent=primary_intent,
                route_state=RouteState.ROUTED,
                workflow_stage=WorkflowStage.COMPLETE,
                required_slots=(),
                missing_slots=(),
                proposed_tool=None,
                proposed_action=primary_intent.value,
                no_tool_response=True,
                needs_clarification=False,
                reason_codes=tuple(reasons),
                has_authority=False,
            )

        # Late correction after an already committed booking must not mutate original booking.
        if (
            correction
            and snapshot.protected_refs.active_booking_ref is not None
            and primary_intent in {Intent.BOOKING_CREATE, None}
        ):
            reasons.append("dialogue.post_commit_distinct_request")

        req_slots = _REQUIRED_DIALOGUE_SLOTS.get(primary_intent, ()) if primary_intent is not None else ()
        missing = tuple(k for k in req_slots if not _slot_is_populated(snapshot.slots.get(k)))

        proposed_tool = _INTENT_TO_TOOL_ID.get(primary_intent) if primary_intent is not None else None
        proposed_action = routing_result.plan.steps[0].action if routing_result.plan.steps else None
        if snapshot.protected_refs.pending_challenge_id is not None and primary_intent is not None:
            _action_map = {
                Intent.BOOKING_CREATE: "create_booking",
                Intent.BOOKING_RESCHEDULE: "reschedule_booking",
                Intent.BOOKING_CANCEL: "cancel_booking",
                Intent.COMPLAINT_CREATE: "create_complaint",
            }
            proposed_action = _action_map.get(primary_intent, proposed_action)

        # Availability check is read-only when date is present but slot is not yet chosen.
        if primary_intent == Intent.BOOKING_CREATE and "selected_slot_id" in missing and "preferred_date" not in missing:
            proposed_tool = "availability.read"
            proposed_action = "clarify_date_and_check_availability"

        no_tool = (
            proposed_tool is None
            or routing_result.decision.route_state == RouteState.OUT_OF_SCOPE
            or (
                primary_intent is not None
                and CATALOGUE[primary_intent].critical_write
                and bool(missing)
                and proposed_tool != "availability.read"
            )
        )

        stage = self.resolve_stage(
            intent=primary_intent,
            slots=snapshot.slots,
            protected_refs=snapshot.protected_refs,
            missing_slots=missing,
            has_options=has_options,
            correction_detected=correction,
            needs_clarification=routing_result.decision.needs_clarification,
        )

        return DialogueDecision(
            intent=primary_intent,
            route_state=routing_result.decision.route_state,
            workflow_stage=stage,
            required_slots=req_slots,
            missing_slots=missing,
            proposed_tool=None if no_tool else proposed_tool,
            proposed_action=proposed_action,
            no_tool_response=no_tool,
            needs_clarification=bool(missing) or routing_result.decision.needs_clarification,
            reason_codes=tuple(dict.fromkeys(reasons)),
            has_authority=False,
        )
