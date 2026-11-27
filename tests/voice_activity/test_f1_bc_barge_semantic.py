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

import math
import threading

import numpy as np
import pytest

from backend.core.contracts.audio import AudioEncoding, AudioFormat, AudioFrame
from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, GenerationRef, StreamDirection, StreamRef, TurnRef
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.result_admission import AdmissionStatus, BoundedMediaQueue, QueuedMediaItem
from backend.core.runtime.turn_generation import PauseController, PauseRef, PauseState
from backend.voice_activity import (
    AcousticEvidence,
    BackchannelCategory,
    ContinuationCue,
    EchoAcousticCategory,
    EndpointAdviceKind,
    ExpectedSlotCategory,
    ExpectedSlotProjection,
    F1BPolicyConfig,
    F1CProfileConfig,
    F1ProfileConfig,
    F1RouteMode,
    FlushIntent,
    InputCandidateRef,
    InterruptionAdviceKind,
    InterruptionController,
    InterruptionState,
    M02PauseBridge,
    OutputAvailability,
    OutputTargetSnapshot,
    SemanticEndpointHint,
    SemanticEndpointPolicy,
    StreamAcousticProcessor,
    classify_turkish_cues,
    quantize_max_windows,
    quantize_min_windows,
    turkish_casefold,
)
from backend.voice_activity.utterance_manager import TurnAllocatorProtocol
from backend.voice_activity.vad_engine import VADEngineAdapter


class FakeMonotonicClock:
    def __init__(self, initial_ns: int = 0, clock_domain: str = "fake") -> None:
        self._now_ns = initial_ns
        self.clock_domain = clock_domain

    def monotonic_ns(self) -> int:
        return self._now_ns

    def advance_ms(self, ms: int) -> int:
        self._now_ns += ms * 1_000_000
        return self._now_ns


class _FakeClockAllocator(TurnAllocatorProtocol):
    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._n = 0

    def is_stream_active(self) -> bool:
        return True

    def allocate_turn(self) -> TurnRef:
        self._n += 1
        return TurnRef(self._session_id, self._n)


class _ScriptedVAD:
    model_revision = "scripted-test-v1"

    def __init__(self, scores: list[float]) -> None:
        self._scores = list(scores)

    def initial_state(self) -> int:
        return 0

    def infer_with_state(self, samples_f32: np.ndarray, sample_rate_hz: int, state: int) -> tuple[float, int]:
        s = self._scores[state] if state < len(self._scores) else 0.1
        return s, state + 1


def _make_candidate(
    session_id: str = "sess-1",
    incarnation_id: str = "inc-1",
    stream_id: str = "in-1",
    epoch: int = 1,
    start_sample: int = 5120,
    seq: int = 1,
) -> InputCandidateRef:
    return InputCandidateRef(
        session_id=session_id,
        incarnation_id=incarnation_id,
        stream_ref=StreamRef(session_id, stream_id, StreamDirection.INPUT, epoch),
        start_sample=start_sample,
        sequence=seq,
    )


def _make_target(
    session_id: str = "sess-1",
    turn_id: int = 1,
    gen_id: int = 1,
    availability: OutputAvailability = OutputAvailability.LOCAL_QUEUED,
    in_flight: bool = False,
    drained: bool = False,
) -> OutputTargetSnapshot:
    return OutputTargetSnapshot(
        generation_ref=GenerationRef(session_id, turn_id, gen_id),
        plan_revision=0,
        availability=availability,
        queued_items=2 if availability == OutputAvailability.LOCAL_QUEUED else 0,
        queued_bytes=1280 if availability == OutputAvailability.LOCAL_QUEUED else 0,
        in_flight_submitted=in_flight,
        drained=drained,
        can_gate=True,
    )


# ---------------------------------------------------------------------------
# F1-B Barge-in & Interruption Control Tests
# ---------------------------------------------------------------------------


