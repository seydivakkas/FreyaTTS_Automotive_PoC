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
import math
import os
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from backend.core.configuration import (
    ConfigSnapshotStore,
    resolve_configuration,
)
from backend.core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    ASROutcome,
    ASRResult,
    ASRStatus,
    AudioEncoding,
    AudioFormat,
    AudioFrame,
    CapabilityDescriptor,
    CapabilityState,
    CatalogStatus,
    ConfidenceEstimate,
    ConfirmationStatus,
    ErrorCategory,
    MetricStatus,
    SessionIdentity,
    SpeechEvent,
    SpeechEventKind,
    StreamDirection,
    StreamRef,
    TurnRef,
    Utterance,
    metadata_to_json,
)
from backend.core.model_registry import ModelDescriptor, ModelKind, ModelRegistry
from backend.core.runtime import (
    AdmissionStatus,
    CancellationScope,
    FakeClock,
    SessionContext,
    SessionRegistry,
)
from backend.core.runtime.session_context import CleanupStatus
from backend.observability import BoundedEventBus, MetricsRegistry, Projection
from backend.runtime_resources import (
    MIB,
    AdmissionOutcome,
    ExecutionLeaseState,
    HandleOwnership,
    MemoryBudget,
    ModelSpec,
    PriorityClass,
    ProviderKind,
    QuarantineManager,
    ResidencyManager,
    UnifiedGpuScheduler,
)
from backend.shared_lexicon import (
    AliasEntry,
    CanonicalEntity,
    EntityCategory,
    LexiconRegistry,
    LexiconSnapshot,
)
from backend.speech_recognition import (
    ASRConfigError,
    ASRDeliveryStatus,
    ASRDispatchStatus,
    ASRInputError,
    ASRLifecycleManager,
    ASRRouteMode,
    ASRTelemetryBridge,
    ASRUtteranceAdmission,
    ClaimStatus,
    CollectorLimits,
    InMemoryASRConsumer,
    PinnedASRConfig,
    SpeechRecognitionPipeline,
    WhisperSchedulerEngine,
    build_asr_resource_request,
    build_final_asr_result,
    build_legacy_hotwords,
    collect_whisper_segments,
    extract_confidence_estimate,
    extract_conservative_candidates,
    pin_lexicon_snapshot,
    project_legacy_transcript,
    resolve_asr_config,
    resolve_language_metadata,
    validate_and_materialize_utterance,
)
from backend.speech_recognition.lexicon_adapter import LegacyHotwordCache
from backend.speech_recognition.telemetry import ASR_TELEMETRY_ALLOWLIST, compute_clock_safe_delta_ms
from tests.harness.adapters.fake_gpu import FakeGPUProbeAdapter
from tests.harness.barriers import DeterministicBarrier
from tests.harness.contracts import GateStatus, PrerequisiteStatus
from tests.harness.evidence_validator import EvidenceValidator, PIISecretScanner

REPO_ROOT = Path(__file__).resolve().parents[2]
FMT_16K_F32 = AudioFormat(sample_rate_hz=16_000, channels=1, encoding=AudioEncoding.FLOAT32_LE)
FMT_16K_PCM16 = AudioFormat(sample_rate_hz=16_000, channels=1, encoding=AudioEncoding.PCM_S16LE)


@dataclass
class FakeWhisperSegment:
    text: str
    start: float | None = None
    end: float | None = None
    avg_logprob: float | None = -0.25
    no_speech_prob: float | None = 0.05
    compression_ratio: float | None = 1.1
    words: list[dict[str, Any]] | None = None


class FakeWhisperModel:
    """Controllable fake Faster-Whisper model supporting lazy generators, barriers, errors, and OOM."""

    def __init__(self, handler: Any = None) -> None:
        self.handler = handler
        self.invocations: list[dict[str, Any]] = []
        self.invocation_count = 0

    def transcribe(self, audio: np.ndarray, **kwargs: Any) -> tuple[Any, Any]:
        self.invocation_count += 1
        # Copy snapshot of observed audio length/sum without storing raw payload in logs
        self.invocations.append({
            "samples": int(len(audio)),
            "dtype": str(audio.dtype),
            "writeable": bool(audio.flags.writeable),
            "kwargs": dict(kwargs),
            "audio_copy": np.array(audio, copy=True),
        })
        if self.handler is not None:
            return self.handler(audio, kwargs)
        segs = [FakeWhisperSegment(text="merhaba dünya", start=0.0, end=0.5)]
        return iter(segs), SimpleNamespace(language="tr", language_probability=0.98)


def _make_f32_payload(samples: int = 16_000, amp: float = 0.1) -> bytes:
    arr = np.full(samples, amp, dtype="<f4")
    return arr.tobytes()


def _make_pcm16_payload(values: list[int]) -> bytes:
    return struct.pack(f"<{len(values)}h", *values)


def _make_utterance(
    *,
    session_id: str = "sess-1",
    stream_id: str = "mic-in",
    format_epoch: int = 0,
    turn_id: int = 1,
    utterance_id: str = "utt-1",
    start_sample: int = 0,
    end_sample_exclusive: int = 16_000,
    finalized: bool = True,
    finalization_reason: str | None = "eos",
    payload: bytes | None = None,
    has_discontinuity: bool = False,
    pre_roll: int = 0,
    post_roll: int = 0,
    frame_refs: tuple[str, ...] = (),
) -> Utterance:
    if payload is None and not frame_refs:
        payload = _make_f32_payload(end_sample_exclusive - start_sample)
    return Utterance(
        utterance_id=utterance_id,
        stream_ref=StreamRef(
            session_id=session_id,
            stream_id=stream_id,
            direction=StreamDirection.INPUT,
            format_epoch=format_epoch,
        ),
        turn_ref=TurnRef(session_id=session_id, turn_id=turn_id),
        start_sample=start_sample,
        end_sample_exclusive=end_sample_exclusive,
        finalized=finalized,
        finalization_reason=finalization_reason,
        frame_refs=frame_refs,
        actual_pre_roll_samples=pre_roll,
        actual_post_roll_samples=post_roll,
        has_discontinuity=has_discontinuity,
        payload=payload,
    )


def _make_pinned_config(
    *,
    route_mode: ASRRouteMode = ASRRouteMode.STRICT,
    require_lexicon: bool = False,
    catalog_hotwords: bool = False,
    min_rms: float = 0.0,
    max_input_samples: int = 320_000,
    deadline_ms: int = 10_000,
) -> PinnedASRConfig:
    snap = resolve_configuration(
        env={
            "STT_CATALOG_HOTWORDS": "true" if catalog_hotwords else "false",
            "STT_MIN_RMS": str(min_rms),
        },
    ).snapshot
    return resolve_asr_config(
        snap,
        route_mode=route_mode,
        require_lexicon_snapshot=require_lexicon,
        max_input_samples=max_input_samples,
        deadline_ms=deadline_ms,
    )


def _make_scheduler(
    clock: FakeClock,
    *,
    free_mib: int | None = 4096,
    max_quarantine_entries: int = 16,
) -> tuple[UnifiedGpuScheduler, FakeGPUProbeAdapter]:
    budget = MemoryBudget(clock=clock, headroom_bytes=256 * MIB, max_probe_age_ms=2_000)
    probe = FakeGPUProbeAdapter(clock, total_mib=8192)
    if free_mib is not None:
        budget.update_probe(probe.valid_probe(free_mib=free_mib))
    residency = ResidencyManager(memory_budget=budget)
    residency.register_model(
        ModelSpec(
            model_id="stt-whisper",
            ownership=HandleOwnership.BORROWED,
            provider=ProviderKind.CTRANSLATE2,
            vram_bytes=0,
            loader=lambda: "borrowed-whisper-handle",
        )
    )
    quarantine = QuarantineManager(clock=clock, max_entries=max_quarantine_entries)
    scheduler = UnifiedGpuScheduler(
        clock=clock,
        memory_budget=budget,
        quarantine_manager=quarantine,
        residency_manager=residency,
    )
    return scheduler, probe


async def _open_session_with_turn(
    clock: FakeClock,
    *,
    session_id: str = "sess-1",
    trace_id: str = "trace-1",
) -> tuple[SessionRegistry, SessionContext, TurnRef, CancellationScope]:
    reg = SessionRegistry(clock=clock)
    ctx = await reg.create(session_id, trace_id=trace_id)
    await ctx.open()
    turn_ref, turn_scope = await ctx.begin_turn()
    return reg, ctx, turn_ref, turn_scope


def _make_pipeline(
    clock: FakeClock,
    model: FakeWhisperModel,
    *,
    free_mib: int | None = 4096,
    consumer_max_items: int = 16,
    max_total_pending: int = 32,
    max_per_session_pending: int = 4,
    limits: CollectorLimits | None = None,
    bus_max_lane: int = 128,
) -> tuple[SpeechRecognitionPipeline, UnifiedGpuScheduler, InMemoryASRConsumer, ASRTelemetryBridge]:
    scheduler, _ = _make_scheduler(clock, free_mib=free_mib)
    engine = WhisperSchedulerEngine(scheduler, model_getter=lambda: model, limits=limits)
    admission = ASRUtteranceAdmission(
        max_total_pending=max_total_pending,
        max_per_session_pending=max_per_session_pending,
    )
    consumer = InMemoryASRConsumer(max_items=consumer_max_items)
    bus = BoundedEventBus(max_lane_size=bus_max_lane)
    telemetry = ASRTelemetryBridge(
        event_bus=bus,
        metrics=MetricsRegistry(),
        projection=Projection(extra_allowlist=ASR_TELEMETRY_ALLOWLIST),
    )
    pipeline = SpeechRecognitionPipeline(
        engine=engine,
        admission=admission,
        consumer=consumer,
        telemetry=telemetry,
        lifecycle=ASRLifecycleManager(),
    )
    return pipeline, scheduler, consumer, telemetry


