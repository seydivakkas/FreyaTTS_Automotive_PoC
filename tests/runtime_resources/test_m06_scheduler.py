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
import subprocess
import sys

import pytest

from backend.core.runtime import CancellationScope, DeadlineBudget, FakeClock, StaleScopeError
from backend.runtime_resources import (
    MIB,
    AdmissionController,
    AdmissionOutcome,
    AgingPolicy,
    BoundedFairPriorityQueue,
    CTranslate2Adapter,
    ExecutionLease,
    ExecutionLeaseState,
    FakeCTranslate2Worker,
    FakeOllamaWorker,
    FakePyTorchWorker,
    HandleOwnership,
    InsufficientVramError,
    MemoryBudget,
    MemoryProbe,
    ModelSpec,
    OllamaAdapter,
    PriorityClass,
    ProbeStatus,
    ProviderKind,
    PyTorchAdapter,
    QuarantineExhaustedError,
    QuarantineManager,
    ResidencyManager,
    ResidencyState,
    ResourceRequest,
    UnifiedGpuScheduler,
    mib_to_bytes,
)


def _req(
    request_id: str,
    priority: PriorityClass,
    scope: CancellationScope,
    *,
    provider: ProviderKind = ProviderKind.PYTORCH,
    model_id: str = "tts-leyla",
    vram_bytes: int = 128 * MIB,
    session_id: str | None = "sess-1",
    deadline: DeadlineBudget | None = None,
    supersession_key: str | None = None,
    drain_grace_ms: int = 20,
) -> ResourceRequest:
    return ResourceRequest(
        request_id=request_id,
        priority=priority,
        provider=provider,
        model_id=model_id,
        estimated_vram_bytes=vram_bytes,
        cancellation_scope=scope,
        session_id=session_id,
        deadline=deadline,
        supersession_key=supersession_key,
        drain_grace_ms=drain_grace_ms,
    )


def test_m06_01_passive_isolated_import():
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, backend.runtime_resources; "
                "forbidden = {'torch', 'ctranslate2', 'faster_whisper', 'httpx', 'sqlalchemy'}; "
                "loaded = forbidden.intersection(sys.modules); "
                "assert not loaded, f'Unexpected imports: {loaded}'"
            ),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_m06_02_priority_classes_p0_to_p7_and_p5_latest_only_supersession():
    clock = FakeClock(1_000_000)
    scope = CancellationScope("root", clock=clock)
    q = BoundedFairPriorityQueue(clock=clock, max_items=32)

    evicted: list[tuple[str, AdmissionOutcome]] = []

    # Enqueue out of order across all P0..P7
    for idx, prio in enumerate(
        [
            PriorityClass.P7,
            PriorityClass.P5,
            PriorityClass.P3,
            PriorityClass.P1,
            PriorityClass.P6,
            PriorityClass.P4,
            PriorityClass.P2,
            PriorityClass.P0,
        ]
    ):
        rid = f"req-{prio.name}-{idx}"
        res = q.enqueue(
            _req(rid, prio, scope, vram_bytes=0),
            on_evicted=lambda outcome, r=rid: evicted.append((r, outcome)),
        )
        assert res.outcome == AdmissionOutcome.QUEUED

    # Enqueue a newer P5 partial ASR for the same session -> supersedes older P5
    res_p5_new = q.enqueue(_req("req-P5-latest", PriorityClass.P5, scope, vram_bytes=0))
    assert res_p5_new.outcome == AdmissionOutcome.QUEUED
    assert res_p5_new.superseded_request_ids == ("req-P5-1",)
    assert evicted == [("req-P5-1", AdmissionOutcome.SUPERSEDED)]
    assert q.superseded_count == 1

    popped_order = []
    while True:
        item = q.pop_next()
        if item is None:
            break
        popped_order.append((item.request.priority, item.request.request_id))

    assert [p for p, _ in popped_order] == [
        PriorityClass.P0,
        PriorityClass.P1,
        PriorityClass.P2,
        PriorityClass.P3,
        PriorityClass.P4,
        PriorityClass.P5,
        PriorityClass.P6,
        PriorityClass.P7,
    ]
    assert popped_order[5][1] == "req-P5-latest"


