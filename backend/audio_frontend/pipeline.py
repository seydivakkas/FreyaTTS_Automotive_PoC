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

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from backend.audio_frontend.f0_b.acoustic_evidence import AcousticEvidence
from backend.audio_frontend.config_adapter import (
    AudioFrontendConfig,
    default_audio_frontend_config,
)
from backend.audio_frontend.dispatcher import F1BoundaryDispatcher
from backend.audio_frontend.format_validator import (
    LEGACY_WEB_EXTENDED_PROFILE,
    InputOutcomeStatus,
    InputProfile,
    bytes_per_sample,
    normalize_encoding,
    validate_audio_frame,
    validate_raw_input,
)
from backend.audio_frontend.legacy_dsp_adapter import DspStageError
from backend.audio_frontend.lifecycle import AudioFrontendLifecycle
from backend.audio_frontend.pcm_conversion import (
    ConversionStats,
    copy_ingress_bytes,
    decode_to_float32,
    encode_from_float32,
)
from backend.audio_frontend.quality_analyzer import AudioQualityMetrics, analyze_float32_quality
from backend.audio_frontend.raw_dtmf_bridge import RawDtmfEvent
from backend.audio_frontend.f0_b.reference_adapter import PlaybackReferenceSource
from backend.audio_frontend.f0_b.rnnoise_adapter import RnnoiseProvider
from backend.audio_frontend.stream_state import StreamAudioState, StreamStateRegistry
from backend.audio_frontend.telemetry import AudioFrontendTelemetry
from backend.core.contracts.audio import AudioEncoding, AudioFormat, AudioFrame
from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    ErrorCategory,
    ErrorInfo,
    Retryability,
    SessionIdentity,
    StreamDirection,
    StreamRef,
)
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.core.runtime.result_admission import AdmissionStatus
from backend.core.runtime.session_context import SessionContext, SessionLifecycleState


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Typed outcome of processing one audio frame or control action in F0-A."""

    ok: bool
    status: InputOutcomeStatus
    reason: str
    output_frames: tuple[AudioFrame, ...] = ()
    dtmf_events: tuple[RawDtmfEvent, ...] = ()
    error_info: ErrorInfo | None = None
    quality: AudioQualityMetrics | None = None
    conversion_stats: ConversionStats | None = None
    route: str = ""
    discontinuity: bool = False
    processing_ms: float = 0.0
    acoustic_evidence: AcousticEvidence | None = None


def _activate_standalone_session(ctx: SessionContext) -> None:
    """Synchronously transition a freshly constructed standalone SessionContext to ACTIVE."""
    if ctx.lifecycle_state == SessionLifecycleState.NEW:
        ctx._move_state(SessionLifecycleState.OPENING)
        ctx._emit_safe("session.opening")
        ctx._move_state(SessionLifecycleState.ACTIVE)
        ctx._emit_safe("session.opened")


class AudioInputPipeline:
    """
    Single authoritative F0-A Audio Input Foundation facade.

    Pipeline flow (single active route per frame, no double DSP/resampling):
      1. Validate raw input / M01 AudioFrame & bounds BEFORE allocation.
      2. Copy mutable ingress at ownership seam and check M02 session/epoch/ordering fence.
      3. Reserve bounded F1 dispatcher capacity before processing.
      4. Decode to normalized float32 [-1.0, 1.0]; exclude terminal padding from speech/DSP.
      5. Run pre-DSP raw DTMF bridge at native source sample rate with cross-path dedup.
      6. Run selected route (already_processed | bypass | legacy_dsp HPF->FFT->AGC/gate).
      7. Resample via per-stream StatefulResampler to 16 kHz mono (identity pass-through at 16 kHz).
      8. Analyze finite quality metrics, construct M01 16 kHz mono AudioFrame, fence-check & dispatch to F1.
      9. Record safe M04 telemetry with zero raw audio/digit/PII leakage.
    """

    def __init__(
        self,
        *,
        session_id: str = "f0a-session",
        trace_id: str | None = None,
        session_ctx: SessionContext | None = None,
        config: AudioFrontendConfig | None = None,
        default_profile: InputProfile | None = None,
        clock: Clock | None = None,
        telemetry: AudioFrontendTelemetry | None = None,
        f1_consumer: Callable[[AudioFrame], None] | None = None,
        dtmf_consumer: Callable[[RawDtmfEvent], None] | None = None,
        raw_tap_observer: Callable[[np.ndarray, int], None] | None = None,
        reference_source: PlaybackReferenceSource | None = None,
        rnnoise_provider: RnnoiseProvider | None = None,
        auto_activate_standalone: bool = True,
    ) -> None:
        self.config = config or default_audio_frontend_config()
        self.clock: Clock = clock or (session_ctx.clock if session_ctx is not None else SystemMonotonicClock())
        if session_ctx is None:
            session_ctx = SessionContext(
                SessionIdentity(session_id=session_id, trace_id=trace_id),
                clock=self.clock,
                max_queue_items=self.config.max_queue_items,
                max_queue_bytes=self.config.max_queue_bytes,
            )
            if auto_activate_standalone:
                _activate_standalone_session(session_ctx)
        self.session_ctx = session_ctx
        self.default_profile = default_profile or LEGACY_WEB_EXTENDED_PROFILE
        self.telemetry = telemetry or AudioFrontendTelemetry(clock=self.clock)
        self._dtmf_consumer = dtmf_consumer
        self._raw_tap_observer = raw_tap_observer
        self._reference_source = reference_source
        self._rnnoise_provider = rnnoise_provider

        self.registry = StreamStateRegistry(self.session_ctx, clock=self.clock)
        self.dispatcher = F1BoundaryDispatcher(
            self.session_ctx,
            max_items=self.config.max_queue_items,
            max_bytes=self.config.max_queue_bytes,
            f1_consumer=f1_consumer,
            control_consumer=dtmf_consumer,
        )
        self.lifecycle = AudioFrontendLifecycle(self.registry, self.dispatcher)

    def open_stream(
        self,
        stream_ref: StreamRef,
        *,
        sample_rate_hz: int,
        profile: InputProfile | None = None,
        config: AudioFrontendConfig | None = None,
    ) -> StreamAudioState:
        """Explicitly open or roll over a stream epoch with pinned config."""
        prof = profile or self.default_profile
        cfg = config or self.config
        if sample_rate_hz not in prof.supported_rates_hz:
            raise ValueError(f"Unsupported sample_rate_hz {sample_rate_hz} for profile {prof.profile_id}")
        return self.registry.create_or_get(
            stream_ref,
            native_sample_rate_hz=sample_rate_hz,
            profile=prof,
            config=cfg,
            raw_tap_observer=self._raw_tap_observer,
            dtmf_dispatch=self._on_dtmf_event,
            reference_source=self._reference_source,
            rnnoise_provider=self._rnnoise_provider,
        )

    def _on_dtmf_event(self, ev: RawDtmfEvent) -> None:
        self.dispatcher.admit_control_event(ev)
        self.telemetry.record_dtmf_observed(
            session_id=self.session_ctx.identity.session_id,
            trace_id=self.session_ctx.identity.trace_id,
            source=ev.source,
            deduped=ev.deduped,
        )

    def _fail(
        self,
        *,
        status: InputOutcomeStatus,
        code: str,
        reason: str,
        category: ErrorCategory = ErrorCategory.VALIDATION,
        backpressure: bool = False,
        discontinuity: bool = False,
    ) -> PipelineResult:
        err = ErrorInfo(
            code=code,
            category=category,
            retryable=Retryability.YES if backpressure else Retryability.NO,
            safe_message=reason,
        )
        self.telemetry.record_rejection(
            session_id=self.session_ctx.identity.session_id,
            trace_id=self.session_ctx.identity.trace_id,
            reason=reason,
            error_info=err,
            backpressure=backpressure,
        )
        return PipelineResult(
            ok=False,
            status=status,
            reason=reason,
            error_info=err,
            discontinuity=discontinuity,
        )

    def ingest_raw(
        self,
        *,
        stream_ref: StreamRef,
        payload: Any,
        sample_rate_hz: Any,
        channels: Any = 1,
        encoding: AudioEncoding | str = AudioEncoding.PCM_S16LE,
        sample_count: Any,
        sequence: int,
        sample_offset: int,
        valid_sample_count: Any = None,
        endian: str = "little",
        captured_monotonic_ns: Any = None,
        clock_domain: str | None = None,
        profile: InputProfile | None = None,
        flags: frozenset[str] = frozenset(),
    ) -> PipelineResult:
        """Validate, own, process, resample, and dispatch a raw audio payload."""
        prof = profile or self.default_profile
        val = validate_raw_input(
            payload=payload,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
            encoding=encoding,
            sample_count=sample_count,
            profile=prof,
            valid_sample_count=valid_sample_count,
            endian=endian,
            captured_monotonic_ns=captured_monotonic_ns,
            clock_domain=clock_domain,
            stream_ref=stream_ref,
        )
        if not val.ok or val.audio_format is None:
            return self._fail(
                status=val.status,
                code=val.error_info.code if val.error_info else "F0_VALIDATION_FAILED",
                reason=val.reason,
            )

        owned_payload = copy_ingress_bytes(payload)
        frame = AudioFrame(
            schema_version=CONTRACT_SCHEMA_VERSION,
            stream_ref=stream_ref,
            sequence=sequence,
            format=val.audio_format,
            sample_count=sample_count,
            sample_offset=sample_offset,
            payload=owned_payload,
            captured_monotonic_ns=captured_monotonic_ns,
            clock_domain=clock_domain,
            valid_sample_count=valid_sample_count,
            flags=flags,
        )
        return self.ingest_frame(frame, profile=prof)

    def ingest_frame(
        self,
        frame: AudioFrame,
        *,
        profile: InputProfile | None = None,
    ) -> PipelineResult:
        """Process a canonical M01 AudioFrame through F0-A and admit 16 kHz mono output to F1."""
        start_ns = self.clock.monotonic_ns()
        prof = profile or self.default_profile

        val = validate_audio_frame(frame, prof)
        if not val.ok:
            return self._fail(
                status=val.status,
                code=val.error_info.code if val.error_info else "F0_INVALID_FRAME",
                reason=val.reason,
            )

        if self.session_ctx.lifecycle_state in {SessionLifecycleState.CLOSING, SessionLifecycleState.CLOSED}:
            return self._fail(
                status=InputOutcomeStatus.CLOSED,
                code="F0_SESSION_CLOSED",
                reason="Session is closing or closed",
                category=ErrorCategory.STALE_SCOPE,
            )
        if self.session_ctx.lifecycle_state != SessionLifecycleState.ACTIVE:
            return self._fail(
                status=InputOutcomeStatus.INVALID,
                code="F0_SESSION_NOT_ACTIVE",
                reason=f"Session not active: {self.session_ctx.lifecycle_state.value}",
            )
        if self.session_ctx.root_scope.is_cancel_requested:
            return self._fail(
                status=InputOutcomeStatus.CLOSED,
                code="F0_SESSION_CANCELED",
                reason="Session root scope canceled",
                category=ErrorCategory.STALE_SCOPE,
            )

        # Retrieve or lazily bind stream state (or roll over to higher epoch); reject stale epoch or closed stream
        state, state_reason = self.registry.get_active(frame.stream_ref)
        if state is None:
            if state_reason in ("stale_session", "stale_epoch"):
                return self._fail(
                    status=InputOutcomeStatus.STALE,
                    code="F0_STALE_STREAM_EPOCH",
                    reason=f"Rejected stale frame: {state_reason}",
                    category=ErrorCategory.STALE_SCOPE,
                )
            if state_reason == "stream_closed":
                return self._fail(
                    status=InputOutcomeStatus.CLOSED,
                    code="F0_STREAM_CLOSED",
                    reason="Stream already closed",
                    category=ErrorCategory.STALE_SCOPE,
                )
            try:
                state = self.registry.create_or_get(
                    frame.stream_ref,
                    native_sample_rate_hz=frame.format.sample_rate_hz,
                    profile=prof,
                    config=self.config,
                    raw_tap_observer=self._raw_tap_observer,
                    dtmf_dispatch=self._on_dtmf_event,
                    reference_source=self._reference_source,
                    rnnoise_provider=self._rnnoise_provider,
                )
            except Exception as exc:
                return self._fail(
                    status=InputOutcomeStatus.STALE,
                    code="F0_STREAM_OPEN_REJECTED",
                    reason=str(exc),
                    category=ErrorCategory.STALE_SCOPE,
                )

        if frame.format.sample_rate_hz != state.native_sample_rate_hz:
            return self._fail(
                status=InputOutcomeStatus.UNSUPPORTED,
                code="F0_RATE_CHANGE_REQUIRES_NEW_EPOCH",
                reason="Sample rate change requires new format_epoch",
            )

        # Verify sequence & half-open [sample_offset, sample_offset + sample_count) ordering
        allow_gap = state.profile.gap_policy == "record_discontinuity"
        ord_ok, ord_reason, gap_samples = state.ledger.check_ordering(
            sequence=frame.sequence,
            sample_offset=frame.sample_offset,
            sample_count=frame.sample_count,
            allow_gap=allow_gap,
        )
        if not ord_ok:
            state.ledger.record_rejected(frame.sample_count, is_overlap="overlap" in ord_reason or "duplicate" in ord_reason)
            return self._fail(
                status=InputOutcomeStatus.INVALID,
                code="F0_ORDERING_VIOLATION",
                reason=ord_reason,
            )

        valid_n = frame.sample_count if frame.valid_sample_count is None else frame.valid_sample_count
        out_bps = bytes_per_sample(state.profile.output_encoding)
        est_out_samples = math.ceil((valid_n * state.profile.output_sample_rate_hz) / state.native_sample_rate_hz) if valid_n > 0 else 0
        est_out_bytes = est_out_samples * out_bps

        if est_out_bytes > 0 and not self.dispatcher.reserve_in_flight(est_out_bytes, est_out_samples):
            state.ledger.record_rejected(frame.sample_count)
            return self._fail(
                status=InputOutcomeStatus.BACKPRESSURE,
                code="F0_F1_QUEUE_FULL",
                reason="F1 boundary queue capacity exhausted",
                category=ErrorCategory.CAPACITY,
                backpressure=True,
            )

        if not self.lifecycle.enter_in_flight(state):
            if est_out_bytes > 0:
                self.dispatcher.release_in_flight(est_out_bytes, est_out_samples)
            return self._fail(
                status=InputOutcomeStatus.CLOSED,
                code="F0_STREAM_CLOSING",
                reason="Stream closed prior to processing",
                category=ErrorCategory.STALE_SCOPE,
            )

        try:
            discontinuity = gap_samples > 0
            if discontinuity:
                # Explicitly reset filter/resampler history across discontinuity gap without fabricating audio
                state.dsp_chain.reset()
                if state.adaptive_chain is not None:
                    state.adaptive_chain.reset()
                state.resampler.reset()

            state.ledger.record_accepted(
                sequence=frame.sequence,
                sample_offset=frame.sample_offset,
                sample_count=frame.sample_count,
                valid_sample_count=frame.valid_sample_count,
                gap_samples=gap_samples,
            )

            decoded, conv_stats = decode_to_float32(
                frame.payload,
                frame.format,
                overrange_policy=state.profile.overrange_policy,
            )
            valid_samples = decoded[:valid_n]

            if valid_n == 0:
                state.ledger.record_consumed_and_emitted(
                    input_sequence=frame.sequence,
                    input_start_sample=frame.sample_offset,
                    input_end_sample_exclusive=frame.sample_offset + frame.sample_count,
                    consumed_valid_samples=0,
                    emitted_output_samples=0,
                    padding_samples=frame.sample_count,
                    has_gap_before=discontinuity,
                )
                elapsed_ms = (self.clock.monotonic_ns() - start_ns) / 1_000_000.0
                return PipelineResult(
                    ok=True,
                    status=InputOutcomeStatus.BUFFERED,
                    reason="padding_only_frame_recorded",
                    output_frames=(),
                    conversion_stats=conv_stats,
                    route="padding_only",
                    discontinuity=discontinuity,
                    processing_ms=elapsed_ms,
                )

            # Pre-DSP raw DTMF tap at native sample rate
            dtmf_res = state.dtmf_bridge.tap_raw_samples(valid_samples)

            # Selected DSP route (F0-B adaptive chain if enabled, else legacy F0-A DSP chain)
            acoustic_evidence: AcousticEvidence | None = None
            try:
                if state.adaptive_chain is not None:
                    adaptive_res = state.adaptive_chain.process(
                        dtmf_res.main_samples,
                        output_start_sample=state.ledger.next_output_offset,
                        output_sample_rate_hz=state.profile.output_sample_rate_hz,
                        capture_clock_domain=frame.clock_domain,
                        dtmf_active=len(dtmf_res.emitted_events) > 0,
                        discontinuity=discontinuity,
                    )
                    dsp_samples = adaptive_res.samples
                    dsp_route = adaptive_res.route
                    acoustic_evidence = adaptive_res.evidence
                else:
                    dsp_res = state.dsp_chain.process(dtmf_res.main_samples)
                    dsp_samples = dsp_res.samples
                    dsp_route = dsp_res.route
            except DspStageError as exc:
                state.ledger.record_explicit_discard(valid_n, 0)
                return self._fail(
                    status=InputOutcomeStatus.FAILED,
                    code=f"F0_DSP_STAGE_ERROR_{exc.stage_name.upper()}",
                    reason=exc.safe_message,
                    category=ErrorCategory.INTERNAL,
                    discontinuity=True,
                )

            # Stateful resample to 16 kHz mono (identity pass-through if already 16 kHz)
            resampled = state.resampler.process(dsp_samples)
            if len(resampled) == 0:
                # Zero-output intermediate resampler buffering: do NOT emit fake empty AudioFrame
                state.ledger.record_consumed_and_emitted(
                    input_sequence=frame.sequence,
                    input_start_sample=frame.sample_offset,
                    input_end_sample_exclusive=frame.sample_offset + frame.sample_count,
                    consumed_valid_samples=valid_n,
                    emitted_output_samples=0,
                    padding_samples=frame.sample_count - valid_n,
                    has_gap_before=discontinuity,
                )
                elapsed_ms = (self.clock.monotonic_ns() - start_ns) / 1_000_000.0
                return PipelineResult(
                    ok=True,
                    status=InputOutcomeStatus.BUFFERED,
                    reason="resampler_buffering_intermediate",
                    output_frames=(),
                    dtmf_events=dtmf_res.emitted_events,
                    conversion_stats=conv_stats,
                    route=dsp_route,
                    discontinuity=discontinuity,
                    processing_ms=elapsed_ms,
                    acoustic_evidence=acoustic_evidence,
                )

            quality = analyze_float32_quality(resampled, stage="output")
            out_payload, _ = encode_from_float32(resampled, state.profile.output_encoding)

            out_flags = set(frame.flags) | {f"DSP_ROUTE:{dsp_route}"}
            if discontinuity:
                out_flags.add("DISCONTINUITY_GAP")
            if frame.valid_sample_count is not None and frame.valid_sample_count < frame.sample_count:
                out_flags.add("FINAL_PADDING_STRIPPED")

            out_frame = AudioFrame(
                schema_version=CONTRACT_SCHEMA_VERSION,
                stream_ref=state.output_stream_ref(),
                sequence=state.ledger.next_output_sequence,
                format=AudioFormat(
                    sample_rate_hz=state.profile.output_sample_rate_hz,
                    channels=1,
                    encoding=state.profile.output_encoding,
                ),
                sample_count=len(resampled),
                sample_offset=state.ledger.next_output_offset,
                payload=out_payload,
                captured_monotonic_ns=frame.captured_monotonic_ns,
                clock_domain=frame.clock_domain if frame.captured_monotonic_ns is not None else None,
                valid_sample_count=len(resampled),
                flags=frozenset(out_flags),
            )

            # Release in-flight reservation right before atomic enqueue so reservation doesn't double-count
            if est_out_bytes > 0:
                self.dispatcher.release_in_flight(est_out_bytes, est_out_samples)
                est_out_bytes = 0

            dispatch = self.dispatcher.admit_output_frame(out_frame, state)
            if dispatch.status != AdmissionStatus.ACCEPTED:
                state.ledger.record_explicit_discard(0, len(resampled))
                is_bp = dispatch.status == AdmissionStatus.BACKPRESSURE
                mapped_status = (
                    InputOutcomeStatus.BACKPRESSURE
                    if is_bp
                    else (
                        InputOutcomeStatus.CLOSED
                        if dispatch.status in {AdmissionStatus.CLOSED, AdmissionStatus.CANCELED}
                        else InputOutcomeStatus.STALE
                    )
                )
                return self._fail(
                    status=mapped_status,
                    code=f"F0_DISPATCH_{dispatch.status.value}",
                    reason=dispatch.reason,
                    category=ErrorCategory.CAPACITY if is_bp else ErrorCategory.STALE_SCOPE,
                    backpressure=is_bp,
                    discontinuity=discontinuity,
                )

            state.ledger.record_consumed_and_emitted(
                input_sequence=frame.sequence,
                input_start_sample=frame.sample_offset,
                input_end_sample_exclusive=frame.sample_offset + frame.sample_count,
                consumed_valid_samples=valid_n,
                emitted_output_samples=len(resampled),
                padding_samples=frame.sample_count - valid_n,
                has_gap_before=discontinuity,
            )

            elapsed_ms = (self.clock.monotonic_ns() - start_ns) / 1_000_000.0
            block_dur_ms = (valid_n / float(state.native_sample_rate_hz)) * 1000.0
            self.telemetry.record_frame_processed(
                session_id=self.session_ctx.identity.session_id,
                trace_id=self.session_ctx.identity.trace_id,
                stream_id=state.stream_ref.stream_id,
                format_epoch=state.stream_ref.format_epoch,
                input_rate_hz=state.native_sample_rate_hz,
                encoding=frame.format.encoding.value,
                valid_sample_count=valid_n,
                padding_samples=frame.sample_count - valid_n,
                config_revision=state.pinned_config.config_revision,
                route=dsp_route,
                processing_ms=elapsed_ms,
                block_duration_ms=block_dur_ms,
                queue_delay_ms=0.0,
                group_delay_samples=state.resampler.delay_samples(),
                quality=quality,
            )
            return PipelineResult(
                ok=True,
                status=InputOutcomeStatus.ACCEPTED,
                reason="processed",
                output_frames=(out_frame,),
                dtmf_events=dtmf_res.emitted_events,
                quality=quality,
                conversion_stats=conv_stats,
                route=dsp_route,
                discontinuity=discontinuity,
                processing_ms=elapsed_ms,
                acoustic_evidence=acoustic_evidence,
            )
        finally:
            if est_out_bytes > 0:
                self.dispatcher.release_in_flight(est_out_bytes, est_out_samples)
            self.lifecycle.exit_in_flight(state)

    def flush_eos(self, stream_ref: StreamRef) -> PipelineResult:
        """Flush buffered resampler tail at End-Of-Stream exactly once (idempotent)."""
        start_ns = self.clock.monotonic_ns()
        state, reason = self.registry.get_active(stream_ref)
        if state is None:
            if reason == "stream_closed":
                return PipelineResult(ok=True, status=InputOutcomeStatus.ACCEPTED, reason="already_closed_idempotent")
            return self._fail(
                status=InputOutcomeStatus.STALE,
                code="F0_EOS_STALE_STREAM",
                reason=reason,
                category=ErrorCategory.STALE_SCOPE,
            )
        if state.eos_flushed:
            return PipelineResult(ok=True, status=InputOutcomeStatus.ACCEPTED, reason="eos_already_flushed_idempotent")

        tail = state.resampler.flush()
        if len(tail) == 0:
            state.ledger.record_eos_flush(0)
            state.eos_flushed = True
            return PipelineResult(
                ok=True,
                status=InputOutcomeStatus.ACCEPTED,
                reason="eos_flushed_empty_tail",
                output_frames=(),
                processing_ms=(self.clock.monotonic_ns() - start_ns) / 1_000_000.0,
            )

        out_payload, _ = encode_from_float32(tail, state.profile.output_encoding)
        out_frame = AudioFrame(
            schema_version=CONTRACT_SCHEMA_VERSION,
            stream_ref=state.output_stream_ref(),
            sequence=state.ledger.next_output_sequence,
            format=AudioFormat(
                sample_rate_hz=state.profile.output_sample_rate_hz,
                channels=1,
                encoding=state.profile.output_encoding,
            ),
            sample_count=len(tail),
            sample_offset=state.ledger.next_output_offset,
            payload=out_payload,
            valid_sample_count=len(tail),
            flags=frozenset({"EOS_FLUSH"}),
        )
        dispatch = self.dispatcher.admit_output_frame(out_frame, state)
        if dispatch.status != AdmissionStatus.ACCEPTED:
            state.ledger.record_explicit_discard(0, len(tail))
            state.eos_flushed = True
            return self._fail(
                status=InputOutcomeStatus.BACKPRESSURE if dispatch.status == AdmissionStatus.BACKPRESSURE else InputOutcomeStatus.CLOSED,
                code=f"F0_EOS_DISPATCH_{dispatch.status.value}",
                reason=dispatch.reason,
                backpressure=dispatch.status == AdmissionStatus.BACKPRESSURE,
            )

        state.ledger.record_eos_flush(len(tail))
        state.eos_flushed = True
        quality = analyze_float32_quality(tail, stage="eos_flush")
        return PipelineResult(
            ok=True,
            status=InputOutcomeStatus.ACCEPTED,
            reason="eos_flushed",
            output_frames=(out_frame,),
            quality=quality,
            route="eos_flush",
            processing_ms=(self.clock.monotonic_ns() - start_ns) / 1_000_000.0,
        )

    def submit_signaling_dtmf(self, stream_ref: StreamRef, digit: str) -> RawDtmfEvent | None:
        """Admit out-of-band DTMF signaling event with cross-path dedup."""
        state, _ = self.registry.get_active(stream_ref)
        if state is None:
            return None
        return state.dtmf_bridge.submit_signaling_digit(digit)

    def close_stream(self, stream_ref: StreamRef, *, reason: str = "normal_close") -> bool:
        return self.lifecycle.close_stream(stream_ref, reason=reason)

    def close(self, *, reason: str = "session_close") -> int:
        return self.lifecycle.close_all(reason=reason)
