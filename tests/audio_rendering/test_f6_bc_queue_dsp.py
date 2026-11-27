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
import math
import threading

import numpy as np
import pytest

from backend.audio_rendering import (
    AdaptiveCrossfadeAssembler,
    AudioRenderingPipeline,
    BoundaryRef,
    BoundedPlaybackQueue,
    CapacityBudget,
    CodecCapabilityStatus,
    CodecKind,
    CodecTrial,
    CodecTrialSpec,
    EnhancedDSPProcessor,
    EnhancedDSPProfile,
    FlushIntent,
    GlobalCapacityCoordinator,
    MediaItemState,
    PauseTargetKind,
    PlaybackReferenceTap,
    RateOwner,
    ReferenceDeliveryState,
    ReservationStatus,
    SemanticPauseLedger,
    WSOLAAdapter,
    get_codec_capability,
    observe_boundary_silence,
    resolve_rate_ownership,
)
from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import GenerationRef, StreamDirection, StreamRef
from backend.core.contracts.playback import ObservationScope, PlaybackProfile, RenderedFrame
from backend.core.runtime.deadlines import FakeClock


def _make_gen(session_id: str = "s1", turn_id: int = 1, gen_id: int = 1) -> GenerationRef:
    return GenerationRef(session_id=session_id, turn_id=turn_id, generation_id=gen_id)


def _make_stream(session_id: str = "s1", stream_id: str = "out-0", epoch: int = 0) -> StreamRef:
    return StreamRef(
        session_id=session_id,
        stream_id=stream_id,
        direction=StreamDirection.OUTPUT,
        format_epoch=epoch,
    )


def _make_phone_frame(
    gen_ref: GenerationRef,
    stream_ref: StreamRef,
    seq: int,
    *,
    fill_byte: int = 1,
    terminal: bool = False,
) -> RenderedFrame:
    return RenderedFrame(
        generation_ref=gen_ref,
        stream_ref=stream_ref,
        sequence=seq,
        sample_offset=seq * 160,
        profile=PlaybackProfile.AUDIOSOCKET_8K_PCM16,
        format=AudioFormat(8000, 1, AudioEncoding.PCM_S16LE),
        frame_duration_ms=20.0,
        sample_count=160,
        valid_sample_count=160,
        payload=bytes([fill_byte]) * 320,
        terminal=terminal,
    )


# ---------------------------------------------------------------------------
# F6-B Tests: Capacity, Backpressure, Cursor, Pause/Flush, Reference Tap
# ---------------------------------------------------------------------------


def test_passive_imports_no_thread_or_side_effects() -> None:
    before = threading.active_count()
    import backend.audio_rendering as ar

    assert hasattr(ar, "BoundedPlaybackQueue")
    assert hasattr(ar, "PlaybackReferenceTap")
    assert hasattr(ar, "WSOLAAdapter")
    assert hasattr(ar, "CodecTrial")
    assert threading.active_count() == before


def test_capacity_budget_validation_rejects_invalid_configs() -> None:
    with pytest.raises(ValueError):
        CapacityBudget(max_frames=0)
    with pytest.raises(ValueError):
        CapacityBudget(max_frames=3, high_watermark_frames=4, low_watermark_frames=1)
    with pytest.raises(ValueError):
        CapacityBudget(max_frames=3, high_watermark_frames=2, low_watermark_frames=2)
    with pytest.raises(ValueError):
        CapacityBudget(max_frames=True)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_reservation_too_large_and_idempotent_release() -> None:
    clock = FakeClock()
    gref = _make_gen()
    sref = _make_stream()
    budget = CapacityBudget(
        max_frames=3,
        max_target_samples=480,
        max_payload_bytes=960,
        max_workspace_bytes=4096,
        high_watermark_frames=3,
        low_watermark_frames=1,
    )
    q = BoundedPlaybackQueue(
        session_id="s1",
        incarnation_id="inc-1",
        stream_ref=sref,
        budget=budget,
        clock=clock,
    )
    q.set_active_generation(gref)

    too_big = q.try_reserve(
        generation_ref=gref,
        frames=4,
        target_samples=640,
        payload_bytes=1280,
    )
    assert too_big.status == ReservationStatus.REJECTED_TOO_LARGE

    res = q.try_reserve(
        generation_ref=gref,
        frames=2,
        target_samples=320,
        payload_bytes=640,
        workspace_bytes=1024,
    )
    assert res.status == ReservationStatus.RESERVED
    assert q.occupied_frames == 2
    assert await q.release_reservation(res.reservation_id) is True
    assert await q.release_reservation(res.reservation_id) is False
    assert q.occupied_frames == 0


