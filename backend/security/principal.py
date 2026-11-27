"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from typing import Iterable, Mapping

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.core.contracts.recognition import ASRStatus
from backend.security.audit import AuditEventKind, SecurityAuditLog
from backend.security.contracts import (
    UNTRUSTED_EVIDENCE_SOURCES,
    AccessContext,
    AuthStrength,
    EvidenceSource,
    PolicyDecision,
    PolicyVerdict,
    PrincipalKind,
    PrincipalRef,
    ToolAccessTier,
    ToolPolicy,
    auth_strength_meets,
)

# Signals that can NEVER authorize protected reads or mutations on their own.
FORBIDDEN_AUTHORITY_SIGNALS: frozenset[EvidenceSource] = frozenset({
    EvidenceSource.ASR_PARTIAL,
    EvidenceSource.ASR_STABLE,
    EvidenceSource.ASR_FINAL,
    EvidenceSource.CALLER_ID,
    EvidenceSource.PLATE_TEXT,
    EvidenceSource.LLM_OUTPUT,
    EvidenceSource.RAG_TEXT,
})


def anonymous_principal(
    principal_id: str = "anonymous",
    *,
    evidence_source: EvidenceSource = EvidenceSource.UNVERIFIED_HEADER,
) -> PrincipalRef:
    """Construct an unauthenticated anonymous PrincipalRef."""
    return PrincipalRef(
        principal_id=principal_id,
        kind=PrincipalKind.ANONYMOUS,
        auth_strength=AuthStrength.UNAUTHENTICATED,
        evidence_source=evidence_source,
        verified=False,
    )


def untrusted_principal(
    principal_id: str,
    *,
    evidence_source: EvidenceSource,
    kind: PrincipalKind = PrincipalKind.CUSTOMER,
) -> PrincipalRef:
    """Construct an explicitly untrusted hint PrincipalRef (verified=False enforced)."""
    return PrincipalRef(
        principal_id=principal_id,
        kind=kind,
        auth_strength=AuthStrength.UNTRUSTED_HINT,
        evidence_source=evidence_source,
        verified=False,
    )


def verified_principal(
    principal_id: str,
    *,
    kind: PrincipalKind,
    auth_strength: AuthStrength,
    evidence_source: EvidenceSource,
    roles: Iterable[str] = (),
    tenant_id: str | None = None,
) -> PrincipalRef:
    """Construct a verified PrincipalRef backed by a trusted authentication signal."""
    return PrincipalRef(
        principal_id=principal_id,
        kind=kind,
        auth_strength=auth_strength,
        evidence_source=evidence_source,
        verified=True,
        roles=frozenset(roles),
        tenant_id=tenant_id,
    )


DEFAULT_TOOL_POLICIES: Mapping[str, ToolPolicy] = {
    "vehicle.read_specs": ToolPolicy(
        tool_id="vehicle.read_specs",
        tier=ToolAccessTier.PUBLIC_READ,
        min_auth_strength=AuthStrength.UNAUTHENTICATED,
        requires_confirmation=False,
        allowed_principal_kinds=frozenset({
            PrincipalKind.ANONYMOUS,
            PrincipalKind.CUSTOMER,
            PrincipalKind.OPERATOR,
            PrincipalKind.SYSTEM,
        }),
    ),
    "availability.read": ToolPolicy(
        tool_id="availability.read",
        tier=ToolAccessTier.PUBLIC_READ,
        min_auth_strength=AuthStrength.UNAUTHENTICATED,
        requires_confirmation=False,
        allowed_principal_kinds=frozenset({
            PrincipalKind.ANONYMOUS,
            PrincipalKind.CUSTOMER,
            PrincipalKind.OPERATOR,
            PrincipalKind.SYSTEM,
        }),
    ),
    "booking.read_status": ToolPolicy(
        tool_id="booking.read_status",
        tier=ToolAccessTier.PROTECTED_READ,
        min_auth_strength=AuthStrength.CHANNEL_VERIFIED,
        requires_confirmation=False,
    ),
    "customer.read_record": ToolPolicy(
        tool_id="customer.read_record",
        tier=ToolAccessTier.PROTECTED_READ,
        min_auth_strength=AuthStrength.STRONG_VERIFIED,
        requires_confirmation=False,
    ),
    "booking.create": ToolPolicy(
        tool_id="booking.create",
        tier=ToolAccessTier.MUTATION,
        min_auth_strength=AuthStrength.CHANNEL_VERIFIED,
        requires_confirmation=True,
    ),
    "booking.reschedule": ToolPolicy(
        tool_id="booking.reschedule",
        tier=ToolAccessTier.MUTATION,
        min_auth_strength=AuthStrength.CHANNEL_VERIFIED,
        requires_confirmation=True,
    ),
    "booking.cancel": ToolPolicy(
        tool_id="booking.cancel",
        tier=ToolAccessTier.MUTATION,
        min_auth_strength=AuthStrength.STRONG_VERIFIED,
        requires_confirmation=True,
    ),
    "complaint.create": ToolPolicy(
        tool_id="complaint.create",
        tier=ToolAccessTier.MUTATION,
        min_auth_strength=AuthStrength.CHANNEL_VERIFIED,
        requires_confirmation=True,
    ),
}


