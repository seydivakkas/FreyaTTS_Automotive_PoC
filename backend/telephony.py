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
import time
from typing import Any
from backend.audiosocket_server import (
    orchestrator,
    read_packet as _read_packet,
    build_packet,
)

read_packet = _read_packet

_inbound_metadata_registry: dict[str, dict[str, Any]] = {}


def register_inbound_metadata(
    call_uuid: str,
    caller_id: str = "",
    caller_channel: str = "",
    did: str = "",
) -> dict[str, Any]:
    """Gelen çağrı için Asterisk dialplan / webhook tarafından iletilen üstveriyi kaydeder."""
    meta = {
        "call_uuid": str(call_uuid).strip(),
        "caller_id": str(caller_id or "").strip(),
        "caller_channel": str(caller_channel or "").strip(),
        "did": str(did or "").strip(),
        "created_at": time.time(),
    }
    _inbound_metadata_registry[str(call_uuid).strip()] = meta
    # Temizlik: 120 saniyeden eski kayıtları düşür
    cutoff = time.time() - 120.0
    for k in list(_inbound_metadata_registry.keys()):
        if _inbound_metadata_registry[k]["created_at"] < cutoff:
            _inbound_metadata_registry.pop(k, None)
    return meta


def get_inbound_metadata(call_uuid: str) -> dict[str, Any] | None:
    """Belirtilen call_uuid için kayıtlı üstveriyi döner."""
    return _inbound_metadata_registry.get(str(call_uuid).strip())


async def connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Asterisk app_audiosocket bağlantısını AudioSocketOrchestrator üzerinden yönetir."""
    await orchestrator.handle_connection(reader, writer)
