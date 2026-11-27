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
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from backend.core.contracts.common import EventEnvelope
from backend.core.runtime.result_admission import AdmissionStatus
from backend.observability.event_catalog import EventPriority, priority_for_event


class DropPolicy(StrEnum):
    """Overflow handling policy for bounded subscriber queues."""

    DROP_NEWEST = "DROP_NEWEST"
    DROP_OLDEST = "DROP_OLDEST"


@dataclass(frozen=True, slots=True)
class BusStats:
    """Immutable snapshot of BoundedEventBus counters."""

    published_count: int
    accepted_count: int
    rejected_count: int
    dropped_count: int
    overflow_count: int
    per_priority_published: Mapping[str, int]
    per_priority_dropped: Mapping[str, int]
    subscriber_count: int
    subscriber_drops: Mapping[str, int]


class _PriorityLaneBuffer:
    """Bounded per-priority-lane FIFO container supporting priority isolation."""

    def __init__(self, lane_capacity: int, drop_policy: DropPolicy = DropPolicy.DROP_NEWEST) -> None:
        if type(lane_capacity) is not int or lane_capacity < 1:
            raise ValueError("lane_capacity must be positive int")
        self.lane_capacity = lane_capacity
        self.drop_policy = drop_policy
        self._lanes: dict[EventPriority, deque[EventEnvelope]] = {p: deque() for p in EventPriority}
        self.accepted_count = 0
        self.dropped_count = 0
        self.overflow_count = 0

    def push(self, event: EventEnvelope, priority: EventPriority) -> bool:
        lane = self._lanes[priority]
        if len(lane) >= self.lane_capacity:
            self.overflow_count += 1
            self.dropped_count += 1
            if self.drop_policy == DropPolicy.DROP_OLDEST:
                lane.popleft()
                lane.append(event)
                self.accepted_count += 1
                return True
            return False
        lane.append(event)
        self.accepted_count += 1
        return True

    def pop_next(self) -> EventEnvelope | None:
        for prio in EventPriority:
            lane = self._lanes[prio]
            if lane:
                return lane.popleft()
        return None

    def drain(self, limit: int | None = None) -> list[EventEnvelope]:
        items: list[EventEnvelope] = []
        for prio in EventPriority:
            lane = self._lanes[prio]
            while lane:
                if limit is not None and len(items) >= limit:
                    return items
                items.append(lane.popleft())
        return items

    def pending_count(self, priority: EventPriority | None = None) -> int:
        if priority is not None:
            return len(self._lanes[priority])
        return sum(len(lane) for lane in self._lanes.values())

    def clear(self) -> int:
        total = self.pending_count()
        for lane in self._lanes.values():
            lane.clear()
        return total


class Subscription:
    """Isolated bounded handle for a single subscriber on BoundedEventBus."""

    def __init__(
        self,
        subscriber_id: str,
        *,
        max_lane_size: int = 64,
        min_priority: EventPriority = EventPriority.LOW,
        event_types: frozenset[str] | None = None,
        drop_policy: DropPolicy = DropPolicy.DROP_NEWEST,
        callback: Callable[[EventEnvelope], None] | None = None,
    ) -> None:
        if not isinstance(subscriber_id, str) or not subscriber_id.strip():
            raise ValueError("subscriber_id must be non-empty")
        self.subscriber_id = subscriber_id
        self.min_priority = min_priority
        self.event_types = event_types
        self.callback = callback
        self._lock = threading.Lock()
        self._buffer = _PriorityLaneBuffer(max_lane_size, drop_policy=drop_policy)
        self._callback_errors = 0
        self._closed = False

    def matches(self, event_type: str, priority: EventPriority) -> bool:
        if priority > self.min_priority:
            return False
        if self.event_types is not None and event_type not in self.event_types:
            return False
        return True

    def _offer(self, event: EventEnvelope, priority: EventPriority) -> bool:
        with self._lock:
            if self._closed:
                return False
            return self._buffer.push(event, priority)

    def try_pop(self) -> EventEnvelope | None:
        with self._lock:
            return self._buffer.pop_next()

    def drain(self, limit: int | None = None) -> list[EventEnvelope]:
        with self._lock:
            return self._buffer.drain(limit=limit)

    def dispatch_pending(self, limit: int | None = None) -> int:
        """Deliver buffered events to this subscriber's callback with failure isolation."""
        if self.callback is None:
            return 0
        batch = self.drain(limit=limit)
        delivered = 0
        for env in batch:
            try:
                self.callback(env)
                delivered += 1
            except Exception:
                with self._lock:
                    self._callback_errors += 1
        return delivered

    @property
    def pending_count(self) -> int:
        with self._lock:
            return self._buffer.pending_count()

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._buffer.dropped_count

    @property
    def overflow_count(self) -> int:
        with self._lock:
            return self._buffer.overflow_count

    @property
    def callback_error_count(self) -> int:
        with self._lock:
            return self._callback_errors

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._buffer.clear()


