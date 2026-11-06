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

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Set

from backend.morphology.contracts import LexiconEntry
from backend.morphology.syllabifier import TurkishSyllabifier, VOWELS, BACK_VOWELS
from backend.morphology.text_utils import tr_lower
from backend.normalizer_rules import BASE_AUTOMOTIVE_LEXICON

logger = logging.getLogger("morphology_lexicon")

_CACHED_DOMAIN_LEXICON: Optional[Dict[str, LexiconEntry]] = None
_CACHED_STRESS_EXCEPTIONS: Optional[Dict[str, int]] = None
_FREYA_VOCAB: Optional[Set[str]] = None


def load_freya_vocab(path: Path | str = "config/freya_vocab.json") -> Set[str]:
    """Modelin 92 karakterlik sözlüğünü yükler."""
    global _FREYA_VOCAB
    if _FREYA_VOCAB is not None:
        return _FREYA_VOCAB

    p = Path(path)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            _FREYA_VOCAB = set(data.keys())
            return _FREYA_VOCAB
        except Exception as e:
            logger.warning(f"freya_vocab.json yüklenirken hata: {e}")

    # Varsayılan 92 karakterlik güvenli yedek sözlük
    _FREYA_VOCAB = {
        "<FILL>", "<UNK>", " ", "%", "&", "'", "+", ",", "-", ".", "/",
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ":", ";", ">", "?",
        "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N",
        "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
        "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n",
        "o", "p", "r", "s", "t", "u", "v", "w", "x", "y", "z",
        "Ç", "Ö", "Ü", "á", "â", "ç", "ö", "ú", "ü", "ğ", "İ", "ı", "Ş", "ş", "’", "€"
    }
    return _FREYA_VOCAB


def load_stress_exceptions(path: Path | str = "config/stress_exceptions.json") -> Dict[str, int]:
    """Kalıplaşmış 1. hece vurgusu alan istisnai kelimeler sözlüğünü yükler."""
    global _CACHED_STRESS_EXCEPTIONS
    if _CACHED_STRESS_EXCEPTIONS is not None:
        return dict(_CACHED_STRESS_EXCEPTIONS)

    p = Path(path)
    exceptions: Dict[str, int] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            exceptions = {tr_lower(k): int(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"stress_exceptions.json yüklenirken hata: {e}")

    if not exceptions:
        exceptions = {
            "halbuki": 0,
            "oysaki": 0,
            "mademki": 0,
            "belki": 0,
            "çünkü": 0,
            "sanki": 0,
            "yoksa": 0,
            "ancak": 0,
            "şimdi": 0,
            "henüz": 0,
        }

    _CACHED_STRESS_EXCEPTIONS = exceptions
    return dict(_CACHED_STRESS_EXCEPTIONS)


def load_domain_lexicon(
    json_path: Path | str = "config/automotive_foreign_lexicon.json",
    vocab_path: Path | str = "config/freya_vocab.json",
) -> Dict[str, LexiconEntry]:
    """
    Otomotiv alan sözlüğünü yükler:
    BASE_AUTOMOTIVE_LEXICON + automotive_foreign_lexicon.json birleştirilir.
    Çakışmalarda JSON girdileri önceliklidir.
    Tüm 'spoken' girdileri freya_vocab.json karakter kümesine karşı doğrulanır.
    """
    global _CACHED_DOMAIN_LEXICON
    if _CACHED_DOMAIN_LEXICON is not None:
        return dict(_CACHED_DOMAIN_LEXICON)

    vocab = load_freya_vocab(vocab_path)
    lexicon: Dict[str, LexiconEntry] = {}

    # 1. Base Otomotiv Sözlüğü (Normalizer kurallarından)
    for stem, raw_spoken in BASE_AUTOMOTIVE_LEXICON.items():
        clean_stem = tr_lower(stem)
        spoken_lower = tr_lower(raw_spoken)
        # Karakter doğrulaması
        invalid_chars = set(spoken_lower.replace("Ğ", "ğ")) - vocab
        if invalid_chars:
            logger.warning(f"Base sözlükteki '{stem}' desteklenmeyen karakterler içeriyor ({invalid_chars}), atlanıyor.")
            continue

        clean_spoken = spoken_lower.replace(" ", "")
        syllables = TurkishSyllabifier.syllabify(clean_spoken) or [clean_spoken]
        last_ch = clean_spoken[-1] if clean_spoken else "a"
        ends_with_c = last_ch not in VOWELS

        # Son ünlü kalınlığı
        last_vowel = "e"
        for ch in reversed(clean_spoken):
            if ch in VOWELS:
                last_vowel = ch
                break
        backness = "back" if last_vowel in BACK_VOWELS else "front"

        lexicon[clean_stem] = LexiconEntry(
            canonical_stem=clean_stem,
            spoken=spoken_lower,
            phonetic_syllables=syllables,
            stress_syllable_idx=max(0, len(syllables) - 1),
            category="base_automotive",
            ends_with_consonant=ends_with_c,
            last_vowel_backness=backness,
        )

    # 2. Özel Yabancı Terim ve Paket Sözlüğü (JSON)
    jp = Path(json_path)
    if jp.exists():
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
            for key, val in data.items():
                clean_key = tr_lower(key)
                spoken = tr_lower(val.get("spoken", ""))
                invalid_chars = set(spoken) - vocab
                if invalid_chars:
                    logger.warning(
                        f"JSON sözlükteki '{key}' desteklenmeyen karakterler içeriyor ({invalid_chars}), atlanıyor."
                    )
                    continue

                syllables = val.get("phonetic_syllables") or TurkishSyllabifier.syllabify(spoken.replace(" ", ""))
                stress_idx = int(val.get("stress_syllable_idx", max(0, len(syllables) - 1)))
                category = val.get("category", "foreign_term")
                ends_with_c = bool(val.get("ends_with_consonant", syllables[-1][-1] not in VOWELS if syllables else True))
                backness = val.get("last_vowel_backness", "back")

                lexicon[clean_key] = LexiconEntry(
                    canonical_stem=clean_key,
                    spoken=spoken,
                    phonetic_syllables=syllables,
                    stress_syllable_idx=stress_idx,
                    category=category,
                    ends_with_consonant=ends_with_c,
                    last_vowel_backness=backness,
                )
        except Exception as e:
            logger.warning(f"automotive_foreign_lexicon.json yüklenirken hata: {e}")

    _CACHED_DOMAIN_LEXICON = lexicon
    return dict(_CACHED_DOMAIN_LEXICON)


def get_domain_lexicon() -> Dict[str, LexiconEntry]:
    """Önbellekteki domain sözlüğünü döndürür."""
    return load_domain_lexicon()


def get_stress_exceptions() -> Dict[str, int]:
    """Önbellekteki kalıplaşmış vurgu istisnalarını döndürür."""
    return load_stress_exceptions()

