"""Explicit booking-only transition graph; no audio, LLM, or CRM side effects."""
from .models import BookingStatus

class BookingStateError(ValueError):
    pass

class BookingStateMachine:
    _ALLOWED = {
        BookingStatus.IDLE: {BookingStatus.AWAITING_CONFIRMATION, BookingStatus.UNAVAILABLE,
                             BookingStatus.UNKNOWN, BookingStatus.HANDOFF},
        BookingStatus.AWAITING_CONFIRMATION: {BookingStatus.CONFIRMING, BookingStatus.DECLINED,
                             BookingStatus.UNKNOWN, BookingStatus.UNAVAILABLE, BookingStatus.HANDOFF},
        BookingStatus.CONFIRMING: {BookingStatus.CONFIRMED, BookingStatus.UNAVAILABLE,
                                   BookingStatus.UNKNOWN, BookingStatus.HANDOFF},
        BookingStatus.CONFIRMED: {BookingStatus.HANDOFF},
        BookingStatus.UNAVAILABLE: {BookingStatus.AWAITING_CONFIRMATION, BookingStatus.UNAVAILABLE,
                                     BookingStatus.UNKNOWN, BookingStatus.HANDOFF},
        BookingStatus.UNKNOWN: {BookingStatus.AWAITING_CONFIRMATION, BookingStatus.UNAVAILABLE,
                                 BookingStatus.UNKNOWN, BookingStatus.CONFIRMED, BookingStatus.HANDOFF},
        BookingStatus.DECLINED: {BookingStatus.AWAITING_CONFIRMATION, BookingStatus.UNAVAILABLE,
                                  BookingStatus.UNKNOWN, BookingStatus.HANDOFF},
        BookingStatus.HANDOFF: set(),
    }

    @classmethod
    def transition(cls, source: BookingStatus, target: BookingStatus) -> BookingStatus:
        if not isinstance(source, BookingStatus) or not isinstance(target, BookingStatus):
            raise BookingStateError('BookingStatus required')
        if target == source:
            return source
        if target not in cls._ALLOWED[source]:
            raise BookingStateError(f'Invalid booking transition: {source.value} -> {target.value}')
        return target
