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
from enum import StrEnum
from typing import Any, Mapping

from backend.core.configuration.contracts import ConfigSnapshot
from backend.core.configuration.feature_flags import FeatureFlagRegistry
from backend.core.configuration.legacy_adapter import snapshot_from_legacy_settings
from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import StreamDirection, StreamRef
from backend.core.contracts.playback import PlaybackProfile
from backend.core.contracts.validation import require_finite, require_strict_int


class UnknownRenderProfileError(ValueError):
    """Raised when channel or profile metadata is unknown, untrusted, or spoofed."""


class PaceOwner(StrEnum):
    SERVER = "SERVER"
    CLIENT = "CLIENT"


class TerminalPolicy(StrEnum):
    PAD_ONCE_WITH_ZERO = "PAD_ONCE_WITH_ZERO"
    SHORT_ALLOWED = "SHORT_ALLOWED"


class QuantizationPolicy(StrEnum):
    SATURATING_32768 = "SATURATING_32768"
    SYMMETRIC_32767 = "SYMMETRIC_32767"


@dataclass(frozen=True, slots=True)
class RenderProfile:
    """Immutable pinned profile for a single output stream epoch."""

    profile: PlaybackProfile
    channel_name: str
    input_format: AudioFormat
    output_format: AudioFormat
    frame_duration_ms: float
    frame_period_ns: int
    samples_per_frame: int
    bytes_per_frame: int
    dsp_enabled: bool
    hp_cutoff_hz: float
    presence_freq_hz: float
    presence_q: float
    presence_gain: float
    limiter_drive: float
    quantization_policy: QuantizationPolicy
    terminal_policy: TerminalPolicy
    pace_owner: PaceOwner
    resampler_backend: str
    config_revision: str
    config_seq: int
    max_chunk_samples: int
    max_queue_items: int
    max_queue_bytes: int
    media_write_timeout_sec: float

    def __post_init__(self) -> None:
        if not isinstance(self.profile, PlaybackProfile):
            raise UnknownRenderProfileError("profile must be PlaybackProfile")
        if self.input_format != AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE):
            raise ValueError("input_format must be 48000 Hz mono FLOAT32_LE")
        require_finite(self.frame_duration_ms, "frame_duration_ms", minimum=1.0, maximum=100.0)
        require_strict_int(self.frame_period_ns, "frame_period_ns", minimum=1_000_000)
        require_strict_int(self.samples_per_frame, "samples_per_frame", minimum=1)
        require_strict_int(self.bytes_per_frame, "bytes_per_frame", minimum=2)
        require_strict_int(self.max_chunk_samples, "max_chunk_samples", minimum=1, maximum=48000 * 60)
        require_strict_int(self.max_queue_items, "max_queue_items", minimum=1, maximum=4096)
        require_strict_int(self.max_queue_bytes, "max_queue_bytes", minimum=320, maximum=32 * 1024 * 1024)
        require_finite(self.media_write_timeout_sec, "media_write_timeout_sec", minimum=0.05, maximum=60.0)


_TRUSTED_CHANNEL_MAP: dict[object, tuple[PlaybackProfile, str]] = {
    PlaybackProfile.WEB_16K_PCM16: (PlaybackProfile.WEB_16K_PCM16, "web"),
    "web": (PlaybackProfile.WEB_16K_PCM16, "web"),
    "WEB": (PlaybackProfile.WEB_16K_PCM16, "web"),
    "WEB_16K_PCM16": (PlaybackProfile.WEB_16K_PCM16, "web"),
    PlaybackProfile.AUDIOSOCKET_8K_PCM16: (PlaybackProfile.AUDIOSOCKET_8K_PCM16, "asterisk"),
    "asterisk": (PlaybackProfile.AUDIOSOCKET_8K_PCM16, "asterisk"),
    "audiosocket": (PlaybackProfile.AUDIOSOCKET_8K_PCM16, "asterisk"),
    "AUDIOSOCKET": (PlaybackProfile.AUDIOSOCKET_8K_PCM16, "asterisk"),
    "AUDIOSOCKET_8K_PCM16": (PlaybackProfile.AUDIOSOCKET_8K_PCM16, "asterisk"),
}


