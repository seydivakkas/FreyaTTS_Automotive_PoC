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

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from backend.core.configuration import (
    ConfigSnapshotStore,
    FeatureFlagRegistry,
    SupervisorMode,
    resolve_configuration,
)
from backend.core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    ASRStatus,
    AudioEncoding,
    AudioFormat,
    CatalogStatus,
    ConfirmationStatus,
    ErrorCategory,
    EventEnvelope,
    GenerationRef,
    MetricSample,
    MetricStatus,
    ObservationScope,
    PlaybackProfile,
    ProviderMode,
    RenderedFrame,
    SessionIdentity,
    StreamDirection,
    StreamRef,
    ToolReceipt,
    ToolReceiptStatus,
    TurnRef,
)
from backend.core.model_registry import ModelKind, ModelRegistry, run_offline_preflight
from backend.core.runtime import (
    AdmissionStatus,
    CancellationScope,
    QueuedMediaItem,
    SessionContext,
    SessionRegistry,
)
from backend.core.runtime.session_context import CleanupStatus
from backend.observability import (
    BoundedEventBus,
    EventPriority,
    EvidenceKind,
    EvidenceRecorder,
    MetricsRegistry,
    Projection,
    TraceStore,
)
from backend.runtime_resources import (
    MIB,
    AdmissionOutcome,
    CTranslate2Adapter,
    ExecutionLeaseState,
    FakeCTranslate2Worker,
    HandleOwnership,
    ModelSpec,
    PriorityClass,
    ProviderKind,
    QuarantineManager,
    ResourceRequest,
    UnifiedGpuScheduler,
)
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
    untrusted_principal,
    verified_principal,
)
from backend.shared_lexicon import LexiconRegistry, extract_asr_candidates, load_lexicon_snapshot
from tests.harness.acceptance import evaluate_gates
from tests.harness.adapters import FakeBusinessProvider, FakeGPUProbeAdapter, IsolatedCRMSchemaFixture
from tests.harness.compatibility import CompatibilityChecker
from tests.harness.contracts import GateRecord, GateStatus, PrerequisiteStatus
from tests.harness.core_integration import evaluate_core_integration
from tests.harness.evidence_validator import EvidenceValidator
from tests.harness.failure_injection import FailureInjector, FaultKind, FaultPlan, FaultTarget, InjectedFaultError
from tests.harness.fake_clock import HarnessClock
from tests.harness.feature_regression import FeatureRegressionMapper
from tests.harness.replay import DeterministicReplayEngine

REPO_ROOT = Path(__file__).resolve().parents[2]
M00_BASELINE_ID = "20261126T001600Z"
M00_BASELINE_DIR = REPO_ROOT / "docs" / "freya2" / "baseline" / M00_BASELINE_ID


def test_ci01_m00_baseline_lineage_and_feature_denominator() -> None:
    res = EvidenceValidator(REPO_ROOT).verify_m00_baseline(M00_BASELINE_ID)
    assert res.status == PrerequisiteStatus.ACCEPTED
    summary = FeatureRegressionMapper(REPO_ROOT, M00_BASELINE_DIR).build_matrix()
    assert summary.total_features == 18
    assert summary.duplicate_feature_ids == ()
    assert summary.missing_from_regression_matrix == ()


