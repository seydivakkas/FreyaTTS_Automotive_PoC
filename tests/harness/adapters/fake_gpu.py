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

from backend.core.runtime.deadlines import Clock
from backend.observability.evidence import EvidenceKind
from backend.runtime_resources.memory_budget import MIB, MemoryProbe


class FakeGPUProbeAdapter:
    """Scripted GPU VRAM probe adapter (no CUDA/torch imports)."""

    source_class: EvidenceKind = EvidenceKind.MOCK_RUNTIME

    def __init__(self, clock: Clock, *, total_mib: int = 8192) -> None:
        self.clock = clock
        self.total_bytes = total_mib * MIB
        self.probe_count = 0

    def valid_probe(self, *, free_mib: int, age_ms: int = 0) -> MemoryProbe:
        self.probe_count += 1
        observed = max(0, self.clock.monotonic_ns() - age_ms * 1_000_000)
        return MemoryProbe(
            total_bytes=self.total_bytes,
            free_bytes=free_mib * MIB,
            observed_at_ns=observed,
            clock_domain=self.clock.clock_domain,
            source="mock.nvml.probe",
        )

    def missing_probe(self) -> MemoryProbe:
        self.probe_count += 1
        return MemoryProbe(
            total_bytes=self.total_bytes,
            free_bytes=None,
            observed_at_ns=self.clock.monotonic_ns(),
            clock_domain=self.clock.clock_domain,
            source="mock.nvml.missing",
        )

    def stale_probe(self, *, free_mib: int, age_ms: int = 5000) -> MemoryProbe:
        return self.valid_probe(free_mib=free_mib, age_ms=age_ms)

    def wrong_domain_probe(self, *, free_mib: int, domain: str = "unsynced.gpu.clock") -> MemoryProbe:
        self.probe_count += 1
        return MemoryProbe(
            total_bytes=self.total_bytes,
            free_bytes=free_mib * MIB,
            observed_at_ns=self.clock.monotonic_ns(),
            clock_domain=domain,
            source="mock.nvml.wrong_domain",
        )
