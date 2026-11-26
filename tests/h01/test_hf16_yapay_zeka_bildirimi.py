"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ. Ayrıntı: LICENSE.

H01.14 — HF16: karşılamada yapay zekâ bildirimi (ADR-X-03, kabul edildi).

Gelen (A/B karşılama şablonları), giden (randevu teyidi, OBD teşhis) ve web
karşılamalarının tamamı yapılandırmadaki tek bildirim metniyle başlar; önbellek
ısıtma listesi bu metinleri Leyla seed 9 ile içerir. Testler sahte sentez kullanır.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.session as session_mod
from backend.ab_testing import GREETING_TEMPLATES, get_greeting_text
from backend.config import settings
from backend.db import Appointment, Base, Slot, Vehicle, VehicleDiagnostic
from backend.models import models

ADR_X03_TEXT = "Merhaba, Freya yapay zekâ destekli müşteri temsilcisine ulaştınız."


def test_hf16_bildirim_metni_yapilandirmada_tek_yerde():
    assert settings.ai_disclosure_text == ADR_X03_TEXT


def test_hf16_tum_gelen_karsilama_sablonlari_bildirimle_baslar():
    for tid, tpl in GREETING_TEMPLATES.items():
        assert tpl["text"].startswith(ADR_X03_TEXT + " "), tid
        assert tpl["text"].count("Merhaba") == 1, tid
        assert get_greeting_text(tid) == tpl["text"]
    assert get_greeting_text(None).startswith(ADR_X03_TEXT)
    assert get_greeting_text("olmayan-sablon").startswith(ADR_X03_TEXT)


def test_hf16_onbellek_isitma_listesi_bildirimli_karsilamayi_seed_9_ile_icerir():
    pairs = models._prewarm_targets()
    for tpl in GREETING_TEMPLATES.values():
        assert (tpl["text"], 9) in pairs
    assert all(seed == 9 for text, seed in pairs if text.startswith(ADR_X03_TEXT))


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "hf16.db"), connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_mod, "Session", maker)
    monkeypatch.setattr("backend.dialogue.Session", maker)

    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(models, "vad", Vad())
    yield maker
    engine.dispose()


async def _spoken_greeting(monkeypatch, **kwargs):
    spoken = []

    async def fake_reply(self, text, start=None, source="live"):
        spoken.append(text)

    monkeypatch.setattr(session_mod.VoiceSession, "reply", fake_reply)

    async def emit(event):
        pass

    async def send(frame):
        pass

    session = session_mod.VoiceSession("hf16", emit, send, **kwargs)
    try:
        await session.start()
    finally:
        await session.close()
    return spoken


async def test_hf16_gelen_web_karsilamasi_bildirim_icerir(db_env, monkeypatch):
    spoken = await _spoken_greeting(monkeypatch)
    assert spoken and spoken[0].startswith(ADR_X03_TEXT)


async def test_hf16_giden_randevu_teyidi_bildirim_icerir(db_env, monkeypatch):
    with db_env() as db:
        v = Vehicle(description="Toyota Corolla 1.5 Vision", plate="34 TYT 55")
        s = Slot(starts_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), duration_minutes=45)
        db.add_all([v, s])
        db.flush()
        a = Appointment(slot_id=s.id, vehicle_id=v.id, customer="Mehmet Bey", idempotency_key="hf16-a", confirmed=True)
        db.add(a)
        db.commit()
    spoken = await _spoken_greeting(monkeypatch, mode="outbound_reminder", appointment_id=a.id)
    assert spoken and spoken[0].startswith(ADR_X03_TEXT)
    assert "Maslak Ekspertiz" in spoken[0]


async def test_hf16_giden_teshis_aramasi_bildirim_icerir(db_env, monkeypatch):
    spoken = await _spoken_greeting(monkeypatch, mode="outbound_diagnostic")
    assert spoken and spoken[0].startswith(ADR_X03_TEXT)


@pytest.mark.parametrize(
    "soru",
    ["İnsanla mı konuşuyorum?", "Siz robot musunuz", "Gerçek bir kişi misiniz?", "yapay zeka mısın"],
)
async def test_hf16_insan_mi_sorusuna_durust_yanit_ve_aktarim_secenegi(soru):
    from backend.dialogue import Dialogue

    d = Dialogue("hf16-soru")
    d.awaiting = True  # bekleyen onay varken bile durum değişmez
    ans = await d.answer(soru)
    assert "yapay zekâ destekli" in ans and "operatöre bağla" in ans
    assert d.awaiting is True and not d.done
