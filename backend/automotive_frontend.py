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
import math
from pathlib import Path
import re
import threading
from typing import Any, Dict, List, Set, Tuple

import numpy as np
from scipy import signal

from backend.normalizer_rules import (
    harmonize_suffix,
    normalize_automotive_turkish,
    spell_tr_int,
    get_lexicon,
)

logger = logging.getLogger("automotive_frontend")

# 48 kHz -> 8 kHz Telefon Parametreleri
DEFAULT_SR_IN = 48000
DEFAULT_SR_OUT = 8000
COMFORT_NOISE_DBFS = -58.0
COMFORT_NOISE_RMS = 10.0 ** (COMFORT_NOISE_DBFS / 20.0)  # ~0.0012589

# Türkçe Bağlaçlar (Prozodik Yumuşak Bölme İçin)
TURKISH_CONJUNCTIONS = [
    "veya",
    "ya da",
    "ancak",
    "fakat",
    "çünkü",
    "oysa",
    "lakin",
    "halbuki",
    "dolayısıyla",
    "ayrıca",
    "buna rağmen",
    "zira",
    "ve",
    "ile",
    "hem",
]

# Sayı ve Terim Kelimeleri (Bölünmemesi Gereken Korunan Öbekler)
NUMBER_WORDS = set(
    "sıfır bir iki üç dört beş altı yedi sekiz dokuz on yirmi otuz kırk elli "
    "altmış yetmiş seksen doksan yüz bin milyon milyar trilyon nokta virgül".split()
)


def load_freya_vocab() -> Set[str]:
    """Modelin 92 sembollü karakter sözlüğünü yükler."""
    candidates = [
        Path("config/freya_vocab.json"),
        Path("vendor/FreyaTTS/freyatts/char_vocab.json"),
        Path("data/a01yt/freya_char_vocab.json"),
    ]
    for p in candidates:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return set(data.keys())
            except Exception:
                pass

    # 92 Standart Karakter Sözlüğü (Yedek)
    return {
        "<FILL>", "<UNK>", " ", "%", "&", "'", "+", ",", "-", ".", "/",
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ":", ";", ">", "?",
        "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N",
        "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
        "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n",
        "o", "p", "r", "s", "t", "u", "v", "w", "x", "y", "z",
        "Ç", "Ö", "Ü", "á", "â", "ç", "ö", "ú", "ü", "ğ", "İ", "ı", "Ş", "ş", "’", "€"
    }


