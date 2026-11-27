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
import json
import random
import sqlite3
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from backend.core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    AudioEncoding,
    AudioFormat,
    ConfidenceEstimate,
    ObservationScope,
    SpeechEventKind,
    StreamDirection,
    StreamRef,
    validate_plan_chunk_consistency,
)
from backend.core.contracts.recognition import ASROutcome, ASRStatus
from backend.core.runtime import (
    AdmissionStatus,
    CancellationScope,
    DeadlineBudget,
    QueuedMediaItem,
    SessionContext,
)
from backend.core.contracts import SessionIdentity
from backend.observability import BoundedEventBus, EventPriority, EvidenceKind, Projection
from backend.runtime_resources import (
    MIB,
    CTranslate2Adapter,
    FakeCTranslate2Worker,
    HandleOwnership,
    MemoryBudget,
    ModelSpec,
    PriorityClass,
    ProbeStatus,
    ProviderKind,
    QuarantineManager,
    ResourceRequest,
    UnifiedGpuScheduler,
)
from backend.security import ConfirmationManager, PolicyEngine, PolicyVerdict, SecurityAuditLog
from tests.harness.acceptance import evaluate_gates
from tests.harness.adapters import (
    FakeASRAdapter,
    FakeAudioSocketTransport,
    FakeBusinessProvider,
    FakeDTMFInjector,
    FakeGPUProbeAdapter,
    FakeIdentityProvider,
    FakeLLMAdapter,
    FakePlaybackEndpoint,
    FakeRTPDatagramChannel,
    FakeTTSAdapter,
    FakeVADAdapter,
    IsolatedCRMSchemaFixture,
)
from tests.harness.adapters.fake_transport import AUDIOSOCKET_AUDIO, AUDIOSOCKET_DTMF, pack_audiosocket_frame
from tests.harness.adapters.fake_vad import ScriptedVADStep
from tests.harness.barriers import DeterministicBarrier, InterleavingPoint, WatchdogTimeoutError, run_with_watchdog
from tests.harness.compatibility import CompatibilityChecker
from tests.harness.contracts import (
    CaseResult,
    FixtureManifest,
    GateRecord,
    GateStatus,
    PrerequisiteStatus,
    RunProfile,
    TestRunManifest,
)
from tests.harness.core_integration import evaluate_core_integration
from tests.harness.evidence_validator import EvidenceValidator, PIISecretScanner, sha256_file
from tests.harness.failure_injection import FailureInjector, FaultKind, FaultPlan, FaultTarget, InjectedFaultError
from tests.harness.fake_clock import CrossClockComparisonError, HarnessClock
from tests.harness.feature_regression import FeatureRegressionMapper
from tests.harness.fixture_registry import (
    FixtureCapExceededError,
    FixtureLimits,
    FixtureRegistry,
    HashMismatchError,
    SplitLeakageError,
    local_rng,
)
from tests.harness.golden_scenarios import GoldenScenarioRegistry
from tests.harness.isolation import (
    IsolationSandbox,
    PathConfinementError,
    SideEffectDeniedError,
    audit_import_closure,
    resolve_confined_path,
)
from tests.harness.replay import DeterministicReplayEngine
from tests.harness.runner import (
    FOUNDATION_SUITE_REGISTRATIONS,
    AllowlistViolationError,
    HarnessRunner,
    PytestSummaryCounts,
    parse_pytest_summary,
    reconcile_run_status,
    validate_no_duplicate_test_ids,
)
from tests.harness.synthetic_audio import (
    AnalyticSignalKind,
    SyntheticAudioGenerator,
    decode_float32_le,
    decode_pcm16_le,
    validate_audio_frame_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
M00_BASELINE_ID = "20261126T001600Z"
M00_BASELINE_DIR = REPO_ROOT / "docs" / "freya2" / "baseline" / M00_BASELINE_ID


# ---------------------------------------------------------------------------
# TH01 - TH16: Preflight, Passive Imports, Runner & Isolation
# ---------------------------------------------------------------------------


def test_th01_missing_accepted_m00_blocks_with_hold(tmp_path: Path) -> None:
    validator = EvidenceValidator(tmp_path)
    res = validator.verify_m00_baseline(M00_BASELINE_ID)
    assert res.status == PrerequisiteStatus.MISSING
    assert "M00_DIRS_MISSING" in res.missing_items


def test_th02_reject_pass_claim_with_missing_gate(tmp_path: Path) -> None:
    pkg_root = tmp_path / "docs" / "freya2" / "m01"
    run_dir = pkg_root / "20261126T010000Z"
    run_dir.mkdir(parents=True)
    (run_dir / "ACCEPTANCE_MATRIX.json").write_text(
        json.dumps({"overall": "PASS", "m02_ready": True, "gates": {"G00": "PASS"}}),
        encoding="utf-8",
    )
    res = EvidenceValidator(tmp_path).verify_package_acceptance_dir(
        "M01", pkg_root, explicit_run_id="20261126T010000Z", required_gates=("G00", "G01"), ready_flag="m02_ready"
    )
    assert res.status == PrerequisiteStatus.HOLD
    assert any("M01_MISSING_OR_FAILED_GATE:G01" in e for e in res.errors)


def test_th03_conflicting_run_candidates_no_timestamp_guess(tmp_path: Path) -> None:
    pkg_root = tmp_path / "docs" / "freya2" / "m02"
    (pkg_root / "20261126T010000Z").mkdir(parents=True)
    (pkg_root / "20261126T020000Z").mkdir(parents=True)
    res = EvidenceValidator(tmp_path).verify_package_acceptance_dir("M02", pkg_root, explicit_run_id=None)
    assert res.status == PrerequisiteStatus.CONFLICTING


def test_th04_approved_lineage_vs_unexplained_drift(tmp_path: Path) -> None:
    validator = EvidenceValidator(REPO_ROOT)
    ok_res = validator.verify_m00_baseline(M00_BASELINE_ID)
    assert ok_res.status == PrerequisiteStatus.ACCEPTED

    manifest = TestRunManifest(
        run_id="run-1",
        suite="m08",
        profile=RunProfile.PACKAGE,
        baseline_run_id=M00_BASELINE_ID,
        dependency_run_ids={"M00": M00_BASELINE_ID},
        source_scope_hash="abc123",
        approved_changes=("tests/harness/runner.py",),
        command=("pytest", "-q"),
        tool_versions={"pytest": "9.2.0"},
        fixture_revision="1.0",
        clock_domain="harness.fake.clock",
        start_utc="2026-11-26T00:00:00Z",
        end_utc="2026-11-26T00:00:01Z",
        elapsed_ms=10.0,
        isolation_mode="TEMP_SANDBOX",
        selected_cases=("TH04",),
        outcome_counts={"PASS": 1},
        completeness=1.0,
        evidence_refs=("evidence/m08/run-1/manifest.json",),
    )
    assert validator.validate_run_manifest(manifest, expected_snapshot="abc123") == []
    drift_errors = validator.validate_run_manifest(manifest, expected_snapshot="different-hash")
    assert any("STALE_SNAPSHOT" in e for e in drift_errors)


def test_th05_optional_seam_absent_keeps_core_hold(tmp_path: Path) -> None:
    m08_summary = evaluate_gates([GateRecord("G00", True, GateStatus.PASS, "ok", ("ev",))])
    assert m08_summary.ready is True
    ci = {f"CI{i:02d}": GateStatus.PASS for i in range(1, 25)}
    cg = [GateRecord(f"CG{i:02d}", True, GateStatus.PASS, "ok", ("ev",)) for i in range(12)]
    pkg_statuses = {f"M0{i}": GateStatus.PASS for i in range(9)}
    pkg_statuses["M06"] = GateStatus.HOLD
    decision = evaluate_core_integration(
        run_id="cg-hold-test",
        m08_summary=m08_summary,
        package_statuses=pkg_statuses,
        ci_results=ci,
        cg_gates=cg,
    )
    assert decision.m08_ready is True
    assert decision.core_integration_ready is False
    assert decision.core_integration_status == GateStatus.HOLD


def test_th06_passive_harness_imports() -> None:
    code = (
        "import sys, threading; "
        "t0 = threading.active_count(); "
        "import tests.harness, tests.harness.runner, tests.harness.isolation, "
        "tests.harness.synthetic_audio, tests.harness.adapters, "
        "tests.harness.compatibility, tests.harness.core_integration; "
        "t1 = threading.active_count(); "
        "assert t0 == t1, 'Threads spawned at import'; "
        "forbidden = {'torch', 'faster_whisper', 'ctranslate2', 'backend.main', 'backend.db', 'backend.models'}; "
        "bad = forbidden & set(sys.modules); "
        "assert not bad, f'Forbidden modules loaded: {bad}'"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert audit_import_closure(["tests.harness", "tests.harness.runner"]) == []


def test_th07_existing_runner_discovery_preserved(tmp_path: Path) -> None:
    runner = HarnessRunner(REPO_ROOT)
    nodes = runner.collect_only(
        RunProfile.PACKAGE,
        ["tests/contracts/test_m01_contracts.py"],
        basetemp=tmp_path / "basetemp_collect",
    )
    assert len(nodes) >= 14
    assert any("test_ct01_safe_isolated_import" in n for n in nodes)


def test_th08_unknown_suite_and_shell_injection_denied() -> None:
    runner = HarnessRunner(REPO_ROOT)
    with pytest.raises(AllowlistViolationError):
        runner.validate_selectors("unknown_profile", ["tests/contracts/test_m01_contracts.py"])  # type: ignore[arg-type]
    with pytest.raises(AllowlistViolationError):
        runner.validate_selectors(RunProfile.QUICK, ["tests/contracts/test_m01_contracts.py && whoami"])
    with pytest.raises(AllowlistViolationError):
        runner.validate_selectors(RunProfile.QUICK, ["tests/security/test_m07_security.py"])
    with pytest.raises(AllowlistViolationError):
        runner.validate_selectors(RunProfile.SYNTHETIC_FUTURE, ["tests/harness_tests/test_m08_harness.py"])


def test_th09_empty_selection_or_mismatch_never_pass() -> None:
    st_empty, reason_empty = reconcile_run_status(
        exit_code=0,
        counts=PytestSummaryCounts(0, 0, 0, 0, 0, 0, 0),
        expected_min_collected=1,
    )
    assert st_empty == GateStatus.HOLD
    assert reason_empty == "EMPTY_OR_UNDERCOLLECTED_SELECTION"

    st_mis, reason_mis = reconcile_run_status(
        exit_code=0,
        counts=PytestSummaryCounts(5, 4, 0, 0, 0, 0, 0),
        expected_min_collected=5,
    )
    assert st_mis == GateStatus.HOLD
    assert reason_mis == "COUNT_MISMATCH_RECONCILE_REQUIRED"


@pytest.mark.asyncio
async def test_th10_bounded_watchdog_terminates_hung_work() -> None:
    never = asyncio.Event()
    with pytest.raises(WatchdogTimeoutError):
        await run_with_watchdog(never.wait(), timeout_sec=0.02, label="hung_unit")
    st, reason = reconcile_run_status(
        exit_code=124,
        counts=PytestSummaryCounts(1, 0, 0, 0, 0, 0, 0),
        timed_out=True,
    )
    assert st == GateStatus.FAIL
    assert reason == "RUNNER_TIMEOUT_EXCEEDED"


def test_th11_existing_working_tree_preserved(tmp_path: Path) -> None:
    user_file = tmp_path / "user_dirty.txt"
    user_file.write_bytes(b"user-uncommitted-bytes")
    sb = IsolationSandbox(run_id="th11", base_dir=tmp_path / "sb")
    _ = sb.path("sub/test.txt")
    sb.cleanup()
    assert user_file.read_bytes() == b"user-uncommitted-bytes"


def test_th12_isolated_db_never_opens_production_db(tmp_path: Path) -> None:
    prod_db = REPO_ROOT / "data" / "assistant.db"
    sb = IsolationSandbox(run_id="th12", base_dir=tmp_path, production_db_paths=[prod_db])
    db_handle = sb.create_isolated_db("isolated.db")
    assert db_handle.db_path.is_relative_to(sb.root)
    assert db_handle.db_path.resolve() != prod_db.resolve()
    conn = db_handle.connect()
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    report = sb.cleanup()
    assert report["clean"] is True


def test_th13_outbound_provider_attempt_denied(tmp_path: Path) -> None:
    sb = IsolationSandbox(run_id="th13", base_dir=tmp_path)
    with pytest.raises(SideEffectDeniedError):
        sb.guard.check_target("https://api.twilio.com/2010-04-01", channel="sms")
    assert sb.guard.blocked_attempts[0].reason_code == "DENIED_OUTBOUND_EXTERNAL"
    sb.cleanup()


def test_th14_unallowlisted_loopback_denied(tmp_path: Path) -> None:
    sb = IsolationSandbox(run_id="th14", base_dir=tmp_path, allowlisted_targets=("127.0.0.1:59999",))
    sb.guard.check_target("http://127.0.0.1:59999/mock")
    with pytest.raises(SideEffectDeniedError):
        sb.guard.check_target("http://127.0.0.1:11434/api/generate")  # Ollama port blocked
    assert sb.guard.blocked_attempts[-1].reason_code == "DENIED_UNALLOWLISTED_LOOPBACK"
    sb.cleanup()


def test_th15_path_traversal_and_escape_rejected(tmp_path: Path) -> None:
    root = tmp_path / "confined"
    root.mkdir()
    with pytest.raises(PathConfinementError):
        resolve_confined_path(root, "../outside.txt", allow_missing=True)
    with pytest.raises(PathConfinementError):
        resolve_confined_path(root, tmp_path / "other.txt", allow_missing=True)


@pytest.mark.asyncio
async def test_th16_owned_resource_cleanup(tmp_path: Path) -> None:
    sb = IsolationSandbox(run_id="th16", base_dir=tmp_path)
    gate = asyncio.Event()
    sb.tracker.register_task(asyncio.create_task(gate.wait()))
    db = sb.create_isolated_db("own.db")
    db.connect()
    report = await sb.cleanup_async()
    assert report["clean"] is True
    assert report["surviving_tasks"] == 0
    assert report["surviving_db_connections"] == 0


# ---------------------------------------------------------------------------
# TH17 - TH25: Fake Clock, Barriers, Fixture Registry & Split Hygiene
# ---------------------------------------------------------------------------


def test_th17_fake_clock_progression_and_wakeup() -> None:
    clock = HarnessClock(initial_ns=1_000_000, clock_domain="test.clock")
    fired: list[int] = []
    clock.schedule_after_ms(15, fired.append)
    clock.advance_ms(10)
    assert fired == []
    clock.advance_ms(5)
    assert fired == [16_000_000]
    budget = DeadlineBudget.from_now(clock, 20)
    clock.advance_ms(20)
    assert budget.is_expired(clock)


def test_th18_backward_or_invalid_fake_clock_rejected() -> None:
    clock = HarnessClock(initial_ns=100)
    with pytest.raises(ValueError):
        clock.advance_ns(-1)
    with pytest.raises(ValueError):
        clock.advance_ms(-5)
    with pytest.raises(ValueError):
        HarnessClock.elapsed_ns(start_ns=200, start_domain="c", end_ns=100, end_domain="c")


def test_th19_cross_clock_comparison_rejected() -> None:
    with pytest.raises(CrossClockComparisonError):
        HarnessClock.elapsed_ns(start_ns=10, start_domain="clock.a", end_ns=20, end_domain="clock.b")


@pytest.mark.asyncio
async def test_th20_barrier_controlled_cancellation_interleaving() -> None:
    async def _run_order(cancel_before_dispatch: bool) -> AdmissionStatus:
        ctx = SessionContext(SessionIdentity("sess-th20"))
        await ctx.open()
        t1, _ = await ctx.begin_turn()
        g1, _ = await ctx.begin_generation(t1)
        await ctx.admit_media(QueuedMediaItem(g1, 0, b"\x01" * 320))
        barrier = DeterministicBarrier(watchdog_sec=1.0)

        async def _worker() -> AdmissionStatus:
            await barrier.checkpoint(InterleavingPoint.AFTER_ADMISSION_BEFORE_DISPATCH)
            st, _ = await ctx.dequeue_for_submission(g1)
            return st

        task = asyncio.create_task(_worker())
        await barrier.wait_for_point(InterleavingPoint.AFTER_ADMISSION_BEFORE_DISPATCH)
        if cancel_before_dispatch:
            await ctx.commit_interrupt("barge_in")
        barrier.release(InterleavingPoint.AFTER_ADMISSION_BEFORE_DISPATCH)
        st = await task
        await ctx.close("done")
        return st

    assert await _run_order(True) == AdmissionStatus.CANCELED
    assert await _run_order(False) == AdmissionStatus.ACCEPTED


def test_th21_local_rng_reproducibility_without_mutating_global() -> None:
    random.seed(999)
    expected_global = random.random()
    random.seed(999)
    gen = SyntheticAudioGenerator()
    s1 = gen.generate(AnalyticSignalKind.WHITE_NOISE, sample_rate_hz=8000, sample_count=160, seed=42)
    s2 = gen.generate(AnalyticSignalKind.WHITE_NOISE, sample_rate_hz=8000, sample_count=160, seed=42)
    assert s1.payload == s2.payload
    assert random.random() == expected_global


@pytest.mark.asyncio
async def test_th22_two_independent_sessions_isolated() -> None:
    c1 = SessionContext(SessionIdentity("sess-ind-1"))
    c2 = SessionContext(SessionIdentity("sess-ind-2"))
    await c1.open()
    await c2.open()
    t1, _ = await c1.begin_turn()
    g1, _ = await c1.begin_generation(t1)
    await c1.commit_interrupt("stop")
    t2, _ = await c2.begin_turn()
    g2, _ = await c2.begin_generation(t2)
    assert await c2.admit_media(QueuedMediaItem(g2, 0, b"\x02" * 320)) == AdmissionStatus.ACCEPTED
    await c1.close("done")
    await c2.close("done")


def test_th23_fixture_hash_mismatch_rejected(tmp_path: Path) -> None:
    fpath = tmp_path / "vec.bin"
    fpath.write_bytes(b"hello-fixture")
    reg = FixtureRegistry(tmp_path)
    m = FixtureManifest(
        fixture_id="fx-1",
        revision="1.0",
        source_class=EvidenceKind.SYNTHETIC_FIXTURE,
        generator_version="1.0",
        seed=1,
        relative_files=("vec.bin",),
        sha256={"vec.bin": "0" * 64},
    )
    with pytest.raises(HashMismatchError):
        reg.register(m, verify_files=True)


def test_th24_fixture_generation_cap_exceeded() -> None:
    gen = SyntheticAudioGenerator(limits=FixtureLimits(max_bytes_per_fixture=512, max_samples_per_fixture=200))
    with pytest.raises(FixtureCapExceededError):
        gen.generate(AnalyticSignalKind.SILENCE, sample_rate_hz=8000, sample_count=201)


def test_th25_calibration_heldout_overlap_detected(tmp_path: Path) -> None:
    reg = FixtureRegistry(tmp_path)
    m_cal = FixtureManifest("fx-a", "1.0", EvidenceKind.SYNTHETIC_FIXTURE, "1.0", 1, (), {}, split="calibration", duplicate_group_id="grp-1")
    m_eval = FixtureManifest("fx-b", "1.0", EvidenceKind.SYNTHETIC_FIXTURE, "1.0", 2, (), {}, split="held_out", duplicate_group_id="grp-1")
    reg.register(m_cal, verify_files=False)
    with pytest.raises(SplitLeakageError):
        reg.register(m_eval, verify_files=False)


# ---------------------------------------------------------------------------
# TH26 - TH34: Synthetic Audio Fixtures & Contracts
# ---------------------------------------------------------------------------


def test_th26_8k_pcm16_20ms() -> None:
    seg = SyntheticAudioGenerator().frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=8000, encoding=AudioEncoding.PCM_S16LE)
    assert seg.sample_count == 160
    assert len(seg.payload) == 320
    assert len(decode_pcm16_le(seg.payload)) == 160


def test_th27_16k_pcm16_20ms() -> None:
    seg = SyntheticAudioGenerator().frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, encoding=AudioEncoding.PCM_S16LE)
    assert seg.sample_count == 320
    assert len(seg.payload) == 640


