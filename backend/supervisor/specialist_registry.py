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

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from backend.core.contracts.dialogue import (
    DialogueOutcome,
    DialogueResponse,
    ProviderMode,
    ToolReceipt,
    ToolReceiptStatus,
)
from backend.core.contracts.validation import freeze_value
from backend.supervisor.contracts import Intent
from backend.supervisor.response_validator import ResponseValidator

MAX_PROPOSAL_JSON_BYTES = 4096
MAX_PROPOSAL_FIELDS = 32

_FORBIDDEN_ARG_KEYS: frozenset[str] = frozenset({
    "sql",
    "query",
    "command",
    "shell",
    "eval",
    "exec",
    "admin",
    "bypass",
    "verified",
    "actor",
    "role",
    "provider_mode",
    "receipt",
    "confirmed",
})
_DANGEROUS_VALUE_RE = re.compile(
    r"(?i)(?:\b(?:select|insert|update|delete|drop|alter|union|exec|eval|__import__|subprocess)\b"
    r"|;\s*--|\bhttps?://|\bfile://)",
)


class CapabilityState(StrEnum):
    """Explicit specialist/tool capability state."""

    VERIFIED = "VERIFIED"
    DECLARED = "DECLARED"
    UNSUPPORTED = "UNSUPPORTED"
    DISABLED = "DISABLED"


class AgentResultStatus(StrEnum):
    """Typed specialist proposal status."""

    PROPOSED = "PROPOSED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    UNSUPPORTED = "UNSUPPORTED"
    BLOCKED = "BLOCKED"


class QualityVerdict(StrEnum):
    """Read-only QualityEvaluator verdict."""

    PASS = "PASS"
    BLOCK = "BLOCK"
    REPAIR_PROJECTION = "REPAIR_PROJECTION"


@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    """Immutable specialist capability declaration (never grants privileges)."""

    agent_id: str
    revision: str
    supported_intents: frozenset[Intent]
    allowed_tools: frozenset[str]
    capability_state: CapabilityState = CapabilityState.VERIFIED
    required_slots: Mapping[Intent, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))
    max_proposals: int = 4
    disabled_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.agent_id or not self.agent_id.strip():
            raise ValueError("agent_id must be non-empty")
        object.__setattr__(self, "required_slots", MappingProxyType(dict(self.required_slots)))


@dataclass(frozen=True, slots=True)
class AgentRequest:
    """Narrow immutable request passed to a specialist (no DB handles, credentials, or URLs)."""

    request_id: str
    session_id: str
    turn_id: int
    intent: Intent
    input_ref: str
    state_revision: int
    slots: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    utterance_text: str = ""
    permitted_tools: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "slots", freeze_value(dict(self.slots)))