def _make_test_lexicon() -> LexiconRegistry:
    snap = LexiconSnapshot(
        entities=(
            CanonicalEntity(
                entity_id="veh:qashqai",
                canonical_name="Qashqai",
                category=EntityCategory.MODEL,
                normalized_key="qashqai",
                brand_name="Nissan",
                model_name="Qashqai",
            ),
            CanonicalEntity(
                entity_id="veh:ambig_a",
                canonical_name="Passat",
                category=EntityCategory.MODEL,
                normalized_key="passat",
                brand_name="Volkswagen",
                model_name="Passat",
            ),
            CanonicalEntity(
                entity_id="veh:ambig_b",
                canonical_name="Polo",
                category=EntityCategory.MODEL,
                normalized_key="polo",
                brand_name="Volkswagen",
                model_name="Polo",
            ),
        ),
        aliases=(
            AliasEntry(
                alias_id="al:kaskay",
                alias_text="kaş kay",
                normalized_key="kaş kay",
                canonical_entity_id="veh:qashqai",
                canonical_name="Qashqai",
                category=EntityCategory.MODEL,
            ),
            AliasEntry(
                alias_id="al:pasat_a",
                alias_text="pasat",
                normalized_key="pasat",
                canonical_entity_id="veh:ambig_a",
                canonical_name="Passat",
                category=EntityCategory.MODEL,
            ),
            AliasEntry(
                alias_id="al:pasat_b",
                alias_text="pasat",
                normalized_key="pasat",
                canonical_entity_id="veh:ambig_b",
                canonical_name="Polo",
                category=EntityCategory.MODEL,
            ),
        ),
        pronunciations=(),
        technical_terms=(),
    )
    return LexiconRegistry.from_snapshot(snap)


# =====================================================================
# AS01 - AS04: Preflight, passive import, M01 contracts
# =====================================================================


def test_as01_missing_core_gate_holds(tmp_path: Path) -> None:
    val = EvidenceValidator(REPO_ROOT)
    missing_root = tmp_path / "missing_core"
    res = val.verify_package_acceptance_dir("CORE_INTEGRATION", missing_root, required_gates=("CG00", "CG11"))
    assert res.status == PrerequisiteStatus.MISSING


def test_as02_stale_dependency_manifest_holds(tmp_path: Path) -> None:
    doc_root = tmp_path / "f1_a"
    run_dir = doc_root / "20261126T000000Z"
    run_dir.mkdir(parents=True)
    (run_dir / "ACCEPTANCE_MATRIX.json").write_text(
        json.dumps({"overall": "HOLD", "f1_a_ready": False, "gates": {"G00": "HOLD"}}),
        encoding="utf-8",
    )
    val = EvidenceValidator(REPO_ROOT)
    res = val.verify_package_acceptance_dir(
        "F1_A", doc_root, required_gates=("G00",), ready_flag="f1_a_ready"
    )
    assert res.status == PrerequisiteStatus.HOLD
    assert any("F1_A_READY_FLAG_FALSE" in e for e in res.errors)


def test_as03_passive_cpu_only_import_no_models_or_threads() -> None:
    code = (
        "import sys, threading; "
        "before_threads = threading.active_count(); "
        "import backend.speech_recognition; "
        "after_threads = threading.active_count(); "
        "forbidden = [m for m in ('torch','torchaudio','faster_whisper','ctranslate2','backend.models','backend.db','sqlalchemy') if m in sys.modules]; "
        "assert not forbidden, f'Forbidden modules imported: {forbidden}'; "
        "assert after_threads == before_threads, f'Thread delta {after_threads - before_threads}'"
    )
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = ""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"


def test_as04_accepted_m01_contract_round_trip() -> None:
    clock = FakeClock(1_000_000, clock_domain="test.clock")
    res = build_final_asr_result(
        session_id="sess-m01",
        utterance_id="utt-m01",
        turn_id=1,
        sequence=0,
        clock=clock,
        outcome=ASROutcome.OK,
        raw_transcript="merhaba",
        language="tr",
        confidence=ConfidenceEstimate(avg_logprob=-0.2, no_speech_prob=0.01),
    )
    assert isinstance(res, ASRResult)
    assert res.envelope.schema_version == CONTRACT_SCHEMA_VERSION
    encoded = metadata_to_json(res)
    decoded = json.loads(encoded)
    assert decoded["utterance_id"] == "utt-m01"
    assert decoded["outcome"] == "OK"


# =====================================================================
# AS05 - AS16: Input validation & immutable materialization
# =====================================================================


def test_as05_valid_16k_float32_mono_utterance() -> None:
    utt = _make_utterance(start_sample=100, end_sample_exclusive=500, payload=_make_f32_payload(400, 0.25))
    val = validate_and_materialize_utterance(utt, FMT_16K_F32)
    arr = val.audio.samples_view()
    assert val.audio.sample_count == 400
    assert val.audio.start_sample == 100
    assert val.audio.end_sample_exclusive == 500
    assert not arr.flags.writeable
    assert np.allclose(arr, 0.25)


def test_as06_valid_16k_pcm16_le_conversion() -> None:
    pcm = _make_pcm16_payload([0, 16384, -16384])
    utt = _make_utterance(start_sample=0, end_sample_exclusive=3, payload=pcm)
    val = validate_and_materialize_utterance(utt, FMT_16K_PCM16)
    arr = val.audio.samples_view()
    assert arr.dtype == np.float32
    assert np.allclose(arr, [0.0, 0.5, -0.5], atol=1e-6)


def test_as07_pcm16_extrema_no_clipping_wrap() -> None:
    pcm = _make_pcm16_payload([-32768, 0, 32767])
    utt = _make_utterance(start_sample=0, end_sample_exclusive=3, payload=pcm)
    val = validate_and_materialize_utterance(utt, FMT_16K_PCM16)
    arr = val.audio.samples_view()
    assert float(arr[0]) == -1.0
    assert float(arr[1]) == 0.0
    assert float(arr[2]) == pytest.approx(32767.0 / 32768.0, rel=1e-6)
    assert float(arr[2]) < 1.0


