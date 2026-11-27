"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from backend.core.contracts.common import ErrorCategory, Retryability
from backend.core.contracts.dialogue import ProviderMode, ToolReceiptStatus
from backend.core.contracts.recognition import ASRStatus
from backend.core.runtime.deadlines import FakeClock
from backend.security import (
    AccessContext,
    AuditEventKind,
    AuthStrength,
    ClaimOutcome,
    ConfirmationExpiredError,
    ConfirmationInvalidatedError,
    ConfirmationManager,
    ConfirmationState,
    ConfirmationStateError,
    DurableIdempotencyStore,
    EvidenceSource,
    IdempotencyConflictError,
    IdempotencyReconciler,
    IdempotencyState,
    IdempotencyStateError,
    PolicyEngine,
    PolicyVerdict,
    PrincipalKind,
    PrincipalRef,
    ReconciliationProbeResult,
    ReconciliationVerdict,
    SecurityAuditLog,
    SecurityPolicyError,
    ToolAccessTier,
    ToolPolicy,
    UntrustedAuthorityError,
    anonymous_principal,
    challenge_to_confirmed_write,
    compute_operation_digest,
    confirmed_write_to_confirmation_reference,
    confirmed_write_to_tool_receipt,
    untrusted_principal,
    verified_principal,
    write_outcome_to_tool_receipt,
)


def test_passive_imports_never_open_db_or_read_env():
    """Importing backend.security in a clean interpreter must not load backend.db or dotenv."""
    code = (
        "import sys; "
        "import backend.security; "
        "import backend.security.legacy_gateway_adapter; "
        "assert 'backend.db' not in sys.modules, 'backend.db was imported'; "
        "assert 'backend.supervisor.gateway' not in sys.modules, 'gateway was imported'; "
        "assert 'dotenv' not in sys.modules, 'dotenv was imported'; "
        "print('PASSIVE_OK')"
    )
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert "PASSIVE_OK" in proc.stdout


@pytest.mark.parametrize(
    "source",
    [
        EvidenceSource.ASR_PARTIAL,
        EvidenceSource.ASR_STABLE,
        EvidenceSource.ASR_FINAL,
        EvidenceSource.CALLER_ID,
        EvidenceSource.PLATE_TEXT,
        EvidenceSource.LLM_OUTPUT,
        EvidenceSource.RAG_TEXT,
        EvidenceSource.UNVERIFIED_HEADER,
    ],
)
def test_untrusted_sources_cannot_construct_verified_principal_or_authorize(source: EvidenceSource):
    with pytest.raises(UntrustedAuthorityError):
        PrincipalRef(
            principal_id="cust-001",
            kind=PrincipalKind.CUSTOMER,
            auth_strength=AuthStrength.CHANNEL_VERIFIED,
            evidence_source=source,
            verified=True,
        )

    untrusted = untrusted_principal("cust-001", evidence_source=source)
    ctx = AccessContext(
        session_id="sess-1",
        trace_id="trace-1",
        principal=untrusted,
        channel="telephony",
        state_revision=1,
        asr_status=ASRStatus.FINAL,
        untrusted_claims=(source,),
    )
    engine = PolicyEngine()
    for tool_id in ("booking.read_status", "customer.read_record", "booking.create", "booking.cancel"):
        decision = engine.evaluate(ctx, tool_id)
        assert not decision.allowed
        assert decision.verdict in {PolicyVerdict.DENY, PolicyVerdict.CHALLENGE}


