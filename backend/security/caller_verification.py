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

import hmac
import re
from dataclasses import dataclass
from enum import Enum


class CallerVerificationStatus(str, Enum):
    """Per-call second-factor verification outcome (ADR-F3-01)."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FAILED_RETRY = "FAILED_RETRY"
    LOCKED_OPERATOR_REQUIRED = "LOCKED_OPERATOR_REQUIRED"
    NO_SECOND_FACTOR_ON_RECORD = "NO_SECOND_FACTOR_ON_RECORD"


@dataclass(frozen=True, slots=True)
class CallerVerificationRecord:
    """Stored second-factor values kept strictly inside deterministic M07 scope."""

    customer_ref: str
    birth_year: str | None = None
    plate: str | None = None


@dataclass(frozen=True, slots=True)
class CallerVerificationOutcome:
    """Safe projection returned to dialogue/LLM — never leaks stored birth year or plate."""

    status: CallerVerificationStatus
    verified: bool
    attempts_used: int
    attempts_remaining: int
    requires_operator_transfer: bool
    factor_prompt_kind: str | None = None


def _normalize_digits_alnum(raw: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", raw.strip().upper())


class CallerVerificationSession:
    """Per-call deterministic second-factor verifier per ADR-F3-01.

    Rules enforced:
    - Phone number alone never authorizes private reads/mutations.
    - Birth year is preferred; if absent on record, last 3-4 digits of plate.
    - If neither exists on record, private access is denied and operator transfer offered.
    - Max 3 failed attempts per call; locked thereafter for this call only.
    - Stored values never leave this verifier (never returned in Outcome/LLM context/logs).
    """

    def __init__(
        self,
        *,
        call_id: str,
        record: CallerVerificationRecord | None,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._call_id = call_id
        self._record = record
        self._max_attempts = max_attempts
        self._attempts = 0
        self._verified = False
        self._locked = False

    @property
    def call_id(self) -> str:
        return self._call_id

    @property
    def is_verified(self) -> bool:
        return self._verified

    def required_factor_kind(self) -> str | None:
        if self._record is None:
            return None
        if self._record.birth_year and self._record.birth_year.strip():
            return "birth_year"
        if self._record.plate and len(_normalize_digits_alnum(self._record.plate)) >= 3:
            return "plate_suffix"
        return None

    def verify_attempt(self, *, provided_value: str) -> CallerVerificationOutcome:
        """Deterministically verify birth year or last 3-4 plate characters."""
        if self._verified:
            return CallerVerificationOutcome(
                status=CallerVerificationStatus.VERIFIED,
                verified=True,
                attempts_used=self._attempts,
                attempts_remaining=max(0, self._max_attempts - self._attempts),
                requires_operator_transfer=False,
                factor_prompt_kind=self.required_factor_kind(),
            )

        factor = self.required_factor_kind()
        if factor is None or self._record is None:
            self._locked = True
            return CallerVerificationOutcome(
                status=CallerVerificationStatus.NO_SECOND_FACTOR_ON_RECORD,
                verified=False,
                attempts_used=self._attempts,
                attempts_remaining=0,
                requires_operator_transfer=True,
                factor_prompt_kind=None,
            )

        if self._locked or self._attempts >= self._max_attempts:
            self._locked = True
            return CallerVerificationOutcome(
                status=CallerVerificationStatus.LOCKED_OPERATOR_REQUIRED,
                verified=False,
                attempts_used=self._attempts,
                attempts_remaining=0,
                requires_operator_transfer=True,
                factor_prompt_kind=factor,
            )

        self._attempts += 1
        cleaned = _normalize_digits_alnum(provided_value)
        matched = False

        if factor == "birth_year" and self._record.birth_year is not None:
            expected_year = _normalize_digits_alnum(self._record.birth_year)
            matched = bool(cleaned) and len(cleaned) == 4 and hmac.compare_digest(cleaned, expected_year)
        elif factor == "plate_suffix" and self._record.plate is not None:
            expected_plate = _normalize_digits_alnum(self._record.plate)
            if len(cleaned) in (3, 4) and len(expected_plate) >= len(cleaned):
                matched = hmac.compare_digest(cleaned, expected_plate[-len(cleaned) :])

        if matched:
            self._verified = True
            return CallerVerificationOutcome(
                status=CallerVerificationStatus.VERIFIED,
                verified=True,
                attempts_used=self._attempts,
                attempts_remaining=max(0, self._max_attempts - self._attempts),
                requires_operator_transfer=False,
                factor_prompt_kind=factor,
            )

        if self._attempts >= self._max_attempts:
            self._locked = True
            return CallerVerificationOutcome(
                status=CallerVerificationStatus.LOCKED_OPERATOR_REQUIRED,
                verified=False,
                attempts_used=self._attempts,
                attempts_remaining=0,
                requires_operator_transfer=True,
                factor_prompt_kind=factor,
            )

        return CallerVerificationOutcome(
            status=CallerVerificationStatus.FAILED_RETRY,
            verified=False,
            attempts_used=self._attempts,
            attempts_remaining=self._max_attempts - self._attempts,
            requires_operator_transfer=False,
            factor_prompt_kind=factor,
        )


__all__ = [
    "CallerVerificationOutcome",
    "CallerVerificationRecord",
    "CallerVerificationSession",
    "CallerVerificationStatus",
]
