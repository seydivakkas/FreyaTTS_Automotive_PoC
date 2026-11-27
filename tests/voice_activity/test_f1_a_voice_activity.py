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
import concurrent.futures
import json
import math
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from backend.core.configuration.contracts import ConfigSource, SupervisorMode
from backend.core.configuration.snapshots import ConfigSnapshotStore, build_snapshot
from backend.core.contracts.audio import AudioEncoding, AudioFormat, AudioFrame
from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    MetricStatus,
    SessionIdentity,
    StreamDirection,
    StreamRef,
    TurnRef,
)
from backend.core.contracts.speech import SpeechEventKind, Utterance
from backend.core.runtime.resource_ledger import LeaseState, ResourceLedger
from backend.core.runtime.session_context import SessionContext
from backend.observability.event_bus import BoundedEventBus, DropPolicy
from backend.observability.projection import Projection
from backend.voice_activity import (
    AcousticState,
    BoundedUtteranceQueue,
    EndpointCutDecision,
    EndpointingPolicy,
    F1ConfigAdapter,
    F1ProfileConfig,
    F1RouteMode,
    FinalizationReason,
    FinalizationStatus,
    FrameSynchronizer,
    LegacyEndpointAdapter,
    LookbackBuffer,
    LookbackCapacityExceededError,
    M02TurnAllocatorBridge,
    PrerequisiteCheckStatus,
    RejectionReason,
    SampleAccountingLedger,
    SileroTemplateAdapter,
    SpeechStateMachine,
    StreamAcousticProcessor,
    UtteranceManager,
    VADEngineAdapter,
    VADIsolationStrategy,
    VADIsolationUnsupportedError,
    VADObservation,
    VADStateManager,
    VADWindow,
    VoiceActivityPipeline,
    check_f1_a_prerequisites,
    compute_same_domain_duration_ms,
    inspect_vad_backend_isolation,
    utterance_to_legacy_stt_ndarray,
)
from tests.harness.evidence_validator import EvidenceValidator, PIISecretScanner
from tests.harness.fake_clock import HarnessClock
from tests.harness.feature_regression import FeatureRegressionMapper
from tests.harness.synthetic_audio import AnalyticSignalKind, SyntheticAudioGenerator

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_RUN_ID = "20261126T004342Z"
FMT_16K_F32 = AudioFormat(16000, 1, AudioEncoding.FLOAT32_LE)
FMT_16K_PCM16 = AudioFormat(16000, 1, AudioEncoding.PCM_S16LE)


class StatefulFakeVADBackend:
    """
    Deterministic stateful fake VAD backend exposing cross-stream contamination
    if an adapter fails to isolate per-stream state.

    Computes score from both input window mean-abs energy / script AND hidden recurrent state.
    """

    model_revision = "fake_stateful_silero_v1"

    def __init__(self, *, script_by_first_sample: dict[int, float] | None = None) -> None:
        self._script = script_by_first_sample or {}
        self.call_count = 0

    def initial_state(self) -> dict[str, float | int]:
        return {"step": 0, "ema": 0.0}

    def infer_with_state(
        self,
        window_f32: np.ndarray,
        sample_rate_hz: int,
        state: dict[str, float | int],
    ) -> tuple[float, dict[str, float | int]]:
        assert sample_rate_hz == 16000
        assert window_f32.shape == (512,)
        self.call_count += 1
        step = int(state["step"]) + 1
        ema = float(state["ema"])
        marker = int(round(float(window_f32[0]) * 10000))
        if marker in self._script:
            raw = self._script[marker]
            new_ema = 0.7 * ema + 0.3 * raw
        else:
            energy = float(np.mean(np.abs(window_f32)))
            raw = min(1.0, max(0.0, energy * 0.8 + 0.25 * ema))
            new_ema = 0.65 * ema + 0.35 * min(1.0, energy)
        score = min(1.0, max(0.0, raw if marker in self._script else 0.75 * raw + 0.25 * new_ema))
        return score, {"step": step, "ema": new_ema}


class WindowIndexScriptedVADBackend:
    """State-passing fake VAD returning scripted score by window counter per stream."""

    model_revision = "fake_scripted_silero_v1"

    def __init__(self, scores: list[float] | dict[int, float], *, default: float = 0.05) -> None:
        if isinstance(scores, list):
            self._scores = {i: s for i, s in enumerate(scores)}
        else:
            self._scores = dict(scores)
        self._default = default
        self.calls = 0

    def initial_state(self) -> int:
        return 0

    def infer_with_state(self, window_f32: np.ndarray, sample_rate_hz: int, state: int) -> tuple[float, int]:
        self.calls += 1
        score = self._scores.get(state, self._default)
        return score, state + 1


class BrokenSharedMutableVAD:
    """Unsafe VAD backend with mutable shared state and no clone/state-passing API."""

    model_revision = "unsafe_shared_v1"

    def __init__(self) -> None:
        self._hidden = 0.0

    def __call__(self, window_f32: np.ndarray, sr: int) -> float:
        self._hidden += float(np.mean(window_f32))
        return 0.5


def _make_stream_ref(session_id: str = "sess-1", stream_id: str = "in-1", epoch: int = 0) -> StreamRef:
    return StreamRef(session_id=session_id, stream_id=stream_id, direction=StreamDirection.INPUT, format_epoch=epoch)


def _make_f32_frame(
    stream_ref: StreamRef,
    seq: int,
    offset: int,
    samples: np.ndarray,
    *,
    valid_sample_count: int | None = None,
    flags: frozenset[str] = frozenset(),
    captured_monotonic_ns: int | None = None,
    clock_domain: str | None = None,
) -> AudioFrame:
    arr = np.ascontiguousarray(samples, dtype=np.float32)
    return AudioFrame(
        schema_version=CONTRACT_SCHEMA_VERSION,
        stream_ref=stream_ref,
        sequence=seq,
        format=FMT_16K_F32,
        sample_count=int(arr.shape[0]),
        sample_offset=offset,
        payload=arr.tobytes(),
        valid_sample_count=valid_sample_count,
        flags=flags,
        captured_monotonic_ns=captured_monotonic_ns,
        clock_domain=clock_domain,
    )


def _make_processor(
    *,
    scores: list[float] | dict[int, float],
    session_id: str = "sess-1",
    stream_id: str = "in-1",
    profile: F1ProfileConfig | None = None,
    clock: HarnessClock | None = None,
    queue_max_items: int = 8,
    event_bus: BoundedEventBus | None = None,
    strict_pinned_capacity: bool = False,
) -> tuple[StreamAcousticProcessor, BoundedUtteranceQueue, HarnessClock, SessionContext]:
    clk = clock or HarnessClock(initial_ns=1_000_000)
    ctx = SessionContext(SessionIdentity(session_id=session_id), clock=clk)
    asyncio.run(ctx.open())
    sref = _make_stream_ref(session_id=session_id, stream_id=stream_id)
    prof = profile or F1ProfileConfig.strict_experimental(route_mode=F1RouteMode.STRICT)
    queue = BoundedUtteranceQueue(max_items=queue_max_items, max_bytes=max(1, queue_max_items) * 1_280_000)
    engine = VADEngineAdapter(WindowIndexScriptedVADBackend(scores), clock=clk)
    proc = StreamAcousticProcessor(
        sref,
        profile=prof,
        config_revision="rev-test",
        vad_engine=engine,
        turn_allocator=M02TurnAllocatorBridge(ctx),
        consumer=queue,
        clock=clk,
        ledger=ctx.ledger,
        event_bus=event_bus,
        session_context=ctx,
        strict_pinned_capacity=strict_pinned_capacity,
    )
    return proc, queue, clk, ctx


def _feed_windows(proc: StreamAcousticProcessor, n_windows: int, *, start_offset: int = 0, start_seq: int = 0) -> list[Any]:
    outcomes = []
    for i in range(n_windows):
        samples = np.full(512, 0.01 * ((i % 7) + 1), dtype=np.float32)
        samples[0] = float(i) / 10000.0
        frame = _make_f32_frame(proc.stream_ref, start_seq + i, start_offset + i * 512, samples)
        outcomes.append(proc.process_frame(frame))
    return outcomes


# ---------------------------------------------------------------------------
# VA01–VA04: Preflight, Passive Import, Contract Mapping
# ---------------------------------------------------------------------------

