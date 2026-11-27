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
from backend.voice_activity.config_adapter import F1ConfigAdapter, F1ProfileConfig, F1RouteMode, parse_f1_route_mode
from backend.voice_activity.continuation_rules import classify_turkish_cues, turkish_casefold
from backend.voice_activity.deadlines import F1DeadlineMonitor, WatchdogStatus, compute_same_domain_duration_ms
from backend.voice_activity.endpointing import EndpointCutDecision, EndpointingPolicy, FinalizationReason
from backend.voice_activity.frame_synchronizer import (
    FrameAdmissionResult,
    FrameSynchronizer,
    SUPPORTED_SAMPLE_RATE_HZ,
    VAD_WINDOW_SAMPLES,
    VADWindow,
    decode_audio_frame_to_f32,
)
from backend.voice_activity.interruption_contracts import (
    DecisionOutcome,
    F1BPolicyConfig,
    FlushIntent,
    InputCandidateRef,
    InterruptionAttempt,
    InterruptionState,
    OutputAvailability,
    OutputTargetSnapshot,
)
from backend.voice_activity.interruption_controller import InterruptionController
from backend.voice_activity.legacy_adapter import LegacyEndpointAdapter, utterance_to_legacy_stt_ndarray
from backend.voice_activity.lifecycle import (
    F1PreflightResult,
    F1StreamLifecycle,
    PrerequisiteCheckStatus,
    check_f1_a_prerequisites,
)
from backend.voice_activity.lookback_buffer import LookbackBuffer, LookbackCapacityExceededError, PinResult
from backend.voice_activity.pause_bridge import M02PauseBridge
from backend.voice_activity.pipeline import ProcessFrameOutcome, StreamAcousticProcessor, VoiceActivityPipeline
from backend.voice_activity.sample_accounting import RejectionReason, SampleAccountingLedger, SampleAccountingSnapshot
from backend.voice_activity.semantic_contracts import (
    AcousticEvidence,
    BackchannelCategory,
    ContinuationCue,
    EchoAcousticCategory,
    EndpointAdvice,
    EndpointAdviceKind,
    ExpectedSlotCategory,
    ExpectedSlotProjection,
    F1CProfileConfig,
    InterruptionAdvice,
    InterruptionAdviceKind,
    SemanticEndpointHint,
    quantize_max_windows,
    quantize_min_windows,
)
from backend.voice_activity.semantic_endpoint_policy import SemanticEndpointPolicy
from backend.voice_activity.speech_state_machine import (
    AcousticState,
    FSMTransition,
    SpeechStateMachine,
    TransitionKind,
)
from backend.voice_activity.telemetry import F1Telemetry
from backend.voice_activity.utterance_manager import (
    BoundedUtteranceQueue,
    FinalizationReceipt,
    FinalizationStatus,
    M02TurnAllocatorBridge,
    UtteranceManager,
)
from backend.voice_activity.vad_engine import (
    CloneableVADBackend,
    SileroTemplateAdapter,
    StatePassingVADBackend,
    VADEngineAdapter,
    VADIsolationStrategy,
    VADIsolationUnsupportedError,
    VADObservation,
    inspect_vad_backend_isolation,
    validate_vad_score,
)
from backend.voice_activity.vad_state import LateCallbackOutcome, VADStateManager

__all__ = [
    "AcousticEvidence",
    "AcousticState",
    "BackchannelCategory",
    "BoundedUtteranceQueue",
    "CloneableVADBackend",
    "ContinuationCue",
    "DecisionOutcome",
    "EchoAcousticCategory",
    "EndpointAdvice",
    "EndpointAdviceKind",
    "EndpointCutDecision",
    "EndpointingPolicy",
    "ExpectedSlotCategory",
    "ExpectedSlotProjection",
    "F1BPolicyConfig",
    "F1CProfileConfig",
    "F1ConfigAdapter",
    "F1DeadlineMonitor",
    "F1PreflightResult",
    "F1ProfileConfig",
    "F1RouteMode",
    "F1StreamLifecycle",
    "F1Telemetry",
    "FSMTransition",
    "FinalizationReason",
    "FinalizationReceipt",
    "FinalizationStatus",
    "FlushIntent",
    "FrameAdmissionResult",
    "FrameSynchronizer",
    "InputCandidateRef",
    "InterruptionAdvice",
    "InterruptionAdviceKind",
    "InterruptionAttempt",
    "InterruptionController",
    "InterruptionState",
    "LateCallbackOutcome",
    "LegacyEndpointAdapter",
    "LookbackBuffer",
    "LookbackCapacityExceededError",
    "M02PauseBridge",
    "M02TurnAllocatorBridge",
    "OutputAvailability",
    "OutputTargetSnapshot",
    "PinResult",
    "PrerequisiteCheckStatus",
    "ProcessFrameOutcome",
    "RejectionReason",
    "SUPPORTED_SAMPLE_RATE_HZ",
    "SampleAccountingLedger",
    "SampleAccountingSnapshot",
    "SemanticEndpointHint",
    "SemanticEndpointPolicy",
    "SileroTemplateAdapter",
    "SpeechStateMachine",
    "StatePassingVADBackend",
    "StreamAcousticProcessor",
    "TransitionKind",
    "UtteranceManager",
    "VADEngineAdapter",
    "VADIsolationStrategy",
    "VADIsolationUnsupportedError",
    "VADObservation",
    "VADStateManager",
    "VADWindow",
    "VAD_WINDOW_SAMPLES",
    "VoiceActivityPipeline",
    "WatchdogStatus",
    "check_f1_a_prerequisites",
    "classify_turkish_cues",
    "compute_same_domain_duration_ms",
    "decode_audio_frame_to_f32",
    "inspect_vad_backend_isolation",
    "parse_f1_route_mode",
    "quantize_max_windows",
    "quantize_min_windows",
    "turkish_casefold",
    "utterance_to_legacy_stt_ndarray",
    "validate_vad_score",
]
