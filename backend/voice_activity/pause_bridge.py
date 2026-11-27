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

from typing import Callable

from backend.core.contracts.common import GenerationRef
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.result_admission import BoundedMediaQueue
from backend.core.runtime.turn_generation import PauseController, PauseRef
from backend.voice_activity.interruption_contracts import FlushIntent


class M02PauseBridge:
    """
    Thin bridge from F1-B interruption decisions to accepted M02 PauseController,
    CancellationScope, and BoundedMediaQueue.

    - Never creates a second pause state machine or second queue.
    - Never claims already-submitted in-flight audio has been recalled.
    """

    def __init__(
        self,
        pause_controller: PauseController,
        *,
        on_flush_intent: Callable[[FlushIntent], None] | None = None,
    ) -> None:
        self._pause = pause_controller
        self._on_flush_intent = on_flush_intent
        self._cmd_seq = 0

    @property
    def pause_controller(self) -> PauseController:
        return self._pause

    def request_soft_pause(
        self,
        gen_ref: GenerationRef,
        gen_scope: CancellationScope | None,
    ) -> PauseRef | None:
        """Request M02 soft pause once for a live, non-canceled generation."""
        if gen_scope is not None and gen_scope.is_cancel_requested:
            return None
        return self._pause.soft_pause(gen_ref)

    def resume_pause(
        self,
        pause_ref: PauseRef,
        current_gen: GenerationRef,
        gen_scope: CancellationScope,
        *,
        cursor_intact: bool = True,
    ) -> bool:
        """Atomically compare-and-open M02 pause gate if cursor and epoch match."""
        if not cursor_intact:
            return False
        return self._pause.resume(pause_ref, current_gen, gen_scope)

    def commit_interrupt(
        self,
        gen_ref: GenerationRef,
        gen_scope: CancellationScope,
        *,
        queue: BoundedMediaQueue | None = None,
        reason: str = "barge_in_commit",
        remote_flush_supported: bool = False,
    ) -> tuple[bool, FlushIntent]:
        """
        Atomically revoke target generation, purge owned unsent media in local queue,
        and construct a target-scoped FlushIntent (never claiming in-flight recall).
        """
        changed = self._pause.commit_interrupt(gen_ref, gen_scope, reason=reason)
        purged = 0
        if queue is not None:
            purged = queue.purge_generation(gen_ref.generation_id)
        self._cmd_seq += 1
        intent = FlushIntent(
            command_id=f"flush-{gen_ref.session_id}-{gen_ref.generation_id}-{self._cmd_seq}",
            target_generation=gen_ref,
            reason=reason,
            requested_scope="SERVER",
            local_purged_items=purged,
            remote_flush_status="PENDING" if remote_flush_supported else "UNSUPPORTED",
            in_flight_recall_claimed=False,
        )
        if self._on_flush_intent is not None:
            try:
                self._on_flush_intent(intent)
            except Exception:
                # Downstream flush callback failure must never reverse local commit fence.
                pass
        return changed, intent
