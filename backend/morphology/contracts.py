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
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from backend.morphology.syllabifier import TurkishSyllabifier
from backend.morphology.text_utils import tr_lower


class LexiconEntry(BaseModel):
    """Yabancı terimler, kısaltmalar ve özel otomotiv marka kodları için sözlük şeması."""
    canonical_stem: str
    spoken: str
    phonetic_syllables: List[str] = Field(default_factory=list)
    stress_syllable_idx: int = 0
    category: str = "automotive"
    ends_with_consonant: bool = True
    last_vowel_backness: str = "back"  # "back" (kalın: a,ı,o,u) | "front" (ince: e,i,ö,ü)


class WordPhoneticHint(BaseModel):
    """Tekil kelimenin hece ayrımı, vurgu indeksi ve ulama rehberi."""
    target_word: str
    morpheme_breakdown: Optional[str] = None          # Örn: "gö-rüş-tü-rü-le-me-di"
    primary_stress_syllable_idx: int = 0              # 0-tabanlı vurgu hecesi indeksi
    stress_reason: str = "default_final"              # "exception" | "suffix:-me" | "clitic_locked" | "default_final"
    phonetic_guide: Optional[str] = None              # Telemetri / teşhis için IPA vurgulu gösterim (örn: "gö-rüş-tü-rü-ˈle-me-di")
    liaison_syllables: Optional[List[str]] = None     # Ulama/köprüleme heceleri (örn: ["e", "ko", "bus", "tun"])
    source: str = "rule"                              # "rule" | "lexicon" | "exception" | "fallback"


class NormalizedUtterance(BaseModel):
    """
    Sentezlenecek normalleştirilmiş metin parçası (chunk).
    Değişmez kural: PreChecker bu nesnenin chunk_text alanını ASLA değiştiremez.
    """
    model_config = ConfigDict(frozen=True)            # Çift normalizasyon ve mutasyon koruma kilidi
    utterance_id: str
    chunk_id: str
    chunk_text: str
    boundary_split_index: Optional[int] = None


class ExtendedProsodyPlan(BaseModel):
    """
    MorphologicalPreChecker tarafından üretilen yan kanal prosodi ve vurgu planı.
    Model giriş metnini bozmadan ek telemetri, mikro duraksamalar ve vurgu hedefleri sağlar.
    """
    chunk_id: str
    emphasis_targets: List[str] = Field(default_factory=list)
    pronunciation_hints: List[WordPhoneticHint] = Field(default_factory=list)
    pause_injections_ms: Dict[int, int] = Field(default_factory=dict)  # token_index -> ms
    warnings: List[str] = Field(default_factory=list)


def generate_hint_for_failed_word(word: str) -> WordPhoneticHint:
    """
    Kalite Kapısı (ASR / Quality Gate) bir kelimede okuma hatası yakaladığında
    otomatik açık heceleme ve vurgu rehberi üretir.
    Üretilen hecelerde yalnızca model sözlüğünde desteklenen karakterler kullanılır.
    """
    clean = re.sub(r"[^a-zçğıöşüâîû]", "", tr_lower(word))
    syllables = TurkishSyllabifier.syllabify(clean) if clean else [word]
    if not syllables:
        syllables = [clean or word]

    stress_idx = len(syllables) - 1
    # IPA vurgu işareti telemetri amaçlı phonetic_guide alanına yazılır
    ipa_guide = "-".join(
        f"ˈ{syl}" if i == stress_idx else syl
        for i, syl in enumerate(syllables)
    )

    return WordPhoneticHint(
        target_word=word,
        morpheme_breakdown="-".join(syllables),
        primary_stress_syllable_idx=stress_idx,
        stress_reason="default_final",
        phonetic_guide=ipa_guide,
        source="fallback_asr_gate",
    )

