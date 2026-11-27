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
from enum import IntEnum, StrEnum
from typing import Any

from backend.core.contracts import GenerationRef, TurnRef
from backend.core.contracts.validation import require_safe_id, require_strict_int
from backend.core.runtime import CancellationScope, DeadlineBudget, StaleScopeError

MIB = 1_048_576  # 1 MiB = 1024 * 1024 bytes


class PriorityClass(IntEnum):
    """Scheduling priority classes P0 (highest) through P7 (lowest)."""

    P0 = 0  # Interruption / barge-in control
    P1 = 1  # Final ASR
    P2 = 2  # First TTS chunk
    P3 = 3  # LLM generation
    P4 = 4  # Later TTS chunks
    P5 = 5  # Partial ASR (superseded latest-only)
    P6 = 6  # Prewarm
    P7 = 7  # Lab / benchmarks


PRIORITY_LABELS: dict[PriorityClass, str] = {
    PriorityClass.P0: "interruption",
    PriorityClass.P1: "final_asr",
    PriorityClass.P2: "first_tts_chunk",
    PriorityClass.P3: "llm",
    PriorityClass.P4: "later_tts_chunks",
    PriorityClass.P5: "partial_asr_latest_only",
    PriorityClass.P6: "prewarm",
    PriorityClass.P7: "lab_benchmarks",
}


class ProviderKind(StrEnum):
    CTRANSLATE2 = "CTRANSLATE2"
    OLLAMA = "OLLAMA"
    PYTORCH = "PYTORCH"
    CONTROL = "CONTROL"


class HandleOwnership(StrEnum):
    OWNED = "OWNED"
    BORROWED = "BORROWED"
    EXTERNAL = "EXTERNAL"


class ResidencyState(StrEnum):
    UNLOADED = "UNLOADED"
    LOADING = "LOADING"
    READY = "READY"
    DRAINING = "DRAINING"


class ExecutionLeaseState(StrEnum):
    ACQUIRED = "ACQUIRED"
    IN_FLIGHT = "IN_FLIGHT"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    COMPLETED = "COMPLETED"
    QUARANTINED = "QUARANTINED"
    RELEASED = "RELEASED"
    FAILED = "FAILED"


class AdmissionOutcome(StrEnum):
    ADMITTED = "ADMITTED"
    QUEUED = "QUEUED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED_DEADLINE = "REJECTED_DEADLINE"
    REJECTED_CANCELLED = "REJECTED_CANCELLED"
    REJECTED_MEMORY = "REJECTED_MEMORY"
    REJECTED_PROBE_UNAVAILABLE = "REJECTED_PROBE_UNAVAILABLE"
    REJECTED_QUARANTINE = "REJECTED_QUARANTINE"
    REJECTED_QUEUE_FULL = "REJECTED_QUEUE_FULL"
    REJECTED_MODEL_UNAVAILABLE = "REJECTED_MODEL_UNAVAILABLE"
    REJECTED_INVALID = "REJECTED_INVALID"


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    """Immutable descriptor of a scheduled GPU/provider work item."""

    request_id: str
    priority: PriorityClass
    provider: ProviderKind
    model_id: str
    estimated_vram_bytes: int
    cancellation_scope: CancellationScope
    session_id: str | None = None
    turn_ref: TurnRef | None = None
    generation_ref: GenerationRef | None = None
    deadline: DeadlineBudget | None = None
    supersession_key: str | None = None
    drain_grace_ms: int = 50
    payload: Any = None

    def __post_init__(self) -> None:
        require_safe_id(self.request_id, "request_id")
        if not isinstance(self.priority, PriorityClass):
            object.__setattr__(self, "priority", PriorityClass(self.priority))
        if not isinstance(self.provider, ProviderKind):
            object.__setattr__(self, "provider", ProviderKind(self.provider))
        require_safe_id(self.model_id, "model_id")
        require_strict_int(self.estimated_vram_bytes, "estimated_vram_bytes", minimum=0)
        if not isinstance(self.cancellation_scope, CancellationScope):
            raise TypeError("cancellation_scope must be CancellationScope")
        if self.session_id is not None:
            require_safe_id(self.session_id, "session_id")
        if self.deadline is not None and not isinstance(self.deadline, DeadlineBudget):
            raise TypeError("deadline must be DeadlineBudget or None")
        require_strict_int(self.drain_grace_ms, "drain_grace_ms", minimum=0)

    @property
    def effective_supersession_key(self) -> str | None:
        if self.supersession_key is not None:
            return self.supersession_key
        if self.priority == PriorityClass.P5:
            scope = self.session_id or self.cancellation_scope.scope_id
            return f"{scope}:P5"
        return None