def test_policy_engine_fail_closed_verdicts_allow_deny_challenge_hold(tmp_path: Path):
    audit = SecurityAuditLog(tmp_path / "audit.db")
    engine = PolicyEngine(audit_log=audit)

    # 1. Unknown tool -> DENY
    verified_cust = verified_principal(
        "cust-123",
        kind=PrincipalKind.CUSTOMER,
        auth_strength=AuthStrength.STRONG_VERIFIED,
        evidence_source=EvidenceSource.MFA_VERIFIED,
    )
    ctx = AccessContext(
        session_id="sess-100",
        trace_id="trace-100",
        principal=verified_cust,
        channel="web",
        state_revision=3,
        asr_status=ASRStatus.FINAL,
    )
    unknown = engine.evaluate(ctx, "nonexistent.mutation")
    assert unknown.verdict == PolicyVerdict.DENY
    assert unknown.error is not None and unknown.error.category == ErrorCategory.SECURITY

    # 2. Partial or stable ASR -> HOLD for protected reads & mutations
    for asr_state in (ASRStatus.PARTIAL, ASRStatus.STABLE_PREFIX):
        hold_ctx = AccessContext(
            session_id="sess-100",
            trace_id="trace-100",
            principal=verified_cust,
            channel="telephony",
            state_revision=3,
            asr_status=asr_state,
        )
        assert engine.evaluate(hold_ctx, "booking.read_status").verdict == PolicyVerdict.HOLD
        assert engine.evaluate(hold_ctx, "booking.create").verdict == PolicyVerdict.HOLD

    # 3. Anonymous unauthenticated -> PUBLIC_READ ALLOW, protected -> CHALLENGE
    anon_ctx = AccessContext(
        session_id="sess-anon",
        principal=anonymous_principal(),
        channel="web",
        state_revision=0,
    )
    assert engine.evaluate(anon_ctx, "vehicle.read_specs").verdict == PolicyVerdict.ALLOW
    assert engine.evaluate(anon_ctx, "booking.read_status").verdict == PolicyVerdict.CHALLENGE

    # 4. Channel verified without strong auth -> booking.cancel CHALLENGE
    weak_cust = verified_principal(
        "cust-123",
        kind=PrincipalKind.CUSTOMER,
        auth_strength=AuthStrength.CHANNEL_VERIFIED,
        evidence_source=EvidenceSource.OTP_CHALLENGE,
    )
    weak_ctx = AccessContext(
        session_id="sess-100",
        principal=weak_cust,
        channel="whatsapp",
        state_revision=3,
    )
    assert engine.evaluate(weak_ctx, "booking.read_status").verdict == PolicyVerdict.ALLOW
    assert engine.evaluate(weak_ctx, "booking.cancel").verdict == PolicyVerdict.CHALLENGE

    # 5. Role & scope enforcement
    engine.register_policy(
        ToolPolicy(
            tool_id="admin.override",
            tier=ToolAccessTier.ADMIN,
            min_auth_strength=AuthStrength.STRONG_VERIFIED,
            allowed_principal_kinds=frozenset({PrincipalKind.OPERATOR}),
            required_roles=frozenset({"supervisor"}),
            required_scopes=frozenset({"write:override"}),
        )
    )
    assert engine.evaluate(ctx, "admin.override").verdict == PolicyVerdict.DENY
    op = verified_principal(
        "op-1",
        kind=PrincipalKind.OPERATOR,
        auth_strength=AuthStrength.STRONG_VERIFIED,
        evidence_source=EvidenceSource.OPERATOR_SESSION,
        roles=("supervisor",),
    )
    op_ctx_no_scope = AccessContext(
        session_id="sess-op",
        principal=op,
        channel="internal",
        state_revision=1,
    )
    assert engine.evaluate(op_ctx_no_scope, "admin.override").verdict == PolicyVerdict.DENY
    op_ctx_ok = AccessContext(
        session_id="sess-op",
        principal=op,
        channel="internal",
        state_revision=1,
        scopes=frozenset({"write:override"}),
    )
    assert engine.evaluate(op_ctx_ok, "admin.override").verdict == PolicyVerdict.ALLOW
    assert audit.verify_chain()


