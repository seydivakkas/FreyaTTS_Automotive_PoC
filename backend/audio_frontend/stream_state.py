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

import threading
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from backend.audio_frontend.f0_b.adaptive_chain import AdaptiveDspChain
from backend.audio_frontend.config_adapter import AudioFrontendConfig
from backend.audio_frontend.format_validator import InputProfile
from backend.audio_frontend.legacy_dsp_adapter import LegacyDspChain
from backend.audio_frontend.f0_b.profiles import resolve_enhancement_profile
from backend.audio_frontend.raw_dtmf_bridge import RawDtmfBridge, RawDtmfEvent
from backend.audio_frontend.f0_b.reference_adapter import PlaybackReferenceSource
from backend.audio_frontend.resampler import StatefulResampler
from backend.audio_frontend.f0_b.rnnoise_adapter import RnnoiseProvider
from backend.audio_frontend.sample_accounting import SampleLedger
from backend.core.contracts.common import StreamDirection, StreamRef
from backend.core.runtime.deadlines import Clock
from backend.core.runtime.session_context import SessionContext

StreamKey = tuple[str, str, str, int]
StreamLogicalKey = tuple[str, str, str]


def make_stream_key(ref: StreamRef) -> StreamKey:
    return (ref.session_id, ref.stream_id, ref.direction.value, ref.format_epoch)


def make_logical_key(ref: StreamRef) -> StreamLogicalKey:
    return (ref.session_id, ref.stream_id, ref.direction.value)


@dataclass(slots=True)
class StreamAudioState:
    """
    Isolated per-(session_id, stream_id, direction, format_epoch) F0-A DSP and accounting state.

    Never shared across sessions, directions, or format epochs.
    """

    stream_ref: StreamRef
    native_sample_rate_hz: int
    profile: InputProfile
    pinned_config: AudioFrontendConfig
    ledger: SampleLedger
    dtmf_bridge: RawDtmfBridge
    dsp_chain: LegacyDspChain
    resampler: StatefulResampler
    lease_id: str
    adaptive_chain: AdaptiveDspChain | None = None
    closed: bool = False
    eos_flushed: bool = False
    in_flight_count: int = 0
    quarantined: bool = False
    release_completed: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def stream_key(self) -> StreamKey:
        return make_stream_key(self.stream_ref)

    @property
    def logical_key(self) -> StreamLogicalKey:
        return make_logical_key(self.stream_ref)

    def output_stream_ref(self) -> StreamRef:
        return StreamRef(
            session_id=self.stream_ref.session_id,
            stream_id=self.stream_ref.stream_id,
            direction=self.stream_ref.direction,
            format_epoch=self.stream_ref.format_epoch,
        )


