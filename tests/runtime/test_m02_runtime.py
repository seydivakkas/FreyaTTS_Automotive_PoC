"""M02 Session & Cancellation Runtime deterministic test suite (RT01-RT48 coverage)."""
from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from backend.core.contracts import GenerationRef, SessionIdentity
from backend.core.runtime import (
    AdmissionStatus,
    CancellationScope,
    CleanupStatus,
    DeadlineBudget,
    FakeClock,
    LeaseState,
    PauseState,
    QueuedMediaItem,
    SessionContext,
    SessionLifecycleState,
    SessionRegistry,
    StaleScopeError,
)


def test_rt01_safe_isolated_import():
    proc = subprocess.run(
        [sys.executable, "-c", "import sys, backend.core.runtime; assert 'torch' not in sys.modules and 'sqlalchemy' not in sys.modules"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.asyncio
async def test_rt02_to_rt08_registry_lifecycle_and_isolation():
    reg = SessionRegistry()
    s1 = await reg.create("sess-a", external_id="ext-1")
    s2 = await reg.create("sess-b", external_id="ext-2")
    assert s1.incarnation_id != s2.incarnation_id
    with pytest.raises(ValueError):
        await reg.create("sess-a")
    with pytest.raises(ValueError):
        await reg.create("sess-c", external_id="ext-1")

    # Partial setup failure cleans up once
    s_fail = SessionContext(SessionIdentity("sess-fail"))
    with pytest.raises(RuntimeError):
        await s_fail.open(setup_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert s_fail.lifecycle_state == SessionLifecycleState.CLOSED

    await s1.open()
    await s2.open()
    t1, _ = await s1.begin_turn()
    t2, _ = await s2.begin_turn()
    assert t1.turn_id == 1 and t2.turn_id == 1
    assert await reg.close_session("sess-a") == CleanupStatus.COMPLETE
    with pytest.raises(ValueError):
        await reg.create("sess-a")
    assert s2.lifecycle_state == SessionLifecycleState.ACTIVE


@pytest.mark.asyncio
async def test_rt09_to_rt14_turn_generation_and_supersession():
    ctx = SessionContext(SessionIdentity("sess-1"))
    await ctx.open()
    t1, t1_scope = await ctx.begin_turn()
    g1, g1_scope = await ctx.begin_generation(t1)
    g2, g2_scope = await ctx.begin_generation(t1)
    assert g2.generation_id == g1.generation_id + 1
    assert g1_scope.is_cancel_requested
    assert not g2_scope.is_cancel_requested

    t2, _ = await ctx.begin_turn()
    assert t2.turn_id == 2 and t1_scope.is_cancel_requested and g2_scope.is_cancel_requested
    assert await ctx.admit_media(QueuedMediaItem(g2, 0, b"\x00" * 320)) == AdmissionStatus.STALE_TURN
    g3, _ = await ctx.begin_generation(t2)
    assert await ctx.admit_media(QueuedMediaItem(g3, 0, b"\x00" * 320), expected_plan_revision=1) == AdmissionStatus.REVISION_MISMATCH


@pytest.mark.asyncio
async def test_rt15_to_rt19_hierarchical_cancellation():
    clock = FakeClock(100)
    root = CancellationScope("root", clock=clock)
    turn = root.child_scope("turn:1")
    gen = turn.child_scope("gen:1")
    assert root.request_cancel("hangup") is True
    assert root.request_cancel("duplicate") is False
    assert root.reason == "hangup" and root.cancelled_at_ns == 100
    assert turn.is_cancel_requested and gen.is_cancel_requested
    late = gen.child_scope("late")
    assert late.is_cancel_requested
    with pytest.raises(StaleScopeError):
        late.check_active()


@pytest.mark.asyncio
async def test_rt20_to_rt30_admission_races_backpressure_and_control_lane():
    ctx = SessionContext(SessionIdentity("sess-q"), max_queue_items=3, max_queue_bytes=960)
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    g1, _ = await ctx.begin_generation(t1)

    for seq in range(3):
        st = await ctx.admit_media(QueuedMediaItem(g1, seq, b"\x01" * 320))
        assert st == AdmissionStatus.ACCEPTED
    # Duplicate rejected
    assert await ctx.admit_media(QueuedMediaItem(g1, 0, b"\x01" * 320)) == AdmissionStatus.DUPLICATE
    # Media capacity full -> BACKPRESSURE, but control lane still admitted
    assert await ctx.admit_media(QueuedMediaItem(g1, 3, b"\x01" * 320)) == AdmissionStatus.BACKPRESSURE
    assert await ctx.admit_media(QueuedMediaItem(g1, 4, b"CTRL", is_control=True)) == AdmissionStatus.ACCEPTED

    st, popped = await ctx.dequeue_for_submission(g1)
    assert st == AdmissionStatus.ACCEPTED and popped.is_control

    # Cancel purges queued media and prevents stale submission
    assert await ctx.commit_interrupt("barge_in") is True
    st2, popped2 = await ctx.dequeue_for_submission(g1)
    assert st2 == AdmissionStatus.CANCELED and popped2 is None
    assert ctx.queue.item_count == 0


@pytest.mark.asyncio
async def test_rt31_to_rt37_pause_resume_commit_deadline_and_sink_failure():
    clock = FakeClock(1_000_000)

    def broken_sink(_env):
        raise RuntimeError("observer down")

    ctx = SessionContext(SessionIdentity("sess-p"), clock=clock, event_sink=broken_sink)
    await ctx.open()
    t1, _ = await ctx.begin_turn()
    g1, _ = await ctx.begin_generation(t1)
    assert await ctx.admit_media(QueuedMediaItem(g1, 0, b"\x02" * 320)) == AdmissionStatus.ACCEPTED

    pref = await ctx.soft_pause()
    assert pref is not None and ctx.pause.state == PauseState.SOFT_PAUSED
    assert (await ctx.dequeue_for_submission(g1))[0] == AdmissionStatus.PAUSED
    assert await ctx.resume_pause(pref) is True
    assert await ctx.resume_pause(pref) is False  # already running
    st, item = await ctx.dequeue_for_submission(g1)
    assert st == AdmissionStatus.ACCEPTED and item.sequence == 0

    budget = DeadlineBudget.from_now(clock, 10)
    clock.advance_ms(11)
    assert await ctx.admit_media(QueuedMediaItem(g1, 1, b"\x02" * 320), deadline=budget) == AdmissionStatus.DEADLINE_EXCEEDED


@pytest.mark.asyncio
async def test_rt38_to_rt44_close_quarantine_and_borrowed_models():
    ctx = SessionContext(SessionIdentity("sess-c"))
    await ctx.open()
    model_released = False

    def destroy_shared():
        nonlocal model_released
        model_released = True

    ctx.ledger.acquire("shared-whisper", "model", borrowed=True, release_fn=destroy_shared)
    ctx.ledger.acquire("native-job-1", "gpu_job", borrowed=False)
    ctx.ledger.mark_in_flight("native-job-1")

    gate = asyncio.Event()

    async def stubborn_worker():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await gate.wait()

    task = ctx.tasks.track(asyncio.create_task(stubborn_worker()))
    res1, res2 = await asyncio.gather(
        ctx.close("hangup", drain_timeout_sec=0.05),
        ctx.close("duplicate_hangup", drain_timeout_sec=0.05),
    )
    assert res1 == CleanupStatus.PENDING_RECLAIM and res2 == CleanupStatus.PENDING_RECLAIM
    assert ctx.lifecycle_state == SessionLifecycleState.CLOSED
    assert ctx.ledger.quarantined_count == 1
    assert model_released is False
    gate.set()
    await task


@pytest.mark.asyncio
async def test_rt48_100_cycle_synthetic_replay():
    clock = FakeClock(0)
    reg = SessionRegistry(clock=clock)
    for i in range(100):
        sid = f"replay-{i}"
        ctx = await reg.create(sid)
        await ctx.open()
        t1, _ = await ctx.begin_turn()
        g1, _ = await ctx.begin_generation(t1)
        assert await ctx.admit_media(QueuedMediaItem(g1, 0, b"\x00" * 320)) == AdmissionStatus.ACCEPTED
        await ctx.commit_interrupt("replay_cancel")
        assert await reg.close_session(sid) == CleanupStatus.COMPLETE
        clock.advance_ms(20)
