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

import hashlib
import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import StreamRef, TurnRef
from backend.core.contracts.recognition import ASROutcome, ASRStatus, UnicodeSpan
from backend.core.contracts.speech import Utterance
from backend.core.contracts.validation import require_strict_int
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.deadlines import Clock, DeadlineBudget
from backend.runtime_resources.contracts import PriorityClass, ProviderKind, ResourceRequest
from backend.shared_lexicon.unicode_normalizer import normalize_matching_key, normalize_with_spans
from backend.speech_recognition.config_adapter import PinnedASRConfig
from backend.speech_recognition.entity_resolver import resolve_automotive_entities
from backend.speech_recognition.hotword_planner import HotwordPlan
from backend.speech_recognition.input_manager import MaterializedAudio, ValidatedUtteranceInput
from backend.speech_recognition.lexicon_adapter import HotwordSelection, PinnedLexiconSnapshot
from backend.speech_recognition.partial_contracts import (
    ContinuationCue,
    DecodeWindow,
    FinalizationBinding,
    PartialHypothesis,
    PartialLaneState,
    ProvisionalRecognitionRevision,
    ReconciledView,
    SemanticEndpointHint,
    SpeechScopeRef,
    StablePrefixEvidence,
    TokenProvenance,
    WordObservation,
)
from backend.speech_recognition.request_builder import ASRJobPayload
from backend.speech_recognition.transcript_collector import CollectedTranscript
from backend.speech_recognition.whisper_engine import WhisperSchedulerEngine

_CONTINUATION_END_TOKENS = frozenset({"ve", "ama", "fakat", "ancak", "bir", "de", "da", "değil", "veya", "yoksa"})


@dataclass(frozen=True, slots=True)
class StreamingWindowConfig:
    """Validated F2-C laboratory windowing, overlap, stability, and TTL parameters."""

    sample_rate_hz: int = 16_000
    earliest_partial_samples: int = 12_800  # 800 ms
    normal_window_samples: int = 32_000  # 2 s
    max_window_samples: int = 80_000  # 5 s
    min_overlap_samples: int = 8_000  # 500 ms
    stride_samples: int = 8_000  # 500 ms
    stability_observations: int = 2
    boundary_guard_samples: int = 5_120  # 320 ms
    hint_ttl_ns: int = 750_000_000  # 750 ms
    partial_deadline_ms: int = 800
    max_tokens_per_window: int = 256
    max_retained_tokens: int = 512

    def __post_init__(self) -> None:
        if self.sample_rate_hz != 16_000:
            raise ValueError("sample_rate_hz must be 16000")
        require_strict_int(self.earliest_partial_samples, "earliest_partial_samples", minimum=1_600)
        require_strict_int(self.normal_window_samples, "normal_window_samples", minimum=self.earliest_partial_samples)
        require_strict_int(self.max_window_samples, "max_window_samples", minimum=self.normal_window_samples)
        require_strict_int(self.min_overlap_samples, "min_overlap_samples", minimum=0, maximum=self.max_window_samples)
        require_strict_int(self.stride_samples, "stride_samples", minimum=1_600)
        require_strict_int(self.stability_observations, "stability_observations", minimum=2, maximum=10)
        require_strict_int(self.boundary_guard_samples, "boundary_guard_samples", minimum=0)
        require_strict_int(self.hint_ttl_ns, "hint_ttl_ns", minimum=1_000_000)
        require_strict_int(self.partial_deadline_ms, "partial_deadline_ms", minimum=50, maximum=10_000)


@dataclass(slots=True)
class _ScopeRuntime:
    scope: SpeechScopeRef
    cancellation_scope: CancellationScope
    state: PartialLaneState = PartialLaneState.CONFIRMED_ACTIVE
    chunks: list[np.ndarray] = field(default_factory=list)
    total_samples: int = 0
    has_gap: bool = False
    last_planned_end: int = 0
    last_accepted_start: int | None = None
    last_accepted_end: int | None = None
    window_seq: int = 0
    revision_seq: int = 0
    last_hypothesis: PartialHypothesis | None = None
    reconciled: ReconciledView | None = None
    token_support: list[tuple[str, str, int, str]] = field(default_factory=list)  # (raw_tok, norm_tok, obs_count, win_id)
    stable_prefix: StablePrefixEvidence | None = None
    latest_hint: SemanticEndpointHint | None = None
    pending_window_id: str | None = None
    running_window_id: str | None = None
    revisions: deque[ProvisionalRecognitionRevision] = field(default_factory=lambda: deque(maxlen=64))
    final_binding: FinalizationBinding | None = None


