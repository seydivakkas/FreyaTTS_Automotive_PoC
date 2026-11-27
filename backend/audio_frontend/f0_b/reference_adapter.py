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
from typing import Protocol

import numpy as np

from backend.audio_frontend.resampler import StatefulResampler
from backend.core.contracts.common import StreamDirection, StreamRef
from backend.core.contracts.playback import ObservationScope


class DeliveryStatus(StrEnum):
    """Truthful provenance of playback reference delivery."""

    CLAIMED = "CLAIMED"
    IN_FLIGHT_POSSIBLE = "IN_FLIGHT_POSSIBLE"
    COMPLETED_LOCAL = "COMPLETED_LOCAL"
    VERIFIED_ENDPOINT = "VERIFIED_ENDPOINT"
    UNKNOWN_DELIVERY = "UNKNOWN_DELIVERY"
    UNAVAILABLE = "UNAVAILABLE"


class ClockMappingStatus(StrEnum):
    """Status of clock-domain mapping between capture and playback reference."""

    SAME_MONOTONIC = "SAME_MONOTONIC"
    VERIFIED_AFFINE = "VERIFIED_AFFINE"
    RELATIVE_CORRELATION_ONLY = "RELATIVE_CORRELATION_ONLY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ClockMapping:
    """Explicit clock-domain mapping; never subtracts unmapped cross-domain clocks."""

    source_domain: str
    target_domain: str
    status: ClockMappingStatus
    mapping_revision: str = "unmapped"
    slope: float = 1.0
    offset_ns: int = 0
    uncertainty_ns: int | None = None

    def map_ns(self, source_monotonic_ns: int) -> int | None:
        if self.status == ClockMappingStatus.SAME_MONOTONIC:
            return int(source_monotonic_ns)
        if self.status == ClockMappingStatus.VERIFIED_AFFINE:
            return int(round(self.slope * source_monotonic_ns + self.offset_ns))
        return None


def resolve_clock_mapping(
    capture_domain: str | None,
    reference_domain: str | None,
    *,
    verified_affine: ClockMapping | None = None,
) -> ClockMapping:
    """Resolve clock mapping truthfully; differing domains without verified affine => UNKNOWN."""
    if not capture_domain or not reference_domain:
        return ClockMapping(
            source_domain=reference_domain or "UNKNOWN",
            target_domain=capture_domain or "UNKNOWN",
            status=ClockMappingStatus.UNKNOWN,
        )
    if capture_domain == reference_domain:
        return ClockMapping(
            source_domain=reference_domain,
            target_domain=capture_domain,
            status=ClockMappingStatus.SAME_MONOTONIC,
            mapping_revision="same_domain_v1",
            uncertainty_ns=0,
        )
    if (
        verified_affine is not None
        and verified_affine.status == ClockMappingStatus.VERIFIED_AFFINE
        and verified_affine.source_domain == reference_domain
        and verified_affine.target_domain == capture_domain
    ):
        return verified_affine
    return ClockMapping(
        source_domain=reference_domain,
        target_domain=capture_domain,
        status=ClockMappingStatus.UNKNOWN,
    )


@dataclass(frozen=True, slots=True)
class ReferenceAssociation:
    """Authorized pairing between an input stream epoch and an output stream epoch."""

    session_id: str
    input_stream_id: str
    input_format_epoch: int
    output_stream_ref: StreamRef
    reference_revision: str = "f6b-ref-v1"

    def __post_init__(self) -> None:
        if self.output_stream_ref.session_id != self.session_id:
            raise ValueError("Cross-session reference association is forbidden")
        if self.output_stream_ref.direction != StreamDirection.OUTPUT:
            raise ValueError("Reference output_stream_ref must have direction OUTPUT")


@dataclass(frozen=True, slots=True)
class ReferenceChunk:
    """One claimed post-render playback reference chunk from F6-B (or test fixture)."""

    stream_ref: StreamRef
    generation_id: int
    sequence: int
    sample_offset: int
    sample_rate_hz: int
    samples: np.ndarray
    valid_sample_count: int
    claimed_monotonic_ns: int | None = None
    clock_domain: str | None = None
    observation_scope: ObservationScope = ObservationScope.SERVER
    delivery_status: DeliveryStatus = DeliveryStatus.CLAIMED
    is_known_silence: bool = False


@dataclass(frozen=True, slots=True)
class ReferenceReadResult:
    """Bounded immutable result of reading aligned-rate reference history."""

    ok: bool
    samples: np.ndarray
    sample_rate_hz: int
    valid_sample_count: int
    physical_sample_count: int
    delivery_status: DeliveryStatus
    observation_scope: ObservationScope
    clock_domain: str | None
    latest_claimed_monotonic_ns: int | None
    latest_generation_id: int | None
    has_gap: bool
    evicted_samples: int
    reason: str


class PlaybackReferenceSource(Protocol):
    """Protocol for F6-B reference providers (non-blocking, bounded)."""

    def read_recent(self, *, max_samples: int) -> ReferenceReadResult: ...


