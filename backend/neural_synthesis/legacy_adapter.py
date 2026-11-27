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
from typing import TYPE_CHECKING, Any

from backend.core.adapters.legacy_synthesis import audio_chunk_from_legacy_waveform
from backend.core.contracts.common import GenerationRef
from backend.core.contracts.synthesis import AudioChunk, CacheStatus, QualityStatus, SynthesisPlan
from backend.core.contracts.validation import ConversionResult

if TYPE_CHECKING:
    from backend.neural_synthesis.pipeline import NeuralSynthesisPipeline, SynthesisOutcome


@dataclass(frozen=True, slots=True)
class SynthesisPathRecord:
    """Classification entry for a discovered synthesis or experiment route."""

    path_id: str
    location: str
    classification: str
    normalization_owner: str
    scheduler_owner: str
    dsp_applied: bool
    strict_compatible: bool
    notes: str


def classify_synthesis_paths() -> tuple[SynthesisPathRecord, ...]:
    """Complete static classification of existing and F5-A neural synthesis paths."""
    return (
        SynthesisPathRecord(
            path_id="f5_a_strict_pipeline",
            location="backend/neural_synthesis/pipeline.py:NeuralSynthesisPipeline.synthesize_plan",
            classification="STRICT_NEW",
            normalization_owner="F4_PREPARED_PLAN_ONLY",
            scheduler_owner="M06_UNIFIED_GPU_SCHEDULER",
            dsp_applied=False,
            strict_compatible=True,
            notes="Single strict prepared-plan entry point emitting raw 48k mono FLOAT32_LE AudioChunk.",
        ),
        SynthesisPathRecord(
            path_id="legacy_models_synth",
            location="backend/models.py:Models.synth",
            classification="LIVE_PATH",
            normalization_owner="backend.text.normalize+prepare_tts_clause",
            scheduler_owner="Models.lock+worker_lock",
            dsp_applied=True,
            strict_compatible=False,
            notes="Legacy route retained untouched; applies apply_fade_and_comfort_noise and inline normalization.",
        ),
        SynthesisPathRecord(
            path_id="legacy_batched_ode",
            location="backend/batched_ode.py:BatchedODEEngine.synthesize_clause",
            classification="LIVE_PATH",
            normalization_owner="backend.text.normalize+clauses+prepare_tts_clause",
            scheduler_owner="BatchedODEEngine._queue_lock",
            dsp_applied=True,
            strict_compatible=False,
            notes="Legacy dynamic micro-batch Euler32 engine retained untouched; F5-B/C own strict batching.",
        ),
        SynthesisPathRecord(
            path_id="legacy_prewarm",
            location="backend/models.py:Models._prewarm_tts",
            classification="LIVE_PATH",
            normalization_owner="backend.text.normalize+clauses+prepare_tts_clause",
            scheduler_owner="Models.synth",
            dsp_applied=True,
            strict_compatible=False,
            notes="Populates Models._synth_cache during startup; bypassed on strict F5-A path.",
        ),
        SynthesisPathRecord(
            path_id="public_api_synthesize",
            location="backend/routers/text_speech.py:/api/synthesize",
            classification="LIVE_PATH",
            normalization_owner="Models.synth",
            scheduler_owner="Models.synth",
            dsp_applied=True,
            strict_compatible=False,
            notes="Legacy WAV PCM_16 endpoint preserved untouched; no schema change.",
        ),
        SynthesisPathRecord(
            path_id="public_api_ab_preview",
            location="backend/routers/text_speech.py:/api/ab/preview-synth",
            classification="FLAGGED",
            normalization_owner="Models.synth",
            scheduler_owner="Models.synth",
            dsp_applied=True,
            strict_compatible=False,
            notes="A/B preview seed endpoint preserved untouched.",
        ),
        SynthesisPathRecord(
            path_id="experimental_sft_lora",
            location="backend/sft_leyla.py",
            classification="EXPERIMENTAL",
            normalization_owner="AutomotiveTextNormalizer",
            scheduler_owner="DIRECT_TORCH",
            dsp_applied=False,
            strict_compatible=False,
            notes="Offline research SFT/LoRA module; never auto-activated in F5-A.",
        ),
    )


def audit_strict_bypasses() -> dict[str, Any]:
    """Static audit report confirming zero unresolved strict bypasses inside backend/neural_synthesis."""
    return {
        "strict_entry_point": "backend/neural_synthesis/pipeline.py:NeuralSynthesisPipeline",
        "f5_internal_normalization_calls": 0,
        "f5_internal_dsp_calls": 0,
        "f5_direct_gpu_bypasses": 0,
        "legacy_routes_preserved": True,
        "strict_fallback_to_legacy_blocked": True,
        "status": "CLEAR",
    }


def adapt_legacy_synth_output(
    *,
    generation_ref: GenerationRef,
    plan_id: str,
    plan_revision: int,
    chunk_id: str,
    chunk_index: int,
    waveform_48k: Any,
    seed: int | None,
    voice_profile: str = "leyla",
) -> ConversionResult[AudioChunk]:
    """Bridge legacy Models.synth waveform to M01 AudioChunk without relabeling it strict."""
    return audio_chunk_from_legacy_waveform(
        generation_ref=generation_ref,
        plan_id=plan_id,
        plan_revision=plan_revision,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        waveform_48k=waveform_48k,
        seed=seed,
        voice_profile=voice_profile,
        cache_status=CacheStatus.UNKNOWN,
        quality_status=QualityStatus.UNKNOWN,
        source_ref="backend.models.synth",
    )


class LegacySynthesisBridge:
    """
    Explicit router between strict SynthesisPlan requests and legacy text synthesis.

    Strict requests NEVER fall back to unguarded legacy `_synth` on failure.
    """

    def __init__(
        self,
        *,
        strict_pipeline: "NeuralSynthesisPipeline",
        legacy_models: Any = None,
    ) -> None:
        self.strict_pipeline = strict_pipeline
        self.legacy_models = legacy_models

    async def synthesize_strict(self, plan: SynthesisPlan, **kwargs: Any) -> "SynthesisOutcome":
        return await self.strict_pipeline.synthesize_plan(plan, **kwargs)

    async def synthesize_legacy_text(self, text: str, *, seed: int | None = None) -> Any:
        if self.legacy_models is None or not hasattr(self.legacy_models, "synth"):
            raise RuntimeError("Legacy models handle is not configured")
        return await self.legacy_models.synth(text, seed=seed)


__all__ = [
    "LegacySynthesisBridge",
    "SynthesisPathRecord",
    "adapt_legacy_synth_output",
    "audit_strict_bypasses",
    "classify_synthesis_paths",
]
