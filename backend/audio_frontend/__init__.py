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

from backend.audio_frontend.f0_b.acoustic_evidence import (
    AcousticEvidence,
    SnrMethod,
    SnrTap,
    compute_erle_db,
    compute_oracle_snr_db,
)
from backend.audio_frontend.f0_b.adaptive_chain import AdaptiveChainResult, AdaptiveDspChain
from backend.audio_frontend.f0_b.adaptive_denoiser import AdaptiveDenoiseResult, AdaptiveDenoiserStage
from backend.audio_frontend.f0_b.aec_adapter import AecOutputStatus, AecProcessResult, BoundedNlmsAec
from backend.audio_frontend.config_adapter import (
    F0_B_ADAPTIVE_DSP_FLAG,
    F0_B_AEC_FLAG,
    F0_B_RNNOISE_FLAG,
    F0_STRICT_PIPELINE_FLAG,
    AudioFrontendConfig,
    build_f0_flag_registry,
    config_from_legacy_settings,
    config_from_snapshot,
    default_audio_frontend_config,
)
from backend.audio_frontend.f0_b.delay_estimator import DelayEstimate, DelayStatus, NccDelayEstimator
from backend.audio_frontend.f0_b.double_talk import (
    AdaptationDecision,
    DoubleTalkCategory,
    DoubleTalkClassifier,
    DoubleTalkEvidence,
)
from backend.audio_frontend.f0_b.profiles import (
    ENVIRONMENT_PROFILES,
    EnhancementProfile,
    EnvironmentProfileId,
    resolve_enhancement_profile,
)
from backend.audio_frontend.f0_b.reference_adapter import (
    ClockMapping,
    ClockMappingStatus,
    DeliveryStatus,
    PlaybackReferenceReader,
    PlaybackReferenceSource,
    ReferenceAssociation,
    ReferenceChunk,
    ReferenceReadResult,
    resolve_clock_mapping,
)
from backend.audio_frontend.f0_b.rnnoise_adapter import (
    RnnoiseCapability,
    RnnoiseDenoiserAdapter,
    RnnoiseProvider,
    probe_rnnoise_capability,
)
from backend.audio_frontend.dispatcher import DispatchResult, F1BoundaryDispatcher
from backend.audio_frontend.format_validator import (
    LEGACY_WEB_EXTENDED_PROFILE,
    PHONE_8K_PROFILE,
    WEB_16K_48K_PROFILE,
    InputOutcomeStatus,
    InputProfile,
    ValidationOutcome,
    validate_audio_frame,
    validate_raw_input,
)
from backend.audio_frontend.input_adapter import (
    AdaptedIngressChunk,
    adapt_audiosocket_chunk,
    adapt_ingress_to_frame,
    adapt_web_ws_chunk,
)
from backend.audio_frontend.legacy_adapter import LegacyAudioInputFacade, LegacyBatchOutput
from backend.audio_frontend.legacy_dsp_adapter import (
    DspProcessingResult,
    DspStageError,
    LegacyAgcGateStage,
    LegacyDspChain,
    LegacyHpfStage,
    LegacySpectralStage,
)
from backend.audio_frontend.lifecycle import (
    AudioFrontendLifecycle,
    CorePreflightResult,
    verify_core_integration_preflight,
)
from backend.audio_frontend.pcm_conversion import (
    ConversionStats,
    copy_ingress_bytes,
    decode_to_float32,
    encode_from_float32,
)
from backend.audio_frontend.pipeline import AudioInputPipeline, PipelineResult
from backend.audio_frontend.quality_analyzer import AudioQualityMetrics, analyze_float32_quality
from backend.audio_frontend.raw_dtmf_bridge import RawDtmfBridge, RawDtmfEvent, RawDtmfTapResult
from backend.audio_frontend.resampler import StatefulResampler
from backend.audio_frontend.sample_accounting import OffsetMapping, SampleLedger
from backend.audio_frontend.stream_state import StreamAudioState, StreamStateRegistry
from backend.audio_frontend.telemetry import AudioFrontendTelemetry

__all__ = [
    "AcousticEvidence",
    "AdaptationDecision",
    "AdaptedIngressChunk",
    "AdaptiveChainResult",
    "AdaptiveDenoiseResult",
    "AdaptiveDenoiserStage",
    "AdaptiveDspChain",
    "AecOutputStatus",
    "AecProcessResult",
    "AudioFrontendConfig",
    "AudioFrontendLifecycle",
    "AudioFrontendTelemetry",
    "AudioInputPipeline",
    "AudioQualityMetrics",
    "BoundedNlmsAec",
    "ClockMapping",
    "ClockMappingStatus",
    "ConversionStats",
    "CorePreflightResult",
    "DelayEstimate",
    "DelayStatus",
    "DeliveryStatus",
    "DispatchResult",
    "DoubleTalkCategory",
    "DoubleTalkClassifier",
    "DoubleTalkEvidence",
    "DspProcessingResult",
    "DspStageError",
    "ENVIRONMENT_PROFILES",
    "EnhancementProfile",
    "EnvironmentProfileId",
    "F0_B_ADAPTIVE_DSP_FLAG",
    "F0_B_AEC_FLAG",
    "F0_B_RNNOISE_FLAG",
    "F0_STRICT_PIPELINE_FLAG",
    "NccDelayEstimator",
    "PlaybackReferenceReader",
    "PlaybackReferenceSource",
    "ReferenceAssociation",
    "ReferenceChunk",
    "ReferenceReadResult",
    "RnnoiseCapability",
    "RnnoiseDenoiserAdapter",
    "RnnoiseProvider",
    "SnrMethod",
    "SnrTap",
    "compute_erle_db",
    "compute_oracle_snr_db",
    "probe_rnnoise_capability",
    "resolve_clock_mapping",
    "resolve_enhancement_profile",
    "F1BoundaryDispatcher",
    "InputOutcomeStatus",
    "InputProfile",
    "LEGACY_WEB_EXTENDED_PROFILE",
    "LegacyAgcGateStage",
    "LegacyAudioInputFacade",
    "LegacyBatchOutput",
    "LegacyDspChain",
    "LegacyHpfStage",
    "LegacySpectralStage",
    "OffsetMapping",
    "PHONE_8K_PROFILE",
    "PipelineResult",
    "RawDtmfBridge",
    "RawDtmfEvent",
    "RawDtmfTapResult",
    "SampleLedger",
    "StatefulResampler",
    "StreamAudioState",
    "StreamStateRegistry",
    "ValidationOutcome",
    "WEB_16K_48K_PROFILE",
    "adapt_audiosocket_chunk",
    "adapt_ingress_to_frame",
    "adapt_web_ws_chunk",
    "analyze_float32_quality",
    "build_f0_flag_registry",
    "config_from_legacy_settings",
    "config_from_snapshot",
    "copy_ingress_bytes",
    "decode_to_float32",
    "default_audio_frontend_config",
    "encode_from_float32",
    "validate_audio_frame",
    "validate_raw_input",
    "verify_core_integration_preflight",
]
