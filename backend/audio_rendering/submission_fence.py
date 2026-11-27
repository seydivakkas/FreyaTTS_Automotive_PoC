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

import inspect
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Callable

from backend.audio_rendering.pacing import MonotonicPacer
from backend.audio_rendering.sample_accounting import SampleAccounting
from backend.core.contracts.common import GenerationRef, StreamRef
from backend.core.contracts.playback import ObservationScope, RenderedFrame
from backend.core.runtime.result_admission import AdmissionStatus, QueuedMediaItem
from backend.core.runtime.session_context import SessionContext, SessionLifecycleState
from backend.core.runtime.turn_generation import PauseState


class SubmissionOutcome(StrEnum):
    SUBMITTED_SERVER = "SUBMITTED_SERVER"
    IN_FLIGHT_POSSIBLE = "IN_FLIGHT_POSSIBLE"
    BLOCKED_CANCELED = "BLOCKED_CANCELED"
    BLOCKED_PAUSED = "BLOCKED_PAUSED"
    BLOCKED_STALE_GENERATION = "BLOCKED_STALE_GENERATION"
    BLOCKED_CLOSED = "BLOCKED_CLOSED"
    BACKPRESSURE = "BACKPRESSURE"
    FAILED_TRANSPORT = "FAILED_TRANSPORT"
    ABORTED_STALE_SCHEDULE = "ABORTED_STALE_SCHEDULE"


class TransportCompletionUncertainError(RuntimeError):
    """Raised when transport write started asynchronously and completion/status is unknown."""


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    """Immutable record of a single linearized submission decision."""

    frame_identity: str
    generation_ref: GenerationRef
    stream_ref: StreamRef
    sequence: int
    valid_sample_count: int
    outcome: SubmissionOutcome
    observation_scope: ObservationScope
    scheduled_ns: int
    actual_ns: int
    clock_domain: str
    bytes_written: int
    reason: str
    lease_id: str | None = None


