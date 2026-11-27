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
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from backend.core.contracts.recognition import ASROutcome, ASRResult, ASRStatus
from backend.core.contracts.speech import Utterance
from backend.core.contracts.validation import require_strict_int
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.deadlines import Clock, DeadlineBudget
from backend.core.runtime.result_admission import AdmissionStatus
from backend.core.runtime.session_context import SessionContext, SessionLifecycleState
from backend.speech_recognition.errors import ASRDeliveryStatus
from backend.speech_recognition.input_manager import ValidatedUtteranceInput


class ClaimStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    STALE_SCOPE = "STALE_SCOPE"
    CAPACITY_REJECTED = "CAPACITY_REJECTED"


@dataclass(frozen=True, slots=True)
class UtteranceClaimKey:
    """Authoritative M02-scoped deduplication identity for final ASR."""

    session_id: str
    stream_id: str
    format_epoch: int
    turn_id: int
    utterance_id: str
    purpose: str = "final_asr"


@dataclass(frozen=True, slots=True)
class _ClaimFingerprint:
    payload_digest: str
    start_sample: int
    end_sample_exclusive: int


@dataclass(frozen=True, slots=True)
class ClaimDecision:
    status: ClaimStatus
    claim_key: UtteranceClaimKey
    reason: str
    turn_scope: CancellationScope | None = None


@dataclass(frozen=True, slots=True)
class ASRResultDelivery:
    """Atomic downstream admission outcome for a single final ASRResult."""

    delivery_status: ASRDeliveryStatus
    admission_status: AdmissionStatus
    reason: str
    delivered_result: ASRResult | None = None


class ASRConsumer(Protocol):
    """Downstream F3-A or legacy dialogue consumer interface."""

    async def admit_asr_result(
        self,
        result: ASRResult,
        *,
        session_ctx: SessionContext,
        stream_epoch: int,
        turn_scope: CancellationScope | None = None,
        deadline: DeadlineBudget | None = None,
    ) -> ASRResultDelivery: ...