def test_m06_03_bounded_aging_fairness_and_deadline_enforcement():
    clock = FakeClock(0)
    scope = CancellationScope("root", clock=clock)
    aging = AgingPolicy(
        aging_quantum_ms=50,
        max_boost_levels=4,
        min_effective_rank=1,
        class_floors={PriorityClass.P7: 3},
    )
    q = BoundedFairPriorityQueue(clock=clock, aging_policy=aging)

    # Enqueue P4 (later TTS) and P7 (lab/benchmark) at t=0
    q.enqueue(_req("p4-old", PriorityClass.P4, scope))
    q.enqueue(_req("p7-old", PriorityClass.P7, scope))

    # Advance 200ms -> 4 quantums of 50ms:
    # P4 boosts by 3 to rank 1 (min_effective_rank=1), P7 boosts by 4 capped at class_floor=3.
    clock.advance_ms(200)
    assert q.effective_rank_of("p4-old") == 1
    assert q.effective_rank_of("p7-old") == 3

    # Fresh P2 (first TTS) and P0 (interruption) arrive at t=200ms
    q.enqueue(_req("p2-fresh", PriorityClass.P2, scope))
    q.enqueue(_req("p0-fresh", PriorityClass.P0, scope, provider=ProviderKind.CONTROL, vram_bytes=0))

    # P0 MUST still come first (cannot be overtaken by aging)
    assert q.pop_next().request.request_id == "p0-fresh"
    # Aged P4 (eff rank 1) beats fresh P2 (eff rank 2)
    assert q.pop_next().request.request_id == "p4-old"
    # Fresh P2 (eff rank 2) beats aged P7 (bounded at floor 3)
    assert q.pop_next().request.request_id == "p2-fresh"
    assert q.pop_next().request.request_id == "p7-old"

    # Deadline enforcement using M02 DeadlineBudget
    budget = DeadlineBudget.from_now(clock, 25)
    q.enqueue(_req("will-expire", PriorityClass.P1, scope, deadline=budget))
    clock.advance_ms(25)
    assert q.pop_next() is None
    assert q.expired_count == 1

    # Already expired at enqueue is rejected immediately
    assert q.enqueue(_req("already-expired", PriorityClass.P1, scope, deadline=budget)).outcome == AdmissionOutcome.REJECTED_DEADLINE

    # Clock domain mismatch rejected as invalid
    other_clock = FakeClock(0, clock_domain="other.domain")
    bad_budget = DeadlineBudget.from_now(other_clock, 100)
    assert q.enqueue(_req("wrong-domain", PriorityClass.P1, scope, deadline=bad_budget)).outcome == AdmissionOutcome.REJECTED_INVALID


def test_m06_04_memory_budget_byte_accuracy_and_conservative_probes():
    assert MIB == 1_048_576
    assert mib_to_bytes(2) == 2_097_152

    clock = FakeClock(1_000_000_000)
    budget = MemoryBudget(clock=clock, headroom_bytes=256 * MIB, max_probe_age_ms=500)

    # 1. Missing probe -> conservative rejection
    chk_missing = budget.check_admission(1 * MIB)
    assert chk_missing.admitted is False
    assert chk_missing.probe_status == ProbeStatus.UNKNOWN
    assert budget.usable_bytes() == 0

    # 2. Unknown free_bytes / unreliable probe -> conservative rejection
    budget.update_probe(
        MemoryProbe(total_bytes=8192 * MIB, free_bytes=None, observed_at_ns=clock.monotonic_ns(), clock_domain=clock.clock_domain)
    )
    assert budget.check_admission(1 * MIB).probe_status == ProbeStatus.UNRELIABLE
    assert budget.check_admission(1 * MIB).admitted is False

    # 3. Clock domain mismatch -> conservative rejection
    budget.update_probe(
        MemoryProbe(total_bytes=8192 * MIB, free_bytes=4096 * MIB, observed_at_ns=clock.monotonic_ns(), clock_domain="wrong.domain")
    )
    assert budget.check_admission(1 * MIB).probe_status == ProbeStatus.DOMAIN_MISMATCH
    assert budget.check_admission(1 * MIB).admitted is False

    # 4. Valid probe: free = 1024 MiB, headroom = 256 MiB => usable = 768 MiB
    budget.update_probe(
        MemoryProbe(total_bytes=8192 * MIB, free_bytes=1024 * MIB, observed_at_ns=clock.monotonic_ns(), clock_domain=clock.clock_domain)
    )
    assert budget.usable_bytes() == 768 * MIB

    # Reserve 500 MiB (unobserved) -> usable = 1024 - 256 - 500 = 268 MiB
    chk_r1, res1 = budget.try_reserve("res-1", 500 * MIB)
    assert chk_r1.admitted is True and res1 is not None
    assert budget.unobserved_reserved_bytes == 500 * MIB
    assert budget.usable_bytes() == 268 * MIB

    # Exact byte boundary check: 268 MiB fits, 268 MiB + 1 byte fails
    assert budget.check_admission(268 * MIB).admitted is True
    assert budget.check_admission(268 * MIB + 1).admitted is False

    # Mark allocated at current probe seq -> still unobserved until a *new* probe arrives!
    budget.mark_allocated("res-1")
    assert budget.unobserved_reserved_bytes == 500 * MIB

    # New probe reflects the 500 MiB physical allocation (free drops from 1024 -> 524 MiB)
    clock.advance_ms(100)
    budget.update_probe(
        MemoryProbe(total_bytes=8192 * MIB, free_bytes=524 * MIB, observed_at_ns=clock.monotonic_ns(), clock_domain=clock.clock_domain)
    )
    assert budget.unobserved_reserved_bytes == 0
    assert budget.usable_bytes() == 268 * MIB  # 524 - 256 - 0 = 268 MiB (no double-counting!)

    # Stale probe (> 500ms) -> conservative rejection
    clock.advance_ms(501)
    chk_stale = budget.check_admission(1 * MIB)
    assert chk_stale.admitted is False
    assert chk_stale.probe_status == ProbeStatus.STALE


