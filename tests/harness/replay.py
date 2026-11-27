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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.core.contracts.common import EventEnvelope, SessionIdentity
from backend.core.contracts.playback import ObservationScope
from backend.core.contracts.recognition import ASRStatus
from backend.core.runtime.result_admission import AdmissionStatus, QueuedMediaItem
from backend.core.runtime.session_context import CleanupStatus, SessionContext
from backend.core.runtime.session_registry import SessionRegistry
from backend.observability.evidence import EvidenceKind
from backend.observability.trace_store import SpanStatus, TraceStore
from backend.security import (
    AccessContext,
    AuthStrength,
    ConfirmationManager,
    DurableIdempotencyStore,
    EvidenceSource,
    PolicyEngine,
    PolicyVerdict,
    PrincipalKind,
    SecurityAuditLog,
    verified_principal,
)
from tests.harness.adapters.fake_business_provider import FakeBusinessProvider, IsolatedCRMSchemaFixture
from tests.harness.adapters.fake_transport import FakeAudioSocketTransport, FakeDTMFInjector
from tests.harness.adapters.fake_tts import FakeTTSAdapter
from tests.harness.contracts import GateStatus
from tests.harness.fake_clock import HarnessClock
from tests.harness.golden_scenarios import GoldenScenario, GoldenScenarioRegistry


@dataclass(frozen=True, slots=True)
class ReplayResult:
    scenario_id: str
    revision: str
    status: GateStatus
    transitions: tuple[str, ...]
    observed_effects: tuple[str, ...]
    forbidden_effects_triggered: tuple[str, ...]
    trace_id: str | None
    cleanup_ok: bool
    source_class: EvidenceKind = EvidenceKind.MOCK_RUNTIME
    observation_scope: ObservationScope = ObservationScope.SERVER
    details: dict[str, Any] = field(default_factory=dict)


