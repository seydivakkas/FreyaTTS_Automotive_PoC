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

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import numpy as np

from backend.audio_rendering.control_adapter import ControlApplicationRecord, iter_bounded_pcm_silence
from backend.audio_rendering.f6_bc.crossfade import AdaptiveCrossfadeAssembler, BoundaryRef, CrossfadeDecision
from backend.audio_rendering.f6_bc.enhanced_dsp import EnhancedDSPProcessor, EnhancedDSPProfile
from backend.audio_rendering.input_validator import InputValidationError, validate_raw_audio_chunk
from backend.audio_rendering.lifecycle import CloseSummary, RenderLifecycleManager
from backend.audio_rendering.pacing import LatePolicy, MonotonicPacer
from backend.audio_rendering.f6_bc.pause_ledger import (
    PauseTargetKind,
    SemanticPauseLedger,
    observe_boundary_silence,
)
from backend.audio_rendering.playback_events import PlaybackEventEmitter
from backend.audio_rendering.f6_bc.playback_queue import (
    BoundedPlaybackQueue,
    CapacityBudget,
    FlushIntent,
    FlushReceipt,
    GlobalCapacityCoordinator,
    ReservationStatus,
)
from backend.audio_rendering.f6_bc.playback_reference import (
    PlaybackReferenceTap,
    ReferenceDeliveryState,
)
from backend.audio_rendering.profile_adapter import (
    PaceOwner,
    QuantizationPolicy,
    RenderProfile,
    StreamProfileBinding,
    TerminalPolicy,
    resolve_render_profile,
)
from backend.audio_rendering.quantizer import quantize_float32_to_pcm16le
from backend.audio_rendering.sample_accounting import SampleAccountingSnapshot
from backend.audio_rendering.stream_state import RenderStreamState, StreamStateRegistry
from backend.audio_rendering.submission_fence import AtomicSubmissionFence, SubmissionOutcome, SubmissionRecord
from backend.audio_rendering.telemetry import RenderTelemetry
from backend.audio_rendering.f6_bc.wsola_adapter import RateOwner, WSOLAAdapter, resolve_rate_ownership
from backend.core.configuration.contracts import ConfigSnapshot
from backend.core.configuration.feature_flags import FeatureFlagRegistry
from backend.core.contracts.common import GenerationRef, SessionIdentity, StreamDirection, StreamRef
from backend.core.contracts.playback import ObservationScope, PlaybackEventKind, PlaybackProfile, RenderedFrame
from backend.core.contracts.synthesis import AudioChunk, ChunkPlan, SynthesisPlan
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.core.runtime.result_admission import AdmissionStatus
from backend.core.runtime.session_context import SessionContext
from backend.core.runtime.turn_generation import PauseRef


@dataclass(frozen=True, slots=True)
class RenderChunkResult:
    admitted: bool
    frames: tuple[RenderedFrame, ...]
    queue_statuses: tuple[AdmissionStatus, ...]
    control_records: tuple[ControlApplicationRecord, ...]
    rejection_reason: str | None = None


