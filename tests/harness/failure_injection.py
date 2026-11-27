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

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable


class FaultKind(StrEnum):
    INVALID_CONTRACT = "INVALID_CONTRACT"
    CANCEL_BEFORE_ADMISSION = "CANCEL_BEFORE_ADMISSION"
    CANCEL_AFTER_ENQUEUE = "CANCEL_AFTER_ENQUEUE"
    DUPLICATE_CALLBACK = "DUPLICATE_CALLBACK"
    OUT_OF_ORDER_EVENT = "OUT_OF_ORDER_EVENT"
    PARTIAL_ASR_UPDATE = "PARTIAL_ASR_UPDATE"
    MISSING_CAPABILITY = "MISSING_CAPABILITY"
    CORRUPT_MANIFEST = "CORRUPT_MANIFEST"
    QUEUE_SATURATION = "QUEUE_SATURATION"
    STALE_GPU_PROBE = "STALE_GPU_PROBE"
    OOM_MOCK = "OOM_MOCK"
    UNKNOWN_PROVIDER = "UNKNOWN_PROVIDER"
    DB_LOCKED = "DB_LOCKED"
    CRASH_AFTER_COMMIT_BEFORE_ACK = "CRASH_AFTER_COMMIT_BEFORE_ACK"
    AUDIT_SINK_FAILURE = "AUDIT_SINK_FAILURE"
    OBSERVER_FAILURE = "OBSERVER_FAILURE"
    TRANSPORT_DISCONNECT = "TRANSPORT_DISCONNECT"
    CLOCK_MISMATCH = "CLOCK_MISMATCH"


class InjectedFaultError(RuntimeError):
    """Test-only bounded exception raised by FailureInjector."""

    def __init__(self, fault_kind: FaultKind, boundary: str, phase: str) -> None:
        self.fault_kind = fault_kind
        self.boundary = boundary
        self.phase = phase
        super().__init__(f"Test-only injected fault {fault_kind.value} at {boundary}:{phase}")


@dataclass(frozen=True, slots=True)
class FaultTarget:
    boundary: str
    phase: str
    occurrence: int = 1
    scope: str = "TEST_ONLY"
    fault_kind: FaultKind = FaultKind.OBSERVER_FAILURE

    def __post_init__(self) -> None:
        if not self.boundary.strip() or not self.phase.strip():
            raise ValueError("boundary and phase required")
        if type(self.occurrence) is not int or self.occurrence < 1:
            raise ValueError("occurrence must be positive int")
        if self.scope != "TEST_ONLY":
            raise ValueError("FaultTarget.scope must be TEST_ONLY")


@dataclass
class FaultPlan:
    plan_id: str
    targets: tuple[FaultTarget, ...]
    production_reachable: bool = False

    def __post_init__(self) -> None:
        if self.production_reachable:
            raise ValueError("FaultPlan cannot be production_reachable")


class FailureInjector:
    """Test-only fault injector keyed by (boundary, phase, occurrence) with zero production reachability."""

    PRODUCTION_REACHABLE: bool = False

    def __init__(self, plan: FaultPlan | None = None) -> None:
        self.plan = plan
        self._counts: dict[tuple[str, str], int] = {}
        self.triggered: list[FaultTarget] = []

    def check_and_fire(
        self,
        boundary: str,
        phase: str,
        *,
        on_fault: Callable[[FaultTarget], None] | None = None,
    ) -> FaultTarget | None:
        if self.plan is None:
            return None
        key = (boundary, phase)
        occ = self._counts.get(key, 0) + 1
        self._counts[key] = occ
        for target in self.plan.targets:
            if target.boundary == boundary and target.phase == phase and target.occurrence == occ:
                self.triggered.append(target)
                if on_fault is not None:
                    on_fault(target)
                raise InjectedFaultError(target.fault_kind, boundary, phase)
        return None
