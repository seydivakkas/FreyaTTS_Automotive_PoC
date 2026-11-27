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

import math
from dataclasses import dataclass
from typing import Any, Sequence

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability

SPEAKER_EVAL_REVISION = "f5c-speaker-eval-v1"
PITCH_EVAL_REVISION = "f5c-pitch-eval-v1"


@dataclass(frozen=True, slots=True)
class SpeakerReferenceManifest:
    """Approved lab-only speaker reference metadata (never biometric auth or customer PCM)."""

    reference_id: str
    voice_profile: str
    seed: int
    corpus_hash: str
    consent_and_license_verified: bool
    lab_scope_only: bool
    source_sample_rate_hz: int
    source_channels: int
    preprocessing_revision: str
    is_self_consistency_reference: bool = True

    def validate(self) -> ErrorInfo | None:
        if not self.consent_and_license_verified:
            return ErrorInfo(
                code="REFERENCE_CONSENT_UNVERIFIED",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Speaker reference lacks verified consent/license",
            )
        if not self.lab_scope_only:
            return ErrorInfo(
                code="REFERENCE_NON_LAB_SCOPE_REJECTED",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Speaker reference must be restricted to enrolled lab scope",
            )
        if not self.corpus_hash or self.source_sample_rate_hz <= 0 or self.source_channels != 1:
            return ErrorInfo(
                code="INVALID_REFERENCE_MANIFEST",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Speaker reference manifest has invalid format or missing hash",
            )
        return None


@dataclass(frozen=True, slots=True)
class SpeakerAssessment:
    """Isolated CPU-safe speaker similarity metadata (never biometric identity authentication)."""

    candidate_id: str
    reference_id: str | None
    preprocessing_revision: str
    embedding_dim: int | None
    embedding_norm: float | None
    cosine_similarity: float | None
    calibrated_threshold_ref: str | None
    outcome: str  # "NOT_RUN" | "EVALUATED" | "INSUFFICIENT_DURATION" | "INVALID_EMBEDDING" | "REJECTED_MANIFEST"
    evidence_class: str  # "SELF_CONSISTENCY_ONLY" | "CALIBRATED_LAB" | "STRUCTURAL_FAKE_ONLY"
    identity_verified: bool = False  # Always False: ECAPA is not biometric authentication
    reason: str = ""


@dataclass(frozen=True, slots=True)
class PitchAssessment:
    """Isolated CPU-safe F0/prosody metadata (null for unvoiced/silent/unavailable, never 0 Hz)."""

    source_rate_hz: int
    extractor_revision: str
    window_ms: float
    hop_ms: float
    voiced_fraction: float | None
    f0_median_hz: float | None
    f0_p10_hz: float | None
    f0_p90_hz: float | None
    semitone_span: float | None
    outcome: str  # "NOT_RUN" | "EVALUATED" | "UNVOICED_OR_SILENT" | "INSUFFICIENT_DURATION"
    missing_reason: str | None = None