def test_th28_48k_float32_20ms_and_variable_chunk() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.CHIRP, sample_rate_hz=48000, encoding=AudioEncoding.FLOAT32_LE)
    assert seg.sample_count == 960
    assert len(seg.payload) == 3840
    var_seg = gen.generate(AnalyticSignalKind.CHIRP, sample_rate_hz=48000, sample_count=1200, encoding=AudioEncoding.FLOAT32_LE)
    assert len(decode_float32_le(var_seg.payload)) == 1200


def test_th29_16k_vad_window_vs_20ms_frame() -> None:
    gen = SyntheticAudioGenerator()
    vad_win = gen.silero_vad_window_16k(AnalyticSignalKind.PINK_NOISE)
    media = gen.frame_20ms(AnalyticSignalKind.PINK_NOISE, sample_rate_hz=16000)
    assert vad_win.sample_count == 512 and vad_win.duration_sec == pytest.approx(0.032)
    assert media.sample_count == 320 and media.duration_sec == pytest.approx(0.020)


def test_th30_analytic_signals_deterministic_finite() -> None:
    gen = SyntheticAudioGenerator()
    for kind in (
        AnalyticSignalKind.SILENCE,
        AnalyticSignalKind.IMPULSE,
        AnalyticSignalKind.SINE,
        AnalyticSignalKind.CHIRP,
        AnalyticSignalKind.WHITE_NOISE,
        AnalyticSignalKind.PINK_NOISE,
        AnalyticSignalKind.MOTOR_FAN,
        AnalyticSignalKind.ECHO_SURROGATE,
    ):
        a = gen.generate(kind, sample_rate_hz=16000, sample_count=320, encoding=AudioEncoding.FLOAT32_LE, seed=7)
        b = gen.generate(kind, sample_rate_hz=16000, sample_count=320, encoding=AudioEncoding.FLOAT32_LE, seed=7)
        assert a.payload == b.payload
        vals = decode_float32_le(a.payload)
        assert len(vals) == 320


