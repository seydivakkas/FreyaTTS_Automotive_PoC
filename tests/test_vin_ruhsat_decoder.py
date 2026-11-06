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

import io
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from backend.db import Appointment, RuhsatScan, Session, Slot, Vehicle
from backend.main import app
from backend.vin_ruhsat_decoder import (
    decode_phonetic_spelling,
    decode_ruhsat_text,
    extract_text_from_ruhsat_image,
    parse_spoken_number,
    process_inbound_ruhsat_image,
)


def uid():
    return uuid4().hex


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(monkeypatch):
    import base64
    from backend.config import settings
    monkeypatch.setattr(settings, "admin_password", "secret")
    creds = base64.b64encode(b"admin:secret").decode("ascii")
    return {"Authorization": f"Basic {creds}"}


def test_parse_spoken_number():
    num1, consumed1 = parse_spoken_number(["otuz", "dört"])
    assert num1 == 34
    assert consumed1 == 2

    num2, consumed2 = parse_spoken_number(["yüz", "yirmi"])
    assert num2 == 120
    assert consumed2 == 2

    num3, consumed3 = parse_spoken_number(["bin", "iki", "yüz", "otuz", "dört"])
    assert num3 == 1234
    assert consumed3 == 5


def test_decode_phonetic_spelling():
    # 1. Spoken Plate
    spoken_1 = "otuz dört bolu ceyhan fatsa bin iki yüz otuz dört"
    res1 = decode_phonetic_spelling(spoken_1)
    assert res1["plate"] == "34 BCF 1234"

    spoken_2 = "sıfır altı ankara niğde kars yetmiş sekiz"
    res2 = decode_phonetic_spelling(spoken_2)
    assert res2["plate"] == "06 ANK 78"

    # 2. Spoken Mixed Letters & Numbers
    spoken_3 = "otuz beş kars samsun bin iki yüz"
    res3 = decode_phonetic_spelling(spoken_3)
    assert res3["plate"] == "35 KS 1200"


def test_decode_ruhsat_text():
    sample_ocr = (
        "T.C. ARAÇ TESCİL BELGESİ\n"
        "(Y) SERİ NO: AB 123456\n"
        "(A) PLAKA: 34 ABC 789\n"
        "(D.1) MARKA: VOLKSWAGEN\n"
        "(D.2) TİCARİ ADI: PASSAT\n"
        "(D.4) MODEL YILI: 2021\n"
        "(E) ŞASİ NO: WVWZZZ3CZWE123456\n"
        "(P.5) MOTOR NO: 1.5 TSI DADA123456\n"
        "TESCİL SAHİBİ SOYADI: YILMAZ ADI: AHMET\n"
    )
    parsed = decode_ruhsat_text(sample_ocr)
    assert parsed["plate"] == "34 ABC 789"
    assert parsed["vin"] == "WVWZZZ3CZWE123456"
    assert parsed["engine_code"] == "1.5 TSI"
    assert parsed["model_year"] == 2021
    assert "VOLKSWAGEN PASSAT" in parsed["brand_model"]
    assert parsed["document_serial"] == "AB123456"
    assert parsed["confidence"] >= 0.8
    assert parsed["is_vin_valid"] is True


def test_process_inbound_ruhsat_image_db():
    rnd_suffix = f"{1000 + (abs(hash(uid())) % 8999)}"
    unique_plate = f"06 TST {rnd_suffix}"
    sample_text = (
        "RUHSAT BELGESİ\n"
        f"PLAKA: {unique_plate}\n"
        "ŞASİ NO: VF1RFD00012345678\n"
        "MARKA: RENAULT\n"
        "MODEL: MEGANE\n"
        "MODEL YILI: 2020\n"
        "MOTOR NO: 1.5 dCi K9K123456\n"
    )
    fake_img_bytes = sample_text.encode("utf-8")

    with Session() as db:
        # Önceden benzersiz bir araç oluşturalım
        veh = Vehicle(plate=unique_plate, description="Renault Araç", vin="")
        db.add(veh)
        db.commit()

        scan, parsed = process_inbound_ruhsat_image(
            db,
            from_phone="05321112233",
            image_bytes=fake_img_bytes,
            filename="ruhsat_test.jpg",
        )

        assert scan.id.startswith("rscan-")
        assert scan.plate == unique_plate
        assert scan.vin == "VF1RFD00012345678"
        assert scan.model_year == 2020
        assert scan.vehicle_id == veh.id

        # Vehicle vin güncellendi mi kontrol et
        db.refresh(veh)
        assert veh.vin == "VF1RFD00012345678"


