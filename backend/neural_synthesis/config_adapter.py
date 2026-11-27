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

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from backend.core.configuration.contracts import ConfigSnapshot
from backend.core.configuration.feature_flags import FeatureFlagRegistry
from backend.core.configuration.legacy_adapter import snapshot_from_legacy_settings
from backend.core.contracts.common import CapabilityState, ErrorCategory, ErrorInfo, Retryability
from backend.core.contracts.synthesis import SynthesisPlan
from backend.core.model_registry.contracts import ModelDescriptor, ModelKind, ProfileTier, VoiceProfile
from backend.core.model_registry.registry import ModelRegistry
from backend.core.model_registry.voice_profiles import (
    DEFAULT_VOICE_PROFILE_REGISTRY,
    EXPERIMENTAL_VOICE_SEEDS,
    LEYLA_BASELINE_SEED,
    VoiceProfileRegistry,
)

BASELINE_SOLVER = "Euler"
BASELINE_ODE_STEPS = 32
BASELINE_SAMPLE_RATE_HZ = 48000
BASELINE_CHANNELS = 1
BASELINE_LATENT_DIM = 64
BASELINE_LATENT_RATE_HZ = 25
BASELINE_SAMPLES_PER_FRAME = 1920
ALLOWED_STRICT_CONTROLS: frozenset[str] = frozenset({
    "pause_hint",
    "speed_hint",
    "emphasis_hint",
    "clause_boundary",
})


@dataclass(frozen=True, slots=True)
class VoiceBinding:
    """Immutable M03 voice and capability binding for a synthesis run."""

    voice_profile_id: str
    speaker: str
    seed: int
    tier: ProfileTier
    model_revision: str
    voice_registry_revision: str
    config_revision: str
    capability_revision: str | None
    lexicon_revision: str | None
    declared_capability: CapabilityState
    verified_capability: CapabilityState


@dataclass(frozen=True, slots=True)
class PinnedSynthesisSnapshot:
    """Immutable pinned M03 configuration, model, and voice snapshot."""

    config_revision: str
    model_registry_revision: str
    voice_registry_revision: str
    model_descriptor: ModelDescriptor
    voice_profile: VoiceProfile
    voice_binding: VoiceBinding
    seed: int
    solver: str = BASELINE_SOLVER
    ode_steps: int = BASELINE_ODE_STEPS
    sample_rate_hz: int = BASELINE_SAMPLE_RATE_HZ
    channels: int = BASELINE_CHANNELS
    latent_dim: int = BASELINE_LATENT_DIM
    latent_rate_hz: int | None = BASELINE_LATENT_RATE_HZ
    samples_per_frame: int | None = BASELINE_SAMPLES_PER_FRAME
    capability_revision: str | None = None
    lexicon_revision: str | None = None
    feature_flags: Mapping[str, bool | str] = field(default_factory=lambda: MappingProxyType({}))
    allowed_controls: frozenset[str] = ALLOWED_STRICT_CONTROLS


class SnapshotPinningError(ValueError):
    """Typed pinning error carrying a safe M01 ErrorInfo."""

    def __init__(self, error_info: ErrorInfo) -> None:
        super().__init__(error_info.safe_message)
        self.error_info = error_info


def _resolve_voice_profile(
    plan: SynthesisPlan,
    voice_registry: VoiceProfileRegistry,
    *,
    feature_flags: Mapping[str, bool | str],
    allow_experimental_seeds: bool,
) -> VoiceProfile:
    seed = plan.seed
    if seed is None or type(seed) is not int:
        raise SnapshotPinningError(
            ErrorInfo(
                code="INVALID_SEED",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Strict plan requires explicit integer seed (no silent fallback)",
                field_name="seed",
            )
        )
    if seed < 0 or seed > (2**31 - 1):
        raise SnapshotPinningError(
            ErrorInfo(
                code="SEED_OUT_OF_RANGE",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Seed is out of supported integer range",
                field_name="seed",
            )
        )

    profile = voice_registry.get_by_seed(seed)
    if profile is None:
        raise SnapshotPinningError(
            ErrorInfo(
                code="UNAPPROVED_SEED",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Seed is not registered in M03 VoiceProfileRegistry",
                field_name="seed",
            )
        )

    if not voice_registry.is_seed_allowed(
        seed,
        feature_flags=feature_flags,
        experimental_enabled=allow_experimental_seeds,
    ):
        raise SnapshotPinningError(
            ErrorInfo(
                code="SEED_DISABLED_BY_POLICY",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Requested voice seed is disabled by M03 feature flags",
                field_name="seed",
            )
        )

    normalized_req_profile = (plan.voice_profile or "").strip().lower()
    if normalized_req_profile not in {profile.profile_id.lower(), profile.speaker.lower()}:
        raise SnapshotPinningError(
            ErrorInfo(
                code="VOICE_PROFILE_MISMATCH",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Plan voice_profile does not match M03 voice profile for seed",
                field_name="voice_profile",
            )
        )
    return profile


def resolve_default_snapshot() -> ConfigSnapshot:
    """Build an immutable ConfigSnapshot from current legacy settings without loading weights."""
    res = snapshot_from_legacy_settings()
    if not res.ok or res.value is None:
        raise SnapshotPinningError(
            ErrorInfo(
                code="CONFIG_SNAPSHOT_UNAVAILABLE",
                category=ErrorCategory.INTERNAL,
                retryable=Retryability.NO,
                safe_message="Failed to build M03 ConfigSnapshot",
            )
        )
    return res.value