def test_va01_missing_or_stale_core_gate_holds(tmp_path: Path) -> None:
    res = check_f1_a_prerequisites(tmp_path, core_run_id="missing_run", require_f0_gate=False)
    assert res.status == PrerequisiteCheckStatus.HOLD
    assert any("MISSING_CORE_GATE" in item for item in res.missing_or_failed)


def test_va02_missing_f0_gate_holds_citing_prerequisite(tmp_path: Path) -> None:
    core_dir = tmp_path / "docs" / "freya2" / "core_integration" / CORE_RUN_ID
    core_dir.mkdir(parents=True)
    (core_dir / "CORE_ACCEPTANCE_MATRIX.json").write_text(
        json.dumps({
            "core_integration_ready": True,
            "core_integration_status": "PASS",
            "gates": {f"CG{i:02d}": "PASS" for i in range(12)},
        }),
        encoding="utf-8",
    )
    res = check_f1_a_prerequisites(tmp_path, core_run_id=CORE_RUN_ID, require_f0_gate=True)
    assert res.status == PrerequisiteCheckStatus.HOLD
    assert any("F0_A" in item for item in res.missing_or_failed)


def test_va03_passive_imports_no_model_or_threads() -> None:
    code = (
        "import sys, threading; "
        "before = threading.active_count(); "
        "import backend.voice_activity; "
        "after = threading.active_count(); "
        "bad = [m for m in ('torch','silero_vad','faster_whisper','ctranslate2','backend.models','backend.db','backend.main') if m in sys.modules]; "
        "assert after == before, (before, after); "
        "assert not bad, bad; "
        "print('PASSIVE_OK')"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "PASSIVE_OK" in proc.stdout


def test_va04_m01_contract_mapping_and_schema_version() -> None:
    sref = _make_stream_ref()
    sync = FrameSynchronizer(sref)
    valid = _make_f32_frame(sref, 0, 0, np.zeros(512, dtype=np.float32))
    assert sync.admit_frame(valid).accepted is True

    with pytest.raises(ValueError):
        AudioFrame(
            schema_version="3.0",
            stream_ref=sref,
            sequence=1,
            format=FMT_16K_F32,
            sample_count=512,
            sample_offset=512,
            payload=np.zeros(512, dtype=np.float32).tobytes(),
        )

    # Also verify synchronizer rejects a spoofed/incompatible schema_version object defensively.
    class FakeBadVersionFrame:
        pass

    res = sync.admit_frame(FakeBadVersionFrame())
    assert res.accepted is False
    assert res.rejection_reason == RejectionReason.NONFINITE_OR_LENGTH


# ---------------------------------------------------------------------------
# VA05–VA16: Frame Synchronizer, Sample Accounting, Format, Gap, EOS
# ---------------------------------------------------------------------------

def test_va05_512_valid_f32_samples_one_window_no_pad() -> None:
    sref = _make_stream_ref()
    sync = FrameSynchronizer(sref)
    arr = np.linspace(-0.5, 0.5, 512, dtype=np.float32)
    res = sync.admit_frame(_make_f32_frame(sref, 0, 0, arr))
    assert res.accepted is True
    assert len(res.windows) == 1
    w = res.windows[0]
    assert w.start_sample == 0
    assert w.end_sample_exclusive == 512
    assert w.valid_samples == 512
    assert w.padded_for_inference is False
    assert np.allclose(w.samples_f32, arr)
    assert sync.remainder_samples == 0
    assert sync.accounting.snapshot().conservation_balanced is True


def test_va06_five_by_320_yields_3_windows_and_64_remainder() -> None:
    sref = _make_stream_ref()
    sync = FrameSynchronizer(sref)
    windows = []
    for i in range(5):
        arr = np.full(320, float(i + 1) * 0.1, dtype=np.float32)
        res = sync.admit_frame(_make_f32_frame(sref, i, i * 320, arr))
        assert res.accepted is True
        windows.extend(res.windows)
    assert len(windows) == 3
    assert [(w.start_sample, w.end_sample_exclusive) for w in windows] == [(0, 512), (512, 1024), (1024, 1536)]
    assert sync.remainder_samples == 64
    snap = sync.accounting.snapshot()
    assert snap.accepted_real_samples == 1600
    assert snap.processed_real_samples == 1536
    assert snap.buffered_remainder_samples == 64
    assert snap.conservation_balanced is True


def test_va07_variable_block_partition_invariance() -> None:
    gen = SyntheticAudioGenerator()
    total = 2048
    ref_seg = gen.generate(AnalyticSignalKind.SPEECH_ENVELOPE, sample_rate_hz=16000, sample_count=total, encoding=AudioEncoding.FLOAT32_LE, seed=7)
    ref_arr = np.frombuffer(ref_seg.payload, dtype="<f4")

    sref_ref = _make_stream_ref(stream_id="ref")
    sync_ref = FrameSynchronizer(sref_ref)
    ref_res = sync_ref.admit_frame(_make_f32_frame(sref_ref, 0, 0, ref_arr))

    sref_var = _make_stream_ref(stream_id="var")
    sync_var = FrameSynchronizer(sref_var)
    chunks = [1, 160, 800, 1023, 64]
    assert sum(chunks) == total
    var_windows = []
    offset = 0
    for seq, size in enumerate(chunks):
        r = sync_var.admit_frame(_make_f32_frame(sref_var, seq, offset, ref_arr[offset : offset + size]))
        assert r.accepted is True
        var_windows.extend(r.windows)
        offset += size

    assert len(var_windows) == len(ref_res.windows) == 4
    for w_ref, w_var in zip(ref_res.windows, var_windows):
        assert w_ref.start_sample == w_var.start_sample
        assert w_ref.end_sample_exclusive == w_var.end_sample_exclusive
        assert np.array_equal(w_ref.samples_f32, w_var.samples_f32)


def test_va08_pcm16_limits_scale_no_overflow_or_double_norm() -> None:
    sref = _make_stream_ref()
    sync = FrameSynchronizer(sref)
    pcm_vals = [-32768, 0, 32767] + [0] * 509
    payload = struct.pack("<512h", *pcm_vals)
    frame = AudioFrame(
        schema_version=CONTRACT_SCHEMA_VERSION,
        stream_ref=sref,
        sequence=0,
        format=FMT_16K_PCM16,
        sample_count=512,
        sample_offset=0,
        payload=payload,
    )
    res = sync.admit_frame(frame)
    assert res.accepted is True
    w = res.windows[0]
    assert w.samples_f32[0] == pytest.approx(-1.0)
    assert w.samples_f32[1] == pytest.approx(0.0)
    assert w.samples_f32[2] == pytest.approx(32767.0 / 32768.0, abs=1e-7)


def test_va09_wrong_rate_channel_direction_rejected_without_vad_call() -> None:
    proc, _, _, _ = _make_processor(scores=[0.9])
    bad_rate_ref = proc.stream_ref
    bad_8k = AudioFrame(
        schema_version=CONTRACT_SCHEMA_VERSION,
        stream_ref=bad_rate_ref,
        sequence=0,
        format=AudioFormat(8000, 1, AudioEncoding.PCM_S16LE),
        sample_count=160,
        sample_offset=0,
        payload=b"\x00\x00" * 160,
    )
    out_8k = proc.process_frame(bad_8k)
    assert out_8k.admission.accepted is False
    assert out_8k.admission.rejection_reason == RejectionReason.WRONG_FORMAT

    bad_stereo = AudioFrame(
        schema_version=CONTRACT_SCHEMA_VERSION,
        stream_ref=bad_rate_ref,
        sequence=1,
        format=AudioFormat(16000, 2, AudioEncoding.FLOAT32_LE),
        sample_count=512,
        sample_offset=0,
        payload=b"\x00\x00\x00\x00" * (512 * 2),
    )
    out_stereo = proc.process_frame(bad_stereo)
    assert out_stereo.admission.accepted is False
    assert out_stereo.admission.rejection_reason == RejectionReason.WRONG_FORMAT

    out_dir_ref = StreamRef("sess-1", "in-1", StreamDirection.OUTPUT, 0)
    bad_dir = _make_f32_frame(out_dir_ref, 2, 0, np.zeros(512, dtype=np.float32))
    out_dir = proc.process_frame(bad_dir)
    assert out_dir.admission.accepted is False
    assert out_dir.admission.rejection_reason == RejectionReason.WRONG_STREAM
    assert proc.vad_state._engine._backend.calls == 0  # type: ignore[attr-defined]


def test_va10_nan_inf_invalid_length_rejected_before_allocation() -> None:
    sref = _make_stream_ref()
    sync = FrameSynchronizer(sref)
    nan_payload = struct.pack("<4f", float("nan"), 0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        AudioFrame(
            schema_version=CONTRACT_SCHEMA_VERSION,
            stream_ref=sref,
            sequence=0,
            format=FMT_16K_F32,
            sample_count=4,
            sample_offset=0,
            payload=nan_payload,
        )
    with pytest.raises(ValueError):
        AudioFrame(
            schema_version=CONTRACT_SCHEMA_VERSION,
            stream_ref=sref,
            sequence=0,
            format=FMT_16K_F32,
            sample_count=4,
            sample_offset=0,
            payload=b"\x00" * 12,
        )
    assert sync.accounting.snapshot().accepted_real_samples == 0


def test_va11_duplicate_sequence_and_overlapping_offset_rejected() -> None:
    sref = _make_stream_ref()
    sync = FrameSynchronizer(sref)
    f0 = _make_f32_frame(sref, 0, 0, np.zeros(512, dtype=np.float32))
    assert sync.admit_frame(f0).accepted is True

    dup = _make_f32_frame(sref, 0, 512, np.zeros(512, dtype=np.float32))
    r_dup = sync.admit_frame(dup)
    assert r_dup.accepted is False
    assert r_dup.rejection_reason == RejectionReason.DUPLICATE

    overlap = _make_f32_frame(sref, 1, 400, np.zeros(512, dtype=np.float32))
    r_ov = sync.admit_frame(overlap)
    assert r_ov.accepted is False
    assert r_ov.rejection_reason == RejectionReason.OVERLAP
    assert sync.accounting.snapshot().accepted_real_samples == 512


def test_va12_gap_in_offsets_triggers_discontinuity_reset_no_silence_synthesis() -> None:
    proc, _, _, _ = _make_processor(scores=[0.9, 0.9, 0.9])
    _feed_windows(proc, 2, start_offset=0, start_seq=0)
    assert proc.fsm.state == AcousticState.SPEECH_ACTIVE

    gap_frame = _make_f32_frame(proc.stream_ref, 2, 5000, np.zeros(512, dtype=np.float32))
    out = proc.process_frame(gap_frame)
    assert out.discontinuity_reset is True
    assert out.admission.discontinuity_gap_samples == 5000 - 1024
    assert proc.accounting.snapshot().excluded_gap_samples == 5000 - 1024
    assert any(e.event_type == "f1.discontinuity" for e in proc.telemetry.events)


def test_va13_old_epoch_frame_rejected_after_epoch_advance() -> None:
    sref0 = _make_stream_ref(epoch=0)
    sref1 = _make_stream_ref(epoch=1)
    sync = FrameSynchronizer(sref0)
    assert sync.admit_frame(_make_f32_frame(sref0, 0, 0, np.zeros(512, dtype=np.float32))).accepted is True
    assert sync.admit_frame(_make_f32_frame(sref1, 1, 0, np.zeros(512, dtype=np.float32))).accepted is True

    stale = sync.admit_frame(_make_f32_frame(sref0, 2, 512, np.zeros(512, dtype=np.float32)))
    assert stale.accepted is False
    assert stale.rejection_reason == RejectionReason.STALE_EPOCH


def test_va14_empty_valid_data_rejected_then_eos_once() -> None:
    proc, _, _, _ = _make_processor(scores=[0.1])
    empty_frame = _make_f32_frame(proc.stream_ref, 0, 0, np.zeros(512, dtype=np.float32), valid_sample_count=0)
    res = proc.process_frame(empty_frame)
    assert res.admission.accepted is False
    assert res.admission.rejection_reason == RejectionReason.EMPTY_FRAME

    evs1, fins1 = proc.flush_eos()
    assert len(evs1) == 0 and len(fins1) == 0
    assert proc.synchronizer.eos_flushed is True


def test_va15_eos_with_73_sample_tail_preserves_real_count_no_fake_payload() -> None:
    sref = _make_stream_ref()
    sync_pad = FrameSynchronizer(sref, allow_eos_model_padding=True)
    assert sync_pad.admit_frame(_make_f32_frame(sref, 0, 0, np.ones(73, dtype=np.float32))).accepted is True
    win, unclass = sync_pad.flush_eos()
    assert unclass == 0
    assert win is not None
    assert win.valid_samples == 73
    assert win.end_sample_exclusive == 73
    assert win.padded_for_inference is True
    assert win.model_input_f32.shape == (512,)
    assert np.all(win.model_input_f32[73:] == 0.0)
    snap = sync_pad.accounting.snapshot()
    assert snap.accepted_real_samples == 73
    assert snap.processed_real_samples == 73
    assert snap.model_padding_samples == 512 - 73

    sync_nopad = FrameSynchronizer(sref, allow_eos_model_padding=False)
    assert sync_nopad.admit_frame(_make_f32_frame(sref, 0, 0, np.ones(73, dtype=np.float32))).accepted is True
    win2, unclass2 = sync_nopad.flush_eos()
    assert win2 is None
    assert unclass2 == 73


def test_va16_eos_repeated_after_finalization_no_second_flush() -> None:
    proc, queue, _, _ = _make_processor(scores=[0.9, 0.9, 0.9])
    _feed_windows(proc, 2)
    _, fins1 = proc.flush_eos()
    _, fins2 = proc.flush_eos()
    assert len(fins1) == 1
    assert len(fins2) == 0
    assert queue.item_count == 1


# ---------------------------------------------------------------------------
# VA17–VA25: Silero / Stateful VAD Isolation & Lifecycle Safety
# ---------------------------------------------------------------------------

def _run_isolated_trajectory(backend: StatefulFakeVADBackend, stream_id: str, seq_samples: list[np.ndarray]) -> list[float]:
    clk = HarnessClock()
    engine = VADEngineAdapter(backend, clock=clk)
    sref = _make_stream_ref(session_id=stream_id, stream_id=stream_id)
    mgr = VADStateManager(sref, engine)
    scores = []
    for idx, arr in enumerate(seq_samples):
        win = VADWindow(sref, idx, idx * 512, (idx + 1) * 512, 512, arr, arr, False, "rev-1")
        obs = mgr.evaluate_window(win)
        assert obs.ok and obs.score is not None
        scores.append(obs.score)
    mgr.revoke_and_close()
    return scores


def test_va17_isolated_a_then_b_deterministic_trajectories() -> None:
    gen = SyntheticAudioGenerator()
    seq_a = [
        np.frombuffer(gen.silero_vad_window_16k(AnalyticSignalKind.SPEECH_ENVELOPE, seed=10 + i).payload, dtype="<f4")
        for i in range(6)
    ]
    seq_b = [
        np.frombuffer(gen.silero_vad_window_16k(AnalyticSignalKind.PINK_NOISE, seed=100 + i).payload, dtype="<f4")
        for i in range(6)
    ]
    ref_a1 = _run_isolated_trajectory(StatefulFakeVADBackend(), "ref-a1", seq_a)
    ref_a2 = _run_isolated_trajectory(StatefulFakeVADBackend(), "ref-a2", seq_a)
    ref_b = _run_isolated_trajectory(StatefulFakeVADBackend(), "ref-b", seq_b)
    assert ref_a1 == pytest.approx(ref_a2, abs=1e-12)
    assert len(ref_a1) == 6 and len(ref_b) == 6
    assert ref_a1 != ref_b

    # Also verify ISOLATED_CLONE strategy (ADR-F1-01 pattern) without loading torch.
    class FakeCloneInstance:
        def __init__(self) -> None:
            self.acc = 0.0

        def reset_states(self) -> None:
            self.acc = 0.0

        def infer(self, window_f32: np.ndarray, sr: int) -> float:
            self.acc = min(1.0, self.acc + 0.1 + float(np.mean(np.abs(window_f32))) * 0.2)
            return self.acc

    class FakeCloneableBackend:
        model_revision = "clone_v1"

        def __init__(self) -> None:
            self.template = FakeCloneInstance()

        def clone_isolated(self) -> FakeCloneInstance:
            inst = FakeCloneInstance()
            inst.reset_states()
            return inst

    backend = FakeCloneableBackend()
    engine = VADEngineAdapter(backend, clock=HarnessClock())
    assert engine.strategy == VADIsolationStrategy.ISOLATED_CLONE
    _, slot_a = engine.create_stream_slot()
    _, slot_b = engine.create_stream_slot()
    s1, _ = engine.infer_slot(slot_a, seq_a[0], 16000)
    s2, _ = engine.infer_slot(slot_b, seq_b[0], 16000)
    assert 0.0 <= s1 <= 1.0 and 0.0 <= s2 <= 1.0
    assert backend.template.acc == 0.0
    # Verify SileroTemplateAdapter satisfies CloneableVADBackend protocol cleanly.
    silero_wrapper = SileroTemplateAdapter(clone_fn=FakeCloneInstance, model_revision="silero_clone_v1")
    assert inspect_vad_backend_isolation(silero_wrapper) == VADIsolationStrategy.ISOLATED_CLONE


def test_va18_interleaved_ab_matches_isolated_references() -> None:
    gen = SyntheticAudioGenerator()
    seq_a = [
        np.frombuffer(gen.silero_vad_window_16k(AnalyticSignalKind.SPEECH_ENVELOPE, seed=10 + i).payload, dtype="<f4")
        for i in range(6)
    ]
    seq_b = [
        np.frombuffer(gen.silero_vad_window_16k(AnalyticSignalKind.PINK_NOISE, seed=100 + i).payload, dtype="<f4")
        for i in range(6)
    ]

    ref_a = _run_isolated_trajectory(StatefulFakeVADBackend(), "ref-a", seq_a)
    ref_b = _run_isolated_trajectory(StatefulFakeVADBackend(), "ref-b", seq_b)

    shared_backend = StatefulFakeVADBackend()
    clk = HarnessClock()
    engine = VADEngineAdapter(shared_backend, clock=clk)
    sref_a = _make_stream_ref(session_id="sess-a", stream_id="in-a")
    sref_b = _make_stream_ref(session_id="sess-b", stream_id="in-b")
    mgr_a = VADStateManager(sref_a, engine)
    mgr_b = VADStateManager(sref_b, engine)

    got_a, got_b = [], []
    for i in range(6):
        wa = VADWindow(sref_a, i, i * 512, (i + 1) * 512, 512, seq_a[i], seq_a[i], False, "rev-1")
        wb = VADWindow(sref_b, i, i * 512, (i + 1) * 512, 512, seq_b[i], seq_b[i], False, "rev-1")
        got_a.append(mgr_a.evaluate_window(wa).score)
        got_b.append(mgr_b.evaluate_window(wb).score)

    assert got_a == pytest.approx(ref_a, abs=1e-12)
    assert got_b == pytest.approx(ref_b, abs=1e-12)
    mgr_a.revoke_and_close()
    mgr_b.revoke_and_close()


def test_va19_reset_or_close_a_leaves_b_unchanged() -> None:
    seq = [np.full(512, 0.25, dtype=np.float32) for _ in range(4)]
    ref_b = _run_isolated_trajectory(StatefulFakeVADBackend(), "ref-b", seq)

    engine = VADEngineAdapter(StatefulFakeVADBackend(), clock=HarnessClock())
    sref_a = _make_stream_ref(session_id="a", stream_id="in-a")
    sref_b = _make_stream_ref(session_id="b", stream_id="in-b")
    mgr_a = VADStateManager(sref_a, engine)
    mgr_b = VADStateManager(sref_b, engine)

    got_b = []
    for i in range(4):
        wa = VADWindow(sref_a, i, i * 512, (i + 1) * 512, 512, seq[i], seq[i], False, "rev-1")
        wb = VADWindow(sref_b, i, i * 512, (i + 1) * 512, 512, seq[i], seq[i], False, "rev-1")
        if i < 2:
            mgr_a.evaluate_window(wa)
        elif i == 2:
            mgr_a.reset_for_gap_or_epoch()
            mgr_a.revoke_and_close()
        got_b.append(mgr_b.evaluate_window(wb).score)

    assert got_b == pytest.approx(ref_b, abs=1e-12)
    mgr_b.revoke_and_close()


def test_va20_new_turn_retains_vad_recurrent_state() -> None:
    scores_list = [0.8, 0.8] + [0.1] * 10 + [0.8, 0.8] + [0.1] * 10
    proc, queue, _, _ = _make_processor(scores=scores_list)
    _feed_windows(proc, 12, start_offset=0, start_seq=0)
    assert queue.item_count == 1
    assert proc.vad_state._slot_state == 12  # retained, not reset on turn handoff

    _feed_windows(proc, 12, start_offset=12 * 512, start_seq=12)
    assert queue.item_count == 2
    assert proc.vad_state._slot_state == 24


def test_va21_output_generation_cancel_does_not_reset_active_input_vad() -> None:
    scores = [0.8, 0.8, 0.8] + [0.1] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, 2, start_offset=0, start_seq=0)
    assert proc.fsm.state == AcousticState.SPEECH_ACTIVE
    slot_before = proc.vad_state._slot_state

    proc.notify_output_cancelled()
    assert proc.lifecycle.is_input_active is True
    assert proc.lifecycle.output_cancellations == 1
    assert proc.fsm.state == AcousticState.SPEECH_ACTIVE
    assert proc.vad_state._slot_state == slot_before

    _feed_windows(proc, 11, start_offset=1024, start_seq=2)
    assert queue.item_count == 1


def test_va22_concurrent_same_stream_submissions_serialized() -> None:
    engine = VADEngineAdapter(StatefulFakeVADBackend(), clock=HarnessClock())
    sref = _make_stream_ref()
    mgr = VADStateManager(sref, engine)
    wins = [
        VADWindow(sref, i, i * 512, (i + 1) * 512, 512, np.full(512, 0.1, dtype=np.float32), np.full(512, 0.1, dtype=np.float32), False, "rev")
        for i in range(10)
    ]

    def submit_in_order() -> list[VADObservation]:
        return [mgr.evaluate_window(w) for w in wins]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(mgr.evaluate_window, wins[0])
        assert f1.result().ok is True

    # Submit remaining concurrently; only increasing order succeeds cleanly, duplicate/out-of-order rejected safely.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(mgr.evaluate_window, wins[1]) for _ in range(4)]
        results = [f.result() for f in futs]
    ok_count = sum(1 for r in results if r.ok)
    ooo_count = sum(1 for r in results if r.error_code == "OUT_OF_ORDER_WINDOW")
    assert ok_count == 1
    assert ooo_count == 3
    mgr.revoke_and_close()


def test_va23_unsafe_vad_backend_triggers_explicit_hold() -> None:
    unsafe = BrokenSharedMutableVAD()
    assert inspect_vad_backend_isolation(unsafe) == VADIsolationStrategy.UNSUPPORTED_HOLD
    with pytest.raises(VADIsolationUnsupportedError):
        VADEngineAdapter(unsafe)


def test_va24_provider_score_nan_oob_exception_explicit_failure() -> None:
    class FailingVAD:
        model_revision = "failing_v1"

        def initial_state(self) -> int:
            return 0

        def infer_with_state(self, window_f32: np.ndarray, sr: int, state: int) -> tuple[Any, int]:
            if state == 0:
                return float("nan"), 1
            if state == 1:
                return 1.5, 2
            if state == 2:
                return True, 3
            raise RuntimeError("boom")

    clk = HarnessClock()
    engine = VADEngineAdapter(FailingVAD(), clock=clk)
    sref = _make_stream_ref()
    mgr = VADStateManager(sref, engine)
    fsm = SpeechStateMachine(F1ProfileConfig.strict_experimental())

    for idx in range(4):
        arr = np.zeros(512, dtype=np.float32)
        w = VADWindow(sref, idx, idx * 512, (idx + 1) * 512, 512, arr, arr, False, "rev")
        obs = mgr.evaluate_window(w)
        assert obs.ok is False
        assert obs.score is None
        tr = fsm.step(obs)
        assert fsm.state == AcousticState.IDLE
        assert tr.low_run_real_samples == 0
    mgr.revoke_and_close()


def test_va25_inflight_native_job_then_revoke_quarantines_and_rejects_late_callback() -> None:
    clk = HarnessClock()
    ledger = ResourceLedger()
    engine = VADEngineAdapter(WindowIndexScriptedVADBackend([0.8]), clock=clk)
    sref = _make_stream_ref()
    mgr = VADStateManager(sref, engine, ledger=ledger)
    arr = np.zeros(512, dtype=np.float32)
    win = VADWindow(sref, 0, 0, 512, 512, arr, arr, False, "rev")

    job_lid = mgr.begin_inflight_job(win)
    assert mgr.inflight_count == 1
    mgr.revoke_and_close()
    assert ledger._leases[mgr.lease_id].state == LeaseState.QUARANTINED  # type: ignore[index]

    late_obs = VADObservation(sref, 0, 0, 512, 512, True, 0.9, "rev", 10, 20, clk.clock_domain)
    outcome = mgr.complete_inflight_job(win, late_obs)
    assert outcome.accepted is False
    assert outcome.reason == "STREAM_REVOKED_OR_CLOSED"
    assert ledger._leases[job_lid].state == LeaseState.RELEASED
    assert ledger._leases[mgr.lease_id].state == LeaseState.RELEASED  # type: ignore[index]


# ---------------------------------------------------------------------------
# VA26–VA34: Unified Lookback Buffer & Candidate Retention
# ---------------------------------------------------------------------------

def test_va26_320ms_prehistory_then_onset_yields_5120_preroll() -> None:
    # 12 windows silence (6144 samples > 5120), then 2 speech, then 10 silence
    scores = [0.05] * 12 + [0.85, 0.85] + [0.05] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, 24)
    utt = queue.pop_next()
    assert utt is not None
    assert utt.actual_pre_roll_samples == 5120
    assert utt.start_sample == 12 * 512 - 5120
    assert utt.end_sample_exclusive == 14 * 512 + 2560