def test_ruhsat_api_endpoints(client, auth_headers):
    # 1. POST /api/ruhsat/decode-text
    payload_text = {
        "ocr_text": "PLAKA: 35 KS 999 ŞASİ: WVWZZZ3CZWE123456 MODEL YILI: 2019 MARKA: FIAT MODEL: EGEA"
    }
    r1 = client.post("/api/ruhsat/decode-text", json=payload_text, headers=auth_headers)
    assert r1.status_code == 200
    res1 = r1.json()
    assert res1["plate"] == "35 KS 999"
    assert res1["vin"] == "WVWZZZ3CZWE123456"
    assert res1["model_year"] == 2019
    assert "FIAT EGEA" in res1["brand_model"]

    # 2. POST /api/ruhsat/decode-phonetic
    payload_phonetic = {
        "spoken_text": "otuz dört bolu ceyhan fatsa bin iki yüz otuz dört"
    }
    r2 = client.post("/api/ruhsat/decode-phonetic", json=payload_phonetic, headers=auth_headers)
    assert r2.status_code == 200
    res2 = r2.json()
    assert res2["plate"] == "34 BCF 1234"

    # 3. POST /api/ruhsat/decode-image (file upload)
    img_content = (
        "PLAKA: 34 BCF 1234\n"
        "ŞASİ: WVWZZZ3CZWE123456\n"
        "MARKA: VOLKSWAGEN\n"
        "MODEL: GOLF\n"
        "MODEL YILI: 2022\n"
    ).encode("utf-8")
    files = {"file": ("ruhsat.png", img_content, "image/png")}
    data = {"from_phone": "05554443322"}
    r3 = client.post("/api/ruhsat/decode-image", files=files, data=data, headers=auth_headers)
    assert r3.status_code == 200
    scan_json = r3.json()
    assert scan_json["plate"] == "34 BCF 1234"
    assert scan_json["vin"] == "WVWZZZ3CZWE123456"
    assert scan_json["model_year"] == 2022

    # 4. POST /api/ruhsat/apply-to-crm
    apply_payload = {
        "scan_id": scan_json["id"],
        "plate": "34 BCF 1234",
        "vin": "WVWZZZ3CZWE123456",
        "brand_model": "2022 Volkswagen Golf",
    }
    r4 = client.post("/api/ruhsat/apply-to-crm", json=apply_payload, headers=auth_headers)
    assert r4.status_code == 200
    crm_res = r4.json()
    assert crm_res["status"] == "applied"
    assert crm_res["plate"] == "34 BCF 1234"

    # 5. GET /api/ruhsat/scans
    r5 = client.get("/api/ruhsat/scans", headers=auth_headers)
    assert r5.status_code == 200
    scans_list = r5.json()
    assert len(scans_list) >= 1

    # 6. Hassas tablo genel liste ucundan kaldırıldı
    r6 = client.get("/api/ruhsat-scans", headers=auth_headers)
    assert r6.status_code == 404


def test_whatsapp_inbound_image(client, auth_headers):
    img_content = (
        "T.C. ARAÇ TESCİL BELGESİ\n"
        "PLAKA: 34 XYZ 12\n"
        "ŞASİ NO: VF1RFD00099887766\n"
        "MARKA: PEUGEOT\n"
        "MODEL: 3008\n"
        "MODEL YILI: 2023\n"
    ).encode("utf-8")
    files = {"file": ("whatsapp_ruhsat.jpg", img_content, "image/jpeg")}
    data = {"from_phone": "05332221100", "customer_name": "Murat Kaya"}

    r = client.post("/api/whatsapp/inbound-image", files=files, data=data, headers=auth_headers)
    assert r.status_code == 200
    res = r.json()
    assert res["status"] == "success"
    assert res["plate"] == "34 XYZ 12"
    assert res["vin"] == "VF1RFD00099887766"
    assert "ruhsatınız başarıyla doğrulandı" in res["reply"]
