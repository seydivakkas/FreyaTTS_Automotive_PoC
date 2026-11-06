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
from typing import Dict, List, Set, Tuple

from backend.morphology.text_utils import tr_lower

# Ayrı yazılan edat, bağlaç ve soru partikülleri
STANDALONE_CLITICS: Set[str] = {
    "de", "da", "ki",
    "mi", "mı", "mu", "mü",
    "misin", "mısın", "musun", "müsün",
    "miyiz", "mıyız", "muyuz", "müyüz",
    "miydi", "mıydı", "muydu", "müydü",
    "miş", "mış", "muş", "müş",
}

TRAILING_PUNCTUATION = set(".,!?;:…")


class CliticLookaheadAnalyzer:
    """
    Cümle içi ayrı yazılan edat/bağlaç kilitleri ve mikro duraksama enjektörü:
    1. Kural 1: Clitic'ten bir önceki kelimenin vurgusunu kilitler ve emphasis_targets listesine alır.
    2. Kural 2: Clitic'ten sonra mikro duraksama (varsayılan 35 ms) ekler.
    3. Kural 3 (Çift Duraksama Önleme): Clitic'in hemen arkasında noktalama işareti varsa
       (örn: 'mi?', 'de,') enjeksiyon yapılmaz; noktalama duraksaması yeterlidir.
    4. Kural 4: Soru partikülü tonlaması mevcut noktalama mekanizmasına bırakılır.
    """

    def __init__(self, default_pause_ms: int = 35):
        # 20-60 ms sınırında güvenli kenetleme
        self.pause_ms = max(20, min(60, default_pause_ms))

    def analyze_tokens(
        self, tokens: List[str]
    ) -> Tuple[List[str], Dict[int, int], Set[int]]:
        """
        Token listesini tarar.
        Döner:
        - emphasis_targets: Vurgulanacak hedef kelimeler listesi
        - pause_injections: {token_index: ms} haritası
        - clitic_indices: Clitic olan tokenların indeks kümesi (vurgu almayacaklar)
        """
        emphasis_targets: List[str] = []
        pause_injections: Dict[int, int] = {}
        clitic_indices: Set[int] = set()

        for idx, token in enumerate(tokens):
            clean = re.sub(r"[^a-zçğıöşüâîû]", "", tr_lower(token))
            if not clean:
                continue

            if clean in STANDALONE_CLITICS:
                clitic_indices.add(idx)

                # Bir önceki kelime varsa vurgu hedefine ekle
                if idx > 0:
                    prev_raw = tokens[idx - 1].strip(".,!?;:\"'()[]")
                    if prev_raw and prev_raw not in emphasis_targets:
                        emphasis_targets.append(prev_raw)

                # Çift duraksama önleme: Tokenın kendisinde veya sonrasında noktalama var mı?
                has_trailing_punct = bool(token and token[-1] in TRAILING_PUNCTUATION)
                if not has_trailing_punct and (idx + 1 < len(tokens)):
                    pause_injections[idx] = self.pause_ms

        return emphasis_targets, pause_injections, clitic_indices

