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

from backend.core.runtime import Clock
from backend.runtime_resources.contracts import (
    AdmissionOutcome,
    HandleOwnership,
    ProviderKind,
    ResidencyState,
    ResourceRequest,
)
from backend.runtime_resources.memory_budget import BudgetCheckResult, MemoryBudget, ProbeStatus
from backend.runtime_resources.quarantine import QuarantineManager
from backend.runtime_resources.residency import ResidencyManager


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    outcome: AdmissionOutcome
    reason: str
    execution_vram_bytes: int
    model_load_vram_bytes: int
    total_required_bytes: int
    budget_check: BudgetCheckResult | None = None

    @property
    def admitted(self) -> bool:
        return self.outcome == AdmissionOutcome.ADMITTED


class AdmissionController:
    """
    Fail-closed GPU resource admission gate combining:
    - CancellationScope state
    - DeadlineBudget clock-domain and expiry validation
    - Bounded Quarantine capacity check
    - ResidencyManager model availability & load VRAM estimation
    - Conservative MemoryBudget check
    """

    def __init__(
        self,
        *,
        clock: Clock,
        memory_budget: MemoryBudget,
        quarantine_manager: QuarantineManager,
        residency_manager: ResidencyManager | None = None,
    ) -> None:
        self._clock = clock
        self._memory_budget = memory_budget
        self._quarantine = quarantine_manager
        self._residency = residency_manager

    def evaluate(self, request: ResourceRequest) -> AdmissionDecision:
        if request.cancellation_scope.is_cancel_requested:
            return AdmissionDecision(
                outcome=AdmissionOutcome.REJECTED_CANCELLED,
                reason="cancellation_scope_cancelled",
                execution_vram_bytes=request.estimated_vram_bytes,
                model_load_vram_bytes=0,
                total_required_bytes=request.estimated_vram_bytes,
            )

        if request.deadline is not None:
            if request.deadline.clock_domain != self._clock.clock_domain:
                return AdmissionDecision(
                    outcome=AdmissionOutcome.REJECTED_INVALID,
                    reason="clock_domain_mismatch",
                    execution_vram_bytes=request.estimated_vram_bytes,
                    model_load_vram_bytes=0,
                    total_required_bytes=request.estimated_vram_bytes,
                )
            if request.deadline.is_expired(self._clock):
                return AdmissionDecision(
                    outcome=AdmissionOutcome.REJECTED_DEADLINE,
                    reason="deadline_expired",
                    execution_vram_bytes=request.estimated_vram_bytes,
                    model_load_vram_bytes=0,
                    total_required_bytes=request.estimated_vram_bytes,
                )

        # Control-plane P0 interruptions with 0 VRAM do not get blocked by GPU quarantine or VRAM.
        if request.provider == ProviderKind.CONTROL and request.estimated_vram_bytes == 0:
            return AdmissionDecision(
                outcome=AdmissionOutcome.ADMITTED,
                reason="control_bypass",
                execution_vram_bytes=0,
                model_load_vram_bytes=0,
                total_required_bytes=0,
            )

        if self._quarantine.is_exhausted:
            return AdmissionDecision(
                outcome=AdmissionOutcome.REJECTED_QUARANTINE,
                reason="quarantine_budget_exhausted",
                execution_vram_bytes=request.estimated_vram_bytes,
                model_load_vram_bytes=0,
                total_required_bytes=request.estimated_vram_bytes,
            )

        model_load_bytes = 0
        if self._residency is not None:
            handle = self._residency.get_handle(request.model_id)
            if handle is None:
                return AdmissionDecision(
                    outcome=AdmissionOutcome.REJECTED_MODEL_UNAVAILABLE,
                    reason="model_not_registered",
                    execution_vram_bytes=request.estimated_vram_bytes,
                    model_load_vram_bytes=0,
                    total_required_bytes=request.estimated_vram_bytes,
                )
            if (
                handle.state == ResidencyState.UNLOADED
                and handle.spec.ownership != HandleOwnership.BORROWED
            ):
                model_load_bytes = handle.spec.vram_bytes

        total_bytes = request.estimated_vram_bytes + model_load_bytes
        check = self._memory_budget.check_admission(total_bytes)
        if not check.admitted:
            outcome = (
                AdmissionOutcome.REJECTED_PROBE_UNAVAILABLE
                if check.probe_status != ProbeStatus.VALID
                else AdmissionOutcome.REJECTED_MEMORY
            )
            return AdmissionDecision(
                outcome=outcome,
                reason=check.reason,
                execution_vram_bytes=request.estimated_vram_bytes,
                model_load_vram_bytes=model_load_bytes,
                total_required_bytes=total_bytes,
                budget_check=check,
            )

        return AdmissionDecision(
            outcome=AdmissionOutcome.ADMITTED,
            reason="ok",
            execution_vram_bytes=request.estimated_vram_bytes,
            model_load_vram_bytes=model_load_bytes,
            total_required_bytes=total_bytes,
            budget_check=check,
        )
