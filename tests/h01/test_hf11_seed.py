"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ. Ayrıntı: LICENSE.

H01.10 — HF11: seed düşürmelerinin kaldırılması (bulgu N3).

Önce (karakterizasyon): `seed=None` sentezi, önbellek anahtarı ve yığınlı yol sessizce
9'a dönüyordu; `except TypeError` blokları seed'siz yeniden deniyordu; fısıltı
çökmesi yedeği öğenin seed'i yerine her zaman 9 kullanıyordu; oturum A/B deney
profilindeki seed'i sessizce 9 ile eziyordu. Sahte TTS motoru kullanılır (SAHTE).
"""

import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import backend.models as models_mod
from backend.batched_ode import BatchedODEEngine


class FakeTTS:
    """SAHTE TTS: `_synth_one` çağrılarının seed'ini kaydeder."""

    def __init__(self, raise_type_error=False):
        self.char_to_id = {ch: i for i, ch in enumerate("abcçdefgğhıijklmnoöprsştuüvyzABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ .,!?'0123456789")}
        self.seeds = []
        self.raise_type_error = raise_type_error

    def _synth_one(self, text, steps=32, seed=None):
        self.seeds.append(seed)
        if self.raise_type_error:
            raise TypeError("SAHTE: motor içi tür hatası")
        return (0.2 * np.sin(np.linspace(0, 200, 4800))).astype(np.float32)


def _models(fake):
    m = models_mod.Models()
    m.tts = fake
    m.batched_ode_engine = None
    return m


async def test_hf11_seedsiz_sentez_sessizce_9a_donmez():
    fake = FakeTTS()
    m = _models(fake)
    with pytest.raises(ValueError):
        await m.synth("Merhaba.", seed=None)
    assert fake.seeds == []
    await m.synth("Merhaba.", seed=42)
    assert fake.seeds and set(fake.seeds) == {42}


async def test_hf11_onbellek_anahtari_none_icin_9_varsaymaz():
    assert models_mod.Models._cache_key("Merhaba.", None) is None
    assert models_mod.Models._cache_key("Merhaba.", 9) != models_mod.Models._cache_key("Merhaba.", 42)


async def test_hf11_tur_hatasi_seedsiz_yeniden_denenmez():
    fake = FakeTTS(raise_type_error=True)
    m = _models(fake)
    with pytest.raises(TypeError):
        await m.synth("Merhaba.", seed=42)
    assert fake.seeds == [42]  # seed'siz ikinci deneme yok


async def test_hf11_yigin_yolu_seedsiz_reddeder_ve_fisilti_yedegi_oge_seedini_kullanir():
    seen = []
    calls = {"n": 0}

    def fallback(text, seed=None):
        seen.append(seed)
        calls["n"] += 1
        if calls["n"] == 1:
            return np.zeros(4800, np.float32)  # fısıltı çökmesi (sessiz)
        return (0.3 * np.sin(np.linspace(0, 400, 4800))).astype(np.float32)

    engine = BatchedODEEngine(batch_size=2, micro_window_ms=5.0, synth_fallback_fn=fallback)
    with pytest.raises(ValueError):
        await engine.synthesize_clause("Seed testi", seed=None)
    await engine.enqueue_clause("Seed testi", seed=42)
    assert seen and set(seen) == {42}


async def test_hf11_deney_profili_seedi_korunur_ve_olay_kaydedilir(tmp_path, monkeypatch):
    import json

    import backend.session as session_mod
    from backend.db import Base, Turn

    engine = create_engine("sqlite:///" + str(tmp_path / "hf11.db"), connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_mod, "Session", maker)
    monkeypatch.setattr("backend.dialogue.Session", maker)
    monkeypatch.setattr(
        "backend.ab_testing.assign_conversation_variant",
        lambda db, cid: {"experiment_id": "e1", "variant_id": "v42", "tts_seed": 42, "greeting_template": "standard"},
    )

    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(models_mod.models, "vad", Vad())

    async def emit(e):
        pass

    async def send(f):
        pass

    s = session_mod.VoiceSession("hf11", emit, send)
    try:
        assert s.tts_seed == 42
        with maker() as db:
            rows = db.scalars(select(Turn).where(Turn.conversation_id == s.id, Turn.role == "event")).all()
        events = [json.loads(r.metrics) for r in rows]
        assert any(e.get("event") == "voice_seed_profile" and e.get("seed") == 42 for e in events)
    finally:
        await s.close()
