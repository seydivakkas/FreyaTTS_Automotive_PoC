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

import asyncio
import inspect
import math
from dataclasses import dataclass
from typing import Any, Iterable

from backend.core.contracts.validation import require_finite, require_strict_int
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.deadlines import Clock, DeadlineBudget
from backend.runtime_resources.contracts import ExecutionLease
from backend.speech_recognition.config_adapter import DecodeProfile
from backend.speech_recognition.errors import ASRProviderError

DEFAULT_TIMESTAMP_TOLERANCE_SEC = 0.05  # Faster-Whisper 20-30ms frame rounding tolerance


@dataclass(frozen=True, slots=True)
class CollectorLimits:
    """Explicit bounds preventing unbounded lazy Whisper iterator materialization."""

    max_segments: int = 256
    max_text_bytes: int = 65_536
    max_word_timestamps: int = 4_096
    timestamp_tolerance_sec: float = DEFAULT_TIMESTAMP_TOLERANCE_SEC
    reject_invalid_timestamps: bool = False

    def __post_init__(self) -> None:
        require_strict_int(self.max_segments, "max_segments", minimum=1, maximum=10_000)
        require_strict_int(self.max_text_bytes, "max_text_bytes", minimum=1, maximum=1_048_576)
        require_strict_int(self.max_word_timestamps, "max_word_timestamps", minimum=0, maximum=100_000)
        require_finite(self.timestamp_tolerance_sec, "timestamp_tolerance_sec", minimum=0.0, maximum=5.0)


@dataclass(frozen=True, slots=True)
class WordTiming:
    """Optional immutable word timing metadata relative to utterance start."""

    word: str
    start_sec: float
    end_sec: float
    probability: float | None = None
    unit: str = "seconds"
    origin: str = "utterance_start"


@dataclass(frozen=True, slots=True)
class SegmentTimestamp:
    """Validated segment timestamp interval relative to utterance start."""

    start_sec: float
    end_sec: float
    unit: str = "seconds"
    origin: str = "utterance_start"


@dataclass(frozen=True, slots=True)
class CollectedSegment:
    """Immutable materialized provider segment preserving exact literal text."""

    index: int
    text: str
    timestamp: SegmentTimestamp | None
    avg_logprob: float | None
    no_speech_prob: float | None
    compression_ratio: float | None
    words: tuple[WordTiming, ...] = ()
    filtered_by_legacy_guard: bool = False
    filter_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CollectedTranscript:
    """Complete materialized output of a bounded Whisper segment iteration."""

    segments: tuple[CollectedSegment, ...]
    raw_transcript: str
    legacy_filtered_transcript: str
    detected_language: str | None
    language_probability: float | None
    terminal_verified: bool
    cancelled: bool
    budget_exceeded: bool
    malformed_metadata: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None


def _is_finite_number(val: object) -> bool:
    return not isinstance(val, bool) and isinstance(val, (int, float)) and math.isfinite(float(val))


def _validate_segment_timestamp(
    raw_start: object,
    raw_end: object,
    *,
    utterance_duration_sec: float | None,
    tolerance_sec: float,
    seg_idx: int,
) -> tuple[SegmentTimestamp | None, str | None]:
    if raw_start is None and raw_end is None:
        return None, None
    if not _is_finite_number(raw_start) or not _is_finite_number(raw_end):
        return None, f"segment_{seg_idx}_nonfinite_timestamp"
    start = float(raw_start)  # type: ignore[arg-type]
    end = float(raw_end)  # type: ignore[arg-type]
    if start < 0.0 or end < 0.0:
        return None, f"segment_{seg_idx}_negative_timestamp"
    if end < start:
        return None, f"segment_{seg_idx}_reversed_timestamp"
    if utterance_duration_sec is not None and end > (utterance_duration_sec + tolerance_sec):
        return None, f"segment_{seg_idx}_timestamp_out_of_range"
    return SegmentTimestamp(start_sec=start, end_sec=end), None


