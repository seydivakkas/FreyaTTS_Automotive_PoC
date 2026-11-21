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

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np

logger = logging.getLogger("redaction_kvkk_guard")

# Türkçe Rakam Kelimeleri
SPOKEN_DIGITS: Dict[str, str] = {
    "sıfır": "0", "sifir": "0",
    "bir": "1",
    "iki": "2",
    "üç": "3", "uc": "3",
    "dört": "4", "dort": "4",
    "beş": "5", "bes": "5",
    "altı": "6", "alti": "6",
    "yedi": "7",
    "sekiz": "8",
    "dokuz": "9",
}

# Regex Kalıpları
# 1. TCKN: 11 basamaklı sayı (0 ile başlayamaz)
TCKN_REGEX = re.compile(r"\b([1-9]\d{10})\b")

# 2. Kredi / Banka Kartı: 13-19 basamaklı (boşluklu veya tireli: 4543 1234 5678 9012)
CARD_REGEX = re.compile(
    r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|2(?:2[2-9][0-9]{12}|[3-6][0-9]{13}|7[0-1][0-9]{12}|720[0-9]{12})|3[47][0-9]{13}|9792[0-9]{12}|(?:[0-9]{4}[-\s]?){3}[0-9]{4})\b"
)

# 3. CVV / CVC: "cvv", "cvc", "güvenlik kodu" ardından 3-4 basamaklı sayı
CVV_REGEX = re.compile(
    r"\b(?:cvv|cvc|güvenlik\s*kodu|güvenlik\s*numarası)[:\s]*([0-9]{3,4})\b",
    re.IGNORECASE,
)

# 4. Son Kullanma Tarihi (MM/YY veya MM/YYYY)
EXPIRY_REGEX = re.compile(
    r"\b(?:son\s*kullanma\s*tarihi|skt|sk\s*tarihi)?[:\s]*(0[1-9]|1[0-2])\s*[\/\-]\s*([2-3][0-9]{1,3})\b",
    re.IGNORECASE,
)

# 5. Türkiye Telefon Numarası: 05xx xxx xx xx, +90 5xx ...
PHONE_REGEX = re.compile(
    r"(?:\+?90\s*|0)?(5[0-9]{2})[\s\-]?([0-9]{3})[\s\-]?([0-9]{2})[\s\-]?([0-9]{2})\b"
)

# 6. E-posta Adresi
EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"
)

# 7. Türkiye IBAN (TR + 24 basamak)
IBAN_REGEX = re.compile(
    r"\bTR\s*(?:[0-9]{2}\s*)(?:[0-9]{4}\s*){5}[0-9]{2}\b",
    re.IGNORECASE,
)


def is_valid_tckn(tckn: Union[str, int]) -> bool:
    """
    T.C. Kimlik Numarası algoritma doğrulaması.
    Kurallar:
      1. 11 basamaktan oluşmalıdır ve tamamı rakam olmalıdır.
      2. İlk basamak '0' olamaz.
      3. (7 * (d1 + d3 + d5 + d7 + d9) - (d2 + d4 + d6 + d8)) % 10 == d10
      4. sum(d1..d10) % 10 == d11
    """
    s = str(tckn).strip()
    if len(s) != 11 or not s.isdigit():
        return False
    if s[0] == "0":
        return False

    digits = [int(c) for c in s]

    # Kural 1: 10. basamak kontrolü
    odd_sum = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
    even_sum = digits[1] + digits[3] + digits[5] + digits[7]
    d10 = (7 * odd_sum - even_sum) % 10
    if d10 != digits[9]:
        return False

    # Kural 2: 11. basamak kontrolü
    if sum(digits[:10]) % 10 != digits[10]:
        return False

    return True


def is_valid_luhn(card_number: Union[str, int]) -> bool:
    """
    Luhn Algoritması (Mod 10) ile kredi/banka kartı numarası doğrulaması.
    Visa, Mastercard, Troy, Amex standartlarına uygundur.
    """
    clean = re.sub(r"\D", "", str(card_number))
    if len(clean) < 13 or len(clean) > 19:
        return False

    total = 0
    reverse_digits = [int(c) for c in reversed(clean)]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            doubled = d * 2
            total += (doubled - 9) if doubled > 9 else doubled
        else:
            total += d

    return total % 10 == 0