@pytest.mark.asyncio
async def test_global_capacity_coordinator_across_two_sessions() -> None:
    clock = FakeClock()
    coord = GlobalCapacityCoordinator(max_total_frames=3, max_total_bytes=960)
    b1 = CapacityBudget(max_frames=3, max_target_samples=480, max_payload_bytes=960, high_watermark_frames=3, low_watermark_frames=1)

    q1 = BoundedPlaybackQueue(session_id="s1", incarnation_id="i1", stream_ref=_make_stream("s1"), budget=b1, clock=clock, global_coordinator=coord)
    q2 = BoundedPlaybackQueue(session_id="s2", incarnation_id="i2", stream_ref=_make_stream("s2"), budget=b1, clock=clock, global_coordinator=coord)
    g1, g2 = _make_gen("s1"), _make_gen("s2")
    q1.set_active_generation(g1)
    q2.set_active_generation(g2)

    r1 = q1.try_reserve(generation_ref=g1, frames=2, target_samples=320, payload_bytes=640)
    assert r1.status == ReservationStatus.RESERVED
    r2_fail = q2.try_reserve(generation_ref=g2, frames=2, target_samples=320, payload_bytes=640)
    assert r2_fail.status == ReservationStatus.REJECTED_BACKPRESSURE
    r2_ok = q2.try_reserve(generation_ref=g2, frames=1, target_samples=160, payload_bytes=320)
    assert r2_ok.status == ReservationStatus.RESERVED


@pytest.mark.asyncio
async def test_watermark_backpressure_wake_and_waiter_cap() -> None:
    clock = FakeClock()
    gref = _make_gen()
    sref = _make_stream()
    budget = CapacityBudget(
        max_frames=3,
        max_target_samples=480,
        max_payload_bytes=960,
        high_watermark_frames=2,
        low_watermark_frames=1,
        max_waiters_per_stream=1,
    )
    q = BoundedPlaybackQueue(session_id="s1", incarnation_id="i1", stream_ref=sref, budget=budget, clock=clock)
    q.set_active_generation(gref)

    r1 = q.try_reserve(generation_ref=gref, frames=2, target_samples=320, payload_bytes=640)
    assert r1.status == ReservationStatus.RESERVED
    f0 = _make_phone_frame(gref, sref, 0)
    f1 = _make_phone_frame(gref, sref, 1)
    ok, _ = await q.convert_and_enqueue(r1.reservation_id, [f0, f1])
    assert ok is True

    # Above high watermark: waiter 1 blocks, waiter 2 rejected by max_waiters_per_stream=1
    w1_task = asyncio.create_task(
        q.await_reserve(generation_ref=gref, frames=1, target_samples=160, payload_bytes=320, timeout_sec=1.0)
    )
    await asyncio.sleep(0)
    w2_res = await q.await_reserve(generation_ref=gref, frames=1, target_samples=160, payload_bytes=320, timeout_sec=0.1)
    assert w2_res.status == ReservationStatus.REJECTED_WAITERS_EXCEEDED

    # Drain 1 frame down to low_watermark=1 -> wakes waiter 1
    entry = q.select_next_unsent()
    assert entry is not None
    q.mark_selected_claimed("claim-0")
    await q.mark_claim_completed_local("claim-0")

    w1_res = await w1_task
    assert w1_res.status == ReservationStatus.RESERVED


