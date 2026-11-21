# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Unit and integration tests for Automotive Intent Engine & Action Dispatch (Milestone 2).

Test covers:
  1. M01-M11 Emergency life-safety override guardrails
  2. Lift & bay station capacity dispatch
  3. OBD-II DTC diagnostic fault analysis
  4. Technician voice dictation processing
  5. WhatsApp expertise report delivery
  6. Dynamic valuation vs. service package pricing differentiation
  7. Caller profile memory context & multi-turn reference resolution
"""

import json
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db import Base, CallerProfile, InspectionLift
import backend.dialogue as dialogue
from backend.automotive_dispatch import (
    dispatch_emergency,
    dispatch_lift_status,
    dispatch_obd_dtc,
    dispatch_technician_dictation,
    dispatch_whatsapp_report,
    dispatch_valuation_or_pricing,
)


@pytest.fixture
def dispatch_db(tmp_path, monkeypatch):
    """Geçici SQLite veritabanı sağlar ve default lift kayıtlarını ekler."""
    db_file = tmp_path / "test_dispatch.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(dialogue, "Session", factory)

    # Örnek lift verisi ekle
    with factory() as db:
        l1 = InspectionLift(id="LIFT-1", name="Lift 1", lift_number=1, status="idle")
        l2 = InspectionLift(id="LIFT-2", name="Lift 2", lift_number=2, status="busy")
        db.add_all([l1, l2])
        db.commit()

    yield factory
    engine.dispose()


@pytest.mark.asyncio
async def test_emergency_override_guardrail(dispatch_db):
    """M01/M03/M07/M11: Can güvenliği ifadeleri derhal operatör aktarımı ve güvenlik uyarısı tetikler."""
    d = dialogue.Dialogue("test-emg-1", mode="inbound")
    ans = await d.answer("Frenler tutmuyor kaza yapacağım!")

    assert d.inbound_intent == "roadside_emergency"
    assert d.transfer_requested is True
    assert "Acil durum uyarısı" in ans
    assert "dörtlü" in ans.lower()
    assert "yol yardım" in ans.lower()

    # Yangın ve duman kontrolü
    d2 = dialogue.Dialogue("test-emg-2", mode="inbound")
    ans2 = await d2.answer("Kaputtan duman çıkıyor araç alev aldı!")
    assert d2.inbound_intent == "roadside_emergency"
    assert d2.transfer_requested is True


@pytest.mark.asyncio
async def test_lift_status_dispatch(dispatch_db):
    """Lift ve muayene istasyonu doluluk sorgusu gerçek kapasite verisini döndürür."""
    d = dialogue.Dialogue("test-lift-1", mode="inbound")
    ans = await d.answer("Liftlerin durumu nedir?")

    assert d.inbound_intent == "lift_durumu"
    assert "lift" in ans.lower() or "istasyon" in ans.lower()
    assert "LIFT-2" in d.assigned_lift or "Mekanik" in d.assigned_lift

    # Alternatif ifade
    d2 = dialogue.Dialogue("test-lift-2", mode="inbound")
    ans2 = await d2.answer("İstasyonlarda boş yer var mı?")
    assert d2.inbound_intent == "lift_durumu"


@pytest.mark.asyncio
async def test_obd_dtc_dispatch(dispatch_db):
    """P0300 vb. DTC arıza kodları ve semptomlar ontolojik teşhis ile yanıtlanır."""
    d = dialogue.Dialogue("test-dtc-1", mode="inbound")
    ans = await d.answer("P0300 arıza kodu nedir?")

    assert d.inbound_intent == "obd_dtc_ariza"
    assert "P0300" in ans
    assert "Ateşleme" in ans or "Silindir" in ans or "önerilen işlem" in ans.lower()

    # Belirti bazlı semptom sorgusu
    d2 = dialogue.Dialogue("test-dtc-2", mode="inbound")
    ans2 = await d2.answer("Motor arıza lambası yanıyor ve tekleme yapıyor")
    assert d2.inbound_intent == "obd_dtc_ariza"
    assert "teşhis" in ans2.lower() or "arıza" in ans2.lower()


@pytest.mark.asyncio
async def test_technician_dictation_dispatch(dispatch_db):
    """Teknisyen sesli mikron ve hasar diktesi yapılandırılmış bulguya çevrilir."""
    d = dialogue.Dialogue("test-dict-1", mode="inbound")
    ans = await d.answer("Sol ön çamurluk boyalı 180 mikron kaput orijinal")

    assert d.inbound_intent == "teknisyen_dikte"
    assert "Teknisyen diktesi" in ans
    assert "100" in ans  # Ekspertiz puanı


@pytest.mark.asyncio
async def test_whatsapp_report_dispatch(dispatch_db):
    """WhatsApp rapor talebi telefon varsa kuyruk kaydı oluşturur, yoksa numara ister."""
    # 1. Telefon numarası tanımlı arayan
    d1 = dialogue.Dialogue("test-wa-1", customer_phone="05321234567", mode="inbound")
    ans1 = await d1.answer("Ekspertiz raporumu WhatsApp ile gönderir misiniz?")

    assert d1.inbound_intent == "whatsapp_rapor"
    assert "WhatsApp" in ans1
    assert "05321234567" in ans1

    # 2. Telefon numarası bulunmayan arayan
    d2 = dialogue.Dialogue("test-wa-2", mode="inbound")
    ans2 = await d2.answer("Raporumu WhatsApp'tan atar mısınız?")
    assert d2.inbound_intent == "whatsapp_rapor"
    assert "telefon" in ans2.lower() and "numara" in ans2.lower()


@pytest.mark.asyncio
async def test_valuation_vs_pricing_dispatch(dispatch_db):
    """Araç değerleme sorgusu sabit servis paketi fiyatlarıyla karıştırılmaz."""
    # Araç değerleme sorgusu
    d1 = dialogue.Dialogue("test-val-1", mode="inbound")
    ans1 = await d1.answer("2020 model Passat 85 binde ne kadar eder?")

    assert d1.inbound_intent == "fiyat_parca_sorgusu"
    assert "Passat" in ans1
    assert "piyasa değeri" in ans1.lower()
    assert "TL" in ans1
    # Sabit paket listesi içermemeli (Passat'ın kendi araç değerini vermeli)
    assert "Motor ve Mekanik 950 TL" not in ans1

    # Servis paketi fiyat sorgusu
    d2 = dialogue.Dialogue("test-pkg-1", mode="inbound")
    ans2 = await d2.answer("Full kapsamlı ekspertiz paket fiyatı ne kadar?")
    assert d2.inbound_intent == "fiyat_parca_sorgusu"
    assert "Full Kapsamlı" in ans2 or "1.950 TL" in ans2


@pytest.mark.asyncio
async def test_caller_profile_and_reference_resolution(dispatch_db):
    """Arayan profili hafıza bağlamı ve geçmiş balata/garanti referanslarını çözümler."""
    with dispatch_db() as db:
        p = CallerProfile(
            name="Ahmet Yılmaz",
            phone="05321234567",
            plate="61 TS 061",
            vehicle_model="2023 Peugeot 3008 1.5 BlueHDi",
            warranty_expires_at="2027-06-15",
            warranty_status="active",
            maintenance_history_json=json.dumps([
                {
                    "date": "2026-09-12",
                    "km": 45000,
                    "item": "Ön fren balatası ve disk değişimi",
                    "notes": "Orijinal Bosch parça takıldı",
                }
            ]),
        )
        db.add(p)
        db.commit()

    d = dialogue.Dialogue("test-mem-ground", customer_phone="05321234567", mode="inbound")

    # Müşteri adı otomatik yüklenmiş olmalı
    assert d.customer == "Ahmet Yılmaz"

    # Durum mesajında hafıza yer almalı
    state = d.build_state_message()
    assert state is not None
    assert "Peugeot 3008" in state
    assert "61 TS 061" in state

    # Garanti sorgusu
    ans_war = await d.answer("Aracımın garantisi devam ediyor mu?")
    assert "aktif" in ans_war.lower() or "devam etmektedir" in ans_war.lower()

    # Geçmiş bakım / balata sorgusu
    ans_maint = await d.answer("Geçen sefer konuştuğumuz balata değişimi yapılmış mıydı?")
    assert "balata" in ans_maint.lower()
    assert "2026-09-12" in ans_maint or "45000" in ans_maint
