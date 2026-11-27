"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, ContractVersion, GenerationRef, MetricSample
from backend.core.contracts.validation import freeze_value, require_finite, require_safe_id, require_strict_int


class CacheStatus(StrEnum):
    HIT = "HIT"
    MISS = "MISS"
    BYPASS = "BYPASS"
    UNKNOWN = "UNKNOWN"


class QualityStatus(StrEnum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class PlanValidationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ChunkPlan:
    chunk_id: str
    chunk_index: int
    model_text: str
    source_span: tuple[int, int] | None = None
    protected_entity_refs: tuple[str, ...] = ()
    requested_speed: float | None = None
    requested_emphasis: tuple[str, ...] = ()
    post_pause_ms: int | None = None
    requested_controls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_safe_id(self.chunk_id, "chunk_id")
        require_strict_int(self.chunk_index, "chunk_index", minimum=0)
        if not isinstance(self.model_text, str) or not self.model_text.strip():
            raise ValueError("model_text must be non-empty for speech chunk")
        if self.source_span is not None:
            if len(self.source_span) != 2:
                raise ValueError("source_span must be (start, end)")
            s, e = self.source_span
            require_strict_int(s, "source_span.start", minimum=0)
            require_strict_int(e, "source_span.end", minimum=s)
        if self.requested_speed is not None:
            require_finite(self.requested_speed, "requested_speed", minimum=0.25, maximum=4.0)
        if self.post_pause_ms is not None:
            require_strict_int(self.post_pause_ms, "post_pause_ms", minimum=0, maximum=10000)
        object.__setattr__(self, "protected_entity_refs", freeze_value(tuple(self.protected_entity_refs)))
        object.__setattr__(self, "requested_emphasis", freeze_value(tuple(self.requested_emphasis)))
        object.__setattr__(self, "requested_controls", freeze_value(tuple(self.requested_controls)))


@dataclass(frozen=True, slots=True)
class SynthesisPlan:
    schema_version: str
    generation_ref: GenerationRef
    plan_id: str
    plan_revision: int
    response_id: str
    source_text: str
    normalized_text: str
    language: str
    voice_profile: str
    seed: int | None
    chunks: tuple[ChunkPlan, ...] = ()
    model_revision: str | None = None
    lexicon_revision: str | None = None
    capability_revision: str | None = None
    normalization_passes: int | None = 1
    speech_act: str = "STATEMENT"
    validation_status: PlanValidationStatus = PlanValidationStatus.UNKNOWN
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ContractVersion.parse(self.schema_version)
        if not isinstance(self.generation_ref, GenerationRef):
            raise TypeError("generation_ref must be GenerationRef")
        require_safe_id(self.plan_id, "plan_id")
        require_strict_int(self.plan_revision, "plan_revision", minimum=0)
        require_safe_id(self.response_id, "response_id")
        if not isinstance(self.source_text, str) or not isinstance(self.normalized_text, str):
            raise TypeError("source_text and normalized_text must be str")
        if self.seed is not None:
            require_strict_int(self.seed, "seed", minimum=0, maximum=2**31 - 1)
        if self.normalization_passes is not None:
            require_strict_int(self.normalization_passes, "normalization_passes", minimum=0, maximum=10)
        if not isinstance(self.validation_status, PlanValidationStatus):
            raise ValueError("validation_status invalid")
        seen_ids: set[str] = set()
        for expected_idx, chunk in enumerate(self.chunks):
            if not isinstance(chunk, ChunkPlan):
                raise TypeError("chunks must contain ChunkPlan")
            if chunk.chunk_index != expected_idx:
                raise ValueError(f"Chunk index {chunk.chunk_index} != expected contiguous {expected_idx}")
            if chunk.chunk_id in seen_ids:
                raise ValueError(f"Duplicate chunk_id: {chunk.chunk_id}")
            seen_ids.add(chunk.chunk_id)
        object.__setattr__(self, "chunks", tuple(self.chunks))
        object.__setattr__(self, "warnings", freeze_value(tuple(self.warnings)))

    def __repr__(self) -> str:
        return (
            f"SynthesisPlan(id={self.plan_id!r}, rev={self.plan_revision}, "
            f"chunks={len(self.chunks)}, seed={self.seed})"
        )


@dataclass(frozen=True, slots=True)
class AudioChunk:
    generation_ref: GenerationRef
    plan_id: str
    plan_revision: int
    chunk_id: str
    chunk_index: int
    format: AudioFormat
    sample_count: int
    payload: bytes
    voice_profile: str
    seed: int | None
    model_revision: str | None = None
    solver: str | None = None
    ode_steps: int | None = None
    cache_status: CacheStatus = CacheStatus.UNKNOWN
    quality_status: QualityStatus = QualityStatus.UNKNOWN
    post_pause_ms: int | None = None
    requested_speed: float | None = None
    applied_speed: float | None = None
    metrics: tuple[MetricSample, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.generation_ref, GenerationRef):
            raise TypeError("generation_ref must be GenerationRef")
        require_safe_id(self.plan_id, "plan_id")
        require_strict_int(self.plan_revision, "plan_revision", minimum=0)
        require_safe_id(self.chunk_id, "chunk_id")
        require_strict_int(self.chunk_index, "chunk_index", minimum=0)
        if not isinstance(self.format, AudioFormat):
            raise TypeError("format must be AudioFormat")
        if self.format.sample_rate_hz != 48000 or self.format.channels != 1 or self.format.encoding != AudioEncoding.FLOAT32_LE:
            raise ValueError("F5 AudioChunk target boundary must be 48000 Hz mono FLOAT32_LE")
        require_strict_int(self.sample_count, "sample_count", minimum=1, maximum=48000 * 60)
        if not isinstance(self.payload, bytes) or len(self.payload) != self.sample_count * 4:
            raise ValueError("AudioChunk payload must be immutable bytes of length 4 * sample_count")
        if self.seed is not None:
            require_strict_int(self.seed, "seed", minimum=0, maximum=2**31 - 1)
        if self.ode_steps is not None:
            require_strict_int(self.ode_steps, "ode_steps", minimum=1, maximum=256)
        if not isinstance(self.cache_status, CacheStatus) or not isinstance(self.quality_status, QualityStatus):
            raise ValueError("Invalid cache_status or quality_status")
        object.__setattr__(self, "metrics", freeze_value(tuple(self.metrics)))

    @property
    def actual_duration_ms(self) -> float:
        return (self.sample_count * 1000.0) / self.format.sample_rate_hz

    def __repr__(self) -> str:
        return (
            f"AudioChunk(plan={self.plan_id!r}, chunk={self.chunk_index}, "
            f"samples={self.sample_count}, dur_ms={self.actual_duration_ms:.2f})"
        )


def validate_plan_chunk_consistency(plan: SynthesisPlan, chunk: AudioChunk) -> None:
    if chunk.generation_ref != plan.generation_ref:
        raise ValueError("AudioChunk generation_ref mismatch with SynthesisPlan")
    if chunk.plan_id != plan.plan_id or chunk.plan_revision != plan.plan_revision:
        raise ValueError("AudioChunk plan_id/revision mismatch with SynthesisPlan")
    if chunk.chunk_index >= len(plan.chunks):
        raise ValueError("AudioChunk chunk_index out of SynthesisPlan bounds")
    expected = plan.chunks[chunk.chunk_index]
    if chunk.chunk_id != expected.chunk_id:
        raise ValueError("AudioChunk chunk_id mismatch with SynthesisPlan chunk")
    if plan.seed is not None and chunk.seed is not None and chunk.seed != plan.seed:
        raise ValueError("AudioChunk seed mismatch with SynthesisPlan")
