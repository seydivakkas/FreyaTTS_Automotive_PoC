# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""
seed_demo_telemetry.py
Deterministik Demo ve Telemetri Veri Enjektörü (v3 - Final Polish)

UYARI: Buradaki tüm görüşme, gecikme ve müşteri kayıtları örnek veridir; gerçek
ölçüm olarak sunulamaz. Betik her zaman DEMO_MODE ile çalışır ve yalnızca
data/demo/ altına yazar; işletim veritabanına erişemez.

Bu betik sunum ve ekran görüntüsü alımı öncesinde demo veritabanını ve aktif
bellek durumlarını deterministik olarak hazırlar:
1. Örnek telemetri:
   - 97 Görüşme: Web: 18 | Tel: 54 | Dış: 25
   - Ort. Süre: 68 sn | Ort. Tur: 4.2
   - TTFA p50: ~780 ms, p95: ~1120 ms; TTFT: ~310 ms; STT: ~240 ms; RTF: 0.38x; 4 barge-in
2. 3.3 SIP Warm Transfer (1 bekleyen fısıltı, 2 tamamlanmış aktarım)
3. 3.4 Canlı Müdahale (RT-10 Takeover aktif simüle çağrı)
4. 3.8 Sıra & Lift Durumu (Canlı Kuyrukta 2 araç: 34 EKP 2026, 06 DEF 456; Tahmini Bekleme: 18 dk; Lift #1 DOLU)
5. 3.9 A/B Test (Kontrol A ve Varyant B oturumları, Z-Skoru ve p-değeri)
6. 3.12 Ekspertiz Raporları (3 farklı araç: Qashqai, Passat, Civic)
7. 3.14 OBD-II DTC Teşhis Kayıtları (P0300, P0420, P0171)
8. 3.15 Araçlar ve Fiyatlar (Tüm araçlar için ekspertiz fiyatları dolu)
9. 3.18 Giden Çağrılar (Teyit Edilen: 38, 60 devam eden · 2 iptal; zengin müşteri listesi)
10. 3.19 Çağrı Geçmişi (Teknik diyaloglar)
"""

import os
import sys
import json
import uuid
import math
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
import httpx
from sqlalchemy import select, delete

# Ensure root dir in path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# backend içe aktarılmadan önce ayarlanmalıdır: veritabanı motoru o anda belirlenir.
os.environ["DEMO_MODE"] = "1"

from alembic import command
from alembic.config import Config

from backend.db import (
    engine,
    Session,
    Vehicle,
    Quote,
    InspectionReport,
    VehicleDiagnostic,
    Appointment,
    Conversation,
    Turn,
    OperatorTransfer,
    ABExperiment,
    ABAssignment,
    CallAnalytics,
    InspectionLift,
    InspectionQueue,
    OutboundCall,
)
from backend.analytics import get_analytics_overview
from backend.ab_testing import seed_default_experiment, get_experiment_report
from backend.config import settings


def seed_telemetry_and_conversations(db):
    """97 adet görüşme ve bunlara ait RT-09 uyumlu deterministik telemetri turları oluşturur."""
    print("[*] 97 görüşme ve RT-09 telemetri turları enjekte ediliyor (Web: 18, Tel: 54, Dış: 25)...")

    # Mevcut demo verilerini temizleyelim (demo_ ile başlayanlar)
    db.execute(delete(Turn).where(Turn.conversation_id.like("demo_conv_%")))
    db.execute(delete(Conversation).where(Conversation.id.like("demo_conv_%")))
    db.commit()

    now_utc = datetime.now(timezone.utc)
    random.seed(42)

    # Toplam 97 görüşme kanalları: 18 web, 54 phone, 25 outbound
    channels = ["web"] * 18 + ["phone"] * 54 + ["outbound"] * 25
    random.shuffle(channels)

    # 97 adet için TTFA, TTFT, STT dizileri
    first_audio_vals = []
    for i in range(97):
        if i < 48:
            val = 620.0 + (i / 47.0) * (780.0 - 620.0) + random.uniform(-10, 10)
        elif i < 90:
            val = 780.0 + ((i - 48) / 42.0) * (1120.0 - 780.0) + random.uniform(-10, 10)
        else:
            val = 1120.0 + ((i - 90) / 6.0) * 80.0 + random.uniform(0, 15)
        first_audio_vals.append(round(val, 1))
    first_audio_vals.sort()

    llm_ft_vals = []
    for i in range(97):
        if i < 48:
            val = 240.0 + (i / 47.0) * (310.0 - 240.0) + random.uniform(-5, 5)
        else:
            val = 310.0 + ((i - 48) / 48.0) * 180.0 + random.uniform(-5, 5)
        llm_ft_vals.append(round(val, 1))
    llm_ft_vals.sort()

    stt_vals = []
    for i in range(97):
        if i < 48:
            val = 180.0 + (i / 47.0) * (240.0 - 180.0) + random.uniform(-5, 5)
        else:
            val = 240.0 + ((i - 48) / 48.0) * 120.0 + random.uniform(-5, 5)
        stt_vals.append(round(val, 1))
    stt_vals.sort()

    rtf_vals = [round(0.35 + (i % 7) * 0.01 + random.uniform(-0.01, 0.01), 3) for i in range(97)]
    barge_in_indices = {12, 34, 58, 83}  # Tam 4 adet barge-in

    sample_dialogues = [
        ("Merhaba, 34 TST 89 plakalı aracım için ekspertiz randevusu almak istiyorum.",
         "Merhaba Murat Bey! 34 TST 89 plakalı Nissan Qashqai aracınız için yarın saat 14:30 ve 16:00 uygundur. Hangi saati tercih edersiniz?"),
        ("1.5 TSI Passat aracımın periyodik muayene öncesi genel kontrolünü yaptırabilir miyim?",
         "Tabii ki! 1.5 TSI motorlu Passat aracınız için 101 nokta ekspertiz ve OBD-II arıza tespit randevunuzu hemen oluşturabilirim."),
        ("Fren disklerinde sürtünme sesi geliyor, acil kontrol gerek.",
         "Fren güvenliği birinci önceliğimizdir. Aracınızı en yakın liftimize almak üzere bugün saat 15:00 için acil teşhis kaydı açıyorum."),
        ("OBD cihazım P0420 hatası verdi, katalitik konvertör durumuna bakabilir misiniz?",
         "P0420 arıza kodu katalizör sistem verimi eşiğiyle ilgilidir. Egzoz emisyon ve oksijen sensörü kontrolleri randevunuza dahil edilmiştir."),
        ("Satın almayı düşündüğüm Honda Civic için tam kapsamlı ekspertiz raporu alabilir miyiz?",
         "Elbette! Kaporta, boya, şasi, motor mekanik ve OBD-II elektronik kontrolünü içeren Full Ekspertiz paketimiz mevcuttur."),
    ]

    for idx in range(97):
        conv_id = f"demo_conv_{idx+1:02d}"
        conv_dt = now_utc - timedelta(days=(idx % 14), hours=(idx % 8), minutes=idx * 5)
        c_status = "resolved" if idx > 12 else ("active" if idx < 3 else "follow_up")

        conv = Conversation(
            id=conv_id,
            channel=channels[idx],
            status=c_status,
            operator_notes=f"Deterministik test oturumu #{idx+1}" if c_status == "resolved" else "",
            created_at=conv_dt.isoformat(),
            resolved_at=(conv_dt + timedelta(seconds=68)).isoformat() if c_status == "resolved" else None,
        )
        db.add(conv)

        # Tur sayısı ortalama 4.2 olacak şekilde: çoğu 4, bazıları 5 veya 6 tur
        num_turns = 4 if idx % 5 != 0 else (6 if idx % 10 == 0 else 5)
        t_delta = 68.0 / max(1, num_turns - 1)

        d_idx = idx % len(sample_dialogues)
        user_text, asst_text = sample_dialogues[d_idx]

        for t_i in range(num_turns):
            is_user = (t_i % 2 == 0)
            t_created = conv_dt + timedelta(seconds=t_i * t_delta)

            m_dict = {}
            if not is_user:
                m_dict = {
                    "first_audio_ms": first_audio_vals[idx],
                    "llm_first_token_ms": llm_ft_vals[idx],
                    "llm_total_ms": round(llm_ft_vals[idx] + 280.0, 1),
                    "stt_ms": stt_vals[idx],
                    "tts_ms": round(290.0 + (idx % 10) * 6.0, 1),
                    "rtf": rtf_vals[idx],
                }
                if idx in barge_in_indices and t_i == 1:
                    m_dict["barge_in_signal_ms"] = 125.0

            turn = Turn(
                id=f"demo_turn_{idx+1:02d}_{t_i+1}",
                conversation_id=conv_id,
                role="user" if is_user else "assistant",
                text=user_text if is_user else asst_text,
                metrics=json.dumps(m_dict) if m_dict else "{}",
                created_at=t_created.isoformat(),
            )
            db.add(turn)

    db.commit()
    print("[OK] 97 görüşme ve telemetri turları kaydedildi.")


def seed_sip_warm_transfers(db):
    """3.3 SIP Warm Transfer için 1 bekleyen (whispering) ve 2 kabul edilmiş aktarım oluşturur."""
    print("[*] 3.3 SIP Warm Transfer kayıtları enjekte ediliyor...")
    db.execute(delete(OperatorTransfer).where(OperatorTransfer.id.like("demo_transfer_%")))
    db.commit()

    now_utc = datetime.now(timezone.utc)

    # 1 Bekleyen Transfer (Fısıltı aşamasında)
    pending_tr = OperatorTransfer(
        id="demo_transfer_pending_01",
        conversation_id="demo_conv_01",
        caller_channel="SIP/Trunk-01/05325551234",
        operator_extension="6002",
        customer_name="Murat Demir",
        vehicle_plate="34 BJK 1903",
        summary="Müşteri 14:30 randevusunu 16:00 olarak revize etmek istiyor ve rot-balans kontrolü talep ediyor.",
        whisper_text="Fısıltı: Müşteri 14:30 randevusunu 16:00 olarak teyit etmek istiyor.",
        status="whispering",
        sip_headers_json=json.dumps({
            "X-Freya-Caller-ID": "05325551234",
            "X-Freya-Intent": "appointment_reschedule",
            "X-Freya-Priority": "HIGH",
        }),
        duration_seconds=8.4,
        created_at=(now_utc - timedelta(seconds=6)).isoformat(),
        completed_at=None,
    )
    db.add(pending_tr)

    # 2 Kabul edilmiş (Accepted) Transfer
    accepted_tr_1 = OperatorTransfer(
        id="demo_transfer_acc_01",
        conversation_id="demo_conv_02",
        caller_channel="SIP/Trunk-02/05339998877",
        operator_extension="6002",
        customer_name="Ayşe Kaya",
        vehicle_plate="34 BCF 1234",
        summary="Volkswagen Golf 1.5 eTSI DSG kavrama titremesi şikayeti ile bağlandı. Randevusu oluşturuldu.",
        whisper_text="Fısıltı: Müşteri kavrama garantisi sorguluyor.",
        status="accepted",
        sip_headers_json=json.dumps({"X-Freya-Intent": "warranty_inquiry"}),
        duration_seconds=142.5,
        created_at=(now_utc - timedelta(minutes=25)).isoformat(),
        completed_at=(now_utc - timedelta(minutes=22)).isoformat(),
    )
    db.add(accepted_tr_1)

    accepted_tr_2 = OperatorTransfer(
        id="demo_transfer_acc_02",
        conversation_id="demo_conv_03",
        caller_channel="SIP/Trunk-01/05423334455",
        operator_extension="6002",
        customer_name="Kemal Sunar",
        vehicle_plate="06 TST 4431",
        summary="Filo ekspertiz indirimi talebi. Kurumsal cariye yönlendirildi.",
        whisper_text="Fısıltı: Filo yöneticisi, 5 araçlık paket soruyor.",
        status="accepted",
        sip_headers_json=json.dumps({"X-Freya-Intent": "fleet_discount"}),
        duration_seconds=98.0,
        created_at=(now_utc - timedelta(hours=1, minutes=10)).isoformat(),
        completed_at=(now_utc - timedelta(hours=1, minutes=8)).isoformat(),
    )
    db.add(accepted_tr_2)

    db.commit()
    print("[OK] SIP Warm Transfer kayıtları eklendi.")


def seed_lifts_and_queue(db):
    """3.8 Sıra & Lift Durumu: Lift #1 DOLU (İŞLEMDE), 2 bekleyen araç (34 EKP 2026, 06 DEF 456), Tahmini Bekleme: 18 dk."""
    print("[*] 3.8 Sıra & Lift Durumu verileri enjekte ediliyor...")
    now_utc = datetime.now(timezone.utc)

    # Mevcut kuyruk ve liftleri temizleyip yeniden yapılandıralım
    db.execute(delete(InspectionQueue))
    db.execute(delete(InspectionLift))
    db.commit()

    # Lift 1: Dolu (İşlemde)
    lift1 = InspectionLift(
        id="lift_01",
        name="Mekanik & Alt Takım Lifti",
        lift_number=1,
        status="busy",
        current_vehicle_plate="34 BJK 1903",
        package_type="101 Nokta Mekanik Muayene",
        started_at=(now_utc - timedelta(minutes=15)).isoformat(),
        estimated_duration_min=30,
        notes="İşlemde: Rot-balans ve fren hortumları inceleniyor",
        created_at=now_utc.isoformat(),
    )
    db.add(lift1)

    # Lift 2: Boş (Hazır)
    lift2 = InspectionLift(
        id="lift_02",
        name="Kaporta & Boya Ekspertizi Lifti",
        lift_number=2,
        status="idle",
        current_vehicle_plate=None,
        package_type=None,
        started_at=None,
        estimated_duration_min=25,
        notes="Müsait / Sıradaki aracı bekliyor",
        created_at=now_utc.isoformat(),
    )
    db.add(lift2)

    # Lift 3: Boş (Hazır)
    lift3 = InspectionLift(
        id="lift_03",
        name="OBD-II & Elektronik Teşhis İstasyonu",
        lift_number=3,
        status="idle",
        current_vehicle_plate=None,
        package_type=None,
        started_at=None,
        estimated_duration_min=20,
        notes="Müsait / Kalibrasyon tamamlandı",
        created_at=now_utc.isoformat(),
    )
    db.add(lift3)

    # Canlı Bekleme Kuyruğu: 2 Araç
    q1 = InspectionQueue(
        id="queue_01",
        queue_number=1,
        plate="34 EKP 2026",
        customer="Emre Kaya",
        package_type="101 Nokta Genel Muayene",
        duration_minutes=25,
        status="waiting",
        check_in_at=(now_utc - timedelta(minutes=12)).isoformat(),
    )
    db.add(q1)

    q2 = InspectionQueue(
        id="queue_02",
        queue_number=2,
        plate="06 DEF 456",
        customer="Deniz Fırat",
        package_type="OBD-II & Hibrit Sistem Teşhisi",
        duration_minutes=25,
        status="waiting",
        check_in_at=(now_utc - timedelta(minutes=6)).isoformat(),
    )
    db.add(q2)

    db.commit()
    print("[OK] Liftler ve Sıra Kuyruğu (2 bekleyen araç, Lift #1 DOLU) kaydedildi.")


def seed_ab_experiment_metrics(db):
    """3.9 A/B Test için Kontrol (A) ve Varyant (B) oturumları, Z-Skoru ve p-değeri oluşturur."""
    print("[*] 3.9 A/B Test istatistiksel verileri enjekte ediliyor...")
    exp = seed_default_experiment(db)

    db.execute(delete(ABAssignment).where(ABAssignment.experiment_id == exp.id))
    db.execute(delete(Conversation).where(Conversation.id.like("demo_ab_%")))
    db.commit()

    now_utc = datetime.now(timezone.utc)

    # 97 görüşmeden ilk 25'i kontrol, sonraki 30'u varyant b olarak eşleştirilir
    # Böylece toplam görüşme sayısı tam olarak 97'de kalır (Web: 18, Tel: 54, Dış: 25)
    for i in range(25):
        conv_id = f"demo_conv_{i+1:02d}"
        assign = ABAssignment(
            id=f"demo_assign_ctrl_{i+1:02d}",
            conversation_id=conv_id,
            experiment_id=exp.id,
            variant_id="control",
            outcome="converted" if i < 11 else "abandoned",
            first_audio_ms=790.0,
            duration_seconds=75.0,
            turns_count=4,
            created_at=(now_utc - timedelta(days=2, hours=i)).isoformat(),
            completed_at=(now_utc - timedelta(days=2, hours=i)).isoformat(),
        )
        db.add(assign)

    for j in range(30):
        conv_id = f"demo_conv_{j+26:02d}"
        assign = ABAssignment(
            id=f"demo_assign_varb_{j+1:02d}",
            conversation_id=conv_id,
            experiment_id=exp.id,
            variant_id="variant_b",
            outcome="converted" if j < 22 else "abandoned",
            first_audio_ms=750.0,
            duration_seconds=64.0,
            turns_count=4,
            created_at=(now_utc - timedelta(days=1, hours=j % 12)).isoformat(),
            completed_at=(now_utc - timedelta(days=1, hours=j % 12)).isoformat(),
        )
        db.add(assign)

    db.commit()
    report = get_experiment_report(db, exp.id)
    comp = report["comparisons"][0] if report.get("comparisons") else {}
    print(f"[OK] A/B Test Raporu: Z-Skoru: {comp.get('z_score')}, p-değeri: {comp.get('p_value')}")


def seed_inspections_and_diagnostics(db):
    """3.12 Ekspertiz Raporları ve 3.14 OBD-II DTC Bulguları: 3 farklı araç (Qashqai, Passat, Civic)."""
    print("[*] 3.12 Ekspertiz (3 farklı araç) ve 3.14 OBD-II DTC teşhis kayıtları enjekte ediliyor...")

    # Araç 1: Nissan Qashqai
    v1 = db.scalars(select(Vehicle).where(Vehicle.plate == "32 ABX 435")).first()
    if not v1:
        v1 = Vehicle(id="demo_veh_qashqai", description="Nissan Qashqai 1.3 DIG-T", plate="32 ABX 435", vin="SJNFAAJ11U1234567")
        db.add(v1)

    # Araç 2: Volkswagen Passat
    v2 = db.scalars(select(Vehicle).where(Vehicle.plate == "34 ABC 123")).first()
    if not v2:
        v2 = Vehicle(id="demo_veh_passat", description="Volkswagen Passat 1.5 TSI", plate="34 ABC 123", vin="WVWZZZ3CZWE987654")
        db.add(v2)

    # Araç 3: Honda Civic
    v3 = db.scalars(select(Vehicle).where(Vehicle.plate == "06 CAN 01")).first()
    if not v3:
        v3 = Vehicle(id="demo_veh_civic", description="Honda Civic 1.5 VTEC", plate="06 CAN 01", vin="SHHFK7760JU456789")
        db.add(v3)

    db.commit()

    db.execute(delete(InspectionReport).where(InspectionReport.id.like("demo_insp_%")))
    db.execute(delete(VehicleDiagnostic).where(VehicleDiagnostic.id.like("demo_dtc_%")))
    db.commit()

    now_utc = datetime.now(timezone.utc)

    # 3 Farklı Araç için Ekspertiz Raporları
    r1 = InspectionReport(
        id="demo_insp_01",
        vehicle_id=v1.id,
        technician_name="Murat Usta (Baş Teknisyen)",
        summary="Motor ve yürüyen aksam mükemmel kondisyonda. Sağ ön çamurluk boyalı, şasi ve podyeler hatasız.",
        mileage_km=48500,
        score=92,
        findings_json=json.dumps({
            "paint_body": {"kaput": "Orijinal", "tavan": "Orijinal", "sag_on_camurluk": "Boyalı"},
            "engine_mechanical": {"motor_performansi_yuzde": 95, "turbo_durumu": "Mükemmel", "sanziman_vites": "Kusursuz"},
            "chassis_frame": {"on_podyeler": "Orijinal / İşlemsiz", "fren_disk_balata": "İyi Durumda (%85)"},
            "tires_wheels": {"on_sol_dis_mm": 6.8, "arka_sol_dis_mm": 6.5, "dot_yili": "2024"},
        }, ensure_ascii=False),
        photos_json="[]",
        pdf_path="reports/demo_32ABX435_full_inspection.pdf",
        delivered_at=(now_utc - timedelta(hours=3)).isoformat(),
        inspected_at=(now_utc - timedelta(hours=4)).isoformat(),
    )
    db.add(r1)

    r2 = InspectionReport(
        id="demo_insp_02",
        vehicle_id=v2.id,
        technician_name="Selim Usta (Kaporta & Boya)",
        summary="Volkswagen Passat 1.5 TSI ekspertiz kontrolü: Bagaj kapağında lokal boya tespit edildi. DSG kavrama ve şanzıman adaptasyonu mükemmel.",
        mileage_km=92000,
        score=84,
        findings_json=json.dumps({
            "paint_body": {"bagaj_kapagi": "Lokal Boyalı", "arka_tampon": "Plastik Onarım", "kaput": "Orijinal"},
            "engine_mechanical": {"motor_performansi_yuzde": 91, "turbo_durumu": "Normal", "yag_sivi_kacaklari": "Kuru / Temiz"},
            "chassis_frame": {"on_podyeler": "Orijinal", "fren_disk_balata": "Yeni (%90)"},
        }, ensure_ascii=False),
        photos_json="[]",
        pdf_path="reports/demo_34ABC123_inspection.pdf",
        delivered_at=(now_utc - timedelta(days=1)).isoformat(),
        inspected_at=(now_utc - timedelta(days=1, hours=2)).isoformat(),
    )
    db.add(r2)

    r3 = InspectionReport(
        id="demo_insp_03",
        vehicle_id=v3.id,
        technician_name="Ahmet Usta (Diyagnostik & OBD)",
        summary="Honda Civic 1.5 VTEC: OBD-II taramasında aktif arıza kodu yok. VTEC zamanlaması kusursuz, CVT şanzıman ve yürüyen aksam tam not aldı.",
        mileage_km=31200,
        score=96,
        findings_json=json.dumps({
            "paint_body": {"tum_parcalar": "Tamamen Orijinal (Hatasız)"},
            "engine_mechanical": {"motor_performansi_yuzde": 98, "turbo_durumu": "Mükemmel"},
            "interior_electronics": {"obd_ariza_taramasi": "0 Hata Kodu", "airbag_guvenlik": "Aktif / Hatasız"},
        }, ensure_ascii=False),
        photos_json="[]",
        pdf_path="reports/demo_06CAN01_inspection.pdf",
        delivered_at=(now_utc - timedelta(days=3)).isoformat(),
        inspected_at=(now_utc - timedelta(days=3, hours=1)).isoformat(),
    )
    db.add(r3)

    # 3 OBD-II DTC Bulgusu
    dtc1 = VehicleDiagnostic(
        id="demo_dtc_01",
        vehicle_id=v1.id,
        dtc_code="P0300",
        severity="critical",
        system_category="engine",
        description_tr="Rastgele / Çoklu Silindir Ateşleme Hatası (Random/Multiple Cylinder Misfire Detected)",
        recommended_action="Buji ve ateşleme bobinlerinin derhal osiloskop ile test edilmesi, enjektör yakıt püskürtme basıncının ölçülmesi önerilir.",
        current_mileage_km=48500,
        next_service_km=50000,
        maintenance_status="critical",
        source="obd_telemetry",
        is_resolved=False,
        owner_phone="05325551234",
        owner_name="Murat Demir",
        last_notified_at=(now_utc - timedelta(hours=1)).isoformat(),
        created_at=(now_utc - timedelta(hours=2)).isoformat(),
    )
    db.add(dtc1)

    dtc2 = VehicleDiagnostic(
        id="demo_dtc_02",
        vehicle_id=v2.id,
        dtc_code="P0420",
        severity="warning",
        system_category="exhaust",
        description_tr="Katalizör Sistem Verimi Eşik Değerin Altında (Bank 1)",
        recommended_action="Katalitik konvertör gözenek tıkanıklığı ve aşağı akış (downstream) oksijen sensörü voltaj dalgalanması kontrol edilmelidir.",
        current_mileage_km=92000,
        next_service_km=100000,
        maintenance_status="warning",
        source="obd_dongle",
        is_resolved=False,
        owner_phone="05339998877",
        owner_name="Ayşe Kaya",
        last_notified_at=None,
        created_at=(now_utc - timedelta(hours=4)).isoformat(),
    )
    db.add(dtc2)

    dtc3 = VehicleDiagnostic(
        id="demo_dtc_03",
        vehicle_id=v3.id,
        dtc_code="P0171",
        severity="warning",
        system_category="fuel_air",
        description_tr="Sistem Aşırı Fakir Karışım (System Too Lean - Bank 1)",
        recommended_action="Emme manifoldu hava kaçağı testi (duman testi) ve kütle hava akış (MAF) sensörü temizliği yapılmalıdır.",
        current_mileage_km=31200,
        next_service_km=40000,
        maintenance_status="warning",
        source="obd_dongle",
        is_resolved=True,
        owner_phone="05423334455",
        owner_name="Can Öztürk",
        last_notified_at=(now_utc - timedelta(days=2)).isoformat(),
        created_at=(now_utc - timedelta(days=3)).isoformat(),
    )
    db.add(dtc3)

    db.commit()
    print("[OK] Ekspertiz (3 araç) ve OBD-II DTC kayıtları eklendi.")


def seed_vehicles_and_quotes(db):
    """3.15 Araçlar ve Fiyatlar: Toyota Corolla, Renault Clio, Honda Civic, Ford Focus fiyatları eksiksiz dolu."""
    print("[*] 3.15 Araçlar ve Ekspertiz Fiyatları (Quote) dolduruluyor...")

    # Standart araç katalog listesi
    catalog = [
        ("veh-qashqai-1", "Nissan Qashqai 1.3 DIG-T", "32 ABX 435", 450000),      # 4.500 TL
        ("veh-passat-1", "Volkswagen Passat 1.5 TSI", "34 ABC 123", 495000),      # 4.950 TL
        ("veh-corolla-1", "Toyota Corolla 1.8 Hybrid", "34 PIN 01", 425000),     # 4.250 TL
        ("veh-clio-1", "Renault Clio 1.0 TCe", "34 WA 123", 350000),             # 3.500 TL
        ("veh-civic-1", "Honda Civic 1.5 VTEC", "06 CAN 01", 480000),             # 4.800 TL
        ("veh-focus-1", "Ford Focus 1.5 EcoBlue", "35 VCS 99", 420000),           # 4.200 TL
        ("veh-golf-1", "Volkswagen Golf 1.5 eTSI", "34 BCF 1234", 460000),        # 4.600 TL
    ]

    # Fazlalık test araçlarını temizleyelim, temiz bir liste kalsın
    db.execute(delete(Quote))
    db.commit()

    for v_id, desc, plate, kurus in catalog:
        veh = db.scalars(select(Vehicle).where(Vehicle.plate == plate)).first()
        if not veh:
            veh = Vehicle(id=v_id, description=desc, plate=plate, vin=f"VIN{plate.replace(' ', '')}026")
            db.add(veh)
            db.flush()
        else:
            veh.description = desc

        # Fiyat kaydı (Quote) ekle
        q = Quote(
            id=f"quote_{veh.id}",
            vehicle_id=veh.id,
            amount_kurus=kurus,
        )
        db.add(q)

    db.commit()
    print("[OK] Araçlar ve ekspertiz fiyatları kaydedildi.")


def seed_outbound_calls(db):
    """3.18 Giden Çağrılar: Teyit Edilen: 38, 60 devam eden · 2 iptal (Toplam: 100 çağrı), zengin müşteri listesi."""
    print("[*] 3.18 Giden Çağrılar enjekte ediliyor (38 teyit, 60 devam eden, 2 iptal)...")
    db.execute(delete(OutboundCall))
    db.commit()

    now_utc = datetime.now(timezone.utc)

    # 100 adet çağrı için müşteri isimleri ve telefonlar
    first_names = ["Murat", "Ahmet", "Mehmet", "Mustafa", "Ali", "Can", "Burak", "Emre", "Serkan", "Hakan",
                   "Ayşe", "Fatma", "Zeynep", "Elif", "Selin", "Gizem", "Büşra", "Ece", "Derya", "Merve"]
    last_names = ["Demir", "Yılmaz", "Kaya", "Çelik", "Şahin", "Öztürk", "Arslan", "Doğan", "Kılıç", "Aslan",
                  "Çetin", "Kara", "Koç", "Kurt", "Özdemir", "Simsek", "Acar", "Yıldız", "Güler", "Polat"]
    area_codes = ["0532", "0533", "0535", "0542", "0544", "0553", "0505", "0530"]

    call_types = ["appointment_confirmation", "reminder", "follow_up", "feedback_survey"]

    # 38 Teyit Edildi (completed + confirmed)
    # 60 Devam Eden (in-progress + pending)
    # 2 Randevu İptal (cancelled + cancelled)
    call_configs = (
        [("completed", "confirmed")] * 38 +
        [("in-progress", "pending")] * 60 +
        [("cancelled", "cancelled")] * 2
    )

    # Mevcut randevuları alalım (foreign key için)
    apps = db.scalars(select(Appointment)).all()
    if not apps:
        # Randevu yoksa 1 adet örnek randevu oluşturalım
        sample_vehicle = db.scalars(select(Vehicle)).first()
        sample_app = Appointment(
            id="app_sample_demo",
            vehicle_id=sample_vehicle.id,
            customer="Örnek Müşteri",
            idempotency_key="demo_sample_appointment",
            confirmed=True,
            status="confirmed",
        )
        db.add(sample_app)
        db.flush()
        apps = [sample_app]

    for i, (status, outcome) in enumerate(call_configs):
        fn = first_names[i % len(first_names)]
        ln = last_names[(i * 3 + 7) % len(last_names)]
        customer = f"{fn} {ln}"

        ac = area_codes[(i * 2 + 3) % len(area_codes)]
        phone = f"{ac} {random.randint(200, 999)} {random.randint(10, 99)} {random.randint(10, 99)}"
        c_type = call_types[i % len(call_types)]

        dt = now_utc - timedelta(hours=(i % 48), minutes=(i * 11) % 60)
        app_id = apps[i % len(apps)].id

        call = OutboundCall(
            id=f"demo_outbound_{i+1:03d}",
            appointment_id=app_id,
            customer=customer,
            phone=phone,
            call_type=c_type,
            status=status,
            outcome=outcome,
            action_id=f"ACT-2026-{i+1:04d}",
            attempts=1 if status == "completed" else 0,
            created_at=dt.isoformat(),
            completed_at=(dt + timedelta(minutes=2)).isoformat() if status == "completed" else None,
        )
        db.add(call)

    db.commit()
    print("[OK] 100 giden çağrı (38 teyit, 60 devam eden, 2 iptal) başarıyla kaydedildi.")


def register_live_call_in_server():
    """Çalışan FastAPI sunucusuna HTTP üzerinden canlı simüle çağrı kaydeder (3.4 Takeover için)."""
    print("[*] 3.4 Canlı Müdahale (Takeover) simüle çağrısı FastAPI'ye kaydediliyor...")
    url = "http://127.0.0.1:8000/api/operator/register-call"
    password = settings.admin_password
    auth = ("admin", password)

    # 8000 portundaki sunucu işletim modunda olabilir; ona sahte çağrı kaydedilmez.
    try:
        ready = httpx.get("http://127.0.0.1:8000/api/readiness", auth=auth, timeout=5.0)
        if ready.status_code != 200 or ready.json().get("demo_mode") is not True:
            print("[*] Çalışan demo sunucusu yok; canlı simüle çağrı kaydedilmedi.")
            return
    except httpx.HTTPError:
        print("[*] Çalışan demo sunucusu yok; canlı simüle çağrı kaydedilmedi.")
        return

    payload = {
        "session_id": "call_sim_active_01",
        "caller_id": "0532 555 12 34",
        "initial_turn_id": "turn_demo_live_01",
        "mos_score": 4.41,
        "rtf": 0.17,
    }

    try:
        r = httpx.post(url, json=payload, auth=auth, timeout=5.0)
        if r.status_code == 200:
            print("[OK] Canlı simüle çağrı başarıyla kaydedildi: call_sim_active_01")
        else:
            print(f"[!] register-call yanıtı: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"[!] Sunucuya HTTP ile bağlanılamadı ({e}); backend henüz açık değilse sunucu başladığında yüklenecektir.")


def main():
    print("=" * 65)
    print("  FREYATTS DEMO VERI YUKLEYICI (ornek veri, gercek olcum degildir)")
    print("=" * 65)

    if not settings.demo_mode or Path(engine.url.database).parent.name != "demo":
        sys.exit(f"Demo veritabanı dışında çalışılamaz: {engine.url.database}")

    alembic_config = Config(str(ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(alembic_config, "head")

    with Session() as db:
        seed_telemetry_and_conversations(db)
        seed_sip_warm_transfers(db)
        seed_lifts_and_queue(db)
        seed_ab_experiment_metrics(db)
        seed_inspections_and_diagnostics(db)
        seed_vehicles_and_quotes(db)
        seed_outbound_calls(db)

        # Doğrulama: Analitik çıktısını kontrol et
        ov = get_analytics_overview(db)
        print("\n--- Yüklenen örnek telemetri (gerçek ölçüm değildir) ---")
        print(f"Toplam Görüşme: {ov['summary']['total_conversations']} (Kanal: {ov['summary']['channels']})")
        print(f"Ortalama Süre: {ov['summary']['avg_duration_seconds']} sn | Ortalama Tur: {ov['summary']['avg_turns_per_conversation']}")
        print(f"İlk Ses Gecikmesi (TTFA) p50: {ov['latency_kpis']['first_audio_ms']['p50']} ms (Hedef: ~780 ms)")
        print(f"İlk Ses Gecikmesi (TTFA) p95: {ov['latency_kpis']['first_audio_ms']['p95']} ms (Hedef: ~1120 ms)")
        print(f"LLM İlk Token (TTFT) p50: {ov['latency_kpis']['llm_ms']['p50_first_token']} ms (Hedef: ~310 ms)")
        print(f"STT Gecikmesi p50: {ov['latency_kpis']['stt_ms']['p50']} ms (Hedef: ~240 ms)")
        print(f"TTS RTF Ortalaması: {ov['latency_kpis']['tts_ms']['avg_rtf']}x (Hedef: ~0.38x)")
        print(f"Barge-In Kesinti Sayısı: {ov['latency_kpis']['barge_in_count']} (Hedef: 4)")

    # Canlı çağrıyı kaydet
    register_live_call_in_server()
    print("\n[TAMAMLANDI] Deterministik demo seed işlemi başarıyla tamamlandı.")


if __name__ == "__main__":
    main()