def test_th31_clipped_and_low_level_analytic_signals() -> None:
    gen = SyntheticAudioGenerator()
    clipped = decode_float32_le(gen.generate(AnalyticSignalKind.CLIPPED, sample_rate_hz=16000, sample_count=320, encoding=AudioEncoding.FLOAT32_LE).payload)
    low = decode_float32_le(gen.generate(AnalyticSignalKind.LOW_LEVEL, sample_rate_hz=16000, sample_count=320, encoding=AudioEncoding.FLOAT32_LE).payload)
    assert max(abs(x) for x in clipped) == pytest.approx(1.0)
    assert max(abs(x) for x in low) <= 0.0051


def test_th32_invalid_audio_payloads_rejected() -> None:
    with pytest.raises(ValueError):
        validate_audio_frame_contract(sample_rate_hz=16000, channels=1, encoding=AudioEncoding.PCM_S16LE, sample_count=160, payload=b"\x00" * 319)
    nan_bytes = struct.pack("<f", float("nan"))
    with pytest.raises(ValueError):
        validate_audio_frame_contract(sample_rate_hz=16000, channels=1, encoding=AudioEncoding.FLOAT32_LE, sample_count=1, payload=nan_bytes)
    with pytest.raises(ValueError):
        validate_audio_frame_contract(sample_rate_hz=12345, channels=1, encoding=AudioEncoding.PCM_S16LE, sample_count=10, payload=b"\x00" * 20)


