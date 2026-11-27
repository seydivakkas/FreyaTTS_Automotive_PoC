"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from backend.core.contracts.common import ErrorInfo, EventEnvelope
from backend.core.contracts.validation import freeze_value, require_safe_id, require_strict_int, require_utc_iso


class ToolReceiptStatus(StrEnum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


class ProviderMode(StrEnum):
    MOCK = "MOCK"
    REAL = "REAL"
    UNKNOWN = "UNKNOWN"


class DialogueOutcome(StrEnum):
    OK = "OK"
    NO_RESPONSE = "NO_RESPONSE"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    IDENTITY_REQUIRED = "IDENTITY_REQUIRED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class VerifiedFactRef:
    provenance: str
    reference_id: str
    status: str
    revision: str | int

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError("provenance required")
        require_safe_id(self.reference_id, "reference_id")
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("status required")


@dataclass(frozen=True, slots=True)
class ConfirmationReference:
    state_revision: int
    operation_digest: str
    confirmation_source_id: str
    expires_at_utc: str | None = None
    actor_ref: str | None = None

    def __post_init__(self) -> None:
        require_strict_int(self.state_revision, "state_revision", minimum=0)
        if not isinstance(self.operation_digest, str) or len(self.operation_digest) < 16:
            raise ValueError("operation_digest required")
        require_safe_id(self.confirmation_source_id, "confirmation_source_id")
        if self.expires_at_utc is not None:
            require_utc_iso(self.expires_at_utc, "expires_at_utc")


@dataclass(frozen=True, slots=True)
class ToolReceipt:
    operation_id: str
    tool_id: str
    status: ToolReceiptStatus
    provider_mode: ProviderMode = ProviderMode.UNKNOWN
    idempotency_key: str | None = None
    evidence_ref: str | None = None
    verified_result: bool = False
    error: ErrorInfo | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.operation_id, "operation_id")
        require_safe_id(self.tool_id, "tool_id")
        if not isinstance(self.status, ToolReceiptStatus):
            raise ValueError("status must be ToolReceiptStatus")
        if not isinstance(self.provider_mode, ProviderMode):
            raise ValueError("provider_mode must be ProviderMode")
        if self.verified_result and self.status != ToolReceiptStatus.COMMITTED:
            raise ValueError("verified_result=True requires status=COMMITTED")
        if self.provider_mode == ProviderMode.MOCK and self.verified_result:
            raise ValueError("MOCK provider cannot yield verified_result=True for real business commit")

    @property
    def is_committed_real(self) -> bool:
        return self.status == ToolReceiptStatus.COMMITTED and self.provider_mode == ProviderMode.REAL and self.verified_result


@dataclass(frozen=True, slots=True)
class DialogueResponse:
    envelope: EventEnvelope
    response_id: str
    speech_text: str
    speech_act: str
    state_revision: int
    outcome: DialogueOutcome
    display_text: str | None = None
    source_asr_revision: int | None = None
    focus_entity_refs: tuple[str, ...] = ()
    verified_fact_refs: tuple[VerifiedFactRef, ...] = ()
    tool_receipt_refs: tuple[str, ...] = ()
    error: ErrorInfo | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EventEnvelope):
            raise TypeError("envelope must be EventEnvelope")
        require_safe_id(self.response_id, "response_id")
        if not isinstance(self.speech_text, str):
            raise TypeError("speech_text must be str")
        if not isinstance(self.speech_act, str) or not self.speech_act.strip():
            raise ValueError("speech_act required")
        require_strict_int(self.state_revision, "state_revision", minimum=0)
        if not isinstance(self.outcome, DialogueOutcome):
            raise ValueError("outcome must be DialogueOutcome")
        if self.source_asr_revision is not None:
            require_strict_int(self.source_asr_revision, "source_asr_revision", minimum=0)
        object.__setattr__(self, "focus_entity_refs", freeze_value(tuple(self.focus_entity_refs)))
        object.__setattr__(self, "verified_fact_refs", freeze_value(tuple(self.verified_fact_refs)))
        object.__setattr__(self, "tool_receipt_refs", freeze_value(tuple(self.tool_receipt_refs)))

    def __repr__(self) -> str:
        return (
            f"DialogueResponse(id={self.response_id!r}, act={self.speech_act!r}, "
            f"state_rev={self.state_revision}, outcome={self.outcome.value})"
        )
