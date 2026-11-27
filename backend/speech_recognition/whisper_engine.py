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
import inspect
from dataclasses import dataclass
from typing import Any, Callable

from backend.core.contracts.recognition import ASROutcome
from backend.core.runtime.deadlines import Clock
from backend.runtime_resources.contracts import (
    AdmissionOutcome,
    ExecutionLease,
    ExecutionLeaseState,
    ProviderKind,
    ResourceRequest,
)
from backend.runtime_resources.provider_adapters import AdapterExecutionReport
from backend.runtime_resources.scheduler import ExecutionOutcome, UnifiedGpuScheduler
from backend.speech_recognition.errors import ASRDispatchStatus
from backend.speech_recognition.request_builder import ASRJobPayload
from backend.speech_recognition.transcript_collector import (
    CollectedTranscript,
    CollectorLimits,
    collect_whisper_segments,
)


@dataclass(frozen=True, slots=True)
class WhisperExecutionResult:
    """Terminal result of running a final ASR request through M06 UnifiedGpuScheduler."""

    request_id: str
    dispatch_status: ASRDispatchStatus
    admission_outcome: AdmissionOutcome
    asr_outcome: ASROutcome
    collected: CollectedTranscript | None
    lease_id: str | None = None
    lease_state: ExecutionLeaseState | None = None
    quarantined: bool = False
    started_monotonic_ns: int | None = None
    completed_monotonic_ns: int | None = None
    error_code: str | None = None
    error_message: str | None = None


