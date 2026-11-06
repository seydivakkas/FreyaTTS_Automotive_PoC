"""Per-session cooperative cancellation and optional asyncio task cancellation."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from automotive_voice.core.identifiers import GenerationId

class StaleGenerationError(RuntimeError): pass

@dataclass(slots=True)
class CancellationToken:
    generation_id: GenerationId
    _cancelled: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _tasks: set[asyncio.Task] = field(default_factory=set, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    async def wait_cancelled(self) -> None:
        await self._cancelled.wait()

    def register_task(self, task: asyncio.Task) -> None:
        if self.cancelled:
            task.cancel()
            raise StaleGenerationError("Generation already cancelled")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def cancel(self) -> None:
        if self.cancelled:
            return
        self._cancelled.set()
        for task in tuple(self._tasks):
            if not task.done():
                task.cancel()

class CancellationController:
    """Caller serializes methods under its session lock (SessionManager)."""
    def __init__(self, initial: GenerationId = GenerationId(0)) -> None:
        self._token = CancellationToken(GenerationId(initial))

    @property
    def current(self) -> CancellationToken:
        return self._token

    def is_current(self, generation_id: int) -> bool:
        return self._token.generation_id == generation_id and not self._token.cancelled

    def token_for(self, generation_id: int) -> CancellationToken:
        if not self.is_current(generation_id):
            raise StaleGenerationError("Stale or cancelled generation")
        return self._token

    def advance(self, generation_id: GenerationId) -> CancellationToken:
        if int(generation_id) <= int(self._token.generation_id):
            raise ValueError("New generation must increase monotonically")
        self._token.cancel()
        self._token = CancellationToken(GenerationId(generation_id))
        return self._token

    def cancel_current(self) -> None:
        self._token.cancel()
