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

from backend.audio_rendering.audiosocket_adapter import (
    AUDIOSOCKET_AUDIO,
    AUDIOSOCKET_DTMF,
    AUDIOSOCKET_ERROR,
    AUDIOSOCKET_HANGUP,
    AUDIOSOCKET_UUID,
    AudioSocketOutboundAdapter,
    AudioSocketStreamParser,
    WireWriteOutcome,
    WireWriteResult,
    encode_audiosocket_audio_frame,
    encode_audiosocket_control,
    encode_audiosocket_packet,
)
from backend.audio_rendering.f6_bc.codec_lab import (
    CodecCapability,
    CodecCapabilityStatus,
    CodecKind,
    CodecTrial,
    CodecTrialResult,
    CodecTrialSpec,
    decode_alaw_pcm16,
    decode_ulaw_pcm16,
    encode_alaw_pcm16,
    encode_ulaw_pcm16,
    get_codec_capability,
)
from backend.audio_rendering.control_adapter import (
    ControlApplicationRecord,
    ControlOwnershipResolver,
    ControlStatus,
    compute_pause_output_samples,
    iter_bounded_pcm_silence,
    validate_post_pause_ms,
)
from backend.audio_rendering.f6_bc.crossfade import (
    AdaptiveCrossfadeAssembler,
    BoundaryRef,
    CrossfadeConfig,
    CrossfadeDecision,
)
from backend.audio_rendering.dsp_adapter import (
    StatefulLegacyDSPAdapter,
    TelephonyFilterCoefficients,
    build_telephony_coefficients,
)
from backend.audio_rendering.f6_bc.enhanced_dsp import EnhancedDSPProcessor, EnhancedDSPProfile
from backend.audio_rendering.framer import FrameSynchronizer
from backend.audio_rendering.input_validator import (
    InputValidationError,
    ValidatedAudioChunk,
    validate_raw_audio_chunk,
)
from backend.audio_rendering.legacy_adapter import (
    ShadowComparisonResult,
    build_legacy_audiosocket_packet,
    compare_legacy_vs_strict,
    iter_legacy_frames,
    render_legacy_wave_48k_to_pcm,
)
from backend.audio_rendering.lifecycle import CloseSummary, RenderLifecycleManager
from backend.audio_rendering.pacing import (
    FRAME_PERIOD_NS,
    ClockDomainMismatchError,
    LatePolicy,
    MonotonicPacer,
    PacingRecord,
    PacingStats,
)
from backend.audio_rendering.f6_bc.pause_ledger import (
    PauseLedgerEntry,
    PauseTargetKind,
    SemanticPauseLedger,
    SilenceObservation,
    observe_boundary_silence,
)
from backend.audio_rendering.pipeline import AudioRenderingPipeline, RenderChunkResult
from backend.audio_rendering.playback_events import PlaybackEventEmitter
from backend.audio_rendering.f6_bc.playback_queue import (
    BoundedPlaybackQueue,
    CapacityBudget,
    CapacityReservation,
    FlushIntent,
    FlushReceipt,
    FlushScopeResult,
    GlobalCapacityCoordinator,
    MediaItemState,
    QueueEntry,
    ReservationStatus,
    UnsentCursor,
)
from backend.audio_rendering.f6_bc.playback_reference import (
    PlaybackReference,
    PlaybackReferenceTap,
    ReferenceDeliveryState,
    ReferenceGap,
    ReferenceReadResult,
)
from backend.audio_rendering.profile_adapter import (
    PaceOwner,
    QuantizationPolicy,
    RenderProfile,
    StreamProfileBinding,
    TerminalPolicy,
    UnknownRenderProfileError,
    resolve_render_profile,
    validate_web_client_capabilities,
)
from backend.audio_rendering.quantizer import QuantizationResult, quantize_float32_to_pcm16le
from backend.audio_rendering.resampler import StreamingOutputResampler
from backend.audio_rendering.sample_accounting import SampleAccounting, SampleAccountingSnapshot
from backend.audio_rendering.stream_state import DiscontinuityRecord, RenderStreamState, StreamStateRegistry
from backend.audio_rendering.submission_fence import (
    AtomicSubmissionFence,
    SubmissionOutcome,
    SubmissionRecord,
    TransportCompletionUncertainError,
)
from backend.audio_rendering.telemetry import RenderTelemetry
from backend.audio_rendering.web_adapter import (
    EXPECTED_WEB_PCM_BYTES,
    WebTransportAdapter,
    WebTransportResult,
    build_web_control_envelope,
    encode_web_audio_frame,
)
from backend.audio_rendering.f6_bc.wsola_adapter import (
    RateDisposition,
    RateOwner,
    WSOLAAdapter,
    WSOLAConfig,
    resolve_rate_ownership,
)

__all__ = [
    "AUDIOSOCKET_AUDIO",
    "AUDIOSOCKET_DTMF",
    "AUDIOSOCKET_ERROR",
    "AUDIOSOCKET_HANGUP",
    "AUDIOSOCKET_UUID",
    "AtomicSubmissionFence",
    "AudioRenderingPipeline",
    "AudioSocketOutboundAdapter",
    "AudioSocketStreamParser",
    "ClockDomainMismatchError",
    "CloseSummary",
    "ControlApplicationRecord",
    "ControlOwnershipResolver",
    "ControlStatus",
    "DiscontinuityRecord",
    "EXPECTED_WEB_PCM_BYTES",
    "FRAME_PERIOD_NS",
    "FrameSynchronizer",
    "InputValidationError",
    "LatePolicy",
    "MonotonicPacer",
    "PaceOwner",
    "PacingRecord",
    "PacingStats",
    "PlaybackEventEmitter",
    "QuantizationPolicy",
    "QuantizationResult",
    "RenderChunkResult",
    "RenderLifecycleManager",
    "RenderProfile",
    "RenderStreamState",
    "RenderTelemetry",
    "SampleAccounting",
    "SampleAccountingSnapshot",
    "ShadowComparisonResult",
    "StatefulLegacyDSPAdapter",
    "StreamProfileBinding",
    "StreamStateRegistry",
    "StreamingOutputResampler",
    "SubmissionOutcome",
    "SubmissionRecord",
    "TelephonyFilterCoefficients",
    "TerminalPolicy",
    "TransportCompletionUncertainError",
    "UnknownRenderProfileError",
    "ValidatedAudioChunk",
    "WebTransportAdapter",
    "WebTransportResult",
    "WireWriteOutcome",
    "WireWriteResult",
    "build_legacy_audiosocket_packet",
    "build_telephony_coefficients",
    "build_web_control_envelope",
    "compare_legacy_vs_strict",
    "compute_pause_output_samples",
    "encode_audiosocket_audio_frame",
    "encode_audiosocket_control",
    "encode_audiosocket_packet",
    "encode_web_audio_frame",
    "iter_bounded_pcm_silence",
    "iter_legacy_frames",
    "quantize_float32_to_pcm16le",
    "render_legacy_wave_48k_to_pcm",
    "resolve_render_profile",
    "validate_post_pause_ms",
    "validate_raw_audio_chunk",
    "validate_web_client_capabilities",
]
