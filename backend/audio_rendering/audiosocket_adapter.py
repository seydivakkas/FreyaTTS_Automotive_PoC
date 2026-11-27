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
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Protocol

from backend.core.contracts.playback import PlaybackProfile, RenderedFrame

AUDIOSOCKET_HANGUP = 0x00
AUDIOSOCKET_UUID = 0x01
AUDIOSOCKET_DTMF = 0x03
AUDIOSOCKET_AUDIO = 0x10
AUDIOSOCKET_ERROR = 0xFF

VALID_AUDIOSOCKET_KINDS = frozenset({
    AUDIOSOCKET_HANGUP,
    AUDIOSOCKET_UUID,
    AUDIOSOCKET_DTMF,
    AUDIOSOCKET_AUDIO,
    AUDIOSOCKET_ERROR,
})
MAX_AUDIOSOCKET_PAYLOAD_BYTES = 64000
EXPECTED_PHONE_PCM_BYTES = 320


class WireWriteOutcome(StrEnum):
    SUBMITTED = "SUBMITTED"
    PARTIAL_WRITE_UNCERTAIN = "PARTIAL_WRITE_UNCERTAIN"
    BACKPRESSURE = "BACKPRESSURE"
    DISCONNECTED_IN_FLIGHT_UNKNOWN = "DISCONNECTED_IN_FLIGHT_UNKNOWN"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class WireWriteResult:
    outcome: WireWriteOutcome
    bytes_written: int
    total_packet_bytes: int
    detail: str
    closed_safely: bool = False


class AudioSocketSink(Protocol):
    def write_frame(self, payload: bytes, *, partial_write_cap: int | None = None) -> tuple[bool, int, str]: ...


def encode_audiosocket_packet(kind: int, payload: bytes) -> bytes:
    """
    Encode an Asterisk app_audiosocket 3-byte header (`!BH`: uint8 kind + uint16_be len)
    followed by immutable payload bytes.
    """
    if type(kind) is not int or kind not in VALID_AUDIOSOCKET_KINDS:
        raise ValueError(f"Unsupported AudioSocket message kind: {kind!r}")
    if not isinstance(payload, bytes):
        raise TypeError("AudioSocket payload must be immutable bytes")
    if len(payload) > MAX_AUDIOSOCKET_PAYLOAD_BYTES:
        raise ValueError(f"AudioSocket payload {len(payload)} exceeds {MAX_AUDIOSOCKET_PAYLOAD_BYTES} byte limit")
    if kind == AUDIOSOCKET_UUID and len(payload) != 16:
        raise ValueError("AudioSocket UUID packet must be exactly 16 bytes")
    return struct.pack("!BH", kind, len(payload)) + payload


def encode_audiosocket_audio_frame(frame: RenderedFrame, *, allow_short: bool = False) -> bytes:
    """Serialize an AUDIOSOCKET_8K_PCM16 RenderedFrame to `10 01 40` + 320B PCM_S16LE."""
    if frame.profile != PlaybackProfile.AUDIOSOCKET_8K_PCM16:
        raise ValueError(f"AudioSocket adapter requires AUDIOSOCKET_8K_PCM16, got {frame.profile.value}")
    if not allow_short and len(frame.payload) != EXPECTED_PHONE_PCM_BYTES:
        raise ValueError(f"Expected {EXPECTED_PHONE_PCM_BYTES} byte phone frame, got {len(frame.payload)}")
    return encode_audiosocket_packet(AUDIOSOCKET_AUDIO, frame.payload)


def encode_audiosocket_control(kind: int, payload: bytes = b"") -> bytes:
    """Encode non-audio AudioSocket control frames (HANGUP/UUID/DTMF/ERROR); never paced as audio."""
    if kind == AUDIOSOCKET_AUDIO:
        raise ValueError("Use encode_audiosocket_audio_frame for 0x10 audio payloads")
    return encode_audiosocket_packet(kind, payload)


