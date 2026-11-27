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

from backend.neural_synthesis.f5_bc.adaptive_profiles import (
    AdaptiveProfileSelector,
    CANDIDATE_STEP_COUNTS,
    COST_MODEL_REVISION,
    ControlDisposition,
    CostEstimate,
    DiscreteSolverDescriptor,
    PROFILE_SELECTOR_REVISION,
    ProfileSelection,
    build_default_profile_catalog,
)
from backend.neural_synthesis.f5_bc.batch_layout import (
    BatchExecutionLayout,
    BatchLayoutBuilder,
    BatchLayoutError,
    LAYOUT_REVISION,
    LatentLayout,
    MASK_SEMANTICS_TRUE_IS_VALID,
)
from backend.neural_synthesis.f5_bc.batch_policy import (
    BatchCandidate,
    BatchFormationDecision,
    DEFAULT_FRAME_BUCKETS,
    DEFAULT_MAX_PADDING_FRACTION,
    DeadlineBatchFormer,
)
from backend.neural_synthesis.cache_adapter import (
    CacheLookupResult,
    RawCacheEntry,
    StrictSynthesisCacheAdapter,
    inventory_experimental_routes,
)
from backend.neural_synthesis.f5_bc.cache_store import (
    CACHE_SCHEMA_VERSION,
    CacheEligibility,
    CacheEligibilityKind,
    CacheStoreStats,
    CanonicalCacheDescriptor,
    VersionedCacheEntry,
    VersionedCacheStore,
)
from backend.neural_synthesis.chunk_builder import RAW_AUDIO_FORMAT, build_audio_chunk
from backend.neural_synthesis.config_adapter import (
    ALLOWED_STRICT_CONTROLS,
    BASELINE_CHANNELS,
    BASELINE_LATENT_DIM,
    BASELINE_LATENT_RATE_HZ,
    BASELINE_ODE_STEPS,
    BASELINE_SAMPLES_PER_FRAME,
    BASELINE_SAMPLE_RATE_HZ,
    BASELINE_SOLVER,
    PinnedSynthesisSnapshot,
    SnapshotPinningError,
    VoiceBinding,
    pin_synthesis_snapshot,
    resolve_default_snapshot,
)
from backend.neural_synthesis.decoder_adapter import (
    DecoderAdapter,
    DecoderOutputDescriptor,
    DecoderValidationError,
)
from backend.neural_synthesis.delivery import DeliveryOutcome, GenerationDeliveryFence
from backend.neural_synthesis.duration_estimator import (
    DurationEstimate,
    DurationEstimationError,
    DurationEstimator,
    compute_clause_frame_count,
)
from backend.neural_synthesis.duration_guard import DurationDecision, DurationGuard
from backend.neural_synthesis.encoder_adapter import (
    EncodedCondition,
    EncoderAdapter,
    EncoderValidationError,
)
from backend.neural_synthesis.latent_initializer import (
    LatentDescriptor,
    LatentInitializationError,
    LatentInitializer,
)
from backend.neural_synthesis.legacy_adapter import (
    LegacySynthesisBridge,
    SynthesisPathRecord,
    adapt_legacy_synth_output,
    audit_strict_bypasses,
    classify_synthesis_paths,
)
from backend.neural_synthesis.lifecycle import SessionCleanupReport, SynthesisLifecycleManager
from backend.neural_synthesis.model_adapter import (
    DEFAULT_VOCAB_RELATIVE_PATH,
    ModelResidencyAdapter,
    StaticVocabSnapshot,
    SynthesisModelHandles,
    VENDOR_VOCAB_RELATIVE_PATH,
    load_static_char_vocab,
)
from backend.neural_synthesis.pipeline import (
    ChunkExecutionOutcome,
    NeuralSynthesisPipeline,
    SynthesisOutcome,
)
from backend.neural_synthesis.plan_validator import (
    PlanAdmission,
    ScopedPlanClaimRegistry,
    validate_and_admit_plan,
)
from backend.neural_synthesis.f5_bc.quality_guard import (
    QUALITY_POLICY_REVISION,
    QualityAssessment,
    QualityGuard,
)
from backend.neural_synthesis.raw_validator import RawAudioValidator, RawValidationResult
from backend.neural_synthesis.f5_bc.recovery_policy import (
    NON_RETRYABLE_FAILURE_CODES,
    RECOVERY_POLICY_REVISION,
    RETRYABLE_FAILURE_CODES,
    RecoveryDecision,
    SameSeedRecoveryPolicy,
)
from backend.neural_synthesis.f5_bc.rng_adapter import (
    IsolatedRngAdapter,
    ItemRngSpec,
    RNG_PROFILE_REVISION,
    SUPPORTED_RNG_ALGORITHMS,
)
from backend.neural_synthesis.scheduler_bridge import (
    FreyaSynthesisProviderAdapter,
    ProviderBarriers,
    ProviderExecutionPayload,
    ProviderExecutionResult,
    SchedulerBridge,
    SynthesisJobRef,
    UncertainDeviceStateError,
)
from backend.neural_synthesis.solver_adapter import (
    BASELINE_SOLVER_PROFILE,
    SolverAdapter,
    SolverExecutionError,
    SolverExecutionResult,
    SolverProfile,
    SolverValidationError,
    validate_solver_profile,
)
from backend.neural_synthesis.f5_bc.speaker_intelligence import (
    PITCH_EVAL_REVISION,
    PitchAssessment,
    SPEAKER_EVAL_REVISION,
    SpeakerAssessment,
    SpeakerIntelligenceEvaluator,
    SpeakerReferenceManifest,
)
from backend.neural_synthesis.telemetry import SynthesisTelemetry