@dataclass(frozen=True, slots=True)
class ToolProposal:
    """Strictly untrusted specialist tool proposal; has_authority is always False."""

    proposal_id: str
    tool_id: str
    schema_revision: str
    action: str
    arguments: Mapping[str, Any]
    source_input_ref: str
    state_revision: int
    has_authority: bool = False

    def __post_init__(self) -> None:
        if self.has_authority:
            raise ValueError("ToolProposal can never hold authority")
        if len(self.arguments) > MAX_PROPOSAL_FIELDS:
            raise ValueError("ToolProposal arguments exceed max field count")
        for k, v in self.arguments.items():
            if str(k).lower() in _FORBIDDEN_ARG_KEYS:
                raise ValueError(f"Forbidden argument key in ToolProposal: {k}")
            if isinstance(v, str) and _DANGEROUS_VALUE_RE.search(v):
                raise ValueError(f"Unsafe argument value in ToolProposal for key: {k}")
        encoded = json.dumps(dict(self.arguments), ensure_ascii=False, default=str).encode("utf-8")
        if len(encoded) > MAX_PROPOSAL_JSON_BYTES:
            raise ValueError("ToolProposal exceeds 4 KiB JSON limit")
        object.__setattr__(self, "arguments", freeze_value(dict(self.arguments)))


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Typed untrusted output of a specialist; cannot directly mutate context or commit."""

    request_id: str
    agent_id: str
    status: AgentResultStatus
    proposals: tuple[ToolProposal, ...] = ()
    slot_deltas: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    needed_facts: tuple[str, ...] = ()
    safe_response_intent: str = ""
    has_authority: bool = False

    def __post_init__(self) -> None:
        if self.has_authority:
            raise ValueError("AgentResult can never hold authority")
        object.__setattr__(self, "slot_deltas", freeze_value(dict(self.slot_deltas)))


@dataclass(frozen=True, slots=True)
class QualityDecision:
    """Read-only QualityEvaluator decision; never executes tools or alters receipts."""

    verdict: QualityVerdict
    reason_codes: tuple[str, ...]
    response: DialogueResponse
    has_tool_authority: bool = False

    def __post_init__(self) -> None:
        if self.has_tool_authority:
            raise ValueError("QualityDecision cannot hold tool authority")


SpecialistHandler = Callable[[AgentRequest, AgentDescriptor], AgentResult]


def _service_booking_handler(req: AgentRequest, desc: AgentDescriptor) -> AgentResult:
    if req.intent == Intent.BOOKING_CREATE:
        if "selected_slot_id" in req.slots and "preferred_date" in req.slots:
            prop = ToolProposal(
                proposal_id=f"prop-{req.request_id}-create",
                tool_id="booking.create",
                schema_revision="f3b-v1",
                action="create_booking",
                arguments={
                    "preferred_date": str(req.slots["preferred_date"]),
                    "selected_slot_id": str(req.slots["selected_slot_id"]),
                },
                source_input_ref=req.input_ref,
                state_revision=req.state_revision,
            )
            return AgentResult(req.request_id, desc.agent_id, AgentResultStatus.PROPOSED, proposals=(prop,))
        if "preferred_date" in req.slots:
            prop = ToolProposal(
                proposal_id=f"prop-{req.request_id}-avail",
                tool_id="availability.read",
                schema_revision="f3b-v1",
                action="check_availability",
                arguments={"preferred_date": str(req.slots["preferred_date"])},
                source_input_ref=req.input_ref,
                state_revision=req.state_revision,
            )
            return AgentResult(req.request_id, desc.agent_id, AgentResultStatus.PROPOSED, proposals=(prop,))
        return AgentResult(
            req.request_id,
            desc.agent_id,
            AgentResultStatus.NEEDS_CLARIFICATION,
            needed_facts=("preferred_date",),
            safe_response_intent="ASK_PREFERRED_DATE",
        )

    if req.intent == Intent.BOOKING_RESCHEDULE:
        if "booking_id" in req.slots and "selected_slot_id" in req.slots:
            prop = ToolProposal(
                proposal_id=f"prop-{req.request_id}-resched",
                tool_id="booking.reschedule",
                schema_revision="f3b-v1",
                action="reschedule_booking",
                arguments={
                    "booking_id": str(req.slots["booking_id"]),
                    "selected_slot_id": str(req.slots["selected_slot_id"]),
                },
                source_input_ref=req.input_ref,
                state_revision=req.state_revision,
            )
            return AgentResult(req.request_id, desc.agent_id, AgentResultStatus.PROPOSED, proposals=(prop,))
        missing = tuple(s for s in ("booking_id", "selected_slot_id") if s not in req.slots)
        return AgentResult(
            req.request_id,
            desc.agent_id,
            AgentResultStatus.NEEDS_CLARIFICATION,
            needed_facts=missing,
            safe_response_intent="ASK_RESCHEDULE_SLOTS",
        )

    if req.intent == Intent.BOOKING_CANCEL:
        if "booking_id" in req.slots:
            prop = ToolProposal(
                proposal_id=f"prop-{req.request_id}-cancel",
                tool_id="booking.cancel",
                schema_revision="f3b-v1",
                action="cancel_booking",
                arguments={"booking_id": str(req.slots["booking_id"])},
                source_input_ref=req.input_ref,
                state_revision=req.state_revision,
            )
            return AgentResult(req.request_id, desc.agent_id, AgentResultStatus.PROPOSED, proposals=(prop,))
        return AgentResult(
            req.request_id,
            desc.agent_id,
            AgentResultStatus.NEEDS_CLARIFICATION,
            needed_facts=("booking_id",),
            safe_response_intent="ASK_BOOKING_ID",
        )

    if req.intent == Intent.BOOKING_STATUS:
        args = {"booking_id": str(req.slots["booking_id"])} if "booking_id" in req.slots else {}
        prop = ToolProposal(
            proposal_id=f"prop-{req.request_id}-status",
            tool_id="booking.read_status",
            schema_revision="f3b-v1",
            action="read_booking_status",
            arguments=args,
            source_input_ref=req.input_ref,
            state_revision=req.state_revision,
        )
        return AgentResult(req.request_id, desc.agent_id, AgentResultStatus.PROPOSED, proposals=(prop,))

    # SERVICE_PRICE_ESTIMATE
    if "service_type" not in req.slots:
        return AgentResult(
            req.request_id,
            desc.agent_id,
            AgentResultStatus.NEEDS_CLARIFICATION,
            needed_facts=("service_type",),
            safe_response_intent="ASK_SERVICE_TYPE",
        )
    prop = ToolProposal(
        proposal_id=f"prop-{req.request_id}-quote",
        tool_id="vehicle.read_specs",
        schema_revision="f3b-v1",
        action="read_service_estimate",
        arguments={"service_type": str(req.slots["service_type"])},
        source_input_ref=req.input_ref,
        state_revision=req.state_revision,
    )
    return AgentResult(req.request_id, desc.agent_id, AgentResultStatus.PROPOSED, proposals=(prop,))


def _technical_knowledge_handler(req: AgentRequest, desc: AgentDescriptor) -> AgentResult:
    args: dict[str, Any] = {}
    if "vehicle_model" in req.slots:
        args["vehicle_model"] = str(req.slots["vehicle_model"])
    if req.intent in {Intent.WARNING_LIGHT_QUESTION, Intent.SYMPTOM_QUESTION}:
        args["safety_caution"] = "true"
    prop = ToolProposal(
        proposal_id=f"prop-{req.request_id}-tech",
        tool_id="approved_technical_lookup",
        schema_revision="f3c-v1",
        action="technical_lookup",
        arguments=args,
        source_input_ref=req.input_ref,
        state_revision=req.state_revision,
    )
    return AgentResult(
        req.request_id,
        desc.agent_id,
        AgentResultStatus.PROPOSED,
        proposals=(prop,),
        safe_response_intent="TECHNICAL_GROUNDED_LOOKUP",
    )


def _sales_parts_handler(req: AgentRequest, desc: AgentDescriptor) -> AgentResult:
    if req.intent in {Intent.PART_COMPATIBILITY, Intent.PART_AVAILABILITY}:
        if "part" not in req.slots:
            return AgentResult(
                req.request_id,
                desc.agent_id,
                AgentResultStatus.NEEDS_CLARIFICATION,
                needed_facts=("part",),
                safe_response_intent="ASK_PART_NAME",
            )
        return AgentResult(
            req.request_id,
            desc.agent_id,
            AgentResultStatus.UNSUPPORTED,
            safe_response_intent="PARTS_CATALOG_UNSUPPORTED",
        )
    if "vehicle_model" not in req.slots and req.intent != Intent.MODEL_COMPARISON:
        return AgentResult(
            req.request_id,
            desc.agent_id,
            AgentResultStatus.NEEDS_CLARIFICATION,
            needed_facts=("vehicle_model",),
            safe_response_intent="ASK_VEHICLE_MODEL",
        )
    args = {"vehicle_model": str(req.slots["vehicle_model"])} if "vehicle_model" in req.slots else {}
    prop = ToolProposal(
        proposal_id=f"prop-{req.request_id}-sales",
        tool_id="vehicle.read_specs",
        schema_revision="f3b-v1",
        action="read_vehicle_specs",
        arguments=args,
        source_input_ref=req.input_ref,
        state_revision=req.state_revision,
    )
    return AgentResult(req.request_id, desc.agent_id, AgentResultStatus.PROPOSED, proposals=(prop,))


def _customer_crm_handler(req: AgentRequest, desc: AgentDescriptor) -> AgentResult:
    if req.intent == Intent.COMPLAINT_CREATE:
        if "complaint_text" not in req.slots:
            return AgentResult(
                req.request_id,
                desc.agent_id,
                AgentResultStatus.NEEDS_CLARIFICATION,
                needed_facts=("complaint_text",),
                safe_response_intent="ASK_COMPLAINT_DETAILS",
            )
        prop = ToolProposal(
            proposal_id=f"prop-{req.request_id}-cmp",
            tool_id="complaint.create",
            schema_revision="f3b-v1",
            action="create_complaint",
            arguments={"complaint_text": str(req.slots["complaint_text"])[:512]},
            source_input_ref=req.input_ref,
            state_revision=req.state_revision,
        )
        return AgentResult(req.request_id, desc.agent_id, AgentResultStatus.PROPOSED, proposals=(prop,))

    prop = ToolProposal(
        proposal_id=f"prop-{req.request_id}-crm",
        tool_id="customer.read_record",
        schema_revision="f3b-v1",
        action="read_customer_record",
        arguments={},
        source_input_ref=req.input_ref,
        state_revision=req.state_revision,
    )
    return AgentResult(req.request_id, desc.agent_id, AgentResultStatus.PROPOSED, proposals=(prop,))


def _workshop_operations_handler(req: AgentRequest, desc: AgentDescriptor) -> AgentResult:
    # Workshop read-only capability; mutations remain unsupported until separate owner approval.
    return AgentResult(
        req.request_id,
        desc.agent_id,
        AgentResultStatus.UNSUPPORTED,
        safe_response_intent="WORKSHOP_READ_ONLY_UNSUPPORTED",
    )


def _human_handoff_handler(req: AgentRequest, desc: AgentDescriptor) -> AgentResult:
    if req.intent == Intent.ROADSIDE_EMERGENCY:
        return AgentResult(
            req.request_id,
            desc.agent_id,
            AgentResultStatus.PROPOSED,
            proposals=(),
            safe_response_intent="URGENT_SAFETY_ESCALATION",
        )
    prop = ToolProposal(
        proposal_id=f"prop-{req.request_id}-xfer",
        tool_id="operator.transfer_request",
        schema_revision="f3b-v1",
        action="request_handoff",
        arguments={"reason": "customer_requested"},
        source_input_ref=req.input_ref,
        state_revision=req.state_revision,
    )
    return AgentResult(req.request_id, desc.agent_id, AgentResultStatus.PROPOSED, proposals=(prop,))


class SpecialistRegistry:
    """
    Single F3-B/C specialist registry.

    Rejects unknown/duplicate agent IDs, blocks dispatch to disabled/unsupported
    descriptors, and enforces untrusted proposal boundaries.
    """

    def __init__(self, *, register_defaults: bool = True) -> None:
        self._descriptors: dict[str, AgentDescriptor] = {}
        self._handlers: dict[str, SpecialistHandler] = {}
        if register_defaults:
            self._register_default_specialists()

    def _register_default_specialists(self) -> None:
        defaults: tuple[tuple[AgentDescriptor, SpecialistHandler], ...] = (
            (
                AgentDescriptor(
                    agent_id="ServiceBooking",
                    revision="1.0",
                    supported_intents=frozenset({
                        Intent.BOOKING_CREATE,
                        Intent.BOOKING_RESCHEDULE,
                        Intent.BOOKING_CANCEL,
                        Intent.BOOKING_STATUS,
                        Intent.SERVICE_PRICE_ESTIMATE,
                    }),
                    allowed_tools=frozenset({
                        "availability.read",
                        "booking.read_status",
                        "booking.create",
                        "booking.reschedule",
                        "booking.cancel",
                        "vehicle.read_specs",
                    }),
                ),
                _service_booking_handler,
            ),
            (
                AgentDescriptor(
                    agent_id="TechnicalKnowledge",
                    revision="1.0",
                    supported_intents=frozenset({
                        Intent.WARNING_LIGHT_QUESTION,
                        Intent.SYMPTOM_QUESTION,
                        Intent.MAINTENANCE_SCHEDULE_QUESTION,
                        Intent.VEHICLE_SPEC_QUESTION,
                    }),
                    allowed_tools=frozenset({"approved_technical_lookup", "vehicle.read_specs"}),
                ),
                _technical_knowledge_handler,
            ),
            (
                AgentDescriptor(
                    agent_id="SalesParts",
                    revision="1.0",
                    supported_intents=frozenset({
                        Intent.MODEL_COMPARISON,
                        Intent.VEHICLE_PRICE_QUOTE,
                        Intent.TEST_DRIVE_REQUEST,
                        Intent.PART_COMPATIBILITY,
                        Intent.PART_AVAILABILITY,
                    }),
                    allowed_tools=frozenset({"vehicle.read_specs"}),
                ),
                _sales_parts_handler,
            ),
            (
                AgentDescriptor(
                    agent_id="CustomerCRM",
                    revision="1.0",
                    supported_intents=frozenset({
                        Intent.CUSTOMER_RECORD_QUESTION,
                        Intent.COMPLAINT_CREATE,
                    }),
                    allowed_tools=frozenset({"customer.read_record", "complaint.create"}),
                ),
                _customer_crm_handler,
            ),
            (
                AgentDescriptor(
                    agent_id="WorkshopOperations",
                    revision="1.0",
                    supported_intents=frozenset(),
                    allowed_tools=frozenset(),
                    capability_state=CapabilityState.UNSUPPORTED,
                    disabled_reason="Workshop write/capacity adapters deferred pending owner approval",
                ),
                _workshop_operations_handler,
            ),
            (
                AgentDescriptor(
                    agent_id="HumanHandoff",
                    revision="1.0",
                    supported_intents=frozenset({
                        Intent.HUMAN_HANDOFF_REQUEST,
                        Intent.ROADSIDE_EMERGENCY,
                    }),
                    allowed_tools=frozenset({"operator.transfer_request"}),
                ),
                _human_handoff_handler,
            ),
        )
        for desc, handler in defaults:
            self.register(desc, handler)

    def register(self, descriptor: AgentDescriptor, handler: SpecialistHandler) -> None:
        if descriptor.agent_id in self._descriptors:
            raise ValueError(f"Duplicate specialist agent_id: {descriptor.agent_id}")
        self._descriptors[descriptor.agent_id] = descriptor
        self._handlers[descriptor.agent_id] = handler

    def get_descriptor(self, agent_id: str) -> AgentDescriptor:
        if agent_id not in self._descriptors:
            raise KeyError(f"Unknown specialist agent_id: {agent_id}")
        return self._descriptors[agent_id]

    def resolve_for_intent(self, intent: Intent) -> AgentDescriptor | None:
        for desc in self._descriptors.values():
            if intent in desc.supported_intents:
                return desc
        return None

    def list_descriptors(self) -> tuple[AgentDescriptor, ...]:
        return tuple(self._descriptors.values())

    def dispatch(self, agent_id: str, request: AgentRequest) -> AgentResult:
        """Dispatch a narrow AgentRequest to a registered specialist (proposals only)."""
        if agent_id not in self._descriptors:
            raise KeyError(f"Unknown specialist agent_id: {agent_id}")
        desc = self._descriptors[agent_id]
        if desc.capability_state in {CapabilityState.DISABLED, CapabilityState.UNSUPPORTED}:
            return AgentResult(
                request_id=request.request_id,
                agent_id=agent_id,
                status=AgentResultStatus.UNSUPPORTED,
                safe_response_intent=desc.disabled_reason or "CAPABILITY_UNSUPPORTED",
            )
        if request.intent not in desc.supported_intents:
            return AgentResult(
                request_id=request.request_id,
                agent_id=agent_id,
                status=AgentResultStatus.BLOCKED,
                safe_response_intent="INTENT_NOT_SUPPORTED_BY_AGENT",
            )
        result = self._handlers[agent_id](request, desc)
        # Enforce proposal allowlist at registry boundary.
        for prop in result.proposals:
            if prop.tool_id not in desc.allowed_tools:
                return AgentResult(
                    request_id=request.request_id,
                    agent_id=agent_id,
                    status=AgentResultStatus.BLOCKED,
                    safe_response_intent="TOOL_NOT_IN_AGENT_ALLOWLIST",
                )
        return result


class QualityEvaluator:
    """
    Deterministic read-only F3-B/C quality gate.

    Validates receipt/provider consistency, grounded facts, and display/speech coherence.
    Never executes tools, grants approvals, or invokes an LLM.
    """

    def __init__(self, *, validator: ResponseValidator | None = None) -> None:
        self._validator = validator or ResponseValidator()

    def evaluate(
        self,
        response: DialogueResponse,
        *,
        receipts: Iterable[ToolReceipt] = (),
        authorized_numbers: Iterable[str] = (),
        authorized_dates: Iterable[str] = (),
        authorized_booking_refs: Iterable[str] = (),
    ) -> QualityDecision:
        receipt_list = tuple(receipts)
        val = self._validator.validate(
            response,
            receipts=receipt_list,
            authorized_numbers=authorized_numbers,
            authorized_dates=authorized_dates,
            authorized_booking_refs=authorized_booking_refs,
        )
        reasons = list(val.violations)

        # Extra check: PENDING or UNKNOWN receipt cannot be paired with CONFIRMATION_COMMITTED speech_act.
        if response.speech_act == "CONFIRMATION_COMMITTED":
            has_real = any(
                r.status == ToolReceiptStatus.COMMITTED
                and r.provider_mode == ProviderMode.REAL
                and r.verified_result
                for r in receipt_list
            )
            if not has_real:
                reasons.append("quality.commit_speech_act_without_real_receipt")

        if not reasons:
            return QualityDecision(
                verdict=QualityVerdict.PASS,
                reason_codes=(),
                response=val.response,
            )

        if val.replaced:
            return QualityDecision(
                verdict=QualityVerdict.REPAIR_PROJECTION,
                reason_codes=tuple(dict.fromkeys(reasons)),
                response=val.response,
            )

        return QualityDecision(
            verdict=QualityVerdict.BLOCK,
            reason_codes=tuple(dict.fromkeys(reasons)),
            response=val.response,
        )
