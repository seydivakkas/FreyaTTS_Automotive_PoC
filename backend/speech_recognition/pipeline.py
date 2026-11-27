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

import inspect
from dataclasses import dataclass, replace
from typing import Awaitable, Callable, Sequence

from backend.core.contracts.audio import AudioFormat, AudioFrame
from backend.core.contracts.common import ErrorCategory, MetricSample, Retryability
from backend.core.contracts.recognition import ASROutcome, ASRResult
from backend.core.contracts.speech import SpeechEvent, Utterance
from backend.core.runtime.deadlines import Clock, DeadlineBudget
from backend.core.runtime.result_admission import AdmissionStatus
from backend.core.runtime.session_context import SessionContext
from backend.runtime_resources.contracts import AdmissionOutcome
from backend.shared_lexicon.registry import LexiconRegistry
from backend.speech_recognition.admission import (
    ASRConsumer,
    ASRResultDelivery,
    ASRUtteranceAdmission,
    ClaimDecision,
    ClaimStatus,
)
from backend.speech_recognition.confidence_metadata import (
    extract_confidence_estimate,
    resolve_language_metadata,
)
from backend.speech_recognition.config_adapter import PinnedASRConfig
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
    EntityResolutionReport,
    resolve_automotive_entities,
)
from backend.speech_recognition.errors import (
    ASRConfigError,
    ASRDeliveryStatus,
    ASRDispatchStatus,
    ASRInputError,
    build_safe_error_info,
)
from backend.speech_recognition.hotword_planner import ContextHintSnapshot, HotwordPlan, HotwordPlanner
from backend.speech_recognition.input_manager import (
    ValidatedUtteranceInput,
    validate_and_materialize_utterance,
)
from backend.speech_recognition.legacy_adapter import LegacyASRProjection, project_legacy_transcript
from backend.speech_recognition.lexicon_adapter import (
    LegacyHotwordCache,
    PinnedLexiconSnapshot,
    extract_conservative_candidates,
    pin_lexicon_snapshot,
)
from backend.speech_recognition.lifecycle import ASRLifecycleManager
from backend.speech_recognition.request_builder import build_asr_resource_request
from backend.speech_recognition.result_builder import build_final_asr_result
from backend.speech_recognition.telemetry import ASRTelemetryBridge
from backend.speech_recognition.whisper_engine import WhisperExecutionResult, WhisperSchedulerEngine


@dataclass(frozen=True, slots=True)
class ASRProcessingRecord:
    """Complete F2-A/F2-B execution record separating recognition outcome from delivery status."""

    result: ASRResult | None
    dispatch_status: ASRDispatchStatus
    delivery: ASRResultDelivery
    claim_decision: ClaimDecision | None
    legacy_projection: LegacyASRProjection
    execution_result: WhisperExecutionResult | None = None
    lexicon_unavailable_reason: str | None = None
    hotword_plan: HotwordPlan | None = None
    entity_resolution: EntityResolutionReport | None = None
    clarification_hint: ClarificationHint | None = None
    attempt_arbitration: AttemptArbitrationResult | None = None


