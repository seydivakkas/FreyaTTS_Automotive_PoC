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

from backend.morphology.contracts import (
    ExtendedProsodyPlan,
    LexiconEntry,
    NormalizedUtterance,
    WordPhoneticHint,
    generate_hint_for_failed_word,
)
from backend.morphology.syllabifier import TurkishSyllabifier
from backend.morphology.text_utils import (
    normalize_apostrophes,
    tr_lower,
    tr_upper,
)

__all__ = [
    "ExtendedProsodyPlan",
    "LexiconEntry",
    "NormalizedUtterance",
    "WordPhoneticHint",
    "generate_hint_for_failed_word",
    "TurkishSyllabifier",
    "normalize_apostrophes",
    "tr_lower",
    "tr_upper",
]

