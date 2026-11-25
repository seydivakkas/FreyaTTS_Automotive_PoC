"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ. Ayrıntı: LICENSE.

H01.03 — arayan kimlik doğrulaması (ADR-F3-01, kabul edildi): HF03, HF04, HF18.

Önce (karakterizasyon): arayan numarasıyla (hatta yalnızca söylenen adla) bulunan
profilden garanti ve bakım geçmişi doğrudan okunuyordu; her yeni arayan için arama
başında profil oluşturuluyordu; plaka, telefon, garanti ve bakım geçmişi LLM durum
mesajına giriyordu.

ADR-F3-01: telefon eşleşmesi + doğum yılı; kayıtta doğum yılı yoksa plakanın son 3–4
hanesi; en fazla 3 deneme; ipucu yok; değerler LLM bağlamında ve günlükte yok.
PoC veritabanında doğum yılı alanı yok (M00 DATABASE_INVENTORY) → plaka yolu sınanır;
doğum yılı yolu profil nesnesine geçici öznitelik verilerek sınanır.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend import dialogue
from backend.db import Base, CallerProfile

PHONE = "05321234567"
PLATE = "61 TS 061"
HISTORY = [{"date": "2026-09-12", "km": 45000, "item": "Ön fren balatası değişimi"}]


@pytest.fixture
def mem_db(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "kimlik.db"), connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(dialogue, "Session", maker)
    yield maker
    engine.dispose()


def _profile(maker):
    with maker() as db:
        p = CallerProfile(
            name="Ahmet Yılmaz",
            phone=PHONE,
            plate=PLATE,
            vehicle_model="Peugeot 3008",
            warranty_expires_at=(datetime.now(timezone.utc) + timedelta(days=300)).strftime("%Y-%m-%d"),
            warranty_status="active",
            maintenance_history_json=json.dumps(HISTORY),
        )
        db.add(p)
        db.commit()
        return p


def _profile_count(maker):
    with maker() as db:
        return db.scalar(select(func.count()).select_from(CallerProfile))


PRIVATE_MARKERS = ("Peugeot", "garantisi", "2026-09-12", "45000", "balata", "Ahmet", "061")


def _no_private(ans):
    return not any(m.lower() in ans.lower() for m in PRIVATE_MARKERS)


async def test_hf04_yeni_arayan_icin_profil_olusturulmaz(mem_db, fake_llm):
    """HF04: arama başında (ve numara/plaka söylendiğinde) profil tablosuna satır eklenmez."""
    fake_llm.reply({})  # SAHTE LLM
    d = dialogue.Dialogue("hf04", customer_phone="05559998877")
    await d.answer("Numaram 0555 999 88 77, plakam 34 ABC 123")
    assert _profile_count(mem_db) == 0
    assert d.customer is None  # profil adı doğrulamasız müşteriye atanmaz


async def test_hf03_dogrulamasiz_arayana_ozel_kayit_soylenmez(mem_db):
    """HF03: numara eşleşse bile doğrulama olmadan garanti/bakım içeriği söylenmez."""
    _profile(mem_db)
    d = dialogue.Dialogue("hf03-a", customer_phone=PHONE)
    assert d.customer is None
    ans = await d.answer("Aracımın garantisi devam ediyor mu?")
    assert _no_private(ans)
    assert "plaka" in ans.lower()  # ADR-F3-01: doğum yılı yok → plaka son haneleri


async def test_hf03_yanlis_bilgide_ipucu_yok_uc_denemede_kilit_ve_aktarim(mem_db, fake_llm):
    """HF03 + HF18: yanlış ikinci bilgi → ipucu yok; 3. yanlıştan sonra kilit + operatör önerisi."""
    fake_llm.reply({})  # SAHTE LLM (kilit sonrası serbest söz)
    _profile(mem_db)
    d = dialogue.Dialogue("hf03-b", customer_phone=PHONE)
    await d.answer("Aracımın garantisi devam ediyor mu?")
    a1 = await d.answer("999")
    a2 = await d.answer("1234")
    assert _no_private(a1) and _no_private(a2)
    assert "son hane" not in a1.lower() and "ile bitiyor" not in a1.lower()
    a3 = await d.answer("555")
    assert _no_private(a3)
    assert "temsilci" in a3.lower() or "operatör" in a3.lower()
    # Kilitlendikten sonra doğru bilgi de kabul edilmez (o görüşmede özel kayıt kapalı).
    await d.answer("Aracımın garantisi devam ediyor mu?")
    a5 = await d.answer("061")
    assert _no_private(a5)


async def test_hf03_ad_soyleyerek_baskasinin_kaydina_erisilemez(mem_db):
    """Söylenen adla profil eşleştirilmez (numara farklı)."""
    _profile(mem_db)
    d = dialogue.Dialogue("hf03-c", customer_phone="05000000000")
    d.customer = "Ahmet Yılmaz"
    ans = await d.answer("Geçen sefer konuştuğumuz balata değişimi yapılmış mıydı?")
    assert "Kayıtlarımıza göre" not in ans and "2026-09-12" not in ans


async def test_hf18_dogru_telefon_ve_plaka_son_haneleri_ile_ozel_kayit_okunur(mem_db, caplog):
    """HF18: doğru telefon + plaka son 3 hanesi → garanti okunur; değer LLM bağlamında ve günlükte yok."""
    _profile(mem_db)
    caplog.set_level(logging.DEBUG)
    d = dialogue.Dialogue("hf18-a", customer_phone=PHONE)
    challenge = await d.answer("Aracımın garantisi devam ediyor mu?")
    assert "plaka" in challenge.lower()
    ans = await d.answer("061")
    assert "devam etmektedir" in ans
    # Doğrulandıktan sonra bakım geçmişi de okunur.
    ans2 = await d.answer("Geçen sefer konuştuğumuz balata değişimi yapılmış mıydı?")
    assert "balata" in ans2.lower()
    # Değerler LLM bağlamında yok
    llm_text = json.dumps(d._llm_messages("Merhaba"), ensure_ascii=False)
    for secret in ("061", PLATE, PHONE, "2026-09-12", "45000"):
        assert secret not in llm_text, secret
    # Günlükte yok
    assert "061" not in caplog.text and PLATE not in caplog.text


async def test_hf18_dogum_yili_kayitta_varsa_once_dogum_yili_sorulur(mem_db, monkeypatch):
    """HF18: kayıtta doğum yılı varsa (ADR birincil yol) doğum yılı sorulur ve doğrulanır."""
    _profile(mem_db)
    from backend import caller_memory

    real_find = caller_memory.find_caller_profile

    def with_birth_year(db, phone=None):
        p = real_find(db, phone=phone)
        if p is not None:
            p.birth_year = 1985  # PoC şemasında alan yok; ileride eklenecek alanı taklit eder
        return p

    monkeypatch.setattr(caller_memory, "find_caller_profile", with_birth_year)
    d = dialogue.Dialogue("hf18-b", customer_phone=PHONE)
    challenge = await d.answer("Aracımın garantisi devam ediyor mu?")
    assert "doğum yıl" in challenge.lower()
    wrong = await d.answer("1990")
    assert _no_private(wrong)
    ok = await d.answer("1985")
    assert "devam etmektedir" in ok


async def test_hf18_ozel_kayit_degerleri_llm_durum_mesajinda_yok(mem_db):
    p = _profile(mem_db)
    d = dialogue.Dialogue("hf18-c", customer_phone=PHONE)
    d.caller_profile = p
    state = d.build_state_message() or ""
    for secret in (PLATE, PHONE, "Peugeot", "balata", "Garanti"):
        assert secret not in state, secret
