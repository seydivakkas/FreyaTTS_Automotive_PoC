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

import asyncio
from dataclasses import dataclass

from backend.core.runtime.resource_ledger import TaskRegistry
from backend.core.runtime.session_context import CleanupStatus
from backend.runtime_resources.scheduler import UnifiedGpuScheduler
from backend.speech_recognition.admission import ASRUtteranceAdmission
from backend.speech_recognition.input_manager import MaterializedAudio


@dataclass(frozen=True, slots=True)
class LifecycleDrainReport:
    """Honest shutdown/drain reconciliation report for F2-A tasks and leases."""

    cleanup_status: CleanupStatus
    cancelled_tasks: int
    still_pending_tasks: int
    quarantined_leases: int
    held_audio_handles: int
    task_exceptions: tuple[str, ...]


class ASRLifecycleManager:
    """Tracks F2-A async tasks and input handles for bounded shutdown and cleanup."""

    def __init__(self, *, max_tasks: int = 32) -> None:
        self._tasks = TaskRegistry(max_tasks=max_tasks)
        self._active_audio: set[int] = set()
        self._audio_refs: dict[int, MaterializedAudio] = {}

    @property
    def active_task_count(self) -> int:
        return self._tasks.active_count

    @property
    def active_audio_count(self) -> int:
        return len(self._audio_refs)

    def track_task(self, task: asyncio.Task) -> asyncio.Task:
        return self._tasks.track(task)

    def register_audio(self, audio: MaterializedAudio) -> None:
        key = id(audio)
        self._active_audio.add(key)
        self._audio_refs[key] = audio

    def release_audio_if_safe(self, audio: MaterializedAudio) -> bool:
        key = id(audio)
        if audio.borrowed_by_native:
            # Cannot release while native inference may still read the buffer.
            return False
        released = audio.release()
        self._active_audio.discard(key)
        self._audio_refs.pop(key, None)
        return released

    async def close_session_resources(
        self,
        *,
        session_id: str,
        admission: ASRUtteranceAdmission,
    ) -> int:
        return await admission.evict_session(session_id)

    async def shutdown_and_drain(
        self,
        *,
        scheduler: UnifiedGpuScheduler | None = None,
        drain_timeout_sec: float = 0.5,
    ) -> LifecycleDrainReport:
        cancelled, still_pending = await self._tasks.cancel_and_drain(timeout_sec=drain_timeout_sec)

        for key, audio in list(self._audio_refs.items()):
            if not audio.borrowed_by_native:
                audio.release()
                self._active_audio.discard(key)
                self._audio_refs.pop(key, None)

        quarantined = 0
        if scheduler is not None:
            quarantined = scheduler.quarantine_manager.active_count

        held_audio = len(self._audio_refs)
        status = (
            CleanupStatus.PENDING_RECLAIM
            if (still_pending > 0 or quarantined > 0 or held_audio > 0)
            else CleanupStatus.COMPLETE
        )
        return LifecycleDrainReport(
            cleanup_status=status,
            cancelled_tasks=cancelled,
            still_pending_tasks=still_pending,
            quarantined_leases=quarantined,
            held_audio_handles=held_audio,
            task_exceptions=tuple(self._tasks.exceptions),
        )