class AtomicSubmissionFence:
    """
    M02-backed single-writer atomic compare-and-submit linearization fence.

    - Checks active session/generation/cancellation/pause under M02 lock right at writer handoff.
    - Never holds M02 lock across pacing sleep or transport I/O.
    - Acquires an explicit ResourceLedger IN_FLIGHT lease before transport handoff so
      racing cancellations distinguish `BLOCKED_CANCELED` (zero bytes sent) from
      `IN_FLIGHT_POSSIBLE` (prior submission cannot be recalled).
    - Guarantees idempotent lease release on duplicate completion callbacks and
      quarantines unresolved/unknown completions without false cleanup.
    """

    def __init__(
        self,
        *,
        session_ctx: SessionContext,
        pacer: MonotonicPacer,
        accounting: SampleAccounting,
    ) -> None:
        self.session_ctx = session_ctx
        self.pacer = pacer
        self.accounting = accounting
        self._frames_by_key: dict[tuple[int, int, int], RenderedFrame] = {}
        self._completed_leases: set[str] = set()
        self.records: list[SubmissionRecord] = []
        self.duplicate_completion_callbacks = 0

    @staticmethod
    def _frame_key(gen_ref: GenerationRef, seq: int) -> tuple[int, int, int]:
        return (gen_ref.turn_id, gen_ref.generation_id, seq)

    async def enqueue_frame(
        self,
        frame: RenderedFrame,
        *,
        plan_revision: int = 0,
    ) -> AdmissionStatus:
        """Reserve bounded capacity in M02 BoundedMediaQueue and admit a RenderedFrame."""
        item = QueuedMediaItem(
            generation_ref=frame.generation_ref,
            sequence=frame.sequence,
            payload=frame.payload,
            plan_revision=plan_revision,
            is_control=False,
        )
        status = await self.session_ctx.admit_media(
            item,
            incarnation_id=self.session_ctx.incarnation_id,
            expected_plan_revision=plan_revision,
        )
        if status == AdmissionStatus.ACCEPTED:
            self._frames_by_key[self._frame_key(frame.generation_ref, frame.sequence)] = frame
            self.accounting.record_queued(frame.valid_sample_count)
        return status

    def release_lease_idempotent(self, lease_id: str) -> bool:
        """Idempotent completion release; duplicate completion callbacks cannot double-release."""
        if lease_id in self._completed_leases:
            self.duplicate_completion_callbacks += 1
            return False
        released = self.session_ctx.ledger.release(lease_id)
        if released:
            self._completed_leases.add(lease_id)
        return released

    def quarantine_lease(self, lease_id: str) -> None:
        """Mark an unresolved/unknown transport lease as QUARANTINED in M02 ResourceLedger."""
        self.session_ctx.ledger.quarantine(lease_id)

    def purge_generation(self, generation_ref: GenerationRef) -> int:
        """Purge unsubmitted frames for a revoked or superseded generation and balance sample accounting."""
        purged = 0
        for key in list(self._frames_by_key.keys()):
            if key[0] == generation_ref.turn_id and key[1] == generation_ref.generation_id:
                frame = self._frames_by_key.pop(key)
                self.accounting.record_canceled_from_queue(frame.valid_sample_count)
                purged += 1
        return purged

    async def submit_next(
        self,
        *,
        expected_gen: GenerationRef,
        stream_ref: StreamRef,
        submit_fn: Callable[[RenderedFrame], Any],
        use_pacer: bool = True,
        underrun_recovered: bool = False,
        before_linearize_hook: Callable[[RenderedFrame], Awaitable[None]] | None = None,
    ) -> SubmissionRecord | None:
        """
        Dequeue next authorized frame, pace outside lock, apply atomic fence at handoff,
        and execute transport submit. Returns None only when queue is empty.
        """
        status, item = await self.session_ctx.dequeue_for_submission(expected_gen)
        if status == AdmissionStatus.INVALID and item is None:
            return None

        if item is None:
            now_ns = self.session_ctx.clock.monotonic_ns()
            mapped = {
                AdmissionStatus.CANCELED: SubmissionOutcome.BLOCKED_CANCELED,
                AdmissionStatus.PAUSED: SubmissionOutcome.BLOCKED_PAUSED,
                AdmissionStatus.CLOSED: SubmissionOutcome.BLOCKED_CLOSED,
                AdmissionStatus.STALE_GENERATION: SubmissionOutcome.BLOCKED_STALE_GENERATION,
            }.get(status, SubmissionOutcome.BLOCKED_STALE_GENERATION)
            rec = SubmissionRecord(
                frame_identity=f"{stream_ref.stream_id}:{expected_gen.turn_id}:{expected_gen.generation_id}:none",
                generation_ref=expected_gen,
                stream_ref=stream_ref,
                sequence=-1,
                valid_sample_count=0,
                outcome=mapped,
                observation_scope=ObservationScope.SERVER,
                scheduled_ns=now_ns,
                actual_ns=now_ns,
                clock_domain=self.session_ctx.clock.clock_domain,
                bytes_written=0,
                reason=status.value,
            )
            self.records.append(rec)
            return rec

        key = self._frame_key(item.generation_ref, item.sequence)
        frame = self._frames_by_key.pop(key)

        # 1. Pace outside any lock
        if use_pacer:
            proceed, target_ns, reanchored = await self.pacer.wait_until_next_target(
                underrun_recovered=underrun_recovered
            )
            if not proceed:
                self.pacer.record_submission(
                    sequence=frame.sequence,
                    target_ns=target_ns,
                    reanchored=False,
                    underrun=underrun_recovered,
                    aborted_stale=True,
                )
                self.accounting.record_canceled_from_queue(frame.valid_sample_count)
                rec = SubmissionRecord(
                    frame_identity=f"{stream_ref.stream_id}:{frame.generation_ref.turn_id}:{frame.generation_ref.generation_id}:{frame.sequence}",
                    generation_ref=frame.generation_ref,
                    stream_ref=stream_ref,
                    sequence=frame.sequence,
                    valid_sample_count=frame.valid_sample_count,
                    outcome=SubmissionOutcome.ABORTED_STALE_SCHEDULE,
                    observation_scope=ObservationScope.SERVER,
                    scheduled_ns=target_ns,
                    actual_ns=self.session_ctx.clock.monotonic_ns(),
                    clock_domain=self.session_ctx.clock.clock_domain,
                    bytes_written=0,
                    reason="PACER_MAX_LATENESS_EXCEEDED",
                )
                self.records.append(rec)
                return rec
        else:
            target_ns = self.session_ctx.clock.monotonic_ns()
            reanchored = False

        # Deterministic test barrier before linearization (e.g. AR71 cancel vs submit race)
        if before_linearize_hook is not None:
            await before_linearize_hook(frame)

        # 2. Atomic compare-and-reserve linearization point under M02 lock
        lease_id = f"sub-{stream_ref.stream_id}-{frame.generation_ref.turn_id}-{frame.generation_ref.generation_id}-{frame.sequence}"
        async with self.session_ctx.lock:
            block_reason: str | None = None
            block_outcome: SubmissionOutcome | None = None

            if self.session_ctx.lifecycle_state != SessionLifecycleState.ACTIVE:
                block_outcome = SubmissionOutcome.BLOCKED_CLOSED
                block_reason = f"SESSION_{self.session_ctx.lifecycle_state.value}"
            elif self.session_ctx.root_scope.is_cancel_requested:
                block_outcome = SubmissionOutcome.BLOCKED_CANCELED
                block_reason = self.session_ctx.root_scope.reason or "ROOT_CANCELLED"
            elif self.session_ctx.tg.active_generation != expected_gen:
                block_outcome = SubmissionOutcome.BLOCKED_STALE_GENERATION
                block_reason = "ACTIVE_GENERATION_CHANGED"
            elif (
                self.session_ctx.tg.generation_scope is None
                or self.session_ctx.tg.generation_scope.is_cancel_requested
            ):
                block_outcome = SubmissionOutcome.BLOCKED_CANCELED
                block_reason = (
                    self.session_ctx.tg.generation_scope.reason
                    if self.session_ctx.tg.generation_scope is not None
                    else "GENERATION_SCOPE_MISSING"
                ) or "GENERATION_CANCELLED"
            elif self.session_ctx.pause.state == PauseState.SOFT_PAUSED:
                block_outcome = SubmissionOutcome.BLOCKED_PAUSED
                block_reason = "SOFT_PAUSED_AT_FENCE"

            if block_outcome is not None:
                if block_outcome == SubmissionOutcome.BLOCKED_PAUSED:
                    # Re-queue unsent paused frame so resume can deliver it without replay
                    self._frames_by_key[key] = frame
                    requeue_item = QueuedMediaItem(
                        generation_ref=frame.generation_ref,
                        sequence=frame.sequence,
                        payload=frame.payload,
                        plan_revision=item.plan_revision,
                        is_control=False,
                    )
                    # Clear seen key check cleanly via direct appendleft if available, else keep paused
                    self.session_ctx.queue._media.appendleft(requeue_item)
                    self.session_ctx.queue._bytes_used += len(requeue_item.payload)
                else:
                    self.accounting.record_canceled_from_queue(frame.valid_sample_count)
                now_ns = self.session_ctx.clock.monotonic_ns()
                rec = SubmissionRecord(
                    frame_identity=f"{stream_ref.stream_id}:{frame.generation_ref.turn_id}:{frame.generation_ref.generation_id}:{frame.sequence}",
                    generation_ref=frame.generation_ref,
                    stream_ref=stream_ref,
                    sequence=frame.sequence,
                    valid_sample_count=frame.valid_sample_count,
                    outcome=block_outcome,
                    observation_scope=ObservationScope.SERVER,
                    scheduled_ns=target_ns,
                    actual_ns=now_ns,
                    clock_domain=self.session_ctx.clock.clock_domain,
                    bytes_written=0,
                    reason=block_reason or block_outcome.value,
                )
                self.records.append(rec)
                return rec

            # Linearization won: reserve IN_FLIGHT lease before releasing lock for I/O
            self.session_ctx.ledger.acquire(lease_id, "media_submit")
            self.session_ctx.ledger.mark_in_flight(lease_id)

        # 3. Execute writer outside M02 lock so concurrent cancel cannot deadlock
        bytes_written = 0
        outcome = SubmissionOutcome.SUBMITTED_SERVER
        scope = ObservationScope.SERVER
        reason = "SERVER_SUBMITTED"
        keep_quarantined = False

        try:
            res = submit_fn(frame)
            if inspect.isawaitable(res):
                res = await res
            if isinstance(res, tuple) and len(res) >= 2 and isinstance(res[1], int):
                # Supports (ok, bytes_written, detail)
                bytes_written = int(res[1])
                ok = bool(res[0])
                detail = str(res[2]) if len(res) > 2 else ""
                if not ok:
                    outcome = SubmissionOutcome.IN_FLIGHT_POSSIBLE if bytes_written > 0 or "IN_FLIGHT" in detail else SubmissionOutcome.FAILED_TRANSPORT
                    scope = ObservationScope.UNKNOWN if "IN_FLIGHT" in detail or bytes_written > 0 else ObservationScope.SERVER
                    reason = detail or "TRANSPORT_WRITE_FAILED"
                    if "UNKNOWN" in detail:
                        keep_quarantined = True
            elif hasattr(res, "bytes_written") and hasattr(res, "outcome"):
                bytes_written = int(getattr(res, "bytes_written", 0))
                res_out = str(getattr(res, "outcome"))
                if "SUBMITTED" in res_out or getattr(res, "accepted", False):
                    outcome = SubmissionOutcome.SUBMITTED_SERVER
                    reason = str(getattr(res, "detail", "SUBMITTED"))
                elif "IN_FLIGHT" in res_out or "PARTIAL" in res_out:
                    outcome = SubmissionOutcome.IN_FLIGHT_POSSIBLE
                    scope = ObservationScope.UNKNOWN
                    reason = str(getattr(res, "detail", res_out))
                    if "UNKNOWN" in res_out:
                        keep_quarantined = True
                elif "BACKPRESSURE" in res_out:
                    outcome = SubmissionOutcome.BACKPRESSURE
                    reason = str(getattr(res, "detail", "BACKPRESSURE"))
                else:
                    outcome = SubmissionOutcome.FAILED_TRANSPORT
                    reason = str(getattr(res, "detail", res_out))
            else:
                bytes_written = len(frame.payload)
        except TransportCompletionUncertainError as exc:
            outcome = SubmissionOutcome.IN_FLIGHT_POSSIBLE
            scope = ObservationScope.UNKNOWN
            reason = str(exc) or "TRANSPORT_COMPLETION_UNKNOWN"
            keep_quarantined = True
        except Exception as exc:
            outcome = SubmissionOutcome.FAILED_TRANSPORT
            scope = ObservationScope.SERVER
            reason = f"TRANSPORT_EXC:{type(exc).__name__}"

        # Check if cancellation raced AFTER linearization handoff
        gen_scope = self.session_ctx.tg.generation_scope
        raced_cancel = self.session_ctx.root_scope.is_cancel_requested or (
            gen_scope is not None and gen_scope.is_cancel_requested
        )
        if raced_cancel and outcome == SubmissionOutcome.SUBMITTED_SERVER:
            outcome = SubmissionOutcome.IN_FLIGHT_POSSIBLE
            reason = "CANCEL_RACED_AFTER_SUBMIT_HANDOFF"

        if keep_quarantined:
            self.quarantine_lease(lease_id)
        else:
            self.release_lease_idempotent(lease_id)

        if use_pacer:
            pacing_rec = self.pacer.record_submission(
                sequence=frame.sequence,
                target_ns=target_ns,
                reanchored=reanchored,
                underrun=underrun_recovered,
            )
            actual_ns = pacing_rec.actual_submit_ns
        else:
            actual_ns = self.session_ctx.clock.monotonic_ns()

        if outcome in (SubmissionOutcome.SUBMITTED_SERVER, SubmissionOutcome.IN_FLIGHT_POSSIBLE):
            self.accounting.record_submitted(
                frame.valid_sample_count,
                in_flight_uncertain=(outcome == SubmissionOutcome.IN_FLIGHT_POSSIBLE and keep_quarantined),
            )
        else:
            self.accounting.record_canceled_from_queue(frame.valid_sample_count)

        rec = SubmissionRecord(
            frame_identity=f"{stream_ref.stream_id}:{frame.generation_ref.turn_id}:{frame.generation_ref.generation_id}:{frame.sequence}",
            generation_ref=frame.generation_ref,
            stream_ref=stream_ref,
            sequence=frame.sequence,
            valid_sample_count=frame.valid_sample_count,
            outcome=outcome,
            observation_scope=scope,
            scheduled_ns=target_ns,
            actual_ns=actual_ns,
            clock_domain=self.session_ctx.clock.clock_domain,
            bytes_written=bytes_written,
            reason=reason,
            lease_id=lease_id,
        )
        self.records.append(rec)
        return rec
