"""Açık seçenek ifadeleri LLM olmadan ayrıştırılır; belirsizler LLM'e kalır."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.dialogue as dialogue
from backend.db import Appointment, Base, Slot, Vehicle
from backend.dialogue import parse_selected_option


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Birinci seçenek", 1),
        ("Birinci seçenek.", 1),
        ("birincisi olsun", 1),
        ("İlk seçenek", 1),
        ("1. seçenek", 1),
        ("1", 1),
        ("Bir numara", 1),
        ("Evet, birinci seçenek.", 1),
        ("İkinci seçenek lütfen", 2),
        ("2. seçenek", 2),
        ("İki numara olsun", 2),
        ("Üçüncü saat uygun", 3),
    ],
)
def test_explicit_choices_are_parsed(text, expected):
    assert parse_selected_option(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Evet",
        "Evet, onaylıyorum.",
        "Birinci değil ikinci",
        "Birinci seçenek olmasın",
        "ikinci el araç",
        "Bir saniye",
        "İki",
        "Aracım 1 numara",
        "Renault Megane",
        "Birinci seçenek olsun ama saati değiştirelim lütfen",
    ],
)
def test_ambiguous_text_goes_to_llm(text):
    assert parse_selected_option(text) is None


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "flow.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(dialogue, "Session", factory)
    with factory() as db:
        db.add(Vehicle(description="Renault Megane"))
        db.add(Slot(starts_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()))
        db.commit()
    yield factory
    engine.dispose()


def _patch_chat(monkeypatch, calls):
    async def chat(messages):
        calls.append(messages[-1]["content"])
        yield json.dumps({"customer": "Ali Yılmaz", "vehicle_description": "Renault Megane"})

    monkeypatch.setattr(dialogue.models, "chat", chat)


async def test_selection_skips_llm_and_still_requires_confirmation(local_db, monkeypatch):
    calls = []
    _patch_chat(monkeypatch, calls)
    d = dialogue.Dialogue("rule-selection")
    assert "1. seçenek" in await d.answer("Ali Yılmaz, Renault Megane")
    assert len(calls) == 1

    answer = await d.answer("Birinci seçenek")
    assert len(calls) == 1
    assert d.awaiting and "onaylıyor musunuz" in answer
    with local_db() as db:
        assert db.query(Appointment).count() == 0

    assert "oluşturuldu" in await d.answer("Evet, onaylıyorum.")
    with local_db() as db:
        assert db.query(Appointment).count() == 1


async def test_out_of_range_choice_is_rejected(local_db, monkeypatch):
    calls = []
    _patch_chat(monkeypatch, calls)
    d = dialogue.Dialogue("rule-range")
    await d.answer("Ali Yılmaz, Renault Megane")
    answer = await d.answer("Üçüncü seçenek")
    assert "Sunulan seçeneklerden" in answer
    assert not d.awaiting and d.slot is None


async def test_selection_before_options_goes_to_llm(local_db, monkeypatch):
    calls = []
    _patch_chat(monkeypatch, calls)
    d = dialogue.Dialogue("rule-no-options")
    await d.answer("Birinci seçenek")
    assert calls == ["Birinci seçenek"]
    assert not d.awaiting
