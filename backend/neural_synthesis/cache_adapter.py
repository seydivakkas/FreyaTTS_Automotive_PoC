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

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.synthesis import CacheStatus, ChunkPlan, SynthesisPlan
from backend.neural_synthesis.f5_bc.cache_store import (
    CACHE_SCHEMA_VERSION,
    CacheEligibility,
    CacheEligibilityKind,
    CanonicalCacheDescriptor,
    VersionedCacheStore,
)
from backend.neural_synthesis.config_adapter import BASELINE_ODE_STEPS, BASELINE_SAMPLE_RATE_HZ, BASELINE_SOLVER, PinnedSynthesisSnapshot


@dataclass(frozen=True, slots=True)
class RawCacheEntry:
    """Provenance-annotated raw 48 kHz FLOAT32_LE cache entry."""

    model_text: str
    voice_profile: str
    seed: int
    model_revision: str
    lexicon_revision: str | None
    capability_revision: str | None
    solver: str
    ode_steps: int
    format: AudioFormat
    sample_count: int
    payload: bytes
    is_raw_unprocessed: bool = True
    is_private: bool = False
    owner_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class CacheLookupResult:
    """Outcome of strict provenance-checked cache lookup."""

    cache_status: CacheStatus
    payload: bytes | None
    sample_count: int | None
    reason: str
    provenance_verified: bool


