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

import hashlib
import json
import math
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from backend.audio_frontend import (
    AdaptationDecision,
    AecOutputStatus,
    AudioInputPipeline,
    BoundedNlmsAec,
    DoubleTalkClassifier,
    EnvironmentProfileId,
    PHONE_8K_PROFILE,
    PlaybackReferenceReader,
    ReferenceAssociation,
    WEB_16K_48K_PROFILE,
    default_audio_frontend_config,
)
from backend.audio_rendering import (
    AUDIOSOCKET_AUDIO,
    AudioRenderingPipeline,
    AudioSocketOutboundAdapter,
    AudioSocketStreamParser,
    BoundedPlaybackQueue,
    CapacityBudget,
    GlobalCapacityCoordinator,
    PlaybackReferenceTap,
    WebTransportAdapter,
)
from backend.core.configuration import ConfigSource, SupervisorMode, build_snapshot, resolve_configuration
from backend.core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    ASROutcome,
    ASRStatus,
    AudioEncoding,
    AudioFormat,
    AudioFrame,
    GenerationRef,
    ObservationScope,
    PlaybackProfile,
    ProviderMode,
    RenderedFrame,
    SessionIdentity,
    StreamDirection,
    StreamRef,
    ToolReceiptStatus,
)
from backend.core.model_registry import ModelRegistry, VoiceProfileRegistry
from backend.core.runtime import BoundedMediaQueue, QueuedMediaItem, SessionContext
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.turn_generation import PauseController, PauseState
from backend.db import Appointment, Base, Slot, Vehicle, pragmas
from backend.linguistic_frontend import (
    INTENT_PROSODY_TABLE,
    FreyaVocabularyValidator,
    LinguisticFrontendPipeline,
    plan_f4c_prosody_and_chunks,
    resolve_intent_prosody,
)
from backend.linguistic_frontend.text_mapping import SpanMappingEntry, TextMapping
from backend.neural_synthesis import (
    RAW_AUDIO_FORMAT,
    IsolatedRngAdapter,
    ModelResidencyAdapter,
    NeuralSynthesisPipeline,
    QualityGuard,
    SameSeedRecoveryPolicy,
    SolverProfile,
    StrictSynthesisCacheAdapter,
    SynthesisModelHandles,
    SynthesisTelemetry,
    VersionedCacheStore,
    load_static_char_vocab,
    pin_synthesis_snapshot,
)
from backend.observability import Projection, SpanStatus, TraceStore
from backend.runtime_resources import (
    MIB,
    HandleOwnership,
    MemoryBudget,
    ModelSpec,
    PriorityClass,
    ProviderKind,
    QuarantineManager,
    ResidencyManager,
    UnifiedGpuScheduler,
)
from backend.security import (
    AccessContext,
    AuthStrength,
    ConfirmationManager,
    DurableIdempotencyStore,
    EvidenceSource,
    PolicyEngine,
    PrincipalKind,
    SecurityAuditLog,
    anonymous_principal,
    verified_principal,
)
from backend.shared_lexicon import (
    AliasEntry,
    CanonicalEntity,
    EntityCategory,
    LexiconRegistry,
    LexiconSnapshot,
    load_lexicon_snapshot,
)
from backend.speech_recognition import (
    ASRLifecycleManager,
    ASRRouteMode,
    ASRTelemetryBridge,
    ASRUtteranceAdmission,
    InMemoryASRConsumer,
    SpeechRecognitionPipeline,
    WhisperSchedulerEngine,
    resolve_asr_config,
)
from backend.supervisor.contracts import ConversationContext, Intent
from backend.supervisor.dialogue_facade import BoundedDialogueConsumer, DialogueFacade
from backend.supervisor.intent_router import HierarchicalIntentRouter
from backend.supervisor.rag_retriever import (
    AccessClass,
    ApplicabilityKind,
    ApplicabilityScope,
    AuthorityClass,
    DocumentManifest,
    KnowledgeChunk,
    OfflineRagRetriever,
    SourceAnchor,
    SupportStatus,
    build_index_snapshot,
    tokenize_turkish,
)
from backend.supervisor.workflow_adapter import WorkflowAdapter
from backend.voice_activity import (
    BoundedUtteranceQueue,
    F1CProfileConfig,
    F1ProfileConfig,
    F1RouteMode,
    FlushIntent as F1FlushIntent,
    InputCandidateRef,
    InterruptionController,
    InterruptionState,
    M02PauseBridge,
    M02TurnAllocatorBridge,
    OutputAvailability,
    OutputTargetSnapshot,
    SemanticEndpointPolicy,
    StreamAcousticProcessor,
    VADEngineAdapter,
)
from tests.harness.acceptance import evaluate_gates
from tests.harness.adapters.fake_gpu import FakeGPUProbeAdapter
from tests.harness.adapters.fake_transport import FakeAudioSocketTransport
from tests.harness.contracts import GateRecord, GateStatus
from tests.harness.evidence_validator import PIISecretScanner
from tests.harness.fake_clock import HarnessClock

REPO_ROOT = Path(__file__).resolve().parents[2]
G2_RUN_ID = "20261126T064418Z"
G3_RUN_ID = "20261126T064550Z"


# ---------------------------------------------------------------------------
# Deterministic Synthetic External Doubles (No Real Models / GPU / SIP)
# ---------------------------------------------------------------------------


