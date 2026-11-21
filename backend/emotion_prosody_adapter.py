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

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import numpy as np

# 1. Duygu ve İtiraz Durumları
class EmotionCategory(str, Enum):
    SATISFIED_CALM = "satisfied_calm"     # Sakin, dengeli, normal müşteri
    HESITANT = "hesitant"                 # Kararsız, tereddütlü, çekingen
    OBJECTION_PRICE = "objection_price"   # Fiyat yüksek / indirim talebi
    OBJECTION_TIME = "objection_time"     # Zaman / saat uyuşmazlığı, yetişememe
    HURRIED = "hurried"                   # Aceleci, telaşlı, zamanı kısıtlı


# 2. İtiraz ve Duygu Anahtar Kelimeleri Sözlüğü
PRICE_OBJECTION_KEYWORDS: set[str] = {
    "pahalı",
    "pahali",
    "pahalıymış",
    "çok fazla",
    "cok fazla",
    "bütçemi aşıyor",
    "butcemi asiyor",
    "indirim",
    "indiriminiz",
    "yüksek",
    "yuksek",
    "daha uygun",
    "çok para",
    "cok para",
    "fiyat yüksek",
    "fiyat yuksek",
    "pazarlık",
    "pazarlik",
    "iskonto",
    "kampanya",
}

TIME_OBJECTION_KEYWORDS: set[str] = {
    "yetişemem",
    "yetisemem",
    "gelemem",
    "uymaz",
    "uygun değil",
    "uygun degil",
    "işteyim",
    "isteyim",
    "mesaideyim",
    "mümkün değil",
    "mumkun degil",
    "geç kalırım",
    "gec kalirim",
    "saat geç",
    "saat gec",
    "başka gün",
    "baska gun",
    "başka saat",
    "baska saat",
    "çakışıyor",
    "cakisiyor",
}

HESITATION_KEYWORDS: set[str] = {
    "bilmiyorum",
    "emin değilim",
    "emin degilim",
    "acaba",
    "düşüneyim",
    "dusuneyim",
    "bakarız",
    "bakariz",
    "belki",
    "kararsızım",
    "kararsizim",
    "bakalım",
    "bakalim",
    "düşünmem lazım",
    "dusunmem lazim",
    "bir baksam",
    "nasıl yapsak",
}

HURRY_KEYWORDS: set[str] = {
    "acil",
    "acelem var",
    "hemen",
    "çabuk",
    "cabuk",
    "hızlıca",
    "hizlica",
    "vaktim yok",
    "bekleyemem",
    "kısa tutalım",
    "kisa tutalim",
    "acele",
    "seri",
    "dakikam az",
}

# 3. Empatik Söylem Belirteçleri (Empathic Discourse Markers)
EMPATHIC_PREFIXES: Dict[EmotionCategory, List[str]] = {
    EmotionCategory.OBJECTION_PRICE: [
        "Sizi çok iyi anlıyorum. ",
        "Haklısınız, bütçenizi düşündüğünüzün farkındayım. ",
        "Fiyat konusundaki hassasiyetinizi anlıyorum. ",
    ],
    EmotionCategory.OBJECTION_TIME: [
        "Haklısınız, yoğunluğunuzu çok iyi anlıyorum. ",
        "Zamanınızı en verimli şekilde değerlendirelim. ",
        "Programınızı aksatmayacak bir çözüm bulalım. ",
    ],
    EmotionCategory.HESITANT: [
        "Tabii ki, hiç acele etmeyin. ",
        "Kararınızı rahatça vermeniz için detayları paylaşayım. ",
        "Aklınıza takılan her noktayı birlikte netleştirelim. ",
    ],
    EmotionCategory.HURRIED: [
        "",  # Acele eden müşteriye doğrudan konuya girilir, vakit kaybettirilmez
    ],
    EmotionCategory.SATISFIED_CALM: [
        "",
    ],
}

# Türkçe Ünlü Harfler (Hece Sayımı İçin)
TURKISH_VOWELS = set("aeıioöuüAEIİOÖUÜ")


def count_turkish_syllables(text: str) -> int:
    """
    Türkçe dil kurallarına göre metindeki hece sayısını hesaplar.
    Türkçede her ünlü harf tam olarak bir hece oluşturur.
    """
    return sum(1 for char in text if char in TURKISH_VOWELS)


def compute_audio_rms_dbfs(audio_samples: np.ndarray) -> float:
    """
    Ses sinyalinin RMS enerji seviyesini dBFS cinsinden hesaplar.
    """
    if len(audio_samples) == 0:
        return -96.0
    rms = np.sqrt(np.mean(audio_samples.astype(np.float32) ** 2))
    if rms <= 1e-9:
        return -96.0
    return float(20.0 * np.log10(rms))


