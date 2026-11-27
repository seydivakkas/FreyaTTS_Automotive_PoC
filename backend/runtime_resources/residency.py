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
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from backend.core.contracts.validation import require_safe_id, require_strict_int
from backend.runtime_resources.contracts import HandleOwnership, ProviderKind, ResidencyState
from backend.runtime_resources.memory_budget import MemoryBudget


class InsufficientVramError(RuntimeError):
    """Raised when MemoryBudget rejects a model load reservation."""


async def _maybe_await(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


@dataclass(frozen=True, slots=True)
class ModelSpec:
    model_id: str
    ownership: HandleOwnership
    provider: ProviderKind
    vram_bytes: int
    loader: Callable[[], Awaitable[Any] | Any]
    unloader: Callable[[Any], Awaitable[None] | None] | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.model_id, "model_id")
        require_strict_int(self.vram_bytes, "vram_bytes", minimum=0)
        if not callable(self.loader):
            raise TypeError("loader must be callable")
        if self.unloader is not None and not callable(self.unloader):
            raise TypeError("unloader must be callable or None")


@dataclass(slots=True)
class ResidencyHandle:
    spec: ModelSpec
    state: ResidencyState = ResidencyState.UNLOADED
    raw_handle: Any = None
    active_pins: int = 0
    load_count: int = 0
    unload_count: int = 0
    reservation_id: str | None = None
    _epoch: int = 0
    _load_task: asyncio.Task[Any] | None = field(default=None, repr=False)
    _unload_task: asyncio.Task[bool] | None = field(default=None, repr=False)
    _pins_zero_event: asyncio.Event | None = field(default=None, repr=False)


@dataclass(slots=True)
class ResidencyPin:
    model_id: str
    _release_cb: Callable[[], None]
    _released: bool = False

    def release(self) -> bool:
        if self._released:
            return False
        self._released = True
        self._release_cb()
        return True


class ResidencyManager:
    """
    Single-flight model residency manager supporting:
    UNLOADED -> LOADING -> READY -> DRAINING -> UNLOADED
    and OWNED / BORROWED / EXTERNAL handle ownership modes.
    """

    def __init__(self, *, memory_budget: MemoryBudget | None = None) -> None:
        self._memory_budget = memory_budget
        self._handles: dict[str, ResidencyHandle] = {}

    def register_model(self, spec: ModelSpec) -> ResidencyHandle:
        if spec.model_id in self._handles:
            raise ValueError(f"Model already registered: {spec.model_id}")
        handle = ResidencyHandle(spec=spec)
        self._handles[spec.model_id] = handle
        return handle

    def get_handle(self, model_id: str) -> ResidencyHandle | None:
        return self._handles.get(model_id)

    def get_state(self, model_id: str) -> ResidencyState | None:
        handle = self._handles.get(model_id)
        return handle.state if handle is not None else None

    def _require_handle(self, model_id: str) -> ResidencyHandle:
        handle = self._handles.get(model_id)
        if handle is None:
            raise KeyError(f"Unknown model_id: {model_id}")
        return handle

    async def ensure_loaded(self, model_id: str) -> ResidencyHandle:
        handle = self._require_handle(model_id)
        while True:
            if handle.state == ResidencyState.READY:
                return handle
            if handle.state == ResidencyState.DRAINING:
                unload_task = handle._unload_task
                if unload_task is not None:
                    await asyncio.shield(unload_task)
                    continue
                if handle.active_pins == 0:
                    await self.unload(model_id)
                    continue
                if handle._pins_zero_event is None:
                    handle._pins_zero_event = asyncio.Event()
                await handle._pins_zero_event.wait()
                continue
            if handle.state == ResidencyState.LOADING:
                load_task = handle._load_task
                assert load_task is not None
                await asyncio.shield(load_task)
                return handle

            # UNLOADED -> LOADING (single-flight)
            handle._epoch += 1
            res_id: str | None = None
            if (
                self._memory_budget is not None
                and handle.spec.vram_bytes > 0
                and handle.spec.ownership != HandleOwnership.BORROWED
            ):
                res_id = f"residency:{model_id}:{handle._epoch}"
                check, _ = self._memory_budget.try_reserve(
                    res_id,
                    handle.spec.vram_bytes,
                    kind=f"residency:{handle.spec.ownership.value.lower()}",
                )
                if not check.admitted:
                    raise InsufficientVramError(
                        f"Cannot load {model_id}: {check.reason} "
                        f"(required={handle.spec.vram_bytes}, usable={check.usable_bytes})"
                    )

            handle.state = ResidencyState.LOADING
            handle.reservation_id = res_id

            async def _run_load() -> ResidencyHandle:
                try:
                    raw = await _maybe_await(handle.spec.loader())
                    handle.raw_handle = raw
                    handle.load_count += 1
                    handle.state = ResidencyState.READY
                    if self._memory_budget is not None and handle.reservation_id is not None:
                        self._memory_budget.mark_allocated(handle.reservation_id)
                    return handle
                except BaseException:
                    if self._memory_budget is not None and handle.reservation_id is not None:
                        self._memory_budget.release(handle.reservation_id)
                    handle.reservation_id = None
                    handle.raw_handle = None
                    handle.state = ResidencyState.UNLOADED
                    raise
                finally:
                    handle._load_task = None

            task = asyncio.create_task(_run_load())
            handle._load_task = task
            return await asyncio.shield(task)

    async def acquire_pin(self, model_id: str) -> ResidencyPin:
        while True:
            handle = await self.ensure_loaded(model_id)
            if handle.state == ResidencyState.READY:
                handle.active_pins += 1
                if handle._pins_zero_event is not None:
                    handle._pins_zero_event.clear()

                def _release() -> None:
                    handle.active_pins = max(0, handle.active_pins - 1)
                    if handle.active_pins == 0 and handle._pins_zero_event is not None:
                        handle._pins_zero_event.set()

                return ResidencyPin(model_id=model_id, _release_cb=_release)

    async def unload(self, model_id: str, *, drain_timeout_ms: int = 500) -> bool:
        require_strict_int(drain_timeout_ms, "drain_timeout_ms", minimum=0)
        handle = self._require_handle(model_id)

        if handle.state == ResidencyState.UNLOADED:
            return False

        if handle.state == ResidencyState.LOADING and handle._load_task is not None:
            try:
                await asyncio.shield(handle._load_task)
            except BaseException:
                if handle.state == ResidencyState.UNLOADED:
                    return False

        if handle.state == ResidencyState.DRAINING and handle._unload_task is not None:
            return await asyncio.shield(handle._unload_task)

        if handle.state == ResidencyState.READY:
            handle.state = ResidencyState.DRAINING

        async def _run_unload() -> bool:
            try:
                if handle.active_pins > 0:
                    if handle._pins_zero_event is None:
                        handle._pins_zero_event = asyncio.Event()
                    else:
                        handle._pins_zero_event.clear()
                    await asyncio.wait_for(
                        handle._pins_zero_event.wait(),
                        timeout=drain_timeout_ms / 1000.0,
                    )
                if handle.spec.ownership != HandleOwnership.BORROWED and handle.spec.unloader is not None:
                    await _maybe_await(handle.spec.unloader(handle.raw_handle))
                if self._memory_budget is not None and handle.reservation_id is not None:
                    self._memory_budget.release(handle.reservation_id)
                handle.reservation_id = None
                handle.raw_handle = None
                handle.unload_count += 1
                handle.state = ResidencyState.UNLOADED
                return True
            finally:
                handle._unload_task = None

        task = asyncio.create_task(_run_unload())
        handle._unload_task = task
        return await asyncio.shield(task)