def test_va27_first_marker_inside_first_high_window_preserved_once() -> None:
    scores = [0.1, 0.1, 0.85, 0.85] + [0.1] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    for i in range(14):
        arr = np.full(512, 0.01, dtype=np.float32)
        if i == 2:
            arr[3] = 0.98765  # first acoustic marker inside first high window
        proc.process_frame(_make_f32_frame(proc.stream_ref, i, i * 512, arr))
    utt = queue.pop_next()
    assert utt is not None
    decoded = utterance_to_legacy_stt_ndarray(utt)
    matches = np.where(np.isclose(decoded, 0.98765, atol=1e-6))[0]
    assert len(matches) == 1
    assert matches[0] == 2 * 512 + 3


def test_va28_onset_at_stream_origin_zero_preroll_no_fake_zeros() -> None:
    scores = [0.85, 0.85] + [0.05] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, 12)
    utt = queue.pop_next()
    assert utt is not None
    assert utt.start_sample == 0
    assert utt.actual_pre_roll_samples == 0


def test_va29_confirmation_after_2_windows_keeps_first_candidate_start() -> None:
    scores = [0.05] * 12 + [0.75, 0.75] + [0.05] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, 24)
    utt = queue.pop_next()
    assert utt is not None
    # Candidate onset was at 12*512 = 6144; pre-roll 5120 -> start_sample = 1024 (NOT 13*512 - 5120)
    assert utt.start_sample == 1024