def pin_synthesis_snapshot(
    plan: SynthesisPlan,
    *,
    config_snapshot: ConfigSnapshot | None = None,
    model_registry: ModelRegistry | None = None,
    voice_registry: VoiceProfileRegistry | None = None,
    feature_flag_registry: FeatureFlagRegistry | None = None,
    expected_capability_revision: str | None = None,
    expected_lexicon_revision: str | None = None,
    allow_experimental_seeds: bool = False,
    latent_rate_hz: int | None = BASELINE_LATENT_RATE_HZ,
    samples_per_frame: int | None = BASELINE_SAMPLES_PER_FRAME,
    verified_capability: CapabilityState = CapabilityState.DECLARED,
    tts_model_id: str = "tts-freya",
) -> PinnedSynthesisSnapshot:
    """
    Pin immutable M03 config, model, capability, lexicon, and voice snapshots for `plan`.

    No silent fallbacks are performed on missing/disabled seeds or mismatched revisions.
    """
    cfg = config_snapshot or resolve_default_snapshot()
    vreg = voice_registry or (model_registry.voice_profiles if model_registry else DEFAULT_VOICE_PROFILE_REGISTRY)
    mreg = model_registry or ModelRegistry.from_snapshot(cfg, voice_profiles=vreg)
    flags_reg = feature_flag_registry or FeatureFlagRegistry.from_snapshot(cfg)
    flags_map = flags_reg.as_primitives()

    model_desc = mreg.get(tts_model_id)
    if model_desc is None or model_desc.kind != ModelKind.TTS:
        raise SnapshotPinningError(
            ErrorInfo(
                code="TTS_MODEL_DESCRIPTOR_MISSING",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Approved M03 TTS model descriptor not found",
                field_name="model_revision",
            )
        )

    if plan.model_revision is not None and plan.model_revision != model_desc.model_revision:
        raise SnapshotPinningError(
            ErrorInfo(
                code="MODEL_REVISION_MISMATCH",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Plan model_revision does not match pinned M03 model descriptor",
                field_name="model_revision",
            )
        )

    if expected_capability_revision is not None:
        if plan.capability_revision is None or plan.capability_revision != expected_capability_revision:
            raise SnapshotPinningError(
                ErrorInfo(
                    code="CAPABILITY_REVISION_MISMATCH",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Plan capability_revision does not match pinned capability revision",
                    field_name="capability_revision",
                )
            )

    if expected_lexicon_revision is not None and plan.lexicon_revision is not None:
        if plan.lexicon_revision != expected_lexicon_revision:
            raise SnapshotPinningError(
                ErrorInfo(
                    code="LEXICON_REVISION_MISMATCH",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Plan lexicon_revision does not match expected lexicon snapshot",
                    field_name="lexicon_revision",
                )
            )

    profile = _resolve_voice_profile(
        plan,
        vreg,
        feature_flags=flags_map,
        allow_experimental_seeds=allow_experimental_seeds,
    )

    if profile.sample_rate_hz != BASELINE_SAMPLE_RATE_HZ or profile.ode_steps != BASELINE_ODE_STEPS:
        raise SnapshotPinningError(
            ErrorInfo(
                code="VOICE_PROFILE_INCOMPATIBLE_BASELINE",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Voice profile parameters diverge from 48 kHz Euler32 baseline",
                field_name="voice_profile",
            )
        )

    declared_cap = model_desc.capability.state if model_desc.capability else CapabilityState.UNKNOWN
    binding = VoiceBinding(
        voice_profile_id=profile.profile_id,
        speaker=profile.speaker,
        seed=profile.seed,
        tier=profile.tier,
        model_revision=model_desc.model_revision,
        voice_registry_revision=vreg.registry_revision,
        config_revision=cfg.config_revision,
        capability_revision=plan.capability_revision or expected_capability_revision,
        lexicon_revision=plan.lexicon_revision or expected_lexicon_revision,
        declared_capability=declared_cap,
        verified_capability=verified_capability,
    )

    return PinnedSynthesisSnapshot(
        config_revision=cfg.config_revision,
        model_registry_revision=mreg.model_registry_revision,
        voice_registry_revision=vreg.registry_revision,
        model_descriptor=model_desc,
        voice_profile=profile,
        voice_binding=binding,
        seed=profile.seed,
        solver=BASELINE_SOLVER,
        ode_steps=profile.ode_steps,
        sample_rate_hz=profile.sample_rate_hz,
        channels=BASELINE_CHANNELS,
        latent_dim=BASELINE_LATENT_DIM,
        latent_rate_hz=latent_rate_hz,
        samples_per_frame=samples_per_frame,
        capability_revision=binding.capability_revision,
        lexicon_revision=binding.lexicon_revision,
        feature_flags=MappingProxyType(flags_map),
        allowed_controls=ALLOWED_STRICT_CONTROLS,
    )


__all__ = [
    "ALLOWED_STRICT_CONTROLS",
    "BASELINE_CHANNELS",
    "BASELINE_LATENT_DIM",
    "BASELINE_LATENT_RATE_HZ",
    "BASELINE_ODE_STEPS",
    "BASELINE_SAMPLES_PER_FRAME",
    "BASELINE_SAMPLE_RATE_HZ",
    "BASELINE_SOLVER",
    "EXPERIMENTAL_VOICE_SEEDS",
    "LEYLA_BASELINE_SEED",
    "PinnedSynthesisSnapshot",
    "SnapshotPinningError",
    "VoiceBinding",
    "pin_synthesis_snapshot",
    "resolve_default_snapshot",
]