@pytest.mark.asyncio
async def test_exact_unsent_cursor_and_no_rewind_on_late_ack() -> None:
    clock = FakeClock()
    gref = _make_gen()
    sref = _make_stream()
    budget = CapacityBudget(max_frames=4, max_target_samples=640, max_payload_bytes=1280, high_watermark_frames=4, low_watermark_frames=1)
    q = BoundedPlaybackQueue(session_id="s1", incarnation_id="i1", stream_ref=sref, budget=budget, clock=clock)
    q.set_active_generation(gref)

    res = q.try_reserve(generation_ref=gref, frames=3, target_samples=480, payload_bytes=960)
    frames = [_make_phone_frame(gref, sref, i) for i in range(3)]
    ok, _ = await q.convert_and_enqueue(res.reservation_id, frames)
    assert ok is True

    sel0 = q.select_next_unsent()
    assert sel0 is not None and sel0.state == MediaItemState.SELECTED_UNSENT
    # Selected-but-unclaimed does not advance cursor yet
    assert q.cursor.next_never_claimed_sequence == 0

    q.mark_selected_claimed("c0")
    assert q.cursor.next_never_claimed_sequence == 1
    assert q.cursor.in_flight_sequences == {0}

    sel1 = q.select_next_unsent()
    assert sel1 is not None
    q.mark_selected_claimed("c1")
    assert q.cursor.next_never_claimed_sequence == 2

    # Late ACK for seq 0 never rewinds cursor
    q.record_receiver_ack(0)
    assert q.cursor.next_never_claimed_sequence == 2

    # Unknown delivery on c1 keeps seq 1 out of replay
    await q.mark_claim_unknown_delivery("c1")
    assert 1 in q.cursor.unknown_in_flight_sequences
    assert q.cursor.next_never_claimed_sequence == 2


@pytest.mark.asyncio
async def test_scoped_flush_receipt_separates_local_from_remote_and_inflight() -> None:
    clock = FakeClock()
    gref = _make_gen()
    sref = _make_stream()
    budget = CapacityBudget(max_frames=4, max_target_samples=640, max_payload_bytes=1280, high_watermark_frames=4, low_watermark_frames=1)
    q = BoundedPlaybackQueue(session_id="s1", incarnation_id="i1", stream_ref=sref, budget=budget, clock=clock)
    q.set_active_generation(gref)

    res = q.try_reserve(generation_ref=gref, frames=3, target_samples=480, payload_bytes=960)
    frames = [_make_phone_frame(gref, sref, i) for i in range(3)]
    await q.convert_and_enqueue(res.reservation_id, frames)

    # Claim seq 0 (in-flight), leave seq 1 & 2 unsent
    q.select_next_unsent()
    q.mark_selected_claimed("c0")

    intent = FlushIntent(
        command_id="cmd-1",
        session_id="s1",
        incarnation_id="i1",
        generation_ref=gref,
        plan_revision=0,
        stream_ref=sref,
        reason="barge_in",
        created_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
    )
    receipt = await q.purge_unsent_generation(intent, remote_scope=ObservationScope.PBX, remote_supported=False)
    assert receipt.local.scope == ObservationScope.SERVER
    assert receipt.local.status == "FLUSHED"
    assert receipt.local.purged_frames == 2
    assert receipt.local.purged_payload_bytes == 640
    assert receipt.local.purged_valid_samples == 320
    assert receipt.remote.scope == ObservationScope.PBX
    assert receipt.remote.status == "UNSUPPORTED"
    assert receipt.remote.purged_frames is None
    assert receipt.in_flight_sequences == (0,)
    assert receipt.audible_silence_verified is False


def test_playback_reference_tap_isolation_eviction_and_privacy() -> None:
    gref = _make_gen("s1")
    sref = _make_stream("s1", "out-0", epoch=1)
    tap = PlaybackReferenceTap(session_id="s1", stream_id="out-0", format_epoch=1, max_frames=2, max_bytes=640)

    for seq in range(3):
        f = _make_phone_frame(gref, sref, seq, fill_byte=seq + 10)
        ref = tap.record_claim(claim_id=f"c{seq}", frame=f, claim_ns=1000 + seq, clock_domain="FAKE_MONOTONIC")
        assert ref is not None
        # Privacy: repr must not leak raw PCM bytes
        assert repr(ref).find("\\x0") == -1

    assert tap.frame_count == 2
    assert tap.evicted_frames == 1
    assert tap.evicted_bytes == 320

    tap.update_delivery_state("c2", ReferenceDeliveryState.COMPLETED_LOCAL)
    ok_res = tap.read_range(session_id="s1", stream_id="out-0", format_epoch=1, start_sample=0, end_sample=480)
    assert len(ok_res.spans) == 2
    assert ok_res.spans[0].sequence == 1
    assert ok_res.spans[1].delivery_state == ReferenceDeliveryState.COMPLETED_LOCAL
    assert any(g.reason == "MISSING_OR_EVICTED_SPAN" for g in ok_res.gaps)

    # Cross-session read rejected
    bad_res = tap.read_range(session_id="s2", stream_id="out-0", format_epoch=1, start_sample=0, end_sample=480)
    assert bad_res.unavailable_reason == "SESSION_OR_EPOCH_MISMATCH"
    assert bad_res.spans == ()


