"""M03 value objects. Avoid raw transcripts or PII in event/audit envelopes."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class Intent(str, Enum):
    GREETING = 'greeting'
    VEHICLE_LOOKUP = 'vehicle_lookup'
    CREATE_CRM_CASE = 'create_crm_case'
    PRICE_LOOKUP = 'price_lookup'
    REQUEST_INSPECTION = 'request_inspection'
    CONFIRM = 'confirm'
    RECHECK_BOOKING = 'recheck_booking'
    DECLINE = 'decline'
    HANDOFF = 'handoff'
    UNKNOWN = 'unknown'

class CaseKind(str, Enum):
    EXPERTISE_INFO = "expertise_info"
    PRICE_REQUEST = "price_request"
    CALLBACK = "callback"

class Availability(str, Enum):
    AVAILABLE = 'available'
    UNAVAILABLE = 'unavailable'
    UNKNOWN = 'unknown'

class BookingStatus(str, Enum):
    IDLE = 'idle'
    AWAITING_CONFIRMATION = 'awaiting_confirmation'
    CONFIRMING = 'confirming'
    CONFIRMED = 'confirmed'
    UNAVAILABLE = 'unavailable'
    UNKNOWN = 'unknown'
    DECLINED = 'declined'
    HANDOFF = 'handoff'

class Commitment(str, Enum):
    CONFIRMED = 'confirmed'
    UNAVAILABLE = 'unavailable'
    UNKNOWN = 'unknown'

@dataclass(frozen=True, slots=True)
class AccessContext:
    authenticated: bool = False
    crm_processing_allowed: bool = False
    marketing_opt_in: bool = False
    # Explicit consent is recorded separately; these flags are demo inputs,
    # not a claim of legal sufficiency under applicable privacy law.

@dataclass(frozen=True, slots=True)
class AppointmentSlot:
    start_at: str
    location_id: str
    def __post_init__(self):
        if not self.location_id or len(self.location_id) > 48 or not all(c.isascii() and (c.isalnum() or c in '_-') for c in self.location_id):
            raise ValueError('invalid location_id')
        try:
            dt = datetime.fromisoformat(self.start_at)
        except (TypeError, ValueError) as e:
            raise ValueError('invalid slot ISO 8601') from e
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError('appointment slot must include timezone offset')

@dataclass(frozen=True, slots=True)
class DialogueInput:
    intent: Intent
    vehicle_id: str | None = None
    slot: AppointmentSlot | None = None
    case_kind: CaseKind | None = None
    def __post_init__(self):
        if not isinstance(self.intent, Intent):
            raise ValueError('invalid intent')
        if self.vehicle_id is not None and (len(self.vehicle_id) > 48 or not self.vehicle_id or not all(c.isascii() and (c.isalnum() or c in '_-') for c in self.vehicle_id)):
            raise ValueError('invalid vehicle_id')
        if self.slot and self.intent != Intent.REQUEST_INSPECTION:
            raise ValueError('slot only valid for inspection request')
        if self.case_kind is not None and (self.intent != Intent.CREATE_CRM_CASE or not isinstance(self.case_kind, CaseKind)):
            raise ValueError('case_kind only valid for CRM case')

@dataclass(frozen=True, slots=True)
class VehicleRecord:
    vehicle_id: str
    brand: str
    model: str
    year: int
    verified: bool = True

@dataclass(frozen=True, slots=True)
class PriceQuote:
    vehicle_id: str
    amount_try: int
    source_ref: str
    valid_until: datetime
    verified: bool = True
    def __post_init__(self):
        if type(self.amount_try) is not int or self.amount_try < 0:
            raise ValueError('positive quote amount expected')
        if not self.source_ref or self.valid_until.tzinfo is None:
            raise ValueError('verifiable quote reference and aware expiry needed')

@dataclass(frozen=True, slots=True)
class BookingReceipt:
    status: Commitment
    reference_id: str | None = None
    def __post_init__(self):
        if self.status == Commitment.CONFIRMED and not self.reference_id:
            raise ValueError('confirmed booking requires reference_id')
        if self.status != Commitment.CONFIRMED and self.reference_id is not None:
            raise ValueError('unconfirmed booking must not expose confirmation ID')

@dataclass(frozen=True, slots=True)
class PolicyDecision:
    response_ref: str | None
    booking_status: BookingStatus
    action: str
    handoff_requested: bool = False
    # No raw text/PII here; only code and opaque reference.

@dataclass(frozen=True, slots=True)
class CaseReceipt:
    accepted: bool
    reference_id: str | None
    def __post_init__(self):
        if bool(self.reference_id) != self.accepted:
            raise ValueError('case reference required only when accepted')
