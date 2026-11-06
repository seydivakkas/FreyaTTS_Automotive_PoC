"""Text-only queue for M05. Consumers MUST revalidate generation at emission time."""
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass
from automotive_voice.core.session import State
from automotive_voice.core.session_manager import SessionManager
from .contracts import ClausePlan, TTSInput

@dataclass(frozen=True, slots=True)
class QueueReceipt:
    accepted: bool
    reason: str
    count: int

class MockTTS:
    """No waveforms, sockets, audio codecs, or synthesis imports.

    Uses per-instance bounded storage. A stale item may be queued when interruption
    races with enqueue; pop_next always checks the current M01 generation again.
    """
    def __init__(self, manager: SessionManager, max_pending: int = 128, dedup_capacity: int = 4096):
        if (type(max_pending) is not int or max_pending < 1 or
            type(dedup_capacity) is not int or dedup_capacity < max_pending):
            raise ValueError('invalid queue or dedup capacity')
        self.manager = manager
        self.max_pending = max_pending
        self.dedup_capacity = dedup_capacity
        self._known: dict[tuple[str, int, int, int], str] = {}
        self._known_order: deque[tuple[str, int, int, int]] = deque()
        self._queue: deque[TTSInput] = deque()
        self._lock = asyncio.Lock()

    async def _active(self, sid: str, t: int, g: int) -> bool:
        try:
            snap = await self.manager.snapshot(sid)
            if snap.state is not State.SPEAKING or snap.turn_id != t or snap.generation_id != g:
                return False
            token = await self.manager.current_token(sid)
            return not token.cancelled and token.generation_id == g
        except (LookupError, ValueError):
            return False

    async def enqueue(self, plan: ClausePlan) -> QueueReceipt:
        if not isinstance(plan, ClausePlan):
            raise TypeError('ClausePlan required')
        if plan.review_required:
            return QueueReceipt(False, 'review_required', 0)
        if not await self._active(plan.session_id, plan.turn_id, plan.generation_id):
            return QueueReceipt(False, 'stale_generation_or_wrong_state', 0)
        items = plan.tts_inputs()
        async with self._lock:
            to_queue = []
            for item in items:
                key = (str(item.session_id), int(item.turn_id), int(item.generation_id), item.clause_index)
                prior = self._known.get(key)
                if prior is not None and prior != item.text_sha256:
                    return QueueReceipt(False, 'conflicting_replay', 0)
                if prior is None:
                    to_queue.append((key, item))
            if not to_queue:
                return QueueReceipt(True, 'duplicate_ignored', 0)
            if len(self._queue) + len(to_queue) > self.max_pending:
                return QueueReceipt(False, 'backpressure', 0)
            for key, item in to_queue:
                self._queue.append(item)
                self._known[key] = item.text_sha256
                self._known_order.append(key)
            # Bounded replay window, not a durable at-most-once guarantee.
            while len(self._known_order) > self.dedup_capacity:
                self._known.pop(self._known_order.popleft(), None)
        return QueueReceipt(True, 'queued_mock_text', len(to_queue))

    async def pop_next(self) -> TTSInput | None:
        async with self._lock:
            while self._queue:
                item = self._queue.popleft()
                if await self._active(item.session_id, item.turn_id, item.generation_id):
                    return item
        return None

    async def discard_stale(self) -> int:
        async with self._lock:
            retained = deque()
            for item in self._queue:
                if await self._active(item.session_id, item.turn_id, item.generation_id):
                    retained.append(item)
            removed = len(self._queue) - len(retained)
            self._queue = retained
            return removed

    @property
    def pending_count(self) -> int:
        return len(self._queue)