def test_f1b_ineligible_targets_do_not_pause() -> None:
    clock = FakeMonotonicClock(1_000_000_000)
    pause_ctrl = PauseController()
    ctrl = InterruptionController("sess-1", "inc-1", M02PauseBridge(pause_ctrl), clock=clock)
    cand = _make_candidate()

    # No live output -> IDLE, no pause
    out1 = ctrl.on_speech_candidate(cand, None)
    assert out1.state == InterruptionState.IDLE
    assert out1.action_taken == "NO_PAUSE"
    assert pause_ctrl.state == PauseState.RUNNING

    # Drained terminal -> REJECTED, no pause
    drained_target = _make_target(availability=OutputAvailability.DRAINED_TERMINAL, drained=True)
    out2 = ctrl.on_speech_candidate(cand, drained_target)
    assert out2.state == InterruptionState.REJECTED
    assert pause_ctrl.state == PauseState.RUNNING

    # Synthesis pending without playback -> REJECTED under default policy
    synth_target = _make_target(availability=OutputAvailability.SYNTHESIS_PENDING)
    out3 = ctrl.on_speech_candidate(cand, synth_target)
    assert out3.state == InterruptionState.REJECTED
    assert pause_ctrl.state == PauseState.RUNNING


def test_f1b_two_stage_soft_pause_and_resume_same_generation() -> None:
    clock = FakeMonotonicClock(1_000_000_000)
    pause_ctrl = PauseController()
    root = CancellationScope("sess:1", clock=clock)
    gen_scope = root.child_scope("gen:1")
    ctrl = InterruptionController("sess-1", "inc-1", M02PauseBridge(pause_ctrl), clock=clock)

    cand1 = _make_candidate(start_sample=5120, seq=1)
    target = _make_target(availability=OutputAvailability.LOCAL_QUEUED, in_flight=True)

    # Stage 1: soft pause
    out1 = ctrl.on_speech_candidate(cand1, target, gen_scope)
    assert out1.state == InterruptionState.SOFT_PAUSED
    assert out1.pause_ref is not None
    assert out1.in_flight_possible is True
    assert out1.in_flight_recall_claimed is False
    assert pause_ctrl.state == PauseState.SOFT_PAUSED
    first_epoch = out1.pause_ref.pause_epoch

    # Duplicate candidate before deadline -> no-op, deadline unchanged
    clock.advance_ms(50)
    dup = ctrl.on_speech_candidate(cand1, target, gen_scope)
    assert dup.action_taken == "NOOP_DUPLICATE_CANDIDATE"
    assert ctrl.active_attempt is not None
    assert ctrl.active_attempt.deadline_monotonic_ns == 1_250_000_000

    # Stage 2: false candidate rejected before deadline -> resume same generation
    clock.advance_ms(50)  # +100ms total < 250ms
    res = ctrl.on_candidate_rejected(cand1, gen_scope, cursor_intact=True)
    assert res.state == InterruptionState.RESUMED
    assert pause_ctrl.state == PauseState.RUNNING

    # Same generation can receive a new attempt with strictly new pause_epoch
    cand2 = _make_candidate(start_sample=10240, seq=2)
    out2 = ctrl.on_speech_candidate(cand2, target, gen_scope)
    assert out2.state == InterruptionState.SOFT_PAUSED
    assert out2.pause_ref is not None
    assert out2.pause_ref.pause_epoch > first_epoch

    # Old pause_ref cannot ABA-resume the new epoch
    assert pause_ctrl.resume(out1.pause_ref, target.generation_ref, gen_scope) is False


def test_f1b_deferred_pause_ack_and_confirmed_commit_before_ack() -> None:
    clock = FakeMonotonicClock(2_000_000_000)
    pause_ctrl = PauseController()
    flushes: list[FlushIntent] = []
    bridge = M02PauseBridge(pause_ctrl, on_flush_intent=flushes.append)
    root = CancellationScope("sess:1", clock=clock)
    gen_scope = root.child_scope("gen:1")
    queue = BoundedMediaQueue(max_items=8, max_bytes=4096)
    gen_ref = GenerationRef("sess-1", 1, 1)
    queue.enqueue(QueuedMediaItem(gen_ref, 1, b"abcd", 0))
    queue.enqueue(QueuedMediaItem(gen_ref, 2, b"efgh", 0))

    ctrl = InterruptionController("sess-1", "inc-1", bridge, clock=clock)
    cand = _make_candidate()
    target = _make_target(in_flight=True)

    out1 = ctrl.on_speech_candidate(cand, target, gen_scope, defer_pause_ack=True)
    assert out1.state == InterruptionState.PAUSE_REQUESTED

    # Confirmed onset arrives BEFORE remote/downstream pause ack -> immediate atomic commit
    out2 = ctrl.on_speech_confirmed(cand, gen_scope, queue=queue, reason="confirmed_onset")
    assert out2.state == InterruptionState.COMMITTED
    assert out2.local_purged_items == 2
    assert out2.in_flight_recall_claimed is False
    assert out2.in_flight_possible is True
    assert gen_scope.is_cancel_requested is True
    assert queue.item_count == 0
    assert len(flushes) == 1
    assert flushes[0].requested_scope == "SERVER"
    assert flushes[0].in_flight_recall_claimed is False

    # Late rejection after commit cannot roll back
    late_rej = ctrl.on_candidate_rejected(cand, gen_scope)
    assert late_rej.state == InterruptionState.COMMITTED
    assert gen_scope.is_cancel_requested is True


