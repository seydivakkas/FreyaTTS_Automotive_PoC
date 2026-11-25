"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ. Ayrıntı: LICENSE.

H01.08 — HF09: tek karakter yanıtı düşürmesin (L5).
H01.09 — HF10: sıra sayısı (L3).

Önce: "−5 °C" ve "Town & Country" ValueError ("Desteklenmeyen karakterler"),
"Mégane"/"Coupé" ValueError ("Model karakter sözlüğü desteklemiyor") veriyordu;
seslendirme yolunda bu hata yanıtın tamamını düşürüyordu. "1. seçenek …" →
"bir. seçenek" olup "Bir." tek sözcüklük parçasına bölünüyordu.
"""

import json

import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.text import clauses, normalize, prepare_tts_clause


@pytest.mark.parametrize(
    "text, expect",
    [
        ("Hava −5 °C.", "eksi beş derece"),
        ("Renault Mégane", "Megane"),
        ("Coupé modeli", "Coupe"),
        ("Town & Country", " ve "),
    ],
)
def test_hf09_guvenli_yedek_tablosu(text, expect):
    out = normalize(text, lenient=True)
    assert expect in out["normalized"]
    assert out["dropped_chars"] == []


def test_hf09_tablo_disi_karakter_atilir_ve_bildirilir_kati_kip_degismez():
    out = normalize("Araç 🚗 hazır.", lenient=True)
    assert out["normalized"].startswith("Araç") and "🚗" not in out["normalized"]
    assert out["dropped_chars"] == ["🚗"]
    with pytest.raises(ValueError):
        normalize("Araç 🚗")  # yönetim ucu / sözlük denetimi katı kalır


async def test_hf09_yanit_dusmez_ve_olay_kaydedilir(tmp_path, monkeypatch):
    import backend.session as session_mod
    from backend.db import Base, Turn
    from backend.models import models

    engine = create_engine("sqlite:///" + str(tmp_path / "hf09.db"), connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_mod, "Session", maker)
    monkeypatch.setattr("backend.dialogue.Session", maker)

    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(models, "vad", Vad())
    synthesized = []

    async def fake_synth(text, seed=None):  # SAHTE sentez
        synthesized.append(text)
        return np.zeros(4800, np.float32)

    monkeypatch.setattr(models, "synth", fake_synth)

    async def emit(e):
        pass

    async def send(f):
        pass

    s = session_mod.VoiceSession("hf09", emit, send)
    try:
        await s.reply("Hava −5 °C, Town & Country 🚗 hazır.")
        assert synthesized, "yanıt düşmemeli"
        assert all("🚗" not in t and "°" not in t and "&" not in t for t in synthesized)
        with maker() as db:
            rows = db.scalars(select(Turn).where(Turn.conversation_id == s.id, Turn.role == "event")).all()
        events = [json.loads(r.metrics) for r in rows]
        assert any(e.get("event") == "tts_chars_dropped" and e.get("chars") == ["🚗"] for e in events)
    finally:
        await s.close()


def test_hf10_sira_sayisi_tek_parca():
    n = normalize("1. seçenek 25 Kasım 10:00.", lenient=True)["normalized"]
    parts = [prepare_tts_clause(c) for c, _ in clauses(n)]
    assert parts[0].startswith("Birinci seçenek yirmi beş Kasım")
    assert "Bir." not in parts and not any(p.strip() in ("Bir.", "bir.") for p in parts)


def test_hf10_ondalik_ve_tarih_bozulmaz():
    n = normalize("Motor 1.6 TDI, tarih 25.11.2026, 4. sıra", lenient=True)["normalized"]
    assert "birinci" not in n and "altıncı" not in n
    assert "dördüncü sıra" in n
