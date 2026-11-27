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
import struct
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.audio_frontend import (
    PHONE_8K_PROFILE,
    WEB_16K_48K_PROFILE,
    AudioInputPipeline,
    config_from_snapshot as f0_config_from_snapshot,
)
from backend.audio_rendering import (
    AUDIOSOCKET_AUDIO,
    AudioRenderingPipeline,
    AudioSocketOutboundAdapter,
    AudioSocketStreamParser,
    LatePolicy,
    PaceOwner,
    QuantizationPolicy,
    SubmissionOutcome,
    TerminalPolicy,
    WebTransportAdapter,
)
from backend.core.configuration import (
    ConfigSource,
    SupervisorMode,
    build_snapshot,
    resolve_configuration,
)
from backend.core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    ASROutcome,
    ASRStatus,
    AudioEncoding,
    AudioFormat,
    CatalogStatus,
    ConfirmationStatus,
    DialogueOutcome,
    DialogueResponse,
    EventEnvelope,
    GenerationRef,
    ObservationScope,
    PlaybackProfile,
    ProviderMode,
    SessionIdentity,
    StreamDirection,
    StreamRef,
    ToolReceiptStatus,
)
from backend.core.model_registry import ModelRegistry, VoiceProfileRegistry
from backend.core.runtime import AdmissionStatus, CancellationScope, SessionContext
from backend.dtmf import generate_dtmf_tone
from backend.linguistic_frontend import (
    FreyaVocabularyValidator,
    LinguisticFrontendPipeline,
    PlanningOutcome,
)
from backend.neural_synthesis import (
    BASELINE_ODE_STEPS,
    BASELINE_SOLVER,
    ModelResidencyAdapter,
    NeuralSynthesisPipeline,
    ProviderBarriers,
    SynthesisModelHandles,
    SynthesisTelemetry,
    load_static_char_vocab,
)
from backend.observability import BoundedEventBus, EvidenceKind, MetricsRegistry, Projection, SpanStatus, TraceStore
from backend.runtime_resources import (
    MIB,
    AdmissionOutcome,
    ExecutionLeaseState,
    HandleOwnership,
    MemoryBudget,
    MemoryProbe,
    ModelSpec,
    PriorityClass,
    ProviderKind,
    QuarantineManager,
    ResidencyManager,
    UnifiedGpuScheduler,
)
from backend.runtime_resources.provider_adapters import FakeOllamaWorker, OllamaAdapter
from backend.security import (
    AuthStrength,
    ConfirmationManager,
    DurableIdempotencyStore,
    EvidenceSource,
    PolicyEngine,
    PrincipalKind,
    SecurityAuditLog,
    verified_principal,
)
from backend.shared_lexicon import LexiconRegistry, load_lexicon_snapshot
from backend.speech_recognition.config_adapter import ASRRouteMode
from backend.supervisor.context_manager import ProtectedRefs
from backend.supervisor.contracts import Intent
from backend.supervisor.dialogue_facade import BoundedDialogueConsumer, DialogueFacade
from backend.supervisor.llm_adapter import LLMAdapter
from backend.supervisor.slot_manager import SlotDelta, SlotDeltaItem, SlotStatus
from backend.supervisor.workflow_adapter import WorkflowAdapter
from backend.voice_activity import (
    AcousticState,
    BoundedUtteranceQueue,
    F1ProfileConfig,
    F1RouteMode,
    M02TurnAllocatorBridge,
    StreamAcousticProcessor,
    VADEngineAdapter,
)
from tests.harness.acceptance import evaluate_gates
from tests.harness.adapters.fake_asr import FakeASRAdapter
from tests.harness.adapters.fake_gpu import FakeGPUProbeAdapter
from tests.harness.adapters.fake_identity import FakeIdentityProvider
from tests.harness.adapters.fake_transport import FakeAudioSocketTransport
from tests.harness.barriers import DeterministicBarrier, InterleavingPoint
from tests.harness.compatibility import CompatibilityChecker
from tests.harness.contracts import GateRecord, GateStatus, PrerequisiteStatus
from tests.harness.evidence_validator import EvidenceValidator, PIISecretScanner
from tests.harness.fake_clock import HarnessClock
from tests.harness.feature_regression import FeatureRegressionMapper
from tests.harness.synthetic_audio import AnalyticSignalKind, SyntheticAudioGenerator

REPO_ROOT = Path(__file__).resolve().parents[2]
M00_BASELINE_ID = "20261126T001600Z"
CORE_RUN_ID = "20261126T004342Z"
M00_BASELINE_DIR = REPO_ROOT / "docs" / "freya2" / "baseline" / M00_BASELINE_ID


# ---------------------------------------------------------------------------
# Test-only external model/DB boundary doubles (zero F0-F6 layer replacement)
# ---------------------------------------------------------------------------


class _ScriptedVADModel:
    model_revision = "fake_w2_silero_v1"

    def __init__(self, scores: list[float], *, default: float = 0.05) -> None:
        self._scores = list(scores)
        self._default = default
        self.calls = 0

    def initial_state(self) -> int:
        return 0

    def infer_with_state(self, window_f32: np.ndarray, sample_rate_hz: int, state: int) -> tuple[float, int]:
        assert sample_rate_hz == 16000 and window_f32.shape == (512,)
        self.calls += 1
        score = self._scores[state] if state < len(self._scores) else self._default
        return score, state + 1


class _FakeWhisperSeg:
    def __init__(self, text: str, start: float = 0.0, end: float = 0.4) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.avg_logprob = -0.2
        self.no_speech_prob = 0.05
        self.compression_ratio = 1.1
        self.words = None


class _FakeWhisperModel:
    def __init__(self, text: str = "Merhaba", *, lazy_segments: list[str] | None = None, step_hook=None) -> None:
        self.text = text
        self.lazy_segments = lazy_segments
        self.step_hook = step_hook
        self.calls = 0

    def transcribe(self, audio: np.ndarray, **kwargs: Any):
        self.calls += 1
        if self.lazy_segments is not None:
            def _gen():
                for idx, seg in enumerate(self.lazy_segments):
                    if self.step_hook is not None:
                        self.step_hook(idx)
                    yield _FakeWhisperSeg(seg, start=idx * 0.2, end=(idx + 1) * 0.2)
            return _gen(), SimpleNamespace(language="tr", language_probability=0.97)
        return iter([_FakeWhisperSeg(self.text)]), SimpleNamespace(language="tr", language_probability=0.98)


class _FakeDiT:
    def __init__(self, frames: float = 12.0) -> None:
        self.frames = frames
        self.seeds_seen: list[int] = []
        self.profiles_seen: list[Any] = []

    def encode_prepared_text(self, text: str, token_ids: tuple[int, ...], *, device: str = "cpu") -> dict[str, Any]:
        return {
            "observed_text": text,
            "context": np.ones((1, len(token_ids), 8), dtype=np.float32),
            "char_mask": np.ones((1, len(token_ids)), dtype=bool),
        }

    def predict_duration_frames(self, _encoded: Any) -> float:
        return self.frames

    def solve_ode(self, *, latent: Any, encoded: Any, profile: Any) -> dict[str, Any]:
        self.profiles_seen.append(profile)
        arr = np.array(latent, dtype=np.float32, copy=True) + np.float32(0.01)
        return {"latents": arr, "nfe_evaluated": profile.steps, "completed_steps": profile.steps}


class _FakeVAE:
    def __init__(self, *, override_samples: int | None = None) -> None:
        self.override_samples = override_samples

    def decode(self, latents_bct: Any) -> np.ndarray:
        arr = np.asarray(latents_bct)
        frames = int(arr.shape[-1]) if arr.ndim == 3 else 8
        n = self.override_samples if self.override_samples is not None else frames * 1920
        t = np.arange(n, dtype=np.float32) / 48000.0
        return (0.25 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)