def test_f1b_deadline_timeout_aborts_and_blocks_late_resume() -> None:
    clock = FakeMonotonicClock(5_000_000_000)
    pause_ctrl = PauseController()
    root = CancellationScope("sess:1", clock=clock)
    gen_scope = root.child_scope("gen:1")
    ctrl = InterruptionController(
        "sess-1",
        "inc-1",
        M02PauseBridge(pause_ctrl),
        policy=F1BPolicyConfig(pause_deadline_ms=250),
        clock=clock,
    )
    cand = _make_candidate()
    target = _make_target()

    ctrl.on_speech_candidate(cand, target, gen_scope)
    assert ctrl.state == InterruptionState.SOFT_PAUSED

    # Advance to exact deadline (now >= deadline)
    clock.advance_ms(250)
    tick = ctrl.on_deadline_tick(gen_scope)
    assert tick is not None
    assert tick.state == InterruptionState.ABORTED
    assert tick.reason == "PAUSE_TIMEOUT"
    assert gen_scope.is_cancel_requested is True

    # Rejection after timeout cannot resume
    rej = ctrl.on_candidate_rejected(cand, gen_scope)
    assert rej.state == InterruptionState.ABORTED


def test_f1b_barrier_race_commit_vs_reject_and_session_isolation() -> None:
    clock = FakeMonotonicClock(1_000_000_000)
    pause_a = PauseController()
    pause_b = PauseController()
    root_a = CancellationScope("sess:A", clock=clock)
    root_b = CancellationScope("sess:B", clock=clock)
    gen_a = root_a.child_scope("gen:1")
    gen_b = root_b.child_scope("gen:1")

    ctrl_a = InterruptionController("sess-A", "inc-A", M02PauseBridge(pause_a), clock=clock)
    ctrl_b = InterruptionController("sess-B", "inc-B", M02PauseBridge(pause_b), clock=clock)

    cand_a = _make_candidate(session_id="sess-A", incarnation_id="inc-A")
    target_a = _make_target(session_id="sess-A")
    ctrl_a.on_speech_candidate(cand_a, target_a, gen_a)

    barrier = threading.Barrier(2)
    results: list[InterruptionState] = []

    def do_commit() -> None:
        barrier.wait(timeout=2.0)
        results.append(ctrl_a.on_speech_confirmed(cand_a, gen_a).state)

    def do_reject() -> None:
        barrier.wait(timeout=2.0)
        results.append(ctrl_a.on_candidate_rejected(cand_a, gen_a).state)

    t1 = threading.Thread(target=do_commit)
    t2 = threading.Thread(target=do_reject)
    t1.start()
    t2.start()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    # Exactly one winner linearized; session B completely untouched
    assert len(results) == 2
    assert ctrl_b.state == InterruptionState.IDLE
    assert gen_b.is_cancel_requested is False


# ---------------------------------------------------------------------------
# F1-C Semantic Endpoint, Backchannel & Double-Talk Tests
# ---------------------------------------------------------------------------


def test_f1c_profile_quantization_and_validation() -> None:
    assert quantize_min_windows(250) == 8  # 8 * 32 = 256 ms
    assert quantize_max_windows(1200) == 37  # 37 * 32 = 1184 ms

    cfg = F1CProfileConfig(mode=F1RouteMode.STRICT, min_budget_ms=250, base_budget_ms=320, max_budget_ms=1200)
    assert cfg.min_budget_samples == 8 * 512
    assert cfg.max_budget_samples == 37 * 512

    with pytest.raises(ValueError):
        F1CProfileConfig(post_roll_samples=5000, min_budget_ms=256)

    with pytest.raises(ValueError):
        F1CProfileConfig(hint_ttl_ms=True)  # type: ignore[arg-type]