def _extract_word_observations(
    collected: CollectedTranscript,
    *,
    window_start_sample: int,
    window_end_sample: int,
    sample_rate_hz: int,
) -> tuple[tuple[WordObservation, ...], str]:
    observations: list[WordObservation] = []
    window_dur_sec = (window_end_sample - window_start_sample) / float(sample_rate_hz)
    has_any_words = any(seg.words for seg in collected.segments)
    if not has_any_words:
        return (), "UNKNOWN"

    for seg in collected.segments:
        for w in seg.words:
            if (
                not math.isfinite(w.start_sec)
                or not math.isfinite(w.end_sec)
                or w.start_sec < 0.0
                or w.end_sec < w.start_sec
                or w.end_sec > (window_dur_sec + 0.05)
            ):
                return (), "INVALID_REJECTED"
            abs_s = window_start_sample + int(math.floor(w.start_sec * sample_rate_hz))
            abs_e = min(window_end_sample, window_start_sample + int(math.ceil(w.end_sec * sample_rate_hz)))
            observations.append(
                WordObservation(
                    word=w.word,
                    normalized_word=normalize_matching_key(w.word),
                    rel_start_sec=w.start_sec,
                    rel_end_sec=w.end_sec,
                    abs_start_sample=abs_s,
                    abs_end_sample_exclusive=max(abs_s, abs_e),
                    probability=w.probability,
                    valid_timing=True,
                )
            )
    return tuple(observations), "VALID"


def _infer_continuation_cue(derived_text: str) -> ContinuationCue:
    stripped = derived_text.strip()
    if not stripped:
        return ContinuationCue.UNCERTAIN
    tokens = normalize_matching_key(stripped).split()
    if not tokens:
        return ContinuationCue.UNCERTAIN
    last = tokens[-1]
    if last in _CONTINUATION_END_TOKENS or last.isdigit():
        return ContinuationCue.POSSIBLE_CONTINUATION
    if stripped.endswith((".", "!", "?")):
        return ContinuationCue.POSSIBLE_COMPLETION
    return ContinuationCue.UNCERTAIN


