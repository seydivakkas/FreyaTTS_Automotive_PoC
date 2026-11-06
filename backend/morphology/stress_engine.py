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

import re
from typing import Dict, List, Optional, Tuple

from backend.morphology.contracts import WordPhoneticHint
from backend.morphology.syllabifier import TurkishSyllabifier
from backend.morphology.text_utils import tr_lower

# Tek heceli veya olumsuzluk eki taşımayan isim kökleri
# (Bu kelimeler -ma/-me ile bitse bile son hece vurguludur)
MONOSYLLABIC_MA_ME_NOUNS = {
    "elma", "armut", "kazma", "sarma", "dolma", "kıyma",
    "basma", "çakma", "lokma", "krema", "drama", "şema", "tema"
}

# Vurgu çeken (Pre-Stressing) istisnai ek kuralları tablosu
# Kural semantiği: Vurgu, ilgili ekin başladığı hecenin HEMEN ÖNCEKİ hecesine kilitlenir.
# Tablo verisi: (kural_adı, regex_pattern)
PRE_STRESSING_RULES: List[Tuple[str, re.Pattern]] = [
    # 1. Olumsuzluk eki (-ma/-me ve şimdiki zaman daralması -mıyor/-miyor/-muyor/-müyor)
    # Örn: gel-ME-di -> ˈgel-me-di, gö-rüş-tü-rü-le-ME-di -> gö-rüş-tü-rü-ˈle-me-di
    (
        "suffix:negation_-ma",
        re.compile(
            r"^(?P<stem>.+[aeıioöuüâîû][^aeıioöuüâîû]*)"
            r"(?P<suffix>m[ae]|m[ıiuü]yor)"
            r"(?P<tail>d[ıiuü]|d[ıiuü]k|d[ıiuü]lar|m[ıiuü]ş|s[ae]|acak|ecek|y?[ae]n|lar|ler|s[ıiuü]n|y?[ıiuü]z)?$",
            re.IGNORECASE,
        ),
    ),
    # 2. Zarf-fiil eki (-ken / -yken)
    # Örn: gi-der-KEN -> gi-ˈder-ken, ça-lı-şır-KEN -> ça-lı-ˈşır-ken, ev-dey-KEN -> ev-ˈdey-ken
    (
        "suffix:converb_-ken",
        re.compile(
            r"^(?P<stem>.+[aeıioöuüâîû][^aeıioöuüâîû]*?)(?P<suffix>y?ken)$",
            re.IGNORECASE,
        ),
    ),
    # 3. Sıfatlaştıran / Bağlaç -ki ve -da/-de ek öbeği (-daki/-deki/-taki/-teki)
    # Örn: ba-yi-de-ki -> ba-ˈyi-de-ki, ev-de-ki -> ˈev-de-ki
    (
        "suffix:relativizer_-deki",
        re.compile(
            r"^(?P<stem>.+[aeıioöuüâîû][^aeıioöuüâîû]*?)(?P<suffix>[dt][ae]ki)$",
            re.IGNORECASE,
        ),
    ),
    # 4. Bildirme (-dır/-dir/-dur/-dür/-tır/-tir) ve Ek-fiil şahıs ekleri (-sın/-sin, -yım/-yim)
    # Örn: öğ-ren-ci-dir -> öğ-ren-ˈci-dir, ha-zı-rım -> ha-ˈzı-rım
    (
        "suffix:copula_-dir",
        re.compile(
            r"^(?P<stem>.+[aeıioöuüâîû][^aeıioöuüâîû]*?)(?P<suffix>[dt][ıiuü]r(?:lar|ler)?|s[ıiuü]n(?:ız|iz|uz|üz)?)$",
            re.IGNORECASE,
        ),
    ),
    # 5. Eşitlik (-ca/-ce/-ça/-çe) ve Vasıta/Birliktelik (-la/-le / -yla/-yle)
    # Örn: hız-lı-ca -> hız-ˈlı-ca, müş-te-ri-ler-le -> müş-te-ri-ˈler-le
    (
        "suffix:adverb_-ce_-le",
        re.compile(
            r"^(?P<stem>.+[aeıioöuüâîû][^aeıioöuüâîû]*?)(?P<suffix>[çc][ae]|y?l[ae])$",
            re.IGNORECASE,
        ),
    ),
]


class MorphologicalStressEngine:
    """
    Türkçe morfolojik vurgu çözümleme motoru:
    1. Öncelik 1: Kalıplaşmış istisnalar (LEXICALIZED_STRESS_EXCEPTIONS)
    2. Öncelik 2: Vurgu çeken ek kuralları (PRE_STRESSING_RULES)
    3. Öncelik 3: Varsayılan Türkçe kuralı (Son hece)
    """

    def __init__(self, stress_exceptions: Optional[Dict[str, int]] = None):
        self.stress_exceptions = stress_exceptions or {}

    def analyze_word(
        self,
        raw_word: str,
        force_stress_before_clitic: bool = False,
    ) -> Optional[WordPhoneticHint]:
        """
        Kelimeyi hecelerine ayırır, vurgu çeken istisnaları analiz eder.
        Vurgu son heceden sapıyorsa veya clitic öncesi vurgu kilitlenmişse WordPhoneticHint döner.
        """
        clean = re.sub(r"[^a-zçğıöşüâîû]", "", tr_lower(raw_word))
        if not clean:
            return None

        syllables = TurkishSyllabifier.syllabify(clean)
        if len(syllables) <= 1:
            return None

        default_last_idx = len(syllables) - 1
        detected_stress_idx = default_last_idx
        stress_reason = "default_final"
        is_exceptional = False

        # 1. Kalıplaşmış 1. hece istisnası (halbuki, oysaki, çünkü, şimdi vb.)
        if clean in self.stress_exceptions:
            detected_stress_idx = self.stress_exceptions[clean]
            stress_reason = "lexicalized_exception"
            is_exceptional = True

        # 2. Morfolojik vurgu çeken istisnai ek kuralları
        elif clean not in MONOSYLLABIC_MA_ME_NOUNS:
            for rule_name, pattern in PRE_STRESSING_RULES:
                match = pattern.match(clean)
                if match:
                    stem_part = match.group("stem")
                    stem_syllables = TurkishSyllabifier.syllabify(stem_part)
                    if stem_syllables:
                        # Vurgu, ekin hemen öncesindeki hecenin son hecesine kilitlenir
                        detected_stress_idx = len(stem_syllables) - 1
                        stress_reason = rule_name
                        is_exceptional = True
                        break

        # 3. Ayrı yazılan clitic öncesi son hece vurgusunu kilitle
        if force_stress_before_clitic and not is_exceptional:
            detected_stress_idx = default_last_idx
            stress_reason = "clitic_locked"
            is_exceptional = True

        if not is_exceptional:
            return None

        ipa_guide = "-".join(
            f"ˈ{syl}" if i == detected_stress_idx else syl
            for i, syl in enumerate(syllables)
        )

        return WordPhoneticHint(
            target_word=raw_word.strip(".,!?;:\"'()[]"),
            morpheme_breakdown="-".join(syllables),
            primary_stress_syllable_idx=detected_stress_idx,
            stress_reason=stress_reason,
            phonetic_guide=ipa_guide,
            source="stress_engine",
        )

