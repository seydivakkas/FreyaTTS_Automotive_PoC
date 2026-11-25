"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ. Ayrıntı: LICENSE.

H01.13 / H01.15 — HF14, HF15, HF17: ölçüm dürüstlüğü ve arayüzde uydurma yanıt yok.

Kaynak taraması (statik): arayüz bileşenleri derlenmiş tarayıcıda çalıştırılmadan
doğrulanır. Tarayıcı davranışı ayrıca Playwright (tests/ui.spec.ts) ile denetlenir.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_hf14_batched_ode_etiketsiz_performans_iddiasi_yok():
    src = _read("backend/batched_ode.py")
    for line in src.splitlines():
        if re.search(r"RTX\s*4090|RTF\s*<=|65\+\s*saniye|3\.8\s*GB", line):
            assert "ÖLÇÜLMEDİ" in src and ("kaynaksız" in line or "ölçülmedi" in line.lower()), line


def test_hf14_arayuzde_sabit_yedek_olcum_sayisi_yok():
    """Ölçüm yokken gösterilen sabit sayılar (eski: 214ms, 194ms, +14.8 dB …) kaldırıldı."""
    banned = ['"214ms"', '"182ms"', '"194ms"', '"138ms"', '"+14.8 dB"', '"-28.4 dBFS"', '"34.2%"',
              "F0 SNR: +14.8dB", "F0 SNR: +15.2dB", "ttfb_ms: 184", "llmDurationMs = 175"]
    for rel in ("tabs/VoiceTab.tsx", "tabs/LabTab.tsx", "CarDenoiserPanel.tsx"):
        text = (SRC / rel).read_text(encoding="utf-8")
        for b in banned:
            assert b not in text, (rel, b)


def test_hf15_ses_laboratuvari_dogru_model_gercek_ornekleme_istek_suresi():
    lab = (SRC / "tabs/LabTab.tsx").read_text(encoding="utf-8")
    assert "Piper" not in lab and "FreyaTTS" in lab
    assert "parseWavInfo" in lab and "/ 44100" not in lab and "sample_rate_hz: 22050" not in lab
    assert "TTFB" not in lab and "İstek süresi" in lab
    assert lab.count("title={INERT_CONTROL_NOTE}") == 4  # konuşmacı, hız, ton, gürültü devre dışı
    assert "speed: speechRate" not in lab


def test_hf15_canli_reel_mod_yalniz_gercek_olcumde():
    hdr = (SRC / "CockpitHeader.tsx").read_text(encoding="utf-8")
    assert '"CANLI REEL MOD"' in hdr and "liveMeasured ?" in hdr


def test_hf17_arayuz_kendi_leyla_yanitini_uretmez():
    voice = (SRC / "tabs/VoiceTab.tsx").read_text(encoding="utf-8")
    assert "başarıyla iletilmiştir" not in voice
    assert "Talebinizi aldım Ahmet Bey" not in voice
    assert "Şu anda yanıt veremiyorum" in voice
    for rel in SRC.rglob("*.tsx"):
        assert "başarıyla iletilmiştir" not in rel.read_text(encoding="utf-8"), rel
