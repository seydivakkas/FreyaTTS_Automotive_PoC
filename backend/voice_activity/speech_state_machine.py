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
from backend.voice_activity.vad_engine import VADObservation


class AcousticState(StrEnum):
    """Acoustic segmentation FSM states (no business/session lifecycle ownership)."""

    IDLE = "IDLE"
    SPEECH_CANDIDATE = "SPEECH_CANDIDATE"
    SPEECH_ACTIVE = "SPEECH_ACTIVE"
    SILENCE_PENDING = "SILENCE_PENDING"
    FINALIZING = "FINALIZING"


class TransitionKind(StrEnum):
    NONE = "NONE"
    CANDIDATE_PINNED = "CANDIDATE_PINNED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"
    SPEECH_STARTED = "SPEECH_STARTED"
    SILENCE_STARTED = "SILENCE_STARTED"
    SILENCE_CANCELED = "SILENCE_CANCELED"
    READY_TO_FINALIZE = "READY_TO_FINALIZE"


@dataclass(frozen=True, slots=True)
class FSMTransition:
    previous_state: AcousticState
    new_state: AcousticState
    kind: TransitionKind
    sample_offset: int
    candidate_onset_sample: int | None = None
    low_run_start_sample: int | None = None
    low_run_real_samples: int = 0
    vad_score: float | None = None
    reason: str = ""


