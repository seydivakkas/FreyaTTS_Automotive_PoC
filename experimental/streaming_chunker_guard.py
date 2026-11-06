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

import asyncio
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import re
import unicodedata
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple, Union

from backend.morphology.lexicon import load_freya_vocab
from backend.morphology.text_utils import normalize_apostrophes, tr_lower
from experimental.normalizer import normalize_text_for_tts

logger = logging.getLogger("streaming_chunker_guard")

# ============================================================================
# Sabitler ve Otomotiv Bölünmezlik Kümeleri (Ajan 1 - RT-03)
# ============================================================================
DEFAULT_VOCAB_PATH = Path("config/freya_vocab.json")

# Marka adları (Model kodu gelene kadar bölünmez)
KNOWN_AUTOMOTIVE_BRANDS: set[str] = {
    "peugeot", "renault", "bmw", "mercedes", "mercedes-benz", "volkswagen",
    "vw", "audi", "skoda", "škoda", "toyota", "fiat", "ford", "hyundai",
    "kia", "togg", "volvo", "opel", "seat", "cupra", "citroen", "citroën",
    "dacia", "nissan", "honda", "jeep", "land rover", "range rover", "porsche",
    "alfa romeo", "byd", "chery", "mg", "suzuki", "subaru", "mini", "tesla",
}

# Sayı arkasından gelen birimler (Para, motor, oran birimleri bölünmez)
ATOMIC_UNITS: set[str] = {
    "tl", "tl'dir", "tl'ye", "tl'nin", "tl'den", "lira", "liradır", "liraya",
    "türk lirası", "avro", "euro", "dolar", "tsi", "tdi", "dci", "tgdi",
    "ecoboost", "gdi", "hdi", "puretech", "motor", "litre", "kwh", "hp",
    "bg", "km", "km/s", "km/sa", "bin", "milyon", "ay", "yıl",
}


# ============================================================================
# 1. Telefona Özel LLM Çıktı Sanitizasyonu (Katman 2)
# ============================================================================
class TelephonyStreamSanitizer:
    """
    LLM'den canlı akan metinlerdeki Markdown biçimlendirmelerini, madde imlerini,
    URL'leri, emojileri ve parantez içi açıklamaları temizleyen kalkan.
    """

    RE_MARKDOWN_BOLD_ITALIC = re.compile(r"(\*\*|\*|__|_)(.*?)\1")
    RE_HEADERS = re.compile(r"^\s*#{1,6}\s+", re.MULTILINE)
    RE_BULLETS = re.compile(r"^\s*([-*+]|\d+\.)\s+", re.MULTILINE)
    RE_BACKTICKS = re.compile(r"`{1,3}(.*?)`{1,3}")
    RE_URLS = re.compile(r"https?://\S+|www\.\S+")
    RE_BRACKETS_NON_INTENT = re.compile(r"\[(?!KESİLDİ)(.*?)\]")
    RE_INTENT_TAG = re.compile(r"<intent:([a-z_]+)>", re.IGNORECASE)

    @classmethod
    def sanitize_text(cls, text: str, strip_edges: bool = True) -> tuple[str, Optional[str]]:
        """
        Metni telefonda seslendirmeye hazır hale getirir.
        Döndürür: (temizlenmiş_metin, varsa_niyet_etiketi)
        """
        if not text:
            return "", None

        detected_intent = None
        intent_match = cls.RE_INTENT_TAG.search(text)
        if intent_match:
            detected_intent = intent_match.group(1).lower()
            text = cls.RE_INTENT_TAG.sub("", text)

        # Markdown kalın/italik temizleme
        t = cls.RE_MARKDOWN_BOLD_ITALIC.sub(r"\2", text)
        # Başlık ve madde imlerini temizleme
        t = cls.RE_HEADERS.sub("", t)
        t = cls.RE_BULLETS.sub("", t)
        # Kod blokları
        t = cls.RE_BACKTICKS.sub(r"\1", t)
        # URL'ler
        t = cls.RE_URLS.sub("", t)
        # Parantez içi açıklamalar
        t = cls.RE_BRACKETS_NON_INTENT.sub(r"\1", t)

        # Emojileri ve ASCII dışı kontrol karakterlerini temizleme
        t = "".join(ch for ch in t if ord(ch) >= 32 or ch in "\n\t")

        # Çoklu boşlukları tekleştir
        t = re.sub(r"[ \t]+", " ", t)
        if strip_edges:
            t = t.strip()
        return t, detected_intent