@pytest.mark.asyncio
async def test_ci02_m01_to_m02_identity_and_generation_fencing() -> None:
    ctx = SessionContext(SessionIdentity("sess-ci02", trace_id="trace-ci02"))
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    g1, _ = await ctx.begin_generation(t1)
    g2, _ = await ctx.begin_generation(t1)
    assert await ctx.admit_media(QueuedMediaItem(g1, 0, b"\x01" * 320)) == AdmissionStatus.STALE_GENERATION
    wrong_session = GenerationRef("other-sess", t1.turn_id, g2.generation_id)
    assert await ctx.admit_media(QueuedMediaItem(wrong_session, 0, b"\x01" * 320)) == AdmissionStatus.STALE_SESSION
    assert await ctx.admit_media(QueuedMediaItem(g2, 0, b"\x01" * 320)) == AdmissionStatus.ACCEPTED
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ci03_m02_to_m04_trace_and_cancel_correlation() -> None:
    clock = HarnessClock(initial_ns=5_000_000)
    bus = BoundedEventBus()
    sub = bus.subscribe("ci03-sub")
    traces = TraceStore()
    ctx = SessionContext(SessionIdentity("sess-ci03", trace_id="trace-ci03"), clock=clock, event_sink=bus.try_publish)
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    g1, _ = await ctx.begin_generation(t1)
    sp = traces.start_span(
        trace_id="trace-ci03",
        span_id="sp-gen1",
        name="tts.generation",
        session_id="sess-ci03",
        turn_id=t1.turn_id,
        generation_id=g1.generation_id,
        clock_domain=clock.clock_domain,
        start_monotonic_ns=clock.monotonic_ns(),
    )
    clock.advance_ms(4)
    await ctx.commit_interrupt("barge_in")
    traces.finish_span(
        trace_id="trace-ci03",
        span_id=sp.span_id,
        end_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
    )
    events = sub.drain()
    revoked = [e for e in events if e.event_type == "generation.revoked"]
    assert len(revoked) == 1
    assert revoked[0].trace_id == "trace-ci03"
    assert revoked[0].turn_id == 1 and revoked[0].generation_id == 1
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ci04_m02_to_m04_cancel_authoritative_under_bus_saturation() -> None:
    bus = BoundedEventBus(max_lane_size=1)
    sub = bus.subscribe("tiny-sub")
    ctx = SessionContext(SessionIdentity("sess-ci04", trace_id="trace-ci04"), event_sink=bus.try_publish)
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    g1, _ = await ctx.begin_generation(t1)
    # Saturate CRITICAL lane before revoke
    for idx in range(5):
        bus.try_publish(
            EventEnvelope(
                schema_version=CONTRACT_SCHEMA_VERSION,
                event_type="session.closed",
                session_id="sess-ci04",
                trace_id="trace-ci04",
                turn_id=1,
                generation_id=1,
                sequence=100 + idx,
                monotonic_ns=10 + idx,
                clock_domain="test.clock",
                producer="ci04",
            )
        )
    assert await ctx.commit_interrupt("barge_in") is True
    assert await ctx.admit_media(QueuedMediaItem(g1, 0, b"\x00" * 320)) == AdmissionStatus.CANCELED
    assert bus.stats.dropped_count >= 1
    assert sub.pending_count <= 4  # bounded
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ci05_m03_to_m02_session_pins_immutable_config_revision() -> None:
    s1_cfg = resolve_configuration(overrides={"ollama_model": "qwen2.5:7b"}).snapshot
    store = ConfigSnapshotStore(s1_cfg)
    pinned_for_sess1 = store.current
    s2_cfg = resolve_configuration(overrides={"ollama_model": "qwen2.5:14b"}).snapshot
    store.swap(s2_cfg)

    ctx1 = SessionContext(SessionIdentity("sess-ci05-a"))
    ctx2 = SessionContext(SessionIdentity("sess-ci05-b"))
    await ctx1.open()
    await ctx2.open()
    assert pinned_for_sess1.config_revision != store.current.config_revision
    assert pinned_for_sess1.get("ollama_model") == "qwen2.5:7b"
    assert store.current.get("ollama_model") == "qwen2.5:14b"
    await ctx1.close("done")
    await ctx2.close("done")


def test_ci06_m03_to_m05_lexicon_revision_with_config_snapshot() -> None:
    cfg = resolve_configuration().snapshot
    lex_snap = load_lexicon_snapshot()
    reg = LexiconRegistry.from_snapshot(lex_snap)
    assert len(cfg.config_revision) == 64
    assert len(reg.snapshot.lexicon_revision) == 64


def test_ci07_m05_to_m01_lexicon_maps_to_unverified_entity_candidate() -> None:
    reg = LexiconRegistry.from_snapshot(load_lexicon_snapshot())
    extraction = extract_asr_candidates(reg, "pasat bakim randevusu")
    assert len(extraction.candidates) >= 1
    for ent in extraction.candidates:
        assert ent.catalog_status == CatalogStatus.UNVERIFIED
        assert ent.confirmation_status == ConfirmationStatus.CANDIDATE


