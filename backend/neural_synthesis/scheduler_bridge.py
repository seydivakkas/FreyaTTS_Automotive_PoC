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

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from backend.core.contracts.common import ErrorCategory, ErrorInfo, GenerationRef, Retryability, TurnRef
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.deadlines import Clock, DeadlineBudget
from backend.neural_synthesis.decoder_adapter import DecoderAdapter, DecoderOutputDescriptor, DecoderValidationError
from backend.neural_synthesis.duration_estimator import DurationEstimate
from backend.neural_synthesis.duration_guard import DurationDecision
from backend.neural_synthesis.encoder_adapter import EncodedCondition
from backend.neural_synthesis.latent_initializer import LatentDescriptor
from backend.neural_synthesis.model_adapter import SynthesisModelHandles
from backend.neural_synthesis.solver_adapter import SolverAdapter, SolverExecutionError, SolverProfile
from backend.runtime_resources.contracts import (
    AdmissionOutcome,
    ExecutionLease,
    ExecutionLeaseState,
    PriorityClass,
    ProviderKind,
    ResourceRequest,
)
from backend.runtime_resources.provider_adapters import AdapterExecutionReport
from backend.runtime_resources.scheduler import ExecutionOutcome, UnifiedGpuScheduler


class UncertainDeviceStateError(RuntimeError):
    """Raised when a native GPU/provider failure leaves device completion state uncertain."""

    uncertain_device_state: bool = True


@dataclass(frozen=True, slots=True)
class SynthesisJobRef:
    """Scoped M06 synthesis job reference for one chunk attempt."""

    request_id: str
    attempt: int
    generation_ref: GenerationRef
    plan_id: str
    plan_revision: int
    chunk_id: str
    chunk_index: int
    priority: PriorityClass
    estimated_vram_bytes: int
    lease_id: str | None = None


@dataclass(slots=True)
class ProviderBarriers:
    """Optional deterministic async barriers for testing interleavings without sleeps."""

    after_ode: Callable[[], Awaitable[None]] | None = None
    after_decode: Callable[[], Awaitable[None]] | None = None
    before_materialize: Callable[[], Awaitable[None]] | None = None
    await_physical_drain: Callable[[ExecutionLease], Awaitable[None]] | None = None


@dataclass(slots=True)
class ProviderExecutionPayload:
    """Execution payload carried inside M06 ResourceRequest.payload."""

    job_ref: SynthesisJobRef
    handles: SynthesisModelHandles
    encoded: EncodedCondition
    estimate: DurationEstimate
    decision: DurationDecision
    latent: Any
    latent_desc: LatentDescriptor
    solver_profile: SolverProfile
    solver_adapter: SolverAdapter
    decoder_adapter: DecoderAdapter
    strict: bool = True
    allow_baseline_frame_trim: bool = True
    barriers: ProviderBarriers | None = None


@dataclass(frozen=True, slots=True)
class ProviderExecutionResult:
    """Distinguished outcome of native execution, materialization, and physical completion."""

    request_id: str
    lease_id: str | None
    lease_state: ExecutionLeaseState | None
    physical_completed: bool
    materialized: bool
    cancelled: bool
    quarantined: bool
    uncertain_device_state: bool
    decoder_desc: DecoderOutputDescriptor | None = None
    raw_payload: bytes | None = None
    nfe_evaluated: int = 0
    ode_ns: int | None = None
    decode_ns: int | None = None
    materialize_ns: int | None = None
    error: ErrorInfo | None = None


