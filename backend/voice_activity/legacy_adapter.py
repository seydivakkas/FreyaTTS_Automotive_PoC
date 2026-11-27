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

from typing import Callable

import numpy as np

from backend.core.contracts.audio import AudioEncoding, AudioFormat, AudioFrame
from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, StreamDirection, StreamRef, TurnRef
from backend.core.contracts.speech import SpeechEventKind, Utterance
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.voice_activity.config_adapter import F1ConfigAdapter, F1ProfileConfig, F1RouteMode
from backend.voice_activity.pipeline import StreamAcousticProcessor
from backend.voice_activity.utterance_manager import BoundedUtteranceQueue
from backend.voice_activity.vad_engine import VADEngineAdapter


def utterance_to_legacy_stt_ndarray(utterance: Utterance) -> np.ndarray:
    """
    Adapt a finalized M01 Utterance (16 kHz mono FLOAT32_LE) to the float32 ndarray
    expected by legacy STT consumers without double trimming, resampling, or padding.
    """
    if not utterance.finalized:
        raise ValueError("Cannot hand unfinalized Utterance to legacy STT")
    if utterance.payload is None:
        raise ValueError("Utterance missing inline FLOAT32_LE payload for legacy STT adapter")
    expected_samples = utterance.end_sample_exclusive - utterance.start_sample
    expected_bytes = expected_samples * 4
    if len(utterance.payload) != expected_bytes:
        raise ValueError(
            f"Utterance payload bytes ({len(utterance.payload)}) != expected ({expected_bytes})"
        )
    arr = np.frombuffer(utterance.payload, dtype="<f4").copy()
    if not np.all(np.isfinite(arr)):
        raise ValueError("Utterance payload contains non-finite samples")
    arr.setflags(write=False)
    return arr


class _LegacyTurnBridge:
    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._counter = 0

    def is_stream_active(self) -> bool:
        return True

    def allocate_turn(self) -> TurnRef:
        self._counter += 1
        return TurnRef(self._session_id, self._counter)


class LegacyEndpointAdapter:
    """
    Compatibility adapter matching legacy `backend.audio.Endpoint.feed(samples)`
    shape `(started: bool, results: list[np.ndarray])` while delegating to the
    isolated F1-A pipeline when enabled (preserving raw F0 DTMF separation and
    avoiding double LookbackBuffer prepending).
    """

    def __init__(
        self,
        *,
        session_id: str,
        vad_engine: VADEngineAdapter,
        profile: F1ProfileConfig | None = None,
        clock: Clock | None = None,
        on_speech_start: Callable[[], None] | None = None,
    ) -> None:
        self.clock: Clock = clock or SystemMonotonicClock()
        self._stream_ref = StreamRef(
            session_id=session_id,
            stream_id="legacy-in",
            direction=StreamDirection.INPUT,
            format_epoch=0,
        )
        self._fmt = AudioFormat(16000, 1, AudioEncoding.FLOAT32_LE)
        self._queue = BoundedUtteranceQueue(max_items=8, max_bytes=8 * 1_280_000)
        cfg = profile or F1ProfileConfig.strict_experimental(route_mode=F1RouteMode.STRICT)
        self._processor = StreamAcousticProcessor(
            self._stream_ref,
            profile=cfg,
            config_revision="legacy-adapter",
            vad_engine=vad_engine,
            turn_allocator=_LegacyTurnBridge(session_id),
            consumer=self._queue,
            clock=self.clock,
        )
        self._seq = 0
        self._offset = 0
        self._on_speech_start = on_speech_start
        self.last_voice_at: float | None = None
        self.speech: list[np.ndarray] = []

    @property
    def active(self) -> bool:
        return self._processor.fsm.state.value in {"SPEECH_ACTIVE", "SILENCE_PENDING"}

    def feed(self, samples: np.ndarray) -> tuple[bool, list[np.ndarray]]:
        arr = np.asarray(samples, dtype=np.float32)
        if arr.ndim != 1 or len(arr) == 0:
            return False, []
        frame = AudioFrame(
            schema_version=CONTRACT_SCHEMA_VERSION,
            stream_ref=self._stream_ref,
            sequence=self._seq,
            format=self._fmt,
            sample_count=int(len(arr)),
            sample_offset=self._offset,
            payload=np.ascontiguousarray(arr, dtype=np.float32).tobytes(),
        )
        self._seq += 1
        self._offset += int(len(arr))
        outcome = self._processor.process_frame(frame)
        started = any(ev.kind == SpeechEventKind.SPEECH_START for ev in outcome.speech_events)
        if started and self._on_speech_start is not None:
            self._on_speech_start()
        if any(o.ok and o.score is not None and o.score >= self._processor.profile.start_threshold for o in outcome.observations):
            self.last_voice_at = self.clock.monotonic_ns() / 1_000_000_000.0

        results: list[np.ndarray] = []
        while True:
            utt = self._queue.pop_next()
            if utt is None:
                break
            results.append(utterance_to_legacy_stt_ndarray(utt))
        return started, results

    def close(self) -> None:
        self._processor.revoke_and_close("legacy_adapter_close")