__all__ = [
    "ALLOWED_STRICT_CONTROLS",
    "AdaptiveProfileSelector",
    "BASELINE_CHANNELS",
    "BASELINE_LATENT_DIM",
    "BASELINE_LATENT_RATE_HZ",
    "BASELINE_ODE_STEPS",
    "BASELINE_SAMPLES_PER_FRAME",
    "BASELINE_SAMPLE_RATE_HZ",
    "BASELINE_SOLVER",
    "BASELINE_SOLVER_PROFILE",
    "BatchCandidate",
    "BatchExecutionLayout",
    "BatchFormationDecision",
    "BatchLayoutBuilder",
    "BatchLayoutError",
    "CACHE_SCHEMA_VERSION",
    "CANDIDATE_STEP_COUNTS",
    "COST_MODEL_REVISION",
    "CacheEligibility",
    "CacheEligibilityKind",
    "CacheLookupResult",
    "CacheStoreStats",
    "CanonicalCacheDescriptor",
    "ChunkExecutionOutcome",
    "ControlDisposition",
    "CostEstimate",
    "DEFAULT_FRAME_BUCKETS",
    "DEFAULT_MAX_PADDING_FRACTION",
    "DEFAULT_VOCAB_RELATIVE_PATH",
    "DeadlineBatchFormer",
    "DecoderAdapter",
    "DecoderOutputDescriptor",
    "DecoderValidationError",
    "DeliveryOutcome",
    "DiscreteSolverDescriptor",
    "DurationDecision",
    "DurationEstimate",
    "DurationEstimationError",
    "DurationEstimator",
    "DurationGuard",
    "EncodedCondition",
    "EncoderAdapter",
    "EncoderValidationError",
    "FreyaSynthesisProviderAdapter",
    "GenerationDeliveryFence",
    "IsolatedRngAdapter",
    "ItemRngSpec",
    "LAYOUT_REVISION",
    "LatentDescriptor",
    "LatentInitializationError",
    "LatentInitializer",
    "LatentLayout",
    "LegacySynthesisBridge",
    "MASK_SEMANTICS_TRUE_IS_VALID",
    "ModelResidencyAdapter",
    "NON_RETRYABLE_FAILURE_CODES",
    "NeuralSynthesisPipeline",
    "PITCH_EVAL_REVISION",
    "PROFILE_SELECTOR_REVISION",
    "PinnedSynthesisSnapshot",
    "PitchAssessment",
    "PlanAdmission",
    "ProfileSelection",
    "ProviderBarriers",
    "ProviderExecutionPayload",
    "ProviderExecutionResult",
    "QUALITY_POLICY_REVISION",
    "QualityAssessment",
    "QualityGuard",
    "RAW_AUDIO_FORMAT",
    "RECOVERY_POLICY_REVISION",
    "RETRYABLE_FAILURE_CODES",
    "RNG_PROFILE_REVISION",
    "RawAudioValidator",
    "RawCacheEntry",
    "RawValidationResult",
    "RecoveryDecision",
    "SPEAKER_EVAL_REVISION",
    "SUPPORTED_RNG_ALGORITHMS",
    "SameSeedRecoveryPolicy",
    "SchedulerBridge",
    "ScopedPlanClaimRegistry",
    "SessionCleanupReport",
    "SnapshotPinningError",
    "SolverAdapter",
    "SolverExecutionError",
    "SolverExecutionResult",
    "SolverProfile",
    "SolverValidationError",
    "SpeakerAssessment",
    "SpeakerIntelligenceEvaluator",
    "SpeakerReferenceManifest",
    "StaticVocabSnapshot",
    "StrictSynthesisCacheAdapter",
    "SynthesisJobRef",
    "SynthesisLifecycleManager",
    "SynthesisModelHandles",
    "SynthesisOutcome",
    "SynthesisPathRecord",
    "SynthesisTelemetry",
    "UncertainDeviceStateError",
    "VENDOR_VOCAB_RELATIVE_PATH",
    "VersionedCacheEntry",
    "VersionedCacheStore",
    "VoiceBinding",
    "adapt_legacy_synth_output",
    "audit_strict_bypasses",
    "build_audio_chunk",
    "build_default_profile_catalog",
    "classify_synthesis_paths",
    "compute_clause_frame_count",
    "inventory_experimental_routes",
    "load_static_char_vocab",
    "pin_synthesis_snapshot",
    "resolve_default_snapshot",
    "validate_and_admit_plan",
    "validate_solver_profile",
]