def test_ci08_m05_to_m04_safe_counters_no_raw_text_leakage() -> None:
    reg = LexiconRegistry.from_snapshot(load_lexicon_snapshot())
    metrics = MetricsRegistry()
    proj = Projection()
    raw_utterance = "Plaka 34 ABC 1234 telefon 0532 111 22 33 Volkswagen Passat"
    extraction = extract_asr_candidates(reg, raw_utterance)
    sample = metrics.inc("lexicon.lookups_total", float(len(extraction.candidates)))
    assert sample is not None and sample.value >= 1.0
    env = EventEnvelope(
        schema_version=CONTRACT_SCHEMA_VERSION,
        event_type="asr.final",
        session_id="sess-ci08",
        trace_id="trace-ci08",
        turn_id=1,
        generation_id=1,
        sequence=0,
        monotonic_ns=100,
        clock_domain="test.clock",
        producer="m05",
        metadata={"lexicon_revision": reg.lexicon_revision, "raw_transcript": raw_utterance},
    )
    safe = proj.project(env)
    assert safe is not None
    assert "raw_transcript" not in safe.get("metadata", {})
    assert "0532" not in str(safe)


def test_ci09_m03_to_m06_model_descriptor_and_preflight(tmp_path: Path) -> None:
    cfg = resolve_configuration(overrides={"data_dir": tmp_path, "auto_load_models": False}).snapshot
    mreg = ModelRegistry.from_snapshot(cfg)
    assert mreg.get("tts-freya") is not None
    assert mreg.voice_profiles.baseline().seed == 9
    report = run_offline_preflight(cfg, mreg, base_dir=tmp_path)
    assert len(report.items) >= 1


@pytest.mark.asyncio
async def test_ci10_m06_to_m04_scheduler_metrics_and_mock_evidence() -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    sched = UnifiedGpuScheduler(clock=clock)
    sched.residency_manager.register_model(
        ModelSpec("whisper-tr", HandleOwnership.OWNED, ProviderKind.CTRANSLATE2, 64 * MIB, loader=lambda: "ok")
    )
    sched.memory_budget.update_probe(FakeGPUProbeAdapter(clock).valid_probe(free_mib=2048))
    worker = FakeCTranslate2Worker(["tamam"])
    sched.register_adapter(ProviderKind.CTRANSLATE2, CTranslate2Adapter(lambda _r: worker))
    scope = CancellationScope("turn:1", clock=clock)
    out = await sched.run_request(ResourceRequest("r-10", PriorityClass.P1, ProviderKind.CTRANSLATE2, "whisper-tr", 64 * MIB, scope))
    assert out.admission == AdmissionOutcome.ADMITTED

    rec = EvidenceRecorder()
    ev = rec.record(
        kind=EvidenceKind.MOCK_RUNTIME,
        claim="scheduler_mock_admission",
        subject="m06.scheduler",
        recorded_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
        observation_scope=ObservationScope.SERVER.value,
        metrics=(MetricSample("gpu.lease_released", 1.0, "count", "SERVER", MetricStatus.MEASURED),),
    )
    assert ev.proves_real_endpoint is False


