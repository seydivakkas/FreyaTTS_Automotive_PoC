"""Deterministic business rules: no LLM can manufacture price or booking status."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable, Awaitable
from .models import (AccessContext, AppointmentSlot, Availability, BookingStatus,
                     Commitment, DialogueInput, Intent, PolicyDecision)
from .ports import CRMPort, InspectionBookingPort
from .booking_state import BookingStateMachine
from .storage import ReferenceStore

CurrentCheck = Callable[[], Awaitable[bool]]

@dataclass(slots=True)
class _BookingSession:
    booking_status: BookingStatus = BookingStatus.IDLE
    vehicle_id: str | None = None
    pending_slot: AppointmentSlot | None = None
    offer_serial: int = 0
    case_requests: dict[str, str] = field(default_factory=dict)
    idempotency_key: str | None = None
    confirmed_reference: str | None = None
    unknown_count: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def change(self, target: BookingStatus) -> None:
        self.booking_status = BookingStateMachine.transition(self.booking_status, target)

class DialoguePolicy:
    def __init__(self, crm: CRMPort, booking: InspectionBookingPort,
                 store: ReferenceStore, *, now: Callable[[], datetime] | None = None):
        self.crm, self.booking, self.store = crm, booking, store
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._sessions: dict[str, _BookingSession] = {}

    def _session(self, sid: str) -> _BookingSession:
        return self._sessions.setdefault(sid, _BookingSession())

    async def _get_vehicle(self, vehicle_id: str):
        try:
            return await self.crm.get_vehicle(vehicle_id)
        except Exception:
            return None  # fail closed: identity/vehicle is not verified

    def snapshot(self, sid: str) -> dict[str, object]:
        s = self._session(sid)
        return {'booking_status': s.booking_status.value, 'has_pending_slot': bool(s.pending_slot),
                'has_confirmation': bool(s.confirmed_reference), 'unknown_count': s.unknown_count}

    def _respond(self, sid: str, s: _BookingSession, code: str, text: str,
                 *, handoff: bool = False) -> PolicyDecision:
        ref = None if handoff else self.store.put_response(sid, text, code)
        return PolicyDecision(ref, s.booking_status, code, handoff)

    async def handle(self, sid: str, inp: DialogueInput, access: AccessContext,
                     *, is_current: CurrentCheck | None = None) -> PolicyDecision:
        if not isinstance(inp, DialogueInput) or not isinstance(access, AccessContext):
            raise TypeError('typed input/access required')
        s = self._session(sid)
        async with s.lock:
            if is_current is not None and not await is_current():
                return PolicyDecision(None, s.booking_status, 'stale_generation')
            if inp.intent == Intent.HANDOFF:
                s.change(BookingStatus.HANDOFF)
                s.pending_slot = None
                return self._respond(sid, s, 'handoff', '', handoff=True)
            if inp.intent == Intent.GREETING:
                return self._respond(sid, s, 'greeting', 'Merhaba, araç bilgisi ve ekspertiz randevusu konusunda yardımcı olabilirim.')
            if inp.intent == Intent.UNKNOWN:
                s.unknown_count += 1
                if s.unknown_count >= 2:
                    s.change(BookingStatus.HANDOFF)
                    return self._respond(sid, s, 'fallback_handoff', '', handoff=True)
                return self._respond(sid, s, 'clarify', 'İsteğinizi anlayamadım. Araç bilgisi, fiyat veya ekspertiz randevusu mu istiyorsunuz?')
            s.unknown_count = 0
            if inp.intent == Intent.DECLINE:
                if s.booking_status == BookingStatus.AWAITING_CONFIRMATION:
                    s.change(BookingStatus.DECLINED)
                    s.pending_slot = None
                    s.idempotency_key = None
                    return self._respond(sid, s, 'declined', 'Randevu talebini oluşturmadım.')
                return self._respond(sid, s, 'no_offer', 'Onay bekleyen bir randevunuz bulunmuyor.')
            # Never retrieve private CRM information or create appointments before access authorization.
            if not access.authenticated:
                return self._respond(sid, s, 'identity_required', 'İşleme devam etmek için kimlik doğrulaması gerekiyor.')
            if not access.crm_processing_allowed:
                return self._respond(sid, s, 'data_permission_required', 'Araç bilgilerinizle işlem yapabilmem için uygun veri işleme yetkisi gerekiyor. Dilerseniz temsilciye aktarabilirim.')
            if inp.intent == Intent.RECHECK_BOOKING:
                if not s.idempotency_key:
                    return self._respond(sid, s, 'nothing_to_recheck', 'Sorgulanabilecek bir randevu işlemi yok.')
                try:
                    outcome = await self.booking.lookup(s.idempotency_key)
                except Exception:
                    outcome = None
                if outcome is not None and outcome.status == Commitment.CONFIRMED and outcome.reference_id:
                    s.change(BookingStatus.CONFIRMED)
                    s.confirmed_reference = outcome.reference_id
                    return self._respond(sid, s, 'booking_reconciled', f'Randevu doğrulandı. Referans: {outcome.reference_id}.')
                s.change(BookingStatus.UNKNOWN)
                return self._respond(sid, s, 'recheck_unknown', 'Randevunun sonucu doğrulanamadı. Yeni bir kayıt denemesi yapmadan temsilciye başvurabilirsiniz.')
            if inp.intent == Intent.CREATE_CRM_CASE:
                if not inp.vehicle_id or inp.case_kind is None:
                    return self._respond(sid, s, 'crm_case_details_missing', 'Talep kaydı için araç ve konu bilgisi gerekiyor.')
                vehicle = await self._get_vehicle(inp.vehicle_id)
                if vehicle is None or not vehicle.verified:
                    return self._respond(sid, s, 'vehicle_unverified', 'Araç doğrulanmadığı için CRM talebi açamıyorum.')
                if is_current is not None and not await is_current():
                    return PolicyDecision(None, s.booking_status, 'stale_generation')
                key = sha256(f'crm-case|{sid}|{inp.vehicle_id}|{inp.case_kind.value}'.encode()).hexdigest()
                try:
                    receipt = await self.crm.create_case(inp.vehicle_id, inp.case_kind, key)
                except Exception:
                    return self._respond(sid, s, 'crm_case_unknown', 'CRM talebinizin kaydedildiği doğrulanamadı.')
                if receipt.accepted and receipt.reference_id:
                    s.case_requests[key] = receipt.reference_id
                    return self._respond(sid, s, 'crm_case_created', f'Talebiniz CRM sisteminde kaydedildi. Takip referansı: {receipt.reference_id}.')
                return self._respond(sid, s, 'crm_case_unavailable', 'CRM talebiniz kaydedilemedi.')
            if inp.intent == Intent.VEHICLE_LOOKUP:
                if inp.vehicle_id is None:
                    return self._respond(sid, s, 'need_vehicle', 'Hangi araç için işlem yapmak istiyorsunuz?')
                v = await self._get_vehicle(inp.vehicle_id)
                if v is None or not v.verified:
                    return self._respond(sid, s, 'vehicle_unverified', 'Araç bilgisi doğrulanamadı. Temsilciye aktarabilirim.')
                return self._respond(sid, s, 'vehicle_verified', f'Doğrulanmış araç kaydı: {v.year} {v.brand} {v.model}.')
            if inp.intent == Intent.PRICE_LOOKUP:
                if not inp.vehicle_id:
                    return self._respond(sid, s, 'need_vehicle', 'Fiyat sorgulamak için araç bilgisi gerekiyor.')
                v = await self._get_vehicle(inp.vehicle_id)
                if v is None or not v.verified:
                    return self._respond(sid, s, 'vehicle_unverified', 'Bu aracın doğrulanmış kaydı yok; fiyat bildiremiyorum.')
                try:
                    quote = await self.crm.get_price_quote(inp.vehicle_id)
                except Exception:
                    quote = None
                current = self.now()
                if (quote is None or quote.vehicle_id != inp.vehicle_id or not quote.verified
                        or quote.valid_until <= current or not quote.source_ref):
                    return self._respond(sid, s, 'price_unavailable', 'Bu araç için güncel ve doğrulanmış fiyat bilgisi bulunmuyor.')
                return self._respond(sid, s, 'price_verified',
                    f'Sistemde doğrulanmış tahmini araç değeri {quote.amount_try:,} Türk lirasıdır.'.replace(',', '.') + ' Bu tutar kesin satış teklifi değildir.')
            if inp.intent == Intent.REQUEST_INSPECTION:
                if not inp.vehicle_id or inp.slot is None:
                    return self._respond(sid, s, 'need_slot', 'Ekspertiz için araç, tarih, saat ve lokasyon bilgisi gerekiyor.')
                v = await self._get_vehicle(inp.vehicle_id)
                if v is None or not v.verified:
                    return self._respond(sid, s, 'vehicle_unverified', 'Araç doğrulanmadan ekspertiz randevusu açamam.')
                if inp.slot.start_at and datetime.fromisoformat(inp.slot.start_at) <= self.now():
                    return self._respond(sid, s, 'slot_past', 'Geçmiş tarihli randevu oluşturamam. Yeni bir zaman belirtin.')
                if s.booking_status == BookingStatus.CONFIRMED:
                    if s.vehicle_id == inp.vehicle_id and s.pending_slot == inp.slot:
                        return self._respond(sid, s, 'already_confirmed', f'Bu randevu daha önce doğrulandı. Referans: {s.confirmed_reference}.')
                    return self._respond(sid, s, 'booking_exists', 'Zaten kesinleşmiş bir randevunuz var. Değişiklik için temsilciye aktarabilirim.')
                if s.booking_status == BookingStatus.UNKNOWN and s.idempotency_key:
                    return self._respond(sid, s, 'reconcile_first', 'Önceki randevu denemesinin sonucu belirsiz. Önce kayıt durumunu doğrulamamız gerekiyor.')
                try:
                    state = await self.booking.check_availability(inp.vehicle_id, inp.slot)
                except Exception:
                    state = Availability.UNKNOWN
                if is_current is not None and not await is_current():
                    return PolicyDecision(None, s.booking_status, 'stale_generation')
                s.vehicle_id, s.pending_slot, s.confirmed_reference = inp.vehicle_id, inp.slot, None
                s.idempotency_key = None  # replace an uncommitted offer, not an uncertain commit
                if state == Availability.UNAVAILABLE:
                    s.change(BookingStatus.UNAVAILABLE)
                    return self._respond(sid, s, 'slot_unavailable', 'İstenen tarih ve saatte ekspertiz müsait değil. Başka zaman seçebilirsiniz.')
                if state == Availability.UNKNOWN:
                    s.change(BookingStatus.UNKNOWN)
                    return self._respond(sid, s, 'slot_unknown', 'Randevu uygunluğu henüz doğrulanamadı. Randevu oluşturulmadı.')
                if state != Availability.AVAILABLE:
                    raise ValueError('unexpected availability state')
                s.change(BookingStatus.AWAITING_CONFIRMATION)
                s.offer_serial += 1
                s.idempotency_key = sha256(f'{sid}|{s.offer_serial}|{inp.vehicle_id}|{inp.slot.start_at}|{inp.slot.location_id}'.encode()).hexdigest()
                return self._respond(sid, s, 'offer_confirmation',
                    f'{inp.slot.start_at} tarihinde, {inp.slot.location_id} lokasyonunda ekspertiz için müsaitlik var. Randevu talebini onaylıyor musunuz? Henüz oluşturulmadı.')
            if inp.intent == Intent.CONFIRM:
                if s.booking_status == BookingStatus.CONFIRMED and s.confirmed_reference:
                    return self._respond(sid, s, 'already_confirmed', f'Randevunuz zaten onaylı. Referans: {s.confirmed_reference}.')
                if s.booking_status != BookingStatus.AWAITING_CONFIRMATION or not s.idempotency_key or not s.pending_slot or not s.vehicle_id:
                    return self._respond(sid, s, 'no_offer', 'Onay bekleyen doğrulanmış bir randevu talebi bulunmuyor.')
                if datetime.fromisoformat(s.pending_slot.start_at) <= self.now():
                    s.change(BookingStatus.UNAVAILABLE)
                    s.idempotency_key = None
                    return self._respond(sid, s, 'slot_expired', 'Seçilen saat artık geçmiş durumda. Yeni bir randevu saati belirtin.')
                if is_current is not None and not await is_current():
                    return PolicyDecision(None, s.booking_status, 'stale_generation')
                s.change(BookingStatus.CONFIRMING)
                try:
                    result = await self.booking.commit(s.vehicle_id, s.pending_slot, s.idempotency_key)
                except Exception:
                    s.change(BookingStatus.UNKNOWN)
                    return self._respond(sid, s, 'booking_service_error', 'Randevu kaydı doğrulanamadı. Oluşturulduğunu söyleyemem.')
                if result.status == Commitment.CONFIRMED and result.reference_id:
                    s.change(BookingStatus.CONFIRMED)
                    s.confirmed_reference = result.reference_id
                    return self._respond(sid, s, 'booking_confirmed', f'Ekspertiz randevunuz oluşturuldu. Onay referansı: {result.reference_id}.')
                s.change(BookingStatus.UNAVAILABLE if result.status == Commitment.UNAVAILABLE else BookingStatus.UNKNOWN)
                code = 'booking_unavailable' if result.status == Commitment.UNAVAILABLE else 'booking_unknown'
                return self._respond(sid, s, code, 'Randevu kaydı onaylanmadı. Kesinleşmiş randevunuz bulunmuyor.')
            return self._respond(sid, s, 'unsupported', 'Bu işlem şu anda desteklenmiyor. Temsilciye aktarabilirim.')
