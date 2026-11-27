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
from dataclasses import dataclass
from typing import Any, Callable

from backend.core.runtime import Clock, SystemMonotonicClock
from backend.runtime_resources.admission import AdmissionController, AdmissionDecision
from backend.runtime_resources.contracts import (
    AdmissionOutcome,
    ExecutionLease,
    ExecutionLeaseState,
    PriorityClass,
    ProviderKind,
    ResourceRequest,
)
from backend.runtime_resources.memory_budget import MemoryBudget
from backend.runtime_resources.priority_queue import AgingPolicy, BoundedFairPriorityQueue, EnqueueResult
from backend.runtime_resources.provider_adapters import AdapterExecutionReport, ProviderAdapter
from backend.runtime_resources.quarantine import QuarantineExhaustedError, QuarantineManager
from backend.runtime_resources.residency import ResidencyManager, ResidencyPin


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    request_id: str
    admission: AdmissionOutcome
    lease_id: str | None = None
    lease_state: ExecutionLeaseState | None = None
    delivered: tuple[Any, ...] = ()
    fenced_outputs: int = 0
    quarantined: bool = False
    error: str | None = None


class UnifiedGpuScheduler:
    """
    Unified GPU resource scheduler coordinating:
    - P0..P7 bounded-fair priority queueing (with P5 latest-only supersession)
    - Deadline enforcement and CancellationScope checks via M02 primitives
    - Conservative byte-accurate MemoryBudget admission & reservations
    - Single-flight ResidencyManager model loading & pinning
    - ExecutionLease cooperative output fencing & bounded Quarantine reclaim
    - Provider adapters (CTranslate2, Ollama, PyTorch)
    """

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        memory_budget: MemoryBudget | None = None,
        quarantine_manager: QuarantineManager | None = None,
        residency_manager: ResidencyManager | None = None,
        max_queue_items: int = 128,
        aging_policy: AgingPolicy | None = None,
    ) -> None:
        self.clock: Clock = clock or SystemMonotonicClock()
        self.memory_budget = memory_budget or MemoryBudget(clock=self.clock)
        self.quarantine_manager = quarantine_manager or QuarantineManager(clock=self.clock)
        self.residency_manager = residency_manager or ResidencyManager(memory_budget=self.memory_budget)
        self.queue = BoundedFairPriorityQueue(
            clock=self.clock,
            max_items=max_queue_items,
            aging_policy=aging_policy,
        )
        self.admission = AdmissionController(
            clock=self.clock,
            memory_budget=self.memory_budget,
            quarantine_manager=self.quarantine_manager,
            residency_manager=self.residency_manager,
        )
        self._adapters: dict[ProviderKind, ProviderAdapter] = {}
        self._leases: dict[str, ExecutionLease] = {}
        self._reclaim_tasks: dict[str, asyncio.Task[None]] = {}
        self._lease_seq = 0

    def register_adapter(self, provider: ProviderKind, adapter: ProviderAdapter) -> None:
        self._adapters[provider] = adapter

    def get_lease(self, lease_id: str) -> ExecutionLease | None:
        return self._leases.get(lease_id)

    def submit(
        self,
        request: ResourceRequest,
        *,
        require_immediate_budget: bool = True,
        on_evicted: Callable[[AdmissionOutcome], None] | None = None,
    ) -> EnqueueResult | AdmissionDecision:
        """
        Evaluate admission and enqueue a request if admitted.

        When `require_immediate_budget=True` (default), memory/probe/quarantine
        rejections fail immediately; when `False`, requests that only fail current
        free-VRAM capacity (while probe is valid) may wait in the priority queue.
        """
        decision = self.admission.evaluate(request)
        if not decision.admitted:
            if not require_immediate_budget and decision.outcome == AdmissionOutcome.REJECTED_MEMORY:
                return self.queue.enqueue(request, on_evicted=on_evicted)
            return decision
        return self.queue.enqueue(request, on_evicted=on_evicted)

    async def dispatch_next(
        self,
        *,
        on_output: Callable[[Any], None] | None = None,
    ) -> ExecutionOutcome | None:
        item = self.queue.pop_next()
        if item is None:
            return None
        return await self.run_request(item.request, on_output=on_output)

    async def run_request(
        self,
        request: ResourceRequest,
        *,
        on_output: Callable[[Any], None] | None = None,
    ) -> ExecutionOutcome:
        decision = self.admission.evaluate(request)
        if not decision.admitted:
            return ExecutionOutcome(
                request_id=request.request_id,
                admission=decision.outcome,
                error=decision.reason,
            )

        if request.provider == ProviderKind.CONTROL and request.priority == PriorityClass.P0:
            request.cancellation_scope.check_active()
            return ExecutionOutcome(
                request_id=request.request_id,
                admission=AdmissionOutcome.ADMITTED,
                lease_state=ExecutionLeaseState.RELEASED,
            )

        adapter = self._adapters.get(request.provider)
        if adapter is None:
            return ExecutionOutcome(
                request_id=request.request_id,
                admission=AdmissionOutcome.REJECTED_INVALID,
                error=f"no_adapter_for_{request.provider.value}",
            )

        pin: ResidencyPin | None = None
        res_id: str | None = None
        lease: ExecutionLease | None = None
        try:
            pin = await self.residency_manager.acquire_pin(request.model_id)
            self._lease_seq += 1
            lease_id = f"lease:{self._lease_seq}:{request.request_id}"
            if request.estimated_vram_bytes > 0:
                res_id = f"exec:{lease_id}"
                check, _ = self.memory_budget.try_reserve(
                    res_id,
                    request.estimated_vram_bytes,
                    kind="execution",
                )
                if not check.admitted:
                    pin.release()
                    return ExecutionOutcome(
                        request_id=request.request_id,
                        admission=AdmissionOutcome.REJECTED_MEMORY,
                        error=check.reason,
                    )
                self.memory_budget.mark_allocated(res_id)

            lease = ExecutionLease(
                lease_id=lease_id,
                request_id=request.request_id,
                model_id=request.model_id,
                provider=request.provider,
                priority=request.priority,
                reserved_bytes=request.estimated_vram_bytes,
                cancellation_scope=request.cancellation_scope,
                acquired_at_ns=self.clock.monotonic_ns(),
                deadline=request.deadline,
                memory_reservation_id=res_id,
            )
            if res_id is not None:
                rid = res_id
                lease.add_release_hook(lambda: self.memory_budget.release(rid))
            active_pin = pin
            lease.add_release_hook(active_pin.release)
            self._leases[lease_id] = lease

            lease.mark_in_flight()
            report: AdapterExecutionReport = await adapter.execute(
                lease,
                request,
                on_output=on_output,
            )

            if report.physical_completed:
                lease.release_physical()
                return ExecutionOutcome(
                    request_id=request.request_id,
                    admission=AdmissionOutcome.ADMITTED,
                    lease_id=lease.lease_id,
                    lease_state=lease.state,
                    delivered=report.delivered,
                    fenced_outputs=report.fenced_count,
                    quarantined=False,
                )

            # Provider did not physically finish within drain grace -> move to bounded Quarantine.
            try:
                self.quarantine_manager.quarantine(lease, reason="provider_drain_timeout")
            except QuarantineExhaustedError as exc:
                self._schedule_reclaim(adapter, lease, reclaim_quarantine=False)
                return ExecutionOutcome(
                    request_id=request.request_id,
                    admission=AdmissionOutcome.REJECTED_QUARANTINE,
                    lease_id=lease.lease_id,
                    lease_state=lease.state,
                    delivered=report.delivered,
                    fenced_outputs=report.fenced_count,
                    quarantined=False,
                    error=str(exc),
                )

            self._schedule_reclaim(adapter, lease, reclaim_quarantine=True)
            return ExecutionOutcome(
                request_id=request.request_id,
                admission=AdmissionOutcome.ADMITTED,
                lease_id=lease.lease_id,
                lease_state=lease.state,
                delivered=report.delivered,
                fenced_outputs=report.fenced_count,
                quarantined=True,
            )
        except Exception as exc:
            if lease is not None:
                lease.release_physical(failed=True)
            else:
                if res_id is not None:
                    self.memory_budget.release(res_id)
                if pin is not None:
                    pin.release()
            return ExecutionOutcome(
                request_id=request.request_id,
                admission=AdmissionOutcome.REJECTED_INVALID,
                lease_id=lease.lease_id if lease is not None else None,
                lease_state=lease.state if lease is not None else None,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _schedule_reclaim(
        self,
        adapter: ProviderAdapter,
        lease: ExecutionLease,
        *,
        reclaim_quarantine: bool,
    ) -> None:
        async def _wait_and_reclaim() -> None:
            failed = False
            try:
                await adapter.await_physical_completion(lease)
            except Exception:
                failed = True
            finally:
                if reclaim_quarantine:
                    self.quarantine_manager.reclaim(lease.lease_id, failed=failed)
                else:
                    lease.release_physical(failed=failed)
                self._reclaim_tasks.pop(lease.lease_id, None)

        self._reclaim_tasks[lease.lease_id] = asyncio.create_task(_wait_and_reclaim())

    async def wait_reclaims(self) -> None:
        tasks = list(self._reclaim_tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