@dataclass
class EmotionProfile:
    primary_category: EmotionCategory
    confidence: float
    speech_rate_syllables_per_sec: Optional[float] = None
    speech_rate_category: str = "normal"  # "slow" | "normal" | "fast"
    rms_dbfs: Optional[float] = None
    detected_keywords: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["primary_category"] = self.primary_category.value
        return d


@dataclass
class AdaptedProsodyPlan:
    original_text: str
    adapted_text: str
    injected_discourse_prefix: str
    emotion_category: str
    speed_ratio: float           # TTS hız ölçeği (0.90 - 1.10)
    pause_multiplier: float      # Noktalama duraksama süresi çarpanı (0.80 - 1.30)
    period_pause_sec: float      # Nokta duraksaması (saniye)
    comma_pause_sec: float       # Virgül duraksaması (saniye)
    acoustic_tone: str           # "calm_empathic" | "direct_brisk" | "reassuring_patient" | "standard"
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EmotionProsodyAdapter:
    """
    Müşterinin konuşma hızından, ses enerjisinden ve itiraz kelimelerinden
    duygu durumunu analiz eden ve Leyla'nın yanıt prozodisini dinamik uyarlayan motor.
    """

    def __init__(
        self,
        *,
        base_period_pause_sec: float = 0.25,
        base_comma_pause_sec: float = 0.14,
    ):
        self.base_period_pause_sec = base_period_pause_sec
        self.base_comma_pause_sec = base_comma_pause_sec

    def analyze_caller_emotion(
        self,
        transcript: str,
        audio_samples: Optional[np.ndarray] = None,
        audio_duration_sec: Optional[float] = None,
        sample_rate: int = 16000,
    ) -> EmotionProfile:
        """
        Müşterinin transkript metnini ve ses telemetrisini inceleyerek duygu profilini çıkarır.
        """
        norm = transcript.lower().strip()
        matched_keywords: List[str] = []
        reasons: List[str] = []

        # 1. Metin Tabanlı İtiraz ve Ruh Hali Taraması
        score_price = 0
        score_time = 0
        score_hesitant = 0
        score_hurry = 0

        for kw in PRICE_OBJECTION_KEYWORDS:
            if kw in norm:
                score_price += 2
                matched_keywords.append(kw)

        for kw in TIME_OBJECTION_KEYWORDS:
            if kw in norm:
                score_time += 2
                matched_keywords.append(kw)

        for kw in HESITATION_KEYWORDS:
            if kw in norm:
                score_hesitant += 2
                matched_keywords.append(kw)

        for kw in HURRY_KEYWORDS:
            if kw in norm:
                score_hurry += 2
                matched_keywords.append(kw)

        # 2. Akustik Analiz (Ses varsa)
        rms_val: Optional[float] = None
        speech_rate: Optional[float] = None
        rate_cat = "normal"

        if audio_samples is not None and len(audio_samples) > 0:
            rms_val = compute_audio_rms_dbfs(audio_samples)
            dur = audio_duration_sec or (len(audio_samples) / float(sample_rate))

            if dur > 0.4:
                syllables = count_turkish_syllables(norm)
                speech_rate = round(syllables / dur, 2)

                if speech_rate >= 5.5:
                    rate_cat = "fast"
                    score_hurry += 2
                    reasons.append(f"Hızlı konuşma temposu ({speech_rate} hece/sn).")
                elif speech_rate <= 3.0 and len(norm) > 10:
                    rate_cat = "slow"
                    score_hesitant += 1
                    reasons.append(f"Yavaş/tereddütlü konuşma temposu ({speech_rate} hece/sn).")

            if rms_val > -16.0:
                reasons.append(f"Yüksek ses enerjisi ({rms_val:.1f} dBFS).")
            elif rms_val < -32.0:
                reasons.append(f"Düşük/çekingen ses enerjisi ({rms_val:.1f} dBFS).")

        # 3. Kategori Belirleme
        scores = {
            EmotionCategory.OBJECTION_PRICE: score_price,
            EmotionCategory.OBJECTION_TIME: score_time,
            EmotionCategory.HURRIED: score_hurry,
            EmotionCategory.HESITANT: score_hesitant,
        }

        max_cat, max_score = max(scores.items(), key=lambda item: item[1])

        if max_score == 0:
            primary = EmotionCategory.SATISFIED_CALM
            confidence = 0.80
            reasons.append("Herhangi bir itiraz veya telaş saptanmadı, sakin konuşma.")
        else:
            primary = max_cat
            confidence = min(0.95, 0.60 + (max_score * 0.10))
            reasons.append(f"{primary.value} kategorisi baskın puan aldı ({max_score} puan).")

        return EmotionProfile(
            primary_category=primary,
            confidence=round(confidence, 2),
            speech_rate_syllables_per_sec=speech_rate,
            speech_rate_category=rate_cat,
            rms_dbfs=round(rms_val, 1) if rms_val is not None else None,
            detected_keywords=matched_keywords,
            reasons=reasons,
        )

    def adapt_prosody(
        self,
        assistant_response_text: str,
        emotion_profile: EmotionProfile,
    ) -> AdaptedProsodyPlan:
        """
        Müşterinin duygu profiline göre asistanın vereceği yanıtı ve ses prozodi ayarlarını düzenler:
        - Empatik söylem belirteci enjekte eder.
        - Noktalama duraksama sürelerini esnetir veya daraltır.
        - TTS hız oranını ayarlar.
        """
        cat = emotion_profile.primary_category
        clean_text = assistant_response_text.strip()

        # 1. Empatik Önek Seçimi
        prefixes = EMPATHIC_PREFIXES.get(cat, [""])
        chosen_prefix = prefixes[0] if prefixes else ""

        # Eğer orijinal metin zaten benzer bir giriş içeriyorsa tekrar ekleme
        lower_resp = clean_text.lower()
        if (
            "anlıyorum" in lower_resp
            or "tabii ki" in lower_resp
            or "haklısınız" in lower_resp
            or not chosen_prefix
        ):
            adapted_text = clean_text
            injected_prefix = ""
        else:
            adapted_text = chosen_prefix + clean_text
            injected_prefix = chosen_prefix

        # 2. Prozodi ve Duraksama Katsayıları
        if cat == EmotionCategory.HESITANT:
            speed_ratio = 0.94          # Daha tane tane ve sakin
            pause_mult = 1.25           # Duraksamalar %25 esnetildi
            tone = "reassuring_patient"
            expl = "Müşteri kararsız olduğundan güven veren, yumuşak ve geniş duraksamalı tempo seçildi."

        elif cat == EmotionCategory.OBJECTION_PRICE:
            speed_ratio = 0.96          # Değer ve güven vurgusu için dengeli
            pause_mult = 1.15           # Duraksamalar %15 esnetildi
            tone = "calm_empathic"
            expl = "Fiyat itirazı algılandı; empatik giriş eklendi, sakin ve güven verici duraksamalar uygulandı."

        elif cat == EmotionCategory.OBJECTION_TIME:
            speed_ratio = 1.02          # Çözüm odaklı akıcı tempo
            pause_mult = 1.05
            tone = "solution_oriented"
            expl = "Zaman uyuşmazlığı algılandı; anlayışlı giriş eklendi ve çözüm odaklı tempo korundu."

        elif cat == EmotionCategory.HURRIED:
            speed_ratio = 1.08          # Seri ve dinamik
            pause_mult = 0.80           # Duraksamalar daraltıldı
            tone = "direct_brisk"
            expl = "Müşteri acele ettiği için gereksiz dolgular atlandı, doğrudan konuya girilip duraksamalar kısaltıldı."

        else:
            speed_ratio = 1.00          # Standart
            pause_mult = 1.00
            tone = "standard"
            expl = "Standart kurumsal Leyla prozodisi uygulandı."

        period_pause = round(self.base_period_pause_sec * pause_mult, 3)
        comma_pause = round(self.base_comma_pause_sec * pause_mult, 3)

        return AdaptedProsodyPlan(
            original_text=clean_text,
            adapted_text=adapted_text,
            injected_discourse_prefix=injected_prefix,
            emotion_category=cat.value,
            speed_ratio=round(speed_ratio, 2),
            pause_multiplier=round(pause_mult, 2),
            period_pause_sec=period_pause,
            comma_pause_sec=comma_pause,
            acoustic_tone=tone,
            explanation=expl,
        )

    def scale_morphological_pauses(
        self,
        pause_injections_ms: Dict[int, int],
        emotion_profile: EmotionProfile,
    ) -> Dict[int, int]:
        """
        ExtendedProsodyPlan içindeki clitic mikro duraksamalarını müşterinin
        duygu profiline göre pause_mult ile orantılı ölçekler (20–60 ms sınırını korur).
        """
        if not pause_injections_ms:
            return {}
        cat = emotion_profile.primary_category
        mult = 1.0
        if cat == EmotionCategory.HESITANT:
            mult = 1.25
        elif cat == EmotionCategory.OBJECTION_PRICE:
            mult = 1.15
        elif cat == EmotionCategory.OBJECTION_TIME:
            mult = 1.05
        elif cat == EmotionCategory.HURRIED:
            mult = 0.80

        scaled: Dict[int, int] = {}
        for idx, ms in pause_injections_ms.items():
            new_val = int(round(ms * mult))
            scaled[idx] = max(20, min(60, new_val))
        return scaled


# Global Singleton Instance
emotion_prosody_adapter = EmotionProsodyAdapter()

