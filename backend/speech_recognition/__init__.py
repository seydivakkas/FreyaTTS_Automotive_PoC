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

from backend.speech_recognition.admission import (
    ASRConsumer,
    ASRResultDelivery,
    ASRUtteranceAdmission,
    ClaimDecision,
    ClaimStatus,
    InMemoryASRConsumer,
)
from backend.speech_recognition.confidence_metadata import (
    ConfidenceExtractionResult,
    extract_confidence_estimate,
    resolve_language_metadata,
)
from backend.speech_recognition.config_adapter import (
    ASRRouteMode,
    DecodeProfile,
    PinnedASRConfig,
    resolve_asr_config,
)
from backend.speech_recognition.errors import (
    ASRAdmissionError,
    ASRConfigError,
    ASRDeliveryError,
    ASRDeliveryStatus,
    ASRDispatchStatus,
    ASRInputError,
    ASRProviderError,
    build_safe_error_info,
)
from backend.speech_recognition.input_manager import (
    DEFAULT_MAX_AUDIO_SAMPLES,
    REQUIRED_SAMPLE_RATE_HZ,
    MaterializedAudio,
    ValidatedUtteranceInput,
    validate_and_materialize_utterance,
)
from backend.speech_recognition.legacy_adapter import (
    LegacyASRProjection,
    project_legacy_transcript,
)
from backend.speech_recognition.lexicon_adapter import (
    HotwordSelection,
    LexiconCandidateBundle,
    PinnedLexiconSnapshot,
    build_legacy_hotwords,
    extract_conservative_candidates,
    pin_lexicon_snapshot,
)
from backend.speech_recognition.lifecycle import ASRLifecycleManager, LifecycleDrainReport
from backend.speech_recognition.pipeline import ASRProcessingRecord, SpeechRecognitionPipeline
from backend.speech_recognition.request_builder import ASRJobPayload, build_asr_resource_request
from backend.speech_recognition.result_builder import build_final_asr_result
from backend.speech_recognition.telemetry import ASRTelemetryBridge
from backend.speech_recognition.transcript_collector import (
    CollectedSegment,
    CollectedTranscript,
    CollectorLimits,
    SegmentTimestamp,
    collect_whisper_segments,
)
from backend.speech_recognition.whisper_engine import (
    WhisperExecutionResult,
    WhisperSchedulerEngine,
)
from backend.speech_recognition.decode_policy import (
    AttemptArbitrationResult,
    DecodeAttemptRecord,
    DecodeBeamProfile,
    arbitrate_decode_attempts,
    build_attempt_decode_profile,
    should_run_alternate_decode,
)
from backend.speech_recognition.entity_resolver import (
    ClarificationHint,
    ClarificationReason,
    CorrectionDecision,
    CorrectionDecisionKind,
    EntityResolutionReport,
    EvidenceTier,
    RankedCandidate,
    resolve_automotive_entities,
)
from backend.speech_recognition.hotword_planner import (
    ContextHintSnapshot,
    HotwordPlan,
    HotwordPlanner,
)
from backend.speech_recognition.partial_contracts import (
    ContinuationCue,
    DecodeWindow,
    FinalizationBinding,
    IncrementalAudioView,
    PartialHypothesis,
    PartialLaneState,
    ProvisionalRecognitionRevision,
    ReconciledView,
    SemanticEndpointHint,
    SpeechScopeRef,
    StablePrefixEvidence,
    TokenProvenance,
    WordObservation,
)
from backend.speech_recognition.protected_spans import (
    ProtectedCategory,
    ProtectedSpanRecord,
    ProtectedSpanScanResult,
    scan_protected_spans,
)
from backend.speech_recognition.streaming_controller import (
    PseudoStreamingController,
    StreamingWindowConfig,
)

__all__ = [
    "ASRAdmissionError",
    "ASRConfigError",
    "ASRConsumer",
    "ASRDeliveryError",
    "ASRDeliveryStatus",
    "ASRDispatchStatus",
    "ASRInputError",
    "ASRJobPayload",
    "ASRLifecycleManager",
    "ASRProcessingRecord",
    "ASRProviderError",
    "ASRResultDelivery",
    "ASRRouteMode",
    "ASRTelemetryBridge",
    "ASRUtteranceAdmission",
    "ClaimDecision",
    "ClaimStatus",
    "CollectedSegment",
    "CollectedTranscript",
    "CollectorLimits",
    "ConfidenceExtractionResult",
    "DEFAULT_MAX_AUDIO_SAMPLES",
    "DecodeProfile",
    "HotwordSelection",
    "InMemoryASRConsumer",
    "LegacyASRProjection",
    "LexiconCandidateBundle",
    "LifecycleDrainReport",
    "MaterializedAudio",
    "PinnedASRConfig",
    "PinnedLexiconSnapshot",
    "REQUIRED_SAMPLE_RATE_HZ",
    "SegmentTimestamp",
    "SpeechRecognitionPipeline",
    "ValidatedUtteranceInput",
    "WhisperExecutionResult",
    "WhisperSchedulerEngine",
    "build_asr_resource_request",
    "build_final_asr_result",
    "build_legacy_hotwords",
    "build_safe_error_info",
    "collect_whisper_segments",
    "extract_confidence_estimate",
    "extract_conservative_candidates",
    "pin_lexicon_snapshot",
    "project_legacy_transcript",
    "resolve_asr_config",
    "resolve_language_metadata",
    "validate_and_materialize_utterance",
]