@pytest.mark.asyncio
async def test_as08_nonfinal_utterance_and_speech_event_rejected() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel()
    pipeline, _, _, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)
    cfg = _make_pinned_config()

    nonfinal = _make_utterance(finalized=False, finalization_reason=None, payload=_make_f32_payload(160))
    rec1 = await pipeline.process_utterance(nonfinal, FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    assert rec1.result is not None and rec1.result.outcome == ASROutcome.REJECTED

    cand_evt = SpeechEvent(
        envelope=build_final_asr_result(
            session_id="sess-1", utterance_id="u0", turn_id=1, sequence=0, clock=clock, outcome=ASROutcome.NO_SPEECH
        ).envelope,
        kind=SpeechEventKind.SPEECH_CANDIDATE,
        stream_ref=StreamRef("sess-1", "mic-in", StreamDirection.INPUT),
        sample_offset=0,
        reason="vad_candidate",
    )
    rec2 = await pipeline.process_utterance(cand_evt, FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    assert rec2.result is not None and rec2.result.outcome == ASROutcome.REJECTED
    assert model.invocation_count == 0


@pytest.mark.asyncio
async def test_as09_empty_audio_with_eos_metadata_is_no_speech() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel()
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)
    cfg = _make_pinned_config()

    empty_utt = _make_utterance(start_sample=320, end_sample_exclusive=320, payload=b"", finalization_reason="eos")
    rec = await pipeline.process_utterance(empty_utt, FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    assert rec.result is not None
    assert rec.result.outcome == ASROutcome.NO_SPEECH
    assert rec.result.raw_transcript == ""
    assert model.invocation_count == 0
    assert consumer.pending_count == 0


def test_as10_odd_pcm_bytes_and_frame_mismatch_rejected() -> None:
    utt_odd = _make_utterance(start_sample=0, end_sample_exclusive=1, payload=b"\x00\x01\x02")
    with pytest.raises(ASRInputError) as exc_odd:
        validate_and_materialize_utterance(utt_odd, FMT_16K_PCM16)
    assert exc_odd.value.code == "ASR_ODD_PCM_BYTES"

    sr = StreamRef("sess-1", "mic-in", StreamDirection.INPUT)
    f1 = AudioFrame(CONTRACT_SCHEMA_VERSION, sr, 0, FMT_16K_F32, 160, 0, _make_f32_payload(160))
    utt_mismatch = _make_utterance(start_sample=0, end_sample_exclusive=320, frame_refs=("f1",), payload=None)
    with pytest.raises(ASRInputError) as exc_frm:
        validate_and_materialize_utterance(utt_mismatch, FMT_16K_F32, frames=[f1])
    assert exc_frm.value.code == "ASR_FRAME_INTERVAL_MISMATCH"


def test_as11_nan_inf_and_unsupported_encoding_rejected() -> None:
    nan_bytes = struct.pack("<2f", float("nan"), 0.0)
    utt_nan = _make_utterance(start_sample=0, end_sample_exclusive=2, payload=nan_bytes)
    with pytest.raises(ASRInputError) as exc_nan:
        validate_and_materialize_utterance(utt_nan, FMT_16K_F32)
    assert exc_nan.value.code == "ASR_NONFINITE_AUDIO"

    inf_bytes = struct.pack("<2f", 0.1, float("inf"))
    utt_inf = _make_utterance(start_sample=0, end_sample_exclusive=2, payload=inf_bytes)
    with pytest.raises(ASRInputError) as exc_inf:
        validate_and_materialize_utterance(utt_inf, FMT_16K_F32)
    assert exc_inf.value.code == "ASR_NONFINITE_AUDIO"

    utt_bad_enc = _make_utterance(start_sample=0, end_sample_exclusive=2, payload=b"\x00" * 8)
    with pytest.raises(ASRInputError) as exc_enc:
        validate_and_materialize_utterance(utt_bad_enc, SimpleNamespace(sample_rate_hz=16000, channels=1, encoding="OPUS"))  # type: ignore[arg-type]
    assert exc_enc.value.code == "ASR_INVALID_FORMAT"


def test_as12_8k_48k_or_stereo_rejected_no_resampler() -> None:
    utt = _make_utterance(start_sample=0, end_sample_exclusive=160, payload=_make_f32_payload(160))
    for bad_fmt, expected_code in (
        (AudioFormat(8000, 1, AudioEncoding.FLOAT32_LE), "ASR_UNSUPPORTED_SAMPLE_RATE"),
        (AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE), "ASR_UNSUPPORTED_SAMPLE_RATE"),
        (AudioFormat(16000, 2, AudioEncoding.FLOAT32_LE), "ASR_UNSUPPORTED_CHANNELS"),
    ):
        with pytest.raises(ASRInputError) as exc:
            validate_and_materialize_utterance(utt, bad_fmt)
        assert exc.value.code == expected_code


def test_as13_unapproved_discontinuity_rejected() -> None:
    utt = _make_utterance(start_sample=0, end_sample_exclusive=160, has_discontinuity=True)
    with pytest.raises(ASRInputError) as exc:
        validate_and_materialize_utterance(utt, FMT_16K_F32, allow_discontinuity=False)
    assert exc.value.code == "ASR_UNAPPROVED_DISCONTINUITY"


def test_as14_pre_post_roll_preserved_without_second_trimming() -> None:
    samples = np.concatenate([
        np.zeros(1600, dtype="<f4"),
        np.full(3200, 0.2, dtype="<f4"),
        np.zeros(800, dtype="<f4"),
    ])
    utt = _make_utterance(
        start_sample=0,
        end_sample_exclusive=5600,
        pre_roll=1600,
        post_roll=800,
        payload=samples.tobytes(),
    )
    val = validate_and_materialize_utterance(utt, FMT_16K_F32)
    assert val.audio.sample_count == 5600
    assert val.audio.pre_roll_samples == 1600
    assert val.audio.post_roll_samples == 800
    assert np.array_equal(val.audio.samples_view(), samples)


def test_as15_oversized_duration_and_bytes_rejected() -> None:
    utt = _make_utterance(start_sample=0, end_sample_exclusive=320_001, payload=b"\x00" * (320_001 * 4))
    with pytest.raises(ASRInputError) as exc:
        validate_and_materialize_utterance(utt, FMT_16K_F32, max_samples=320_000)
    assert exc.value.code == "ASR_DURATION_LIMIT_EXCEEDED"


def test_as16_caller_buffer_mutation_after_materialization_isolated() -> None:
    buf = bytearray(np.full(160, 0.25, dtype="<f4").tobytes())
    utt = _make_utterance(start_sample=0, end_sample_exclusive=160, payload=bytes(buf))
    val = validate_and_materialize_utterance(utt, FMT_16K_F32)
    # Mutate caller's original bytearray
    for i in range(len(buf)):
        buf[i] = 0xFF
    assert np.allclose(val.audio.samples_view(), 0.25)


# =====================================================================
# AS17 - AS23: Utterance admission, dedup, concurrency & caps
# =====================================================================


@pytest.mark.asyncio
async def test_as17_wrong_session_stream_epoch_turn_rejected() -> None:
    clock = FakeClock(1_000)
    _, ctx, _, _ = await _open_session_with_turn(clock, session_id="sess-A")
    adm = ASRUtteranceAdmission()

    bad_sess = validate_and_materialize_utterance(_make_utterance(session_id="sess-B", turn_id=1), FMT_16K_F32)
    d1 = await adm.claim_utterance(bad_sess, session_ctx=ctx)
    assert d1.status == ClaimStatus.STALE_SCOPE

    bad_epoch = validate_and_materialize_utterance(_make_utterance(session_id="sess-A", format_epoch=2, turn_id=1), FMT_16K_F32)
    d2 = await adm.claim_utterance(bad_epoch, session_ctx=ctx, expected_stream_epoch=0)
    assert d2.status == ClaimStatus.STALE_SCOPE

    bad_turn = validate_and_materialize_utterance(_make_utterance(session_id="sess-A", turn_id=99), FMT_16K_F32)
    d3 = await adm.claim_utterance(bad_turn, session_ctx=ctx)
    assert d3.status == ClaimStatus.STALE_SCOPE


@pytest.mark.asyncio
async def test_as18_duplicate_identical_utterance_single_claim() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel()
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)
    cfg = _make_pinned_config()

    utt = _make_utterance(utterance_id="utt-dup", turn_id=1)
    r1 = await pipeline.process_utterance(utt, FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    r2 = await pipeline.process_utterance(utt, FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    assert r1.claim_decision is not None and r1.claim_decision.status == ClaimStatus.ACCEPTED
    assert r2.claim_decision is not None and r2.claim_decision.status == ClaimStatus.DUPLICATE
    assert model.invocation_count == 1
    assert consumer.pending_count == 1


@pytest.mark.asyncio
async def test_as19_same_identity_changed_payload_is_conflict() -> None:
    clock = FakeClock(1_000)
    _, ctx, _, _ = await _open_session_with_turn(clock)
    adm = ASRUtteranceAdmission()

    v1 = validate_and_materialize_utterance(
        _make_utterance(utterance_id="utt-c", payload=_make_f32_payload(160, 0.1), end_sample_exclusive=160),
        FMT_16K_F32,
    )
    v2 = validate_and_materialize_utterance(
        _make_utterance(utterance_id="utt-c", payload=_make_f32_payload(160, 0.5), end_sample_exclusive=160),
        FMT_16K_F32,
    )
    d1 = await adm.claim_utterance(v1, session_ctx=ctx)
    d2 = await adm.claim_utterance(v2, session_ctx=ctx)
    assert d1.status == ClaimStatus.ACCEPTED
    assert d2.status == ClaimStatus.CONFLICT


@pytest.mark.asyncio
async def test_as20_simultaneous_claims_exactly_one_accepted() -> None:
    clock = FakeClock(1_000)
    _, ctx, _, _ = await _open_session_with_turn(clock)
    adm = ASRUtteranceAdmission()
    v1 = validate_and_materialize_utterance(_make_utterance(utterance_id="utt-race"), FMT_16K_F32)
    v2 = validate_and_materialize_utterance(_make_utterance(utterance_id="utt-race"), FMT_16K_F32)

    d1, d2 = await asyncio.gather(
        adm.claim_utterance(v1, session_ctx=ctx),
        adm.claim_utterance(v2, session_ctx=ctx),
    )
    statuses = sorted([d1.status.value, d2.status.value])
    assert statuses == [ClaimStatus.ACCEPTED.value, ClaimStatus.DUPLICATE.value]


@pytest.mark.asyncio
async def test_as21_per_session_and_global_job_caps() -> None:
    clock = FakeClock(1_000)
    reg = SessionRegistry(clock=clock)
    ctx1 = await reg.create("sess-1")
    ctx2 = await reg.create("sess-2")
    await ctx1.open()
    await ctx2.open()
    await ctx1.begin_turn()
    await ctx2.begin_turn()

    adm = ASRUtteranceAdmission(max_total_pending=3, max_per_session_pending=2)
    d1 = await adm.claim_utterance(validate_and_materialize_utterance(_make_utterance(session_id="sess-1", utterance_id="u1"), FMT_16K_F32), session_ctx=ctx1)
    d2 = await adm.claim_utterance(validate_and_materialize_utterance(_make_utterance(session_id="sess-1", utterance_id="u2"), FMT_16K_F32), session_ctx=ctx1)
    d3 = await adm.claim_utterance(validate_and_materialize_utterance(_make_utterance(session_id="sess-1", utterance_id="u3"), FMT_16K_F32), session_ctx=ctx1)
    assert d1.status == ClaimStatus.ACCEPTED
    assert d2.status == ClaimStatus.ACCEPTED
    assert d3.status == ClaimStatus.CAPACITY_REJECTED

    d4 = await adm.claim_utterance(validate_and_materialize_utterance(_make_utterance(session_id="sess-2", utterance_id="u1"), FMT_16K_F32), session_ctx=ctx2)
    assert d4.status == ClaimStatus.ACCEPTED

    ctx3 = await reg.create("sess-3")
    await ctx3.open()
    await ctx3.begin_turn()
    d5 = await adm.claim_utterance(validate_and_materialize_utterance(_make_utterance(session_id="sess-3", utterance_id="u1"), FMT_16K_F32), session_ctx=ctx3)
    assert d5.status == ClaimStatus.CAPACITY_REJECTED


@pytest.mark.asyncio
async def test_as22_two_sessions_same_local_utterance_id_isolated() -> None:
    clock = FakeClock(1_000)

    def _handler(audio: np.ndarray, _kwargs: dict[str, Any]) -> tuple[Any, Any]:
        val = float(audio[0])
        txt = "sess one text" if val < 0.3 else "sess two text"
        return iter([FakeWhisperSegment(text=txt, start=0.0, end=0.4)]), SimpleNamespace(language="tr")

    model = FakeWhisperModel(handler=_handler)
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    reg = SessionRegistry(clock=clock)
    ctx_a = await reg.create("sess-alpha")
    ctx_b = await reg.create("sess-beta")
    await ctx_a.open()
    await ctx_b.open()
    await ctx_a.begin_turn()
    await ctx_b.begin_turn()
    cfg = _make_pinned_config()

    utt_a = _make_utterance(session_id="sess-alpha", utterance_id="local-utt-1", payload=_make_f32_payload(16_000, 0.1))
    utt_b = _make_utterance(session_id="sess-beta", utterance_id="local-utt-1", payload=_make_f32_payload(16_000, 0.5))
    rec_a, rec_b = await asyncio.gather(
        pipeline.process_utterance(utt_a, FMT_16K_F32, session_ctx=ctx_a, pinned_config=cfg),
        pipeline.process_utterance(utt_b, FMT_16K_F32, session_ctx=ctx_b, pinned_config=cfg),
    )
    assert rec_a.result is not None and rec_a.result.raw_transcript == "sess one text"
    assert rec_a.result.envelope.session_id == "sess-alpha"
    assert rec_b.result is not None and rec_b.result.raw_transcript == "sess two text"
    assert rec_b.result.envelope.session_id == "sess-beta"
    assert consumer.pending_count == 2


@pytest.mark.asyncio
async def test_as23_late_duplicate_after_prior_final_no_second_dispatch() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel()
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)
    cfg = _make_pinned_config()

    utt = _make_utterance(utterance_id="utt-final-once")
    first = await pipeline.process_utterance(utt, FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    assert first.delivery.delivery_status == ASRDeliveryStatus.DELIVERED
    popped = consumer.pop_next_valid()
    assert popped is not None

    late = await pipeline.process_utterance(utt, FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    assert late.claim_decision is not None and late.claim_decision.status == ClaimStatus.DUPLICATE
    assert model.invocation_count == 1
    assert consumer.pop_next_valid() is None


# =====================================================================
# AS24 - AS29: Configuration, ModelRegistry, and Hotwords
# =====================================================================


def test_as24_legacy_settings_mapped_to_m03_profile() -> None:
    resolved = resolve_configuration()
    cfg = resolve_asr_config(resolved.snapshot)
    assert cfg.model_name == "large-v3-turbo"
    assert cfg.device == "cuda"
    assert cfg.compute_type == "float16"
    assert cfg.decode_profile.language == "tr"
    assert cfg.decode_profile.beam_size == 1
    assert cfg.decode_profile.no_speech_threshold == 0.50
    assert cfg.decode_profile.log_prob_threshold == -0.80
    assert cfg.decode_profile.compression_ratio_threshold == 2.2
    assert cfg.decode_profile.post_no_speech_prob_max == 0.40
    assert cfg.decode_profile.post_avg_logprob_min == -0.85
    assert cfg.decode_profile.post_compression_ratio_max == 2.2
    assert cfg.route_mode == ASRRouteMode.LEGACY


def test_as25_config_swap_while_queued_preserves_pinned_snapshot() -> None:
    r1 = resolve_configuration(env={"STT_MIN_RMS": "0.01"})
    r2 = resolve_configuration(env={"STT_MIN_RMS": "0.50"})
    store = ConfigSnapshotStore(r1.snapshot)
    pinned = resolve_asr_config(store.current, route_mode=ASRRouteMode.STRICT)
    store.swap(r2.snapshot)

    clock = FakeClock(1_000)
    scope = CancellationScope("turn:1", clock=clock)
    validated = validate_and_materialize_utterance(_make_utterance(), FMT_16K_F32)
    lex_snap = pin_lexicon_snapshot(None)
    hw = build_legacy_hotwords(catalog_enabled=False)
    req = build_asr_resource_request(
        recognition_job_id="job-pin-1",
        utterance_input=validated,
        pinned_config=pinned,
        pinned_lexicon=lex_snap,
        hotwords=hw,
        cancellation_scope=scope,
        clock=clock,
    )
    assert store.current.get("stt_min_rms") == 0.50
    assert req.payload.pinned_config.min_rms == 0.01
    assert req.payload.pinned_config.config_revision == r1.snapshot.config_revision


def test_as26_missing_or_unsupported_model_revision_fails_explicitly() -> None:
    snap = resolve_configuration().snapshot
    empty_reg = ModelRegistry([])
    with pytest.raises(ASRConfigError) as exc1:
        resolve_asr_config(snap, empty_reg)
    assert exc1.value.code == "ASR_MODEL_UNAVAILABLE"

    unsupported_reg = ModelRegistry([
        ModelDescriptor(
            model_id="stt-whisper",
            kind=ModelKind.STT,
            model_revision="large-v3-turbo:float16",
            version="large-v3-turbo",
            device="cuda",
            capability=CapabilityDescriptor(
                name="stt-whisper",
                scope="ASR_TRANSCRIPTION",
                state=CapabilityState.UNSUPPORTED,
            ),
        )
    ])
    with pytest.raises(ASRConfigError) as exc2:
        resolve_asr_config(snap, unsupported_reg)
    assert exc2.value.code == "ASR_MODEL_UNSUPPORTED"


def test_as27_legacy_hotword_list_cap_ttl_and_order() -> None:
    clock = FakeClock(1_000_000_000)
    cache = LegacyHotwordCache(ttl_sec=60.0, cap=50, clock=clock)
    calls = 0

    def _provider(cap: int) -> list[str]:
        nonlocal calls
        calls += 1
        return [f"Model-{i}" for i in range(70)][:cap] + ["Model-0"]

    sel1 = cache.select(catalog_enabled=True, catalog_provider=_provider, custom_hotwords=["Özel", "Model-0"])
    assert len(sel1.terms) == 51  # 50 unique catalog + 1 unique custom
    assert sel1.terms[0] == "Model-0"
    assert sel1.terms[-1] == "Özel"
    assert not sel1.from_cache
    assert calls == 1

    clock.advance_ms(10_000)
    sel2 = cache.select(catalog_enabled=True, catalog_provider=_provider, custom_hotwords=["Özel"])
    assert sel2.from_cache
    assert calls == 1

    clock.advance_ms(60_000)
    sel3 = cache.select(catalog_enabled=True, catalog_provider=_provider)
    assert not sel3.from_cache
    assert calls == 2


def test_as28_m05_snapshot_change_while_job_running() -> None:
    lex_v1 = _make_test_lexicon()
    lex_v2 = LexiconRegistry.from_snapshot(
        LexiconSnapshot(entities=(), aliases=(), pronunciations=(), technical_terms=())
    )
    pinned_v1 = pin_lexicon_snapshot(lex_v1, strict_required=True)
    # Caller switches active registry to lex_v2 while job runs; pinned_v1 stays immutable
    _ = lex_v2
    bundle = extract_conservative_candidates(pinned_v1, "Nisan kaş kay")
    assert bundle.lexicon_revision == lex_v1.lexicon_revision
    assert len(bundle.candidates) == 1
    assert bundle.candidates[0].canonical_value == "Qashqai"


def test_as29_pii_blocked_from_hotwords() -> None:
    sel = build_legacy_hotwords(
        catalog_enabled=True,
        catalog_provider=lambda _cap: ["Qashqai", "+90 532 111 22 33", "34 ABC 123", "WVWZZZ3CZWE123456"],
        custom_hotwords=["bearer supersecret12345", "Megane"],
    )
    assert sel.terms == ("Qashqai", "Megane")
    assert sel.filtered_pii_count == 4


# =====================================================================
# AS30 - AS40: M06 scheduling, lazy completion, leases & quarantine
# =====================================================================


def test_as30_valid_final_job_request_to_m06() -> None:
    clock = FakeClock(5_000)
    scope = CancellationScope("turn:1", clock=clock)
    cfg = _make_pinned_config()
    validated = validate_and_materialize_utterance(_make_utterance(), FMT_16K_F32)
    req = build_asr_resource_request(
        recognition_job_id="job-30",
        utterance_input=validated,
        pinned_config=cfg,
        pinned_lexicon=pin_lexicon_snapshot(None),
        hotwords=build_legacy_hotwords(catalog_enabled=False),
        cancellation_scope=scope,
        clock=clock,
    )
    assert req.priority == PriorityClass.P1
    assert req.provider == ProviderKind.CTRANSLATE2
    assert req.turn_ref == TurnRef("sess-1", 1)
    assert req.deadline is not None and req.deadline.clock_domain == clock.clock_domain


@pytest.mark.asyncio
async def test_as31_scheduler_waiting_vs_admitted() -> None:
    clock = FakeClock(5_000)
    scheduler, probe = _make_scheduler(clock, free_mib=300)  # usable = 300 - 256 = 44 MiB
    model = FakeWhisperModel()
    engine = WhisperSchedulerEngine(scheduler, model_getter=lambda: model)

    cfg = resolve_asr_config(
        resolve_configuration().snapshot,
        estimated_vram_bytes=128 * MIB,
    )
    req = build_asr_resource_request(
        recognition_job_id="job-wait",
        utterance_input=validate_and_materialize_utterance(_make_utterance(), FMT_16K_F32),
        pinned_config=cfg,
        pinned_lexicon=pin_lexicon_snapshot(None),
        hotwords=build_legacy_hotwords(catalog_enabled=False),
        cancellation_scope=CancellationScope("turn:1", clock=clock),
        clock=clock,
    )
    status = engine.submit_to_queue(req, require_immediate_budget=False)
    assert status == ASRDispatchStatus.QUEUED
    assert model.invocation_count == 0

    scheduler.memory_budget.update_probe(probe.valid_probe(free_mib=2048))
    exec_res = await engine.dispatch_next()
    assert exec_res is not None
    assert exec_res.dispatch_status == ASRDispatchStatus.COMPLETED
    assert exec_res.asr_outcome == ASROutcome.OK
    assert model.invocation_count == 1


@pytest.mark.asyncio
async def test_as32_m06_rejected_expired_unavailable_no_bypass() -> None:
    clock = FakeClock(5_000)
    model = FakeWhisperModel()
    # Probe missing -> REJECTED_PROBE_UNAVAILABLE
    pipeline, _, _, _ = _make_pipeline(clock, model, free_mib=None)
    _, ctx, _, _ = await _open_session_with_turn(clock)
    cfg = _make_pinned_config()

    rec = await pipeline.process_utterance(_make_utterance(), FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    assert rec.dispatch_status == ASRDispatchStatus.UNAVAILABLE
    assert rec.result is not None and rec.result.outcome == ASROutcome.REJECTED
    assert model.invocation_count == 0


@pytest.mark.asyncio
async def test_as33_two_requests_against_shared_existing_model() -> None:
    clock = FakeClock(5_000)
    model = FakeWhisperModel()
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)
    cfg = _make_pinned_config()

    r1 = await pipeline.process_utterance(_make_utterance(utterance_id="u1"), FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    r2 = await pipeline.process_utterance(_make_utterance(utterance_id="u2"), FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    assert r1.result is not None and r1.result.outcome == ASROutcome.OK
    assert r2.result is not None and r2.result.outcome == ASROutcome.OK
    assert model.invocation_count == 2
    assert consumer.pending_count == 2


@pytest.mark.asyncio
async def test_as34_lazy_generator_retains_lease_through_iteration() -> None:
    clock = FakeClock(5_000)
    lease_states_during_iter: list[ExecutionLeaseState] = []
    scheduler, _ = _make_scheduler(clock)

    def _lazy_gen(_audio: np.ndarray, _kwargs: dict[str, Any]) -> tuple[Any, Any]:
        def _gen():
            yield FakeWhisperSegment("bir", 0.0, 0.2)
            yield FakeWhisperSegment(" iki", 0.2, 0.4)
        return _gen(), SimpleNamespace(language="tr")

    model = FakeWhisperModel(handler=_lazy_gen)
    engine = WhisperSchedulerEngine(scheduler, model_getter=lambda: model)

    def _on_seg(_seg: Any) -> None:
        # Lease seq 1 is active IN_FLIGHT while generator emits
        lease = scheduler.get_lease("lease:1:job-34")
        assert lease is not None
        lease_states_during_iter.append(lease.state)

    req = build_asr_resource_request(
        recognition_job_id="job-34",
        utterance_input=validate_and_materialize_utterance(_make_utterance(), FMT_16K_F32),
        pinned_config=_make_pinned_config(),
        pinned_lexicon=pin_lexicon_snapshot(None),
        hotwords=build_legacy_hotwords(catalog_enabled=False),
        cancellation_scope=CancellationScope("turn:1", clock=clock),
        clock=clock,
    )
    res = await engine.run_admitted(req, on_segment=_on_seg)
    assert lease_states_during_iter == [ExecutionLeaseState.IN_FLIGHT, ExecutionLeaseState.IN_FLIGHT]
    assert res.lease_state == ExecutionLeaseState.RELEASED


@pytest.mark.asyncio
async def test_as35_generator_raises_after_first_segment_no_ok_final() -> None:
    clock = FakeClock(5_000)

    def _failing_gen(_audio: np.ndarray, _kwargs: dict[str, Any]) -> tuple[Any, Any]:
        def _gen():
            yield FakeWhisperSegment("yarım", 0.0, 0.2)
            raise RuntimeError("cuda decode crash")
        return _gen(), SimpleNamespace(language="tr")

    model = FakeWhisperModel(handler=_failing_gen)
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)

    rec = await pipeline.process_utterance(_make_utterance(), FMT_16K_F32, session_ctx=ctx, pinned_config=_make_pinned_config())
    assert rec.result is not None
    assert rec.result.outcome == ASROutcome.ERROR
    assert consumer.pending_count == 0


@pytest.mark.asyncio
async def test_as36_iterator_exceeds_bounded_budget_stops_safely() -> None:
    def _huge_gen():
        for i in range(500):
            yield FakeWhisperSegment(f"seg{i} ", 0.0, 0.01)

    collected = await collect_whisper_segments(
        _huge_gen(),
        limits=CollectorLimits(max_segments=5, max_text_bytes=1024),
    )
    assert collected.budget_exceeded
    assert not collected.terminal_verified
    assert len(collected.segments) == 5
    assert collected.error_code == "ASR_SEGMENT_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_as37_cooperative_cancel_holds_borrowed_buffer_and_lease_until_safe() -> None:
    clock = FakeClock(5_000)
    barrier = DeterministicBarrier()
    pulled: list[str] = []

    def _async_handler(_audio: np.ndarray, _kwargs: dict[str, Any]) -> tuple[Any, Any]:
        async def _agen():
            pulled.append("seg1")
            yield FakeWhisperSegment("bir", 0.0, 0.2)
            try:
                await barrier.checkpoint("in_flight")
                pulled.append("seg2")
                yield FakeWhisperSegment(" iki", 0.2, 0.4)
                pulled.append("seg3")
                yield FakeWhisperSegment(" üç", 0.4, 0.6)
            finally:
                await barrier.checkpoint("teardown_hang")
        return _agen(), SimpleNamespace(language="tr")

    model = FakeWhisperModel(handler=_async_handler)
    pipeline, scheduler, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, turn_scope = await _open_session_with_turn(clock)
    cfg = _make_pinned_config()

    task = asyncio.create_task(pipeline.process_utterance(_make_utterance(), FMT_16K_F32, session_ctx=ctx, pinned_config=cfg))
    await barrier.wait_for_point("in_flight")

    # Cancel input turn while native generator is suspended before seg2
    turn_scope.request_cancel("user_cancelled_turn")
    barrier.release("in_flight")
    await barrier.wait_for_point("teardown_hang")

    rec = await task
    assert rec.execution_result is not None and rec.execution_result.quarantined
    assert rec.result is not None and rec.result.outcome == ASROutcome.UNKNOWN
    assert consumer.pending_count == 0
    assert "seg3" not in pulled
    # Input audio handle MUST remain un-released while native teardown is still blocked
    assert pipeline.lifecycle.active_audio_count == 1

    # Release native teardown and let M06 reclaim quarantine
    barrier.release("teardown_hang")
    await scheduler.wait_reclaims()
    report = await pipeline.lifecycle.shutdown_and_drain(scheduler=scheduler)
    assert report.cleanup_status == CleanupStatus.COMPLETE
    assert report.quarantined_leases == 0
    assert report.held_audio_handles == 0


def test_as38_duplicate_terminal_callback_idempotent() -> None:
    clock = FakeClock(1_000)
    scheduler, _ = _make_scheduler(clock)
    model = FakeWhisperModel()
    engine = WhisperSchedulerEngine(scheduler, model_getter=lambda: model)
    from backend.speech_recognition.whisper_engine import WhisperExecutionResult

    res = WhisperExecutionResult(
        request_id="req-38",
        dispatch_status=ASRDispatchStatus.COMPLETED,
        admission_outcome=AdmissionOutcome.ADMITTED,
        asr_outcome=ASROutcome.OK,
        collected=None,
    )
    assert engine.record_external_completion("req-38", res) is True
    assert engine.record_external_completion("req-38", res) is False


@pytest.mark.asyncio
async def test_as39_uncertain_completion_quarantines_and_no_dialogue() -> None:
    clock = FakeClock(5_000)
    entered_gate = asyncio.Event()
    hang_gate = asyncio.Event()

    def _hung_gen(_audio: np.ndarray, _kwargs: dict[str, Any]) -> tuple[Any, Any]:
        async def _agen():
            try:
                yield FakeWhisperSegment("test", 0.0, 0.2)
                entered_gate.set()
                await hang_gate.wait()
            finally:
                await hang_gate.wait()
        return _agen(), None

    model = FakeWhisperModel(handler=_hung_gen)
    pipeline, scheduler, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, turn_scope = await _open_session_with_turn(clock)
    cfg = _make_pinned_config()

    task = asyncio.create_task(pipeline.process_utterance(_make_utterance(), FMT_16K_F32, session_ctx=ctx, pinned_config=cfg))
    await asyncio.wait_for(entered_gate.wait(), timeout=2.0)
    turn_scope.request_cancel("shutdown")
    rec = await task
    assert rec.result is not None and rec.result.outcome == ASROutcome.UNKNOWN
    assert rec.execution_result is not None and rec.execution_result.quarantined
    assert consumer.pending_count == 0

    hang_gate.set()
    await scheduler.wait_reclaims()


@pytest.mark.asyncio
async def test_as40_provider_oom_handled_no_blind_retry() -> None:
    clock = FakeClock(5_000)

    def _oom_handler(_audio: np.ndarray, _kwargs: dict[str, Any]) -> tuple[Any, Any]:
        raise RuntimeError("CUDA out of memory")

    model = FakeWhisperModel(handler=_oom_handler)
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)

    rec = await pipeline.process_utterance(_make_utterance(), FMT_16K_F32, session_ctx=ctx, pinned_config=_make_pinned_config())
    assert model.invocation_count == 1  # No blind local retry
    assert rec.result is not None and rec.result.outcome == ASROutcome.ERROR
    assert rec.result.error is not None and rec.result.error.code == "ASR_PROVIDER_OOM"
    assert consumer.pending_count == 0


# =====================================================================
# AS41 - AS52: Raw transcript, timestamps, confidence, outcomes & guards
# =====================================================================


@pytest.mark.asyncio
async def test_as41_literal_raw_assembly_whitespace_and_punctuation() -> None:
    segs = [
        FakeWhisperSegment(" Nisan ", 0.0, 0.3),
        FakeWhisperSegment("kaş kay,", 0.3, 0.7),
        FakeWhisperSegment(" iki bin yirmi! ", 0.7, 1.0),
    ]
    collected = await collect_whisper_segments(iter(segs), utterance_duration_sec=1.0)
    assert collected.raw_transcript == " Nisan kaş kay, iki bin yirmi! "


@pytest.mark.asyncio
async def test_as42_turkish_unicode_and_decomposed_preserved() -> None:
    text = "Iğdır İstanbul ılık i\u0307şçöğüŞÇÖĞÜ"
    collected = await collect_whisper_segments(iter([FakeWhisperSegment(text, 0.0, 0.5)]), utterance_duration_sec=1.0)
    assert collected.raw_transcript == text
    assert [ord(c) for c in collected.raw_transcript] == [ord(c) for c in text]


@pytest.mark.asyncio
async def test_as43_legacy_strip_projection_separate_from_raw() -> None:
    segs = [
        FakeWhisperSegment("  Nisan kaş kay  ", 0.0, 0.5, no_speech_prob=0.1),
        FakeWhisperSegment(" gürültü ", 0.5, 0.8, no_speech_prob=0.9),
        FakeWhisperSegment("  randevu  ", 0.8, 1.0, no_speech_prob=0.1),
    ]
    collected = await collect_whisper_segments(iter(segs), utterance_duration_sec=1.0)
    proj = project_legacy_transcript(collected=collected)
    assert proj.raw_transcript == "  Nisan kaş kay   gürültü   randevu  "
    assert proj.legacy_text == "Nisan kaş kay randevu"
    assert proj.outcome == ASROutcome.OK


@pytest.mark.asyncio
async def test_as44_repeated_words_and_misspellings_unchanged() -> None:
    text = "kaş kay kaş kay evet evet"
    collected = await collect_whisper_segments(iter([FakeWhisperSegment(text, 0.0, 0.5)]), utterance_duration_sec=1.0)
    assert collected.raw_transcript == text


@pytest.mark.asyncio
async def test_as45_valid_segment_timestamps_origin_and_bounds() -> None:
    segs = [
        FakeWhisperSegment("bir", 0.0, 0.45),
        FakeWhisperSegment(" iki", 0.45, 1.02),  # within 0.05 tolerance of 1.0s
    ]
    collected = await collect_whisper_segments(iter(segs), utterance_duration_sec=1.0)
    assert not collected.malformed_metadata
    assert collected.segments[0].timestamp is not None
    assert collected.segments[0].timestamp.unit == "seconds"
    assert collected.segments[0].timestamp.origin == "utterance_start"
    assert collected.segments[1].timestamp is not None
    assert collected.segments[1].timestamp.end_sec == pytest.approx(1.02)


@pytest.mark.asyncio
async def test_as46_invalid_timestamps_handled_safely() -> None:
    bad_segs = [
        FakeWhisperSegment("neg", -0.1, 0.2),
        FakeWhisperSegment("nan", float("nan"), 0.4),
        FakeWhisperSegment("rev", 0.8, 0.5),
        FakeWhisperSegment("oob", 0.0, 5.0),
    ]
    collected = await collect_whisper_segments(iter(bad_segs), utterance_duration_sec=1.0)
    assert len(collected.malformed_metadata) == 4
    assert all(s.timestamp is None for s in collected.segments)

    strict_collected = await collect_whisper_segments(
        iter(bad_segs),
        utterance_duration_sec=1.0,
        limits=CollectorLimits(reject_invalid_timestamps=True),
    )
    assert not strict_collected.terminal_verified
    assert strict_collected.error_code == "ASR_INVALID_SEGMENT_TIMESTAMP"


@pytest.mark.asyncio
async def test_as47_missing_words_timestamps_language_remain_null() -> None:
    collected = await collect_whisper_segments(
        iter([FakeWhisperSegment("merhaba", start=None, end=None, words=None)]),
        info=None,
    )
    assert collected.segments[0].timestamp is None
    assert collected.segments[0].words == ()
    assert resolve_language_metadata(collected, requested_language="tr") is None


@pytest.mark.asyncio
async def test_as48_negative_avg_logprob_preserved_raw() -> None:
    collected = await collect_whisper_segments(
        iter([FakeWhisperSegment("merhaba", avg_logprob=-0.42, no_speech_prob=0.1)]),
    )
    conf = extract_confidence_estimate(collected)
    assert conf.estimate is not None
    assert conf.estimate.avg_logprob == pytest.approx(-0.42)


@pytest.mark.asyncio
async def test_as49_valid_no_speech_prob_and_malformed_nonfinite_score() -> None:
    collected = await collect_whisper_segments(
        iter([
            FakeWhisperSegment("a", avg_logprob=float("nan"), no_speech_prob=0.12),
            FakeWhisperSegment("b", avg_logprob=-0.30, no_speech_prob=1.5),
        ]),
    )
    conf = extract_confidence_estimate(collected)
    assert conf.estimate is not None
    assert conf.estimate.no_speech_prob == pytest.approx(0.12)
    assert conf.estimate.avg_logprob == pytest.approx(-0.30)
    assert any("invalid_avg_logprob" in m for m in conf.malformed_scores)
    assert any("invalid_no_speech_prob" in m for m in conf.malformed_scores)


@pytest.mark.asyncio
async def test_as50_no_calibrated_confidence_fabricated() -> None:
    collected = await collect_whisper_segments(
        iter([FakeWhisperSegment("merhaba", avg_logprob=-0.2, no_speech_prob=0.05)]),
    )
    conf = extract_confidence_estimate(collected)
    assert conf.estimate is not None
    assert conf.estimate.calibrated_prob is None
    assert conf.estimate.calibration_version is None


@pytest.mark.asyncio
async def test_as51_empty_or_whitespace_result_is_no_speech() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel(
        handler=lambda _a, _kw: (iter([FakeWhisperSegment("   \n\t ", 0.0, 0.5)]), SimpleNamespace(language="tr"))
    )
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)

    rec = await pipeline.process_utterance(_make_utterance(), FMT_16K_F32, session_ctx=ctx, pinned_config=_make_pinned_config())
    assert rec.result is not None
    assert rec.result.outcome == ASROutcome.NO_SPEECH
    assert not rec.result.is_write_eligible
    assert consumer.pending_count == 0


@pytest.mark.asyncio
async def test_as52_legacy_guards_reject_hallucination_to_no_speech() -> None:
    clock = FakeClock(1_000)
    for bad_seg in (
        FakeWhisperSegment("altyazı", 0.0, 0.5, no_speech_prob=0.55, avg_logprob=-0.2, compression_ratio=1.0),
        FakeWhisperSegment("altyazı", 0.0, 0.5, no_speech_prob=0.1, avg_logprob=-1.2, compression_ratio=1.0),
        FakeWhisperSegment("altyazı", 0.0, 0.5, no_speech_prob=0.1, avg_logprob=-0.2, compression_ratio=2.8),
    ):
        model = FakeWhisperModel(handler=lambda _a, _kw, s=bad_seg: (iter([s]), SimpleNamespace(language="tr")))
        pipeline, _, consumer, _ = _make_pipeline(clock, model)
        _, ctx, _, _ = await _open_session_with_turn(clock)
        rec = await pipeline.process_utterance(_make_utterance(), FMT_16K_F32, session_ctx=ctx, pinned_config=_make_pinned_config())
        assert rec.result is not None
        assert rec.result.outcome == ASROutcome.NO_SPEECH
        assert rec.result.raw_transcript == "altyazı"
        assert rec.legacy_projection.legacy_text == ""
        assert consumer.pending_count == 0


# =====================================================================
# AS53 - AS60: M05 Conservative Candidates & M01 Final Result Assembly
# =====================================================================


def test_as53_exact_approved_m05_entity_candidate_unverified() -> None:
    pinned = pin_lexicon_snapshot(_make_test_lexicon())
    raw = " Nisan kaş kay iki bin yirmi. "
    bundle = extract_conservative_candidates(pinned, raw)
    assert len(bundle.candidates) == 1
    cand = bundle.candidates[0]
    assert cand.canonical_value == "Qashqai"
    assert cand.raw_value == "kaş kay"
    assert cand.catalog_status == CatalogStatus.UNVERIFIED
    assert cand.confirmation_status == ConfirmationStatus.CANDIDATE


def test_as54_ambiguous_alias_bounded_no_silent_winner() -> None:
    pinned = pin_lexicon_snapshot(_make_test_lexicon())
    bundle = extract_conservative_candidates(pinned, "pasat istiyorum")
    assert len(bundle.candidates) == 1
    cand = bundle.candidates[0]
    assert cand.canonical_value is None
    assert set(cand.alternatives) == {"Passat", "Polo"}
    assert cand.catalog_status == CatalogStatus.UNVERIFIED
    assert cand.confirmation_status == ConfirmationStatus.CANDIDATE


def test_as55_unknown_vehicle_no_forced_correction() -> None:
    pinned = pin_lexicon_snapshot(_make_test_lexicon())
    bundle = extract_conservative_candidates(pinned, "xyzbilinmeyen araç")
    assert bundle.candidates == ()


def test_as56_protected_plate_vin_year_price_untouched() -> None:
    # Load full repo lexicon if available, or test lexicon
    lex = LexiconRegistry.from_default_sources()
    pinned = pin_lexicon_snapshot(lex)
    raw = "34 ABC 123 plakalı 2020 model 1250000 TL WVWZZZ3CZWE123456"
    bundle = extract_conservative_candidates(pinned, raw)
    # Protected plate, VIN, year, and price must never produce rewritten candidates
    for cand in bundle.candidates:
        assert "34 ABC 123" not in cand.raw_value
        assert "WVWZZZ3CZWE123456" not in cand.raw_value
        assert "1250000" not in cand.raw_value


def test_as57_unicode_span_offsets_exact_raw_substring() -> None:
    pinned = pin_lexicon_snapshot(_make_test_lexicon())
    raw = "İstanbul'da kaş kay bakımı"
    bundle = extract_conservative_candidates(pinned, raw)
    assert len(bundle.candidates) == 1
    span = bundle.candidates[0].source_span
    assert span is not None and span.representation == "RAW"
    assert raw[span.start : span.end_exclusive] == bundle.candidates[0].raw_value == "kaş kay"


def test_as58_m05_unavailable_snapshot_policy() -> None:
    pinned_opt = pin_lexicon_snapshot(None, strict_required=False)
    bundle = extract_conservative_candidates(pinned_opt, "kaş kay", strict_required=False)
    assert bundle.candidates == ()
    assert not bundle.snapshot_available
    assert bundle.lexicon_revision is None

    with pytest.raises(ASRConfigError) as exc:
        pin_lexicon_snapshot(None, strict_required=True)
    assert exc.value.code == "ASR_LEXICON_UNAVAILABLE"


@pytest.mark.asyncio
async def test_as59_m01_final_asr_result_and_evet_requires_confirmation() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel(
        handler=lambda _a, _kw: (iter([FakeWhisperSegment("evet", 0.0, 0.3)]), SimpleNamespace(language="tr"))
    )
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)

    rec = await pipeline.process_utterance(_make_utterance(), FMT_16K_F32, session_ctx=ctx, pinned_config=_make_pinned_config())
    assert rec.result is not None
    assert rec.result.status == ASRStatus.FINAL
    assert rec.result.outcome == ASROutcome.OK
    assert rec.result.raw_transcript == "evet"
    assert rec.result.normalized_transcript is None
    assert rec.result.canonical_transcript is None
    assert rec.result.stable_prefix is None
    assert rec.result.requires_confirmation is True
    assert consumer.pop_next_valid() is rec.result


def test_as60_caller_submitting_partial_as_final_rejected() -> None:
    clock = FakeClock(1_000)
    with pytest.raises(ASRInputError) as exc:
        build_final_asr_result(
            session_id="sess-1",
            utterance_id="utt-60",
            turn_id=1,
            sequence=0,
            clock=clock,
            outcome=ASROutcome.OK,
            raw_transcript="kısmi",
            status=ASRStatus.PARTIAL,
        )
    assert exc.value.code == "ASR_PARTIAL_NOT_ALLOWED_IN_F2A"


# =====================================================================
# AS61 - AS67: Cancellation, atomic fences & backpressure
# =====================================================================


@pytest.mark.asyncio
async def test_as61_cancel_before_admission_no_native_execution() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel()
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, turn_scope = await _open_session_with_turn(clock)
    turn_scope.request_cancel("user_cancelled")

    rec = await pipeline.process_utterance(_make_utterance(), FMT_16K_F32, session_ctx=ctx, pinned_config=_make_pinned_config())
    assert model.invocation_count == 0
    assert rec.delivery.delivery_status == ASRDeliveryStatus.FENCED_STALE
    assert consumer.pending_count == 0


@pytest.mark.asyncio
async def test_as62_cancel_queued_job_before_dispatch() -> None:
    clock = FakeClock(1_000)
    scheduler, _ = _make_scheduler(clock)
    model = FakeWhisperModel()
    engine = WhisperSchedulerEngine(scheduler, model_getter=lambda: model)
    scope = CancellationScope("turn:1", clock=clock)

    req = build_asr_resource_request(
        recognition_job_id="job-62",
        utterance_input=validate_and_materialize_utterance(_make_utterance(), FMT_16K_F32),
        pinned_config=_make_pinned_config(),
        pinned_lexicon=pin_lexicon_snapshot(None),
        hotwords=build_legacy_hotwords(catalog_enabled=False),
        cancellation_scope=scope,
        clock=clock,
    )
    assert engine.submit_to_queue(req) == ASRDispatchStatus.QUEUED
    scope.request_cancel("cancelled_in_queue")

    # M06 BoundedFairPriorityQueue prunes cancelled items on pop_next -> None & 0 provider calls
    exec_res = await engine.dispatch_next()
    assert exec_res is None
    assert scheduler.queue.cancelled_count >= 1
    assert model.invocation_count == 0


@pytest.mark.asyncio
async def test_as63_turn_superseded_while_native_running_fenced() -> None:
    clock = FakeClock(1_000)
    barrier = DeterministicBarrier()

    def _slow_handler(_audio: np.ndarray, _kwargs: dict[str, Any]) -> tuple[Any, Any]:
        async def _agen():
            await barrier.checkpoint("in_flight")
            yield FakeWhisperSegment("eski tur", 0.0, 0.3)
        return _agen(), SimpleNamespace(language="tr")

    model = FakeWhisperModel(handler=_slow_handler)
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)

    task = asyncio.create_task(pipeline.process_utterance(_make_utterance(turn_id=1), FMT_16K_F32, session_ctx=ctx, pinned_config=_make_pinned_config()))
    await barrier.wait_for_point("in_flight")
    await ctx.begin_turn()  # Turn 2 supersedes Turn 1
    barrier.release("in_flight")

    rec = await task
    assert rec.delivery.delivery_status == ASRDeliveryStatus.FENCED_STALE
    assert consumer.pending_count == 0