# ============================================================================
# 2. Düşük Gecikmeli Akıllı Cümlecik Akış Bölücüsü (Ajan 1 - RT-03)
# ============================================================================
class AtomicTokenStreamingChunker:
    """
    LLM Token Akışını Dinleyen, İlk Cümlecik Hızını (TTFA <= 1.5 sn) Optimize Eden,
    Ancak Otomotiv Varlıklarını ve Fiyatları Asla Bölmeyen Akış Bölücüsü.

    Kurallar:
    1. İlk Cümlecik Hızı: İlk yan cümle 4-7 kelimede tamamlandığı anda senteze gönderilir.
    2. Sonraki Cümlecikler: 6-12 kelimelik doğal ritmik pencerelerde bölünür.
    3. Bölünmezlik Kuralı: "Peugeot 3008", "1.5 TSI", "1.250.000 TL", "C-SUV" gibi
       varlıklar asla iki ayrı cümlecik parçasına bölünmez; tamamlanana kadar tamponda tutulur.
    """

    def __init__(
        self,
        min_words_first_clause: int = 4,
        max_words_first_clause: int = 7,
        min_words_normal: int = 6,
        max_words_normal: int = 12,
        force_split_words: int = 15,
    ):
        self.min_words_first_clause = min_words_first_clause
        self.max_words_first_clause = max_words_first_clause
        self.min_words_normal = min_words_normal
        self.max_words_normal = max_words_normal
        self.force_split_words = force_split_words

        self._buffer: str = ""
        self.emitted_chunks_count: int = 0
        self.active_intent: Optional[str] = None

    def reset(self) -> None:
        """Yeni bir konuşma sırası için durumu sıfırlar."""
        self._buffer = ""
        self.emitted_chunks_count = 0
        self.active_intent = None

    @staticmethod
    def is_atomic_pending(words: list[str]) -> bool:
        """
        Son kelimenin bölünmez bir otomotiv varlığının başlangıcı olup olmadığını kontrol eder.
        True dönerse cümlecik bölme işlemi bekletilir.
        """
        if not words:
            return False

        last_raw = words[-1].strip()
        last_clean = tr_lower(re.sub(r"[^\w-]", "", last_raw))

        # Terminal noktalama varsa (.!?), cümle bitmiştir, atomik varlık beklenmez
        if re.search(r"[.!?]$", last_raw):
            return False

        # 1. Bilinen otomotiv markası (Model kodu henüz gelmemiş olabilir: "Peugeot ...")
        if last_clean in KNOWN_AUTOMOTIVE_BRANDS:
            return True

        # 2. Sayı veya fiyat başlangıcı (Birim henüz gelmemiş olabilir: "1.850.000 ...", "1.5 ...")
        if re.search(r"^\d+[\d\.,]*$", last_raw.rstrip(".,;!?")):
            return True

        # 3. Tire ile biten bileşik parça ("C-", "DM-")
        if last_clean.endswith("-"):
            return True

        return False

    def feed_token(self, token: str) -> list[str]:
        """
        Gelen her token parçasını tampona ekler ve bölünme şartı sağlandıysa
        tamamlanan cümlecikleri liste olarak döndürür.
        """
        if not token:
            return []

        # Niyet etiketi varsa yakala
        if "<intent:" in token or "<intent:" in self._buffer:
            combined = self._buffer + token
            sanitized, intent = TelephonyStreamSanitizer.sanitize_text(combined, strip_edges=False)
            if intent:
                self.active_intent = intent
            self._buffer = sanitized
        else:
            sanitized, _ = TelephonyStreamSanitizer.sanitize_text(token, strip_edges=False)
            self._buffer += sanitized

        # Boşluklara göre kelimeleri ayrıştır
        words = self._buffer.split()
        if not words:
            return []

        # Eğer son kelime atomik varlık bekliyorsa bölünme yapma
        if self.is_atomic_pending(words):
            return []

        # Hedef kelime sınırları
        is_first = (self.emitted_chunks_count == 0)
        min_words = self.min_words_first_clause if is_first else self.min_words_normal

        emitted: list[str] = []

        # Kelimeleri baştan itibaren tara
        i = 0
        while i < len(words):
            count = i + 1
            w = words[i]
            is_terminal = bool(re.search(r"[.!?;\n]$", w))
            is_comma = bool(re.search(r",\s*$", w))

            can_split = False
            if count >= min_words and (is_terminal or is_comma):
                can_split = True
            elif count >= self.force_split_words:
                can_split = True

            if can_split and not self.is_atomic_pending(words[:count]):
                clause = " ".join(words[:count]).strip()
                emitted.append(clause)
                self.emitted_chunks_count += 1
                words = words[count:]
                i = 0
                min_words = self.min_words_normal
            else:
                i += 1

        # Kalan kelimeleri tampona geri yaz
        if emitted:
            self._buffer = " ".join(words)
            if self._buffer:
                self._buffer += " "

        return emitted

    def flush(self) -> list[str]:
        """Akış tamamlandığında tamponda kalan son metni döner."""
        remaining = self._buffer.strip()
        self._buffer = ""
        if remaining:
            self.emitted_chunks_count += 1
            return [remaining]
        return []

    async def stream_chunks(
        self,
        token_stream: AsyncGenerator[str, None],
    ) -> AsyncGenerator[str, None]:
        """Asenkron token akışını tüketir ve hazır cümlecikleri yield eder."""
        self.reset()
        async for token in token_stream:
            chunks = self.feed_token(token)
            for c in chunks:
                yield c
        for c in self.flush():
            yield c


