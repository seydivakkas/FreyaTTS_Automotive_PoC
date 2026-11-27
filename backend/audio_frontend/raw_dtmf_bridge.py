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
from typing import Callable

import numpy as np

from backend.core.contracts.common import StreamRef
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.dtmf import GoertzelDetector


@dataclass(frozen=True, slots=True)
class RawDtmfEvent:
    """Internal raw DTMF detection event (digits are NEVER logged in M04 telemetry)."""

    stream_ref: StreamRef
    digit: str
    source: str  # "inband" or "signaling"
    detected_monotonic_ns: int
    clock_domain: str
    deduped: bool = False

    def __repr__(self) -> str:
        # Redact digit from repr to prevent accidental PII/digit leaks in logs.
        return (
            f"RawDtmfEvent(stream={self.stream_ref.stream_id!r}, "
            f"source={self.source!r}, deduped={self.deduped})"
        )


@dataclass(frozen=True, slots=True)
class RawDtmfTapResult:
    """Outcome of tapping original source-rate PCM prior to DSP and resampling."""

    main_samples: np.ndarray
    emitted_events: tuple[RawDtmfEvent, ...]
    suppressed_duplicates: int
    tap_errors: int


class RawDtmfBridge:
    """
    Pre-DSP raw DTMF detector and cross-path deduplication bridge.

    - Operates at the stream's true native sample_rate_hz (8k / 16k / 48k, etc.).
    - Observes original source samples BEFORE HPF, spectral suppression, AGC/gate, and resampling.
    - Passes an immutable read-only copy to any external raw tap observer so observer
      mutation attempts or failures cannot corrupt the main audio stream.
    - Deduplicates overlapping in-band Goertzel and out-of-band signaling DTMF events.
    """

    def __init__(
        self,
        stream_ref: StreamRef,
        *,
        sample_rate_hz: int,
        clock: Clock | None = None,
        dedup_window_ms: int = 120,
        notch_main_audio: bool = True,
        raw_tap_observer: Callable[[np.ndarray, int], None] | None = None,
        dispatch_callback: Callable[[RawDtmfEvent], None] | None = None,
    ) -> None:
        if type(sample_rate_hz) is not int or sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive int")
        if type(dedup_window_ms) is not int or dedup_window_ms < 0:
            raise ValueError("dedup_window_ms must be non-negative int")
        self.stream_ref = stream_ref
        self.sample_rate_hz = sample_rate_hz
        self.clock: Clock = clock or SystemMonotonicClock()
        self.dedup_window_ns = dedup_window_ms * 1_000_000
        self.notch_main_audio = notch_main_audio
        self._raw_tap_observer = raw_tap_observer
        self._dispatch_callback = dispatch_callback

        self._detector = GoertzelDetector(sample_rate=sample_rate_hz, frame_ms=20)
        self._frame_size = self._detector.frame_size
        self._pending_tap = np.zeros(0, dtype=np.float32)
        self._max_pending_samples = self._frame_size * 4

        self._last_digit: str | None = None
        self._last_digit_ns: int | None = None
        self.total_emitted: int = 0
        self.total_deduped: int = 0
        self.tap_error_count: int = 0
        self.dispatch_error_count: int = 0

    def _should_emit(self, digit: str, now_ns: int) -> bool:
        if (
            self._last_digit == digit
            and self._last_digit_ns is not None
            and (now_ns - self._last_digit_ns) < self.dedup_window_ns
        ):
            self.total_deduped += 1
            return False
        self._last_digit = digit
        self._last_digit_ns = now_ns
        return True

    def _dispatch_event(self, ev: RawDtmfEvent) -> None:
        self.total_emitted += 1
        if self._dispatch_callback is not None:
            try:
                self._dispatch_callback(ev)
            except Exception:
                self.dispatch_error_count += 1

    def _notify_raw_observer(self, raw_samples: np.ndarray) -> None:
        if self._raw_tap_observer is None:
            return
        # Provide an isolated read-only copy so observer mutations fail safely without affecting main audio
        readonly_copy = raw_samples.copy()
        readonly_copy.setflags(write=False)
        try:
            self._raw_tap_observer(readonly_copy, self.sample_rate_hz)
        except Exception:
            self.tap_error_count += 1

    def tap_raw_samples(self, samples: np.ndarray) -> RawDtmfTapResult:
        """
        Inspect original native-rate samples prior to DSP.

        Returns RawDtmfTapResult with main_samples (notched only if tone detected and notch enabled)
        and deduplicated RawDtmfEvent objects.
        """
        arr = np.ascontiguousarray(samples, dtype=np.float32)
        if len(arr) == 0:
            return RawDtmfTapResult(
                main_samples=arr,
                emitted_events=(),
                suppressed_duplicates=0,
                tap_errors=self.tap_error_count,
            )

        self._notify_raw_observer(arr)

        main_out = arr.copy()
        detected_digits: list[str] = []

        if len(self._pending_tap) == 0 and len(arr) >= self._frame_size and len(arr) % self._frame_size == 0:
            digits, cleaned = self._detector.process_samples(arr)
            detected_digits.extend(digits)
            if self.notch_main_audio:
                main_out = np.ascontiguousarray(cleaned, dtype=np.float32)
        else:
            # Buffer partial/unaligned chunks only for raw detector alignment; never delay main_out
            combined = np.concatenate((self._pending_tap, arr))
            usable = (len(combined) // self._frame_size) * self._frame_size
            if usable >= self._frame_size:
                block = combined[:usable]
                rem = combined[usable:]
                digits, cleaned_block = self._detector.process_samples(block)
                detected_digits.extend(digits)
                if self.notch_main_audio and digits:
                    # Apply notch to tail region overlapping current arrival
                    overlap_len = min(len(main_out), len(cleaned_block))
                    if overlap_len > 0:
                        main_out[:overlap_len] = cleaned_block[-overlap_len:]
                self._pending_tap = rem[-self._max_pending_samples :] if len(rem) > self._max_pending_samples else rem
            else:
                self._pending_tap = combined[-self._max_pending_samples :] if len(combined) > self._max_pending_samples else combined

        now_ns = self.clock.monotonic_ns()
        emitted: list[RawDtmfEvent] = []
        suppressed = 0
        for d in detected_digits:
            if self._should_emit(d, now_ns):
                ev = RawDtmfEvent(
                    stream_ref=self.stream_ref,
                    digit=d,
                    source="inband",
                    detected_monotonic_ns=now_ns,
                    clock_domain=self.clock.clock_domain,
                    deduped=False,
                )
                self._dispatch_event(ev)
                emitted.append(ev)
            else:
                suppressed += 1

        return RawDtmfTapResult(
            main_samples=main_out,
            emitted_events=tuple(emitted),
            suppressed_duplicates=suppressed,
            tap_errors=self.tap_error_count,
        )

    def submit_signaling_digit(self, digit: str) -> RawDtmfEvent | None:
        """
        Admit an out-of-band signaling DTMF digit (e.g. AudioSocket 0x03 or WS JSON)
        with shared cross-path deduplication.
        """
        clean = str(digit).strip().upper()
        if not clean:
            return None
        now_ns = self.clock.monotonic_ns()
        if not self._should_emit(clean, now_ns):
            return None
        ev = RawDtmfEvent(
            stream_ref=self.stream_ref,
            digit=clean,
            source="signaling",
            detected_monotonic_ns=now_ns,
            clock_domain=self.clock.clock_domain,
            deduped=False,
        )
        self._dispatch_event(ev)
        return ev

    def reset(self) -> None:
        self._detector = GoertzelDetector(sample_rate=self.sample_rate_hz, frame_ms=20)
        self._pending_tap = np.zeros(0, dtype=np.float32)
        self._last_digit = None
        self._last_digit_ns = None