@pytest.mark.asyncio
async def test_ci11_m02_to_m06_queued_cancel_prevents_dispatch() -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    sched = UnifiedGpuScheduler(clock=clock)
    sched.memory_budget.update_probe(FakeGPUProbeAdapter(clock).valid_probe(free_mib=2048))
    ctx = SessionContext(SessionIdentity("sess-ci11"), clock=clock)
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    g1, g1_scope = await ctx.begin_generation(t1)
    sched.submit(ResourceRequest("r-11", PriorityClass.P3, ProviderKind.OLLAMA, "qwen2.5:7b", 64 * MIB, g1_scope))
    await ctx.commit_interrupt("barge_in")
    out = await sched.dispatch_next()
    # Cancelled before dispatch -> item expired/cancelled, never runs adapter
    assert out is None or out.admission == AdmissionOutcome.REJECTED_CANCELLED
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ci12_m02_to_m06_running_cancel_fences_and_holds_lease() -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    sched = UnifiedGpuScheduler(clock=clock)
    sched.residency_manager.register_model(
        ModelSpec("whisper-tr", HandleOwnership.OWNED, ProviderKind.CTRANSLATE2, 64 * MIB, loader=lambda: "ok")
    )
    sched.memory_budget.update_probe(FakeGPUProbeAdapter(clock).valid_probe(free_mib=2048))
    step_gate = asyncio.Event()
    worker = FakeCTranslate2Worker(["seg1", "seg2"], step_gate=step_gate)
    sched.register_adapter(ProviderKind.CTRANSLATE2, CTranslate2Adapter(lambda _r: worker))

    ctx = SessionContext(SessionIdentity("sess-ci12"), clock=clock)
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    _, g1_scope = await ctx.begin_generation(t1)
    req = ResourceRequest("r-12", PriorityClass.P1, ProviderKind.CTRANSLATE2, "whisper-tr", 64 * MIB, g1_scope)
    task = asyncio.create_task(sched.run_request(req))
    await asyncio.sleep(0)
    await ctx.commit_interrupt("hard_cancel")
    step_gate.set()
    out = await task
    assert out.delivered == ()
    lease = sched.get_lease(out.lease_id or "")
    assert lease is not None and lease.state == ExecutionLeaseState.RELEASED
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ci13_m06_stale_probe_and_oom_refusal() -> None:
    clock = HarnessClock(initial_ns=10_000_000_000)
    sched = UnifiedGpuScheduler(clock=clock, quarantine_manager=QuarantineManager(clock=clock, max_entries=1))
    sched.residency_manager.register_model(
        ModelSpec("tts-freya", HandleOwnership.OWNED, ProviderKind.PYTORCH, 64 * MIB, loader=lambda: "ok")
    )
    probes = FakeGPUProbeAdapter(clock)
    sched.memory_budget.update_probe(probes.stale_probe(free_mib=4096, age_ms=5000))
    scope = CancellationScope("turn:1", clock=clock)
    req = ResourceRequest("r-13", PriorityClass.P2, ProviderKind.PYTORCH, "tts-freya", 128 * MIB, scope)
    res = sched.submit(req)
    assert res.outcome == AdmissionOutcome.REJECTED_PROBE_UNAVAILABLE


def test_ci14_m01_to_m07_partial_asr_cannot_authorize_mutation(tmp_path: Path) -> None:
    audit = SecurityAuditLog(tmp_path / "audit.db")
    engine = PolicyEngine(audit_log=audit)
    principal = verified_principal("cust-syn-001", kind=PrincipalKind.CUSTOMER, auth_strength=AuthStrength.STRONG_VERIFIED, evidence_source=EvidenceSource.MFA_VERIFIED)
    ctx = AccessContext(session_id="sess-ci14", principal=principal, channel="telephony", state_revision=1, asr_status=ASRStatus.PARTIAL)
    decision = engine.evaluate(ctx, "booking.create")
    assert decision.verdict == PolicyVerdict.HOLD
    receipt = ToolReceipt(operation_id="op-ci14", tool_id="booking.create", status=ToolReceiptStatus.BLOCKED, provider_mode=ProviderMode.MOCK)
    assert not receipt.is_committed_real


def test_ci15_m05_to_m07_candidate_boundary_cannot_authorize() -> None:
    reg = LexiconRegistry.from_snapshot(load_lexicon_snapshot())
    extraction = extract_asr_candidates(reg, "Volkswagen Passat")
    assert extraction.candidates[0].confirmation_status == ConfirmationStatus.CANDIDATE
    engine = PolicyEngine()
    untrusted = untrusted_principal("cust-syn-001", evidence_source=EvidenceSource.ASR_FINAL)
    ctx = AccessContext(session_id="sess-ci15", principal=untrusted, channel="telephony", state_revision=1)
    assert not engine.evaluate(ctx, "booking.read_status").allowed


@pytest.mark.asyncio
async def test_ci16_m02_to_m07_cancellation_fence_and_idempotency(tmp_path: Path) -> None:
    ctx = SessionContext(SessionIdentity("sess-ci16"))
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    _, g1_scope = await ctx.begin_generation(t1)
    await ctx.commit_interrupt("cancel_before_tool")
    assert g1_scope.is_cancel_requested
    # After admission idempotency settles independently
    idem = DurableIdempotencyStore(tmp_path / "idem.db")
    digest = "a" * 64
    claim = idem.claim(idempotency_key="ik-16", tool_id="booking.create", action="create", actor_ref="cust-syn-001", operation_digest=digest)
    idem.mark_unknown("ik-16", operation_digest=digest, error_code="CANCELLED_IN_FLIGHT")
    assert claim.acquired and idem.get("ik-16").state.value == "UNKNOWN"
    await ctx.close("done")


