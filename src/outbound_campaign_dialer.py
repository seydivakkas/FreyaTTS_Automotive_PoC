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

from backend.outbound_dialer import (
    OutboundCampaignDialer,
    campaign_dialer,
    AMDResult,
    detect_turkish_amd,
    detect_voicemail_beep,
    generate_call_file_content,
    write_atomic_call_file,
    DEFAULT_OUTGOING_DIR,
    DEFAULT_TMP_DIR,
    MAX_HUMAN_GREETING_SEC,
    MIN_HUMAN_PAUSE_SEC,
    MIN_MACHINE_GREETING_SEC,
    BEEP_DETECT_FREQ_HZ,
)

__all__ = [
    "OutboundCampaignDialer",
    "campaign_dialer",
    "AMDResult",
    "detect_turkish_amd",
    "detect_voicemail_beep",
    "generate_call_file_content",
    "write_atomic_call_file",
    "DEFAULT_OUTGOING_DIR",
    "DEFAULT_TMP_DIR",
    "MAX_HUMAN_GREETING_SEC",
    "MIN_HUMAN_PAUSE_SEC",
    "MIN_MACHINE_GREETING_SEC",
    "BEEP_DETECT_FREQ_HZ",
]

