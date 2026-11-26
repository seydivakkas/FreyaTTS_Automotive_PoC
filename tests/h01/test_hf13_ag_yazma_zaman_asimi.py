"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ. Ayrıntı: LICENSE.

H01.12 — HF13: ağ yazma zaman aşımı (bulgu R6).

Okumayı durduran sahte AudioSocket ve chan_websocket istemcileri: yazma süresiz
beklemez; zaman aşımında bağlantı kontrollü kapanır ve olay sayacı artar.
"""

import asyncio
import time

import pytest

from backend import audiosocket_server as aso
from backend.websocket_adapter import ChanWebSocketAdapter, ChanWebSocketSession


class StalledWriter:
    """SAHTE: tamponu dolu, drain hiç tamamlanmayan AudioSocket istemcisi."""

    def __init__(self):
        self.written = []
        self.closed = False

    def write(self, data):
        self.written.append(data)

    async def drain(self):
        await asyncio.Event().wait()  # okuma yok → sonsuza dek bekler

    def is_closing(self):
        return self.closed

    def close(self):
        self.closed = True


async def test_hf13_audiosocket_drain_zaman_asiminda_kontrollu_kapanir():
    w = StalledWriter()
    started = time.monotonic()
    with pytest.raises(aso.NetworkWriteTimeout):
        await aso.write_audio_packet(w, b"\x00" * 320)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0  # süresiz bekleme yok
    assert elapsed >= aso.NETWORK_WRITE_TIMEOUT_S * 0.9
    assert w.closed is True
    # Kapandıktan sonra yeni yazma denenmez (kapalı bağlantı hatası, bekleme yok).
    with pytest.raises(ConnectionError):
        await aso.write_audio_packet(w, b"\x00" * 320)


def test_hf13_zaman_asimi_alt_siniri_200_ms():
    assert aso.NETWORK_WRITE_TIMEOUT_S >= 0.2


async def test_hf13_chan_websocket_okumayan_istemci_kapanir():
    closed = []

    async def stalled_send(_):
        await asyncio.Event().wait()

    async def close_fn():
        closed.append(True)

    adapter = ChanWebSocketAdapter()
    s = ChanWebSocketSession("s1", "PJSIP/test", stalled_send, stalled_send, adapter)
    s.close_fn = close_fn
    started = time.monotonic()
    await s.send_audio_frame(b"\x00" * 320)
    assert time.monotonic() - started < 2.0
    assert s.is_closed is True and s.write_timeouts == 1 and closed == [True]
    # Kapalı oturumda sonraki gönderim anında döner.
    started = time.monotonic()
    await s.send_command("PING")
    await s.send_audio_frame(b"\x00" * 320)
    assert time.monotonic() - started < 0.1
