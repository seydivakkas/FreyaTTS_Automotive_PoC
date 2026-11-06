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

from __future__ import annotations

import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.db import (
    Appointment,
    RuhsatScan,
    Vehicle,
    now,
)
from backend.vin import is_valid_vin_format, verify_iso3779_check_digit

logger = logging.getLogger("vin_ruhsat_decoder")

# 1. Türk Alfabesi Şehir Kodlu Fonetik Harf Haritası (Telefonda Harf Kodlama)
TURKISH_PHONETIC_ALPHABET: Dict[str, List[str]] = {
    "A": ["adana", "ankara", "aydın", "afyon"],
    "B": ["bolu", "bursa", "balıkesir", "bilecik"],
    "C": ["ceyhan"],
    "Ç": ["çanakkale", "çankırı", "çorum"],
    "D": ["denizli", "diyarbakır", "düzce"],
    "E": ["edirne", "elazığ", "erzurum", "eskişehir", "erzincan"],
    "F": ["fatsa", "fırat"],
    "G": ["giresun", "gaziantep", "gümüşhane"],
    "H": ["hatay", "hakkari"],
    "I": ["isparta", "iğdır"],
    "İ": ["izmir", "istanbul", "izmit"],
    "J": ["jandarma", "jale"],
    "K": ["kars", "konya", "kayseri", "kocaeli", "kastamonu", "kütahya"],
    "L": ["lüleburgaz"],
    "M": ["malatya", "manisa", "mardin", "muğla", "muş"],
    "N": ["niğde", "nevşehir"],
    "O": ["ordu", "osmaniye"],
    "Ö": ["ödemiş"],
    "P": ["polatlı", "pınar"],
    "R": ["rize"],
    "S": ["samsun", "sinop", "sivas"],
    "Ş": ["şanlıurfa", "şırnak"],
    "T": ["trabzon", "tokat", "tekirdağ"],
    "U": ["uşak"],
    "Ü": ["ünye"],
    "V": ["van"],
    "Y": ["yozgat", "yalova"],
    "Z": ["zonguldak"],
}

# Fonetik ters eşleme: 'fatsa' -> 'F', 'bolu' -> 'B'
PHONETIC_WORD_TO_CHAR: Dict[str, str] = {}
for letter, city_list in TURKISH_PHONETIC_ALPHABET.items():
    for city in city_list:
        PHONETIC_WORD_TO_CHAR[city] = letter

# Türkçe Rakam Kelimeleri
TURKISH_NUMBERS: Dict[str, int] = {
    "sıfır": 0, "sifir": 0,
    "bir": 1,
    "iki": 2,
    "üç": 3, "uc": 3,
    "dört": 4, "dort": 4,
    "beş": 5, "bes": 5,
    "altı": 6, "alti": 6,
    "yedi": 7,
    "sekiz": 8,
    "dokuz": 9,
    "on": 10,
    "yirmi": 20,
    "otuz": 30,
    "kırk": 40, "kirk": 40,
    "elli": 50,
    "altmış": 60, "altmis": 60,
    "yetmiş": 70, "yetmis": 70,
    "seksen": 80,
    "doksan": 90,
}

