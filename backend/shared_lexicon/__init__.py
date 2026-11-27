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

from backend.shared_lexicon.asr_adapter import (
    ASRLexiconExtraction,
    enrich_asr_result,
    extract_asr_candidates,
)
from backend.shared_lexicon.catalog_adapter import (
    CatalogItemRef,
    CatalogMatchRef,
    CatalogReader,
    CatalogResolution,
    InMemoryCatalogSeam,
)
from backend.shared_lexicon.contracts import (
    AliasEntry,
    CanonicalEntity,
    EntityCategory,
    LexiconSnapshot,
    LookupMatch,
    LookupResult,
    LookupStatus,
    MatchKind,
    PronunciationVariant,
    ProtectedSpan,
    ProtectedSpanKind,
    TechnicalTerm,
    compute_lexicon_revision,
    make_safe_id,
)
from backend.shared_lexicon.registry import LexiconRegistry
from backend.shared_lexicon.source_loader import load_lexicon_snapshot, load_vocab_chars
from backend.shared_lexicon.tts_adapter import (
    ScopedPronunciation,
    get_pronunciation_variants,
    resolve_scoped_pronunciations,
)
from backend.shared_lexicon.unicode_normalizer import (
    AlignedToken,
    NormalizedTextMap,
    detect_protected_spans,
    fold_foreign_diacritics,
    normalize_matching_key,
    normalize_with_spans,
    tokenize_aligned,
    turkish_nfc_lower,
)

__all__ = [
    "ASRLexiconExtraction",
    "AliasEntry",
    "AlignedToken",
    "CanonicalEntity",
    "CatalogItemRef",
    "CatalogMatchRef",
    "CatalogReader",
    "CatalogResolution",
    "EntityCategory",
    "InMemoryCatalogSeam",
    "LexiconRegistry",
    "LexiconSnapshot",
    "LookupMatch",
    "LookupResult",
    "LookupStatus",
    "MatchKind",
    "NormalizedTextMap",
    "PronunciationVariant",
    "ProtectedSpan",
    "ProtectedSpanKind",
    "ScopedPronunciation",
    "TechnicalTerm",
    "compute_lexicon_revision",
    "detect_protected_spans",
    "enrich_asr_result",
    "extract_asr_candidates",
    "fold_foreign_diacritics",
    "get_pronunciation_variants",
    "load_lexicon_snapshot",
    "load_vocab_chars",
    "make_safe_id",
    "normalize_matching_key",
    "normalize_with_spans",
    "resolve_scoped_pronunciations",
    "tokenize_aligned",
    "turkish_nfc_lower",
]
