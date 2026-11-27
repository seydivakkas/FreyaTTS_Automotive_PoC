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

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from backend.core.contracts.recognition import EntityCandidate
from backend.core.contracts.validation import require_safe_id, require_strict_int

_ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
_WEEKDAYS_TR: tuple[str, ...] = (
    "pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar",
)
_RELATIVE_DATE_RE = re.compile(
    r"\b(" + "|".join((*_WEEKDAYS_TR, "bugün", "yarın")) + r")\b",
    re.IGNORECASE,
)
_EXPLICIT_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_EXPLICIT_TR_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")
_TIME_RE = re.compile(r"\b([012]?\d)[:.]([0-5]\d)\b")
_VALID_CURRENCIES: frozenset[str] = frozenset({"TRY", "EUR", "USD"})

_UNTRUSTED_SLOT_SOURCES: frozenset[str] = frozenset({
    "asr_final",
    "asr_partial",
    "m05_lexicon",
    "llm_output",
    "caller_id",
    "plate_text",
})
_TRUSTED_IDENTITY_SOURCES: frozenset[str] = frozenset({
    "m07_verified",
    "operator_session",
    "otp_challenge",
    "mfa_verified",
    "signed_token",
})


class SlotStatus(StrEnum):
    """Authoritative slot lifecycle statuses."""

    EMPTY = "EMPTY"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class SlotFamily(StrEnum):
    """Typed slot domain families."""

    CUSTOMER = "CUSTOMER"
    VEHICLE = "VEHICLE"
    SERVICE = "SERVICE"
    APPOINTMENT = "APPOINTMENT"
    QUOTE = "QUOTE"
    CONTACT = "CONTACT"
    TRANSFER = "TRANSFER"
    COMPLAINT = "COMPLAINT"


@dataclass(frozen=True, slots=True)
class SlotSpec:
    """Catalog specification defining allowed type, dependencies, and confirmation invalidation."""

    key: str
    family: SlotFamily
    value_type: str  # "str" | "int" | "decimal" | "iso_date" | "iso_time" | "bool"
    protected_raw: bool = False
    requires_m07_for_confirmed: bool = False
    dependent_keys: tuple[str, ...] = ()
    invalidates_confirmation: bool = True
    invalidates_availability: bool = False