def _extract_word_timings(
    raw_words: object,
    *,
    max_remaining: int,
    utterance_duration_sec: float | None,
    tolerance_sec: float,
    seg_idx: int,
) -> tuple[tuple[WordTiming, ...], list[str], bool]:
    if raw_words is None:
        return (), [], False
    if not isinstance(raw_words, Iterable) or isinstance(raw_words, (str, bytes)):
        return (), [f"segment_{seg_idx}_invalid_words_container"], False
    collected: list[WordTiming] = []
    warnings: list[str] = []
    for w_idx, w in enumerate(raw_words):
        if len(collected) >= max_remaining:
            return tuple(collected), warnings, True
        w_text = getattr(w, "word", None) if not isinstance(w, dict) else w.get("word")
        w_start = getattr(w, "start", None) if not isinstance(w, dict) else w.get("start")
        w_end = getattr(w, "end", None) if not isinstance(w, dict) else w.get("end")
        w_prob = getattr(w, "probability", None) if not isinstance(w, dict) else w.get("probability")
        if not isinstance(w_text, str):
            warnings.append(f"segment_{seg_idx}_word_{w_idx}_invalid_text")
            continue
        ts, ts_err = _validate_segment_timestamp(
            w_start,
            w_end,
            utterance_duration_sec=utterance_duration_sec,
            tolerance_sec=tolerance_sec,
            seg_idx=seg_idx,
        )
        if ts is None:
            warnings.append(ts_err or f"segment_{seg_idx}_word_{w_idx}_missing_timestamp")
            continue
        prob_val: float | None = None
        if w_prob is not None:
            if _is_finite_number(w_prob) and 0.0 <= float(w_prob) <= 1.0:
                prob_val = float(w_prob)
            else:
                warnings.append(f"segment_{seg_idx}_word_{w_idx}_invalid_probability")
        collected.append(WordTiming(word=w_text, start_sec=ts.start_sec, end_sec=ts.end_sec, probability=prob_val))
    return tuple(collected), warnings, False


def _extract_segment_fields(seg: Any) -> tuple[str, object, object, object, object, object, object]:
    if isinstance(seg, str):
        return seg, None, None, None, None, None, None
    if isinstance(seg, dict):
        return (
            seg.get("text", ""),
            seg.get("start"),
            seg.get("end"),
            seg.get("avg_logprob"),
            seg.get("no_speech_prob"),
            seg.get("compression_ratio"),
            seg.get("words"),
        )
    return (
        getattr(seg, "text", ""),
        getattr(seg, "start", None),
        getattr(seg, "end", None),
        getattr(seg, "avg_logprob", None),
        getattr(seg, "no_speech_prob", None),
        getattr(seg, "compression_ratio", None),
        getattr(seg, "words", None),
    )