class InMemoryASRConsumer:
    """
    Bounded M02-fenced consumer queue for final ASRResult objects.

    Performs atomic compare-and-enqueue under `session_ctx.lock` (no `await`
    between fence check and queue insertion) and re-checks the turn fence on pop.
    """

    def __init__(self, *, max_items: int = 16) -> None:
        require_strict_int(max_items, "max_items", minimum=1, maximum=4096)
        self.max_items = max_items
        self._queue: deque[tuple[ASRResult, SessionContext, int, CancellationScope | None]] = deque()
        self._closed = False
        self._delivered_utterances: set[tuple[str, int, str]] = set()
        self.rejected_count = 0
        self.fenced_on_pop_count = 0

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True
        self._queue.clear()

    async def admit_asr_result(
        self,
        result: ASRResult,
        *,
        session_ctx: SessionContext,
        stream_epoch: int,
        turn_scope: CancellationScope | None = None,
        deadline: DeadlineBudget | None = None,
    ) -> ASRResultDelivery:
        if result.status != ASRStatus.FINAL:
            self.rejected_count += 1
            return ASRResultDelivery(
                delivery_status=ASRDeliveryStatus.NOT_DELIVERED,
                admission_status=AdmissionStatus.INVALID,
                reason="only_final_asr_result_admissible",
            )
        if result.outcome != ASROutcome.OK:
            self.rejected_count += 1
            return ASRResultDelivery(
                delivery_status=ASRDeliveryStatus.NOT_DELIVERED,
                admission_status=AdmissionStatus.INVALID,
                reason=f"non_ok_outcome_{result.outcome.value}",
            )

        # Atomic compare-and-enqueue under M02 session lock (zero awaits inside fence->enqueue).
        async with session_ctx.lock:
            if self._closed:
                self.rejected_count += 1
                return ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.REJECTED_CLOSED,
                    admission_status=AdmissionStatus.CLOSED,
                    reason="consumer_closed",
                )
            if session_ctx.lifecycle_state in {SessionLifecycleState.CLOSING, SessionLifecycleState.CLOSED}:
                self.rejected_count += 1
                return ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.FENCED_STALE,
                    admission_status=AdmissionStatus.CLOSED,
                    reason="session_closing_or_closed",
                )
            if session_ctx.lifecycle_state != SessionLifecycleState.ACTIVE:
                self.rejected_count += 1
                return ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.FENCED_STALE,
                    admission_status=AdmissionStatus.INVALID,
                    reason="session_not_active",
                )
            if session_ctx.root_scope.is_cancel_requested:
                self.rejected_count += 1
                return ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.FENCED_STALE,
                    admission_status=AdmissionStatus.CANCELED,
                    reason="session_root_cancelled",
                )
            if result.envelope.session_id != session_ctx.identity.session_id:
                self.rejected_count += 1
                return ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.FENCED_STALE,
                    admission_status=AdmissionStatus.STALE_SESSION,
                    reason="session_id_mismatch",
                )
            active_turn = session_ctx.tg.active_turn
            if active_turn is None or result.envelope.turn_id != active_turn.turn_id:
                self.rejected_count += 1
                return ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.FENCED_STALE,
                    admission_status=AdmissionStatus.STALE_TURN,
                    reason="stale_turn_id",
                )
            active_turn_scope = session_ctx.tg.turn_scope
            if active_turn_scope is not None and active_turn_scope.is_cancel_requested:
                self.rejected_count += 1
                return ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.FENCED_STALE,
                    admission_status=AdmissionStatus.CANCELED,
                    reason="turn_scope_cancelled",
                )
            if turn_scope is not None and turn_scope.is_cancel_requested:
                self.rejected_count += 1
                return ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.FENCED_STALE,
                    admission_status=AdmissionStatus.CANCELED,
                    reason="utterance_scope_cancelled",
                )
            if deadline is not None and deadline.is_expired(session_ctx.clock):
                self.rejected_count += 1
                return ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.FENCED_STALE,
                    admission_status=AdmissionStatus.DEADLINE_EXCEEDED,
                    reason="deadline_exceeded",
                )
            dedup_key = (result.envelope.session_id, active_turn.turn_id, result.utterance_id)
            if dedup_key in self._delivered_utterances:
                self.rejected_count += 1
                return ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.FENCED_STALE,
                    admission_status=AdmissionStatus.DUPLICATE,
                    reason="duplicate_final_delivery",
                )
            if len(self._queue) >= self.max_items:
                self.rejected_count += 1
                return ASRResultDelivery(
                    delivery_status=ASRDeliveryStatus.REJECTED_BACKPRESSURE,
                    admission_status=AdmissionStatus.BACKPRESSURE,
                    reason="consumer_queue_full",
                )
            self._delivered_utterances.add(dedup_key)
            self._queue.append((result, session_ctx, stream_epoch, turn_scope))
            return ASRResultDelivery(
                delivery_status=ASRDeliveryStatus.DELIVERED,
                admission_status=AdmissionStatus.ACCEPTED,
                reason="admitted",
                delivered_result=result,
            )

    def pop_next_valid(self) -> ASRResult | None:
        """Consume next queued result after re-checking M02 turn and session fences."""
        while self._queue:
            result, session_ctx, _epoch, turn_scope = self._queue.popleft()
            if self._closed or session_ctx.lifecycle_state != SessionLifecycleState.ACTIVE:
                self.fenced_on_pop_count += 1
                continue
            if session_ctx.root_scope.is_cancel_requested:
                self.fenced_on_pop_count += 1
                continue
            active_turn = session_ctx.tg.active_turn
            if active_turn is None or result.envelope.turn_id != active_turn.turn_id:
                self.fenced_on_pop_count += 1
                continue
            if session_ctx.tg.turn_scope is not None and session_ctx.tg.turn_scope.is_cancel_requested:
                self.fenced_on_pop_count += 1
                continue
            if turn_scope is not None and turn_scope.is_cancel_requested:
                self.fenced_on_pop_count += 1
                continue
            return result
        return None


