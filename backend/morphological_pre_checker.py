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

from backend.config import settings
from backend.morphology.clitics import CliticLookaheadAnalyzer, STANDALONE_CLITICS
from backend.morphology.contracts import (
    ExtendedProsodyPlan,
    LexiconEntry,
    NormalizedUtterance,
    WordPhoneticHint,
    generate_hint_for_failed_word as _contracts_generate_hint,
)
from backend.morphology.inflected_matcher import InflectedLexiconMatcher
from backend.morphology.lexicon import get_domain_lexicon, get_stress_exceptions
from backend.morphology.stress_engine import MorphologicalStressEngine
from backend.morphology.text_utils import tr_lower


class MorphologicalPreChecker:
    """
    MorphologicalPreChecker (Faz 2 Ön-Denetim Cephesi):
    - NormalizedUtterance.chunk_text'i ASLA değiştirmez.
    - Yabancı marka/kök + Türkçe ek bileşimlerini ve hece ulamasını (liaison) çözer.
    - Morfolojik istisnai ekleri (-mA, -ken, -ki, -dIr, -lA, -cA) ve kalıplaşmış kelimeleri analiz eder.
    - Ayrı yazılan clitic'leri (de/da, ki, mi) yakalayıp 35 ms mikro duraksama üretir.
    - Hot path'te sıfır I/O ve LRU önbellekleme ile < 1 ms hedefi sağlar.
    - MORPH_PRECHECK_ENABLED bayrağı ile dinamik olarak devre dışı bırakılabilir.
    """

    def __init__(
        self,
        domain_lexicon: Optional[Dict[str, LexiconEntry]] = None,
        stress_exceptions: Optional[Dict[str, int]] = None,
        pause_ms: int = 35,
        enabled: Optional[bool] = None,
    ):
        self.enabled = (
            enabled
            if enabled is not None
            else getattr(settings, "morph_precheck_enabled", True)
        )
        self.lexicon = domain_lexicon if domain_lexicon is not None else get_domain_lexicon()
        self.stress_exceptions = (
            stress_exceptions if stress_exceptions is not None else get_stress_exceptions()
        )

        self.matcher = InflectedLexiconMatcher(self.lexicon)
        self.stress_engine = MorphologicalStressEngine(self.stress_exceptions)
        self.clitic_analyzer = CliticLookaheadAnalyzer(default_pause_ms=pause_ms)

        # Kelime bazlı hızlı önbellek (Hot path performansı < 0.2 ms)
        self._word_cache: Dict[str, Optional[WordPhoneticHint]] = {}

    def analyze(self, utterance: NormalizedUtterance) -> ExtendedProsodyPlan:
        """
        Sentez öncesi koruyucu analiz:
        NormalizedUtterance nesnesini inceler ve ExtendedProsodyPlan döner.
        chunk_text ASLA değiştirilmez.
        """
        plan = ExtendedProsodyPlan(chunk_id=utterance.chunk_id)
        if not self.enabled or not utterance.chunk_text:
            return plan

        tokens = utterance.chunk_text.split()
        if not tokens:
            return plan

        # 1. Clitic Lookahead analizi (Vurgu hedefleri, mikro duraksamalar, clitic indeksleri)
        clitic_emphasis, pause_injections, clitic_indices = (
            self.clitic_analyzer.analyze_tokens(tokens)
        )
        plan.emphasis_targets.extend(clitic_emphasis)
        plan.pause_injections_ms.update(pause_injections)

        # 2. Token bazlı morfolojik ve yabancı kök analizi
        for i, token in enumerate(tokens):
            if i in clitic_indices:
                continue

            clean_token = re.sub(r"[^a-zçğıöşüâîû]", "", tr_lower(token))
            if not clean_token:
                continue

            next_is_clitic = (i + 1 < len(tokens)) and (
                re.sub(r"[^a-zçğıöşüâîû]", "", tr_lower(tokens[i + 1])) in STANDALONE_CLITICS
            )

            hint = self.analyze_word(token, force_stress_before_clitic=next_is_clitic)
            if hint is not None:
                plan.pronunciation_hints.append(hint)
                if hint.target_word not in plan.emphasis_targets:
                    plan.emphasis_targets.append(hint.target_word)

        return plan

    def build_initial_prosody(self, utterance: NormalizedUtterance) -> ExtendedProsodyPlan:
        """Kullanıcı şartnamesi ile birebir uyumlu takma ad."""
        return self.analyze(utterance)

    def analyze_word(
        self, raw_word: str, force_stress_before_clitic: bool = False
    ) -> Optional[WordPhoneticHint]:
        """
        Tekil kelimeyi analiz eder:
        1. Yabancı / Domain sözlüğü + çekim eki eşleşmesi
        2. Kalıplaşmış istisnalar & morfolojik vurgu çeken ekler
        """
        cache_key = f"{raw_word}:{force_stress_before_clitic}"
        if cache_key in self._word_cache:
            return self._word_cache[cache_key]

        # 1. Yabancı sözlük eşleşmesi
        hint = self.matcher.match(raw_word)
        if hint is not None:
            self._word_cache[cache_key] = hint
            return hint

        # 2. Morfolojik vurgu analizi
        hint = self.stress_engine.analyze_word(
            raw_word, force_stress_before_clitic=force_stress_before_clitic
        )
        self._word_cache[cache_key] = hint
        return hint

    def expand_inflected_words(self, text: str) -> str:
        """
        Normalizer aşaması için yardımcı metot:
        NormalizedUtterance oluşmadan ÖNCE çekimli yabancı terimlerin
        okunuşlarını genişletir.
        Örn: 'EcoBoost'un paketi' -> 'ekobustun paketi'
        """
        if not self.enabled or not text:
            return text

        tokens = text.split()
        expanded: List[str] = []
        for tok in tokens:
            # Noktalama ayıkla
            lead = ""
            trail = ""
            m_lead = re.match(r"^([^\w]+)", tok)
            if m_lead:
                lead = m_lead.group(1)
            m_trail = re.search(r"([^\w]+)$", tok)
            if m_trail:
                trail = m_trail.group(1)

            core = tok[len(lead): len(tok) - len(trail)] if trail else tok[len(lead):]
            spoken = self.matcher.expand_spoken_token(core)
            if spoken:
                expanded.append(f"{lead}{spoken}{trail}")
            else:
                expanded.append(tok)

        return " ".join(expanded)

    def generate_hint_for_failed_word(self, word: str) -> WordPhoneticHint:
        """Kalite kapısı (ASR) geri bildirimi için açık heceleme ipucu."""
        hint = self.analyze_word(word, force_stress_before_clitic=True)
        if hint is not None:
            return hint
        return _contracts_generate_hint(word)


# Singleton örneği
morphological_pre_checker = MorphologicalPreChecker()

