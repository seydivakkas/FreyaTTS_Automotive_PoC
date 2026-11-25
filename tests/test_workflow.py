import asyncio
import json
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base, Vehicle, Slot, Appointment
import backend.dialogue as dialogue
from backend.models import Models


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "flow.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(dialogue, "Session", factory)
    with factory() as db:
        v = Vehicle(description="Volkswagen Passat")
        s = Slot(starts_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        db.add_all([v, s])
        db.commit()
    yield factory
    engine.dispose()


async def test_confirmed_workflow_and_unknown_price(local_db, monkeypatch):
    async def chat(messages):
        text = messages[-1]["content"]
        yield json.dumps(
            {
                "customer": "Ada Yılmaz",
                "vehicle_description": "Volkswagen Passat",
                "selected_option": 1 if text == "birinci seçenek" else None,
            }
        )

    monkeypatch.setattr(dialogue.models, "chat", chat)
    d = dialogue.Dialogue("test-confirmation")
    answer = await d.answer("Ada Yılmaz Volkswagen Passat")
    assert "Kayıtlı fiyat bulunmuyor" in answer
    answer = await d.answer("birinci seçenek")
    assert "onaylıyor musunuz" in answer
    assert "Volkswagen Passat" in answer
    with local_db() as db:
        assert db.query(Appointment).count() == 0
    assert "oluşturuldu" in await d.answer("Evet, onaylıyorum.")
    with local_db() as db:
        assert db.query(Appointment).count() == 1


async def test_negative_confirmation_and_retries(local_db):
    d = dialogue.Dialogue("negative")
    d.awaiting = True
    assert "oluşturmadım" in await d.answer("hayır")
    with local_db() as db:
        assert db.query(Appointment).count() == 0
    for _ in range(3):
        await d.answer("")
    assert d.done and d.retries == 3


async def test_unknown_booking_result_never_claims_confirmation(local_db, monkeypatch):
    from automotive_voice.dialogue.models import BookingStatus

    def unavailable(*args, **kwargs):
        raise RuntimeError("local database unavailable")

    monkeypatch.setattr(dialogue, "book", unavailable)
    d = dialogue.Dialogue("unknown-booking")
    d.customer = "Test"
    d.vehicle = "test"
    d.slot = "test"
    d.awaiting = True
    answer = await d.answer("Evet, evet. Onaylıyorum.")
    assert "doğrulayamadım" in answer
    assert d.booking_status == BookingStatus.UNKNOWN and d.done and not d.confirmed
    with local_db() as db:
        assert db.query(Appointment).count() == 0


async def test_synthesis_bounded_and_cancellation(monkeypatch):
    import threading

    m = Models()
    m.tts = object()
    started = threading.Event()
    release = threading.Event()
    executed = []

    # H01.10: seed anahtar sözcükle verilir; seed'siz sentez ve TypeError yedeği yok.
    def slow(text, seed=None):
        started.set()
        release.wait(5)
        executed.append(text)
        return text

    monkeypatch.setattr(m, "_synth", slow)
    first = asyncio.create_task(m.synth("old", seed=9))
    await asyncio.to_thread(started.wait, 2)
    second = asyncio.create_task(m.synth("new", seed=9))
    await asyncio.sleep(0.01)
    with pytest.raises(RuntimeError, match="kuyruğu dolu"):
        await m.synth("overflow", seed=9)
    first.cancel()
    await asyncio.sleep(0.01)
    assert m.pending == 2
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert await second == "New." and executed == ["Old.", "New."] and m.pending == 0


async def test_multi_turn_sliding_window_and_entity_memory(local_db, monkeypatch):
    """Verify that Dialogue remembers entities across turns and supports repeat_options."""
    responses = {
        "Benim adım Deniz Yılmaz": {
            "customer": "Deniz Yılmaz",
            "vehicle_description": None,
            "selected_option": None,
            "repeat_options": None,
        },
        "Volkswagen Passat": {
            "customer": None,
            "vehicle_description": "Volkswagen Passat",
            "selected_option": None,
            "repeat_options": None,
        },
        "Seçenekleri tekrar eder misiniz?": {
            "customer": None,
            "vehicle_description": None,
            "selected_option": None,
            "repeat_options": True,
        },
        "İlk seçenek": {
            "customer": None,
            "vehicle_description": None,
            "selected_option": 1,
            "repeat_options": None,
        },
    }

    async def chat(messages):
        user_msg = messages[-1]["content"]
        extracted = responses.get(user_msg, {})
        yield json.dumps(extracted)

    monkeypatch.setattr(dialogue.models, "chat", chat)
    d = dialogue.Dialogue("multi-turn-test", max_history_turns=6)
    d.record_turn(
        "assistant",
        "Merhaba, ekspertiz randevusu için yardımcı olabilirim. Adınızı ve aracınızı söyler misiniz?",
    )

    # Turn 1: Only name
    ans1 = await d.answer("Benim adım Deniz Yılmaz")
    assert d.customer == "Deniz Yılmaz"
    assert "marka ve modelini" in ans1

    # Turn 2: Only vehicle description
    ans2 = await d.answer("Volkswagen Passat")
    assert d.customer == "Deniz Yılmaz"
    assert len(d.options) > 0
    assert "seçenek" in ans2

    # Turn 3: User asks to repeat options
    ans3 = await d.answer("Seçenekleri tekrar eder misiniz?")
    assert "seçenek" in ans3
    assert d.retries == 0

    # Turn 4: User selects first option
    ans4 = await d.answer("İlk seçenek")
    assert d.awaiting
    assert "Deniz Yılmaz" in ans4
    assert "Volkswagen Passat" in ans4
    assert "onaylıyor musunuz" in ans4

    # Turn 5: User confirms
    ans5 = await d.answer("Evet, onaylıyorum.")
    assert "oluşturuldu" in ans5
    assert d.confirmed and d.done

    with local_db() as db:
        app = db.query(Appointment).filter_by(customer="Deniz Yılmaz").first()
        assert app is not None
        assert app.confirmed


async def test_multi_turn_vehicle_correction(local_db, monkeypatch):
    """Verify that in-call vehicle correction switches the vehicle and resets pending slot."""
    with local_db() as db:
        v2 = Vehicle(description="Renault Megane", plate="06RN01")
        db.add(v2)
        db.commit()

    responses = {
        "Adım Ali Kaya Passat": {
            "customer": "Ali Kaya",
            "vehicle_description": "Passat",
            "selected_option": None,
            "repeat_options": None,
        },
        "Pardon aracım Renault Megane olacaktı": {
            "customer": None,
            "vehicle_description": "Renault Megane",
            "selected_option": None,
            "repeat_options": None,
        },
    }

    async def chat(messages):
        user_msg = messages[-1]["content"]
        yield json.dumps(responses.get(user_msg, {}))

    monkeypatch.setattr(dialogue.models, "chat", chat)
    d = dialogue.Dialogue("correction-test")

    ans1 = await d.answer("Adım Ali Kaya Passat")
    assert d.customer == "Ali Kaya"
    assert "seçenek" in ans1

    # Switch vehicle
    ans2 = await d.answer("Pardon aracım Renault Megane olacaktı")
    assert d.customer == "Ali Kaya"
    assert "seçenek" in ans2
    assert d.slot is None  # Any prior slot is cleared


def test_dialogue_history_bounded():
    """Verify that history does not exceed max_history_turns."""
    d = dialogue.Dialogue("history-bounded", max_history_turns=4)
    for i in range(10):
        d.record_turn("user", f"Mesaj {i}")
        d.record_turn("assistant", f"Yanıt {i}")
    assert len(d.history) == 4
    assert d.history[-1]["content"] == "Yanıt 9"


async def test_corporate_voice_dialogue_booking(local_db, monkeypatch):
    """Verify that the assistant recognizes corporate dealership and books with discounted credit."""
    from backend.db import CorporateAccount, CorporateLedger, Quote

    with local_db() as db:
        v = db.query(Vehicle).first()
        # Add 2.000 TL quote
        db.add(Quote(vehicle_id=v.id, amount_kurus=200000))
        # Add corporate dealership account with 20% discount
        corp = CorporateAccount(
            name="Özdemir Galeri",
            tax_id="9998887770",
            credit_limit_kurus=5000000,
            discount_percent=20,
            active=True,
        )
        db.add(corp)
        db.commit()
        corp_id = corp.id

    responses = {
        "Özdemir Galeri Serkan Passat": {
            "customer": "Serkan",
            "corporate_name": "Özdemir Galeri",
            "vehicle_description": "Passat",
            "selected_option": None,
            "repeat_options": None,
        },
        "Birinci seçenek": {
            "customer": None,
            "corporate_name": None,
            "vehicle_description": None,
            "selected_option": 1,
            "repeat_options": None,
        },
    }

    async def chat(messages):
        user_msg = messages[-1]["content"]
        yield json.dumps(responses.get(user_msg, {}))

    monkeypatch.setattr(dialogue.models, "chat", chat)
    d = dialogue.Dialogue("corp-dialogue-test")

    # Turn 1: Dealership intro
    ans1 = await d.answer("Özdemir Galeri Serkan Passat")
    assert d.corporate_account_id == corp_id
    assert "Özdemir Galeri kurumsal anlaşmalı fiyatı 1600,00 TL" in ans1
    assert "1. seçenek" in ans1

    # Turn 2: Option selection
    ans2 = await d.answer("Birinci seçenek")
    assert d.awaiting
    assert "Serkan" in ans2
    assert "onaylıyor musunuz" in ans2

    # Turn 3: Confirmation
    ans3 = await d.answer("Evet, onaylıyorum.")
    assert "Özdemir Galeri kurumsal cari hesabınıza işlenerek oluşturuldu" in ans3
    assert d.confirmed and d.done

    # Verify database state
    with local_db() as db:
        acc = db.get(CorporateAccount, corp_id)
        assert acc.balance_kurus == 160000  # 2000 TL - %20 = 1600 TL
        appt = db.query(Appointment).filter_by(corporate_account_id=corp_id).first()
        assert appt is not None
        assert appt.billed_amount_kurus == 160000
        ledger = db.query(CorporateLedger).filter_by(account_id=corp_id).all()
        assert len(ledger) == 1
        assert ledger[0].entry_type == "charge"
        assert ledger[0].amount_kurus == 160000


async def test_vehicle_inspection_history_dialogue(local_db, monkeypatch):
    """Verify that assistant speaks past inspection record when presenting options."""
    from backend.db import InspectionReport

    with local_db() as db:
        v = db.query(Vehicle).first()
        # Add past inspection report
        report = InspectionReport(
            vehicle_id=v.id,
            summary="Sol ön kapı boyalı, yürüyen aksam kusursuz.",
            mileage_km=90000,
            score=91,
        )
        db.add(report)
        db.commit()

    responses = {
        "Caner Yılmaz Passat": {
            "customer": "Caner Yılmaz",
            "vehicle_description": "Passat",
            "selected_option": None,
            "repeat_options": None,
        },
    }

    async def chat(messages):
        user_msg = messages[-1]["content"]
        yield json.dumps(responses.get(user_msg, {}))

    monkeypatch.setattr(dialogue.models, "chat", chat)
    d = dialogue.Dialogue("history-announcement-test")

    ans = await d.answer("Caner Yılmaz Passat")
    assert "Bu aracın sistemimizde daha önce 1 adet ekspertiz kaydı bulunuyor (son puanı 91)" in ans
    assert "seçenek" in ans