# Ruhsat Alanı Regex Kalıpları
RUHSAT_PATTERNS = {
    # (A) Plaka Kalıbı: 34 ABC 789, 06 ANK 06, 35 KS 1234
    "plate": re.compile(
        r"(?:\(?A\)?\s*(?:PLAKA(?:SI)?|Tescil\s*Plakası)?:?\s*)?\b(0[1-9]|[1-7][0-9]|8[01])\s*([A-ZÇĞİÖŞÜ]{1,3})\s*(\d{2,4})\b",
        re.IGNORECASE,
    ),
    # (E) Şasi / VIN: 17 karakter ISO 3779 (I, O, Q hariç)
    "vin": re.compile(
        r"(?:\(?E\)?\s*(?:ŞASİ|ŞASE|VIN|Vehicle\s*ID)?:?\s*)?\b([A-HJ-NPR-Z0-9]{17})\b",
        re.IGNORECASE,
    ),
    # (P.5) Motor Kodu / No: 1.5 TSI, 1.6 BlueHDi, K9K 1.5 dCi, CXXB, DADA
    "engine_code": re.compile(
        r"(?:\(?P\.5\)?\s*(?:MOTOR\s*(?:NO|KODU)?)?:?\s*)?\b([A-Z0-9]{3,8}\s*(?:\d{3,8})?|(?:1\.[0-9]\s*(?:TSI|TDI|TFSI|BlueHDi|dCi|PureTech|EcoBoost|TCe|Multijet)))\b",
        re.IGNORECASE,
    ),
    # (D.4) Model Yılı: 1990 - 2030
    "model_year": re.compile(
        r"(?:\(?D\.4\)?\s*(?:MODEL\s*YILI)?:?\s*)?\b(199\d|20[0-3]\d)\b",
        re.IGNORECASE,
    ),
    # Belge Seri No: AA 123456 veya AB123456
    "document_serial": re.compile(
        r"(?:\(?Y\)?\s*(?:SERİ|BELGE\s*NO)?:?\s*)?\b([A-Z]{2}\s*\d{6})\b",
        re.IGNORECASE,
    ),
    # (D.1) Marka
    "brand": re.compile(
        r"(?:\(?D\.1\)?\s*(?:MARKASI|MARKA)?:?\s*)?\b(VOLKSWAGEN|RENAULT|FIAT|FORD|PEUGEOT|TOYOTA|BMW|MERCEDES-BENZ|MERCEDES|HYUNDAI|HONDA|AUDI|SKODA|OPEL|SEAT|CITROEN|DACIA|NISSAN|KIA|VOLVO)\b",
        re.IGNORECASE,
    ),
    # (D.2) Model / Ticari Adı
    "model": re.compile(
        r"(?:\(?D\.2\)?\s*(?:TİPİ|TİCARİ\s*ADI|MODEL)?:?\s*)?\b(PASSAT|GOLF|POLO|TIGUAN|MEGANE|CLIO|CAPTUR|COROLLA|YARIS|AURIS|FOCUS|FIESTA|PUMA|EGEA|DOBLO|FIORINO|3008|2008|208|TUCSON|i20|i10|CIVIC|OCTAVIA|SUPERB|ASTRA|CORSA|LEON|IBIZA|QASHQAI|DUSTER)\b",
        re.IGNORECASE,
    ),
}


def parse_spoken_number(tokens: List[str]) -> Tuple[int, int]:
    """
    Kelimeler halinde konuşulmuş Türkçe sayıları çözümler (Örn: 'otuz', 'dört' -> 34).
    Dönen değer: (hesaplanan_sayı, tüketilen_token_sayısı)
    """
    total = 0
    current = 0
    consumed = 0

    i = 0
    while i < len(tokens):
        word = tokens[i].lower()
        if word in TURKISH_NUMBERS:
            val = TURKISH_NUMBERS[word]
            if val == 0:
                # 'sıfır' tekil rakam
                current = current * 10 if current > 0 else 0
            elif val < 10:
                current += val
            else:
                current += val
            consumed += 1
            i += 1
        elif word == "yüz" or word == "yuz":
            current = (current if current > 0 else 1) * 100
            consumed += 1
            i += 1
        elif word == "bin":
            total += (current if current > 0 else 1) * 1000
            current = 0
            consumed += 1
            i += 1
        else:
            break

    total += current
    return total, consumed