def _evaluate_legacy_guards(
    *,
    text: str,
    avg_logprob: object,
    no_speech_prob: object,
    compression_ratio: object,
    profile: DecodeProfile,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if _is_finite_number(no_speech_prob) and 0.0 <= float(no_speech_prob) <= 1.0 and float(no_speech_prob) > profile.post_no_speech_prob_max:
        reasons.append("no_speech_prob")
    if _is_finite_number(avg_logprob) and float(avg_logprob) <= 0.0 and float(avg_logprob) < profile.post_avg_logprob_min:
        reasons.append("avg_logprob")
    if _is_finite_number(compression_ratio) and float(compression_ratio) >= 0.0 and float(compression_ratio) > profile.post_compression_ratio_max:
        reasons.append("compression_ratio")
    if not text.strip():
        reasons.append("empty_text")
    return bool(reasons), tuple(reasons)


def _close_iterator_best_effort(iterator: Any) -> None:
    close_fn = getattr(iterator, "close", None)
    if callable(close_fn):
        try:
            close_fn()
        except Exception:
            pass


async def _aclose_iterator_best_effort(iterator: Any) -> None:
    aclose_fn = getattr(iterator, "aclose", None)
    if callable(aclose_fn):
        try:
            res = aclose_fn()
            if inspect.isawaitable(res):
                await res
        except Exception:
            pass
    else:
        _close_iterator_best_effort(iterator)


async def collect_whisper_segments(
    segments_iter: Any,
    *,
    info: Any = None,
    decode_profile: DecodeProfile | None = None,
    limits: CollectorLimits | None = None,
    utterance_duration_sec: float | None = None,
    lease: ExecutionLease | None = None,
    cancellation_scope: CancellationScope | None = None,
    deadline: DeadlineBudget | None = None,
    clock: Clock | None = None,
) -> CollectedTranscript:
    """
    Safely materialize a lazy sync or async Whisper segment iterator under explicit bounds.

    - Never calls `list()` on unbounded iterators.
    - Preserves exact literal segment text ordering (`"".join(seg.text)`).
    - Separates `raw_transcript` from `legacy_filtered_transcript`.
    - Requires terminal iterator exhaustion before `terminal_verified=True`.
    """
    profile = decode_profile or DecodeProfile()
    lim = limits or CollectorLimits()
    collected: list[CollectedSegment] = []
    malformed: list[str] = []
    total_text_bytes = 0
    total_words = 0
    cancelled = False
    budget_exceeded = False
    terminal_verified = False
    error_code: str | None = None
    error_message: str | None = None

    def _is_cancelled() -> bool:
        if lease is not None and lease.is_output_fenced:
            return True
        if cancellation_scope is not None and cancellation_scope.is_cancel_requested:
            return True
        return False

    def _is_expired() -> bool:
        if deadline is not None and clock is not None:
            return deadline.is_expired(clock)
        return False

    def _process_raw_segment(raw_seg: Any, idx: int) -> bool:
        nonlocal total_text_bytes, total_words, budget_exceeded, error_code, error_message
        raw_text, raw_start, raw_end, raw_lp, raw_nsp, raw_cr, raw_words = _extract_segment_fields(raw_seg)
        if not isinstance(raw_text, str):
            raise ASRProviderError("ASR_MALFORMED_SEGMENT_TEXT", "Provider segment text must be str")

        seg_bytes = len(raw_text.encode("utf-8"))
        if len(collected) >= lim.max_segments:
            budget_exceeded = True
            error_code = "ASR_SEGMENT_LIMIT_EXCEEDED"
            error_message = f"Segment count exceeded max_segments={lim.max_segments}"
            return False
        if total_text_bytes + seg_bytes > lim.max_text_bytes:
            budget_exceeded = True
            error_code = "ASR_TEXT_BYTE_LIMIT_EXCEEDED"
            error_message = f"Transcript bytes exceeded max_text_bytes={lim.max_text_bytes}"
            return False

        ts, ts_err = _validate_segment_timestamp(
            raw_start,
            raw_end,
            utterance_duration_sec=utterance_duration_sec,
            tolerance_sec=lim.timestamp_tolerance_sec,
            seg_idx=idx,
        )
        if ts_err is not None:
            malformed.append(ts_err)
            if lim.reject_invalid_timestamps:
                raise ASRProviderError("ASR_INVALID_SEGMENT_TIMESTAMP", f"Invalid segment timestamp: {ts_err}")

        words: tuple[WordTiming, ...] = ()
        if raw_words is not None:
            words, w_warn, word_limit_hit = _extract_word_timings(
                raw_words,
                max_remaining=max(0, lim.max_word_timestamps - total_words),
                utterance_duration_sec=utterance_duration_sec,
                tolerance_sec=lim.timestamp_tolerance_sec,
                seg_idx=idx,
            )
            malformed.extend(w_warn)
            total_words += len(words)
            if word_limit_hit:
                budget_exceeded = True
                error_code = "ASR_WORD_TIMESTAMP_LIMIT_EXCEEDED"
                error_message = f"Word timestamps exceeded max_word_timestamps={lim.max_word_timestamps}"
                return False

        avg_lp = float(raw_lp) if _is_finite_number(raw_lp) and float(raw_lp) <= 0.0 else None
        if raw_lp is not None and avg_lp is None:
            malformed.append(f"segment_{idx}_invalid_avg_logprob")
        nsp = float(raw_nsp) if _is_finite_number(raw_nsp) and 0.0 <= float(raw_nsp) <= 1.0 else None
        if raw_nsp is not None and nsp is None:
            malformed.append(f"segment_{idx}_invalid_no_speech_prob")
        cr = float(raw_cr) if _is_finite_number(raw_cr) and float(raw_cr) >= 0.0 else None
        if raw_cr is not None and cr is None:
            malformed.append(f"segment_{idx}_invalid_compression_ratio")

        filtered, reasons = _evaluate_legacy_guards(
            text=raw_text,
            avg_logprob=raw_lp,
            no_speech_prob=raw_nsp,
            compression_ratio=raw_cr,
            profile=profile,
        )
        collected.append(
            CollectedSegment(
                index=idx,
                text=raw_text,
                timestamp=ts,
                avg_logprob=avg_lp,
                no_speech_prob=nsp,
                compression_ratio=cr,
                words=words,
                filtered_by_legacy_guard=filtered,
                filter_reasons=reasons,
            )
        )
        total_text_bytes += seg_bytes
        return True

    idx = 0
    if hasattr(segments_iter, "stream_segments"):
        segments_iter = segments_iter.stream_segments()
    try:
        if hasattr(segments_iter, "__aiter__"):
            try:
                async for seg in segments_iter:
                    if _is_cancelled():
                        cancelled = True
                        break
                    if _is_expired():
                        budget_exceeded = True
                        error_code = "ASR_DEADLINE_EXCEEDED"
                        error_message = "Deadline exceeded during lazy segment iteration"
                        break
                    if not _process_raw_segment(seg, idx):
                        break
                    idx += 1
                else:
                    if not _is_cancelled() and not _is_expired():
                        terminal_verified = True
            finally:
                await _aclose_iterator_best_effort(segments_iter)
        else:
            iterator = iter(segments_iter)
            try:
                for seg in iterator:
                    if _is_cancelled():
                        cancelled = True
                        break
                    if _is_expired():
                        budget_exceeded = True
                        error_code = "ASR_DEADLINE_EXCEEDED"
                        error_message = "Deadline exceeded during lazy segment iteration"
                        break
                    if not _process_raw_segment(seg, idx):
                        break
                    idx += 1
                    await asyncio.sleep(0)
                else:
                    if not _is_cancelled() and not _is_expired():
                        terminal_verified = True
            finally:
                _close_iterator_best_effort(iterator)
    except ASRProviderError as exc:
        error_code = exc.code
        error_message = exc.safe_message
        terminal_verified = False
    except Exception as exc:
        error_code = "ASR_PROVIDER_ITERATION_ERROR"
        error_message = f"Provider iteration failed: {type(exc).__name__}"
        terminal_verified = False

    detected_lang = None
    lang_prob: float | None = None
    if info is not None:
        raw_lang = info.get("language") if isinstance(info, dict) else getattr(info, "language", None)
        if isinstance(raw_lang, str) and raw_lang.strip():
            detected_lang = raw_lang.strip()
        raw_prob = info.get("language_probability") if isinstance(info, dict) else getattr(info, "language_probability", None)
        if _is_finite_number(raw_prob) and 0.0 <= float(raw_prob) <= 1.0:
            lang_prob = float(raw_prob)

    raw_transcript = "".join(s.text for s in collected)
    legacy_parts = [s.text.strip() for s in collected if not s.filtered_by_legacy_guard and s.text.strip()]
    legacy_filtered = " ".join(legacy_parts)

    return CollectedTranscript(
        segments=tuple(collected),
        raw_transcript=raw_transcript,
        legacy_filtered_transcript=legacy_filtered,
        detected_language=detected_lang,
        language_probability=lang_prob,
        terminal_verified=terminal_verified,
        cancelled=cancelled,
        budget_exceeded=budget_exceeded,
        malformed_metadata=tuple(malformed),
        error_code=error_code,
        error_message=error_message,
    )
