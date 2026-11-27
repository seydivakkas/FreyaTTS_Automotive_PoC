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

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from backend.core.contracts.dialogue import ProviderMode, ToolReceipt, ToolReceiptStatus
from backend.observability.evidence import EvidenceKind
from tests.harness.isolation import IsolatedSQLiteHandle


@dataclass(frozen=True, slots=True)
class ProviderInvocationRecord:
    operation_id: str
    tool_id: str
    scope: str
    outcome: str
    provider_mode: ProviderMode


class IsolatedCRMSchemaFixture:
    """Explicit synthetic SQLite CRM fixture schema (distinct from production backend/db.py)."""

    schema_provenance: str = "SYNTHETIC_ISOLATED_CRM_FIXTURE"

    def __init__(self, db_path: Path) -> None:
        self.handle = IsolatedSQLiteHandle(db_path)
        self.init_schema()

    def init_schema(self) -> None:
        conn = self.handle.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS slot_inventory (
                    slot_id TEXT PRIMARY KEY,
                    capacity INTEGER NOT NULL CHECK (capacity >= 0),
                    claimed_count INTEGER NOT NULL DEFAULT 0 CHECK (claimed_count >= 0)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fixture_bookings (
                    booking_id TEXT PRIMARY KEY,
                    slot_id TEXT NOT NULL REFERENCES slot_inventory(slot_id),
                    customer_ref TEXT NOT NULL,
                    vehicle_ref TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_synthetic INTEGER NOT NULL DEFAULT 1 CHECK (is_synthetic = 1)
                )
                """
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            self.handle.close_all()

    def seed_slot(self, slot_id: str, capacity: int = 1) -> None:
        conn = self.handle.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR REPLACE INTO slot_inventory (slot_id, capacity, claimed_count) VALUES (?, ?, 0)",
                (slot_id, capacity),
            )
            conn.execute("COMMIT")
        finally:
            self.handle.close_all()

    def try_claim_slot(self, *, booking_id: str, slot_id: str, customer_ref: str, vehicle_ref: str) -> bool:
        """Atomic BEGIN IMMEDIATE claim across independent connections."""
        conn = sqlite3.connect(str(self.handle.db_path), timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT capacity, claimed_count FROM slot_inventory WHERE slot_id = ?",
                (slot_id,),
            ).fetchone()
            if row is None or row["claimed_count"] >= row["capacity"]:
                conn.execute("ROLLBACK")
                return False
            conn.execute(
                "UPDATE slot_inventory SET claimed_count = claimed_count + 1 WHERE slot_id = ?",
                (slot_id,),
            )
            conn.execute(
                """
                INSERT INTO fixture_bookings (booking_id, slot_id, customer_ref, vehicle_ref, status, is_synthetic)
                VALUES (?, ?, ?, ?, 'SYNTHETIC_BOOKED', 1)
                """,
                (booking_id, slot_id, customer_ref, vehicle_ref),
            )
            conn.execute("COMMIT")
            return True
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def list_bookings(self) -> list[dict[str, object]]:
        conn = sqlite3.connect(str(self.handle.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT booking_id, slot_id, customer_ref, vehicle_ref, status, is_synthetic FROM fixture_bookings").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


class FakeBusinessProvider:
    """Mock CRM/business provider emitting visibly synthetic receipts and safe invocation records."""

    source_class: EvidenceKind = EvidenceKind.MOCK_RUNTIME

    def __init__(self, crm: IsolatedCRMSchemaFixture | None = None) -> None:
        self.crm = crm
        self.invocation_count = 0
        self.invocations: list[ProviderInvocationRecord] = []

    def execute_booking(
        self,
        *,
        operation_id: str,
        idempotency_key: str,
        slot_id: str,
        customer_ref: str,
        vehicle_ref: str,
        simulate_unknown: bool = False,
    ) -> ToolReceipt:
        self.invocation_count += 1
        if simulate_unknown:
            self.invocations.append(
                ProviderInvocationRecord(
                    operation_id=operation_id,
                    tool_id="booking.create",
                    scope="MOCK_SYNTHETIC",
                    outcome="UNKNOWN_RECONCILE_REQUIRED",
                    provider_mode=ProviderMode.MOCK,
                )
            )
            return ToolReceipt(
                operation_id=operation_id,
                tool_id="booking.create",
                status=ToolReceiptStatus.UNKNOWN,
                provider_mode=ProviderMode.MOCK,
                idempotency_key=idempotency_key,
                evidence_ref=f"mock-unknown:{operation_id}",
                verified_result=False,
            )
        ok = True
        if self.crm is not None:
            ok = self.crm.try_claim_slot(
                booking_id=operation_id,
                slot_id=slot_id,
                customer_ref=customer_ref,
                vehicle_ref=vehicle_ref,
            )
        status = ToolReceiptStatus.COMMITTED if ok else ToolReceiptStatus.FAILED
        self.invocations.append(
            ProviderInvocationRecord(
                operation_id=operation_id,
                tool_id="booking.create",
                scope="MOCK_SYNTHETIC",
                outcome=status.value,
                provider_mode=ProviderMode.MOCK,
            )
        )
        return ToolReceipt(
            operation_id=operation_id,
            tool_id="booking.create",
            status=status,
            provider_mode=ProviderMode.MOCK,
            idempotency_key=idempotency_key,
            evidence_ref=f"mock-crm:{operation_id}",
            verified_result=False,
        )