def test_f1c_turkish_cues_and_confirmation_slot_guard() -> None:
    assert turkish_casefold("İPTAL VE IŞIK") == "iptal ve ışık"
    assert classify_turkish_cues("randevu almak istiyorum ve") == ContinuationCue.POSSIBLE_CONTINUATION
    assert classify_turkish_cues("hayır") == ContinuationCue.CORRECTION_OR_NEGATION
    assert classify_turkish_cues("bir dakika lütfen") == ContinuationCue.EXPLICIT_INTERRUPT_CUE

    time_ctx = ExpectedSlotProjection(
        context_revision=1,
        workflow_stage="slot_fill",
        expected_slot=ExpectedSlotCategory.DATE_TIME,
        prompt_role="ask_time",
        confirmation_pending=False,
        prompt_presented=True,
        issued_monotonic_ns=1_000_000,
        ttl_ms=60000,
        clock_domain="fake",
        subject_scope_id="subj-1",
    )
    assert classify_turkish_cues("saat on dört", context=time_ctx) == ContinuationCue.INCOMPLETE_EXPECTED_SLOT

    confirm_ctx = ExpectedSlotProjection(
        context_revision=2,
        workflow_stage="confirm",
        expected_slot=ExpectedSlotCategory.SHORT_CONFIRMATION,
        prompt_role="confirm_booking",
        confirmation_pending=True,
        prompt_presented=True,
        issued_monotonic_ns=1_000_000,
        ttl_ms=60000,
        clock_domain="fake",
        subject_scope_id="subj-1",
    )
    # In confirmation slot, "evet" is meaningful completion, NOT mere backchannel
    assert classify_turkish_cues("evet", context=confirm_ctx) == ContinuationCue.POSSIBLE_COMPLETION


def test_f1c_semantic_endpoint_extension_ttl_and_deadline_cap() -> None:
    clock = FakeMonotonicClock(1_000_000_000)
    sref = StreamRef("sess-1", "in-1", StreamDirection.INPUT, 1)
    cfg = F1CProfileConfig(mode=F1RouteMode.STRICT, base_budget_ms=320, max_budget_ms=1200, semantic_wait_deadline_ms=1200)
    policy = SemanticEndpointPolicy(cfg, sref, clock=clock)
    policy.set_speech_scope("scope-1")

    hint = SemanticEndpointHint(
        hint_id="h1",
        speech_scope_id="scope-1",
        stream_ref=sref,
        revision=1,
        covered_end_sample_exclusive=16000,
        observed_monotonic_ns=clock.monotonic_ns(),
        ttl_ms=750,
        clock_domain=clock.clock_domain,
        provisional_text="yarın gelmek istiyorum ama",
    )
    assert policy.ingest_hint(hint) is True

    # At 320ms (5120 low samples), continuation cue extends budget -> WAIT
    adv1 = policy.evaluate_silence_pending(
        low_run_start_sample=16000,
        low_run_real_samples=5120,
        last_real_sample=21120,
    )
    assert adv1.kind == EndpointAdviceKind.WAIT
    assert adv1.effective_silence_samples > 5120
    assert adv1.actionable_for_business is False

    # Repeated hint at +500ms does NOT reset semantic_wait_deadline_ms
    clock.advance_ms(500)
    hint2 = SemanticEndpointHint(
        hint_id="h2",
        speech_scope_id="scope-1",
        stream_ref=sref,
        revision=2,
        covered_end_sample_exclusive=16000,
        observed_monotonic_ns=clock.monotonic_ns(),
        ttl_ms=750,
        clock_domain=clock.clock_domain,
        provisional_text="yarın gelmek istiyorum ama",
    )
    policy.ingest_hint(hint2)
    adv2 = policy.evaluate_silence_pending(
        low_run_start_sample=16000,
        low_run_real_samples=10240,
        last_real_sample=26240,
    )
    assert adv2.kind == EndpointAdviceKind.WAIT

    # Advance past 1200ms semantic wait deadline -> extension removed, base 5120 met -> FINALIZE
    clock.advance_ms(700)
    adv3 = policy.evaluate_silence_pending(
        low_run_start_sample=16000,
        low_run_real_samples=10240,
        last_real_sample=26240,
    )
    assert adv3.kind == EndpointAdviceKind.FINALIZE
    assert adv3.reason == "semantic_wait_deadline_expired"