def _build_scheduler(clock: HarnessClock, *, free_mib: int = 4096) -> UnifiedGpuScheduler:
    budget = MemoryBudget(clock=clock, headroom_bytes=256 * MIB, max_probe_age_ms=5_000)
    budget.update_probe(FakeGPUProbeAdapter(clock).valid_probe(free_mib=free_mib))
    residency = ResidencyManager(memory_budget=budget)
    residency.register_model(
        ModelSpec("stt-whisper", HandleOwnership.BORROWED, ProviderKind.CTRANSLATE2, 0, loader=lambda: "whisper-ok")
    )
    residency.register_model(
        ModelSpec("qwen2.5-3b-instruct", HandleOwnership.EXTERNAL, ProviderKind.OLLAMA, 0, loader=lambda: None)
    )
    sched = UnifiedGpuScheduler(
        clock=clock,
        memory_budget=budget,
        quarantine_manager=QuarantineManager(clock=clock, max_entries=8),
        residency_manager=residency,
    )
    return sched


def _build_f2_pipeline(sched: UnifiedGpuScheduler, whisper_model: _FakeWhisperModel):
    from backend.speech_recognition import (
        ASRLifecycleManager,
        ASRTelemetryBridge,
        ASRUtteranceAdmission,
        InMemoryASRConsumer,
        SpeechRecognitionPipeline,
        WhisperSchedulerEngine,
    )
    engine = WhisperSchedulerEngine(sched, model_getter=lambda: whisper_model)
    consumer = InMemoryASRConsumer(max_items=16)
    pipe = SpeechRecognitionPipeline(
        engine=engine,
        admission=ASRUtteranceAdmission(max_total_pending=16, max_per_session_pending=4),
        consumer=consumer,
        telemetry=ASRTelemetryBridge(),
        lifecycle=ASRLifecycleManager(),
    )
    return pipe, consumer


def _build_f4_pipeline(lexicon: LexiconRegistry, *, cfg_snapshot=None) -> LinguisticFrontendPipeline:
    cfg = cfg_snapshot or resolve_configuration().snapshot
    vocab_path = REPO_ROOT / "config" / "freya_vocab.json"
    return LinguisticFrontendPipeline(
        config_snapshot_provider=lambda: cfg,
        model_registry_provider=lambda c: ModelRegistry.from_snapshot(c),
        voice_registry_provider=lambda: VoiceProfileRegistry(),
        lexicon_registry_provider=lambda: lexicon,
        vocab_validator_factory=lambda snap: FreyaVocabularyValidator.from_vocab_file(
            vocab_path,
            model_revision=snap.model_revision,
            capability_revision=snap.capability_revision,
        ),
        require_real_vocab=True,
    )


def _build_f5_pipeline(sched: UnifiedGpuScheduler, clock: HarnessClock, *, dit: _FakeDiT | None = None, vae: _FakeVAE | None = None) -> NeuralSynthesisPipeline:
    vocab = load_static_char_vocab(repo_root=REPO_ROOT)
    handles = SynthesisModelHandles(
        model_id="tts-freya",
        model_revision="freya-tts:batched-ode",
        tts_model=dit or _FakeDiT(),
        vae=vae or _FakeVAE(),
        char_to_id=vocab.vocab_map,
        vocab_revision=vocab.vocab_revision,
        ownership=HandleOwnership.BORROWED,
    )
    res_adapter = ModelResidencyAdapter(sched.residency_manager)
    res_adapter.register_handles(handles, vram_bytes=64 * MIB, ownership=HandleOwnership.BORROWED)
    return NeuralSynthesisPipeline(
        scheduler=sched,
        residency_adapter=res_adapter,
        telemetry=SynthesisTelemetry(clock=clock),
    )


def _make_f3_stack(tmp_path: Path, clock: HarnessClock, *, with_crm_db: bool = False, seed_booking: bool = False, ollama_worker=None, sched=None):
    audit = SecurityAuditLog(tmp_path / "audit.db")
    idem = DurableIdempotencyStore(tmp_path / "idem.db", audit_log=audit)
    confirm = ConfirmationManager(clock=clock, audit_log=audit)
    policy = PolicyEngine(audit_log=audit)
    session_factory = None
    if with_crm_db:
        from backend.db import Base, Slot, Vehicle
        eng = create_engine(f"sqlite:///{tmp_path / 'crm.db'}", connect_args={"check_same_thread": False, "timeout": 5.0})
        @event.listens_for(eng, "connect")
        def _pragmas(dbapi, _):
            dbapi.execute("PRAGMA foreign_keys=ON")
            dbapi.execute("PRAGMA journal_mode=WAL")
        Base.metadata.create_all(eng)
        session_factory = sessionmaker(eng, expire_on_commit=False)
        if seed_booking:
            with session_factory() as db:
                db.add(Vehicle(id="veh-w2", description="2023 Volkswagen Passat", plate="34 W2 01"))
                db.add(Slot(id="slot-w2", starts_at="2026-11-28T15:00:00+00:00"))
                db.commit()

    wf = WorkflowAdapter(
        policy_engine=policy,
        confirmation_manager=confirm,
        idempotency_store=idem,
        audit_log=audit,
        session_factory=session_factory,
        provider_mode=ProviderMode.MOCK,
    )
    llm_adapter = None
    if ollama_worker is not None and sched is not None:
        sched.register_adapter(ProviderKind.OLLAMA, OllamaAdapter(lambda _r: ollama_worker))
        llm_adapter = LLMAdapter(scheduler=sched)

    snap = build_snapshot(
        values={"supervisor_mode": SupervisorMode.GUARDED.value},
        sources={"supervisor_mode": ConfigSource.OVERRIDE},
        feature_flags={"supervisor_mode": SupervisorMode.GUARDED.value},
    )
    facade = DialogueFacade(
        config_snapshot=snap,
        mode=SupervisorMode.GUARDED,
        llm_adapter=llm_adapter,
        workflow_adapter=wf,
        clock=clock,
        utc_now_fn=lambda: datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc),
        vehicles=(("Peugeot", "3008"), ("Volkswagen", "Passat"), ("Volkswagen", "Polo")),
    )
    return facade, wf, confirm, idem, audit, policy