# ============================================================================
# 3. FreyaTTS İçsel Normalizer Baypas Kalkanı (Anti-Double Normalization Guard)
# ============================================================================
class AntiDoubleNormalizationGuard:
    """
    Ajan 1'in Ürettiği Konuşma Metinlerini (Spoken Text) FreyaTTS'nin İçsel
    `clean_text` Normalizer'ının Bozmasını Önleyen Baypas ve Doğrulama Kalkanı.

    Özellikler:
    1. skip_internal_normalizer=True bayrağıyla FreyaTTS çıkarımına doğrudan iletilir.
    2. combining dot above (\u0307) ve sıfır genişlikli baytları temizler.
    3. freya_vocab.json (92 karakter) uyumluluğunu %100 doğrular.
    4. Söylenmemiş rakam (0-9) veya döviz sembolü (₺, $, €) kalmadığını teyit eder.
    """

    def __init__(self, vocab_path: Path = DEFAULT_VOCAB_PATH):
        raw_vocab = load_freya_vocab(vocab_path)
        if isinstance(raw_vocab, dict):
            self.vocab_chars = {ch for ch in raw_vocab.keys() if len(ch) == 1}
        else:
            self.vocab_chars = {ch for ch in raw_vocab if len(ch) == 1}

    @staticmethod
    def strip_unicode_artifacts(text: str) -> str:
        """Python .lower() kaynaklı combining dot above (\\u0307) vb. yapay ekleri temizler."""
        if not text:
            return ""
        # 1. Combining Dot Above (\u0307) temizliği
        cleaned = text.replace("\u0307", "")
        # 2. Sıfır genişlikli boşluk ve BOM temizliği
        cleaned = cleaned.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
        # 3. Unicode NFC normalizasyonu
        cleaned = unicodedata.normalize("NFC", cleaned)
        # 4. Kesme işaretlerini tek tırnak yap
        cleaned = normalize_apostrophes(cleaned)
        return cleaned

    def validate_spoken_text(self, text: str) -> tuple[bool, list[str]]:
        """
        Metnin model sözlüğü (92 karakter) ile tam uyumlu olduğunu ve
        çifte normalizasyona ihtiyaç duymadığını doğrular.
        Döndürür: (geçerli_mi, geçersiz_karakterler_listesi)
        """
        cleaned = self.strip_unicode_artifacts(text)
        invalid_chars = [ch for ch in cleaned if ch not in self.vocab_chars and ch != "\n"]
        is_valid = (len(invalid_chars) == 0)
        return is_valid, invalid_chars

    def is_double_normalization_safe(self, text: str) -> tuple[bool, list[str]]:
        """
        Metinde okunmamış rakam (0-9) veya dönüştürülmemiş sembol kalıp kalmadığını denetler.
        """
        issues: list[str] = []
        if re.search(r"\d", text):
            issues.append("Metinde okunmamış ham rakam (0-9) bulundu.")
        if re.search(r"[₺$€%]", text):
            issues.append("Metinde dönüştürülmemiş sembol (₺, $, €, %) bulundu.")
        return (len(issues) == 0), issues

    def sanitize_for_char_embedding(self, text: str) -> tuple[str, bool]:
        """
        Metni FreyaTTS karakter indeksleyiciye (`char_to_id`) girmeye hazır hale getirir.
        Döndürür: (nihai_temiz_metin, skip_internal_normalizer=True)
        """
        cleaned = self.strip_unicode_artifacts(text)
        # Fazla boşlukları temizle
        cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
        return cleaned, True


# Global Tekil Örnekler
stream_sanitizer = TelephonyStreamSanitizer()
atomic_chunker = AtomicTokenStreamingChunker()
anti_double_guard = AntiDoubleNormalizationGuard()

__all__ = [
    "DEFAULT_VOCAB_PATH",
    "KNOWN_AUTOMOTIVE_BRANDS",
    "ATOMIC_UNITS",
    "TelephonyStreamSanitizer",
    "AtomicTokenStreamingChunker",
    "AntiDoubleNormalizationGuard",
    "stream_sanitizer",
    "atomic_chunker",
    "anti_double_guard",
]
