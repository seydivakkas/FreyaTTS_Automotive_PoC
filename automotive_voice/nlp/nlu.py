"""Conservative, deterministic NLU -> unchanged M03 DialogueInput API.

No LLM, no guessed vehicle identity, no implied booking confirmation, and no
implicit timezone or location. Transcripts stay outside event/audit payloads.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
import re
import unicodedata
from automotive_voice.dialogue.models import AppointmentSlot, CaseKind, DialogueInput, Intent
from .lexicon import tr_key

DATE_ISO = re.compile(r'(?<!\d)(?P<y>20\d{2})-(?P<m>\d{2})-(?P<d>\d{2})(?!\d)')
DATE_TR = re.compile(r'(?<!\d)(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>20\d{2})(?!\d)')
TIME = re.compile(r'(?<!\d)(?:saat\s+)?(?P<h>\d{1,2}):(?P<m>\d{2})(?!\d)', re.I)


@dataclass(frozen=True, slots=True)
class ParseContext:
    """All IDs originate from trusted app state, never generated from ASR text."""
    vehicle_aliases: dict[str, str] = field(default_factory=dict)
    location_aliases: dict[str, str] = field(default_factory=dict)
    as_of: datetime | None = None  # aware clock with authoritative customer timezone offset
    timezone_offset_minutes: int | None = None  # required for absolute-date slot without as_of
    awaiting_confirmation: bool = False

    def __post_init__(self):
        if self.as_of is not None and (self.as_of.tzinfo is None or self.as_of.utcoffset() is None):
            raise ValueError('as_of must be timezone-aware')
        if self.timezone_offset_minutes is not None and not -720 <= self.timezone_offset_minutes <= 840:
            raise ValueError('invalid UTC offset')
        if self.as_of is not None and self.timezone_offset_minutes is not None:
            if self.as_of.utcoffset() != timedelta(minutes=self.timezone_offset_minutes):
                raise ValueError('conflicting as_of timezone and explicit timezone offset')
        for mapping in (self.vehicle_aliases, self.location_aliases):
            if any(not isinstance(k, str) or not isinstance(v, str) for k, v in mapping.items()):
                raise ValueError('alias mapping must contain strings')


@dataclass(frozen=True, slots=True)
class ParseResult:
    dialogue_input: DialogueInput
    matched_rules: tuple[str, ...]
    warnings: tuple[str, ...]
    requires_clarification: bool
    # No raw ASR, customer names, phone numbers or verbatim transcript in this result.

    def safe_diagnostics(self) -> dict:
        return {'intent': self.dialogue_input.intent.value,
                'has_vehicle_id': self.dialogue_input.vehicle_id is not None,
                'has_slot': self.dialogue_input.slot is not None,
                'matched_rules': list(self.matched_rules),
                'warning_codes': list(self.warnings),
                'requires_clarification': self.requires_clarification}


class DeterministicNLU:
    _patterns = (
        (Intent.HANDOFF, (r'\btemsilci(?:ye|yi|yle|nin|den)?\b', r'\binsanla\s+görüş', r'\bmüşteri\s+hizmetleri\b')),
        (Intent.RECHECK_BOOKING, (r'\brandevum\s+ne\s+oldu\b', r'\brandevu\s+durumu\b')),
        (Intent.CREATE_CRM_CASE, (r'\bgeri\s+ara', r'\btalep\s+kayd[ıi]\b')),
        (Intent.REQUEST_INSPECTION, (r'\bekspertiz\b', r'\brandevu\s+(?:al|oluştur|ist)')),
        (Intent.PRICE_LOOKUP, (r'\bfiyat(?:ı|i|lar|ları)?\b', r'\bdeğer\b', r'\bteklif\b')),
        (Intent.VEHICLE_LOOKUP, (r'\baraç\s+bilgi', r'\bmodel\s+bilgi', r'\bhangi\s+araç\b')),
    )

    def parse(self, transcript: str, context: ParseContext) -> ParseResult:
        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError('non-empty ASR text expected')
        if not isinstance(context, ParseContext):
            raise TypeError('typed context required')
        if len(transcript) > 2000:
            raise ValueError('transcript too long')
        text = tr_key(unicodedata.normalize('NFC', transcript)).replace('’', "'")
        warnings: list[str] = []
        matches = []
        if re.search(r'\b(?:vazgeçtim|iptal\s+et|istemiyorum)\b', text):
            matches.append(Intent.DECLINE)
        for intent, patterns in self._patterns:
            if any(re.search(p, text) for p in patterns):
                matches.append(intent)
        # A handoff is explicit and should win even when the request mentions pricing.
        if Intent.HANDOFF in matches:
            intent = Intent.HANDOFF
        elif len(set(matches)) > 1:
            intent = Intent.UNKNOWN
            warnings.append('multi_intent_requires_clarification')
        elif matches:
            intent = matches[0]
        elif context.awaiting_confirmation and re.fullmatch(r'\s*(?:evet|onaylıyorum|onaylıyorum\s+evet|tamam\s+onaylıyorum)[.!?\s]*', text):
            intent = Intent.CONFIRM
        elif context.awaiting_confirmation and re.fullmatch(r'\s*(?:hayır|istemiyorum|vazgeçtim)[.!?\s]*', text):
            intent = Intent.DECLINE
        elif re.fullmatch(r'\s*(?:merhaba|selam|iyi\s+günler)[.!?\s]*', text):
            intent = Intent.GREETING
        else:
            intent = Intent.UNKNOWN
            warnings.append('intent_not_resolved')

        vehicle_id = None
        location_id = None
        if intent in (Intent.PRICE_LOOKUP, Intent.VEHICLE_LOOKUP, Intent.REQUEST_INSPECTION, Intent.CREATE_CRM_CASE):
            vehicles = [value for name, value in context.vehicle_aliases.items()
                        if re.search(r'(?<!\w)' + re.escape(tr_key(name)) + r'(?!\w)', text)]
            if len(set(vehicles)) == 1:
                vehicle_id = vehicles[0]
            elif len(set(vehicles)) > 1:
                warnings.append('ambiguous_vehicle')
            else:
                warnings.append('vehicle_not_resolved')
            places = [value for name, value in context.location_aliases.items()
                      if re.search(r'(?<!\w)' + re.escape(tr_key(name)) + r'(?!\w)', text)]
            if len(set(places)) == 1:
                location_id = places[0]
            elif len(set(places)) > 1:
                warnings.append('ambiguous_location')

        slot = None
        if intent == Intent.REQUEST_INSPECTION:
            day = None
            found_dates = list(DATE_ISO.finditer(text)) + list(DATE_TR.finditer(text))
            m_iso = next((m for m in found_dates if m.re is DATE_ISO), None)
            m_tr = next((m for m in found_dates if m.re is DATE_TR), None)
            if len(found_dates) > 1 or (found_dates and re.search(r'\byarın\b', text)):
                warnings.append('ambiguous_date')
            elif m_iso or m_tr:
                m = m_iso or m_tr
                try:
                    day = date(int(m['y']), int(m['m']), int(m['d']))
                except ValueError:
                    warnings.append('invalid_date')
            elif re.search(r'\byarın\b', text):
                if context.as_of is None:
                    warnings.append('relative_date_without_anchor')
                else:
                    day = context.as_of.date() + timedelta(days=1)
            else:
                warnings.append('date_missing')
            clocks = list(TIME.finditer(text))
            clock = clocks[0] if len(clocks) == 1 else None
            if len(clocks) > 1:
                warnings.append('ambiguous_time')
            elif clock is None:
                warnings.append('time_missing')
            else:
                hh, mm = int(clock['h']), int(clock['m'])
                if hh > 23 or mm > 59:
                    warnings.append('invalid_time')
            if location_id is None:
                warnings.append('location_not_resolved')
            offset = (context.as_of.utcoffset() if context.as_of is not None else
                      timedelta(minutes=context.timezone_offset_minutes) if context.timezone_offset_minutes is not None else None)
            if offset is None:
                warnings.append('timezone_not_resolved')
            if day is not None and clock is not None and hh <= 23 and mm <= 59 and offset is not None and location_id:
                tz = timezone(offset)
                stamp = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz).isoformat()
                try:
                    slot = AppointmentSlot(start_at=stamp, location_id=location_id)
                except ValueError:
                    warnings.append('invalid_slot')

        case_kind = None
        if intent == Intent.CREATE_CRM_CASE:
            if re.search(r'\bgeri\s+ara', text):
                case_kind = CaseKind.CALLBACK
            elif re.search(r'\bfiyat(?:ı|i|lar|ları)?\b', text):
                case_kind = CaseKind.PRICE_REQUEST
            else:
                case_kind = CaseKind.EXPERTISE_INFO
        # Avoid passing a vehicle id for intents that do not use it.
        dto = DialogueInput(intent=intent, vehicle_id=vehicle_id, slot=slot, case_kind=case_kind)
        if intent == Intent.CONFIRM and not context.awaiting_confirmation:
            raise AssertionError('confirmation context invariant')
        return ParseResult(dto, tuple(dict.fromkeys(i.value for i in matches)),
                           tuple(dict.fromkeys(warnings)),
                           bool(warnings) or (intent == Intent.REQUEST_INSPECTION and (slot is None or vehicle_id is None)))