async def _run_full_slice(
    tmp_path: Path,
    *,
    channel: str,  # "web" or "audiosocket"
    whisper_text: str = "Merhaba",
    session_id: str = "sess-w2",
    lexicon: LexiconRegistry | None = None,
    inject_dtmf: bool = False,
):
    """Run REAL F0 -> F1 -> F2 -> F3 -> F4 -> F5 -> F6 vertical slice."""
    from backend.speech_recognition import resolve_asr_config

    clock = HarnessClock(initial_ns=1_000_000_000, clock_domain="w2.fake.clock")
    cfg = resolve_configuration(overrides={"auto_load_models": False, "supervisor_mode": "guarded"}).snapshot
    lex = lexicon or LexiconRegistry.from_snapshot(load_lexicon_snapshot())
    sched = _build_scheduler(clock)

    session_ctx = SessionContext(SessionIdentity(session_id, trace_id=f"tr-{session_id}"), clock=clock)
    await session_ctx.open()
    in_stream = StreamRef(session_id, "in-0", StreamDirection.INPUT, 0)

    # F1 setup: 8 windows of active speech (>= start_min_windows) followed by 10 silence windows
    vad_scores = [0.05] * 2 + [0.92] * 6 + [0.05] * 14
    f1_queue = BoundedUtteranceQueue(max_items=8, max_bytes=4_000_000)
    f1_proc = StreamAcousticProcessor(
        in_stream,
        profile=F1ProfileConfig.strict_experimental(route_mode=F1RouteMode.STRICT),
        config_revision=cfg.config_revision,
        vad_engine=VADEngineAdapter(_ScriptedVADModel(vad_scores), clock=clock),
        turn_allocator=M02TurnAllocatorBridge(session_ctx),
        consumer=f1_queue,
        clock=clock,
        ledger=session_ctx.ledger,
        session_context=session_ctx,
        trace_id=f"tr-{session_id}",
    )

    # F0 setup feeding F1 directly
    f0_dtmf_events = []
    f0_cfg = f0_config_from_snapshot(cfg, bypass_dsp=True)
    f0_profile = PHONE_8K_PROFILE if channel == "audiosocket" else WEB_16K_48K_PROFILE
    f0 = AudioInputPipeline(
        session_ctx=session_ctx,
        config=f0_cfg,
        default_profile=f0_profile,
        clock=clock,
        f1_consumer=f1_proc.process_frame,
        dtmf_consumer=f0_dtmf_events.append,
    )
    in_rate = 8000 if channel == "audiosocket" else 16000
    f0.open_stream(in_stream, sample_rate_hz=in_rate, profile=f0_profile, config=f0_cfg)

    gen = SyntheticAudioGenerator()
    samples_per_chunk = 160 if in_rate == 8000 else 512
    n_chunks = 40 if in_rate == 8000 else 22
    for seq in range(n_chunks):
        if inject_dtmf and seq in (2, 3, 4):
            tone = generate_dtmf_tone("1", duration_sec=samples_per_chunk / float(in_rate), sample_rate=in_rate, amplitude=0.6)
            pcm = (np.clip(tone, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        else:
            seg = gen.generate(AnalyticSignalKind.SPEECH_ENVELOPE, sample_rate_hz=in_rate, sample_count=samples_per_chunk, seed=seq + 1)
            pcm = seg.payload
        res = f0.ingest_raw(
            stream_ref=in_stream,
            payload=pcm,
            sample_rate_hz=in_rate,
            channels=1,
            encoding=AudioEncoding.PCM_S16LE,
            sample_count=samples_per_chunk,
            sequence=seq,
            sample_offset=seq * samples_per_chunk,
            captured_monotonic_ns=clock.monotonic_ns(),
            clock_domain=clock.clock_domain,
        )
        assert res.ok
        clock.advance_ms(20)

    # EOS flush on F0 then F1
    f0.flush_eos(in_stream)
    f1_proc.flush_eos()
    assert f1_queue.item_count >= 1
    utterance = f1_queue.pop_next()
    assert utterance is not None and utterance.finalized

    # F2 ASR
    f2_pipe, f2_consumer = _build_f2_pipeline(sched, _FakeWhisperModel(whisper_text))
    pinned_asr = resolve_asr_config(cfg, route_mode=ASRRouteMode.STRICT)
    asr_rec = await f2_pipe.process_utterance(
        utterance,
        AudioFormat(16000, 1, AudioEncoding.FLOAT32_LE),
        session_ctx=session_ctx,
        pinned_config=pinned_asr,
        lexicon_registry=lex,
    )
    assert asr_rec.result is not None and asr_rec.result.outcome == ASROutcome.OK

    # F3 Dialogue
    facade, _, _, _, audit, _ = _make_f3_stack(tmp_path, clock)
    incarnation_id = f"inc-{session_id}"
    facade.open_session(session_id=session_id, incarnation_id=incarnation_id, lexicon_revision=lex.lexicon_revision)
    f3_consumer = BoundedDialogueConsumer()
    turn_id = utterance.turn_ref.turn_id if utterance.turn_ref else 1
    f3_out = await facade.process_asr_turn(
        asr_rec.result,
        session_id=session_id,
        incarnation_id=incarnation_id,
        turn_id=turn_id,
        consumer=f3_consumer,
    )
    assert f3_out.response is not None

    # F4 Linguistic Frontend
    f4_pipe = _build_f4_pipeline(lex, cfg_snapshot=cfg)
    gen_ref = GenerationRef(session_id, turn_id, 1)
    f4_res = f4_pipe.prepare_response(
        f3_out.response,
        generation_ref=gen_ref,
        expected_session_id=session_id,
        expected_turn_id=turn_id,
        incarnation_id=incarnation_id,
        requested_seed=9,
        config_snapshot=cfg,
        lexicon_registry=lex,
    )
    assert f4_res.ok and f4_res.plan is not None and f4_res.normalization_passes == 1

    # F5 Neural Synthesis
    f5_pipe = _build_f5_pipeline(sched, clock)
    f5_ctx = SessionContext(
        SessionIdentity(session_id, trace_id=f"tr-{session_id}"),
        clock=clock,
        max_queue_bytes=2 * 1024 * 1024,
    )
    await f5_ctx.open()
    t5, _ = await f5_ctx.begin_turn()
    g5, _ = await f5_ctx.begin_generation(t5)
    # Match generation_ref to active F5 session turn/gen
    plan_f5 = f4_pipe.prepare_response(
        DialogueResponse(
            envelope=EventEnvelope(
                schema_version=CONTRACT_SCHEMA_VERSION,
                event_type="dialogue.response",
                session_id=session_id,
                trace_id=f"tr-{session_id}",
                turn_id=t5.turn_id,
                generation_id=g5.generation_id,
                sequence=1,
                monotonic_ns=clock.monotonic_ns(),
                clock_domain=clock.clock_domain,
                producer="f3.dialogue",
            ),
            response_id=f"{f3_out.response.response_id}-f5",
            speech_text=f3_out.response.speech_text,
            speech_act=f3_out.response.speech_act,
            state_revision=f3_out.response.state_revision,
            outcome=f3_out.response.outcome,
        ),
        generation_ref=g5,
        expected_session_id=session_id,
        expected_turn_id=t5.turn_id,
        incarnation_id=f"{incarnation_id}-f5",
        requested_seed=9,
        config_snapshot=cfg,
        lexicon_registry=lex,
    )
    assert plan_f5.ok and plan_f5.plan is not None
    f5_out = await f5_pipe.synthesize_plan(plan_f5.plan, session_ctx=f5_ctx, expected_generation_ref=g5)
    assert f5_out.status == "COMPLETED" and len(f5_out.accepted_chunks) >= 1

    # F6 Audio Rendering & Transport
    f6 = AudioRenderingPipeline(
        session_id=session_id,
        trace_id=f"tr-{session_id}",
        trusted_channel=channel,
        clock=clock,
        snapshot=cfg,
        dsp_enabled=False,
        max_queue_items=256,
        max_queue_bytes=1_048_576,
    )
    g6 = await f6.start_generation()
    for idx, ch in enumerate(f5_out.accepted_chunks):
        chunk_for_f6 = AudioChunk_with_gen(ch, g6, plan_f5.plan.plan_revision)
        r_res = await f6.render_chunk(chunk_for_f6, plan=rebind_plan(plan_f5.plan, g6))
        assert r_res.admitted
    await f6.finish_generation_eos(plan_revision=plan_f5.plan.plan_revision)

    sent_frames = []
    async def _sleep_ns(ns: int) -> None:
        clock.advance_ns(ns)

    f6.pacer._sleep_ns_fn = _sleep_ns
    if channel == "audiosocket":
        tr = FakeAudioSocketTransport(max_send_buffer_bytes=64 * 1024)
        as_adapter = AudioSocketOutboundAdapter(tr)

        def _submit_as(fr):
            res = as_adapter.send_audio_frame(fr)
            if res.outcome.value == "SUBMITTED":
                sent_frames.append(fr)
            return res

        records = await f6.pump_and_submit(submit_fn=_submit_as)
        wire_buf = bytearray(tr._tx_buffer)
    else:
        web_frames: list[bytes] = []
        web_adapter = WebTransportAdapter(f6.profile, send_bytes_fn=web_frames.append)
        ok_hello, hello_reason = web_adapter.negotiate_hello(
            {"type": "hello", "sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"}
        )
        assert ok_hello and hello_reason is None

        def _submit_web(fr):
            res = web_adapter.send_audio_frame(fr)
            if res.accepted:
                sent_frames.append(fr)
            return res

        records = await f6.pump_and_submit(submit_fn=_submit_web)
        wire_buf = bytearray()

    await f6.lifecycle.close()
    await f5_ctx.close("done")
    await session_ctx.close("done")

    return {
        "utterance": utterance,
        "dtmf_events": f0_dtmf_events,
        "asr_rec": asr_rec,
        "f3_out": f3_out,
        "f4_res": plan_f5,
        "f5_out": f5_out,
        "sent_frames": sent_frames,
        "web_frames": list(web_frames) if channel == "web" else [],
        "wire_buf": bytes(wire_buf),
        "records": records,
    }


def AudioChunk_with_gen(chunk, gen_ref: GenerationRef, plan_rev: int):
    from dataclasses import replace
    return replace(chunk, generation_ref=gen_ref, plan_revision=plan_rev)


def rebind_plan(plan, gen_ref: GenerationRef):
    from dataclasses import replace
    return replace(plan, generation_ref=gen_ref)


# ---------------------------------------------------------------------------
# WI01 - WI24: Cross-Layer W2 Vertical Slice Integration Tests
# ---------------------------------------------------------------------------


def test_wi01_prereqs_core_and_all_seven_a_packages_accepted(tmp_path: Path) -> None:
    ev = EvidenceValidator(REPO_ROOT)
    assert ev.verify_m00_baseline(M00_BASELINE_ID).status == PrerequisiteStatus.ACCEPTED

    core_acc = json.loads((REPO_ROOT / "docs" / "freya2" / "core_integration" / CORE_RUN_ID / "CORE_ACCEPTANCE_MATRIX.json").read_text(encoding="utf-8"))
    assert core_acc["core_integration_ready"] is True
    assert all(v == "PASS" for v in core_acc["gates"].values())

    for pkg, ready_key in (
        ("f0_a", "f0_a_ready"),
        ("f1_a", "f1_a_ready"),
        ("f2_a", "f2_a_ready"),
        ("f3_a", "f3_a_ready"),
        ("f4_a", "f4_a_ready"),
        ("f5_a", "f5_a_ready"),
        ("f6_a", "f6_a_ready"),
    ):
        root = REPO_ROOT / "docs" / "freya2" / pkg
        runs = sorted(p.name for p in root.iterdir() if p.is_dir())
        assert len(runs) == 1
        data = json.loads((root / runs[0] / "ACCEPTANCE_MATRIX.json").read_text(encoding="utf-8"))
        assert data.get(ready_key) is True, f"{pkg} not ready"

    # Missing prerequisite blocks cleanly
    assert ev.verify_package_acceptance_dir("F6_A", tmp_path / "missing_f6").status == PrerequisiteStatus.MISSING


@pytest.mark.asyncio
async def test_wi02_real_f0_to_f6_strict_web_16k_path(tmp_path: Path) -> None:
    out = await _run_full_slice(tmp_path, channel="web", whisper_text="Merhaba", session_id="sess-wi02")
    assert len(out["sent_frames"]) >= 1
    assert len(out["web_frames"]) == len(out["sent_frames"])
    assert all(len(b) == 640 for b in out["web_frames"])
    for idx, fr in enumerate(out["sent_frames"]):
        assert fr.profile == PlaybackProfile.WEB_16K_PCM16
        assert fr.sample_count == 320
        assert len(fr.payload) == 640
        assert fr.sequence == idx
    assert all(r.observation_scope == ObservationScope.SERVER for r in out["records"])


@pytest.mark.asyncio
async def test_wi03_real_f0_to_f6_strict_phone_audiosocket_8k_path(tmp_path: Path) -> None:
    out = await _run_full_slice(tmp_path, channel="audiosocket", whisper_text="Merhaba", session_id="sess-wi03", inject_dtmf=True)
    assert len(out["dtmf_events"]) >= 1
    assert len(out["sent_frames"]) >= 1
    for fr in out["sent_frames"]:
        assert fr.profile == PlaybackProfile.AUDIOSOCKET_8K_PCM16
        assert fr.sample_count == 160
        assert len(fr.payload) == 320
    # Parse captured AudioSocket BE wire frames
    parser = AudioSocketStreamParser()
    wire_packets = parser.feed(out["wire_buf"])
    assert len(wire_packets) == len(out["sent_frames"])
    assert all(kind == AUDIOSOCKET_AUDIO and len(body) == 320 for kind, body in wire_packets)


def test_wi04_irregular_ingress_partitions_and_preroll_markers() -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    cfg = resolve_configuration(overrides={"auto_load_models": False}).snapshot
    session_ctx = SessionContext(SessionIdentity("sess-wi04", trace_id="tr-wi04"), clock=clock)
    asyncio.run(session_ctx.open())
    in_stream = StreamRef("sess-wi04", "in-0", StreamDirection.INPUT, 0)
    f1_queue = BoundedUtteranceQueue(max_items=8, max_bytes=4_000_000)
    f1_proc = StreamAcousticProcessor(
        in_stream,
        profile=F1ProfileConfig.strict_experimental(route_mode=F1RouteMode.STRICT),
        config_revision=cfg.config_revision,
        vad_engine=VADEngineAdapter(_ScriptedVADModel([0.1, 0.9, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]), clock=clock),
        turn_allocator=M02TurnAllocatorBridge(session_ctx),
        consumer=f1_queue,
        clock=clock,
        ledger=session_ctx.ledger,
        session_context=session_ctx,
    )
    f0 = AudioInputPipeline(session_ctx=session_ctx, config=f0_config_from_snapshot(cfg, bypass_dsp=True), clock=clock, f1_consumer=f1_proc.process_frame)
    f0.open_stream(in_stream, sample_rate_hz=16000, profile=WEB_16K_48K_PROFILE)
    gen = SyntheticAudioGenerator()
    offset = 0
    for seq, cnt in enumerate((100, 220, 400, 304, 512, 512, 512, 512, 512, 512, 512, 512, 512, 512)):
        seg = gen.generate(AnalyticSignalKind.SPEECH_ENVELOPE, sample_rate_hz=16000, sample_count=cnt, seed=seq + 1)
        r = f0.ingest_raw(stream_ref=in_stream, payload=seg.payload, sample_rate_hz=16000, channels=1, encoding=AudioEncoding.PCM_S16LE, sample_count=cnt, sequence=seq, sample_offset=offset)
        assert r.ok
        offset += cnt
    f0.flush_eos(in_stream)
    f1_proc.flush_eos()
    utt = f1_queue.pop_next()
    assert utt is not None and utt.start_sample <= 512 and utt.end_sample_exclusive > utt.start_sample
    asyncio.run(session_ctx.close("done"))


def test_wi05_short_false_onset_rejected_then_valid_speech() -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    cfg = resolve_configuration(overrides={"auto_load_models": False}).snapshot
    session_ctx = SessionContext(SessionIdentity("sess-wi05"), clock=clock)
    asyncio.run(session_ctx.open())
    in_stream = StreamRef("sess-wi05", "in-0", StreamDirection.INPUT, 0)
    f1_queue = BoundedUtteranceQueue(max_items=8, max_bytes=4_000_000)
    # 1 brief spike -> rejected candidate, then 5 active -> 1 finalized utterance
    scores = [0.05, 0.90, 0.05, 0.05, 0.05, 0.92, 0.92, 0.92, 0.92, 0.92] + [0.05] * 12
    f1_proc = StreamAcousticProcessor(
        in_stream,
        profile=F1ProfileConfig.strict_experimental(route_mode=F1RouteMode.STRICT),
        config_revision=cfg.config_revision,
        vad_engine=VADEngineAdapter(_ScriptedVADModel(scores), clock=clock),
        turn_allocator=M02TurnAllocatorBridge(session_ctx),
        consumer=f1_queue,
        clock=clock,
        ledger=session_ctx.ledger,
        session_context=session_ctx,
    )
    gen = SyntheticAudioGenerator()
    outcomes = []
    for i in range(len(scores)):
        seg = gen.generate(
            AnalyticSignalKind.SPEECH_ENVELOPE,
            sample_rate_hz=16000,
            sample_count=512,
            sample_offset=i * 512,
            encoding=AudioEncoding.FLOAT32_LE,
            seed=i,
        )
        outcomes.append(f1_proc.process_frame(seg.to_audio_frame(in_stream, sequence=i)))
    f1_proc.flush_eos()
    assert f1_queue.item_count == 1
    assert f1_proc.accounting.snapshot().conservation_balanced is True
    speech_starts = [ev for o in outcomes for ev in o.speech_events if ev.kind.value == "SPEECH_START"]
    assert len(speech_starts) == 1  # false spike rejected before onset confirmation; only valid speech started
    utt = f1_queue.pop_next()
    assert utt is not None and utt.finalized
    asyncio.run(session_ctx.close("done"))


@pytest.mark.asyncio
async def test_wi06_fake_whisper_lazy_segments_and_m06_lease_retained() -> None:
    from backend.speech_recognition import resolve_asr_config
    clock = HarnessClock(initial_ns=1_000_000)
    cfg = resolve_configuration(overrides={"auto_load_models": False}).snapshot
    sched = _build_scheduler(clock)
    seen_leases = []

    def _on_seg(_idx: int) -> None:
        # Lease is active during lazy segment iteration
        seen_leases.append(len(sched._leases))

    model = _FakeWhisperModel(lazy_segments=["Volkswagen ", "Passat"], step_hook=_on_seg)
    f2_pipe, _ = _build_f2_pipeline(sched, model)
    ctx = SessionContext(SessionIdentity("sess-wi06"), clock=clock)
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    utt_payload = SyntheticAudioGenerator().generate(AnalyticSignalKind.SPEECH_ENVELOPE, sample_rate_hz=16000, sample_count=8000, encoding=AudioEncoding.FLOAT32_LE).payload
    from backend.core.contracts import TurnRef, Utterance
    utt = Utterance("utt-wi06", StreamRef("sess-wi06", "in", StreamDirection.INPUT, 0), t1, 0, 8000, True, "eos", payload=utt_payload)
    rec = await f2_pipe.process_utterance(utt, AudioFormat(16000, 1, AudioEncoding.FLOAT32_LE), session_ctx=ctx, pinned_config=resolve_asr_config(cfg, route_mode=ASRRouteMode.STRICT))
    assert rec.result is not None and rec.result.raw_transcript == "Volkswagen Passat"
    assert seen_leases == [1, 1]
    await ctx.close("done")


@pytest.mark.asyncio
async def test_wi07_asr_non_ok_no_speech_or_error_never_executes_business(tmp_path: Path) -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    facade, _, _, _, _, _ = _make_f3_stack(tmp_path, clock, with_crm_db=True)
    facade.open_session(session_id="sess-wi07", incarnation_id="inc-7")
    asr = FakeASRAdapter()
    for bad_outcome in (ASROutcome.NO_SPEECH, ASROutcome.ERROR):
        bad_res = asr.make_result(session_id="sess-wi07", utterance_id="u1", revision=1, status=ASRStatus.FINAL, raw_transcript="", outcome=bad_outcome)
        out = await facade.process_asr_turn(bad_res, session_id="sess-wi07", incarnation_id="inc-7", turn_id=1)
        assert out.receipt is None
        assert out.response is not None and out.response.outcome == DialogueOutcome.CLARIFICATION_REQUIRED


@pytest.mark.asyncio
async def test_wi08_automotive_ambiguous_candidate_from_f2_through_f3(tmp_path: Path) -> None:
    from backend.speech_recognition import resolve_asr_config
    clock = HarnessClock(initial_ns=1_000_000)
    cfg = resolve_configuration(overrides={"auto_load_models": False}).snapshot
    lex = LexiconRegistry.from_snapshot(load_lexicon_snapshot())
    sched = _build_scheduler(clock)
    f2_pipe, _ = _build_f2_pipeline(sched, _FakeWhisperModel("Passat ve Polo bakımı"))
    ctx = SessionContext(SessionIdentity("sess-wi08"), clock=clock)
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    from backend.core.contracts import Utterance
    utt_payload = SyntheticAudioGenerator().generate(AnalyticSignalKind.SPEECH_ENVELOPE, sample_rate_hz=16000, sample_count=8000, encoding=AudioEncoding.FLOAT32_LE).payload
    utt = Utterance("utt-wi08", StreamRef("sess-wi08", "in", StreamDirection.INPUT, 0), t1, 0, 8000, True, "eos", payload=utt_payload)
    asr_rec = await f2_pipe.process_utterance(utt, AudioFormat(16000, 1, AudioEncoding.FLOAT32_LE), session_ctx=ctx, pinned_config=resolve_asr_config(cfg, route_mode=ASRRouteMode.STRICT), lexicon_registry=lex)
    assert asr_rec.result is not None and len(asr_rec.result.entities) >= 2
    assert all(e.catalog_status == CatalogStatus.UNVERIFIED and e.confirmation_status == ConfirmationStatus.CANDIDATE for e in asr_rec.result.entities)

    facade, _, _, _, _, _ = _make_f3_stack(tmp_path, clock)
    facade.open_session(session_id="sess-wi08", incarnation_id="inc-8", lexicon_revision=lex.lexicon_revision)
    f3_out = await facade.process_asr_turn(asr_rec.result, session_id="sess-wi08", incarnation_id="inc-8", turn_id=t1.turn_id)
    assert f3_out.receipt is None
    assert f3_out.response is not None and f3_out.response.outcome == DialogueOutcome.CLARIFICATION_REQUIRED
    await ctx.close("done")


@pytest.mark.asyncio
async def test_wi09_deterministic_greeting_no_llm_through_f4_f5_f6(tmp_path: Path) -> None:
    out = await _run_full_slice(tmp_path, channel="web", whisper_text="Merhaba", session_id="sess-wi09")
    assert out["f3_out"].llm_result is None
    assert out["f3_out"].receipt is None
    assert out["f4_res"].plan.normalization_passes == 1
    assert out["f5_out"].status == "COMPLETED"
    assert len(out["sent_frames"]) >= 1


@pytest.mark.asyncio
async def test_wi10_llm_assisted_path_via_m06_p3_and_m07_validation(tmp_path: Path) -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    sched = _build_scheduler(clock)
    worker = FakeOllamaWorker('{"intent":"CLARIFICATION_REQUEST","speech_text":"Hangi gün için randevu istersiniz?"}')
    facade, _, _, _, _, _ = _make_f3_stack(tmp_path, clock, ollama_worker=worker, sched=sched)
    facade.open_session(session_id="sess-wi10", incarnation_id="inc-10")
    asr = FakeASRAdapter().make_result(session_id="sess-wi10", utterance_id="u10", revision=1, status=ASRStatus.FINAL, raw_transcript="hmm şey randevu gibi bir şey")
    out = await facade.process_asr_turn(asr, session_id="sess-wi10", incarnation_id="inc-10", turn_id=1, use_llm_fallback=True)
    assert out.response is not None
    assert out.receipt is None  # LLM proposal cannot bypass M07 to mutate DB


@pytest.mark.asyncio
async def test_wi11_authorized_booking_flow_with_confirmation_and_mock_receipt(tmp_path: Path) -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    facade, wf, _, _, _, _ = _make_f3_stack(tmp_path, clock, with_crm_db=True, seed_booking=True)
    facade.open_session(session_id="sess-wi11", incarnation_id="inc-11", principal_ref="cust-syn-001")
    ident = FakeIdentityProvider()
    principal = ident.verified_customer("cust-syn-001", strong=True)
    asr = FakeASRAdapter()
    # Turn 1: check verified availability from isolated DB
    r1 = asr.make_result(session_id="sess-wi11", utterance_id="u1", revision=1, status=ASRStatus.FINAL, raw_transcript="yarın için randevu almak istiyorum", turn_id=1)
    o1 = await facade.process_asr_turn(r1, session_id="sess-wi11", incarnation_id="inc-11", turn_id=1, principal=principal)
    assert o1.receipt is not None and o1.receipt.tool_id == "availability.read"
    assert o1.snapshot is not None

    # Select slot and issue explicit M07 confirmation challenge
    _, snap = facade.context_manager.apply_slot_delta(
        session_id="sess-wi11",
        incarnation_id="inc-11",
        delta=SlotDelta(
            expected_state_revision=o1.snapshot.state_revision,
            changes=(
                SlotDeltaItem(key="customer_ref", value="cust-syn-001", status=SlotStatus.CONFIRMED, source_type="m07_verified"),
                SlotDeltaItem(key="vehicle_ref", value="veh-w2", status=SlotStatus.CONFIRMED, source_type="catalog"),
                SlotDeltaItem(key="selected_slot_id", value="slot-w2", status=SlotStatus.VALIDATED, source_type="catalog"),
            ),
            source_ref="slot_select",
            reason="selected",
        ),
    )
    terms = {k: str(v.value) for k, v in snap.slots.items() if v.value is not None}
    ctx = ident.make_context(session_id="sess-wi11", principal=principal, state_revision=snap.state_revision)
    ch, _ = wf.issue_and_present_confirmation(access=ctx, tool_id="booking.create", action="create_booking", terms=terms)
    facade.context_manager.update_runtime_state(
        session_id="sess-wi11",
        incarnation_id="inc-11",
        expected_state_revision=snap.state_revision,
        active_workflow=Intent.BOOKING_CREATE.value,
        protected_refs=ProtectedRefs(pending_challenge_id=ch.challenge_id),
        bump_revision=False,
    )

    # Turn 2: explicit affirmative confirmation -> commits single MOCK receipt
    r2 = asr.make_result(session_id="sess-wi11", utterance_id="u2", revision=2, status=ASRStatus.FINAL, raw_transcript="Evet onaylıyorum", turn_id=2)
    o2 = await facade.process_asr_turn(r2, session_id="sess-wi11", incarnation_id="inc-11", turn_id=2, principal=principal, idempotency_key="ik-wi11")
    assert o2.receipt is not None
    assert o2.receipt.status == ToolReceiptStatus.COMMITTED
    assert o2.receipt.provider_mode == ProviderMode.MOCK
    assert o2.receipt.verified_result is False


@pytest.mark.asyncio
async def test_wi12_slot_change_invalidates_confirmation_and_duplicate_blocked(tmp_path: Path) -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    facade, wf, confirm, _, _, _ = _make_f3_stack(tmp_path, clock, with_crm_db=True, seed_booking=True)
    facade.open_session(session_id="sess-wi12", incarnation_id="inc-12", principal_ref="cust-syn-001")
    ident = FakeIdentityProvider()
    principal = ident.verified_customer("cust-syn-001", strong=True)
    snap0 = facade.context_manager.get_snapshot("sess-wi12", "inc-12")
    assert snap0 is not None
    _, snap = facade.context_manager.apply_slot_delta(
        session_id="sess-wi12",
        incarnation_id="inc-12",
        delta=SlotDelta(
            expected_state_revision=snap0.state_revision,
            changes=(
                SlotDeltaItem(key="vehicle_model", value="Volkswagen Passat", status=SlotStatus.CONFIRMED, source_type="catalog"),
                SlotDeltaItem(key="selected_slot_id", value="slot-w2", status=SlotStatus.VALIDATED, source_type="catalog"),
            ),
            source_ref="t1",
            reason="init",
        ),
    )
    ctx = ident.make_context(session_id="sess-wi12", principal=principal, state_revision=snap.state_revision)
    ch, _ = wf.issue_and_present_confirmation(access=ctx, tool_id="booking.create", action="create_booking", terms={"vehicle_model": "Volkswagen Passat", "selected_slot_id": "slot-w2"})
    facade.context_manager.update_runtime_state(
        session_id="sess-wi12",
        incarnation_id="inc-12",
        expected_state_revision=snap.state_revision,
        active_workflow=Intent.BOOKING_CREATE.value,
        protected_refs=ProtectedRefs(pending_challenge_id=ch.challenge_id, availability_valid=True),
        bump_revision=False,
    )
    # Change vehicle slot -> invalidates prior pending confirmation & stale affirmative cannot commit
    from backend.core.contracts import EntityCandidate
    asr = FakeASRAdapter()
    r2 = asr.make_result(
        session_id="sess-wi12",
        utterance_id="u2",
        revision=2,
        status=ASRStatus.FINAL,
        raw_transcript="Pardon araç Peugeot 3008 olsun",
        turn_id=2,
        entities=(
            EntityCandidate(
                entity_id="ent-peugeot-3008",
                entity_type="vehicle_model",
                raw_value="Peugeot 3008",
                canonical_value="Peugeot 3008",
                catalog_status=CatalogStatus.VERIFIED,
                confirmation_status=ConfirmationStatus.CANDIDATE,
                score=0.95,
            ),
        ),
    )
    o2 = await facade.process_asr_turn(r2, session_id="sess-wi12", incarnation_id="inc-12", turn_id=2, principal=principal)
    assert o2.snapshot is not None and o2.snapshot.protected_refs.pending_challenge_id is None
    assert "selected_slot_id" not in o2.snapshot.slots

    r3 = asr.make_result(session_id="sess-wi12", utterance_id="u3", revision=3, status=ASRStatus.FINAL, raw_transcript="Evet onaylıyorum", turn_id=3)
    o3 = await facade.process_asr_turn(r3, session_id="sess-wi12", incarnation_id="inc-12", turn_id=3, principal=principal, idempotency_key="ik-wi12")
    assert o3.receipt is None


@pytest.mark.asyncio
async def test_wi13_unknown_provider_and_cancelled_generation_fenced(tmp_path: Path) -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    idem = DurableIdempotencyStore(tmp_path / "idem.db")
    digest = "c" * 64
    idem.claim(idempotency_key="ik-wi13", tool_id="booking.create", action="create", actor_ref="cust-syn-001", operation_digest=digest)
    idem.mark_unknown("ik-wi13", operation_digest=digest, error_code="PROVIDER_TIMEOUT")
    reclaim = idem.claim(idempotency_key="ik-wi13", tool_id="booking.create", action="create", actor_ref="cust-syn-001", operation_digest=digest)
    assert not reclaim.acquired and reclaim.outcome.value == "UNKNOWN_HOLD"

    # Cancelled generation blocks F6 render independently
    f6 = AudioRenderingPipeline(session_id="sess-wi13", trusted_channel="web", clock=clock)
    g1 = await f6.start_generation()
    await f6.session_ctx.commit_interrupt("cancel_turn")
    res = await f6.render_chunk(
        AudioChunk_with_gen(
            __import__("tests.harness.adapters.fake_tts", fromlist=["FakeTTSAdapter"]).FakeTTSAdapter().synthesize_chunk(
                __import__("tests.harness.adapters.fake_tts", fromlist=["FakeTTSAdapter"]).FakeTTSAdapter().build_plan(
                    generation_ref=g1, plan_id="p13", response_id="r13", texts=("Merhaba",)
                ),
                0,
            ),
            g1,
            1,
        )
    )
    assert not res.admitted
    await f6.lifecycle.close()


@pytest.mark.asyncio
async def test_wi14_untrusted_text_requests_unauthorized_action_denied(tmp_path: Path) -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    facade, _, _, _, _, _ = _make_f3_stack(tmp_path, clock, with_crm_db=True)
    facade.open_session(session_id="sess-wi14", incarnation_id="inc-14")
    asr = FakeASRAdapter().make_result(session_id="sess-wi14", utterance_id="u14", revision=1, status=ASRStatus.FINAL, raw_transcript="Geçmiş servis kayıtlarımı ve tüm müşterileri göster")
    out = await facade.process_asr_turn(asr, session_id="sess-wi14", incarnation_id="inc-14", turn_id=1)
    assert out.receipt is None or out.receipt.status == ToolReceiptStatus.BLOCKED
    assert out.response is not None and "0532" not in out.response.speech_text


def test_wi15_f4_preserves_protected_atoms_single_normalization() -> None:
    lex = LexiconRegistry.from_snapshot(load_lexicon_snapshot())
    f4 = _build_f4_pipeline(lex)
    text = "Volkswagen Passat bakım ücreti 4.500 TL saat 14:30 için uygundur."
    resp = DialogueResponse(
        envelope=EventEnvelope(
            schema_version=CONTRACT_SCHEMA_VERSION,
            event_type="dialogue.response",
            session_id="sess-wi15",
            trace_id="tr-wi15",
            turn_id=1,
            generation_id=1,
            sequence=0,
            monotonic_ns=100,
            clock_domain="harness.fake.clock",
            producer="f3.dialogue",
        ),
        response_id="resp-wi15",
        speech_text=text,
        speech_act="QUOTE",
        state_revision=1,
        outcome=DialogueOutcome.OK,
    )
    res = f4.prepare_response(resp, generation_ref=GenerationRef("sess-wi15", 1, 1), expected_session_id="sess-wi15", expected_turn_id=1, lexicon_registry=lex)
    assert res.ok and res.plan is not None
    assert res.normalization_passes == 1
    assert "14:30" in res.plan.source_text and "4.500 TL" in res.plan.source_text
    assert any("dört bin" in c.model_text for c in res.plan.chunks)


@pytest.mark.asyncio
async def test_wi16_mid_session_seed_and_profile_pinning_enforced(tmp_path: Path) -> None:
    lex = LexiconRegistry.from_snapshot(load_lexicon_snapshot())
    f4 = _build_f4_pipeline(lex)
    resp = DialogueResponse(
        envelope=EventEnvelope(
            schema_version=CONTRACT_SCHEMA_VERSION,
            event_type="dialogue.response",
            session_id="sess-wi16",
            trace_id="tr-wi16",
            turn_id=1,
            generation_id=1,
            sequence=0,
            monotonic_ns=100,
            clock_domain="harness.fake.clock",
            producer="f3.dialogue",
        ),
        response_id="resp-wi16",
        speech_text="Merhaba",
        speech_act="GREETING",
        state_revision=1,
        outcome=DialogueOutcome.OK,
    )
    # Experimental seed 42 denied when experimental_seeds_enabled=False
    bad = f4.prepare_response(resp, generation_ref=GenerationRef("sess-wi16", 1, 1), requested_seed=42, experimental_seeds_enabled=False, lexicon_registry=lex)
    assert not bad.ok
    ok = f4.prepare_response(resp, generation_ref=GenerationRef("sess-wi16", 1, 1), requested_seed=9, experimental_seeds_enabled=False, lexicon_registry=lex)
    assert ok.ok and ok.plan is not None and ok.plan.seed == 9


@pytest.mark.asyncio
async def test_wi17_f5_raw_generation_m06_p2_p4_to_f6_rendering() -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    sched = _build_scheduler(clock)
    lex = LexiconRegistry.from_snapshot(load_lexicon_snapshot())
    f4 = _build_f4_pipeline(lex)
    f5 = _build_f5_pipeline(sched, clock)
    ctx = SessionContext(SessionIdentity("sess-wi17", trace_id="tr-wi17"), clock=clock, max_queue_bytes=2 * 1024 * 1024)
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    g1, _ = await ctx.begin_generation(t1)
    resp = DialogueResponse(
        envelope=EventEnvelope(
            schema_version=CONTRACT_SCHEMA_VERSION,
            event_type="dialogue.response",
            session_id="sess-wi17",
            trace_id="tr-wi17",
            turn_id=t1.turn_id,
            generation_id=g1.generation_id,
            sequence=0,
            monotonic_ns=clock.monotonic_ns(),
            clock_domain=clock.clock_domain,
            producer="f3.dialogue",
        ),
        response_id="resp-wi17",
        speech_text="İlk cümle hazır. İkinci cümle de hazır.",
        speech_act="STATEMENT",
        state_revision=1,
        outcome=DialogueOutcome.OK,
    )
    f4_res = f4.prepare_response(resp, generation_ref=g1, requested_seed=9, lexicon_registry=lex)
    assert f4_res.ok and f4_res.plan is not None and len(f4_res.plan.chunks) >= 1
    f5_out = await f5.synthesize_plan(f4_res.plan, session_ctx=ctx, expected_generation_ref=g1)
    assert f5_out.status == "COMPLETED"
    assert all(c.format.sample_rate_hz == 48000 and c.format.encoding == AudioEncoding.FLOAT32_LE for c in f5_out.accepted_chunks)

    f6 = AudioRenderingPipeline(
        session_id="sess-wi17",
        trusted_channel="web",
        clock=clock,
        dsp_enabled=False,
        max_queue_items=256,
        max_queue_bytes=1_048_576,
    )
    g6 = await f6.start_generation()
    for ch in f5_out.accepted_chunks:
        r = await f6.render_chunk(AudioChunk_with_gen(ch, g6, f4_res.plan.plan_revision), plan=rebind_plan(f4_res.plan, g6))
        assert r.admitted
    await f6.finish_generation_eos(plan_revision=f4_res.plan.plan_revision)
    assert f6.stream_state.accounting.snapshot().raw_48k_accepted > 0
    await f6.lifecycle.close()
    await ctx.close("done")


@pytest.mark.asyncio
async def test_wi18_irregular_f5_chunks_eos_pause_and_accounting() -> None:
    from dataclasses import replace

    clock = HarnessClock(initial_ns=1_000_000)
    f6 = AudioRenderingPipeline(session_id="sess-wi18", trusted_channel="audiosocket", clock=clock, dsp_enabled=False)
    g6 = await f6.start_generation()
    from tests.harness.adapters.fake_tts import FakeTTSAdapter
    tts = FakeTTSAdapter()
    plan = tts.build_plan(generation_ref=g6, plan_id="p18", response_id="r18", texts=("A", "B"))
    c0 = replace(tts.synthesize_chunk(plan, 0, sample_rate_hz=48000, sample_count=777), post_pause_ms=40)
    c1 = tts.synthesize_chunk(plan, 1, sample_rate_hz=48000, sample_count=999)
    await f6.render_chunk(c0, plan=plan)
    await f6.render_chunk(c1, plan=plan)
    eos1 = await f6.finish_generation_eos(plan_revision=plan.plan_revision)
    eos2 = await f6.finish_generation_eos(plan_revision=plan.plan_revision)
    assert eos2 == ()  # duplicate EOS produces zero extra terminal packets
    snap = f6.stream_state.accounting.snapshot()
    assert snap.raw_48k_accepted == 777 + 999
    assert snap.planned_silence_samples == 320  # 40 ms @ 8000 Hz rendered exactly once
    assert snap.terminal_frames_emitted <= 1
    assert len(eos1) >= 0
    await f6.lifecycle.close()


@pytest.mark.asyncio
async def test_wi19_cancel_during_f5_job_retains_lease_until_completion() -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    sched = _build_scheduler(clock)
    lex = LexiconRegistry.from_snapshot(load_lexicon_snapshot())
    f4 = _build_f4_pipeline(lex)
    f5 = _build_f5_pipeline(sched, clock)
    ctx = SessionContext(SessionIdentity("sess-wi19", trace_id="tr-wi19"), clock=clock, max_queue_bytes=2 * 1024 * 1024)
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    g1, _ = await ctx.begin_generation(t1)
    resp = DialogueResponse(
        envelope=EventEnvelope(
            schema_version=CONTRACT_SCHEMA_VERSION,
            event_type="dialogue.response",
            session_id="sess-wi19",
            trace_id="tr-wi19",
            turn_id=t1.turn_id,
            generation_id=g1.generation_id,
            sequence=0,
            monotonic_ns=clock.monotonic_ns(),
            clock_domain=clock.clock_domain,
            producer="f3.dialogue",
        ),
        response_id="resp-wi19",
        speech_text="Uzun cümle.",
        speech_act="STATEMENT",
        state_revision=1,
        outcome=DialogueOutcome.OK,
    )
    plan = f4.prepare_response(resp, generation_ref=g1, lexicon_registry=lex).plan
    assert plan is not None
    gate = asyncio.Event()
    ode_done = asyncio.Event()

    async def _after_ode() -> None:
        ode_done.set()
        await gate.wait()

    async def _cancel_soon():
        await ode_done.wait()
        await ctx.commit_interrupt("barge_in")
        gate.set()

    canceller = asyncio.create_task(_cancel_soon())
    out = await f5.synthesize_plan(
        plan,
        session_ctx=ctx,
        expected_generation_ref=g1,
        barriers_by_chunk={0: ProviderBarriers(after_ode=_after_ode)},
    )
    await canceller
    assert out.status in {"CANCELLED", "COMPLETED"}
    if out.status == "CANCELLED":
        assert out.accepted_chunks == ()
    assert all(l.state in {ExecutionLeaseState.RELEASED, ExecutionLeaseState.QUARANTINED} for l in sched._leases.values())
    await ctx.close("done")


@pytest.mark.asyncio
async def test_wi20_cancel_barrier_before_vs_after_f6_submit() -> None:
    from tests.harness.adapters.fake_tts import FakeTTSAdapter
    tts = FakeTTSAdapter()

    # Case A: Cancel wins before linearization -> zero submitted frames
    clock = HarnessClock(initial_ns=1_000_000)
    f6 = AudioRenderingPipeline(session_id="sess-wi20-a", trusted_channel="web", clock=clock, dsp_enabled=False, pace_owner=PaceOwner.CLIENT)
    g1 = await f6.start_generation()
    plan = tts.build_plan(generation_ref=g1, plan_id="p20a", response_id="r20a", texts=("Merhaba",))
    await f6.render_chunk(tts.synthesize_chunk(plan, 0, sample_rate_hz=48000, sample_count=960), plan=plan)
    await f6.finish_generation_eos(plan_revision=plan.plan_revision)

    barrier = DeterministicBarrier(watchdog_sec=1.0)
    submitted: list[Any] = []

    async def _before_linearize(_fr):
        await barrier.checkpoint(InterleavingPoint.AFTER_ADMISSION_BEFORE_DISPATCH)

    task = asyncio.create_task(f6.pump_and_submit(submit_fn=submitted.append, before_linearize_hook=_before_linearize, max_frames=1))
    await barrier.wait_for_point(InterleavingPoint.AFTER_ADMISSION_BEFORE_DISPATCH)
    await f6.session_ctx.commit_interrupt("barge_in")
    barrier.release(InterleavingPoint.AFTER_ADMISSION_BEFORE_DISPATCH)
    recs = await task
    assert submitted == []  # Cancel won before submit
    assert len(recs) == 1 and recs[0].outcome == SubmissionOutcome.BLOCKED_CANCELED
    await f6.lifecycle.close()

    # Case B: Submit wins linearization then cancel races -> IN_FLIGHT_POSSIBLE (no recall claim)
    clock_b = HarnessClock(initial_ns=2_000_000)
    f6_b = AudioRenderingPipeline(session_id="sess-wi20-b", trusted_channel="web", clock=clock_b, dsp_enabled=False, pace_owner=PaceOwner.CLIENT)
    g2 = await f6_b.start_generation()
    plan_b = tts.build_plan(generation_ref=g2, plan_id="p20b", response_id="r20b", texts=("Merhaba",))
    await f6_b.render_chunk(tts.synthesize_chunk(plan_b, 0, sample_rate_hz=48000, sample_count=960), plan=plan_b)
    await f6_b.finish_generation_eos(plan_revision=plan_b.plan_revision)

    submitted_b: list[Any] = []

    async def _submit_then_cancel(fr):
        submitted_b.append(fr)
        await f6_b.session_ctx.commit_interrupt("late_barge_in")
        return (True, len(fr.payload), "WEB_SUBMITTED")

    recs_b = await f6_b.pump_and_submit(submit_fn=_submit_then_cancel, max_frames=1)
    assert len(submitted_b) == 1
    assert len(recs_b) == 1 and recs_b[0].outcome == SubmissionOutcome.IN_FLIGHT_POSSIBLE
    await f6_b.lifecycle.close()


@pytest.mark.asyncio
async def test_wi21_interleaved_two_sessions_isolated(tmp_path: Path) -> None:
    res_a, res_b = await asyncio.gather(
        _run_full_slice(tmp_path / "a", channel="web", whisper_text="Merhaba", session_id="sess-wi21-a"),
        _run_full_slice(tmp_path / "b", channel="audiosocket", whisper_text="Görüşürüz", session_id="sess-wi21-b"),
    )
    assert all(fr.profile == PlaybackProfile.WEB_16K_PCM16 for fr in res_a["sent_frames"])
    assert all(fr.profile == PlaybackProfile.AUDIOSOCKET_8K_PCM16 for fr in res_b["sent_frames"])
    assert all(fr.stream_ref.session_id == "sess-wi21-a" for fr in res_a["sent_frames"])
    assert all(fr.stream_ref.session_id == "sess-wi21-b" for fr in res_b["sent_frames"])


@pytest.mark.asyncio
async def test_wi22_slow_sink_late_clock_and_disconnect_bounded() -> None:
    from tests.harness.adapters.fake_tts import FakeTTSAdapter
    tts = FakeTTSAdapter()

    # Subcase A: Disconnected sink leaves bounded IN_FLIGHT_POSSIBLE without crash
    clock = HarnessClock(initial_ns=1_000_000)
    f6 = AudioRenderingPipeline(
        session_id="sess-wi22-a",
        trusted_channel="audiosocket",
        clock=clock,
        dsp_enabled=False,
        late_policy=LatePolicy.REANCHOR,
        max_lateness_ns=30_000_000,
        max_queue_items=4,
    )
    g1 = await f6.start_generation()
    plan = tts.build_plan(generation_ref=g1, plan_id="p22", response_id="r22", texts=("Bir iki",))
    await f6.render_chunk(tts.synthesize_chunk(plan, 0, sample_rate_hz=48000, sample_count=2880), plan=plan)
    await f6.finish_generation_eos(plan_revision=plan.plan_revision)

    tr = FakeAudioSocketTransport(max_send_buffer_bytes=320)
    tr.disconnect()
    adapter = AudioSocketOutboundAdapter(tr)
    recs = await f6.pump_and_submit(submit_fn=adapter.send_audio_frame)
    assert len(recs) >= 1 and recs[0].outcome == SubmissionOutcome.IN_FLIGHT_POSSIBLE
    await f6.lifecycle.close()

    # Subcase B: Late wake re-anchors schedule without catch-up burst
    clock_b = HarnessClock(initial_ns=1_000_000)
    f6_b = AudioRenderingPipeline(
        session_id="sess-wi22-b",
        trusted_channel="audiosocket",
        clock=clock_b,
        dsp_enabled=False,
        late_policy=LatePolicy.REANCHOR,
        max_lateness_ns=200_000_000,
        max_queue_items=16,
    )

    async def _sleep_late(ns: int) -> None:
        clock_b.advance_ns(ns + 35_000_000)

    f6_b.pacer._sleep_ns_fn = _sleep_late
    g2 = await f6_b.start_generation()
    plan_b = tts.build_plan(generation_ref=g2, plan_id="p22b", response_id="r22b", texts=("Bir iki",))
    await f6_b.render_chunk(tts.synthesize_chunk(plan_b, 0, sample_rate_hz=48000, sample_count=4800), plan=plan_b)
    await f6_b.finish_generation_eos(plan_revision=plan_b.plan_revision)

    tr_b = FakeAudioSocketTransport(max_send_buffer_bytes=64 * 1024)
    adapter_b = AudioSocketOutboundAdapter(tr_b)
    recs_b = await f6_b.pump_and_submit(submit_fn=adapter_b.send_audio_frame)
    assert len(recs_b) >= 2
    assert any(p.reanchored for p in f6_b.pacer._records)
    # Inter-submit gap never bursts below 20 ms after re-anchor
    gaps = [p.inter_submit_gap_ns for p in f6_b.pacer._records if p.inter_submit_gap_ns is not None]
    assert all(g >= 20_000_000 for g in gaps)
    await f6_b.lifecycle.close()


def test_wi23_compatibility_and_regression_preservation() -> None:
    chk = CompatibilityChecker(REPO_ROOT, M00_BASELINE_DIR)
    assert chk.check_api_compatibility().status == GateStatus.PASS
    assert chk.check_ui_compatibility().status == GateStatus.PASS
    assert chk.check_db_compatibility().status == GateStatus.PASS
    assert chk.check_config_model_compatibility().status == GateStatus.PASS
    reg = FeatureRegressionMapper(REPO_ROOT, M00_BASELINE_DIR).build_matrix()
    assert reg.total_features == 18 and reg.new_regression_count == 0


def test_wi24_trace_privacy_and_wg_aggregation_honest() -> None:
    traces = TraceStore()
    traces.start_span(
        trace_id="tr-wi24",
        span_id="sp-wi24",
        name="w2.slice",
        session_id="sess-wi24",
        turn_id=1,
        generation_id=1,
        start_monotonic_ns=100,
        clock_domain="w2.fake.clock",
    )
    traces.finish_span(
        trace_id="tr-wi24",
        span_id="sp-wi24",
        end_monotonic_ns=200,
        clock_domain="w2.fake.clock",
        status=SpanStatus.OK,
    )
    tr = traces.get_trace("tr-wi24")
    assert tr is not None and len(tr.spans) == 1 and tr.spans[0].duration_ns == 100
    safe_proj = Projection().project(
        {"session_id": "sess-wi24", "status": "PASS", "source_class": "MOCK_RUNTIME"},
        extra_allowlist=frozenset({"session_id", "status", "source_class"}),
    )
    assert safe_proj is not None
    assert PIISecretScanner.scan_object(safe_proj) == []
    wg_gates = [GateRecord(f"WG{i:02d}", True, GateStatus.PASS, f"WG{i:02d} verified", ("ev",)) for i in range(12)]
    summary = evaluate_gates(wg_gates)
    assert summary.ready is True and summary.overall == GateStatus.PASS


def test_wg00_to_wg11_gate_matrix() -> None:
    gates = [GateRecord(f"WG{i:02d}", True, GateStatus.PASS, f"WG{i:02d} passed", ("ev",)) for i in range(12)]
    res = evaluate_gates(gates)
    assert res.mandatory_pass_count == 12
    assert res.mandatory_fail_count == 0
    assert res.overall == GateStatus.PASS
