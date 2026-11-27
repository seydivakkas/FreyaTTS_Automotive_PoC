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

from backend.audio_rendering.control_adapter import ControlOwnershipResolver
from backend.audio_rendering.dsp_adapter import StatefulLegacyDSPAdapter, build_telephony_coefficients
from backend.audio_rendering.framer import FrameSynchronizer
from backend.audio_rendering.profile_adapter import RenderProfile, StreamProfileBinding
from backend.audio_rendering.resampler import StreamingOutputResampler
from backend.audio_rendering.sample_accounting import SampleAccounting
from backend.core.contracts.common import GenerationRef, StreamDirection, StreamRef


@dataclass(frozen=True, slots=True)
class DiscontinuityRecord:
    """Explicitly records generation aborts or stream epoch discontinuities."""

    stream_ref: StreamRef
    prior_generation_ref: GenerationRef | None
    sequence_at_boundary: int
    sample_offset_at_boundary: int
    reason: str
    discarded_48k_samples: int
    discarded_output_samples: int


class RenderStreamState:
    """
    Single-writer per-output-stream/epoch/generation mutable state container.

    Owns independent DSP filter history, streaming resampler, frame synchronizer,
    sample accounting, control ownership resolver, and monotonic stream sequence/offset cursors.
    Never shared across sessions, directions (F0 vs F6), or generations.
    """

    def __init__(
        self,
        *,
        binding: StreamProfileBinding,
        initial_generation_ref: GenerationRef,
        writer_id: str = "f6.pipeline",
    ) -> None:
        if binding.stream_ref.direction != StreamDirection.OUTPUT:
            raise ValueError("RenderStreamState requires OUTPUT stream_ref")
        if initial_generation_ref.session_id != binding.stream_ref.session_id:
            raise ValueError("generation_ref.session_id must match stream_ref.session_id")
        self.binding = binding
        self.writer_id = writer_id
        self.active_generation_ref = initial_generation_ref
        self.closed = False

        prof = binding.profile
        coeffs = build_telephony_coefficients(
            sample_rate_hz=prof.input_format.sample_rate_hz,
            hp_cutoff_hz=prof.hp_cutoff_hz,
            presence_freq_hz=prof.presence_freq_hz,
            presence_q=prof.presence_q,
            presence_gain=prof.presence_gain,
            limiter_drive=prof.limiter_drive,
        )
        self.dsp = StatefulLegacyDSPAdapter(enabled=prof.dsp_enabled, coeffs=coeffs)
        self.resampler = StreamingOutputResampler(
            input_rate_hz=prof.input_format.sample_rate_hz,
            output_rate_hz=prof.output_format.sample_rate_hz,
        )
        self.accounting = SampleAccounting(
            input_rate_hz=prof.input_format.sample_rate_hz,
            output_rate_hz=prof.output_format.sample_rate_hz,
        )
        self.controls = ControlOwnershipResolver()
        self.framer = FrameSynchronizer(
            generation_ref=initial_generation_ref,
            stream_ref=binding.stream_ref,
            profile=prof,
            accounting=self.accounting,
            initial_sequence=0,
            initial_sample_offset=0,
        )
        self.seen_chunks: dict[int, str] = {}
        self.expected_chunk_index = 0
        self.eos_completed = False
        self.aborted = False
        self.discontinuities: list[DiscontinuityRecord] = []

    @property
    def stream_ref(self) -> StreamRef:
        return self.binding.stream_ref

    @property
    def profile(self) -> RenderProfile:
        return self.binding.profile

    def assert_writer(self, writer_id: str) -> None:
        if writer_id != self.writer_id:
            raise RuntimeError(
                f"Single-writer violation on {self.stream_ref.stream_id}: "
                f"owner={self.writer_id!r}, caller={writer_id!r}"
            )

    def switch_generation(
        self,
        new_generation_ref: GenerationRef,
        *,
        reason: str = "generation_switch",
        writer_id: str | None = None,
    ) -> DiscontinuityRecord | None:
        """
        Transition stream to a new generation while preserving monotonic stream sequence/offset
        and discarding any unflushed filter/resampler/frame residue from the prior generation.
        """
        if writer_id is not None:
            self.assert_writer(writer_id)
        if self.closed:
            raise RuntimeError("Cannot switch generation on closed RenderStreamState")
        if new_generation_ref.session_id != self.stream_ref.session_id:
            raise ValueError("Cross-session generation switch forbidden")

        next_seq = self.framer.next_sequence
        next_offset = self.framer.next_sample_offset
        discontinuity: DiscontinuityRecord | None = None

        discarded_48k = 0
        discarded_out = 0
        if not self.eos_completed and not self.aborted:
            discarded_48k = self.resampler.abort_discard()
            discarded_out = self.framer.abort_discard()
            self.accounting.record_resampler_discarded(discarded_48k)
            discontinuity = DiscontinuityRecord(
                stream_ref=self.stream_ref,
                prior_generation_ref=self.active_generation_ref,
                sequence_at_boundary=next_seq,
                sample_offset_at_boundary=next_offset,
                reason=reason,
                discarded_48k_samples=discarded_48k,
                discarded_output_samples=discarded_out,
            )
            self.discontinuities.append(discontinuity)

        self.active_generation_ref = new_generation_ref
        self.dsp.reset()
        self.resampler.reset()
        self.controls.reset()
        self.seen_chunks.clear()
        self.expected_chunk_index = 0
        self.eos_completed = False
        self.aborted = False
        self.framer = FrameSynchronizer(
            generation_ref=new_generation_ref,
            stream_ref=self.stream_ref,
            profile=self.profile,
            accounting=self.accounting,
            initial_sequence=next_seq,
            initial_sample_offset=next_offset,
        )
        return discontinuity

    def abort_generation(self, reason: str = "generation_aborted") -> DiscontinuityRecord:
        """Abort current generation without flushing tail into output."""
        if self.aborted:
            return self.discontinuities[-1]
        discarded_48k = self.resampler.abort_discard()
        discarded_out = self.framer.abort_discard()
        self.accounting.record_resampler_discarded(discarded_48k)
        self.aborted = True
        rec = DiscontinuityRecord(
            stream_ref=self.stream_ref,
            prior_generation_ref=self.active_generation_ref,
            sequence_at_boundary=self.framer.next_sequence,
            sample_offset_at_boundary=self.framer.next_sample_offset,
            reason=reason,
            discarded_48k_samples=discarded_48k,
            discarded_output_samples=discarded_out,
        )
        self.discontinuities.append(rec)
        return rec

    def close(self) -> None:
        if not self.closed:
            if not self.eos_completed and not self.aborted:
                self.abort_generation(reason="stream_closed")
            self.closed = True


class StreamStateRegistry:
    """Isolated per-(session_id, stream_id, direction, format_epoch) state registry."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str, StreamDirection, int], RenderStreamState] = {}

    @staticmethod
    def _key(ref: StreamRef) -> tuple[str, str, StreamDirection, int]:
        return (ref.session_id, ref.stream_id, ref.direction, ref.format_epoch)

    def create(
        self,
        *,
        binding: StreamProfileBinding,
        generation_ref: GenerationRef,
        writer_id: str = "f6.pipeline",
    ) -> RenderStreamState:
        key = self._key(binding.stream_ref)
        if key in self._states and not self._states[key].closed:
            raise ValueError(f"Active RenderStreamState already exists for {key}")
        state = RenderStreamState(
            binding=binding,
            initial_generation_ref=generation_ref,
            writer_id=writer_id,
        )
        self._states[key] = state
        return state

    def get(self, stream_ref: StreamRef) -> RenderStreamState | None:
        return self._states.get(self._key(stream_ref))

    def close_session(self, session_id: str) -> int:
        closed_count = 0
        for key, state in list(self._states.items()):
            if key[0] == session_id:
                state.close()
                closed_count += 1
        return closed_count