class AutomotiveTextNormalizer:
    """
    Otomotiv Telaffuz Sözlüğü, Ek Uyumlaması ve <UNK> Güvenlik Ağı:
    - Yabancı markaları (Volkswagen -> 'Folksvagen', Qashqai -> 'Kaşkai'),
      motor hacimlerini (1.5 TSI -> 'bir nokta beş te se i'),
      noktasız fiyatları (1250000 ₺ -> 'bir milyon iki yüz elli bin Türk lirası'),
      saat eklerini (14:30'da -> 'on dört otuzda') ses uyumuna göre açar.
    - Modelin 92 sembollü sözlüğünde yer almayan q, ₺, !, $, (, ) karakterlerini
      temizleyerek akustik cızırtı ve halüsinasyonları önler.
    """

    def __init__(self, vocab: Set[str] | None = None):
        self.vocab = vocab or load_freya_vocab()
        self._lock = threading.Lock()

    def normalize(self, text: str) -> str:
        """Kapsamlı otomotiv metin normalizasyonu uygular."""
        if not text or not text.strip():
            return ""

        t = text.strip()

        # 1. Saat formatları ve ses uyumlu ekler (14:30'da -> on dört otuzda, 15:00'te -> on beşte)
        def _replace_time(m: re.Match) -> str:
            prefix = m.group("prefix") or ""
            hh = int(m.group("h"))
            mm = int(m.group("m"))
            suf = m.group("suf")
            spoken = spell_tr_int(hh) if mm == 0 else f"{spell_tr_int(hh)} {spell_tr_int(mm)}"
            if suf:
                spoken = harmonize_suffix(spoken, suf)
            return f"{prefix}{spoken}"

        t = re.sub(
            r"(?P<prefix>(?:saat|yarın|bugün|sabah|akşam)\s+)?\b(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?\b",
            _replace_time,
            t,
            flags=re.IGNORECASE,
        )

        # 2. Noktasız ve noktalı para birimleri (1250000 ₺ -> bir milyon iki yüz elli bin Türk lirası)
        def _replace_currency(m: re.Match) -> str:
            int_val = int(m.group("int").replace(".", ""))
            frac = m.group("frac")
            suf = m.group("suf")
            if frac and int(frac) > 0:
                spoken = f"{spell_tr_int(int_val)} lira {spell_tr_int(int(frac))} kuruş"
            else:
                spoken = f"{spell_tr_int(int_val)} Türk lirası"
            if suf:
                spoken = harmonize_suffix(spoken, suf)
            return spoken

        t = re.sub(
            r"\b(?P<int>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<frac>\d{1,2}))?\s*(?:TL|₺|Türk\s+[Ll]irası)(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?",
            _replace_currency,
            t,
            flags=re.IGNORECASE,
        )

        # 3. Motor hacmi ve şanzıman kombinasyonları (1.5 TSI -> bir nokta beş te se i)
        def _replace_engine(m: re.Match) -> str:
            maj = spell_tr_int(int(m.group("maj")))
            mi = spell_tr_int(int(m.group("min")))
            raw_rest = m.group("rest")
            suf = m.group("suf")
            lex = get_lexicon()
            rest_spoken = lex.get(raw_rest.lower(), raw_rest)
            engine_str = f"{maj} nokta {mi} {rest_spoken}"
            if suf:
                engine_str = harmonize_suffix(engine_str, suf)
            return engine_str

        t = re.sub(
            r"\b(?P<maj>[0-6])\.(?P<min>[0-9])\s+(?P<rest>(?:TSI|TDI|TFSI|dCi|BlueHDi|HDi|TCe|MultiJet|PureTech|EcoTSI|e-Power|e-Tech|Hybrid|L|litre)\b)(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?",
            _replace_engine,
            t,
            flags=re.IGNORECASE,
        )

        # 4. Genel normalizasyon kuralları ve otomotiv sözlüğü
        t = normalize_automotive_turkish(t)

        # 4.5. Çekimli Yabancı Terimlerin Genişletilmesi (Liaison & Ulama)
        from backend.config import settings
        if getattr(settings, "morph_precheck_enabled", True):
            try:
                from backend.morphological_pre_checker import morphological_pre_checker
                t = morphological_pre_checker.expand_inflected_words(t)
            except Exception as e:
                logger.warning(f"expand_inflected_words hatası: {e}")

        # 5. <UNK> Güvenlik Ağı temizliği
        t = self.clean_unk_characters(t)
        return t

    def clean_unk_characters(self, text: str) -> str:
        """
        Model sözlüğünde (char_vocab.json) yer almayan q, ₺, !, $, (, ) gibi
        karakterleri temizler veya ses eşdeğerlerine dönüştürür.
        """
        t = text
        # Ses eşdeğeri dönüşümleri
        t = t.replace("₺", " Türk lirası ").replace("$", " dolar ").replace("€", " avro ")
        t = t.replace("!", ".").replace("?", "?")
        t = t.replace("q", "k").replace("Q", "K")
        t = t.replace("w", "v").replace("W", "V")
        t = t.replace("x", "ks").replace("X", "Ks")
        t = t.replace("Ğ", "ğ")  # Vocab'da sadece küçük ğ var

        # Parantez ve kesme/tırnak işaretlerini hafif duraklamaya (virgül) veya boşluğa çevir
        t = re.sub(r"[()\[\]{}]", ", ", t)
        t = re.sub(r"[\"#\*\^_`|~<>\\]", " ", t)
        t = t.replace("...", ", ").replace("…", ", ").replace(" — ", ", ").replace(" - ", ", ")

        # Vocab dışı kalan bilinmeyen karakterleri filtrele
        valid_chars = self.vocab | {"\n", "\t", " "}
        cleaned_chars = [ch if ch in valid_chars else " " for ch in t]
        res = "".join(cleaned_chars)
        return re.sub(r"\s+", " ", res).strip()

    def split_prosodic_clauses(
        self,
        text: str,
        max_words: int = 12,
        max_chars: int = 240,
    ) -> List[Tuple[str, float]]:
        """
        Bağlaç duyarlı yumuşak bölme ve noktalama duyarlı dinamik duraksama (80–320 ms):
        - Sabit kelime sayısı yerine cümle terminatörleri ve Türkçe bağlaçlar
          (ve, veya, ancak, çünkü, fakat...) üzerinden doğal nefes payı bırakır.
        """
        normalized_text = self.normalize(text)
        if not normalized_text:
            return []

        # 1. Cümleleri temel noktalama işaretlerinden ayır
        sentences = re.split(r"(?<=[,.;?!:])\s+", normalized_text)
        clauses: List[Tuple[str, float]] = []

        pause_map = {
            "?": 0.32,  # Soru işareti: 320 ms
            ".": 0.28,  # Nokta: 280 ms
            "!": 0.28,  # Ünlem: 280 ms
            ";": 0.20,  # Noktalı virgül: 200 ms
            ":": 0.20,  # İki nokta: 200 ms
            ",": 0.14,  # Virgül: 140 ms
        }

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            last_char = sentence[-1]
            base_pause = pause_map.get(last_char, 0.08)

            words = sentence.split()
            # Kısa cümleler doğrudan tek parça olarak eklenebilir
            if len(words) <= max_words and len(sentence) <= max_chars:
                clauses.append((sentence, base_pause))
                continue

            # Uzun cümlelerde bağlaç duyarlı yumuşak bölme
            chunks = self._soft_split_by_conjunctions(words, max_words=max_words, max_chars=max_chars)
            for idx, chunk in enumerate(chunks):
                is_last = (idx == len(chunks) - 1)
                chunk_pause = base_pause if is_last else 0.12  # Bağlaç arası nefes: 120 ms
                clauses.append((chunk, chunk_pause))

        # Seçenek B: Clitic mikro duraksamalarını (pause_injections_ms) sınır paylarına yansıt
        from backend.config import settings
        if getattr(settings, "morph_precheck_enabled", True):
            try:
                from backend.morphological_pre_checker import morphological_pre_checker
                from backend.morphology.contracts import NormalizedUtterance
                utt = NormalizedUtterance(
                    utterance_id="utt_clause_pause",
                    chunk_id="chk_0",
                    chunk_text=normalized_text,
                )
                plan = morphological_pre_checker.analyze(utt)
                if plan.pause_injections_ms and clauses:
                    extra_sec = sum(plan.pause_injections_ms.values()) / 1000.0
                    adjusted = []
                    for idx, (c_text, p_sec) in enumerate(clauses):
                        if idx == len(clauses) - 1:
                            adjusted.append((c_text, round(p_sec + extra_sec, 3)))
                        else:
                            adjusted.append((c_text, p_sec))
                    return adjusted
            except Exception:
                pass

        return clauses

    def _soft_split_by_conjunctions(
        self, words: List[str], max_words: int = 12, max_chars: int = 240
    ) -> List[str]:
        """Uzun bir kelime listesini bağlaç ve anlam bütünlüğünü koruyarak böler."""
        chunks: List[str] = []
        current: List[str] = []

        i = 0
        while i < len(words):
            word = words[i]
            clean_w = word.lower().strip(".,:;?!")

            # Korunan sayı veya deyim öbekleri kontrolü
            atom = [word]
            if clean_w in NUMBER_WORDS:
                # Sayı zincirini tek atomda topla
                j = i + 1
                while j < len(words) and words[j].lower().strip(".,:;?!") in NUMBER_WORDS:
                    atom.append(words[j])
                    j += 1
                i = j - 1

            candidate_words = current + atom
            candidate_str = " ".join(candidate_words)

            # Bağlaç tespit edildi ve mevcut öbek yeterince uzun mu?
            is_conj = clean_w in TURKISH_CONJUNCTIONS and len(current) >= 4

            if (len(candidate_words) > max_words or len(candidate_str) > max_chars or is_conj) and current:
                chunks.append(" ".join(current))
                current = atom
            else:
                current.extend(atom)

            i += 1

        if current:
            chunks.append(" ".join(current))

        return chunks


