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
from typing import Dict, Optional

from backend.morphology.contracts import LexiconEntry, WordPhoneticHint
from backend.morphology.syllabifier import TurkishSyllabifier, VOWELS
from backend.morphology.text_utils import tr_lower, normalize_apostrophes

# Türkçe geçerli çekim ve yapım eki zinciri kalıbı (küçük, kapalı küme)
# Çoğul (-lAr), İyelik/Şahıs, Hâl (-A, -DA, -DAn, -In, -I), -lI, -sIz, -cA, -lA, -ki, -dIr
SUFFIX_CHAIN_REGEX = re.compile(
    r"^(?:(?:lar|ler)?"
    r"(?:[ıiuü]m|[ıiuü]n|s?[ıiuü]|[ıiuü]m[ıiuü]z|[ıiuü]n[ıiuü]z|lar[ıi]|ler[ıi])?"
    r"(?:l[ıiuü]|s[ıiuü]z|c[ıiuü]|ç[ıiuü])?"
    r"(?:y?[ae]|d[ae]|t[ae]|d[ae]n|t[ae]n|n?[ıiuü]|n?[ıiuü]n)?"
    r"(?:y?l[ae]|d[ae]ki|t[ae]ki|d[ıiuü]r|t[ıiuü]r|m[ıiuü]ş)*)$",
    re.IGNORECASE,
)


class InflectedLexiconMatcher:
    """
    Yabancı kelimeler ve özel marka kodlarını Türkçe ek almış olsalar bile
    kök-ek düzeyinde çözümleyen eşleyici:
    - Kesmeli ("EcoBoost'ta", "SUV'lerin") ve kesmesiz ("Bluetoothlu", "ecoboostun")
      formları en uzun önek (longest-prefix) algoritmasıyla yakalar.
    - Ünsüz Köprülemesi (Liaison / Ulama): Kök ünsüzle bitip ek ünlüyle başladığında
      (örn: "e-ko-bust" + "un" -> "e-ko-bus-tun") son ünsüzü eke bağlayarak
      yapay kesik ses (glottal stop) oluşmasını önler.
    - Vurguyu yabancı kökteki hecesinde sabitler.
    """

    def __init__(self, lexicon: Dict[str, LexiconEntry]):
        self.lexicon = lexicon
        # En uzun önek eşleşmesi için anahtarları uzunluğa göre azalan sırala
        self._sorted_keys = sorted(self.lexicon.keys(), key=len, reverse=True)

    def match(self, raw_token: str) -> Optional[WordPhoneticHint]:
        """Ham kelimeyi kontrol eder, eşleşme varsa WordPhoneticHint döner."""
        clean_token = normalize_apostrophes(raw_token).strip(".,!?;:\"'()[]")
        lowered = tr_lower(clean_token)
        if not lowered:
            return None

        # 1. Kesme işaretiyle ayrılmış form kontrolü (Örn: EcoBoost'ta)
        if "'" in lowered:
            parts = lowered.split("'", 1)
            stem_candidate, suffix_str = parts[0], parts[1]
            if stem_candidate in self.lexicon:
                return self._build_hint(raw_token, self.lexicon[stem_candidate], suffix_str)

        # 2. Kesmesiz en uzun önek (longest-prefix) eşleşmesi (Örn: bluetoothlu, ecoboostun)
        for key in self._sorted_keys:
            if lowered.startswith(key):
                suffix_str = lowered[len(key):]
                # Kalan kısmın geçerli bir Türkçe ek zinciri olduğunu doğrula
                if suffix_str == "" or SUFFIX_CHAIN_REGEX.fullmatch(suffix_str):
                    return self._build_hint(raw_token, self.lexicon[key], suffix_str)

        return None

    def expand_spoken_token(self, raw_token: str) -> Optional[str]:
        """
        Normalizer katmanı için metin genişletmesi üretir.
        Örn: "EcoBoost'un" -> "ekobustun", "Bluetooth'lu" -> "blututlu"
        """
        hint = self.match(raw_token)
        if hint and hint.morpheme_breakdown:
            # Heceleri tirelerden arındırıp modelin okuyacağı birleşik metin üret
            return hint.morpheme_breakdown.replace("-", "")
        return None

    def _build_hint(
        self, original_word: str, entry: LexiconEntry, suffix_str: str
    ) -> WordPhoneticHint:
        stem_syllables = list(entry.phonetic_syllables)
        suffix_syllables = TurkishSyllabifier.syllabify(suffix_str) if suffix_str else []

        all_syllables = stem_syllables + suffix_syllables
        liaison_applied = False

        # Ünsüz Köprülemesi (Liaison / Ulama):
        # Kök ünsüzle bitiyor ve ek ünlüyle başlıyorsa:
        # Örn: ["e", "ko", "bust"] + ["un"] -> ["e", "ko", "bus", "tun"]
        if (
            suffix_syllables
            and suffix_syllables[0]
            and suffix_syllables[0][0] in VOWELS
            and stem_syllables
            and stem_syllables[-1]
            and stem_syllables[-1][-1] not in VOWELS
        ):
            bridged_consonant = stem_syllables[-1][-1]
            last_stem_syllable = stem_syllables[-1][:-1]
            first_suffix_syllable = bridged_consonant + suffix_syllables[0]

            new_syllables = (
                stem_syllables[:-1]
                + ([last_stem_syllable] if last_stem_syllable else [])
                + [first_suffix_syllable]
                + suffix_syllables[1:]
            )
            all_syllables = [s for s in new_syllables if s]
            liaison_applied = True

        stress_idx = min(entry.stress_syllable_idx, len(all_syllables) - 1)
        ipa_guide = "-".join(
            f"ˈ{syl}" if i == stress_idx else syl
            for i, syl in enumerate(all_syllables)
        )

        return WordPhoneticHint(
            target_word=original_word.strip(".,!?;:\"'()[]"),
            morpheme_breakdown="-".join(all_syllables),
            primary_stress_syllable_idx=stress_idx,
            stress_reason="lexicon_root_fixed",
            phonetic_guide=ipa_guide,
            liaison_syllables=all_syllables if liaison_applied else None,
            source="inflected_lexicon",
        )

