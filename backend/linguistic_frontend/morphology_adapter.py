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
from typing import Any


@dataclass(frozen=True, slots=True)
class MorphologyAnalysisResult:
    """
    Read-only morphological & clitic hint output kept separate from model_text.

    Never injects IPA stress glyphs or SSML into model_text and never re-normalizes.
    """

    enabled: bool
    emphasis_targets: tuple[str, ...] = ()
    clitic_pause_ms: int = 0
    hint_count: int = 0
    phonetic_guides_held_back: int = 0
    warnings: tuple[str, ...] = ()


def analyze_morphology_readonly(
    normalized_text: str,
    *,
    enabled: bool = True,
    pause_ms: int = 35,
    prechecker: Any | None = None,
) -> MorphologyAnalysisResult:
    """
    Run existing MorphologicalPreChecker read-only over normalized_text.

    Phonetic/IPA guides remain strictly in local/telemetry diagnostics and are NEVER
    injected into model_text.
    """
    if not enabled or not normalized_text or not normalized_text.strip():
        return MorphologyAnalysisResult(enabled=enabled)

    from backend.morphology.contracts import NormalizedUtterance

    checker = prechecker
    if checker is None:
        from backend.morphological_pre_checker import MorphologicalPreChecker
        checker = MorphologicalPreChecker(pause_ms=pause_ms, enabled=True)

    utterance = NormalizedUtterance(
        utterance_id="utt_f4a_readonly",
        chunk_id="chk_0",
        chunk_text=normalized_text,
    )
    plan = checker.analyze(utterance)
    total_pause_ms = sum(int(v) for v in plan.pause_injections_ms.values() if int(v) > 0)
    guides_count = sum(1 for h in plan.pronunciation_hints if getattr(h, "phonetic_guide", None))

    return MorphologyAnalysisResult(
        enabled=True,
        emphasis_targets=tuple(plan.emphasis_targets),
        clitic_pause_ms=total_pause_ms,
        hint_count=len(plan.pronunciation_hints),
        phonetic_guides_held_back=guides_count,
        warnings=tuple(plan.warnings),
    )
