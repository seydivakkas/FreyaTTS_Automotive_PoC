"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from backend.core.contracts.common import GenerationRef


class AdmissionStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    STALE_SESSION = "STALE_SESSION"
    STALE_TURN = "STALE_TURN"
    STALE_GENERATION = "STALE_GENERATION"
    CANCELED = "CANCELED"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    BACKPRESSURE = "BACKPRESSURE"
    INVALID = "INVALID"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"


@dataclass(frozen=True, slots=True)
class QueuedMediaItem:
    generation_ref: GenerationRef
    sequence: int
    payload: bytes
    plan_revision: int = 0
    is_control: bool = False


class BoundedMediaQueue:
    """Bounded FIFO media queue with separate control lane and selective purge."""

    def __init__(self, max_items: int = 64, max_bytes: int = 256 * 1024) -> None:
        if max_items < 1 or max_bytes < 1:
            raise ValueError("Queue caps must be positive")
        self.max_items = max_items
        self.max_bytes = max_bytes
        self._media: deque[QueuedMediaItem] = deque()
        self._control: deque[QueuedMediaItem] = deque()
        self._bytes_used: int = 0
        self._seen_keys: set[tuple[int, int, int]] = set()

    @property
    def item_count(self) -> int:
        return len(self._media)

    @property
    def bytes_used(self) -> int:
        return self._bytes_used

    def can_reserve(self, size_bytes: int, *, is_control: bool = False) -> bool:
        if is_control:
            return True
        return len(self._media) < self.max_items and (self._bytes_used + size_bytes) <= self.max_bytes

    def enqueue(self, item: QueuedMediaItem) -> AdmissionStatus:
        key = (item.generation_ref.turn_id, item.generation_ref.generation_id, item.sequence)
        if key in self._seen_keys:
            return AdmissionStatus.DUPLICATE
        if item.is_control:
            self._control.append(item)
            self._seen_keys.add(key)
            return AdmissionStatus.ACCEPTED
        size = len(item.payload)
        if not self.can_reserve(size):
            return AdmissionStatus.BACKPRESSURE
        self._media.append(item)
        self._bytes_used += size
        self._seen_keys.add(key)
        return AdmissionStatus.ACCEPTED

    def pop_next(self) -> QueuedMediaItem | None:
        if self._control:
            return self._control.popleft()
        if self._media:
            item = self._media.popleft()
            self._bytes_used -= len(item.payload)
            return item
        return None

    def purge_generation(self, generation_id: int) -> int:
        kept: deque[QueuedMediaItem] = deque()
        removed = 0
        new_bytes = 0
        for item in self._media:
            if item.generation_ref.generation_id == generation_id:
                removed += 1
            else:
                kept.append(item)
                new_bytes += len(item.payload)
        self._media = kept
        self._bytes_used = new_bytes
        return removed

    def clear_all(self) -> int:
        count = len(self._media) + len(self._control)
        self._media.clear()
        self._control.clear()
        self._bytes_used = 0
        return count