class AutomotiveDSPChain:
    """
    Dinamik Prozodi ve 8 kHz Telefon DSP Zinciri:
    - 10-15 ms Kosinüs Sönümleme (Fade-in/out ile tıklama/patlama engelleme)
    - -58 dBFS Konfor Gürültüsü Enjeksiyonu (Comfort Noise Injection)
    - 5.5 kHz – 7.5 kHz Sibilance Kesici (De-Esser)
    - 80 Hz Sub-bass Uğultu Kesici HPF
    - 3.2 kHz Bell Labs Telefon Berraklaştırma Tepe Filtresi (+2.8 dB)
    - 48 kHz -> 8 kHz Polifaz Aşağı Örnekleme (resample_poly)
    - Yumuşak Tepe Sınırlayıcı (Soft Limiter) ve 16-bit slin16 PCM kodlama
    """

    def __init__(
        self,
        sr_in: int = DEFAULT_SR_IN,
        sr_out: int = DEFAULT_SR_OUT,
        comfort_noise_dbfs: float = COMFORT_NOISE_DBFS,
    ):
        self.sr_in = sr_in
        self.sr_out = sr_out
        self.comfort_noise_dbfs = comfort_noise_dbfs
        self.comfort_noise_rms = 10.0 ** (comfort_noise_dbfs / 20.0)

    def apply_cosine_fade(
        self, wav: np.ndarray, sr: int = DEFAULT_SR_IN, fade_ms: float = 12.0
    ) -> np.ndarray:
        """Parça başı ve sonuna tıklama önleyici kosinüs (Hanning) sönümleme uygular."""
        n_fade = int(sr * (fade_ms / 1000.0))
        if len(wav) <= 2 * n_fade or n_fade <= 0:
            return wav

        out = wav.copy()
        fade_in = 0.5 * (1.0 - np.cos(np.linspace(0, math.pi, n_fade, dtype=np.float32)))
        fade_out = 0.5 * (1.0 + np.cos(np.linspace(0, math.pi, n_fade, dtype=np.float32)))

        out[:n_fade] *= fade_in
        out[-n_fade:] *= fade_out
        return out

    def apply_de_esser(
        self,
        wav: np.ndarray,
        sr: int = DEFAULT_SR_IN,
        f_center: float = 6500.0,
        bandwidth: float = 2000.0,
        reduction_db: float = 4.5,
    ) -> np.ndarray:
        """
        Türkçe konuşmadaki aşırı 's', 'ş', 'z' tiz ıslık enerjisini (5.5 - 7.5 kHz)
        alt frekanslara dokunmadan yumuşatır.
        """
        if len(wav) < 64:
            return wav

        low = max(20.0, f_center - bandwidth / 2.0)
        high = min(sr / 2.0 - 50.0, f_center + bandwidth / 2.0)

        sos_bp = signal.butter(2, [low / (sr / 2), high / (sr / 2)], btype="bandpass", output="sos")
        sibilance = signal.sosfilt(sos_bp, wav)

        # Sibilance bandını reduction_db kadar bastırıp ana sinyale geri birleştir
        attenuation_factor = 1.0 - (10.0 ** (-reduction_db / 20.0))
        cleaned = wav - (attenuation_factor * sibilance)
        return cleaned.astype(np.float32)

    def generate_comfort_noise(self, num_samples: int, sr: int = DEFAULT_SR_OUT) -> np.ndarray:
        """-58 dBFS seviyesinde spektral şekillendirilmiş konfor gürültüsü üretir."""
        if num_samples <= 0:
            return np.zeros(0, dtype=np.float32)

        noise = np.random.normal(0.0, self.comfort_noise_rms, num_samples).astype(np.float32)
        # 150 Hz altını keserek boğuk dip uğultusunu engelle
        if num_samples >= 32 and (150.0 / (sr / 2)) < 1.0:
            sos = signal.butter(1, 150.0 / (sr / 2), btype="highpass", output="sos")
            noise = signal.sosfilt(sos, noise).astype(np.float32)
        return noise

    def process_telephony_dsp(
        self,
        wav_48k: np.ndarray,
        apply_de_ess: bool = True,
        inject_noise: bool = True,
    ) -> np.ndarray:
        """
        Tam 48 kHz -> 8 kHz slin16 DSP dönüşüm zinciri:
        1. 12 ms Kosinüs Sönümleme
        2. 6.5 kHz De-Esser (Sibilance Bastırıcı)
        3. 80 Hz High-Pass Filtresi (Sub-bass kesici)
        4. 3.2 kHz Bell Labs Telefon Anlaşılırlık Tepe Filtresi (+2.8 dB)
        5. 48 kHz -> 8 kHz Polifaz Aşağı Örnekleme (resample_poly)
        6. -58 dBFS Konfor Gürültüsü Enjeksiyonu
        7. Tanh Yumuşak Tepe Sınırlayıcı (Soft Limiter)
        8. int16 slin16 PCM formatına dönüştürme
        """
        y = wav_48k.astype(np.float32)

        # 1. Kosinüs sönümleme
        y = self.apply_cosine_fade(y, sr=self.sr_in, fade_ms=12.0)

        # 2. De-Esser
        if apply_de_ess:
            y = self.apply_de_esser(y, sr=self.sr_in)

        # 3. 80 Hz Sub-bass High-Pass Filtresi
        sos_hp = signal.butter(2, 80.0 / (self.sr_in / 2), btype="highpass", output="sos")
        y = signal.sosfilt(sos_hp, y).astype(np.float32)

        # 4. 3.2 kHz Bell Labs Varlık (Presence) Artışı (+2.8 dB)
        b_peak, a_peak = signal.iirpeak(3200.0 / (self.sr_in / 2), Q=1.5)
        y = (y + 0.35 * signal.lfilter(b_peak, a_peak, y)).astype(np.float32)

        # 5. Polifaz Aşağı Örnekleme (48 kHz -> 8 kHz, oran 1 / 6)
        y_8k = signal.resample_poly(y, up=1, down=6).astype(np.float32)

        # 6. -58 dBFS Konfor Gürültüsü
        if inject_noise:
            noise = self.generate_comfort_noise(len(y_8k), sr=self.sr_out)
            y_8k += noise

        # 7. Yumuşak Tepe Sınırlayıcı
        y_8k = np.tanh(y_8k * 1.15)

        # 8. int16 slin16 dönüşümü
        pcm16 = (np.clip(y_8k, -1.0, 1.0) * 32767.0).round().astype("<i2")
        return pcm16

    def generate_pause_audio(self, pause_sec: float) -> bytes:
        """Belirtilen süre kadar -58 dBFS konfor gürültüsü içeren 8 kHz slin16 PCM üretir."""
        n_samples = int(self.sr_out * max(0.0, pause_sec))
        if n_samples <= 0:
            return b""
        noise = self.generate_comfort_noise(n_samples, sr=self.sr_out)
        pcm16 = (np.clip(noise, -1.0, 1.0) * 32767.0).round().astype("<i2")
        return pcm16.tobytes()