class AudioSocketStreamParser:
    """Incremental TCP byte-stream parser handling arbitrary segmentation and coalescing."""

    def __init__(self, *, max_buffer_bytes: int = 256 * 1024) -> None:
        self._buf = bytearray()
        self._max_buffer_bytes = max_buffer_bytes

    def feed(self, chunk: bytes) -> list[tuple[int, bytes]]:
        if not isinstance(chunk, (bytes, bytearray)):
            raise TypeError("chunk must be bytes")
        if len(self._buf) + len(chunk) > self._max_buffer_bytes:
            raise MemoryError("AudioSocket parser buffer limit exceeded")
        self._buf.extend(chunk)
        packets: list[tuple[int, bytes]] = []
        while len(self._buf) >= 3:
            kind, length = struct.unpack("!BH", self._buf[:3])
            if kind not in VALID_AUDIOSOCKET_KINDS:
                raise ValueError(f"Invalid AudioSocket kind byte: {kind:#x}")
            if length > MAX_AUDIOSOCKET_PAYLOAD_BYTES:
                raise ValueError(f"AudioSocket payload length overflow: {length}")
            if len(self._buf) < 3 + length:
                break
            body = bytes(self._buf[3 : 3 + length])
            del self._buf[: 3 + length]
            packets.append((kind, body))
        return packets

    @property
    def buffered_bytes(self) -> int:
        return len(self._buf)


class AudioSocketOutboundAdapter:
    """
    AudioSocket 8 kHz outbound adapter separating media frames from control frames and
    handling short writes/disconnects without blind media retries.
    """

    def __init__(
        self,
        sink: AudioSocketSink,
        *,
        on_safe_close: Callable[[str], None] | None = None,
    ) -> None:
        self._sink = sink
        self._on_safe_close = on_safe_close
        self.audio_packets_submitted = 0
        self.control_packets_submitted = 0
        self.bytes_submitted = 0
        self.uncertain_packets = 0
        self.closed = False

    def send_audio_frame(
        self,
        frame: RenderedFrame,
        *,
        partial_write_cap: int | None = None,
    ) -> WireWriteResult:
        if self.closed:
            return WireWriteResult(
                outcome=WireWriteOutcome.REJECTED,
                bytes_written=0,
                total_packet_bytes=0,
                detail="ADAPTER_CLOSED",
            )
        packet = encode_audiosocket_audio_frame(frame)
        ok, written, status = self._sink.write_frame(packet, partial_write_cap=partial_write_cap)
        self.bytes_submitted += written
        if ok and written == len(packet):
            self.audio_packets_submitted += 1
            return WireWriteResult(
                outcome=WireWriteOutcome.SUBMITTED,
                bytes_written=written,
                total_packet_bytes=len(packet),
                detail=status,
            )
        if status == "BACKPRESSURE" and written == 0:
            return WireWriteResult(
                outcome=WireWriteOutcome.BACKPRESSURE,
                bytes_written=0,
                total_packet_bytes=len(packet),
                detail=status,
            )
        # Partial write or disconnect leaves byte stream out of framing sync -> record uncertainty & close safely, no blind retry.
        self.uncertain_packets += 1
        self._close_safely(status)
        outcome = (
            WireWriteOutcome.DISCONNECTED_IN_FLIGHT_UNKNOWN
            if "DISCONNECTED" in status
            else WireWriteOutcome.PARTIAL_WRITE_UNCERTAIN
        )
        return WireWriteResult(
            outcome=outcome,
            bytes_written=written,
            total_packet_bytes=len(packet),
            detail=status,
            closed_safely=True,
        )

    def send_control(self, kind: int, payload: bytes = b"") -> WireWriteResult:
        """Send control packet immediately on non-paced control boundary."""
        packet = encode_audiosocket_control(kind, payload)
        ok, written, status = self._sink.write_frame(packet)
        self.bytes_submitted += written
        if ok and written == len(packet):
            self.control_packets_submitted += 1
            return WireWriteResult(
                outcome=WireWriteOutcome.SUBMITTED,
                bytes_written=written,
                total_packet_bytes=len(packet),
                detail=status,
            )
        return WireWriteResult(
            outcome=WireWriteOutcome.DISCONNECTED_IN_FLIGHT_UNKNOWN,
            bytes_written=written,
            total_packet_bytes=len(packet),
            detail=status,
        )

    def _close_safely(self, reason: str) -> None:
        self.closed = True
        if self._on_safe_close is not None:
            self._on_safe_close(reason)
