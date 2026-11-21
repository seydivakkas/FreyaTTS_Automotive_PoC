"""Business-authoritative replaceable ports, with deterministic no-network fakes."""
from __future__ import annotations
from typing import Protocol
from uuid import uuid5, NAMESPACE_URL
from .models import VehicleRecord, PriceQuote, AppointmentSlot, Availability, BookingReceipt, Commitment, CaseKind, CaseReceipt

class CRMPort(Protocol):
    async def get_vehicle(self, vehicle_id: str) -> VehicleRecord | None: ...
    async def get_price_quote(self, vehicle_id: str) -> PriceQuote | None: ...
    async def create_case(self, vehicle_id: str, kind: CaseKind, idempotency_key: str) -> CaseReceipt: ...

class InspectionBookingPort(Protocol):
    async def check_availability(self, vehicle_id: str, slot: AppointmentSlot) -> Availability: ...
    async def commit(self, vehicle_id: str, slot: AppointmentSlot, idempotency_key: str) -> BookingReceipt: ...
    async def lookup(self, idempotency_key: str) -> BookingReceipt: ...

class FakeCRM:
    def __init__(self, vehicles: dict[str, VehicleRecord] | None = None, quotes: dict[str, PriceQuote] | None = None):
        self.vehicles = vehicles or {}
        self.quotes = quotes or {}
        self.vehicle_reads = 0
        self.price_reads = 0
        self.cases: dict[str, CaseReceipt] = {}
        self.case_creations = 0

    async def get_vehicle(self, vehicle_id: str) -> VehicleRecord | None:
        self.vehicle_reads += 1
        return self.vehicles.get(vehicle_id)

    async def get_price_quote(self, vehicle_id: str) -> PriceQuote | None:
        self.price_reads += 1
        return self.quotes.get(vehicle_id)

    async def create_case(self, vehicle_id: str, kind: CaseKind, idempotency_key: str) -> CaseReceipt:
        if idempotency_key in self.cases:
            return self.cases[idempotency_key]
        if vehicle_id not in self.vehicles or not self.vehicles[vehicle_id].verified:
            return CaseReceipt(False, None)
        ref = "CASE-" + uuid5(NAMESPACE_URL, idempotency_key).hex[:12].upper()
        receipt = CaseReceipt(True, ref)
        self.cases[idempotency_key] = receipt
        self.case_creations += 1
        return receipt

class FakeBookingService:
    def __init__(self, availability: dict[tuple[str, str, str], Availability] | None = None):
        self.availability = availability or {}
        self.receipts: dict[str, BookingReceipt] = {}
        self.request_fingerprints: dict[str, tuple[str, str, str]] = {}
        self.commit_calls = 0
        self.creations = 0

    @staticmethod
    def key(vehicle_id: str, slot: AppointmentSlot) -> tuple[str, str, str]:
        return vehicle_id, slot.start_at, slot.location_id

    async def check_availability(self, vehicle_id: str, slot: AppointmentSlot) -> Availability:
        return self.availability.get(self.key(vehicle_id, slot), Availability.UNKNOWN)

    async def commit(self, vehicle_id: str, slot: AppointmentSlot, idempotency_key: str) -> BookingReceipt:
        self.commit_calls += 1
        fingerprint = self.key(vehicle_id, slot)
        if idempotency_key in self.request_fingerprints and self.request_fingerprints[idempotency_key] != fingerprint:
            raise ValueError('idempotency key reused for another booking')
        if idempotency_key in self.receipts:
            return self.receipts[idempotency_key]
        status = await self.check_availability(vehicle_id, slot)
        if status == Availability.AVAILABLE:
            ref = 'EX-' + uuid5(NAMESPACE_URL, idempotency_key).hex[:12].upper()
            outcome = BookingReceipt(Commitment.CONFIRMED, ref)
            self.creations += 1
        elif status == Availability.UNAVAILABLE:
            outcome = BookingReceipt(Commitment.UNAVAILABLE)
        else:
            outcome = BookingReceipt(Commitment.UNKNOWN)
        # This is a deterministic test double; a real service must guarantee
        # the idempotency key transactionally on its own server side.
        self.receipts[idempotency_key] = outcome
        self.request_fingerprints[idempotency_key] = fingerprint
        return outcome

    async def lookup(self, idempotency_key: str) -> BookingReceipt:
        return self.receipts.get(idempotency_key, BookingReceipt(Commitment.UNKNOWN))