@pytest.mark.asyncio
async def test_m06_05_residency_single_flight_and_ownership_modes():
    clock = FakeClock(1_000_000)
    budget = MemoryBudget(clock=clock, headroom_bytes=256 * MIB, max_probe_age_ms=2_000)
    budget.update_probe(
        MemoryProbe(total_bytes=8192 * MIB, free_bytes=2048 * MIB, observed_at_ns=clock.monotonic_ns(), clock_domain=clock.clock_domain)
    )
    residency = ResidencyManager(memory_budget=budget)

    load_gate = asyncio.Event()
    owned_loads = 0
    owned_unloads = 0

    async def load_owned():
        nonlocal owned_loads
        owned_loads += 1
        await load_gate.wait()
        return {"model": "freya-tts"}

    async def unload_owned(_handle):
        nonlocal owned_unloads
        owned_unloads += 1

    residency.register_model(
        ModelSpec(
            model_id="tts-owned",
            ownership=HandleOwnership.OWNED,
            provider=ProviderKind.PYTORCH,
            vram_bytes=512 * MIB,
            loader=load_owned,
            unloader=unload_owned,
        )
    )

    borrowed_unloads = 0
    residency.register_model(
        ModelSpec(
            model_id="vad-borrowed",
            ownership=HandleOwnership.BORROWED,
            provider=ProviderKind.PYTORCH,
            vram_bytes=64 * MIB,
            loader=lambda: "shared-silero",
            unloader=lambda _h: (_ for _ in ()).throw(AssertionError("BORROWED model must never be destroyed")),
        )
    )

    external_unloads = 0

    def unload_external(_h):
        nonlocal external_unloads
        external_unloads += 1

    residency.register_model(
        ModelSpec(
            model_id="ollama-external",
            ownership=HandleOwnership.EXTERNAL,
            provider=ProviderKind.OLLAMA,
            vram_bytes=1024 * MIB,
            loader=lambda: {"url": "http://localhost:11434"},
            unloader=unload_external,
        )
    )

    # Single-flight: 5 concurrent callers share 1 load
    load_tasks = [asyncio.create_task(residency.ensure_loaded("tts-owned")) for _ in range(5)]
    await asyncio.sleep(0)
    assert residency.get_state("tts-owned") == ResidencyState.LOADING
    load_gate.set()
    handles = await asyncio.gather(*load_tasks)
    assert owned_loads == 1
    assert all(h.state == ResidencyState.READY for h in handles)
    assert budget.unobserved_reserved_bytes == 512 * MIB

    # Pin prevents UNLOADED until drained
    pin = await residency.acquire_pin("tts-owned")
    unload_task = asyncio.create_task(residency.unload("tts-owned", drain_timeout_ms=500))
    await asyncio.sleep(0)
    assert residency.get_state("tts-owned") == ResidencyState.DRAINING

    # Concurrent ensure_loaded waits for DRAINING -> UNLOADED before reloading
    reload_task = asyncio.create_task(residency.ensure_loaded("tts-owned"))
    await asyncio.sleep(0)
    assert not unload_task.done()
    pin.release()
    assert await unload_task is True
    assert owned_unloads == 1
    reloaded = await reload_task
    assert reloaded.state == ResidencyState.READY
    assert owned_loads == 2
    assert await residency.unload("tts-owned") is True
    assert residency.get_state("tts-owned") == ResidencyState.UNLOADED
    assert budget.unobserved_reserved_bytes == 0

    # BORROWED handle never calls unloader and does not reserve VRAM
    await residency.ensure_loaded("vad-borrowed")
    assert budget.unobserved_reserved_bytes == 0
    assert await residency.unload("vad-borrowed") is True
    assert residency.get_state("vad-borrowed") == ResidencyState.UNLOADED
    assert borrowed_unloads == 0

    # EXTERNAL handle tracks VRAM and calls external unloader
    await residency.ensure_loaded("ollama-external")
    assert budget.unobserved_reserved_bytes == 1024 * MIB
    assert await residency.unload("ollama-external") is True
    assert external_unloads == 1
    assert budget.unobserved_reserved_bytes == 0


