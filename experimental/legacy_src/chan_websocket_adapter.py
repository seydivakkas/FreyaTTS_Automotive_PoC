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

from backend.websocket_adapter import (
    ChanWebSocketAdapter,
    ChanWebSocketSession,
    chan_ws_adapter,
    build_command,
    parse_event,
    COMMAND_FLUSH_MEDIA,
    COMMAND_PAUSE_MEDIA,
    COMMAND_RESUME_MEDIA,
    COMMAND_SET_VARIABLE,
    COMMAND_HANGUP,
    EVENT_CALL_START,
    EVENT_DTMF,
    EVENT_HANGUP,
    EVENT_MEDIA_FLUSHED,
    SAMPLE_RATE,
    FRAME_SIZE_BYTES,
)

__all__ = [
    "ChanWebSocketAdapter",
    "ChanWebSocketSession",
    "chan_ws_adapter",
    "build_command",
    "parse_event",
    "COMMAND_FLUSH_MEDIA",
    "COMMAND_PAUSE_MEDIA",
    "COMMAND_RESUME_MEDIA",
    "COMMAND_SET_VARIABLE",
    "COMMAND_HANGUP",
    "EVENT_CALL_START",
    "EVENT_DTMF",
    "EVENT_HANGUP",
    "EVENT_MEDIA_FLUSHED",
    "SAMPLE_RATE",
    "FRAME_SIZE_BYTES",
]

