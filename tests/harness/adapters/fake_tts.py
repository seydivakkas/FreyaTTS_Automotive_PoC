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

from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, GenerationRef
from backend.core.contracts.synthesis import (
    AudioChunk,
    CacheStatus,
    ChunkPlan,
    PlanValidationStatus,
    QualityStatus,
    SynthesisPlan,
    validate_plan_chunk_consistency,
)
from backend.core.runtime.cancellation import CancellationScope
from backend.observability.evidence import EvidenceKind
from tests.harness.synthetic_audio import AnalyticSignalKind, SyntheticAudioGenerator


@dataclass(frozen=True, slots=True)
class TTSGenerationOutcome:
    accepted_chunks: tuple[AudioChunk, ...]
    rejected_stale_chunks: int
    logical_cancelled: bool
    physical_completed: bool
    is_production_fallback: bool = False
    source_class: EvidenceKind = EvidenceKind.SYNTHETIC_FIXTURE


class FakeTTSAdapter:
    """Mock TTS emitting deterministic synthetic AudioChunks (never a production fallback)."""

    source_class: EvidenceKind = EvidenceKind.SYNTHETIC_FIXTURE
    is_production_fallback: bool = False

    def __init__(self) -> None:
        self._audio = SyntheticAudioGenerator()
        self.invocation_count = 0

    def build_plan(
        self,
        *,
        generation_ref: GenerationRef,
        plan_id: str,
        response_id: str,
        texts: tuple[str, ...],
        voice_profile: str = "leyla-baseline-9",
        seed: int = 9,
        plan_revision: int = 1,
    ) -> SynthesisPlan:
        chunks = tuple(
            ChunkPlan(chunk_id=f"chk-{idx}", chunk_index=idx, model_text=txt)
            for idx, txt in enumerate(texts)
        )
        full_text = " ".join(texts)
        return SynthesisPlan(
            schema_version=CONTRACT_SCHEMA_VERSION,
            generation_ref=generation_ref,
            plan_id=plan_id,
            plan_revision=plan_revision,
            response_id=response_id,
            source_text=full_text,
            normalized_text=full_text,
            language="tr",
            voice_profile=voice_profile,
            seed=seed,
            chunks=chunks,
            validation_status=PlanValidationStatus.VALID,
        )

    def synthesize_chunk(
        self,
        plan: SynthesisPlan,
        chunk_index: int,
        *,
        sample_rate_hz: int = 48000,
        sample_count: int = 960,
        override_chunk_id: str | None = None,
    ) -> AudioChunk:
        self.invocation_count += 1
        chunk_plan = plan.chunks[chunk_index]
        seg = self._audio.generate(
            AnalyticSignalKind.SINE,
            sample_rate_hz=sample_rate_hz,
            sample_count=sample_count,
            encoding=AudioEncoding.FLOAT32_LE,
            seed=plan.seed or 9,
        )
        chunk = AudioChunk(
            generation_ref=plan.generation_ref,
            plan_id=plan.plan_id,
            plan_revision=plan.plan_revision,
            chunk_id=override_chunk_id or chunk_plan.chunk_id,
            chunk_index=chunk_index,
            format=AudioFormat(sample_rate_hz, 1, AudioEncoding.FLOAT32_LE),
            sample_count=seg.sample_count,
            payload=seg.payload,
            voice_profile=plan.voice_profile,
            seed=plan.seed,
            model_revision="synthetic-tts-fixture",
            solver="euler32-mock",
            ode_steps=32,
            cache_status=CacheStatus.MISS,
            quality_status=QualityStatus.PASS,
        )
        validate_plan_chunk_consistency(plan, chunk)
        return chunk

    async def synthesize_with_delay(
        self,
        plan: SynthesisPlan,
        scope: CancellationScope,
        *,
        ready_gate: asyncio.Event | None = None,
    ) -> TTSGenerationOutcome:
        accepted: list[AudioChunk] = []
        rejected = 0
        if ready_gate is not None:
            await ready_gate.wait()
        for idx in range(len(plan.chunks)):
            if scope.is_cancel_requested:
                rejected += 1
                continue
            accepted.append(self.synthesize_chunk(plan, idx))
        return TTSGenerationOutcome(
            accepted_chunks=tuple(accepted),
            rejected_stale_chunks=rejected,
            logical_cancelled=scope.is_cancel_requested,
            physical_completed=True,
        )