def is_valid_tr_iban(iban: str) -> bool:
    """
    Türkiye IBAN doğrulaması (Mod 97 kontrolü).
    """
    clean = re.sub(r"\s+", "", str(iban)).upper()
    if len(clean) != 26 or not clean.startswith("TR"):
        return False
    if not clean[2:].isdigit():
        return False

    # TR ve kontrol basamaklarını sona taşı: TRXX -> XX TR -> XX 29 27
    reordered = clean[4:] + str(ord(clean[0]) - 55) + str(ord(clean[1]) - 55) + clean[2:4]
    try:
        return int(reordered) % 97 == 1
    except ValueError:
        return False


def mask_tckn(tckn: str, mask_char: str = "*") -> str:
    """
    TCKN maskeleme: İlk 3 ve son 2 basamağı gösterir, ortadaki 6 basamağı maskeler.
    Örnek: 12345678901 -> 123******01
    """
    s = re.sub(r"\D", "", str(tckn))
    if len(s) == 11:
        return f"{s[:3]}{mask_char * 6}{s[9:]}"
    return mask_char * len(s)


def mask_credit_card(card: str, mask_char: str = "*") -> str:
    """
    Kredi kartı maskeleme: İlk 4 (veya 6 BIN) ve son 4 haneyi gösterir.
    Örnek: 4543 1234 5678 9012 -> 4543 **** **** 9012
    """
    digits = re.sub(r"\D", "", str(card))
    if len(digits) >= 15:
        first4 = digits[:4]
        last4 = digits[-4:]
        middle_len = len(digits) - 8
        groups = []
        groups.append(first4)
        for _ in range((middle_len + 3) // 4):
            groups.append(mask_char * 4)
        groups.append(last4)
        return " ".join(groups)
    return mask_char * len(card)


def mask_phone(phone: str, mask_char: str = "*") -> str:
    """
    Telefon maskeleme: Alan kodu ve son 2 basamağı korur.
    Örnek: 0532 123 45 67 -> 0532 *** ** 67
    """
    clean = re.sub(r"\D", "", str(phone))
    if clean.startswith("90") and len(clean) == 12:
        clean = "0" + clean[2:]
    if len(clean) == 11 and clean.startswith("05"):
        return f"{clean[:4]} {mask_char * 3} {mask_char * 2} {clean[9:]}"
    elif len(clean) == 10 and clean.startswith("5"):
        return f"0{clean[:3]} {mask_char * 3} {mask_char * 2} {clean[8:]}"
    return mask_char * len(phone)


def mask_email(email: str, mask_char: str = "*") -> str:
    """
    E-posta maskeleme: İlk harf, son harf ve etki alanını korur.
    Örnek: ahmet.yilmaz@gmail.com -> a**********z@gmail.com
    """
    if "@" not in email:
        return mask_char * len(email)
    user_part, domain_part = email.split("@", 1)
    if len(user_part) <= 2:
        masked_user = mask_char * len(user_part)
    else:
        masked_user = f"{user_part[0]}{mask_char * (len(user_part) - 2)}{user_part[-1]}"
    return f"{masked_user}@{domain_part}"


def mask_iban(iban: str, mask_char: str = "*") -> str:
    """
    IBAN maskeleme: TR ve son 4 haneyi korur.
    Örnek: TR12 3456 7890 1234 5678 9012 34 -> TR** **** **** **** **** **12 34
    """
    clean = re.sub(r"\s+", "", str(iban)).upper()
    if len(clean) == 26:
        return f"TR{mask_char * 2} {mask_char * 4} {mask_char * 4} {mask_char * 4} {mask_char * 4} {mask_char * 2}{clean[-4:-2]} {clean[-2:]}"
    return f"TR{mask_char * (len(clean) - 2)}"


@dataclass
class RedactionEntity:
    entity_type: str
    raw_value: str
    masked_value: str
    start_pos: int
    end_pos: int
    is_valid: bool


@dataclass
class RedactionResult:
    original_text: str
    redacted_text: str
    entities: List[Dict[str, Any]] = field(default_factory=list)
    redaction_count: int = 0


class KVKKGuard:
    """
    Kurumsal KVKK / GDPR Veri Maskeleme ve Koruma Kalkanı.
    Metin, transkript ve ses kayıtlarındaki hassas kişisel verileri
    algoritmik denetimlerle tespit eder ve maskeler.
    """

    def __init__(
        self,
        *,
        mask_char: str = "*",
        validate_strict: bool = True,
        enabled_categories: Optional[Set[str]] = None,
        beep_freq_hz: float = 1000.0,
    ):
        self.mask_char = mask_char
        self.validate_strict = validate_strict
        self.enabled_categories = enabled_categories or {
            "tckn",
            "credit_card",
            "cvv",
            "expiry",
            "phone",
            "email",
            "iban",
            "spoken_numbers",
        }
        self.beep_freq_hz = beep_freq_hz

    def redact_spoken_numbers(self, text: str) -> Tuple[str, List[RedactionEntity]]:
        """
        Telefonda sesli telaffuz edilen ardışık rakam dizilerini (Örn: 'TC kimlik numaram bir iki üç...')
        çözümler, TCKN veya Kredi Kartı kuralına uyuyorsa maskeler.
        """
        if "spoken_numbers" not in self.enabled_categories:
            return text, []

        tokens = text.split()
        entities: List[RedactionEntity] = []
        i = 0
        result_tokens = list(tokens)

        while i < len(tokens):
            w = tokens[i].lower().strip(".,!?:")
            if w in SPOKEN_DIGITS:
                # Kesintisiz rakam serisini topla
                start_idx = i
                run_digits = []
                while i < len(tokens):
                    cw = tokens[i].lower().strip(".,!?:")
                    if cw in SPOKEN_DIGITS:
                        run_digits.append(SPOKEN_DIGITS[cw])
                        i += 1
                    else:
                        break
                digit_seq = "".join(run_digits)

                # 11 Basamaklı TCKN Kontrolü
                if len(digit_seq) == 11 and (not self.validate_strict or is_valid_tckn(digit_seq)):
                    masked_val = f"[TCKN MASKELENDİ: {mask_tckn(digit_seq, self.mask_char)}]"
                    for k in range(start_idx, i):
                        result_tokens[k] = ""
                    result_tokens[start_idx] = masked_val
                    entities.append(
                        RedactionEntity(
                            entity_type="spoken_tckn",
                            raw_value=" ".join(tokens[start_idx:i]),
                            masked_value=masked_val,
                            start_pos=start_idx,
                            end_pos=i,
                            is_valid=is_valid_tckn(digit_seq),
                        )
                    )
                # 16 Basamaklı Kredi Kartı Kontrolü
                elif len(digit_seq) in (15, 16) and (not self.validate_strict or is_valid_luhn(digit_seq)):
                    masked_val = f"[KART MASKELENDİ: {mask_credit_card(digit_seq, self.mask_char)}]"
                    for k in range(start_idx, i):
                        result_tokens[k] = ""
                    result_tokens[start_idx] = masked_val
                    entities.append(
                        RedactionEntity(
                            entity_type="spoken_card",
                            raw_value=" ".join(tokens[start_idx:i]),
                            masked_value=masked_val,
                            start_pos=start_idx,
                            end_pos=i,
                            is_valid=is_valid_luhn(digit_seq),
                        )
                    )
            else:
                i += 1

        filtered_tokens = [t for t in result_tokens if t]
        return " ".join(filtered_tokens), entities

    def redact_text(self, text: str) -> RedactionResult:
        """
        Metin içindeki tüm hassas kişisel verileri (TCKN, Kredi Kartı, CVV,
        Telefon, E-posta, IBAN) regex ve algoritmik doğrulamalarla maskeler.
        """
        if not text:
            return RedactionResult(original_text="", redacted_text="", entities=[], redaction_count=0)

        current_text = text
        found_entities: List[RedactionEntity] = []

        # 1. Sesli Rakam Dizilerini Çözümle
        current_text, spoken_entities = self.redact_spoken_numbers(current_text)
        found_entities.extend(spoken_entities)

        # 2. IBAN Maskeleme
        if "iban" in self.enabled_categories:
            for match in IBAN_REGEX.finditer(current_text):
                raw = match.group(0)
                valid = is_valid_tr_iban(raw)
                if not self.validate_strict or valid:
                    masked = mask_iban(raw, self.mask_char)
                    found_entities.append(
                        RedactionEntity(
                            entity_type="iban",
                            raw_value=raw,
                            masked_value=masked,
                            start_pos=match.start(),
                            end_pos=match.end(),
                            is_valid=valid,
                        )
                    )
                    current_text = current_text.replace(raw, masked)

        # 3. Kredi Kartı (Luhn Doğrulamalı)
        if "credit_card" in self.enabled_categories:
            for match in CARD_REGEX.finditer(current_text):
                raw = match.group(0)
                clean_digits = re.sub(r"\D", "", raw)
                valid = is_valid_luhn(clean_digits)
                if not self.validate_strict or valid:
                    masked = mask_credit_card(raw, self.mask_char)
                    found_entities.append(
                        RedactionEntity(
                            entity_type="credit_card",
                            raw_value=raw,
                            masked_value=masked,
                            start_pos=match.start(),
                            end_pos=match.end(),
                            is_valid=valid,
                        )
                    )
                    current_text = current_text.replace(raw, masked)

        # 4. CVV / CVC Maskeleme
        if "cvv" in self.enabled_categories:
            for match in CVV_REGEX.finditer(current_text):
                raw_cvv = match.group(1)
                masked_cvv = self.mask_char * len(raw_cvv)
                full_raw = match.group(0)
                full_masked = full_raw.replace(raw_cvv, masked_cvv)
                found_entities.append(
                    RedactionEntity(
                        entity_type="cvv",
                        raw_value=raw_cvv,
                        masked_value=masked_cvv,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        is_valid=True,
                    )
                )
                current_text = current_text.replace(full_raw, full_masked)

        # 5. TCKN Maskeleme (11 Basamak + Algoritmik Doğrulama)
        if "tckn" in self.enabled_categories:
            for match in TCKN_REGEX.finditer(current_text):
                raw = match.group(1)
                valid = is_valid_tckn(raw)
                if not self.validate_strict or valid:
                    masked = mask_tckn(raw, self.mask_char)
                    found_entities.append(
                        RedactionEntity(
                            entity_type="tckn",
                            raw_value=raw,
                            masked_value=masked,
                            start_pos=match.start(),
                            end_pos=match.end(),
                            is_valid=valid,
                        )
                    )
                    current_text = current_text.replace(raw, masked)

        # 6. E-posta Maskeleme
        if "email" in self.enabled_categories:
            for match in EMAIL_REGEX.finditer(current_text):
                raw = match.group(0)
                masked = mask_email(raw, self.mask_char)
                found_entities.append(
                    RedactionEntity(
                        entity_type="email",
                        raw_value=raw,
                        masked_value=masked,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        is_valid=True,
                    )
                )
                current_text = current_text.replace(raw, masked)

        # 7. Telefon Maskeleme
        if "phone" in self.enabled_categories:
            for match in PHONE_REGEX.finditer(current_text):
                raw = match.group(0)
                masked = mask_phone(raw, self.mask_char)
                found_entities.append(
                    RedactionEntity(
                        entity_type="phone",
                        raw_value=raw,
                        masked_value=masked,
                        start_pos=match.start(),
                        end_pos=match.end(),
                        is_valid=True,
                    )
                )
                current_text = current_text.replace(raw, masked)

        return RedactionResult(
            original_text=text,
            redacted_text=current_text,
            entities=[asdict(e) for e in found_entities],
            redaction_count=len(found_entities),
        )

    def redact_audio(
        self,
        audio_data: np.ndarray,
        sample_rate: int,
        time_ranges: List[Tuple[float, float]],
        mode: str = "beep",
    ) -> np.ndarray:
        """
        Ses kaydı üzerindeki hassas zaman aralıklarını sessize alır ('mute')
        veya 1000 Hz sinüs bip sesiyle ('beep') maskeler.
        Tıklama / patlama sesini önlemek için 5 ms kosinüs yumuşatma uygulanır.
        """
        if audio_data is None or len(audio_data) == 0:
            return audio_data

        out = np.copy(audio_data).astype(np.float32)
        total_samples = len(out)
        ramp_len = max(2, int(0.005 * sample_rate))  # 5 ms rampa

        for start_sec, end_sec in time_ranges:
            start_idx = max(0, int(start_sec * sample_rate))
            end_idx = min(total_samples, int(end_sec * sample_rate))
            if end_idx <= start_idx:
                continue

            seg_len = end_idx - start_idx

            if mode == "mute" or mode == "silence":
                # Sessizleştirme (Cosine Fade In / Fade Out ile)
                if seg_len > 2 * ramp_len:
                    fade_out = 0.5 * (1 + np.cos(np.linspace(0, np.pi, ramp_len)))
                    fade_in = 0.5 * (1 - np.cos(np.linspace(0, np.pi, ramp_len)))
                    out[start_idx : start_idx + ramp_len] *= fade_out
                    out[start_idx + ramp_len : end_idx - ramp_len] = 0.0
                    out[end_idx - ramp_len : end_idx] *= fade_in
                else:
                    out[start_idx:end_idx] = 0.0

            elif mode == "beep" or mode == "sine":
                # 1000 Hz Bip Sesi (Genlik -12 dBFS ≈ 0.25)
                t = np.arange(seg_len) / sample_rate
                beep_signal = (0.25 * np.sin(2 * np.pi * self.beep_freq_hz * t)).astype(np.float32)
                if seg_len > 2 * ramp_len:
                    fade_in = 0.5 * (1 - np.cos(np.linspace(0, np.pi, ramp_len)))
                    fade_out = 0.5 * (1 + np.cos(np.linspace(0, np.pi, ramp_len)))
                    beep_signal[:ramp_len] *= fade_in
                    beep_signal[-ramp_len:] *= fade_out

                out[start_idx:end_idx] = beep_signal

            elif mode == "noise":
                # Konfor Gürültüsü (-48 dBFS)
                noise = np.random.normal(0.0, 0.004, seg_len).astype(np.float32)
                out[start_idx:end_idx] = noise

        return out


# Global singleton varsayılan koruma örneği
default_kvkk_guard = KVKKGuard()


def redact_text(
    text: str,
    categories: Optional[Set[str]] = None,
    mask_char: str = "*",
    validate_strict: bool = True,
) -> RedactionResult:
    """Tekil metin maskeleme yardımcı fonksiyonu."""
    guard = KVKKGuard(
        mask_char=mask_char,
        validate_strict=validate_strict,
        enabled_categories=categories,
    )
    return guard.redact_text(text)


def redact_audio(
    audio_data: np.ndarray,
    sample_rate: int,
    time_ranges: List[Tuple[float, float]],
    mode: str = "beep",
    beep_freq: float = 1000.0,
) -> np.ndarray:
    """Ses maskeleme yardımcı fonksiyonu."""
    guard = KVKKGuard(beep_freq_hz=beep_freq)
    return guard.redact_audio(audio_data, sample_rate, time_ranges, mode=mode)


def redact_dialogue_turns(
    turns: List[Dict[str, Any]],
    guard: Optional[KVKKGuard] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Diyalog turları listesindeki tüm kullanıcı ve asistan metinlerini maskeler.
    Dönen değer: (maskelenmiş_turlar, toplam_maskeleme_adedi)
    """
    active_guard = guard or default_kvkk_guard
    redacted_turns: List[Dict[str, Any]] = []
    total_redactions = 0

    for turn in turns:
        t_copy = dict(turn)
        orig_text = str(t_copy.get("text", ""))
        if orig_text:
            res = active_guard.redact_text(orig_text)
            t_copy["text"] = res.redacted_text
            total_redactions += res.redaction_count
        redacted_turns.append(t_copy)

    return redacted_turns, total_redactions

