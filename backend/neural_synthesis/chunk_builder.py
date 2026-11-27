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

from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import MetricSample
from backend.core.contracts.synthesis import (
    AudioChunk,
    CacheStatus,
    ChunkPlan,
    QualityStatus,
    SynthesisPlan,
    validate_plan_chunk_consistency,
)
from backend.neural_synthesis.config_adapter import BASELINE_SAMPLE_RATE_HZ, PinnedSynthesisSnapshot
from backend.neural_synthesis.solver_adapter import SolverProfile

RAW_AUDIO_FORMAT = AudioFormat(BASELINE_SAMPLE_RATE_HZ, 1, AudioEncoding.FLOAT32_LE)


def build_audio_chunk(
    *,
    plan: SynthesisPlan,
    chunk_plan: ChunkPlan,
    snapshot: PinnedSynthesisSnapshot,
    solver_profile: SolverProfile,
    sample_count: int,
    payload: bytes,
    cache_status: CacheStatus,
    quality_status: QualityStatus,
    applied_speed: float | None = None,
    metrics: tuple[MetricSample, ...] = (),
) -> AudioChunk:
    """
    Build an immutable M01 AudioChunk for F6 consumption and verify plan-chunk consistency.

    - Output format is strictly 48 kHz mono FLOAT32_LE.
    - `post_pause_ms` and `requested_speed` pass through unchanged; F6 owns rendering silence/speed.
    - `quality_status` reflects structural/guard state (UNKNOWN/PENDING/FAIL, never unmeasured PASS).
    """
    chunk = AudioChunk(
        generation_ref=plan.generation_ref,
        plan_id=plan.plan_id,
        plan_revision=plan.plan_revision,
        chunk_id=chunk_plan.chunk_id,
        chunk_index=chunk_plan.chunk_index,
        format=RAW_AUDIO_FORMAT,
        sample_count=sample_count,
        payload=payload,
        voice_profile=snapshot.voice_profile.profile_id,
        seed=snapshot.seed,
        model_revision=snapshot.model_descriptor.model_revision,
        solver=solver_profile.solver_name,
        ode_steps=solver_profile.steps,
        cache_status=cache_status,
        quality_status=quality_status,
        post_pause_ms=chunk_plan.post_pause_ms,
        requested_speed=chunk_plan.requested_speed,
        applied_speed=applied_speed,
        metrics=metrics,
    )
    validate_plan_chunk_consistency(plan, chunk)
    return chunk


__all__ = [
    "RAW_AUDIO_FORMAT",
    "build_audio_chunk",
]
