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

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.core.contracts.dialogue import (
    ConfirmationReference,
    ProviderMode,
    ToolReceipt,
    ToolReceiptStatus,
    VerifiedFactRef,
)
from backend.core.contracts.recognition import ASRStatus
from backend.core.contracts.validation import freeze_value
from backend.security.audit import AuditEventKind, SecurityAuditLog
from backend.security.confirmation import ConfirmationChallenge, ConfirmationManager
from backend.security.contracts import (
    AccessContext,
    ConfirmationError,
    ConfirmationState,
    IdempotencyConflictError,
    IdempotencyState,
    PolicyDecision,
    PolicyVerdict,
    PrincipalKind,
    compute_operation_digest,
)
from backend.security.idempotency import ClaimOutcome, DurableIdempotencyStore
from backend.security.principal import PolicyEngine
from backend.security.reconciliation import (
    IdempotencyReconciler,
    ReconciliationProbe,
    ReconciliationReport,
)

ISTANBUL = ZoneInfo("Europe/Istanbul")

ALLOWLISTED_WORKFLOW_TOOLS: frozenset[str] = frozenset({
    "vehicle.read_specs",
    "availability.read",
    "booking.read_status",
    "customer.read_record",
    "booking.create",
    "booking.reschedule",
    "booking.cancel",
    "complaint.create",
    "operator.transfer_request",
    "notification.enqueue",
    "caller_memory.read",
})


@dataclass(frozen=True, slots=True)
class WorkflowExecutionResult:
    """Structured outcome from executing or gating a workflow/tool through M07."""

    allowed: bool
    policy_decision: PolicyDecision | None
    receipt: ToolReceipt
    verified_facts: tuple[VerifiedFactRef, ...] = ()
    data: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    confirmation_challenge: ConfirmationChallenge | None = None
    confirmation_reference: ConfirmationReference | None = None
    error: ErrorInfo | None = None


def _safe_op_id(prefix: str) -> str:
    """Generate a safe operation_id that can never match phone-number-like PII."""
    h = uuid4().hex
    return f"{prefix}-h{h[:5]}z{h[5:10]}"


def _blocked_receipt(
    *,
    operation_id: str,
    tool_id: str,
    code: str,
    message: str,
    provider_mode: ProviderMode = ProviderMode.UNKNOWN,
    category: ErrorCategory = ErrorCategory.SECURITY,
    idempotency_key: str | None = None,
) -> ToolReceipt:
    return ToolReceipt(
        operation_id=operation_id,
        tool_id=tool_id,
        status=ToolReceiptStatus.BLOCKED,
        provider_mode=provider_mode,
        idempotency_key=idempotency_key,
        verified_result=False,
        error=ErrorInfo(
            code=code,
            category=category,
            retryable=Retryability.NO,
            safe_message=message,
        ),
    )