@pytest.mark.asyncio
async def test_m06_06_residency_load_failure_rolls_back_vram_and_state():
    clock = FakeClock(0)
    budget = MemoryBudget(clock=clock, headroom_bytes=128 * MIB)
    budget.update_probe(
        MemoryProbe(total_bytes=4096 * MIB, free_bytes=1024 * MIB, observed_at_ns=0, clock_domain=clock.clock_domain)
    )
    residency = ResidencyManager(memory_budget=budget)
    attempts = 0

    def flaky_loader():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("weights missing")
        return "ok-model"

    residency.register_model(
        ModelSpec(
            model_id="flaky",
            ownership=HandleOwnership.OWNED,
            provider=ProviderKind.PYTORCH,
            vram_bytes=256 * MIB,
            loader=flaky_loader,
        )
    )

    with pytest.raises(RuntimeError, match="weights missing"):
        await residency.ensure_loaded("flaky")
    assert residency.get_state("flaky") == ResidencyState.UNLOADED
    assert budget.unobserved_reserved_bytes == 0

    h = await residency.ensure_loaded("flaky")
    assert h.state == ResidencyState.READY
    assert budget.unobserved_reserved_bytes == 256 * MIB


@pytest.mark.asyncio
async def test_m06_07_ctranslate2_lazy_iterator_cancel_fences_and_quarantines():
    clock = FakeClock(0)
    budget = MemoryBudget(clock=clock, headroom_bytes=128 * MIB)
    budget.update_probe(
        MemoryProbe(total_bytes=4096 * MIB, free_bytes=2048 * MIB, observed_at_ns=0, clock_domain=clock.clock_domain)
    )
    scheduler = UnifiedGpuScheduler(clock=clock, memory_budget=budget)
    scheduler.residency_manager.register_model(
        ModelSpec(
            model_id="whisper-tr",
            ownership=HandleOwnership.OWNED,
            provider=ProviderKind.CTRANSLATE2,
            vram_bytes=256 * MIB,
            loader=lambda: "ct2-model",
        )
    )

    step_gate = asyncio.Event()
    step_gate.set()
    hang_close = asyncio.Event()
    worker = FakeCTranslate2Worker(
        segments=["randevu", "almak", "istiyorum"],
        step_gate=step_gate,
        hang_on_close_gate=hang_close,
    )
    scheduler.register_adapter(ProviderKind.CTRANSLATE2, CTranslate2Adapter(lambda _req: worker))

    root = CancellationScope("sess-ct2", clock=clock)
    delivered: list[str] = []

    def on_seg(seg: str) -> None:
        delivered.append(seg)
        if len(delivered) == 1:
            # Barge-in right after first segment!
            root.request_cancel("barge_in")

    req = _req(
        "asr-1",
        PriorityClass.P1,
        root,
        provider=ProviderKind.CTRANSLATE2,
        model_id="whisper-tr",
        vram_bytes=128 * MIB,
        drain_grace_ms=10,
    )
    outcome = await scheduler.run_request(req, on_output=on_seg)

    # First segment delivered; remaining segments fenced; iterator close hung -> Quarantined!
    assert delivered == ["randevu"]
    assert outcome.quarantined is True
    assert outcome.lease_state == ExecutionLeaseState.QUARANTINED
    assert scheduler.quarantine_manager.active_count == 1
    # Physical VRAM remains reserved while quarantined (256 MiB model + 128 MiB execution)
    assert budget.unobserved_reserved_bytes == 384 * MIB
    assert scheduler.residency_manager.get_handle("whisper-tr").active_pins == 1

    # Unblock lazy iterator teardown -> Quarantine reclaims lease and frees execution VRAM + pin
    hang_close.set()
    await scheduler.wait_reclaims()
    assert scheduler.quarantine_manager.active_count == 0
    assert scheduler.quarantine_manager.total_reclaimed == 1
    assert scheduler.get_lease(outcome.lease_id).state == ExecutionLeaseState.RELEASED
    assert budget.unobserved_reserved_bytes == 256 * MIB
    assert scheduler.residency_manager.get_handle("whisper-tr").active_pins == 0