def _is_oom_exception(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return "outofmemory" in name or "cuda out of memory" in msg or "oom" in msg


class _WhisperProviderAdapter:
    """
    M06 ProviderAdapter wrapping an existing Whisper/CTranslate2 handle without
    creating a new loader, new model instance, or separate global lock.
    """

    def __init__(
        self,
        *,
        model_getter: Callable[[], Any],
        clock: Clock,
        limits: CollectorLimits,
        on_terminal_report: Callable[[str, WhisperExecutionResult], None] | None = None,
    ) -> None:
        self._model_getter = model_getter
        self._clock = clock
        self._limits = limits
        self._on_terminal_report = on_terminal_report
        self._inflight_tasks: dict[str, asyncio.Task[None]] = {}
        self._results_by_request: dict[str, WhisperExecutionResult] = {}
        self._completed_requests: set[str] = set()

    def pop_result(self, request_id: str) -> WhisperExecutionResult | None:
        return self._results_by_request.pop(request_id, None)

    def record_terminal_once(self, request_id: str, result: WhisperExecutionResult) -> bool:
        """Duplicate callback guard: preserves first terminal completion state."""
        if request_id in self._completed_requests:
            return False
        self._completed_requests.add(request_id)
        self._results_by_request[request_id] = result
        if self._on_terminal_report is not None:
            self._on_terminal_report(request_id, result)
        return True

    async def execute(
        self,
        lease: ExecutionLease,
        request: ResourceRequest,
        *,
        on_output: Callable[[Any], None] | None = None,
    ) -> AdapterExecutionReport:
        job = request.payload
        if not isinstance(job, ASRJobPayload):
            res = WhisperExecutionResult(
                request_id=request.request_id,
                dispatch_status=ASRDispatchStatus.REJECTED,
                admission_outcome=AdmissionOutcome.REJECTED_INVALID,
                asr_outcome=ASROutcome.ERROR,
                collected=None,
                lease_id=lease.lease_id,
                lease_state=lease.state,
                error_code="ASR_INVALID_JOB_PAYLOAD",
                error_message="ResourceRequest payload is not ASRJobPayload",
            )
            self.record_terminal_once(request.request_id, res)
            return AdapterExecutionReport(delivered=(), fenced_count=0, physical_completed=True, cancelled=False)

        if lease.is_output_fenced:
            res = WhisperExecutionResult(
                request_id=request.request_id,
                dispatch_status=ASRDispatchStatus.CANCELED,
                admission_outcome=AdmissionOutcome.ADMITTED,
                asr_outcome=ASROutcome.UNKNOWN,
                collected=None,
                lease_id=lease.lease_id,
                lease_state=lease.state,
                error_code="ASR_CANCELED_BEFORE_START",
                error_message="Scope canceled before native transcribe start",
            )
            self.record_terminal_once(request.request_id, res)
            return AdapterExecutionReport(
                delivered=(),
                fenced_count=lease.fenced_outputs,
                physical_completed=True,
                cancelled=True,
            )

        audio_handle = job.utterance_input.audio
        audio_handle.acquire_native_borrow()
        started_ns = self._clock.monotonic_ns()
        delivered_segments: list[Any] = []
        collected_holder: list[CollectedTranscript] = []
        provider_error_holder: list[tuple[str, str, bool]] = []

        async def _run_native() -> None:
            try:
                model = self._model_getter()
                if model is None:
                    provider_error_holder.append(("ASR_MODEL_NOT_LOADED", "STT model handle is None", False))
                    return
                kwargs = job.pinned_config.decode_profile.to_transcribe_kwargs(job.hotwords.hotwords_text)
                if job.word_timestamps:
                    kwargs["word_timestamps"] = True

                raw_out = model.transcribe(audio_handle.samples_view(), **kwargs)
                if inspect.isawaitable(raw_out):
                    raw_out = await raw_out

                if isinstance(raw_out, tuple) and len(raw_out) == 2:
                    segments_iter, info = raw_out
                else:
                    segments_iter, info = raw_out, None

                collected = await collect_whisper_segments(
                    segments_iter,
                    info=info,
                    decode_profile=job.pinned_config.decode_profile,
                    limits=self._limits,
                    utterance_duration_sec=audio_handle.duration_sec,
                    lease=lease,
                    cancellation_scope=request.cancellation_scope,
                    deadline=request.deadline,
                    clock=self._clock,
                )
                collected_holder.append(collected)
                if on_output is not None and not lease.is_output_fenced:
                    for seg in collected.segments:
                        if not lease.try_deliver_output(on_output, seg):
                            break
                        delivered_segments.append(seg)
            except BaseException as exc:
                if _is_oom_exception(exc):
                    provider_error_holder.append(("ASR_PROVIDER_OOM", "Native provider OOM", False))
                else:
                    provider_error_holder.append(("ASR_PROVIDER_EXECUTION_ERROR", f"Provider error: {type(exc).__name__}", False))
            finally:
                audio_handle.release_native_borrow()

        task = asyncio.create_task(_run_native())
        self._inflight_tasks[lease.lease_id] = task
        cancel_wait = asyncio.create_task(lease.cancellation_scope.wait_cancelled())
        try:
            done, _ = await asyncio.wait({task, cancel_wait}, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                await task
                self._inflight_tasks.pop(lease.lease_id, None)
                completed_ns = self._clock.monotonic_ns()
                self._finalize_execution(
                    request=request,
                    lease=lease,
                    started_ns=started_ns,
                    completed_ns=completed_ns,
                    collected_holder=collected_holder,
                    provider_error_holder=provider_error_holder,
                    physical_completed=True,
                )
                return AdapterExecutionReport(
                    delivered=tuple(delivered_segments),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=True,
                    cancelled=lease.cancellation_scope.is_cancel_requested,
                )

            grace = request.drain_grace_ms / 1000.0
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=grace)
                self._inflight_tasks.pop(lease.lease_id, None)
                completed_ns = self._clock.monotonic_ns()
                self._finalize_execution(
                    request=request,
                    lease=lease,
                    started_ns=started_ns,
                    completed_ns=completed_ns,
                    collected_holder=collected_holder,
                    provider_error_holder=provider_error_holder,
                    physical_completed=True,
                )
                return AdapterExecutionReport(
                    delivered=tuple(delivered_segments),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=True,
                    cancelled=True,
                )
            except asyncio.TimeoutError:
                # Native work still running; lease moves to M06 Quarantine and input stays borrowed!
                self.record_terminal_once(
                    request.request_id,
                    WhisperExecutionResult(
                        request_id=request.request_id,
                        dispatch_status=ASRDispatchStatus.UNKNOWN,
                        admission_outcome=AdmissionOutcome.ADMITTED,
                        asr_outcome=ASROutcome.UNKNOWN,
                        collected=None,
                        lease_id=lease.lease_id,
                        lease_state=ExecutionLeaseState.QUARANTINED,
                        quarantined=True,
                        started_monotonic_ns=started_ns,
                        completed_monotonic_ns=None,
                        error_code="ASR_PROVIDER_COMPLETION_UNCERTAIN",
                        error_message="Provider did not complete within drain grace; lease quarantined",
                    ),
                )
                return AdapterExecutionReport(
                    delivered=tuple(delivered_segments),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=False,
                    cancelled=True,
                )
        finally:
            cancel_wait.cancel()

    def _finalize_execution(
        self,
        *,
        request: ResourceRequest,
        lease: ExecutionLease,
        started_ns: int,
        completed_ns: int,
        collected_holder: list[CollectedTranscript],
        provider_error_holder: list[tuple[str, str, bool]],
        physical_completed: bool,
    ) -> None:
        if provider_error_holder:
            code, msg, _ = provider_error_holder[0]
            self.record_terminal_once(
                request.request_id,
                WhisperExecutionResult(
                    request_id=request.request_id,
                    dispatch_status=ASRDispatchStatus.UNKNOWN if not physical_completed else ASRDispatchStatus.COMPLETED,
                    admission_outcome=AdmissionOutcome.ADMITTED,
                    asr_outcome=ASROutcome.ERROR,
                    collected=None,
                    lease_id=lease.lease_id,
                    lease_state=lease.state,
                    quarantined=not physical_completed,
                    started_monotonic_ns=started_ns,
                    completed_monotonic_ns=completed_ns,
                    error_code=code,
                    error_message=msg,
                ),
            )
            return

        collected = collected_holder[0] if collected_holder else None
        if collected is None or not collected.terminal_verified:
            if collected is not None and collected.cancelled:
                outcome = ASROutcome.UNKNOWN
                code = "ASR_CANCELED_IN_FLIGHT"
                msg = "Recognition canceled during segment iteration"
            else:
                outcome = ASROutcome.ERROR if (collected and collected.error_code) else ASROutcome.UNKNOWN
                code = (collected.error_code if collected and collected.error_code else "ASR_COMPLETION_UNVERIFIED")
                msg = (collected.error_message if collected and collected.error_message else "Provider terminal state unverified")
            self.record_terminal_once(
                request.request_id,
                WhisperExecutionResult(
                    request_id=request.request_id,
                    dispatch_status=ASRDispatchStatus.CANCELED if (collected and collected.cancelled) else ASRDispatchStatus.COMPLETED,
                    admission_outcome=AdmissionOutcome.ADMITTED,
                    asr_outcome=outcome,
                    collected=collected,
                    lease_id=lease.lease_id,
                    lease_state=lease.state,
                    started_monotonic_ns=started_ns,
                    completed_monotonic_ns=completed_ns,
                    error_code=code,
                    error_message=msg,
                ),
            )
            return

        has_valid_speech = bool(collected.legacy_filtered_transcript.strip())
        asr_outcome = ASROutcome.OK if has_valid_speech else ASROutcome.NO_SPEECH
        self.record_terminal_once(
            request.request_id,
            WhisperExecutionResult(
                request_id=request.request_id,
                dispatch_status=ASRDispatchStatus.COMPLETED,
                admission_outcome=AdmissionOutcome.ADMITTED,
                asr_outcome=asr_outcome,
                collected=collected,
                lease_id=lease.lease_id,
                lease_state=lease.state,
                started_monotonic_ns=started_ns,
                completed_monotonic_ns=completed_ns,
            ),
        )

    async def await_physical_completion(self, lease: ExecutionLease) -> None:
        task = self._inflight_tasks.pop(lease.lease_id, None)
        if task is not None:
            await task


class WhisperSchedulerEngine:
    """
    Canonical F2-A execution facade routing every strict ASR job through M06
    `UnifiedGpuScheduler` (`ProviderKind.CTRANSLATE2`).
    """

    def __init__(
        self,
        scheduler: UnifiedGpuScheduler,
        *,
        model_getter: Callable[[], Any],
        limits: CollectorLimits | None = None,
        register_adapter: bool = True,
    ) -> None:
        self._scheduler = scheduler
        self._adapter = _WhisperProviderAdapter(
            model_getter=model_getter,
            clock=scheduler.clock,
            limits=limits or CollectorLimits(),
        )
        if register_adapter:
            self._scheduler.register_adapter(ProviderKind.CTRANSLATE2, self._adapter)

    @property
    def scheduler(self) -> UnifiedGpuScheduler:
        return self._scheduler

    def submit_to_queue(self, request: ResourceRequest, *, require_immediate_budget: bool = True) -> ASRDispatchStatus:
        """Evaluate M06 admission & enqueue P1 ASR request; never invokes provider directly."""
        res = self._scheduler.submit(request, require_immediate_budget=require_immediate_budget)
        outcome = getattr(res, "outcome", None)
        if outcome is not None:
            return self._map_rejection_status(outcome)
        return ASRDispatchStatus.QUEUED

    async def run_admitted(
        self,
        request: ResourceRequest,
        *,
        on_segment: Callable[[Any], None] | None = None,
    ) -> WhisperExecutionResult:
        """Execute a P1 ASR request through M06 `UnifiedGpuScheduler.run_request`."""
        outcome: ExecutionOutcome = await self._scheduler.run_request(request, on_output=on_segment)
        return self._to_execution_result(request.request_id, outcome)

    async def dispatch_next(
        self,
        *,
        on_segment: Callable[[Any], None] | None = None,
    ) -> WhisperExecutionResult | None:
        """Pop and run the next highest-priority queued request via M06 scheduler."""
        outcome = await self._scheduler.dispatch_next(on_output=on_segment)
        if outcome is None:
            return None
        return self._to_execution_result(outcome.request_id, outcome)

    def record_external_completion(self, request_id: str, result: WhisperExecutionResult) -> bool:
        """Expose idempotent terminal completion gate for callback-based integrations."""
        return self._adapter.record_terminal_once(request_id, result)

    def _to_execution_result(self, request_id: str, outcome: ExecutionOutcome) -> WhisperExecutionResult:
        recorded = self._adapter.pop_result(request_id)
        if recorded is not None:
            return WhisperExecutionResult(
                request_id=recorded.request_id,
                dispatch_status=recorded.dispatch_status,
                admission_outcome=outcome.admission,
                asr_outcome=recorded.asr_outcome,
                collected=recorded.collected,
                lease_id=outcome.lease_id,
                lease_state=outcome.lease_state,
                quarantined=outcome.quarantined,
                started_monotonic_ns=recorded.started_monotonic_ns,
                completed_monotonic_ns=recorded.completed_monotonic_ns,
                error_code=recorded.error_code,
                error_message=recorded.error_message,
            )

        status = self._map_rejection_status(outcome.admission)
        asr_out = ASROutcome.UNKNOWN if status == ASRDispatchStatus.CANCELED else ASROutcome.REJECTED
        return WhisperExecutionResult(
            request_id=request_id,
            dispatch_status=status,
            admission_outcome=outcome.admission,
            asr_outcome=asr_out,
            collected=None,
            lease_id=outcome.lease_id,
            lease_state=outcome.lease_state,
            quarantined=outcome.quarantined,
            error_code=f"ASR_SCHEDULER_{outcome.admission.value}",
            error_message=outcome.error or f"M06 scheduler admission outcome: {outcome.admission.value}",
        )

    @staticmethod
    def _map_rejection_status(admission: AdmissionOutcome) -> ASRDispatchStatus:
        if admission == AdmissionOutcome.ADMITTED:
            return ASRDispatchStatus.ADMITTED
        if admission == AdmissionOutcome.QUEUED:
            return ASRDispatchStatus.QUEUED
        if admission == AdmissionOutcome.REJECTED_DEADLINE:
            return ASRDispatchStatus.EXPIRED
        if admission == AdmissionOutcome.REJECTED_CANCELLED:
            return ASRDispatchStatus.CANCELED
        if admission in {
            AdmissionOutcome.REJECTED_MODEL_UNAVAILABLE,
            AdmissionOutcome.REJECTED_PROBE_UNAVAILABLE,
            AdmissionOutcome.REJECTED_QUARANTINE,
        }:
            return ASRDispatchStatus.UNAVAILABLE
        return ASRDispatchStatus.REJECTED
