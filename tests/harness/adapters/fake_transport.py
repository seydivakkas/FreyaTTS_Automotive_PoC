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

import struct
from collections import deque
from dataclasses import dataclass

from backend.core.contracts.playback import ObservationScope
from backend.observability.evidence import EvidenceKind

AUDIOSOCKET_HANGUP = 0x00
AUDIOSOCKET_UUID = 0x01
AUDIOSOCKET_DTMF = 0x03
AUDIOSOCKET_AUDIO = 0x10
AUDIOSOCKET_ERROR = 0xFF


def pack_audiosocket_frame(kind: int, payload: bytes) -> bytes:
    return struct.pack("!BH", kind, len(payload)) + payload


class FakeAudioSocketTransport:
    """In-memory ordered TCP stream simulator supporting fragmentation, coalescing, and backpressure."""

    source_class: EvidenceKind = EvidenceKind.MOCK_RUNTIME
    transport_mode: str = "ORDERED_TCP_STREAM"

    def __init__(self, *, max_send_buffer_bytes: int = 4096) -> None:
        self.max_send_buffer_bytes = max_send_buffer_bytes
        self._rx_buffer = bytearray()
        self._tx_buffer = bytearray()
        self.connected = True
        self.backpressured = False
        self.written_bytes = 0
        self.in_flight_unknown_bytes = 0

    def push_rx_bytes(self, chunk: bytes) -> None:
        self._rx_buffer.extend(chunk)

    def try_parse_frames(self) -> list[tuple[int, bytes]]:
        frames: list[tuple[int, bytes]] = []
        while len(self._rx_buffer) >= 3:
            kind, length = struct.unpack("!BH", self._rx_buffer[:3])
            if length > 64000:
                raise ValueError(f"AudioSocket payload exceeds 64KB limit: {length}")
            if len(self._rx_buffer) < 3 + length:
                break
            payload = bytes(self._rx_buffer[3 : 3 + length])
            del self._rx_buffer[: 3 + length]
            frames.append((kind, payload))
        return frames

    def write_frame(self, payload: bytes, *, partial_write_cap: int | None = None) -> tuple[bool, int, str]:
        if not self.connected:
            self.in_flight_unknown_bytes += len(payload)
            return False, 0, "DISCONNECTED_IN_FLIGHT_UNKNOWN"
        available = self.max_send_buffer_bytes - len(self._tx_buffer)
        if available <= 0:
            self.backpressured = True
            return False, 0, "BACKPRESSURE"
        limit = min(available, partial_write_cap) if partial_write_cap is not None else available
        written = min(len(payload), limit)
        self._tx_buffer.extend(payload[:written])
        self.written_bytes += written
        if written < len(payload):
            self.backpressured = True
            return False, written, "PARTIAL_WRITE"
        return True, written, "SUBMITTED"

    def disconnect(self) -> None:
        self.connected = False


@dataclass(frozen=True, slots=True)
class RTPDatagram:
    sequence: int
    payload: bytes


class FakeRTPDatagramChannel:
    """Separate simulated UDP/RTP datagram channel (never labeled TCP packet loss)."""

    source_class: EvidenceKind = EvidenceKind.MOCK_RUNTIME
    transport_mode: str = "RTP_DATAGRAM_SIMULATION"

    def __init__(self) -> None:
        self._datagrams: list[RTPDatagram] = []

    def send(self, sequence: int, payload: bytes) -> None:
        self._datagrams.append(RTPDatagram(sequence=sequence, payload=payload))

    def deliver_with_reordering_and_loss(
        self,
        *,
        drop_sequences: frozenset[int] = frozenset(),
        reverse_order: bool = False,
    ) -> list[RTPDatagram]:
        kept = [d for d in self._datagrams if d.sequence not in drop_sequences]
        if reverse_order:
            kept = list(reversed(kept))
        self._datagrams.clear()
        return kept


class FakePlaybackEndpoint:
    """Distinguishes server queue clear, transport submission, fake endpoint ack, and audible endpoint proof."""

    def __init__(self) -> None:
        self.server_queue: deque[bytes] = deque()
        self.transport_submitted: list[bytes] = []
        self.endpoint_acks: list[int] = []
        self.audible_cut_verified: bool = False  # Fake endpoint NEVER proves real human-audible cut.
        self.observation_scope: ObservationScope = ObservationScope.SERVER

    def enqueue(self, payload: bytes) -> None:
        self.server_queue.append(payload)

    def flush_server_queue(self) -> int:
        cleared = len(self.server_queue)
        self.server_queue.clear()
        return cleared

    def submit_next(self) -> int | None:
        if not self.server_queue:
            return None
        pkt = self.server_queue.popleft()
        self.transport_submitted.append(pkt)
        return len(self.transport_submitted) - 1

    def ack_submitted(self, idx: int) -> None:
        self.endpoint_acks.append(idx)


class FakeDTMFInjector:
    """Deterministic DTMF wire event fixture with optional duplicate suppression."""

    def __init__(self, *, dedup_window_ms: int = 120) -> None:
        self.dedup_window_ms = dedup_window_ms
        self._last_digit: str | None = None
        self._last_ms: int | None = None

    def receive_digit(self, digit: str, *, at_ms: int) -> bool:
        if self._last_digit == digit and self._last_ms is not None and (at_ms - self._last_ms) < self.dedup_window_ms:
            return False
        self._last_digit = digit
        self._last_ms = at_ms
        return True