def test_confirmation_lifecycle_digest_binding_expiry_and_invalidation(tmp_path: Path):
    clock = FakeClock(initial_ns=1_000_000_000)
    audit = SecurityAuditLog(tmp_path / "audit.db")
    mgr = ConfirmationManager(clock=clock, default_ttl_ms=5_000, audit_log=audit)

    terms = {"slot_id": "slot-2026-11-30-0900", "vehicle_id": "veh-3008", "package": "standart"}
    c1 = mgr.issue(
        tool_id="booking.create",
        action="create_booking",
        actor_ref="cust-42",
        state_revision=7,
        terms=terms,
    )
    assert c1.state == ConfirmationState.ISSUED
    assert len(c1.operation_digest) == 64

    # Cannot skip PRESENTED -> APPROVED
    with pytest.raises(ConfirmationStateError):
        mgr.approve(c1.challenge_id, actor_ref="cust-42", state_revision=7, terms=terms)

    c1_p = mgr.present(c1.challenge_id)
    assert c1_p.state == ConfirmationState.PRESENTED

    c1_a = mgr.approve(c1.challenge_id, actor_ref="cust-42", state_revision=7, terms=terms)
    assert c1_a.state == ConfirmationState.APPROVED

    # PolicyEngine integrates with ConfirmationReference
    engine = PolicyEngine(audit_log=audit)
    principal = verified_principal(
        "cust-42",
        kind=PrincipalKind.CUSTOMER,
        auth_strength=AuthStrength.CHANNEL_VERIFIED,
        evidence_source=EvidenceSource.OTP_CHALLENGE,
    )
    ctx_with_conf = AccessContext(
        session_id="sess-42",
        principal=principal,
        channel="web",
        state_revision=7,
        asr_status=ASRStatus.FINAL,
        confirmation_ref=c1_a.to_confirmation_reference(),
    )
    assert engine.evaluate(
        ctx_with_conf,
        "booking.create",
        operation_digest=c1_a.operation_digest,
        confirmation_approved=True,
    ).verdict == PolicyVerdict.ALLOW

    # Mismatched operation_digest in PolicyEngine -> DENY
    bad_digest = compute_operation_digest(
        tool_id="booking.create",
        action="create_booking",
        actor_ref="cust-42",
        state_revision=7,
        terms={"slot_id": "slot-CHANGED", "vehicle_id": "veh-3008", "package": "standart"},
    )
    assert engine.evaluate(
        ctx_with_conf,
        "booking.create",
        operation_digest=bad_digest,
        confirmation_approved=True,
    ).verdict == PolicyVerdict.DENY

    # Single-use consume
    c1_c = mgr.consume(c1.challenge_id, actor_ref="cust-42", state_revision=7, terms=terms)
    assert c1_c.state == ConfirmationState.CONSUMED
    with pytest.raises(ConfirmationStateError):
        mgr.consume(c1.challenge_id, actor_ref="cust-42", state_revision=7, terms=terms)

    # Slot/terms change invalidates -> REVOKED
    c2 = mgr.issue(
        tool_id="booking.create",
        action="create_booking",
        actor_ref="cust-42",
        state_revision=8,
        terms=terms,
    )
    mgr.present(c2.challenge_id)
    with pytest.raises(ConfirmationInvalidatedError):
        mgr.approve(
            c2.challenge_id,
            actor_ref="cust-42",
            state_revision=8,
            terms={**terms, "slot_id": "slot-DIFFERENT"},
        )
    assert mgr.get(c2.challenge_id).state == ConfirmationState.REVOKED

    # State revision change invalidates -> REVOKED
    c3 = mgr.issue(
        tool_id="booking.create",
        action="create_booking",
        actor_ref="cust-42",
        state_revision=9,
        terms=terms,
    )
    mgr.present(c3.challenge_id)
    revoked = mgr.invalidate_if_changed(
        c3.challenge_id,
        actor_ref="cust-42",
        state_revision=10,
        terms=terms,
    )
    assert revoked.state == ConfirmationState.REVOKED

    # TTL expiry -> EXPIRED
    c4 = mgr.issue(
        tool_id="booking.create",
        action="create_booking",
        actor_ref="cust-42",
        state_revision=11,
        terms=terms,
        ttl_ms=1_000,
    )
    mgr.present(c4.challenge_id)
    clock.advance_ms(1_000)
    with pytest.raises(ConfirmationExpiredError):
        mgr.approve(c4.challenge_id, actor_ref="cust-42", state_revision=11, terms=terms)
    assert mgr.get(c4.challenge_id).state == ConfirmationState.EXPIRED
    assert audit.verify_chain()