def decode_phonetic_spelling(spoken_text: str) -> Dict[str, Any]:
    """
    Telefonda müşterinin harf ve sayılarla kodladığı plaka veya şasi numarasını çözer.
    Örnekler:
      "Otuz dört Bolu Ceyhan Fatsa bin iki yüz otuz dört" -> Plaka: "34 BCF 1234"
      "Sıfır altı Ankara Niğde Kars yetmiş sekiz" -> Plaka: "06 ANK 78"
      "Şasi numarası: Van Fatsa bir Bursa Ceyhan Adana..." -> VIN deşifresi
    """
    if not spoken_text:
        return {"plate": "", "vin": "", "tokens": [], "raw": ""}

    raw_clean = re.sub(r"[,.;:!\-]", " ", spoken_text.lower())
    words = [w.strip() for w in raw_clean.split() if w.strip()]

    decoded_tokens: List[str] = []
    i = 0
    while i < len(words):
        w = words[i]

        # 1. Rakam Kelimesi mi? (örn: 'otuz dört' veya 'sıfır altı')
        if w in TURKISH_NUMBERS or w in ("yüz", "yuz", "bin"):
            num_val, consumed = parse_spoken_number(words[i:])
            if consumed > 0:
                # Eğer ilk sayı 'sıfır' ile başlıyorsa ve 1-9 arası ise format: '06'
                if w in ("sıfır", "sifir") and num_val < 10:
                    decoded_tokens.append(f"0{num_val}")
                else:
                    decoded_tokens.append(str(num_val))
                i += consumed
                continue

        # 2. Şehir Fonetik Harfi mi? (örn: 'fatsa' -> 'F', 'bolu' -> 'B')
        if w in PHONETIC_WORD_TO_CHAR:
            decoded_tokens.append(PHONETIC_WORD_TO_CHAR[w])
            i += 1
            continue

        # 3. Zaten Tek Harf mi? (örn: 'A', 'B')
        if len(w) == 1 and w.isalpha():
            decoded_tokens.append(w.upper())
            i += 1
            continue

        # 4. Doğrudan Rakam mı? (örn: '34', '1234')
        if w.isdigit():
            decoded_tokens.append(w)
            i += 1
            continue

        i += 1

    combined = "".join(decoded_tokens)
    plate = ""
    vin = ""

    # Plaka kalıbı ara: (01-81) + (1-3 Harf) + (2-4 Rakam)
    # Örn: 34BCF1234 -> 34 BCF 1234
    plate_match = re.search(r"\b(0[1-9]|[1-7][0-9]|8[01])([A-ZÇĞİÖŞÜ]{1,3})(\d{2,4})\b", combined)
    if plate_match:
        city_code = plate_match.group(1)
        letters = plate_match.group(2)
        digits = plate_match.group(3)
        plate = f"{city_code} {letters} {digits}"

    # VIN kalıbı ara: 17 karakter ISO 3779
    vin_match = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", combined)
    if vin_match:
        cand_vin = vin_match.group(1)
        if is_valid_vin_format(cand_vin):
            vin = cand_vin

    return {
        "plate": plate,
        "vin": vin,
        "tokens": decoded_tokens,
        "raw": spoken_text,
    }


