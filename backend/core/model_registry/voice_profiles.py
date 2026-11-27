"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Iterable, Mapping

from backend.core.model_registry.contracts import ProfileTier, VoiceProfile

LEYLA_BASELINE_SEED = 9
EXPERIMENTAL_VOICE_SEEDS: tuple[int, ...] = (42, 77, 123)

DEFAULT_VOICE_PROFILES: tuple[VoiceProfile, ...] = (
    VoiceProfile(
        profile_id="leyla-baseline-9",
        speaker="leyla",
        seed=LEYLA_BASELINE_SEED,
        tier=ProfileTier.BASELINE,
        display_name="Leyla — Standart & Dengeli (Seed 9)",
        tone="Dengeli, Kurumsal",
        language="tr",
        sample_rate_hz=48000,
        ode_steps=32,
        enabled_by_default=True,
        flag_name=None,
    ),
    VoiceProfile(
        profile_id="leyla-warm-42",
        speaker="leyla",
        seed=42,
        tier=ProfileTier.EXPERIMENTAL,
        display_name="Leyla — Sıcak & Samimi (Seed 42)",
        tone="Sıcak, Empatik",
        language="tr",
        sample_rate_hz=48000,
        ode_steps=32,
        enabled_by_default=False,
        flag_name="experimental_voice_seed_42",
    ),
    VoiceProfile(
        profile_id="leyla-dynamic-77",
        speaker="leyla",
        seed=77,
        tier=ProfileTier.EXPERIMENTAL,
        display_name="Leyla — Dinamik & Canlı (Seed 77)",
        tone="Dinamik, Enerjik",
        language="tr",
        sample_rate_hz=48000,
        ode_steps=32,
        enabled_by_default=False,
        flag_name="experimental_voice_seed_77",
    ),
    VoiceProfile(
        profile_id="leyla-formal-123",
        speaker="leyla",
        seed=123,
        tier=ProfileTier.EXPERIMENTAL,
        display_name="Leyla — Resmi & Otoriter (Seed 123)",
        tone="Resmi, Ciddi",
        language="tr",
        sample_rate_hz=48000,
        ode_steps=32,
        enabled_by_default=False,
        flag_name="experimental_voice_seed_123",
    ),
)


class VoiceProfileRegistry:
    """Registry of baseline and experimental TTS voice profiles (Leyla seeds 9, 42, 77, 123)."""

    def __init__(self, profiles: Iterable[VoiceProfile] = DEFAULT_VOICE_PROFILES) -> None:
        by_id: dict[str, VoiceProfile] = {}
        by_seed: dict[int, VoiceProfile] = {}
        for profile in profiles:
            if profile.profile_id in by_id:
                raise ValueError(f"Duplicate voice profile_id: {profile.profile_id}")
            if profile.seed in by_seed:
                raise ValueError(f"Duplicate voice seed: {profile.seed}")
            by_id[profile.profile_id] = profile
            by_seed[profile.seed] = profile
        if LEYLA_BASELINE_SEED not in by_seed:
            raise ValueError(f"Baseline voice seed {LEYLA_BASELINE_SEED} is required")
        self._by_id = MappingProxyType(by_id)
        self._by_seed = MappingProxyType(by_seed)

    @property
    def profiles(self) -> Mapping[str, VoiceProfile]:
        return self._by_id

    @property
    def registry_revision(self) -> str:
        payload = [
            {
                "profile_id": p.profile_id,
                "speaker": p.speaker,
                "seed": p.seed,
                "tier": p.tier.value,
                "sample_rate_hz": p.sample_rate_hz,
                "ode_steps": p.ode_steps,
                "enabled_by_default": p.enabled_by_default,
                "flag_name": p.flag_name,
            }
            for _, p in sorted(self._by_id.items())
        ]
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def baseline(self) -> VoiceProfile:
        return self._by_seed[LEYLA_BASELINE_SEED]

    def get(self, profile_id: str) -> VoiceProfile | None:
        return self._by_id.get(profile_id)

    def get_by_seed(self, seed: int) -> VoiceProfile | None:
        return self._by_seed.get(seed)

    def list_profiles(self, *, include_experimental: bool = False) -> tuple[VoiceProfile, ...]:
        items = [
            p
            for p in self._by_id.values()
            if include_experimental or p.tier == ProfileTier.BASELINE
        ]
        return tuple(sorted(items, key=lambda p: p.seed))

    def is_seed_allowed(
        self,
        seed: int,
        *,
        feature_flags: Mapping[str, bool | str] | None = None,
        experimental_enabled: bool = False,
    ) -> bool:
        profile = self._by_seed.get(seed)
        if profile is None:
            return False
        if profile.tier == ProfileTier.BASELINE and profile.enabled_by_default:
            return True
        if experimental_enabled:
            return True
        if feature_flags and profile.flag_name:
            return bool(feature_flags.get(profile.flag_name, False))
        return False

    def resolve_seed(
        self,
        requested_seed: int | None = None,
        *,
        feature_flags: Mapping[str, bool | str] | None = None,
        experimental_enabled: bool = False,
        fallback_to_baseline: bool = True,
    ) -> VoiceProfile:
        if requested_seed is None:
            return self.baseline()
        profile = self._by_seed.get(requested_seed)
        if profile is None:
            if fallback_to_baseline:
                return self.baseline()
            raise KeyError(f"Unknown voice seed: {requested_seed}")
        if self.is_seed_allowed(
            requested_seed,
            feature_flags=feature_flags,
            experimental_enabled=experimental_enabled,
        ):
            return profile
        if fallback_to_baseline:
            return self.baseline()
        raise PermissionError(f"Experimental voice seed {requested_seed} is disabled by feature flags")

    def register(self, profile: VoiceProfile) -> "VoiceProfileRegistry":
        return VoiceProfileRegistry([*self._by_id.values(), profile])


DEFAULT_VOICE_PROFILE_REGISTRY = VoiceProfileRegistry()