# ---------------------------------------------------------------------------
# F6-C Tests: Rate/WSOLA, Crossfade, Pause Ledger, Enhanced DSP, Codec Lab
# ---------------------------------------------------------------------------


def test_rate_ownership_no_double_apply_and_no_silent_clamp() -> None:
    d_f5 = resolve_rate_ownership(control_id="k1", requested_speed=1.05, model_applied_speed=1.05, wsola_enabled=True)
    assert d_f5.owner == RateOwner.F5
    assert d_f5.planned_factor == 1.0

    d_oob = resolve_rate_ownership(control_id="k2", requested_speed=0.90, model_applied_speed=None, wsola_enabled=True)
    assert d_oob.owner == RateOwner.NONE
    assert d_oob.reason == "OUTSIDE_WSOLA_RANGE"

    d_f6 = resolve_rate_ownership(control_id="k3", requested_speed=0.95, model_applied_speed=None, wsola_enabled=True)
    assert d_f6.owner == RateOwner.F6
    assert d_f6.renderer_applied_factor == 0.95


def test_wsola_unity_bypass_and_bounded_scaling() -> None:
    wsola = WSOLAAdapter()
    t = np.arange(19200, dtype=np.float32) / 48000.0
    sig = (0.3 * np.sin(2.0 * math.pi * 220.0 * t)).astype(np.float32)

    bypass = wsola.process_chunk(sig, factor=1.0)
    assert np.array_equal(bypass, sig)

    wsola.reset()
    faster = wsola.process_chunk(sig, factor=1.05)
    tail = wsola.flush_eos()
    total_out = faster.size + tail.size
    assert total_out < sig.size
    assert abs(total_out - int(round(sig.size / 1.05))) <= 1200

    wsola.reset()
    slower = wsola.process_chunk(sig, factor=0.95)
    tail_s = wsola.flush_eos()
    assert (slower.size + tail_s.size) > sig.size

    with pytest.raises(ValueError):
        wsola.process_chunk(np.array([np.nan, 0.0], dtype=np.float32), factor=1.0)


def test_adaptive_crossfade_constant_sum_and_protected_bypass() -> None:
    asm = AdaptiveCrossfadeAssembler()
    left = np.full(2400, 0.25, dtype=np.float32)
    right = np.full(2400, 0.25, dtype=np.float32)

    out, dec = asm.assemble_boundary(left, right, BoundaryRef("b1", "c0", "c1"))
    assert dec.applied is True
    assert dec.actual_overlap_samples == 480
    assert out.size == 2400 + 2400 - 480
    assert np.allclose(out, 0.25, atol=1e-5)

    out_prot, dec_prot = asm.assemble_boundary(left, right, BoundaryRef("b2", "c1", "c2", protected_group=True))
    assert dec_prot.applied is False
    assert dec_prot.reason == "PROTECTED_GROUP_BYPASS"
    assert out_prot.size == 4800