def test_durable_idempotency_store_wal_transitions_and_unknown_never_autoretries(tmp_path: Path):
    db_path = tmp_path / "idempotency.db"
    audit = SecurityAuditLog(tmp_path / "audit.db")
    store = DurableIdempotencyStore(db_path, audit_log=audit)

    # Verify SQLite WAL mode is enabled
    with sqlite3.connect(str(db_path)) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"

    digest_a = compute_operation_digest(
        tool_id="booking.create",
        action="create_booking",
        actor_ref="cust-77",
        state_revision=1,
        terms={"slot_id": "s1"},
    )
    digest_b = compute_operation_digest(
        tool_id="booking.create",
        action="create_booking",
        actor_ref="cust-77",
        state_revision=1,
        terms={"slot_id": "s2"},
    )

    # Concurrent claim race: only one caller acquires CLAIMED, other sees IN_FLIGHT
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: store.claim(
                    "idem-race-1",
                    tool_id="booking.create",
                    action="create_booking",
                    actor_ref="cust-77",
                    operation_digest=digest_a,
                ),
                range(4),
            )
        )
    assert sum(1 for r in results if r.acquired) == 1
    assert sum(1 for r in results if not r.acquired and r.outcome == ClaimOutcome.IN_FLIGHT) == 3

    # Same key with different digest is rejected fail-closed
    with pytest.raises(IdempotencyConflictError):
        store.claim(
            "idem-race-1",
            tool_id="booking.create",
            action="create_booking",
            actor_ref="cust-77",
            operation_digest=digest_b,
        )

    # COMMITTED prevents re-execution
    committed = store.mark_committed("idem-race-1", operation_digest=digest_a, result_ref="appt-001")
    assert committed.state == IdempotencyState.COMMITTED
    replay = store.claim(
        "idem-race-1",
        tool_id="booking.create",
        action="create_booking",
        actor_ref="cust-77",
        operation_digest=digest_a,
    )
    assert not replay.acquired
    assert replay.outcome == ClaimOutcome.ALREADY_COMMITTED
    assert replay.record.result_ref == "appt-001"

    # BLOCKED and FAILED_CONFIRMED transitions
    store.claim("idem-blk", tool_id="booking.cancel", action="cancel", actor_ref="cust-77", operation_digest=digest_a)
    blk = store.mark_blocked("idem-blk", operation_digest=digest_a, error_code="policy.denied")
    assert blk.state == IdempotencyState.BLOCKED
    assert store.claim("idem-blk", tool_id="booking.cancel", action="cancel", actor_ref="cust-77", operation_digest=digest_a).outcome == ClaimOutcome.ALREADY_BLOCKED

    store.claim("idem-fail", tool_id="booking.cancel", action="cancel", actor_ref="cust-77", operation_digest=digest_a)
    failed = store.mark_failed_confirmed("idem-fail", operation_digest=digest_a, error_code="slot.not_found")
    assert failed.state == IdempotencyState.FAILED_CONFIRMED
    assert store.claim("idem-fail", tool_id="booking.cancel", action="cancel", actor_ref="cust-77", operation_digest=digest_a).outcome == ClaimOutcome.ALREADY_FAILED_CONFIRMED

    # UNKNOWN NEVER auto-retries; only explicit reconciliation transitions UNKNOWN -> RECONCILING
    store.claim("idem-unk", tool_id="booking.create", action="create_booking", actor_ref="cust-77", operation_digest=digest_a)
    unk = store.mark_unknown("idem-unk", operation_digest=digest_a, error_code="gateway.timeout")
    assert unk.state == IdempotencyState.UNKNOWN

    for _ in range(3):
        retry_attempt = store.claim(
            "idem-unk",
            tool_id="booking.create",
            action="create_booking",
            actor_ref="cust-77",
            operation_digest=digest_a,
        )
        assert not retry_attempt.acquired
        assert retry_attempt.outcome == ClaimOutcome.UNKNOWN_HOLD
        assert retry_attempt.record.state == IdempotencyState.UNKNOWN

    # Cannot jump directly to COMMITTED from UNKNOWN without RECONCILING
    with pytest.raises(IdempotencyStateError):
        store.mark_committed("idem-unk", operation_digest=digest_a, result_ref="appt-bad")

    # Reconciler settles UNKNOWN -> RECONCILING -> COMMITTED / FAILED_CONFIRMED / UNKNOWN
    reconciler = IdempotencyReconciler(store, audit_log=audit)

    # Probe failure keeps record in UNKNOWN fail-closed
    def failing_probe(_rec):
        raise RuntimeError("upstream unavailable")

    r_err = reconciler.reconcile_one("idem-unk", failing_probe)
    assert r_err.final_state == IdempotencyState.UNKNOWN
    assert store.get("idem-unk").reconcile_attempts == 1

    # Successful probe commits
    reports = reconciler.reconcile_pending(
        lambda rec: ReconciliationProbeResult(
            verdict=ReconciliationVerdict.CONFIRMED_COMMITTED,
            result_ref="appt-reconciled-9",
        )
    )
    assert len(reports) == 1
    assert reports[0].final_state == IdempotencyState.COMMITTED
    assert store.get("idem-unk").result_ref == "appt-reconciled-9"
    assert store.get("idem-unk").reconcile_attempts == 2
    assert audit.verify_chain()


