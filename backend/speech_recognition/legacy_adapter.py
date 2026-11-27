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

from backend.core.contracts.recognition import ASROutcome, ASRResult
from backend.speech_recognition.transcript_collector import CollectedTranscript


@dataclass(frozen=True, slots=True)
class LegacyASRProjection:
    """
    Historical `Models.transcribe` string projection separated from literal `raw_transcript`.

    Matches `backend/models.py:347-351`: per-segment `.strip()`, filtered by
    no_speech_prob/avg_logprob/compression_ratio guards, joined by single spaces.
    """

    legacy_text: str
    raw_transcript: str
    outcome: ASROutcome


def project_legacy_transcript(
    *,
    result: ASRResult | None = None,
    collected: CollectedTranscript | None = None,
) -> LegacyASRProjection:
    """
    Project exact historical `str` output at the legacy compatibility boundary
    without mutating `ASRResult.raw_transcript`.
    """
    if collected is not None:
        raw = collected.raw_transcript
        legacy = collected.legacy_filtered_transcript
        outcome = (
            result.outcome
            if result is not None
            else (ASROutcome.OK if legacy.strip() else ASROutcome.NO_SPEECH)
        )
        if outcome != ASROutcome.OK:
            legacy = ""
        return LegacyASRProjection(legacy_text=legacy, raw_transcript=raw, outcome=outcome)

    if result is None:
        return LegacyASRProjection(legacy_text="", raw_transcript="", outcome=ASROutcome.NO_SPEECH)

    if result.outcome != ASROutcome.OK:
        return LegacyASRProjection(
            legacy_text="",
            raw_transcript=result.raw_transcript,
            outcome=result.outcome,
        )

    return LegacyASRProjection(
        legacy_text=result.raw_transcript.strip(),
        raw_transcript=result.raw_transcript,
        outcome=result.outcome,
    )