class BoundedEventBus:
    """Non-blocking, priority-laned event bus with isolated bounded per-subscriber delivery."""

    def __init__(
        self,
        *,
        max_lane_size: int = 128,
        drop_policy: DropPolicy = DropPolicy.DROP_NEWEST,
    ) -> None:
        self._lock = threading.Lock()
        self._closed = False
        self._max_lane_size = max_lane_size
        self._drop_policy = drop_policy
        self._unclaimed = _PriorityLaneBuffer(max_lane_size, drop_policy=drop_policy)
        self._subscribers: dict[str, Subscription] = {}
        self._published_count = 0
        self._accepted_count = 0
        self._rejected_count = 0
        self._dropped_count = 0
        self._overflow_count = 0
        self._per_priority_published: dict[str, int] = {p.name: 0 for p in EventPriority}
        self._per_priority_dropped: dict[str, int] = {p.name: 0 for p in EventPriority}

    def subscribe(
        self,
        subscriber_id: str,
        *,
        max_lane_size: int | None = None,
        min_priority: EventPriority = EventPriority.LOW,
        event_types: Iterable[str] | None = None,
        drop_policy: DropPolicy | None = None,
        callback: Callable[[EventEnvelope], None] | None = None,
    ) -> Subscription:
        with self._lock:
            if self._closed:
                raise RuntimeError("Cannot subscribe to closed BoundedEventBus")
            if subscriber_id in self._subscribers:
                raise ValueError(f"Subscriber already registered: {subscriber_id}")
            sub = Subscription(
                subscriber_id,
                max_lane_size=max_lane_size or self._max_lane_size,
                min_priority=min_priority,
                event_types=frozenset(event_types) if event_types is not None else None,
                drop_policy=drop_policy or self._drop_policy,
                callback=callback,
            )
            self._subscribers[subscriber_id] = sub
            return sub

    def unsubscribe(self, subscriber_id: str) -> bool:
        with self._lock:
            sub = self._subscribers.pop(subscriber_id, None)
        if sub is None:
            return False
        sub.close()
        return True

    def try_publish(
        self,
        event: EventEnvelope,
        *,
        priority: EventPriority | None = None,
    ) -> AdmissionStatus:
        """Non-blocking admission of EventEnvelope into priority lanes without stalling producers."""
        if not isinstance(event, EventEnvelope):
            with self._lock:
                self._rejected_count += 1
            return AdmissionStatus.INVALID

        resolved_prio = priority if priority is not None else priority_for_event(event.event_type)
        if not isinstance(resolved_prio, EventPriority):
            with self._lock:
                self._rejected_count += 1
            return AdmissionStatus.INVALID

        with self._lock:
            if self._closed:
                self._rejected_count += 1
                return AdmissionStatus.CLOSED
            self._published_count += 1
            self._per_priority_published[resolved_prio.name] += 1
            subs = [s for s in self._subscribers.values() if s.matches(event.event_type, resolved_prio)]

            if not self._subscribers:
                ok = self._unclaimed.push(event, resolved_prio)
                if ok:
                    self._accepted_count += 1
                    return AdmissionStatus.ACCEPTED
                self._dropped_count += 1
                self._overflow_count += 1
                self._per_priority_dropped[resolved_prio.name] += 1
                return AdmissionStatus.BACKPRESSURE

        # Deliver outside bus lock across independent subscriber locks for strict isolation.
        if not subs:
            with self._lock:
                self._accepted_count += 1
            return AdmissionStatus.ACCEPTED

        delivered_any = False
        dropped_any = False
        for sub in subs:
            if sub._offer(event, resolved_prio):
                delivered_any = True
            else:
                dropped_any = True

        with self._lock:
            if dropped_any:
                self._overflow_count += 1
            if delivered_any:
                self._accepted_count += 1
                return AdmissionStatus.ACCEPTED
            self._dropped_count += 1
            self._per_priority_dropped[resolved_prio.name] += 1
            return AdmissionStatus.BACKPRESSURE

    def pop_next(self) -> EventEnvelope | None:
        """Pop the highest-priority buffered event when no subscribers were attached."""
        with self._lock:
            return self._unclaimed.pop_next()

    def dispatch_all(self, limit_per_subscriber: int | None = None) -> dict[str, int]:
        """Dispatch buffered events to registered callbacks with per-subscriber isolation."""
        with self._lock:
            subs = list(self._subscribers.values())
        return {sub.subscriber_id: sub.dispatch_pending(limit=limit_per_subscriber) for sub in subs}

    def close(self) -> None:
        with self._lock:
            self._closed = True
            subs = list(self._subscribers.values())
            self._subscribers.clear()
            self._unclaimed.clear()
        for sub in subs:
            sub.close()

    @property
    def stats(self) -> BusStats:
        with self._lock:
            sub_drops = {sid: sub.dropped_count for sid, sub in self._subscribers.items()}
            return BusStats(
                published_count=self._published_count,
                accepted_count=self._accepted_count,
                rejected_count=self._rejected_count,
                dropped_count=self._dropped_count,
                overflow_count=self._overflow_count,
                per_priority_published=MappingProxyType(dict(self._per_priority_published)),
                per_priority_dropped=MappingProxyType(dict(self._per_priority_dropped)),
                subscriber_count=len(self._subscribers),
                subscriber_drops=MappingProxyType(sub_drops),
            )
