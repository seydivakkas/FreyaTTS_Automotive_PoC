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

import threading
from dataclasses import dataclass

from backend.core.contracts.common import GenerationRef
from backend.core.runtime.session_context import CleanupStatus, SessionContext
from backend.neural_synthesis.delivery import GenerationDeliveryFence
from backend.neural_synthesis.plan_validator import ScopedPlanClaimRegistry
from backend.runtime_resources.scheduler import UnifiedGpuScheduler


@dataclass(frozen=True, slots=True)
class SessionCleanupReport:
    session_id: str
    closed: bool
    cleanup_status: CleanupStatus
    purged_claims: int
    quarantined_leases: int


class SynthesisLifecycleManager:
    """
    Coordinates F5-A session/generation lifecycle, reentry prevention, and safe cleanup.

    Buffer and claim cleanup proceeds only without destroying active M06 physical leases
    or Quarantine ownership.
    """

    def __init__(
        self,
        *,
        claims: ScopedPlanClaimRegistry,
        delivery_fence: GenerationDeliveryFence,
        scheduler: UnifiedGpuScheduler | None = None,
    ) -> None:
        self._claims = claims
        self._delivery_fence = delivery_fence
        self._scheduler = scheduler
        self._closed_sessions: set[str] = set()
        self._lock = threading.Lock()

    def is_session_closed(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._closed_sessions

    def cancel_generation(self, generation_ref: GenerationRef) -> None:
        """Cancel logical delivery/claims for a generation while retaining physical M06 leases."""
        self._delivery_fence.purge_generation(generation_ref)

    async def close_session(
        self,
        session_id: str,
        *,
        session_ctx: SessionContext | None = None,
        reason: str = "synthesis_session_closed",
        wait_reclaims: bool = False,
    ) -> SessionCleanupReport:
        with self._lock:
            self._closed_sessions.add(session_id)

        cleanup_status = CleanupStatus.COMPLETE
        if session_ctx is not None:
            cleanup_status = await session_ctx.close(reason)

        if wait_reclaims and self._scheduler is not None:
            await self._scheduler.wait_reclaims()

        quarantined = 0
        if self._scheduler is not None:
            quarantined = self._scheduler.quarantine_manager.active_count
            if quarantined > 0:
                cleanup_status = CleanupStatus.PENDING_RECLAIM

        self._delivery_fence.purge_session(session_id)
        purged_claims = self._claims.purge_session(session_id)

        return SessionCleanupReport(
            session_id=session_id,
            closed=True,
            cleanup_status=cleanup_status,
            purged_claims=purged_claims,
            quarantined_leases=quarantined,
        )


__all__ = [
    "SessionCleanupReport",
    "SynthesisLifecycleManager",
]