def test_va30_single_high_window_rejected_no_turn_or_dispatch() -> None:
    scores = [0.05] * 5 + [0.85, 0.10] + [0.05] * 10
    proc, queue, _, ctx = _make_processor(scores=scores)
    _feed_windows(proc, 17)
    assert proc.fsm.state == AcousticState.IDLE
    assert queue.item_count == 0
    assert ctx.tg.active_turn is None


def test_va31_rejected_candidate_followed_by_true_onset_reuses_history_no_duplicates() -> None:
    scores = [0.05] * 4 + [0.85, 0.10] + [0.05] * 6 + [0.85, 0.85] + [0.05] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    for i in range(24):
        arr = np.arange(i * 512, (i + 1) * 512, dtype=np.float32)
        proc.process_frame(_make_f32_frame(proc.stream_ref, i, i * 512, arr))
    assert queue.item_count == 1
    utt = queue.pop_next()
    assert utt is not None
    decoded = utterance_to_legacy_stt_ndarray(utt)
    expected = np.arange(utt.start_sample, utt.end_sample_exclusive, dtype=np.float32)
    assert np.array_equal(decoded, expected)


def test_va32_ring_wraparound_ordered_slice_no_stale_alias() -> None:
    buf = LookbackBuffer(pre_roll_samples=5120, history_capacity_samples=6656)
    for i in range(40):
        arr = np.arange(i * 512, (i + 1) * 512, dtype=np.float32)
        buf.append_samples(i * 512, arr)
    assert buf.total_samples == 6656
    pin = buf.pin_candidate(39 * 512)
    assert pin.actual_pre_roll_samples == 5120
    sl = buf.extract_slice(pin.utterance_start_sample, 40 * 512)
    decoded = np.frombuffer(sl, dtype="<f4")
    expected = np.arange(pin.utterance_start_sample, 40 * 512, dtype=np.float32)
    assert np.array_equal(decoded, expected)