@dataclass(slots=True)
class ExecutionLease:
    """
    Tracks physical GPU execution ownership separately from cooperative output cancellation.

    Cooperative cancellation via `cancellation_scope` immediately fences output delivery,
    while the physical lease (and its VRAM reservation / residency pin) stays held until
    the provider completes or the lease moves to bounded Quarantine.
    """

    lease_id: str
    request_id: str
    model_id: str
    provider: ProviderKind
    priority: PriorityClass
    reserved_bytes: int
    cancellation_scope: CancellationScope
    acquired_at_ns: int
    deadline: DeadlineBudget | None = None
    memory_reservation_id: str | None = None
    state: ExecutionLeaseState = ExecutionLeaseState.ACQUIRED
    fenced_outputs: int = 0
    delivered_outputs: int = 0
    quarantine_reason: str | None = None
    _on_physical_release: list[Any] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        require_safe_id(self.lease_id, "lease_id")
        require_safe_id(self.request_id, "request_id")
        require_safe_id(self.model_id, "model_id")
        require_strict_int(self.reserved_bytes, "reserved_bytes", minimum=0)
        require_strict_int(self.acquired_at_ns, "acquired_at_ns", minimum=0)

    @property
    def is_output_fenced(self) -> bool:
        if self.cancellation_scope.is_cancel_requested:
            if self.state == ExecutionLeaseState.IN_FLIGHT:
                self.state = ExecutionLeaseState.CANCEL_REQUESTED
            return True
        return self.state in {
            ExecutionLeaseState.CANCEL_REQUESTED,
            ExecutionLeaseState.QUARANTINED,
            ExecutionLeaseState.RELEASED,
            ExecutionLeaseState.FAILED,
        }

    @property
    def holds_physical_resources(self) -> bool:
        return self.state in {
            ExecutionLeaseState.ACQUIRED,
            ExecutionLeaseState.IN_FLIGHT,
            ExecutionLeaseState.CANCEL_REQUESTED,
            ExecutionLeaseState.QUARANTINED,
        }

    def mark_in_flight(self) -> None:
        if self.state in {ExecutionLeaseState.RELEASED, ExecutionLeaseState.FAILED, ExecutionLeaseState.QUARANTINED}:
            raise RuntimeError(f"Cannot mark lease {self.lease_id} in-flight from {self.state}")
        if self.cancellation_scope.is_cancel_requested:
            self.state = ExecutionLeaseState.CANCEL_REQUESTED
            return
        self.state = ExecutionLeaseState.IN_FLIGHT

    def request_cancel(self, reason: str = "lease_cancelled") -> bool:
        changed = self.cancellation_scope.request_cancel(reason)
        if self.state in {ExecutionLeaseState.ACQUIRED, ExecutionLeaseState.IN_FLIGHT}:
            self.state = ExecutionLeaseState.CANCEL_REQUESTED
        return changed

    def assert_output_allowed(self) -> None:
        if self.cancellation_scope.is_cancel_requested:
            self.fenced_outputs += 1
            if self.state == ExecutionLeaseState.IN_FLIGHT:
                self.state = ExecutionLeaseState.CANCEL_REQUESTED
            self.cancellation_scope.check_active()
        if self.is_output_fenced:
            self.fenced_outputs += 1
            raise StaleScopeError(f"Lease {self.lease_id} output fenced in state {self.state}")

    def try_deliver_output(self, sink: Any, item: Any) -> bool:
        """Deliver `item` to `sink` only if not fenced by cancellation or lease state."""
        if self.is_output_fenced:
            self.fenced_outputs += 1
            return False
        sink(item)
        self.delivered_outputs += 1
        return True

    def add_release_hook(self, fn: Any) -> None:
        self._on_physical_release.append(fn)

    def release_physical(self, *, failed: bool = False) -> bool:
        if self.state in {ExecutionLeaseState.RELEASED, ExecutionLeaseState.FAILED}:
            return False
        hooks = list(self._on_physical_release)
        self._on_physical_release.clear()
        for fn in hooks:
            fn()
        self.state = ExecutionLeaseState.FAILED if failed else ExecutionLeaseState.RELEASED
        return True
