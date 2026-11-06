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
import unicodedata

# Unicode Güvenli Türkçe Dönüşüm Eşlemeleri
TR_LOWER_MAP = str.maketrans(
    "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZÂÎÛ",
    "abcçdefgğhıijklmnoöprsştuüvyzâîû",
)

TR_UPPER_MAP = str.maketrans(
    "abcçdefgğhıijklmnoöprsştuüvyzâîû",
    "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZÂÎÛ",
)

APOSTROPHE_PATTERN = re.compile(r"[’‘ʼ´`]")


def tr_lower(text: str) -> str:
    """
    Unicode güvenli Türkçe küçük harfe dönüştürücü.
    Standart Python .lower() fonksiyonunun 'İ' -> 'i\\u0307' (combining dot above)
    çift karakter üretme ve FreyaTTS sözlüğünü bozma hatasını kesin olarak önler.
    """
    if not text:
        return ""
    # 1. 'İ' ve 'I' harflerini Türkçeye uygun dönüştür
    t = text.replace("İ", "i").replace("I", "ı")
    # 2. Genel Türkçe karakter tablosu üzerinden çevir
    t = t.translate(TR_LOWER_MAP).lower()
    # 3. Olası combining dot above (U+0307) kalıntılarını temizle
    t = t.replace("\u0307", "")
    # 4. NFC Standart Kanonik Birleştirme uygula
    return unicodedata.normalize("NFC", t)


def tr_upper(text: str) -> str:
    """
    Unicode güvenli Türkçe büyük harfe dönüştürücü.
    'i' -> 'İ', 'ı' -> 'I' dönüşümünü garanti eder.
    """
    if not text:
        return ""
    t = text.replace("i", "İ").replace("ı", "I")
    t = t.translate(TR_UPPER_MAP).upper()
    return unicodedata.normalize("NFC", t)


def normalize_apostrophes(text: str) -> str:
    """
    Tüm kesme ve tırnak varyantlarını standart tek tırnak/kesme karakterine (') dönüştürür.
    Böylece 'EcoBoost’un' veya 'SUV`nin' gibi girdiler tekdüze işlenir.
    """
    if not text:
        return ""
    return APOSTROPHE_PATTERN.sub("'", text)

