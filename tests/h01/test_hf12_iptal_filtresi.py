# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz

import asyncio
import time

import numpy as np
import pytest

from backend.batched_ode import BatchItem, BatchedODEEngine


@pytest.mark.asyncio
@pytest.mark.parametrize("has_live_item", [False, True])
async def test_HF12_cancelled_queue_items_never_reach_solver(monkeypatch, has_live_item):
    engine = BatchedODEEngine(batch_size=2)
    loop = asyncio.get_running_loop()
    cancelled = loop.create_future()
    cancelled.cancel()
    live = loop.create_future()
    engine._queue.append(BatchItem("eski", 0.0, 9, cancelled, time.monotonic()))
    if has_live_item:
        engine._queue.append(BatchItem("yeni", 0.0, 9, live, time.monotonic()))
    calls = []

    def solve(batch):
        calls.append([item.text for item in batch])
        return [np.ones(480, dtype=np.float32) for item in batch]

    monkeypatch.setattr(engine, "_solve_ode_batch", solve)
    await engine._process_queue_now()
    assert cancelled.cancelled()
    assert calls == ([["yeni"]] if has_live_item else [])
    assert engine._queue == []
    if has_live_item:
        assert live.done()
        assert len(live.result()) == 480
    else:
        live.cancel()
