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
from typing import Any, Mapping

from backend.audio_frontend.f0_b.profiles import EnvironmentProfileId
from backend.core.configuration.contracts import ConfigSnapshot, FeatureFlagSpec
from backend.core.configuration.feature_flags import FeatureFlagRegistry
from backend.core.configuration.legacy_adapter import snapshot_from_legacy_settings
from backend.core.configuration.resolver import resolve_configuration
from backend.core.configuration.setting_catalog import SETTING_CATALOG

F0_STRICT_PIPELINE_FLAG = FeatureFlagSpec(
    name="f0_a_strict_input_pipeline",
    default=False,
    experimental=True,
    description="Enable strict F0-A audio input pipeline route (default OFF).",
)

F0_B_ADAPTIVE_DSP_FLAG = FeatureFlagSpec(
    name="f0_b_adaptive_dsp",
    default=False,
    experimental=True,
    description="Enable F0-B adaptive DSP, noise PSD estimation, and environment profiles (default OFF).",
)

F0_B_AEC_FLAG = FeatureFlagSpec(
    name="f0_b_aec_enabled",
    default=False,
    experimental=True,
    description="Enable F0-B bounded NLMS AEC when F6-B reference is eligible (default OFF).",
)

F0_B_RNNOISE_FLAG = FeatureFlagSpec(
    name="f0_b_rnnoise_enabled",
    default=False,
    experimental=True,
    description="Enable optional RNNoise denoiser alternative when verified (default OFF).",
)


@dataclass(frozen=True, slots=True)
class AudioFrontendConfig:
    """Immutable F0-A configuration pinned per stream/epoch from M03 ConfigSnapshot."""

    config_revision: str
    snapshot_seq: int
    car_denoiser_enabled: bool = True
    hpf_cutoff_hz: float = 120.0
    suppression_db: float = 18.0
    target_dbfs: float = -16.0
    noise_gate_dbfs: float = -42.0
    max_boost_db: float = 12.0
    gate_attenuation_db: float = 30.0
    strict_pipeline_enabled: bool = False
    bypass_dsp: bool = False
    max_queue_items: int = 64
    max_queue_bytes: int = 256 * 1024
    max_frame_bytes: int = 192000
    max_frame_samples: int = 96000
    overrange_policy: str = "saturate"
    resampler_quality: str = "HQ"
    f0_b_adaptive_dsp_enabled: bool = False
    f0_b_aec_enabled: bool = False
    f0_b_rnnoise_enabled: bool = False
    environment_profile: EnvironmentProfileId = EnvironmentProfileId.PARKED_CAR
    browser_native_aec_active: bool = False

    def __post_init__(self) -> None:
        if not self.config_revision:
            raise ValueError("config_revision required")
        if self.max_queue_items < 1 or self.max_queue_bytes < 1:
            raise ValueError("Queue caps must be positive")
        if self.max_frame_bytes < 1 or self.max_frame_samples < 1:
            raise ValueError("Frame caps must be positive")
        if self.overrange_policy not in ("reject", "saturate"):
            raise ValueError(f"Unsupported overrange_policy: {self.overrange_policy}")


def build_f0_flag_registry(
    snapshot: ConfigSnapshot,
    *,
    strict_pipeline_enabled: bool | None = None,
    f0_b_adaptive_dsp_enabled: bool | None = None,
    f0_b_aec_enabled: bool | None = None,
    f0_b_rnnoise_enabled: bool | None = None,
) -> FeatureFlagRegistry:
    """Resolve M03 FeatureFlagRegistry with additive default-OFF F0-A/F0-B flags."""
    base = FeatureFlagRegistry.from_snapshot(snapshot)
    for spec, override in (
        (F0_STRICT_PIPELINE_FLAG, strict_pipeline_enabled),
        (F0_B_ADAPTIVE_DSP_FLAG, f0_b_adaptive_dsp_enabled),
        (F0_B_AEC_FLAG, f0_b_aec_enabled),
        (F0_B_RNNOISE_FLAG, f0_b_rnnoise_enabled),
    ):
        if spec.name in base.specs:
            continue
        val = override
        if val is None and spec.name in snapshot.feature_flags:
            val = bool(snapshot.feature_flags[spec.name])
        base = base.register(spec, value=val)
    return base