def test_th33_gap_overlap_and_final_padding_metadata() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.generate(
        AnalyticSignalKind.SINE,
        sample_rate_hz=8000,
        sample_count=160,
        valid_sample_count=100,
        sample_offset=320,
        has_gap=True,
    )
    frame = seg.to_audio_frame(StreamRef("s1", "in", StreamDirection.INPUT, 0), sequence=2)
    assert frame.sample_offset == 320
    assert frame.valid_sample_count == 100
    assert "DISCONTINUITY_GAP" in frame.flags
    assert "FINAL_PADDING" in frame.flags


def test_th34_synthetic_speech_label_never_human() -> None:
    seg = SyntheticAudioGenerator().generate(AnalyticSignalKind.SPEECH_ENVELOPE, sample_rate_hz=16000, sample_count=320)
    assert seg.source_class == EvidenceKind.SYNTHETIC_FIXTURE
    assert seg.is_human_speech is False
    assert seg.acoustic_benchmark_eligible is False


# ---------------------------------------------------------------------------
# TH35 - TH60: Mock Providers, GPU, DB, Security & Transport
# ---------------------------------------------------------------------------


def test_th35_fake_vad_scripted_offsets() -> None:
    vad = FakeVADAdapter([
        ScriptedVADStep(SpeechEventKind.SPEECH_START, 160, "vad_onset", 0.9),
        ScriptedVADStep(SpeechEventKind.SPEECH_END, 800, "vad_offset", 0.1),
    ])
    events = vad.emit_all(session_id="sess-1")
    assert [e.sample_offset for e in events] == [160, 800]
    assert vad.measures_acoustic_vad is False


