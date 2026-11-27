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
from backend.runtime_resources.admission import AdmissionController, AdmissionDecision
from backend.runtime_resources.contracts import (
    MIB,
    PRIORITY_LABELS,
    AdmissionOutcome,
    ExecutionLease,
    ExecutionLeaseState,
    HandleOwnership,
    PriorityClass,
    ProviderKind,
    ResidencyState,
    ResourceRequest,
)
from backend.runtime_resources.memory_budget import (
    BudgetCheckResult,
    MemoryBudget,
    MemoryProbe,
    MemoryReservation,
    ProbeStatus,
    mib_to_bytes,
)
from backend.runtime_resources.priority_queue import (
    AgingPolicy,
    BoundedFairPriorityQueue,
    EnqueueResult,
    QueuedWorkItem,
)
from backend.runtime_resources.provider_adapters import (
    AdapterExecutionReport,
    CTranslate2Adapter,
    FakeCudaHandle,
    FakeCTranslate2Worker,
    FakeOllamaWorker,
    FakePyTorchWorker,
    OllamaAdapter,
    ProviderAdapter,
    PyTorchAdapter,
)
from backend.runtime_resources.quarantine import (
    QuarantineEntry,
    QuarantineExhaustedError,
    QuarantineManager,
)
from backend.runtime_resources.residency import (
    InsufficientVramError,
    ModelSpec,
    ResidencyHandle,
    ResidencyManager,
    ResidencyPin,
)
from backend.runtime_resources.scheduler import ExecutionOutcome, UnifiedGpuScheduler

__all__ = [
    "AdapterExecutionReport",
    "AdmissionController",
    "AdmissionDecision",
    "AdmissionOutcome",
    "AgingPolicy",
    "BoundedFairPriorityQueue",
    "BudgetCheckResult",
    "CTranslate2Adapter",
    "EnqueueResult",
    "ExecutionLease",
    "ExecutionLeaseState",
    "ExecutionOutcome",
    "FakeCTranslate2Worker",
    "FakeCudaHandle",
    "FakeOllamaWorker",
    "FakePyTorchWorker",
    "HandleOwnership",
    "InsufficientVramError",
    "MIB",
    "MemoryBudget",
    "MemoryProbe",
    "MemoryReservation",
    "ModelSpec",
    "OllamaAdapter",
    "PRIORITY_LABELS",
    "PriorityClass",
    "ProbeStatus",
    "ProviderAdapter",
    "ProviderKind",
    "PyTorchAdapter",
    "QuarantineEntry",
    "QuarantineExhaustedError",
    "QuarantineManager",
    "QueuedWorkItem",
    "ResidencyHandle",
    "ResidencyManager",
    "ResidencyPin",
    "ResidencyState",
    "ResourceRequest",
    "UnifiedGpuScheduler",
    "mib_to_bytes",
]
