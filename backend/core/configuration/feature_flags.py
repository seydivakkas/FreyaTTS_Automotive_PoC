"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from backend.core.configuration.contracts import (
    ConfigSnapshot,
    FeatureFlagSpec,
    SupervisorMode,
)
from backend.core.contracts.validation import require_safe_id


def _flag(
    name: str,
    default: bool | SupervisorMode,
    *,
    setting_key: str | None = None,
    experimental: bool = False,
    description: str = "",
) -> FeatureFlagSpec:
    return FeatureFlagSpec(
        name=name,
        default=default,
        setting_key=setting_key,
        experimental=experimental,
        description=description,
    )


DEFAULT_FEATURE_FLAGS: tuple[FeatureFlagSpec, ...] = (
    # Existing production flags preserving exact backend/config.py defaults
    _flag("demo_mode", False, setting_key="demo_mode", description="Demo storage isolation."),
    _flag("auto_load_models", True, setting_key="auto_load_models", description="Load models on startup."),
    _flag("stt_catalog_hotwords", False, setting_key="stt_catalog_hotwords", description="STT vehicle catalog hotwords."),
    _flag("kvkk_erasure_enabled", False, setting_key="kvkk_erasure_enabled", description="KVKK erasure endpoint."),
    _flag("multi_vehicle_booking_enabled", False, setting_key="multi_vehicle_booking_enabled", description="Multi-vehicle booking."),
    _flag("twilio_enabled", False, setting_key="twilio_enabled", description="Twilio outbound notifications."),
    _flag("auto_purge_transcripts", False, setting_key="auto_purge_transcripts", description="Automatic transcript purge."),
    _flag("record_audio", False, setting_key="record_audio", description="Call audio recording."),
    _flag("ami_enabled", False, setting_key="ami_enabled", description="Real Asterisk AMI integration."),
    _flag("car_denoiser_enabled", True, setting_key="car_denoiser_enabled", description="Car cabin DSP denoiser."),
    _flag("batched_ode_enabled", True, setting_key="batched_ode_enabled", description="Batched ODE TTS engine."),
    _flag("chan_websocket_enabled", True, setting_key="chan_websocket_enabled", description="Asterisk chan_websocket server."),
    _flag("morph_precheck_enabled", True, setting_key="morph_precheck_enabled", description="Morphological TTS pre-check."),
    _flag("supervisor_mode", SupervisorMode.OFF, setting_key="supervisor_mode", description="Supervisor rollout mode (off/shadow/guarded)."),
    _flag("fqici_enabled", False, setting_key="fqici_enabled", description="FQICI closure queue."),
    _flag("supervisor_llm_fallback", False, setting_key="supervisor_llm_fallback", description="Supervisor LLM fallback."),
    # Experimental flags — MUST default OFF / False
    _flag("experimental_voice_seed_42", False, experimental=True, description="Allow experimental warm Leyla TTS seed 42."),
    _flag("experimental_voice_seed_77", False, experimental=True, description="Allow experimental dynamic Leyla TTS seed 77."),
    _flag("experimental_voice_seed_123", False, experimental=True, description="Allow experimental formal Leyla TTS seed 123."),
    _flag("experimental_barge_in_v2", False, experimental=True, description="Experimental M02 barge-in heuristics."),
    _flag("experimental_lexicon_v2", False, experimental=True, description="Experimental M05 lexicon matching pipeline."),
    _flag("f0_pipeline_v2", False, experimental=True, description="Enable Freya 2.0 F0 audio frontend pipeline."),
    _flag("f1_pipeline_v2", False, experimental=True, description="Enable Freya 2.0 F1 voice activity & barge-in pipeline."),
    _flag("f2_pipeline_v2", False, experimental=True, description="Enable Freya 2.0 F2 speech recognition pipeline."),
    _flag("f3_pipeline_v2", False, experimental=True, description="Enable Freya 2.0 F3 dialogue & multi-agent pipeline."),
    _flag("f4_pipeline_v2", False, experimental=True, description="Enable Freya 2.0 F4 Turkish linguistic & prosody pipeline."),
    _flag("f5_pipeline_v2", False, experimental=True, description="Enable Freya 2.0 F5 neural synthesis pipeline."),
    _flag("f6_pipeline_v2", False, experimental=True, description="Enable Freya 2.0 F6 rendering & transport pipeline."),
)