@pytest.mark.asyncio
async def test_m06_08_ollama_http_cancel_non_guarantee_quarantine_and_backpressure():
    clock = FakeClock(0)
    budget = MemoryBudget(clock=clock, headroom_bytes=128 * MIB)
    budget.update_probe(
        MemoryProbe(total_bytes=8192 * MIB, free_bytes=4096 * MIB, observed_at_ns=0, clock_domain=clock.clock_domain)
    )
    # Tight quarantine cap = 1 so we also verify quarantine exhaustion blocks new admissions!
    quarantine = QuarantineManager(clock=clock, max_entries=1)
    scheduler = UnifiedGpuScheduler(
        clock=clock,
        memory_budget=budget,
        quarantine_manager=quarantine,
    )
    scheduler.residency_manager.register_model(
        ModelSpec(
            model_id="qwen-ollama",
            ownership=HandleOwnership.EXTERNAL,
            provider=ProviderKind.OLLAMA,
            vram_bytes=1024 * MIB,
            loader=lambda: "ollama-proc",
        )
    )
    scheduler.residency_manager.register_model(
        ModelSpec(
            model_id="tts-leyla",
            ownership=HandleOwnership.OWNED,
            provider=ProviderKind.PYTORCH,
            vram_bytes=256 * MIB,
            loader=lambda: "tts",
        )
    )

    token_gate = asyncio.Event()
    token_gate.set()
    server_gate = asyncio.Event()
    worker = FakeOllamaWorker(
        tokens=["Araç", " plakanız", " nedir?"],
        ignore_http_cancel=True,
        token_gate=token_gate,
        server_finish_gate=server_gate,
    )
    scheduler.register_adapter(ProviderKind.OLLAMA, OllamaAdapter(lambda _req: worker))

    scope = CancellationScope("sess-llm", clock=clock)
    tokens: list[str] = []

    def on_tok(tok: str) -> None:
        tokens.append(tok)
        token_gate.clear()
        scope.request_cancel("user_barge_in")

    req = _req(
        "llm-1",
        PriorityClass.P3,
        scope,
        provider=ProviderKind.OLLAMA,
        model_id="qwen-ollama",
        vram_bytes=512 * MIB,
        drain_grace_ms=10,
    )
    outcome = await scheduler.run_request(req, on_output=on_tok)

    # HTTP stream closed and output fenced, yet server GPU worker is STILL running!
    assert tokens == ["Araç"]
    assert worker.http_closed is True
    assert worker.server_running is True
    assert outcome.quarantined is True
    assert quarantine.active_count == 1
    assert quarantine.is_exhausted is True

    # While quarantine is exhausted, new GPU work is rejected fail-closed, while 0-VRAM P0 control passes
    other_scope = CancellationScope("sess-other", clock=clock)
    gpu_blocked = scheduler.admission.evaluate(
        _req("tts-blocked", PriorityClass.P2, other_scope, provider=ProviderKind.PYTORCH, model_id="tts-leyla")
    )
    assert gpu_blocked.outcome == AdmissionOutcome.REJECTED_QUARANTINE

    p0_ctrl = scheduler.admission.evaluate(
        _req("p0-ctrl", PriorityClass.P0, other_scope, provider=ProviderKind.CONTROL, model_id="tts-leyla", vram_bytes=0)
    )
    assert p0_ctrl.outcome == AdmissionOutcome.ADMITTED

    # Server finally finishes -> Quarantine reclaims and GPU admission unblocks
    server_gate.set()
    await scheduler.wait_reclaims()
    assert worker.server_completed is True
    assert quarantine.active_count == 0
    assert scheduler.get_lease(outcome.lease_id).state == ExecutionLeaseState.RELEASED
    gpu_unblocked = scheduler.admission.evaluate(
        _req("tts-ok", PriorityClass.P2, other_scope, provider=ProviderKind.PYTORCH, model_id="tts-leyla")
    )
    assert gpu_unblocked.outcome == AdmissionOutcome.ADMITTED