class StrictSynthesisCacheAdapter:
    """
    Strict cache compatibility adapter.

    - Legacy cache entries (e.g. `(normalized_text, seed)` in Models._synth_cache) lack
      full revision/raw-format provenance and are explicitly BYPASSED on strict path.
    - Rendered/phone entries or entries with mismatched seed/rate/revisions are rejected.
    - Private text entries never hit across sessions.
    """

    def __init__(self, *, store: VersionedCacheStore | None = None) -> None:
        self._verified_store: dict[str, RawCacheEntry] = {}
        self.store = store or VersionedCacheStore()

    @staticmethod
    def build_canonical_descriptor(
        *,
        chunk: ChunkPlan,
        snapshot: PinnedSynthesisSnapshot,
        solver_name: str = BASELINE_SOLVER,
        ode_steps: int = BASELINE_ODE_STEPS,
        time_grid_mode: str = "uniform_0_to_1",
        numeric_precision: str = "float32",
        layout_class: str = "singleton",
        duration_policy_revision: str = "f5b-duration-v1",
        effective_model_speed: float | None = None,
        rng_profile_revision: str = "f5b-rng-v1",
        quality_policy_revision: str = "f5b-quality-v1",
    ) -> CanonicalCacheDescriptor:
        return CanonicalCacheDescriptor(
            cache_schema_version=CACHE_SCHEMA_VERSION,
            policy_revision="f5b-cache-policy-v1",
            model_text=chunk.model_text,
            language="tr",
            model_revision=snapshot.model_descriptor.model_revision,
            vocab_revision=getattr(snapshot.model_descriptor, "vocab_revision", None),
            lexicon_revision=snapshot.lexicon_revision,
            capability_revision=snapshot.capability_revision,
            voice_profile_id=snapshot.voice_profile.profile_id,
            seed=snapshot.seed,
            solver_name=solver_name,
            ode_steps=ode_steps,
            time_grid_mode=time_grid_mode,
            numeric_precision=numeric_precision,
            layout_class=layout_class,
            duration_policy_revision=duration_policy_revision,
            effective_model_speed=effective_model_speed,
            rng_profile_revision=rng_profile_revision,
            quality_policy_revision=quality_policy_revision,
        )

    @staticmethod
    def _entry_key(
        *,
        model_text: str,
        voice_profile: str,
        seed: int,
        model_revision: str,
        lexicon_revision: str | None,
        capability_revision: str | None,
    ) -> str:
        digest = hashlib.sha256(
            f"{model_text}|{voice_profile}|{seed}|{model_revision}|{lexicon_revision or ''}|{capability_revision or ''}".encode(
                "utf-8"
            )
        ).hexdigest()
        return digest

    def put_verified_raw(self, entry: RawCacheEntry) -> str:
        if not entry.is_raw_unprocessed:
            raise ValueError("Strict raw cache refuses rendered/DSP-processed audio")
        if (
            entry.format.sample_rate_hz != BASELINE_SAMPLE_RATE_HZ
            or entry.format.channels != 1
            or entry.format.encoding != AudioEncoding.FLOAT32_LE
        ):
            raise ValueError("Strict raw cache requires 48000 Hz mono FLOAT32_LE")
        if len(entry.payload) != entry.sample_count * 4:
            raise ValueError("Cache payload byte length mismatch")
        key = self._entry_key(
            model_text=entry.model_text,
            voice_profile=entry.voice_profile,
            seed=entry.seed,
            model_revision=entry.model_revision,
            lexicon_revision=entry.lexicon_revision,
            capability_revision=entry.capability_revision,
        )
        # Store owned immutable bytes copy
        self._verified_store[key] = RawCacheEntry(
            model_text=entry.model_text,
            voice_profile=entry.voice_profile,
            seed=entry.seed,
            model_revision=entry.model_revision,
            lexicon_revision=entry.lexicon_revision,
            capability_revision=entry.capability_revision,
            solver=entry.solver,
            ode_steps=entry.ode_steps,
            format=entry.format,
            sample_count=entry.sample_count,
            payload=bytes(entry.payload),
            is_raw_unprocessed=True,
            is_private=entry.is_private,
            owner_session_id=entry.owner_session_id,
        )
        return key

    def lookup(
        self,
        *,
        plan: SynthesisPlan,
        chunk: ChunkPlan,
        snapshot: PinnedSynthesisSnapshot,
        legacy_cache: Mapping[tuple[str, int], Any] | None = None,
    ) -> CacheLookupResult:
        key = self._entry_key(
            model_text=chunk.model_text,
            voice_profile=snapshot.voice_profile.profile_id,
            seed=snapshot.seed,
            model_revision=snapshot.model_descriptor.model_revision,
            lexicon_revision=snapshot.lexicon_revision,
            capability_revision=snapshot.capability_revision,
        )
        entry = self._verified_store.get(key)
        if entry is not None:
            if not entry.is_raw_unprocessed:
                return CacheLookupResult(
                    cache_status=CacheStatus.BYPASS,
                    payload=None,
                    sample_count=None,
                    reason="REJECTED_RENDERED_CACHE_ENTRY",
                    provenance_verified=False,
                )
            if (
                entry.format.sample_rate_hz != BASELINE_SAMPLE_RATE_HZ
                or entry.format.channels != 1
                or entry.format.encoding != AudioEncoding.FLOAT32_LE
            ):
                return CacheLookupResult(
                    cache_status=CacheStatus.BYPASS,
                    payload=None,
                    sample_count=None,
                    reason="REJECTED_FORMAT_MISMATCH",
                    provenance_verified=False,
                )
            if entry.seed != snapshot.seed or entry.solver != BASELINE_SOLVER or entry.ode_steps != BASELINE_ODE_STEPS:
                return CacheLookupResult(
                    cache_status=CacheStatus.BYPASS,
                    payload=None,
                    sample_count=None,
                    reason="REJECTED_SEED_OR_SOLVER_MISMATCH",
                    provenance_verified=False,
                )
            if entry.is_private and entry.owner_session_id != plan.generation_ref.session_id:
                return CacheLookupResult(
                    cache_status=CacheStatus.BYPASS,
                    payload=None,
                    sample_count=None,
                    reason="PRIVATE_CROSS_SESSION_DISALLOWED",
                    provenance_verified=False,
                )
            return CacheLookupResult(
                cache_status=CacheStatus.HIT,
                payload=bytes(entry.payload),
                sample_count=entry.sample_count,
                reason="VERIFIED_RAW_CACHE_HIT",
                provenance_verified=True,
            )

        if legacy_cache is not None and (chunk.model_text, snapshot.seed) in legacy_cache:
            return CacheLookupResult(
                cache_status=CacheStatus.BYPASS,
                payload=None,
                sample_count=None,
                reason="LEGACY_CACHE_PROVENANCE_INCOMPLETE_BYPASS",
                provenance_verified=False,
            )

        return CacheLookupResult(
            cache_status=CacheStatus.MISS,
            payload=None,
            sample_count=None,
            reason="CACHE_MISS",
            provenance_verified=True,
        )


def inventory_experimental_routes() -> dict[str, dict[str, Any]]:
    """Static read-only inventory of preserved experimental/legacy synthesis routes (none activated here)."""
    return {
        "models_synth_cache": {
            "owner": "backend/models.py:Models._synth_cache",
            "classification": "LIVE_PATH_LEGACY",
            "key": "(normalized_text, seed)",
            "contains_dsp_fade": True,
            "strict_action": "BYPASS",
        },
        "prewarm_tts": {
            "owner": "backend/models.py:Models._prewarm_tts",
            "classification": "LIVE_PATH_LEGACY",
            "auto_activated_in_f5a": False,
        },
        "ab_seed_presets": {
            "owner": "backend/ab_testing.py:TTS_SEED_PRESETS",
            "classification": "FLAGGED_EXPERIMENTAL",
            "seeds": (9, 42, 77, 123),
            "default_experimental_enabled": False,
        },
        "sft_leyla_lora": {
            "owner": "backend/sft_leyla.py",
            "classification": "EXPERIMENTAL_RESEARCH",
            "auto_activated_in_f5a": False,
        },
    }


__all__ = [
    "CacheLookupResult",
    "RawCacheEntry",
    "StrictSynthesisCacheAdapter",
    "inventory_experimental_routes",
]
