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
from typing import Any, Callable, Mapping

from backend.core.contracts.common import (
    ErrorCategory,
    ErrorInfo,
    GenerationRef,
    MetricSample,
    Retryability,
)
from backend.core.contracts.synthesis import (
    AudioChunk,
    CacheStatus,
    QualityStatus,
    SynthesisPlan,
)
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.deadlines import Clock, DeadlineBudget
from backend.core.runtime.result_admission import AdmissionStatus
from backend.core.runtime.session_context import SessionContext
from backend.neural_synthesis.f5_bc.adaptive_profiles import AdaptiveProfileSelector
from backend.neural_synthesis.cache_adapter import StrictSynthesisCacheAdapter
from backend.neural_synthesis.f5_bc.cache_store import CacheEligibility
from backend.neural_synthesis.chunk_builder import RAW_AUDIO_FORMAT, build_audio_chunk
from backend.neural_synthesis.config_adapter import BASELINE_ODE_STEPS, BASELINE_SOLVER, PinnedSynthesisSnapshot
from backend.neural_synthesis.decoder_adapter import DecoderAdapter, DecoderOutputDescriptor
from backend.neural_synthesis.delivery import DeliveryOutcome, GenerationDeliveryFence
from backend.neural_synthesis.duration_estimator import DurationEstimate, DurationEstimationError, DurationEstimator
from backend.neural_synthesis.duration_guard import DurationDecision, DurationGuard
from backend.neural_synthesis.encoder_adapter import EncodedCondition, EncoderAdapter, EncoderValidationError
from backend.neural_synthesis.latent_initializer import (
    LatentDescriptor,
    LatentInitializationError,
    LatentInitializer,
)
from backend.neural_synthesis.lifecycle import SynthesisLifecycleManager
from backend.neural_synthesis.model_adapter import ModelResidencyAdapter, SynthesisModelHandles
from backend.neural_synthesis.plan_validator import PlanAdmission, ScopedPlanClaimRegistry, validate_and_admit_plan
from backend.neural_synthesis.f5_bc.quality_guard import QualityAssessment, QualityGuard
from backend.neural_synthesis.raw_validator import RawAudioValidator, RawValidationResult
from backend.neural_synthesis.f5_bc.recovery_policy import RecoveryDecision, SameSeedRecoveryPolicy
from backend.neural_synthesis.scheduler_bridge import ProviderBarriers, SchedulerBridge, SynthesisJobRef
from backend.neural_synthesis.solver_adapter import (
    BASELINE_SOLVER_PROFILE,
    SolverAdapter,
    SolverProfile,
    SolverValidationError,
    validate_solver_profile,
)
from backend.neural_synthesis.telemetry import SynthesisTelemetry
from backend.runtime_resources.contracts import AdmissionOutcome, ExecutionLeaseState
from backend.runtime_resources.scheduler import UnifiedGpuScheduler


@dataclass(frozen=True, slots=True)
class ChunkExecutionOutcome:
    """Per-chunk separated execution, structural validation, delivery, and lease outcome."""

    chunk_id: str
    chunk_index: int
    execution_ok: bool
    structurally_valid: bool
    delivery_accepted: bool
    physical_completed: bool
    quarantined: bool
    cache_status: CacheStatus
    quality_status: QualityStatus
    audio_chunk: AudioChunk | None = None
    job_ref: SynthesisJobRef | None = None
    duration_decision: DurationDecision | None = None
    latent_descriptor: LatentDescriptor | None = None
    decoder_descriptor: DecoderOutputDescriptor | None = None
    raw_validation: RawValidationResult | None = None
    delivery_outcome: DeliveryOutcome | None = None
    lease_state: ExecutionLeaseState | None = None
    error: ErrorInfo | None = None
    metrics: tuple[MetricSample, ...] = ()


@dataclass(frozen=True, slots=True)
class SynthesisOutcome:
    """Aggregate F5-A synthesis result distinguishing execution, validity, delivery, and completion."""

    status: str  # "COMPLETED" | "NO_SPEECH" | "FAILED" | "CANCELLED" | "HELD"
    plan_admission: PlanAdmission
    accepted_chunks: tuple[AudioChunk, ...]
    chunk_outcomes: tuple[ChunkExecutionOutcome, ...]
    execution_ok: bool
    structurally_valid: bool
    delivery_accepted: bool
    physical_completed: bool
    quarantined: bool
    quality_status: QualityStatus
    error: ErrorInfo | None = None
    metrics: tuple[MetricSample, ...] = ()


