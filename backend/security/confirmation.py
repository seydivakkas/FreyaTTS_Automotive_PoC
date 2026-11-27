"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4

from backend.core.contracts.dialogue import ConfirmationReference
from backend.core.contracts.validation import require_safe_id, require_strict_int, require_utc_iso
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.security.audit import AuditEventKind, SecurityAuditLog
from backend.security.contracts import (
    ConfirmationExpiredError,
    ConfirmationInvalidatedError,
    ConfirmationState,
    ConfirmationStateError,
    compute_operation_digest,
)

_CONFIRMATION_TRANSITIONS: Mapping[ConfirmationState, frozenset[ConfirmationState]] = {
    ConfirmationState.ISSUED: frozenset({
        ConfirmationState.PRESENTED,
        ConfirmationState.REVOKED,
        ConfirmationState.EXPIRED,
    }),
    ConfirmationState.PRESENTED: frozenset({
        ConfirmationState.APPROVED,
        ConfirmationState.REVOKED,
        ConfirmationState.EXPIRED,
    }),
    ConfirmationState.APPROVED: frozenset({
        ConfirmationState.CONSUMED,
        ConfirmationState.REVOKED,
        ConfirmationState.EXPIRED,
    }),
    ConfirmationState.CONSUMED: frozenset(),
    ConfirmationState.REVOKED: frozenset(),
    ConfirmationState.EXPIRED: frozenset(),
}

_TERMINAL_STATES = frozenset({
    ConfirmationState.CONSUMED,
    ConfirmationState.REVOKED,
    ConfirmationState.EXPIRED,
})