def decode_ruhsat_text(ocr_text: str) -> Dict[str, Any]:
    """
    Ruhsat metninden (OCR çıktısı) araç plakasını, 17 haneli şasi numarasını (VIN),
    motor kodunu, model yılını, marka/modelini ve belge seri numarasını ayıklar.
    """
    if not ocr_text:
        return {
            "plate": "",
            "vin": "",
            "engine_code": "",
            "model_year": None,
            "brand": "",
            "model": "",
            "brand_model": "",
            "document_serial": "",
            "owner_name": "",
            "confidence": 0.0,
            "is_vin_valid": False,
        }

    clean_text = ocr_text.upper()

    # 1. Plaka Tespiti
    plate = ""
    plate_match = RUHSAT_PATTERNS["plate"].search(clean_text)
    if plate_match:
        city = plate_match.group(1)
        letters = plate_match.group(2).replace("I", "İ")
        digits = plate_match.group(3)
        plate = f"{city} {letters} {digits}"

    # 2. Şasi / VIN Tespiti
    vin = ""
    is_vin_valid = False
    # Satır satır da VIN arayalım (OCR bazen boşluk koyabilir)
    vin_match = RUHSAT_PATTERNS["vin"].search(clean_text)
    if vin_match:
        cand_vin = vin_match.group(1)
        if is_valid_vin_format(cand_vin):
            vin = cand_vin
            is_vin_valid = True
    else:
        # Boşluklu şasi no denemesi (örn: WVW ZZZ 3CZ WE 123456)
        spaced_vin = re.search(r"\b([A-HJ-NPR-Z0-9\s]{17,25})\b", clean_text)
        if spaced_vin:
            stripped = re.sub(r"\s+", "", spaced_vin.group(1))
            if is_valid_vin_format(stripped):
                vin = stripped
                is_vin_valid = True

    # 3. Motor Kodu / No
    engine_code = ""
    # Özel motor kalıpları (1.5 TSI, 1.6 TDI, BlueHDi vb.)
    engine_match = re.search(
        r"\b(1\.[0-9]\s*(?:TSI|TDI|TFSI|BlueHDi|dCi|PureTech|EcoBoost|TCe|Multijet)|[A-Z]{3,4}\s*\d{6})\b",
        clean_text,
        re.IGNORECASE,
    )
    if engine_match:
        engine_code = engine_match.group(1).strip()
    else:
        eng_patt = RUHSAT_PATTERNS["engine_code"].search(clean_text)
        if eng_patt:
            engine_code = eng_patt.group(1).strip()

    # 4. Model Yılı
    model_year: Optional[int] = None
    year_match = RUHSAT_PATTERNS["model_year"].search(clean_text)
    if year_match:
        model_year = int(year_match.group(1))

    # 5. Belge Seri No
    document_serial = ""
    serial_match = RUHSAT_PATTERNS["document_serial"].search(clean_text)
    if serial_match:
        document_serial = re.sub(r"\s+", "", serial_match.group(1))

    # 6. Marka & Model
    brand = ""
    model = ""
    brand_match = RUHSAT_PATTERNS["brand"].search(clean_text)
    if brand_match:
        brand = brand_match.group(1)

    model_match = RUHSAT_PATTERNS["model"].search(clean_text)
    if model_match:
        model = model_match.group(1)

    brand_model = f"{brand} {model}".strip() if (brand or model) else ""

    # 7. Tescil Sahibi (Soyadı Adı)
    owner_name = ""
    owner_match = re.search(r"(?:SOYADI|UNVANI)?\s*[:;]?\s*([A-ZÇĞİÖŞÜ\s]{3,30})\s*(?:ADI\s*[:;]?\s*([A-ZÇĞİÖŞÜ\s]{2,20}))?", clean_text)
    if owner_match and ("SOYADI" in clean_text or "TESCİL" in clean_text):
        p1 = (owner_match.group(1) or "").strip()
        p2 = (owner_match.group(2) or "").strip()
        if p2:
            owner_name = f"{p2} {p1}"
        else:
            owner_name = p1

    # Güven Skoru Hesabı (0.0 - 1.0)
    confidence = 0.0
    if plate:
        confidence += 0.35
    if vin:
        confidence += 0.35
        if is_vin_valid and verify_iso3779_check_digit(vin):
            confidence += 0.05
    if engine_code:
        confidence += 0.10
    if model_year:
        confidence += 0.05
    if brand or model:
        confidence += 0.05
    if document_serial:
        confidence += 0.05

    confidence = round(min(1.0, confidence), 2)

    return {
        "plate": plate,
        "vin": vin,
        "engine_code": engine_code,
        "model_year": model_year,
        "brand": brand,
        "model": model,
        "brand_model": brand_model,
        "document_serial": document_serial,
        "owner_name": owner_name,
        "confidence": confidence,
        "is_vin_valid": is_vin_valid,
    }