def test_va33_consecutive_utterances_non_overlapping_strict() -> None:
    # Utt 1: onset at w10, 10 low windows -> cut at w12*512 + 2560 = 12*512 + 2560 = 8704
    # Utt 2: onset at w22 (shortly after u1 end)
    scores = [0.05] * 10 + [0.85, 0.85] + [0.05] * 10 + [0.85, 0.85] + [0.05] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, 34)
    u1 = queue.pop_next()
    u2 = queue.pop_next()
    assert u1 is not None and u2 is not None
    assert u2.start_sample >= u1.end_sample_exclusive


def test_va34_candidate_pin_plus_full_capacity_explicit_overflow() -> None:
    prof = F1ProfileConfig.strict_experimental()
    proc, _, _, _ = _make_processor(scores=[0.85] * 20, profile=prof, strict_pinned_capacity=True)
    with pytest.raises(LookbackCapacityExceededError):
        _feed_windows(proc, 15)
    assert any(e.event_type == "f1.buffer.overflow" for e in proc.telemetry.events)


# ---------------------------------------------------------------------------
# VA35–VA48: Hysteresis FSM, Thresholds, Post-Roll, Profiles
# ---------------------------------------------------------------------------

def test_va35_idle_threshold_boundary_059_vs_060() -> None:
    prof = F1ProfileConfig.strict_experimental()
    fsm = SpeechStateMachine(prof)
    sref = _make_stream_ref()
    clk = HarnessClock()
    obs0 = VADObservation(sref, 0, 0, 512, 512, True, 0.59, "m", 0, 1, clk.clock_domain)
    assert fsm.step(obs0).new_state == AcousticState.IDLE
    obs1 = VADObservation(sref, 1, 512, 1024, 512, True, 0.60, "m", 1, 2, clk.clock_domain)
    assert fsm.step(obs1).new_state == AcousticState.SPEECH_CANDIDATE


def test_va36_active_threshold_boundary_036_vs_035() -> None:
    prof = F1ProfileConfig.strict_experimental()
    fsm = SpeechStateMachine(prof)
    sref = _make_stream_ref()
    clk = HarnessClock()
    for i in range(2):
        fsm.step(VADObservation(sref, i, i * 512, (i + 1) * 512, 512, True, 0.60, "m", 0, 1, clk.clock_domain))
    assert fsm.state == AcousticState.SPEECH_ACTIVE
    assert fsm.step(VADObservation(sref, 2, 1024, 1536, 512, True, 0.36, "m", 0, 1, clk.clock_domain)).new_state == AcousticState.SPEECH_ACTIVE
    assert fsm.step(VADObservation(sref, 3, 1536, 2048, 512, True, 0.35, "m", 0, 1, clk.clock_domain)).new_state == AcousticState.SILENCE_PENDING


def test_va37_oscillating_mid_band_no_flapping() -> None:
    scores = [0.65, 0.65] + [0.36, 0.59, 0.40, 0.58, 0.37, 0.55]
    proc, queue, _, _ = _make_processor(scores=scores)
    outcomes = _feed_windows(proc, len(scores))
    starts = [ev for o in outcomes for ev in o.speech_events if ev.kind == SpeechEventKind.SPEECH_START]
    assert len(starts) == 1
    assert proc.fsm.state == AcousticState.SPEECH_ACTIVE
    assert queue.item_count == 0


def test_va38_candidate_high_then_mid_then_high_resets_confirmation() -> None:
    scores = [0.70, 0.50, 0.70]
    proc, _, _, _ = _make_processor(scores=scores)
    outcomes = _feed_windows(proc, 3)
    assert outcomes[0].speech_events[0].kind == SpeechEventKind.SPEECH_CANDIDATE
    assert proc.fsm.state == AcousticState.SPEECH_CANDIDATE
    assert proc.fsm.consecutive_high_windows == 1
    assert not any(ev.kind == SpeechEventKind.SPEECH_START for o in outcomes for ev in o.speech_events)


