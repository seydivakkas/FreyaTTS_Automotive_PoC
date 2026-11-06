"""The LLM is never authoritative about confirmed bookings."""
from dataclasses import dataclass

@dataclass(frozen=True)
class BookingOutcome:
    status: str
    reference_id: str | None


def can_announce_booking(outcome: BookingOutcome, user_confirmed: bool) -> bool:
    return bool(user_confirmed and outcome.status == "confirmed" and outcome.reference_id)