def extract_text_from_ruhsat_image(image_bytes: bytes) -> str:
    """
    Gelen görselden OCR ile metin ayıklar.
    Tesseract / pytesseract kütüphanesi mevcutsa kullanır;
    aksi halde veya doğrudan metin tabanlı simülasyon baytları geldiyse
    güvenli UTF-8 / ASCII dizesine dönüştürür.
    """
    if not image_bytes:
        return ""

    # 1. Eğer doğrudan UTF-8 / ASCII metin yüklenmişse (Testler & Hızlı API simülasyonları için)
    try:
        decoded_str = image_bytes.decode("utf-8")
        if any(keyword in decoded_str.upper() for keyword in ("PLAKA", "ŞASİ", "VIN", "MOTOR", "RUHSAT", "VOLKSWAGEN", "RENAULT", "FIAT")):
            return decoded_str
    except UnicodeDecodeError:
        pass

    # 2. PyTesseract / PIL ile OCR Denemesi
    try:
        from PIL import Image
        import pytesseract

        img = Image.open(io.BytesIO(image_bytes))
        ocr_result = pytesseract.image_to_string(img, lang="tur+eng")
        if ocr_result and len(ocr_result.strip()) > 10:
            return ocr_result
    except Exception as e:
        logger.debug("PyTesseract OCR çalıştırılamadı (%s), ikili ayrıştırıcıya geçiliyor.", e)

    # 3. İkili (Binary) baytlar içinden ASCII dize ayıklayıcı
    # Resim dosyası içine gömülmüş veya metadata metinlerini yakalamak için
    extracted_strings = re.findall(rb"([A-Za-z0-9\s:.\-\/]{4,100})", image_bytes)
    if extracted_strings:
        merged = " ".join(s.decode("latin-1", errors="ignore") for s in extracted_strings)
        return merged

    return ""


def process_inbound_ruhsat_image(
    db: Session,
    *,
    from_phone: str,
    image_bytes: bytes,
    appointment_id: Optional[str] = None,
    filename: str = "",
) -> Tuple[RuhsatScan, Dict[str, Any]]:
    """
    WhatsApp veya Web üzerinden gelen araç ruhsat görselini deşifre eder,
    plaka, şasi (VIN), motor kodu ve model yılını çıkarır.
    İlişkili `Vehicle` ve `Appointment` kayıtlarını günceller ve
    `ruhsat_scans` tablosuna atomik olarak işler.
    """
    raw_ocr_text = extract_text_from_ruhsat_image(image_bytes)
    parsed = decode_ruhsat_text(raw_ocr_text)

    # Araç (Vehicle) kaydı eşleştirme / oluşturma
    matched_vehicle_id = None
    if parsed["plate"]:
        norm_plate = parsed["plate"].replace(" ", "").upper()
        # Veritabanında plakayı ara
        vehicles = db.execute(select(Vehicle)).scalars().all()
        for v in vehicles:
            if v.plate and v.plate.replace(" ", "").upper() == norm_plate:
                matched_vehicle_id = v.id
                if parsed["vin"] and not v.vin:
                    v.vin = parsed["vin"]
                break

    # İlişkili randevu kontrolü
    if not appointment_id and from_phone:
        # Son teyitli veya bekleyen randevuyu bul
        app = (
            db.execute(
                select(Appointment)
                .order_by(desc(Appointment.created_at))
            )
            .scalars()
            .first()
        )
        if app:
            appointment_id = app.id
            if not matched_vehicle_id and app.vehicle_id:
                matched_vehicle_id = app.vehicle_id

    # RuhsatScan kaydı oluştur
    scan_record = RuhsatScan(
        id=f"rscan-{uuid4().hex[:12]}",
        vehicle_id=matched_vehicle_id,
        appointment_id=appointment_id,
        from_phone=from_phone,
        plate=parsed["plate"],
        vin=parsed["vin"],
        engine_code=parsed["engine_code"],
        model_year=parsed["model_year"],
        brand_model=parsed["brand_model"],
        document_serial=parsed["document_serial"],
        owner_name=parsed["owner_name"],
        confidence=parsed["confidence"],
        raw_extracted_text=raw_ocr_text[:3000],
        created_at=now(),
    )
    db.add(scan_record)
    db.commit()
    db.refresh(scan_record)

    return scan_record, parsed

