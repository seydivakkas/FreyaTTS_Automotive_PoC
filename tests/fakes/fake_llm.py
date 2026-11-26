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

SAHTE (MOCK) LLM — H01.01 hermetik test minimumu.

Canlı Ollama yerine geçer; ağ çağrısı yapmaz. Ürettiği hiçbir çıktı model
ölçümü değildir. Varsayılan kip "erişilemez"dir: Ollama'nın çalışmadığı CI
ortamındaki davranışın aynısını (bağlantı hatası) ağsız üretir. Yanıt gereken
test, ``fake_llm.reply(...)`` ile JSON yanıtı sıraya koyar.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

FAKE_LABEL = "SAHTE-LLM"


class FakeLLM:
    """``Models._chat`` yerine geçen sahte akış üreticisi."""

    def __init__(self) -> None:
        self._replies: list[str] = []
        self.calls: list[dict[str, Any]] = []
        self.available = False

    def reply(self, payload: dict[str, Any] | str) -> "FakeLLM":
        """Bir sonraki çağrının döndüreceği yanıtı sıraya koyar ve LLM'i erişilebilir yapar."""
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        self._replies.append(text)
        self.available = True
        return self

    async def chat(self, messages, *, response_schema=None):
        self.calls.append({"messages": messages, "response_schema": response_schema})
        if not self.available:
            raise httpx.ConnectError(f"{FAKE_LABEL}: hermetik testte canlı LLM yok")
        text = self._replies.pop(0) if self._replies else "{}"
        # Gerçek istemci gibi parça parça akıt.
        mid = len(text) // 2
        for part in (text[:mid], text[mid:]):
            if part:
                yield part