class _ScriptedVADModel:
    model_revision = "fake_g4_silero_v1"

    def __init__(self, scores: list[float], *, default: float = 0.05) -> None:
        self._scores = list(scores)
        self._default = default

    def initial_state(self) -> int:
        return 0

    def infer_with_state(self, window_f32: np.ndarray, sample_rate_hz: int, state: int) -> tuple[float, int]:
        assert sample_rate_hz == 16000 and window_f32.shape == (512,)
        score = self._scores[state] if state < len(self._scores) else self._default
        return score, state + 1


class _FakeWhisperSeg:
    def __init__(self, text: str, start: float = 0.0, end: float = 1.2) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.avg_logprob = -0.18
        self.no_speech_prob = 0.04
        self.compression_ratio = 1.1
        self.words = None


class _ScriptedWhisperModel:
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self._idx = 0

    def transcribe(self, audio: np.ndarray, **kwargs: Any):
        text = self._texts[min(self._idx, len(self._texts) - 1)]
        self._idx += 1
        return [_FakeWhisperSeg(text)], SimpleNamespace(language="tr", language_probability=0.99)


class _FakeDiT:
    def __init__(self, *, fail_first_n: int = 0, uncertain_on_fail: bool = False) -> None:
        self.calls = 0
        self.fail_first_n = fail_first_n
        self.uncertain_on_fail = uncertain_on_fail

    def encode_prepared_text(self, text: str, token_ids: tuple[int, ...], *, device: str = "cpu") -> dict[str, Any]:
        return {
            "observed_text": text,
            "context": np.ones((1, len(token_ids), 8), dtype=np.float32),
            "char_mask": np.ones((1, len(token_ids)), dtype=bool),
        }

    def predict_duration_frames(self, _encoded: Any) -> float:
        return 12.0

    def solve_ode(self, *, latent: Any, encoded: Any, profile: SolverProfile) -> dict[str, Any]:
        self.calls += 1
        if self.calls <= self.fail_first_n:
            err = RuntimeError("injected_ode_fault")
            if self.uncertain_on_fail:
                setattr(err, "uncertain_device_state", True)
            raise err
        return {
            "latents": np.array(latent, dtype=np.float32, copy=True) + np.float32(0.01),
            "nfe_evaluated": profile.steps,
            "completed_steps": profile.steps,
        }


class _FakeVAE:
    sample_rate_hz = 48000

    def __init__(self, *, silent_first_n: int = 0) -> None:
        self.calls = 0
        self.silent_first_n = silent_first_n

    def decode(self, latents_bct: Any) -> np.ndarray:
        self.calls += 1
        arr = np.asarray(latents_bct)
        frames = int(arr.shape[-1]) if arr.ndim == 3 else 12
        n_samples = frames * 1920
        if self.calls <= self.silent_first_n:
            return np.zeros((1, 1, n_samples), dtype=np.float32)
        t = np.arange(n_samples, dtype=np.float32) / 48000.0
        wave = 0.25 * np.sin(2.0 * np.pi * 220.0 * t)
        return wave.reshape(1, 1, n_samples).astype(np.float32)


class _DeterministicFakeEmbedder:
    revision = "g4-fake-embed-v1"
    dimension = 4

    def _embed(self, text: str) -> tuple[float, ...]:
        toks = set(tokenize_turkish(text))
        return (
            1.0 if "bakım" in toks or "periyodik" in toks else 0.1,
            1.0 if "fren" in toks or "uyarı" in toks else 0.1,
            1.0 if "garanti" in toks or "servis" in toks else 0.1,
            1.0 if "lastik" in toks or "basınç" in toks else 0.1,
        )

    def embed_query(self, query: str) -> tuple[float, ...]:
        return self._embed(query)

    def embed_documents(self, texts: Any) -> tuple[tuple[float, ...], ...]:
        return tuple(self._embed(t) for t in texts)


def _doc_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_scheduler(clock: HarnessClock) -> UnifiedGpuScheduler:
    budget = MemoryBudget(clock=clock, headroom_bytes=256 * MIB, max_probe_age_ms=5_000)
    budget.update_probe(FakeGPUProbeAdapter(clock).valid_probe(free_mib=4096))
    residency = ResidencyManager(memory_budget=budget)
    residency.register_model(
        ModelSpec("stt-whisper", HandleOwnership.BORROWED, ProviderKind.CTRANSLATE2, 0, loader=lambda: "whisper-ok")
    )
    residency.register_model(
        ModelSpec("qwen2.5-3b-instruct", HandleOwnership.EXTERNAL, ProviderKind.OLLAMA, 0, loader=lambda: None)
    )
    return UnifiedGpuScheduler(
        clock=clock,
        memory_budget=budget,
        quarantine_manager=QuarantineManager(clock=clock, max_entries=8),
        residency_manager=residency,
    )


def _register_f5_handles(scheduler: UnifiedGpuScheduler, dit: Any, vae: Any) -> None:
    vocab = load_static_char_vocab(repo_root=REPO_ROOT)
    handles = SynthesisModelHandles(
        model_id="tts-freya",
        model_revision="freya-tts:batched-ode",
        tts_model=dit,
        vae=vae,
        char_to_id=vocab.vocab_map,
        vocab_revision=vocab.vocab_revision,
        ownership=HandleOwnership.BORROWED,
        rng_isolation_mode="ISOLATED_GENERATOR",
    )
    res_adapter = ModelResidencyAdapter(scheduler.residency_manager)
    res_adapter.register_handles(handles, vram_bytes=64 * MIB, ownership=HandleOwnership.BORROWED)


