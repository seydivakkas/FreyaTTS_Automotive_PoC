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

import re

_ONES = (
    "",
    "bir",
    "iki",
    "üç",
    "dört",
    "beş",
    "altı",
    "yedi",
    "sekiz",
    "dokuz",
)
_TENS = (
    "",
    "on",
    "yirmi",
    "otuz",
    "kırk",
    "elli",
    "altmış",
    "yetmiş",
    "seksen",
    "doksan",
)

# Belirtme (-i/-ı/-u/-ü) ve yönelme (-e/-a) durumları, saat 1..12 için (ADR-F4-02)
_HOUR_NOM = {
    1: "bir",
    2: "iki",
    3: "üç",
    4: "dört",
    5: "beş",
    6: "altı",
    7: "yedi",
    8: "sekiz",
    9: "dokuz",
    10: "on",
    11: "on bir",
    12: "on iki",
}
_HOUR_ACC = {
    1: "biri",
    2: "ikiyi",
    3: "üçü",
    4: "dördü",
    5: "beşi",
    6: "altıyı",
    7: "yediyi",
    8: "sekizi",
    9: "dokuzu",
    10: "onu",
    11: "on biri",
    12: "on ikiyi",
}
_HOUR_DAT = {
    1: "bire",
    2: "ikiye",
    3: "üçe",
    4: "dörde",
    5: "beşe",
    6: "altıya",
    7: "yediye",
    8: "sekize",
    9: "dokuza",
    10: "ona",
    11: "on bire",
    12: "on ikiye",
}
_HOUR_LOC = {
    1: "birde",
    2: "ikide",
    3: "üçte",
    4: "dörtte",
    5: "beşte",
    6: "altıda",
    7: "yedide",
    8: "sekizde",
    9: "dokuzda",
    10: "onda",
    11: "on birde",
    12: "on ikide",
}


def _int_to_turkish_under_1000(n: int) -> str:
    """Convert 0..999 integer to Turkish words."""
    if n == 0:
        return "sıfır"
    parts: list[str] = []
    hundreds = n // 100
    rem = n % 100
    if hundreds == 1:
        parts.append("yüz")
    elif hundreds > 1:
        parts.append(f"{_ONES[hundreds]} yüz")
    tens = rem // 10
    ones = rem % 10
    if tens:
        parts.append(_TENS[tens])
    if ones:
        parts.append(_ONES[ones])
    return " ".join(parts)


def _day_period_24h(hour24: int) -> str:
    """Resolve Turkish day period per ADR-F4-02."""
    if 5 <= hour24 <= 11:
        return "sabah"
    if hour24 == 12:
        return "öğlen"
    if 13 <= hour24 <= 17:
        return "öğleden sonra"
    if 18 <= hour24 <= 21:
        return "akşam"
    return "gece"


def format_turkish_time(hour: int, minute: int, *, with_locative: bool = False) -> str:
    """Format 24-hour time into natural spoken Turkish per ADR-F4-02.

    Examples:
      09:30 -> 'sabah dokuz buçuk'
      14:00 -> 'öğleden sonra iki'
      09:15 -> 'sabah dokuzu çeyrek geçe'
      09:45 -> 'sabah ona çeyrek var'
      11:45 -> 'sabah on ikiye çeyrek var'
      00:00 -> 'gece yarısı'
    """
    if isinstance(hour, bool) or isinstance(minute, bool):
        raise ValueError("hour and minute must be integers, not bool")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time: {hour:02d}:{minute:02d}")

    if hour == 0 and minute == 0:
        return "gece yarısında" if with_locative else "gece yarısı"

    period = _day_period_24h(hour)
    h12 = hour % 12 or 12
    next_h12 = (hour + 1) % 12 or 12

    if minute == 0:
        hour_word = _HOUR_LOC[h12] if with_locative else _HOUR_NOM[h12]
        return f"{period} {hour_word}"

    if minute == 30:
        suffix = "buçukta" if with_locative else "buçuk"
        return f"{period} {_HOUR_NOM[h12]} {suffix}"

    if minute == 15:
        return f"{period} {_HOUR_ACC[h12]} çeyrek geçe"

    if minute == 45:
        tail = "çeyrek kala" if with_locative else "çeyrek var"
        return f"{period} {_HOUR_DAT[next_h12]} {tail}"

    if 1 <= minute <= 29:
        min_word = _int_to_turkish_under_1000(minute)
        return f"{period} {_HOUR_ACC[h12]} {min_word} geçe"

    rem_min = 60 - minute
    min_word = _int_to_turkish_under_1000(rem_min)
    tail = "kala" if with_locative else "var"
    return f"{period} {_HOUR_DAT[next_h12]} {min_word} {tail}"


def _read_digit_group(group: str) -> str:
    """Read a 2- or 3-digit group preserving leading zeros per ADR-F4-03."""
    if not group:
        return ""
    leading_zeros = len(group) - len(group.lstrip("0"))
    if leading_zeros == len(group):
        return " ".join(["sıfır"] * len(group))
    prefix = " ".join(["sıfır"] * leading_zeros)
    rest_val = int(group[leading_zeros:])
    rest_words = _int_to_turkish_under_1000(rest_val)
    return f"{prefix} {rest_words}".strip()


def format_turkish_phone(phone: str) -> str:
    """Format Turkish phone number in 4-3-2-2 groups (05xx xxx xx xx) per ADR-F4-03.

    Non-standard / short / international numbers fall back to digit-by-digit
    without inventing missing digits.
    """
    digits = re.sub(r"[^\d+]", "", phone.strip())
    if digits.startswith("+90"):
        digits = "0" + digits[3:]
    elif digits.startswith("0090"):
        digits = "0" + digits[4:]
    elif digits.startswith("+"):
        digits = digits[1:]

    if len(digits) == 11 and digits.startswith("0") and digits.isdigit():
        g1 = _read_digit_group(digits[0:4])
        g2 = _read_digit_group(digits[4:7])
        g3 = _read_digit_group(digits[7:9])
        g4 = _read_digit_group(digits[9:11])
        return f"{g1}, {g2}, {g3}, {g4}"

    # Fallback: digit-by-digit for short/international numbers
    digit_words = {
        "0": "sıfır",
        "1": "bir",
        "2": "iki",
        "3": "üç",
        "4": "dört",
        "5": "beş",
        "6": "altı",
        "7": "yedi",
        "8": "sekiz",
        "9": "dokuz",
    }
    return " ".join(digit_words[ch] for ch in digits if ch in digit_words)


__all__ = ["format_turkish_phone", "format_turkish_time"]