class SpeechStateMachine:
    """
    Deterministic hysteresis acoustic state machine.

    Rules:
    - Start qualification: score >= start_threshold
    - End qualification: score <= end_threshold
    - Mid-band (end_threshold < score < start_threshold) sustains active speech,
      cancels pending silence, and resets unconfirmed candidate confirmation.
    - Failed VAD observations (ok=False) do not advance low-run silence or onset.
    """

    def __init__(self, profile: F1ProfileConfig) -> None:
        self._profile = profile
        self._state: AcousticState = AcousticState.IDLE
        self._consecutive_high_windows: int = 0
        self._candidate_onset_sample: int | None = None
        self._utterance_start_sample: int | None = None
        self._actual_pre_roll_samples: int = 0
        self._low_run_start_sample: int | None = None
        self._low_run_real_samples: int = 0
        self._last_real_sample: int = 0
        self._speech_start_emitted: bool = False

    @property
    def state(self) -> AcousticState:
        return self._state

    @property
    def candidate_onset_sample(self) -> int | None:
        return self._candidate_onset_sample

    @property
    def utterance_start_sample(self) -> int | None:
        return self._utterance_start_sample

    @property
    def actual_pre_roll_samples(self) -> int:
        return self._actual_pre_roll_samples

    @property
    def low_run_start_sample(self) -> int | None:
        return self._low_run_start_sample

    @property
    def low_run_real_samples(self) -> int:
        return self._low_run_real_samples

    @property
    def last_real_sample(self) -> int:
        return self._last_real_sample

    @property
    def consecutive_high_windows(self) -> int:
        return self._consecutive_high_windows

    def attach_pinned_start(self, utterance_start_sample: int, actual_pre_roll_samples: int) -> None:
        self._utterance_start_sample = utterance_start_sample
        self._actual_pre_roll_samples = actual_pre_roll_samples

    def reset(self) -> None:
        self._state = AcousticState.IDLE
        self._consecutive_high_windows = 0
        self._candidate_onset_sample = None
        self._utterance_start_sample = None
        self._actual_pre_roll_samples = 0
        self._low_run_start_sample = None
        self._low_run_real_samples = 0
        self._speech_start_emitted = False

    def step(self, obs: VADObservation) -> FSMTransition:
        """Advance acoustic FSM by one VADObservation."""
        prev = self._state
        self._last_real_sample = max(self._last_real_sample, obs.end_sample_exclusive)

        if not obs.ok or obs.score is None:
            return FSMTransition(
                previous_state=prev,
                new_state=self._state,
                kind=TransitionKind.NONE,
                sample_offset=obs.start_sample,
                candidate_onset_sample=self._candidate_onset_sample,
                low_run_start_sample=self._low_run_start_sample,
                low_run_real_samples=self._low_run_real_samples,
                vad_score=None,
                reason=obs.error_code or "vad_observation_failed",
            )

        score = obs.score
        start_th = self._profile.start_threshold
        end_th = self._profile.end_threshold
        real_in_window = 0 if obs.padded_for_inference else obs.valid_samples

        if self._state == AcousticState.IDLE:
            if score >= start_th:
                self._candidate_onset_sample = obs.start_sample
                self._consecutive_high_windows = 1
                self._low_run_start_sample = None
                self._low_run_real_samples = 0
                if self._profile.onset_confirmation_windows <= 1:
                    self._state = AcousticState.SPEECH_ACTIVE
                    self._speech_start_emitted = True
                    return FSMTransition(
                        previous_state=prev,
                        new_state=self._state,
                        kind=TransitionKind.SPEECH_STARTED,
                        sample_offset=obs.start_sample,
                        candidate_onset_sample=self._candidate_onset_sample,
                        vad_score=score,
                        reason="onset_confirmed_1w",
                    )
                self._state = AcousticState.SPEECH_CANDIDATE
                return FSMTransition(
                    previous_state=prev,
                    new_state=self._state,
                    kind=TransitionKind.CANDIDATE_PINNED,
                    sample_offset=obs.start_sample,
                    candidate_onset_sample=self._candidate_onset_sample,
                    vad_score=score,
                    reason="candidate_threshold_met",
                )
            return FSMTransition(
                previous_state=prev,
                new_state=self._state,
                kind=TransitionKind.NONE,
                sample_offset=obs.start_sample,
                vad_score=score,
                reason="idle_below_start_threshold",
            )

        if self._state == AcousticState.SPEECH_CANDIDATE:
            if score >= start_th:
                self._consecutive_high_windows += 1
                if self._consecutive_high_windows >= self._profile.onset_confirmation_windows:
                    self._state = AcousticState.SPEECH_ACTIVE
                    self._speech_start_emitted = True
                    return FSMTransition(
                        previous_state=prev,
                        new_state=self._state,
                        kind=TransitionKind.SPEECH_STARTED,
                        sample_offset=obs.start_sample,
                        candidate_onset_sample=self._candidate_onset_sample,
                        vad_score=score,
                        reason="onset_confirmed",
                    )
                return FSMTransition(
                    previous_state=prev,
                    new_state=self._state,
                    kind=TransitionKind.NONE,
                    sample_offset=obs.start_sample,
                    candidate_onset_sample=self._candidate_onset_sample,
                    vad_score=score,
                    reason="candidate_accumulating",
                )

            # Rejected before onset confirmation (even mid-band scores reset consecutive counter).
            rejected_onset = self._candidate_onset_sample
            self.reset()
            return FSMTransition(
                previous_state=prev,
                new_state=self._state,
                kind=TransitionKind.CANDIDATE_REJECTED,
                sample_offset=obs.start_sample,
                candidate_onset_sample=rejected_onset,
                vad_score=score,
                reason="candidate_rejected_before_confirmation",
            )

        if self._state == AcousticState.SPEECH_ACTIVE:
            if score <= end_th:
                self._state = AcousticState.SILENCE_PENDING
                self._low_run_start_sample = obs.start_sample
                self._low_run_real_samples = real_in_window
                return FSMTransition(
                    previous_state=prev,
                    new_state=self._state,
                    kind=TransitionKind.SILENCE_STARTED,
                    sample_offset=obs.start_sample,
                    candidate_onset_sample=self._candidate_onset_sample,
                    low_run_start_sample=self._low_run_start_sample,
                    low_run_real_samples=self._low_run_real_samples,
                    vad_score=score,
                    reason="silence_run_started",
                )
            return FSMTransition(
                previous_state=prev,
                new_state=self._state,
                kind=TransitionKind.NONE,
                sample_offset=obs.start_sample,
                candidate_onset_sample=self._candidate_onset_sample,
                vad_score=score,
                reason="active_speech_sustained",
            )

        if self._state == AcousticState.SILENCE_PENDING:
            if score > end_th:
                self._state = AcousticState.SPEECH_ACTIVE
                self._low_run_start_sample = None
                self._low_run_real_samples = 0
                return FSMTransition(
                    previous_state=prev,
                    new_state=self._state,
                    kind=TransitionKind.SILENCE_CANCELED,
                    sample_offset=obs.start_sample,
                    candidate_onset_sample=self._candidate_onset_sample,
                    vad_score=score,
                    reason="speech_resumed_during_hangover",
                )
            self._low_run_real_samples += real_in_window
            return FSMTransition(
                previous_state=prev,
                new_state=self._state,
                kind=TransitionKind.NONE,
                sample_offset=obs.start_sample,
                candidate_onset_sample=self._candidate_onset_sample,
                low_run_start_sample=self._low_run_start_sample,
                low_run_real_samples=self._low_run_real_samples,
                vad_score=score,
                reason="silence_run_accumulating",
            )

        return FSMTransition(
            previous_state=prev,
            new_state=self._state,
            kind=TransitionKind.NONE,
            sample_offset=obs.start_sample,
            vad_score=score,
            reason="finalizing_pending",
        )

    def mark_finalizing(self) -> None:
        self._state = AcousticState.FINALIZING