@pytest.mark.asyncio
async def test_m06_09_pytorch_async_cuda_completion_and_cancel_fencing():
    clock = FakeClock(0)
    budget = MemoryBudget(clock=clock, headroom_bytes=128 * MIB)
    budget.update_probe(
        MemoryProbe(total_bytes=8192 * MIB, free_bytes=4096 * MIB, observed_at_ns=0, clock_domain=clock.clock_domain)
    )
    scheduler = UnifiedGpuScheduler(clock=clock, memory_budget=budget)
    scheduler.residency_manager.register_model(
        ModelSpec(
            model_id="tts-leyla",
            ownership=HandleOwnership.OWNED,
            provider=ProviderKind.PYTORCH,
            vram_bytes=512 * MIB,
            loader=lambda: "freya-dit",
        )
    )

    workers: list[FakePyTorchWorker] = []

    def make_worker(_req):
        w = FakePyTorchWorker(result=b"audio-pcm", auto_complete=False)
        workers.append(w)
        return w

    scheduler.register_adapter(ProviderKind.PYTORCH, PyTorchAdapter(make_worker))

    # Case A: Normal async CUDA completion — host launch returns immediately, lease waits for CUDA event
    s1 = CancellationScope("s-cuda-ok", clock=clock)
    task_ok = asyncio.create_task(
        scheduler.run_request(
            _req("tts-1", PriorityClass.P2, s1, provider=ProviderKind.PYTORCH, vram_bytes=256 * MIB)
        )
    )
    for _ in range(10):
        if workers:
            break
        await asyncio.sleep(0)
    assert len(workers) == 1 and workers[0].launched is True and workers[0].gpu_completed is False
    assert not task_ok.done()
    assert budget.unobserved_reserved_bytes == 768 * MIB  # 512 model + 256 exec

    workers[0].complete_gpu(b"audio-48k")
    res_ok = await task_ok
    assert res_ok.admission == AdmissionOutcome.ADMITTED
    assert res_ok.delivered == (b"audio-48k",)
    assert res_ok.quarantined is False
    assert res_ok.lease_state == ExecutionLeaseState.RELEASED
    assert budget.unobserved_reserved_bytes == 512 * MIB  # exec freed, model remains READY

    # Case B: Cancelled while CUDA stream still running -> output fenced, quarantined until GPU finishes
    s2 = CancellationScope("s-cuda-cancel", clock=clock)
    delivered_cancelled: list[bytes] = []
    task_cancel = asyncio.create_task(
        scheduler.run_request(
            _req(
                "tts-2",
                PriorityClass.P4,
                s2,
                provider=ProviderKind.PYTORCH,
                vram_bytes=256 * MIB,
                drain_grace_ms=10,
            ),
            on_output=delivered_cancelled.append,
        )
    )
    for _ in range(10):
        if len(workers) == 2:
            break
        await asyncio.sleep(0)
    assert len(workers) == 2 and workers[1].launched is True

    # Trigger cooperative cancel while GPU kernel is mid-flight
    s2.request_cancel("turn_superseded")
    res_cancel = await task_cancel
    assert delivered_cancelled == []
    assert res_cancel.quarantined is True
    assert res_cancel.lease_state == ExecutionLeaseState.QUARANTINED
    assert budget.unobserved_reserved_bytes == 768 * MIB

    # Late GPU completion triggers automatic reclaim; output is NEVER delivered
    workers[1].complete_gpu(b"stale-audio")
    await scheduler.wait_reclaims()
    assert delivered_cancelled == []
    assert scheduler.quarantine_manager.active_count == 0
    assert scheduler.get_lease(res_cancel.lease_id).state == ExecutionLeaseState.RELEASED
    assert budget.unobserved_reserved_bytes == 512 * MIB


