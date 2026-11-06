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
from typing import List, Tuple

from backend.morphology.text_utils import tr_lower

# Türkçe fonolojik ünlü kümesi ('ğ' ünsüzdür)
VOWELS = set("aeıioöuüâîû")
BACK_VOWELS = set("aıouâû")
FRONT_VOWELS = set("eiöüî")


class TurkishSyllabifier:
    """
    Türkçe fonotaktik kurallarına göre deterministik heceleme motoru:
    - Sağdan sola ünlü-çekirdek (nucleus) analizi uygular.
    - V-V (sa-at), V-C-V (a-ra-ba), V-CC-V (kar-deş), V-CCC-V (türk-çe, kont-rol)
      yapılarını kural tabanlı olarak çözer.
    - 'spor', 'plan', 'tren' gibi yabancı kökenli başlangıç ünsüz öbeklerini korur.
    - Ünlüsüz kısaltmaları (km, tl) ve rakamları hata fırlatmadan tek parça döner.
    """

    @classmethod
    def syllabify(cls, word: str) -> List[str]:
        """Kelimeyi hecelerine ayırır ve hece dizisi döndürür."""
        if not word:
            return []
        res = cls.syllabify_with_offsets(word)
        return [syl for syl, _, _ in res]

    @classmethod
    def syllabify_with_offsets(cls, word: str) -> List[Tuple[str, int, int]]:
        """
        Kelimeyi hecelerine ayırır; her hece için (hece_metni, baslangic, bitis)
        karakter ofsetlerini döndürür.
        """
        clean = re.sub(r"[^a-zçğıöşüâîû]", "", tr_lower(word))
        if not clean:
            return [(word, 0, len(word))] if word else []

        vowel_indices = [i for i, ch in enumerate(clean) if ch in VOWELS]
        if not vowel_indices:
            # Ünlü içermeyen token (kısaltma, yabancı kod vb.)
            return [(clean, 0, len(clean))]

        if len(vowel_indices) == 1:
            # Tek heceli kelime (spor, tren, türk, ev vb.)
            return [(clean, 0, len(clean))]

        split_points: List[int] = []
        for idx in range(len(vowel_indices) - 1):
            v1 = vowel_indices[idx]
            v2 = vowel_indices[idx + 1]
            num_consonants = v2 - v1 - 1

            if num_consonants == 0:
                # İki ünlü yan yana (örn: sa-at, ka-atil, fi-il)
                split_points.append(v2)
            elif num_consonants == 1:
                # Tek ünsüz sonraki hecenin başına bağlanır (örn: a-ra-ba)
                split_points.append(v2 - 1)
            elif num_consonants == 2:
                # İki ünsüz ortadan ayrılır (örn: kar-deş, bar-dak)
                split_points.append(v2 - 1)
            else:
                # 3 veya daha fazla ünsüz: ilk ikisi solda, üçüncüsü sağda (örn: türk-çe, kont-rol)
                split_points.append(v2 - 1)

        syllables_with_offsets: List[Tuple[str, int, int]] = []
        start = 0
        for sp in split_points:
            syllables_with_offsets.append((clean[start:sp], start, sp))
            start = sp
        syllables_with_offsets.append((clean[start:], start, len(clean)))

        return syllables_with_offsets

