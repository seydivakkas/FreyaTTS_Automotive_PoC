"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, is_dataclass
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from backend.core.contracts.dialogue import ConfirmationReference
from backend.core.contracts.recognition import ASRStatus
from backend.core.contracts.validation import freeze_value, require_safe_id, require_strict_int, thaw_value

SECURITY_POLICY_VERSION = "m07.policy-v1"


class PrincipalKind(StrEnum):
    CUSTOMER = "CUSTOMER"
    OPERATOR = "OPERATOR"
    SYSTEM = "SYSTEM"
    ANONYMOUS = "ANONYMOUS"


class AuthStrength(StrEnum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    UNTRUSTED_HINT = "UNTRUSTED_HINT"
    CHANNEL_VERIFIED = "CHANNEL_VERIFIED"
    STRONG_VERIFIED = "STRONG_VERIFIED"
    SYSTEM_INTERNAL = "SYSTEM_INTERNAL"


_AUTH_STRENGTH_RANK: Mapping[AuthStrength, int] = MappingProxyType({
    AuthStrength.UNAUTHENTICATED: 0,
    AuthStrength.UNTRUSTED_HINT: 0,
    AuthStrength.CHANNEL_VERIFIED: 1,
    AuthStrength.STRONG_VERIFIED: 2,
    AuthStrength.SYSTEM_INTERNAL: 3,
})


def auth_strength_meets(actual: AuthStrength, minimum: AuthStrength) -> bool:
    """Return True only when actual strength satisfies minimum requirement."""
    return _AUTH_STRENGTH_RANK[actual] >= _AUTH_STRENGTH_RANK[minimum]


class EvidenceSource(StrEnum):
    # Untrusted signals: NEVER authorize protected reads or mutations
    ASR_PARTIAL = "ASR_PARTIAL"
    ASR_STABLE = "ASR_STABLE"
    ASR_FINAL = "ASR_FINAL"
    CALLER_ID = "CALLER_ID"
    PLATE_TEXT = "PLATE_TEXT"
    LLM_OUTPUT = "LLM_OUTPUT"
    RAG_TEXT = "RAG_TEXT"
    UNVERIFIED_HEADER = "UNVERIFIED_HEADER"
    # Trusted verification signals
    OTP_CHALLENGE = "OTP_CHALLENGE"
    SIGNED_TOKEN = "SIGNED_TOKEN"
    MFA_VERIFIED = "MFA_VERIFIED"
    OPERATOR_SESSION = "OPERATOR_SESSION"
    INTERNAL_MTLS = "INTERNAL_MTLS"
    CONFIRMED_CONTEXT = "CONFIRMED_CONTEXT"


UNTRUSTED_EVIDENCE_SOURCES: frozenset[EvidenceSource] = frozenset({
    EvidenceSource.ASR_PARTIAL,
    EvidenceSource.ASR_STABLE,
    EvidenceSource.ASR_FINAL,
    EvidenceSource.CALLER_ID,
    EvidenceSource.PLATE_TEXT,
    EvidenceSource.LLM_OUTPUT,
    EvidenceSource.RAG_TEXT,
    EvidenceSource.UNVERIFIED_HEADER,
})

TRUSTED_EVIDENCE_SOURCES: frozenset[EvidenceSource] = frozenset({
    EvidenceSource.OTP_CHALLENGE,
    EvidenceSource.SIGNED_TOKEN,
    EvidenceSource.MFA_VERIFIED,
    EvidenceSource.OPERATOR_SESSION,
    EvidenceSource.INTERNAL_MTLS,
    EvidenceSource.CONFIRMED_CONTEXT,
})


class ToolAccessTier(StrEnum):
    PUBLIC_READ = "PUBLIC_READ"
    PROTECTED_READ = "PROTECTED_READ"
    MUTATION = "MUTATION"
    ADMIN = "ADMIN"


class PolicyVerdict(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    CHALLENGE = "CHALLENGE"
    HOLD = "HOLD"


class ConfirmationState(StrEnum):
    ISSUED = "ISSUED"
    PRESENTED = "PRESENTED"
    APPROVED = "APPROVED"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class IdempotencyState(StrEnum):
    CLAIMED = "CLAIMED"
    COMMITTED = "COMMITTED"
    BLOCKED = "BLOCKED"
    FAILED_CONFIRMED = "FAILED_CONFIRMED"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"


class SecurityPolicyError(ValueError):
    """Base fail-closed security policy error."""


class UntrustedAuthorityError(SecurityPolicyError):
    """Raised when an untrusted signal attempts to assert verified authority."""


class ConfirmationError(SecurityPolicyError):
    """Base error for confirmation challenge lifecycle violations."""


class ConfirmationStateError(ConfirmationError):
    """Raised on invalid confirmation state transition."""


class ConfirmationExpiredError(ConfirmationError):
    """Raised when acting on an expired confirmation challenge."""


class ConfirmationInvalidatedError(ConfirmationError):
    """Raised when slot, terms, state revision, or actor binding changed."""


class IdempotencyError(SecurityPolicyError):
    """Base error for durable idempotency store operations."""


class IdempotencyConflictError(IdempotencyError):
    """Raised when an idempotency key is reused with a mismatched digest or actor."""


class IdempotencyStateError(IdempotencyError):
    """Raised on invalid idempotency state transition."""


def _normalize_for_digest(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _normalize_for_digest(getattr(value, k)) for k in sorted(value.__dataclass_fields__)}
    if isinstance(value, Mapping):
        return {str(k): _normalize_for_digest(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize_for_digest(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_normalize_for_digest(v) for v in value), key=lambda item: json.dumps(item, sort_keys=True))
    return thaw_value(value)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize value deterministically to UTF-8 canonical JSON rejecting NaN/Inf."""
    normalized = _normalize_for_digest(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def compute_operation_digest(
    *,
    tool_id: str,
    action: str,
    actor_ref: str,
    state_revision: int,
    terms: Mapping[str, Any] | None = None,
) -> str:
    """Compute canonical SHA-256 operation digest bound to tool, action, actor, revision, and terms."""
    require_safe_id(tool_id, "tool_id")
    if not isinstance(action, str) or not action.strip():
        raise ValueError("action must be non-empty str")
    require_safe_id(actor_ref, "actor_ref")
    require_strict_int(state_revision, "state_revision", minimum=0)
    payload = {
        "tool_id": tool_id,
        "action": action,
        "actor_ref": actor_ref,
        "state_revision": state_revision,
        "terms": dict(terms or {}),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class PrincipalRef:
    principal_id: str
    kind: PrincipalKind
    auth_strength: AuthStrength
    evidence_source: EvidenceSource
    verified: bool = False
    roles: frozenset[str] = frozenset()
    tenant_id: str | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.principal_id, "principal_id")
        if not isinstance(self.kind, PrincipalKind):
            raise ValueError("kind must be PrincipalKind")
        if not isinstance(self.auth_strength, AuthStrength):
            raise ValueError("auth_strength must be AuthStrength")
        if not isinstance(self.evidence_source, EvidenceSource):
            raise ValueError("evidence_source must be EvidenceSource")
        if type(self.verified) is not bool:
            raise ValueError("verified must be bool")
        if self.tenant_id is not None:
            require_safe_id(self.tenant_id, "tenant_id")
        frozen_roles = frozenset(str(r) for r in self.roles if isinstance(r, str) and r.strip())
        object.__setattr__(self, "roles", frozen_roles)

        if self.evidence_source in UNTRUSTED_EVIDENCE_SOURCES:
            if self.verified:
                raise UntrustedAuthorityError(
                    f"Untrusted evidence source {self.evidence_source.value} cannot yield verified principal"
                )
            if self.auth_strength not in {AuthStrength.UNAUTHENTICATED, AuthStrength.UNTRUSTED_HINT}:
                raise UntrustedAuthorityError(
                    f"Untrusted evidence source {self.evidence_source.value} cannot hold auth_strength {self.auth_strength.value}"
                )
        if self.verified:
            if self.kind == PrincipalKind.ANONYMOUS:
                raise SecurityPolicyError("ANONYMOUS principal cannot be marked verified")
            if self.evidence_source not in TRUSTED_EVIDENCE_SOURCES:
                raise UntrustedAuthorityError("Verified principal requires trusted evidence_source")
            if self.auth_strength in {AuthStrength.UNAUTHENTICATED, AuthStrength.UNTRUSTED_HINT}:
                raise SecurityPolicyError("Verified principal requires verified auth_strength")


@dataclass(frozen=True, slots=True)
class AccessContext:
    session_id: str
    principal: PrincipalRef
    channel: str
    state_revision: int
    trace_id: str | None = None
    asr_status: ASRStatus | None = None
    untrusted_claims: tuple[EvidenceSource, ...] = ()
    confirmation_ref: ConfirmationReference | None = None
    scopes: frozenset[str] = frozenset()
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        require_safe_id(self.session_id, "session_id")
        if not isinstance(self.principal, PrincipalRef):
            raise TypeError("principal must be PrincipalRef")
        if not isinstance(self.channel, str) or not self.channel.strip():
            raise ValueError("channel must be non-empty str")
        require_strict_int(self.state_revision, "state_revision", minimum=0)
        if self.trace_id is not None:
            require_safe_id(self.trace_id, "trace_id")
        if self.asr_status is not None and not isinstance(self.asr_status, ASRStatus):
            raise ValueError("asr_status must be ASRStatus")
        if self.confirmation_ref is not None and not isinstance(self.confirmation_ref, ConfirmationReference):
            raise TypeError("confirmation_ref must be ConfirmationReference")
        claims = tuple(self.untrusted_claims)
        for claim in claims:
            if not isinstance(claim, EvidenceSource):
                raise ValueError("untrusted_claims items must be EvidenceSource")
        object.__setattr__(self, "untrusted_claims", claims)
        object.__setattr__(
            self,
            "scopes",
            frozenset(str(s) for s in self.scopes if isinstance(s, str) and s.strip()),
        )
        object.__setattr__(self, "metadata", freeze_value(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    tool_id: str
    tier: ToolAccessTier
    min_auth_strength: AuthStrength
    requires_confirmation: bool = False
    allowed_principal_kinds: frozenset[PrincipalKind] = frozenset({
        PrincipalKind.CUSTOMER,
        PrincipalKind.OPERATOR,
        PrincipalKind.SYSTEM,
    })
    required_roles: frozenset[str] = frozenset()
    required_scopes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        require_safe_id(self.tool_id, "tool_id")
        if not isinstance(self.tier, ToolAccessTier):
            raise ValueError("tier must be ToolAccessTier")
        if not isinstance(self.min_auth_strength, AuthStrength):
            raise ValueError("min_auth_strength must be AuthStrength")
        if type(self.requires_confirmation) is not bool:
            raise ValueError("requires_confirmation must be bool")
        object.__setattr__(self, "allowed_principal_kinds", frozenset(self.allowed_principal_kinds))
        object.__setattr__(self, "required_roles", frozenset(self.required_roles))
        object.__setattr__(self, "required_scopes", frozenset(self.required_scopes))


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    verdict: PolicyVerdict
    tool_id: str
    reason_codes: tuple[str, ...]
    required_auth_strength: AuthStrength | None = None
    requires_confirmation: bool = False
    error: Any = None
    policy_version: str = SECURITY_POLICY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.verdict, PolicyVerdict):
            raise ValueError("verdict must be PolicyVerdict")
        require_safe_id(self.tool_id, "tool_id")
        object.__setattr__(self, "reason_codes", tuple(str(r) for r in self.reason_codes))

    @property
    def allowed(self) -> bool:
        return self.verdict == PolicyVerdict.ALLOW


# Strict PII / secret redaction rules shared across security audit and projections.
_FORBIDDEN_AUDIT_KEYS = frozenset({
    "phone",
    "customer_phone",
    "owner_phone",
    "caller_phone",
    "plate",
    "license_plate",
    "vin",
    "tc",
    "tckn",
    "identity_no",
    "email",
    "address",
    "customer_name",
    "owner_name",
    "full_name",
    "transcript",
    "raw_transcript",
    "normalized_transcript",
    "speech_text",
    "utterance",
    "password",
    "passwd",
    "secret",
    "ami_secret",
    "api_key",
    "token",
    "webhook_token",
    "master_key",
    "signing_key",
    "authorization",
    "auth_header",
    "cookie",
    "private_key",
    "bearer",
    "raw_audio",
    "payload",
})

_SENSITIVE_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<!\w)(?:\+?90|0)\s*\(?[2-5]\d{2}\)?[\s-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\w)"),
    re.compile(r"(?<!\w)\+?\d(?:[\s().-]*\d){8,}(?!\w)"),
    re.compile(r"\b\d{2}\s*[A-Za-zÇĞİÖŞÜçğıöşü]{1,3}\s*\d{2,5}\b"),
    re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-+/=]{8,}\b", re.IGNORECASE),
    re.compile(r"\b(?:sk|pk|tok|key|secret)[_-][A-Za-z0-9._-]{8,}\b", re.IGNORECASE),
)

_SAFE_AUDIT_DETAIL_KEYS = frozenset({
    "tool_id",
    "action",
    "verdict",
    "reason_codes",
    "state",
    "previous_state",
    "next_state",
    "challenge_id",
    "idempotency_key",
    "state_revision",
    "tier",
    "auth_strength",
    "evidence_source",
    "channel",
    "attempt_count",
    "reconcile_attempts",
    "error_code",
    "result_ref",
    "policy_version",
    "provider_mode",
    "status",
    "revocation_reason",
    "sanitized",
})


def redact_sensitive_text(text: str) -> str:
    """Redact phone numbers, plates, VINs, emails, and token/secret patterns."""
    result = text
    for pattern in _SENSITIVE_TEXT_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return redact_sensitive_text(str(value.value))
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(v) for v in value]
    if isinstance(value, Mapping):
        return sanitize_audit_payload(value)
    return redact_sensitive_text(str(value))


def sanitize_audit_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlist and redact metadata so zero raw PII or secrets enter durable audit logs."""
    cleaned: dict[str, Any] = {}
    for raw_key, value in payload.items():
        key = str(raw_key)
        lower = key.lower()
        if lower in _FORBIDDEN_AUDIT_KEYS or any(
            marker in lower for marker in ("secret", "token", "password", "phone", "plate", "vin", "transcript")
        ):
            cleaned[key] = "[REDACTED]"
            continue
        if key in _SAFE_AUDIT_DETAIL_KEYS:
            cleaned[key] = _sanitize_value(value)
        else:
            cleaned[key] = "[FILTERED]"
    return cleaned
