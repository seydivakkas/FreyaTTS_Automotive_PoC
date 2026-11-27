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

from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from backend.core.contracts.audio import AudioEncoding
from backend.core.contracts.common import GenerationRef
from backend.core.contracts.playback import ObservationScope, RenderedFrame
from backend.core.contracts.validation import require_strict_int


class ReferenceDeliveryState(StrEnum):
    IN_FLIGHT_POSSIBLE = "IN_FLIGHT_POSSIBLE"
    COMPLETED_LOCAL = "COMPLETED_LOCAL"
    UNKNOWN_DELIVERY = "UNKNOWN_DELIVERY"


@dataclass(slots=True)
class PlaybackReference:
    """
    Bounded post-DSP, post-resampler, post-quantization playback reference
    recorded at submission claim boundary for F0-B echo cancellation.
    """

    reference_id: str
    claim_id: str
    session_id: str
    stream_id: str
    format_epoch: int
    generation_ref: GenerationRef
    sequence: int
    sample_offset: int
    sample_rate_hz: int
    encoding: AudioEncoding
    sample_count: int
    valid_sample_count: int
    pcm_bytes: bytes
    claim_ns: int
    clock_domain: str
    observation_scope: ObservationScope
    delivery_state: ReferenceDeliveryState

    def __repr__(self) -> str:
        return (
            f"PlaybackReference(id={self.reference_id!r}, seq={self.sequence}, "
            f"offset={self.sample_offset}, valid={self.valid_sample_count}/{self.sample_count}, "
            f"scope={self.observation_scope.value}, state={self.delivery_state.value})"
        )


@dataclass(frozen=True, slots=True)
class ReferenceGap:
    start_sample: int
    end_sample: int
    reason: str


@dataclass(frozen=True, slots=True)
class ReferenceReadResult:
    session_id: str
    stream_id: str
    format_epoch: int
    requested_start_sample: int
    requested_end_sample: int
    spans: tuple[PlaybackReference, ...]
    gaps: tuple[ReferenceGap, ...]
    evicted_frames: int
    evicted_bytes: int
    unavailable_reason: str | None = None


