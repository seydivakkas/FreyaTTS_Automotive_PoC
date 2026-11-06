"""P5: ses turu gecikmesi — sabit istem öneki, kural tabanlı çıkarım, TTS önbelleği, hotword önbelleği."""

import json
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import dialogue, models as models_mod
from backend.db import Base, CorporateAccount, Slot, Vehicle

pytestmark = pytest.mark.asyncio


@pytest.fixture
def local_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(dialogue, "Session", factory)
    with factory() as db:
        db.add_all(
            [
                Vehicle(description="Volkswagen Passat"),
                Vehicle(description="Renault Megane"),
                Slot(starts_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()),
            ]
        )
        db.commit()
    yield factory
    engine.dispose()


def _chat_recorder(monkeypatch, reply=None):
    calls = []

    async def chat(messages):
        calls.append(messages)
        yield json.dumps(reply or {})

    monkeypatch.setattr(dialogue.models, "chat", chat)
    return calls


# ---- 1. Sabit önek -----------------------------------------------------------------


async def test_prompt_is_constant_and_state_precedes_last_user(local_db, monkeypatch):
    calls = _chat_recorder(monkeypatch, {"customer": "Ali Veli"})
    d = dialogue.Dialogue("p5-prefix")
    base = d.build_prompt()
    d.customer = "Ali Veli"
    d.corporate_account_name = "Oto Galeri"
    d.options = [("s1", "07.11.2026 saat 10:00")]
    assert d.build_prompt() == base  # dinamik durum sistem istemine girmez
    d.history = [
        {"role": "user", "content": "eski 1"},
        {"role": "assistant", "content": "eski 2"},
        {"role": "user", "content": "yakın kullanıcı"},
        {"role": "assistant", "content": "x" * 500},
    ]
    await d.answer("bir şeyler söylüyorum")
    msgs = calls[0]
    assert msgs[0] == {"role": "system", "content": base}
    assert msgs[-1] == {"role": "user", "content": "bir şeyler söylüyorum"}
    assert msgs[-2]["role"] == "system" and msgs[-2]["content"].startswith("Durum:")
    assert "Ali Veli" in msgs[-2]["content"] and "1. seçenek" in msgs[-2]["content"]
    middle = msgs[1:-2]
    assert [m["role"] for m in middle] == ["user", "assistant"]  # yalnızca son 2 mesaj
    assert middle[0]["content"] == "yakın kullanıcı"
    assert len(middle[1]["content"]) < 500
    assert len(d.history) <= d.max_history_turns + 2  # history kendi sınırını korur


async def test_no_state_message_when_nothing_known(local_db, monkeypatch):
    calls = _chat_recorder(monkeypatch, {})
    d = dialogue.Dialogue("p5-nostate")
    await d.answer("anlaşılmaz bir cümle")
    assert [m["role"] for m in calls[0]] == ["system", "user"]


# ---- 2/3. Katalog ve ad kuralı -----------------------------------------------------


async def test_name_rule_and_catalog_skip_llm(local_db, monkeypatch):
    calls = _chat_recorder(monkeypatch)
    d = dialogue.Dialogue("p5-both")
    ans = await d.answer("Adım Ada Yılmaz. Aracım Volkswagen Passat.")
    assert calls == []
    assert d.customer == "Ada Yılmaz" and d.vehicle
    assert "1. seçenek" in ans


async def test_name_only_and_vehicle_only_skip_llm(local_db, monkeypatch):
    calls = _chat_recorder(monkeypatch)
    d = dialogue.Dialogue("p5-parts")
    assert "marka ve modelini" in await d.answer("Benim ismim Deniz Yılmaz")
    assert d.customer == "Deniz Yılmaz" and calls == []
    assert "1. seçenek" in await d.answer("Renault Megane")
    assert calls == []


async def test_vehicle_only_asks_name_without_llm(local_db, monkeypatch):
    calls = _chat_recorder(monkeypatch)
    d = dialogue.Dialogue("p5-vehicle-first")
    assert "Adınızı ve soyadınızı" in await d.answer("Aracım Volkswagen Passat")
    assert calls == [] and d.vehicle


async def test_name_with_unread_words_goes_to_llm(local_db, monkeypatch):
    calls = _chat_recorder(monkeypatch, {"customer": "Ada Yılmaz"})
    d = dialogue.Dialogue("p5-llm-name")
    await d.answer("Ada Yılmaz Volkswagen Passat")  # "Adım" kalıbı yok
    assert len(calls) == 1
    await d.answer("Adım atıyorum")  # tek sözcük: ad kuralı eşleşmez
    assert len(calls) == 2
    await d.answer("Adım Ada Yılmaz ve randevu tarihini ileri alalım")
    assert len(calls) == 3


