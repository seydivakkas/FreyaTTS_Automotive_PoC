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

from backend.audiosocket_server import (
    AudioSocketOrchestrator,
    AudioPacer,
    LookbackBuffer,
    TwoStageBargeInController,
    orchestrator,
    read_packet,
    build_packet,
    AUDIOSOCKET_HANGUP,
    AUDIOSOCKET_UUID,
    AUDIOSOCKET_DTMF,
    AUDIOSOCKET_AUDIO,
    AUDIOSOCKET_ERROR,
    SAMPLE_RATE,
    FRAME_DURATION_MS,
    FRAME_SIZE_BYTES,
    LOOKBACK_FRAMES_COUNT,
    LOOKBACK_TOTAL_BYTES,
    BACKCHANNEL_WORDS,
)

__all__ = [
    "AudioSocketOrchestrator",
    "AudioPacer",
    "LookbackBuffer",
    "TwoStageBargeInController",
    "orchestrator",
    "read_packet",
    "build_packet",
    "AUDIOSOCKET_HANGUP",
    "AUDIOSOCKET_UUID",
    "AUDIOSOCKET_DTMF",
    "AUDIOSOCKET_AUDIO",
    "AUDIOSOCKET_ERROR",
    "SAMPLE_RATE",
    "FRAME_DURATION_MS",
    "FRAME_SIZE_BYTES",
    "LOOKBACK_FRAMES_COUNT",
    "LOOKBACK_TOTAL_BYTES",
    "BACKCHANNEL_WORDS",
]

