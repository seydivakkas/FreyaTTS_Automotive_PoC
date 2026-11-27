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
from enum import StrEnum
from typing import Callable, Protocol

from backend.core.contracts.common import StreamRef, TurnRef
from backend.core.contracts.speech import Utterance
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.result_admission import AdmissionStatus
from backend.core.runtime.session_context import SessionContext, SessionLifecycleState
from backend.voice_activity.endpointing import EndpointCutDecision


class FinalizationStatus(StrEnum):
    ADMITTED = "ADMITTED"
    DUPLICATE = "DUPLICATE"
    REJECTED_REVOKED = "REJECTED_REVOKED"
    REJECTED_CLOSED = "REJECTED_CLOSED"
    BACKPRESSURE = "BACKPRESSURE"
    CONSUMER_ERROR = "CONSUMER_ERROR"


@dataclass(frozen=True, slots=True)
class FinalizationReceipt:
    utterance_id: str
    stream_ref: StreamRef
    status: FinalizationStatus
    turn_ref: TurnRef | None
    utterance: Utterance | None
    start_sample: int
    end_sample_exclusive: int
    error_detail: str = ""


class UtteranceConsumerProtocol(Protocol):
    def can_accept(self, payload_bytes: int) -> bool: ...

    def accept_utterance(self, utterance: Utterance) -> None: ...