class PseudoStreamingController:
    """
    Bounded F2-C pseudo-streaming controller running M06 P5 windowed partial decodes
    around F2-A/B's WhisperSchedulerEngine and sealing cleanly on F1-A finalization.
    """

    def __init__(
        self,
        *,
        engine: WhisperSchedulerEngine,
        config: StreamingWindowConfig | None = None,
        pinned_lexicon: PinnedLexiconSnapshot | None = None,
    ) -> None:
        self.engine = engine
        self.config = config or StreamingWindowConfig()
        self.pinned_lexicon = pinned_lexicon
        self._scopes: dict[str, _ScopeRuntime] = {}
        self._terminated_scopes: set[str] = set()

    @property
    def clock(self) -> Clock:
        return self.engine.scheduler.clock

    def open_scope(
        self,
        scope: SpeechScopeRef,
        *,
        cancellation_scope: CancellationScope | None = None,
    ) -> SpeechScopeRef:
        """Register a confirmed acoustic onset scope; rejects reopening terminal scopes."""
        if scope.speech_ref in self._terminated_scopes:
            raise ValueError(f"Scope {scope.speech_ref!r} is terminal and cannot reopen")
        if scope.speech_ref in self._scopes:
            return self._scopes[scope.speech_ref].scope
        c_scope = cancellation_scope or CancellationScope(f"partial:{scope.speech_ref}")
        self._scopes[scope.speech_ref] = _ScopeRuntime(scope=scope, cancellation_scope=c_scope)
        return scope

    def get_state(self, speech_ref: str) -> PartialLaneState | None:
        rt = self._scopes.get(speech_ref)
        if rt is not None:
            return rt.state
        if speech_ref in self._terminated_scopes:
            return PartialLaneState.TERMINAL
        return None

    def append_audio(
        self,
        speech_ref: str,
        samples_f32: np.ndarray,
        *,
        audio_format: AudioFormat,
        has_gap: bool = False,
    ) -> int:
        """Append validated 16 kHz mono float32 audio samples to an active scope."""
        rt = self._scopes.get(speech_ref)
        if rt is None or rt.state != PartialLaneState.CONFIRMED_ACTIVE:
            raise RuntimeError(f"Scope {speech_ref!r} is not CONFIRMED_ACTIVE")
        if audio_format.sample_rate_hz != self.config.sample_rate_hz or audio_format.channels != 1:
            raise ValueError("Invalid audio format for F2-C streaming")
        if audio_format.encoding not in {AudioEncoding.FLOAT32_LE, AudioEncoding.PCM_S16LE}:
            raise ValueError("Unsupported audio encoding for F2-C streaming")
        arr = np.asarray(samples_f32, dtype=np.float32)
        if arr.ndim != 1 or arr.size == 0:
            raise ValueError("samples_f32 must be non-empty 1D array")
        ro = arr.copy()
        ro.setflags(write=False)
        rt.chunks.append(ro)
        rt.total_samples += int(ro.size)
        if has_gap:
            rt.has_gap = True
        return rt.total_samples

    def plan_next_window(
        self,
        speech_ref: str,
        *,
        pinned_config: PinnedASRConfig,
    ) -> DecodeWindow | None:
        """
        Plan next half-open DecodeWindow if warm-up and stride thresholds are met.
        Uses bounded expansion up to max_window_samples to restore overlap on delay.
        """
        rt = self._scopes.get(speech_ref)
        if rt is None or rt.state != PartialLaneState.CONFIRMED_ACTIVE:
            return None
        if rt.cancellation_scope.is_cancel_requested or rt.has_gap:
            return None

        end_abs = rt.scope.start_sample + rt.total_samples
        real_len = rt.total_samples
        if real_len < self.config.earliest_partial_samples:
            return None
        if rt.last_planned_end > 0 and (end_abs - rt.last_planned_end) < self.config.stride_samples:
            return None

        if rt.last_accepted_end is None:
            win_len = min(real_len, self.config.normal_window_samples)
            start_abs = max(rt.scope.start_sample, end_abs - win_len)
            overlap = 0
        else:
            desired_start = max(rt.scope.start_sample, end_abs - self.config.normal_window_samples)
            overlap = rt.last_accepted_end - desired_start
            if overlap < self.config.min_overlap_samples:
                # Bounded expansion up to max_window_samples to restore overlap
                expanded_start = max(rt.scope.start_sample, end_abs - self.config.max_window_samples)
                target_start = min(desired_start, max(expanded_start, rt.last_accepted_end - self.config.min_overlap_samples))
                start_abs = max(expanded_start, target_start)
                overlap = max(0, rt.last_accepted_end - start_abs)
            else:
                start_abs = desired_start

        rt.window_seq += 1
        rt.last_planned_end = end_abs
        win_id = f"w-{rt.window_seq}-{rt.scope.speech_ref[:24]}"
        rt.pending_window_id = win_id
        return DecodeWindow(
            scope=rt.scope,
            window_id=win_id,
            request_revision=rt.window_seq,
            start_sample=start_abs,
            end_sample_exclusive=end_abs,
            overlap_with_prev_samples=overlap,
            model_revision=pinned_config.model_revision,
            config_revision=pinned_config.config_revision,
            lexicon_revision=self.pinned_lexicon.lexicon_revision if self.pinned_lexicon else None,
            deadline_ns=self.clock.monotonic_ns() + self.config.partial_deadline_ms * 1_000_000,
        )

    def _slice_window_audio(self, rt: _ScopeRuntime, start_abs: int, end_abs: int) -> np.ndarray:
        full = np.concatenate(rt.chunks) if len(rt.chunks) > 1 else rt.chunks[0]
        rel_s = start_abs - rt.scope.start_sample
        rel_e = end_abs - rt.scope.start_sample
        sliced = full[rel_s:rel_e].copy()
        sliced.setflags(write=False)
        return sliced

    async def run_partial_window(
        self,
        window: DecodeWindow,
        *,
        pinned_config: PinnedASRConfig,
        audio_format: AudioFormat,
        hotword_plan: HotwordPlan | None = None,
        word_timestamps: bool = True,
    ) -> ProvisionalRecognitionRevision | None:
        """
        Execute a P5 partial decode through M06 UnifiedGpuScheduler, reconcile overlap,
        update revocable StablePrefixEvidence, and publish non-actionable revision.
        """
        rt = self._scopes.get(window.scope.speech_ref)
        if rt is None or rt.state != PartialLaneState.CONFIRMED_ACTIVE:
            return None
        if rt.cancellation_scope.is_cancel_requested:
            return None
        if window.scope.stream_ref.format_epoch != rt.scope.stream_ref.format_epoch:
            return None

        # Supersede pending if newer window arrived; never run two partials concurrently per scope
        if rt.running_window_id is not None:
            return None
        rt.running_window_id = window.window_id
        rt.pending_window_id = None

        try:
            samples = self._slice_window_audio(rt, window.start_sample, window.end_sample_exclusive)
            digest = hashlib.sha256(samples.tobytes()).hexdigest()
            mat_audio = MaterializedAudio(
                sample_rate_hz=self.config.sample_rate_hz,
                channels=1,
                source_encoding=audio_format.encoding,
                sample_count=int(samples.size),
                start_sample=window.start_sample,
                end_sample_exclusive=window.end_sample_exclusive,
                pre_roll_samples=0,
                post_roll_samples=0,
                payload_sha256=digest,
                _array=samples,
            )
            dummy_turn = rt.scope.turn_ref or TurnRef(
                session_id=rt.scope.session_id,
                turn_id=0,
            )
            utt = Utterance(
                utterance_id=f"partial-{window.window_id}",
                stream_ref=rt.scope.stream_ref,
                turn_ref=dummy_turn,
                start_sample=window.start_sample,
                end_sample_exclusive=window.end_sample_exclusive,
                finalized=True,
                finalization_reason="partial_window",
                frame_refs=(window.window_id,),
            )
            val_input = ValidatedUtteranceInput(
                utterance=utt,
                stream_ref=rt.scope.stream_ref,
                turn_ref=dummy_turn,
                audio_format=audio_format,
                audio=mat_audio,
                payload_digest=digest,
                empty_audio=False,
            )
            lex = self.pinned_lexicon or PinnedLexiconSnapshot(registry=None, lexicon_revision=None, available=False)
            hw = HotwordSelection(
                terms=hotword_plan.terms if hotword_plan else (),
                hotwords_text=hotword_plan.hotwords_text if hotword_plan else None,
                from_cache=False,
                filtered_pii_count=0,
            )
            req_id = f"p5-{window.window_id}"
            payload = ASRJobPayload(
                recognition_job_id=req_id,
                attempt_index=0,
                utterance_input=val_input,
                stream_ref=rt.scope.stream_ref,
                turn_ref=dummy_turn,
                pinned_config=pinned_config,
                pinned_lexicon=lex,
                hotwords=hw,
                word_timestamps=word_timestamps,
            )
            request = ResourceRequest(
                request_id=req_id,
                priority=PriorityClass.P5,
                provider=ProviderKind.CTRANSLATE2,
                model_id=pinned_config.model_id,
                estimated_vram_bytes=pinned_config.estimated_vram_bytes,
                cancellation_scope=rt.cancellation_scope,
                session_id=rt.scope.session_id,
                turn_ref=None,
                generation_ref=None,
                deadline=DeadlineBudget.from_now(self.clock, self.config.partial_deadline_ms),
                supersession_key=f"partial:{rt.scope.session_id}",
                drain_grace_ms=30,
                payload=payload,
            )

            exec_res = await self.engine.run_admitted(request)
            mat_audio.release()

            # Check seal/cancel after native completion (never publish after seal!)
            if rt.state != PartialLaneState.CONFIRMED_ACTIVE or rt.cancellation_scope.is_cancel_requested:
                return None
            if exec_res.asr_outcome != ASROutcome.OK or exec_res.collected is None:
                return None

            raw_text = exec_res.collected.raw_transcript
            norm_text = normalize_with_spans(raw_text).normalized_text
            words, ts_status = _extract_word_observations(
                exec_res.collected,
                window_start_sample=window.start_sample,
                window_end_sample=window.end_sample_exclusive,
                sample_rate_hz=self.config.sample_rate_hz,
            )

            hyp = PartialHypothesis(
                scope=rt.scope,
                window_id=window.window_id,
                request_id=req_id,
                raw_transcript=raw_text,
                normalized_text=norm_text,
                words=words,
                start_sample=window.start_sample,
                end_sample_exclusive=window.end_sample_exclusive,
                outcome=exec_res.asr_outcome,
                timestamp_status=ts_status,
            )
            return self._reconcile_and_publish(rt, window, hyp)
        finally:
            rt.running_window_id = None

    def _reconcile_and_publish(
        self,
        rt: _ScopeRuntime,
        window: DecodeWindow,
        hyp: PartialHypothesis,
    ) -> ProvisionalRecognitionRevision:
        raw_tokens = hyp.raw_transcript.strip().split()[: self.config.max_tokens_per_window]
        norm_tokens = [normalize_matching_key(t) for t in raw_tokens]

        gap_detected = (
            rt.last_accepted_end is not None
            and window.start_sample > rt.last_accepted_end
        )
        if gap_detected or not rt.token_support:
            # First window or discontinuity gap: reset support
            rt.token_support = [
                (raw_t, norm_t, 1, window.window_id)
                for raw_t, norm_t in zip(raw_tokens, norm_tokens)
            ]
        else:
            # Find longest aligned overlap between previous token_support suffix and current norm_tokens prefix
            prev_norms = [item[1] for item in rt.token_support]
            best_overlap = 0
            max_k = min(len(prev_norms), len(norm_tokens))
            for k in range(max_k, 0, -1):
                if prev_norms[-k:] == norm_tokens[:k]:
                    best_overlap = k
                    break

            if best_overlap > 0:
                # Re-confirm overlapping tokens only if window actually advanced
                advanced = window.end_sample_exclusive > (rt.last_accepted_end or 0)
                prefix_keep = rt.token_support[:-best_overlap] if best_overlap < len(rt.token_support) else []
                reconfirmed = []
                for idx in range(best_overlap):
                    old_raw, old_norm, old_cnt, _ = rt.token_support[len(rt.token_support) - best_overlap + idx]
                    new_cnt = old_cnt + (1 if advanced else 0)
                    reconfirmed.append((raw_tokens[idx], old_norm, new_cnt, window.window_id))
                new_tail = [
                    (raw_t, norm_t, 1, window.window_id)
                    for raw_t, norm_t in zip(raw_tokens[best_overlap:], norm_tokens[best_overlap:])
                ]
                rt.token_support = (prefix_keep + reconfirmed + new_tail)[-self.config.max_retained_tokens :]
            else:
                # Overlap alignment failed or text contradicted -> shrink/reset stability
                rt.token_support = [
                    (raw_t, norm_t, 1, window.window_id)
                    for raw_t, norm_t in zip(raw_tokens, norm_tokens)
                ]

        derived_text = " ".join(item[0] for item in rt.token_support)
        provenance = tuple(
            TokenProvenance(
                token=item[0],
                normalized=item[1],
                window_id=item[3],
                abs_start_sample=None,
                abs_end_sample_exclusive=None,
            )
            for item in rt.token_support
        )

        # Compute revocable stable prefix: contiguous prefix with obs_count >= stability_observations,
        # excluding the last token if it sits near the right boundary guard.
        guard_cut = max(0, len(rt.token_support) - 1) if len(rt.token_support) > 1 else 0
        stable_tokens: list[str] = []
        min_obs = 0
        for idx in range(guard_cut):
            raw_t, _, cnt, _ = rt.token_support[idx]
            if cnt >= self.config.stability_observations:
                stable_tokens.append(raw_t)
                min_obs = cnt if min_obs == 0 else min(min_obs, cnt)
            else:
                break

        stable_prefix_str = " ".join(stable_tokens) if stable_tokens else None
        prefix_span = (
            UnicodeSpan(start=0, end_exclusive=len(stable_prefix_str), representation="RAW")
            if stable_prefix_str is not None
            else None
        )

        rt.revision_seq += 1
        rev = rt.revision_seq
        rt.last_accepted_start = window.start_sample
        rt.last_accepted_end = window.end_sample_exclusive
        rt.last_hypothesis = hyp
        rt.reconciled = ReconciledView(
            version=rev,
            derived_text=derived_text,
            token_provenance=provenance,
            covered_start_sample=rt.scope.start_sample,
            covered_end_sample_exclusive=window.end_sample_exclusive,
            has_gap=gap_detected,
            discontinuity_reason="scheduler_gap" if gap_detected else None,
        )

        now_ns = self.clock.monotonic_ns()
        rt.stable_prefix = StablePrefixEvidence(
            revision=rev,
            stable_prefix=stable_prefix_str,
            prefix_span=prefix_span,
            independent_observations=min_obs,
            boundary_guard_samples=self.config.boundary_guard_samples,
            valid=(stable_prefix_str is not None and not gap_detected),
            expiry_ns=now_ns + self.config.hint_ttl_ns,
        )

        entities = ()
        if self.pinned_lexicon is not None and self.pinned_lexicon.available:
            res_rep = resolve_automotive_entities(
                utterance_id=f"partial-{rt.scope.speech_ref}",
                raw_transcript=hyp.raw_transcript,
                pinned_lexicon=self.pinned_lexicon,
                projection_policy="candidate_only",
                final_revision=rev,
            )
            entities = res_rep.candidates

        status = ASRStatus.STABLE_PREFIX if stable_prefix_str is not None else ASRStatus.PARTIAL
        pub = ProvisionalRecognitionRevision(
            scope=rt.scope,
            revision=rev,
            status=status,
            window_id=window.window_id,
            window_range=(window.start_sample, window.end_sample_exclusive),
            raw_transcript=hyp.raw_transcript,
            derived_view=derived_text,
            stable_prefix=stable_prefix_str,
            prefix_span=prefix_span,
            independent_observations=min_obs,
            entities=entities,
            canonical_transcript=None,
            timestamp_status=hyp.timestamp_status,
            actionable=False,
            business_action_eligible=False,
        )
        rt.revisions.append(pub)

        if not gap_detected:
            rt.latest_hint = SemanticEndpointHint(
                hint_id=f"hint-{rt.scope.speech_ref[:16]}-{rev}",
                speech_ref=rt.scope.speech_ref,
                revision=rev,
                covered_end_sample_exclusive=window.end_sample_exclusive,
                observed_monotonic_ns=now_ns,
                valid_until_monotonic_ns=now_ns + self.config.hint_ttl_ns,
                clock_domain=self.clock.clock_domain,
                continuation_cue=_infer_continuation_cue(derived_text),
            )
        else:
            rt.latest_hint = None

        return pub

    def get_semantic_hint(self, speech_ref: str) -> SemanticEndpointHint | None:
        """Return latest valid non-expired SemanticEndpointHint, or None on stale/sealed/gap."""
        rt = self._scopes.get(speech_ref)
        if rt is None or rt.state != PartialLaneState.CONFIRMED_ACTIVE or rt.latest_hint is None:
            return None
        now_ns = self.clock.monotonic_ns()
        hint = rt.latest_hint
        if hint.clock_domain != self.clock.clock_domain or now_ns > hint.valid_until_monotonic_ns:
            rt.latest_hint = None
            return None
        return hint

    def seal_for_finalization(
        self,
        speech_ref: str,
        *,
        utterance: Utterance,
        turn_ref: TurnRef,
        final_claim_id: str,
    ) -> FinalizationBinding:
        """
        Atomically seal the partial lane on authoritative F1-A UTTERANCE_FINALIZED.
        Invalidates pending partial requests and semantic hints, returning FinalizationBinding.
        """
        rt = self._scopes.get(speech_ref)
        if rt is None:
            raise RuntimeError(f"Unknown speech_ref {speech_ref!r}")
        if rt.state in {PartialLaneState.TERMINAL, PartialLaneState.ABORTED}:
            raise RuntimeError(f"Cannot seal scope {speech_ref!r} in state {rt.state.value}")

        rt.state = PartialLaneState.SEALED_FINALIZING
        rt.pending_window_id = None
        rt.latest_hint = None
        rt.cancellation_scope.request_cancel("finalization_seal")

        covered_end = rt.last_accepted_end or rt.scope.start_sample
        shortened = utterance.end_sample_exclusive < covered_end
        binding = FinalizationBinding(
            scope=rt.scope,
            utterance_id=utterance.utterance_id,
            turn_ref=turn_ref,
            final_start_sample=utterance.start_sample,
            final_end_sample_exclusive=utterance.end_sample_exclusive,
            sealed_partial_high_watermark=rt.revision_seq,
            final_claim_id=final_claim_id,
            coverage_shortened=shortened,
        )
        rt.final_binding = binding
        return binding

    def mark_terminal(self, speech_ref: str) -> None:
        """Release partial audio buffers and mark scope TERMINAL."""
        rt = self._scopes.pop(speech_ref, None)
        if rt is not None:
            rt.state = PartialLaneState.TERMINAL
            rt.chunks.clear()
            rt.latest_hint = None
        self._terminated_scopes.add(speech_ref)

    def abort_scope(self, speech_ref: str, *, reason: str = "aborted") -> None:
        """Abort and seal partial lane on session close or cancellation."""
        rt = self._scopes.pop(speech_ref, None)
        if rt is not None:
            rt.state = PartialLaneState.ABORTED
            rt.cancellation_scope.request_cancel(reason)
            rt.chunks.clear()
            rt.latest_hint = None
        self._terminated_scopes.add(speech_ref)