def test_f1c_double_talk_and_echo_only_advice() -> None:
    clock = FakeMonotonicClock(1_000_000_000)
    sref = StreamRef("sess-1", "in-1", StreamDirection.INPUT, 1)
    cfg = F1CProfileConfig(
        mode=F1RouteMode.STRICT,
        enable_echo_rejection=True,
        enable_backchannel_rejection=True,
    )
    policy = SemanticEndpointPolicy(cfg, sref, clock=clock)

    # Double-talk -> COMMIT_ELIGIBLE
    policy.ingest_acoustic_evidence(
        AcousticEvidence(
            evidence_id="ev-dt",
            stream_ref=sref,
            start_sample=0,
            end_sample_exclusive=512,
            sample_rate_hz=16000,
            observed_monotonic_ns=clock.monotonic_ns(),
            clock_domain=clock.clock_domain,
            category=EchoAcousticCategory.DOUBLE_TALK_LIKELY,
        )
    )
    adv_dt = policy.advise_interruption(window_start_sample=0, window_end_sample_exclusive=512, has_active_output=True)
    assert adv_dt.kind == InterruptionAdviceKind.COMMIT_ELIGIBLE
    assert adv_dt.business_approval is False

    # Reliable far-end echo only -> RESUME_ELIGIBLE
    policy.ingest_acoustic_evidence(
        AcousticEvidence(
            evidence_id="ev-echo",
            stream_ref=sref,
            start_sample=512,
            end_sample_exclusive=1024,
            sample_rate_hz=16000,
            observed_monotonic_ns=clock.monotonic_ns(),
            clock_domain=clock.clock_domain,
            category=EchoAcousticCategory.FAR_END_ONLY_LIKELY,
            reference_valid=True,
            alignment_valid=True,
            history_sufficient=True,
        )
    )
    adv_echo = policy.advise_interruption(window_start_sample=512, window_end_sample_exclusive=1024, has_active_output=True)
    assert adv_echo.kind == InterruptionAdviceKind.RESUME_ELIGIBLE
    assert adv_echo.backchannel_category == BackchannelCategory.ECHO_ONLY_LIKELY


def test_f1c_pipeline_integration_silence_pending_adaptive_extension() -> None:
    clock = FakeMonotonicClock(1_000_000_000)
    sref = StreamRef("sess-pipe", "in-1", StreamDirection.INPUT, 1)
    fmt = AudioFormat(16000, 1, AudioEncoding.PCM_S16LE)
    f1_profile = F1ProfileConfig.strict_experimental(route_mode=F1RouteMode.STRICT)
    f1c_profile = F1CProfileConfig(mode=F1RouteMode.STRICT, base_budget_ms=320, max_budget_ms=1200)
    f1c_policy = SemanticEndpointPolicy(f1c_profile, sref, clock=clock)

    # 3 high windows (speech), then 12 low windows (384ms > 320ms base, < 1152ms continuation)
    scores = [0.85, 0.85, 0.85] + [0.10] * 12
    vad = VADEngineAdapter(_ScriptedVAD(scores), clock=clock)
    proc = StreamAcousticProcessor(
        sref,
        profile=f1_profile,
        config_revision="rev-1",
        vad_engine=vad,
        turn_allocator=_FakeClockAllocator("sess-pipe"),
        clock=clock,
        f1c_policy=f1c_policy,
    )

    # Feed 3 speech windows (32ms each = 512 samples)
    pcm = (np.ones(512, dtype=np.int16) * 1000).tobytes()
    for i in range(3):
        frame = AudioFrame(CONTRACT_SCHEMA_VERSION, sref, i, fmt, 512, i * 512, pcm)
        proc.process_frame(frame)

    # Ingest fresh continuation hint before low run reaches 320ms
    f1c_policy.ingest_hint(
        SemanticEndpointHint(
            hint_id="h-pipe",
            speech_scope_id="scope-pipe",
            stream_ref=sref,
            revision=1,
            covered_end_sample_exclusive=1536,
            observed_monotonic_ns=clock.monotonic_ns(),
            ttl_ms=750,
            clock_domain=clock.clock_domain,
            cue=ContinuationCue.POSSIBLE_CONTINUATION,
        )
    )

    # Feed 10 low windows (320ms): normally F1-A would finalize at window 10,
    # but F1-C extends threshold so it stays SILENCE_PENDING!
    finals = []
    for i in range(3, 13):
        frame = AudioFrame(CONTRACT_SCHEMA_VERSION, sref, i, fmt, 512, i * 512, pcm)
        out = proc.process_frame(frame)
        finals.extend(out.finalizations)
    assert len(finals) == 0

    # Explicit EOS still finalizes immediately per F1-A precedence
    _, eos_finals = proc.flush_eos()
    assert len(eos_finals) == 1
    assert eos_finals[0].utterance.finalization_reason == "EXPLICIT_EOS"