class SpeechRecognitionPipeline:
    """
    Canonical F2-A final-only ASR pipeline.

    Coordinates:
    - M01 Utterance validation & immutable float32 buffer materialization
    - M02-scoped deduplication claim & atomic result delivery fence
    - Pinned M03 config & M05 lexicon snapshot capture at admission
    - M06 P1 CTranslate2/Whisper scheduler execution
    - Bounded lazy segment materialization, literal raw transcript & conservative M05 candidates
    - Isolated M04 telemetry & lifecycle tracking
    """

    def __init__(
        self,
        *,
        engine: WhisperSchedulerEngine,
        admission: ASRUtteranceAdmission,
        consumer: ASRConsumer,
        telemetry: ASRTelemetryBridge | None = None,
        lifecycle: ASRLifecycleManager | None = None,
        hotword_cache: LegacyHotwordCache | None = None,
    ) -> None:
        self.engine = engine
        self.admission = admission
        self.consumer = consumer
        self.telemetry = telemetry or ASRTelemetryBridge()
        self.lifecycle = lifecycle or ASRLifecycleManager()
        self.hotword_cache = hotword_cache or LegacyHotwordCache(clock=engine.scheduler.clock)
        self._event_seq = 0
        self._job_seq = 0

    def _next_seq(self) -> int:
        seq = self._event_seq
        self._event_seq += 1
        return seq

    def _next_job_id(self, utterance_id: str) -> str:
        self._job_seq += 1
        safe_utt = utterance_id[:80]
        return f"asr-job-{self._job_seq}:{safe_utt}"

    @property
    def clock(self) -> Clock:
        return self.engine.scheduler.clock

    async def process_utterance(
        self,
        utterance: Utterance | SpeechEvent,
        audio_format: AudioFormat,
        *,
        session_ctx: SessionContext,
        pinned_config: PinnedASRConfig,
        lexicon_registry: LexiconRegistry | None = None,
        frames: Sequence[AudioFrame] | None = None,
        expected_stream_epoch: int | None = None,
        catalog_hotword_provider: Callable[[int], Sequence[str]] | None = None,
        custom_hotwords: Sequence[str] = (),
        word_timestamps: bool = False,
        before_enqueue_hook: Callable[[ASRResult], Awaitable[None] | None] | None = None,
        context_hint: ContextHintSnapshot | None = None,
        enable_f2b: bool = False,
        beam_profile: DecodeBeamProfile = DecodeBeamProfile.BASELINE_COMPAT,
        alternate_enabled: bool = False,
        projection_policy: str = "candidate_only",
        min_revision: int = 0,
    ) -> ASRProcessingRecord:
        admitted_ns = self.clock.monotonic_ns()
        admitted_domain = self.clock.clock_domain
        session_id = session_ctx.identity.session_id
        turn_id = session_ctx.tg.active_turn.turn_id if session_ctx.tg.active_turn else None
        utt_id = getattr(utterance, "utterance_id", "invalid-utterance")

        self.telemetry.emit_event(
            event_type="asr.requested",
            session_id=session_id,
            turn_id=turn_id,
            sequence=self._next_seq(),
            monotonic_ns=admitted_ns,
            clock_domain=admitted_domain,
            trace_id=session_ctx.identity.trace_id,
            metadata={"utterance_id": utt_id, "route_mode": pinned_config.route_mode.value},
        )

        # 1. Validate & materialize M01 Utterance
        try:
            validated: ValidatedUtteranceInput = validate_and_materialize_utterance(
                utterance,
                audio_format,
                frames=frames,
                max_samples=pinned_config.max_input_samples,
                allow_discontinuity=pinned_config.allow_discontinuity,
            )
        except ASRInputError as exc:
            err_info = exc.to_error_info()
            res = build_final_asr_result(
                session_id=session_id,
                utterance_id=utt_id if isinstance(utt_id, str) and utt_id else "invalid-utterance",
                turn_id=turn_id,
                sequence=self._next_seq(),
                clock=self.clock,
                outcome=ASROutcome.REJECTED,
                error=err_info,
                trace_id=session_ctx.identity.trace_id,
                model_revision=pinned_config.model_revision,
                config_revision=pinned_config.config_revision,
            )
            delivery = ASRResultDelivery(
                delivery_status=ASRDeliveryStatus.NOT_DELIVERED,
                admission_status=AdmissionStatus.INVALID,
                reason=exc.code,
            )
            self.telemetry.record_outcome_counters(
                dispatch_status=ASRDispatchStatus.REJECTED,
                delivery_status=delivery.delivery_status,
                is_error=True,
            )
            self.telemetry.emit_event(
                event_type="asr.rejected",
                session_id=session_id,
                turn_id=turn_id,
                sequence=self._next_seq(),
                monotonic_ns=self.clock.monotonic_ns(),
                clock_domain=self.clock.clock_domain,
                metadata={"utterance_id": res.utterance_id, "reason": exc.code},
            )
            return ASRProcessingRecord(
                result=res,
                dispatch_status=ASRDispatchStatus.REJECTED,
                delivery=delivery,
                claim_decision=None,
                legacy_projection=project_legacy_transcript(result=res),
            )

        self.lifecycle.register_audio(validated.audio)

        # Zero-length finalized audio with EOS metadata -> NO_SPEECH, never GPU work or invented speech.
        if validated.empty_audio:
            res = build_final_asr_result(
                session_id=session_id,
                utterance_id=validated.utterance.utterance_id,
                turn_id=validated.turn_ref.turn_id,
                sequence=self._next_seq(),
                clock=self.clock,
                outcome=ASROutcome.NO_SPEECH,
                raw_transcript="",
                trace_id=session_ctx.identity.trace_id,
                model_revision=pinned_config.model_revision,
                config_revision=pinned_config.config_revision,
            )
            self.lifecycle.release_audio_if_safe(validated.audio)
            delivery = ASRResultDelivery(
                delivery_status=ASRDeliveryStatus.NOT_DELIVERED,
                admission_status=AdmissionStatus.INVALID,
                reason="empty_audio_eos",
            )
            self.telemetry.record_outcome_counters(
                dispatch_status=ASRDispatchStatus.COMPLETED,
                delivery_status=delivery.delivery_status,
                is_no_speech=True,
            )
            return ASRProcessingRecord(
                result=res,
                dispatch_status=ASRDispatchStatus.COMPLETED,
                delivery=delivery,
                claim_decision=None,
                legacy_projection=project_legacy_transcript(result=res),
            )

        # 2. Pin M05 Lexicon snapshot & hotwords at admission
        try:
            pinned_lexicon: PinnedLexiconSnapshot = pin_lexicon_snapshot(
                lexicon_registry,
                strict_required=pinned_config.require_lexicon_snapshot,
            )
        except ASRConfigError as exc:
            self.lifecycle.release_audio_if_safe(validated.audio)
            res = build_final_asr_result(
                session_id=session_id,
                utterance_id=validated.utterance.utterance_id,
                turn_id=validated.turn_ref.turn_id,
                sequence=self._next_seq(),
                clock=self.clock,
                outcome=ASROutcome.REJECTED,
                error=exc.to_error_info(),
                trace_id=session_ctx.identity.trace_id,
                model_revision=pinned_config.model_revision,
                config_revision=pinned_config.config_revision,
            )
            delivery = ASRResultDelivery(
                delivery_status=ASRDeliveryStatus.NOT_DELIVERED,
                admission_status=AdmissionStatus.INVALID,
                reason=exc.code,
            )
            self.telemetry.record_outcome_counters(
                dispatch_status=ASRDispatchStatus.REJECTED,
                delivery_status=delivery.delivery_status,
                is_error=True,
            )
            return ASRProcessingRecord(
                result=res,
                dispatch_status=ASRDispatchStatus.REJECTED,
                delivery=delivery,
                claim_decision=None,
                legacy_projection=project_legacy_transcript(result=res),
                lexicon_unavailable_reason=exc.safe_message,
            )

        hotwords = self.hotword_cache.select(
            catalog_enabled=pinned_config.catalog_hotwords_enabled,
            catalog_provider=catalog_hotword_provider,
            custom_hotwords=custom_hotwords,
        )

        # 3. M02-scoped atomic utterance claim
        claim = await self.admission.claim_utterance(
            validated,
            session_ctx=session_ctx,
            expected_stream_epoch=expected_stream_epoch,
        )
        if claim.status != ClaimStatus.ACCEPTED:
            self.lifecycle.release_audio_if_safe(validated.audio)
            is_dup = claim.status == ClaimStatus.DUPLICATE
            res = build_final_asr_result(
                session_id=session_id,
                utterance_id=validated.utterance.utterance_id,
                turn_id=validated.turn_ref.turn_id,
                sequence=self._next_seq(),
                clock=self.clock,
                outcome=ASROutcome.REJECTED,
                error=build_safe_error_info(
                    code=f"ASR_CLAIM_{claim.status.value}",
                    category=(
                        ErrorCategory.CAPACITY
                        if claim.status == ClaimStatus.CAPACITY_REJECTED
                        else ErrorCategory.STALE_SCOPE
                    ),
                    retryable=Retryability.NO,
                    safe_message=claim.reason,
                ),
                trace_id=session_ctx.identity.trace_id,
                model_revision=pinned_config.model_revision,
                config_revision=pinned_config.config_revision,
                lexicon_revision=pinned_lexicon.lexicon_revision,
            )
            delivery = ASRResultDelivery(
                delivery_status=ASRDeliveryStatus.FENCED_STALE
                if claim.status == ClaimStatus.STALE_SCOPE
                else ASRDeliveryStatus.NOT_DELIVERED,
                admission_status=(
                    AdmissionStatus.DUPLICATE
                    if is_dup
                    else AdmissionStatus.BACKPRESSURE
                    if claim.status == ClaimStatus.CAPACITY_REJECTED
                    else AdmissionStatus.STALE_TURN
                ),
                reason=claim.reason,
            )
            self.telemetry.record_outcome_counters(
                dispatch_status=ASRDispatchStatus.REJECTED,
                delivery_status=delivery.delivery_status,
                is_duplicate=is_dup,
                is_error=not is_dup,
            )
            self.telemetry.emit_event(
                event_type="asr.rejected",
                session_id=session_id,
                turn_id=validated.turn_ref.turn_id,
                sequence=self._next_seq(),
                monotonic_ns=self.clock.monotonic_ns(),
                clock_domain=self.clock.clock_domain,
                metadata={"utterance_id": validated.utterance.utterance_id, "reason": claim.reason},
            )
            return ASRProcessingRecord(
                result=res,
                dispatch_status=ASRDispatchStatus.REJECTED,
                delivery=delivery,
                claim_decision=claim,
                legacy_projection=project_legacy_transcript(result=res),
            )

        turn_scope = claim.turn_scope or session_ctx.tg.turn_scope or session_ctx.root_scope

        try:
            # Legacy minimum RMS energy guard (if enabled) before GPU work
            if pinned_config.min_rms > 0.0 and validated.audio.rms_energy() < pinned_config.min_rms:
                res = build_final_asr_result(
                    session_id=session_id,
                    utterance_id=validated.utterance.utterance_id,
                    turn_id=validated.turn_ref.turn_id,
                    sequence=self._next_seq(),
                    clock=self.clock,
                    outcome=ASROutcome.NO_SPEECH,
                    raw_transcript="",
                    trace_id=session_ctx.identity.trace_id,
                    model_revision=pinned_config.model_revision,
                    config_revision=pinned_config.config_revision,
                    lexicon_revision=pinned_lexicon.lexicon_revision,
                )
                delivery = ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.NOT_DELIVERED,
                    admission_status=AdmissionStatus.INVALID,
                    reason="below_min_rms_threshold",
                )
                self.telemetry.record_outcome_counters(
                    dispatch_status=ASRDispatchStatus.COMPLETED,
                    delivery_status=delivery.delivery_status,
                    is_no_speech=True,
                )
                return ASRProcessingRecord(
                    result=res,
                    dispatch_status=ASRDispatchStatus.COMPLETED,
                    delivery=delivery,
                    claim_decision=claim,
                    legacy_projection=project_legacy_transcript(result=res),
                )

            # 4. Build M06 P1 ResourceRequest & execute through UnifiedGpuScheduler
            hotword_plan: HotwordPlan | None = None
            effective_config = pinned_config
            effective_hotwords = hotwords
            if enable_f2b:
                planner = HotwordPlanner()
                hotword_plan = planner.plan(
                    scope_id=validated.utterance.utterance_id,
                    session_id=session_id,
                    incarnation_id=getattr(session_ctx, "incarnation_id", None) or (context_hint.incarnation_id if context_hint is not None else session_id),
                    pinned_lexicon=pinned_lexicon,
                    now_monotonic_ns=self.clock.monotonic_ns(),
                    clock_domain=self.clock.clock_domain,
                    context_hint=context_hint,
                    baseline_terms=hotwords.terms,
                    profile_name=projection_policy,
                )
                effective_hotwords = replace(
                    hotwords,
                    terms=hotword_plan.terms,
                    hotwords_text=hotword_plan.hotwords_text,
                )
                effective_config = replace(
                    pinned_config,
                    decode_profile=build_attempt_decode_profile(pinned_config.decode_profile, beam_profile),
                )

            job_id = self._next_job_id(validated.utterance.utterance_id)
            request = build_asr_resource_request(
                recognition_job_id=job_id,
                utterance_input=validated,
                pinned_config=effective_config,
                pinned_lexicon=pinned_lexicon,
                hotwords=effective_hotwords,
                cancellation_scope=turn_scope,
                clock=self.clock,
                word_timestamps=word_timestamps,
            )

            self.telemetry.emit_event(
                event_type="asr.started",
                session_id=session_id,
                turn_id=validated.turn_ref.turn_id,
                sequence=self._next_seq(),
                monotonic_ns=self.clock.monotonic_ns(),
                clock_domain=self.clock.clock_domain,
                metadata={
                    "utterance_id": validated.utterance.utterance_id,
                    "model_revision": pinned_config.model_revision,
                    "priority": "P1",
                },
            )

            exec_res = await self.engine.run_admitted(request)

            # 5. Extract confidence, language & conservative M05 / F2-B candidates
            collected = exec_res.collected
            raw_text = collected.raw_transcript if collected is not None else ""
            conf_res = extract_confidence_estimate(collected) if collected is not None else None
            detected_lang = (
                resolve_language_metadata(collected, requested_language=pinned_config.decode_profile.language)
                if collected is not None
                else None
            )

            entity_resolution: EntityResolutionReport | None = None
            clarification_hint: ClarificationHint | None = None
            arbitration: AttemptArbitrationResult | None = None

            if enable_f2b:
                entity_resolution = resolve_automotive_entities(
                    utterance_id=validated.utterance.utterance_id,
                    raw_transcript=raw_text if exec_res.asr_outcome == ASROutcome.OK else "",
                    pinned_lexicon=pinned_lexicon,
                    context_hint=context_hint,
                    projection_policy=projection_policy,
                    final_revision=min_revision,
                    low_acoustic_evidence=(
                        conf_res is not None
                        and conf_res.estimate is not None
                        and conf_res.estimate.avg_logprob is not None
                        and conf_res.estimate.avg_logprob < -0.65
                    ),
                )
                assert hotword_plan is not None
                attempt0 = DecodeAttemptRecord(
                    utterance_id=validated.utterance.utterance_id,
                    attempt_index=0,
                    beam_profile=beam_profile,
                    beam_size=effective_config.decode_profile.beam_size,
                    hotword_plan=hotword_plan,
                    outcome=exec_res.asr_outcome,
                    raw_transcript=raw_text,
                    avg_logprob=conf_res.estimate.avg_logprob if conf_res and conf_res.estimate else None,
                    no_speech_prob=conf_res.estimate.no_speech_prob if conf_res and conf_res.estimate else None,
                    compression_ratio=None,
                )
                attempt1: DecodeAttemptRecord | None = None
                res1: EntityResolutionReport | None = None
                exec_res1: WhisperExecutionResult | None = None

                remaining_ms = max(0, request.deadline.remaining_ns(self.clock) // 1_000_000)
                run_alt, _ = should_run_alternate_decode(
                    alternate_enabled=alternate_enabled,
                    attempt0=attempt0,
                    resolution0=entity_resolution,
                    remaining_deadline_ms=remaining_ms,
                    cancelled=turn_scope.is_cancel_requested,
                    quarantined=exec_res.quarantined,
                )
                if run_alt:
                    alt_plan = HotwordPlanner().plan(
                        scope_id=validated.utterance.utterance_id,
                        session_id=session_id,
                        incarnation_id=getattr(session_ctx, "incarnation_id", None) or (context_hint.incarnation_id if context_hint is not None else session_id),
                        pinned_lexicon=pinned_lexicon,
                        now_monotonic_ns=self.clock.monotonic_ns(),
                        clock_domain=self.clock.clock_domain,
                        context_hint=context_hint,
                        baseline_terms=hotwords.terms,
                        profile_name=projection_policy,
                        disable_context_bias=True,
                    )
                    alt_cfg = replace(
                        pinned_config,
                        decode_profile=build_attempt_decode_profile(pinned_config.decode_profile, DecodeBeamProfile.ALTERNATE_FINAL),
                    )
                    alt_hw = replace(hotwords, terms=alt_plan.terms, hotwords_text=alt_plan.hotwords_text)
                    alt_req = build_asr_resource_request(
                        recognition_job_id=self._next_job_id(validated.utterance.utterance_id),
                        utterance_input=validated,
                        pinned_config=alt_cfg,
                        pinned_lexicon=pinned_lexicon,
                        hotwords=alt_hw,
                        cancellation_scope=turn_scope,
                        clock=self.clock,
                        attempt_index=1,
                        word_timestamps=word_timestamps,
                    )
                    exec_res1 = await self.engine.run_admitted(alt_req)
                    raw1 = exec_res1.collected.raw_transcript if exec_res1.collected is not None else ""
                    conf1 = extract_confidence_estimate(exec_res1.collected) if exec_res1.collected is not None else None
                    res1 = resolve_automotive_entities(
                        utterance_id=validated.utterance.utterance_id,
                        raw_transcript=raw1 if exec_res1.asr_outcome == ASROutcome.OK else "",
                        pinned_lexicon=pinned_lexicon,
                        context_hint=context_hint,
                        projection_policy=projection_policy,
                        final_revision=min_revision,
                    )
                    attempt1 = DecodeAttemptRecord(
                        utterance_id=validated.utterance.utterance_id,
                        attempt_index=1,
                        beam_profile=DecodeBeamProfile.ALTERNATE_FINAL,
                        beam_size=alt_cfg.decode_profile.beam_size,
                        hotword_plan=alt_plan,
                        outcome=exec_res1.asr_outcome,
                        raw_transcript=raw1,
                        avg_logprob=conf1.estimate.avg_logprob if conf1 and conf1.estimate else None,
                        no_speech_prob=conf1.estimate.no_speech_prob if conf1 and conf1.estimate else None,
                        compression_ratio=None,
                    )

                arbitration = arbitrate_decode_attempts(
                    attempt0=attempt0,
                    resolution0=entity_resolution,
                    attempt1=attempt1,
                    resolution1=res1,
                )
                if arbitration.selected_attempt.attempt_index == 1 and exec_res1 is not None:
                    exec_res = exec_res1
                    collected = exec_res1.collected
                    raw_text = arbitration.selected_attempt.raw_transcript
                    conf_res = extract_confidence_estimate(collected) if collected is not None else None
                    detected_lang = (
                        resolve_language_metadata(collected, requested_language=pinned_config.decode_profile.language)
                        if collected is not None
                        else None
                    )
                entity_resolution = arbitration.selected_resolution
                clarification_hint = arbitration.clarification_hint
                selected_entities = entity_resolution.candidates
                lex_rev = pinned_lexicon.lexicon_revision
                lex_unavail = pinned_lexicon.unavailable_reason
            else:
                cand_bundle = extract_conservative_candidates(
                    pinned_lexicon,
                    raw_text if exec_res.asr_outcome == ASROutcome.OK else "",
                    strict_required=pinned_config.require_lexicon_snapshot,
                )
                selected_entities = cand_bundle.candidates
                lex_rev = cand_bundle.lexicon_revision
                lex_unavail = cand_bundle.unavailable_reason

            safe_error = None
            if exec_res.asr_outcome in {ASROutcome.ERROR, ASROutcome.REJECTED, ASROutcome.UNKNOWN}:
                safe_error = build_safe_error_info(
                    code=exec_res.error_code or f"ASR_{exec_res.asr_outcome.value}",
                    category=(
                        ErrorCategory.PROVIDER
                        if exec_res.asr_outcome in {ASROutcome.ERROR, ASROutcome.UNKNOWN}
                        else ErrorCategory.CAPACITY
                    ),
                    retryable=Retryability.UNKNOWN,
                    safe_message=exec_res.error_message or "ASR execution did not succeed",
                )
            elif exec_res.asr_outcome == ASROutcome.NO_SPEECH and collected is not None and collected.malformed_metadata:
                safe_error = build_safe_error_info(
                    code="ASR_NO_SPEECH_WITH_METADATA_WARNINGS",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message="No valid speech after provider guards",
                )

            built_ns = self.clock.monotonic_ns()
            built_domain = self.clock.clock_domain

            prelim_metrics: tuple[MetricSample, ...] = self.telemetry.record_timings(
                admitted_ns=admitted_ns,
                admitted_domain=admitted_domain,
                started_ns=exec_res.started_monotonic_ns,
                started_domain=self.clock.clock_domain if exec_res.started_monotonic_ns is not None else None,
                completed_ns=exec_res.completed_monotonic_ns,
                completed_domain=self.clock.clock_domain if exec_res.completed_monotonic_ns is not None else None,
                built_ns=built_ns,
                built_domain=built_domain,
                delivered_ns=None,
                delivered_domain=None,
                audio_duration_sec=validated.audio.duration_sec,
                succeeded=(exec_res.asr_outcome == ASROutcome.OK),
            )

            result = build_final_asr_result(
                session_id=session_id,
                utterance_id=validated.utterance.utterance_id,
                turn_id=validated.turn_ref.turn_id,
                sequence=self._next_seq(),
                clock=self.clock,
                outcome=exec_res.asr_outcome,
                raw_transcript=raw_text,
                language=detected_lang,
                entities=selected_entities,
                confidence=conf_res.estimate if conf_res is not None else None,
                error=safe_error,
                metrics=prelim_metrics,
                trace_id=session_ctx.identity.trace_id,
                revision=min_revision,
                model_revision=pinned_config.model_revision,
                config_revision=pinned_config.config_revision,
                lexicon_revision=lex_rev,
            )

            if before_enqueue_hook is not None:
                hook_res = before_enqueue_hook(result)
                if inspect.isawaitable(hook_res):
                    await hook_res

            # 6. Atomic M02 delivery fence (only for valid OK results)
            if result.outcome == ASROutcome.OK:
                delivery = await self.consumer.admit_asr_result(
                    result,
                    session_ctx=session_ctx,
                    stream_epoch=validated.stream_ref.format_epoch,
                    turn_scope=turn_scope,
                    deadline=request.deadline,
                )
            else:
                delivery = ASRResultDelivery(
                    delivery_status=(
                        ASRDeliveryStatus.FENCED_STALE
                        if turn_scope.is_cancel_requested
                        else ASRDeliveryStatus.NOT_DELIVERED
                    ),
                    admission_status=(
                        AdmissionStatus.CANCELED
                        if turn_scope.is_cancel_requested
                        else AdmissionStatus.INVALID
                    ),
                    reason=f"outcome_{result.outcome.value.lower()}",
                )

            self.telemetry.record_outcome_counters(
                dispatch_status=exec_res.dispatch_status,
                delivery_status=delivery.delivery_status,
                is_no_speech=(result.outcome == ASROutcome.NO_SPEECH),
                is_error=(result.outcome in {ASROutcome.ERROR, ASROutcome.UNKNOWN}),
            )

            evt_type = (
                "asr.completed"
                if delivery.delivery_status == ASRDeliveryStatus.DELIVERED
                else "asr.result.discarded"
                if delivery.delivery_status == ASRDeliveryStatus.FENCED_STALE
                else "asr.completed"
            )
            self.telemetry.emit_event(
                event_type=evt_type,
                session_id=session_id,
                turn_id=validated.turn_ref.turn_id,
                sequence=self._next_seq(),
                monotonic_ns=self.clock.monotonic_ns(),
                clock_domain=self.clock.clock_domain,
                metadata={
                    "utterance_id": result.utterance_id,
                    "outcome": result.outcome.value,
                    "delivery_status": delivery.delivery_status.value,
                    "model_revision": pinned_config.model_revision,
                    "lexicon_revision": lex_rev or "unavailable",
                },
            )

            return ASRProcessingRecord(
                result=result,
                dispatch_status=exec_res.dispatch_status,
                delivery=delivery,
                claim_decision=claim,
                legacy_projection=project_legacy_transcript(result=result, collected=collected),
                execution_result=exec_res,
                lexicon_unavailable_reason=lex_unavail,
                hotword_plan=hotword_plan,
                entity_resolution=entity_resolution,
                clarification_hint=clarification_hint,
                attempt_arbitration=arbitration,
            )
        finally:
            await self.admission.complete_claim(claim.claim_key)
            # Releases input buffer only when native inference no longer borrows it.
            self.lifecycle.release_audio_if_safe(validated.audio)
