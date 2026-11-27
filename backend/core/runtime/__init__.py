"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from backend.core.runtime.cancellation import CancellationScope, StaleScopeError
from backend.core.runtime.deadlines import Clock, DeadlineBudget, FakeClock, SystemMonotonicClock
from backend.core.runtime.legacy_bridge import attach_runtime_context, ensure_active
from backend.core.runtime.resource_ledger import LeaseState, ResourceLease, ResourceLedger, TaskRegistry
from backend.core.runtime.result_admission import AdmissionStatus, BoundedMediaQueue, QueuedMediaItem
from backend.core.runtime.session_context import CleanupStatus, RuntimeSnapshot, SessionContext, SessionLifecycleState
from backend.core.runtime.session_registry import SessionRegistry
from backend.core.runtime.turn_generation import PauseController, PauseRef, PauseState, TurnGenerationManager

__all__ = [
    "AdmissionStatus",
    "BoundedMediaQueue",
    "CancellationScope",
    "CleanupStatus",
    "Clock",
    "DeadlineBudget",
    "FakeClock",
    "LeaseState",
    "PauseController",
    "PauseRef",
    "PauseState",
    "QueuedMediaItem",
    "ResourceLease",
    "ResourceLedger",
    "RuntimeSnapshot",
    "SessionContext",
    "SessionLifecycleState",
    "SessionRegistry",
    "StaleScopeError",
    "SystemMonotonicClock",
    "TaskRegistry",
    "TurnGenerationManager",
    "attach_runtime_context",
    "ensure_active",
]
