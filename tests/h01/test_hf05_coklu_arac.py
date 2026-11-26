"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ. Ayrıntı: LICENSE.

H01.04 — HF05: çoklu araç idempotency (bulgu P7).

Önce (karakterizasyon, M00/H01 bulgusu): her araç onayı aynı işlem anahtarını
(`idempotency_key = görüşme kimliği`) kullanıyordu; ikinci araç onayında `book()`
"İşlem anahtarı farklı bir istekte kullanılmış" hatası verip ikinci randevu
oluşmuyordu. Ayrıca görüşme bittikten sonra her söze sabit "TEST-001" referansı
söyleniyordu ve "bir aracım daha var" isteği hiç işlenmiyordu.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.db import Appointment, Base, Slot, Vehicle
from backend.dialogue import Dialogue


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "hf05.db"), connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("backend.dialogue.Session", maker)
    monkeypatch.setattr(settings, "multi_vehicle_booking_enabled", True)
    yield maker
    engine.dispose()


def _slot(db, hours):
    s = Slot(starts_at=(datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(), duration_minutes=45)
    db.add(s)
    db.flush()
    return s


def _ready(d, vehicle_id, slot_id):
    d.customer = "Kemal Sunal"
    d.vehicle = vehicle_id
    d.slot = slot_id
    d.awaiting = True


async def test_hf05_iki_arac_iki_onay_iki_randevu_tekrar_yeni_kayit_uretmez(env):
    """HF05: iki araç, iki ayrı onay → iki randevu; aynı onayın tekrarı ikinci kayıt üretmez."""
    with env() as db:
        v1 = Vehicle(description="Volkswagen Passat 1.5 TSI", plate="34 VAG 01")
        v2 = Vehicle(description="Renault Megane 1.3 TCe", plate="34 REN 02")
        db.add_all([v1, v2])
        db.flush()
        s1, s2 = _slot(db, 24), _slot(db, 26)
        db.commit()

    d = Dialogue("hf05-cagri-1", customer_phone="05325556677")
    d.multi_vehicle_planned = True
    _ready(d, v1.id, s1.id)
    first = await d.answer("Evet, onaylıyorum.")
    assert "İlk aracınız için randevunuz oluşturuldu" in first

    _ready(d, v2.id, s2.id)
    d.multi_vehicle_planned = False
    second = await d.answer("Evet, onaylıyorum.")
    assert second.startswith("Randevunuz oluşturuldu. Referansınız ")
    assert "doğrulayamadım" not in second

    # Aynı onayın tekrarı (ör. ağ yeniden denemesi) yeni kayıt üretmez.
    again = await d.answer("Evet, onaylıyorum.")
    assert "Randevunuz oluşturulmuştur" in again
    with env() as db:
        rows = db.scalars(select(Appointment)).all()
    assert len(rows) == 2
    assert {r.vehicle_id for r in rows} == {v1.id, v2.id}
    assert len({r.idempotency_key for r in rows}) == 2


async def test_hf05_randevu_sonrasi_ikinci_arac_istegi_islenir(env):
    """Görüşme bitmeden "bir aracım daha var" → ikinci araç akışı açılır."""
    with env() as db:
        v1 = Vehicle(description="Dacia Duster 1.3 TCe", plate="34 DAC 55")
        db.add(v1)
        db.flush()
        s1 = _slot(db, 20)
        db.commit()

    d = Dialogue("hf05-cagri-2")
    _ready(d, v1.id, s1.id)
    booked = await d.answer("Evet, onaylıyorum.")
    assert booked.startswith("Randevunuz oluşturuldu.")
    nxt = await d.answer("Bir aracım daha var onun için de randevu alalım.")
    assert "diğer aracınızın marka ve modelini" in nxt.lower()
    assert d.done is False and d.customer == "Kemal Sunal"


async def test_hf05_randevu_olmadan_biten_gorusmede_sahte_referans_soylenmez(env):
    """Randevu oluşmadan biten görüşmede "Referansınız TEST-001" gibi uydurma makbuz yok."""
    d = Dialogue("hf05-cagri-3")
    d.done = True
    ans = await d.answer("Alo, randevum oluştu mu?")
    assert "Referans" not in ans and "oluşturulmuştur" not in ans
