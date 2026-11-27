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

from dataclasses import dataclass

from backend.core.contracts.validation import require_strict_int
from backend.core.runtime import Clock
from backend.runtime_resources.contracts import ExecutionLease, ExecutionLeaseState, ProviderKind


class QuarantineExhaustedError(RuntimeError):
    """Raised when bounded quarantine capacity has been reached."""


@dataclass(frozen=True, slots=True)
class QuarantineEntry:
    lease_id: str
    request_id: str
    model_id: str
    provider: ProviderKind
    reserved_bytes: int
    quarantined_at_ns: int
    reason: str


class QuarantineManager:
    """
    Bounded quarantine tracker for cancelled/timed-out leases whose physical GPU
    or external provider work has not yet finished.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        max_entries: int = 16,
        max_quarantined_bytes: int | None = None,
    ) -> None:
        require_strict_int(max_entries, "max_entries", minimum=1)
        if max_quarantined_bytes is not None:
            require_strict_int(max_quarantined_bytes, "max_quarantined_bytes", minimum=0)
        self._clock = clock
        self.max_entries = max_entries
        self.max_quarantined_bytes = max_quarantined_bytes
        self._entries: dict[str, tuple[QuarantineEntry, ExecutionLease]] = {}
        self.total_quarantined = 0
        self.total_reclaimed = 0

    @property
    def active_count(self) -> int:
        return len(self._entries)

    @property
    def active_bytes(self) -> int:
        return sum(entry.reserved_bytes for entry, _ in self._entries.values())

    def can_quarantine(self, additional_bytes: int = 0) -> bool:
        if len(self._entries) >= self.max_entries:
            return False
        if self.max_quarantined_bytes is not None and (self.active_bytes + additional_bytes) > self.max_quarantined_bytes:
            return False
        return True

    @property
    def is_exhausted(self) -> bool:
        return len(self._entries) >= self.max_entries or (
            self.max_quarantined_bytes is not None and self.active_bytes >= self.max_quarantined_bytes
        )

    def quarantine(self, lease: ExecutionLease, reason: str) -> QuarantineEntry:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("quarantine reason must be non-empty")
        existing = self._entries.get(lease.lease_id)
        if existing is not None:
            return existing[0]
        if not self.can_quarantine(lease.reserved_bytes):
            raise QuarantineExhaustedError(
                f"Quarantine budget exhausted ({self.active_count}/{self.max_entries})"
            )
        lease.state = ExecutionLeaseState.QUARANTINED
        lease.quarantine_reason = reason
        entry = QuarantineEntry(
            lease_id=lease.lease_id,
            request_id=lease.request_id,
            model_id=lease.model_id,
            provider=lease.provider,
            reserved_bytes=lease.reserved_bytes,
            quarantined_at_ns=self._clock.monotonic_ns(),
            reason=reason,
        )
        self._entries[lease.lease_id] = (entry, lease)
        self.total_quarantined += 1
        return entry

    def reclaim(self, lease_id: str, *, failed: bool = False) -> bool:
        pair = self._entries.pop(lease_id, None)
        if pair is None:
            return False
        _, lease = pair
        lease.release_physical(failed=failed)
        self.total_reclaimed += 1
        return True

    def get_entry(self, lease_id: str) -> QuarantineEntry | None:
        pair = self._entries.get(lease_id)
        return pair[0] if pair is not None else None

    def list_entries(self) -> tuple[QuarantineEntry, ...]:
        return tuple(entry for entry, _ in self._entries.values())