def test_va39_two_consecutive_high_windows_emit_one_speech_start_no_turn() -> None:
    proc, _, _, ctx = _make_processor(scores=[0.65, 0.65])
    outcomes = _feed_windows(proc, 2)
    starts = [ev for o in outcomes for ev in o.speech_events if ev.kind == SpeechEventKind.SPEECH_START]
    assert len(starts) == 1
    assert ctx.tg.active_turn is None  # no speculative turn allocation


def test_va40_nine_low_windows_not_finalized_at_288ms() -> None:
    scores = [0.80, 0.80] + [0.10] * 9
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, 11)
    assert proc.fsm.state == AcousticState.SILENCE_PENDING
    assert proc.fsm.low_run_real_samples == 9 * 512
    assert queue.item_count == 0


def test_va41_ten_low_windows_finalizes_at_320ms() -> None:
    scores = [0.80, 0.80] + [0.10] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, 12)
    assert proc.fsm.state == AcousticState.IDLE
    assert queue.item_count == 1


def test_va42_speech_resumes_after_9_low_windows_keeps_same_utterance() -> None:
    scores = [0.80, 0.80] + [0.10] * 9 + [0.70] + [0.10] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, len(scores))
    assert queue.item_count == 1
    utt = queue.pop_next()
    assert utt is not None
    assert utt.start_sample == 0
    assert utt.end_sample_exclusive == 12 * 512 + 2560


def test_va43_450ms_and_800ms_silence_split_documented() -> None:
    # 450 ms (~15 windows) and 800 ms (25 windows) exceed 320 ms acoustic profile -> split into separate utterances
    scores = [0.80, 0.80] + [0.10] * 15 + [0.80, 0.80] + [0.10] * 25 + [0.80, 0.80] + [0.10] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, len(scores))
    assert queue.item_count == 3


def test_va44_post_roll_160ms_cut_at_low_start_plus_2560_tail_accounted() -> None:
    scores = [0.80, 0.80] + [0.10] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, len(scores))
    u1 = queue.pop_next()
    assert u1 is not None
    assert u1.end_sample_exclusive == 1024 + 2560
    assert u1.actual_post_roll_samples == 2560
    assert proc.lookback.total_samples == 2560


def test_va45_next_onset_uses_leftover_history_no_overlap() -> None:
    scores = [0.80, 0.80] + [0.10] * 10 + [0.10, 0.80, 0.80] + [0.10] * 10
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, len(scores))
    u1 = queue.pop_next()
    u2 = queue.pop_next()
    assert u1 is not None and u2 is not None
    assert u2.start_sample == u1.end_sample_exclusive
    assert u2.actual_pre_roll_samples == 13 * 512 - u1.end_sample_exclusive


def test_va46_profile_post_roll_gt_endpoint_silence_rejected() -> None:
    with pytest.raises(ValueError):
        F1ProfileConfig(post_roll_samples=6000, endpoint_silence_samples=5120)


def test_va47_profile_equal_thresholds_or_nan_rejected() -> None:
    with pytest.raises(ValueError):
        F1ProfileConfig(start_threshold=0.5, end_threshold=0.5)
    with pytest.raises(ValueError):
        F1ProfileConfig(start_threshold=float("nan"), end_threshold=0.3)
    with pytest.raises(ValueError):
        F1ProfileConfig(max_utterance_samples=True)  # type: ignore[arg-type]


def test_va48_config_revision_pinned_per_stream() -> None:
    snap1 = build_snapshot(
        values={"car_denoiser_enabled": True},
        sources={"car_denoiser_enabled": ConfigSource.DEFAULT},
        feature_flags={"f1_vad_route_mode": "strict"},
    )
    snap2 = build_snapshot(
        values={"car_denoiser_enabled": False},
        sources={"car_denoiser_enabled": ConfigSource.OVERRIDE},
        feature_flags={"f1_vad_route_mode": "shadow"},
    )
    adapter = F1ConfigAdapter()
    adapter.publish_revision(snap1)
    engine = VADEngineAdapter(WindowIndexScriptedVADBackend([0.1]), clock=HarnessClock())
    ctx = SessionContext(SessionIdentity("s-cfg"), clock=HarnessClock())
    asyncio.run(ctx.open())

    p1 = VoiceActivityPipeline(_make_stream_ref("s-cfg", "in-1"), config_adapter=adapter, vad_engine=engine, session_context=ctx)
    adapter.publish_revision(snap2)
    p2 = VoiceActivityPipeline(_make_stream_ref("s-cfg", "in-2"), config_adapter=adapter, vad_engine=engine, session_context=ctx)

    assert p1.config_revision == snap1.config_revision
    assert p1.route_mode == F1RouteMode.STRICT
    assert p2.config_revision == snap2.config_revision
    assert p2.route_mode == F1RouteMode.SHADOW
    p1.close()
    p2.close()


# ---------------------------------------------------------------------------
# VA49–VA58: Max Duration Cap, Watchdog, EOS, Cancel, Races
# ---------------------------------------------------------------------------

def test_va49_hard_cap_320000_samples_exact_max_duration() -> None:
    # 625 windows * 512 = 320,000 samples exactly
    scores = [0.80] * 625
    proc, queue, _, _ = _make_processor(scores=scores)
    _feed_windows(proc, 625)
    utt = queue.pop_next()
    assert utt is not None
    assert utt.finalization_reason == FinalizationReason.MAX_DURATION.value
    assert utt.start_sample == 0
    assert utt.end_sample_exclusive == 320000
    assert len(utt.payload or b"") == 320000 * 4


def test_va50_hard_cap_inside_vad_window_exact_cut() -> None:
    prof = F1ProfileConfig(
        start_threshold=0.60,
        end_threshold=0.35,
        onset_confirmation_windows=2,
        pre_roll_samples=0,
        post_roll_samples=512,
        endpoint_silence_samples=1024,
        max_utterance_samples=1200,  # inside 3rd 512-sample window [1024, 1536)
        history_capacity_samples=4096,
    )
    proc, queue, _, _ = _make_processor(scores=[0.80, 0.80, 0.80], profile=prof)
    _feed_windows(proc, 3)
    utt = queue.pop_next()
    assert utt is not None
    assert utt.finalization_reason == FinalizationReason.MAX_DURATION.value
    assert utt.end_sample_exclusive == 1200
    assert proc.lookback.min_eligible_offset == 1200
    assert proc.lookback.buffer_end_sample == 1536


def test_va51_hard_cap_and_silence_tie_deterministic_max_duration() -> None:
    prof = F1ProfileConfig(
        start_threshold=0.60,
        end_threshold=0.35,
        onset_confirmation_windows=2,
        pre_roll_samples=0,
        post_roll_samples=512,
        endpoint_silence_samples=1024,
        max_utterance_samples=2048,  # 4 windows; w0..w1 high, w2..w3 low -> tie at 2048
        history_capacity_samples=4096,
    )
    proc, queue, _, _ = _make_processor(scores=[0.80, 0.80, 0.10, 0.10], profile=prof)
    _feed_windows(proc, 4)
    utt = queue.pop_next()
    assert utt is not None
    assert utt.finalization_reason == FinalizationReason.MAX_DURATION.value
    assert utt.end_sample_exclusive == 2048


def test_va52_continuous_speech_after_max_duration_cut_no_duplicate_audio() -> None:
    prof = F1ProfileConfig(
        start_threshold=0.60,
        end_threshold=0.35,
        onset_confirmation_windows=2,
        pre_roll_samples=0,
        post_roll_samples=512,
        endpoint_silence_samples=1024,
        max_utterance_samples=1024,
        history_capacity_samples=4096,
    )
    proc, queue, _, _ = _make_processor(scores=[0.80, 0.80, 0.80, 0.80], profile=prof)
    _feed_windows(proc, 4)
    u1 = queue.pop_next()
    u2 = queue.pop_next()
    assert u1 is not None and u2 is not None
    assert (u1.start_sample, u1.end_sample_exclusive) == (0, 1024)
    assert (u2.start_sample, u2.end_sample_exclusive) == (1024, 2048)


def test_va53_low_score_idle_produces_no_utterance_or_turn() -> None:
    proc, queue, _, ctx = _make_processor(scores=[0.10] * 20)
    _feed_windows(proc, 20)
    assert proc.fsm.state == AcousticState.IDLE
    assert queue.item_count == 0
    assert ctx.tg.active_turn is None