def test_m06_10_execution_lease_direct_output_fencing():
    clock = FakeClock(50)
    scope = CancellationScope("direct", clock=clock)
    lease = ExecutionLease(
        lease_id="lease-direct",
        request_id="req-direct",
        model_id="tts-leyla",
        provider=ProviderKind.PYTORCH,
        priority=PriorityClass.P2,
        reserved_bytes=64 * MIB,
        cancellation_scope=scope,
        acquired_at_ns=clock.monotonic_ns(),
    )
    lease.mark_in_flight()
    sink: list[str] = []
    assert lease.try_deliver_output(sink.append, "chunk-0") is True
    assert lease.holds_physical_resources is True

    # Cancel fences output immediately while physical resources remain held
    assert lease.request_cancel("barge_in") is True
    assert lease.state == ExecutionLeaseState.CANCEL_REQUESTED
    assert lease.holds_physical_resources is True
    assert lease.try_deliver_output(sink.append, "chunk-1") is False
    with pytest.raises(StaleScopeError):
        lease.assert_output_allowed()
    assert sink == ["chunk-0"]
    assert lease.fenced_outputs == 2

    assert lease.release_physical() is True
    assert lease.holds_physical_resources is False


@pytest.mark.asyncio
async def test_m06_11_scheduler_submit_dispatch_and_residency_drain_timeout():
    clock = FakeClock(0)
    budget = MemoryBudget(clock=clock, headroom_bytes=128 * MIB)
    budget.update_probe(
        MemoryProbe(total_bytes=4096 * MIB, free_bytes=2048 * MIB, observed_at_ns=0, clock_domain=clock.clock_domain)
    )
    qm = QuarantineManager(clock=clock, max_entries=2, max_quarantined_bytes=256 * MIB)
    scheduler = UnifiedGpuScheduler(clock=clock, memory_budget=budget, quarantine_manager=qm)
    scheduler.residency_manager.register_model(
        ModelSpec(
            model_id="tts-leyla",
            ownership=HandleOwnership.OWNED,
            provider=ProviderKind.PYTORCH,
            vram_bytes=256 * MIB,
            loader=lambda: "tts",
        )
    )
    scheduler.register_adapter(
        ProviderKind.PYTORCH,
        PyTorchAdapter(lambda _req: FakePyTorchWorker(result=b"ok", auto_complete=True)),
    )

    # Submit P4 then P1 -> dispatch_next pops P1 first
    scope = CancellationScope("s-disp", clock=clock)
    assert scheduler.submit(_req("tts-later", PriorityClass.P4, scope, vram_bytes=64 * MIB)).outcome == AdmissionOutcome.QUEUED
    assert scheduler.submit(_req("tts-first", PriorityClass.P2, scope, vram_bytes=64 * MIB)).outcome == AdmissionOutcome.QUEUED
    out1 = await scheduler.dispatch_next()
    out2 = await scheduler.dispatch_next()
    assert out1 is not None and out1.request_id == "tts-first"
    assert out2 is not None and out2.request_id == "tts-later"
    assert await scheduler.dispatch_next() is None

    # Drain timeout while pinned keeps DRAINING; once unpinned, unload finishes cleanly
    pin = await scheduler.residency_manager.acquire_pin("tts-leyla")
    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await scheduler.residency_manager.unload("tts-leyla", drain_timeout_ms=10)
    assert scheduler.residency_manager.get_state("tts-leyla") == ResidencyState.DRAINING
    pin.release()
    assert await scheduler.residency_manager.unload("tts-leyla", drain_timeout_ms=50) is True
    assert scheduler.residency_manager.get_state("tts-leyla") == ResidencyState.UNLOADED

    # Quarantine byte-cap enforcement
    l1 = ExecutionLease("l1", "r1", "tts-leyla", ProviderKind.PYTORCH, PriorityClass.P2, 200 * MIB, scope, 0)
    l2 = ExecutionLease("l2", "r2", "tts-leyla", ProviderKind.PYTORCH, PriorityClass.P2, 100 * MIB, scope, 0)
    qm.quarantine(l1, "slow_cuda")
    with pytest.raises(QuarantineExhaustedError):
        qm.quarantine(l2, "exceeds_byte_cap")
    assert qm.reclaim("l1") is True
    assert qm.active_bytes == 0

