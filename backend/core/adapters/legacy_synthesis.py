"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import numpy as np

from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, GenerationRef
from backend.core.contracts.synthesis import (
    AudioChunk,
    CacheStatus,
    ChunkPlan,
    PlanValidationStatus,
    QualityStatus,
    SynthesisPlan,
)
from backend.core.contracts.validation import ConversionResult


def synthesis_plan_from_legacy(
    *,
    session_id: str,
    turn_id: int,
    generation_id: int,
    plan_id: str,
    response_id: str,
    source_text: str,
    normalized_text: str,
    chunks_text: list[tuple[str, float]],
    seed: int | None,
    voice_profile: str = "leyla",
    source_ref: str = "backend.text",
) -> ConversionResult[SynthesisPlan]:
    missing = ("model_revision", "lexicon_revision", "capability_revision")
    chunk_plans = tuple(
        ChunkPlan(
            chunk_id=f"{plan_id}-c{idx}",
            chunk_index=idx,
            model_text=txt,
            post_pause_ms=int(round(pause_sec * 1000)) if pause_sec > 0 else 0,
        )
        for idx, (txt, pause_sec) in enumerate(chunks_text)
    )
    plan = SynthesisPlan(
        schema_version=CONTRACT_SCHEMA_VERSION,
        generation_ref=GenerationRef(session_id=session_id, turn_id=turn_id, generation_id=generation_id),
        plan_id=plan_id,
        plan_revision=0,
        response_id=response_id,
        source_text=source_text,
        normalized_text=normalized_text,
        language="tr",
        voice_profile=voice_profile,
        seed=seed,
        chunks=chunk_plans,
        normalization_passes=None,
        validation_status=PlanValidationStatus.UNKNOWN,
    )
    return ConversionResult(plan, missing, warnings=("Legacy normalization pass count unverified",), lossy=True, source_ref=source_ref)


def audio_chunk_from_legacy_waveform(
    *,
    generation_ref: GenerationRef,
    plan_id: str,
    plan_revision: int,
    chunk_id: str,
    chunk_index: int,
    waveform_48k: np.ndarray,
    seed: int | None,
    voice_profile: str = "leyla",
    cache_status: CacheStatus = CacheStatus.UNKNOWN,
    quality_status: QualityStatus = QualityStatus.UNKNOWN,
    source_ref: str = "backend.models.synth",
) -> ConversionResult[AudioChunk]:
    arr = np.ascontiguousarray(waveform_48k, dtype=np.float32)
    if arr.ndim != 1 or arr.shape[0] == 0:
        return ConversionResult(None, error="Waveform must be non-empty 1D float32", source_ref=source_ref)
    if not np.isfinite(arr).all():
        return ConversionResult(None, error="Waveform contains non-finite samples", source_ref=source_ref)
    payload = arr.astype("<f4").tobytes()
    chunk = AudioChunk(
        generation_ref=generation_ref,
        plan_id=plan_id,
        plan_revision=plan_revision,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        format=AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE),
        sample_count=int(arr.shape[0]),
        payload=payload,
        voice_profile=voice_profile,
        seed=seed,
        cache_status=cache_status,
        quality_status=quality_status,
    )
    return ConversionResult(chunk, ("model_revision",), warnings=("Legacy output may include 10ms fade DSP",), lossy=True, source_ref=source_ref)