def _build_enriched_lexicon() -> LexiconRegistry:
    base = load_lexicon_snapshot()
    extra_entities = (
        CanonicalEntity(
            entity_id="brand:nissan",
            canonical_name="Nissan",
            category=EntityCategory.BRAND,
            normalized_key="nissan",
            brand_name="Nissan",
            priority=10,
        ),
        CanonicalEntity(
            entity_id="model:qashqai",
            canonical_name="Qashqai",
            category=EntityCategory.MODEL,
            normalized_key="qashqai",
            brand_name="Nissan",
            model_name="Qashqai",
            priority=20,
        ),
        CanonicalEntity(
            entity_id="model:juke",
            canonical_name="Juke",
            category=EntityCategory.MODEL,
            normalized_key="juke",
            brand_name="Nissan",
            model_name="Juke",
            priority=20,
        ),
    )
    extra_aliases = (
        AliasEntry(
            alias_id="alias:kaskay",
            alias_text="kaşkay",
            normalized_key="kaşkay",
            canonical_entity_id="model:qashqai",
            canonical_name="Qashqai",
            category=EntityCategory.MODEL,
            priority=20,
            source="reviewed_asr",
        ),
    )
    snap = LexiconSnapshot(
        entities=base.entities + extra_entities,
        aliases=base.aliases + extra_aliases,
        pronunciations=base.pronunciations,
        technical_terms=base.technical_terms,
    )
    return LexiconRegistry.from_snapshot(snap)


def _make_speech_like_signal(n: int, sr: int = 16000, *, amp: float = 0.25, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=np.float32) / float(sr)
    sig = 0.5 * np.sin(2.0 * np.pi * 220.0 * t) + 0.35 * np.sin(2.0 * np.pi * 660.0 * t)
    noise = 0.005 * rng.standard_normal(n).astype(np.float32)
    return (amp * sig + noise).astype(np.float32)


# ---------------------------------------------------------------------------
# G4.01-G4.03: Entry Lineage, Passive Imports & T0/T1 Deterministic Baseline
# ---------------------------------------------------------------------------


def test_g4_01_entry_lineage_g2_g3_and_passive_imports() -> None:
    g2 = json.loads((REPO_ROOT / "docs" / "freya2" / "g2_integration" / G2_RUN_ID / "G2_ACCEPTANCE_MATRIX.json").read_text(encoding="utf-8"))
    assert g2["overall"] == "PASS"
    assert g2["g2_accepted"] is True
    assert g2["g3_ready"] is True

    g3 = json.loads((REPO_ROOT / "docs" / "freya2" / "g3_ui" / G3_RUN_ID / "G3_ACCEPTANCE_MATRIX.json").read_text(encoding="utf-8"))
    assert g3["g3_ui_build_passed"] is True
    assert g3["gates"]["UG16"] == "PASS"
    assert g3["gates"]["UG17"] == "HOLD"
    assert g3["hardware_acceptance_status"] == "NOT_RUN"
    assert g3["human_sip_status"] == "NOT_RUN"

    script = (
        "import sys, threading; "
        "t0 = threading.active_count(); "
        "import backend.audio_frontend, backend.voice_activity, backend.speech_recognition, "
        "backend.supervisor.dialogue_facade, backend.linguistic_frontend, backend.linguistic_frontend.intent_prosody, "
        "backend.neural_synthesis, backend.audio_rendering; "
        "from tests.harness.isolation import audit_import_closure; "
        "bad = audit_import_closure(sys.modules.keys()); "
        "assert not bad, f'bad modules: {bad}'; "
        "assert 'torch' not in sys.modules; "
        "assert 'backend.models' not in sys.modules; "
        "assert 'librosa' not in sys.modules; "
        "assert threading.active_count() == t0"
    )
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr or proc.stdout