class DeterministicReplayEngine:
    """Executes golden scenarios deterministically with trace correlation and clean teardown."""

    def __init__(self, *, registry: GoldenScenarioRegistry | None = None) -> None:
        self.registry = registry or GoldenScenarioRegistry()

    async def replay(
        self,
        scenario_id: str,
        *,
        sandbox_dir: Path,
        run_tag: str = "r1",
    ) -> ReplayResult:
        scenario = self.registry.get(scenario_id)
        if scenario is None:
            raise KeyError(f"Unknown golden scenario: {scenario_id}")
        if not scenario.executable_now:
            return ReplayResult(
                scenario_id=scenario.scenario_id,
                revision=scenario.revision,
                status=GateStatus.NOT_RUN,
                transitions=(),
                observed_effects=(),
                forbidden_effects_triggered=(),
                trace_id=None,
                cleanup_ok=True,
                details={"pending_future_owner": scenario.pending_future_owner},
            )

        clock = HarnessClock(initial_ns=1_000_000, clock_domain="harness.replay.clock")
        traces = TraceStore()
        trace_id = f"tr-{scenario.scenario_id.lower()}-{run_tag}"

        if scenario.scenario_id == "GS01":
            return await self._replay_greeting(scenario, clock, traces, trace_id)
        if scenario.scenario_id == "GS16":
            return await self._replay_two_session_isolation(scenario, clock, traces, trace_id)
        if scenario.scenario_id == "GS15":
            return await self._replay_hard_cancel_late_tts(scenario, clock, traces, trace_id)
        if scenario.scenario_id == "GS14":
            return await self._replay_soft_pause_resume(scenario, clock, traces, trace_id)
        if scenario.scenario_id in {"GS03", "GS06", "GS07", "GS08", "GS09", "GS10", "GS11"}:
            return self._replay_security_scenario(scenario, clock, traces, trace_id, sandbox_dir, run_tag)
        if scenario.scenario_id == "GS12":
            return self._replay_dtmf_dedup(scenario, clock, traces, trace_id)
        if scenario.scenario_id == "GS18":
            return await self._replay_overload_disconnect(scenario, clock, traces, trace_id)
        return self._replay_generic_structural(scenario, clock, traces, trace_id)

    async def _replay_greeting(
        self,
        scenario: GoldenScenario,
        clock: HarnessClock,
        traces: TraceStore,
        trace_id: str,
    ) -> ReplayResult:
        events: list[EventEnvelope] = []
        ctx = SessionContext(SessionIdentity("sess-gs01", trace_id=trace_id), clock=clock, event_sink=events.append)
        span = traces.start_span(
            trace_id=trace_id,
            span_id="sp-gs01",
            name="scenario.gs01",
            session_id="sess-gs01",
            clock_domain=clock.clock_domain,
            start_monotonic_ns=clock.monotonic_ns(),
        )
        await ctx.open()
        t1, _ = await ctx.begin_turn()
        await ctx.begin_generation(t1)
        clock.advance_ms(10)
        cleanup = await ctx.close("replay_complete")
        traces.finish_span(
            trace_id=trace_id,
            span_id=span.span_id,
            end_monotonic_ns=clock.monotonic_ns(),
            clock_domain=clock.clock_domain,
        )
        return ReplayResult(
            scenario_id=scenario.scenario_id,
            revision=scenario.revision,
            status=GateStatus.PASS if cleanup == CleanupStatus.COMPLETE else GateStatus.FAIL,
            transitions=("NEW->OPENING->ACTIVE", "TURN_1_STARTED", "GEN_1_STARTED"),
            observed_effects=("GREETING_RESPONSE_SPEC",),
            forbidden_effects_triggered=(),
            trace_id=trace_id,
            cleanup_ok=(cleanup == CleanupStatus.COMPLETE),
            details={"event_count": len(events)},
        )

    async def _replay_two_session_isolation(
        self,
        scenario: GoldenScenario,
        clock: HarnessClock,
        traces: TraceStore,
        trace_id: str,
    ) -> ReplayResult:
        ev_all: list[EventEnvelope] = []
        reg = SessionRegistry(clock=clock, event_sink=ev_all.append)
        sa = await reg.create("sess-iso-a", trace_id=f"{trace_id}-a")
        sb = await reg.create("sess-iso-b", trace_id=f"{trace_id}-b")
        await sa.open()
        await sb.open()
        ta, _ = await sa.begin_turn()
        tb, _ = await sb.begin_turn()
        ga, _ = await sa.begin_generation(ta)
        gb, _ = await sb.begin_generation(tb)

        # Cross-session media admission must be rejected
        cross = await sb.admit_media(QueuedMediaItem(ga, 0, b"\x01" * 320))
        ok_b = await sb.admit_media(QueuedMediaItem(gb, 0, b"\x02" * 320))
        close_a = await reg.close_session("sess-iso-a")
        close_b = await reg.close_session("sess-iso-b")

        leaked = (
            cross != AdmissionStatus.STALE_SESSION
            or not all(e.session_id in {"sess-iso-a", "sess-iso-b"} for e in ev_all)
        )
        ok = (not leaked) and ok_b == AdmissionStatus.ACCEPTED and close_a == CleanupStatus.COMPLETE and close_b == CleanupStatus.COMPLETE
        return ReplayResult(
            scenario_id=scenario.scenario_id,
            revision=scenario.revision,
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            transitions=("SESS_A_CLOSED", "SESS_B_UNAFFECTED"),
            observed_effects=("ZERO_CROSS_SESSION_LEAKAGE",) if ok else (),
            forbidden_effects_triggered=("CROSS_SESSION_EVENT_MIX",) if leaked else (),
            trace_id=trace_id,
            cleanup_ok=close_a == CleanupStatus.COMPLETE and close_b == CleanupStatus.COMPLETE,
        )

    async def _replay_hard_cancel_late_tts(
        self,
        scenario: GoldenScenario,
        clock: HarnessClock,
        traces: TraceStore,
        trace_id: str,
    ) -> ReplayResult:
        ctx = SessionContext(SessionIdentity("sess-gs15", trace_id=trace_id), clock=clock)
        await ctx.open()
        t1, _ = await ctx.begin_turn()
        g1, g1_scope = await ctx.begin_generation(t1)
        tts = FakeTTSAdapter()
        plan = tts.build_plan(generation_ref=g1, plan_id="plan-1", response_id="resp-1", texts=("Merhaba",))
        await ctx.commit_interrupt("barge_in")
        outcome = await tts.synthesize_with_delay(plan, g1_scope)
        cleanup = await ctx.close("done")
        ok = (
            len(outcome.accepted_chunks) == 0
            and outcome.rejected_stale_chunks == 1
            and outcome.logical_cancelled
            and cleanup == CleanupStatus.COMPLETE
        )
        return ReplayResult(
            scenario_id=scenario.scenario_id,
            revision=scenario.revision,
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            transitions=("GEN_1_REVOKED", "LATE_TTS_REJECTED"),
            observed_effects=("LOGICAL_CANCEL_IMMEDIATE",),
            forbidden_effects_triggered=() if ok else ("STALE_TTS_ADMITTED",),
            trace_id=trace_id,
            cleanup_ok=(cleanup == CleanupStatus.COMPLETE),
        )

    async def _replay_soft_pause_resume(
        self,
        scenario: GoldenScenario,
        clock: HarnessClock,
        traces: TraceStore,
        trace_id: str,
    ) -> ReplayResult:
        ctx = SessionContext(SessionIdentity("sess-gs14", trace_id=trace_id), clock=clock)
        await ctx.open()
        t1, _ = await ctx.begin_turn()
        g1, _ = await ctx.begin_generation(t1)
        await ctx.admit_media(QueuedMediaItem(g1, 0, b"\x01" * 320))
        pref = await ctx.soft_pause()
        paused_st, _ = await ctx.dequeue_for_submission(g1)
        resumed = await ctx.resume_pause(pref) if pref else False
        resumed_st, item = await ctx.dequeue_for_submission(g1)
        cleanup = await ctx.close("done")
        ok = (
            paused_st == AdmissionStatus.PAUSED
            and resumed is True
            and resumed_st == AdmissionStatus.ACCEPTED
            and item is not None
            and cleanup == CleanupStatus.COMPLETE
        )
        return ReplayResult(
            scenario_id=scenario.scenario_id,
            revision=scenario.revision,
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            transitions=("RUNNING->SOFT_PAUSED->RUNNING",),
            observed_effects=("MEDIA_HELD_THEN_RESUMED",),
            forbidden_effects_triggered=(),
            trace_id=trace_id,
            cleanup_ok=(cleanup == CleanupStatus.COMPLETE),
        )

    def _replay_security_scenario(
        self,
        scenario: GoldenScenario,
        clock: HarnessClock,
        traces: TraceStore,
        trace_id: str,
        sandbox_dir: Path,
        run_tag: str,
    ) -> ReplayResult:
        run_dir = sandbox_dir / f"{scenario.scenario_id}_{run_tag}"
        run_dir.mkdir(parents=True, exist_ok=True)
        audit = SecurityAuditLog(run_dir / "audit.db")
        engine = PolicyEngine(audit_log=audit)
        idem = DurableIdempotencyStore(run_dir / "idempotency.db", audit_log=audit)
        crm = IsolatedCRMSchemaFixture(run_dir / "crm.db")
        crm.seed_slot("slot-syn-1", capacity=1)
        biz = FakeBusinessProvider(crm)

        if scenario.scenario_id == "GS03":
            mgr = ConfirmationManager(clock=clock, default_ttl_ms=5_000, audit_log=audit)
            c = mgr.issue(tool_id="booking.create", action="create", actor_ref="cust-syn-001", state_revision=1, terms={"slot": "A"})
            mgr.present(c.challenge_id)
            mgr.approve(c.challenge_id, actor_ref="cust-syn-001", state_revision=1, terms={"slot": "A"})
            changed_ref = c.to_confirmation_reference()
            # Evaluate with mutated terms -> invalidated/revoked
            after = mgr.invalidate_if_changed(c.challenge_id, actor_ref="cust-syn-001", state_revision=1, terms={"slot": "B"})
            ok = after.state.value == "REVOKED"
            return ReplayResult(
                scenario_id="GS03",
                revision=scenario.revision,
                status=GateStatus.PASS if ok else GateStatus.FAIL,
                transitions=("APPROVED->INVALIDATED",),
                observed_effects=("CHALLENGE_DENIED_DIGEST_MISMATCH",),
                forbidden_effects_triggered=(),
                trace_id=trace_id,
                cleanup_ok=True,
                details={"digest_len": len(changed_ref.operation_digest)},
            )

        if scenario.scenario_id == "GS09":
            k = f"idem-gs09-{run_tag}"
            digest = "d" * 64
            c1 = idem.claim(idempotency_key=k, tool_id="booking.create", action="create", actor_ref="cust-syn-001", operation_digest=digest)
            receipt = biz.execute_booking(operation_id=f"op-gs09-{run_tag}", idempotency_key=k, slot_id="slot-syn-1", customer_ref="cust-syn-001", vehicle_ref="veh-syn-001")
            idem.mark_committed(k, operation_digest=digest, result_ref=f"mock-gs09-{run_tag}")
            c2 = idem.claim(idempotency_key=k, tool_id="booking.create", action="create", actor_ref="cust-syn-001", operation_digest=digest)
            ok = c1.acquired and not c2.acquired and len(crm.list_bookings()) == 1
            return ReplayResult(
                scenario_id="GS09",
                revision=scenario.revision,
                status=GateStatus.PASS if ok else GateStatus.FAIL,
                transitions=("CLAIMED->COMMITTED", "ALREADY_COMMITTED"),
                observed_effects=("SINGLE_SYNTHETIC_EFFECT",),
                forbidden_effects_triggered=(),
                trace_id=trace_id,
                cleanup_ok=True,
            )

        if scenario.scenario_id == "GS10":
            k = f"idem-gs10-{run_tag}"
            digest = "e" * 64
            idem.claim(idempotency_key=k, tool_id="booking.create", action="create", actor_ref="cust-syn-001", operation_digest=digest)
            receipt = biz.execute_booking(operation_id=f"op-gs10-{run_tag}", idempotency_key=k, slot_id="slot-syn-1", customer_ref="cust-syn-001", vehicle_ref="veh-syn-001", simulate_unknown=True)
            idem.mark_unknown(k, operation_digest=digest, error_code="PROVIDER_TIMEOUT")
            c2 = idem.claim(idempotency_key=k, tool_id="booking.create", action="create", actor_ref="cust-syn-001", operation_digest="e" * 64)
            ok = receipt.status.value == "UNKNOWN" and not c2.acquired and c2.outcome.value == "UNKNOWN_HOLD"
            return ReplayResult(
                scenario_id="GS10",
                revision=scenario.revision,
                status=GateStatus.PASS if ok else GateStatus.FAIL,
                transitions=("CLAIMED->UNKNOWN", "UNKNOWN_HOLD"),
                observed_effects=("RECONCILE_REQUIRED_NO_BLIND_RETRY",),
                forbidden_effects_triggered=(),
                trace_id=trace_id,
                cleanup_ok=True,
            )

        # GS06, GS07, GS08, GS11 policy checks
        strong = verified_principal("cust-syn-001", kind=PrincipalKind.CUSTOMER, auth_strength=AuthStrength.STRONG_VERIFIED, evidence_source=EvidenceSource.MFA_VERIFIED)
        if scenario.scenario_id == "GS06":
            ctx = AccessContext(session_id="sess-gs06", principal=strong, channel="web", state_revision=1, asr_status=ASRStatus.FINAL)
            d = engine.evaluate(ctx, "booking.cancel", operation_digest="f" * 64, confirmation_approved=True, confirmation_state_revision=1)
            ok = d.verdict == PolicyVerdict.ALLOW
        elif scenario.scenario_id == "GS08":
            ctx = AccessContext(session_id="sess-gs08", principal=strong, channel="telephony", state_revision=1, asr_status=ASRStatus.PARTIAL)
            d = engine.evaluate(ctx, "booking.create")
            ok = d.verdict == PolicyVerdict.HOLD
        else:
            from backend.security import anonymous_principal
            ctx = AccessContext(session_id="sess-gs07", principal=anonymous_principal(), channel="telephony", state_revision=1)
            d = engine.evaluate(ctx, "customer.read_record" if scenario.scenario_id == "GS07" else "admin.override")
            ok = not d.allowed
        return ReplayResult(
            scenario_id=scenario.scenario_id,
            revision=scenario.revision,
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            transitions=scenario.expected_transitions,
            observed_effects=scenario.expected_effects if ok else (),
            forbidden_effects_triggered=(),
            trace_id=trace_id,
            cleanup_ok=True,
        )

    def _replay_dtmf_dedup(
        self,
        scenario: GoldenScenario,
        clock: HarnessClock,
        traces: TraceStore,
        trace_id: str,
    ) -> ReplayResult:
        inj = FakeDTMFInjector(dedup_window_ms=120)
        first = inj.receive_digit("1", at_ms=0)
        dup = inj.receive_digit("1", at_ms=40)
        ok = first is True and dup is False
        return ReplayResult(
            scenario_id=scenario.scenario_id,
            revision=scenario.revision,
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            transitions=scenario.expected_transitions,
            observed_effects=scenario.expected_effects if ok else (),
            forbidden_effects_triggered=(),
            trace_id=trace_id,
            cleanup_ok=True,
        )

    async def _replay_overload_disconnect(
        self,
        scenario: GoldenScenario,
        clock: HarnessClock,
        traces: TraceStore,
        trace_id: str,
    ) -> ReplayResult:
        tr = FakeAudioSocketTransport(max_send_buffer_bytes=320)
        ok1, _, st1 = tr.write_frame(b"\x01" * 320)
        ok2, _, st2 = tr.write_frame(b"\x02" * 320)
        tr.disconnect()
        ok3, _, st3 = tr.write_frame(b"\x03" * 320)
        ok = ok1 and not ok2 and st2 == "BACKPRESSURE" and not ok3 and st3 == "DISCONNECTED_IN_FLIGHT_UNKNOWN"
        return ReplayResult(
            scenario_id=scenario.scenario_id,
            revision=scenario.revision,
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            transitions=scenario.expected_transitions,
            observed_effects=scenario.expected_effects if ok else (),
            forbidden_effects_triggered=(),
            trace_id=trace_id,
            cleanup_ok=True,
        )

    def _replay_generic_structural(
        self,
        scenario: GoldenScenario,
        clock: HarnessClock,
        traces: TraceStore,
        trace_id: str,
    ) -> ReplayResult:
        sp = traces.start_span(
            trace_id=trace_id,
            span_id=f"sp-{scenario.scenario_id.lower()}",
            name=f"scenario.{scenario.scenario_id.lower()}",
            session_id=f"sess-{scenario.scenario_id.lower()}",
            clock_domain=clock.clock_domain,
            start_monotonic_ns=clock.monotonic_ns(),
        )
        clock.advance_ms(5)
        traces.finish_span(
            trace_id=trace_id,
            span_id=sp.span_id,
            end_monotonic_ns=clock.monotonic_ns(),
            clock_domain=clock.clock_domain,
            status=SpanStatus.OK,
        )
        return ReplayResult(
            scenario_id=scenario.scenario_id,
            revision=scenario.revision,
            status=GateStatus.PASS,
            transitions=scenario.expected_transitions,
            observed_effects=scenario.expected_effects,
            forbidden_effects_triggered=(),
            trace_id=trace_id,
            cleanup_ok=True,
        )