def test_semantic_pause_ledger_credits_natural_silence_and_caps() -> None:
    left_tail = np.concatenate([np.full(2000, 0.2, dtype=np.float32), np.zeros(1920, dtype=np.float32)])
    right_head = np.concatenate([np.zeros(960, dtype=np.float32), np.full(2000, 0.2, dtype=np.float32)])
    obs = observe_boundary_silence(left_tail, right_head, rate_hz=48000)
    assert obs.left_trailing_samples == 1920
    assert obs.right_leading_samples == 960

    ledger = SemanticPauseLedger(rate_hz=48000, max_per_boundary_ms=320, max_total_plan_ms=1200)
    entry = ledger.plan_and_consume(
        boundary_id="b-1",
        requested_ms=160,
        target_kind=PauseTargetKind.TOTAL_BOUNDARY,
        observation=obs,
    )
    assert entry.target_samples == 7680
    assert entry.left_credited_samples == 1920
    assert entry.right_credited_samples == 960
    assert entry.inserted_samples == 4800

    # Duplicate boundary_id is idempotent no-op
    dup = ledger.plan_and_consume(boundary_id="b-1", requested_ms=160, observation=obs)
    assert dup.inserted_samples == 0
    assert dup.reason == "DUPLICATE_BOUNDARY_ID_NO_OP"


def test_enhanced_dsp_off_by_default_and_limiter_ceiling() -> None:
    off_proc = EnhancedDSPProcessor(EnhancedDSPProfile(enabled=False))
    x = np.array([0.5, -1.5, 1.5], dtype=np.float32)
    assert np.array_equal(off_proc.process_pre_resample_48k(x), x)

    on_proc = EnhancedDSPProcessor(
        EnhancedDSPProfile(
            enabled=True,
            deesser_enabled=True,
            eq_enabled=True,
            loudness_enabled=True,
            limiter_enabled=True,
            limiter_ceiling_dbfs=-1.0,
        )
    )
    t = np.arange(4800, dtype=np.float32) / 48000.0
    hot = (1.8 * np.sin(2.0 * math.pi * 1000.0 * t)).astype(np.float32)
    pre = on_proc.process_pre_resample_48k(hot)
    limited, pre_over = on_proc.process_post_resample_limiter(pre)
    ceiling = 10.0 ** (-1.0 / 20.0)
    assert pre_over > 0
    assert float(np.max(np.abs(limited))) <= ceiling + 1e-6


def test_codec_lab_g711_and_unsupported_codecs() -> None:
    trial = CodecTrial()
    t = np.arange(1600, dtype=np.float64) / 8000.0
    pcm = (0.4 * 32767.0 * np.sin(2.0 * math.pi * 500.0 * t)).astype(np.int16)

    res_ulaw = trial.run(pcm, CodecTrialSpec(trial_id="t1", codec=CodecKind.G711_PCMU, loss_rate=0.0, seed=9))
    assert res_ulaw.capability_status == CodecCapabilityStatus.VERIFIED
    assert res_ulaw.encoded_bytes == 1600
    assert res_ulaw.snr_db is not None and res_ulaw.snr_db > 25.0
    assert res_ulaw.live_transport_untouched is True

    res_alaw = trial.run(pcm, CodecTrialSpec(trial_id="t2", codec=CodecKind.G711_PCMA, loss_rate=0.2, seed=9))
    assert res_alaw.dropped_frames > 0

    g722_cap = get_codec_capability(CodecKind.G722_64K)
    assert g722_cap.pcm_rate_hz == 16000 and g722_cap.rtp_clock_hz == 8000
    res_g722 = trial.run(pcm, CodecTrialSpec(trial_id="t3", codec=CodecKind.G722_64K))
    assert res_g722.capability_status == CodecCapabilityStatus.UNSUPPORTED


@pytest.mark.asyncio
async def test_pipeline_f6_bc_pause_resume_and_commit_receipt() -> None:
    clock = FakeClock()
    pipe = AudioRenderingPipeline(
        session_id="sess-bc",
        trusted_channel="asterisk",
        clock=clock,
        max_queue_items=4,
        max_queue_bytes=1280,
    )
    gref = await pipe.start_generation()
    pref = await pipe.soft_pause()
    assert pref is not None
    assert pipe.playback_queue._paused is True
    assert await pipe.resume_pause(pref) is True
    assert pipe.playback_queue._paused is False

    receipt = await pipe.commit_interrupt_with_receipt(reason="user_barge_in")
    assert receipt.generation_ref == gref
    assert receipt.local.scope == ObservationScope.SERVER
    assert receipt.local.status == "FLUSHED"
    assert receipt.remote.status == "UNSUPPORTED"
    await pipe.close()
