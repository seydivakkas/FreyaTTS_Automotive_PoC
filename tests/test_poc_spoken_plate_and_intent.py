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
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db import Appointment, Base, Quote, Slot, Vehicle
import backend.dialogue as dialogue
from backend.turkish_plate import TurkishPlateParser, extract_plate


# ---------------------------------------------------------------------------
# TEST FİKSTÜRÜ: POC DONDURULMUŞ TAKVİM VE ARAÇ VERİTABANI
# ---------------------------------------------------------------------------
@pytest.fixture
def poc_db(tmp_path, monkeypatch):
    """
    POC_CANLI_SES_VE_NIYET_PLANI.md Madde 67:
    - Corolla için standart ekspertiz bedeli 2.500 TL (250000 kuruş).
    - Yarın 09.00 dolu, 10.00 açık.
    - Taşıma / iptal için 11.00 aktif randevu.
    """
    engine = create_engine("sqlite:///" + str(tmp_path / "poc_flow.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(dialogue, "Session", factory)

    tomorrow = datetime.now(ZoneInfo("Europe/Istanbul")) + timedelta(days=1)
    t_09 = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()
    t_10 = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
    t_11 = tomorrow.replace(hour=11, minute=0, second=0, microsecond=0).isoformat()

    with factory() as db:
        corolla = Vehicle(description="Toyota Corolla", plate="")
        db.add(corolla)
        db.flush()

        quote = Quote(vehicle_id=corolla.id, amount_kurus=250000)
        db.add(quote)

        slot_09 = Slot(starts_at=t_09)
        slot_10 = Slot(starts_at=t_10)
        slot_11 = Slot(starts_at=t_11)
        db.add_all([slot_09, slot_10, slot_11])
        db.flush()

        # 09.00 slotu DOLU
        occupied_app = Appointment(
            slot_id=slot_09.id,
            vehicle_id=corolla.id,
            customer="Mevcut Müşteri",
            idempotency_key="occupied-09",
            confirmed=True,
            status="confirmed",
        )
        # 11.00 slotu iptal/taşıma testleri için mevcut randevu
        existing_app = Appointment(
            slot_id=slot_11.id,
            vehicle_id=corolla.id,
            customer="Seydi Eryılmaz",
            customer_phone="05000000001",
            idempotency_key="existing-11",
            confirmed=True,
            status="confirmed",
        )
        corolla.plate = "34 ABC 123"
        db.add_all([occupied_app, existing_app])
        db.commit()

    yield factory
    engine.dispose()


# ---------------------------------------------------------------------------
# BÖLÜM 1: TÜRKÇE SÖZLÜ PLAKA AYRIŞTIRMA VE HEDEF HARF DÜZELTME TESTLERİ
# ---------------------------------------------------------------------------
def test_spoken_plate_extraction():
    """Sözlü Türkçe şehir fonetik alfabesi ve sayıların plakaya dönüşümü."""
    # 34 Adana Bursa Ceyhan 123
    p1 = extract_plate("Otuz dört Adana Bursa Ceyhan yüz yirmi üç.")
    assert p1 == "34 ABC 123"

    # Sıfır altı Ankara Niğde Kars doksan dokuz
    p2 = extract_plate("Plakam sıfır altı Ankara Niğde Kars doksan dokuz")
    assert p2 == "06 ANK 99"

    # 35 İzmir Manisa 456
    p3 = extract_plate("otuz beş izmir manisa dört yüz elli altı")
    assert p3 == "35 İM 456" or p3 == "35 IM 456"

    # Çift harf söylemi ("a çift b")
    p4 = extract_plate("otuz dört adana çift bursa yüz yirmi üç")
    assert p4 == "34 ABB 123"

    # Yazılı standart plaka
    p5 = extract_plate("Yarın Corolla için randevu. Plakam 34 AB 123.")
    assert p5 == "34 AB 123"


def test_targeted_plate_letter_correction():
    """Hedefe yönelik harf, rakam ve il kodu düzeltmeleri."""
    # Harf değişimi: "C değil, Denizli’nin D’si" -> 34 ABC 123 -> 34 ABD 123
    c1 = TurkishPlateParser.correct_plate("34 ABC 123", "C değil, Denizli’nin D’si")
    assert c1 is not None
    assert c1.plate == "34 ABD 123"
    assert c1.is_correction is True

    # Kısaltılmış harf değişimi: "c değil d"
    c2 = TurkishPlateParser.correct_plate("34 ABC 123", "c değil d")
    assert c2 is not None
    assert c2.plate == "34 ABD 123"

    # Şehir bazlı harf değişimi: "ceyhan değil denizli"
    c3 = TurkishPlateParser.correct_plate("34 ABC 123", "ceyhan değil denizli")
    assert c3 is not None
    assert c3.plate == "34 ABD 123"

    # Harf ekleme: "34 AB 123" -> "Ceyhan’ın C’si de var" -> "34 ABC 123"
    c4 = TurkishPlateParser.correct_plate("34 AB 123", "Hayır, 34 ABC 123. Ceyhan’ın C’si de var.")
    assert c4 is not None
    assert c4.plate == "34 ABC 123"

    # Sayı / sonu düzeltme: "sonu 124"
    c5 = TurkishPlateParser.correct_plate("34 ABC 123", "sonu 124")
    assert c5 is not None
    assert c5.plate == "34 ABC 124"

    # İl kodu düzeltme: "34 değil 35"
    c6 = TurkishPlateParser.correct_plate("34 ABC 123", "34 değil 35")
    assert c6 is not None
    assert c6.plate == "35 ABC 123"


# ---------------------------------------------------------------------------
# BÖLÜM 2: POC ÇEKİRDEK CANLI SES VE DİYALOG DEMOSU (P0)
# Akış: Ekspertiz isteği -> Plaka söyleme -> Plaka düzeltme -> Erken 'evet' -> Açık onay -> Tek kayıt
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_poc_core_demo_flow(poc_db):
    """
    Kullanıcının ana PoC hedefi:
    Müşteri mikrofonda doğal Türkçeyle Corolla ekspertizi ister.
    Plakasını söyler: 'Otuz dört Adana Bursa Ceyhan yüz yirmi üç'.
    Düzeltir: 'C değil, Denizli’nin D’si'.
    Asistan güncel plakayı okuyup açık onay ister.
    'Evet, sizi duyuyorum' randevu yazdırmaz (mutations == 0).
    Açık onayda veritabanına tek kayıt düşer (34 ABD 123).
    """
    d = dialogue.Dialogue("POC-DEMO-LIVE-001")

    # Tur 1: Randevu isteği (Plaka henüz yok)
    r1 = await d.answer("Toyota Corolla için yarın ekspertiz randevusu istiyorum.")
    assert "Yarın 10.00 uygun" in r1
    assert "Plakanızı söyler misiniz" in r1
    with poc_db() as db:
        # Onay öncesi mutasyon 0 olmalı!
        assert db.query(Appointment).filter(Appointment.idempotency_key == "POC-DEMO-LIVE-001").count() == 0
    assert d.mutations_before_confirmation == 0

    # Tur 2: Sözlü plaka söyleme
    r2 = await d.answer("Otuz dört Adana Bursa Ceyhan yüz yirmi üç.")
    assert "34 ABC 123" in r2
    assert "Toyota Corolla" in r2
    assert "2.500 TL" in r2
    assert "onaylıyor musunuz" in r2
    with poc_db() as db:
        assert db.query(Appointment).filter(Appointment.idempotency_key == "POC-DEMO-LIVE-001").count() == 0

    # Tur 3: Hedefe yönelik plaka düzeltmesi ("C değil, Denizli’nin D’si")
    r3 = await d.answer("C değil, Denizli’nin D’si.")
    assert "34 ABD 123" in r3
    assert "onaylıyor musunuz" in r3
    assert d.plate == "34 ABD 123"
    with poc_db() as db:
        assert db.query(Appointment).filter(Appointment.idempotency_key == "POC-DEMO-LIVE-001").count() == 0

    # Tur 4: Erken "evet" / Ses kontrolü ("Evet, sizi duyuyorum") -> KESİNLİKLE RANDEVU OLUŞTURMAZ!
    r4 = await d.answer("Evet, sizi duyuyorum.")
    assert "Peki, devam edelim" in r4
    with poc_db() as db:
        # Guardrail kontrolü: mutations_before_confirmation == 0!
        assert db.query(Appointment).filter(Appointment.idempotency_key == "POC-DEMO-LIVE-001").count() == 0
    assert d.mutations_before_confirmation == 0

    # Tur 4b: İşlemi onaylamadığını belirtme
    r4b = await d.answer("Bu arada henüz hiçbir işlemi onaylamadım.")
    assert "henüz işlem yapmadım" in r4b
    with poc_db() as db:
        assert db.query(Appointment).filter(Appointment.idempotency_key == "POC-DEMO-LIVE-001").count() == 0

    # Tur 5: Açık onay ("Evet, onaylıyorum.") -> TEK VE DOĞRU KAYIT ATOMİK YAZILIR!
    r5 = await d.answer("Evet, onaylıyorum.")
    assert "Randevunuz oluşturuldu" in r5
    assert d.done is True
    assert d.plate_confirmed is True

    with poc_db() as db:
        apps = db.query(Appointment).filter(Appointment.idempotency_key == "POC-DEMO-LIVE-001").all()
        assert len(apps) == 1
        app = apps[0]
        # Doğru ve düzeltilmiş plaka ile kaydedildiği teyit edilir
        vehicle = db.get(Vehicle, app.vehicle_id)
        assert vehicle.plate == "34 ABD 123"
        assert app.status == "confirmed"

    # Tur 6: İkinci kez onay söylense bile idempotency sayesinde çift kayıt oluşmaz (duplicate == 0)
    await d.answer("Evet, onaylıyorum.")
    with poc_db() as db:
        assert db.query(Appointment).filter(Appointment.idempotency_key == "POC-DEMO-LIVE-001").count() == 1


# ---------------------------------------------------------------------------
# BÖLÜM 3: 512 YAZILI REGRESYON TEST AİLELERİ KONTROLÜ
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_family_plate_direct_correction(poc_db):
    """PLATE-DIRECT-1: Plaka ilk turda verilir, sonra 'Ceyhan’ın C’si de var' ile düzeltilir."""
    d = dialogue.Dialogue("PLATE-DIRECT-1")

    # Tur 1: Corolla + 34 AB 123
    r1 = await d.answer("Yarın Corolla için ekspertiz istiyorum. Plakam 34 AB 123.")
    assert "34 AB 123 olarak duydum" in r1

    # Tur 2: Düzeltme
    r2 = await d.answer("Hayır, 34 ABC 123. Ceyhan’ın C’si de var.")
    assert "34 ABC 123" in r2
    assert "onaylıyor musunuz" in r2

    # Tur 3: Onay
    r3 = await d.answer("Evet, onaylıyorum.")
    assert "Randevunuz oluşturuldu" in r3

    with poc_db() as db:
        app = db.query(Appointment).filter(Appointment.idempotency_key == "PLATE-DIRECT-1").one()
        vehicle = db.get(Vehicle, app.vehicle_id)
        assert vehicle.plate == "34 ABC 123"


@pytest.mark.asyncio
async def test_family_price_direct(poc_db):
    """PRICE-DIRECT-1: Fiyat sorusu ve koşullu randevu talebi."""
    d = dialogue.Dialogue("PRICE-DIRECT-1")

    r1 = await d.answer("Corolla ekspertizi kaç lira? Uygunsa yarın geleyim.")
    assert "Standart paket 2.500 TL" in r1
    assert "Yarın 10.00 müsait" in r1

    r2 = await d.answer("Devam edelim. Plakam 34 ABC 123.")
    assert "34 ABC 123" in r2
    assert "onaylıyor musunuz" in r2

    r3 = await d.answer("Evet, onaylıyorum.")
    assert "Randevunuz oluşturuldu" in r3

    with poc_db() as db:
        assert db.query(Appointment).filter(Appointment.idempotency_key == "PRICE-DIRECT-1").count() == 1


@pytest.mark.asyncio
async def test_family_full_direct(poc_db):
    """FULL-DIRECT-1: Dolu saat (09.00) istenince alternatif (10.00) sunumu."""
    d = dialogue.Dialogue("FULL-DIRECT-1")

    r1 = await d.answer("Corolla için yarın saat dokuzda ekspertiz istiyorum.")
    assert "09.00 dolu" in r1
    assert "10.00 müsait" in r1

    r2 = await d.answer("10.00 olur, plakam 34 ABC 123.")
    assert "34 ABC 123" in r2
    assert "onaylıyor musunuz" in r2

    r3 = await d.answer("Evet, onaylıyorum.")
    assert "Randevunuz oluşturuldu" in r3

    with poc_db() as db:
        assert db.query(Appointment).filter(Appointment.idempotency_key == "FULL-DIRECT-1").count() == 1


@pytest.mark.asyncio
async def test_family_car_direct(poc_db):
    """CAR-DIRECT-1: Yalnızca marka söyleyince model sorgulanması."""
    d = dialogue.Dialogue("CAR-DIRECT-1")

    r1 = await d.answer("Toyota için yarına ekspertiz istiyorum.")
    assert "Toyota’nın modeli nedir" in r1

    r2 = await d.answer("Corolla. Plakam 34 ABC 123.")
    assert "34 ABC 123" in r2
    assert "onaylıyor musunuz" in r2

    r3 = await d.answer("Evet, onaylıyorum.")
    assert "Randevunuz oluşturuldu" in r3


@pytest.mark.asyncio
async def test_family_info_direct(poc_db):
    """INFO-DIRECT-1: Sadece fiyat bilgisi isteme, randevu istememe -> 0 DB mutasyonu."""
    d = dialogue.Dialogue("INFO-DIRECT-1")

    r1 = await d.answer("Corolla ekspertiz fiyatı nedir? Şimdilik randevu istemiyorum.")
    assert "Standart paket 2.500 TL" in r1
    assert "Başka bir sorunuz var mı" in r1

    r2 = await d.answer("Hayır, teşekkürler.")
    assert "Rica ederim" in r2

    with poc_db() as db:
        assert db.query(Appointment).filter(Appointment.idempotency_key == "INFO-DIRECT-1").count() == 0


@pytest.mark.asyncio
async def test_family_cancel_direct(poc_db):
    """CANCEL-DIRECT-1: İptalden vazgeçme -> Randevu silinmez, 0 mutasyon."""
    d = dialogue.Dialogue("CANCEL-DIRECT-1")

    r1 = await d.answer("Corolla randevumu iptal etmek istiyorum.")
    assert "plaka" in r1 and "telefon" in r1

    r2 = await d.answer("34 ABC 123 ve 0500 000 00 01.")
    assert "iptal etmemi onaylıyor musunuz" in r2 or "iptal etmek istediğinizi" in r2

    r3 = await d.answer("Hayır, kalsın.")
    assert "geçerlidir" in r3 or "devam ediyor" in r3

    with poc_db() as db:
        # Randevu iptal edilmemeli!
        app = db.query(Appointment).filter(Appointment.idempotency_key == "existing-11").one()
        assert app.status == "confirmed"


# ---------------------------------------------------------------------------
# BÖLÜM 4: KATMAN BAZLI HATA VE İŞLEM İZLEME (TURN TRACE) TESTİ
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_turn_trace_layered_attribution(poc_db):
    """
    Her diyalog turunda TurnTrace katman verisinin eksiksiz oluştuğunu doğrular:
    - turn_id
    - timestamp
    - input_text
    - intent
    - plate_candidate
    - state_before & state_after
    - db_mutations
    """
    d = dialogue.Dialogue("TRACE-TEST-001")
    await d.answer("Toyota Corolla için yarın ekspertiz randevusu istiyorum.")

    trace = d.last_turn_trace
    assert trace is not None
    assert trace["turn_id"].startswith("TRACE-TEST-001-")
    assert trace["input_text"] == "Toyota Corolla için yarın ekspertiz randevusu istiyorum."
    assert trace["intent"] == "slot_offered_ask_plate"
    assert trace["db_mutations"] == 0
    assert trace["mutations_before_confirmation"] == 0