class NeuralSynthesisPipeline:
    """
    Single strict prepared-plan neural synthesis entry point for Freya 2.0 (F5-A).

    Pipeline stages per admitted speech chunk:
      1. M01/M03 plan admission & snapshot pinning (`validate_and_admit_plan`)
      2. M02 scope/cancellation check & scoped deduplication claim (`ScopedPlanClaimRegistry`)
      3. Strict cache check (`StrictSynthesisCacheAdapter`, BYPASS on incomplete legacy provenance)
      4. Prepared text encoding (`EncoderAdapter`, zero F5 linguistic normalization)
      5. Duration estimation & pre-allocation guard (`DurationEstimator` + `DurationGuard`)
      6. Seeded latent preparation & Euler32 baseline check (`LatentInitializer` + `SolverAdapter`)
      7. M06 scheduled DiT/VAE/materialization (`SchedulerBridge`, P2 first chunk / P4 subsequent)
      8. Raw 48 kHz mono FLOAT32_LE validation (`RawAudioValidator`, zero DSP)
      9. Immutable M01 `AudioChunk` creation (`build_audio_chunk`)
     10. Atomic M02 generation delivery (`GenerationDeliveryFence`) & safe M04 telemetry
    """

    def __init__(
        self,
        *,
        scheduler: UnifiedGpuScheduler,
        residency_adapter: ModelResidencyAdapter | None = None,
        cache_adapter: StrictSynthesisCacheAdapter | None = None,
        encoder_adapter: EncoderAdapter | None = None,
        duration_estimator: DurationEstimator | None = None,
        duration_guard: DurationGuard | None = None,
        latent_initializer: LatentInitializer | None = None,
        solver_adapter: SolverAdapter | None = None,
        decoder_adapter: DecoderAdapter | None = None,
        raw_validator: RawAudioValidator | None = None,
        quality_guard: QualityGuard | None = None,
        recovery_policy: SameSeedRecoveryPolicy | None = None,
        profile_selector: AdaptiveProfileSelector | None = None,
        delivery_fence: GenerationDeliveryFence | None = None,
        claims: ScopedPlanClaimRegistry | None = None,
        telemetry: SynthesisTelemetry | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.clock: Clock = scheduler.clock
        self.residency_adapter = residency_adapter or ModelResidencyAdapter(scheduler.residency_manager)
        self.scheduler_bridge = SchedulerBridge(scheduler, max_in_flight_per_generation=1)
        self.cache_adapter = cache_adapter or StrictSynthesisCacheAdapter()
        self.encoder_adapter = encoder_adapter or EncoderAdapter()
        self.duration_estimator = duration_estimator or DurationEstimator()
        self.duration_guard = duration_guard or DurationGuard()
        self.latent_initializer = latent_initializer or LatentInitializer()
        self.solver_adapter = solver_adapter or SolverAdapter()
        self.decoder_adapter = decoder_adapter or DecoderAdapter()
        self.raw_validator = raw_validator or RawAudioValidator()
        self.quality_guard = quality_guard or QualityGuard(raw_validator=self.raw_validator)
        self.recovery_policy = recovery_policy or SameSeedRecoveryPolicy(enabled=False, clock=self.clock)
        self.profile_selector = profile_selector or AdaptiveProfileSelector(mode="BASELINE_ONLY")
        self.delivery_fence = delivery_fence or GenerationDeliveryFence()
        self.claims = claims or ScopedPlanClaimRegistry()
        self.telemetry = telemetry or SynthesisTelemetry(clock=self.clock)
        self.lifecycle = SynthesisLifecycleManager(
            claims=self.claims,
            delivery_fence=self.delivery_fence,
            scheduler=self.scheduler,
        )

    async def synthesize_plan(
        self,
        plan: SynthesisPlan | Any,
        *,
        session_ctx: SessionContext | None = None,
        expected_generation_ref: GenerationRef | None = None,
        cancellation_scope: CancellationScope | None = None,
        chunk_sink: Callable[[AudioChunk], None] | None = None,
        deadline: DeadlineBudget | None = None,
        legacy_cache: Mapping[tuple[str, int], Any] | None = None,
        collapse_guard_fn: Callable[[Any, int], bool | float] | None = None,
        requested_solver: str = BASELINE_SOLVER,
        requested_ode_steps: int = BASELINE_ODE_STEPS,
        duration_units: str = "frames@25Hz",
        allow_baseline_frame_trim: bool = True,
        untrusted_already_normalized_flag: bool | None = None,
        pin_kwargs: dict[str, Any] | None = None,
        barriers_by_chunk: Mapping[int, ProviderBarriers] | None = None,
        admit_media_to_session_queue: bool = True,
        use_torch: bool | None = None,
        override_latent: Any = None,
        override_rng_isolation_mode: str | None = None,
    ) -> SynthesisOutcome:
        request_accepted_ns = self.clock.monotonic_ns()
        if session_ctx is not None and self.lifecycle.is_session_closed(session_ctx.identity.session_id):
            err = ErrorInfo(
                code="SESSION_CLOSED_NO_REENTRY",
                category=ErrorCategory.STALE_SCOPE,
                retryable=Retryability.NO,
                safe_message="Closed session refuses synthesis reentry",
            )
            return self._failed_before_admission(plan, err)

        admission = validate_and_admit_plan(
            plan,
            session_ctx=session_ctx,
            expected_generation_ref=expected_generation_ref,
            untrusted_already_normalized_flag=untrusted_already_normalized_flag,
            pin_kwargs=pin_kwargs,
        )
        if not admission.accepted or admission.pinned_snapshot is None:
            self.telemetry.inc_counter("f5.plan_rejections")
            return SynthesisOutcome(
                status="FAILED",
                plan_admission=admission,
                accepted_chunks=(),
                chunk_outcomes=(),
                execution_ok=False,
                structurally_valid=False,
                delivery_accepted=False,
                physical_completed=True,
                quarantined=False,
                quality_status=QualityStatus.UNKNOWN,
                error=admission.error,
            )

        assert isinstance(plan, SynthesisPlan)
        snapshot = admission.pinned_snapshot
        self.delivery_fence.register_active_plan(plan.generation_ref, plan.plan_id, plan.plan_revision)

        if admission.is_no_speech:
            return SynthesisOutcome(
                status="NO_SPEECH",
                plan_admission=admission,
                accepted_chunks=(),
                chunk_outcomes=(),
                execution_ok=True,
                structurally_valid=True,
                delivery_accepted=True,
                physical_completed=True,
                quarantined=False,
                quality_status=QualityStatus.UNKNOWN,
            )

        try:
            solver_profile = validate_solver_profile(requested_solver, requested_ode_steps, strict=True)
        except SolverValidationError as exc:
            return SynthesisOutcome(
                status="FAILED",
                plan_admission=admission,
                accepted_chunks=(),
                chunk_outcomes=(),
                execution_ok=False,
                structurally_valid=False,
                delivery_accepted=False,
                physical_completed=True,
                quarantined=False,
                quality_status=QualityStatus.UNKNOWN,
                error=exc.error_info,
            )

        eff_scope = self._resolve_scope(plan, session_ctx, cancellation_scope)
        trace_id = session_ctx.identity.trace_id if session_ctx is not None else None

        # Borrow single authoritative residency handle pin for this synthesis invocation
        try:
            residency_pin, handles = await self.residency_adapter.borrow_pin(snapshot)
        except Exception as exc:
            err = ErrorInfo(
                code="MODEL_HANDLE_UNAVAILABLE",
                category=ErrorCategory.PROVIDER,
                retryable=Retryability.NO,
                safe_message=f"Failed to borrow approved model handle ({type(exc).__name__})",
            )
            return SynthesisOutcome(
                status="FAILED",
                plan_admission=admission,
                accepted_chunks=(),
                chunk_outcomes=(),
                execution_ok=False,
                structurally_valid=False,
                delivery_accepted=False,
                physical_completed=True,
                quarantined=False,
                quality_status=QualityStatus.UNKNOWN,
                error=err,
            )

        accepted_chunks: list[AudioChunk] = []
        chunk_outcomes: list[ChunkExecutionOutcome] = []
        all_metrics: list[MetricSample] = []
        any_quarantined = False
        all_physical_completed = True
        first_error: ErrorInfo | None = None
        final_status = "COMPLETED"

        try:
            for idx, chunk_plan in enumerate(plan.chunks):
                if eff_scope.is_cancel_requested or (
                    self.delivery_fence.preflight_generation_active(
                        plan.generation_ref,
                        plan_id=plan.plan_id,
                        plan_revision=plan.plan_revision,
                        session_ctx=session_ctx,
                    )
                    != AdmissionStatus.ACCEPTED
                ):
                    final_status = "CANCELLED"
                    first_error = ErrorInfo(
                        code="GENERATION_CANCELLED",
                        category=ErrorCategory.STALE_SCOPE,
                        retryable=Retryability.NO,
                        safe_message="Generation cancelled before chunk dispatch",
                    )
                    break

                claim_status, _ = self.claims.claim(plan, chunk_plan)
                if claim_status in {"DUPLICATE", "CONFLICT"}:
                    self.telemetry.inc_counter("f5.stale_or_duplicate_count")
                    code = "DUPLICATE_CHUNK_CLAIM" if claim_status == "DUPLICATE" else "CONFLICTING_CHUNK_PAYLOAD"
                    err = ErrorInfo(
                        code=code,
                        category=ErrorCategory.VALIDATION,
                        retryable=Retryability.NO,
                        safe_message=f"Chunk claim rejected ({claim_status})",
                    )
                    first_error = err
                    final_status = "FAILED"
                    chunk_outcomes.append(
                        ChunkExecutionOutcome(
                            chunk_id=chunk_plan.chunk_id,
                            chunk_index=chunk_plan.chunk_index,
                            execution_ok=False,
                            structurally_valid=False,
                            delivery_accepted=False,
                            physical_completed=True,
                            quarantined=False,
                            cache_status=CacheStatus.UNKNOWN,
                            quality_status=QualityStatus.UNKNOWN,
                            error=err,
                        )
                    )
                    break

                # Cache lookup (explicit BYPASS on unproven legacy cache)
                cache_res = self.cache_adapter.lookup(
                    plan=plan,
                    chunk=chunk_plan,
                    snapshot=snapshot,
                    legacy_cache=legacy_cache,
                )
                if cache_res.cache_status == CacheStatus.HIT and cache_res.payload is not None and cache_res.sample_count is not None:
                    co = await self._deliver_cached_chunk(
                        plan=plan,
                        chunk_plan=chunk_plan,
                        snapshot=snapshot,
                        solver_profile=solver_profile,
                        payload=cache_res.payload,
                        sample_count=cache_res.sample_count,
                        session_ctx=session_ctx,
                        chunk_sink=chunk_sink,
                        deadline=deadline,
                        admit_media_to_session_queue=admit_media_to_session_queue,
                        collapse_guard_fn=collapse_guard_fn,
                        request_accepted_ns=request_accepted_ns,
                        is_first_chunk=(idx == 0),
                        trace_id=trace_id,
                    )
                    chunk_outcomes.append(co)
                    all_metrics.extend(co.metrics)
                    if co.delivery_accepted and co.audio_chunk is not None:
                        accepted_chunks.append(co.audio_chunk)
                        continue
                    first_error = co.error
                    final_status = "FAILED"
                    break

                co = await self._execute_native_chunk_with_recovery(
                    plan=plan,
                    chunk_index=idx,
                    snapshot=snapshot,
                    handles=handles,
                    solver_profile=solver_profile,
                    cache_status=cache_res.cache_status,
                    eff_scope=eff_scope,
                    session_ctx=session_ctx,
                    chunk_sink=chunk_sink,
                    deadline=deadline,
                    collapse_guard_fn=collapse_guard_fn,
                    duration_units=duration_units,
                    allow_baseline_frame_trim=allow_baseline_frame_trim,
                    barriers=(barriers_by_chunk or {}).get(idx),
                    admit_media_to_session_queue=admit_media_to_session_queue,
                    request_accepted_ns=request_accepted_ns,
                    trace_id=trace_id,
                    use_torch=use_torch,
                    override_latent=override_latent,
                    override_rng_isolation_mode=override_rng_isolation_mode,
                )
                chunk_outcomes.append(co)
                all_metrics.extend(co.metrics)
                if co.quarantined:
                    any_quarantined = True
                if not co.physical_completed:
                    all_physical_completed = False
                if co.delivery_accepted and co.audio_chunk is not None:
                    accepted_chunks.append(co.audio_chunk)
                    continue
                first_error = co.error
                final_status = "CANCELLED" if eff_scope.is_cancel_requested else "FAILED"
                break
        finally:
            await self.residency_adapter.release_session_pin(residency_pin)

        exec_ok = bool(chunk_outcomes) and all(c.execution_ok for c in chunk_outcomes) and len(accepted_chunks) == len(plan.chunks)
        struct_ok = bool(chunk_outcomes) and all(c.structurally_valid for c in chunk_outcomes) and len(accepted_chunks) == len(plan.chunks)
        deliv_ok = bool(chunk_outcomes) and all(c.delivery_accepted for c in chunk_outcomes) and len(accepted_chunks) == len(plan.chunks)
        agg_quality = (
            QualityStatus.FAIL
            if any(c.quality_status == QualityStatus.FAIL for c in chunk_outcomes)
            else QualityStatus.UNKNOWN
        )
        return SynthesisOutcome(
            status=final_status,
            plan_admission=admission,
            accepted_chunks=tuple(accepted_chunks),
            chunk_outcomes=tuple(chunk_outcomes),
            execution_ok=exec_ok,
            structurally_valid=struct_ok,
            delivery_accepted=deliv_ok,
            physical_completed=all_physical_completed,
            quarantined=any_quarantined,
            quality_status=agg_quality,
            error=first_error,
            metrics=tuple(all_metrics),
        )

    async def _deliver_cached_chunk(
        self,
        *,
        plan: SynthesisPlan,
        chunk_plan: Any,
        snapshot: PinnedSynthesisSnapshot,
        solver_profile: SolverProfile,
        payload: bytes,
        sample_count: int,
        session_ctx: SessionContext | None,
        chunk_sink: Callable[[AudioChunk], None] | None,
        deadline: DeadlineBudget | None,
        admit_media_to_session_queue: bool,
        collapse_guard_fn: Callable[[Any, int], bool | float] | None,
        request_accepted_ns: int,
        is_first_chunk: bool,
        trace_id: str | None,
    ) -> ChunkExecutionOutcome:
        raw_val = self.raw_validator.validate(
            payload=payload,
            sample_count=sample_count,
            audio_format=RAW_AUDIO_FORMAT,
            collapse_guard_fn=collapse_guard_fn,
            collapse_guard_scope="CACHE_HIT_STRUCTURAL",
        )
        if not raw_val.structurally_valid:
            return ChunkExecutionOutcome(
                chunk_id=chunk_plan.chunk_id,
                chunk_index=chunk_plan.chunk_index,
                execution_ok=True,
                structurally_valid=False,
                delivery_accepted=False,
                physical_completed=True,
                quarantined=False,
                cache_status=CacheStatus.HIT,
                quality_status=raw_val.quality_status,
                raw_validation=raw_val,
                error=raw_val.error,
            )

        ready_ns = self.clock.monotonic_ns()
        ttfa_ms = self.telemetry.elapsed_ms(request_accepted_ns, ready_ns) if is_first_chunk else None
        actual_dur_ms = (sample_count * 1000.0) / 48000.0
        metrics = self.telemetry.record_chunk_metrics(
            generation_ref=plan.generation_ref,
            plan_id=plan.plan_id,
            plan_revision=plan.plan_revision,
            chunk_id=chunk_plan.chunk_id,
            chunk_index=chunk_plan.chunk_index,
            cache_status=CacheStatus.HIT,
            sample_count=sample_count,
            actual_duration_ms=actual_dur_ms,
            queue_wait_ms=0.0,
            encoder_ms=None,
            duration_guard_ms=None,
            ode_ms=None,
            decoder_ms=None,
            inference_ms=0.0,
            dispatch_wait_ms=0.0,
            ttfa_ms=ttfa_ms,
            solver=solver_profile.solver_name,
            ode_steps=solver_profile.steps,
            voice_profile=snapshot.voice_profile.profile_id,
            model_revision=snapshot.model_descriptor.model_revision,
            trace_id=trace_id,
        )
        chunk = build_audio_chunk(
            plan=plan,
            chunk_plan=chunk_plan,
            snapshot=snapshot,
            solver_profile=solver_profile,
            sample_count=sample_count,
            payload=payload,
            cache_status=CacheStatus.HIT,
            quality_status=raw_val.quality_status,
            metrics=metrics,
        )
        deliv = await self.delivery_fence.deliver(
            chunk,
            session_ctx=session_ctx,
            chunk_sink=chunk_sink,
            expected_plan_revision=plan.plan_revision,
            deadline=deadline,
            admit_media_to_session_queue=admit_media_to_session_queue,
        )
        return ChunkExecutionOutcome(
            chunk_id=chunk_plan.chunk_id,
            chunk_index=chunk_plan.chunk_index,
            execution_ok=True,
            structurally_valid=True,
            delivery_accepted=deliv.accepted,
            physical_completed=True,
            quarantined=False,
            cache_status=CacheStatus.HIT,
            quality_status=raw_val.quality_status,
            audio_chunk=deliv.chunk,
            raw_validation=raw_val,
            delivery_outcome=deliv,
            error=deliv.error,
            metrics=metrics,
        )

    async def _execute_native_chunk_with_recovery(
        self,
        *,
        plan: SynthesisPlan,
        chunk_index: int,
        snapshot: PinnedSynthesisSnapshot,
        handles: SynthesisModelHandles,
        solver_profile: SolverProfile,
        cache_status: CacheStatus,
        eff_scope: CancellationScope,
        session_ctx: SessionContext | None,
        chunk_sink: Callable[[AudioChunk], None] | None,
        deadline: DeadlineBudget | None,
        collapse_guard_fn: Callable[[Any, int], bool | float] | None,
        duration_units: str,
        allow_baseline_frame_trim: bool,
        barriers: ProviderBarriers | None,
        admit_media_to_session_queue: bool,
        request_accepted_ns: int,
        trace_id: str | None,
        use_torch: bool | None,
        override_latent: Any,
        override_rng_isolation_mode: str | None,
    ) -> ChunkExecutionOutcome:
        co = await self._execute_native_chunk(
            plan=plan,
            chunk_index=chunk_index,
            snapshot=snapshot,
            handles=handles,
            solver_profile=solver_profile,
            cache_status=cache_status,
            eff_scope=eff_scope,
            session_ctx=session_ctx,
            chunk_sink=chunk_sink,
            deadline=deadline,
            collapse_guard_fn=collapse_guard_fn,
            duration_units=duration_units,
            allow_baseline_frame_trim=allow_baseline_frame_trim,
            barriers=barriers,
            admit_media_to_session_queue=admit_media_to_session_queue,
            request_accepted_ns=request_accepted_ns,
            trace_id=trace_id,
            use_torch=use_torch,
            override_latent=override_latent,
            override_rng_isolation_mode=override_rng_isolation_mode,
        )
        if co.delivery_accepted:
            return co

        chunk_plan = plan.chunks[chunk_index]
        rec = self.recovery_policy.evaluate(
            attempt=1,
            seed=snapshot.seed,
            generation_ref=plan.generation_ref,
            plan_id=plan.plan_id,
            plan_revision=plan.plan_revision,
            chunk_id=chunk_plan.chunk_id,
            error=co.error,
            physical_completed=co.physical_completed,
            quarantined=co.quarantined,
            already_delivered=co.delivery_accepted,
            cancellation_scope=eff_scope,
            deadline=deadline,
        )
        if not rec.should_retry:
            return co

        self.telemetry.inc_counter("f5.same_seed_recovery_attempts")
        return await self._execute_native_chunk(
            plan=plan,
            chunk_index=chunk_index,
            snapshot=snapshot,
            handles=handles,
            solver_profile=solver_profile,
            cache_status=cache_status,
            eff_scope=eff_scope,
            session_ctx=session_ctx,
            chunk_sink=chunk_sink,
            deadline=deadline,
            collapse_guard_fn=collapse_guard_fn,
            duration_units=duration_units,
            allow_baseline_frame_trim=allow_baseline_frame_trim,
            barriers=barriers,
            admit_media_to_session_queue=admit_media_to_session_queue,
            request_accepted_ns=request_accepted_ns,
            trace_id=trace_id,
            use_torch=use_torch,
            override_latent=override_latent,
            override_rng_isolation_mode=override_rng_isolation_mode,
        )

    async def _execute_native_chunk(
        self,
        *,
        plan: SynthesisPlan,
        chunk_index: int,
        snapshot: PinnedSynthesisSnapshot,
        handles: SynthesisModelHandles,
        solver_profile: SolverProfile,
        cache_status: CacheStatus,
        eff_scope: CancellationScope,
        session_ctx: SessionContext | None,
        chunk_sink: Callable[[AudioChunk], None] | None,
        deadline: DeadlineBudget | None,
        collapse_guard_fn: Callable[[Any, int], bool | float] | None,
        duration_units: str,
        allow_baseline_frame_trim: bool,
        barriers: ProviderBarriers | None,
        admit_media_to_session_queue: bool,
        request_accepted_ns: int,
        trace_id: str | None,
        use_torch: bool | None,
        override_latent: Any,
        override_rng_isolation_mode: str | None,
    ) -> ChunkExecutionOutcome:
        chunk_plan = plan.chunks[chunk_index]

        # Stage 4: Prepared-text encoding (zero normalization)
        t_enc_start = self.clock.monotonic_ns()
        try:
            encoded = self.encoder_adapter.encode(
                chunk_plan,
                tts_model=handles.tts_model,
                char_to_id=handles.char_to_id,
                vocab_revision=handles.vocab_revision,
                device=handles.device,
            )
        except EncoderValidationError as exc:
            return self._fail_chunk(chunk_plan, cache_status, exc.error_info)
        encoder_ms = self.telemetry.elapsed_ms(t_enc_start, self.clock.monotonic_ns())

        # Stage 5: Duration estimation & pre-allocation guard
        t_dur_start = self.clock.monotonic_ns()
        try:
            estimate = self.duration_estimator.estimate(
                encoded,
                tts_model=handles.tts_model,
                snapshot=snapshot,
                override_units=duration_units,
            )
        except DurationEstimationError as exc:
            self.telemetry.inc_counter("f5.duration_guard_rejections")
            return self._fail_chunk(chunk_plan, cache_status, exc.error_info)

        decision = self.duration_guard.evaluate(
            estimate,
            snapshot,
            batch_size=1,
            memory_budget=self.scheduler.memory_budget,
        )
        duration_guard_ms = self.telemetry.elapsed_ms(t_dur_start, self.clock.monotonic_ns())
        if not decision.allowed:
            self.telemetry.inc_counter("f5.duration_guard_rejections")
            return self._fail_chunk(chunk_plan, cache_status, decision.error, duration_decision=decision)

        # Stage 6: Seeded latent initialization with strict RNG isolation
        rng_mode = override_rng_isolation_mode or handles.rng_isolation_mode
        try:
            latent, latent_desc = self.latent_initializer.initialize(
                decision=decision,
                snapshot=snapshot,
                tts_model=handles.tts_model,
                device=handles.device,
                rng_isolation_mode=rng_mode,
                use_torch=use_torch,
                override_latent=override_latent,
            )
        except LatentInitializationError as exc:
            return self._fail_chunk(chunk_plan, cache_status, exc.error_info, duration_decision=decision)

        # Stage 7: M06 scheduling & provider execution (P2 first chunk, P4 subsequent)
        enqueue_ns = self.clock.monotonic_ns()
        job_ref, req = self.scheduler_bridge.build_request(
            generation_ref=plan.generation_ref,
            plan_id=plan.plan_id,
            plan_revision=plan.plan_revision,
            chunk_id=chunk_plan.chunk_id,
            chunk_index=chunk_plan.chunk_index,
            handles=handles,
            encoded=encoded,
            estimate=estimate,
            decision=decision,
            latent=latent,
            latent_desc=latent_desc,
            solver_profile=solver_profile,
            solver_adapter=self.solver_adapter,
            decoder_adapter=self.decoder_adapter,
            cancellation_scope=eff_scope,
            deadline=deadline,
            is_first_speech_chunk=(chunk_index == 0),
            strict=True,
            allow_baseline_frame_trim=allow_baseline_frame_trim,
            barriers=barriers,
        )

        sched_out, prov_res = await self.scheduler_bridge.dispatch_and_execute(job_ref, req)
        native_done_ns = self.clock.monotonic_ns()

        if sched_out.admission != AdmissionOutcome.ADMITTED:
            err = ErrorInfo(
                code=f"SCHEDULER_{sched_out.admission.value}",
                category=ErrorCategory.CAPACITY
                if sched_out.admission
                in {
                    AdmissionOutcome.REJECTED_MEMORY,
                    AdmissionOutcome.REJECTED_QUEUE_FULL,
                    AdmissionOutcome.REJECTED_PROBE_UNAVAILABLE,
                    AdmissionOutcome.REJECTED_QUARANTINE,
                }
                else ErrorCategory.STALE_SCOPE
                if sched_out.admission == AdmissionOutcome.REJECTED_CANCELLED
                else ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message=f"M06 scheduler rejected synthesis ({sched_out.admission.value})",
            )
            return ChunkExecutionOutcome(
                chunk_id=chunk_plan.chunk_id,
                chunk_index=chunk_plan.chunk_index,
                execution_ok=False,
                structurally_valid=False,
                delivery_accepted=False,
                physical_completed=True,
                quarantined=sched_out.quarantined,
                cache_status=cache_status,
                quality_status=QualityStatus.UNKNOWN,
                job_ref=job_ref,
                duration_decision=decision,
                latent_descriptor=latent_desc,
                lease_state=sched_out.lease_state,
                error=err,
            )

        if prov_res is None or not prov_res.materialized or prov_res.raw_payload is None or prov_res.decoder_desc is None:
            return ChunkExecutionOutcome(
                chunk_id=chunk_plan.chunk_id,
                chunk_index=chunk_plan.chunk_index,
                execution_ok=False,
                structurally_valid=False,
                delivery_accepted=False,
                physical_completed=prov_res.physical_completed if prov_res else False,
                quarantined=sched_out.quarantined or (prov_res.quarantined if prov_res else False),
                cache_status=cache_status,
                quality_status=QualityStatus.UNKNOWN,
                job_ref=job_ref,
                duration_decision=decision,
                latent_descriptor=latent_desc,
                lease_state=sched_out.lease_state,
                error=(prov_res.error if prov_res and prov_res.error else ErrorInfo(
                    code="PROVIDER_DID_NOT_MATERIALIZE",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message="Provider did not materialize verified raw waveform",
                )),
            )

        # Stage 8: Raw 48kHz mono FLOAT32_LE structural validation (zero DSP)
        raw_val = self.raw_validator.validate(
            payload=prov_res.raw_payload,
            sample_count=prov_res.decoder_desc.sample_count,
            audio_format=RAW_AUDIO_FORMAT,
            estimate=estimate,
            collapse_guard_fn=collapse_guard_fn,
        )
        if not raw_val.structurally_valid:
            self.telemetry.inc_counter("f5.invalid_output_count")
            return ChunkExecutionOutcome(
                chunk_id=chunk_plan.chunk_id,
                chunk_index=chunk_plan.chunk_index,
                execution_ok=True,
                structurally_valid=False,
                delivery_accepted=False,
                physical_completed=prov_res.physical_completed,
                quarantined=sched_out.quarantined,
                cache_status=cache_status,
                quality_status=raw_val.quality_status,
                job_ref=job_ref,
                duration_decision=decision,
                latent_descriptor=latent_desc,
                decoder_descriptor=prov_res.decoder_desc,
                raw_validation=raw_val,
                lease_state=sched_out.lease_state,
                error=raw_val.error,
            )

        # Stage 9 & 10: Build immutable AudioChunk, atomic M02 delivery, safe M04 telemetry
        ode_ms = (prov_res.ode_ns / 1_000_000.0) if prov_res.ode_ns is not None else None
        decoder_ms = (prov_res.decode_ns / 1_000_000.0) if prov_res.decode_ns is not None else None
        inference_ms = self.telemetry.elapsed_ms(enqueue_ns, native_done_ns)
        actual_dur_ms = (prov_res.decoder_desc.sample_count * 1000.0) / 48000.0
        ttfa_ms = self.telemetry.elapsed_ms(request_accepted_ns, native_done_ns) if chunk_index == 0 else None

        pre_metrics = self.telemetry.record_chunk_metrics(
            generation_ref=plan.generation_ref,
            plan_id=plan.plan_id,
            plan_revision=plan.plan_revision,
            chunk_id=chunk_plan.chunk_id,
            chunk_index=chunk_plan.chunk_index,
            cache_status=cache_status,
            sample_count=prov_res.decoder_desc.sample_count,
            actual_duration_ms=actual_dur_ms,
            queue_wait_ms=0.0,
            encoder_ms=encoder_ms,
            duration_guard_ms=duration_guard_ms,
            ode_ms=ode_ms,
            decoder_ms=decoder_ms,
            inference_ms=inference_ms,
            dispatch_wait_ms=self.telemetry.elapsed_ms(native_done_ns, self.clock.monotonic_ns()),
            ttfa_ms=ttfa_ms,
            solver=solver_profile.solver_name,
            ode_steps=solver_profile.steps,
            voice_profile=snapshot.voice_profile.profile_id,
            model_revision=snapshot.model_descriptor.model_revision,
            trace_id=trace_id,
        )

        chunk = build_audio_chunk(
            plan=plan,
            chunk_plan=chunk_plan,
            snapshot=snapshot,
            solver_profile=solver_profile,
            sample_count=prov_res.decoder_desc.sample_count,
            payload=prov_res.raw_payload,
            cache_status=cache_status,
            quality_status=raw_val.quality_status,
            metrics=pre_metrics,
        )

        deliv = await self.delivery_fence.deliver(
            chunk,
            session_ctx=session_ctx,
            chunk_sink=chunk_sink,
            expected_plan_revision=plan.plan_revision,
            deadline=deadline,
            admit_media_to_session_queue=admit_media_to_session_queue,
        )
        if not deliv.accepted:
            self.telemetry.inc_counter("f5.stale_or_duplicate_count")

        return ChunkExecutionOutcome(
            chunk_id=chunk_plan.chunk_id,
            chunk_index=chunk_plan.chunk_index,
            execution_ok=True,
            structurally_valid=True,
            delivery_accepted=deliv.accepted,
            physical_completed=prov_res.physical_completed,
            quarantined=sched_out.quarantined,
            cache_status=cache_status,
            quality_status=raw_val.quality_status,
            audio_chunk=deliv.chunk,
            job_ref=job_ref,
            duration_decision=decision,
            latent_descriptor=latent_desc,
            decoder_descriptor=prov_res.decoder_desc,
            raw_validation=raw_val,
            delivery_outcome=deliv,
            lease_state=sched_out.lease_state,
            error=deliv.error,
            metrics=pre_metrics,
        )

    @staticmethod
    def _resolve_scope(
        plan: SynthesisPlan,
        session_ctx: SessionContext | None,
        cancellation_scope: CancellationScope | None,
    ) -> CancellationScope:
        if cancellation_scope is not None:
            return cancellation_scope
        if session_ctx is not None and session_ctx.tg.generation_scope is not None:
            return session_ctx.tg.generation_scope
        return CancellationScope(
            f"f5:{plan.generation_ref.session_id}:{plan.generation_ref.turn_id}:{plan.generation_ref.generation_id}",
        )

    @staticmethod
    def _fail_chunk(
        chunk_plan: Any,
        cache_status: CacheStatus,
        error: ErrorInfo | None,
        *,
        duration_decision: DurationDecision | None = None,
    ) -> ChunkExecutionOutcome:
        return ChunkExecutionOutcome(
            chunk_id=chunk_plan.chunk_id,
            chunk_index=chunk_plan.chunk_index,
            execution_ok=False,
            structurally_valid=False,
            delivery_accepted=False,
            physical_completed=True,
            quarantined=False,
            cache_status=cache_status,
            quality_status=QualityStatus.UNKNOWN,
            duration_decision=duration_decision,
            error=error,
        )

    @staticmethod
    def _failed_before_admission(plan: Any, error: ErrorInfo) -> SynthesisOutcome:
        dummy_adm = PlanAdmission(
            accepted=False,
            plan_id=getattr(plan, "plan_id", None) if isinstance(getattr(plan, "plan_id", None), str) else None,
            plan_revision=getattr(plan, "plan_revision", None) if type(getattr(plan, "plan_revision", None)) is int else None,
            generation_ref=getattr(plan, "generation_ref", None) if isinstance(getattr(plan, "generation_ref", None), GenerationRef) else None,
            response_id=getattr(plan, "response_id", None) if isinstance(getattr(plan, "response_id", None), str) else None,
            is_no_speech=False,
            reason_code=error.code,
            error=error,
        )
        return SynthesisOutcome(
            status="FAILED",
            plan_admission=dummy_adm,
            accepted_chunks=(),
            chunk_outcomes=(),
            execution_ok=False,
            structurally_valid=False,
            delivery_accepted=False,
            physical_completed=True,
            quarantined=False,
            quality_status=QualityStatus.UNKNOWN,
            error=error,
        )


__all__ = [
    "ChunkExecutionOutcome",
    "NeuralSynthesisPipeline",
    "SynthesisOutcome",
]