class StreamStateRegistry:
    """
    Authoritative per-stream/epoch state registry bound to M02 SessionContext leases.

    Enforces single active format_epoch per (session_id, stream_id, direction),
    epoch rollover cleanup, stale epoch rejection, and pinned config isolation.
    """

    def __init__(
        self,
        session_ctx: SessionContext,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.session_ctx = session_ctx
        self.clock = clock or session_ctx.clock
        self._lock = threading.RLock()
        self._states: dict[StreamKey, StreamAudioState] = {}
        self._active_epochs: dict[StreamLogicalKey, int] = {}
        self._retired_keys: set[StreamKey] = set()

    def create_or_get(
        self,
        stream_ref: StreamRef,
        *,
        native_sample_rate_hz: int,
        profile: InputProfile,
        config: AudioFrontendConfig,
        raw_tap_observer: Callable[[np.ndarray, int], None] | None = None,
        dtmf_dispatch: Callable[[RawDtmfEvent], None] | None = None,
        reference_source: PlaybackReferenceSource | None = None,
        rnnoise_provider: RnnoiseProvider | None = None,
    ) -> StreamAudioState:
        """Create or retrieve active StreamAudioState; rejects retired/stale epochs."""
        if stream_ref.session_id != self.session_ctx.identity.session_id:
            raise ValueError("StreamRef session_id mismatch with SessionContext")
        if stream_ref.direction != StreamDirection.INPUT:
            raise ValueError("F0-A StreamStateRegistry only admits StreamDirection.INPUT")

        key = make_stream_key(stream_ref)
        lkey = make_logical_key(stream_ref)

        with self._lock:
            if key in self._retired_keys:
                raise RuntimeError(f"Stale or retired format_epoch {stream_ref.format_epoch} for {lkey}")
            active_epoch = self._active_epochs.get(lkey)
            if active_epoch is not None:
                if stream_ref.format_epoch < active_epoch:
                    raise RuntimeError(
                        f"Stale format_epoch {stream_ref.format_epoch} < active {active_epoch}"
                    )
                if stream_ref.format_epoch == active_epoch and key in self._states:
                    return self._states[key]
                # New higher format_epoch: retire previous epoch state cleanly
                if stream_ref.format_epoch > active_epoch:
                    old_key = (lkey[0], lkey[1], lkey[2], active_epoch)
                    old_state = self._states.get(old_key)
                    if old_state is not None:
                        self._retire_state_locked(old_state, reason="format_epoch_rollover")

            adaptive_chain: AdaptiveDspChain | None = None
            if config.f0_b_adaptive_dsp_enabled:
                adaptive_chain = AdaptiveDspChain(
                    session_id=stream_ref.session_id,
                    input_stream_id=stream_ref.stream_id,
                    input_format_epoch=stream_ref.format_epoch,
                    sample_rate_hz=native_sample_rate_hz,
                    profile=resolve_enhancement_profile(config.environment_profile),
                    aec_enabled=config.f0_b_aec_enabled,
                    rnnoise_enabled=config.f0_b_rnnoise_enabled,
                    rnnoise_provider=rnnoise_provider,
                    reference_source=reference_source,
                    browser_native_aec_active=config.browser_native_aec_active,
                    bypass=profile.bypass or not profile.dsp_enabled or config.bypass_dsp,
                    already_processed=profile.already_processed,
                )

            lease_id = f"f0a:{stream_ref.session_id}:{stream_ref.stream_id}:{stream_ref.direction.value}:{stream_ref.format_epoch}"
            state = StreamAudioState(
                stream_ref=stream_ref,
                native_sample_rate_hz=native_sample_rate_hz,
                profile=profile,
                pinned_config=config,
                ledger=SampleLedger(
                    native_sample_rate_hz=native_sample_rate_hz,
                    output_sample_rate_hz=profile.output_sample_rate_hz,
                ),
                dtmf_bridge=RawDtmfBridge(
                    stream_ref,
                    sample_rate_hz=native_sample_rate_hz,
                    clock=self.clock,
                    raw_tap_observer=raw_tap_observer,
                    dispatch_callback=dtmf_dispatch,
                ),
                dsp_chain=LegacyDspChain(
                    sample_rate_hz=native_sample_rate_hz,
                    config=config,
                    hpf_enabled=profile.hpf_enabled,
                    spectral_enabled=profile.spectral_enabled,
                    agc_gate_enabled=profile.agc_gate_enabled,
                    bypass=profile.bypass or not profile.dsp_enabled,
                    already_processed=profile.already_processed,
                ),
                resampler=StatefulResampler(
                    native_sample_rate_hz,
                    profile.output_sample_rate_hz,
                    quality=profile.resampler_quality,
                ),
                lease_id=lease_id,
                adaptive_chain=adaptive_chain,
            )

            # Register M02 resource lease with deterministic cleanup callback
            def _release_resources() -> None:
                state.resampler.close()
                state.dsp_chain.reset()
                if state.adaptive_chain is not None:
                    state.adaptive_chain.close()
                state.dtmf_bridge.reset()
                state.release_completed = True

            self.session_ctx.ledger.acquire(
                lease_id,
                kind="audio_frontend_stream",
                borrowed=False,
                release_fn=_release_resources,
            )
            self._states[key] = state
            self._active_epochs[lkey] = stream_ref.format_epoch
            return state

    def get_active(self, stream_ref: StreamRef) -> tuple[StreamAudioState | None, str]:
        """Return (state, reason) verifying session, active epoch, and non-closed status."""
        if stream_ref.session_id != self.session_ctx.identity.session_id:
            return None, "stale_session"
        key = make_stream_key(stream_ref)
        lkey = make_logical_key(stream_ref)
        with self._lock:
            if key in self._retired_keys:
                return None, "stale_epoch"
            active_epoch = self._active_epochs.get(lkey)
            if active_epoch is None:
                return None, "unregistered_stream"
            if stream_ref.format_epoch < active_epoch:
                return None, "stale_epoch"
            if stream_ref.format_epoch > active_epoch:
                return None, "epoch_rollover"
            state = self._states.get(key)
            if state is None:
                return None, "unregistered_stream"
            if state.closed:
                return None, "stream_closed"
            return state, "ok"

    def _retire_state_locked(self, state: StreamAudioState, *, reason: str) -> None:
        key = state.stream_key
        state.closed = True
        self._retired_keys.add(key)
        pending_in = state.ledger.pending_input_samples
        pending_out = state.ledger.pending_output_samples
        if pending_in > 0 or pending_out > 0:
            state.ledger.record_explicit_discard(pending_in, pending_out)
        if state.in_flight_count > 0:
            state.quarantined = True
            self.session_ctx.ledger.quarantine(state.lease_id)
        else:
            self.session_ctx.ledger.release(state.lease_id)

    def close_stream(self, stream_ref: StreamRef, *, reason: str = "normal_close") -> bool:
        key = make_stream_key(stream_ref)
        with self._lock:
            state = self._states.get(key)
            if state is None or state.closed:
                if state is not None:
                    self._retired_keys.add(key)
                return False
            self._retire_state_locked(state, reason=reason)
            return True

    def close_all(self, *, reason: str = "session_close") -> int:
        with self._lock:
            closed_count = 0
            for state in list(self._states.values()):
                if not state.closed:
                    self._retire_state_locked(state, reason=reason)
                    closed_count += 1
            return closed_count

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._states.values() if not s.closed)