# ---------------------------------------------------------------------------
# G4.17: T3-mock Synthetic E2E Journeys (Web 16k & Phone AudioSocket 8k)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["web", "audiosocket"])
async def test_g4_02_t3_mock_e2e_web_16k_and_audiosocket_8k(tmp_path: Path, channel: str) -> None:
    clock = HarnessClock(initial_ns=2_000_000_000, clock_domain="server_mono")
    cfg = resolve_configuration(overrides={"auto_load_models": False, "supervisor_mode": "guarded"}).snapshot
    lex = _build_enriched_lexicon()
    sched = _build_scheduler(clock)

    session_id = f"sess-g4-e2e-{channel}"
    session_ctx = SessionContext(SessionIdentity(session_id, trace_id=f"tr-{session_id}"), clock=clock, max_queue_bytes=2 * 1024 * 1024)
    await session_ctx.open()
    in_stream = StreamRef(session_id, "in-0", StreamDirection.INPUT, 1)
    out_stream = StreamRef(session_id, "out-0", StreamDirection.OUTPUT, 1)

    tap = PlaybackReferenceTap(session_id=session_id, stream_id="out-0", format_epoch=0, max_frames=256, max_bytes=256 * 640)
    assoc = ReferenceAssociation(session_id=session_id, input_stream_id="in-0", input_format_epoch=1, output_stream_ref=out_stream)
    ref_reader = PlaybackReferenceReader(assoc, target_rate_hz=16000)

    f1_queue = BoundedUtteranceQueue(max_items=8, max_bytes=4_000_000)
    f1c_policy = SemanticEndpointPolicy(F1CProfileConfig(mode=F1RouteMode.STRICT), in_stream, clock=clock)
    vad_scores = [0.05] * 2 + [0.92] * 5 + [0.05] * 14
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
        f1c_policy=f1c_policy,
    )

    f0_cfg = default_audio_frontend_config(
        f0_b_adaptive_dsp_enabled=True,
        f0_b_aec_enabled=True,
        environment_profile=EnvironmentProfileId.PARKED_CAR,
    )
    f0_profile = PHONE_8K_PROFILE if channel == "audiosocket" else WEB_16K_48K_PROFILE
    f0_pipe = AudioInputPipeline(
        session_id=session_id,
        session_ctx=session_ctx,
        config=f0_cfg,
        default_profile=f0_profile,
        clock=clock,
        f1_consumer=f1_proc.process_frame,
        reference_source=ref_reader,
    )
    in_rate = 8000 if channel == "audiosocket" else 16000
    f0_pipe.open_stream(in_stream, sample_rate_hz=in_rate, profile=f0_profile)
    samples_per_chunk = 160 if in_rate == 8000 else 512
    n_chunks = 40 if in_rate == 8000 else 21
    for seq in range(n_chunks):
        sig = _make_speech_like_signal(samples_per_chunk, sr=in_rate, amp=0.25, seed=seq + 10)
        pcm = (np.clip(sig, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        r = f0_pipe.ingest_raw(
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
        assert r.ok and r.acoustic_evidence is not None
        clock.advance_ms(20)

    f0_pipe.flush_eos(in_stream)
    f1_proc.flush_eos()
    utt = f1_queue.pop_next()
    assert utt is not None and utt.finalized

    pinned_asr = resolve_asr_config(cfg, route_mode=ASRRouteMode.STRICT)
    asr_engine = WhisperSchedulerEngine(sched, model_getter=lambda: _ScriptedWhisperModel(["Merhaba"]))
    asr_pipe = SpeechRecognitionPipeline(
        engine=asr_engine,
        admission=ASRUtteranceAdmission(),
        consumer=InMemoryASRConsumer(),
        telemetry=ASRTelemetryBridge(),
        lifecycle=ASRLifecycleManager(),
    )
    asr_rec = await asr_pipe.process_utterance(
        utt,
        AudioFormat(16000, 1, AudioEncoding.FLOAT32_LE),
        session_ctx=session_ctx,
        pinned_config=pinned_asr,
        lexicon_registry=lex,
        enable_f2b=True,
    )
    assert asr_rec.result is not None and asr_rec.result.outcome == ASROutcome.OK

    router = HierarchicalIntentRouter()
    rdec = await router.route(
        asr_result=asr_rec.result,
        context=ConversationContext(session_id=uuid4(), turn_at=datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)),
    )
    assert rdec.primary_intent == Intent.GREETING

    audit = SecurityAuditLog(tmp_path / f"audit_{channel}.db")
    idem = DurableIdempotencyStore(tmp_path / f"idem_{channel}.db", audit_log=audit)
    wf = WorkflowAdapter(
        policy_engine=PolicyEngine(audit_log=audit),
        confirmation_manager=ConfirmationManager(clock=clock, audit_log=audit),
        idempotency_store=idem,
        audit_log=audit,
        provider_mode=ProviderMode.MOCK,
    )
    snap = build_snapshot(
        values={"supervisor_mode": SupervisorMode.GUARDED.value},
        sources={"supervisor_mode": ConfigSource.OVERRIDE},
        feature_flags={"supervisor_mode": SupervisorMode.GUARDED.value},
    )
    facade = DialogueFacade(
        config_snapshot=snap,
        mode=SupervisorMode.GUARDED,
        workflow_adapter=wf,
        clock=clock,
        utc_now_fn=lambda: datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc),
    )
    facade.open_session(session_id=session_id, incarnation_id=f"inc-{channel}", lexicon_revision=lex.lexicon_revision)
    turn_id = utt.turn_ref.turn_id if utt.turn_ref else 1
    f3_out = await facade.process_asr_turn(asr_rec.result, session_id=session_id, incarnation_id=f"inc-{channel}", turn_id=turn_id, consumer=BoundedDialogueConsumer())
    assert f3_out.response is not None

    vocab_path = REPO_ROOT / "config" / "freya_vocab.json"
    f4_pipe = LinguisticFrontendPipeline(
        config_snapshot_provider=lambda: cfg,
        model_registry_provider=lambda c: ModelRegistry.from_snapshot(c),
        voice_registry_provider=lambda: VoiceProfileRegistry(),
        lexicon_registry_provider=lambda: lex,
        vocab_validator_factory=lambda s: FreyaVocabularyValidator.from_vocab_file(vocab_path, model_revision=s.model_revision, capability_revision=s.capability_revision),
        require_real_vocab=True,
    )
    t_out, _ = await session_ctx.begin_turn()
    g_out, _ = await session_ctx.begin_generation(t_out)
    f4_resp = replace(f3_out.response, envelope=replace(f3_out.response.envelope, turn_id=t_out.turn_id, generation_id=g_out.generation_id))
    f4_res = f4_pipe.prepare_response(f4_resp, generation_ref=g_out, expected_session_id=session_id, expected_turn_id=t_out.turn_id, requested_seed=9, config_snapshot=cfg, lexicon_registry=lex)
    assert f4_res.ok and f4_res.plan is not None and f4_res.normalization_passes == 1

    dit, vae = _FakeDiT(), _FakeVAE()
    _register_f5_handles(sched, dit, vae)
    f5_pipe = NeuralSynthesisPipeline(scheduler=sched, recovery_policy=SameSeedRecoveryPolicy(enabled=True, clock=clock), telemetry=SynthesisTelemetry(clock=clock))
    f5_out = await f5_pipe.synthesize_plan(f4_res.plan, session_ctx=session_ctx, expected_generation_ref=g_out)
    assert f5_out.status == "COMPLETED" and len(f5_out.accepted_chunks) >= 1

    f6 = AudioRenderingPipeline(session_id=session_id, trace_id=f"tr-{session_id}", trusted_channel=channel, clock=clock, snapshot=cfg, dsp_enabled=False, max_queue_items=256, max_queue_bytes=1_048_576)
    g6 = await f6.start_generation()
    for ch in f5_out.accepted_chunks:
        r_res = await f6.render_chunk(replace(ch, generation_ref=g6, plan_revision=f4_res.plan.plan_revision), plan=replace(f4_res.plan, generation_ref=g6))
        assert r_res.admitted
    await f6.finish_generation_eos(plan_revision=f4_res.plan.plan_revision)

    async def _sleep_ns(ns: int) -> None:
        clock.advance_ns(ns)

    f6.pacer._sleep_ns_fn = _sleep_ns
    sent: list[RenderedFrame] = []
    if channel == "audiosocket":
        tr = FakeAudioSocketTransport(max_send_buffer_bytes=64 * 1024)
        as_adapter = AudioSocketOutboundAdapter(tr)

        def _send_as(fr: RenderedFrame):
            w = as_adapter.send_audio_frame(fr)
            if w.outcome.value == "SUBMITTED":
                sent.append(fr)
                tap.record_claim(claim_id=f"as-{fr.sequence}", frame=fr, claim_ns=clock.monotonic_ns(), clock_domain=clock.clock_domain)
            return w

        await f6.pump_and_submit(submit_fn=_send_as)
        pkts = AudioSocketStreamParser().feed(bytes(tr._tx_buffer))
        assert len(pkts) == len(sent) >= 1
        assert all(kind == AUDIOSOCKET_AUDIO and len(body) == 320 for kind, body in pkts)
    else:
        web_frames: list[bytes] = []
        web_adapter = WebTransportAdapter(f6.profile, send_bytes_fn=web_frames.append)
        ok_h, _ = web_adapter.negotiate_hello({"type": "hello", "sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"})
        assert ok_h

        def _send_web(fr: RenderedFrame):
            w = web_adapter.send_audio_frame(fr)
            if w.accepted:
                sent.append(fr)
                tap.record_claim(claim_id=f"web-{fr.sequence}", frame=fr, claim_ns=clock.monotonic_ns(), clock_domain=clock.clock_domain)
            return w

        await f6.pump_and_submit(submit_fn=_send_web)
        assert len(web_frames) == len(sent) >= 1
        assert all(len(b) == 640 for b in web_frames)

    assert tap.frame_count >= 1
    await f6.lifecycle.close()
    f0_pipe.close()
    ref_reader.close()
    await session_ctx.close("done")


# ---------------------------------------------------------------------------
# G4.10 / G4.17: Multi-Turn Slot Correction + M07 Challenge & Receipt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g4_03_multi_turn_slot_correction_and_m07_challenge_receipt(tmp_path: Path) -> None:
    clock = HarnessClock(initial_ns=3_000_000_000, clock_domain="server_mono")
    db_path = tmp_path / "g4_crm.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    event.listen(engine, "connect", pragmas)
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, expire_on_commit=False)

    target_day = datetime.now(timezone.utc).date() + timedelta(days=1)
    slot_am = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    slot_pm = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
    with sf() as db:
        db.add(Vehicle(id="veh-qashqai", description="Nissan Qashqai 2024", plate="34 G4 01"))
        db.add(Vehicle(id="veh-juke", description="Nissan Juke 2024", plate="34 G4 02"))
        db.add(Slot(id="slot-am", starts_at=slot_am.isoformat()))
        db.add(Slot(id="slot-pm", starts_at=slot_pm.isoformat()))
        db.commit()

    audit = SecurityAuditLog(tmp_path / "g4_audit.db")
    policy = PolicyEngine(audit_log=audit)
    confirm = ConfirmationManager(clock=clock, audit_log=audit)
    idem = DurableIdempotencyStore(tmp_path / "g4_idem.db", audit_log=audit)
    wf = WorkflowAdapter(
        policy_engine=policy,
        confirmation_manager=confirm,
        idempotency_store=idem,
        audit_log=audit,
        session_factory=sf,
        provider_mode=ProviderMode.MOCK,
    )

    # Turn 1 (anonymous caller): can read availability, CANNOT mutate
    anon_access = AccessContext(session_id="sess-g4-03", principal=anonymous_principal(), channel="voice", state_revision=1)
    avail = wf.read_availability(access=anon_access, target_day=target_day, now_utc=datetime.now(timezone.utc))
    assert avail.allowed is True
    denied_anon = wf.execute_mutation(
        access=anon_access,
        tool_id="booking.create",
        action="create_booking",
        idempotency_key="ik-g4-anon",
        terms={"selected_slot_id": "slot-am", "vehicle_ref": "veh-qashqai", "customer_ref": "anon"},
        challenge_id=None,
    )
    assert denied_anon.receipt.status != ToolReceiptStatus.COMMITTED

    # Turn 2 (verified customer): initial slot/vehicle -> corrected to slot-pm & veh-juke
    cust = verified_principal("cust-g4", kind=PrincipalKind.CUSTOMER, auth_strength=AuthStrength.STRONG_VERIFIED, evidence_source=EvidenceSource.MFA_VERIFIED)
    cust_access = AccessContext(session_id="sess-g4-03", principal=cust, channel="voice", state_revision=2)

    initial_terms = {"selected_slot_id": "slot-am", "vehicle_ref": "veh-qashqai", "customer_ref": "cust-g4"}
    ch_old, _ = wf.issue_and_present_confirmation(access=cust_access, tool_id="booking.create", action="create_booking", terms=initial_terms)
    assert ch_old is not None

    # Customer corrects slot and vehicle -> digest mismatch must reject old challenge!
    corrected_terms = {"selected_slot_id": "slot-pm", "vehicle_ref": "veh-juke", "customer_ref": "cust-g4"}
    _, mismatch_err = wf.approve_confirmation(challenge_id=ch_old.challenge_id, access=cust_access, terms=corrected_terms)
    assert mismatch_err is not None

    # Issue fresh challenge for corrected terms -> approve -> single COMMITTED MOCK receipt
    ch_new, _ = wf.issue_and_present_confirmation(access=cust_access, tool_id="booking.create", action="create_booking", terms=corrected_terms)
    assert ch_new is not None and ch_new.challenge_id != ch_old.challenge_id
    approved_ch, app_err = wf.approve_confirmation(challenge_id=ch_new.challenge_id, access=cust_access, terms=corrected_terms)
    assert approved_ch is not None and app_err is None

    committed = wf.execute_mutation(
        access=cust_access,
        tool_id="booking.create",
        action="create_booking",
        idempotency_key="ik-g4-corrected",
        terms=corrected_terms,
        challenge_id=ch_new.challenge_id,
    )
    assert committed.receipt.status == ToolReceiptStatus.COMMITTED
    assert committed.receipt.provider_mode == ProviderMode.MOCK
    assert committed.receipt.verified_result is False

    # Idempotent replay returns same receipt without duplicate DB booking
    replay = wf.execute_mutation(
        access=cust_access,
        tool_id="booking.create",
        action="create_booking",
        idempotency_key="ik-g4-corrected",
        terms=corrected_terms,
        challenge_id=ch_new.challenge_id,
    )
    assert replay.receipt.status == ToolReceiptStatus.COMMITTED
    assert replay.receipt.evidence_ref == committed.receipt.evidence_ref
    with sf() as db:
        rows = db.execute(select(Appointment)).scalars().all()
        assert len(rows) == 1
        assert rows[0].slot_id == "slot-pm"
        assert rows[0].vehicle_id == "veh-juke"