def test_th36_fake_asr_partial_then_final_variants() -> None:
    asr = FakeASRAdapter()
    p = asr.make_result(session_id="s1", utterance_id="u1", revision=1, status=ASRStatus.PARTIAL, raw_transcript="pasat")
    f = asr.make_result(
        session_id="s1",
        utterance_id="u1",
        revision=2,
        status=ASRStatus.FINAL,
        raw_transcript="pasat bakim",
        normalized_transcript="passat bakim",
        canonical_transcript="Volkswagen Passat bakim",
    )
    assert p.revision < f.revision
    assert f.raw_transcript != f.normalized_transcript != f.canonical_transcript


def test_th37_fake_asr_late_result_rejected_by_m02_fence() -> None:
    asr = FakeASRAdapter()
    scope = CancellationScope("gen:1")
    res = asr.make_result(session_id="s1", utterance_id="u1", revision=1, status=ASRStatus.FINAL, raw_transcript="test")
    scope.request_cancel("barge_in")
    admitted, reason = asr.deliver_with_fence(res, scope)
    assert admitted is False
    assert reason == "REJECTED_STALE_SCOPE"


def test_th38_fake_asr_unknown_confidence_stays_null() -> None:
    asr = FakeASRAdapter()
    res = asr.make_result(
        session_id="s1",
        utterance_id="u1",
        revision=1,
        status=ASRStatus.FINAL,
        raw_transcript="randevu",
        confidence=ConfidenceEstimate(avg_logprob=None, no_speech_prob=None, calibrated_prob=None),
    )
    assert res.confidence is not None
    assert res.confidence.avg_logprob is None
    assert res.confidence.calibrated_prob is None


def test_th39_fake_llm_malformed_response_safe() -> None:
    llm = FakeLLMAdapter()
    out = llm.parse_proposal("{not-valid-json")
    assert out.valid is False
    assert out.error_code == "MALFORMED_LLM_JSON"
    assert llm.executed_side_effects == []


def test_th40_fake_llm_admin_claim_and_tool_injection_untrusted() -> None:
    llm = FakeLLMAdapter()
    out = llm.parse_proposal(json.dumps({"intent": "booking_create", "claimed_role": "administrator", "proposed_tool": "admin.override"}))
    assert out.valid is True
    assert out.has_authority is False
    assert llm.executed_side_effects == []


def test_th41_fake_tts_generated_chunk_metadata() -> None:
    from backend.core.contracts import GenerationRef

    tts = FakeTTSAdapter()
    plan = tts.build_plan(generation_ref=GenerationRef("s1", 1, 1), plan_id="p1", response_id="r1", texts=("Merhaba",))
    chunk = tts.synthesize_chunk(plan, 0)
    assert chunk.sample_count == 960
    assert tts.is_production_fallback is False


def test_th42_fake_tts_invalid_or_reordered_chunk_rejected() -> None:
    from backend.core.contracts import GenerationRef

    tts = FakeTTSAdapter()
    plan = tts.build_plan(generation_ref=GenerationRef("s1", 1, 1), plan_id="p1", response_id="r1", texts=("Bir", "Iki"))
    with pytest.raises(ValueError):
        tts.synthesize_chunk(plan, 0, override_chunk_id="wrong-id")


@pytest.mark.asyncio
async def test_th43_delayed_fake_tts_after_revoke_rejected() -> None:
    from backend.core.contracts import GenerationRef

    tts = FakeTTSAdapter()
    scope = CancellationScope("gen:1")
    plan = tts.build_plan(generation_ref=GenerationRef("s1", 1, 1), plan_id="p1", response_id="r1", texts=("Bir",))
    scope.request_cancel("barge_in")
    outcome = await tts.synthesize_with_delay(plan, scope)
    assert outcome.accepted_chunks == ()
    assert outcome.rejected_stale_chunks == 1
    assert outcome.logical_cancelled and outcome.physical_completed


def test_th44_fake_gpu_stale_and_missing_probe() -> None:
    clock = HarnessClock(initial_ns=10_000_000_000)
    probe_adapter = FakeGPUProbeAdapter(clock)
    budget = MemoryBudget(clock=clock, headroom_bytes=256 * MIB, max_probe_age_ms=500)
    budget.update_probe(probe_adapter.missing_probe())
    assert budget.check_admission(64 * MIB).probe_status == ProbeStatus.UNRELIABLE
    budget.update_probe(probe_adapter.stale_probe(free_mib=4096, age_ms=5000))
    assert budget.check_admission(64 * MIB).probe_status == ProbeStatus.STALE


@pytest.mark.asyncio
async def test_th45_fake_gpu_async_completion_holds_lease_until_finish() -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    sched = UnifiedGpuScheduler(clock=clock)
    sched.residency_manager.register_model(
        ModelSpec("whisper-tr", HandleOwnership.OWNED, ProviderKind.CTRANSLATE2, 64 * MIB, loader=lambda: "ok")
    )
    sched.memory_budget.update_probe(FakeGPUProbeAdapter(clock).valid_probe(free_mib=2048))
    gate = asyncio.Event()
    worker = FakeCTranslate2Worker(["s1", "s2"], step_gate=gate)
    sched.register_adapter(ProviderKind.CTRANSLATE2, CTranslate2Adapter(lambda _r: worker))
    scope = CancellationScope("turn:1", clock=clock)
    req = ResourceRequest("req-1", PriorityClass.P1, ProviderKind.CTRANSLATE2, "whisper-tr", 64 * MIB, scope)
    task = asyncio.create_task(sched.run_request(req))
    await asyncio.sleep(0)
    gate.set()
    out = await task
    assert out.delivered == ("s1", "s2")


@pytest.mark.asyncio
async def test_th46_fake_gpu_oom_and_quarantine() -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    qm = QuarantineManager(clock=clock, max_entries=1)
    sched = UnifiedGpuScheduler(clock=clock, quarantine_manager=qm)
    sched.residency_manager.register_model(
        ModelSpec("tts-freya", HandleOwnership.OWNED, ProviderKind.PYTORCH, 64 * MIB, loader=lambda: "ok")
    )
    sched.memory_budget.update_probe(FakeGPUProbeAdapter(clock).valid_probe(free_mib=300))
    scope = CancellationScope("turn:1", clock=clock)
    req = ResourceRequest("req-oom", PriorityClass.P2, ProviderKind.PYTORCH, "tts-freya", 512 * MIB, scope)
    out = await sched.run_request(req)
    assert out.admission.value == "REJECTED_MEMORY"


