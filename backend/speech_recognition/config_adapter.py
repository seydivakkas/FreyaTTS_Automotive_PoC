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

from backend.core.configuration.contracts import ConfigSnapshot
from backend.core.configuration.feature_flags import FeatureFlagRegistry
from backend.core.contracts.common import CapabilityState
from backend.core.contracts.validation import require_finite, require_safe_id, require_strict_int
from backend.core.model_registry.contracts import ModelDescriptor, ModelKind
from backend.core.model_registry.registry import ModelRegistry
from backend.speech_recognition.errors import ASRConfigError

SUPPORTED_STT_DEVICES: frozenset[str] = frozenset({"cuda", "cpu"})
SUPPORTED_STT_COMPUTE_TYPES: frozenset[str] = frozenset(
    {"float16", "float32", "int8", "int8_float16", "bfloat16"}
)
LEGACY_HOTWORDS_CAP = 50
LEGACY_HOTWORDS_TTL_SEC = 60.0
DEFAULT_ASR_DEADLINE_MS = 10_000
DEFAULT_MAX_DURATION_SEC = 20
DEFAULT_MAX_SAMPLES_16K = 16_000 * DEFAULT_MAX_DURATION_SEC


class ASRRouteMode(StrEnum):
    """Routing selector preserving legacy defaults unless strict F2-A is opted in."""

    LEGACY = "LEGACY"
    STRICT = "STRICT"


@dataclass(frozen=True, slots=True)
class DecodeProfile:
    """
    Immutable decoder parameters pinned at utterance admission.

    Matches audited `backend/models.py` Faster-Whisper defaults without adding
    F2-B/C calibration or adaptive beam changes.
    """

    language: str = "tr"
    beam_size: int = 1
    condition_on_previous_text: bool = False
    no_speech_threshold: float = 0.50
    log_prob_threshold: float = -0.80
    compression_ratio_threshold: float = 2.2
    repetition_penalty: float = 1.2
    no_repeat_ngram_size: int = 3
    hallucination_silence_threshold: float = 2.0
    # Audited post-segment guards in `backend/models.py:341-346`
    post_no_speech_prob_max: float = 0.40
    post_avg_logprob_min: float = -0.85
    post_compression_ratio_max: float = 2.2
    vad_filter: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.language, str) or not self.language.strip():
            raise ValueError("language must be non-empty")
        require_strict_int(self.beam_size, "beam_size", minimum=1, maximum=16)
        require_finite(self.no_speech_threshold, "no_speech_threshold", minimum=0.0, maximum=1.0)
        require_finite(self.log_prob_threshold, "log_prob_threshold", maximum=0.0)
        require_finite(self.compression_ratio_threshold, "compression_ratio_threshold", minimum=0.1)
        require_finite(self.repetition_penalty, "repetition_penalty", minimum=0.1)
        require_strict_int(self.no_repeat_ngram_size, "no_repeat_ngram_size", minimum=0, maximum=32)
        require_finite(self.hallucination_silence_threshold, "hallucination_silence_threshold", minimum=0.0)
        require_finite(self.post_no_speech_prob_max, "post_no_speech_prob_max", minimum=0.0, maximum=1.0)
        require_finite(self.post_avg_logprob_min, "post_avg_logprob_min", maximum=0.0)
        require_finite(self.post_compression_ratio_max, "post_compression_ratio_max", minimum=0.1)

    def to_transcribe_kwargs(self, hotwords: str | None = None) -> dict[str, object]:
        return {
            "language": self.language,
            "beam_size": self.beam_size,
            "hotwords": hotwords or None,
            "condition_on_previous_text": self.condition_on_previous_text,
            "no_speech_threshold": self.no_speech_threshold,
            "log_prob_threshold": self.log_prob_threshold,
            "compression_ratio_threshold": self.compression_ratio_threshold,
            "repetition_penalty": self.repetition_penalty,
            "no_repeat_ngram_size": self.no_repeat_ngram_size,
            "hallucination_silence_threshold": self.hallucination_silence_threshold,
        }


@dataclass(frozen=True, slots=True)
class PinnedASRConfig:
    """Immutable F2-A configuration & model snapshot captured at utterance admission."""

    config_revision: str
    model_registry_revision: str
    model_id: str
    model_name: str
    model_revision: str
    device: str
    compute_type: str
    min_rms: float
    catalog_hotwords_enabled: bool
    hotwords_cap: int
    hotwords_ttl_sec: float
    route_mode: ASRRouteMode
    max_input_samples: int
    deadline_ms: int
    decode_profile: DecodeProfile
    require_lexicon_snapshot: bool = False
    allow_discontinuity: bool = False
    estimated_vram_bytes: int = 0
    capability_state: CapabilityState = CapabilityState.DECLARED

    def __post_init__(self) -> None:
        require_safe_id(self.model_id, "model_id")
        if not self.model_name.strip():
            raise ValueError("model_name required")
        if not self.model_revision.strip():
            raise ValueError("model_revision required")
        if self.device not in SUPPORTED_STT_DEVICES:
            raise ASRConfigError("ASR_UNSUPPORTED_DEVICE", f"Unsupported STT device: {self.device}", field_name="stt_device")
        if self.compute_type not in SUPPORTED_STT_COMPUTE_TYPES:
            raise ASRConfigError(
                "ASR_UNSUPPORTED_COMPUTE_TYPE",
                f"Unsupported STT compute_type: {self.compute_type}",
                field_name="stt_compute_type",
            )
        require_finite(self.min_rms, "min_rms", minimum=0.0, maximum=1.0)
        require_strict_int(self.hotwords_cap, "hotwords_cap", minimum=0, maximum=500)
        require_finite(self.hotwords_ttl_sec, "hotwords_ttl_sec", minimum=0.0)
        require_strict_int(self.max_input_samples, "max_input_samples", minimum=1, maximum=16_000 * 120)
        require_strict_int(self.deadline_ms, "deadline_ms", minimum=1, maximum=120_000)
        require_strict_int(self.estimated_vram_bytes, "estimated_vram_bytes", minimum=0)