def test_va54_stall_watchdog_does_not_advance_sample_cursor() -> None:
    clk = HarnessClock(initial_ns=10_000_000)
    proc, _, _, _ = _make_processor(scores=[0.1], clock=clk)
    _feed_windows(proc, 1)
    cursor_before = proc.synchronizer.expected_next_offset
    clk.advance_ms(6000)
    wd = proc.check_watchdogs()
    assert wd.ingress_stalled is True
    assert proc.synchronizer.expected_next_offset == cursor_before


def test_va55_graceful_eos_during_active_speech_finalizes_real_tail() -> None:
    proc, queue, _, _ = _make_processor(scores=[0.85, 0.85, 0.85])
    _feed_windows(proc, 2, start_offset=0, start_seq=0)
    tail_frame = _make_f32_frame(proc.stream_ref, 2, 1024, np.full(100, 0.5, dtype=np.float32))
    proc.process_frame(tail_frame)
    evs, fins = proc.flush_eos()
    assert len(fins) == 1
    assert fins[0].status == FinalizationStatus.ADMITTED
    utt = queue.pop_next()
    assert utt is not None
    assert utt.finalization_reason == FinalizationReason.EXPLICIT_EOS.value
    assert utt.end_sample_exclusive == 1124


def test_va56_disconnect_or_cancel_during_active_speech_no_turn_dispatch() -> None:
    proc, queue, _, ctx = _make_processor(scores=[0.85, 0.85])
    _feed_windows(proc, 2)
    assert proc.fsm.state == AcousticState.SPEECH_ACTIVE
    proc.revoke_and_close("client_disconnect")
    assert queue.item_count == 0
    assert ctx.tg.active_turn is None
    assert proc.accounting.snapshot().discarded_abort_samples == 1024


def test_va57_eos_and_acoustic_callback_race_at_most_once() -> None:
    ctx = SessionContext(SessionIdentity("s-race"), clock=HarnessClock())
    asyncio.run(ctx.open())
    sref = _make_stream_ref("s-race")
    queue = BoundedUtteranceQueue(max_items=4)
    um = UtteranceManager(sref, turn_allocator=M02TurnAllocatorBridge(ctx), consumer=queue)
    dec_ac = EndpointCutDecision(True, FinalizationReason.ACOUSTIC_SILENCE, 0, 1024, 512, 0, 512)
    dec_eos = EndpointCutDecision(True, FinalizationReason.EXPLICIT_EOS, 0, 1024, 512, 0, 512)
    payload = np.zeros(1024, dtype=np.float32).tobytes()
    r1 = um.finalize_and_handoff(dec_ac, payload=payload)
    r2 = um.finalize_and_handoff(dec_eos, payload=payload)
    assert r1.status == FinalizationStatus.ADMITTED
    assert r2 is r1
    assert queue.item_count == 1
    assert ctx.tg.active_turn == TurnRef("s-race", 1)


def test_va58_duplicate_final_callback_same_identity_no_extra_turn() -> None:
    ctx = SessionContext(SessionIdentity("s-dup"), clock=HarnessClock())
    asyncio.run(ctx.open())
    sref = _make_stream_ref("s-dup")
    queue = BoundedUtteranceQueue(max_items=4)
    um = UtteranceManager(sref, turn_allocator=M02TurnAllocatorBridge(ctx), consumer=queue)
    dec = EndpointCutDecision(True, FinalizationReason.ACOUSTIC_SILENCE, 0, 1024, 512, 0, 512)
    payload = np.zeros(1024, dtype=np.float32).tobytes()
    r1 = um.finalize_and_handoff(dec, payload=payload, explicit_utterance_id="utt-same-1")
    r2 = um.finalize_and_handoff(dec, payload=payload, explicit_utterance_id="utt-same-1")
    assert r1.status == FinalizationStatus.ADMITTED
    assert r2 is r1
    assert queue.item_count == 1
    assert ctx.tg.active_turn == TurnRef("s-dup", 1)


# ---------------------------------------------------------------------------
# VA59–VA72: Handoff, Backpressure, Mutation Safety, Privacy, Compatibility
# ---------------------------------------------------------------------------

def test_va59_m02_revocation_before_handoff_rejects_and_releases() -> None:
    ctx = SessionContext(SessionIdentity("s-rev"), clock=HarnessClock())
    asyncio.run(ctx.open())
    sref = _make_stream_ref("s-rev")
    um = UtteranceManager(sref, turn_allocator=M02TurnAllocatorBridge(ctx), consumer=BoundedUtteranceQueue())
    ctx.root_scope.request_cancel("stream_revoked")
    dec = EndpointCutDecision(True, FinalizationReason.ACOUSTIC_SILENCE, 0, 512, 256, 0, 256)
    rec = um.finalize_and_handoff(dec, payload=np.zeros(512, dtype=np.float32).tobytes())
    assert rec.status == FinalizationStatus.REJECTED_REVOKED
    assert rec.turn_ref is None


def test_va60_final_admitted_before_close_retained() -> None:
    proc, queue, _, ctx = _make_processor(scores=[0.85, 0.85] + [0.05] * 10)
    _feed_windows(proc, 12)
    assert queue.item_count == 1
    proc.revoke_and_close("normal_close")
    asyncio.run(ctx.close("normal_close"))
    assert queue.item_count == 1
    assert proc.utterance_manager.receipt_count == 1


def test_va61_f2_queue_full_backpressure_no_speculative_turn() -> None:
    proc, queue, _, ctx = _make_processor(
        scores=[0.85, 0.85] + [0.05] * 10 + [0.85, 0.85] + [0.05] * 10,
        queue_max_items=1,
    )
    outcomes = _feed_windows(proc, 24)
    finals = [f for o in outcomes for f in o.finalizations]
    assert len(finals) == 2
    assert finals[0].status == FinalizationStatus.ADMITTED
    assert finals[1].status == FinalizationStatus.BACKPRESSURE
    assert finals[1].turn_ref is None
    assert ctx.tg.active_turn == TurnRef(ctx.identity.session_id, 1)
    assert queue.item_count == 1


def test_va62_consumer_raises_records_error_no_duplicate_dispatch() -> None:
    class RaisingConsumer:
        def __init__(self) -> None:
            self.attempts = 0

        def can_accept(self, payload_bytes: int) -> bool:
            return True

        def accept_utterance(self, utterance: Utterance) -> None:
            self.attempts += 1
            raise RuntimeError("downstream_failure")

    ctx = SessionContext(SessionIdentity("s-err"), clock=HarnessClock())
    asyncio.run(ctx.open())
    sref = _make_stream_ref("s-err")
    cons = RaisingConsumer()
    um = UtteranceManager(sref, turn_allocator=M02TurnAllocatorBridge(ctx), consumer=cons)
    dec = EndpointCutDecision(True, FinalizationReason.ACOUSTIC_SILENCE, 0, 512, 256, 0, 256)
    payload = np.zeros(512, dtype=np.float32).tobytes()
    r1 = um.finalize_and_handoff(dec, payload=payload)
    r2 = um.finalize_and_handoff(dec, payload=payload)
    assert r1.status == FinalizationStatus.CONSUMER_ERROR
    assert r2 is r1
    assert cons.attempts == 1


def test_va63_mutate_producer_ndarray_after_admission_leaves_utterance_intact() -> None:
    proc, queue, _, _ = _make_processor(scores=[0.85, 0.85] + [0.05] * 10)
    buf = np.empty(512, dtype=np.float32)
    for i in range(12):
        buf[:] = 0.42
        frame = _make_f32_frame(proc.stream_ref, i, i * 512, buf)
        proc.process_frame(frame)
        buf[:] = -0.99  # mutate caller buffer after admission
    utt = queue.pop_next()
    assert utt is not None
    arr = utterance_to_legacy_stt_ndarray(utt)
    assert arr.flags.writeable is False
    assert np.allclose(arr, 0.42)


def test_va64_repeated_open_close_and_failed_inference_zero_leaks() -> None:
    for idx in range(5):
        clk = HarnessClock()
        ledger = ResourceLedger()
        ctx = SessionContext(SessionIdentity(f"s-oc-{idx}"), clock=clk)
        asyncio.run(ctx.open())
        sref = _make_stream_ref(f"s-oc-{idx}")
        engine = VADEngineAdapter(WindowIndexScriptedVADBackend([0.85, 0.85]), clock=clk)
        proc = StreamAcousticProcessor(
            sref,
            profile=F1ProfileConfig.strict_experimental(),
            config_revision="rev",
            vad_engine=engine,
            turn_allocator=M02TurnAllocatorBridge(ctx),
            ledger=ledger,
            clock=clk,
            session_context=ctx,
        )
        _feed_windows(proc, 2)
        proc.revoke_and_close()
        proc.revoke_and_close()  # idempotent
        assert ledger.active_count == 0
        assert ledger.quarantined_count == 0
        asyncio.run(ctx.close())