class ASRUtteranceAdmission:
    """
    Bounded, concurrency-safe M02 utterance claim registry and turn fence validator.

    Note: Playback `generation_scope` cancellation does NOT revoke active input turn
    recognition; only session close, turn supersession, or input turn cancellation does.
    """

    def __init__(
        self,
        *,
        max_total_pending: int = 32,
        max_per_session_pending: int = 4,
        max_tombstones: int = 512,
    ) -> None:
        require_strict_int(max_total_pending, "max_total_pending", minimum=1, maximum=10_000)
        require_strict_int(max_per_session_pending, "max_per_session_pending", minimum=1, maximum=1000)
        require_strict_int(max_tombstones, "max_tombstones", minimum=1, maximum=100_000)
        self.max_total_pending = max_total_pending
        self.max_per_session_pending = max_per_session_pending
        self.max_tombstones = max_tombstones
        self._lock = asyncio.Lock()
        self._pending: dict[UtteranceClaimKey, _ClaimFingerprint] = {}
        self._session_pending_counts: dict[str, int] = {}
        self._tombstones: deque[tuple[UtteranceClaimKey, _ClaimFingerprint]] = deque()
        self._tombstone_map: dict[UtteranceClaimKey, _ClaimFingerprint] = {}

    @property
    def total_pending(self) -> int:
        return len(self._pending)

    def pending_for_session(self, session_id: str) -> int:
        return self._session_pending_counts.get(session_id, 0)

    async def claim_utterance(
        self,
        validated: ValidatedUtteranceInput,
        *,
        session_ctx: SessionContext,
        expected_stream_epoch: int | None = None,
        purpose: str = "final_asr",
    ) -> ClaimDecision:
        utt: Utterance = validated.utterance
        assert validated.turn_ref is not None
        key = UtteranceClaimKey(
            session_id=utt.stream_ref.session_id,
            stream_id=utt.stream_ref.stream_id,
            format_epoch=utt.stream_ref.format_epoch,
            turn_id=validated.turn_ref.turn_id,
            utterance_id=utt.utterance_id,
            purpose=purpose,
        )
        fp = _ClaimFingerprint(
            payload_digest=validated.payload_digest,
            start_sample=utt.start_sample,
            end_sample_exclusive=utt.end_sample_exclusive,
        )

        async with self._lock:
            # Verify M02 session, stream epoch, and active turn (independent of playback generation!)
            if session_ctx.lifecycle_state != SessionLifecycleState.ACTIVE:
                return ClaimDecision(ClaimStatus.STALE_SCOPE, key, f"session_state_{session_ctx.lifecycle_state.value}")
            if session_ctx.root_scope.is_cancel_requested:
                return ClaimDecision(ClaimStatus.STALE_SCOPE, key, "session_cancelled")
            if session_ctx.identity.session_id != utt.stream_ref.session_id:
                return ClaimDecision(ClaimStatus.STALE_SCOPE, key, "session_id_mismatch")
            if expected_stream_epoch is not None and utt.stream_ref.format_epoch != expected_stream_epoch:
                return ClaimDecision(ClaimStatus.STALE_SCOPE, key, "stream_epoch_mismatch")
            active_turn = session_ctx.tg.active_turn
            if active_turn is None or active_turn.turn_id != validated.turn_ref.turn_id:
                return ClaimDecision(ClaimStatus.STALE_SCOPE, key, "turn_mismatch_or_superseded")
            turn_scope = session_ctx.tg.turn_scope
            if turn_scope is not None and turn_scope.is_cancel_requested:
                return ClaimDecision(ClaimStatus.STALE_SCOPE, key, "turn_cancelled")

            existing_fp = self._pending.get(key) or self._tombstone_map.get(key)
            if existing_fp is not None:
                if existing_fp != fp:
                    return ClaimDecision(ClaimStatus.CONFLICT, key, "claim_identity_payload_conflict")
                return ClaimDecision(ClaimStatus.DUPLICATE, key, "duplicate_utterance_claim")

            if len(self._pending) >= self.max_total_pending:
                return ClaimDecision(ClaimStatus.CAPACITY_REJECTED, key, "global_pending_cap_reached")
            sess_count = self._session_pending_counts.get(key.session_id, 0)
            if sess_count >= self.max_per_session_pending:
                return ClaimDecision(ClaimStatus.CAPACITY_REJECTED, key, "session_pending_cap_reached")

            self._pending[key] = fp
            self._session_pending_counts[key.session_id] = sess_count + 1
            return ClaimDecision(ClaimStatus.ACCEPTED, key, "claimed", turn_scope=turn_scope)

    async def complete_claim(self, key: UtteranceClaimKey) -> None:
        async with self._lock:
            fp = self._pending.pop(key, None)
            if fp is not None:
                cur = self._session_pending_counts.get(key.session_id, 0)
                if cur <= 1:
                    self._session_pending_counts.pop(key.session_id, None)
                else:
                    self._session_pending_counts[key.session_id] = cur - 1
                self._tombstones.append((key, fp))
                self._tombstone_map[key] = fp
                while len(self._tombstones) > self.max_tombstones:
                    old_key, _ = self._tombstones.popleft()
                    self._tombstone_map.pop(old_key, None)

    async def evict_session(self, session_id: str) -> int:
        async with self._lock:
            removed = 0
            for key in [k for k in self._pending if k.session_id == session_id]:
                self._pending.pop(key, None)
                removed += 1
            self._session_pending_counts.pop(session_id, None)
            return removed