def test_security_audit_log_redacts_pii_secrets_and_survives_lossy_observer(tmp_path: Path):
    dropped_observer_calls = 0

    def failing_lossy_bus(_event):
        nonlocal dropped_observer_calls
        dropped_observer_calls += 1
        raise BufferError("M04 bounded bus queue full")

    db_path = tmp_path / "security_audit.db"
    audit = SecurityAuditLog(db_path, observer_sink=failing_lossy_bus)

    entry = audit.append(
        kind=AuditEventKind.SECURITY_VIOLATION,
        action="auth.rejected for +90 555 123 45 67",
        outcome="DENY",
        actor_ref="0555 123 45 67",
        session_id="sess-audit-1",
        trace_id="trace-audit-1",
        details={
            "tool_id": "booking.create",
            "phone": "+90 555 123 45 67",
            "plate": "34 ABC 123",
            "vin": "VF3MJAHXVKS123456",
            "transcript": "Randevumu iptal edin plakam 34 ABC 123",
            "api_key": "sk-supersecret123456",
            "ami_secret": "test-ami-secret",
            "webhook_token": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
            "error_code": "Bearer secret_token_xyz987",
            "arbitrary_raw": "secret@example.com",
        },
    )
    assert dropped_observer_calls == 1
    assert audit.count() == 1
    assert entry.actor_ref == "[REDACTED]"

    raw_bytes = json.dumps(
        {
            "action": entry.action,
            "actor_ref": entry.actor_ref,
            "details": dict(entry.details),
        },
        ensure_ascii=False,
    )
    for forbidden in (
        "555 123 45 67",
        "34 ABC 123",
        "VF3MJAHXVKS123456",
        "Randevumu iptal",
        "sk-supersecret123456",
        "test-ami-secret",
        "eyJhbGciOiJIUzI1NiJ9",
        "secret_token_xyz987",
        "secret@example.com",
    ):
        assert forbidden not in raw_bytes
    assert audit.verify_chain()


def test_legacy_gateway_adapter_bridges_confirmed_write_and_outcomes(tmp_path: Path):
    clock = FakeClock(initial_ns=5_000_000_000)
    mgr = ConfirmationManager(clock=clock)
    terms = {"booking_id": "slot-test"}
    ch = mgr.issue(
        tool_id="booking.cancel",
        action="cancel_booking",
        actor_ref="owner-1",
        state_revision=2,
        terms=terms,
    )
    mgr.present(ch.challenge_id)
    approved = mgr.approve(ch.challenge_id, actor_ref="owner-1", state_revision=2, terms=terms)

    idem_id = uuid4()
    trace_id = uuid4()
    grant = challenge_to_confirmed_write(approved, idempotency_key=idem_id, trace_id=trace_id)
    assert grant.action == "cancel_booking"
    assert grant.request_digest == approved.operation_digest
    assert grant.verified_customer_id == "owner-1"

    # Non-approved challenge cannot be converted to ConfirmedWrite
    with pytest.raises(SecurityPolicyError):
        challenge_to_confirmed_write(ch, idempotency_key=idem_id, trace_id=trace_id)

    conf_ref = confirmed_write_to_confirmation_reference(grant, state_revision=2)
    assert conf_ref.operation_digest == approved.operation_digest
    assert conf_ref.actor_ref == "owner-1"

    applied_real = confirmed_write_to_tool_receipt(
        grant, "applied", provider_mode=ProviderMode.REAL, verified_result=True
    )
    assert applied_real.status == ToolReceiptStatus.COMMITTED
    assert applied_real.is_committed_real

    applied_mock = confirmed_write_to_tool_receipt(
        grant, "applied", provider_mode=ProviderMode.MOCK, verified_result=True
    )
    assert applied_mock.status == ToolReceiptStatus.COMMITTED
    assert not applied_mock.verified_result

    dup = confirmed_write_to_tool_receipt(grant, "duplicate", provider_mode=ProviderMode.REAL, verified_result=True)
    assert dup.status == ToolReceiptStatus.COMMITTED
    assert dup.evidence_ref == f"idempotency:{idem_id}"

    denied = confirmed_write_to_tool_receipt(grant, "denied")
    assert denied.status == ToolReceiptStatus.BLOCKED
    assert denied.error is not None and denied.error.category == ErrorCategory.SECURITY

    state_changed = confirmed_write_to_tool_receipt(grant, "state_changed")
    assert state_changed.status == ToolReceiptStatus.BLOCKED
    assert state_changed.error is not None and state_changed.error.category == ErrorCategory.STALE_SCOPE

    timeout = confirmed_write_to_tool_receipt(grant, "timeout")
    assert timeout.status == ToolReceiptStatus.UNKNOWN
    assert timeout.error is not None and timeout.error.retryable == Retryability.UNKNOWN

    unavailable = write_outcome_to_tool_receipt(
        operation_id="op-99",
        action="create_booking",
        outcome="unavailable",
    )
    assert unavailable.status == ToolReceiptStatus.FAILED
    assert unavailable.error is not None and unavailable.error.retryable == Retryability.YES

    failed = write_outcome_to_tool_receipt(
        operation_id="op-100",
        action="create_booking",
        outcome="failed",
    )
    assert failed.status == ToolReceiptStatus.FAILED
    assert failed.tool_id == "supervisor.create_booking"
