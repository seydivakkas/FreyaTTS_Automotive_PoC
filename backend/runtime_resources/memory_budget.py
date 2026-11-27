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
from enum import StrEnum

from backend.core.contracts.validation import require_strict_int
from backend.core.runtime import Clock
from backend.runtime_resources.contracts import MIB


def mib_to_bytes(mib: int) -> int:
    """Convert whole MiB to exact bytes (1 MiB = 1,048,576 bytes)."""
    require_strict_int(mib, "mib", minimum=0)
    return mib * MIB


class ProbeStatus(StrEnum):
    VALID = "VALID"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    DOMAIN_MISMATCH = "DOMAIN_MISMATCH"
    UNRELIABLE = "UNRELIABLE"


@dataclass(frozen=True, slots=True)
class MemoryProbe:
    """Point-in-time GPU memory probe snapshot in exact bytes."""

    total_bytes: int | None
    free_bytes: int | None
    observed_at_ns: int
    clock_domain: str
    source: str = "probe"
    reliable: bool = True

    def __post_init__(self) -> None:
        if self.total_bytes is not None:
            require_strict_int(self.total_bytes, "total_bytes", minimum=0)
        if self.free_bytes is not None:
            require_strict_int(self.free_bytes, "free_bytes", minimum=0)
        if (
            self.total_bytes is not None
            and self.free_bytes is not None
            and self.free_bytes > self.total_bytes
        ):
            raise ValueError("free_bytes cannot exceed total_bytes")
        require_strict_int(self.observed_at_ns, "observed_at_ns", minimum=0)
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("clock_domain must be non-empty")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be non-empty")


@dataclass(slots=True)
class MemoryReservation:
    reservation_id: str
    reserved_bytes: int
    reserved_at_ns: int
    kind: str = "execution"
    allocated_at_ns: int | None = None
    allocated_at_probe_seq: int | None = None
    observed: bool = False


@dataclass(frozen=True, slots=True)
class BudgetCheckResult:
    admitted: bool
    probe_status: ProbeStatus
    reason: str
    required_bytes: int
    usable_bytes: int
    free_bytes: int | None
    headroom_bytes: int
    unobserved_reserved_bytes: int


class MemoryBudget:
    """
    Byte-accurate GPU memory budget.

    Formula:
        usable = max(0, free - headroom - unobserved_reserved)

    Conservative policy:
        Missing, unknown, unreliable, clock-mismatched, or stale probes reject admissions.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        headroom_bytes: int = 256 * MIB,
        max_probe_age_ms: int = 2_000,
    ) -> None:
        require_strict_int(headroom_bytes, "headroom_bytes", minimum=0)
        require_strict_int(max_probe_age_ms, "max_probe_age_ms", minimum=1)
        self._clock = clock
        self._headroom_bytes = headroom_bytes
        self._max_probe_age_ns = max_probe_age_ms * 1_000_000
        self._probe: MemoryProbe | None = None
        self._probe_seq: int = 0
        self._reservations: dict[str, MemoryReservation] = {}

    @property
    def headroom_bytes(self) -> int:
        return self._headroom_bytes

    @property
    def latest_probe(self) -> MemoryProbe | None:
        return self._probe

    @property
    def unobserved_reserved_bytes(self) -> int:
        return sum(r.reserved_bytes for r in self._reservations.values() if not r.observed)

    @property
    def total_reserved_bytes(self) -> int:
        return sum(r.reserved_bytes for r in self._reservations.values())

    def probe_status(self) -> ProbeStatus:
        probe = self._probe
        if probe is None:
            return ProbeStatus.UNKNOWN
        if probe.clock_domain != self._clock.clock_domain:
            return ProbeStatus.DOMAIN_MISMATCH
        if not probe.reliable or probe.free_bytes is None or probe.total_bytes is None:
            return ProbeStatus.UNRELIABLE
        now_ns = self._clock.monotonic_ns()
        age_ns = now_ns - probe.observed_at_ns
        if age_ns < 0 or age_ns > self._max_probe_age_ns:
            return ProbeStatus.STALE
        return ProbeStatus.VALID

    def update_probe(self, probe: MemoryProbe) -> None:
        self._probe = probe
        self._probe_seq += 1
        if (
            probe.reliable
            and probe.free_bytes is not None
            and probe.total_bytes is not None
            and probe.clock_domain == self._clock.clock_domain
        ):
            for res in self._reservations.values():
                if (
                    res.allocated_at_ns is not None
                    and res.allocated_at_probe_seq is not None
                    and self._probe_seq > res.allocated_at_probe_seq
                    and probe.observed_at_ns >= res.allocated_at_ns
                ):
                    res.observed = True

    def usable_bytes(self) -> int:
        if self.probe_status() != ProbeStatus.VALID:
            return 0
        assert self._probe is not None and self._probe.free_bytes is not None
        return max(0, self._probe.free_bytes - self._headroom_bytes - self.unobserved_reserved_bytes)

    def check_admission(self, required_bytes: int) -> BudgetCheckResult:
        require_strict_int(required_bytes, "required_bytes", minimum=0)
        status = self.probe_status()
        unobserved = self.unobserved_reserved_bytes
        free = self._probe.free_bytes if self._probe is not None else None
        if status != ProbeStatus.VALID:
            return BudgetCheckResult(
                admitted=False,
                probe_status=status,
                reason=f"probe_{status.value.lower()}",
                required_bytes=required_bytes,
                usable_bytes=0,
                free_bytes=free,
                headroom_bytes=self._headroom_bytes,
                unobserved_reserved_bytes=unobserved,
            )
        usable = self.usable_bytes()
        admitted = required_bytes <= usable
        return BudgetCheckResult(
            admitted=admitted,
            probe_status=status,
            reason="ok" if admitted else "insufficient_usable_vram",
            required_bytes=required_bytes,
            usable_bytes=usable,
            free_bytes=free,
            headroom_bytes=self._headroom_bytes,
            unobserved_reserved_bytes=unobserved,
        )

    def try_reserve(
        self,
        reservation_id: str,
        required_bytes: int,
        *,
        kind: str = "execution",
    ) -> tuple[BudgetCheckResult, MemoryReservation | None]:
        if reservation_id in self._reservations:
            raise ValueError(f"Reservation already active: {reservation_id}")
        check = self.check_admission(required_bytes)
        if not check.admitted:
            return check, None
        res = MemoryReservation(
            reservation_id=reservation_id,
            reserved_bytes=required_bytes,
            reserved_at_ns=self._clock.monotonic_ns(),
            kind=kind,
            observed=False,
        )
        self._reservations[reservation_id] = res
        return check, res

    def mark_allocated(self, reservation_id: str, at_ns: int | None = None) -> None:
        res = self._reservations.get(reservation_id)
        if res is None:
            raise KeyError(f"Unknown reservation: {reservation_id}")
        alloc_ns = self._clock.monotonic_ns() if at_ns is None else at_ns
        require_strict_int(alloc_ns, "at_ns", minimum=0)
        res.allocated_at_ns = alloc_ns
        res.allocated_at_probe_seq = self._probe_seq

    def release(self, reservation_id: str) -> bool:
        return self._reservations.pop(reservation_id, None) is not None