DEFAULT_SLOT_CATALOG: Mapping[str, SlotSpec] = MappingProxyType({
    "customer_ref": SlotSpec(
        "customer_ref",
        SlotFamily.CUSTOMER,
        "str",
        requires_m07_for_confirmed=True,
        dependent_keys=(
            "corporate_account_id",
            "vehicle_ref",
            "vehicle_plate",
            "booking_id",
            "selected_slot_id",
            "quote_amount_kurus",
            "quote_amount_decimal",
            "quote_currency",
            "quote_revision",
            "contact_phone",
            "complaint_text",
        ),
        invalidates_confirmation=True,
        invalidates_availability=True,
    ),
    "customer_name": SlotSpec("customer_name", SlotFamily.CUSTOMER, "str", invalidates_confirmation=False),
    "corporate_account_id": SlotSpec(
        "corporate_account_id",
        SlotFamily.CUSTOMER,
        "str",
        requires_m07_for_confirmed=True,
        dependent_keys=("quote_amount_kurus", "quote_amount_decimal", "quote_revision", "selected_slot_id"),
        invalidates_confirmation=True,
        invalidates_availability=True,
    ),
    "vehicle_brand": SlotSpec(
        "vehicle_brand",
        SlotFamily.VEHICLE,
        "str",
        dependent_keys=("vehicle_model", "vehicle_ref", "quote_amount_kurus", "quote_amount_decimal", "quote_revision"),
        invalidates_confirmation=True,
        invalidates_availability=True,
    ),
    "vehicle_model": SlotSpec(
        "vehicle_model",
        SlotFamily.VEHICLE,
        "str",
        dependent_keys=("vehicle_ref", "quote_amount_kurus", "quote_amount_decimal", "quote_revision", "selected_slot_id"),
        invalidates_confirmation=True,
        invalidates_availability=True,
    ),
    "vehicle_year": SlotSpec(
        "vehicle_year",
        SlotFamily.VEHICLE,
        "int",
        protected_raw=True,
        dependent_keys=("quote_amount_kurus", "quote_amount_decimal", "quote_revision"),
        invalidates_confirmation=True,
    ),
    "vehicle_plate": SlotSpec(
        "vehicle_plate",
        SlotFamily.VEHICLE,
        "str",
        protected_raw=True,
        invalidates_confirmation=True,
    ),
    "engine_code": SlotSpec(
        "engine_code",
        SlotFamily.VEHICLE,
        "str",
        protected_raw=True,
        dependent_keys=("quote_amount_kurus", "quote_amount_decimal", "quote_revision"),
        invalidates_confirmation=True,
    ),
    "vehicle_ref": SlotSpec(
        "vehicle_ref",
        SlotFamily.VEHICLE,
        "str",
        dependent_keys=("quote_amount_kurus", "quote_amount_decimal", "quote_revision", "selected_slot_id"),
        invalidates_confirmation=True,
        invalidates_availability=True,
    ),
    "service_type": SlotSpec(
        "service_type",
        SlotFamily.SERVICE,
        "str",
        dependent_keys=("selected_slot_id", "quote_amount_kurus", "quote_amount_decimal", "quote_revision"),
        invalidates_confirmation=True,
        invalidates_availability=True,
    ),
    "package_type": SlotSpec(
        "package_type",
        SlotFamily.SERVICE,
        "str",
        dependent_keys=("selected_slot_id", "quote_amount_kurus", "quote_amount_decimal", "quote_revision"),
        invalidates_confirmation=True,
        invalidates_availability=True,
    ),
    "booking_id": SlotSpec(
        "booking_id",
        SlotFamily.APPOINTMENT,
        "str",
        invalidates_confirmation=True,
        invalidates_availability=True,
    ),
    "selected_slot_id": SlotSpec(
        "selected_slot_id",
        SlotFamily.APPOINTMENT,
        "str",
        invalidates_confirmation=True,
    ),
    "preferred_date": SlotSpec(
        "preferred_date",
        SlotFamily.APPOINTMENT,
        "iso_date",
        dependent_keys=("selected_slot_id",),
        invalidates_confirmation=True,
        invalidates_availability=True,
    ),
    "preferred_time": SlotSpec(
        "preferred_time",
        SlotFamily.APPOINTMENT,
        "iso_time",
        dependent_keys=("selected_slot_id",),
        invalidates_confirmation=True,
        invalidates_availability=True,
    ),
    "quote_amount_kurus": SlotSpec("quote_amount_kurus", SlotFamily.QUOTE, "int", invalidates_confirmation=True),
    "quote_amount_decimal": SlotSpec("quote_amount_decimal", SlotFamily.QUOTE, "decimal", invalidates_confirmation=True),
    "quote_currency": SlotSpec("quote_currency", SlotFamily.QUOTE, "str", invalidates_confirmation=True),
    "quote_revision": SlotSpec("quote_revision", SlotFamily.QUOTE, "str", invalidates_confirmation=True),
    "contact_phone": SlotSpec("contact_phone", SlotFamily.CONTACT, "str", protected_raw=True, invalidates_confirmation=False),
    "transfer_target": SlotSpec("transfer_target", SlotFamily.TRANSFER, "str", invalidates_confirmation=False),
    "transfer_reason": SlotSpec("transfer_reason", SlotFamily.TRANSFER, "str", invalidates_confirmation=False),
    "complaint_text": SlotSpec("complaint_text", SlotFamily.COMPLAINT, "str", invalidates_confirmation=True),
    "symptom": SlotSpec("symptom", SlotFamily.SERVICE, "str", invalidates_confirmation=False),
    "part": SlotSpec("part", SlotFamily.SERVICE, "str", invalidates_confirmation=False),
})


@dataclass(frozen=True, slots=True)
class SlotValue:
    """Immutable typed slot entry with provenance and revision."""

    key: str
    family: SlotFamily
    value: str | int | Decimal | None
    raw_value: str | None
    status: SlotStatus
    source_type: str
    source_ref: str
    value_revision: int
    evidence_ref: str | None = None
    scope: str = "session"

    def __post_init__(self) -> None:
        if self.key not in DEFAULT_SLOT_CATALOG:
            raise ValueError(f"Unknown slot key: {self.key!r}")
        spec = DEFAULT_SLOT_CATALOG[self.key]
        if self.family != spec.family:
            raise ValueError(f"Slot {self.key!r} requires family {spec.family.value}")
        if not isinstance(self.status, SlotStatus):
            raise ValueError("status must be SlotStatus")
        require_strict_int(self.value_revision, "value_revision", minimum=0)
        if not isinstance(self.source_type, str) or not self.source_type.strip():
            raise ValueError("source_type required")
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise ValueError("source_ref required")
        if spec.requires_m07_for_confirmed and self.status == SlotStatus.CONFIRMED:
            if self.source_type not in _TRUSTED_IDENTITY_SOURCES:
                raise ValueError(
                    f"Slot {self.key!r} cannot become CONFIRMED from untrusted source {self.source_type!r}"
                )
        if self.value is None and self.status not in {SlotStatus.EMPTY, SlotStatus.REJECTED}:
            raise ValueError("Null slot value is only permitted with EMPTY or REJECTED status")