# ---------------------------------------------------------------------------
# G4.07: Barge-In Soft Pause / Resume / Confirmed Commit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g4_04_barge_in_soft_pause_resume_and_confirmed_commit() -> None:
    clock = HarnessClock(initial_ns=4_000_000_000, clock_domain="g4.fake.clock")
    pause_ctrl = PauseController()
    flushes: list[F1FlushIntent] = []
    bridge = M02PauseBridge(pause_ctrl, on_flush_intent=flushes.append)
    root = CancellationScope("sess:g4-04", clock=clock)
    gen_scope = root.child_scope("gen:1")

    ctrl = InterruptionController("sess-g4-04", "inc-1", bridge, clock=clock)
    in_ref = StreamRef("sess-g4-04", "in-0", StreamDirection.INPUT, 1)
    gref = GenerationRef("sess-g4-04", 1, 1)
    target = OutputTargetSnapshot(
        generation_ref=gref,
        plan_revision=1,
        availability=OutputAvailability.LOCAL_QUEUED,
        queued_items=3,
        queued_bytes=960,
        in_flight_submitted=True,
        drained=False,
        can_gate=True,
    )

    # Stage 1: soft pause -> rejected candidate -> resume same generation
    cand1 = InputCandidateRef("sess-g4-04", "inc-1", in_ref, start_sample=3200, sequence=1)
    s1 = ctrl.on_speech_candidate(cand1, target, gen_scope)
    assert s1.state == InterruptionState.SOFT_PAUSED
    assert s1.in_flight_recall_claimed is False
    assert pause_ctrl.state == PauseState.SOFT_PAUSED

    clock.advance_ms(80)
    r1 = ctrl.on_candidate_rejected(cand1, gen_scope, cursor_intact=True)
    assert r1.state == InterruptionState.RESUMED
    assert pause_ctrl.state == PauseState.RUNNING

    # Stage 2: confirmed barge-in -> cancel scope + queue flush + honest scoped receipt
    cand2 = InputCandidateRef("sess-g4-04", "inc-1", in_ref, start_sample=6400, sequence=2)
    s2 = ctrl.on_speech_candidate(cand2, target, gen_scope, defer_pause_ack=True)
    assert s2.state == InterruptionState.PAUSE_REQUESTED

    m02_q = BoundedMediaQueue(max_items=8, max_bytes=4096)
    m02_q.enqueue(QueuedMediaItem(gref, 1, b"\x01" * 320, 1))
    commit = ctrl.on_speech_confirmed(cand2, gen_scope, queue=m02_q, reason="confirmed_barge")
    assert commit.state == InterruptionState.COMMITTED
    assert gen_scope.is_cancel_requested is True
    assert len(flushes) == 1

    f6_pipe = AudioRenderingPipeline(session_id="sess-g4-04", trusted_channel="asterisk", clock=clock, max_queue_items=4, max_queue_bytes=1280)
    await f6_pipe.start_generation()
    receipt = await f6_pipe.commit_interrupt_with_receipt(reason="user_barge_in")
    assert receipt.local.scope == ObservationScope.SERVER
    assert receipt.local.status == "FLUSHED"
    assert receipt.remote.scope == ObservationScope.PBX
    assert receipt.remote.status == "UNSUPPORTED"
    assert receipt.audible_silence_verified is False
    await f6_pipe.close()


