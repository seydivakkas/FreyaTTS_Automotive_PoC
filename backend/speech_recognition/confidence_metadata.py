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

import math
from dataclasses import dataclass

from backend.core.contracts.recognition import ConfidenceEstimate
from backend.speech_recognition.transcript_collector import CollectedTranscript


@dataclass(frozen=True, slots=True)
class ConfidenceExtractionResult:
    """Native ASR confidence evidence without synthetic calibration."""

    estimate: ConfidenceEstimate | None
    malformed_scores: tuple[str, ...] = ()


def _valid_float(value: object, *, minimum: float | None = None, maximum: float | None = None) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    if not math.isfinite(f):
        return None
    if minimum is not None and f < minimum:
        return None
    if maximum is not None and f > maximum:
        return None
    return f


def extract_confidence_estimate(collected: CollectedTranscript) -> ConfidenceExtractionResult:
    """
    Extract native `ConfidenceEstimate` from validated provider segment metadata.

    Preserves negative `avg_logprob` directly (never converted into a fake probability)
    and rejects non-finite or out-of-range native scores instead of fabricating defaults.
    """
    kept = [s for s in collected.segments if not s.filtered_by_legacy_guard]
    target_segments = kept if kept else list(collected.segments)
    if not target_segments:
        return ConfidenceExtractionResult(estimate=None, malformed_scores=())

    malformed: list[str] = list(collected.malformed_metadata)
    logprobs: list[float] = []
    no_speech_probs: list[float] = []

    for seg in target_segments:
        if seg.avg_logprob is not None:
            lp = _valid_float(seg.avg_logprob, maximum=0.0)
            if lp is None:
                malformed.append(f"segment_{seg.index}_invalid_avg_logprob")
            else:
                logprobs.append(lp)
        if seg.no_speech_prob is not None:
            nsp = _valid_float(seg.no_speech_prob, minimum=0.0, maximum=1.0)
            if nsp is None:
                malformed.append(f"segment_{seg.index}_invalid_no_speech_prob")
            else:
                no_speech_probs.append(nsp)

    avg_lp = (sum(logprobs) / len(logprobs)) if logprobs else None
    max_nsp = max(no_speech_probs) if no_speech_probs else None

    if avg_lp is None and max_nsp is None:
        return ConfidenceExtractionResult(estimate=None, malformed_scores=tuple(malformed))

    estimate = ConfidenceEstimate(
        avg_logprob=avg_lp,
        no_speech_prob=max_nsp,
        ranking_score=None,
        calibrated_prob=None,
        calibration_version=None,
    )
    return ConfidenceExtractionResult(estimate=estimate, malformed_scores=tuple(malformed))


def resolve_language_metadata(
    collected: CollectedTranscript,
    *,
    requested_language: str | None = None,
) -> str | None:
    """
    Return detected/observed provider language if reported; never claim requested
    configuration language as a detected-language measurement when provider omitted it.
    """
    _ = requested_language  # explicitly unused as detected-language fallback
    if collected.detected_language and collected.detected_language.strip():
        return collected.detected_language.strip()
    return None