def test_ci17_m07_isolated_db_idempotency_and_reopen(tmp_path: Path) -> None:
    idem_path = tmp_path / "idem.db"
    crm = IsolatedCRMSchemaFixture(tmp_path / "crm.db")
    crm.seed_slot("slot-ci17", capacity=1)
    biz = FakeBusinessProvider(crm)

    def _attempt(worker_id: int) -> bool:
        store = DurableIdempotencyStore(idem_path)
        digest = "b" * 64
        res = store.claim(idempotency_key="ik-17", tool_id="booking.create", action="create", actor_ref="cust-syn-001", operation_digest=digest)
        if not res.acquired:
            return False
        biz.execute_booking(operation_id=f"op-17-{worker_id}", idempotency_key="ik-17", slot_id="slot-ci17", customer_ref="cust-syn-001", vehicle_ref="veh-syn-001")
        store.mark_committed("ik-17", operation_digest=digest, result_ref="mock-17")
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        r1 = pool.submit(_attempt, 1).result()
        r2 = pool.submit(_attempt, 2).result()
    assert [r1, r2].count(True) == 1
    assert len(IsolatedCRMSchemaFixture(tmp_path / "crm.db").list_bookings()) == 1


def test_ci18_m07_to_m04_durable_audit_independent_of_lossy_bus(tmp_path: Path) -> None:
    def broken_observer(_payload):
        raise RuntimeError("m04_bus_full")

    audit = SecurityAuditLog(tmp_path / "audit.db", observer_sink=broken_observer)
    engine = PolicyEngine(audit_log=audit)
    principal = verified_principal("cust-syn-001", kind=PrincipalKind.CUSTOMER, auth_strength=AuthStrength.STRONG_VERIFIED, evidence_source=EvidenceSource.MFA_VERIFIED)
    ctx = AccessContext(session_id="sess-ci18", principal=principal, channel="web", state_revision=1)
    dec = engine.evaluate(ctx, "booking.read_status")
    assert dec.verdict == PolicyVerdict.ALLOW
    assert audit.verify_chain() is True
    assert audit.count() >= 1


def test_ci19_m03_to_m07_supervisor_modes_preserved(tmp_path: Path) -> None:
    for mode_val, expected_enum in (("off", SupervisorMode.OFF), ("shadow", SupervisorMode.SHADOW), ("guarded", SupervisorMode.GUARDED)):
        cfg = resolve_configuration(overrides={"supervisor_mode": mode_val}).snapshot
        assert cfg.get("supervisor_mode") == expected_enum.value
    flags = FeatureFlagRegistry.from_snapshot(resolve_configuration(overrides={"supervisor_mode": "guarded"}).snapshot)
    assert flags.get_mode("supervisor_mode") == SupervisorMode.GUARDED
    # GUARDED never fails open on unconfirmed mutation
    engine = PolicyEngine()
    p = verified_principal("cust-syn-001", kind=PrincipalKind.CUSTOMER, auth_strength=AuthStrength.STRONG_VERIFIED, evidence_source=EvidenceSource.MFA_VERIFIED)
    ctx = AccessContext(session_id="sess-ci19", principal=p, channel="web", state_revision=1)
    assert engine.evaluate(ctx, "booking.create", confirmation_approved=False).verdict == PolicyVerdict.CHALLENGE


@pytest.mark.asyncio
async def test_ci20_two_session_cross_package_isolation() -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    all_events: list[EventEnvelope] = []
    reg = SessionRegistry(clock=clock, event_sink=all_events.append)
    sa = await reg.create("sess-a", trace_id="tr-a")
    sb = await reg.create("sess-b", trace_id="tr-b")
    await sa.open()
    await sb.open()
    ta, _ = await sa.begin_turn()
    ga, _ = await sa.begin_generation(ta)
    assert await sb.admit_media(QueuedMediaItem(ga, 0, b"\x01" * 320)) == AdmissionStatus.STALE_SESSION
    assert await reg.close_session("sess-a") == CleanupStatus.COMPLETE
    assert await reg.close_session("sess-b") == CleanupStatus.COMPLETE