async def test_ambiguous_or_missing_vehicle_goes_to_llm(local_db, monkeypatch):
    with local_db() as db:
        db.add(Vehicle(description="Volkswagen Passat Variant"))
        db.commit()
    calls = _chat_recorder(monkeypatch, {})
    d = dialogue.Dialogue("p5-ambiguous")
    await d.answer("Volkswagen Passat Variant")  # iki araç tam sözcük olarak geçer
    assert len(calls) == 1
    await d.answer("Tesla Model S")  # katalogda yok
    assert len(calls) == 2


async def test_name_with_catalog_word_goes_to_llm(local_db, monkeypatch):
    calls = _chat_recorder(monkeypatch, {})
    d = dialogue.Dialogue("p5-name-vehicle-word")
    await d.answer("Adım Ali Kaya Passat")
    assert len(calls) == 1


async def test_rule_vehicle_correction_resets_slot(local_db, monkeypatch):
    calls = _chat_recorder(monkeypatch)
    d = dialogue.Dialogue("p5-correction")
    await d.answer("Adım Ada Yılmaz. Aracım Volkswagen Passat.")
    first = d.vehicle
    d.slot = "eski-slot"
    ans = await d.answer("Renault Megane")
    assert calls == [] and d.vehicle != first and d.slot is None
    assert "seçenek" in ans


async def test_rule_corporate_name_routes_through_extract(local_db, monkeypatch):
    with local_db() as db:
        db.add(CorporateAccount(name="Oto Galeri", tax_id="123", discount_percent=10))
        db.commit()
    calls = _chat_recorder(monkeypatch)
    d = dialogue.Dialogue("p5-corp")
    await d.answer("Adım Ada Yılmaz. Oto Galeri. Aracım Volkswagen Passat.")
    assert calls == [] and d.corporate_account_name == "Oto Galeri"


async def test_selection_text_with_vehicle_goes_to_llm(local_db, monkeypatch):
    calls = _chat_recorder(monkeypatch, {})
    d = dialogue.Dialogue("p5-select-extra")
    await d.answer("Volkswagen Passat için birinci seçenek olsun")
    assert len(calls) == 1


# ---- 4. TTS önbelleği --------------------------------------------------------------


def _models_with_fake_synth():
    m = models_mod.Models()
    m.tts = object()
    calls = []

    def fake(text, seed=None):
        calls.append((text, seed))
        return np.full(100, float(len(calls)), np.float32)

    m._synth = fake
    return m, calls


async def test_synth_cache_hit_miss_copy_and_seed_default():
    m, calls = _models_with_fake_synth()
    key = m._cache_key("Merhaba, nasılsınız?", None)
    m._cache_put(key, np.ones(5, np.float32))
    a = await m.synth("Merhaba, nasılsınız?")
    assert calls == [] and a.tolist() == [1.0] * 5
    a[:] = 0  # çağıran önbelleği bozamaz
    assert (await m.synth("Merhaba, nasılsınız?", seed=9)).tolist() == [1.0] * 5  # None == 9
    await m.synth("Merhaba, nasılsınız?", seed=42)  # farklı seed: ıskalama
    assert calls == [("Merhaba, nasılsınız?", 42)]
    await m.synth("Başka cümle")
    assert len(calls) == 2


async def test_synth_cache_is_bounded():
    m, _ = _models_with_fake_synth()
    for i in range(models_mod.SYNTH_CACHE_MAX + 10):
        m._cache_put((f"cümle {i}", 9), np.zeros(2, np.float32))
    assert len(m._synth_cache) == models_mod.SYNTH_CACHE_MAX
    assert ("cümle 0", 9) not in m._synth_cache


async def test_prewarm_fills_cache_and_failure_is_not_fatal(monkeypatch):
    m, calls = _models_with_fake_synth()
    monkeypatch.setattr(m, "_prewarm_targets", lambda: [("Merhaba. Nasılsınız?", 9)])
    await m._prewarm_tts()
    assert calls[0][0] == "Merhaba."  # ısınma sentezi
    n = len(calls)
    wave = await m.synth("Merhaba.", seed=9)
    assert len(calls) == n and len(wave) == 100  # önbellekten

    broken, _ = _models_with_fake_synth()

    def boom(text, seed=None):
        raise RuntimeError("GPU yok")

    broken._synth = boom
    await broken._prewarm_tts()  # istisna yutulur (yalnızca log)
    assert not broken._synth_cache


# ---- 5. Hotword önbelleği ----------------------------------------------------------


async def test_hotwords_cached_ttl_and_invalidate(monkeypatch):
    m = models_mod.Models()
    queries = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def scalars(self, stmt):
            queries.append(1)

            class R:
                def all(_):
                    return ["Passat"]

            return R()

    monkeypatch.setattr(models_mod, "Session", FakeSession)
    assert m._catalog_hotwords() == ["Passat"]
    assert m._catalog_hotwords() == ["Passat"]
    assert len(queries) == 1
    m._hotwords_cache = (time.monotonic() - models_mod.HOTWORDS_TTL_SEC - 1, ["eski"])
    assert m._catalog_hotwords() == ["Passat"] and len(queries) == 2
    m.invalidate_hotwords()
    m._catalog_hotwords()
    assert len(queries) == 3