class AudioRenderingPipeline:
    """
    Single authoritative F6-A audio rendering and transport orchestration pipeline.

    Stage order:
    1. M02 session/generation admission & M01 AudioChunk validation
    2. Control ownership evaluation (speed, fade, post_pause_ms)
    3. Stateful legacy DSP pre-resample (48 kHz HPF + 3.2 kHz presence boost when enabled)
    4. Stateful CPU output resampler (48k -> 16k WEB or 48k -> 8k AUDIOSOCKET)
    5. Stateful post-resample soft peak limiter (`tanh(x * 1.15)` when enabled)
    6. Finite saturating PCM_S16LE quantization
    7. Exact 20 ms frame assembly (`RenderedFrame`: 320/640B web, 160/320B phone)
    8. Bounded M02 queue + monotonic 20_000_000 ns pacing + atomic submission fence
    """

    def __init__(
        self,
        *,
        session_id: str,
        trace_id: str | None = None,
        trusted_channel: str | PlaybackProfile = "web",
        stream_id: str = "output-0",
        clock: Clock | None = None,
        snapshot: ConfigSnapshot | None = None,
        flag_registry: FeatureFlagRegistry | None = None,
        dsp_enabled: bool | None = None,
        quantization_policy: QuantizationPolicy = QuantizationPolicy.SATURATING_32768,
        terminal_policy: TerminalPolicy = TerminalPolicy.PAD_ONCE_WITH_ZERO,
        pace_owner: PaceOwner = PaceOwner.SERVER,
        late_policy: LatePolicy = LatePolicy.REANCHOR,
        max_lateness_ns: int = 500_000_000,
        sleep_ns_fn: Callable[[int], Awaitable[None]] | None = None,
        max_queue_items: int | None = None,
        max_queue_bytes: int | None = None,
        telemetry: RenderTelemetry | None = None,
        writer_id: str = "f6.pipeline",
        capacity_budget: CapacityBudget | None = None,
        global_capacity: GlobalCapacityCoordinator | None = None,
        reference_tap: PlaybackReferenceTap | None = None,
        enhanced_dsp_profile: EnhancedDSPProfile | None = None,
        wsola_enabled: bool = False,
        crossfade_enabled: bool = False,
        pause_target_kind: PauseTargetKind = PauseTargetKind.ADDITIONAL_LEGACY,
    ) -> None:
        self.clock: Clock = clock or SystemMonotonicClock()
        self.profile: RenderProfile = resolve_render_profile(
            trusted_channel,
            snapshot=snapshot,
            flag_registry=flag_registry,
            dsp_enabled=dsp_enabled,
            quantization_policy=quantization_policy,
            terminal_policy=terminal_policy,
            pace_owner=pace_owner,
            max_queue_items=max_queue_items or 64,
            max_queue_bytes=max_queue_bytes or (256 * 1024),
        )
        self.session_ctx = SessionContext(
            SessionIdentity(session_id=session_id, trace_id=trace_id),
            clock=self.clock,
            max_queue_items=self.profile.max_queue_items,
            max_queue_bytes=self.profile.max_queue_bytes,
        )
        self.registry = StreamStateRegistry()
        self.events = PlaybackEventEmitter(clock=self.clock)
        self.telemetry = telemetry or RenderTelemetry(clock=self.clock)
        self.lifecycle = RenderLifecycleManager(
            session_ctx=self.session_ctx,
            registry=self.registry,
            events=self.events,
            telemetry=self.telemetry,
        )
        self.pacer = MonotonicPacer(
            self.clock,
            frame_period_ns=self.profile.frame_period_ns,
            late_policy=late_policy,
            max_lateness_ns=max_lateness_ns,
            sleep_ns_fn=sleep_ns_fn,
        )
        self.writer_id = writer_id
        self.binding = StreamProfileBinding(
            StreamRef(
                session_id=session_id,
                stream_id=stream_id,
                direction=StreamDirection.OUTPUT,
                format_epoch=0,
            ),
            self.profile,
        )
        self._stream_state: RenderStreamState | None = None
        self._fence: AtomicSubmissionFence | None = None
        self._started_generations: set[tuple[int, int]] = set()
        self._active_plan: SynthesisPlan | None = None

        # F6-B queue & reference tap
        eff_max_items = self.profile.max_queue_items
        eff_max_bytes = self.profile.max_queue_bytes
        self.capacity_budget = capacity_budget or CapacityBudget(
            max_frames=eff_max_items,
            max_target_samples=eff_max_items * self.profile.samples_per_frame,
            max_payload_bytes=eff_max_bytes,
            max_workspace_bytes=max(eff_max_bytes * 2, 64 * 1024),
            high_watermark_frames=max(1, eff_max_items - max(1, eff_max_items // 4)) if eff_max_items > 1 else 1,
            low_watermark_frames=max(0, eff_max_items // 4) if eff_max_items > 1 else 0,
        )
        self.playback_queue = BoundedPlaybackQueue(
            session_id=session_id,
            incarnation_id=self.session_ctx.incarnation_id,
            stream_ref=self.binding.stream_ref,
            budget=self.capacity_budget,
            clock=self.clock,
            global_coordinator=global_capacity,
        )
        self.reference_tap = reference_tap or PlaybackReferenceTap(
            session_id=session_id,
            stream_id=stream_id,
            format_epoch=self.binding.stream_ref.format_epoch,
        )

        # F6-C opt-in modules (all OFF by default)
        self.enhanced_dsp_profile = enhanced_dsp_profile or EnhancedDSPProfile(enabled=False)
        self.enhanced_dsp = EnhancedDSPProcessor(
            self.enhanced_dsp_profile,
            input_rate_hz=self.profile.input_format.sample_rate_hz,
        )
        self.wsola_enabled = wsola_enabled
        self.wsola = WSOLAAdapter()
        self.crossfade_enabled = crossfade_enabled
        self.crossfader = AdaptiveCrossfadeAssembler()
        self.pause_target_kind = pause_target_kind
        self.pause_ledger = SemanticPauseLedger(rate_hz=self.profile.input_format.sample_rate_hz)
        self._prev_chunk_tail_48k: np.ndarray | None = None
        self._prev_chunk_id: str | None = None
        self._flush_seq = 0

    @property
    def stream_state(self) -> RenderStreamState:
        if self._stream_state is None:
            raise RuntimeError("Pipeline has no active turn/generation; call start_generation() first")
        return self._stream_state

    @property
    def fence(self) -> AtomicSubmissionFence:
        if self._fence is None:
            raise RuntimeError("Pipeline has no active fence; call start_generation() first")
        return self._fence

    async def start_generation(self, *, reason: str = "start_generation") -> GenerationRef:
        await self.lifecycle.ensure_open()
        tref, _ = await self.session_ctx.begin_turn()
        gref, _ = await self.session_ctx.begin_generation(tref)
        if self._stream_state is None:
            self._stream_state = self.registry.create(
                binding=self.binding,
                generation_ref=gref,
                writer_id=self.writer_id,
            )
            self._fence = AtomicSubmissionFence(
                session_ctx=self.session_ctx,
                pacer=self.pacer,
                accounting=self._stream_state.accounting,
            )
        else:
            prior_gen = self._stream_state.active_generation_ref
            if self._fence is not None:
                self._fence.purge_generation(prior_gen)
            self._stream_state.switch_generation(gref, reason=reason, writer_id=self.writer_id)
            self.pacer.reset_segment()
        self._active_plan = None
        self.playback_queue.set_active_generation(gref, plan_revision=0)
        self.enhanced_dsp.reset()
        self.wsola.reset()
        self.crossfader.reset()
        self.pause_ledger.reset()
        self._prev_chunk_tail_48k = None
        self._prev_chunk_id = None
        return gref

    async def advance_epoch(
        self,
        *,
        new_snapshot: ConfigSnapshot,
        dsp_enabled: bool | None = None,
        quantization_policy: QuantizationPolicy | None = None,
    ) -> StreamRef:
        """Open a new format_epoch for updated config without mutating the prior epoch."""
        new_profile = resolve_render_profile(
            self.profile.profile,
            snapshot=new_snapshot,
            dsp_enabled=self.profile.dsp_enabled if dsp_enabled is None else dsp_enabled,
            quantization_policy=quantization_policy or self.profile.quantization_policy,
            terminal_policy=self.profile.terminal_policy,
            pace_owner=self.profile.pace_owner,
            max_queue_items=self.profile.max_queue_items,
            max_queue_bytes=self.profile.max_queue_bytes,
        )
        if self._stream_state is not None:
            self._stream_state.close()
        self.profile = new_profile
        self.binding = self.binding.advance_epoch(new_profile)
        gref = self.session_ctx.tg.active_generation
        if gref is None:
            await self.lifecycle.ensure_open()
            tref, _ = await self.session_ctx.begin_turn()
            gref, _ = await self.session_ctx.begin_generation(tref)
        self._stream_state = self.registry.create(
            binding=self.binding,
            generation_ref=gref,
            writer_id=self.writer_id,
        )
        self._fence = AtomicSubmissionFence(
            session_ctx=self.session_ctx,
            pacer=self.pacer,
            accounting=self._stream_state.accounting,
        )
        self.pacer.reset_segment()
        return self.binding.stream_ref

    async def render_chunk(
        self,
        chunk: AudioChunk,
        *,
        plan: SynthesisPlan | None = None,
        fade_applied_upstream: bool = True,
        writer_id: str | None = None,
    ) -> RenderChunkResult:
        """Validate, render, quantize, frame, and enqueue an accepted F5 AudioChunk."""
        state = self.stream_state
        state.assert_writer(writer_id or self.writer_id)
        fence = self.fence
        t0_ns = self.clock.monotonic_ns()

        # Check M02 cancellation/scope before allocating or processing DSP
        gen_scope = self.session_ctx.tg.generation_scope
        if (
            self.session_ctx.root_scope.is_cancel_requested
            or gen_scope is None
            or gen_scope.is_cancel_requested
            or self.session_ctx.tg.active_generation != chunk.generation_ref
        ):
            state.accounting.record_raw_rejected(chunk.sample_count if isinstance(chunk, AudioChunk) else 0)
            self.telemetry.record_render_chunk(
                generation_ref=state.active_generation_ref,
                profile=self.profile.profile,
                wall_ns=max(0, self.clock.monotonic_ns() - t0_ns),
                rms_dbfs=None,
                rejected_stale=True,
            )
            return RenderChunkResult(
                admitted=False,
                frames=(),
                queue_statuses=(),
                control_records=(),
                rejection_reason="STALE_OR_CANCELLED_GENERATION",
            )

        if plan is not None:
            self._active_plan = plan
        effective_plan = plan or self._active_plan

        try:
            validated = validate_raw_audio_chunk(
                chunk,
                plan=effective_plan,
                expected_generation_ref=state.active_generation_ref,
                expected_plan_revision=effective_plan.plan_revision if effective_plan else None,
                expected_chunk_index=state.expected_chunk_index,
                seen_chunks=state.seen_chunks,
                max_chunk_samples=self.profile.max_chunk_samples,
            )
        except InputValidationError as exc:
            state.accounting.record_raw_rejected(chunk.sample_count if isinstance(chunk, AudioChunk) else 0)
            raise exc

        state.seen_chunks[chunk.chunk_index] = chunk.chunk_id
        state.expected_chunk_index += 1
        state.accounting.record_raw_accepted(chunk.sample_count, raw_clipped=validated.raw_overrange_samples)

        chunk_plan: ChunkPlan | None = None
        if effective_plan is not None and chunk.chunk_index < len(effective_plan.chunks):
            chunk_plan = effective_plan.chunks[chunk.chunk_index]

        pause_out_samples, ctrl_records = state.controls.evaluate_chunk_controls(
            chunk,
            output_rate_hz=self.profile.output_format.sample_rate_hz,
            chunk_plan=chunk_plan,
            fade_applied_upstream=fade_applied_upstream,
        )

        # Stage 1: pre-resample DSP (48 kHz)
        pre_48k = state.dsp.process_pre_resample_48k(validated.samples)
        state.accounting.record_dsp_processed(int(pre_48k.size))

        # Stage 2: stateful output resampler (48k -> 16k or 8k)
        resampled = state.resampler.process_chunk(pre_48k)
        state.accounting.record_resample_step(int(pre_48k.size), int(resampled.size), is_eos_flush=False)

        # Stage 3: post-resample limiter (when DSP enabled)
        limited, limiter_clipped = state.dsp.process_post_resample_limiter(resampled)

        # Stage 4: PCM16 quantization
        qres = quantize_float32_to_pcm16le(limited, policy=self.profile.quantization_policy)
        state.accounting.record_quantized(
            qres.sample_count,
            limiter_saturated=limiter_clipped,
            quantizer_saturated=qres.saturated_count,
        )

        # Stage 5: exact 20 ms frame assembly + bounded post-pause silence streaming
        emitted_frames: list[RenderedFrame] = []
        if qres.pcm_bytes:
            emitted_frames.extend(state.framer.push_pcm(qres.pcm_bytes))
        if pause_out_samples > 0:
            state.accounting.record_planned_silence(pause_out_samples)
            for silence_slice in iter_bounded_pcm_silence(
                pause_out_samples,
                slice_samples=self.profile.samples_per_frame * 8,
            ):
                emitted_frames.extend(state.framer.push_pcm(silence_slice))

        # Re-check M02 cancellation after render/resample before admitting frames into queue
        if self.session_ctx.root_scope.is_cancel_requested or gen_scope.is_cancel_requested:
            state.abort_generation(reason="cancelled_during_render")
            state.accounting.record_raw_discarded(chunk.sample_count)
            for frame in emitted_frames:
                state.accounting.record_unenqueued_frame_discarded(frame.valid_sample_count)
            return RenderChunkResult(
                admitted=False,
                frames=(),
                queue_statuses=(),
                control_records=tuple(ctrl_records),
                rejection_reason="CANCELLED_DURING_RENDER",
            )

        statuses: list[AdmissionStatus] = []
        admitted_frames: list[RenderedFrame] = []
        for frame in emitted_frames:
            st = await fence.enqueue_frame(frame, plan_revision=chunk.plan_revision)
            statuses.append(st)
            if st == AdmissionStatus.ACCEPTED:
                admitted_frames.append(frame)
                ev = self.events.emit_server_event(
                    generation_ref=chunk.generation_ref,
                    kind=PlaybackEventKind.QUEUED,
                    queue_depth=self.session_ctx.queue.item_count,
                    sample_progress=frame.sample_offset,
                )
                if ev is not None:
                    self.telemetry.publish_playback_event(ev)
            else:
                state.accounting.record_unenqueued_frame_discarded(frame.valid_sample_count)

        wall_ns = max(0, self.clock.monotonic_ns() - t0_ns)
        self.telemetry.record_render_chunk(
            generation_ref=chunk.generation_ref,
            profile=self.profile.profile,
            wall_ns=wall_ns,
            rms_dbfs=qres.rms_dbfs,
            rejected_stale=False,
        )

        return RenderChunkResult(
            admitted=all(s == AdmissionStatus.ACCEPTED for s in statuses) if statuses else True,
            frames=tuple(admitted_frames),
            queue_statuses=tuple(statuses),
            control_records=tuple(ctrl_records),
            rejection_reason=None if all(s == AdmissionStatus.ACCEPTED for s in statuses) else statuses[-1].value,
        )

    async def finish_generation_eos(self, *, plan_revision: int = 0) -> tuple[RenderedFrame, ...]:
        """Flush resampler tail and terminal frame once on authorized normal EOS."""
        state = self.stream_state
        state.assert_writer(self.writer_id)
        if state.aborted or state.eos_completed:
            return ()

        gen_scope = self.session_ctx.tg.generation_scope
        if self.session_ctx.root_scope.is_cancel_requested or gen_scope is None or gen_scope.is_cancel_requested:
            state.abort_generation(reason="eos_blocked_by_cancel")
            return ()

        tail = state.resampler.flush_eos()
        state.accounting.record_resample_step(0, int(tail.size), is_eos_flush=True)

        if tail.size > 0:
            limited, limiter_clipped = state.dsp.process_post_resample_limiter(tail)
            qres = quantize_float32_to_pcm16le(limited, policy=self.profile.quantization_policy)
            state.accounting.record_quantized(
                qres.sample_count,
                limiter_saturated=limiter_clipped,
                quantizer_saturated=qres.saturated_count,
            )
            emitted = state.framer.push_pcm(qres.pcm_bytes)
        else:
            emitted = []

        emitted.extend(state.framer.flush_eos())
        state.eos_completed = True

        admitted: list[RenderedFrame] = []
        fence = self.fence
        for frame in emitted:
            st = await fence.enqueue_frame(frame, plan_revision=plan_revision)
            if st == AdmissionStatus.ACCEPTED:
                admitted.append(frame)
                ev = self.events.emit_server_event(
                    generation_ref=state.active_generation_ref,
                    kind=PlaybackEventKind.QUEUED,
                    queue_depth=self.session_ctx.queue.item_count,
                    sample_progress=frame.sample_offset,
                )
                if ev is not None:
                    self.telemetry.publish_playback_event(ev)
            else:
                state.accounting.record_unenqueued_frame_discarded(frame.valid_sample_count)
        return tuple(admitted)

    async def pump_and_submit(
        self,
        *,
        submit_fn: Callable[[RenderedFrame], Any],
        before_linearize_hook: Callable[[RenderedFrame], Awaitable[None]] | None = None,
        max_frames: int | None = None,
    ) -> list[SubmissionRecord]:
        """Submit queued frames through the monotonic pacer and M02 atomic fence."""
        state = self.stream_state
        fence = self.fence
        gref = state.active_generation_ref
        records: list[SubmissionRecord] = []
        use_pacer = self.profile.pace_owner == PaceOwner.SERVER

        while max_frames is None or len(records) < max_frames:
            rec = await fence.submit_next(
                expected_gen=gref,
                stream_ref=self.binding.stream_ref,
                submit_fn=submit_fn,
                use_pacer=use_pacer,
                before_linearize_hook=before_linearize_hook,
            )
            if rec is None:
                break
            records.append(rec)

            if rec.outcome in (SubmissionOutcome.SUBMITTED_SERVER, SubmissionOutcome.IN_FLIGHT_POSSIBLE):
                gkey = (gref.turn_id, gref.generation_id)
                if gkey not in self._started_generations:
                    self._started_generations.add(gkey)
                    ev_start = self.events.emit_server_event(
                        generation_ref=gref,
                        kind=PlaybackEventKind.PLAYBACK_STARTED,
                        sample_progress=rec.sequence * self.profile.samples_per_frame,
                        observation_scope=rec.observation_scope,
                        metadata={"completion_stage": "SERVER_LOCAL_SUBMIT_STARTED"},
                    )
                    if ev_start is not None:
                        self.telemetry.publish_playback_event(ev_start)
                last_pacing = self.pacer._records[-1] if self.pacer._records else None
                self.telemetry.record_frame_submitted(
                    generation_ref=gref,
                    profile=self.profile.profile,
                    sequence=rec.sequence,
                    outcome=rec.outcome.value,
                    observation_scope=rec.observation_scope.value,
                    signed_error_ns=last_pacing.signed_error_ns if last_pacing else 0,
                    abs_error_ns=last_pacing.abs_error_ns if last_pacing else 0,
                    inter_submit_gap_ns=last_pacing.inter_submit_gap_ns if last_pacing else None,
                    reanchored=last_pacing.reanchored if last_pacing else False,
                    underrun=last_pacing.underrun if last_pacing else False,
                )
            elif rec.outcome in (
                SubmissionOutcome.BLOCKED_PAUSED,
                SubmissionOutcome.BLOCKED_CANCELED,
                SubmissionOutcome.BLOCKED_CLOSED,
                SubmissionOutcome.BLOCKED_STALE_GENERATION,
                SubmissionOutcome.BACKPRESSURE,
                SubmissionOutcome.FAILED_TRANSPORT,
                SubmissionOutcome.ABORTED_STALE_SCHEDULE,
            ):
                break

        # Emit truthful SERVER DRAINED / COMPLETED when EOS has flushed and queue is empty
        if state.eos_completed and not state.aborted and self.session_ctx.queue.item_count == 0:
            if not records or records[-1].outcome in (
                SubmissionOutcome.SUBMITTED_SERVER,
                SubmissionOutcome.IN_FLIGHT_POSSIBLE,
            ):
                snap = state.accounting.snapshot()
                ev_drained = self.events.emit_server_event(
                    generation_ref=gref,
                    kind=PlaybackEventKind.DRAINED,
                    queue_depth=0,
                    sample_progress=snap.submitted_samples,
                    observation_scope=ObservationScope.SERVER,
                    metadata={"completion_stage": "SERVER_QUEUE_DRAINED"},
                )
                ev_done = self.events.emit_server_event(
                    generation_ref=gref,
                    kind=PlaybackEventKind.COMPLETED,
                    queue_depth=0,
                    sample_progress=snap.submitted_samples,
                    observation_scope=ObservationScope.SERVER,
                    metadata={"completion_stage": "SERVER_SUBMISSION_COMPLETE"},
                )
                for ev in (ev_drained, ev_done):
                    if ev is not None:
                        self.telemetry.publish_playback_event(ev)

        return records

    async def soft_pause(self) -> PauseRef | None:
        pref = await self.lifecycle.soft_pause(generation_ref=self.stream_state.active_generation_ref)
        if pref is not None:
            self.playback_queue.set_paused(True)
        return pref

    async def resume_pause(self, pause_ref: PauseRef) -> bool:
        ok = await self.lifecycle.resume_pause(pause_ref, generation_ref=self.stream_state.active_generation_ref)
        if ok:
            self.playback_queue.set_paused(False)
            self.pacer.reset_segment()
        return ok

    async def commit_interrupt(self, *, reason: str = "barge_in_commit", flush_command_sent: bool = False) -> bool:
        gref = (
            self._stream_state.active_generation_ref
            if self._stream_state is not None
            else self.session_ctx.tg.active_generation
        )
        if gref is None:
            return False
        changed = await self.lifecycle.commit_interrupt(
            stream_state=self._stream_state,
            generation_ref=gref,
            reason=reason,
            flush_command_sent=flush_command_sent,
        )
        if self._fence is not None:
            self._fence.purge_generation(gref)
        self.wsola.abort_discard()
        self._prev_chunk_tail_48k = None
        return changed

    async def commit_interrupt_with_receipt(
        self,
        *,
        reason: str = "barge_in_commit",
        remote_scope: ObservationScope = ObservationScope.PBX,
        remote_supported: bool = False,
        remote_command_sent: bool = False,
    ) -> FlushReceipt:
        gref = (
            self._stream_state.active_generation_ref
            if self._stream_state is not None
            else self.session_ctx.tg.active_generation
        )
        if gref is None:
            raise RuntimeError("No active generation to interrupt")
        self._flush_seq += 1
        intent = FlushIntent(
            command_id=f"flush-{self.session_ctx.identity.session_id}-{gref.turn_id}-{gref.generation_id}-{self._flush_seq}",
            session_id=self.session_ctx.identity.session_id,
            incarnation_id=self.session_ctx.incarnation_id,
            generation_ref=gref,
            plan_revision=self._active_plan.plan_revision if self._active_plan else 0,
            stream_ref=self.binding.stream_ref,
            reason=reason,
            created_ns=self.clock.monotonic_ns(),
            clock_domain=self.clock.clock_domain,
        )
        await self.commit_interrupt(reason=reason, flush_command_sent=remote_command_sent)
        return await self.playback_queue.purge_unsent_generation(
            intent,
            remote_scope=remote_scope,
            remote_supported=remote_supported,
            remote_command_sent=remote_command_sent,
        )

    async def close(self, *, reason: str = "normal_close", drain_timeout_sec: float = 0.5) -> CloseSummary:
        await self.playback_queue.close()
        self.reference_tap.clear_session()
        return await self.lifecycle.close(reason=reason, drain_timeout_sec=drain_timeout_sec)

    def accounting_snapshot(self) -> SampleAccountingSnapshot:
        return self.stream_state.accounting.snapshot()