class FreyaSynthesisProviderAdapter:
    """
    M06 ProviderAdapter coordinating DiT Euler32 ODE -> AudioVAE decode -> CPU materialization.

    Guarantees:
    - Lease remains held across ODE, VAE decode, and CPU materialization.
    - Cancellation immediately fences delivery via ExecutionLease while retaining physical lease.
    - Duplicate completion callbacks execute idempotently with at most one release/delivery.
    - Uncertain device-state failures move the lease into M06 Quarantine instead of early release.
    """

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._results: dict[str, ProviderExecutionResult] = {}
        self._inflight_tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_drains: dict[str, ProviderBarriers] = {}
        self._completion_callbacks_seen: dict[str, int] = {}
        self._lock = threading.Lock()

    def get_result(self, request_id: str) -> ProviderExecutionResult | None:
        with self._lock:
            return self._results.get(request_id)

    def completion_callback_count(self, request_id: str) -> int:
        with self._lock:
            return self._completion_callbacks_seen.get(request_id, 0)

    def notify_completion_callback(self, lease: ExecutionLease, request_id: str) -> bool:
        """Idempotent completion callback handler; returns True only on first callback."""
        with self._lock:
            count = self._completion_callbacks_seen.get(request_id, 0) + 1
            self._completion_callbacks_seen[request_id] = count
            if count > 1:
                return False
        if lease.holds_physical_resources and lease.state != ExecutionLeaseState.QUARANTINED:
            return lease.release_physical()
        return False

    async def execute(
        self,
        lease: ExecutionLease,
        request: ResourceRequest,
        *,
        on_output: Callable[[Any], None] | None = None,
    ) -> AdapterExecutionReport:
        payload = request.payload
        if not isinstance(payload, ProviderExecutionPayload):
            raise TypeError("ResourceRequest.payload must be ProviderExecutionPayload")

        if lease.is_output_fenced:
            self._store_result(
                ProviderExecutionResult(
                    request_id=request.request_id,
                    lease_id=lease.lease_id,
                    lease_state=lease.state,
                    physical_completed=True,
                    materialized=False,
                    cancelled=True,
                    quarantined=False,
                    uncertain_device_state=False,
                    error=ErrorInfo(
                        code="CANCELLED_BEFORE_DISPATCH",
                        category=ErrorCategory.STALE_SCOPE,
                        retryable=Retryability.NO,
                        safe_message="Execution lease fenced prior to native dispatch",
                    ),
                )
            )
            return AdapterExecutionReport(
                delivered=(),
                fenced_count=lease.fenced_outputs,
                physical_completed=True,
                cancelled=True,
            )

        delivered: list[Any] = []
        sink = on_output if on_output is not None else delivered.append
        barriers = payload.barriers
        state: dict[str, Any] = {
            "decoder_desc": None,
            "raw_payload": None,
            "nfe": 0,
            "ode_ns": None,
            "decode_ns": None,
            "materialize_ns": None,
            "error": None,
            "uncertain": False,
        }

        async def _run_native() -> None:
            try:
                t0 = self._clock.monotonic_ns()
                ode_res = payload.solver_adapter.solve(
                    tts_model=payload.handles.tts_model,
                    latent=payload.latent,
                    latent_desc=payload.latent_desc,
                    encoded=payload.encoded,
                    profile=payload.solver_profile,
                    strict=payload.strict,
                )
                state["nfe"] = ode_res.nfe_evaluated
                state["ode_ns"] = max(0, self._clock.monotonic_ns() - t0)

                if barriers and barriers.after_ode is not None:
                    await barriers.after_ode()

                if lease.is_output_fenced:
                    lease.fenced_outputs += 1
                    return

                t1 = self._clock.monotonic_ns()
                raw_decode_out = payload.decoder_adapter._invoke_decode(payload.handles.vae, ode_res.latents)
                state["decode_ns"] = max(0, self._clock.monotonic_ns() - t1)

                if barriers and barriers.after_decode is not None:
                    await barriers.after_decode()

                if lease.is_output_fenced:
                    lease.fenced_outputs += 1
                    return

                if barriers and barriers.before_materialize is not None:
                    await barriers.before_materialize()

                t2 = self._clock.monotonic_ns()
                meta_rate = getattr(
                    payload.handles.vae,
                    "sample_rate_hz",
                    getattr(payload.handles.vae, "sample_rate", payload.handles.sample_rate_hz),
                )
                if isinstance(raw_decode_out, dict):
                    actual_rate = raw_decode_out.get("sample_rate_hz", meta_rate)
                    wave = raw_decode_out["waveform"]
                else:
                    actual_rate = meta_rate
                    wave = raw_decode_out

                desc, raw_bytes = payload.decoder_adapter.materialize_raw_waveform(
                    waveform=wave,
                    sample_rate_hz=actual_rate,
                    estimate=payload.estimate,
                    allow_baseline_frame_trim=payload.allow_baseline_frame_trim,
                )
                state["materialize_ns"] = max(0, self._clock.monotonic_ns() - t2)
                state["decoder_desc"] = desc
                state["raw_payload"] = raw_bytes

                # Check fence immediately before logical delivery
                lease.try_deliver_output(sink, (desc, raw_bytes))
            except (SolverExecutionError, DecoderValidationError) as exc:
                state["error"] = exc.error_info
                if getattr(exc, "uncertain_device_state", False):
                    state["uncertain"] = True
            except Exception as exc:
                uncertain = bool(getattr(exc, "uncertain_device_state", False)) or isinstance(
                    exc, UncertainDeviceStateError
                )
                state["uncertain"] = uncertain
                state["error"] = ErrorInfo(
                    code="UNCERTAIN_DEVICE_STATE" if uncertain else "PROVIDER_EXECUTION_ERROR",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO if uncertain else Retryability.UNKNOWN,
                    safe_message=f"Provider execution failed ({type(exc).__name__})",
                )

        task = asyncio.create_task(_run_native())
        self._inflight_tasks[lease.lease_id] = task
        cancel_wait = asyncio.create_task(lease.cancellation_scope.wait_cancelled())
        try:
            done, _ = await asyncio.wait({task, cancel_wait}, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                await task
                self._inflight_tasks.pop(lease.lease_id, None)
                if state["uncertain"]:
                    if barriers is not None:
                        self._pending_drains[lease.lease_id] = barriers
                    self._store_result(
                        ProviderExecutionResult(
                            request_id=request.request_id,
                            lease_id=lease.lease_id,
                            lease_state=ExecutionLeaseState.QUARANTINED,
                            physical_completed=False,
                            materialized=False,
                            cancelled=lease.cancellation_scope.is_cancel_requested,
                            quarantined=True,
                            uncertain_device_state=True,
                            nfe_evaluated=state["nfe"],
                            ode_ns=state["ode_ns"],
                            decode_ns=state["decode_ns"],
                            materialize_ns=state["materialize_ns"],
                            error=state["error"],
                        )
                    )
                    return AdapterExecutionReport(
                        delivered=(),
                        fenced_count=lease.fenced_outputs,
                        physical_completed=False,
                        cancelled=lease.cancellation_scope.is_cancel_requested,
                    )

                with self._lock:
                    self._completion_callbacks_seen[request.request_id] = max(
                        1, self._completion_callbacks_seen.get(request.request_id, 0)
                    )
                self._store_result(
                    ProviderExecutionResult(
                        request_id=request.request_id,
                        lease_id=lease.lease_id,
                        lease_state=lease.state,
                        physical_completed=True,
                        materialized=state["raw_payload"] is not None,
                        cancelled=lease.cancellation_scope.is_cancel_requested,
                        quarantined=False,
                        uncertain_device_state=False,
                        decoder_desc=state["decoder_desc"],
                        raw_payload=state["raw_payload"],
                        nfe_evaluated=state["nfe"],
                        ode_ns=state["ode_ns"],
                        decode_ns=state["decode_ns"],
                        materialize_ns=state["materialize_ns"],
                        error=state["error"],
                    )
                )
                return AdapterExecutionReport(
                    delivered=tuple(delivered),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=True,
                    cancelled=lease.cancellation_scope.is_cancel_requested,
                )

            # Cancelled while ODE / VAE decode / materialization still executing
            grace_sec = request.drain_grace_ms / 1000.0
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=grace_sec)
                self._inflight_tasks.pop(lease.lease_id, None)
                lease.fenced_outputs += 1
                self._store_result(
                    ProviderExecutionResult(
                        request_id=request.request_id,
                        lease_id=lease.lease_id,
                        lease_state=lease.state,
                        physical_completed=True,
                        materialized=False,
                        cancelled=True,
                        quarantined=False,
                        uncertain_device_state=state["uncertain"],
                        nfe_evaluated=state["nfe"],
                        ode_ns=state["ode_ns"],
                        decode_ns=state["decode_ns"],
                        materialize_ns=state["materialize_ns"],
                        error=state["error"]
                        or ErrorInfo(
                            code="CANCELLED_DURING_EXECUTION",
                            category=ErrorCategory.STALE_SCOPE,
                            retryable=Retryability.NO,
                            safe_message="Synthesis cancelled during native execution",
                        ),
                    )
                )
                return AdapterExecutionReport(
                    delivered=(),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=True,
                    cancelled=True,
                )
            except asyncio.TimeoutError:
                lease.fenced_outputs += 1
                if barriers is not None:
                    self._pending_drains[lease.lease_id] = barriers
                self._store_result(
                    ProviderExecutionResult(
                        request_id=request.request_id,
                        lease_id=lease.lease_id,
                        lease_state=ExecutionLeaseState.QUARANTINED,
                        physical_completed=False,
                        materialized=False,
                        cancelled=True,
                        quarantined=True,
                        uncertain_device_state=True,
                        error=ErrorInfo(
                            code="CANCELLED_LEASE_QUARANTINED",
                            category=ErrorCategory.STALE_SCOPE,
                            retryable=Retryability.NO,
                            safe_message="Native execution did not drain within grace; lease quarantined",
                        ),
                    )
                )
                return AdapterExecutionReport(
                    delivered=(),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=False,
                    cancelled=True,
                )
        finally:
            cancel_wait.cancel()

    async def await_physical_completion(self, lease: ExecutionLease) -> None:
        task = self._inflight_tasks.pop(lease.lease_id, None)
        if task is not None:
            await task
        barriers = self._pending_drains.pop(lease.lease_id, None)
        if barriers is not None and barriers.await_physical_drain is not None:
            await barriers.await_physical_drain(lease)

    def _store_result(self, result: ProviderExecutionResult) -> None:
        with self._lock:
            self._results[result.request_id] = result