def test_th47_fake_provider_invocation_recording_no_pii(tmp_path: Path) -> None:
    crm = IsolatedCRMSchemaFixture(tmp_path / "crm.db")
    crm.seed_slot("slot-1", 1)
    biz = FakeBusinessProvider(crm)
    biz.execute_booking(operation_id="op-1", idempotency_key="ik-1", slot_id="slot-1", customer_ref="cust-syn-001", vehicle_ref="veh-syn-001")
    assert biz.invocation_count == 1
    assert PIISecretScanner.scan_object([{"op": r.operation_id, "scope": r.scope} for r in biz.invocations]) == []


def test_th48_temp_db_fixture_schema_and_provenance(tmp_path: Path) -> None:
    crm = IsolatedCRMSchemaFixture(tmp_path / "crm.db")
    assert crm.schema_provenance == "SYNTHETIC_ISOLATED_CRM_FIXTURE"
    crm.seed_slot("slot-1", capacity=1)
    assert crm.try_claim_slot(booking_id="b1", slot_id="slot-1", customer_ref="cust-syn-001", vehicle_ref="veh-syn-001") is True


def test_th49_two_db_connections_concurrent_claim(tmp_path: Path) -> None:
    crm = IsolatedCRMSchemaFixture(tmp_path / "concurrent.db")
    crm.seed_slot("slot-race", capacity=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(crm.try_claim_slot, booking_id="b1", slot_id="slot-race", customer_ref="cust-syn-001", vehicle_ref="veh-syn-001")
        f2 = pool.submit(crm.try_claim_slot, booking_id="b2", slot_id="slot-race", customer_ref="cust-syn-002", vehicle_ref="veh-syn-002")
        wins = [f1.result(), f2.result()]
    assert wins.count(True) == 1
    assert wins.count(False) == 1


def test_th50_reopen_temp_db_verifies_persistence(tmp_path: Path) -> None:
    db_file = tmp_path / "persist.db"
    crm1 = IsolatedCRMSchemaFixture(db_file)
    crm1.seed_slot("slot-p", capacity=1)
    crm1.try_claim_slot(booking_id="b-persist", slot_id="slot-p", customer_ref="cust-syn-001", vehicle_ref="veh-syn-001")
    crm2 = IsolatedCRMSchemaFixture(db_file)
    rows = crm2.list_bookings()
    assert len(rows) == 1 and rows[0]["booking_id"] == "b-persist" and rows[0]["is_synthetic"] == 1


def test_th51_fake_principal_outside_resource_scope() -> None:
    idp = FakeIdentityProvider()
    p1 = idp.verified_customer("cust-syn-001")
    assert idp.can_access_record(p1, "rec-syn-001") is True
    assert idp.can_access_record(p1, "rec-syn-002") is False


def test_th52_expired_or_modified_confirmation_denied(tmp_path: Path) -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    audit = SecurityAuditLog(tmp_path / "audit.db")
    mgr = ConfirmationManager(clock=clock, default_ttl_ms=100, audit_log=audit)
    c = mgr.issue(tool_id="booking.create", action="create", actor_ref="cust-syn-001", state_revision=1, terms={"slot": "A"})
    mgr.present(c.challenge_id)
    mgr.approve(c.challenge_id, actor_ref="cust-syn-001", state_revision=1, terms={"slot": "A"})
    revoked = mgr.invalidate_if_changed(c.challenge_id, actor_ref="cust-syn-001", state_revision=1, terms={"slot": "B"})
    assert revoked.state.value == "REVOKED"

    c2 = mgr.issue(tool_id="booking.create", action="create", actor_ref="cust-syn-001", state_revision=1, terms={"slot": "A"})
    mgr.present(c2.challenge_id)
    mgr.approve(c2.challenge_id, actor_ref="cust-syn-001", state_revision=1, terms={"slot": "A"})
    clock.advance_ms(200)
    with pytest.raises(Exception):
        mgr.consume(c2.challenge_id, actor_ref="cust-syn-001", state_revision=1, terms={"slot": "A"})


def test_th53_unknown_provider_result_requires_reconcile(tmp_path: Path) -> None:
    biz = FakeBusinessProvider()
    receipt = biz.execute_booking(operation_id="op-u", idempotency_key="ik-u", slot_id="s1", customer_ref="c1", vehicle_ref="v1", simulate_unknown=True)
    assert receipt.status.value == "UNKNOWN"
    assert receipt.verified_result is False


def test_th54_audit_failure_blocks_protected_effect(tmp_path: Path) -> None:
    class BrokenAudit:
        def append(self, **kwargs):
            raise RuntimeError("audit_disk_error")

    engine = PolicyEngine(audit_log=BrokenAudit())  # type: ignore[arg-type]
    idp = FakeIdentityProvider()
    ctx = idp.make_context(session_id="s1", principal=idp.verified_customer())
    with pytest.raises(RuntimeError, match="audit_disk_error"):
        engine.evaluate(ctx, "booking.create")


def test_th55_tcp_fragmented_header_and_body() -> None:
    tr = FakeAudioSocketTransport()
    pkt = pack_audiosocket_frame(AUDIOSOCKET_AUDIO, b"\x01\x02" * 160)
    tr.push_rx_bytes(pkt[:2])
    assert tr.try_parse_frames() == []
    tr.push_rx_bytes(pkt[2:10])
    assert tr.try_parse_frames() == []
    tr.push_rx_bytes(pkt[10:])
    frames = tr.try_parse_frames()
    assert len(frames) == 1 and frames[0][0] == AUDIOSOCKET_AUDIO and len(frames[0][1]) == 320


def test_th56_tcp_coalesced_frames() -> None:
    tr = FakeAudioSocketTransport()
    p1 = pack_audiosocket_frame(AUDIOSOCKET_DTMF, b"1")
    p2 = pack_audiosocket_frame(AUDIOSOCKET_AUDIO, b"\x00" * 320)
    tr.push_rx_bytes(p1 + p2)
    frames = tr.try_parse_frames()
    assert len(frames) == 2 and frames[0] == (AUDIOSOCKET_DTMF, b"1") and len(frames[1][1]) == 320


def test_th57_disconnect_partial_write_and_backpressure() -> None:
    tr = FakeAudioSocketTransport(max_send_buffer_bytes=500)
    ok_p, written, st_p = tr.write_frame(b"\x01" * 320, partial_write_cap=100)
    assert ok_p is False and written == 100 and st_p == "PARTIAL_WRITE"
    tr.disconnect()
    ok_d, _, st_d = tr.write_frame(b"\x01" * 100)
    assert ok_d is False and st_d == "DISCONNECTED_IN_FLIGHT_UNKNOWN"


def test_th58_dtmf_duplicate_fixture() -> None:
    inj = FakeDTMFInjector(dedup_window_ms=100)
    assert inj.receive_digit("5", at_ms=0) is True
    assert inj.receive_digit("5", at_ms=50) is False
    assert inj.receive_digit("5", at_ms=120) is True


def test_th59_playback_flush_submit_ack_distinct() -> None:
    ep = FakePlaybackEndpoint()
    ep.enqueue(b"f1")
    ep.enqueue(b"f2")
    idx = ep.submit_next()
    assert idx == 0
    ep.ack_submitted(0)
    cleared = ep.flush_server_queue()
    assert cleared == 1
    assert ep.audible_cut_verified is False


def test_th60_rtp_reordering_and_loss_separate_from_tcp() -> None:
    rtp = FakeRTPDatagramChannel()
    assert rtp.transport_mode == "RTP_DATAGRAM_SIMULATION"
    rtp.send(1, b"a")
    rtp.send(2, b"b")
    rtp.send(3, b"c")
    out = rtp.deliver_with_reordering_and_loss(drop_sequences=frozenset({2}), reverse_order=True)
    assert [d.sequence for d in out] == [3, 1]


# ---------------------------------------------------------------------------
# TH61 - TH80: Golden Replay, Fault Injection, Compatibility & Evidence Gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_th61_golden_greeting_replay(tmp_path: Path) -> None:
    res = await DeterministicReplayEngine().replay("GS01", sandbox_dir=tmp_path)
    assert res.status == GateStatus.PASS and res.cleanup_ok is True


@pytest.mark.asyncio
async def test_th62_golden_booking_deferred_and_slot_change_replay(tmp_path: Path) -> None:
    eng = DeterministicReplayEngine()
    gs02 = await eng.replay("GS02", sandbox_dir=tmp_path)
    gs03 = await eng.replay("GS03", sandbox_dir=tmp_path)
    assert gs02.status == GateStatus.NOT_RUN and gs02.details["pending_future_owner"] == "F3"
    assert gs03.status == GateStatus.PASS


@pytest.mark.asyncio
async def test_th63_golden_ambiguous_vehicle_and_no_slot(tmp_path: Path) -> None:
    eng = DeterministicReplayEngine()
    gs04 = await eng.replay("GS04", sandbox_dir=tmp_path)
    gs05 = await eng.replay("GS05", sandbox_dir=tmp_path)
    assert gs04.status == GateStatus.PASS
    assert gs05.status == GateStatus.NOT_RUN


@pytest.mark.asyncio
async def test_th64_golden_two_session_isolation(tmp_path: Path) -> None:
    res = await DeterministicReplayEngine().replay("GS16", sandbox_dir=tmp_path)
    assert res.status == GateStatus.PASS and res.forbidden_effects_triggered == ()


@pytest.mark.asyncio
async def test_th65_replay_same_revision_twice_idempotent(tmp_path: Path) -> None:
    eng = DeterministicReplayEngine()
    r1 = await eng.replay("GS09", sandbox_dir=tmp_path, run_tag="runA")
    r2 = await eng.replay("GS09", sandbox_dir=tmp_path, run_tag="runB")
    assert r1.status == GateStatus.PASS and r2.status == GateStatus.PASS
    assert r1.observed_effects == r2.observed_effects


def test_th66_fault_plan_targets_occurrence_and_not_production() -> None:
    plan = FaultPlan("fp-1", (FaultTarget("asr", "decode", occurrence=2, fault_kind=FaultKind.INVALID_CONTRACT),))
    inj = FailureInjector(plan)
    assert inj.PRODUCTION_REACHABLE is False
    assert inj.check_and_fire("asr", "decode") is None
    with pytest.raises(InjectedFaultError):
        inj.check_and_fire("asr", "decode")


@pytest.mark.asyncio
async def test_th67_observer_failure_does_not_corrupt_core_control() -> None:
    bus = BoundedEventBus(max_lane_size=4)

    def broken_sink(_env):
        raise RuntimeError("observer_down")

    ctx = SessionContext(SessionIdentity("sess-th67"), event_sink=broken_sink)
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    g1, _ = await ctx.begin_generation(t1)
    assert await ctx.commit_interrupt("barge_in") is True
    assert await ctx.admit_media(QueuedMediaItem(g1, 0, b"\x00" * 320)) == AdmissionStatus.CANCELED
    await ctx.close("done")
    assert bus.stats.published_count == 0


def test_th68_m00_feature_join_detects_missing_or_duplicate(tmp_path: Path) -> None:
    reg = json.loads((M00_BASELINE_DIR / "FEATURE_REGISTRY.json").read_text(encoding="utf-8"))
    reg["records"].append(dict(reg["records"][0]))  # inject duplicate ID
    bad_dir = tmp_path / "bad_m00"
    bad_dir.mkdir()
    (bad_dir / "FEATURE_REGISTRY.json").write_text(json.dumps(reg), encoding="utf-8")
    (bad_dir / "REGRESSION_MATRIX.csv").write_text((M00_BASELINE_DIR / "REGRESSION_MATRIX.csv").read_text(encoding="utf-8"), encoding="utf-8")
    summary = FeatureRegressionMapper(REPO_ROOT, bad_dir).build_matrix()
    assert summary.status == GateStatus.FAIL
    assert reg["records"][0]["feature_id"] in summary.duplicate_feature_ids


def test_th69_feature_mapped_but_no_executable_test_visible(tmp_path: Path) -> None:
    reg = {"records": [{"feature_id": "FT-X", "name": "MissingTest", "domain": "CORE", "target_owner": "CORE", "implementation_state": "LIVE_PATH", "existing_test_ids": ["tests/nonexistent_test_file.py"], "verification_status": "PASS"}]}
    bad_dir = tmp_path / "gap_m00"
    bad_dir.mkdir()
    (bad_dir / "FEATURE_REGISTRY.json").write_text(json.dumps(reg), encoding="utf-8")
    (bad_dir / "REGRESSION_MATRIX.csv").write_text("feature_id,target_owner,preserve_behavior,existing_tests,baseline_status\nFT-X,CORE,x,tests/nonexistent_test_file.py,PASS\n", encoding="utf-8")
    summary = FeatureRegressionMapper(REPO_ROOT, bad_dir).build_matrix()
    assert summary.status == GateStatus.FAIL
    assert summary.rows[0].disposition == "COVERAGE_GAP_NO_EXECUTABLE_TEST"


def test_th70_historical_failure_preserved_new_regression_blocks() -> None:
    mapper = FeatureRegressionMapper(REPO_ROOT, M00_BASELINE_DIR)
    s_base = mapper.build_matrix(observed_test_outcomes={"tests/test_madde3_customer_experience.py": GateStatus.FAIL})
    f3 = next(r for r in s_base.rows if r.feature_id == "FT-F3-0001")
    assert f3.disposition == "KNOWN_BASELINE_FAILURE_UNCHANGED"
    assert f3.behavioral_verified is False

    s_new_reg = mapper.build_matrix(observed_test_outcomes={"tests/test_core.py": GateStatus.FAIL})
    assert s_new_reg.status == GateStatus.FAIL
    assert s_new_reg.new_regression_count >= 1


def test_th71_api_compatibility_snapshot_checked() -> None:
    rep = CompatibilityChecker(REPO_ROOT, M00_BASELINE_DIR).check_api_compatibility()
    assert rep.baseline_count == 243
    assert rep.status == GateStatus.PASS, rep.drift_items


def test_th72_ui_compatibility_static_scope_retained() -> None:
    rep = CompatibilityChecker(REPO_ROOT, M00_BASELINE_DIR).check_ui_compatibility()
    assert rep.baseline_count == 29
    assert rep.status == GateStatus.PASS, rep.drift_items
    assert rep.observation_scope == "STATIC_SOURCE_TRACE_ONLY"


def test_th73_db_config_seed_compatibility_checked() -> None:
    chk = CompatibilityChecker(REPO_ROOT, M00_BASELINE_DIR)
    db_rep = chk.check_db_compatibility()
    cfg_rep = chk.check_config_model_compatibility()
    assert db_rep.baseline_count == 33 and db_rep.status == GateStatus.PASS, db_rep.drift_items
    assert cfg_rep.baseline_count == 81 and cfg_rep.status == GateStatus.PASS, cfg_rep.drift_items


def test_th74_foundation_test_id_registration_no_duplicates() -> None:
    dups = validate_no_duplicate_test_ids()
    assert dups == []
    total_ids = sum(len(r.planned_ids) for r in FOUNDATION_SUITE_REGISTRATIONS)
    assert total_ids == 460


def test_th75_evidence_tampered_sha_rejected(tmp_path: Path) -> None:
    ev_dir = tmp_path / "evidence"
    ev_dir.mkdir()
    target = tmp_path / "rep.json"
    target.write_text("{}", encoding="utf-8")
    (ev_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (ev_dir / "artifact_hashes.json").write_text(json.dumps({"rep.json": "f" * 64}), encoding="utf-8")
    errs = EvidenceValidator(tmp_path).verify_evidence_bundle(ev_dir)
    assert any("ARTIFACT_SHA_MISMATCH" in e for e in errs)


def test_th76_mandatory_gate_aggregation_truth_table() -> None:
    # Optional fail does not block
    s1 = evaluate_gates([
        GateRecord("G00", True, GateStatus.PASS, "ok", ("e",)),
        GateRecord("OPT", False, GateStatus.FAIL, "opt", ("e",)),
    ])
    assert s1.overall == GateStatus.PASS and s1.ready is True
    # Mandatory HOLD -> HOLD
    s2 = evaluate_gates([
        GateRecord("G00", True, GateStatus.PASS, "ok", ("e",)),
        GateRecord("G01", True, GateStatus.HOLD, "hold", ("e",)),
    ])
    assert s2.overall == GateStatus.HOLD and s2.ready is False
    # Mandatory FAIL overrides HOLD -> FAIL
    s3 = evaluate_gates([
        GateRecord("G01", True, GateStatus.HOLD, "hold", ("e",)),
        GateRecord("G02", True, GateStatus.FAIL, "fail", ("e",)),
    ])
    assert s3.overall == GateStatus.FAIL and s3.ready is False


def test_th77_skip_xpass_inconsistent_counts_rejected() -> None:
    st_skip, _ = reconcile_run_status(exit_code=0, counts=PytestSummaryCounts(5, 4, 0, 1, 0, 0, 0))
    st_xpass, _ = reconcile_run_status(exit_code=0, counts=PytestSummaryCounts(5, 4, 0, 0, 0, 1, 0))
    assert st_skip == GateStatus.HOLD
    assert st_xpass == GateStatus.HOLD


def test_th78_synthetic_evidence_mislabeled_endpoint_rejected() -> None:
    with pytest.raises(ValueError):
        CaseResult(
            case_id="TH78-BAD",
            collected_node_ids=("node::1",),
            executed=True,
            status=GateStatus.PASS,
            reason_code="OK",
            source_class=EvidenceKind.MOCK_RUNTIME,
            observation_scope=ObservationScope.ENDPOINT,
        )


def test_th79_secret_pii_canary_rejected() -> None:
    findings = PIISecretScanner.scan_object({
        "raw_transcript": "aracim 34 ABC 1234",
        "note": "tel 0532 123 45 67 Bearer eyJhbGciOiJIUzI1NiJ9.abc.def",
    })
    assert len(findings) >= 2


def test_th80_core_gate_missing_package_blocks_even_when_m08_pass() -> None:
    m08_summary = evaluate_gates([GateRecord("G00", True, GateStatus.PASS, "ok", ("ev",))])
    ci = {f"CI{i:02d}": GateStatus.PASS for i in range(1, 25)}
    ci["CI21"] = GateStatus.NOT_RUN
    cg = [GateRecord(f"CG{i:02d}", True, GateStatus.PASS, "ok", ("ev",)) for i in range(12)]
    pkgs = {f"M0{i}": GateStatus.PASS for i in range(9)}
    dec = evaluate_core_integration(run_id="th80", m08_summary=m08_summary, package_statuses=pkgs, ci_results=ci, cg_gates=cg)
    assert dec.m08_ready is True
    assert dec.core_integration_ready is False
    assert dec.vertical_slice_ready is False
    assert dec.owner_execution_authorized is False
    assert dec.synthetic_product_acceptance_status == GateStatus.NOT_RUN
    assert dec.human_sip_status == GateStatus.NOT_RUN
