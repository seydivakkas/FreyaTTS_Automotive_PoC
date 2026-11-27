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

from backend.core.contracts.common import StreamRef
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.voice_activity.config_adapter import F1RouteMode
from backend.voice_activity.continuation_rules import classify_turkish_cues
from backend.voice_activity.semantic_contracts import (
    AcousticEvidence,
    BackchannelCategory,
    ContinuationCue,
    EchoAcousticCategory,
    EndpointAdvice,
    EndpointAdviceKind,
    ExpectedSlotCategory,
    ExpectedSlotProjection,
    F1CProfileConfig,
    InterruptionAdvice,
    InterruptionAdviceKind,
    SemanticEndpointHint,
    quantize_min_windows,
)

_SLOT_BUDGET_MS: dict[ExpectedSlotCategory, int] = {
    ExpectedSlotCategory.SHORT_CONFIRMATION: 256,
    ExpectedSlotCategory.NAME: 512,
    ExpectedSlotCategory.VEHICLE: 640,
    ExpectedSlotCategory.DATE_TIME: 768,
    ExpectedSlotCategory.PHONE_PLATE: 1024,
}


class SemanticEndpointPolicy:
    """
    F1-C adaptive semantic endpointing policy inside SILENCE_PENDING.

    - Consumes optional F2-C SemanticEndpointHint, F0-B AcousticEvidence, and F3-A ExpectedSlotProjection.
    - Never manufactures silence, never allocates turns, and never exceeds pinned sample/wall caps.
    - Repeated hints never reset the per-episode monotonic semantic wait deadline.
    """

    def __init__(
        self,
        profile: F1CProfileConfig,
        stream_ref: StreamRef,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._profile = profile
        self._stream_ref = stream_ref
        self._clock: Clock = clock or SystemMonotonicClock()

        self._episode_low_start_sample: int | None = None
        self._episode_first_observed_ns: int | None = None
        self._episode_deadline_ns: int | None = None
        self._latest_hint: SemanticEndpointHint | None = None
        self._latest_context: ExpectedSlotProjection | None = None
        self._latest_acoustic: AcousticEvidence | None = None
        self._speech_scope_id: str | None = None

    @property
    def profile(self) -> F1CProfileConfig:
        return self._profile

    def update_stream_ref(self, stream_ref: StreamRef) -> None:
        if stream_ref != self._stream_ref:
            self._stream_ref = stream_ref
            self.reset_episode()
            self._latest_hint = None

    def set_speech_scope(self, speech_scope_id: str | None) -> None:
        if speech_scope_id != self._speech_scope_id:
            self._speech_scope_id = speech_scope_id
            self._latest_hint = None
            self.reset_episode()

    def reset_episode(self) -> None:
        self._episode_low_start_sample = None
        self._episode_first_observed_ns = None
        self._episode_deadline_ns = None

    def ingest_hint(self, hint: SemanticEndpointHint) -> bool:
        """Coalesce latest valid hint for current stream & speech scope."""
        if hint.stream_ref != self._stream_ref:
            return False
        if self._speech_scope_id is not None and hint.speech_scope_id != self._speech_scope_id:
            return False
        if self._latest_hint is not None and hint.revision < self._latest_hint.revision:
            return False
        if hint.stable_prefix_revoked:
            self._latest_hint = None
            return False
        self._latest_hint = hint
        return True

    def ingest_context(self, context: ExpectedSlotProjection) -> None:
        self._latest_context = context

    def ingest_acoustic_evidence(self, evidence: AcousticEvidence) -> bool:
        if evidence.stream_ref != self._stream_ref:
            return False
        self._latest_acoustic = evidence
        return True

    def _is_hint_valid(self, hint: SemanticEndpointHint | None, *, last_real_sample: int, now_ns: int) -> bool:
        if hint is None or hint.sealed or hint.stable_prefix_revoked:
            return False
        if hint.stream_ref != self._stream_ref:
            return False
        if hint.clock_domain != self._clock.clock_domain:
            return False
        age_ns = now_ns - hint.observed_monotonic_ns
        ttl_ns = min(hint.ttl_ms, self._profile.hint_ttl_ms) * 1_000_000
        if age_ns < 0 or age_ns > ttl_ns:
            return False
        if hint.covered_end_sample_exclusive > last_real_sample:
            return False
        if (last_real_sample - hint.covered_end_sample_exclusive) > self._profile.hint_max_coverage_lag_samples:
            return False
        return True

    def _is_context_valid(self, ctx: ExpectedSlotProjection | None, *, now_ns: int) -> bool:
        if ctx is None or ctx.clock_domain != self._clock.clock_domain:
            return False
        age_ns = now_ns - ctx.issued_monotonic_ns
        ttl_ns = min(ctx.ttl_ms, self._profile.context_ttl_ms) * 1_000_000
        return 0 <= age_ns <= ttl_ns

    def evaluate_silence_pending(
        self,
        *,
        low_run_start_sample: int,
        low_run_real_samples: int,
        last_real_sample: int,
    ) -> EndpointAdvice:
        """Compute bounded adaptive silence threshold inside SILENCE_PENDING."""
        base_samples = self._profile.base_budget_samples
        base_windows = base_samples // self._profile.window_samples
        if self._profile.mode == F1RouteMode.OFF:
            kind = EndpointAdviceKind.FINALIZE if low_run_real_samples >= base_samples else EndpointAdviceKind.ACOUSTIC_FALLBACK
            return EndpointAdvice(
                kind=kind,
                effective_silence_samples=base_samples,
                effective_windows=base_windows,
                requested_budget_ms=self._profile.base_budget_ms,
                effective_budget_ms=base_windows * 32,
                reason="f1c_mode_off_baseline",
            )

        now_ns = self._clock.monotonic_ns()
        if self._episode_low_start_sample != low_run_start_sample:
            self._episode_low_start_sample = low_run_start_sample
            self._episode_first_observed_ns = now_ns
            self._episode_deadline_ns = now_ns + (self._profile.semantic_wait_deadline_ms * 1_000_000)

        # If semantic wait deadline expired, drop any optional extension and use base acoustic threshold.
        if self._episode_deadline_ns is not None and now_ns >= self._episode_deadline_ns:
            kind = EndpointAdviceKind.FINALIZE if low_run_real_samples >= base_samples else EndpointAdviceKind.ACOUSTIC_FALLBACK
            return EndpointAdvice(
                kind=kind,
                effective_silence_samples=base_samples,
                effective_windows=base_windows,
                requested_budget_ms=self._profile.base_budget_ms,
                effective_budget_ms=base_windows * 32,
                reason="semantic_wait_deadline_expired",
            )

        ctx = self._latest_context if self._is_context_valid(self._latest_context, now_ns=now_ns) else None
        hint = self._latest_hint if self._is_hint_valid(self._latest_hint, last_real_sample=last_real_sample, now_ns=now_ns) else None

        cue = ContinuationCue.UNKNOWN
        if hint is not None:
            if hint.cue is not None and hint.cue != ContinuationCue.UNKNOWN:
                cue = hint.cue
            elif hint.provisional_text:
                cue = classify_turkish_cues(hint.provisional_text, context=ctx)

        requested_ms = self._profile.base_budget_ms
        reason = "acoustic_fallback"

        if cue in (ContinuationCue.POSSIBLE_CONTINUATION, ContinuationCue.CORRECTION_OR_NEGATION):
            requested_ms = 1152
            reason = f"cue_{cue.value.lower()}"
        elif cue == ContinuationCue.INCOMPLETE_EXPECTED_SLOT:
            slot_ms = _SLOT_BUDGET_MS.get(ctx.expected_slot, 1024) if ctx is not None else 1024
            requested_ms = max(slot_ms, 768)
            reason = "incomplete_expected_slot"
        elif cue == ContinuationCue.POSSIBLE_COMPLETION and ctx is not None and ctx.expected_slot == ExpectedSlotCategory.SHORT_CONFIRMATION:
            requested_ms = self._profile.min_budget_ms
            reason = "short_confirmation_completion"
        elif ctx is not None and ctx.expected_slot in _SLOT_BUDGET_MS:
            requested_ms = _SLOT_BUDGET_MS[ctx.expected_slot]
            reason = f"expected_slot_{ctx.expected_slot.value.lower()}"

        # Clamp to [min_budget_samples, max_budget_samples] with exact window quantization.
        req_windows = quantize_min_windows(
            requested_ms,
            sample_rate_hz=self._profile.sample_rate_hz,
            window_samples=self._profile.window_samples,
        )
        eff_samples = req_windows * self._profile.window_samples
        eff_samples = max(self._profile.min_budget_samples, min(self._profile.max_budget_samples, eff_samples))
        eff_windows = eff_samples // self._profile.window_samples

        if self._profile.mode == F1RouteMode.SHADOW:
            # Shadow mode observes without altering the actual acoustic threshold.
            kind = EndpointAdviceKind.FINALIZE if low_run_real_samples >= base_samples else EndpointAdviceKind.ACOUSTIC_FALLBACK
            return EndpointAdvice(
                kind=kind,
                effective_silence_samples=base_samples,
                effective_windows=base_windows,
                requested_budget_ms=requested_ms,
                effective_budget_ms=eff_windows * 32,
                reason=f"shadow:{reason}",
                cue=cue,
            )

        kind = EndpointAdviceKind.FINALIZE if low_run_real_samples >= eff_samples else EndpointAdviceKind.WAIT
        return EndpointAdvice(
            kind=kind,
            effective_silence_samples=eff_samples,
            effective_windows=eff_windows,
            requested_budget_ms=requested_ms,
            effective_budget_ms=eff_windows * 32,
            reason=reason,
            cue=cue,
        )

    def advise_interruption(
        self,
        *,
        window_start_sample: int,
        window_end_sample_exclusive: int,
        has_active_output: bool,
    ) -> InterruptionAdvice:
        """
        Advise F1-B on echo-only vs double-talk vs backchannel during active output.
        Never forces F1-B to drop confirmed near-end speech.
        """
        if not has_active_output:
            return InterruptionAdvice(
                kind=InterruptionAdviceKind.BASELINE,
                backchannel_category=BackchannelCategory.UNKNOWN,
                acoustic_category=EchoAcousticCategory.UNKNOWN,
                reason="no_active_output",
            )

        now_ns = self._clock.monotonic_ns()
        ev = self._latest_acoustic
        acoustic_cat = EchoAcousticCategory.UNKNOWN
        if (
            ev is not None
            and ev.stream_ref == self._stream_ref
            and ev.clock_domain == self._clock.clock_domain
            and ev.reference_valid
            and ev.alignment_valid
            and ev.history_sufficient
            and 0 <= (now_ns - ev.observed_monotonic_ns) <= (self._profile.acoustic_evidence_max_age_ms * 1_000_000)
            and ev.start_sample < window_end_sample_exclusive
            and ev.end_sample_exclusive > window_start_sample
        ):
            acoustic_cat = ev.category

        ctx = self._latest_context if self._is_context_valid(self._latest_context, now_ns=now_ns) else None
        hint = self._latest_hint if self._is_hint_valid(self._latest_hint, last_real_sample=window_end_sample_exclusive, now_ns=now_ns) else None

        cue = ContinuationCue.UNKNOWN
        if hint is not None:
            cue = hint.cue if (hint.cue is not None and hint.cue != ContinuationCue.UNKNOWN) else classify_turkish_cues(hint.provisional_text, context=ctx)

        if acoustic_cat in (EchoAcousticCategory.DOUBLE_TALK_LIKELY, EchoAcousticCategory.NEAR_END_ONLY_LIKELY):
            return InterruptionAdvice(
                kind=InterruptionAdviceKind.COMMIT_ELIGIBLE,
                backchannel_category=BackchannelCategory.INTERRUPT_LIKELY,
                acoustic_category=acoustic_cat,
                reason="near_end_or_double_talk_detected",
            )

        if cue in (ContinuationCue.EXPLICIT_INTERRUPT_CUE, ContinuationCue.CORRECTION_OR_NEGATION):
            return InterruptionAdvice(
                kind=InterruptionAdviceKind.COMMIT_ELIGIBLE,
                backchannel_category=BackchannelCategory.INTERRUPT_LIKELY,
                acoustic_category=acoustic_cat,
                reason="explicit_interrupt_or_negation_cue",
            )

        if acoustic_cat == EchoAcousticCategory.FAR_END_ONLY_LIKELY:
            kind = InterruptionAdviceKind.RESUME_ELIGIBLE if self._profile.enable_echo_rejection else InterruptionAdviceKind.BASELINE
            return InterruptionAdvice(
                kind=kind,
                backchannel_category=BackchannelCategory.ECHO_ONLY_LIKELY,
                acoustic_category=acoustic_cat,
                reason="far_end_echo_only_likely",
            )

        if cue == ContinuationCue.BACKCHANNEL_CANDIDATE:
            if ctx is not None and (ctx.confirmation_pending or ctx.expected_slot == ExpectedSlotCategory.SHORT_CONFIRMATION):
                return InterruptionAdvice(
                    kind=InterruptionAdviceKind.COMMIT_ELIGIBLE,
                    backchannel_category=BackchannelCategory.MEANINGFUL_RESPONSE,
                    acoustic_category=acoustic_cat,
                    reason="meaningful_response_in_confirmation_context",
                )
            kind = InterruptionAdviceKind.RESUME_ELIGIBLE if self._profile.enable_backchannel_rejection else InterruptionAdviceKind.BASELINE
            return InterruptionAdvice(
                kind=kind,
                backchannel_category=BackchannelCategory.BACKCHANNEL_LIKELY,
                acoustic_category=acoustic_cat,
                reason="backchannel_candidate",
            )

        return InterruptionAdvice(
            kind=InterruptionAdviceKind.BASELINE,
            backchannel_category=BackchannelCategory.UNKNOWN,
            acoustic_category=acoustic_cat,
            reason="no_valid_precommit_semantic_evidence",
        )