def _security_error(code: str, safe_message: str, retryable: Retryability = Retryability.NO) -> ErrorInfo:
    return ErrorInfo(
        code=code,
        category=ErrorCategory.SECURITY,
        retryable=retryable,
        safe_message=safe_message,
    )


class PolicyEngine:
    """Fail-closed policy evaluator for tool reads and mutations."""

    def __init__(
        self,
        policies: Mapping[str, ToolPolicy] | None = None,
        *,
        audit_log: SecurityAuditLog | None = None,
    ) -> None:
        base = DEFAULT_TOOL_POLICIES if policies is None else policies
        self._policies: dict[str, ToolPolicy] = dict(base)
        self._audit_log = audit_log

    def register_policy(self, policy: ToolPolicy) -> None:
        if not isinstance(policy, ToolPolicy):
            raise TypeError("policy must be ToolPolicy")
        self._policies[policy.tool_id] = policy

    def get_policy(self, tool_id: str) -> ToolPolicy | None:
        return self._policies.get(tool_id)

    def _record_decision(self, context: AccessContext | None, decision: PolicyDecision) -> PolicyDecision:
        if self._audit_log is not None:
            actor_ref = context.principal.principal_id if isinstance(context, AccessContext) else None
            session_id = context.session_id if isinstance(context, AccessContext) else None
            trace_id = context.trace_id if isinstance(context, AccessContext) else None
            details: dict[str, object] = {
                "tool_id": decision.tool_id,
                "verdict": decision.verdict.value,
                "reason_codes": list(decision.reason_codes),
                "policy_version": decision.policy_version,
            }
            if isinstance(context, AccessContext):
                details["channel"] = context.channel
                details["state_revision"] = context.state_revision
                details["auth_strength"] = context.principal.auth_strength.value
                details["evidence_source"] = context.principal.evidence_source.value
            self._audit_log.append(
                kind=AuditEventKind.POLICY_DECISION,
                action="policy.evaluate",
                outcome=decision.verdict.value,
                actor_ref=actor_ref,
                session_id=session_id,
                trace_id=trace_id,
                details=details,
            )
        return decision

    def evaluate(
        self,
        context: AccessContext,
        tool_id: str,
        *,
        operation_digest: str | None = None,
        confirmation_approved: bool = False,
        confirmation_state_revision: int | None = None,
        reconciliation_pending: bool = False,
    ) -> PolicyDecision:
        """Evaluate access fail-closed returning ALLOW, DENY, CHALLENGE, or HOLD."""
        if not isinstance(context, AccessContext):
            decision = PolicyDecision(
                verdict=PolicyVerdict.DENY,
                tool_id="invalid_context",
                reason_codes=("policy.invalid_context",),
                error=_security_error("policy.invalid_context", "Invalid access context"),
            )
            return self._record_decision(None, decision)

        policy = self._policies.get(tool_id)
        if policy is None:
            return self._record_decision(
                context,
                PolicyDecision(
                    verdict=PolicyVerdict.DENY,
                    tool_id=tool_id,
                    reason_codes=("policy.unknown_tool",),
                    error=_security_error("policy.unknown_tool", "Tool is not registered in policy"),
                ),
            )

        if reconciliation_pending:
            return self._record_decision(
                context,
                PolicyDecision(
                    verdict=PolicyVerdict.HOLD,
                    tool_id=tool_id,
                    reason_codes=("policy.reconciliation_hold",),
                    requires_confirmation=policy.requires_confirmation,
                    error=_security_error(
                        "policy.reconciliation_hold",
                        "Operation held pending idempotency reconciliation",
                        Retryability.UNKNOWN,
                    ),
                ),
            )

        principal = context.principal
        is_protected = policy.tier != ToolAccessTier.PUBLIC_READ

        if is_protected:
            if context.asr_status in {ASRStatus.PARTIAL, ASRStatus.STABLE_PREFIX}:
                return self._record_decision(
                    context,
                    PolicyDecision(
                        verdict=PolicyVerdict.HOLD,
                        tool_id=tool_id,
                        reason_codes=("policy.asr_non_final_hold",),
                        required_auth_strength=policy.min_auth_strength,
                        requires_confirmation=policy.requires_confirmation,
                        error=_security_error(
                            "policy.asr_non_final_hold",
                            "Protected operation held while ASR transcript is non-final",
                            Retryability.YES,
                        ),
                    ),
                )

            if principal.evidence_source in FORBIDDEN_AUTHORITY_SIGNALS:
                return self._record_decision(
                    context,
                    PolicyDecision(
                        verdict=PolicyVerdict.DENY,
                        tool_id=tool_id,
                        reason_codes=(f"policy.untrusted_source.{principal.evidence_source.value.lower()}",),
                        required_auth_strength=policy.min_auth_strength,
                        requires_confirmation=policy.requires_confirmation,
                        error=_security_error(
                            "policy.untrusted_evidence_denied",
                            "Untrusted signal cannot authorize protected read or mutation",
                        ),
                    ),
                )

            if not principal.verified:
                if (
                    principal.evidence_source == EvidenceSource.UNVERIFIED_HEADER
                    and principal.auth_strength == AuthStrength.UNAUTHENTICATED
                    and not (set(context.untrusted_claims) & FORBIDDEN_AUTHORITY_SIGNALS)
                ):
                    return self._record_decision(
                        context,
                        PolicyDecision(
                            verdict=PolicyVerdict.CHALLENGE,
                            tool_id=tool_id,
                            reason_codes=("policy.authentication_required",),
                            required_auth_strength=policy.min_auth_strength,
                            requires_confirmation=policy.requires_confirmation,
                            error=_security_error(
                                "policy.authentication_required",
                                "Customer identity verification required",
                                Retryability.YES,
                            ),
                        ),
                    )
                return self._record_decision(
                    context,
                    PolicyDecision(
                        verdict=PolicyVerdict.DENY,
                        tool_id=tool_id,
                        reason_codes=("policy.unverified_principal_denied",),
                        required_auth_strength=policy.min_auth_strength,
                        requires_confirmation=policy.requires_confirmation,
                        error=_security_error(
                            "policy.unverified_principal_denied",
                            "Unverified principal denied for protected operation",
                        ),
                    ),
                )

            if principal.evidence_source in UNTRUSTED_EVIDENCE_SOURCES:
                return self._record_decision(
                    context,
                    PolicyDecision(
                        verdict=PolicyVerdict.DENY,
                        tool_id=tool_id,
                        reason_codes=("policy.untrusted_evidence_denied",),
                        required_auth_strength=policy.min_auth_strength,
                        requires_confirmation=policy.requires_confirmation,
                        error=_security_error(
                            "policy.untrusted_evidence_denied",
                            "Untrusted evidence cannot authorize protected operation",
                        ),
                    ),
                )

        if principal.kind not in policy.allowed_principal_kinds:
            return self._record_decision(
                context,
                PolicyDecision(
                    verdict=PolicyVerdict.DENY,
                    tool_id=tool_id,
                    reason_codes=("policy.principal_kind_denied",),
                    error=_security_error("policy.principal_kind_denied", "Principal kind not permitted"),
                ),
            )

        if not policy.required_roles <= principal.roles:
            return self._record_decision(
                context,
                PolicyDecision(
                    verdict=PolicyVerdict.DENY,
                    tool_id=tool_id,
                    reason_codes=("policy.missing_role",),
                    error=_security_error("policy.missing_role", "Required role missing"),
                ),
            )

        if not policy.required_scopes <= context.scopes:
            return self._record_decision(
                context,
                PolicyDecision(
                    verdict=PolicyVerdict.DENY,
                    tool_id=tool_id,
                    reason_codes=("policy.missing_scope",),
                    error=_security_error("policy.missing_scope", "Required scope missing"),
                ),
            )

        if not auth_strength_meets(principal.auth_strength, policy.min_auth_strength):
            return self._record_decision(
                context,
                PolicyDecision(
                    verdict=PolicyVerdict.CHALLENGE,
                    tool_id=tool_id,
                    reason_codes=("policy.step_up_auth_required",),
                    required_auth_strength=policy.min_auth_strength,
                    requires_confirmation=policy.requires_confirmation,
                    error=_security_error(
                        "policy.step_up_auth_required",
                        "Stronger authentication required",
                        Retryability.YES,
                    ),
                ),
            )

        if policy.requires_confirmation:
            if context.confirmation_ref is None or not confirmation_approved:
                return self._record_decision(
                    context,
                    PolicyDecision(
                        verdict=PolicyVerdict.CHALLENGE,
                        tool_id=tool_id,
                        reason_codes=("policy.confirmation_required",),
                        required_auth_strength=policy.min_auth_strength,
                        requires_confirmation=True,
                        error=_security_error(
                            "policy.confirmation_required",
                            "Explicit approved confirmation required",
                            Retryability.YES,
                        ),
                    ),
                )

            if context.confirmation_ref.state_revision != context.state_revision or (
                confirmation_state_revision is not None and confirmation_state_revision != context.state_revision
            ):
                return self._record_decision(
                    context,
                    PolicyDecision(
                        verdict=PolicyVerdict.DENY,
                        tool_id=tool_id,
                        reason_codes=("policy.stale_state_revision",),
                        requires_confirmation=True,
                        error=_security_error("policy.stale_state_revision", "Confirmation state_revision mismatch"),
                    ),
                )

            if (
                context.confirmation_ref.actor_ref is not None
                and context.confirmation_ref.actor_ref != principal.principal_id
            ):
                return self._record_decision(
                    context,
                    PolicyDecision(
                        verdict=PolicyVerdict.DENY,
                        tool_id=tool_id,
                        reason_codes=("policy.actor_mismatch",),
                        requires_confirmation=True,
                        error=_security_error("policy.actor_mismatch", "Confirmation actor_ref mismatch"),
                    ),
                )

            if operation_digest is not None and context.confirmation_ref.operation_digest != operation_digest:
                return self._record_decision(
                    context,
                    PolicyDecision(
                        verdict=PolicyVerdict.DENY,
                        tool_id=tool_id,
                        reason_codes=("policy.operation_digest_mismatch",),
                        requires_confirmation=True,
                        error=_security_error("policy.operation_digest_mismatch", "Confirmation digest mismatch"),
                    ),
                )

        return self._record_decision(
            context,
            PolicyDecision(
                verdict=PolicyVerdict.ALLOW,
                tool_id=tool_id,
                reason_codes=("policy.allowed",),
                required_auth_strength=policy.min_auth_strength,
                requires_confirmation=policy.requires_confirmation,
            ),
        )
