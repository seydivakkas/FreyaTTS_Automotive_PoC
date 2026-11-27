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
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from backend.core.contracts.common import GenerationRef, StreamRef
from backend.core.contracts.playback import ObservationScope, RenderedFrame
from backend.core.contracts.validation import require_strict_int
from backend.core.runtime.deadlines import Clock


class ReservationStatus(StrEnum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    REJECTED_BACKPRESSURE = "REJECTED_BACKPRESSURE"
    REJECTED_TOO_LARGE = "REJECTED_TOO_LARGE"
    REJECTED_WAITERS_EXCEEDED = "REJECTED_WAITERS_EXCEEDED"
    REJECTED_STALE = "REJECTED_STALE"
    REJECTED_PAUSED = "REJECTED_PAUSED"
    REJECTED_CLOSED = "REJECTED_CLOSED"
    TIMEOUT = "TIMEOUT"


class MediaItemState(StrEnum):
    RESERVED = "RESERVED"
    QUEUED_UNSENT = "QUEUED_UNSENT"
    SELECTED_UNSENT = "SELECTED_UNSENT"
    SUBMISSION_CLAIMED = "SUBMISSION_CLAIMED"
    COMPLETED_LOCAL = "COMPLETED_LOCAL"
    UNKNOWN_DELIVERY = "UNKNOWN_DELIVERY"
    DISCARDED = "DISCARDED"


@dataclass(frozen=True, slots=True)
class CapacityBudget:
    """Validated finite capacity and watermark budget for a playback stream."""

    max_frames: int = 64
    max_target_samples: int = 64 * 320
    max_payload_bytes: int = 256 * 1024
    max_workspace_bytes: int = 512 * 1024
    high_watermark_frames: int = 48
    low_watermark_frames: int = 16
    max_waiters_per_stream: int = 8
    max_waiters_global: int = 64

    def __post_init__(self) -> None:
        require_strict_int(self.max_frames, "max_frames", minimum=1, maximum=4096)
        require_strict_int(self.max_target_samples, "max_target_samples", minimum=1)
        require_strict_int(self.max_payload_bytes, "max_payload_bytes", minimum=320)
        require_strict_int(self.max_workspace_bytes, "max_workspace_bytes", minimum=320)
        require_strict_int(self.low_watermark_frames, "low_watermark_frames", minimum=0)
        require_strict_int(self.high_watermark_frames, "high_watermark_frames", minimum=1)
        require_strict_int(self.max_waiters_per_stream, "max_waiters_per_stream", minimum=1, maximum=256)
        require_strict_int(self.max_waiters_global, "max_waiters_global", minimum=1, maximum=1024)
        if not (0 <= self.low_watermark_frames < self.high_watermark_frames <= self.max_frames):
            raise ValueError(
                "Watermarks must satisfy 0 <= low_watermark_frames < high_watermark_frames <= max_frames"
            )


class GlobalCapacityCoordinator:
    """Aggregate capacity and waiter cap across multiple concurrent playback streams."""

    def __init__(
        self,
        *,
        max_total_frames: int = 512,
        max_total_bytes: int = 2 * 1024 * 1024,
        max_total_waiters: int = 64,
    ) -> None:
        require_strict_int(max_total_frames, "max_total_frames", minimum=1)
        require_strict_int(max_total_bytes, "max_total_bytes", minimum=320)
        require_strict_int(max_total_waiters, "max_total_waiters", minimum=1)
        self.max_total_frames = max_total_frames
        self.max_total_bytes = max_total_bytes
        self.max_total_waiters = max_total_waiters
        self.occupied_frames = 0
        self.occupied_bytes = 0
        self.active_waiters = 0

    def can_fit(self, frames: int, payload_bytes: int) -> bool:
        return (
            (self.occupied_frames + frames) <= self.max_total_frames
            and (self.occupied_bytes + payload_bytes) <= self.max_total_bytes
        )

    def acquire(self, frames: int, payload_bytes: int) -> bool:
        if not self.can_fit(frames, payload_bytes):
            return False
        self.occupied_frames += frames
        self.occupied_bytes += payload_bytes
        return True

    def release(self, frames: int, payload_bytes: int) -> None:
        self.occupied_frames = max(0, self.occupied_frames - frames)
        self.occupied_bytes = max(0, self.occupied_bytes - payload_bytes)


@dataclass(slots=True)
class CapacityReservation:
    """Atomic capacity reservation converted once into queue ownership or released once."""

    reservation_id: str
    session_id: str
    incarnation_id: str
    generation_ref: GenerationRef
    plan_revision: int
    stream_ref: StreamRef
    reserved_frames: int
    reserved_target_samples: int
    reserved_payload_bytes: int
    reserved_workspace_bytes: int
    status: ReservationStatus = ReservationStatus.RESERVED
    reason: str = "RESERVED"


@dataclass(slots=True)
class QueueEntry:
    """Owned media item in the bounded playback queue."""

    frame: RenderedFrame
    plan_revision: int
    state: MediaItemState
    reservation_id: str | None = None
    claim_id: str | None = None
    discard_reason: str | None = None


@dataclass(slots=True)
class UnsentCursor:
    """
    Exact local linearization cursor.

    `next_never_claimed_sequence` advances exactly once at SUBMISSION_CLAIMED
    and NEVER rewinds on timeout, pause, cancellation, error, or late/duplicate ACK.
    """

    next_never_claimed_sequence: int = 0
    next_never_claimed_sample_offset: int = 0
    last_claimed_sequence: int | None = None
    completed_local_sequences: set[int] = field(default_factory=set)
    unknown_in_flight_sequences: set[int] = field(default_factory=set)
    in_flight_sequences: set[int] = field(default_factory=set)
    receiver_acked_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class FlushIntent:
    command_id: str
    session_id: str
    incarnation_id: str
    generation_ref: GenerationRef
    plan_revision: int
    stream_ref: StreamRef
    reason: str
    created_ns: int
    clock_domain: str


@dataclass(frozen=True, slots=True)
class FlushScopeResult:
    scope: ObservationScope
    status: str
    purged_frames: int | None
    purged_payload_bytes: int | None
    purged_valid_samples: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class FlushReceipt:
    command_id: str
    generation_ref: GenerationRef
    stream_ref: StreamRef
    local: FlushScopeResult
    remote: FlushScopeResult
    in_flight_sequences: tuple[int, ...]
    audible_silence_verified: bool = False
    endpoint_silence_ms: float | None = None


class BoundedPlaybackQueue:
    """
    F6-B single-owner bounded playback queue with:
    - pre-copy capacity reservation (frames, target samples, payload bytes, workspace bytes)
    - high/low watermark backpressure with bounded cancellable async wait outside M02 lock
    - exact unsent cursor & state transitions:
      RESERVED -> QUEUED_UNSENT -> SELECTED_UNSENT -> SUBMISSION_CLAIMED -> COMPLETED_LOCAL / UNKNOWN_DELIVERY
    - scoped local purge accounting and remote capability separation
    """

    def __init__(
        self,
        *,
        session_id: str,
        incarnation_id: str,
        stream_ref: StreamRef,
        budget: CapacityBudget,
        clock: Clock,
        global_coordinator: GlobalCapacityCoordinator | None = None,
    ) -> None:
        self.session_id = session_id
        self.incarnation_id = incarnation_id
        self.stream_ref = stream_ref
        self.budget = budget
        self.clock = clock
        self.global_coordinator = global_coordinator

        self._cond = asyncio.Condition()
        self._closed = False
        self._paused = False
        self._active_generation: GenerationRef | None = None
        self._active_plan_revision: int = 0
        self._revoked_generations: set[tuple[int, int]] = set()

        self._reservations: dict[str, CapacityReservation] = {}
        self._queued: deque[QueueEntry] = deque()
        self._selected: QueueEntry | None = None
        self._in_flight: dict[str, QueueEntry] = {}
        self._seen_frame_keys: set[tuple[int, int, int]] = set()
        self._cursor = UnsentCursor()
        self._waiters = 0

        self._reserved_frames = 0
        self._reserved_samples = 0
        self._reserved_bytes = 0
        self._reserved_workspace_bytes = 0

        self._queued_frames = 0
        self._queued_samples = 0
        self._queued_bytes = 0

        self._in_flight_frames = 0
        self._in_flight_samples = 0
        self._in_flight_bytes = 0

        self._high_watermark_active = False
        self.watermark_transitions = 0
        self.waiter_rejections = 0

    @property
    def cursor(self) -> UnsentCursor:
        return self._cursor

    @property
    def occupied_frames(self) -> int:
        selected_f = 1 if self._selected is not None else 0
        return self._reserved_frames + self._queued_frames + selected_f + self._in_flight_frames

    @property
    def occupied_bytes(self) -> int:
        selected_b = len(self._selected.frame.payload) if self._selected is not None else 0
        return self._reserved_bytes + self._queued_bytes + selected_b + self._in_flight_bytes

    @property
    def occupied_samples(self) -> int:
        selected_s = self._selected.frame.sample_count if self._selected is not None else 0
        return self._reserved_samples + self._queued_samples + selected_s + self._in_flight_samples

    @property
    def queued_unsent_sequences(self) -> tuple[int, ...]:
        return tuple(e.frame.sequence for e in self._queued)

    @property
    def selected_unsent_sequences(self) -> tuple[int, ...]:
        return (self._selected.frame.sequence,) if self._selected is not None else ()

    @property
    def in_flight_sequences(self) -> tuple[int, ...]:
        return tuple(sorted(self._cursor.in_flight_sequences))

    def set_active_generation(self, gen_ref: GenerationRef, *, plan_revision: int = 0) -> None:
        self._active_generation = gen_ref
        self._active_plan_revision = plan_revision

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def _update_watermark_state(self) -> None:
        occ = self.occupied_frames
        if not self._high_watermark_active and occ >= self.budget.high_watermark_frames:
            self._high_watermark_active = True
            self.watermark_transitions += 1
        elif self._high_watermark_active and occ <= self.budget.low_watermark_frames:
            self._high_watermark_active = False
            self.watermark_transitions += 1

    def _exceeds_hard_cap(self, frames: int, samples: int, payload_bytes: int, workspace_bytes: int) -> bool:
        return (
            frames > self.budget.max_frames
            or samples > self.budget.max_target_samples
            or payload_bytes > self.budget.max_payload_bytes
            or workspace_bytes > self.budget.max_workspace_bytes
        )

    def _can_admit_now(self, frames: int, samples: int, payload_bytes: int, workspace_bytes: int) -> bool:
        if self.occupied_frames + frames > self.budget.max_frames:
            return False
        if self.occupied_samples + samples > self.budget.max_target_samples:
            return False
        if self.occupied_bytes + payload_bytes > self.budget.max_payload_bytes:
            return False
        if self._reserved_workspace_bytes + workspace_bytes > self.budget.max_workspace_bytes:
            return False
        if self._high_watermark_active:
            return False
        if self.global_coordinator is not None and not self.global_coordinator.can_fit(frames, payload_bytes):
            return False
        return True

    def _validate_scope(self, gen_ref: GenerationRef, plan_revision: int, stream_ref: StreamRef) -> ReservationStatus | None:
        if self._closed:
            return ReservationStatus.REJECTED_CLOSED
        if stream_ref.session_id != self.session_id or stream_ref.format_epoch != self.stream_ref.format_epoch:
            return ReservationStatus.REJECTED_STALE
        gkey = (gen_ref.turn_id, gen_ref.generation_id)
        if gkey in self._revoked_generations:
            return ReservationStatus.REJECTED_STALE
        if self._active_generation is not None and self._active_generation != gen_ref:
            return ReservationStatus.REJECTED_STALE
        if plan_revision != self._active_plan_revision:
            return ReservationStatus.REJECTED_STALE
        return None

    def try_reserve(
        self,
        *,
        generation_ref: GenerationRef,
        plan_revision: int = 0,
        stream_ref: StreamRef | None = None,
        frames: int,
        target_samples: int,
        payload_bytes: int,
        workspace_bytes: int = 0,
    ) -> CapacityReservation:
        sref = stream_ref or self.stream_ref
        stale = self._validate_scope(generation_ref, plan_revision, sref)
        if stale is not None:
            return CapacityReservation(
                reservation_id="",
                session_id=self.session_id,
                incarnation_id=self.incarnation_id,
                generation_ref=generation_ref,
                plan_revision=plan_revision,
                stream_ref=sref,
                reserved_frames=0,
                reserved_target_samples=0,
                reserved_payload_bytes=0,
                reserved_workspace_bytes=0,
                status=stale,
                reason=stale.value,
            )

        if self._exceeds_hard_cap(frames, target_samples, payload_bytes, workspace_bytes):
            return CapacityReservation(
                reservation_id="",
                session_id=self.session_id,
                incarnation_id=self.incarnation_id,
                generation_ref=generation_ref,
                plan_revision=plan_revision,
                stream_ref=sref,
                reserved_frames=0,
                reserved_target_samples=0,
                reserved_payload_bytes=0,
                reserved_workspace_bytes=0,
                status=ReservationStatus.REJECTED_TOO_LARGE,
                reason="EXCEEDS_CAPACITY_BUDGET",
            )

        self._update_watermark_state()
        if not self._can_admit_now(frames, target_samples, payload_bytes, workspace_bytes):
            return CapacityReservation(
                reservation_id="",
                session_id=self.session_id,
                incarnation_id=self.incarnation_id,
                generation_ref=generation_ref,
                plan_revision=plan_revision,
                stream_ref=sref,
                reserved_frames=0,
                reserved_target_samples=0,
                reserved_payload_bytes=0,
                reserved_workspace_bytes=0,
                status=ReservationStatus.REJECTED_BACKPRESSURE,
                reason="HIGH_WATERMARK_OR_FULL",
            )

        if self.global_coordinator is not None:
            if not self.global_coordinator.acquire(frames, payload_bytes):
                return CapacityReservation(
                    reservation_id="",
                    session_id=self.session_id,
                    incarnation_id=self.incarnation_id,
                    generation_ref=generation_ref,
                    plan_revision=plan_revision,
                    stream_ref=sref,
                    reserved_frames=0,
                    reserved_target_samples=0,
                    reserved_payload_bytes=0,
                    reserved_workspace_bytes=0,
                    status=ReservationStatus.REJECTED_BACKPRESSURE,
                    reason="GLOBAL_CAPACITY_FULL",
                )

        rid = f"res-{uuid4().hex[:12]}"
        res = CapacityReservation(
            reservation_id=rid,
            session_id=self.session_id,
            incarnation_id=self.incarnation_id,
            generation_ref=generation_ref,
            plan_revision=plan_revision,
            stream_ref=sref,
            reserved_frames=frames,
            reserved_target_samples=target_samples,
            reserved_payload_bytes=payload_bytes,
            reserved_workspace_bytes=workspace_bytes,
            status=ReservationStatus.RESERVED,
            reason="RESERVED",
        )
        self._reservations[rid] = res
        self._reserved_frames += frames
        self._reserved_samples += target_samples
        self._reserved_bytes += payload_bytes
        self._reserved_workspace_bytes += workspace_bytes
        self._update_watermark_state()
        return res

    async def await_reserve(
        self,
        *,
        generation_ref: GenerationRef,
        plan_revision: int = 0,
        stream_ref: StreamRef | None = None,
        frames: int,
        target_samples: int,
        payload_bytes: int,
        workspace_bytes: int = 0,
        timeout_sec: float = 1.0,
    ) -> CapacityReservation:
        """Wait outside M02 lock for capacity below low watermark, with bounded waiters."""
        sref = stream_ref or self.stream_ref
        res = self.try_reserve(
            generation_ref=generation_ref,
            plan_revision=plan_revision,
            stream_ref=sref,
            frames=frames,
            target_samples=target_samples,
            payload_bytes=payload_bytes,
            workspace_bytes=workspace_bytes,
        )
        if res.status != ReservationStatus.REJECTED_BACKPRESSURE:
            return res

        async with self._cond:
            if self._waiters >= self.budget.max_waiters_per_stream or (
                self.global_coordinator is not None
                and self.global_coordinator.active_waiters >= self.global_coordinator.max_total_waiters
            ):
                self.waiter_rejections += 1
                return CapacityReservation(
                    reservation_id="",
                    session_id=self.session_id,
                    incarnation_id=self.incarnation_id,
                    generation_ref=generation_ref,
                    plan_revision=plan_revision,
                    stream_ref=sref,
                    reserved_frames=0,
                    reserved_target_samples=0,
                    reserved_payload_bytes=0,
                    reserved_workspace_bytes=0,
                    status=ReservationStatus.REJECTED_WAITERS_EXCEEDED,
                    reason="MAX_WAITERS_EXCEEDED",
                )

            self._waiters += 1
            if self.global_coordinator is not None:
                self.global_coordinator.active_waiters += 1
            deadline_ns = self.clock.monotonic_ns() + int(timeout_sec * 1_000_000_000)
            try:
                while True:
                    res = self.try_reserve(
                        generation_ref=generation_ref,
                        plan_revision=plan_revision,
                        stream_ref=sref,
                        frames=frames,
                        target_samples=target_samples,
                        payload_bytes=payload_bytes,
                        workspace_bytes=workspace_bytes,
                    )
                    if res.status != ReservationStatus.REJECTED_BACKPRESSURE:
                        return res
                    remaining_ns = deadline_ns - self.clock.monotonic_ns()
                    if remaining_ns <= 0:
                        return CapacityReservation(
                            reservation_id="",
                            session_id=self.session_id,
                            incarnation_id=self.incarnation_id,
                            generation_ref=generation_ref,
                            plan_revision=plan_revision,
                            stream_ref=sref,
                            reserved_frames=0,
                            reserved_target_samples=0,
                            reserved_payload_bytes=0,
                            reserved_workspace_bytes=0,
                            status=ReservationStatus.TIMEOUT,
                            reason="BACKPRESSURE_WAIT_TIMEOUT",
                        )
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=remaining_ns / 1_000_000_000)
                    except asyncio.TimeoutError:
                        return CapacityReservation(
                            reservation_id="",
                            session_id=self.session_id,
                            incarnation_id=self.incarnation_id,
                            generation_ref=generation_ref,
                            plan_revision=plan_revision,
                            stream_ref=sref,
                            reserved_frames=0,
                            reserved_target_samples=0,
                            reserved_payload_bytes=0,
                            reserved_workspace_bytes=0,
                            status=ReservationStatus.TIMEOUT,
                            reason="BACKPRESSURE_WAIT_TIMEOUT",
                        )
            finally:
                self._waiters -= 1
                if self.global_coordinator is not None:
                    self.global_coordinator.active_waiters = max(0, self.global_coordinator.active_waiters - 1)

    async def release_reservation(self, reservation_id: str, *, reason: str = "CANCELLED") -> bool:
        res = self._reservations.get(reservation_id)
        if res is None or res.status != ReservationStatus.RESERVED:
            return False
        res.status = ReservationStatus.RELEASED
        res.reason = reason
        self._reserved_frames = max(0, self._reserved_frames - res.reserved_frames)
        self._reserved_samples = max(0, self._reserved_samples - res.reserved_target_samples)
        self._reserved_bytes = max(0, self._reserved_bytes - res.reserved_payload_bytes)
        self._reserved_workspace_bytes = max(0, self._reserved_workspace_bytes - res.reserved_workspace_bytes)
        if self.global_coordinator is not None:
            self.global_coordinator.release(res.reserved_frames, res.reserved_payload_bytes)
        self._update_watermark_state()
        async with self._cond:
            self._cond.notify_all()
        return True

    async def convert_and_enqueue(
        self,
        reservation_id: str,
        frames: tuple[RenderedFrame, ...] | list[RenderedFrame],
        *,
        plan_revision: int = 0,
    ) -> tuple[bool, str]:
        """Atomically replace reservation estimate with actual frame ownership."""
        res = self._reservations.get(reservation_id)
        if res is None or res.status != ReservationStatus.RESERVED:
            return False, "INVALID_OR_CONSUMED_RESERVATION"
        stale = self._validate_scope(res.generation_ref, plan_revision, res.stream_ref)
        if stale is not None:
            await self.release_reservation(reservation_id, reason=stale.value)
            return False, stale.value

        actual_frames = len(frames)
        actual_samples = sum(f.sample_count for f in frames)
        actual_bytes = sum(len(f.payload) for f in frames)

        # Check if actual exceeds reservation AND would exceed hard cap
        extra_frames = actual_frames - res.reserved_frames
        extra_samples = actual_samples - res.reserved_target_samples
        extra_bytes = actual_bytes - res.reserved_payload_bytes
        if (
            self.occupied_frames + extra_frames > self.budget.max_frames
            or self.occupied_samples + extra_samples > self.budget.max_target_samples
            or self.occupied_bytes + extra_bytes > self.budget.max_payload_bytes
        ):
            await self.release_reservation(reservation_id, reason="ACTUAL_EXCEEDS_CAP")
            return False, "ACTUAL_EXCEEDS_CAP"

        # Validate ordering & uniqueness before mutating
        expected_seq = self._cursor.next_never_claimed_sequence + len(self._queued) + (1 if self._selected else 0)
        for idx, frame in enumerate(frames):
            fkey = (frame.generation_ref.turn_id, frame.generation_ref.generation_id, frame.sequence)
            if fkey in self._seen_frame_keys:
                await self.release_reservation(reservation_id, reason="DUPLICATE_FRAME")
                return False, "DUPLICATE_FRAME"
            if self._queued and frame.sequence != self._queued[-1].frame.sequence + 1 + idx:
                await self.release_reservation(reservation_id, reason="OUT_OF_ORDER_SEQUENCE")
                return False, "OUT_OF_ORDER_SEQUENCE"
            if not self._queued and self._selected is not None and frame.sequence != self._selected.frame.sequence + 1 + idx:
                await self.release_reservation(reservation_id, reason="OUT_OF_ORDER_SEQUENCE")
                return False, "OUT_OF_ORDER_SEQUENCE"
            if not self._queued and self._selected is None and frame.sequence != expected_seq + idx:
                if self._cursor.next_never_claimed_sequence > 0:
                    await self.release_reservation(reservation_id, reason="OUT_OF_ORDER_SEQUENCE")
                    return False, "OUT_OF_ORDER_SEQUENCE"

        # Consume reservation
        res.status = ReservationStatus.CONSUMED
        res.reason = "CONSUMED"
        self._reserved_frames = max(0, self._reserved_frames - res.reserved_frames)
        self._reserved_samples = max(0, self._reserved_samples - res.reserved_target_samples)
        self._reserved_bytes = max(0, self._reserved_bytes - res.reserved_payload_bytes)
        self._reserved_workspace_bytes = max(0, self._reserved_workspace_bytes - res.reserved_workspace_bytes)
        if self.global_coordinator is not None and (extra_frames != 0 or extra_bytes != 0):
            if extra_frames < 0 or extra_bytes < 0:
                self.global_coordinator.release(max(0, -extra_frames), max(0, -extra_bytes))
            else:
                self.global_coordinator.acquire(max(0, extra_frames), max(0, extra_bytes))

        for frame in frames:
            fkey = (frame.generation_ref.turn_id, frame.generation_ref.generation_id, frame.sequence)
            self._seen_frame_keys.add(fkey)
            entry = QueueEntry(
                frame=frame,
                plan_revision=plan_revision,
                state=MediaItemState.QUEUED_UNSENT,
                reservation_id=reservation_id,
            )
            self._queued.append(entry)
            self._queued_frames += 1
            self._queued_samples += frame.sample_count
            self._queued_bytes += len(frame.payload)

        self._update_watermark_state()
        async with self._cond:
            self._cond.notify_all()
        return True, "ENQUEUED"

    def select_next_unsent(self) -> QueueEntry | None:
        if self._selected is not None:
            return self._selected
        if not self._queued:
            return None
        entry = self._queued.popleft()
        self._queued_frames -= 1
        self._queued_samples -= entry.frame.sample_count
        self._queued_bytes -= len(entry.frame.payload)
        entry.state = MediaItemState.SELECTED_UNSENT
        self._selected = entry
        return entry

    def mark_selected_claimed(self, claim_id: str) -> QueueEntry | None:
        entry = self._selected
        if entry is None:
            return None
        self._selected = None
        entry.state = MediaItemState.SUBMISSION_CLAIMED
        entry.claim_id = claim_id
        self._in_flight[claim_id] = entry
        self._in_flight_frames += 1
        self._in_flight_samples += entry.frame.sample_count
        self._in_flight_bytes += len(entry.frame.payload)

        # Advance exact never-claimed cursor once!
        self._cursor.last_claimed_sequence = entry.frame.sequence
        self._cursor.next_never_claimed_sequence = entry.frame.sequence + 1
        self._cursor.next_never_claimed_sample_offset = entry.frame.sample_offset + entry.frame.sample_count
        self._cursor.in_flight_sequences.add(entry.frame.sequence)
        return entry

    def requeue_selected_paused(self) -> bool:
        entry = self._selected
        if entry is None:
            return False
        self._selected = None
        entry.state = MediaItemState.QUEUED_UNSENT
        self._queued.appendleft(entry)
        self._queued_frames += 1
        self._queued_samples += entry.frame.sample_count
        self._queued_bytes += len(entry.frame.payload)
        return True

    async def mark_claim_completed_local(self, claim_id: str) -> bool:
        entry = self._in_flight.pop(claim_id, None)
        if entry is None:
            return False
        entry.state = MediaItemState.COMPLETED_LOCAL
        self._in_flight_frames = max(0, self._in_flight_frames - 1)
        self._in_flight_samples = max(0, self._in_flight_samples - entry.frame.sample_count)
        self._in_flight_bytes = max(0, self._in_flight_bytes - len(entry.frame.payload))
        self._cursor.in_flight_sequences.discard(entry.frame.sequence)
        self._cursor.completed_local_sequences.add(entry.frame.sequence)
        if self.global_coordinator is not None:
            self.global_coordinator.release(1, len(entry.frame.payload))
        self._update_watermark_state()
        async with self._cond:
            self._cond.notify_all()
        return True

    async def mark_claim_unknown_delivery(self, claim_id: str) -> bool:
        entry = self._in_flight.get(claim_id)
        if entry is None:
            return False
        entry.state = MediaItemState.UNKNOWN_DELIVERY
        self._cursor.in_flight_sequences.discard(entry.frame.sequence)
        self._cursor.unknown_in_flight_sequences.add(entry.frame.sequence)
        return True

    def record_receiver_ack(self, sequence: int) -> None:
        """Record remote ACK separately; NEVER rewinds next_never_claimed_sequence."""
        if self._cursor.receiver_acked_sequence is None or sequence > self._cursor.receiver_acked_sequence:
            self._cursor.receiver_acked_sequence = sequence

    async def purge_unsent_generation(
        self,
        intent: FlushIntent,
        *,
        remote_scope: ObservationScope = ObservationScope.PBX,
        remote_supported: bool = False,
        remote_command_sent: bool = False,
    ) -> FlushReceipt:
        """
        Atomically purge owned UNSENT items (RESERVED, QUEUED_UNSENT, SELECTED_UNSENT)
        for target generation, leaving IN_FLIGHT items tracked separately, and wake waiters.
        """
        gkey = (intent.generation_ref.turn_id, intent.generation_ref.generation_id)
        self._revoked_generations.add(gkey)

        purged_frames = 0
        purged_bytes = 0
        purged_valid_samples = 0

        # Release pending reservations for this generation
        for rid, res in list(self._reservations.items()):
            if res.status == ReservationStatus.RESERVED and res.generation_ref == intent.generation_ref:
                await self.release_reservation(rid, reason="FLUSH_PURGED")

        if self._selected is not None and self._selected.frame.generation_ref == intent.generation_ref:
            entry = self._selected
            self._selected = None
            entry.state = MediaItemState.DISCARDED
            entry.discard_reason = intent.reason
            purged_frames += 1
            purged_bytes += len(entry.frame.payload)
            purged_valid_samples += entry.frame.valid_sample_count
            if self.global_coordinator is not None:
                self.global_coordinator.release(1, len(entry.frame.payload))

        kept: deque[QueueEntry] = deque()
        while self._queued:
            entry = self._queued.popleft()
            if entry.frame.generation_ref == intent.generation_ref:
                entry.state = MediaItemState.DISCARDED
                entry.discard_reason = intent.reason
                purged_frames += 1
                purged_bytes += len(entry.frame.payload)
                purged_valid_samples += entry.frame.valid_sample_count
                if self.global_coordinator is not None:
                    self.global_coordinator.release(1, len(entry.frame.payload))
            else:
                kept.append(entry)
        self._queued = kept
        self._queued_frames = len(self._queued)
        self._queued_samples = sum(e.frame.sample_count for e in self._queued)
        self._queued_bytes = sum(len(e.frame.payload) for e in self._queued)

        self._update_watermark_state()
        async with self._cond:
            self._cond.notify_all()

        if not remote_supported:
            remote_res = FlushScopeResult(
                scope=remote_scope,
                status="UNSUPPORTED",
                purged_frames=None,
                purged_payload_bytes=None,
                purged_valid_samples=None,
                reason="REMOTE_FLUSH_NOT_SUPPORTED",
            )
        elif remote_command_sent:
            remote_res = FlushScopeResult(
                scope=remote_scope,
                status="PENDING",
                purged_frames=None,
                purged_payload_bytes=None,
                purged_valid_samples=None,
                reason="REMOTE_ACK_PENDING",
            )
        else:
            remote_res = FlushScopeResult(
                scope=remote_scope,
                status="UNKNOWN",
                purged_frames=None,
                purged_payload_bytes=None,
                purged_valid_samples=None,
                reason="REMOTE_COMMAND_NOT_SENT",
            )

        return FlushReceipt(
            command_id=intent.command_id,
            generation_ref=intent.generation_ref,
            stream_ref=intent.stream_ref,
            local=FlushScopeResult(
                scope=ObservationScope.SERVER,
                status="FLUSHED",
                purged_frames=purged_frames,
                purged_payload_bytes=purged_bytes,
                purged_valid_samples=purged_valid_samples,
                reason=intent.reason,
            ),
            remote=remote_res,
            in_flight_sequences=self.in_flight_sequences,
            audible_silence_verified=False,
            endpoint_silence_ms=None,
        )

    async def close(self) -> None:
        self._closed = True
        for rid in list(self._reservations.keys()):
            await self.release_reservation(rid, reason="QUEUE_CLOSED")
        async with self._cond:
            self._cond.notify_all()