class PlaybackReferenceTap:
    """
    Nonblocking, privacy-safe, independently bounded playback reference tap for F0-B.

    - Only records frames at actual submission claim (never QUEUED_UNSENT or purged frames).
    - Slow or absent consumer never blocks playback or writer.
    - Enforces strict session_id / stream_id / format_epoch isolation on reads.
    - Retains bounded history across generation cancel (echo tail may persist), clears on close.
    """

    def __init__(
        self,
        *,
        session_id: str,
        stream_id: str,
        format_epoch: int = 0,
        max_frames: int = 10,
        max_bytes: int = 6400,
    ) -> None:
        require_strict_int(max_frames, "max_frames", minimum=1, maximum=4096)
        require_strict_int(max_bytes, "max_bytes", minimum=320, maximum=4 * 1024 * 1024)
        self.session_id = session_id
        self.stream_id = stream_id
        self.format_epoch = format_epoch
        self.max_frames = max_frames
        self.max_bytes = max_bytes

        self._ring: deque[PlaybackReference] = deque()
        self._by_claim: dict[str, PlaybackReference] = {}
        self._bytes_used = 0
        self.evicted_frames = 0
        self.evicted_bytes = 0
        self._closed = False

    @property
    def frame_count(self) -> int:
        return len(self._ring)

    @property
    def bytes_used(self) -> int:
        return self._bytes_used

    def record_claim(
        self,
        *,
        claim_id: str,
        frame: RenderedFrame,
        claim_ns: int,
        clock_domain: str,
        delivery_state: ReferenceDeliveryState = ReferenceDeliveryState.IN_FLIGHT_POSSIBLE,
    ) -> PlaybackReference | None:
        if self._closed:
            return None
        if frame.stream_ref.session_id != self.session_id or frame.stream_ref.format_epoch != self.format_epoch:
            return None
        payload_len = len(frame.payload)
        if payload_len > self.max_bytes:
            return None

        while len(self._ring) >= self.max_frames or (self._bytes_used + payload_len) > self.max_bytes:
            if not self._ring:
                break
            old = self._ring.popleft()
            self._by_claim.pop(old.claim_id, None)
            self._bytes_used = max(0, self._bytes_used - len(old.pcm_bytes))
            self.evicted_frames += 1
            self.evicted_bytes += len(old.pcm_bytes)

        ref = PlaybackReference(
            reference_id=f"ref-{claim_id}",
            claim_id=claim_id,
            session_id=self.session_id,
            stream_id=self.stream_id,
            format_epoch=self.format_epoch,
            generation_ref=frame.generation_ref,
            sequence=frame.sequence,
            sample_offset=frame.sample_offset,
            sample_rate_hz=frame.format.sample_rate_hz,
            encoding=frame.format.encoding,
            sample_count=frame.sample_count,
            valid_sample_count=frame.valid_sample_count,
            pcm_bytes=frame.payload,
            claim_ns=claim_ns,
            clock_domain=clock_domain,
            observation_scope=ObservationScope.SERVER,
            delivery_state=delivery_state,
        )
        self._ring.append(ref)
        self._by_claim[claim_id] = ref
        self._bytes_used += payload_len
        return ref

    def update_delivery_state(self, claim_id: str, state: ReferenceDeliveryState) -> bool:
        ref = self._by_claim.get(claim_id)
        if ref is None:
            return False
        ref.delivery_state = state
        return True

    def read_range(
        self,
        *,
        session_id: str,
        stream_id: str,
        format_epoch: int,
        start_sample: int,
        end_sample: int,
    ) -> ReferenceReadResult:
        if session_id != self.session_id or stream_id != self.stream_id or format_epoch != self.format_epoch:
            return ReferenceReadResult(
                session_id=session_id,
                stream_id=stream_id,
                format_epoch=format_epoch,
                requested_start_sample=start_sample,
                requested_end_sample=end_sample,
                spans=(),
                gaps=(ReferenceGap(start_sample, end_sample, "SESSION_OR_EPOCH_MISMATCH"),),
                evicted_frames=self.evicted_frames,
                evicted_bytes=self.evicted_bytes,
                unavailable_reason="SESSION_OR_EPOCH_MISMATCH",
            )
        if self._closed:
            return ReferenceReadResult(
                session_id=session_id,
                stream_id=stream_id,
                format_epoch=format_epoch,
                requested_start_sample=start_sample,
                requested_end_sample=end_sample,
                spans=(),
                gaps=(ReferenceGap(start_sample, end_sample, "TAP_CLOSED"),),
                evicted_frames=self.evicted_frames,
                evicted_bytes=self.evicted_bytes,
                unavailable_reason="TAP_CLOSED",
            )

        matched: list[PlaybackReference] = []
        gaps: list[ReferenceGap] = []
        cursor = start_sample
        for ref in self._ring:
            ref_start = ref.sample_offset
            ref_end = ref.sample_offset + ref.valid_sample_count
            if ref_end <= start_sample or ref_start >= end_sample:
                continue
            if ref_start > cursor:
                gaps.append(ReferenceGap(cursor, min(ref_start, end_sample), "MISSING_OR_EVICTED_SPAN"))
            matched.append(ref)
            cursor = max(cursor, min(ref_end, end_sample))

        if cursor < end_sample:
            gaps.append(ReferenceGap(cursor, end_sample, "UNAVAILABLE_TAIL"))

        return ReferenceReadResult(
            session_id=session_id,
            stream_id=stream_id,
            format_epoch=format_epoch,
            requested_start_sample=start_sample,
            requested_end_sample=end_sample,
            spans=tuple(matched),
            gaps=tuple(gaps),
            evicted_frames=self.evicted_frames,
            evicted_bytes=self.evicted_bytes,
            unavailable_reason=None if matched else "NO_MATCHING_REFERENCE",
        )

    def clear_session(self) -> None:
        self._closed = True
        self._ring.clear()
        self._by_claim.clear()
        self._bytes_used = 0