def parse_supervisor_mode(raw: object) -> SupervisorMode:
    if isinstance(raw, SupervisorMode):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        for mode in SupervisorMode:
            if mode.value == normalized:
                return mode
    raise ValueError(f"Invalid supervisor_mode {raw!r}; expected one of: off, shadow, guarded")


@dataclass(frozen=True, slots=True)
class FeatureFlagRegistry:
    """Registry of runtime and experimental feature flags with safe defaults."""

    specs: Mapping[str, FeatureFlagSpec]
    values: Mapping[str, bool | SupervisorMode]

    @classmethod
    def default(cls) -> "FeatureFlagRegistry":
        specs = {spec.name: spec for spec in DEFAULT_FEATURE_FLAGS}
        values = {spec.name: spec.default for spec in DEFAULT_FEATURE_FLAGS}
        return cls(specs=MappingProxyType(specs), values=MappingProxyType(values))

    @classmethod
    def from_snapshot(
        cls,
        snapshot: ConfigSnapshot,
        *,
        extra_flags: Mapping[str, bool | SupervisorMode] | None = None,
    ) -> "FeatureFlagRegistry":
        base = cls.default()
        resolved: dict[str, bool | SupervisorMode] = dict(base.values)
        for name, spec in base.specs.items():
            if spec.setting_key and spec.setting_key in snapshot.values:
                raw = snapshot.values[spec.setting_key]
                resolved[name] = parse_supervisor_mode(raw) if isinstance(spec.default, SupervisorMode) else bool(raw)
            elif name in snapshot.feature_flags:
                raw = snapshot.feature_flags[name]
                resolved[name] = parse_supervisor_mode(raw) if isinstance(spec.default, SupervisorMode) else bool(raw)
        if extra_flags:
            for name, val in extra_flags.items():
                if name not in base.specs:
                    raise KeyError(f"Unregistered feature flag: {name}")
                spec = base.specs[name]
                resolved[name] = parse_supervisor_mode(val) if isinstance(spec.default, SupervisorMode) else bool(val)
        return cls(specs=base.specs, values=MappingProxyType(resolved))

    def register(self, spec: FeatureFlagSpec, value: bool | SupervisorMode | None = None) -> "FeatureFlagRegistry":
        require_safe_id(spec.name, "spec.name")
        if spec.name in self.specs:
            raise ValueError(f"Feature flag already registered: {spec.name}")
        new_specs = dict(self.specs)
        new_specs[spec.name] = spec
        new_values = dict(self.values)
        chosen = spec.default if value is None else value
        if isinstance(spec.default, SupervisorMode):
            chosen = parse_supervisor_mode(chosen)
        elif type(chosen) is not bool:
            raise ValueError(f"Boolean feature flag {spec.name!r} requires bool")
        new_values[spec.name] = chosen
        return FeatureFlagRegistry(specs=MappingProxyType(new_specs), values=MappingProxyType(new_values))

    def is_enabled(self, name: str) -> bool:
        val = self.values[name]
        if isinstance(val, SupervisorMode):
            return val != SupervisorMode.OFF
        return bool(val)

    def get_mode(self, name: str = "supervisor_mode") -> SupervisorMode:
        val = self.values[name]
        if not isinstance(val, SupervisorMode):
            raise TypeError(f"Flag {name!r} is not a tri-state SupervisorMode")
        return val

    def as_primitives(self) -> dict[str, bool | str]:
        return {
            k: (v.value if isinstance(v, SupervisorMode) else bool(v))
            for k, v in sorted(self.values.items())
        }
