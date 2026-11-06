"""Bounded, in-process, at-most-once fanout with atomic backpressure.

No durable storage. Publish does not invoke subscribers; consumers drain queues.
An event cannot be partially enqueued among subscribers on queue overflow.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from automotive_voice.core.events import EventEnvelope

class EventBusError(Exception): pass
class EventBusFull(EventBusError): pass
class EventBusClosed(EventBusError): pass
class EventOrderingError(EventBusError): pass

@dataclass(slots=True)
class Subscription:
    name: str
    _queue: asyncio.Queue[EventEnvelope]
    _closed: bool = False

    def get_nowait(self) -> EventEnvelope:
        return self._queue.get_nowait()

    async def get(self) -> EventEnvelope:
        # call with timeout/cancellation in long-running clients; M01 does not
        # guarantee wake-up for readers already blocked when unsubscribed.
        if self._closed and self._queue.empty():
            raise EventBusClosed("Subscription is closed")
        return await self._queue.get()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

class EventBus:
    def __init__(self, default_capacity: int = 128):
        if type(default_capacity) is not int or default_capacity < 1:
            raise ValueError("default_capacity must be positive")
        self._capacity = default_capacity
        self._subs: dict[str, Subscription] = {}
        self._last_sequence: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def subscribe(self, name: str, capacity: int | None = None) -> Subscription:
        cap = self._capacity if capacity is None else capacity
        if not isinstance(name, str) or not name.strip() or type(cap) is not int or cap < 1:
            raise ValueError("Subscription name/capacity invalid")
        async with self._lock:
            if self._closed:
                raise EventBusClosed("Event bus closed")
            if name in self._subs:
                raise ValueError("Subscription name already used")
            sub = Subscription(name, asyncio.Queue(maxsize=cap))
            self._subs[name] = sub
            return sub

    async def unsubscribe(self, name: str) -> None:
        async with self._lock:
            sub = self._subs.pop(name, None)
            if sub is not None:
                sub._closed = True

    async def publish(self, event: EventEnvelope) -> None:
        if not isinstance(event, EventEnvelope):
            raise TypeError("publish requires EventEnvelope")
        async with self._lock:
            if self._closed:
                raise EventBusClosed("Event bus closed")
            sid = str(event.session_id)
            prev = self._last_sequence.get(sid, -1)
            if event.sequence != prev + 1:
                raise EventOrderingError(f"Session {sid}: expected sequence {prev + 1}, got {event.sequence}")
            # Fanout preflight: do not send to one consumer if another is full.
            if any(sub._queue.full() for sub in self._subs.values()):
                raise EventBusFull("A subscription has reached its bounded capacity")
            for sub in self._subs.values():
                sub._queue.put_nowait(event)
            self._last_sequence[sid] = event.sequence

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            for sub in self._subs.values():
                sub._closed = True
            self._subs.clear()

    def last_published_sequence(self, session_id: str) -> int:
        return self._last_sequence.get(session_id, -1)
