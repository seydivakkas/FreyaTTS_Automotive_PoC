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
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any
from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.audio_frontend import (
    AdaptationDecision,
    AecOutputStatus,
    AudioInputPipeline,
    BoundedNlmsAec,
    DeliveryStatus as F0RefDeliveryStatus,
    DoubleTalkCategory,
    DoubleTalkClassifier,
    EnvironmentProfileId,
    NccDelayEstimator,
    PHONE_8K_PROFILE,
    PlaybackReferenceReader,
    ReferenceAssociation,
    ReferenceChunk,
    WEB_16K_48K_PROFILE,
    compute_erle_db,
    default_audio_frontend_config,
    resolve_enhancement_profile,
)
from backend.audio_rendering import (
    AUDIOSOCKET_AUDIO,
    AdaptiveCrossfadeAssembler,
    AudioRenderingPipeline,
    AudioSocketOutboundAdapter,
    AudioSocketStreamParser,
    BoundaryRef,
    BoundedPlaybackQueue,
    CapacityBudget,
    CodecCapabilityStatus,
    CodecKind,
    CodecTrial,
    CodecTrialSpec,
    EnhancedDSPProcessor,
    EnhancedDSPProfile,
    GlobalCapacityCoordinator,
    PauseTargetKind,
    PlaybackReferenceTap,
    RateOwner,
    ReferenceDeliveryState,
    SemanticPauseLedger,
    WSOLAAdapter,
    WebTransportAdapter,
    get_codec_capability,
    observe_boundary_silence,
    resolve_rate_ownership,
)
from backend.core.configuration import ConfigSource, SupervisorMode, build_snapshot, resolve_configuration
from backend.core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    ASROutcome,
    ASRStatus,
    AudioEncoding,
    AudioFormat,
    AudioFrame,
    CapabilityState,
    CatalogStatus,
    ConfirmationStatus,
    DialogueOutcome,
    DialogueResponse,
    EventEnvelope,
    GenerationRef,
    ObservationScope,
    PlaybackProfile,
    ProviderMode,
    RenderedFrame,
    SessionIdentity,
    StreamDirection,
    StreamRef,
    ToolReceiptStatus,
    TurnRef,
    Utterance,
)
from backend.core.model_registry import ModelRegistry, VoiceProfileRegistry
from backend.core.runtime import BoundedMediaQueue, QueuedMediaItem, SessionContext
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.turn_generation import PauseController, PauseState
from backend.db import Base, Slot, Vehicle, pragmas
from backend.linguistic_frontend import (
    CliticType,
    FreyaVocabularyValidator,
    INTENT_PROSODY_TABLE,
    LexiconAdapter,
    LinguisticFrontendPipeline,
    PlanningOutcome,
    RealizationDecisionKind,
    VariantGovernanceStatus,
    VocabularyStatus,
    analyze_f4b_morphology,
    plan_f4c_prosody_and_chunks,
    resolve_intent_prosody,
    resolve_vowel_harmony,
)
from backend.linguistic_frontend.text_mapping import SpanMappingEntry, TextMapping
from backend.neural_synthesis import (
    BASELINE_SOLVER,
    AdaptiveProfileSelector,
    BatchCandidate,
    CacheEligibilityKind,
    DeadlineBatchFormer,
    DiscreteSolverDescriptor,
    DurationDecision,
    DurationEstimate,
    IsolatedRngAdapter,
    ModelResidencyAdapter,
    NeuralSynthesisPipeline,
    QualityGuard,
    RAW_AUDIO_FORMAT,
    SameSeedRecoveryPolicy,
    SolverProfile,
    StrictSynthesisCacheAdapter,
    SynthesisModelHandles,
    SynthesisTelemetry,
    VersionedCacheStore,
    load_static_char_vocab,
    pin_synthesis_snapshot,
    resolve_default_snapshot,
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
    PronunciationVariant,
    load_lexicon_snapshot,
)
from backend.speech_recognition import (
    ASRDeliveryStatus,
    ASRLifecycleManager,
    ASRRouteMode,
    ASRTelemetryBridge,
    ASRUtteranceAdmission,
    ContextHintSnapshot,
    ContinuationCue as F2ContinuationCue,
    DecodeBeamProfile,
    HotwordPlanner,
    InMemoryASRConsumer,
    PartialLaneState,
    PseudoStreamingController,
    SpeechRecognitionPipeline,
    SpeechScopeRef,
    StreamingWindowConfig,
    WhisperSchedulerEngine,
    pin_lexicon_snapshot,
    resolve_asr_config,
)
from backend.supervisor.contracts import ConversationContext, Intent, IntentCandidate
from backend.supervisor.dialogue_facade import BoundedDialogueConsumer, DialogueFacade
from backend.supervisor.intent_router import (
    EffectClass,
    HierarchicalIntentRouter,
    RouteDisposition,
    RouteLevel,
    decompose_multi_intent,
)
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
from backend.supervisor.workflow_dag import (
    NodeKind,
    NodeResult,
    NodeStatus,
    WorkflowDagExecutor,
    WorkflowNode,
    WorkflowPlan,
)
from backend.voice_activity import (
    AcousticEvidence,
    BackchannelCategory,
    BoundedUtteranceQueue,
    ContinuationCue as F1ContinuationCue,
    EchoAcousticCategory,
    EndpointAdviceKind,
    ExpectedSlotCategory,
    ExpectedSlotProjection,
    F1CProfileConfig,
    F1ProfileConfig,
    F1RouteMode,
    FlushIntent as F1FlushIntent,
    InputCandidateRef,
    InterruptionAdviceKind,
    InterruptionController,
    InterruptionState,
    M02PauseBridge,
    M02TurnAllocatorBridge,
    OutputAvailability,
    OutputTargetSnapshot,
    SemanticEndpointHint as F1SemanticEndpointHint,
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
W2_RUN_ID = "20261126T032114Z"


# ---------------------------------------------------------------------------
# Test-only external model/provider doubles (no F0-F6 layer replacement)
# ---------------------------------------------------------------------------


class _ScriptedVADModel:
    model_revision = "fake_g2_silero_v1"

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
    def __init__(self, text: str, start: float = 0.0, end: float = 1.3, words=None) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.avg_logprob = -0.2
        self.no_speech_prob = 0.05
        self.compression_ratio = 1.1
        self.words = words


class _ScriptedWhisperModel:
    def __init__(self, outputs: list[tuple[str, list[dict[str, Any]]]]) -> None:
        self._outputs = outputs
        self._idx = 0

    def transcribe(self, audio: np.ndarray, **kwargs: Any):
        text, words = self._outputs[min(self._idx, len(self._outputs) - 1)]
        self._idx += 1
        return [_FakeWhisperSeg(text, words=words or None)], SimpleNamespace(language="tr", language_probability=0.98)


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
            err = RuntimeError("transient_ode_failure")
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


def _doc_sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _DeterministicFakeEmbedder:
    revision = "fixture-fake-embed-v1"
    dimension = 4

    def _embed(self, text: str) -> tuple[float, ...]:
        toks = set(tokenize_turkish(text))
        return (
            1.0 if "bakım" in toks or "periyodik" in toks else 0.1,
            1.0 if "fren" in toks or "uyarı" in toks else 0.1,
            1.0 if "dsg" in toks or "şanzıman" in toks else 0.1,
            1.0 if "garanti" in toks or "servis" in toks else 0.1,
        )

    def embed_query(self, query: str) -> tuple[float, ...]:
        return self._embed(query)

    def embed_documents(self, texts) -> tuple[tuple[float, ...], ...]:
        return tuple(self._embed(t) for t in texts)


# ---------------------------------------------------------------------------
# G2 Gate Tests: Prerequisites, Passive Imports, Cross-Domain W3+W4 Integration
# ---------------------------------------------------------------------------


def test_g2_01_prereqs_w2_and_all_w34_packages_accepted() -> None:
    w2_acc = json.loads((REPO_ROOT / "docs" / "freya2" / "w2_integration" / W2_RUN_ID / "W2_ACCEPTANCE_MATRIX.json").read_text(encoding="utf-8"))
    assert w2_acc["overall"] == "PASS"
    assert w2_acc["w2_vertical_slice_accepted"] is True
    assert w2_acc["f1_b_ready"] is True

    expected_w34 = (
        ("f0_b", ("f0_b_ready",)),
        ("f1_bc", ("f1_b_ready", "f1_c_ready")),
        ("f2_bc", ("f2_b_ready", "f2_c_ready")),
        ("f3_bc", ("f3_b_ready", "f3_c_ready")),
        ("f4_bc", ("f4_b_ready", "f4_c_ready")),
        ("f5_bc", ("f5_b_ready", "f5_c_ready")),
        ("f6_bc", ("f6_b_ready", "f6_c_ready")),
    )
    for pkg, keys in expected_w34:
        root = REPO_ROOT / "docs" / "freya2" / pkg
        runs = sorted(p.name for p in root.iterdir() if p.is_dir())
        assert len(runs) >= 1, f"missing {pkg} run"
        data = json.loads((root / runs[-1] / "ACCEPTANCE_MATRIX.json").read_text(encoding="utf-8"))
        assert data.get("overall") == "PASS", f"{pkg} not PASS"
        for k in keys:
            assert data.get(k) is True, f"{pkg}.{k} not True"


def test_g2_02_passive_imports_zero_threads_no_torch() -> None:
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


def test_g2_03_f6b_reference_tap_to_f0b_aec_double_talk_and_f1c_advice() -> None:
    clock = HarnessClock(initial_ns=1_000_000_000, clock_domain="server_mono")
    out_ref = StreamRef("sess-g2-03", "out-0", StreamDirection.OUTPUT, format_epoch=1)
    gref = GenerationRef("sess-g2-03", 1, 1)

    # 1. F6-B PlaybackReferenceTap captures submitted frames -> F0-B PlaybackReferenceReader
    tap = PlaybackReferenceTap(session_id="sess-g2-03", stream_id="out-0", format_epoch=1, max_frames=32, max_bytes=32 * 640)
    assoc = ReferenceAssociation(session_id="sess-g2-03", input_stream_id="in-0", input_format_epoch=1, output_stream_ref=out_ref)
    ref_reader = PlaybackReferenceReader(assoc, target_rate_hz=16000, max_history_samples=16000)

    rng = np.random.default_rng(77)
    far_16k = (0.35 * rng.standard_normal(320 * 10)).astype(np.float32)
    for seq in range(10):
        blk = far_16k[seq * 320 : (seq + 1) * 320]
        pcm_bytes = (np.clip(blk, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        frame = RenderedFrame(
            generation_ref=gref,
            stream_ref=out_ref,
            sequence=seq,
            sample_offset=seq * 320,
            profile=PlaybackProfile.WEB_16K_PCM16,
            format=AudioFormat(16000, 1, AudioEncoding.PCM_S16LE),
            frame_duration_ms=20.0,
            sample_count=320,
            valid_sample_count=320,
            payload=pcm_bytes,
        )
        tap_rec = tap.record_claim(claim_id=f"c-{seq}", frame=frame, claim_ns=clock.monotonic_ns(), clock_domain=clock.clock_domain)
        assert tap_rec is not None
        tap.update_delivery_state(f"c-{seq}", ReferenceDeliveryState.COMPLETED_LOCAL)
        decoded_f32 = (np.frombuffer(frame.payload, dtype="<i2").astype(np.float32)) / np.float32(32768.0)
        pushed = ref_reader.push_reference_chunk(
            ReferenceChunk(
                stream_ref=out_ref,
                generation_id=1,
                sequence=seq,
                sample_offset=seq * 320,
                sample_rate_hz=16000,
                samples=decoded_f32,
                valid_sample_count=320,
                claimed_monotonic_ns=clock.monotonic_ns(),
                clock_domain=clock.clock_domain,
                observation_scope=ObservationScope.SERVER,
                delivery_status=F0RefDeliveryStatus.COMPLETED_LOCAL,
            )
        )
        assert pushed is True
        clock.advance_ms(20)

    tap_view = tap.read_range(session_id="sess-g2-03", stream_id="out-0", format_epoch=1, start_sample=0, end_sample=3200)
    assert len(tap_view.spans) == 10

    # 2. F0-B AudioInputPipeline with MOVING_CAR adaptive DSP + AEC consumes reference reader
    for prof_id in EnvironmentProfileId:
        prof = resolve_enhancement_profile(prof_id)
        assert prof.profile_id == prof_id

    cfg = default_audio_frontend_config(
        f0_b_adaptive_dsp_enabled=True,
        f0_b_aec_enabled=True,
        environment_profile=EnvironmentProfileId.MOVING_CAR,
    )
    emitted: list[AudioFrame] = []
    in_ref = StreamRef("sess-g2-03", "in-0", StreamDirection.INPUT, format_epoch=1)
    f0_pipe = AudioInputPipeline(session_id="sess-g2-03", config=cfg, clock=clock, f1_consumer=emitted.append, reference_source=ref_reader)
    f0_pipe.open_stream(in_ref, sample_rate_hz=16000)

    mic_echo_pcm = (np.clip(far_16k[:320] * 0.4, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    ing = f0_pipe.ingest_raw(
        stream_ref=in_ref,
        payload=mic_echo_pcm,
        sample_rate_hz=16000,
        sample_count=320,
        sequence=0,
        sample_offset=0,
        captured_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
    )
    assert ing.ok is True and ing.route == "f0b_adaptive:MOVING_CAR"
    assert ing.acoustic_evidence is not None
    assert len(emitted) == 1

    # 3. NccDelayEstimator + BoundedNlmsAec + DoubleTalkClassifier -> F1-C InterruptionAdvice
    ref_hist = (0.3 * rng.standard_normal(4000)).astype(np.float32)
    lag = 96
    mic_delayed = ref_hist[4000 - 1280 - lag : 4000 - lag] * 0.5
    delay = NccDelayEstimator(sample_rate_hz=16000).estimate(mic_delayed, ref_hist)
    assert delay.lag_samples == lag

    aec = BoundedNlmsAec(sample_rate_hz=16000, filter_len_ms=16.0, mu=0.4)
    dt = DoubleTalkClassifier()
    echo = np.zeros_like(far_16k)
    echo[:] += 0.5 * far_16k[:]
    last_erle = None
    for i in range(0, len(far_16k) - 320, 320):
        m_blk = echo[i : i + 320]
        r_blk = far_16k[i : i + 320]
        ev = dt.classify(mic_samples=m_blk, aligned_ref_samples=r_blk, delay_confident=True)
        out_blk = aec.process_block(m_blk, r_blk, adaptation=ev.adaptation_decision)
        if i >= len(far_16k) // 2:
            last_erle = compute_erle_db(m_blk, out_blk.samples)
    assert last_erle is not None and last_erle > 5.0

    # Double-talk freeze + F1-C advice mapping
    near_end = _make_speech_like_signal(320, sr=16000, amp=0.35, seed=9)
    dt_ev = dt.classify(mic_samples=near_end + echo[:320], aligned_ref_samples=far_16k[:320], residual_samples=near_end + echo[:320], delay_confident=True)
    assert dt_ev.category == DoubleTalkCategory.DOUBLE_TALK_LIKELY
    assert dt_ev.adaptation_decision == AdaptationDecision.FREEZE
    frozen = aec.process_block(near_end + echo[:320], far_16k[:320], adaptation=dt_ev.adaptation_decision)
    assert frozen.output_status == AecOutputStatus.FROZEN_FILTER

    f1c = SemanticEndpointPolicy(F1CProfileConfig(mode=F1RouteMode.STRICT, enable_echo_rejection=True), in_ref, clock=clock)
    f1c.ingest_acoustic_evidence(
        AcousticEvidence(
            evidence_id="ev-dt-g2",
            stream_ref=in_ref,
            start_sample=0,
            end_sample_exclusive=320,
            sample_rate_hz=16000,
            observed_monotonic_ns=clock.monotonic_ns(),
            clock_domain=clock.clock_domain,
            category=EchoAcousticCategory.DOUBLE_TALK_LIKELY,
        )
    )
    adv = f1c.advise_interruption(window_start_sample=0, window_end_sample_exclusive=320, has_active_output=True)
    assert adv.kind == InterruptionAdviceKind.COMMIT_ELIGIBLE

    # Browser native AEC prevents double AEC
    browser_cfg = default_audio_frontend_config(
        f0_b_adaptive_dsp_enabled=True, f0_b_aec_enabled=True, browser_native_aec_active=True
    )
    f0_browser = AudioInputPipeline(session_id="sess-g2-br", config=browser_cfg, reference_source=ref_reader)
    br_res = f0_browser.ingest_raw(
        stream_ref=StreamRef("sess-g2-br", "in-0", StreamDirection.INPUT, 1),
        payload=np.zeros(320, dtype="<i2").tobytes(),
        sample_rate_hz=16000,
        sample_count=320,
        sequence=0,
        sample_offset=0,
    )
    assert br_res.acoustic_evidence is not None and br_res.acoustic_evidence.aec_status == AecOutputStatus.BYPASS
    f0_browser.close()
    f0_pipe.close()
    ref_reader.close()


@pytest.mark.asyncio
async def test_g2_04_f1b_two_stage_barge_in_with_f6b_bounded_queue_flush_receipt() -> None:
    clock = HarnessClock(initial_ns=1_000_000_000, clock_domain="g2.fake.clock")
    pause_ctrl = PauseController()
    flushes: list[F1FlushIntent] = []
    bridge = M02PauseBridge(pause_ctrl, on_flush_intent=flushes.append)
    root = CancellationScope("sess:g2-04", clock=clock)
    gen_scope = root.child_scope("gen:1")

    ctrl = InterruptionController("sess-g2-04", "inc-1", bridge, clock=clock)
    in_ref = StreamRef("sess-g2-04", "in-0", StreamDirection.INPUT, 1)
    out_ref = StreamRef("sess-g2-04", "out-0", StreamDirection.OUTPUT, 1)
    gref = GenerationRef("sess-g2-04", 1, 1)

    # Stage 1: soft pause -> false candidate rejected -> resume same generation
    cand1 = InputCandidateRef("sess-g2-04", "inc-1", in_ref, start_sample=5120, sequence=1)
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
    s1 = ctrl.on_speech_candidate(cand1, target, gen_scope)
    assert s1.state == InterruptionState.SOFT_PAUSED
    assert s1.in_flight_possible is True and s1.in_flight_recall_claimed is False
    assert pause_ctrl.state == PauseState.SOFT_PAUSED

    clock.advance_ms(80)
    r1 = ctrl.on_candidate_rejected(cand1, gen_scope, cursor_intact=True)
    assert r1.state == InterruptionState.RESUMED
    assert pause_ctrl.state == PauseState.RUNNING

    # Stage 2: F6-B BoundedPlaybackQueue + confirmed barge-in -> FlushReceipt
    coord = GlobalCapacityCoordinator(max_total_frames=8, max_total_bytes=2560)
    budget = CapacityBudget(max_frames=4, max_target_samples=640, max_payload_bytes=1280, high_watermark_frames=4, low_watermark_frames=1)
    q = BoundedPlaybackQueue(session_id="sess-g2-04", incarnation_id="inc-1", stream_ref=out_ref, budget=budget, clock=clock, global_coordinator=coord)
    q.set_active_generation(gref)
    res = q.try_reserve(generation_ref=gref, frames=3, target_samples=480, payload_bytes=960)
    assert res.status.value == "RESERVED"
    frames = [
        RenderedFrame(
            generation_ref=gref,
            stream_ref=out_ref,
            sequence=i,
            sample_offset=i * 160,
            profile=PlaybackProfile.AUDIOSOCKET_8K_PCM16,
            format=AudioFormat(8000, 1, AudioEncoding.PCM_S16LE),
            frame_duration_ms=20.0,
            sample_count=160,
            valid_sample_count=160,
            payload=b"\x01" * 320,
        )
        for i in range(3)
    ]
    ok, _ = await q.convert_and_enqueue(res.reservation_id, frames)
    assert ok is True
    q.select_next_unsent()
    q.mark_selected_claimed("claim-0")

    cand2 = InputCandidateRef("sess-g2-04", "inc-1", in_ref, start_sample=10240, sequence=2)
    s2 = ctrl.on_speech_candidate(cand2, target, gen_scope, defer_pause_ack=True)
    assert s2.state == InterruptionState.PAUSE_REQUESTED

    m02_q = BoundedMediaQueue(max_items=8, max_bytes=4096)
    m02_q.enqueue(QueuedMediaItem(gref, 1, b"\x01" * 320, 1))
    commit = ctrl.on_speech_confirmed(cand2, gen_scope, queue=m02_q, reason="confirmed_barge")
    assert commit.state == InterruptionState.COMMITTED
    assert gen_scope.is_cancel_requested is True
    assert len(flushes) == 1

    # F6-B scoped flush receipt separates local SERVER purge vs remote PBX unsupported
    f6_pipe = AudioRenderingPipeline(session_id="sess-g2-04", trusted_channel="asterisk", clock=clock, max_queue_items=4, max_queue_bytes=1280)
    await f6_pipe.start_generation()
    f6_receipt = await f6_pipe.commit_interrupt_with_receipt(reason="user_barge_in")
    assert f6_receipt.local.scope == ObservationScope.SERVER
    assert f6_receipt.local.status == "FLUSHED"
    assert f6_receipt.remote.scope == ObservationScope.PBX
    assert f6_receipt.remote.status == "UNSUPPORTED"
    assert f6_receipt.audible_silence_verified is False
    await f6_pipe.close()


@pytest.mark.asyncio
async def test_g2_05_f2bc_hotwords_partial_to_final_and_f1c_semantic_endpoint_extension() -> None:
    clock = HarnessClock(initial_ns=1_000_000_000, clock_domain="g2.fake.clock")
    cfg = resolve_configuration(overrides={"auto_load_models": False}, env={"STT_CATALOG_HOTWORDS": "true", "STT_MIN_RMS": "0.0"}).snapshot
    pinned_asr = resolve_asr_config(cfg, route_mode=ASRRouteMode.STRICT)
    lex_reg = _build_enriched_lexicon()
    pinned_lex = pin_lexicon_snapshot(lex_reg)
    sched = _build_scheduler(clock)

    # 1. F2-B HotwordPlanner with ContextHintSnapshot + PII scrub
    ctx_hint = ContextHintSnapshot(
        session_id="sess-g2-05",
        incarnation_id="inc-1",
        state_revision=2,
        source_turn_id=1,
        captured_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
        lexicon_revision=lex_reg.lexicon_revision,
        confirmed_entity_ids=("brand:nissan", "model:qashqai"),
        service_categories=("periyodik bakım", "PII_SENTINEL_NAME"),
    )
    hw_plan = HotwordPlanner(max_items=4, max_chars=48, max_tokens=16).plan(
        scope_id="utt-g2-05",
        session_id="sess-g2-05",
        incarnation_id="inc-1",
        pinned_lexicon=pinned_lex,
        now_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
        context_hint=ctx_hint,
    )
    assert hw_plan.context_used is True
    assert "PII_SENTINEL_NAME" not in hw_plan.terms

    # 2. F2-C PseudoStreamingController: partial -> stable prefix -> continuation hint -> seal -> P1 final
    scripted = [
        ("Aracım Nissan", [{"word": "Aracım", "start": 0.0, "end": 0.4}, {"word": "Nissan", "start": 0.4, "end": 0.8}]),
        ("Aracım Nissan Qashqai", [{"word": "Aracım", "start": 0.0, "end": 0.35}, {"word": "Nissan", "start": 0.35, "end": 0.7}, {"word": "Qashqai", "start": 0.7, "end": 1.2}]),
        ("Nissan Qashqai değil", [{"word": "Nissan", "start": 0.0, "end": 0.4}, {"word": "Qashqai", "start": 0.4, "end": 0.9}, {"word": "değil", "start": 0.9, "end": 1.3}]),
        ("Aracım Nissan Qashqai değil, Juke.", []),
    ]
    scripted_model = _ScriptedWhisperModel(scripted)
    engine = WhisperSchedulerEngine(sched, model_getter=lambda: scripted_model)
    ctrl = PseudoStreamingController(engine=engine, config=StreamingWindowConfig(), pinned_lexicon=pinned_lex)
    in_ref = StreamRef("sess-g2-05", "in-0", StreamDirection.INPUT, 1)
    audio_fmt = AudioFormat(16000, 1, AudioEncoding.FLOAT32_LE)
    ctrl.open_scope(SpeechScopeRef("sess-g2-05", "inc-1", in_ref, "speech-g2-05", start_sample=0, turn_ref=None))

    ctrl.append_audio("speech-g2-05", np.full(12_800, 0.02, dtype=np.float32), audio_format=audio_fmt)
    w1 = ctrl.plan_next_window("speech-g2-05", pinned_config=pinned_asr)
    assert w1 is not None
    r1 = await ctrl.run_partial_window(w1, pinned_config=pinned_asr, audio_format=audio_fmt)
    assert r1 is not None and r1.status == ASRStatus.PARTIAL

    ctrl.append_audio("speech-g2-05", np.full(8_000, 0.02, dtype=np.float32), audio_format=audio_fmt)
    w2 = ctrl.plan_next_window("speech-g2-05", pinned_config=pinned_asr)
    assert w2 is not None
    r2 = await ctrl.run_partial_window(w2, pinned_config=pinned_asr, audio_format=audio_fmt)
    assert r2 is not None and r2.status == ASRStatus.STABLE_PREFIX and r2.stable_prefix is not None and r2.stable_prefix.startswith("Aracım")

    ctrl.append_audio("speech-g2-05", np.full(8_000, 0.02, dtype=np.float32), audio_format=audio_fmt)
    w3 = ctrl.plan_next_window("speech-g2-05", pinned_config=pinned_asr)
    assert w3 is not None
    r3 = await ctrl.run_partial_window(w3, pinned_config=pinned_asr, audio_format=audio_fmt)
    assert r3 is not None
    f2_hint = ctrl.get_semantic_hint("speech-g2-05")
    assert f2_hint is not None
    assert f2_hint.continuation_cue == F2ContinuationCue.POSSIBLE_CONTINUATION

    # 3. Bridge F2-C hint into F1-C SemanticEndpointPolicy inside StreamAcousticProcessor
    f1c_policy = SemanticEndpointPolicy(F1CProfileConfig(mode=F1RouteMode.STRICT, base_budget_ms=320, max_budget_ms=1200), in_ref, clock=clock)
    f1_ctx = SessionContext(SessionIdentity("sess-g2-05", trace_id="tr-g2-05"), clock=clock)
    await f1_ctx.open()
    f1_queue = BoundedUtteranceQueue(max_items=8, max_bytes=4_000_000)
    f1_proc = StreamAcousticProcessor(
        in_ref,
        profile=F1ProfileConfig.strict_experimental(route_mode=F1RouteMode.STRICT),
        config_revision=cfg.config_revision,
        vad_engine=VADEngineAdapter(_ScriptedVADModel([0.9, 0.9, 0.9] + [0.1] * 12), clock=clock),
        turn_allocator=M02TurnAllocatorBridge(f1_ctx),
        consumer=f1_queue,
        clock=clock,
        ledger=f1_ctx.ledger,
        session_context=f1_ctx,
        f1c_policy=f1c_policy,
    )
    pcm = (np.ones(512, dtype=np.int16) * 1000).tobytes()
    s16_fmt = AudioFormat(16000, 1, AudioEncoding.PCM_S16LE)
    for i in range(3):
        f1_proc.process_frame(AudioFrame(CONTRACT_SCHEMA_VERSION, in_ref, i, s16_fmt, 512, i * 512, pcm))

    assert f1c_policy.ingest_hint(
        F1SemanticEndpointHint(
            hint_id=f2_hint.hint_id,
            speech_scope_id="speech-g2-05",
            stream_ref=in_ref,
            revision=f2_hint.revision,
            covered_end_sample_exclusive=1536,
            observed_monotonic_ns=clock.monotonic_ns(),
            ttl_ms=750,
            clock_domain=clock.clock_domain,
            cue=F1ContinuationCue(f2_hint.continuation_cue.value),
        )
    )
    # 10 low windows (320 ms) stay SILENCE_PENDING due to F1-C semantic extension
    for i in range(3, 13):
        out = f1_proc.process_frame(AudioFrame(CONTRACT_SCHEMA_VERSION, in_ref, i, s16_fmt, 512, i * 512, pcm))
        assert out.finalizations == ()
    _, eos_fins = f1_proc.flush_eos()
    assert len(eos_fins) == 1
    utt = eos_fins[0].utterance
    assert utt.finalization_reason == "EXPLICIT_EOS"
    assert utt.turn_ref is not None

    # 4. Seal F2-C partial lane and execute authoritative F2-B P1 final decode
    binding = ctrl.seal_for_finalization("speech-g2-05", utterance=utt, turn_ref=utt.turn_ref, final_claim_id="claim-g2-05")
    assert ctrl.get_state("speech-g2-05") == PartialLaneState.SEALED_FINALIZING
    asr_pipe = SpeechRecognitionPipeline(
        engine=engine,
        admission=ASRUtteranceAdmission(),
        consumer=InMemoryASRConsumer(),
        telemetry=ASRTelemetryBridge(),
        lifecycle=ASRLifecycleManager(),
    )
    final_rec = await asr_pipe.process_utterance(
        utt,
        audio_fmt,
        session_ctx=f1_ctx,
        pinned_config=pinned_asr,
        lexicon_registry=lex_reg,
        context_hint=ctx_hint,
        enable_f2b=True,
        beam_profile=DecodeBeamProfile.FAST_FINAL,
        min_revision=binding.sealed_partial_high_watermark + 1,
    )
    assert final_rec.delivery.delivery_status == ASRDeliveryStatus.DELIVERED
    assert final_rec.result is not None
    assert final_rec.result.status == ASRStatus.FINAL
    assert final_rec.result.revision > binding.sealed_partial_high_watermark
    assert any(e.catalog_status == CatalogStatus.UNVERIFIED and e.confirmation_status == ConfirmationStatus.CANDIDATE for e in final_rec.result.entities)
    ctrl.mark_terminal("speech-g2-05")
    await f1_ctx.close("done")


@pytest.mark.asyncio
async def test_g2_06_f3bc_hierarchical_router_rag_multi_intent_dag_and_m07_gate(tmp_path: Path) -> None:
    # 1. HierarchicalIntentRouter (L0-L5)
    router = HierarchicalIntentRouter()
    emerg = await router.route(
        asr_result=SimpleNamespace(
            status=ASRStatus.FINAL,
            outcome=ASROutcome.OK,
            raw_transcript="Yoldayım, frenler tutmuyor",
            normalized_transcript="yoldayım, frenler tutmuyor",
            canonical_transcript="yoldayım, frenler tutmuyor",
            entities=(),
            protected_spans=(),
            confidence=0.95,
        ),
        context=ConversationContext(session_id=uuid4(), turn_at=datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)),
    )
    assert emerg.level == RouteLevel.L1_SAFETY_CONTROL
    assert emerg.primary_intent == Intent.ROADSIDE_EMERGENCY

    # 2. OfflineRagRetriever (HYBRID_RRF, WORKSHOP_INTERNAL denied for anon, CONFLICT abstains)
    t_spec = "Model-A periyodik bakım aralığı 15000 km veya 12 aydır."
    t_priv = "Dahili servis prosedürü garanti onayı."
    m_spec = DocumentManifest(
        doc_id="doc-spec",
        revision="1",
        content_sha256=_doc_sha(t_spec),
        byte_size=len(t_spec),
        media_type="text/plain",
        language="tr",
        publisher="OEM",
        authority_class=AuthorityClass.OEM_MANUAL,
        effective_date="2025-01-01",
        applicability=ApplicabilityScope(kind=ApplicabilityKind.SPECIFIC, model="Model-A", year_min=2024, year_max=2024),
        access_class=AccessClass.PUBLIC,
    )
    m_priv = DocumentManifest(
        doc_id="doc-priv",
        revision="1",
        content_sha256=_doc_sha(t_priv),
        byte_size=len(t_priv),
        media_type="text/plain",
        language="tr",
        publisher="Workshop",
        authority_class=AuthorityClass.WORKSHOP_POLICY,
        effective_date="2025-01-01",
        applicability=ApplicabilityScope(kind=ApplicabilityKind.GENERAL),
        access_class=AccessClass.WORKSHOP_INTERNAL,
        allowed_principal_kinds=frozenset({PrincipalKind.OPERATOR}),
    )
    chunks = [
        KnowledgeChunk("c-spec", "doc-spec", "1", t_spec, SourceAnchor("doc-spec", "1", _doc_sha(t_spec), "1.1"), m_spec.applicability, AccessClass.PUBLIC, m_spec.allowed_principal_kinds, AuthorityClass.OEM_MANUAL, "2025-01-01", claim_key="interval", claim_value="15000_km"),
        KnowledgeChunk("c-priv", "doc-priv", "1", t_priv, SourceAnchor("doc-priv", "1", _doc_sha(t_priv), "2.1"), m_priv.applicability, AccessClass.WORKSHOP_INTERNAL, m_priv.allowed_principal_kinds, AuthorityClass.WORKSHOP_POLICY, "2025-01-01"),
    ]
    embedder = _DeterministicFakeEmbedder()
    snap = build_index_snapshot(snapshot_id="g2-rag", manifests=[m_spec, m_priv], chunks=chunks, embedding_provider=embedder)
    retriever = OfflineRagRetriever(snapshot=snap, embedding_provider=embedder)
    anon = AccessContext(session_id="sess-g2-06", principal=anonymous_principal(), channel="voice", state_revision=1)

    priv_res = retriever.retrieve(query_text="Dahili servis prosedürü garanti onayı", access=anon)
    assert all(h.chunk.chunk_id != "c-priv" for h in priv_res.hits)
    match_res = retriever.retrieve(query_text="Model-A periyodik bakım aralığı nedir", access=anon, vehicle_model="Model-A", vehicle_year=2024)
    assert match_res.branch_mode == "HYBRID_RRF" and not match_res.abstained and match_res.support.status == SupportStatus.SUPPORTED

    # 3. Multi-intent decomposition + WorkflowDagExecutor + M07 security gate
    subs = decompose_multi_intent("34 ABC 123 plakalı aracımın bakım aralığı nedir ve yarın randevu almak istiyorum")
    assert len(subs) == 2 and subs[0].effect_class == EffectClass.READ and subs[1].effect_class == EffectClass.MUTATION

    from sqlalchemy import event
    db_path = tmp_path / "g2_crm.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    event.listen(engine, "connect", pragmas)
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, expire_on_commit=False)
    target_day = datetime.now(timezone.utc).date() + timedelta(days=1)
    slot_start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
    with sf() as db:
        db.add(Vehicle(id="veh-g2", description="Nissan Qashqai 2024", plate="34 G2 01"))
        db.add(Slot(id="slot-g2", starts_at=slot_start.isoformat()))
        db.commit()

    audit = SecurityAuditLog(tmp_path / "audit.db")
    policy = PolicyEngine(audit_log=audit)
    confirm = ConfirmationManager(audit_log=audit)
    idem = DurableIdempotencyStore(tmp_path / "idem.db", audit_log=audit)
    wf = WorkflowAdapter(policy_engine=policy, confirmation_manager=confirm, idempotency_store=idem, audit_log=audit, session_factory=sf, provider_mode=ProviderMode.MOCK)
    cust = verified_principal("cust-g2", kind=PrincipalKind.CUSTOMER, auth_strength=AuthStrength.STRONG_VERIFIED, evidence_source=EvidenceSource.MFA_VERIFIED)
    access = AccessContext(session_id="sess-g2-06", principal=cust, channel="voice", state_revision=1)

    plan = WorkflowPlan(
        workflow_id="wf-g2-06",
        input_ref="in-g2-06",
        context_revision=1,
        nodes=(
            WorkflowNode("n1", NodeKind.READ, "approved_technical_lookup", "TechnicalKnowledge"),
            WorkflowNode("n2", NodeKind.READ, "availability.read", "ServiceBooking"),
            WorkflowNode("n3", NodeKind.MUTATION_PROPOSAL, "booking.create", "ServiceBooking", depends_on=("n2",), requires_confirmation=True),
        ),
    )

    async def _run_read(node: WorkflowNode) -> NodeResult:
        if node.tool_id == "availability.read":
            res = wf.read_availability(access=access, target_day=target_day, now_utc=datetime.now(timezone.utc))
            return NodeResult(node.node_id, node.kind, NodeStatus.SUCCEEDED_READ if res.allowed else NodeStatus.BLOCKED, receipt=res.receipt, data=res.data)
        return NodeResult(node.node_id, node.kind, NodeStatus.SUCCEEDED_READ, data={"answer": match_res.hits[0].chunk.text})

    async def _run_mutation(node: WorkflowNode, _prev) -> NodeResult:
        res = wf.execute_mutation(
            access=access,
            tool_id="booking.create",
            action="create_booking",
            idempotency_key="ik-g2-unconfirmed",
            terms={"selected_slot_id": "slot-g2", "vehicle_ref": "veh-g2", "customer_ref": "cust-g2"},
            challenge_id=None,
        )
        return NodeResult(node.node_id, node.kind, NodeStatus.COMMITTED if res.receipt.status == ToolReceiptStatus.COMMITTED else NodeStatus.BLOCKED, receipt=res.receipt)

    dag_out = await WorkflowDagExecutor().execute(plan, read_runner=_run_read, mutation_runner=_run_mutation)
    assert dag_out.overall_status == "MIXED"
    assert dag_out.results[2].status == NodeStatus.BLOCKED

    # Explicit confirmation -> single COMMITTED MOCK receipt
    booking_terms = {"selected_slot_id": "slot-g2", "vehicle_ref": "veh-g2", "customer_ref": "cust-g2"}
    ch, _ = wf.issue_and_present_confirmation(access=access, tool_id="booking.create", action="create_booking", terms=booking_terms)
    assert ch is not None
    approved_ch, app_err = wf.approve_confirmation(challenge_id=ch.challenge_id, access=access, terms=booking_terms)
    assert approved_ch is not None and app_err is None
    committed = wf.execute_mutation(
        access=access,
        tool_id="booking.create",
        action="create_booking",
        idempotency_key="ik-g2-confirmed",
        terms=booking_terms,
        challenge_id=ch.challenge_id,
    )
    assert committed.receipt.status == ToolReceiptStatus.COMMITTED
    assert committed.receipt.provider_mode == ProviderMode.MOCK
    assert committed.receipt.verified_result is False


def test_g2_07_f4bc_morphology_g2p_prosody_and_all_31_intent_prosody() -> None:
    assert len(INTENT_PROSODY_TABLE) == 31
    assert resolve_vowel_harmony("göz") == ("e", "ü")

    ent = CanonicalEntity(entity_id="brand:peugeottest", canonical_name="PeugeotTest", category=EntityCategory.BRAND, normalized_key="peugeottest")
    var = PronunciationVariant(variant_id="var-prop", canonical_entity_id="brand:peugeottest", surface_key="peugeottest", spoken_text="Pejo", profile="tts_2026", vocab_validated=True)
    snap = load_lexicon_snapshot(extra_entities=(ent,), extra_pronunciations=(var,))
    reg = LexiconRegistry(snap)
    lex_adapter = LexiconAdapter(reg, variant_governance={"var-prop": VariantGovernanceStatus.PROPOSED})
    morph = analyze_f4b_morphology("PeugeotTest'ya bakın.", lexicon_adapter=lex_adapter)
    assert morph.realization_decisions[0].decision == RealizationDecisionKind.PRESERVE
    assert morph.g2p_guidances[0].phone_sequence is not None

    pipe = LinguisticFrontendPipeline(lexicon_registry_provider=lambda: reg, variant_governance={"var-prop": VariantGovernanceStatus.PROPOSED}, require_real_vocab=True)
    resp = DialogueResponse(
        envelope=EventEnvelope(CONTRACT_SCHEMA_VERSION, "dialogue.response", "sess-g2-07", "tr-g2-07", 1, 1, 0, 100, "g2.fake.clock", "f3.dialogue"),
        response_id="resp-g2-07",
        speech_text="Aracınız hazır. Saat 14:30 uygun mu?",
        speech_act="QUESTION",
        state_revision=1,
        outcome=DialogueOutcome.OK,
    )
    f4_res = pipe.prepare_response(resp, generation_ref=GenerationRef("sess-g2-07", 1, 1))
    assert f4_res.ok and f4_res.normalization_passes == 1 and f4_res.plan is not None
    assert f4_res.f4b_morphology is not None and f4_res.f4c_prosody is not None
    assert any(cl.clitic_type == CliticType.QUESTION_MI and not cl.may_split for cl in f4_res.f4c_prosody.clitic_links)
    for vc in f4_res.vocab_checks:
        assert vc.status == VocabularyStatus.PASS

    # Advisory 31-intent prosody table wired into plan_f4c_prosody_and_chunks without mutating text
    text = "Kaza algılandı, acil destek yönlendiriliyor."
    mapping = TextMapping(source_text=text, normalized_text=text, entries=(SpanMappingEntry((0, len(text)), (0, len(text))),))
    chk_res, prosody = plan_f4c_prosody_and_chunks(text, atoms=(), text_mapping=mapping, speech_act="WARNING", intent="kaza_algilandi")
    assert prosody.intent_prosody is not None
    assert prosody.intent_prosody == resolve_intent_prosody("kaza_algilandi")
    assert prosody.intent_prosody.style_token == "<emergency>"
    assert all("<emergency>" not in c.model_text for c in chk_res.chunks)


@pytest.mark.asyncio
async def test_g2_08_f5bc_isolated_rng_cache_quality_recovery_adaptive_solver_and_batching() -> None:
    clock = HarnessClock(initial_ns=1_000_000_000, clock_domain="g2.fake.clock")
    sched = _build_scheduler(clock)

    from backend.core.contracts import ChunkPlan, PlanValidationStatus, SynthesisPlan
    gref = GenerationRef("sess-g2-08", 1, 1)
    plan = SynthesisPlan(
        schema_version=CONTRACT_SCHEMA_VERSION,
        generation_ref=gref,
        plan_id="plan-g2-08",
        plan_revision=1,
        response_id="resp-g2-08",
        source_text="Merhaba.",
        normalized_text="Merhaba.",
        language="tr",
        voice_profile="leyla-warm-42",
        seed=42,
        chunks=(ChunkPlan(chunk_id="c0", chunk_index=0, model_text="Merhaba."),),
        normalization_passes=1,
        validation_status=PlanValidationStatus.VALID,
    )
    pin_snap = pin_synthesis_snapshot(plan, allow_experimental_seeds=True)

    # 1. Isolated RNG & VersionedCacheStore
    rng_adapter = IsolatedRngAdapter()
    est = DurationEstimate(
        token_count=8,
        char_count=8,
        raw_predicted_frames=12.0,
        raw_predicted_sec=0.48,
        effective_frames=12,
        effective_duration_sec=0.48,
        expected_samples=12 * 1920,
        clamped=False,
        clamp_reason=None,
        units="frames@25Hz",
        latent_rate_hz=25,
        samples_per_frame=1920,
        sample_rate_hz=48000,
        profile_revision="g2-test",
    )
    decision = DurationDecision(
        allowed=True,
        reason_code="OK",
        estimate=est,
        estimated_latent_bytes=12 * 64 * 4,
        estimated_waveform_bytes=12 * 1920 * 4,
        estimated_vram_bytes=10 * MIB,
    )
    lat_a, _ = rng_adapter.draw_true_latent(
        spec=rng_adapter.build_spec(attempt_ref="att-a", seed=42, true_frames=12, latent_dim=64),
        decision=decision,
        snapshot=pin_snap,
    )
    lat_b, _ = rng_adapter.draw_true_latent(
        spec=rng_adapter.build_spec(attempt_ref="att-b", seed=42, true_frames=12, latent_dim=64),
        decision=decision,
        snapshot=pin_snap,
    )
    assert np.array_equal(lat_a, lat_b)
    store = VersionedCacheStore(max_entries=2, max_bytes=8192, ttl_ns=10_000_000_000, clock=clock)
    desc = StrictSynthesisCacheAdapter.build_canonical_descriptor(chunk=plan.chunks[0], snapshot=pin_snap)
    elig_pub = store.classify_eligibility(session_id="sess-g2-08", is_public_template=True, template_id="greet", contains_pii=False)
    assert elig_pub.kind == CacheEligibilityKind.PUBLIC_TEMPLATE
    assert store.put(descriptor=desc, eligibility=elig_pub, payload=b"\x00\x00\x80\x3f" * 16, sample_count=16, audio_format=RAW_AUDIO_FORMAT)
    entry, _ = store.get(descriptor=desc, eligibility=elig_pub)
    assert entry is not None
    store.release_borrow(entry)

    # 2. QualityGuard & SameSeedRecoveryPolicy
    guard = QualityGuard(calibrated_thresholds_approved=False)
    z_res = guard.assess(payload=np.zeros(4800, dtype=np.float32).tobytes(), sample_count=4800, audio_format=RAW_AUDIO_FORMAT)
    assert not z_res.structurally_valid and z_res.rms_dbfs is None

    dit = _FakeDiT()
    vae = _FakeVAE(silent_first_n=1)
    _register_f5_handles(sched, dit, vae)
    pipe = NeuralSynthesisPipeline(scheduler=sched, recovery_policy=SameSeedRecoveryPolicy(enabled=True, clock=clock), telemetry=SynthesisTelemetry(clock=clock))
    out = await pipe.synthesize_plan(plan, pin_kwargs={"allow_experimental_seeds": True})
    assert out.status == "COMPLETED" and dit.calls == 2 and vae.calls == 2 and out.accepted_chunks[0].seed == 42

    # 3. AdaptiveProfileSelector & DeadlineBatchFormer
    sel = AdaptiveProfileSelector(mode="SHADOW")
    pick = sel.select(latent_frames=40, is_critical_speech=True)
    assert pick.effective_descriptor.profile_id == "euler_32"

    now = clock.monotonic_ns()
    former = DeadlineBatchFormer(max_batch_size=4, max_wait_ms=12.0, max_padding_fraction=0.25)
    bdec = former.form_batches(
        candidates=[
            BatchCandidate("p2", 10, 20, 20 * 1920, 64, "euler32", PriorityClass.P2, now, now + 500_000_000, 9),
            BatchCandidate("p4", 12, 22, 22 * 1920, 64, "euler32", PriorityClass.P4, now + 1, now + 500_000_000, 9),
        ],
        now_monotonic_ns=now,
        memory_budget=sched.memory_budget,
    )
    assert len(bdec.batches) == 2 and bdec.batches[0].member_ids == ("p2",)


def test_g2_09_f6c_wsola_crossfade_pause_ledger_enhanced_dsp_and_codec_lab() -> None:
    assert resolve_rate_ownership(control_id="k1", requested_speed=1.05, model_applied_speed=1.05, wsola_enabled=True).owner == RateOwner.F5
    assert resolve_rate_ownership(control_id="k2", requested_speed=0.95, model_applied_speed=None, wsola_enabled=True).owner == RateOwner.F6

    wsola = WSOLAAdapter()
    t = np.arange(19200, dtype=np.float32) / 48000.0
    sig = (0.3 * np.sin(2.0 * math.pi * 220.0 * t)).astype(np.float32)
    assert np.array_equal(wsola.process_chunk(sig, factor=1.0), sig)
    wsola.reset()
    faster = wsola.process_chunk(sig, factor=1.05)
    tail = wsola.flush_eos()
    assert (faster.size + tail.size) < sig.size

    asm = AdaptiveCrossfadeAssembler()
    out_cf, dec_cf = asm.assemble_boundary(np.full(2400, 0.25, dtype=np.float32), np.full(2400, 0.25, dtype=np.float32), BoundaryRef("b1", "c0", "c1"))
    assert dec_cf.applied is True and np.allclose(out_cf, 0.25, atol=1e-5)
    _, dec_prot = asm.assemble_boundary(np.full(2400, 0.25, dtype=np.float32), np.full(2400, 0.25, dtype=np.float32), BoundaryRef("b2", "c1", "c2", protected_group=True))
    assert dec_prot.applied is False

    obs = observe_boundary_silence(
        np.concatenate([np.full(2000, 0.2, dtype=np.float32), np.zeros(1920, dtype=np.float32)]),
        np.concatenate([np.zeros(960, dtype=np.float32), np.full(2000, 0.2, dtype=np.float32)]),
        rate_hz=48000,
    )
    ledger = SemanticPauseLedger(rate_hz=48000)
    entry = ledger.plan_and_consume(boundary_id="b1", requested_ms=160, target_kind=PauseTargetKind.TOTAL_BOUNDARY, observation=obs)
    assert entry.inserted_samples == 4800

    off_dsp = EnhancedDSPProcessor(EnhancedDSPProfile(enabled=False))
    raw_hot = (1.8 * np.sin(2.0 * math.pi * 1000.0 * t[:4800])).astype(np.float32)
    assert np.array_equal(off_dsp.process_pre_resample_48k(raw_hot), raw_hot)
    on_dsp = EnhancedDSPProcessor(EnhancedDSPProfile(enabled=True, limiter_enabled=True, limiter_ceiling_dbfs=-1.0))
    limited, clipped = on_dsp.process_post_resample_limiter(on_dsp.process_pre_resample_48k(raw_hot))
    assert clipped > 0 and float(np.max(np.abs(limited))) <= (10.0 ** (-1.0 / 20.0)) + 1e-6

    trial = CodecTrial()
    pcm_8k = (0.4 * 32767.0 * np.sin(2.0 * math.pi * 500.0 * (np.arange(1600, dtype=np.float64) / 8000.0))).astype(np.int16)
    ulaw = trial.run(pcm_8k, CodecTrialSpec(trial_id="t-ulaw", codec=CodecKind.G711_PCMU, seed=9))
    assert ulaw.capability_status == CodecCapabilityStatus.VERIFIED and ulaw.live_transport_untouched is True
    assert get_codec_capability(CodecKind.G722_64K).status == CodecCapabilityStatus.UNSUPPORTED


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["web", "audiosocket"])
async def test_g2_10_end_to_end_w34_vertical_slice_web_and_phone(tmp_path: Path, channel: str) -> None:
    clock = HarnessClock(initial_ns=1_000_000_000, clock_domain="server_mono")
    cfg = resolve_configuration(overrides={"auto_load_models": False, "supervisor_mode": "guarded"}).snapshot
    lex = _build_enriched_lexicon()
    sched = _build_scheduler(clock)

    session_id = f"sess-g2-e2e-{channel}"
    session_ctx = SessionContext(SessionIdentity(session_id, trace_id=f"tr-{session_id}"), clock=clock, max_queue_bytes=2 * 1024 * 1024)
    await session_ctx.open()
    in_stream = StreamRef(session_id, "in-0", StreamDirection.INPUT, 1)
    out_stream = StreamRef(session_id, "out-0", StreamDirection.OUTPUT, 1)

    # F6-B ReferenceTap -> F0-B ReferenceReader
    tap = PlaybackReferenceTap(session_id=session_id, stream_id="out-0", format_epoch=0, max_frames=256, max_bytes=256 * 640)
    assoc = ReferenceAssociation(session_id=session_id, input_stream_id="in-0", input_format_epoch=1, output_stream_ref=out_stream)
    ref_reader = PlaybackReferenceReader(assoc, target_rate_hz=16000)

    # F1-B/C Processor
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

    # F0-B Pipeline
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
        sig = _make_speech_like_signal(samples_per_chunk, sr=in_rate, amp=0.25, seed=seq + 1)
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

    # F2-B/C ASR
    pinned_asr = resolve_asr_config(cfg, route_mode=ASRRouteMode.STRICT)
    asr_engine = WhisperSchedulerEngine(sched, model_getter=lambda: _ScriptedWhisperModel([("Merhaba", [])]))
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

    # F3-B/C Router + DialogueFacade
    router = HierarchicalIntentRouter()
    rdec = await router.route(
        asr_result=asr_rec.result,
        context=ConversationContext(session_id=uuid4(), turn_at=datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)),
    )
    assert rdec.primary_intent == Intent.GREETING

    audit = SecurityAuditLog(tmp_path / f"audit_{channel}.db")
    idem = DurableIdempotencyStore(tmp_path / f"idem_{channel}.db", audit_log=audit)
    wf = WorkflowAdapter(policy_engine=PolicyEngine(audit_log=audit), confirmation_manager=ConfirmationManager(clock=clock, audit_log=audit), idempotency_store=idem, audit_log=audit, provider_mode=ProviderMode.MOCK)
    snap = build_snapshot(values={"supervisor_mode": SupervisorMode.GUARDED.value}, sources={"supervisor_mode": ConfigSource.OVERRIDE}, feature_flags={"supervisor_mode": SupervisorMode.GUARDED.value})
    facade = DialogueFacade(config_snapshot=snap, mode=SupervisorMode.GUARDED, workflow_adapter=wf, clock=clock, utc_now_fn=lambda: datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc))
    facade.open_session(session_id=session_id, incarnation_id=f"inc-{channel}", lexicon_revision=lex.lexicon_revision)
    turn_id = utt.turn_ref.turn_id if utt.turn_ref else 1
    f3_out = await facade.process_asr_turn(asr_rec.result, session_id=session_id, incarnation_id=f"inc-{channel}", turn_id=turn_id, consumer=BoundedDialogueConsumer())
    assert f3_out.response is not None

    # F4-B/C + intent_prosody
    vocab_path = REPO_ROOT / "config" / "freya_vocab.json"
    f4_pipe = LinguisticFrontendPipeline(
        config_snapshot_provider=lambda: cfg,
        model_registry_provider=lambda c: ModelRegistry.from_snapshot(c),
        voice_registry_provider=lambda: VoiceProfileRegistry(),
        lexicon_registry_provider=lambda: lex,
        vocab_validator_factory=lambda s: FreyaVocabularyValidator.from_vocab_file(vocab_path, model_revision=s.model_revision, capability_revision=s.capability_revision),
        require_real_vocab=True,
    )
    t5, _ = await session_ctx.begin_turn()
    g5, _ = await session_ctx.begin_generation(t5)
    f4_resp = replace(f3_out.response, envelope=replace(f3_out.response.envelope, turn_id=t5.turn_id, generation_id=g5.generation_id))
    f4_res = f4_pipe.prepare_response(f4_resp, generation_ref=g5, expected_session_id=session_id, expected_turn_id=t5.turn_id, requested_seed=9, config_snapshot=cfg, lexicon_registry=lex)
    assert f4_res.ok and f4_res.plan is not None and f4_res.normalization_passes == 1
    assert f4_res.f4b_morphology is not None and f4_res.f4c_prosody is not None
    ip = resolve_intent_prosody("kullanici_karsilama")
    assert ip.style_token == "<welcome>"

    # F5-B/C Synthesis with SameSeedRecoveryPolicy + QualityGuard
    dit, vae = _FakeDiT(), _FakeVAE()
    _register_f5_handles(sched, dit, vae)
    f5_pipe = NeuralSynthesisPipeline(scheduler=sched, recovery_policy=SameSeedRecoveryPolicy(enabled=True, clock=clock), telemetry=SynthesisTelemetry(clock=clock))
    f5_out = await f5_pipe.synthesize_plan(f4_res.plan, session_ctx=session_ctx, expected_generation_ref=g5)
    assert f5_out.status == "COMPLETED" and len(f5_out.accepted_chunks) >= 1

    # F6-B/C Rendering + Transport + ReferenceTap
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


def test_g2_11_g2_acceptance_privacy_and_scope_honesty() -> None:
    traces = TraceStore()
    traces.start_span(trace_id="tr-g2-11", span_id="sp-g2", name="g2.gate", session_id="sess-g2-11", turn_id=1, generation_id=1, start_monotonic_ns=100, clock_domain="server_mono")
    traces.finish_span(trace_id="tr-g2-11", span_id="sp-g2", end_monotonic_ns=200, clock_domain="server_mono", status=SpanStatus.OK)
    proj = Projection().project({"session_id": "sess-g2-11", "status": "PASS", "source_class": "MOCK_RUNTIME"}, extra_allowlist=frozenset({"session_id", "status", "source_class"}))
    assert proj is not None and PIISecretScanner.scan_object(proj) == []

    g2_gates = [GateRecord(f"G2_{i:02d}", True, GateStatus.PASS, f"G2_{i:02d} verified", ("ev",)) for i in range(1, 12)]
    summary = evaluate_gates(g2_gates)
    assert summary.ready is True and summary.overall == GateStatus.PASS