@pytest.mark.asyncio
async def test_as64_barrier_cancel_between_build_and_enqueue_atomic_reject() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel()
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, turn_scope = await _open_session_with_turn(clock)

    def _cancel_right_before_enqueue(_res: ASRResult) -> None:
        turn_scope.request_cancel("race_before_enqueue")

    rec = await pipeline.process_utterance(
        _make_utterance(),
        FMT_16K_F32,
        session_ctx=ctx,
        pinned_config=_make_pinned_config(),
        before_enqueue_hook=_cancel_right_before_enqueue,
    )
    assert rec.result is not None and rec.result.outcome == ASROutcome.OK
    assert rec.delivery.delivery_status == ASRDeliveryStatus.FENCED_STALE
    assert rec.delivery.admission_status == AdmissionStatus.CANCELED
    assert consumer.pending_count == 0


@pytest.mark.asyncio
async def test_as65_cancel_after_enqueue_before_consume_dropped() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel()
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)

    rec = await pipeline.process_utterance(_make_utterance(), FMT_16K_F32, session_ctx=ctx, pinned_config=_make_pinned_config())
    assert rec.delivery.delivery_status == ASRDeliveryStatus.DELIVERED
    assert consumer.pending_count == 1

    # Supersede turn before consumer pops
    await ctx.begin_turn()
    assert consumer.pop_next_valid() is None
    assert consumer.fenced_on_pop_count == 1


