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

import threading
from collections import deque
from typing import Callable

from backend.core.contracts.common import GenerationRef
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.core.runtime.result_admission import BoundedMediaQueue
from backend.core.runtime.turn_generation import PauseRef
from backend.voice_activity.interruption_contracts import (
    DecisionOutcome,
    F1BPolicyConfig,
    FlushIntent,
    InputCandidateRef,
    InterruptionAttempt,
    InterruptionState,
    OutputAvailability,
    OutputTargetSnapshot,
)
from backend.voice_activity.pause_bridge import M02PauseBridge


class InterruptionController:
    """
    F1-B two-stage acoustic barge-in decision orchestrator.

    State lifecycle:
    IDLE -> CANDIDATE_PENDING -> PAUSE_REQUESTED -> SOFT_PAUSED
         -> RESUMED | COMMITTED | ABORTED | REJECTED

    Invariants:
    - M02 PauseController + CancellationScope remain the authoritative output gate.
    - At most one active attempt per output generation.
    - Same generation may receive a new attempt after RESUMED with a strictly new pause_epoch.
    - Already COMMITTED or ABORTED attempts never roll back or resurrect old generations.
    - Never claims in-flight submitted audio was recalled.
    """

    def __init__(
        self,
        session_id: str,
        incarnation_id: str,
        pause_bridge: M02PauseBridge,
        *,
        policy: F1BPolicyConfig | None = None,
        clock: Clock | None = None,
        on_outcome: Callable[[DecisionOutcome], None] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._session_id = session_id
        self._incarnation_id = incarnation_id
        self._bridge = pause_bridge
        self._policy = policy or F1BPolicyConfig()
        self._clock: Clock = clock or SystemMonotonicClock()
        self._on_outcome = on_outcome

        self._state: InterruptionState = InterruptionState.IDLE
        self._active_attempt: InterruptionAttempt | None = None
        self._active_target: OutputTargetSnapshot | None = None
        self._attempt_seq: int = 0
        self._terminal_attempts: deque[InterruptionAttempt] = deque(
            maxlen=self._policy.max_retained_terminal_attempts
        )

    @property
    def state(self) -> InterruptionState:
        with self._lock:
            return self._state

    @property
    def active_attempt(self) -> InterruptionAttempt | None:
        with self._lock:
            return self._active_attempt

    @property
    def terminal_attempts(self) -> tuple[InterruptionAttempt, ...]:
        with self._lock:
            return tuple(self._terminal_attempts)

    def _emit_outcome(self, outcome: DecisionOutcome) -> DecisionOutcome:
        if self._on_outcome is not None:
            try:
                self._on_outcome(outcome)
            except Exception:
                # Telemetry/observer failure must never affect control decisions.
                pass
        return outcome

    def _is_eligible(self, candidate: InputCandidateRef, target: OutputTargetSnapshot | None) -> tuple[bool, str]:
        if not self._policy.enabled:
            return False, "f1b_disabled"
        if candidate.session_id != self._session_id or candidate.incarnation_id != self._incarnation_id:
            return False, "stale_session_or_incarnation"
        if target is None:
            return False, "no_live_output"
        if target.generation_ref.session_id != self._session_id:
            return False, "cross_session_target_rejected"
        if target.drained or target.availability == OutputAvailability.DRAINED_TERMINAL:
            return False, "output_drained_terminal"
        if target.availability == OutputAvailability.NONE:
            return False, "no_live_output"
        if target.availability == OutputAvailability.SYNTHESIS_PENDING and not self._policy.allow_synthesis_pending_pause:
            return False, "synthesis_pending_not_gated"
        if not target.can_gate:
            return False, "target_not_gateable"
        return True, "eligible"

    def _retire_active(self, attempt: InterruptionAttempt) -> None:
        self._terminal_attempts.append(attempt)
        self._active_attempt = None

    def on_speech_candidate(
        self,
        candidate: InputCandidateRef,
        target: OutputTargetSnapshot | None,
        gen_scope: CancellationScope | None = None,
        *,
        defer_pause_ack: bool = False,
    ) -> DecisionOutcome:
        """Stage 1: evaluate eligibility and request M02 soft pause once."""
        outcome: DecisionOutcome
        with self._lock:
            # Check if an existing active attempt has timed out first.
            if self._active_attempt is not None:
                if self._clock.monotonic_ns() >= self._active_attempt.deadline_monotonic_ns and gen_scope is not None:
                    self._abort_active_locked(gen_scope, reason="PAUSE_TIMEOUT")

            if self._active_attempt is not None:
                if self._active_attempt.candidate_ref.candidate_key == candidate.candidate_key:
                    outcome = DecisionOutcome(
                        attempt_id=self._active_attempt.attempt_id,
                        state=self._state,
                        action_taken="NOOP_DUPLICATE_CANDIDATE",
                        reason="duplicate_candidate_ignored",
                        pause_ref=self._active_attempt.pause_ref,
                        in_flight_possible=self._active_attempt.in_flight_possible,
                    )
                    return self._emit_outcome(outcome)
                outcome = DecisionOutcome(
                    attempt_id=self._active_attempt.attempt_id,
                    state=self._state,
                    action_taken="REJECT_FOREIGN_CANDIDATE",
                    reason="active_attempt_already_pending",
                    pause_ref=self._active_attempt.pause_ref,
                    in_flight_possible=self._active_attempt.in_flight_possible,
                )
                return self._emit_outcome(outcome)

            eligible, reason = self._is_eligible(candidate, target)
            if not eligible or target is None:
                self._state = InterruptionState.REJECTED if reason != "no_live_output" else InterruptionState.IDLE
                outcome = DecisionOutcome(
                    attempt_id=None,
                    state=self._state,
                    action_taken="NO_PAUSE",
                    reason=reason,
                )
                return self._emit_outcome(outcome)

            if gen_scope is not None and gen_scope.is_cancel_requested:
                self._state = InterruptionState.REJECTED
                outcome = DecisionOutcome(
                    attempt_id=None,
                    state=self._state,
                    action_taken="NO_PAUSE",
                    reason="target_already_canceled",
                )
                return self._emit_outcome(outcome)

            self._attempt_seq += 1
            attempt_id = f"int-{self._session_id}-{target.generation_ref.generation_id}-{self._attempt_seq}"
            now_ns = self._clock.monotonic_ns()
            deadline_ns = now_ns + (self._policy.pause_deadline_ms * 1_000_000)

            self._state = InterruptionState.CANDIDATE_PENDING
            pause_ref = self._bridge.request_soft_pause(target.generation_ref, gen_scope)
            if pause_ref is None:
                self._state = InterruptionState.ABORTED
                outcome = DecisionOutcome(
                    attempt_id=attempt_id,
                    state=self._state,
                    action_taken="PAUSE_FAILED",
                    reason="m02_pause_rejected",
                )
                return self._emit_outcome(outcome)

            next_state = InterruptionState.PAUSE_REQUESTED if defer_pause_ack else InterruptionState.SOFT_PAUSED
            self._state = next_state
            self._active_target = target
            self._active_attempt = InterruptionAttempt(
                attempt_id=attempt_id,
                candidate_ref=candidate,
                target_generation=target.generation_ref,
                plan_revision=target.plan_revision,
                pause_epoch=pause_ref.pause_epoch,
                state=next_state,
                pause_ref=pause_ref,
                created_monotonic_ns=now_ns,
                deadline_monotonic_ns=deadline_ns,
                clock_domain=self._clock.clock_domain,
                reason="soft_pause_requested" if defer_pause_ack else "soft_paused",
                in_flight_possible=target.in_flight_submitted,
            )
            outcome = DecisionOutcome(
                attempt_id=attempt_id,
                state=next_state,
                action_taken="SOFT_PAUSE_REQUESTED" if defer_pause_ack else "SOFT_PAUSED",
                reason=self._active_attempt.reason,
                pause_ref=pause_ref,
                in_flight_possible=target.in_flight_submitted,
            )
        return self._emit_outcome(outcome)

    def on_pause_acknowledged(
        self,
        attempt_id: str,
        pause_ref: PauseRef,
        gen_scope: CancellationScope | None = None,
    ) -> DecisionOutcome:
        """Transition PAUSE_REQUESTED -> SOFT_PAUSED when downstream ack arrives before deadline."""
        with self._lock:
            att = self._active_attempt
            if att is None or att.attempt_id != attempt_id or att.pause_ref != pause_ref:
                return self._emit_outcome(
                    DecisionOutcome(
                        attempt_id=attempt_id,
                        state=self._state,
                        action_taken="IGNORE_STALE_PAUSE_ACK",
                        reason="stale_or_mismatched_pause_ack",
                    )
                )
            if self._clock.monotonic_ns() >= att.deadline_monotonic_ns:
                if gen_scope is not None:
                    return self._emit_outcome(self._abort_active_locked(gen_scope, reason="PAUSE_TIMEOUT"))
                self._state = InterruptionState.ABORTED
                retired = InterruptionAttempt(
                    attempt_id=att.attempt_id,
                    candidate_ref=att.candidate_ref,
                    target_generation=att.target_generation,
                    plan_revision=att.plan_revision,
                    pause_epoch=att.pause_epoch,
                    state=InterruptionState.ABORTED,
                    pause_ref=att.pause_ref,
                    created_monotonic_ns=att.created_monotonic_ns,
                    deadline_monotonic_ns=att.deadline_monotonic_ns,
                    clock_domain=att.clock_domain,
                    resolved_monotonic_ns=self._clock.monotonic_ns(),
                    reason="PAUSE_TIMEOUT",
                    in_flight_possible=att.in_flight_possible,
                )
                self._retire_active(retired)
                return self._emit_outcome(
                    DecisionOutcome(
                        attempt_id=attempt_id,
                        state=InterruptionState.ABORTED,
                        action_taken="ABORT_TIMEOUT",
                        reason="PAUSE_TIMEOUT",
                        pause_ref=pause_ref,
                        in_flight_possible=att.in_flight_possible,
                    )
                )
            if self._state == InterruptionState.PAUSE_REQUESTED:
                self._state = InterruptionState.SOFT_PAUSED
                self._active_attempt = InterruptionAttempt(
                    attempt_id=att.attempt_id,
                    candidate_ref=att.candidate_ref,
                    target_generation=att.target_generation,
                    plan_revision=att.plan_revision,
                    pause_epoch=att.pause_epoch,
                    state=InterruptionState.SOFT_PAUSED,
                    pause_ref=att.pause_ref,
                    created_monotonic_ns=att.created_monotonic_ns,
                    deadline_monotonic_ns=att.deadline_monotonic_ns,
                    clock_domain=att.clock_domain,
                    reason="soft_paused",
                    in_flight_possible=att.in_flight_possible,
                )
            return self._emit_outcome(
                DecisionOutcome(
                    attempt_id=attempt_id,
                    state=self._state,
                    action_taken="PAUSE_ACKNOWLEDGED",
                    reason="soft_paused",
                    pause_ref=pause_ref,
                    in_flight_possible=att.in_flight_possible,
                )
            )

    def on_speech_confirmed(
        self,
        candidate: InputCandidateRef,
        gen_scope: CancellationScope,
        *,
        target: OutputTargetSnapshot | None = None,
        queue: BoundedMediaQueue | None = None,
        reason: str = "confirmed_speech",
        remote_flush_supported: bool = False,
    ) -> DecisionOutcome:
        """Stage 2: hard commit interruption on confirmed acoustic onset."""
        with self._lock:
            att = self._active_attempt
            if att is not None:
                if att.candidate_ref.candidate_key != candidate.candidate_key:
                    return self._emit_outcome(
                        DecisionOutcome(
                            attempt_id=att.attempt_id,
                            state=self._state,
                            action_taken="REJECT_FOREIGN_CONFIRM",
                            reason="candidate_mismatch",
                            pause_ref=att.pause_ref,
                            in_flight_possible=att.in_flight_possible,
                        )
                    )
                target_gen = att.target_generation
                in_flight_possible = att.in_flight_possible
                attempt_id = att.attempt_id
            else:
                if self._state in (InterruptionState.COMMITTED, InterruptionState.ABORTED):
                    return self._emit_outcome(
                        DecisionOutcome(
                            attempt_id=None,
                            state=self._state,
                            action_taken="NOOP_ALREADY_TERMINAL",
                            reason="already_terminal",
                        )
                    )
                eligible, elig_reason = self._is_eligible(candidate, target)
                if not eligible or target is None:
                    return self._emit_outcome(
                        DecisionOutcome(
                            attempt_id=None,
                            state=self._state,
                            action_taken="NO_COMMIT",
                            reason=elig_reason,
                        )
                    )
                self._attempt_seq += 1
                attempt_id = f"int-{self._session_id}-{target.generation_ref.generation_id}-{self._attempt_seq}"
                target_gen = target.generation_ref
                in_flight_possible = target.in_flight_submitted

            _, flush_intent = self._bridge.commit_interrupt(
                target_gen,
                gen_scope,
                queue=queue,
                reason=reason,
                remote_flush_supported=remote_flush_supported,
            )
            now_ns = self._clock.monotonic_ns()
            self._state = InterruptionState.COMMITTED
            if att is not None:
                retired = InterruptionAttempt(
                    attempt_id=att.attempt_id,
                    candidate_ref=att.candidate_ref,
                    target_generation=att.target_generation,
                    plan_revision=att.plan_revision,
                    pause_epoch=att.pause_epoch,
                    state=InterruptionState.COMMITTED,
                    pause_ref=att.pause_ref,
                    created_monotonic_ns=att.created_monotonic_ns,
                    deadline_monotonic_ns=att.deadline_monotonic_ns,
                    clock_domain=att.clock_domain,
                    resolved_monotonic_ns=now_ns,
                    reason=reason,
                    flush_intent=flush_intent,
                    in_flight_possible=in_flight_possible,
                )
                self._retire_active(retired)
            outcome = DecisionOutcome(
                attempt_id=attempt_id,
                state=InterruptionState.COMMITTED,
                action_taken="COMMIT_INTERRUPT",
                reason=reason,
                flush_intent=flush_intent,
                in_flight_recall_claimed=False,
                local_purged_items=flush_intent.local_purged_items,
                in_flight_possible=in_flight_possible,
            )
        return self._emit_outcome(outcome)

    def on_candidate_rejected(
        self,
        candidate: InputCandidateRef,
        gen_scope: CancellationScope,
        *,
        cursor_intact: bool = True,
        target_drained: bool = False,
        reason: str = "candidate_rejected",
    ) -> DecisionOutcome:
        """Stage 2 rollback: resume same generation if before deadline and cursor intact."""
        with self._lock:
            att = self._active_attempt
            if att is None:
                return self._emit_outcome(
                    DecisionOutcome(
                        attempt_id=None,
                        state=self._state,
                        action_taken="IGNORE_LATE_REJECTION",
                        reason="no_active_attempt",
                    )
                )
            if att.candidate_ref.candidate_key != candidate.candidate_key:
                return self._emit_outcome(
                    DecisionOutcome(
                        attempt_id=att.attempt_id,
                        state=self._state,
                        action_taken="REJECT_FOREIGN_REJECTION",
                        reason="candidate_mismatch",
                        pause_ref=att.pause_ref,
                        in_flight_possible=att.in_flight_possible,
                    )
                )
            now_ns = self._clock.monotonic_ns()
            if now_ns >= att.deadline_monotonic_ns:
                return self._emit_outcome(self._abort_active_locked(gen_scope, reason="PAUSE_TIMEOUT"))
            if target_drained:
                self._state = InterruptionState.ABORTED
                retired = InterruptionAttempt(
                    attempt_id=att.attempt_id,
                    candidate_ref=att.candidate_ref,
                    target_generation=att.target_generation,
                    plan_revision=att.plan_revision,
                    pause_epoch=att.pause_epoch,
                    state=InterruptionState.ABORTED,
                    pause_ref=att.pause_ref,
                    created_monotonic_ns=att.created_monotonic_ns,
                    deadline_monotonic_ns=att.deadline_monotonic_ns,
                    clock_domain=att.clock_domain,
                    resolved_monotonic_ns=now_ns,
                    reason="target_drained_during_pause",
                    in_flight_possible=att.in_flight_possible,
                )
                self._retire_active(retired)
                return self._emit_outcome(
                    DecisionOutcome(
                        attempt_id=att.attempt_id,
                        state=InterruptionState.ABORTED,
                        action_taken="CLOSE_DRAINED_NO_RESUME",
                        reason="target_drained_during_pause",
                        pause_ref=att.pause_ref,
                        in_flight_possible=att.in_flight_possible,
                    )
                )

            if att.pause_ref is None or not self._bridge.resume_pause(
                att.pause_ref,
                att.target_generation,
                gen_scope,
                cursor_intact=cursor_intact,
            ):
                return self._emit_outcome(self._abort_active_locked(gen_scope, reason="resume_failed_or_cursor_invalid"))

            self._state = InterruptionState.RESUMED
            retired = InterruptionAttempt(
                attempt_id=att.attempt_id,
                candidate_ref=att.candidate_ref,
                target_generation=att.target_generation,
                plan_revision=att.plan_revision,
                pause_epoch=att.pause_epoch,
                state=InterruptionState.RESUMED,
                pause_ref=att.pause_ref,
                created_monotonic_ns=att.created_monotonic_ns,
                deadline_monotonic_ns=att.deadline_monotonic_ns,
                clock_domain=att.clock_domain,
                resolved_monotonic_ns=now_ns,
                reason=reason,
                in_flight_possible=att.in_flight_possible,
            )
            self._retire_active(retired)
            outcome = DecisionOutcome(
                attempt_id=att.attempt_id,
                state=InterruptionState.RESUMED,
                action_taken="RESUMED",
                reason=reason,
                pause_ref=att.pause_ref,
                in_flight_possible=att.in_flight_possible,
            )
        return self._emit_outcome(outcome)

    def on_deadline_tick(
        self,
        gen_scope: CancellationScope,
        *,
        queue: BoundedMediaQueue | None = None,
    ) -> DecisionOutcome | None:
        """Check bounded pause deadline; abort target if unresolved at now >= deadline."""
        with self._lock:
            att = self._active_attempt
            if att is None:
                return None
            if self._clock.monotonic_ns() < att.deadline_monotonic_ns:
                return None
            outcome = self._abort_active_locked(gen_scope, queue=queue, reason="PAUSE_TIMEOUT")
        return self._emit_outcome(outcome)

    def on_target_invalidated(
        self,
        gen_scope: CancellationScope | None = None,
        *,
        queue: BoundedMediaQueue | None = None,
        reason: str = "epoch_loss",
    ) -> DecisionOutcome | None:
        """Invalidate any active attempt on disconnect, epoch change, or target replacement."""
        with self._lock:
            if self._active_attempt is None:
                return None
            outcome = self._abort_active_locked(gen_scope, queue=queue, reason=reason)
        return self._emit_outcome(outcome)

    def _abort_active_locked(
        self,
        gen_scope: CancellationScope | None,
        *,
        queue: BoundedMediaQueue | None = None,
        reason: str,
    ) -> DecisionOutcome:
        att = self._active_attempt
        assert att is not None
        now_ns = self._clock.monotonic_ns()
        flush_intent: FlushIntent | None = None
        if gen_scope is not None:
            _, flush_intent = self._bridge.commit_interrupt(
                att.target_generation,
                gen_scope,
                queue=queue,
                reason=reason,
            )
        self._state = InterruptionState.ABORTED
        retired = InterruptionAttempt(
            attempt_id=att.attempt_id,
            candidate_ref=att.candidate_ref,
            target_generation=att.target_generation,
            plan_revision=att.plan_revision,
            pause_epoch=att.pause_epoch,
            state=InterruptionState.ABORTED,
            pause_ref=att.pause_ref,
            created_monotonic_ns=att.created_monotonic_ns,
            deadline_monotonic_ns=att.deadline_monotonic_ns,
            clock_domain=att.clock_domain,
            resolved_monotonic_ns=now_ns,
            reason=reason,
            flush_intent=flush_intent,
            in_flight_possible=att.in_flight_possible,
        )
        self._retire_active(retired)
        return DecisionOutcome(
            attempt_id=att.attempt_id,
            state=InterruptionState.ABORTED,
            action_taken="ABORT_TARGET",
            reason=reason,
            pause_ref=att.pause_ref,
            flush_intent=flush_intent,
            in_flight_recall_claimed=False,
            local_purged_items=flush_intent.local_purged_items if flush_intent else 0,
            in_flight_possible=att.in_flight_possible,
        )