# ---------------------------------------------------------------------------
# G4.12: 31-Intent Prosody Table & Advisory Routing
# ---------------------------------------------------------------------------


def test_g4_05_31_intent_prosody_table_and_advisory_routing() -> None:
    assert len(INTENT_PROSODY_TABLE) == 31
    expected_priorities = {"Düşük", "Orta", "Yüksek", "Kritik"}
    for intent_name, spec in INTENT_PROSODY_TABLE.items():
        assert spec.intent == intent_name
        assert spec.style_token.startswith("<") and spec.style_token.endswith(">")
        assert spec.priority in expected_priorities
        assert 0.5 <= spec.f0_factor <= 1.5
        assert 0.5 <= spec.rate_factor <= 1.5
        assert 0.5 <= spec.energy_factor <= 1.5
        assert 0.5 <= spec.pause_factor <= 1.5

        resolved = resolve_intent_prosody(intent_name)
        assert resolved == spec

        text = "Test sürüş ve servis bilgilendirmesi."
        mapping = TextMapping(source_text=text, normalized_text=text, entries=(SpanMappingEntry((0, len(text)), (0, len(text))),))
        chk_res, prosody = plan_f4c_prosody_and_chunks(text, atoms=(), text_mapping=mapping, speech_act="STATEMENT", intent=intent_name)
        assert prosody.intent_prosody == spec
        assert all(spec.style_token not in c.model_text for c in chk_res.chunks)


