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

from backend.prosody_wsola_streamer import (
    LEYLA_SEED,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_MIN_DURATION_SEC,
    IntentCategory,
    ProsodyProfile,
    INTENT_PROFILES,
    VoicingReport,
    SynthesizedClause,
    WSOLATimeStretch,
    ContextualProsodyPlanner,
    DurationFloorGuard,
    AudioVoicingChecker,
    ModelHashAndSeedGuard,
    OverlappingClauseStreamer,
    prosody_wsola_streamer,
)

__all__ = [
    "LEYLA_SEED",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_MIN_DURATION_SEC",
    "IntentCategory",
    "ProsodyProfile",
    "INTENT_PROFILES",
    "VoicingReport",
    "SynthesizedClause",
    "WSOLATimeStretch",
    "ContextualProsodyPlanner",
    "DurationFloorGuard",
    "AudioVoicingChecker",
    "ModelHashAndSeedGuard",
    "OverlappingClauseStreamer",
    "prosody_wsola_streamer",
]

