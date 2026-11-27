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

import threading
from dataclasses import dataclass
from typing import Any

from backend.core.contracts.audio import AudioFrame
from backend.core.contracts.common import StreamRef, TurnRef
from backend.core.contracts.speech import SpeechEvent, SpeechEventKind
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.core.runtime.resource_ledger import ResourceLedger
from backend.core.runtime.session_context import SessionContext
from backend.observability.event_bus import BoundedEventBus
from backend.observability.event_catalog import EventPriority
from backend.voice_activity.config_adapter import F1ConfigAdapter, F1ProfileConfig, F1RouteMode
from backend.voice_activity.deadlines import F1DeadlineMonitor, WatchdogStatus
from backend.voice_activity.endpointing import EndpointCutDecision, EndpointingPolicy
from backend.voice_activity.frame_synchronizer import FrameAdmissionResult, FrameSynchronizer, VADWindow
from backend.voice_activity.lifecycle import F1StreamLifecycle
from backend.voice_activity.lookback_buffer import LookbackBuffer, LookbackCapacityExceededError
from backend.voice_activity.sample_accounting import SampleAccountingLedger
from backend.voice_activity.semantic_endpoint_policy import SemanticEndpointPolicy
from backend.voice_activity.speech_state_machine import AcousticState, SpeechStateMachine, TransitionKind
from backend.voice_activity.telemetry import F1Telemetry
from backend.voice_activity.utterance_manager import (
    BoundedUtteranceQueue,
    FinalizationReceipt,
    M02TurnAllocatorBridge,
    TurnAllocatorProtocol,
    UtteranceConsumerProtocol,
    UtteranceManager,
)
from backend.voice_activity.vad_engine import VADEngineAdapter, VADObservation
from backend.voice_activity.vad_state import VADStateManager


class _ShadowNoOpTurnAllocator:
    """Shadow mode must never allocate real M02 turns."""

    def is_stream_active(self) -> bool:
        return True

    def allocate_turn(self) -> TurnRef:
        raise RuntimeError("Shadow mode cannot allocate M02 turns")


class _ShadowSilentConsumer:
    """Bounded sink for shadow observations; never dispatches to ASR/F2."""

    def __init__(self, *, max_items: int = 4) -> None:
        self.queue = BoundedUtteranceQueue(max_items=max_items, max_bytes=1_280_000 * max_items)

    def can_accept(self, payload_bytes: int) -> bool:
        return self.queue.can_accept(payload_bytes)

    def accept_utterance(self, utterance: Any) -> None:
        self.queue.accept_utterance(utterance)


@dataclass(frozen=True, slots=True)
class ProcessFrameOutcome:
    admission: FrameAdmissionResult
    observations: tuple[VADObservation, ...]
    speech_events: tuple[SpeechEvent, ...]
    finalizations: tuple[FinalizationReceipt, ...]
    discontinuity_reset: bool = False


