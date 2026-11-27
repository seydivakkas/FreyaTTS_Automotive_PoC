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
from dataclasses import dataclass
from typing import Callable

from backend.core.contracts.common import StreamRef
from backend.core.runtime.resource_ledger import LeaseState, ResourceLedger
from backend.voice_activity.frame_synchronizer import VADWindow
from backend.voice_activity.vad_engine import VADEngineAdapter, VADIsolationStrategy, VADObservation


@dataclass(frozen=True, slots=True)
class LateCallbackOutcome:
    accepted: bool
    reason: str
    observation: VADObservation | None = None


class VADStateManager:
    """
    Per-stream serialized VAD state owner backed by M02 ResourceLedger leases.

    - Retains recurrent state across frames, rejected candidates, normal endpoints, and turns.
    - Resets ONLY on initial attach, explicit gap/format_epoch advance, close, or explicit recovery.
    - Never resets on output generation cancel or new dialogue turn.
    - Serializes concurrent submissions on the same stream while keeping separate streams isolated.
    """

    def __init__(
        self,
        stream_ref: StreamRef,
        engine: VADEngineAdapter,
        *,
        ledger: ResourceLedger | None = None,
    ) -> None:
        self._stream_ref = stream_ref
        self._engine = engine
        self._ledger = ledger or ResourceLedger()
        self._lock = threading.RLock()
        self._closed = False
        self._revoked = False
        self._lease_counter = 0
        self._active_lease_id: str | None = None
        self._strategy: VADIsolationStrategy | None = None
        self._slot_state: object | None = None
        self._inflight_jobs: dict[tuple[int, int], str] = {}
        self._last_processed_window_index: int = -1
        self._consecutive_failures: int = 0

        self._allocate_slot_locked()

    @property
    def stream_ref(self) -> StreamRef:
        return self._stream_ref

    @property
    def lease_id(self) -> str | None:
        with self._lock:
            return self._active_lease_id

    @property
    def inflight_count(self) -> int:
        with self._lock:
            return len(self._inflight_jobs)

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures

    def _allocate_slot_locked(self) -> None:
        self._lease_counter += 1
        lid = (
            f"vad:{self._stream_ref.session_id}:{self._stream_ref.stream_id}:"
            f"ep{self._stream_ref.format_epoch}:{self._lease_counter}"
        )
        strategy, slot = self._engine.create_stream_slot()
        self._ledger.acquire(lid, "vad_stream_state", borrowed=False, release_fn=self._make_release_fn(slot))
        self._active_lease_id = lid
        self._strategy = strategy
        self._slot_state = slot
        self._last_processed_window_index = -1

    @staticmethod
    def _make_release_fn(slot: object) -> Callable[[], None]:
        def _release() -> None:
            if hasattr(slot, "reset_states") and callable(slot.reset_states):
                slot.reset_states()

        return _release

    def reset_for_gap_or_epoch(self, new_stream_ref: StreamRef | None = None) -> None:
        """Reset recurrent VAD state strictly on explicit gap or format_epoch advance."""
        with self._lock:
            if self._closed:
                return
            if new_stream_ref is not None:
                if new_stream_ref.format_epoch != self._stream_ref.format_epoch:
                    old_lid = self._active_lease_id
                    if old_lid is not None and not self._inflight_jobs:
                        self._ledger.release(old_lid)
                    elif old_lid is not None:
                        self._ledger.quarantine(old_lid)
                    self._stream_ref = new_stream_ref
                    self._allocate_slot_locked()
                    return
                self._stream_ref = new_stream_ref
            self._slot_state = self._engine.reset_slot(self._slot_state)
            self._consecutive_failures = 0

    def evaluate_window(self, window: VADWindow) -> VADObservation:
        """
        Synchronously evaluate one 512-sample VADWindow in strict serialized stream order.
        Provider exceptions or invalid scores yield an explicit failed VADObservation without
        fabricating 0.0 silence or triggering false endpointing.
        """
        with self._lock:
            t0 = self._engine.clock.monotonic_ns()
            clock_domain = self._engine.clock.clock_domain
            if self._closed or self._revoked:
                t1 = self._engine.clock.monotonic_ns()
                return VADObservation(
                    stream_ref=window.stream_ref,
                    window_index=window.window_index,
                    start_sample=window.start_sample,
                    end_sample_exclusive=window.end_sample_exclusive,
                    valid_samples=window.valid_samples,
                    ok=False,
                    score=None,
                    model_revision=self._engine.model_revision,
                    inference_start_ns=t0,
                    inference_end_ns=t1,
                    clock_domain=clock_domain,
                    padded_for_inference=window.padded_for_inference,
                    error_code="STREAM_REVOKED_OR_CLOSED",
                    error_detail="stream revoked or closed before inference",
                )
            if window.stream_ref.format_epoch != self._stream_ref.format_epoch:
                t1 = self._engine.clock.monotonic_ns()
                return VADObservation(
                    stream_ref=window.stream_ref,
                    window_index=window.window_index,
                    start_sample=window.start_sample,
                    end_sample_exclusive=window.end_sample_exclusive,
                    valid_samples=window.valid_samples,
                    ok=False,
                    score=None,
                    model_revision=self._engine.model_revision,
                    inference_start_ns=t0,
                    inference_end_ns=t1,
                    clock_domain=clock_domain,
                    padded_for_inference=window.padded_for_inference,
                    error_code="STALE_EPOCH",
                    error_detail="window epoch does not match active stream epoch",
                )
            if window.window_index <= self._last_processed_window_index:
                t1 = self._engine.clock.monotonic_ns()
                return VADObservation(
                    stream_ref=window.stream_ref,
                    window_index=window.window_index,
                    start_sample=window.start_sample,
                    end_sample_exclusive=window.end_sample_exclusive,
                    valid_samples=window.valid_samples,
                    ok=False,
                    score=None,
                    model_revision=self._engine.model_revision,
                    inference_start_ns=t0,
                    inference_end_ns=t1,
                    clock_domain=clock_domain,
                    padded_for_inference=window.padded_for_inference,
                    error_code="OUT_OF_ORDER_WINDOW",
                    error_detail="window_index already processed",
                )

            lid = self._active_lease_id
            if lid is not None:
                self._ledger.mark_in_flight(lid)
            try:
                score, next_state = self._engine.infer_slot(
                    self._slot_state,
                    window.model_input_f32,
                    sample_rate_hz=16000,
                )
                self._slot_state = next_state
                self._last_processed_window_index = window.window_index
                self._consecutive_failures = 0
                t1 = self._engine.clock.monotonic_ns()
                return VADObservation(
                    stream_ref=window.stream_ref,
                    window_index=window.window_index,
                    start_sample=window.start_sample,
                    end_sample_exclusive=window.end_sample_exclusive,
                    valid_samples=window.valid_samples,
                    ok=True,
                    score=score,
                    model_revision=self._engine.model_revision,
                    inference_start_ns=t0,
                    inference_end_ns=t1,
                    clock_domain=clock_domain,
                    padded_for_inference=window.padded_for_inference,
                )
            except Exception as exc:
                self._consecutive_failures += 1
                self._last_processed_window_index = window.window_index
                t1 = self._engine.clock.monotonic_ns()
                return VADObservation(
                    stream_ref=window.stream_ref,
                    window_index=window.window_index,
                    start_sample=window.start_sample,
                    end_sample_exclusive=window.end_sample_exclusive,
                    valid_samples=window.valid_samples,
                    ok=False,
                    score=None,
                    model_revision=self._engine.model_revision,
                    inference_start_ns=t0,
                    inference_end_ns=t1,
                    clock_domain=clock_domain,
                    padded_for_inference=window.padded_for_inference,
                    error_code="PROVIDER_FAILURE",
                    error_detail=type(exc).__name__,
                )
            finally:
                if lid is not None:
                    lease = self._ledger._leases.get(lid)
                    if lease is not None and lease.state == LeaseState.IN_FLIGHT:
                        lease.state = LeaseState.OWNED

    def begin_inflight_job(self, window: VADWindow) -> str:
        """Acquire/mark an in-flight native inference lease before running work outside the lock."""
        with self._lock:
            if self._closed or self._revoked:
                raise RuntimeError("Cannot start native VAD job on closed/revoked stream")
            if self._active_lease_id is None:
                raise RuntimeError("No active VAD lease")
            job_lid = f"{self._active_lease_id}:job:{window.stream_ref.format_epoch}:{window.window_index}"
            self._ledger.acquire(job_lid, "vad_inflight_job", borrowed=False)
            self._ledger.mark_in_flight(job_lid)
            self._inflight_jobs[(window.stream_ref.format_epoch, window.window_index)] = job_lid
            return job_lid

    def complete_inflight_job(
        self,
        window: VADWindow,
        observation: VADObservation,
    ) -> LateCallbackOutcome:
        """
        Complete an async/off-thread inference job and release its lease once.
        If stream was revoked/closed or epoch changed while in flight, reject stale result cleanly.
        """
        key = (window.stream_ref.format_epoch, window.window_index)
        with self._lock:
            job_lid = self._inflight_jobs.pop(key, None)
            if job_lid is not None:
                self._ledger.release(job_lid)
            if self._closed or self._revoked:
                if not self._inflight_jobs and self._active_lease_id is not None:
                    self._ledger.release(self._active_lease_id)
                return LateCallbackOutcome(accepted=False, reason="STREAM_REVOKED_OR_CLOSED", observation=None)
            if window.stream_ref.format_epoch != self._stream_ref.format_epoch:
                return LateCallbackOutcome(accepted=False, reason="STALE_EPOCH", observation=None)
            return LateCallbackOutcome(accepted=True, reason="ACCEPTED", observation=observation)

    def revoke_and_close(self) -> None:
        """
        Idempotent cleanup. If native jobs are still in flight, quarantine the main lease
        until the last in-flight job completes; otherwise release immediately.
        """
        with self._lock:
            if self._closed:
                return
            self._revoked = True
            self._closed = True
            if self._active_lease_id is not None:
                if self._inflight_jobs:
                    self._ledger.quarantine(self._active_lease_id)
                else:
                    self._ledger.release(self._active_lease_id)