class BoundedUtteranceQueue:
    """Bounded per-stream/session consumer queue for finalized Utterances (no GPU/ASR coupling)."""

    def __init__(self, *, max_items: int = 1, max_bytes: int = 1_280_000) -> None:
        if max_items < 1 or max_bytes < 1:
            raise ValueError("BoundedUtteranceQueue caps must be positive")
        self.max_items = max_items
        self.max_bytes = max_bytes
        self._items: deque[Utterance] = deque()
        self._bytes_used: int = 0
        self._lock = threading.Lock()

    @property
    def item_count(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def bytes_used(self) -> int:
        with self._lock:
            return self._bytes_used

    def can_accept(self, payload_bytes: int) -> bool:
        with self._lock:
            return len(self._items) < self.max_items and (self._bytes_used + payload_bytes) <= self.max_bytes

    def accept_utterance(self, utterance: Utterance) -> None:
        payload_len = len(utterance.payload or b"")
        with self._lock:
            if len(self._items) >= self.max_items or (self._bytes_used + payload_len) > self.max_bytes:
                raise RuntimeError("BACKPRESSURE: Utterance queue full")
            self._items.append(utterance)
            self._bytes_used += payload_len

    def pop_next(self) -> Utterance | None:
        with self._lock:
            if not self._items:
                return None
            utt = self._items.popleft()
            self._bytes_used -= len(utt.payload or b"")
            return utt


class TurnAllocatorProtocol(Protocol):
    def is_stream_active(self) -> bool: ...

    def allocate_turn(self) -> TurnRef: ...


class M02TurnAllocatorBridge:
    """Bridges synchronous atomic Utterance handoff to M02 SessionContext turn authority."""

    def __init__(self, session_ctx: SessionContext, input_scope: CancellationScope | None = None) -> None:
        self._ctx = session_ctx
        self._input_scope = input_scope or session_ctx.root_scope

    def is_stream_active(self) -> bool:
        if self._ctx.lifecycle_state != SessionLifecycleState.ACTIVE:
            return False
        if self._ctx.root_scope.is_cancel_requested or self._input_scope.is_cancel_requested:
            return False
        return True

    def allocate_turn(self) -> TurnRef:
        if not self.is_stream_active():
            raise RuntimeError("Cannot allocate turn on inactive/revoked M02 SessionContext")
        tref, _ = self._ctx.tg.begin_turn()
        return tref


class UtteranceManager:
    """
    Atomic once-only finalization & M02 turn handoff owner.

    - Checks revocation/closure and downstream queue capacity BEFORE allocating an M02 TurnRef.
    - Deduplicates finalization identity (session_id, stream_id, format_epoch, start_sample, end_sample_exclusive)
      and explicit utterance_id so concurrent EOS/silence/max-cap callbacks cannot dispatch twice.
    - Never synthesizes fake turn IDs from frame sequences.
    """

    def __init__(
        self,
        stream_ref: StreamRef,
        *,
        turn_allocator: TurnAllocatorProtocol,
        consumer: UtteranceConsumerProtocol | None = None,
    ) -> None:
        self._stream_ref = stream_ref
        self._turn_allocator = turn_allocator
        self._consumer = consumer
        self._lock = threading.Lock()
        self._seq_counter = 0
        self._finalized_receipts: dict[tuple[int, int, int], FinalizationReceipt] = {}
        self._seen_utterance_ids: dict[str, FinalizationReceipt] = {}
        self._revoked = False
        self._closed = False

    @property
    def receipt_count(self) -> int:
        with self._lock:
            return len(self._finalized_receipts)

    def update_epoch(self, new_stream_ref: StreamRef) -> None:
        with self._lock:
            self._stream_ref = new_stream_ref

    def revoke_input(self) -> None:
        with self._lock:
            self._revoked = True

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def get_receipt(self, utterance_id: str) -> FinalizationReceipt | None:
        with self._lock:
            return self._seen_utterance_ids.get(utterance_id)

    def finalize_and_handoff(
        self,
        decision: EndpointCutDecision,
        *,
        payload: bytes,
        has_discontinuity: bool = False,
        explicit_utterance_id: str | None = None,
    ) -> FinalizationReceipt:
        """
        Atomically validate, reserve capacity, allocate M02 TurnRef, build immutable M01 Utterance,
        and deliver at most once.
        """
        if not decision.should_finalize or decision.reason is None:
            raise ValueError("EndpointCutDecision is not ready for finalization")

        with self._lock:
            interval_key = (
                self._stream_ref.format_epoch,
                decision.start_sample,
                decision.end_sample_exclusive,
            )
            if explicit_utterance_id is not None and explicit_utterance_id in self._seen_utterance_ids:
                return self._seen_utterance_ids[explicit_utterance_id]
            if interval_key in self._finalized_receipts:
                return self._finalized_receipts[interval_key]

            self._seq_counter += 1
            utt_id = explicit_utterance_id or (
                f"utt-{self._stream_ref.session_id}-{self._stream_ref.stream_id}-"
                f"ep{self._stream_ref.format_epoch}-{self._seq_counter}"
            )

            if self._closed:
                rec = FinalizationReceipt(
                    utterance_id=utt_id,
                    stream_ref=self._stream_ref,
                    status=FinalizationStatus.REJECTED_CLOSED,
                    turn_ref=None,
                    utterance=None,
                    start_sample=decision.start_sample,
                    end_sample_exclusive=decision.end_sample_exclusive,
                    error_detail="stream_closed",
                )
                return rec

            if self._revoked or not self._turn_allocator.is_stream_active():
                rec = FinalizationReceipt(
                    utterance_id=utt_id,
                    stream_ref=self._stream_ref,
                    status=FinalizationStatus.REJECTED_REVOKED,
                    turn_ref=None,
                    utterance=None,
                    start_sample=decision.start_sample,
                    end_sample_exclusive=decision.end_sample_exclusive,
                    error_detail="stream_revoked_before_handoff",
                )
                return rec

            if self._consumer is not None and not self._consumer.can_accept(len(payload)):
                rec = FinalizationReceipt(
                    utterance_id=utt_id,
                    stream_ref=self._stream_ref,
                    status=FinalizationStatus.BACKPRESSURE,
                    turn_ref=None,
                    utterance=None,
                    start_sample=decision.start_sample,
                    end_sample_exclusive=decision.end_sample_exclusive,
                    error_detail="downstream_queue_full",
                )
                return rec

            turn_ref = self._turn_allocator.allocate_turn()
            utterance = Utterance(
                utterance_id=utt_id,
                stream_ref=self._stream_ref,
                turn_ref=turn_ref,
                start_sample=decision.start_sample,
                end_sample_exclusive=decision.end_sample_exclusive,
                finalized=True,
                finalization_reason=decision.reason.value,
                frame_refs=(f"slice:{self._stream_ref.format_epoch}:{decision.start_sample}:{decision.end_sample_exclusive}",),
                actual_pre_roll_samples=decision.actual_pre_roll_samples,
                actual_post_roll_samples=decision.actual_post_roll_samples,
                has_discontinuity=has_discontinuity,
                payload=payload,
            )

            if self._consumer is not None:
                try:
                    self._consumer.accept_utterance(utterance)
                except Exception as exc:
                    rec = FinalizationReceipt(
                        utterance_id=utt_id,
                        stream_ref=self._stream_ref,
                        status=FinalizationStatus.CONSUMER_ERROR,
                        turn_ref=turn_ref,
                        utterance=utterance,
                        start_sample=decision.start_sample,
                        end_sample_exclusive=decision.end_sample_exclusive,
                        error_detail=type(exc).__name__,
                    )
                    self._finalized_receipts[interval_key] = rec
                    self._seen_utterance_ids[utt_id] = rec
                    return rec

            rec = FinalizationReceipt(
                utterance_id=utt_id,
                stream_ref=self._stream_ref,
                status=FinalizationStatus.ADMITTED,
                turn_ref=turn_ref,
                utterance=utterance,
                start_sample=decision.start_sample,
                end_sample_exclusive=decision.end_sample_exclusive,
            )
            self._finalized_receipts[interval_key] = rec
            self._seen_utterance_ids[utt_id] = rec
            return rec
