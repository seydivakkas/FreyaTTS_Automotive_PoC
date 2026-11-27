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

from backend.core.contracts.common import StreamRef, TurnRef
from backend.core.contracts.validation import require_safe_id, require_strict_int
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.deadlines import Clock, DeadlineBudget
from backend.runtime_resources.contracts import PriorityClass, ProviderKind, ResourceRequest
from backend.speech_recognition.config_adapter import PinnedASRConfig
from backend.speech_recognition.input_manager import ValidatedUtteranceInput
from backend.speech_recognition.lexicon_adapter import HotwordSelection, PinnedLexiconSnapshot


@dataclass(frozen=True, slots=True)
class ASRJobPayload:
    """Immutable snapshot-bound F2-A job payload passed inside M06 ResourceRequest."""

    recognition_job_id: str
    attempt_index: int
    utterance_input: ValidatedUtteranceInput
    stream_ref: StreamRef
    turn_ref: TurnRef
    pinned_config: PinnedASRConfig
    pinned_lexicon: PinnedLexiconSnapshot
    hotwords: HotwordSelection
    word_timestamps: bool = False

    def __post_init__(self) -> None:
        require_safe_id(self.recognition_job_id, "recognition_job_id")
        require_strict_int(self.attempt_index, "attempt_index", minimum=0)


def build_asr_resource_request(
    *,
    recognition_job_id: str,
    utterance_input: ValidatedUtteranceInput,
    pinned_config: PinnedASRConfig,
    pinned_lexicon: PinnedLexiconSnapshot,
    hotwords: HotwordSelection,
    cancellation_scope: CancellationScope,
    clock: Clock,
    attempt_index: int = 0,
    drain_grace_ms: int = 50,
    word_timestamps: bool = False,
) -> ResourceRequest:
    """
    Map an admitted final utterance and pinned snapshots into an M06 P1 ResourceRequest.

    Always uses PriorityClass.P1 (final ASR) and ProviderKind.CTRANSLATE2, bound to
    the input turn CancellationScope (never an unrelated playback generation scope).
    """
    deadline = DeadlineBudget.from_now(clock, pinned_config.deadline_ms)
    job_payload = ASRJobPayload(
        recognition_job_id=recognition_job_id,
        attempt_index=attempt_index,
        utterance_input=utterance_input,
        stream_ref=utterance_input.stream_ref,
        turn_ref=utterance_input.turn_ref,
        pinned_config=pinned_config,
        pinned_lexicon=pinned_lexicon,
        hotwords=hotwords,
        word_timestamps=word_timestamps,
    )
    return ResourceRequest(
        request_id=recognition_job_id,
        priority=PriorityClass.P1,
        provider=ProviderKind.CTRANSLATE2,
        model_id=pinned_config.model_id,
        estimated_vram_bytes=pinned_config.estimated_vram_bytes,
        cancellation_scope=cancellation_scope,
        session_id=utterance_input.stream_ref.session_id,
        turn_ref=utterance_input.turn_ref,
        generation_ref=None,
        deadline=deadline,
        supersession_key=None,
        drain_grace_ms=drain_grace_ms,
        payload=job_payload,
    )