@dataclass(frozen=True, slots=True)
class ConfirmationChallenge:
    challenge_id: str
    tool_id: str
    action: str
    operation_digest: str
    state_revision: int
    actor_ref: str
    state: ConfirmationState
    clock_domain: str
    issued_monotonic_ns: int
    expires_monotonic_ns: int
    expires_at_utc: str
    revocation_reason: str | None = None
    presented_monotonic_ns: int | None = None
    approved_monotonic_ns: int | None = None
    consumed_monotonic_ns: int | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.challenge_id, "challenge_id")
        require_safe_id(self.tool_id, "tool_id")
        if not isinstance(self.action, str) or not self.action.strip():
            raise ValueError("action required")
        if not isinstance(self.operation_digest, str) or len(self.operation_digest) != 64:
            raise ValueError("operation_digest must be 64-char SHA-256 hex")
        require_strict_int(self.state_revision, "state_revision", minimum=0)
        require_safe_id(self.actor_ref, "actor_ref")
        if not isinstance(self.state, ConfirmationState):
            raise ValueError("state must be ConfirmationState")
        require_strict_int(self.issued_monotonic_ns, "issued_monotonic_ns", minimum=0)
        require_strict_int(self.expires_monotonic_ns, "expires_monotonic_ns", minimum=self.issued_monotonic_ns)
        require_utc_iso(self.expires_at_utc, "expires_at_utc")

    def to_confirmation_reference(self, *, confirmation_source_id: str | None = None) -> ConfirmationReference:
        """Convert to M01 ConfirmationReference bound to digest, state_revision, actor_ref, and expiry."""
        return ConfirmationReference(
            state_revision=self.state_revision,
            operation_digest=self.operation_digest,
            confirmation_source_id=confirmation_source_id or self.challenge_id,
            expires_at_utc=self.expires_at_utc,
            actor_ref=self.actor_ref,
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConfirmationManager:
    """Manages confirmation challenge lifecycle with canonical digest & slot/terms invalidation."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        utc_now_fn: Callable[[], datetime] = _utc_now,
        default_ttl_ms: int = 120_000,
        audit_log: SecurityAuditLog | None = None,
    ) -> None:
        require_strict_int(default_ttl_ms, "default_ttl_ms", minimum=1)
        self._clock: Clock = clock or SystemMonotonicClock()
        self._utc_now_fn = utc_now_fn
        self._default_ttl_ms = default_ttl_ms
        self._audit_log = audit_log
        self._lock = threading.RLock()
        self._challenges: dict[str, ConfirmationChallenge] = {}

    def _audit(self, challenge: ConfirmationChallenge, action: str, previous_state: ConfirmationState | None) -> None:
        if self._audit_log is None:
            return
        self._audit_log.append(
            kind=AuditEventKind.CONFIRMATION_LIFECYCLE,
            action=action,
            outcome=challenge.state.value,
            actor_ref=challenge.actor_ref,
            operation_digest=challenge.operation_digest,
            details={
                "challenge_id": challenge.challenge_id,
                "tool_id": challenge.tool_id,
                "action": challenge.action,
                "previous_state": previous_state.value if previous_state else None,
                "state": challenge.state.value,
                "state_revision": challenge.state_revision,
                "revocation_reason": challenge.revocation_reason,
            },
        )

    def _transition(
        self,
        challenge: ConfirmationChallenge,
        target: ConfirmationState,
        *,
        now_ns: int,
        reason: str | None = None,
    ) -> ConfirmationChallenge:
        if target not in _CONFIRMATION_TRANSITIONS[challenge.state]:
            raise ConfirmationStateError(
                f"Invalid confirmation transition: {challenge.state.value} -> {target.value}"
            )
        kwargs: dict[str, Any] = {"state": target}
        if target == ConfirmationState.PRESENTED:
            kwargs["presented_monotonic_ns"] = now_ns
        elif target == ConfirmationState.APPROVED:
            kwargs["approved_monotonic_ns"] = now_ns
        elif target == ConfirmationState.CONSUMED:
            kwargs["consumed_monotonic_ns"] = now_ns
        elif target == ConfirmationState.REVOKED:
            kwargs["revocation_reason"] = reason or "revoked"
        elif target == ConfirmationState.EXPIRED:
            kwargs["revocation_reason"] = reason or "expired"
        updated = replace(challenge, **kwargs)
        self._challenges[challenge.challenge_id] = updated
        self._audit(updated, f"confirmation.{target.value.lower()}", challenge.state)
        return updated

    def _expire_if_needed(self, challenge: ConfirmationChallenge, now_ns: int) -> ConfirmationChallenge:
        if challenge.clock_domain != self._clock.clock_domain:
            raise ConfirmationStateError(
                f"Clock domain mismatch: {self._clock.clock_domain} != {challenge.clock_domain}"
            )
        if challenge.state not in _TERMINAL_STATES and now_ns >= challenge.expires_monotonic_ns:
            return self._transition(challenge, ConfirmationState.EXPIRED, now_ns=now_ns, reason="ttl_expired")
        return challenge

    def _require_challenge(self, challenge_id: str) -> tuple[ConfirmationChallenge, int]:
        challenge = self._challenges.get(challenge_id)
        if challenge is None:
            raise ConfirmationStateError(f"Unknown confirmation challenge: {challenge_id}")
        now_ns = self._clock.monotonic_ns()
        challenge = self._expire_if_needed(challenge, now_ns)
        return challenge, now_ns

    def _verify_binding(
        self,
        challenge: ConfirmationChallenge,
        *,
        now_ns: int,
        actor_ref: str,
        state_revision: int,
        terms: Mapping[str, Any] | None = None,
        operation_digest: str | None = None,
    ) -> None:
        mismatch_reason: str | None = None
        if actor_ref != challenge.actor_ref:
            mismatch_reason = "actor_mismatch"
        elif state_revision != challenge.state_revision:
            mismatch_reason = "state_revision_changed"
        else:
            expected_digest = operation_digest
            if terms is not None:
                expected_digest = compute_operation_digest(
                    tool_id=challenge.tool_id,
                    action=challenge.action,
                    actor_ref=actor_ref,
                    state_revision=state_revision,
                    terms=terms,
                )
            if expected_digest is not None and expected_digest != challenge.operation_digest:
                mismatch_reason = "slot_or_terms_changed"

        if mismatch_reason is not None:
            if challenge.state not in _TERMINAL_STATES:
                self._transition(challenge, ConfirmationState.REVOKED, now_ns=now_ns, reason=mismatch_reason)
            raise ConfirmationInvalidatedError(
                f"Confirmation challenge invalidated due to {mismatch_reason}"
            )

    def issue(
        self,
        *,
        tool_id: str,
        action: str,
        actor_ref: str,
        state_revision: int,
        terms: Mapping[str, Any],
        ttl_ms: int | None = None,
        challenge_id: str | None = None,
    ) -> ConfirmationChallenge:
        """Issue a new confirmation challenge bound to canonical SHA-256 digest, revision, actor, and TTL."""
        effective_ttl = self._default_ttl_ms if ttl_ms is None else ttl_ms
        require_strict_int(effective_ttl, "ttl_ms", minimum=1)
        cid = challenge_id or f"cnf-{uuid4().hex[:20]}"
        digest = compute_operation_digest(
            tool_id=tool_id,
            action=action,
            actor_ref=actor_ref,
            state_revision=state_revision,
            terms=terms,
        )
        with self._lock:
            if cid in self._challenges:
                raise ConfirmationStateError(f"Duplicate challenge_id: {cid}")
            now_ns = self._clock.monotonic_ns()
            expires_ns = now_ns + effective_ttl * 1_000_000
            expires_utc = (
                self._utc_now_fn().astimezone(timezone.utc) + timedelta(milliseconds=effective_ttl)
            ).isoformat().replace("+00:00", "Z")
            challenge = ConfirmationChallenge(
                challenge_id=cid,
                tool_id=tool_id,
                action=action,
                operation_digest=digest,
                state_revision=state_revision,
                actor_ref=actor_ref,
                state=ConfirmationState.ISSUED,
                clock_domain=self._clock.clock_domain,
                issued_monotonic_ns=now_ns,
                expires_monotonic_ns=expires_ns,
                expires_at_utc=expires_utc,
            )
            self._challenges[cid] = challenge
            self._audit(challenge, "confirmation.issued", None)
            return challenge

    def present(self, challenge_id: str) -> ConfirmationChallenge:
        """Transition ISSUED -> PRESENTED."""
        with self._lock:
            challenge, now_ns = self._require_challenge(challenge_id)
            if challenge.state == ConfirmationState.EXPIRED:
                raise ConfirmationExpiredError("Confirmation challenge expired before presentation")
            return self._transition(challenge, ConfirmationState.PRESENTED, now_ns=now_ns)

    def approve(
        self,
        challenge_id: str,
        *,
        actor_ref: str,
        state_revision: int,
        terms: Mapping[str, Any] | None = None,
        operation_digest: str | None = None,
    ) -> ConfirmationChallenge:
        """Transition PRESENTED -> APPROVED after validating actor, state_revision, and terms/digest."""
        with self._lock:
            challenge, now_ns = self._require_challenge(challenge_id)
            if challenge.state == ConfirmationState.EXPIRED:
                raise ConfirmationExpiredError("Confirmation challenge expired before approval")
            if challenge.state != ConfirmationState.PRESENTED:
                raise ConfirmationStateError(
                    f"Cannot approve challenge in state {challenge.state.value}; must be PRESENTED"
                )
            self._verify_binding(
                challenge,
                now_ns=now_ns,
                actor_ref=actor_ref,
                state_revision=state_revision,
                terms=terms,
                operation_digest=operation_digest,
            )
            return self._transition(challenge, ConfirmationState.APPROVED, now_ns=now_ns)

    def consume(
        self,
        challenge_id: str,
        *,
        actor_ref: str,
        state_revision: int,
        terms: Mapping[str, Any] | None = None,
        operation_digest: str | None = None,
    ) -> ConfirmationChallenge:
        """Single-use transition APPROVED -> CONSUMED after verifying binding."""
        with self._lock:
            challenge, now_ns = self._require_challenge(challenge_id)
            if challenge.state == ConfirmationState.EXPIRED:
                raise ConfirmationExpiredError("Confirmation challenge expired before consumption")
            if challenge.state != ConfirmationState.APPROVED:
                raise ConfirmationStateError(
                    f"Cannot consume challenge in state {challenge.state.value}; must be APPROVED"
                )
            self._verify_binding(
                challenge,
                now_ns=now_ns,
                actor_ref=actor_ref,
                state_revision=state_revision,
                terms=terms,
                operation_digest=operation_digest,
            )
            return self._transition(challenge, ConfirmationState.CONSUMED, now_ns=now_ns)

    def revoke(self, challenge_id: str, reason: str = "revoked") -> ConfirmationChallenge:
        """Explicitly revoke a non-terminal challenge."""
        with self._lock:
            challenge, now_ns = self._require_challenge(challenge_id)
            if challenge.state == ConfirmationState.EXPIRED:
                return challenge
            return self._transition(challenge, ConfirmationState.REVOKED, now_ns=now_ns, reason=reason)

    def invalidate_if_changed(
        self,
        challenge_id: str,
        *,
        actor_ref: str,
        state_revision: int,
        terms: Mapping[str, Any],
    ) -> ConfirmationChallenge:
        """Revoke challenge if actor, state_revision, or slot/terms changed; return current snapshot."""
        with self._lock:
            challenge, now_ns = self._require_challenge(challenge_id)
            if challenge.state in _TERMINAL_STATES:
                return challenge
            try:
                self._verify_binding(
                    challenge,
                    now_ns=now_ns,
                    actor_ref=actor_ref,
                    state_revision=state_revision,
                    terms=terms,
                )
            except ConfirmationInvalidatedError:
                return self._challenges[challenge_id]
            return challenge

    def get(self, challenge_id: str) -> ConfirmationChallenge | None:
        """Fetch challenge snapshot, updating state to EXPIRED if clock elapsed past TTL."""
        with self._lock:
            challenge = self._challenges.get(challenge_id)
            if challenge is None:
                return None
            return self._expire_if_needed(challenge, self._clock.monotonic_ns())
