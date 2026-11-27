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
from typing import Callable, Mapping

from backend.core.contracts.validation import require_strict_int
from backend.core.runtime import Clock
from backend.runtime_resources.contracts import AdmissionOutcome, PriorityClass, ResourceRequest


@dataclass(frozen=True, slots=True)
class AgingPolicy:
    """
    Bounded aging fairness configuration.

    P0 (interruption) always retains effective rank 0 and can never be overtaken.
    P1..P7 gain up to `max_boost_levels` priority steps over time, bounded below by
    `min_effective_rank` (default 1) and optional per-class floor overrides.
    """

    aging_quantum_ms: int = 50
    max_boost_levels: int = 6
    min_effective_rank: int = 1
    class_floors: Mapping[PriorityClass, int] | None = None

    def __post_init__(self) -> None:
        require_strict_int(self.aging_quantum_ms, "aging_quantum_ms", minimum=1)
        require_strict_int(self.max_boost_levels, "max_boost_levels", minimum=0, maximum=7)
        require_strict_int(self.min_effective_rank, "min_effective_rank", minimum=1, maximum=7)

    def effective_rank(self, priority: PriorityClass, waited_ns: int) -> int:
        if priority == PriorityClass.P0:
            return 0
        quantum_ns = self.aging_quantum_ms * 1_000_000
        steps = max(0, waited_ns) // quantum_ns
        boost = min(self.max_boost_levels, steps)
        floor = self.min_effective_rank
        if self.class_floors is not None and priority in self.class_floors:
            floor = max(1, min(int(priority), int(self.class_floors[priority])))
        return max(floor, int(priority) - boost)


@dataclass(slots=True)
class QueuedWorkItem:
    request: ResourceRequest
    enqueued_at_ns: int
    sequence: int
    on_evicted: Callable[[AdmissionOutcome], None] | None = None


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    outcome: AdmissionOutcome
    superseded_request_ids: tuple[str, ...] = ()


class BoundedFairPriorityQueue:
    """
    Bounded P0..P7 priority queue with:
    - Bounded aging fairness using M02 Clock
    - Deadline enforcement via M02 DeadlineBudget
    - Cooperative cancellation filtering via M02 CancellationScope
    - Latest-only supersession for P5 partial ASR (or any latest-only supersession key)
    """

    def __init__(
        self,
        *,
        clock: Clock,
        max_items: int = 128,
        aging_policy: AgingPolicy | None = None,
    ) -> None:
        require_strict_int(max_items, "max_items", minimum=1)
        self._clock = clock
        self.max_items = max_items
        self.aging_policy = aging_policy or AgingPolicy()
        self._items: list[QueuedWorkItem] = []
        self._seq: int = 0
        self.superseded_count: int = 0
        self.expired_count: int = 0
        self.cancelled_count: int = 0

    def __len__(self) -> int:
        return len(self._items)

    def _is_deadline_expired(self, req: ResourceRequest) -> bool:
        if req.deadline is None:
            return False
        return req.deadline.is_expired(self._clock)

    def _validate_deadline_domain(self, req: ResourceRequest) -> bool:
        if req.deadline is None:
            return True
        return req.deadline.clock_domain == self._clock.clock_domain

    def enqueue(
        self,
        request: ResourceRequest,
        *,
        on_evicted: Callable[[AdmissionOutcome], None] | None = None,
    ) -> EnqueueResult:
        if request.cancellation_scope.is_cancel_requested:
            self.cancelled_count += 1
            return EnqueueResult(AdmissionOutcome.REJECTED_CANCELLED)
        if not self._validate_deadline_domain(request):
            return EnqueueResult(AdmissionOutcome.REJECTED_INVALID)
        if self._is_deadline_expired(request):
            self.expired_count += 1
            return EnqueueResult(AdmissionOutcome.REJECTED_DEADLINE)

        superseded_ids: list[str] = []
        skey = request.effective_supersession_key
        if skey is not None:
            kept: list[QueuedWorkItem] = []
            for existing in self._items:
                if (
                    existing.request.priority == request.priority
                    and existing.request.effective_supersession_key == skey
                ):
                    superseded_ids.append(existing.request.request_id)
                    self.superseded_count += 1
                    if existing.on_evicted is not None:
                        existing.on_evicted(AdmissionOutcome.SUPERSEDED)
                else:
                    kept.append(existing)
            self._items = kept

        self.prune_inactive()
        if len(self._items) >= self.max_items:
            return EnqueueResult(
                AdmissionOutcome.REJECTED_QUEUE_FULL,
                superseded_request_ids=tuple(superseded_ids),
            )

        self._seq += 1
        self._items.append(
            QueuedWorkItem(
                request=request,
                enqueued_at_ns=self._clock.monotonic_ns(),
                sequence=self._seq,
                on_evicted=on_evicted,
            )
        )
        return EnqueueResult(
            AdmissionOutcome.QUEUED,
            superseded_request_ids=tuple(superseded_ids),
        )

    def prune_inactive(self) -> int:
        """Evict cancelled or deadline-expired queued items."""
        kept: list[QueuedWorkItem] = []
        removed = 0
        for item in self._items:
            if item.request.cancellation_scope.is_cancel_requested:
                self.cancelled_count += 1
                removed += 1
                if item.on_evicted is not None:
                    item.on_evicted(AdmissionOutcome.REJECTED_CANCELLED)
                continue
            if self._is_deadline_expired(item.request):
                self.expired_count += 1
                removed += 1
                if item.on_evicted is not None:
                    item.on_evicted(AdmissionOutcome.REJECTED_DEADLINE)
                continue
            kept.append(item)
        self._items = kept
        return removed

    def _sort_key(self, item: QueuedWorkItem, now_ns: int) -> tuple[int, int, int]:
        waited_ns = max(0, now_ns - item.enqueued_at_ns)
        eff_rank = self.aging_policy.effective_rank(item.request.priority, waited_ns)
        return (eff_rank, item.enqueued_at_ns, item.sequence)

    def peek_next(self) -> QueuedWorkItem | None:
        self.prune_inactive()
        if not self._items:
            return None
        now_ns = self._clock.monotonic_ns()
        return min(self._items, key=lambda item: self._sort_key(item, now_ns))

    def pop_next(self) -> QueuedWorkItem | None:
        self.prune_inactive()
        if not self._items:
            return None
        now_ns = self._clock.monotonic_ns()
        best_idx = 0
        best_key = self._sort_key(self._items[0], now_ns)
        for idx in range(1, len(self._items)):
            k = self._sort_key(self._items[idx], now_ns)
            if k < best_key:
                best_key = k
                best_idx = idx
        return self._items.pop(best_idx)

    def effective_rank_of(self, request_id: str) -> int | None:
        now_ns = self._clock.monotonic_ns()
        for item in self._items:
            if item.request.request_id == request_id:
                return self.aging_policy.effective_rank(
                    item.request.priority,
                    max(0, now_ns - item.enqueued_at_ns),
                )
        return None