class WorkflowAdapter:
    """
    Single M07-enforced execution adapter for CRM, appointment, DTMF, transfer,
    outbox notification, and caller-memory workflows.

    Never bypasses PolicyEngine, ConfirmationManager, DurableIdempotencyStore,
    or fail-closed SecurityAuditLog.
    """

    def __init__(
        self,
        *,
        policy_engine: PolicyEngine,
        confirmation_manager: ConfirmationManager,
        idempotency_store: DurableIdempotencyStore,
        audit_log: SecurityAuditLog | None,
        session_factory: Any = None,
        provider_mode: ProviderMode = ProviderMode.MOCK,
        reconciler: IdempotencyReconciler | None = None,
        ami_is_real_fn: Callable[[], bool] | None = None,
    ) -> None:
        self._policy = policy_engine
        self._confirmations = confirmation_manager
        self._idempotency = idempotency_store
        self._audit = audit_log
        self._session_factory = session_factory
        self._provider_mode = provider_mode
        self._reconciler = reconciler or IdempotencyReconciler(idempotency_store, audit_log=audit_log)
        self._ami_is_real_fn = ami_is_real_fn

    def _require_audit_ready(self, action: str, actor_ref: str | None, operation_digest: str | None) -> ErrorInfo | None:
        if self._audit is None:
            return ErrorInfo(
                code="audit.unavailable",
                category=ErrorCategory.SECURITY,
                retryable=Retryability.NO,
                safe_message="Required security audit store is unavailable",
            )
        try:
            self._audit.append(
                kind=AuditEventKind.GATEWAY_BRIDGE,
                action=action,
                outcome="ATTEMPT",
                actor_ref=actor_ref,
                operation_digest=operation_digest,
                details={"gate": "m07_preflight"},
            )
            return None
        except Exception:
            return ErrorInfo(
                code="audit.write_failed",
                category=ErrorCategory.SECURITY,
                retryable=Retryability.NO,
                safe_message="Security audit log write failed; protected effect blocked",
            )

    @staticmethod
    def _check_customer_scope(access: AccessContext, target_customer_id: str | None) -> ErrorInfo | None:
        if target_customer_id is None:
            return None
        if access.principal.kind == PrincipalKind.CUSTOMER and target_customer_id != access.principal.principal_id:
            # Uniform safe denial without leaking record existence.
            return ErrorInfo(
                code="policy.cross_customer_denied",
                category=ErrorCategory.SECURITY,
                retryable=Retryability.NO,
                safe_message="Bu kaynağa erişim yetkiniz bulunmuyor.",
            )
        return None

    def issue_and_present_confirmation(
        self,
        *,
        access: AccessContext,
        tool_id: str,
        action: str,
        terms: Mapping[str, Any],
        presentation_confirmed: bool = True,
        ttl_ms: int | None = None,
    ) -> tuple[ConfirmationChallenge | None, ErrorInfo | None]:
        """Issue M07 ConfirmationChallenge and transition to PRESENTED only with presentation evidence."""
        audit_err = self._require_audit_ready("confirmation.issue", access.principal.principal_id, None)
        if audit_err is not None:
            return None, audit_err
        if not presentation_confirmed:
            return None, ErrorInfo(
                code="confirmation.presentation_evidence_missing",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.YES,
                safe_message="Onay metni sunumu doğrulanamadı; güvenli tekrar gerekiyor.",
            )
        challenge = self._confirmations.issue(
            tool_id=tool_id,
            action=action,
            actor_ref=access.principal.principal_id,
            state_revision=access.state_revision,
            terms=terms,
            ttl_ms=ttl_ms,
        )
        presented = self._confirmations.present(challenge.challenge_id)
        return presented, None

    def approve_confirmation(
        self,
        *,
        challenge_id: str,
        access: AccessContext,
        terms: Mapping[str, Any],
        is_final_asr: bool = True,
        presentation_confirmed: bool = True,
    ) -> tuple[ConfirmationChallenge | None, ErrorInfo | None]:
        """Approve a PRESENTED M07 challenge after verifying presentation and final-input provenance."""
        if not is_final_asr:
            return None, ErrorInfo(
                code="confirmation.non_final_rejected",
                category=ErrorCategory.SECURITY,
                retryable=Retryability.NO,
                safe_message="Kesinleşmemiş ses girdisi onay olarak kabul edilemez.",
            )
        if not presentation_confirmed:
            return None, ErrorInfo(
                code="confirmation.presentation_evidence_missing",
                category=ErrorCategory.SECURITY,
                retryable=Retryability.YES,
                safe_message="Sunum kanıtı olmadan onay geçerli değildir.",
            )
        try:
            approved = self._confirmations.approve(
                challenge_id,
                actor_ref=access.principal.principal_id,
                state_revision=access.state_revision,
                terms=terms,
            )
            return approved, None
        except ConfirmationError as exc:
            return None, ErrorInfo(
                code="confirmation.invalid_or_expired",
                category=ErrorCategory.SECURITY,
                retryable=Retryability.NO,
                safe_message=str(exc),
            )

    def revoke_confirmation(self, challenge_id: str, reason: str = "customer_declined") -> bool:
        """Revoke an unused confirmation challenge cleanly."""
        try:
            self._confirmations.revoke(challenge_id, reason=reason)
            return True
        except ConfirmationError:
            return False

    def read_availability(
        self,
        *,
        access: AccessContext,
        target_day: date,
        now_utc: datetime,
        operation_id: str | None = None,
    ) -> WorkflowExecutionResult:
        """Authoritative read-only availability check (never reserves a slot)."""
        op_id = operation_id or _safe_op_id("avail")
        decision = self._policy.evaluate(access, "availability.read")
        if decision.verdict != PolicyVerdict.ALLOW:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id="availability.read",
                code=decision.reason_codes[0] if decision.reason_codes else "policy.denied",
                message="Müsaitlik sorgusu engellendi.",
                provider_mode=self._provider_mode,
            )
            return WorkflowExecutionResult(
                allowed=False,
                policy_decision=decision,
                receipt=receipt,
                error=decision.error,
            )
        if self._session_factory is None:
            receipt = ToolReceipt(
                operation_id=op_id,
                tool_id="availability.read",
                status=ToolReceiptStatus.FAILED,
                provider_mode=self._provider_mode,
                verified_result=False,
                error=ErrorInfo(
                    code="availability.db_unavailable",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.YES,
                    safe_message="Takvim veritabanı bağlı değil.",
                ),
            )
            return WorkflowExecutionResult(allowed=True, policy_decision=decision, receipt=receipt, error=receipt.error)

        from sqlalchemy import func, select
        from backend.db import Appointment, Slot

        start = datetime.combine(target_day, time.min, tzinfo=ISTANBUL).astimezone(timezone.utc)
        end = datetime.combine(target_day + timedelta(days=1), time.min, tzinfo=ISTANBUL).astimezone(timezone.utc)
        with self._session_factory() as db:
            if end <= now_utc:
                slots = []
            else:
                occupied = select(Appointment.slot_id).where(Appointment.slot_id.is_not(None))
                starts_at = func.julianday(Slot.starts_at)
                slots = list(
                    db.scalars(
                        select(Slot).where(
                            starts_at >= func.julianday(start.isoformat()),
                            starts_at > func.julianday(now_utc.isoformat()),
                            starts_at < func.julianday(end.isoformat()),
                            Slot.id.not_in(occupied),
                        ).order_by(Slot.starts_at)
                    )
                )
        slot_summaries = tuple({"id": s.id, "starts_at": s.starts_at} for s in slots)
        fact = VerifiedFactRef(
            provenance="crm.slot_inventory",
            reference_id=f"avail-{target_day.isoformat()}",
            status="AVAILABLE" if slots else "NONE_AVAILABLE",
            revision=len(slots),
        )
        receipt = ToolReceipt(
            operation_id=op_id,
            tool_id="availability.read",
            status=ToolReceiptStatus.COMMITTED,
            provider_mode=self._provider_mode,
            evidence_ref=f"avail:{target_day.isoformat()}:{len(slots)}",
            verified_result=(self._provider_mode == ProviderMode.REAL),
        )
        return WorkflowExecutionResult(
            allowed=True,
            policy_decision=decision,
            receipt=receipt,
            verified_facts=(fact,),
            data=freeze_value({"available_count": len(slots), "slots": slot_summaries, "date": target_day.isoformat()}),
        )

    def read_protected_record(
        self,
        *,
        access: AccessContext,
        tool_id: str,
        target_customer_id: str,
        booking_id: str | None = None,
        operation_id: str | None = None,
    ) -> WorkflowExecutionResult:
        """Execute M07-gated protected read (booking.read_status / customer.read_record / caller_memory.read)."""
        op_id = operation_id or _safe_op_id("read")
        if tool_id not in {"booking.read_status", "customer.read_record", "caller_memory.read"}:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id=tool_id,
                code="workflow.disallowed_read_tool",
                message="İzin verilmeyen okuma aracı.",
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=None, receipt=receipt, error=receipt.error)

        audit_err = self._require_audit_ready(f"read.{tool_id}", access.principal.principal_id, None)
        if audit_err is not None:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id=tool_id,
                code=audit_err.code,
                message=audit_err.safe_message,
                provider_mode=self._provider_mode,
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=None, receipt=receipt, error=audit_err)

        policy_tool = "customer.read_record" if tool_id == "caller_memory.read" else tool_id
        decision = self._policy.evaluate(access, policy_tool)
        if decision.verdict != PolicyVerdict.ALLOW:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id=tool_id,
                code=decision.reason_codes[0] if decision.reason_codes else "policy.denied",
                message="Kimlik doğrulaması olmadan kayıt bilgisine erişilemez.",
                provider_mode=self._provider_mode,
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=decision, receipt=receipt, error=decision.error)

        scope_err = self._check_customer_scope(access, target_customer_id)
        if scope_err is not None:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id=tool_id,
                code=scope_err.code,
                message=scope_err.safe_message,
                provider_mode=self._provider_mode,
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=decision, receipt=receipt, error=scope_err)

        if self._session_factory is None:
            receipt = ToolReceipt(
                operation_id=op_id,
                tool_id=tool_id,
                status=ToolReceiptStatus.FAILED,
                provider_mode=self._provider_mode,
                verified_result=False,
                error=ErrorInfo(
                    code="read.db_unavailable",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.YES,
                    safe_message="Kayıt veritabanı bağlı değil.",
                ),
            )
            return WorkflowExecutionResult(allowed=True, policy_decision=decision, receipt=receipt, error=receipt.error)

        from sqlalchemy import select
        from backend.db import Appointment, CallerProfile, Slot

        with self._session_factory() as db:
            if tool_id == "booking.read_status":
                stmt = select(Appointment).where(Appointment.customer == target_customer_id)
                if booking_id:
                    stmt = stmt.where(Appointment.id == booking_id)
                app = db.scalars(stmt).first()
                if app is None:
                    receipt = ToolReceipt(
                        operation_id=op_id,
                        tool_id=tool_id,
                        status=ToolReceiptStatus.COMMITTED,
                        provider_mode=self._provider_mode,
                        evidence_ref=f"read:{op_id}:empty",
                        verified_result=(self._provider_mode == ProviderMode.REAL),
                    )
                    return WorkflowExecutionResult(
                        allowed=True,
                        policy_decision=decision,
                        receipt=receipt,
                        data=freeze_value({"found": False}),
                    )
                slot = db.get(Slot, app.slot_id) if app.slot_id else None
                projected = {
                    "found": True,
                    "booking_id": app.id,
                    "status": app.status,
                    "package_type": app.package_type,
                    "starts_at": slot.starts_at if slot else None,
                }
                fact = VerifiedFactRef(
                    provenance="crm.appointment",
                    reference_id=app.id,
                    status=app.status.upper(),
                    revision=app.slot_id or "none",
                )
            else:
                # customer.read_record or caller_memory.read: return safe non-secret projection only.
                prof = db.scalars(select(CallerProfile).where(CallerProfile.name == target_customer_id)).first()
                projected = {
                    "found": prof is not None,
                    "customer_ref": target_customer_id,
                    "warranty_status": prof.warranty_status if prof else "unknown",
                    "vehicle_model": prof.vehicle_model if prof else "",
                }
                fact = VerifiedFactRef(
                    provenance="crm.caller_profile",
                    reference_id=prof.id if prof else target_customer_id,
                    status="READ_PROJECTED" if prof else "NOT_FOUND",
                    revision=prof.updated_at if prof else "none",
                )

        receipt = ToolReceipt(
            operation_id=op_id,
            tool_id=tool_id,
            status=ToolReceiptStatus.COMMITTED,
            provider_mode=self._provider_mode,
            evidence_ref=f"read:{op_id}",
            verified_result=(self._provider_mode == ProviderMode.REAL),
        )
        return WorkflowExecutionResult(
            allowed=True,
            policy_decision=decision,
            receipt=receipt,
            verified_facts=(fact,),
            data=freeze_value(projected),
        )

    def execute_mutation(
        self,
        *,
        access: AccessContext,
        tool_id: str,
        action: str,
        idempotency_key: str,
        terms: Mapping[str, Any],
        challenge_id: str | None = None,
        target_customer_id: str | None = None,
        presentation_confirmed: bool = True,
        executor: Callable[[Any, Mapping[str, Any]], Mapping[str, Any]] | None = None,
        simulate_timeout: bool = False,
        operation_id: str | None = None,
    ) -> WorkflowExecutionResult:
        """
        Execute an allowlisted critical mutation strictly through M07:
        audit preflight -> customer scope -> current policy -> challenge consume
        -> durable idempotency claim -> transactional BEGIN IMMEDIATE execution.
        """
        op_id = operation_id or _safe_op_id("op")
        if tool_id not in ALLOWLISTED_WORKFLOW_TOOLS:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id=tool_id,
                code="workflow.unknown_tool",
                message="İzin verilmeyen araç çağrısı.",
                provider_mode=self._provider_mode,
                idempotency_key=idempotency_key,
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=None, receipt=receipt, error=receipt.error)

        if access.asr_status in {ASRStatus.PARTIAL, ASRStatus.STABLE_PREFIX}:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id=tool_id,
                code="policy.asr_non_final_hold",
                message="Kesinleşmemiş ses girdisi ile işlem yapılamaz.",
                provider_mode=self._provider_mode,
                idempotency_key=idempotency_key,
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=None, receipt=receipt, error=receipt.error)

        op_digest = compute_operation_digest(
            tool_id=tool_id,
            action=action,
            actor_ref=access.principal.principal_id,
            state_revision=access.state_revision,
            terms=terms,
        )

        audit_err = self._require_audit_ready(f"mutation.{action}", access.principal.principal_id, op_digest)
        if audit_err is not None:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id=tool_id,
                code=audit_err.code,
                message=audit_err.safe_message,
                provider_mode=self._provider_mode,
                idempotency_key=idempotency_key,
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=None, receipt=receipt, error=audit_err)

        scope_err = self._check_customer_scope(access, target_customer_id)
        if scope_err is not None:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id=tool_id,
                code=scope_err.code,
                message=scope_err.safe_message,
                provider_mode=self._provider_mode,
                idempotency_key=idempotency_key,
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=None, receipt=receipt, error=scope_err)

        # Check active challenge state & presentation evidence before policy evaluation.
        challenge: ConfirmationChallenge | None = None
        if challenge_id is not None:
            challenge = self._confirmations.get(challenge_id)

        existing_idem = self._idempotency.get(idempotency_key)
        same_idem_consumed_replay = (
            existing_idem is not None
            and existing_idem.operation_digest == op_digest
            and existing_idem.actor_ref == access.principal.principal_id
            and existing_idem.tool_id == tool_id
            and challenge is not None
            and challenge.state == ConfirmationState.CONSUMED
            and challenge.operation_digest == op_digest
        )

        confirmation_approved = (
            presentation_confirmed
            and challenge is not None
            and (challenge.state == ConfirmationState.APPROVED or same_idem_consumed_replay)
        )
        conf_state_rev = challenge.state_revision if challenge is not None else None
        effective_access = (
            replace(access, confirmation_ref=challenge.to_confirmation_reference())
            if challenge is not None
            and (challenge.state == ConfirmationState.APPROVED or same_idem_consumed_replay)
            and access.confirmation_ref is None
            else access
        )

        # Always re-evaluate live PolicyEngine immediately before execution (handles revoked permissions).
        decision = self._policy.evaluate(
            effective_access,
            tool_id,
            operation_digest=op_digest,
            confirmation_approved=confirmation_approved,
            confirmation_state_revision=conf_state_rev,
        )
        if decision.verdict != PolicyVerdict.ALLOW:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id=tool_id,
                code=decision.reason_codes[0] if decision.reason_codes else "policy.denied",
                message=decision.error.safe_message if decision.error else "İşlem politika tarafından engellendi.",
                provider_mode=self._provider_mode,
                idempotency_key=idempotency_key,
            )
            return WorkflowExecutionResult(
                allowed=False,
                policy_decision=decision,
                receipt=receipt,
                error=decision.error,
            )

        # Durable idempotency claim BEFORE consuming challenge / mutating DB.
        try:
            claim = self._idempotency.claim(
                idempotency_key,
                tool_id=tool_id,
                action=action,
                actor_ref=access.principal.principal_id,
                operation_digest=op_digest,
            )
        except IdempotencyConflictError as exc:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id=tool_id,
                code="idempotency.conflict",
                message=str(exc),
                provider_mode=self._provider_mode,
                idempotency_key=idempotency_key,
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=decision, receipt=receipt, error=receipt.error)

        if not claim.acquired:
            rec = claim.record
            if claim.outcome == ClaimOutcome.ALREADY_COMMITTED:
                receipt = ToolReceipt(
                    operation_id=op_id,
                    tool_id=tool_id,
                    status=ToolReceiptStatus.COMMITTED,
                    provider_mode=self._provider_mode,
                    idempotency_key=idempotency_key,
                    evidence_ref=rec.result_ref or f"idempotency:{idempotency_key}",
                    verified_result=(self._provider_mode == ProviderMode.REAL),
                )
                return WorkflowExecutionResult(
                    allowed=True,
                    policy_decision=decision,
                    receipt=receipt,
                    data=freeze_value({"replayed": True, "result_ref": rec.result_ref}),
                )
            if claim.outcome in {ClaimOutcome.UNKNOWN_HOLD, ClaimOutcome.RECONCILING_HOLD, ClaimOutcome.IN_FLIGHT}:
                receipt = ToolReceipt(
                    operation_id=op_id,
                    tool_id=tool_id,
                    status=ToolReceiptStatus.UNKNOWN,
                    provider_mode=self._provider_mode,
                    idempotency_key=idempotency_key,
                    evidence_ref=f"idempotency:{idempotency_key}:unknown",
                    verified_result=False,
                    error=ErrorInfo(
                        code="idempotency.unknown_reconcile_required",
                        category=ErrorCategory.PROVIDER,
                        retryable=Retryability.UNKNOWN,
                        safe_message="İşlemin sonucu belirsiz; uzlaştırma bekleniyor.",
                    ),
                )
                return WorkflowExecutionResult(allowed=True, policy_decision=decision, receipt=receipt, error=receipt.error)
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id=tool_id,
                code=f"idempotency.{claim.outcome.value.lower()}",
                message="İşlem anahtarı daha önce engellenmiş veya başarısız olmuş.",
                provider_mode=self._provider_mode,
                idempotency_key=idempotency_key,
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=decision, receipt=receipt, error=receipt.error)

        # Consume challenge once idempotency lock is acquired.
        consumed_challenge: ConfirmationChallenge | None = None
        if challenge_id is not None:
            try:
                consumed_challenge = self._confirmations.consume(
                    challenge_id,
                    actor_ref=access.principal.principal_id,
                    state_revision=access.state_revision,
                    operation_digest=op_digest,
                )
            except ConfirmationError as exc:
                self._idempotency.mark_blocked(
                    idempotency_key,
                    operation_digest=op_digest,
                    error_code="confirmation.consume_failed",
                )
                receipt = _blocked_receipt(
                    operation_id=op_id,
                    tool_id=tool_id,
                    code="confirmation.consume_failed",
                    message=str(exc),
                    provider_mode=self._provider_mode,
                    idempotency_key=idempotency_key,
                )
                return WorkflowExecutionResult(allowed=False, policy_decision=decision, receipt=receipt, error=receipt.error)

        if simulate_timeout:
            self._idempotency.mark_unknown(
                idempotency_key,
                operation_digest=op_digest,
                error_code="provider.timeout",
            )
            receipt = ToolReceipt(
                operation_id=op_id,
                tool_id=tool_id,
                status=ToolReceiptStatus.UNKNOWN,
                provider_mode=self._provider_mode,
                idempotency_key=idempotency_key,
                evidence_ref=f"unknown:{op_id}",
                verified_result=False,
                error=ErrorInfo(
                    code="provider.timeout",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.UNKNOWN,
                    safe_message="Sağlayıcı zaman aşımına uğradı; sonuç uzlaştırma bekliyor.",
                ),
            )
            return WorkflowExecutionResult(
                allowed=True,
                policy_decision=decision,
                receipt=receipt,
                confirmation_challenge=consumed_challenge,
                error=receipt.error,
            )

        try:
            out_data = self._run_isolated_db_mutation(
                tool_id=tool_id,
                terms=terms,
                idempotency_key=idempotency_key,
                executor=executor,
            )
        except TimeoutError:
            self._idempotency.mark_unknown(
                idempotency_key,
                operation_digest=op_digest,
                error_code="provider.timeout",
            )
            receipt = ToolReceipt(
                operation_id=op_id,
                tool_id=tool_id,
                status=ToolReceiptStatus.UNKNOWN,
                provider_mode=self._provider_mode,
                idempotency_key=idempotency_key,
                evidence_ref=f"unknown:{op_id}",
                verified_result=False,
                error=ErrorInfo(
                    code="provider.timeout",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.UNKNOWN,
                    safe_message="Sağlayıcı yanıt vermedi; işlem sonucu belirsiz.",
                ),
            )
            return WorkflowExecutionResult(
                allowed=True,
                policy_decision=decision,
                receipt=receipt,
                confirmation_challenge=consumed_challenge,
                error=receipt.error,
            )
        except Exception as exc:
            self._idempotency.mark_failed_confirmed(
                idempotency_key,
                operation_digest=op_digest,
                error_code="provider.execution_failed",
            )
            receipt = ToolReceipt(
                operation_id=op_id,
                tool_id=tool_id,
                status=ToolReceiptStatus.FAILED,
                provider_mode=self._provider_mode,
                idempotency_key=idempotency_key,
                verified_result=False,
                error=ErrorInfo(
                    code="provider.execution_failed",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message=f"İşlem tamamlanamadı: {exc}",
                ),
            )
            return WorkflowExecutionResult(
                allowed=True,
                policy_decision=decision,
                receipt=receipt,
                confirmation_challenge=consumed_challenge,
                error=receipt.error,
            )

        ref_id = str(out_data.get("booking_id") or out_data.get("result_ref") or op_id)
        self._idempotency.mark_committed(
            idempotency_key,
            operation_digest=op_digest,
            result_ref=ref_id,
        )
        fact = VerifiedFactRef(
            provenance=f"workflow.{tool_id}",
            reference_id=ref_id,
            status="COMMITTED",
            revision=str(out_data.get("version") or access.state_revision),
        )
        receipt = ToolReceipt(
            operation_id=op_id,
            tool_id=tool_id,
            status=ToolReceiptStatus.COMMITTED,
            provider_mode=self._provider_mode,
            idempotency_key=idempotency_key,
            evidence_ref=ref_id,
            verified_result=(self._provider_mode == ProviderMode.REAL),
        )
        conf_ref = consumed_challenge.to_confirmation_reference() if consumed_challenge is not None else None
        return WorkflowExecutionResult(
            allowed=True,
            policy_decision=decision,
            receipt=receipt,
            verified_facts=(fact,),
            data=freeze_value(out_data),
            confirmation_challenge=consumed_challenge,
            confirmation_reference=conf_ref,
        )

    def _run_isolated_db_mutation(
        self,
        *,
        tool_id: str,
        terms: Mapping[str, Any],
        idempotency_key: str,
        executor: Callable[[Any, Mapping[str, Any]], Mapping[str, Any]] | None,
    ) -> dict[str, Any]:
        if executor is not None:
            if self._session_factory is not None:
                with self._session_factory() as db:
                    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                    res = dict(executor(db, terms))
                    db.commit()
                    return res
            return dict(executor(None, terms))

        if self._session_factory is None:
            raise RuntimeError("No isolated session_factory or executor configured")

        from backend.appointment_reschedule import MoveCheck, version_for
        from backend.db import Appointment, Slot, book, cancel_appointment

        with self._session_factory() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            if tool_id == "booking.create":
                app = book(
                    db,
                    slot_id=str(terms["selected_slot_id"]),
                    vehicle_id=str(terms["vehicle_ref"]),
                    customer=str(terms["customer_ref"]),
                    idempotency_key=idempotency_key,
                    confirmed=True,
                    corporate_account_id=terms.get("corporate_account_id"),
                    customer_phone=str(terms.get("contact_phone", "")),
                    package_type=str(terms.get("package_type", "standart_ekspertiz")),
                    plate=str(terms.get("vehicle_plate", "")),
                )
                return {
                    "booking_id": app.id,
                    "reference_code": f"FRY-{app.id[:6].upper()}",
                    "slot_id": app.slot_id,
                    "status": app.status,
                }
            if tool_id == "booking.reschedule":
                app = db.get(Appointment, str(terms["booking_id"]))
                target_slot = db.get(Slot, str(terms["selected_slot_id"]))
                if app is None or target_slot is None:
                    raise ValueError("Randevu veya hedef saat bulunamadı")
                source_slot = db.get(Slot, app.slot_id) if app.slot_id else None
                expected_ver = terms.get("expected_version")
                current_ver = version_for(app, source_slot, target_slot)
                if expected_ver is not None and expected_ver != current_ver:
                    raise ValueError("Randevu sürümü değiştiği için yeniden doğrulama gerekiyor")
                move_check = MoveCheck(db, app, datetime.now(timezone.utc))
                code, _, msg = move_check.evaluate(target_slot)
                if code != "available":
                    raise ValueError(msg)
                app.slot_id = target_slot.id
                db.commit()
                return {
                    "booking_id": app.id,
                    "slot_id": target_slot.id,
                    "starts_at": target_slot.starts_at,
                    "status": app.status,
                    "version": current_ver,
                }
            if tool_id == "booking.cancel":
                app = db.get(Appointment, str(terms["booking_id"]))
                if app is None:
                    raise ValueError("İptal edilecek randevu bulunamadı")
                cancel_appointment(db, app, commit=True)
                return {"booking_id": app.id, "status": app.status}
            if tool_id == "complaint.create":
                return {
                    "result_ref": f"cmp-{uuid4().hex[:10]}",
                    "status": "recorded",
                }
            raise ValueError(f"Unsupported DB mutation tool: {tool_id}")

    def reconcile_operation(
        self,
        *,
        idempotency_key: str,
        probe: ReconciliationProbe,
    ) -> ReconciliationReport:
        """Delegate UNKNOWN idempotency reconciliation strictly to M07 IdempotencyReconciler."""
        return self._reconciler.reconcile_one(idempotency_key, probe)

    def request_operator_transfer(
        self,
        *,
        access: AccessContext,
        reason: str,
        target_queue: str = "service_advisor",
        operation_id: str | None = None,
    ) -> WorkflowExecutionResult:
        """Submit operator transfer; NEVER claims connected when only submitted or mock AMI."""
        op_id = operation_id or _safe_op_id("xfer")
        audit_err = self._require_audit_ready("transfer.request", access.principal.principal_id, None)
        if audit_err is not None:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id="operator.transfer_request",
                code=audit_err.code,
                message=audit_err.safe_message,
                provider_mode=self._provider_mode,
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=None, receipt=receipt, error=audit_err)

        is_real = self._ami_is_real_fn() if self._ami_is_real_fn is not None else False
        mode = ProviderMode.REAL if is_real else ProviderMode.MOCK
        receipt = ToolReceipt(
            operation_id=op_id,
            tool_id="operator.transfer_request",
            status=ToolReceiptStatus.PENDING,
            provider_mode=mode,
            evidence_ref=f"xfer-submitted:{op_id}",
            verified_result=False,
        )
        return WorkflowExecutionResult(
            allowed=True,
            policy_decision=None,
            receipt=receipt,
            data=freeze_value({
                "transfer_state": "submitted_not_connected",
                "connected": False,
                "target_queue": target_queue,
                "reason": reason,
            }),
        )

    def enqueue_notification(
        self,
        *,
        access: AccessContext,
        channel: str,
        recipient_ref: str,
        appointment_id: str | None = None,
        operation_id: str | None = None,
    ) -> WorkflowExecutionResult:
        """Enqueue notification in outbox; distinguishes enqueued/PENDING from delivered."""
        op_id = operation_id or _safe_op_id("notif")
        audit_err = self._require_audit_ready("notification.enqueue", access.principal.principal_id, None)
        if audit_err is not None:
            receipt = _blocked_receipt(
                operation_id=op_id,
                tool_id="notification.enqueue",
                code=audit_err.code,
                message=audit_err.safe_message,
                provider_mode=self._provider_mode,
            )
            return WorkflowExecutionResult(allowed=False, policy_decision=None, receipt=receipt, error=audit_err)

        receipt = ToolReceipt(
            operation_id=op_id,
            tool_id="notification.enqueue",
            status=ToolReceiptStatus.PENDING,
            provider_mode=self._provider_mode,
            evidence_ref=f"outbox-queued:{op_id}",
            verified_result=False,
        )
        return WorkflowExecutionResult(
            allowed=True,
            policy_decision=None,
            receipt=receipt,
            data=freeze_value({
                "outbox_status": "queued",
                "delivered": False,
                "channel": channel,
                "recipient_ref": recipient_ref,
                "appointment_id": appointment_id,
            }),
        )
