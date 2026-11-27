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

from backend.audio_rendering.profile_adapter import RenderProfile, TerminalPolicy
from backend.audio_rendering.sample_accounting import SampleAccounting
from backend.core.contracts.common import GenerationRef, StreamRef
from backend.core.contracts.playback import RenderedFrame


class FrameSynchronizer:
    """
    Assembles exact 20 ms output frames (`RenderedFrame`) from contiguous PCM_S16LE bytes.

    - WEB_16K_PCM16: 320 samples / 640 bytes
    - AUDIOSOCKET_8K_PCM16: 160 samples / 320 bytes
    - Retains bounded sub-frame residual across chunks within the same continuous generation.
    - Never pads intermediate chunks or emits an extra all-padding frame on exact EOS boundaries.
    - Terminal EOS flush runs at most once per generation.
    """

    def __init__(
        self,
        *,
        generation_ref: GenerationRef,
        stream_ref: StreamRef,
        profile: RenderProfile,
        accounting: SampleAccounting,
        initial_sequence: int = 0,
        initial_sample_offset: int = 0,
        max_residual_buffer_bytes: int = 256 * 1024,
    ) -> None:
        self.generation_ref = generation_ref
        self.stream_ref = stream_ref
        self.profile = profile
        self.accounting = accounting
        self._sequence = initial_sequence
        self._sample_offset = initial_sample_offset
        self._max_residual_buffer_bytes = max_residual_buffer_bytes
        self._residual = bytearray()
        self._eos_flushed = False
        self._aborted = False
        self.duplicate_eos_count = 0

    @property
    def next_sequence(self) -> int:
        return self._sequence

    @property
    def next_sample_offset(self) -> int:
        return self._sample_offset

    @property
    def residual_bytes(self) -> int:
        return len(self._residual)

    @property
    def residual_samples(self) -> int:
        return len(self._residual) // 2

    @property
    def eos_flushed(self) -> bool:
        return self._eos_flushed

    @property
    def aborted(self) -> bool:
        return self._aborted

    def push_pcm(self, pcm_bytes: bytes) -> list[RenderedFrame]:
        """Push contiguous PCM_S16LE bytes and emit all complete 20 ms RenderedFrames."""
        if self._aborted:
            raise RuntimeError("Cannot push PCM into aborted FrameSynchronizer")
        if self._eos_flushed:
            raise RuntimeError("Cannot push PCM after EOS flush")
        if not isinstance(pcm_bytes, (bytes, bytearray)):
            raise TypeError("pcm_bytes must be bytes")
        if len(pcm_bytes) % 2 != 0:
            raise ValueError("PCM_S16LE byte slice must have even length")
        if len(self._residual) + len(pcm_bytes) > self._max_residual_buffer_bytes:
            raise MemoryError("FrameSynchronizer residual buffer capacity exceeded")
        if not pcm_bytes:
            return []

        self._residual.extend(pcm_bytes)
        emitted: list[RenderedFrame] = []
        frame_bytes = self.profile.bytes_per_frame
        frame_samples = self.profile.samples_per_frame

        while len(self._residual) >= frame_bytes:
            body = bytes(self._residual[:frame_bytes])
            del self._residual[:frame_bytes]
            frame = RenderedFrame(
                generation_ref=self.generation_ref,
                stream_ref=self.stream_ref,
                sequence=self._sequence,
                sample_offset=self._sample_offset,
                profile=self.profile.profile,
                format=self.profile.output_format,
                frame_duration_ms=self.profile.frame_duration_ms,
                sample_count=frame_samples,
                valid_sample_count=frame_samples,
                payload=body,
                terminal=False,
            )
            self._sequence += 1
            self._sample_offset += frame_samples
            self.accounting.record_frame_emitted(
                valid_samples=frame_samples,
                padding_samples=0,
                is_terminal=False,
                new_residual_pending=len(self._residual) // 2,
            )
            emitted.append(frame)

        if not emitted:
            self.accounting.record_residual_updated(len(self._residual) // 2)
        return emitted

    def flush_eos(self) -> list[RenderedFrame]:
        """
        Flush sub-frame residual at authorized EOS at most once.
        On exact frame boundary (residual == 0), emits no extra all-padding frame.
        """
        if self._aborted:
            return []
        if self._eos_flushed:
            self.duplicate_eos_count += 1
            return []
        self._eos_flushed = True

        if not self._residual:
            self.accounting.record_residual_updated(0)
            return []

        valid_samples = len(self._residual) // 2
        frame_samples = self.profile.samples_per_frame
        frame_bytes = self.profile.bytes_per_frame
        if self.profile.terminal_policy not in {
            TerminalPolicy.PAD_ONCE_WITH_ZERO,
            TerminalPolicy.SHORT_ALLOWED,
        }:
            raise ValueError(f"Unsupported terminal_policy: {self.profile.terminal_policy!r}")

        # M01 RenderedFrame contract requires fixed payload length (640B web / 320B phone)
        # and sets valid_sample_count = valid_samples, terminal = True.
        padded_body = bytes(self._residual).ljust(frame_bytes, b"\x00")
        pad_samples = frame_samples - valid_samples
        self._residual.clear()

        frame = RenderedFrame(
            generation_ref=self.generation_ref,
            stream_ref=self.stream_ref,
            sequence=self._sequence,
            sample_offset=self._sample_offset,
            profile=self.profile.profile,
            format=self.profile.output_format,
            frame_duration_ms=self.profile.frame_duration_ms,
            sample_count=frame_samples,
            valid_sample_count=valid_samples,
            payload=padded_body,
            terminal=True,
        )
        self._sequence += 1
        self._sample_offset += valid_samples
        self.accounting.record_frame_emitted(
            valid_samples=valid_samples,
            padding_samples=pad_samples,
            is_terminal=True,
            new_residual_pending=0,
        )
        return [frame]

    def abort_discard(self) -> int:
        """Discard residual PCM bytes on abort without emitting into output."""
        if self._aborted:
            return 0
        discarded = len(self._residual) // 2
        self._residual.clear()
        self._aborted = True
        self._eos_flushed = True
        self.accounting.record_residual_discarded(discarded)
        return discarded