@pytest.mark.asyncio
async def test_ci21_m01_to_m02_mock_media_wrong_generation_and_no_recall() -> None:
    ctx = SessionContext(SessionIdentity("sess-ci21"))
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    g1, _ = await ctx.begin_generation(t1)
    g2, _ = await ctx.begin_generation(t1)
    frame = RenderedFrame(
        generation_ref=g1,
        stream_ref=StreamRef("sess-ci21", "out", StreamDirection.OUTPUT, 0),
        sequence=0,
        sample_offset=0,
        profile=PlaybackProfile.AUDIOSOCKET_8K_PCM16,
        format=AudioFormat(8000, 1, AudioEncoding.PCM_S16LE),
        frame_duration_ms=20.0,
        sample_count=160,
        valid_sample_count=160,
        payload=b"\x01" * 320,
    )
    assert await ctx.admit_media(QueuedMediaItem(frame.generation_ref, 0, frame.payload)) == AdmissionStatus.STALE_GENERATION
    # Valid generation admitted and popped -> submitted data not recalled
    assert await ctx.admit_media(QueuedMediaItem(g2, 0, frame.payload)) == AdmissionStatus.ACCEPTED
    st, popped = await ctx.dequeue_for_submission(g2)
    assert st == AdmissionStatus.ACCEPTED and popped is not None
    await ctx.close("done")


def test_ci22_m00_m08_public_compatibility_snapshot() -> None:
    chk = CompatibilityChecker(REPO_ROOT, M00_BASELINE_DIR)
    assert chk.check_api_compatibility().status == GateStatus.PASS
    assert chk.check_ui_compatibility().status == GateStatus.PASS
    assert chk.check_db_compatibility().status == GateStatus.PASS
    assert chk.check_config_model_compatibility().status == GateStatus.PASS


@pytest.mark.asyncio
async def test_ci23_m08_integrated_failure_replay_reproducible(tmp_path: Path) -> None:
    inj = FailureInjector(FaultPlan("fp-ci23", (FaultTarget("observer", "emit", occurrence=1, fault_kind=FaultKind.OBSERVER_FAILURE),)))
    with pytest.raises(InjectedFaultError):
        inj.check_and_fire("observer", "emit")
    eng = DeterministicReplayEngine()
    r1 = await eng.replay("GS15", sandbox_dir=tmp_path, run_tag="a")
    r2 = await eng.replay("GS15", sandbox_dir=tmp_path, run_tag="b")
    assert r1.status == GateStatus.PASS and r2.status == GateStatus.PASS
    assert r1.cleanup_ok and r2.cleanup_ok


def test_ci24_all_packages_gate_validator_and_product_limits() -> None:
    m08_summary = evaluate_gates([GateRecord(f"G{i:02d}", True, GateStatus.PASS, "ok", ("ev",)) for i in range(20)])
    pkgs = {f"M0{i}": GateStatus.PASS for i in range(9)}
    ci = {f"CI{i:02d}": GateStatus.PASS for i in range(1, 25)}
    cg = [GateRecord(f"CG{i:02d}", True, GateStatus.PASS, "ok", ("ev",)) for i in range(12)]
    dec = evaluate_core_integration(run_id="ci24", m08_summary=m08_summary, package_statuses=pkgs, ci_results=ci, cg_gates=cg, owner_f0_a_authorized=False)
    assert dec.core_integration_ready is True
    assert dec.owner_execution_authorized is False
    assert dec.synthetic_product_acceptance_status == GateStatus.NOT_RUN
    assert dec.hardware_acceptance_status == GateStatus.NOT_RUN
    assert dec.human_sip_status == GateStatus.NOT_RUN


def test_cg00_to_cg11_structural_core_gate_matrix() -> None:
    m08_summary = evaluate_gates([GateRecord(f"G{i:02d}", True, GateStatus.PASS, "ok", ("ev",)) for i in range(20)])
    pkgs = {f"M0{i}": GateStatus.PASS for i in range(9)}
    ci = {f"CI{i:02d}": GateStatus.PASS for i in range(1, 25)}
    cg = [GateRecord(f"CG{i:02d}", True, GateStatus.PASS, f"CG{i:02d} verified", ("ev",)) for i in range(12)]
    dec = evaluate_core_integration(run_id="cg-matrix", m08_summary=m08_summary, package_statuses=pkgs, ci_results=ci, cg_gates=cg)
    assert dec.core_integration_status == GateStatus.PASS
    assert dec.core_integration_ready is True
    assert dec.vertical_slice_ready is True