def resolve_asr_config(
    snapshot: ConfigSnapshot,
    model_registry: ModelRegistry | None = None,
    *,
    route_mode: ASRRouteMode | None = None,
    max_input_samples: int = DEFAULT_MAX_SAMPLES_16K,
    deadline_ms: int = DEFAULT_ASR_DEADLINE_MS,
    require_lexicon_snapshot: bool = False,
    allow_discontinuity: bool = False,
    estimated_vram_bytes: int = 0,
    model_id: str = "stt-whisper",
) -> PinnedASRConfig:
    """
    Resolve and validate an immutable F2-A config snapshot from M03 ConfigSnapshot & ModelRegistry.

    Fails explicitly on missing/unsupported model revision or capabilities without silent fallback.
    """
    if not isinstance(snapshot, ConfigSnapshot):
        raise ASRConfigError("ASR_INVALID_CONFIG_SNAPSHOT", "snapshot must be M03 ConfigSnapshot")

    registry = model_registry if model_registry is not None else ModelRegistry.from_snapshot(snapshot)
    descriptor: ModelDescriptor | None = registry.get(model_id)
    if descriptor is None or descriptor.kind != ModelKind.STT:
        raise ASRConfigError(
            "ASR_MODEL_UNAVAILABLE",
            f"STT model descriptor {model_id!r} missing from ModelRegistry",
            field_name="model_id",
        )
    if descriptor.capability is not None and descriptor.capability.state == CapabilityState.UNSUPPORTED:
        raise ASRConfigError(
            "ASR_MODEL_UNSUPPORTED",
            f"STT model {model_id!r} capability is UNSUPPORTED",
            field_name="capability",
        )

    stt_model = str(snapshot.get("stt_model", descriptor.version)).strip()
    stt_device = str(snapshot.get("stt_device", descriptor.device)).strip()
    stt_compute = str(snapshot.get("stt_compute_type", "float16")).strip()
    if not stt_model or descriptor.version != stt_model:
        raise ASRConfigError(
            "ASR_MODEL_REVISION_MISMATCH",
            f"Configured stt_model {stt_model!r} does not match registry descriptor {descriptor.version!r}",
            field_name="stt_model",
        )
    if stt_device not in SUPPORTED_STT_DEVICES or descriptor.device != stt_device:
        raise ASRConfigError(
            "ASR_DEVICE_MISMATCH",
            f"Configured stt_device {stt_device!r} is unsupported or mismatches registry {descriptor.device!r}",
            field_name="stt_device",
        )
    if stt_compute not in SUPPORTED_STT_COMPUTE_TYPES:
        raise ASRConfigError(
            "ASR_UNSUPPORTED_COMPUTE_TYPE",
            f"Unsupported stt_compute_type: {stt_compute!r}",
            field_name="stt_compute_type",
        )

    flags = FeatureFlagRegistry.from_snapshot(snapshot)
    catalog_hotwords = bool(flags.is_enabled("stt_catalog_hotwords"))
    min_rms = float(snapshot.get("stt_min_rms", 0.0))

    effective_mode = route_mode
    if effective_mode is None:
        raw_strict = snapshot.feature_flags.get("asr_strict_mode", False)
        effective_mode = ASRRouteMode.STRICT if bool(raw_strict) else ASRRouteMode.LEGACY

    return PinnedASRConfig(
        config_revision=snapshot.config_revision,
        model_registry_revision=registry.model_registry_revision,
        model_id=descriptor.model_id,
        model_name=stt_model,
        model_revision=descriptor.model_revision,
        device=stt_device,
        compute_type=stt_compute,
        min_rms=min_rms,
        catalog_hotwords_enabled=catalog_hotwords,
        hotwords_cap=LEGACY_HOTWORDS_CAP,
        hotwords_ttl_sec=LEGACY_HOTWORDS_TTL_SEC,
        route_mode=effective_mode,
        max_input_samples=max_input_samples,
        deadline_ms=deadline_ms,
        decode_profile=DecodeProfile(),
        require_lexicon_snapshot=require_lexicon_snapshot,
        allow_discontinuity=allow_discontinuity,
        estimated_vram_bytes=estimated_vram_bytes,
        capability_state=(
            descriptor.capability.state if descriptor.capability is not None else CapabilityState.UNKNOWN
        ),
    )