# ---------------------------------------------------------------------------
# G4.20: T4-fault Deterministic Fault Injection, Isolation & Cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g4_06_t4_fault_injection_quarantine_acl_backpressure_and_cleanup() -> None:
    clock = HarnessClock(initial_ns=5_000_000_000, clock_domain="g4.fake.clock")
    sched = _build_scheduler(clock)

    # 1. F5 transient ODE failure with uncertain_device_state=True -> M06 quarantine / zero leaked leases
    from backend.core.contracts import ChunkPlan, PlanValidationStatus, SynthesisPlan
    gref = GenerationRef("sess-g4-06", 1, 1)
    plan = SynthesisPlan(
        schema_version=CONTRACT_SCHEMA_VERSION,
        generation_ref=gref,
        plan_id="plan-g4-06",
        plan_revision=1,
        response_id="resp-g4-06",
        source_text="Merhaba.",
        normalized_text="Merhaba.",
        language="tr",
        voice_profile="leyla-warm-42",
        seed=42,
        chunks=(ChunkPlan(chunk_id="c0", chunk_index=0, model_text="Merhaba."),),
        normalization_passes=1,
        validation_status=PlanValidationStatus.VALID,
    )
    dit_fault = _FakeDiT(fail_first_n=2, uncertain_on_fail=True)
    vae_ok = _FakeVAE()
    _register_f5_handles(sched, dit_fault, vae_ok)
    pipe = NeuralSynthesisPipeline(scheduler=sched, recovery_policy=SameSeedRecoveryPolicy(enabled=True, clock=clock), telemetry=SynthesisTelemetry(clock=clock))
    out = await pipe.synthesize_plan(plan, pin_kwargs={"allow_experimental_seeds": True})
    assert out.status == "FAILED" and dit_fault.calls == 1
    await sched.wait_reclaims()
    assert sched.quarantine_manager.active_count == 0

    # 2. F5 QualityGuard silent output rejection + VersionedCacheStore PII rejection
    guard = QualityGuard(calibrated_thresholds_approved=False)
    z_res = guard.assess(payload=np.zeros(4800, dtype=np.float32).tobytes(), sample_count=4800, audio_format=RAW_AUDIO_FORMAT)
    assert not z_res.structurally_valid
    store = VersionedCacheStore(max_entries=2, max_bytes=8192, ttl_ns=10_000_000_000, clock=clock)
    elig_pii = store.classify_eligibility(session_id="sess-g4-06", is_public_template=True, template_id="t1", contains_pii=True)
    assert not elig_pii.cacheable

    # 3. F0-B browser native AEC -> BYPASS & missing reference -> FROZEN_FILTER / BYPASS
    browser_cfg = default_audio_frontend_config(f0_b_adaptive_dsp_enabled=True, f0_b_aec_enabled=True, browser_native_aec_active=True)
    f0_br = AudioInputPipeline(session_id="sess-g4-06", config=browser_cfg)
    br_res = f0_br.ingest_raw(
        stream_ref=StreamRef("sess-g4-06", "in-0", StreamDirection.INPUT, 1),
        payload=np.zeros(320, dtype="<i2").tobytes(),
        sample_rate_hz=16000,
        sample_count=320,
        sequence=0,
        sample_offset=0,
    )
    assert br_res.acoustic_evidence is not None and br_res.acoustic_evidence.aec_status == AecOutputStatus.BYPASS
    f0_br.close()

    # 4. F3-C OfflineRagRetriever ACL isolation & CONFLICT abstention
    t_priv = "Dahili servis prosedürü garanti onayı."
    t_c1 = "Model-X bakım aralığı 10000 km."
    t_c2 = "Model-X bakım aralığı 20000 km."
    m_priv = DocumentManifest("doc-priv", "1", _doc_sha(t_priv), len(t_priv), "text/plain", "tr", "Workshop", AuthorityClass.WORKSHOP_POLICY, "2025-01-01", ApplicabilityScope(ApplicabilityKind.GENERAL), AccessClass.WORKSHOP_INTERNAL, frozenset({PrincipalKind.OPERATOR}))
    m_c1 = DocumentManifest("doc-c1", "1", _doc_sha(t_c1), len(t_c1), "text/plain", "tr", "OEM", AuthorityClass.OEM_MANUAL, "2025-01-01", ApplicabilityScope(ApplicabilityKind.SPECIFIC, model="Model-X"), AccessClass.PUBLIC)
    m_c2 = DocumentManifest("doc-c2", "1", _doc_sha(t_c2), len(t_c2), "text/plain", "tr", "OEM", AuthorityClass.OEM_MANUAL, "2025-01-01", ApplicabilityScope(ApplicabilityKind.SPECIFIC, model="Model-X"), AccessClass.PUBLIC)
    chunks = [
        KnowledgeChunk("c-priv", "doc-priv", "1", t_priv, SourceAnchor("doc-priv", "1", _doc_sha(t_priv), "1"), m_priv.applicability, AccessClass.WORKSHOP_INTERNAL, m_priv.allowed_principal_kinds, AuthorityClass.WORKSHOP_POLICY, "2025-01-01"),
        KnowledgeChunk("c-c1", "doc-c1", "1", t_c1, SourceAnchor("doc-c1", "1", _doc_sha(t_c1), "1"), m_c1.applicability, AccessClass.PUBLIC, m_c1.allowed_principal_kinds, AuthorityClass.OEM_MANUAL, "2025-01-01", claim_key="interval", claim_value="10000_km"),
        KnowledgeChunk("c-c2", "doc-c2", "1", t_c2, SourceAnchor("doc-c2", "1", _doc_sha(t_c2), "1"), m_c2.applicability, AccessClass.PUBLIC, m_c2.allowed_principal_kinds, AuthorityClass.OEM_MANUAL, "2025-01-01", claim_key="interval", claim_value="20000_km"),
    ]
    embedder = _DeterministicFakeEmbedder()
    snap = build_index_snapshot(snapshot_id="g4-rag", manifests=[m_priv, m_c1, m_c2], chunks=chunks, embedding_provider=embedder)
    retriever = OfflineRagRetriever(snapshot=snap, embedding_provider=embedder)
    anon = AccessContext(session_id="sess-g4-06", principal=anonymous_principal(), channel="voice", state_revision=1)
    assert all(h.chunk.chunk_id != "c-priv" for h in retriever.retrieve(query_text="Dahili servis prosedürü", access=anon).hits)
    conflict_res = retriever.retrieve(query_text="Model-X bakım aralığı", access=anon, vehicle_model="Model-X")
    assert conflict_res.abstained and conflict_res.support.status == SupportStatus.CONFLICT

    # 5. F6-B BoundedPlaybackQueue capacity exhaustion -> bounded reject & clean close
    out_ref = StreamRef("sess-g4-06", "out-0", StreamDirection.OUTPUT, 1)
    coord = GlobalCapacityCoordinator(max_total_frames=2, max_total_bytes=640)
    budget = CapacityBudget(max_frames=2, max_target_samples=320, max_payload_bytes=640, high_watermark_frames=2, low_watermark_frames=1)
    q = BoundedPlaybackQueue(session_id="sess-g4-06", incarnation_id="inc-1", stream_ref=out_ref, budget=budget, clock=clock, global_coordinator=coord)
    q.set_active_generation(gref)
    r_ok = q.try_reserve(generation_ref=gref, frames=2, target_samples=320, payload_bytes=640)
    assert r_ok.status.value == "RESERVED"
    r_full = q.try_reserve(generation_ref=gref, frames=1, target_samples=160, payload_bytes=320)
    assert r_full.status.value != "RESERVED"


