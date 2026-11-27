"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, ErrorCategory, ErrorInfo, EventEnvelope, Retryability
from backend.core.contracts.dialogue import (
    DialogueOutcome,
    DialogueResponse,
    ProviderMode,
    ToolReceipt,
    ToolReceiptStatus,
)
from backend.core.contracts.validation import ConversionResult


def tool_receipt_from_legacy_outcome(
    *,
    operation_id: str,
    tool_id: str,
    legacy_outcome: str,
    idempotency_key: str | None = None,
    provider_mode: ProviderMode = ProviderMode.UNKNOWN,
    source_ref: str = "backend.supervisor.gateway",
) -> ToolReceipt:
    mapping = {
        "applied": ToolReceiptStatus.COMMITTED,
        "duplicate": ToolReceiptStatus.COMMITTED,
        "denied": ToolReceiptStatus.BLOCKED,
        "state_changed": ToolReceiptStatus.FAILED,
        "unavailable": ToolReceiptStatus.FAILED,
        "timeout": ToolReceiptStatus.UNKNOWN,
        "failed": ToolReceiptStatus.FAILED,
    }
    status = mapping.get(legacy_outcome, ToolReceiptStatus.UNKNOWN)
    verified = status == ToolReceiptStatus.COMMITTED and provider_mode == ProviderMode.REAL
    err = None
    if status in {ToolReceiptStatus.FAILED, ToolReceiptStatus.UNKNOWN, ToolReceiptStatus.BLOCKED}:
        err = ErrorInfo(
            code=f"gateway.{legacy_outcome}",
            category=ErrorCategory.SECURITY if status == ToolReceiptStatus.BLOCKED else ErrorCategory.PROVIDER,
            retryable=Retryability.NO if status == ToolReceiptStatus.BLOCKED else Retryability.UNKNOWN,
            safe_message=f"Legacy gateway outcome: {legacy_outcome}",
        )
    return ToolReceipt(
        operation_id=operation_id,
        tool_id=tool_id,
        status=status,
        provider_mode=provider_mode,
        idempotency_key=idempotency_key,
        verified_result=verified,
        error=err,
    )


def dialogue_response_from_legacy(
    *,
    session_id: str,
    response_id: str,
    speech_text: str,
    sequence: int,
    monotonic_ns: int,
    turn_id: int | None = None,
    speech_act: str = "STATEMENT",
    state_revision: int = 0,
    outcome: DialogueOutcome = DialogueOutcome.OK,
    source_ref: str = "backend.dialogue",
) -> ConversionResult[DialogueResponse]:
    env = EventEnvelope(
        schema_version=CONTRACT_SCHEMA_VERSION,
        event_type="dialogue.responded",
        session_id=session_id,
        trace_id=None,
        turn_id=turn_id,
        generation_id=None,
        sequence=sequence,
        monotonic_ns=monotonic_ns,
        clock_domain="legacy.local",
        producer=source_ref,
    )
    resp = DialogueResponse(
        envelope=env,
        response_id=response_id,
        speech_text=speech_text,
        speech_act=speech_act,
        state_revision=state_revision,
        outcome=outcome,
    )
    missing = ("trace_id",) if turn_id is not None else ("trace_id", "turn_id")
    return ConversionResult(resp, missing, lossy=True, source_ref=source_ref)
