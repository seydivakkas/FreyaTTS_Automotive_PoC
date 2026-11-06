"""Vehicle Identification Number (VIN / Şase No) validation according to ISO 3779."""

import re

# ISO 3779 forbids letters I (India), O (Oscar), and Q (Quebec) to avoid confusion with digits 1 and 0.
VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

VIN_TRANSLITERATION = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
}

VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


def is_valid_vin_format(vin: str) -> bool:
    """Check if VIN has valid 17-character structure without forbidden characters (I, O, Q)."""
    if not vin or not isinstance(vin, str):
        return False
    clean = vin.strip().upper()
    return bool(VIN_PATTERN.match(clean))


def calculate_check_digit(vin: str) -> str:
    """Calculate ISO 3779 / North American position-9 check digit."""
    clean = vin.strip().upper()
    if not VIN_PATTERN.match(clean):
        raise ValueError("Geçersiz VIN formatı")
    total = sum(VIN_TRANSLITERATION[clean[i]] * VIN_WEIGHTS[i] for i in range(17))
    remainder = total % 11
    return "X" if remainder == 10 else str(remainder)


def verify_iso3779_check_digit(vin: str) -> bool:
    """Verify position 9 against the calculated checksum."""
    clean = vin.strip().upper()
    if not is_valid_vin_format(clean):
        return False
    expected = calculate_check_digit(clean)
    return clean[8] == expected


def validate_vin(vin: str, strict_check_digit: bool = False) -> str:
    """Clean and validate VIN. Raises ValueError if invalid."""
    if not vin:
        return ""
    clean = vin.strip().upper()
    if not is_valid_vin_format(clean):
        raise ValueError(
            "Geçersiz şase numarası (VIN). 17 karakter olmalı ve I, O, Q harfleri içermemelidir."
        )
    if strict_check_digit and not verify_iso3779_check_digit(clean):
        raise ValueError("Şase numarası kontrol basamağı (check digit) doğrulanamadı.")
    return clean