def config_from_snapshot(
    snapshot: ConfigSnapshot,
    *,
    strict_pipeline_enabled: bool | None = None,
    bypass_dsp: bool = False,
    max_queue_items: int = 64,
    max_queue_bytes: int = 256 * 1024,
    max_frame_bytes: int = 192000,
    max_frame_samples: int = 96000,
    overrange_policy: str = "saturate",
    resampler_quality: str = "HQ",
    f0_b_adaptive_dsp_enabled: bool | None = None,
    f0_b_aec_enabled: bool | None = None,
    f0_b_rnnoise_enabled: bool | None = None,
    environment_profile: EnvironmentProfileId | str = EnvironmentProfileId.PARKED_CAR,
    browser_native_aec_active: bool = False,
) -> AudioFrontendConfig:
    """Extract pinned immutable AudioFrontendConfig from an M03 ConfigSnapshot."""
    if not isinstance(snapshot, ConfigSnapshot):
        raise TypeError("snapshot must be M03 ConfigSnapshot")
    flags = build_f0_flag_registry(
        snapshot,
        strict_pipeline_enabled=strict_pipeline_enabled,
        f0_b_adaptive_dsp_enabled=f0_b_adaptive_dsp_enabled,
        f0_b_aec_enabled=f0_b_aec_enabled,
        f0_b_rnnoise_enabled=f0_b_rnnoise_enabled,
    )
    env_prof = (
        environment_profile
        if isinstance(environment_profile, EnvironmentProfileId)
        else EnvironmentProfileId(str(environment_profile))
    )
    v = snapshot.values
    return AudioFrontendConfig(
        config_revision=snapshot.config_revision,
        snapshot_seq=snapshot.snapshot_seq,
        car_denoiser_enabled=bool(v.get("car_denoiser_enabled", True)),
        hpf_cutoff_hz=float(v.get("car_denoiser_hpf_cutoff", 120.0)),
        suppression_db=float(v.get("car_denoiser_suppression_db", 18.0)),
        target_dbfs=float(v.get("car_denoiser_target_dbfs", -16.0)),
        noise_gate_dbfs=float(v.get("car_denoiser_noise_gate_dbfs", -42.0)),
        max_boost_db=float(v.get("car_denoiser_max_boost_db", 12.0)),
        gate_attenuation_db=float(v.get("car_denoiser_gate_attenuation_db", 30.0)),
        strict_pipeline_enabled=flags.is_enabled(F0_STRICT_PIPELINE_FLAG.name),
        bypass_dsp=bypass_dsp,
        max_queue_items=max_queue_items,
        max_queue_bytes=max_queue_bytes,
        max_frame_bytes=max_frame_bytes,
        max_frame_samples=max_frame_samples,
        overrange_policy=overrange_policy,
        resampler_quality=resampler_quality,
        f0_b_adaptive_dsp_enabled=flags.is_enabled(F0_B_ADAPTIVE_DSP_FLAG.name),
        f0_b_aec_enabled=flags.is_enabled(F0_B_AEC_FLAG.name),
        f0_b_rnnoise_enabled=flags.is_enabled(F0_B_RNNOISE_FLAG.name),
        environment_profile=env_prof,
        browser_native_aec_active=browser_native_aec_active,
    )


def default_audio_frontend_config(
    *,
    overrides: Mapping[str, Any] | None = None,
    strict_pipeline_enabled: bool = False,
    bypass_dsp: bool = False,
    max_queue_items: int = 64,
    max_queue_bytes: int = 256 * 1024,
    max_frame_bytes: int = 192000,
    max_frame_samples: int = 96000,
    overrange_policy: str = "saturate",
    f0_b_adaptive_dsp_enabled: bool = False,
    f0_b_aec_enabled: bool = False,
    f0_b_rnnoise_enabled: bool = False,
    environment_profile: EnvironmentProfileId | str = EnvironmentProfileId.PARKED_CAR,
    browser_native_aec_active: bool = False,
) -> AudioFrontendConfig:
    """Resolve default M03 snapshot cleanly without touching .env or backend.config."""
    resolution = resolve_configuration(overrides=overrides, catalog=SETTING_CATALOG)
    return config_from_snapshot(
        resolution.snapshot,
        strict_pipeline_enabled=strict_pipeline_enabled,
        bypass_dsp=bypass_dsp,
        max_queue_items=max_queue_items,
        max_queue_bytes=max_queue_bytes,
        max_frame_bytes=max_frame_bytes,
        max_frame_samples=max_frame_samples,
        overrange_policy=overrange_policy,
        f0_b_adaptive_dsp_enabled=f0_b_adaptive_dsp_enabled,
        f0_b_aec_enabled=f0_b_aec_enabled,
        f0_b_rnnoise_enabled=f0_b_rnnoise_enabled,
        environment_profile=environment_profile,
        browser_native_aec_active=browser_native_aec_active,
    )


def config_from_legacy_settings(
    settings_obj: Any = None,
    *,
    strict_pipeline_enabled: bool = False,
) -> AudioFrontendConfig:
    """On-demand bridge from legacy backend.config.Settings to AudioFrontendConfig."""
    conv = snapshot_from_legacy_settings(settings_obj, catalog=SETTING_CATALOG)
    if not conv.ok or conv.value is None:
        raise ValueError(f"Failed to resolve legacy settings: {conv.error}")
    return config_from_snapshot(conv.value, strict_pipeline_enabled=strict_pipeline_enabled)
