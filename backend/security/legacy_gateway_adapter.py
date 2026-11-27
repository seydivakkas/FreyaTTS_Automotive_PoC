"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import UUID

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.core.contracts.dialogue import (
    ConfirmationReference,
    ProviderMode,
    ToolReceipt,
    ToolReceiptStatus,
)
from backend.core.contracts.validation import require_safe_id
from backend.security.confirmation import ConfirmationChallenge
from backend.security.contracts import ConfirmationState, ConfirmationStateError, redact_sensitive_text


class LegacyConfirmedWriteLike(Protocol):
    """Structural protocol matching backend.supervisor.gateway.ConfirmedWrite without importing backend.db."""

    idempotency_key: UUID
    trace_id: UUID
    action: str
    request_digest: str
    verified_customer_id: str
    expires_at: datetime


_OUTCOME_MAPPING: dict[str, tuple[ToolReceiptStatus, tuple[str, ErrorCategory, Retryability, str] | None]] = {
    "applied": (ToolReceiptStatus.COMMITTED, None),
    "duplicate": (ToolReceiptStatus.COMMITTED, None),
    "denied": (
        ToolReceiptStatus.BLOCKED,
        ("gateway.denied", ErrorCategory.SECURITY, Retryability.NO, "Write denied by supervisor gateway"),
    ),
    "state_changed": (
        ToolReceiptStatus.BLOCKED,
        ("gateway.state_changed", ErrorCategory.STALE_SCOPE, Retryability.NO, "State changed before commit"),
    ),
    "unavailable": (
        ToolReceiptStatus.FAILED,
        ("gateway.unavailable", ErrorCategory.PROVIDER, Retryability.YES, "Write tool unavailable"),
    ),
    "timeout": (
        ToolReceiptStatus.UNKNOWN,
        (
            "gateway.timeout",
            ErrorCategory.PROVIDER,
            Retryability.UNKNOWN,
            "Write timed out; outcome unknown pending reconciliation",
        ),
    ),
    "failed": (
        ToolReceiptStatus.FAILED,
        ("gateway.failed", ErrorCategory.INTERNAL, Retryability.UNKNOWN, "Write execution failed"),
    ),
}


def _safe_tool_id(action: str) -> str:
    candidate = f"supervisor.{action}" if not action.startswith("supervisor.") else action
    return require_safe_id(candidate, "tool_id")


def write_outcome_to_tool_receipt(
    *,
    operation_id: str,
    action: str,
    outcome: str,
    provider_mode: ProviderMode = ProviderMode.UNKNOWN,
    idempotency_key: str | None = None,
    evidence_ref: str | None = None,
    verified_result: bool = False,
) -> ToolReceipt:
    """Bridge legacy supervisor gateway WriteOutcome into M01 ToolReceipt."""
    tool_id = _safe_tool_id(action)
    mapped = _OUTCOME_MAPPING.get(outcome)
    if mapped is None:
        status = ToolReceiptStatus.UNKNOWN
        error = ErrorInfo(
            code="gateway.unrecognized_outcome",
            category=ErrorCategory.INTERNAL,
            retryable=Retryability.NO,
            safe_message="Unrecognized gateway write outcome",
        )
    else:
        status, err_spec = mapped
        error = (
            ErrorInfo(
                code=err_spec[0],
                category=err_spec[1],
                retryable=err_spec[2],
                safe_message=err_spec[3],
            )
            if err_spec is not None
            else None
        )

    effective_verified = (
        bool(verified_result)
        and status == ToolReceiptStatus.COMMITTED
        and provider_mode == ProviderMode.REAL
    )
    resolved_evidence = evidence_ref
    if resolved_evidence is None and outcome == "duplicate" and idempotency_key:
        resolved_evidence = f"idempotency:{idempotency_key}"

    return ToolReceipt(
        operation_id=operation_id,
        tool_id=tool_id,
        status=status,
        provider_mode=provider_mode,
        idempotency_key=idempotency_key,
        evidence_ref=resolved_evidence,
        verified_result=effective_verified,
        error=error,
    )


def confirmed_write_to_tool_receipt(
    grant: LegacyConfirmedWriteLike,
    outcome: str,
    *,
    provider_mode: ProviderMode = ProviderMode.UNKNOWN,
    verified_result: bool = False,
    evidence_ref: str | None = None,
) -> ToolReceipt:
    """Bridge legacy ConfirmedWrite grant + WriteOutcome into M01 ToolReceipt."""
    return write_outcome_to_tool_receipt(
        operation_id=str(grant.trace_id),
        action=grant.action,
        outcome=outcome,
        provider_mode=provider_mode,
        idempotency_key=str(grant.idempotency_key),
        evidence_ref=evidence_ref,
        verified_result=verified_result,
    )


def confirmed_write_to_confirmation_reference(
    grant: LegacyConfirmedWriteLike,
    *,
    state_revision: int = 0,
    confirmation_source_id: str | None = None,
) -> ConfirmationReference:
    """Bridge legacy ConfirmedWrite grant into M01 ConfirmationReference."""
    if grant.expires_at.utcoffset() is None:
        raise ValueError("ConfirmedWrite.expires_at must have UTC timezone offset")
    expires_utc = grant.expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    source_id = confirmation_source_id or f"grant-{grant.idempotency_key}"
    raw_actor = str(grant.verified_customer_id).strip()
    safe_actor = redact_sensitive_text(raw_actor) if raw_actor else None
    return ConfirmationReference(
        state_revision=state_revision,
        operation_digest=grant.request_digest,
        confirmation_source_id=source_id,
        expires_at_utc=expires_utc,
        actor_ref=safe_actor,
    )


def challenge_to_confirmed_write(
    challenge: ConfirmationChallenge,
    *,
    idempotency_key: UUID,
    trace_id: UUID,
    grant_factory: Callable[..., Any] | None = None,
) -> Any:
    """Convert an APPROVED ConfirmationChallenge into a legacy ConfirmedWrite grant."""
    if challenge.state != ConfirmationState.APPROVED:
        raise ConfirmationStateError(
            f"Only APPROVED challenge can issue ConfirmedWrite (got {challenge.state.value})"
        )
    expires_at = datetime.fromisoformat(challenge.expires_at_utc.replace("Z", "+00:00"))
    factory = grant_factory
    if factory is None:
        # Lazy import to preserve passive import invariant when backend.db is not initialized.
        from backend.supervisor.gateway import ConfirmedWrite

        factory = ConfirmedWrite
    return factory(
        idempotency_key=idempotency_key,
        trace_id=trace_id,
        action=challenge.action,
        request_digest=challenge.operation_digest,
        verified_customer_id=challenge.actor_ref,
        expires_at=expires_at,
    )