@dataclass(frozen=True, slots=True)
class SlotDeltaItem:
    """Single ordered slot mutation request."""

    key: str
    value: Any
    raw_value: str | None = None
    status: SlotStatus = SlotStatus.CANDIDATE
    source_type: str = "asr_final"
    source_ref: str = "asr"
    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class SlotDelta:
    """CAS batch mutation against a specific expected state_revision."""

    expected_state_revision: int
    changes: tuple[SlotDeltaItem, ...]
    source_ref: str
    reason: str

    def __post_init__(self) -> None:
        require_strict_int(self.expected_state_revision, "expected_state_revision", minimum=0)
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise ValueError("source_ref required")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason required")


@dataclass(frozen=True, slots=True)
class SlotMutationOutcome:
    """Deterministic outcome of applying a SlotDelta via CAS."""

    applied: bool
    no_op: bool
    previous_revision: int
    new_revision: int
    invalidated_keys: tuple[str, ...] = ()
    invalidate_confirmation: bool = False
    invalidate_availability: bool = False
    customer_switched: bool = False
    error_code: str | None = None
    clarification_needed: bool = False
    candidates: tuple[str, ...] = ()


def from_m05_entity_candidate(
    candidate: EntityCandidate,
    *,
    slot_key: str = "vehicle_model",
    value_revision: int = 0,
    source_ref: str = "m05.lexicon",
) -> SlotValue:
    """Convert an M05 EntityCandidate into an untrusted CANDIDATE SlotValue (never CONFIRMED)."""
    if not isinstance(candidate, EntityCandidate):
        raise TypeError("candidate must be M01 EntityCandidate")
    spec = DEFAULT_SLOT_CATALOG.get(slot_key)
    if spec is None:
        raise ValueError(f"Unknown slot key for M05 candidate: {slot_key!r}")
    val = candidate.canonical_value or candidate.raw_value
    return SlotValue(
        key=slot_key,
        family=spec.family,
        value=val,
        raw_value=candidate.raw_value,
        status=SlotStatus.CANDIDATE,
        source_type="m05_lexicon",
        source_ref=source_ref,
        value_revision=value_revision,
        evidence_ref=candidate.entity_id,
    )


