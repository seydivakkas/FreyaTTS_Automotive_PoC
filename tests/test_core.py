import asyncio
import struct
from datetime import datetime, timezone, timedelta
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from backend.db import Base, Vehicle, Slot, Appointment, book
from backend.text import normalize, clauses
from backend.audio import frames, pace, resample, pcm
from backend.telephony import read_packet


@pytest.mark.parametrize(
    "source,expected",
    [
        (
            "Volkswagen Passat 1.5 TSI aracınız için sizi arıyorum.",
            "Folksvagen Passat bir nokta beş ti es ay",
        ),
        (
            "Aracınızın tahmini değeri 1.250.000 TL.",
            "bir milyon iki yüz elli bin Türk lirası",
        ),
        (
            "Sizin için yarın saat 14:30’da ekspertiz randevusu oluşturabiliriz.",
            "on dört otuzda",
        ),
        (
            "2023 model Nissan Qashqai 1.5 e-Power aracınızın 145.000 km’deki ekspertiz fiyatı 1450000 ₺!",
            "yüz kırk beş bin kilometredeki",
        ),
        ("Saat 15:00'da", "on beşte"),
        ("saat 14.30'da", "on dört otuzda"),
        ("31.10.2026", "otuz bir ekim iki bin yirmi altı"),
        ("34 ABC 123", "otuz dört a be ce yüz yirmi üç"),
        ("1,6 TDI motor", "bir nokta altı te de i motor"),
        ("2.2 CDI motor", "iki nokta iki ce de i motor"),
        ("Randevu 2026-11-03 tarihinde", "Randevu üç kasım iki bin yirmi altı tarihinde"),
        ("Teklif 2.035.000 TRY oldu", "iki milyon otuz beş bin Türk lirası oldu"),
        ("Citroën C3 var", "Sitroen ce üç var"),
        ("BMW X5 var", "iks beş var"),
        ("Volvo XC40 var", "Volvo iks ce kırk var"),
        ("Audi A3'ün raporu", "Audi a üçün raporu"),
        ("Kod P0420 geldi", "pe sıfır dört iki sıfır geldi"),
        ("Araç 4x4 sürüşlü", "Araç dört çeker sürüşlü"),
        ("Tip e-CVT oldu", "Tip i ce ve te oldu"),
        ("AWD çekiş var", "a ve de çekiş var"),
        ("Dış sıcaklık −5 °C.", "eksi beş derece santigrat"),
        ("Mégane Coupé", "Megaan Coupe"),
        ("Town & Country", "Tovn ve Country"),
    ],
)
def test_normalization(source, expected):
    assert expected in normalize(source)["normalized"]


def test_unknown_character_is_reported_and_speech_survives(caplog):
    result = normalize("Araç 🚗 servise hazır.")
    assert result["source"] == "Araç 🚗 servise hazır."
    assert result["normalized"] == "Araç servise hazır."
    assert "U+1F697" in result["warnings"][-1]
    assert "f4.char_dropped codepoints=U+1F697" in caplog.text
    with pytest.raises(ValueError, match="Seslendirilebilir metin bulunamadı"):
        normalize("🚗")


@pytest.mark.parametrize(
    "source,expected",
    [
        ("1250000 TL'ye", "bir milyon iki yüz elli bin Türk lirasına"),
        ("850.500,75 TL'ye", "sekiz yüz elli bin beş yüz lira yetmiş beş kuruşa"),
        ("1,5 TL", "bir lira elli kuruş"),
        ("5 TL mi?", "beş Türk lirası mı?"),
        ("4'üncü", "dördüncü"),
    ],
)
def test_money_suffixes(source, expected):
    assert normalize(source)["normalized"] == expected


def test_phrase_not_split():
    phrase = "bir milyon iki yüz elli bin Türk lirası"
    assert any(phrase in c for c, p in clauses("Aracınızın fiyatı " + phrase + "."))


def test_long_automotive_sentence_preserves_number_groups():
    source = "2023 model Nissan Qashqai 1.5 e-Power aracınızın 145.000 km'deki ekspertiz fiyatı 1.450.000 TL'dir!"
    parts = [c for c, p in clauses(normalize(source)["normalized"])]
    assert len(parts) >= 3 and all(len(p.split()) <= 15 for p in parts)
    for phrase in [
        "bir nokta beş i pavır",
        "yüz kırk beş bin kilometredeki",
        "bir milyon dört yüz elli bin Türk lirasıdır",
    ]:
        assert any(phrase in p for p in parts)


def test_audio():
    x = np.sin(2 * np.pi * 440 * np.arange(48000) / 48000).astype(np.float32) * 0.5
    y = resample(x, 48000, 8000)
    assert len(y) == 8000 and np.max(abs(y)) < 1
    data = pcm(y) + b"\x01\x02"
    f = list(frames(data))
    assert all(len(p) == 320 for p in f)
    assert b"".join(f).startswith(data)


async def test_packets_fragmented():
    reader = asyncio.StreamReader()
    packet = struct.pack("!BH", 0x10, 4) + b"abcd"

    async def feed():
        for b in packet:
            reader.feed_data(bytes([b]))
            await asyncio.sleep(0)

    task = asyncio.create_task(feed())
    assert await read_packet(reader) == (0x10, b"abcd")
    await task


async def test_packet_disconnect():
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x10\x00")
    reader.feed_eof()
    with pytest.raises(asyncio.IncompleteReadError):
        await read_packet(reader)


async def test_pacing_cancel_and_no_burst():
    t = [0.0]
    times = []
    sleeps = []

    async def send(frame):
        times.append(t[0])
        t[0] += 0.5 if len(times) == 1 else 0

    async def sleep(delay):
        sleeps.append(delay)
        t[0] += delay

    await pace(
        b"x" * 1000, send, lambda: len(times) >= 3, clock=lambda: t[0], sleep=sleep
    )
    assert len(times) == 3 and times[1] - times[0] >= 0.52 and min(sleeps) >= 0.019


def test_atomic_booking(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "test.db"))
    Base.metadata.create_all(engine)
    Factory = sessionmaker(engine)
    with Factory() as db:
        v = Vehicle(description="Passat")
        s = Slot(starts_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        db.add_all([v, s])
        db.commit()
        args = dict(
            slot_id=s.id,
            vehicle_id=v.id,
            customer="Ada Yılmaz",
            idempotency_key="request-1",
        )
        with pytest.raises(ValueError):
            book(db, **args, confirmed=False)
        one = book(db, **args, confirmed=True)
        assert book(db, **args, confirmed=True).id == one.id
        args["idempotency_key"] = "request-2"
        with pytest.raises(IntegrityError):
            book(db, **args, confirmed=True)
        db.rollback()
        assert db.query(Appointment).count() == 1
    engine.dispose()
