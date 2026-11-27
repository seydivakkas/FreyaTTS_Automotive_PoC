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
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Iterator, Protocol

from backend.runtime_resources.contracts import ExecutionLease, ResourceRequest


@dataclass(frozen=True, slots=True)
class AdapterExecutionReport:
    delivered: tuple[Any, ...]
    fenced_count: int
    physical_completed: bool
    cancelled: bool


class ProviderAdapter(Protocol):
    async def execute(
        self,
        lease: ExecutionLease,
        request: ResourceRequest,
        *,
        on_output: Callable[[Any], None] | None = None,
    ) -> AdapterExecutionReport: ...

    async def await_physical_completion(self, lease: ExecutionLease) -> None: ...


class FakeCTranslate2Worker:
    """
    Controllable fake CTranslate2 / faster-whisper lazy-iterator worker.

    Models lazy segment generation where pulling from the iterator drives GPU compute,
    and optionally simulates a non-cancellable cleanup/teardown block on cancel.
    """

    def __init__(
        self,
        segments: list[str] | None = None,
        *,
        per_segment_delay_sec: float = 0.0,
        step_gate: asyncio.Event | None = None,
        hang_on_close_gate: asyncio.Event | None = None,
    ) -> None:
        self.segments = list(segments or ["merhaba", "dünya"])
        self.per_segment_delay_sec = per_segment_delay_sec
        self.step_gate = step_gate
        self.hang_on_close_gate = hang_on_close_gate
        self.pulled_count = 0
        self.closed = False
        self.physically_finished = False

    async def stream_segments(self) -> AsyncIterator[str]:
        try:
            for seg in self.segments:
                if self.step_gate is not None:
                    await self.step_gate.wait()
                if self.per_segment_delay_sec > 0:
                    await asyncio.sleep(self.per_segment_delay_sec)
                self.pulled_count += 1
                yield seg
        finally:
            self.closed = True
            if self.hang_on_close_gate is not None:
                await self.hang_on_close_gate.wait()
            self.physically_finished = True