class PlaybackReferenceReader:
    """
    Bounded per-stream F6-B playback reference consumer.

    - Matches session_id and output StreamRef (no cross-session fallback).
    - Converts reference to target AEC processing rate via an independent StatefulResampler.
    - Enforces finite ring-buffer capacity; slow reader loses oldest history explicitly.
    - Never blocks output writer and never fabricates zero reference when data is missing.
    """

    def __init__(
        self,
        association: ReferenceAssociation,
        *,
        target_rate_hz: int,
        max_history_samples: int = 16000,
    ) -> None:
        if max_history_samples < 1:
            raise ValueError("max_history_samples must be positive")
        self.association = association
        self.target_rate_hz = int(target_rate_hz)
        self.max_history_samples = int(max_history_samples)

        self._resampler: StatefulResampler | None = None
        self._source_rate_hz: int | None = None
        self._buffer: deque[float] = deque(maxlen=self.max_history_samples)
        self._last_seq: int | None = None
        self._last_end_offset: int | None = None
        self._evicted_samples: int = 0
        self._has_gap: bool = False
        self._latest_ns: int | None = None
        self._latest_clock_domain: str | None = None
        self._latest_gen_id: int | None = None
        self._latest_scope: ObservationScope = ObservationScope.UNKNOWN
        self._latest_delivery: DeliveryStatus = DeliveryStatus.UNAVAILABLE
        self._total_valid_samples: int = 0
        self._total_physical_samples: int = 0
        self._closed: bool = False

    def reset(self, *, reason: str = "discontinuity") -> None:
        """Reset buffered reference and resampler state on route/epoch discontinuity."""
        self._buffer.clear()
        if self._resampler is not None:
            self._resampler.reset()
        self._last_seq = None
        self._last_end_offset = None
        self._has_gap = reason != "init"
        self._latest_delivery = DeliveryStatus.UNAVAILABLE

    def close(self) -> None:
        """Close reader; subsequent pushes/reads are rejected cleanly."""
        self._closed = True
        self._buffer.clear()
        if self._resampler is not None:
            self._resampler.close()

    def push_reference_chunk(self, chunk: ReferenceChunk) -> bool:
        """Ingest one authorized F6-B ReferenceChunk without blocking."""
        if self._closed:
            return False
        if chunk.stream_ref.session_id != self.association.session_id:
            return False
        if chunk.stream_ref != self.association.output_stream_ref:
            return False

        arr = np.asarray(chunk.samples, dtype=np.float32)
        if arr.ndim != 1 or len(arr) == 0 or not np.isfinite(arr).all():
            return False

        if self._source_rate_hz is None:
            self._source_rate_hz = int(chunk.sample_rate_hz)
            self._resampler = StatefulResampler(self._source_rate_hz, self.target_rate_hz, quality="HQ")
        elif chunk.sample_rate_hz != self._source_rate_hz:
            # Output rate epoch changed -> reset resampler & mark gap
            self._source_rate_hz = int(chunk.sample_rate_hz)
            self._resampler.close()
            self._resampler = StatefulResampler(self._source_rate_hz, self.target_rate_hz, quality="HQ")
            self._buffer.clear()
            self._has_gap = True

        if self._last_seq is not None and chunk.sequence != self._last_seq + 1:
            self._has_gap = True
        if self._last_end_offset is not None and chunk.sample_offset != self._last_end_offset:
            self._has_gap = True

        self._last_seq = chunk.sequence
        self._last_end_offset = chunk.sample_offset + len(arr)
        self._latest_ns = chunk.claimed_monotonic_ns
        self._latest_clock_domain = chunk.clock_domain
        self._latest_gen_id = chunk.generation_id
        self._latest_scope = chunk.observation_scope
        self._latest_delivery = chunk.delivery_status
        self._total_valid_samples += int(chunk.valid_sample_count)
        self._total_physical_samples += int(len(arr))

        assert self._resampler is not None
        resampled = self._resampler.process(arr)
        if len(resampled) > 0:
            prev_len = len(self._buffer)
            overflow = max(0, prev_len + len(resampled) - self.max_history_samples)
            self._evicted_samples += overflow
            self._buffer.extend(resampled.tolist())
        return True

    def read_recent(self, *, max_samples: int) -> ReferenceReadResult:
        """Return up to max_samples of most recent target-rate reference PCM."""
        if self._closed:
            return ReferenceReadResult(
                ok=False,
                samples=np.zeros(0, dtype=np.float32),
                sample_rate_hz=self.target_rate_hz,
                valid_sample_count=0,
                physical_sample_count=0,
                delivery_status=DeliveryStatus.UNAVAILABLE,
                observation_scope=ObservationScope.UNKNOWN,
                clock_domain=None,
                latest_claimed_monotonic_ns=None,
                latest_generation_id=None,
                has_gap=self._has_gap,
                evicted_samples=self._evicted_samples,
                reason="reference_reader_closed",
            )
        if len(self._buffer) == 0:
            return ReferenceReadResult(
                ok=False,
                samples=np.zeros(0, dtype=np.float32),
                sample_rate_hz=self.target_rate_hz,
                valid_sample_count=0,
                physical_sample_count=0,
                delivery_status=self._latest_delivery,
                observation_scope=self._latest_scope,
                clock_domain=self._latest_clock_domain,
                latest_claimed_monotonic_ns=self._latest_ns,
                latest_generation_id=self._latest_gen_id,
                has_gap=self._has_gap,
                evicted_samples=self._evicted_samples,
                reason="reference_unavailable",
            )

        n = min(int(max_samples), len(self._buffer))
        if n <= 0:
            data = np.zeros(0, dtype=np.float32)
        else:
            # Slice most recent n samples from deque
            buf_list = list(self._buffer)
            data = np.asarray(buf_list[-n:], dtype=np.float32)
        return ReferenceReadResult(
            ok=True,
            samples=data,
            sample_rate_hz=self.target_rate_hz,
            valid_sample_count=len(data),
            physical_sample_count=len(data),
            delivery_status=self._latest_delivery,
            observation_scope=self._latest_scope,
            clock_domain=self._latest_clock_domain,
            latest_claimed_monotonic_ns=self._latest_ns,
            latest_generation_id=self._latest_gen_id,
            has_gap=self._has_gap,
            evicted_samples=self._evicted_samples,
            reason="ok",
        )