class SpeakerIntelligenceEvaluator:
    """
    Isolated CPU-safe speaker similarity and F0/pitch assessment seam for F5-C lab use.

    Guarantees:
    - Never downloads models, enrolls customer voices, or performs biometric authentication.
    - Never mutates raw AudioChunk or runs in the live critical synthesis path.
    - Returns None (never 0.0) for unvoiced/silent/insufficient-duration pitch or invalid embeddings.
    """

    def __init__(
        self,
        *,
        min_duration_sec: float = 0.25,
        fmin_hz: float = 65.0,
        fmax_hz: float = 500.0,
        window_ms: float = 40.0,
        hop_ms: float = 10.0,
    ) -> None:
        self.min_duration_sec = min_duration_sec
        self.fmin_hz = fmin_hz
        self.fmax_hz = fmax_hz
        self.window_ms = window_ms
        self.hop_ms = hop_ms

    @staticmethod
    def cosine_similarity(emb_a: Sequence[float], emb_b: Sequence[float]) -> tuple[float | None, float | None, int | None]:
        """Compute bounded cosine similarity in [-1, 1]; returns (sim, norm_a, dim) or (None, ...)."""
        import numpy as np

        a = np.asarray(emb_a, dtype=np.float64)
        b = np.asarray(emb_b, dtype=np.float64)
        if a.ndim != 1 or b.ndim != 1 or a.size == 0 or a.shape != b.shape:
            return None, None, None
        if not (np.isfinite(a).all() and np.isfinite(b).all()):
            return None, None, int(a.size)
        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a <= 1e-12 or norm_b <= 1e-12:
            return None, 0.0, int(a.size)
        cos = float(np.dot(a, b) / (norm_a * norm_b))
        cos = max(-1.0, min(1.0, cos))
        return cos, norm_a, int(a.size)

    def assess_speaker_embeddings(
        self,
        *,
        candidate_id: str,
        manifest: SpeakerReferenceManifest,
        candidate_embedding: Sequence[float] | None,
        reference_embedding: Sequence[float] | None,
        duration_sec: float,
        evidence_class: str = "STRUCTURAL_FAKE_ONLY",
        calibrated_threshold_ref: str | None = None,
    ) -> SpeakerAssessment:
        err = manifest.validate()
        if err is not None:
            return SpeakerAssessment(
                candidate_id=candidate_id,
                reference_id=manifest.reference_id,
                preprocessing_revision=manifest.preprocessing_revision,
                embedding_dim=None,
                embedding_norm=None,
                cosine_similarity=None,
                calibrated_threshold_ref=None,
                outcome="REJECTED_MANIFEST",
                evidence_class=evidence_class,
                identity_verified=False,
                reason=err.code,
            )
        if duration_sec < self.min_duration_sec:
            return SpeakerAssessment(
                candidate_id=candidate_id,
                reference_id=manifest.reference_id,
                preprocessing_revision=manifest.preprocessing_revision,
                embedding_dim=None,
                embedding_norm=None,
                cosine_similarity=None,
                calibrated_threshold_ref=calibrated_threshold_ref,
                outcome="INSUFFICIENT_DURATION",
                evidence_class=evidence_class,
                identity_verified=False,
                reason="DURATION_BELOW_MIN_EVAL_SEC",
            )
        if candidate_embedding is None or reference_embedding is None:
            return SpeakerAssessment(
                candidate_id=candidate_id,
                reference_id=manifest.reference_id,
                preprocessing_revision=manifest.preprocessing_revision,
                embedding_dim=None,
                embedding_norm=None,
                cosine_similarity=None,
                calibrated_threshold_ref=calibrated_threshold_ref,
                outcome="NOT_RUN",
                evidence_class=evidence_class,
                identity_verified=False,
                reason="EMBEDDING_UNAVAILABLE",
            )

        cos, norm_a, dim = self.cosine_similarity(candidate_embedding, reference_embedding)
        if cos is None:
            return SpeakerAssessment(
                candidate_id=candidate_id,
                reference_id=manifest.reference_id,
                preprocessing_revision=manifest.preprocessing_revision,
                embedding_dim=dim,
                embedding_norm=norm_a,
                cosine_similarity=None,
                calibrated_threshold_ref=calibrated_threshold_ref,
                outcome="INVALID_EMBEDDING",
                evidence_class=evidence_class,
                identity_verified=False,
                reason="NONFINITE_OR_ZERO_NORM_OR_DIM_MISMATCH",
            )

        return SpeakerAssessment(
            candidate_id=candidate_id,
            reference_id=manifest.reference_id,
            preprocessing_revision=manifest.preprocessing_revision,
            embedding_dim=dim,
            embedding_norm=norm_a,
            cosine_similarity=cos,
            calibrated_threshold_ref=calibrated_threshold_ref,
            outcome="EVALUATED",
            evidence_class=evidence_class,
            identity_verified=False,
            reason="COSINE_COMPUTED",
        )

    def assess_pitch_cpu(
        self,
        *,
        waveform_f32: Any,
        sample_rate_hz: int,
    ) -> PitchAssessment:
        """Pure-NumPy CPU-safe autocorrelation F0 seam (null for unvoiced/short, never 0 Hz)."""
        import numpy as np

        if sample_rate_hz <= 0:
            return PitchAssessment(
                source_rate_hz=sample_rate_hz,
                extractor_revision=PITCH_EVAL_REVISION,
                window_ms=self.window_ms,
                hop_ms=self.hop_ms,
                voiced_fraction=None,
                f0_median_hz=None,
                f0_p10_hz=None,
                f0_p90_hz=None,
                semitone_span=None,
                outcome="NOT_RUN",
                missing_reason="INVALID_SAMPLE_RATE",
            )

        arr = np.asarray(waveform_f32, dtype=np.float32)
        if arr.ndim != 1 or arr.size == 0 or not np.isfinite(arr).all():
            return PitchAssessment(
                source_rate_hz=sample_rate_hz,
                extractor_revision=PITCH_EVAL_REVISION,
                window_ms=self.window_ms,
                hop_ms=self.hop_ms,
                voiced_fraction=None,
                f0_median_hz=None,
                f0_p10_hz=None,
                f0_p90_hz=None,
                semitone_span=None,
                outcome="NOT_RUN",
                missing_reason="INVALID_OR_NONFINITE_WAVEFORM",
            )

        dur_sec = float(arr.size) / float(sample_rate_hz)
        win_len = max(16, int(round(sample_rate_hz * (self.window_ms / 1000.0))))
        hop_len = max(8, int(round(sample_rate_hz * (self.hop_ms / 1000.0))))
        if dur_sec < self.min_duration_sec or arr.size < win_len:
            return PitchAssessment(
                source_rate_hz=sample_rate_hz,
                extractor_revision=PITCH_EVAL_REVISION,
                window_ms=self.window_ms,
                hop_ms=self.hop_ms,
                voiced_fraction=None,
                f0_median_hz=None,
                f0_p10_hz=None,
                f0_p90_hz=None,
                semitone_span=None,
                outcome="INSUFFICIENT_DURATION",
                missing_reason="DURATION_BELOW_WINDOW_OR_MIN_SEC",
            )

        min_lag = max(1, int(sample_rate_hz / self.fmax_hz))
        max_lag = min(win_len - 1, int(sample_rate_hz / self.fmin_hz))
        if max_lag <= min_lag:
            return PitchAssessment(
                source_rate_hz=sample_rate_hz,
                extractor_revision=PITCH_EVAL_REVISION,
                window_ms=self.window_ms,
                hop_ms=self.hop_ms,
                voiced_fraction=None,
                f0_median_hz=None,
                f0_p10_hz=None,
                f0_p90_hz=None,
                semitone_span=None,
                outcome="NOT_RUN",
                missing_reason="INVALID_LAG_BOUNDS",
            )

        voiced_f0: list[float] = []
        total_frames = 0
        for start in range(0, arr.size - win_len + 1, hop_len):
            total_frames += 1
            frame = arr[start : start + win_len].astype(np.float64)
            frame = frame - float(np.mean(frame))
            energy = float(np.dot(frame, frame))
            if energy <= 1e-8:
                continue
            corr = np.correlate(frame, frame, mode="full")[win_len - 1 :]
            if corr[0] <= 1e-12:
                continue
            segment = corr[min_lag : max_lag + 1]
            best_rel = int(np.argmax(segment))
            peak_ratio = float(segment[best_rel]) / float(corr[0])
            if peak_ratio >= 0.35:
                lag = min_lag + best_rel
                f0 = float(sample_rate_hz) / float(lag)
                if self.fmin_hz <= f0 <= self.fmax_hz:
                    voiced_f0.append(f0)

        if total_frames == 0 or not voiced_f0:
            return PitchAssessment(
                source_rate_hz=sample_rate_hz,
                extractor_revision=PITCH_EVAL_REVISION,
                window_ms=self.window_ms,
                hop_ms=self.hop_ms,
                voiced_fraction=0.0 if total_frames > 0 else None,
                f0_median_hz=None,
                f0_p10_hz=None,
                f0_p90_hz=None,
                semitone_span=None,
                outcome="UNVOICED_OR_SILENT",
                missing_reason="NO_VOICED_FRAMES_DETECTED",
            )

        f0_arr = np.asarray(voiced_f0, dtype=np.float64)
        p10 = float(np.percentile(f0_arr, 10))
        p50 = float(np.percentile(f0_arr, 50))
        p90 = float(np.percentile(f0_arr, 90))
        span = (12.0 * math.log2(p90 / p10)) if (p10 > 0.0 and p90 > 0.0) else None
        return PitchAssessment(
            source_rate_hz=sample_rate_hz,
            extractor_revision=PITCH_EVAL_REVISION,
            window_ms=self.window_ms,
            hop_ms=self.hop_ms,
            voiced_fraction=float(len(voiced_f0)) / float(total_frames),
            f0_median_hz=p50,
            f0_p10_hz=p10,
            f0_p90_hz=p90,
            semitone_span=span,
            outcome="EVALUATED",
            missing_reason=None,
        )


__all__ = [
    "PITCH_EVAL_REVISION",
    "PitchAssessment",
    "SPEAKER_EVAL_REVISION",
    "SpeakerAssessment",
    "SpeakerIntelligenceEvaluator",
    "SpeakerReferenceManifest",
]
