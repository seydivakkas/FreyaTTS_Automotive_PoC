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

from backend.semantic_turn_detector import (
    COMPLETING_PREDICATE_WORDS,
    DISCOURSE_MARKERS_UNFINISHED_MULTI,
    DISCOURSE_MARKERS_UNFINISHED_SINGLE,
    POSTPOSITIONS_INCOMPLETE,
    QUESTION_PARTICLES,
    VERB_PATTERNS,
    SemanticAnalysisResult,
    SemanticTurnDetector,
    SmartTurnAudioSocketAdapter,
    TurnDecision,
    analyze_semantic_completeness,
    estimate_f0_pitch_slope,
    normalize_turkish_text,
    resample_to_16k,
)

__all__ = [
    "COMPLETING_PREDICATE_WORDS",
    "DISCOURSE_MARKERS_UNFINISHED_MULTI",
    "DISCOURSE_MARKERS_UNFINISHED_SINGLE",
    "POSTPOSITIONS_INCOMPLETE",
    "QUESTION_PARTICLES",
    "VERB_PATTERNS",
    "SemanticAnalysisResult",
    "SemanticTurnDetector",
    "SmartTurnAudioSocketAdapter",
    "TurnDecision",
    "analyze_semantic_completeness",
    "estimate_f0_pitch_slope",
    "normalize_turkish_text",
    "resample_to_16k",
]

