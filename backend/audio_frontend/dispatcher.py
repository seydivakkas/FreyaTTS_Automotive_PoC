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
from dataclasses import dataclass
from typing import Callable

from backend.audio_frontend.raw_dtmf_bridge import RawDtmfEvent
from backend.audio_frontend.stream_state import StreamAudioState
from backend.core.contracts.audio import AudioFrame
from backend.core.contracts.common import StreamRef
from backend.core.runtime.result_admission import AdmissionStatus
from backend.core.runtime.session_context import SessionContext, SessionLifecycleState


@dataclass(frozen=True, slots=True)
class DispatchResult:
    status: AdmissionStatus
    reason: str
    frame: AudioFrame | None = None
    enqueued_monotonic_ns: int | None = None


class F1BoundaryDispatcher:
    """
    Bounded, fence-checked output dispatcher at the F0 -> F1 boundary.

    - Enforces capacity reservation BEFORE admitting 16 kHz mono M01 AudioFrames.
    - Tracks queued + in-flight bytes and sample counts.
    - Separates control/DTMF lane from media queue so control is never starved
      when the media queue is full.
    - Checks session lifecycle, root_scope cancellation, and active format_epoch
      fences (note: output generation cancellation / barge-in does NOT cancel
      inbound F0->F1 speech admission).
    """

    def __init__(
        self,
        session_ctx: SessionContext,
        *,
        max_items: int = 64,
        max_bytes: int = 256 * 1024,
        f1_consumer: Callable[[AudioFrame], None] | None = None,
        control_consumer: Callable[[RawDtmfEvent], None] | None = None,
    ) -> None:
        if max_items < 1 or max_bytes < 1:
            raise ValueError("Dispatcher capacity limits must be positive")
        self.session_ctx = session_ctx
        self.max_items = max_items
        self.max_bytes = max_bytes
        self._f1_consumer = f1_consumer
        self._control_consumer = control_consumer

        self._lock = threading.Lock()
        self._media_queue: deque[tuple[AudioFrame, int]] = deque()
        self._control_queue: deque[RawDtmfEvent] = deque()
        self._queued_bytes: int = 0
        self._queued_samples: int = 0
        self._in_flight_bytes: int = 0
        self._in_flight_samples: int = 0
        self._seen_keys: set[tuple[str, int, int]] = set()
        self.dropped_stale_count: int = 0
        self.backpressure_count: int = 0
        self.consumer_error_count: int = 0

    @property
    def queued_items(self) -> int:
        with self._lock:
            return len(self._media_queue)

    @property
    def queued_bytes(self) -> int:
        with self._lock:
            return self._queued_bytes

    @property
    def queued_samples(self) -> int:
        with self._lock:
            return self._queued_samples

    @property
    def in_flight_bytes(self) -> int:
        with self._lock:
            return self._in_flight_bytes

    @property
    def control_queued_count(self) -> int:
        with self._lock:
            return len(self._control_queue)

    def can_reserve(self, size_bytes: int) -> bool:
        with self._lock:
            return (
                len(self._media_queue) < self.max_items
                and (self._queued_bytes + self._in_flight_bytes + size_bytes) <= self.max_bytes
            )

    def reserve_in_flight(self, size_bytes: int, sample_count: int) -> bool:
        """Reserve capacity for an in-flight frame before DSP/resampling work begins."""
        with self._lock:
            if len(self._media_queue) >= self.max_items:
                return False
            if (self._queued_bytes + self._in_flight_bytes + size_bytes) > self.max_bytes:
                return False
            self._in_flight_bytes += size_bytes
            self._in_flight_samples += sample_count
            return True

    def release_in_flight(self, size_bytes: int, sample_count: int) -> None:
        with self._lock:
            self._in_flight_bytes = max(0, self._in_flight_bytes - size_bytes)
            self._in_flight_samples = max(0, self._in_flight_samples - sample_count)

    def check_fence(self, stream_state: StreamAudioState, stream_ref: StreamRef) -> AdmissionStatus:
        """Verify session, root cancellation, stream state, and format_epoch fence."""
        if self.session_ctx.lifecycle_state in {SessionLifecycleState.CLOSING, SessionLifecycleState.CLOSED}:
            return AdmissionStatus.CLOSED
        if self.session_ctx.root_scope.is_cancel_requested:
            return AdmissionStatus.CANCELED
        if stream_ref.session_id != self.session_ctx.identity.session_id:
            return AdmissionStatus.STALE_SESSION
        if stream_state.closed:
            return AdmissionStatus.CLOSED
        if stream_ref.format_epoch != stream_state.stream_ref.format_epoch:
            return AdmissionStatus.STALE_GENERATION
        return AdmissionStatus.ACCEPTED

    def admit_output_frame(
        self,
        frame: AudioFrame,
        stream_state: StreamAudioState,
    ) -> DispatchResult:
        """
        Atomically fence-check and enqueue a validated 16 kHz mono AudioFrame for F1.
        """
        fence = self.check_fence(stream_state, frame.stream_ref)
        if fence != AdmissionStatus.ACCEPTED:
            with self._lock:
                self.dropped_stale_count += 1
            return DispatchResult(status=fence, reason=f"fence_rejected:{fence.value}")

        size_bytes = len(frame.payload)
        dedup_key = (frame.stream_ref.stream_id, frame.stream_ref.format_epoch, frame.sequence)
        now_ns = self.session_ctx.clock.monotonic_ns()

        with self._lock:
            if dedup_key in self._seen_keys:
                return DispatchResult(status=AdmissionStatus.DUPLICATE, reason="duplicate_output_sequence")
            if (
                len(self._media_queue) >= self.max_items
                or (self._queued_bytes + self._in_flight_bytes + size_bytes) > self.max_bytes
            ):
                self.backpressure_count += 1
                return DispatchResult(status=AdmissionStatus.BACKPRESSURE, reason="f1_queue_capacity_exceeded")
            self._media_queue.append((frame, now_ns))
            self._queued_bytes += size_bytes
            self._queued_samples += frame.sample_count
            self._seen_keys.add(dedup_key)

        if self._f1_consumer is not None:
            popped = self.pop_output_frame()
            if popped is not None:
                try:
                    self._f1_consumer(popped)
                except Exception:
                    with self._lock:
                        self.consumer_error_count += 1
                    return DispatchResult(
                        status=AdmissionStatus.INVALID,
                        reason="f1_consumer_exception",
                        frame=popped,
                        enqueued_monotonic_ns=now_ns,
                    )

        return DispatchResult(
            status=AdmissionStatus.ACCEPTED,
            reason="admitted_to_f1_boundary",
            frame=frame,
            enqueued_monotonic_ns=now_ns,
        )

    def admit_control_event(self, event: RawDtmfEvent) -> AdmissionStatus:
        """Admit raw DTMF control event on dedicated control lane (never starved by full media queue)."""
        if self.session_ctx.lifecycle_state in {SessionLifecycleState.CLOSING, SessionLifecycleState.CLOSED}:
            return AdmissionStatus.CLOSED
        if self.session_ctx.root_scope.is_cancel_requested:
            return AdmissionStatus.CANCELED
        with self._lock:
            self._control_queue.append(event)
        if self._control_consumer is not None:
            ev = self.pop_control_event()
            if ev is not None:
                try:
                    self._control_consumer(ev)
                except Exception:
                    with self._lock:
                        self.consumer_error_count += 1
        return AdmissionStatus.ACCEPTED

    def pop_output_frame(self) -> AudioFrame | None:
        with self._lock:
            if not self._media_queue:
                return None
            frame, _ = self._media_queue.popleft()
            self._queued_bytes = max(0, self._queued_bytes - len(frame.payload))
            self._queued_samples = max(0, self._queued_samples - frame.sample_count)
            return frame

    def pop_control_event(self) -> RawDtmfEvent | None:
        with self._lock:
            if not self._control_queue:
                return None
            return self._control_queue.popleft()

    def drain_output_frames(self) -> list[AudioFrame]:
        out: list[AudioFrame] = []
        while True:
            frame = self.pop_output_frame()
            if frame is None:
                break
            out.append(frame)
        return out

    def drain_control_events(self) -> list[RawDtmfEvent]:
        out: list[RawDtmfEvent] = []
        while True:
            ev = self.pop_control_event()
            if ev is None:
                break
            out.append(ev)
        return out

    def clear_stream_epoch(self, stream_ref: StreamRef) -> int:
        """Drop buffered frames belonging to an old closed/rolled-over stream epoch."""
        with self._lock:
            kept: deque[tuple[AudioFrame, int]] = deque()
            removed = 0
            new_bytes = 0
            new_samples = 0
            for frame, ts in self._media_queue:
                if (
                    frame.stream_ref.stream_id == stream_ref.stream_id
                    and frame.stream_ref.format_epoch == stream_ref.format_epoch
                ):
                    removed += 1
                else:
                    kept.append((frame, ts))
                    new_bytes += len(frame.payload)
                    new_samples += frame.sample_count
            self._media_queue = kept
            self._queued_bytes = new_bytes
            self._queued_samples = new_samples
            return removed

    def clear_all(self) -> int:
        with self._lock:
            count = len(self._media_queue) + len(self._control_queue)
            self._media_queue.clear()
            self._control_queue.clear()
            self._queued_bytes = 0
            self._queued_samples = 0
            return count
