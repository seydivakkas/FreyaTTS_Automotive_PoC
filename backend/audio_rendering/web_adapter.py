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

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from backend.audio_rendering.profile_adapter import (
    PaceOwner,
    RenderProfile,
    validate_web_client_capabilities,
)
from backend.core.contracts.playback import PlaybackProfile, RenderedFrame

EXPECTED_WEB_PCM_BYTES = 640


@dataclass(frozen=True, slots=True)
class WebTransportResult:
    accepted: bool
    bytes_written: int
    pace_owner: PaceOwner
    detail: str


def encode_web_audio_frame(frame: RenderedFrame) -> bytes:
    """
    Encode a WEB_16K_PCM16 RenderedFrame to raw 640-byte PCM_S16LE binary WebSocket payload.
    Never prepends an AudioSocket 3-byte header.
    """
    if frame.profile != PlaybackProfile.WEB_16K_PCM16:
        raise ValueError(f"Web adapter requires WEB_16K_PCM16, got {frame.profile.value}")
    if len(frame.payload) != EXPECTED_WEB_PCM_BYTES:
        raise ValueError(f"Web audio frame must be {EXPECTED_WEB_PCM_BYTES} bytes, got {len(frame.payload)}")
    return frame.payload


def build_web_control_envelope(event_type: str, **fields: Any) -> dict[str, Any]:
    """Preserve existing `/ws/voice` JSON control envelope schema."""
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("event_type must be non-empty string")
    envelope = {"type": event_type}
    envelope.update(fields)
    return envelope


class WebTransportAdapter:
    """
    Preserves `/ws/voice` binary PCM frame + JSON control envelope semantics
    and enforces negotiated capability + pinned pace ownership without UI changes.
    """

    def __init__(
        self,
        profile: RenderProfile,
        *,
        send_bytes_fn: Callable[[bytes], None],
        send_json_fn: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if profile.profile != PlaybackProfile.WEB_16K_PCM16:
            raise ValueError("WebTransportAdapter requires WEB_16K_PCM16 profile")
        self.profile = profile
        self._send_bytes_fn = send_bytes_fn
        self._send_json_fn = send_json_fn
        self.capability_verified = False
        self.hold_reason: str | None = None
        self.frames_sent = 0
        self.bytes_sent = 0
        self.control_messages_sent = 0

    @property
    def pace_owner(self) -> PaceOwner:
        return self.profile.pace_owner

    @property
    def server_should_pace(self) -> bool:
        """Prevent duplicate pacing sleeps when web client owns playout cadence."""
        return self.profile.pace_owner == PaceOwner.SERVER

    def negotiate_hello(self, client_hello: Mapping[str, Any]) -> tuple[bool, str | None]:
        """Validate client WebSocket hello against pinned profile without silent rate swap."""
        ok, reason = validate_web_client_capabilities(client_hello, self.profile)
        self.capability_verified = ok
        self.hold_reason = None if ok else (reason or "CAPABILITY_MISMATCH")
        return ok, reason

    def send_audio_frame(self, frame: RenderedFrame) -> WebTransportResult:
        if not self.capability_verified:
            return WebTransportResult(
                accepted=False,
                bytes_written=0,
                pace_owner=self.pace_owner,
                detail=self.hold_reason or "CAPABILITY_NOT_VERIFIED_HOLD",
            )
        payload = encode_web_audio_frame(frame)
        self._send_bytes_fn(payload)
        self.frames_sent += 1
        self.bytes_sent += len(payload)
        return WebTransportResult(
            accepted=True,
            bytes_written=len(payload),
            pace_owner=self.pace_owner,
            detail="SUBMITTED_WEB_BINARY",
        )

    def send_control_envelope(self, event_type: str, **fields: Any) -> dict[str, Any]:
        env = build_web_control_envelope(event_type, **fields)
        if self._send_json_fn is not None:
            self._send_json_fn(env)
        self.control_messages_sent += 1
        return env
