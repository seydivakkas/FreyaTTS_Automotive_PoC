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

from backend.emotion_prosody_adapter import (
    EMPATHIC_PREFIXES,
    HESITATION_KEYWORDS,
    HURRY_KEYWORDS,
    PRICE_OBJECTION_KEYWORDS,
    TIME_OBJECTION_KEYWORDS,
    AdaptedProsodyPlan,
    EmotionCategory,
    EmotionProfile,
    EmotionProsodyAdapter,
    compute_audio_rms_dbfs,
    count_turkish_syllables,
    emotion_prosody_adapter,
)

__all__ = [
    "EMPATHIC_PREFIXES",
    "HESITATION_KEYWORDS",
    "HURRY_KEYWORDS",
    "PRICE_OBJECTION_KEYWORDS",
    "TIME_OBJECTION_KEYWORDS",
    "AdaptedProsodyPlan",
    "EmotionCategory",
    "EmotionProfile",
    "EmotionProsodyAdapter",
    "compute_audio_rms_dbfs",
    "count_turkish_syllables",
    "emotion_prosody_adapter",
]