def resolve_turkish_relative_date(
    text: str,
    *,
    reference_utc: datetime,
    tz_name: str = "Europe/Istanbul",
) -> tuple[str | None, str | None]:
    """
    Resolve Turkish relative or explicit dates using injected clock/timezone.

    Returns (iso_date, error_code). Rejects ambiguous multi-date or invalid calendar dates.
    """
    if reference_utc.utcoffset() is None:
        raise ValueError("reference_utc must be timezone-aware")
    clean = (text or "").strip().lower()
    if not clean:
        return None, "date.empty"

    iso_matches = _EXPLICIT_ISO_DATE_RE.findall(clean)
    tr_matches = _EXPLICIT_TR_DATE_RE.findall(clean)
    rel_matches = [m.lower() for m in _RELATIVE_DATE_RE.findall(clean)]

    total_hits = len(iso_matches) + len(tr_matches) + len(set(rel_matches))
    if total_hits > 1:
        return None, "date.ambiguous_multiple"

    if iso_matches:
        y, m, d = (int(x) for x in iso_matches[0])
        try:
            return date(y, m, d).isoformat(), None
        except ValueError:
            return None, "date.malformed"

    if tr_matches:
        d, m, y = (int(x) for x in tr_matches[0])
        try:
            return date(y, m, d).isoformat(), None
        except ValueError:
            return None, "date.malformed"

    # Reject malformed numeric date-like strings like "32/13/2026" or "99.99"
    if re.search(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", clean):
        return None, "date.malformed"

    if len(set(rel_matches)) == 1:
        day_token = rel_matches[0]
        local_today = reference_utc.astimezone(ZoneInfo(tz_name)).date()
        if day_token == "bugün":
            return local_today.isoformat(), None
        if day_token == "yarın":
            return (local_today + timedelta(days=1)).isoformat(), None
        target_wd = _WEEKDAYS_TR.index(day_token)
        offset = (target_wd - local_today.weekday()) % 7
        if "gelecek hafta" in clean:
            offset = 7 - local_today.weekday() + target_wd
        return (local_today + timedelta(days=offset)).isoformat(), None

    return None, "date.unrecognized"


def parse_exact_quote_amount(
    amount: str | int | Decimal,
    *,
    currency: str = "TRY",
) -> tuple[Decimal, int]:
    """Parse quote amount using exact Decimal arithmetic (rejects float/NaN/Inf)."""
    if isinstance(amount, float):
        raise ValueError("Float currency amounts are prohibited; pass Decimal, int kurus, or str")
    curr = (currency or "").strip().upper()
    if curr not in _VALID_CURRENCIES:
        raise ValueError(f"Unsupported currency: {currency!r}")
    if isinstance(amount, int) and not isinstance(amount, bool):
        if amount < 0:
            raise ValueError("Quote amount cannot be negative")
        dec = (Decimal(amount) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return dec, amount
    if isinstance(amount, (str, Decimal)):
        try:
            dec = Decimal(str(amount).strip().replace(",", "."))
        except InvalidOperation as exc:
            raise ValueError("Malformed decimal quote amount") from exc
        if not dec.is_finite() or dec < Decimal("0"):
            raise ValueError("Quote amount must be finite and non-negative")
        dec_q = dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        kurus = int((dec_q * Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))
        return dec_q, kurus
    raise TypeError("Quote amount must be int, str, or Decimal")


def _validate_typed_value(spec: SlotSpec, value: Any, raw_value: str | None) -> tuple[Any, str | None, str | None]:
    """Validate value against SlotSpec without unsafe coercion; returns (typed_val, raw_val, error_code)."""
    if value is None:
        return None, raw_value, None
    vtype = spec.value_type
    if vtype == "str":
        if not isinstance(value, str) or not value.strip():
            return None, raw_value, "slot.invalid_type_str"
        clean = value if spec.protected_raw else value.strip()
        return clean, raw_value if raw_value is not None else clean, None
    if vtype == "int":
        if isinstance(value, bool) or type(value) is not int:
            return None, raw_value, "slot.invalid_type_int"
        if spec.key == "vehicle_year" and not (1950 <= value <= 2035):
            return None, raw_value, "slot.invalid_vehicle_year"
        if spec.key == "quote_amount_kurus" and value < 0:
            return None, raw_value, "slot.negative_amount"
        return value, raw_value if raw_value is not None else str(value), None
    if vtype == "decimal":
        if isinstance(value, float):
            if not math.isfinite(value):
                return None, raw_value, "slot.non_finite_decimal"
            return None, raw_value, "slot.float_prohibited"
        try:
            dec = value if isinstance(value, Decimal) else Decimal(str(value).strip())
        except InvalidOperation:
            return None, raw_value, "slot.invalid_decimal"
        if not dec.is_finite() or dec < Decimal("0"):
            return None, raw_value, "slot.invalid_decimal"
        dec_q = dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return dec_q, raw_value if raw_value is not None else str(dec_q), None
    if vtype == "iso_date":
        if not isinstance(value, str):
            return None, raw_value, "slot.invalid_date"
        try:
            parsed = date.fromisoformat(value.strip())
            return parsed.isoformat(), raw_value if raw_value is not None else parsed.isoformat(), None
        except ValueError:
            return None, raw_value, "slot.malformed_iso_date"
    if vtype == "iso_time":
        if not isinstance(value, str):
            return None, raw_value, "slot.invalid_time"
        m = _TIME_RE.fullmatch(value.strip())
        if not m:
            return None, raw_value, "slot.malformed_iso_time"
        hh, mm = int(m.group(1)), int(m.group(2))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None, raw_value, "slot.invalid_time_range"
        formatted = f"{hh:02d}:{mm:02d}"
        return formatted, raw_value if raw_value is not None else formatted, None
    return None, raw_value, "slot.unsupported_type"


class SlotManager:
    """Stateless typed validator and CAS slot-delta evaluator."""

    def __init__(self, *, catalog: Mapping[str, SlotSpec] = DEFAULT_SLOT_CATALOG) -> None:
        self._catalog = catalog

    def validate_and_apply(
        self,
        current_slots: dict[str, SlotValue],
        current_revision: int,
        delta: SlotDelta,
        *,
        max_slots: int = 32,
    ) -> SlotMutationOutcome:
        """
        Apply `delta` atomically against `current_slots` if `expected_state_revision` matches.

        Does not perform I/O or network calls; intended to run inside ContextManager's fast lock.
        """
        if delta.expected_state_revision != current_revision:
            return SlotMutationOutcome(
                applied=False,
                no_op=False,
                previous_revision=current_revision,
                new_revision=current_revision,
                error_code="slot.cas_revision_mismatch",
            )

        staged = dict(current_slots)
        invalidated: list[str] = []
        invalidate_confirmation = False
        invalidate_availability = False
        customer_switched = False
        any_material_change = False

        for item in delta.changes:
            spec = self._catalog.get(item.key)
            if spec is None:
                return SlotMutationOutcome(
                    applied=False,
                    no_op=False,
                    previous_revision=current_revision,
                    new_revision=current_revision,
                    error_code=f"slot.unknown_key:{item.key}",
                )

            if spec.requires_m07_for_confirmed and item.status == SlotStatus.CONFIRMED:
                if item.source_type not in _TRUSTED_IDENTITY_SOURCES:
                    return SlotMutationOutcome(
                        applied=False,
                        no_op=False,
                        previous_revision=current_revision,
                        new_revision=current_revision,
                        error_code="slot.untrusted_identity_confirmation",
                    )

            typed_val, raw_val, type_err = _validate_typed_value(spec, item.value, item.raw_value)
            if type_err is not None:
                return SlotMutationOutcome(
                    applied=False,
                    no_op=False,
                    previous_revision=current_revision,
                    new_revision=current_revision,
                    error_code=type_err,
                    clarification_needed=True,
                )

            if spec.key == "quote_currency" and typed_val is not None:
                if str(typed_val).upper() not in _VALID_CURRENCIES:
                    return SlotMutationOutcome(
                        applied=False,
                        no_op=False,
                        previous_revision=current_revision,
                        new_revision=current_revision,
                        error_code="slot.unsupported_currency",
                    )
                typed_val = str(typed_val).upper()

            prev = staged.get(item.key)
            if (
                prev is not None
                and prev.value == typed_val
                and prev.raw_value == raw_val
                and prev.status == item.status
                and prev.source_type == item.source_type
            ):
                # Exact duplicate / no-op must not churn revision or confirmation.
                continue

            any_material_change = True
            next_val_rev = current_revision + 1
            staged[item.key] = SlotValue(
                key=item.key,
                family=spec.family,
                value=typed_val,
                raw_value=raw_val,
                status=item.status,
                source_type=item.source_type,
                source_ref=item.source_ref,
                value_revision=next_val_rev,
                evidence_ref=item.evidence_ref,
            )

            if item.key in {"customer_ref", "corporate_account_id"} and prev is not None and prev.value != typed_val:
                customer_switched = True

            if spec.invalidates_confirmation:
                invalidate_confirmation = True
            if spec.invalidates_availability:
                invalidate_availability = True

            for dep_key in spec.dependent_keys:
                if dep_key in staged and dep_key not in {c.key for c in delta.changes}:
                    staged.pop(dep_key, None)
                    if dep_key not in invalidated:
                        invalidated.append(dep_key)

        if not any_material_change:
            return SlotMutationOutcome(
                applied=True,
                no_op=True,
                previous_revision=current_revision,
                new_revision=current_revision,
            )

        if len(staged) > max_slots:
            return SlotMutationOutcome(
                applied=False,
                no_op=False,
                previous_revision=current_revision,
                new_revision=current_revision,
                error_code="slot.capacity_exceeded",
            )

        current_slots.clear()
        current_slots.update(staged)
        new_revision = current_revision + 1
        return SlotMutationOutcome(
            applied=True,
            no_op=False,
            previous_revision=current_revision,
            new_revision=new_revision,
            invalidated_keys=tuple(invalidated),
            invalidate_confirmation=invalidate_confirmation,
            invalidate_availability=invalidate_availability,
            customer_switched=customer_switched,
        )