def resolve_render_profile(
    trusted_channel: str | PlaybackProfile,
    *,
    snapshot: ConfigSnapshot | None = None,
    flag_registry: FeatureFlagRegistry | None = None,
    dsp_enabled: bool | None = None,
    quantization_policy: QuantizationPolicy = QuantizationPolicy.SATURATING_32768,
    terminal_policy: TerminalPolicy = TerminalPolicy.PAD_ONCE_WITH_ZERO,
    pace_owner: PaceOwner = PaceOwner.SERVER,
    resampler_backend: str = "soxr",
    max_queue_items: int = 64,
    max_queue_bytes: int = 256 * 1024,
) -> RenderProfile:
    """Resolve and pin an immutable RenderProfile from trusted channel context and M03 snapshot."""
    if not isinstance(trusted_channel, (str, PlaybackProfile)):
        raise UnknownRenderProfileError(f"Unsupported trusted_channel type: {type(trusted_channel).__name__}")
    key = trusted_channel if isinstance(trusted_channel, PlaybackProfile) else trusted_channel.strip()
    mapped = _TRUSTED_CHANNEL_MAP.get(key)
    if mapped is None:
        raise UnknownRenderProfileError(f"Unknown or untrusted render channel/profile: {trusted_channel!r}")
    profile, canonical_channel = mapped

    if resampler_backend not in {"soxr"}:
        raise UnknownRenderProfileError(f"Unsupported resampler_backend: {resampler_backend!r}")

    if snapshot is None:
        conv = snapshot_from_legacy_settings()
        if not conv.ok or conv.value is None:
            raise RuntimeError(f"Failed to load M03 ConfigSnapshot: {conv.error}")
        snapshot = conv.value

    if flag_registry is None:
        flag_registry = FeatureFlagRegistry.from_snapshot(snapshot)

    timeout_sec = float(snapshot.values.get("media_write_timeout_sec", 2.0))
    if profile == PlaybackProfile.WEB_16K_PCM16:
        out_fmt = AudioFormat(16000, 1, AudioEncoding.PCM_S16LE)
        samples_per_frame = 320
        bytes_per_frame = 640
        effective_dsp = False if dsp_enabled is None else bool(dsp_enabled)
    else:
        out_fmt = AudioFormat(8000, 1, AudioEncoding.PCM_S16LE)
        samples_per_frame = 160
        bytes_per_frame = 320
        effective_dsp = True if dsp_enabled is None else bool(dsp_enabled)
        if pace_owner != PaceOwner.SERVER:
            raise UnknownRenderProfileError("AUDIOSOCKET profile requires SERVER pace_owner")

    _ = flag_registry  # Retained for explicit M03 flag validation & future epoch checks.
    return RenderProfile(
        profile=profile,
        channel_name=canonical_channel,
        input_format=AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE),
        output_format=out_fmt,
        frame_duration_ms=20.0,
        frame_period_ns=20_000_000,
        samples_per_frame=samples_per_frame,
        bytes_per_frame=bytes_per_frame,
        dsp_enabled=effective_dsp,
        hp_cutoff_hz=120.0,
        presence_freq_hz=3200.0,
        presence_q=1.5,
        presence_gain=0.35,
        limiter_drive=1.15,
        quantization_policy=quantization_policy,
        terminal_policy=terminal_policy,
        pace_owner=pace_owner,
        resampler_backend=resampler_backend,
        config_revision=snapshot.config_revision,
        config_seq=snapshot.snapshot_seq,
        max_chunk_samples=48000 * 60,
        max_queue_items=max_queue_items,
        max_queue_bytes=max_queue_bytes,
        media_write_timeout_sec=timeout_sec,
    )


def validate_web_client_capabilities(
    client_hello: Mapping[str, Any],
    profile: RenderProfile,
) -> tuple[bool, str | None]:
    """
    Validate web client negotiated audio format against pinned RenderProfile.
    Never silently swaps sample rate or encoding on mismatch.
    """
    if profile.profile != PlaybackProfile.WEB_16K_PCM16:
        return False, "NON_WEB_PROFILE"
    rate = client_hello.get("sample_rate")
    encoding = str(client_hello.get("encoding", "")).strip().lower()
    channels = client_hello.get("channels")
    if type(rate) is not int or rate != profile.output_format.sample_rate_hz:
        return False, f"CLIENT_RATE_MISMATCH:{rate!r}!={profile.output_format.sample_rate_hz}"
    if encoding != "pcm_s16le":
        return False, f"CLIENT_ENCODING_MISMATCH:{encoding!r}"
    if type(channels) is not int or channels != 1:
        return False, f"CLIENT_CHANNELS_MISMATCH:{channels!r}"
    return True, None


class StreamProfileBinding:
    """Pins a RenderProfile to a stream epoch; config updates require a new epoch."""

    def __init__(self, stream_ref: StreamRef, profile: RenderProfile) -> None:
        if stream_ref.direction != StreamDirection.OUTPUT:
            raise ValueError("Render stream_ref must have direction=OUTPUT")
        self._stream_ref = stream_ref
        self._profile = profile

    @property
    def stream_ref(self) -> StreamRef:
        return self._stream_ref

    @property
    def profile(self) -> RenderProfile:
        return self._profile

    def advance_epoch(self, next_profile: RenderProfile) -> "StreamProfileBinding":
        """Explicitly open a new format_epoch for a new config revision without mutating active epoch."""
        new_ref = StreamRef(
            session_id=self._stream_ref.session_id,
            stream_id=self._stream_ref.stream_id,
            direction=StreamDirection.OUTPUT,
            format_epoch=self._stream_ref.format_epoch + 1,
        )
        return StreamProfileBinding(new_ref, next_profile)
