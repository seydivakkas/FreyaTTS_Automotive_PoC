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

from backend.voice_activity.config_adapter import F1ProfileConfig
from backend.voice_activity.speech_state_machine import AcousticState, SpeechStateMachine


class FinalizationReason(StrEnum):
    ACOUSTIC_SILENCE = "ACOUSTIC_SILENCE"
    MAX_DURATION = "MAX_DURATION"
    EXPLICIT_EOS = "EXPLICIT_EOS"


@dataclass(frozen=True, slots=True)
class EndpointCutDecision:
    should_finalize: bool
    reason: FinalizationReason | None = None
    start_sample: int = 0
    end_sample_exclusive: int = 0
    speech_end_estimate_sample: int | None = None
    actual_pre_roll_samples: int = 0
    actual_post_roll_samples: int = 0


class EndpointingPolicy:
    """
    Deterministic acoustic endpointing, post-roll cut, hard max-duration cap,
    and EOS precedence policy.

    Precedence at linearization point:
    1. Hard max duration cap (MAX_DURATION) whenever last_real_sample >= start + max_utterance_samples,
       including exact tie with acoustic silence cut.
    2. Acoustic silence endpoint when consecutive low real samples >= endpoint_silence_samples.
       Final slice end = min(last_real_sample, low_run_start + post_roll_samples, hard_cap_end).
    3. Explicit graceful EOS on active/pending utterance.
    """

    def __init__(self, profile: F1ProfileConfig) -> None:
        self._profile = profile

    def evaluate(
        self,
        fsm: SpeechStateMachine,
        *,
        eos_requested: bool = False,
        effective_silence_samples: int | None = None,
    ) -> EndpointCutDecision:
        if fsm.state not in (AcousticState.SPEECH_ACTIVE, AcousticState.SILENCE_PENDING):
            return EndpointCutDecision(should_finalize=False)

        if fsm.utterance_start_sample is None:
            return EndpointCutDecision(should_finalize=False)

        start = fsm.utterance_start_sample
        last_real = fsm.last_real_sample
        hard_cap_end = start + self._profile.max_utterance_samples
        pre_roll = fsm.actual_pre_roll_samples
        silence_threshold = (
            effective_silence_samples
            if effective_silence_samples is not None
            else self._profile.endpoint_silence_samples
        )

        silence_ready = (
            fsm.state == AcousticState.SILENCE_PENDING
            and fsm.low_run_start_sample is not None
            and fsm.low_run_real_samples >= silence_threshold
        )
        hard_cap_reached = last_real >= hard_cap_end

        if hard_cap_reached:
            cut_end = hard_cap_end
            low_start = fsm.low_run_start_sample if silence_ready else None
            post_roll = max(0, min(cut_end - low_start, self._profile.post_roll_samples)) if low_start is not None else 0
            return EndpointCutDecision(
                should_finalize=True,
                reason=FinalizationReason.MAX_DURATION,
                start_sample=start,
                end_sample_exclusive=cut_end,
                speech_end_estimate_sample=low_start if low_start is not None else cut_end,
                actual_pre_roll_samples=pre_roll,
                actual_post_roll_samples=post_roll,
            )

        if silence_ready:
            assert fsm.low_run_start_sample is not None
            low_start = fsm.low_run_start_sample
            cut_end = min(last_real, low_start + self._profile.post_roll_samples, hard_cap_end)
            cut_end = max(start, cut_end)
            actual_post_roll = max(0, cut_end - low_start)
            return EndpointCutDecision(
                should_finalize=True,
                reason=FinalizationReason.ACOUSTIC_SILENCE,
                start_sample=start,
                end_sample_exclusive=cut_end,
                speech_end_estimate_sample=low_start,
                actual_pre_roll_samples=pre_roll,
                actual_post_roll_samples=actual_post_roll,
            )

        if eos_requested and last_real > start:
            cut_end = min(last_real, hard_cap_end)
            low_start = fsm.low_run_start_sample
            actual_post_roll = 0
            if low_start is not None and cut_end > low_start:
                actual_post_roll = min(cut_end - low_start, self._profile.post_roll_samples)
            return EndpointCutDecision(
                should_finalize=True,
                reason=FinalizationReason.EXPLICIT_EOS,
                start_sample=start,
                end_sample_exclusive=cut_end,
                speech_end_estimate_sample=low_start if low_start is not None else cut_end,
                actual_pre_roll_samples=pre_roll,
                actual_post_roll_samples=actual_post_roll,
            )

        return EndpointCutDecision(should_finalize=False)