class SchedulerBridge:
    """
    Coordinates F5-A chunk synthesis through M06 UnifiedGpuScheduler.

    - Priority P2 for first required speech chunk, P4 for subsequent chunks.
    - Enforces at most `max_in_flight_per_generation` (default 1) outstanding strict chunk.
    - Never adds a second scheduler or independent retry loop.
    """

    def __init__(
        self,
        scheduler: UnifiedGpuScheduler,
        *,
        max_in_flight_per_generation: int = 1,
        default_drain_grace_ms: int = 50,
    ) -> None:
        if type(max_in_flight_per_generation) is not int or max_in_flight_per_generation < 1:
            raise ValueError("max_in_flight_per_generation must be >= 1")
        self.scheduler = scheduler
        self.max_in_flight_per_generation = max_in_flight_per_generation
        self.default_drain_grace_ms = default_drain_grace_ms
        self.adapter = FreyaSynthesisProviderAdapter(scheduler.clock)
        self.scheduler.register_adapter(ProviderKind.PYTORCH, self.adapter)
        self._in_flight_by_gen: dict[tuple[str, int, int], int] = {}
        self._attempt_seq: dict[str, int] = {}
        self._lock = threading.Lock()

    @staticmethod
    def priority_for_chunk(chunk_index: int, *, is_first_speech_chunk: bool | None = None) -> PriorityClass:
        first = (chunk_index == 0) if is_first_speech_chunk is None else is_first_speech_chunk
        return PriorityClass.P2 if first else PriorityClass.P4

    def in_flight_count(self, generation_ref: GenerationRef) -> int:
        key = (generation_ref.session_id, generation_ref.turn_id, generation_ref.generation_id)
        with self._lock:
            return self._in_flight_by_gen.get(key, 0)

    def build_request(
        self,
        *,
        generation_ref: GenerationRef,
        plan_id: str,
        plan_revision: int,
        chunk_id: str,
        chunk_index: int,
        handles: SynthesisModelHandles,
        encoded: EncodedCondition,
        estimate: DurationEstimate,
        decision: DurationDecision,
        latent: Any,
        latent_desc: LatentDescriptor,
        solver_profile: SolverProfile,
        solver_adapter: SolverAdapter,
        decoder_adapter: DecoderAdapter,
        cancellation_scope: CancellationScope,
        deadline: DeadlineBudget | None = None,
        is_first_speech_chunk: bool | None = None,
        strict: bool = True,
        allow_baseline_frame_trim: bool = True,
        barriers: ProviderBarriers | None = None,
        drain_grace_ms: int | None = None,
    ) -> tuple[SynthesisJobRef, ResourceRequest]:
        base_id = f"{generation_ref.session_id}.{generation_ref.turn_id}.{generation_ref.generation_id}.{plan_id}.{plan_revision}.{chunk_id}"
        with self._lock:
            attempt = self._attempt_seq.get(base_id, 0) + 1
            self._attempt_seq[base_id] = attempt
        safe_req_id = f"f5.{plan_id}.{plan_revision}.{chunk_id}.a{attempt}"[:128]
        prio = self.priority_for_chunk(chunk_index, is_first_speech_chunk=is_first_speech_chunk)
        job_ref = SynthesisJobRef(
            request_id=safe_req_id,
            attempt=attempt,
            generation_ref=generation_ref,
            plan_id=plan_id,
            plan_revision=plan_revision,
            chunk_id=chunk_id,
            chunk_index=chunk_index,
            priority=prio,
            estimated_vram_bytes=decision.estimated_vram_bytes,
        )
        payload = ProviderExecutionPayload(
            job_ref=job_ref,
            handles=handles,
            encoded=encoded,
            estimate=estimate,
            decision=decision,
            latent=latent,
            latent_desc=latent_desc,
            solver_profile=solver_profile,
            solver_adapter=solver_adapter,
            decoder_adapter=decoder_adapter,
            strict=strict,
            allow_baseline_frame_trim=allow_baseline_frame_trim,
            barriers=barriers,
        )
        req = ResourceRequest(
            request_id=safe_req_id,
            priority=prio,
            provider=ProviderKind.PYTORCH,
            model_id=handles.model_id,
            estimated_vram_bytes=decision.estimated_vram_bytes,
            cancellation_scope=cancellation_scope,
            session_id=generation_ref.session_id,
            turn_ref=TurnRef(generation_ref.session_id, generation_ref.turn_id),
            generation_ref=generation_ref,
            deadline=deadline,
            drain_grace_ms=self.default_drain_grace_ms if drain_grace_ms is None else drain_grace_ms,
            payload=payload,
        )
        return job_ref, req

    async def dispatch_and_execute(
        self,
        job_ref: SynthesisJobRef,
        request: ResourceRequest,
    ) -> tuple[ExecutionOutcome, ProviderExecutionResult | None]:
        gen_key = (
            job_ref.generation_ref.session_id,
            job_ref.generation_ref.turn_id,
            job_ref.generation_ref.generation_id,
        )
        with self._lock:
            cur = self._in_flight_by_gen.get(gen_key, 0)
            if cur >= self.max_in_flight_per_generation:
                return (
                    ExecutionOutcome(
                        request_id=request.request_id,
                        admission=AdmissionOutcome.REJECTED_QUEUE_FULL,
                        error="max_in_flight_per_generation_exceeded",
                    ),
                    None,
                )
            self._in_flight_by_gen[gen_key] = cur + 1

        try:
            outcome = await self.scheduler.run_request(request)
            result = self.adapter.get_result(request.request_id)
            return outcome, result
        finally:
            with self._lock:
                rem = self._in_flight_by_gen.get(gen_key, 1) - 1
                if rem <= 0:
                    self._in_flight_by_gen.pop(gen_key, None)
                else:
                    self._in_flight_by_gen[gen_key] = rem


__all__ = [
    "FreyaSynthesisProviderAdapter",
    "ProviderBarriers",
    "ProviderExecutionPayload",
    "ProviderExecutionResult",
    "SchedulerBridge",
    "SynthesisJobRef",
    "UncertainDeviceStateError",
]
