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
from typing import Any, Callable

import numpy as np

from backend.audio_frontend.config_adapter import (
    AudioFrontendConfig,
    default_audio_frontend_config,
)
from backend.audio_frontend.format_validator import (
    LEGACY_WEB_EXTENDED_PROFILE,
    PHONE_8K_PROFILE,
    InputProfile,
)
from backend.audio_frontend.pipeline import AudioInputPipeline, PipelineResult
from backend.audio_frontend.raw_dtmf_bridge import RawDtmfEvent
from backend.core.contracts.audio import AudioEncoding
from backend.core.contracts.common import StreamDirection, StreamRef
from backend.core.runtime.deadlines import Clock


@dataclass(frozen=True, slots=True)
class LegacyBatchOutput:
    """Compatibility return object matching legacy VoiceSession.input 16 kHz float32 expectations."""

    samples_16k: np.ndarray
    dtmf_digits: tuple[str, ...]
    buffered_only: bool
    route: str


class LegacyAudioInputFacade:
    """
    Minimal compatibility seam bridging legacy web/phone callers onto AudioInputPipeline
    with preserved defaults (100 ms legacy optional buffering, car_denoiser_enabled=True,
    single active route, and no duplicate DTMF dispatch).
    """

    def __init__(
        self,
        *,
        session_id: str,
        sample_rate_hz: int = 8000,
        stream_id: str = "legacy-in",
        channel: str = "web",
        config: AudioFrontendConfig | None = None,
        clock: Clock | None = None,
        enable_100ms_coalesce: bool = False,
        dtmf_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.session_id = session_id
        self.sample_rate_hz = int(sample_rate_hz)
        self.stream_id = stream_id
        self.channel = channel
        self.config = config or default_audio_frontend_config()
        self.enable_100ms_coalesce = enable_100ms_coalesce
        self._dtmf_callback = dtmf_callback

        self._profile: InputProfile = (
            PHONE_8K_PROFILE if (channel == "asterisk" and sample_rate_hz == 8000) else LEGACY_WEB_EXTENDED_PROFILE
        )
        self._stream_ref = StreamRef(
            session_id=session_id,
            stream_id=stream_id,
            direction=StreamDirection.INPUT,
            format_epoch=0,
        )
        self._emitted_dtmf_buffer: list[str] = []

        def _on_dtmf(ev: RawDtmfEvent) -> None:
            self._emitted_dtmf_buffer.append(ev.digit)
            if self._dtmf_callback is not None:
                self._dtmf_callback(ev.digit)

        self.pipeline = AudioInputPipeline(
            session_id=session_id,
            config=self.config,
            default_profile=self._profile,
            clock=clock,
            dtmf_consumer=_on_dtmf,
        )
        self.pipeline.open_stream(
            self._stream_ref,
            sample_rate_hz=self.sample_rate_hz,
            profile=self._profile,
            config=self.config,
        )
        self._sequence = 0
        self._sample_offset = 0
        self._pending_bytes = bytearray()
        self._coalesce_bytes = (self.sample_rate_hz // 10) * 2

    def process_pcm16_chunk(self, data: bytes | bytearray) -> LegacyBatchOutput:
        """Process legacy PCM16 LE mono bytes through the single F0-A route."""
        if len(data) % 2 != 0:
            raise ValueError("Eksik PCM örneği")

        if self.enable_100ms_coalesce:
            self._pending_bytes.extend(data)
            if len(self._pending_bytes) < self._coalesce_bytes:
                return LegacyBatchOutput(
                    samples_16k=np.zeros(0, dtype=np.float32),
                    dtmf_digits=(),
                    buffered_only=True,
                    route="legacy_coalesce_buffering",
                )
            usable = (len(self._pending_bytes) // self._coalesce_bytes) * self._coalesce_bytes
            chunk = bytes(self._pending_bytes[:usable])
            del self._pending_bytes[:usable]
        else:
            chunk = bytes(data)

        if not chunk:
            return LegacyBatchOutput(
                samples_16k=np.zeros(0, dtype=np.float32),
                dtmf_digits=(),
                buffered_only=True,
                route="empty",
            )

        sample_count = len(chunk) // 2
        self._emitted_dtmf_buffer.clear()
        res: PipelineResult = self.pipeline.ingest_raw(
            stream_ref=self._stream_ref,
            payload=chunk,
            sample_rate_hz=self.sample_rate_hz,
            channels=1,
            encoding=AudioEncoding.PCM_S16LE,
            sample_count=sample_count,
            sequence=self._sequence,
            sample_offset=self._sample_offset,
            profile=self._profile,
        )
        if not res.ok:
            raise ValueError(res.reason)

        self._sequence += 1
        self._sample_offset += sample_count

        frames = self.pipeline.dispatcher.drain_output_frames()
        if not frames:
            return LegacyBatchOutput(
                samples_16k=np.zeros(0, dtype=np.float32),
                dtmf_digits=tuple(self._emitted_dtmf_buffer),
                buffered_only=True,
                route=res.route,
            )

        arrays = [np.frombuffer(f.payload, dtype="<f4").copy() for f in frames]
        merged = np.concatenate(arrays) if len(arrays) > 1 else arrays[0]
        return LegacyBatchOutput(
            samples_16k=merged,
            dtmf_digits=tuple(self._emitted_dtmf_buffer),
            buffered_only=False,
            route=res.route,
        )

    def submit_signaling_dtmf(self, digit: str) -> bool:
        """Admit out-of-band DTMF with cross-path dedup (no duplicate dispatch)."""
        ev = self.pipeline.submit_signaling_dtmf(self._stream_ref, digit)
        return ev is not None

    def flush_eos(self) -> np.ndarray:
        """Flush buffered resampler tail (and any pending coalesced tail) once at EOS."""
        out_parts: list[np.ndarray] = []
        if self.enable_100ms_coalesce and len(self._pending_bytes) > 0:
            tail_bytes = bytes(self._pending_bytes)
            self._pending_bytes.clear()
            sample_count = len(tail_bytes) // 2
            if sample_count > 0:
                self.pipeline.ingest_raw(
                    stream_ref=self._stream_ref,
                    payload=tail_bytes,
                    sample_rate_hz=self.sample_rate_hz,
                    channels=1,
                    encoding=AudioEncoding.PCM_S16LE,
                    sample_count=sample_count,
                    sequence=self._sequence,
                    sample_offset=self._sample_offset,
                    profile=self._profile,
                )
                self._sequence += 1
                self._sample_offset += sample_count
                for f in self.pipeline.dispatcher.drain_output_frames():
                    out_parts.append(np.frombuffer(f.payload, dtype="<f4").copy())

        eos_res = self.pipeline.flush_eos(self._stream_ref)
        for f in self.pipeline.dispatcher.drain_output_frames():
            out_parts.append(np.frombuffer(f.payload, dtype="<f4").copy())
        if not out_parts:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(out_parts) if len(out_parts) > 1 else out_parts[0]

    def close(self) -> None:
        self._pending_bytes.clear()
        self.pipeline.close(reason="legacy_facade_close")