class AutomotiveFrontend:
    """
    Otomotiv Metin Ön Yüzü, Prozodi ve 8 kHz EQ Birleşik Orkestratörü:
    - Metin normalizasyonu ve sözlük ek uyumlaması
    - <UNK> Güvenlik Ağı
    - Bağlaç duyarlı yumuşak cümle bölme ve noktalama duraksamaları
    - 8 kHz telefon DSP zinciri ve konfor gürültüsü
    """

    def __init__(self):
        self.normalizer = AutomotiveTextNormalizer()
        self.dsp = AutomotiveDSPChain()
        self._lock = threading.Lock()

        # Telemetri Sayaçları
        self.total_processed_texts = 0
        self.total_generated_clauses = 0
        self.total_audio_seconds = 0.0

    def prepare_text_for_synthesis(self, text: str) -> dict[str, Any]:
        """Metni temizler, normalleştirir ve prozodik duraksamalarla parçalara böler."""
        normalized = self.normalizer.normalize(text)
        clauses = self.normalizer.split_prosodic_clauses(text)

        with self._lock:
            self.total_processed_texts += 1
            self.total_generated_clauses += len(clauses)

        prosody_plan: dict[str, Any] | None = None
        from backend.config import settings
        if getattr(settings, "morph_precheck_enabled", True):
            try:
                from backend.morphological_pre_checker import morphological_pre_checker
                from backend.morphology.contracts import NormalizedUtterance
                utterance = NormalizedUtterance(
                    utterance_id="utt_synth",
                    chunk_id="chunk_0",
                    chunk_text=normalized,
                )
                plan = morphological_pre_checker.analyze(utterance)
                prosody_plan = plan.model_dump()
            except Exception as e:
                logger.warning(f"MorphologicalPreChecker analizi atlandı: {e}")

        return {
            "source": text,
            "normalized": normalized,
            "clauses": [
                {"clause": c, "pause_sec": round(p, 3)}
                for c, p in clauses
            ],
            "total_clauses": len(clauses),
            "prosody_plan": prosody_plan,
        }

    def process_synthesized_audio(
        self, wav_48k: np.ndarray, apply_de_ess: bool = True, inject_noise: bool = True
    ) -> np.ndarray:
        """Sentezlenmiş 48 kHz sesi 8 kHz slin16 telefon formatına dönüştürür."""
        pcm16 = self.dsp.process_telephony_dsp(
            wav_48k, apply_de_ess=apply_de_ess, inject_noise=inject_noise
        )
        with self._lock:
            self.total_audio_seconds += len(wav_48k) / DEFAULT_SR_IN
        return pcm16

    def generate_pause_pcm(self, pause_sec: float) -> bytes:
        """Duraksamalar için konfor gürültüsü üretir."""
        return self.dsp.generate_pause_audio(pause_sec)

    def get_metrics(self) -> dict[str, Any]:
        """Ön yüz telemetri metriklerini döndürür."""
        with self._lock:
            return {
                "total_processed_texts": self.total_processed_texts,
                "total_generated_clauses": self.total_generated_clauses,
                "total_audio_seconds": round(self.total_audio_seconds, 2),
                "comfort_noise_dbfs": self.dsp.comfort_noise_dbfs,
                "sr_in": self.dsp.sr_in,
                "sr_out": self.dsp.sr_out,
            }


# Modül düzeyinde tekil ön yüz nesnesi
automotive_frontend = AutomotiveFrontend()