class StreamAcousticProcessor:
    """
    Single authoritative F1-A acoustic segmentation pipeline for one input stream.

    Integrates FrameSynchronizer, LookbackBuffer, VADStateManager, SpeechStateMachine,
    EndpointingPolicy, UtteranceManager, F1DeadlineMonitor, and F1Telemetry under
    strict per-stream lock serialization.
    """

    def __init__(
        self,
        stream_ref: StreamRef,
        *,
        profile: F1ProfileConfig,
        config_revision: str,
        vad_engine: VADEngineAdapter,
        turn_allocator: TurnAllocatorProtocol,
        consumer: UtteranceConsumerProtocol | None = None,
        clock: Clock | None = None,
        ledger: ResourceLedger | None = None,
        event_bus: BoundedEventBus | None = None,
        session_context: SessionContext | None = None,
        trace_id: str | None = None,
        strict_pinned_capacity: bool = False,
        f1c_policy: SemanticEndpointPolicy | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.profile = profile
        self.config_revision = config_revision
        self.stream_ref = stream_ref
        self.clock: Clock = clock or vad_engine.clock or SystemMonotonicClock()
        self.accounting = SampleAccountingLedger()
        self.synchronizer = FrameSynchronizer(
            stream_ref,
            config_revision=config_revision,
            max_pending_input_samples=profile.max_pending_input_samples,
            max_pending_bytes=profile.max_pending_bytes,
            allow_eos_model_padding=profile.allow_eos_model_padding,
            accounting=self.accounting,
        )
        self.vad_state = VADStateManager(stream_ref, vad_engine, ledger=ledger)
        self.lookback = LookbackBuffer(
            pre_roll_samples=profile.pre_roll_samples,
            history_capacity_samples=profile.history_capacity_samples,
            max_utterance_samples=profile.max_utterance_samples,
            overlap_consecutive_utterances=profile.overlap_consecutive_utterances,
            strict_pinned_capacity=strict_pinned_capacity,
        )
        self.fsm = SpeechStateMachine(profile)
        self.endpointing = EndpointingPolicy(profile)
        self.utterance_manager = UtteranceManager(
            stream_ref,
            turn_allocator=turn_allocator,
            consumer=consumer,
        )
        self.deadlines = F1DeadlineMonitor(
            clock=self.clock,
            idle_watchdog_ms=profile.idle_watchdog_ms,
            input_stall_watchdog_ms=profile.input_stall_watchdog_ms,
        )
        self.telemetry = F1Telemetry(stream_ref, trace_id=trace_id, clock=self.clock, bus=event_bus)
        self.lifecycle = F1StreamLifecycle(session_context=session_context)
        self.f1c_policy = f1c_policy
        self._has_active_discontinuity = False

    def process_frame(self, frame: AudioFrame) -> ProcessFrameOutcome:
        """Process one M01 AudioFrame through synchronizer, isolated VAD, FSM, and endpointing."""
        with self._lock:
            if not self.lifecycle.is_input_active:
                rejected = FrameAdmissionResult(
                    accepted=False,
                    rejection_reason=None,
                    windows=(),
                    error_detail="input_stream_inactive_or_closed",
                )
                return ProcessFrameOutcome(rejected, (), (), ())

            self.deadlines.record_ingress()
            admission = self.synchronizer.admit_frame(frame)
            if not admission.accepted:
                self.telemetry.emit_event(
                    "f1.utterance.rejected",
                    extras={
                        "reason": admission.rejection_reason.value if admission.rejection_reason else "rejected",
                        "error_code": admission.error_detail,
                    },
                    priority=EventPriority.HIGH,
                )
                return ProcessFrameOutcome(admission, (), (), ())

            discontinuity = False
            if admission.discontinuity_gap_samples > 0 or self.synchronizer.stream_ref.format_epoch != self.stream_ref.format_epoch:
                discontinuity = True
                self.stream_ref = self.synchronizer.stream_ref
                self._handle_discontinuity_locked(
                    new_epoch_start=frame.sample_offset,
                    gap_samples=admission.discontinuity_gap_samples,
                )

            observations: list[VADObservation] = []
            speech_events: list[SpeechEvent] = []
            finalizations: list[FinalizationReceipt] = []

            for win in admission.windows:
                self.telemetry.emit_event(
                    "f1.window.accepted",
                    extras={
                        "window_index": win.window_index,
                        "sample_offset": win.start_sample,
                        "valid_samples": win.valid_samples,
                        "config_revision": self.config_revision,
                    },
                    priority=EventPriority.LOW,
                )
                obs, evs, fins = self._process_window_locked(win, eos_requested=False)
                observations.append(obs)
                speech_events.extend(evs)
                finalizations.extend(fins)

            self.accounting.set_retained_history(self.lookback.total_samples)
            return ProcessFrameOutcome(
                admission=admission,
                observations=tuple(observations),
                speech_events=tuple(speech_events),
                finalizations=tuple(finalizations),
                discontinuity_reset=discontinuity,
            )

    def _handle_discontinuity_locked(self, *, new_epoch_start: int, gap_samples: int) -> None:
        if self.fsm.state in (AcousticState.SPEECH_CANDIDATE, AcousticState.SPEECH_ACTIVE, AcousticState.SILENCE_PENDING):
            if self.fsm.utterance_start_sample is not None:
                discarded = max(0, self.fsm.last_real_sample - self.fsm.utterance_start_sample)
                self.accounting.record_abort_discarded(discarded)
        self.fsm.reset()
        self.lookback.reset_for_gap(new_epoch_start)
        self.vad_state.reset_for_gap_or_epoch(self.stream_ref)
        self.utterance_manager.update_epoch(self.stream_ref)
        self.telemetry.update_stream_ref(self.stream_ref)
        if self.f1c_policy is not None:
            self.f1c_policy.update_stream_ref(self.stream_ref)
        self._has_active_discontinuity = True
        self.telemetry.emit_event(
            "f1.discontinuity",
            extras={"gap_samples": gap_samples, "sample_offset": new_epoch_start, "reason": "gap_or_epoch_change"},
            priority=EventPriority.CRITICAL,
        )

    def _process_window_locked(
        self,
        win: VADWindow,
        *,
        eos_requested: bool,
    ) -> tuple[VADObservation, list[SpeechEvent], list[FinalizationReceipt]]:
        events: list[SpeechEvent] = []
        finals: list[FinalizationReceipt] = []

        try:
            self.lookback.append_samples(win.start_sample, win.samples_f32)
        except LookbackCapacityExceededError:
            self.telemetry.emit_event(
                "f1.buffer.overflow",
                extras={"sample_offset": win.start_sample, "reason": "lookback_capacity_exceeded"},
                priority=EventPriority.CRITICAL,
            )
            raise

        obs = self.vad_state.evaluate_window(win)
        self.telemetry.record_vad_inference_duration(
            start_ns=obs.inference_start_ns,
            start_domain=obs.clock_domain,
            end_ns=obs.inference_end_ns,
            end_domain=obs.clock_domain,
        )
        self.telemetry.emit_event(
            "f1.vad.observed",
            extras={
                "window_index": win.window_index,
                "sample_offset": win.start_sample,
                "model_revision": obs.model_revision,
                "status": "ok" if obs.ok else "error",
                "error_code": obs.error_code or "",
            },
            priority=EventPriority.LOW,
        )

        if obs.ok and obs.score is not None and obs.score >= self.profile.start_threshold:
            self.deadlines.record_voice_activity()

        tr = self.fsm.step(obs)
        if tr.kind == TransitionKind.CANDIDATE_PINNED:
            assert tr.candidate_onset_sample is not None
            pin = self.lookback.pin_candidate(tr.candidate_onset_sample)
            self.fsm.attach_pinned_start(pin.utterance_start_sample, pin.actual_pre_roll_samples)
            events.append(
                self.telemetry.emit_speech_event(
                    SpeechEventKind.SPEECH_CANDIDATE,
                    sample_offset=pin.utterance_start_sample,
                    reason=tr.reason,
                    vad_score=tr.vad_score,
                    extras={"actual_pre_roll_samples": pin.actual_pre_roll_samples},
                )
            )
        elif tr.kind == TransitionKind.SPEECH_STARTED:
            if self.fsm.utterance_start_sample is None:
                assert tr.candidate_onset_sample is not None
                pin = self.lookback.pin_candidate(tr.candidate_onset_sample)
                self.fsm.attach_pinned_start(pin.utterance_start_sample, pin.actual_pre_roll_samples)
            events.append(
                self.telemetry.emit_speech_event(
                    SpeechEventKind.SPEECH_START,
                    sample_offset=self.fsm.utterance_start_sample or tr.sample_offset,
                    reason=tr.reason,
                    vad_score=tr.vad_score,
                    extras={"actual_pre_roll_samples": self.fsm.actual_pre_roll_samples},
                )
            )
        elif tr.kind == TransitionKind.CANDIDATE_REJECTED:
            if self.fsm.utterance_start_sample is not None:
                self.accounting.record_candidate_discarded(
                    max(0, obs.end_sample_exclusive - self.fsm.utterance_start_sample)
                )
            self.lookback.release_candidate_pin()
        elif tr.kind == TransitionKind.SILENCE_CANCELED:
            if self.f1c_policy is not None:
                self.f1c_policy.reset_episode()

        effective_silence_samples = self._effective_silence_samples_locked()
        cut = self.endpointing.evaluate(
            self.fsm,
            eos_requested=eos_requested,
            effective_silence_samples=effective_silence_samples,
        )
        if cut.should_finalize:
            if self.f1c_policy is not None:
                self.f1c_policy.reset_episode()
            rec = self._finalize_cut_locked(cut, events)
            finals.append(rec)
            # If a MAX_DURATION cut happened mid-window while speech continues in remaining samples,
            # subsequent windows remain eligible from cut.end_sample_exclusive without overlap.
            if (
                cut.end_sample_exclusive < win.end_sample_exclusive
                and obs.ok
                and obs.score is not None
                and obs.score >= self.profile.start_threshold
            ):
                # Re-seed candidate on leftover slice within same window if needed.
                leftover_start = cut.end_sample_exclusive
                pin = self.lookback.pin_candidate(leftover_start)
                self.fsm.attach_pinned_start(pin.utterance_start_sample, pin.actual_pre_roll_samples)
                # Enter candidate cleanly for next windows.
                self.fsm._state = AcousticState.SPEECH_CANDIDATE
                self.fsm._candidate_onset_sample = leftover_start
                self.fsm._consecutive_high_windows = 1

        return obs, events, finals

    def _effective_silence_samples_locked(self) -> int | None:
        if (
            self.f1c_policy is not None
            and self.fsm.state == AcousticState.SILENCE_PENDING
            and self.fsm.low_run_start_sample is not None
        ):
            advice = self.f1c_policy.evaluate_silence_pending(
                low_run_start_sample=self.fsm.low_run_start_sample,
                low_run_real_samples=self.fsm.low_run_real_samples,
                last_real_sample=self.fsm.last_real_sample,
            )
            return advice.effective_silence_samples
        return None

    def _finalize_cut_locked(
        self,
        cut: EndpointCutDecision,
        events: list[SpeechEvent],
    ) -> FinalizationReceipt:
        self.fsm.mark_finalizing()
        payload = self.lookback.extract_slice(cut.start_sample, cut.end_sample_exclusive)
        rec = self.utterance_manager.finalize_and_handoff(
            cut,
            payload=payload,
            has_discontinuity=self._has_active_discontinuity,
        )
        self._has_active_discontinuity = False
        if rec.status.value == "ADMITTED":
            self.accounting.record_transferred_utterance(
                total_samples=cut.end_sample_exclusive - cut.start_sample,
                pre_roll_samples=cut.actual_pre_roll_samples,
                post_roll_samples=cut.actual_post_roll_samples,
            )
        events.append(
            self.telemetry.emit_speech_event(
                SpeechEventKind.SPEECH_END,
                sample_offset=cut.speech_end_estimate_sample or cut.end_sample_exclusive,
                reason=cut.reason.value if cut.reason else "FINALIZED",
                turn_ref=rec.turn_ref,
            )
        )
        events.append(
            self.telemetry.emit_speech_event(
                SpeechEventKind.UTTERANCE_FINALIZED,
                sample_offset=cut.end_sample_exclusive,
                reason=cut.reason.value if cut.reason else "FINALIZED",
                turn_ref=rec.turn_ref,
                extras={
                    "utterance_id": rec.utterance_id,
                    "actual_pre_roll_samples": cut.actual_pre_roll_samples,
                    "actual_post_roll_samples": cut.actual_post_roll_samples,
                    "status": rec.status.value,
                },
            )
        )
        self.lookback.commit_finalized(cut.end_sample_exclusive)
        self.fsm.reset()
        return rec

    def flush_eos(self) -> tuple[tuple[SpeechEvent, ...], tuple[FinalizationReceipt, ...]]:
        """Handle explicit graceful EOS idempotently."""
        with self._lock:
            if not self.lifecycle.is_input_active or self.synchronizer.eos_flushed:
                return (), ()
            tail_win, _ = self.synchronizer.flush_eos()
            events: list[SpeechEvent] = []
            finals: list[FinalizationReceipt] = []
            if tail_win is not None:
                _, evs, fins = self._process_window_locked(tail_win, eos_requested=True)
                events.extend(evs)
                finals.extend(fins)
            if not finals:
                cut = self.endpointing.evaluate(
                    self.fsm,
                    eos_requested=True,
                    effective_silence_samples=self._effective_silence_samples_locked(),
                )
                if cut.should_finalize:
                    if self.f1c_policy is not None:
                        self.f1c_policy.reset_episode()
                    finals.append(self._finalize_cut_locked(cut, events))
                elif self.fsm.state == AcousticState.SPEECH_CANDIDATE:
                    if self.fsm.utterance_start_sample is not None:
                        self.accounting.record_candidate_discarded(
                            max(0, self.fsm.last_real_sample - self.fsm.utterance_start_sample)
                        )
                    self.lookback.release_candidate_pin()
                    self.fsm.reset()
            self.accounting.set_retained_history(self.lookback.total_samples)
            return tuple(events), tuple(finals)

    def notify_output_cancelled(self) -> None:
        """Output generation cancellation leaves active input VAD state intact."""
        self.lifecycle.notify_output_generation_cancelled()

    def check_watchdogs(self) -> WatchdogStatus:
        with self._lock:
            speech_active = self.fsm.state in (AcousticState.SPEECH_ACTIVE, AcousticState.SILENCE_PENDING)
            return self.deadlines.evaluate(speech_active=speech_active)

    def revoke_and_close(self, reason: str = "normal_close") -> None:
        """Idempotently revoke input, discard incomplete candidate/utterance, and release resources."""
        with self._lock:
            if not self.lifecycle.close(reason):
                return
            if self.fsm.state in (AcousticState.SPEECH_CANDIDATE, AcousticState.SPEECH_ACTIVE, AcousticState.SILENCE_PENDING):
                if self.fsm.utterance_start_sample is not None:
                    self.accounting.record_abort_discarded(
                        max(0, self.fsm.last_real_sample - self.fsm.utterance_start_sample)
                    )
            self.fsm.reset()
            self.synchronizer.close()
            self.lookback.clear()
            self.utterance_manager.revoke_input()
            self.utterance_manager.close()
            self.vad_state.revoke_and_close()
            self.accounting.set_retained_history(0)


class VoiceActivityPipeline:
    """
    Top-level F1-A route coordinator enforcing OFF / STRICT / SHADOW isolation.
    Guarantees at most one active authoritative segmentation output per stream.
    """

    def __init__(
        self,
        stream_ref: StreamRef,
        *,
        config_adapter: F1ConfigAdapter,
        vad_engine: VADEngineAdapter,
        turn_allocator: TurnAllocatorProtocol | None = None,
        consumer: UtteranceConsumerProtocol | None = None,
        clock: Clock | None = None,
        ledger: ResourceLedger | None = None,
        event_bus: BoundedEventBus | None = None,
        session_context: SessionContext | None = None,
        trace_id: str | None = None,
        strict_pinned_capacity: bool = False,
        f1c_policy: SemanticEndpointPolicy | None = None,
    ) -> None:
        self.profile, self.config_revision = config_adapter.pin_for_stream()
        self.route_mode = self.profile.route_mode
        self.stream_ref = stream_ref
        self.strict_processor: StreamAcousticProcessor | None = None
        self.shadow_processor: StreamAcousticProcessor | None = None

        if self.route_mode == F1RouteMode.STRICT:
            if turn_allocator is None:
                if session_context is None:
                    raise ValueError("STRICT mode requires turn_allocator or session_context")
                turn_allocator = M02TurnAllocatorBridge(session_context)
            self.strict_processor = StreamAcousticProcessor(
                stream_ref,
                profile=self.profile,
                config_revision=self.config_revision,
                vad_engine=vad_engine,
                turn_allocator=turn_allocator,
                consumer=consumer,
                clock=clock,
                ledger=ledger,
                event_bus=event_bus,
                session_context=session_context,
                trace_id=trace_id,
                strict_pinned_capacity=strict_pinned_capacity,
            )
        elif self.route_mode == F1RouteMode.SHADOW:
            self.shadow_processor = StreamAcousticProcessor(
                stream_ref,
                profile=self.profile,
                config_revision=self.config_revision,
                vad_engine=vad_engine,
                turn_allocator=_ShadowNoOpTurnAllocator(),
                consumer=_ShadowSilentConsumer(max_items=4),
                clock=clock,
                ledger=ledger,
                event_bus=event_bus,
                session_context=None,
                trace_id=trace_id,
                strict_pinned_capacity=strict_pinned_capacity,
            )

    def process_frame(self, frame: AudioFrame) -> ProcessFrameOutcome | None:
        if self.route_mode == F1RouteMode.OFF:
            return None
        if self.route_mode == F1RouteMode.STRICT and self.strict_processor is not None:
            return self.strict_processor.process_frame(frame)
        if self.route_mode == F1RouteMode.SHADOW and self.shadow_processor is not None:
            # Shadow runs on immutable frame copy; never dispatches or allocates turns.
            try:
                self.shadow_processor.process_frame(frame)
            except Exception:
                pass
            return None
        return None

    def close(self, reason: str = "normal_close") -> None:
        if self.strict_processor is not None:
            self.strict_processor.revoke_and_close(reason)
        if self.shadow_processor is not None:
            self.shadow_processor.revoke_and_close(reason)