# ---------------------------------------------------------------------------
# G4.22 / G4.24: Privacy Projection & Honest Scope Disposition
# ---------------------------------------------------------------------------


def test_g4_07_privacy_projection_and_honest_scope_disposition() -> None:
    traces = TraceStore()
    traces.start_span(trace_id="tr-g4-07", span_id="sp-g4", name="g4.synthetic", session_id="sess-g4-07", turn_id=1, generation_id=1, start_monotonic_ns=100, clock_domain="server_mono")
    traces.finish_span(trace_id="tr-g4-07", span_id="sp-g4", end_monotonic_ns=200, clock_domain="server_mono", status=SpanStatus.OK)
    proj = Projection().project(
        {"session_id": "sess-g4-07", "status": "PASS", "source_class": "MOCK_RUNTIME"},
        extra_allowlist=frozenset({"session_id", "status", "source_class"}),
    )
    assert proj is not None and PIISecretScanner.scan_object(proj) == []

    g4_synthetic_gates = [
        GateRecord("T0_T1_DETERMINISTIC", True, GateStatus.PASS, "Deterministic synthetic contract & unit suite PASS", ("ev",)),
        GateRecord("T3_MOCK_E2E", True, GateStatus.PASS, "Web 16k & AudioSocket 8k T3-mock E2E PASS", ("ev",)),
        GateRecord("T4_FAULT_INJECTION", True, GateStatus.PASS, "Deterministic fault injection, quarantine, ACL & cleanup PASS", ("ev",)),
    ]
    summary = evaluate_gates(g4_synthetic_gates)
    assert summary.ready is True and summary.overall == GateStatus.PASS