class CTranslate2Adapter:
    """
    Adapter for lazy-iterator ASR workers (e.g. faster-whisper / CTranslate2).

    Fences segment delivery via `ExecutionLease` / `CancellationScope`, stops pulling
    new lazy segments once cancelled, and awaits iterator teardown before declaring
    physical completion.
    """

    def __init__(
        self,
        worker_factory: Callable[[ResourceRequest], FakeCTranslate2Worker | Iterator[Any] | AsyncIterator[Any]],
    ) -> None:
        self._worker_factory = worker_factory
        self._inflight_tasks: dict[str, asyncio.Task[None]] = {}

    async def execute(
        self,
        lease: ExecutionLease,
        request: ResourceRequest,
        *,
        on_output: Callable[[Any], None] | None = None,
    ) -> AdapterExecutionReport:
        if lease.is_output_fenced:
            return AdapterExecutionReport(
                delivered=(),
                fenced_count=lease.fenced_outputs,
                physical_completed=True,
                cancelled=True,
            )
        worker = self._worker_factory(request)
        delivered: list[Any] = []
        sink = on_output if on_output is not None else delivered.append
        completion_event = asyncio.Event()

        async def _consume() -> None:
            if hasattr(worker, "stream_segments"):
                aiter = worker.stream_segments()
                try:
                    async for seg in aiter:
                        if lease.is_output_fenced:
                            lease.fenced_outputs += 1
                            break
                        if not lease.try_deliver_output(sink, seg):
                            break
                finally:
                    await aiter.aclose()
            elif hasattr(worker, "__aiter__"):
                try:
                    async for seg in worker:  # type: ignore[union-attr]
                        if lease.is_output_fenced:
                            lease.fenced_outputs += 1
                            break
                        if not lease.try_deliver_output(sink, seg):
                            break
                finally:
                    if hasattr(worker, "aclose"):
                        await worker.aclose()  # type: ignore[union-attr]
            else:
                try:
                    for seg in worker:  # type: ignore[union-attr]
                        if lease.is_output_fenced:
                            lease.fenced_outputs += 1
                            break
                        if not lease.try_deliver_output(sink, seg):
                            break
                finally:
                    if hasattr(worker, "close"):
                        worker.close()  # type: ignore[union-attr]
            completion_event.set()

        task = asyncio.create_task(_consume())
        self._inflight_tasks[lease.lease_id] = task
        cancel_wait = asyncio.create_task(lease.cancellation_scope.wait_cancelled())
        try:
            done, _ = await asyncio.wait(
                {task, cancel_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if task in done:
                await task
                self._inflight_tasks.pop(lease.lease_id, None)
                return AdapterExecutionReport(
                    delivered=tuple(delivered),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=True,
                    cancelled=lease.cancellation_scope.is_cancel_requested,
                )

            # Cancelled while lazy iterator may still be executing or tearing down.
            grace = request.drain_grace_ms / 1000.0
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=grace)
                self._inflight_tasks.pop(lease.lease_id, None)
                return AdapterExecutionReport(
                    delivered=tuple(delivered),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=True,
                    cancelled=True,
                )
            except asyncio.TimeoutError:
                return AdapterExecutionReport(
                    delivered=tuple(delivered),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=False,
                    cancelled=True,
                )
        finally:
            cancel_wait.cancel()

    async def await_physical_completion(self, lease: ExecutionLease) -> None:
        task = self._inflight_tasks.pop(lease.lease_id, None)
        if task is not None:
            await task


class FakeOllamaWorker:
    """
    Controllable fake Ollama HTTP streaming worker modeling HTTP cancel non-guarantee:
    closing the client HTTP stream stops client reads immediately, while server-side
    GPU inference can keep running until `server_finish_gate` is released.
    """

    def __init__(
        self,
        tokens: list[str] | None = None,
        *,
        ignore_http_cancel: bool = True,
        token_gate: asyncio.Event | None = None,
        server_finish_gate: asyncio.Event | None = None,
    ) -> None:
        self.tokens = list(tokens or ["Merhaba", " size", " yardımcı", " olayım."])
        self.ignore_http_cancel = ignore_http_cancel
        self.token_gate = token_gate
        self.server_finish_gate = server_finish_gate
        self.http_closed = False
        self.server_running = False
        self.server_completed = False
        self._server_task: asyncio.Task[None] | None = None
        self._server_done_event = asyncio.Event()

    def start_server_work(self) -> asyncio.Task[None]:
        if self._server_task is None:
            self.server_running = True

            async def _run_server() -> None:
                try:
                    if self.server_finish_gate is not None:
                        await self.server_finish_gate.wait()
                    self.server_completed = True
                finally:
                    self.server_running = False
                    self._server_done_event.set()

            self._server_task = asyncio.create_task(_run_server())
        return self._server_task

    async def stream_tokens(self) -> AsyncIterator[str]:
        self.start_server_work()
        try:
            for tok in self.tokens:
                if self.token_gate is not None:
                    await self.token_gate.wait()
                yield tok
        finally:
            self.http_closed = True
            if not self.ignore_http_cancel and self._server_task is not None and not self._server_task.done():
                self._server_task.cancel()

    async def wait_server_idle(self) -> None:
        if self._server_task is not None:
            await self._server_done_event.wait()


class OllamaAdapter:
    """
    Adapter for streaming HTTP LLM workers (Ollama).

    Demonstrates HTTP cancel non-guarantee: client cancellation immediately fences
    token output and closes the HTTP stream, while the physical lease cannot be
    released until the server worker finishes (or moves to Quarantine).
    """

    def __init__(self, worker_factory: Callable[[ResourceRequest], FakeOllamaWorker]) -> None:
        self._worker_factory = worker_factory
        self._inflight_workers: dict[str, FakeOllamaWorker] = {}

    async def execute(
        self,
        lease: ExecutionLease,
        request: ResourceRequest,
        *,
        on_output: Callable[[Any], None] | None = None,
    ) -> AdapterExecutionReport:
        if lease.is_output_fenced:
            return AdapterExecutionReport(
                delivered=(),
                fenced_count=lease.fenced_outputs,
                physical_completed=True,
                cancelled=True,
            )
        worker = self._worker_factory(request)
        self._inflight_workers[lease.lease_id] = worker
        delivered: list[Any] = []
        sink = on_output if on_output is not None else delivered.append
        stream = worker.stream_tokens()

        async def _read_stream() -> None:
            try:
                async for tok in stream:
                    if lease.is_output_fenced:
                        lease.fenced_outputs += 1
                        break
                    if not lease.try_deliver_output(sink, tok):
                        break
            finally:
                await stream.aclose()

        read_task = asyncio.create_task(_read_stream())
        cancel_wait = asyncio.create_task(lease.cancellation_scope.wait_cancelled())
        try:
            done, _ = await asyncio.wait(
                {read_task, cancel_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_wait in done and not read_task.done():
                # Client stream closed/cancelled immediately, fencing further delivery.
                read_task.cancel()
                try:
                    await read_task
                except asyncio.CancelledError:
                    pass
            elif read_task in done:
                await read_task

            # Now check whether the physical Ollama GPU execution actually finished.
            grace = request.drain_grace_ms / 1000.0
            try:
                await asyncio.wait_for(worker.wait_server_idle(), timeout=grace)
                self._inflight_workers.pop(lease.lease_id, None)
                return AdapterExecutionReport(
                    delivered=tuple(delivered),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=True,
                    cancelled=lease.cancellation_scope.is_cancel_requested,
                )
            except asyncio.TimeoutError:
                return AdapterExecutionReport(
                    delivered=tuple(delivered),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=False,
                    cancelled=True,
                )
        finally:
            cancel_wait.cancel()

    async def await_physical_completion(self, lease: ExecutionLease) -> None:
        worker = self._inflight_workers.pop(lease.lease_id, None)
        if worker is not None:
            await worker.wait_server_idle()


@dataclass(slots=True)
class FakeCudaHandle:
    result: Any
    done_event: asyncio.Event = field(default_factory=asyncio.Event)

    def complete(self, result: Any | None = None) -> None:
        if result is not None:
            self.result = result
        self.done_event.set()


class FakePyTorchWorker:
    """
    Controllable fake PyTorch async CUDA worker:
    `launch()` returns immediately on the host while the GPU kernel/stream remains
    busy until `complete_gpu()` is signalled.
    """

    def __init__(
        self,
        *,
        result: Any = b"pcm-48k",
        auto_complete: bool = False,
        gpu_delay_sec: float = 0.0,
    ) -> None:
        self.result = result
        self.auto_complete = auto_complete
        self.gpu_delay_sec = gpu_delay_sec
        self.launched = False
        self.gpu_completed = False
        self.handle: FakeCudaHandle | None = None

    def launch(self, request: ResourceRequest) -> FakeCudaHandle:
        self.launched = True
        handle = FakeCudaHandle(result=self.result)
        self.handle = handle
        if self.auto_complete:
            async def _finish() -> None:
                if self.gpu_delay_sec > 0:
                    await asyncio.sleep(self.gpu_delay_sec)
                self.gpu_completed = True
                handle.complete()

            asyncio.create_task(_finish())
        return handle

    def complete_gpu(self, result: Any | None = None) -> None:
        self.gpu_completed = True
        if self.handle is not None:
            self.handle.complete(result)


class PyTorchAdapter:
    """
    Adapter for async CUDA kernel execution (FreyaTTS / BatchedODE / Silero).

    Host kernel launch returns immediately; physical lease is retained until the
    CUDA completion event fires (or moves to Quarantine if cancelled and drain
    grace expires while GPU is still busy).
    """

    def __init__(self, worker_factory: Callable[[ResourceRequest], FakePyTorchWorker]) -> None:
        self._worker_factory = worker_factory
        self._inflight_handles: dict[str, FakeCudaHandle] = {}

    async def execute(
        self,
        lease: ExecutionLease,
        request: ResourceRequest,
        *,
        on_output: Callable[[Any], None] | None = None,
    ) -> AdapterExecutionReport:
        if lease.is_output_fenced:
            return AdapterExecutionReport(
                delivered=(),
                fenced_count=lease.fenced_outputs,
                physical_completed=True,
                cancelled=True,
            )
        worker = self._worker_factory(request)
        cuda_handle = worker.launch(request)
        self._inflight_handles[lease.lease_id] = cuda_handle

        delivered: list[Any] = []
        sink = on_output if on_output is not None else delivered.append

        gpu_wait = asyncio.create_task(cuda_handle.done_event.wait())
        cancel_wait = asyncio.create_task(lease.cancellation_scope.wait_cancelled())
        try:
            done, _ = await asyncio.wait(
                {gpu_wait, cancel_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if gpu_wait in done:
                self._inflight_handles.pop(lease.lease_id, None)
                lease.try_deliver_output(sink, cuda_handle.result)
                return AdapterExecutionReport(
                    delivered=tuple(delivered),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=True,
                    cancelled=lease.cancellation_scope.is_cancel_requested,
                )

            # Cancelled while CUDA stream is still running on GPU!
            grace = request.drain_grace_ms / 1000.0
            try:
                await asyncio.wait_for(asyncio.shield(gpu_wait), timeout=grace)
                self._inflight_handles.pop(lease.lease_id, None)
                # GPU finished within drain grace, but output MUST remain fenced!
                lease.fenced_outputs += 1
                return AdapterExecutionReport(
                    delivered=tuple(delivered),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=True,
                    cancelled=True,
                )
            except asyncio.TimeoutError:
                lease.fenced_outputs += 1
                return AdapterExecutionReport(
                    delivered=tuple(delivered),
                    fenced_count=lease.fenced_outputs,
                    physical_completed=False,
                    cancelled=True,
                )
        finally:
            cancel_wait.cancel()
            if not gpu_wait.done():
                gpu_wait.cancel()

    async def await_physical_completion(self, lease: ExecutionLease) -> None:
        handle = self._inflight_handles.pop(lease.lease_id, None)
        if handle is not None:
            await handle.done_event.wait()