def test_va65_mixed_dtmf_and_speech_raw_dtmf_path_unchanged() -> None:
    from backend.dtmf import GoertzelDetector

    dtmf = GoertzelDetector(sample_rate=16000)
    # 80 ms of 697+1209 Hz ('1') followed by speech-like low-score silence in F1
    t = np.arange(1600, dtype=np.float32) / 16000.0
    tone = 0.5 * (np.sin(2 * np.pi * 697 * t) + np.sin(2 * np.pi * 1209 * t))
    digits, muted = dtmf.process_samples(tone.astype(np.float32))
    assert "1" in digits

    proc, queue, _, _ = _make_processor(scores=[0.10] * 3)
    res = proc.process_frame(_make_f32_frame(proc.stream_ref, 0, 0, muted))
    assert res.admission.accepted is True
    assert queue.item_count == 0


def test_va66_telemetry_subscriber_failure_and_overflow_isolated() -> None:
    bus = BoundedEventBus(max_lane_size=1, drop_policy=DropPolicy.DROP_NEWEST)

    def exploding_cb(_env: Any) -> None:
        raise RuntimeError("subscriber_exploded")

    bus.subscribe("bad-sub", max_lane_size=1, callback=exploding_cb)
    proc, queue, _, _ = _make_processor(scores=[0.85, 0.85] + [0.05] * 10, event_bus=bus)
    _feed_windows(proc, 12)
    bus.dispatch_all()
    assert queue.item_count == 1
    assert bus.stats.overflow_count > 0


def test_va67_pii_and_raw_audio_redacted_rejected_in_telemetry() -> None:
    sref = _make_stream_ref()
    proj = Projection()
    proc, _, _, _ = _make_processor(scores=[0.85])
    ev = proc.telemetry.emit_event(
        "f1.vad.observed",
        extras={
            "reason": "caller +90 532 123 45 67 plate 34 ABC 1234 vin WBA3B1C50DF123456 token sk-abc1234567890",
            "raw_transcript": "gizli metin",
            "pcm": b"RAW_AUDIO",
            "phone": "05321234567",
        },
    )
    projected = proj.project(ev)
    assert projected is not None
    findings = PIISecretScanner.scan_object(projected)
    assert findings == []
    assert "raw_transcript" not in projected.get("metadata", {})
    assert "pcm" not in projected.get("metadata", {})
    assert "0532" not in str(projected)
    assert "WBA3B1C50DF123456" not in str(projected)


def test_va68_missing_or_foreign_clock_domain_yields_null_unavailable() -> None:
    s_missing = compute_same_domain_duration_ms(
        start_ns=None,
        start_clock_domain=None,
        end_ns=1000,
        end_clock_domain="server.monotonic",
        metric_name="f1.endpoint_delay_ms",
    )
    assert s_missing.value is None and s_missing.status == MetricStatus.UNAVAILABLE

    s_foreign = compute_same_domain_duration_ms(
        start_ns=1000,
        start_clock_domain="client.wall",
        end_ns=2000,
        end_clock_domain="server.monotonic",
        metric_name="f1.endpoint_delay_ms",
    )
    assert s_foreign.value is None and s_foreign.status == MetricStatus.UNAVAILABLE


def test_va69_legacy_stt_boundary_preserves_shape_no_double_trim() -> None:
    clk = HarnessClock()
    engine = VADEngineAdapter(WindowIndexScriptedVADBackend([0.85, 0.85] + [0.05] * 10), clock=clk)
    legacy = LegacyEndpointAdapter(session_id="leg-1", vad_engine=engine, clock=clk)
    all_utts: list[np.ndarray] = []
    started_any = False
    for i in range(12):
        arr = np.full(512, 0.33, dtype=np.float32)
        started, utts = legacy.feed(arr)
        started_any = started_any or started
        all_utts.extend(utts)
    assert started_any is True
    assert len(all_utts) == 1
    assert all_utts[0].dtype == np.float32
    assert all_utts[0].shape == (1024 + 2560,)
    legacy.close()


def test_va70_off_strict_shadow_mode_selection_and_isolation() -> None:
    adapter = F1ConfigAdapter()
    assert adapter.current_profile.route_mode == F1RouteMode.OFF  # default preserved

    engine = VADEngineAdapter(WindowIndexScriptedVADBackend([0.85, 0.85] + [0.05] * 10), clock=HarnessClock())
    ctx = SessionContext(SessionIdentity("s-mode"), clock=HarnessClock())
    asyncio.run(ctx.open())
    sref = _make_stream_ref("s-mode")

    # OFF mode -> no strict action
    p_off = VoiceActivityPipeline(sref, config_adapter=adapter, vad_engine=engine, session_context=ctx)
    assert p_off.process_frame(_make_f32_frame(sref, 0, 0, np.zeros(512, dtype=np.float32))) is None
    assert ctx.tg.active_turn is None

    # SHADOW mode -> observes internally, returns None, allocates 0 M02 turns
    snap_shadow = build_snapshot(
        values={},
        sources={},
        feature_flags={"f1_vad_route_mode": "shadow"},
    )
    adapter.publish_revision(snap_shadow)
    p_shadow = VoiceActivityPipeline(sref, config_adapter=adapter, vad_engine=engine, session_context=ctx)
    for i in range(12):
        res = p_shadow.process_frame(_make_f32_frame(sref, i, i * 512, np.zeros(512, dtype=np.float32)))
        assert res is None
    assert ctx.tg.active_turn is None
    p_shadow.close()

    # STRICT mode -> single authoritative output
    snap_strict = build_snapshot(
        values={},
        sources={},
        feature_flags={"f1_vad_route_mode": "strict"},
    )
    adapter.publish_revision(snap_strict)
    q = BoundedUtteranceQueue(max_items=4)
    p_strict = VoiceActivityPipeline(sref, config_adapter=adapter, vad_engine=engine, consumer=q, session_context=ctx)
    for i in range(12):
        p_strict.process_frame(_make_f32_frame(sref, i, i * 512, np.zeros(512, dtype=np.float32)))
    assert q.item_count == 1
    assert ctx.tg.active_turn == TurnRef("s-mode", 1)
    p_strict.close()


def test_va71_m00_feature_regression_mapping_preserved() -> None:
    baseline_dir = REPO_ROOT / "docs" / "freya2" / "baseline" / "20261126T001600Z"
    mapper = FeatureRegressionMapper(REPO_ROOT, baseline_dir)
    summary = mapper.build_matrix()
    f1_rows = [r for r in summary.rows if r.feature_id.startswith("FT-F1-")]
    assert len(f1_rows) >= 2
    assert all(not r.blocking for r in f1_rows)


def test_va72_rollback_and_evidence_integrity_validation(tmp_path: Path) -> None:
    snap_off = build_snapshot(values={}, sources={}, feature_flags={"f1_vad_route_mode": "off"})
    snap_strict = build_snapshot(values={}, sources={}, feature_flags={"f1_vad_route_mode": "strict"})
    store = ConfigSnapshotStore(snap_off)
    store.swap(snap_strict)
    adapter = F1ConfigAdapter()
    adapter.publish_revision(store.current)
    assert adapter.current_profile.route_mode == F1RouteMode.STRICT

    rolled = store.rollback()
    adapter.publish_revision(rolled)
    assert adapter.current_profile.route_mode == F1RouteMode.OFF

    # Noncircular SHA-256 verification via M08 EvidenceValidator
    ev_dir = tmp_path / "evidence"
    ev_dir.mkdir()
    artifact = tmp_path / "sample_report.json"
    artifact.write_text('{"ok": true}\n', encoding="utf-8")
    (ev_dir / "manifest.json").write_text('{"run_id": "test"}\n', encoding="utf-8")
    validator = EvidenceValidator(tmp_path)
    validator.write_noncircular_hashes([artifact, ev_dir / "manifest.json"], ev_dir / "artifact_hashes.json")
    assert validator.verify_evidence_bundle(ev_dir) == []