@pytest.mark.asyncio
async def test_as66_unrelated_playback_generation_cancel_does_not_revoke_asr() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel()
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, turn_ref, _ = await _open_session_with_turn(clock)
    await ctx.begin_generation(turn_ref)
    await ctx.commit_interrupt("barge_in_playback_only")

    rec = await pipeline.process_utterance(_make_utterance(turn_id=turn_ref.turn_id), FMT_16K_F32, session_ctx=ctx, pinned_config=_make_pinned_config())
    assert rec.result is not None and rec.result.outcome == ASROutcome.OK
    assert rec.delivery.delivery_status == ASRDeliveryStatus.DELIVERED
    assert consumer.pending_count == 1


@pytest.mark.asyncio
async def test_as67_full_or_closed_downstream_queue_and_session_close() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel()
    pipeline, _, consumer, _ = _make_pipeline(clock, model, consumer_max_items=1)
    reg, ctx, _, _ = await _open_session_with_turn(clock)
    cfg = _make_pinned_config()

    r1 = await pipeline.process_utterance(_make_utterance(utterance_id="u1"), FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    r2 = await pipeline.process_utterance(_make_utterance(utterance_id="u2"), FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    assert r1.delivery.delivery_status == ASRDeliveryStatus.DELIVERED
    assert r2.delivery.delivery_status == ASRDeliveryStatus.REJECTED_BACKPRESSURE

    consumer.close()
    r3 = await pipeline.process_utterance(_make_utterance(utterance_id="u3"), FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    assert r3.delivery.delivery_status == ASRDeliveryStatus.REJECTED_CLOSED

    await reg.close_session("sess-1")
    r4 = await pipeline.process_utterance(_make_utterance(utterance_id="u4"), FMT_16K_F32, session_ctx=ctx, pinned_config=cfg)
    assert r4.delivery.delivery_status == ASRDeliveryStatus.FENCED_STALE


# =====================================================================
# AS68 - AS72: Telemetry, PII hygiene, legacy parity & integrated slice
# =====================================================================


def test_as68_same_clock_and_cross_clock_timing_metadata() -> None:
    same = compute_clock_safe_delta_ms(
        1_000_000, "fake.clock", 15_000_000, "fake.clock", metric_name="f2.inference_ms"
    )
    assert same.status == MetricStatus.MEASURED
    assert same.value == pytest.approx(14.0)

    cross = compute_clock_safe_delta_ms(
        1_000_000, "fake.clock", 15_000_000, "process.monotonic", metric_name="f2.inference_ms"
    )
    assert cross.status == MetricStatus.UNKNOWN
    assert cross.value is None


@pytest.mark.asyncio
async def test_as69_m04_queue_overflow_or_exception_isolated() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel()
    pipeline, _, consumer, telemetry = _make_pipeline(clock, model, bus_max_lane=1)
    _, ctx, _, _ = await _open_session_with_turn(clock)

    # Pre-fill bus and inject a broken projection redactor
    def _boom(_s: str) -> tuple[str, dict[str, int]]:
        raise RuntimeError("telemetry failure")

    telemetry.projection = Projection(extra_allowlist=ASR_TELEMETRY_ALLOWLIST, redactor=_boom)
    rec = await pipeline.process_utterance(_make_utterance(), FMT_16K_F32, session_ctx=ctx, pinned_config=_make_pinned_config())
    assert rec.result is not None and rec.result.outcome == ASROutcome.OK
    assert rec.delivery.delivery_status == ASRDeliveryStatus.DELIVERED
    assert telemetry.dropped_events >= 1
    assert consumer.pop_next_valid() is not None


@pytest.mark.asyncio
async def test_as70_pii_sentinel_zero_leak_in_telemetry_and_errors() -> None:
    clock = FakeClock(1_000)
    pii_text = "Nisan kaş kay 34 XYZ 987 +90 532 555 44 33 sk-secret1234567890"
    model = FakeWhisperModel(
        handler=lambda _a, _kw: (iter([FakeWhisperSegment(pii_text, 0.0, 0.5)]), SimpleNamespace(language="tr"))
    )
    pipeline, _, _, telemetry = _make_pipeline(clock, model)
    sub = telemetry.event_bus.subscribe("audit")
    _, ctx, _, _ = await _open_session_with_turn(clock)

    rec = await pipeline.process_utterance(
        _make_utterance(),
        FMT_16K_F32,
        session_ctx=ctx,
        pinned_config=_make_pinned_config(catalog_hotwords=True),
        catalog_hotword_provider=lambda _cap: ["34 XYZ 987", "+90 532 555 44 33", "Qashqai"],
    )
    assert rec.result is not None and rec.result.raw_transcript == pii_text
    events = sub.drain()
    for env in events:
        payload = json.loads(metadata_to_json(env))
        assert PIISecretScanner.scan_object(payload) == []
        assert pii_text not in json.dumps(payload)


@pytest.mark.asyncio
async def test_as71_legacy_vs_strict_route_single_dispatch_and_parity() -> None:
    clock = FakeClock(1_000)
    model = FakeWhisperModel(
        handler=lambda _a, _kw: (
            iter([
                FakeWhisperSegment("  Merhaba  ", 0.0, 0.3, no_speech_prob=0.1),
                FakeWhisperSegment("  Kaşkai ", 0.3, 0.6, no_speech_prob=0.1),
            ]),
            SimpleNamespace(language="tr"),
        )
    )
    pipeline, _, consumer, _ = _make_pipeline(clock, model)
    _, ctx, _, _ = await _open_session_with_turn(clock)

    rec_legacy = await pipeline.process_utterance(
        _make_utterance(utterance_id="u-leg"),
        FMT_16K_F32,
        session_ctx=ctx,
        pinned_config=_make_pinned_config(route_mode=ASRRouteMode.LEGACY),
    )
    assert rec_legacy.legacy_projection.legacy_text == "Merhaba Kaşkai"
    assert rec_legacy.result is not None and rec_legacy.result.raw_transcript == "  Merhaba    Kaşkai "
    assert model.invocation_count == 1

    rec_strict = await pipeline.process_utterance(
        _make_utterance(utterance_id="u-str"),
        FMT_16K_F32,
        session_ctx=ctx,
        pinned_config=_make_pinned_config(route_mode=ASRRouteMode.STRICT),
    )
    assert rec_strict.result is not None and rec_strict.result.outcome == ASROutcome.OK
    assert model.invocation_count == 2
    assert consumer.pending_count == 2


@pytest.mark.asyncio
async def test_as72_integrated_f1_f2_f3_consumer_and_rollback_rehearsal() -> None:
    clock = FakeClock(10_000_000)
    r_base = resolve_configuration().snapshot
    r_strict = resolve_configuration(
        env={"STT_CATALOG_HOTWORDS": "true"},
    ).snapshot
    store = ConfigSnapshotStore(r_base)
    store.swap(r_strict)

    lex = _make_test_lexicon()
    model = FakeWhisperModel(
        handler=lambda _a, _kw: (
            iter([FakeWhisperSegment(" Nisan kaş kay ", 0.0, 0.6, avg_logprob=-0.22, no_speech_prob=0.04)]),
            SimpleNamespace(language="tr", language_probability=0.97),
        )
    )
    pipeline, scheduler, consumer, telemetry = _make_pipeline(clock, model)
    sub = telemetry.event_bus.subscribe("f2_obs")
    reg, ctx, _, _ = await _open_session_with_turn(clock)

    pinned_cfg = resolve_asr_config(store.current, route_mode=ASRRouteMode.STRICT)
    pcm = _make_pcm16_payload([1000, -1000] * 4000)
    utt = _make_utterance(start_sample=0, end_sample_exclusive=8000, payload=pcm)

    rec = await pipeline.process_utterance(
        utt,
        FMT_16K_PCM16,
        session_ctx=ctx,
        pinned_config=pinned_cfg,
        lexicon_registry=lex,
        catalog_hotword_provider=lambda _cap: ["Qashqai"],
    )
    assert rec.result is not None
    assert rec.result.status == ASRStatus.FINAL
    assert rec.result.outcome == ASROutcome.OK
    assert rec.result.raw_transcript == " Nisan kaş kay "
    assert rec.legacy_projection.legacy_text == "Nisan kaş kay"
    assert len(rec.result.entities) == 1
    assert rec.result.entities[0].canonical_value == "Qashqai"
    assert rec.result.entities[0].catalog_status == CatalogStatus.UNVERIFIED
    assert rec.result.entities[0].confirmation_status == ConfirmationStatus.CANDIDATE
    assert rec.result.requires_confirmation is True
    assert rec.delivery.delivery_status == ASRDeliveryStatus.DELIVERED

    f3_item = consumer.pop_next_valid()
    assert f3_item is rec.result

    # Rollback rehearsal: roll back config snapshot to baseline & drain lifecycle cleanly
    rolled = store.rollback()
    assert rolled.config_revision == r_base.config_revision
    assert store.rollback_count == 1

    await reg.close_session("sess-1")
    drain = await pipeline.lifecycle.shutdown_and_drain(scheduler=scheduler)
    assert drain.cleanup_status == CleanupStatus.COMPLETE
    assert len(sub.drain()) >= 2
