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
from typing import Mapping

from backend.core.configuration.contracts import ConfigSnapshot
from backend.core.configuration.feature_flags import FeatureFlagRegistry
from backend.core.configuration.resolver import resolve_configuration
from backend.core.model_registry.contracts import ModelDescriptor, ModelKind, VoiceProfile
from backend.core.model_registry.registry import ModelRegistry
from backend.core.model_registry.voice_profiles import (
    DEFAULT_VOICE_PROFILE_REGISTRY,
    LEYLA_BASELINE_SEED,
    VoiceProfileRegistry,
)
from backend.shared_lexicon.registry import LexiconRegistry


DEFAULT_MAX_CHUNK_CHARS = 270
DEFAULT_MAX_CHUNK_WORDS = 15
DEFAULT_MAX_TOTAL_CHUNKS = 64
DEFAULT_MAX_EXPANDED_CHARS = 16000


@dataclass(frozen=True, slots=True)
class PinnedFrontendSnapshot:
    """Immutable pinned M03 + M05 snapshot bound for a single F4-A plan preparation."""

    config_revision: str
    model_registry_revision: str
    lexicon_revision: str
    capability_revision: str
    model_revision: str
    voice_profile_id: str
    speaker: str
    seed: int
    language: str
    ode_steps: int
    sample_rate_hz: int
    morph_precheck_enabled: bool
    morph_precheck_pause_ms: int
    freya_path: str
    freya_vocab_path: str
    max_input_chars: int
    max_chunk_chars: int
    max_chunk_words: int
    max_total_chunks: int
    max_expanded_chars: int
    strict_enabled: bool
    lexicon_registry: LexiconRegistry


@dataclass(frozen=True, slots=True)
class SnapshotPinResult:
    """Result of pinning M03 config/model/voice and M05 lexicon snapshots."""

    ok: bool
    snapshot: PinnedFrontendSnapshot | None = None
    reason_code: str = "OK"
    safe_message: str = ""


def _resolve_voice_profile(
    voice_registry: VoiceProfileRegistry,
    *,
    requested_seed: int | None,
    requested_profile_id: str | None,
    flag_map: Mapping[str, bool | str],
    experimental_enabled: bool,
) -> tuple[VoiceProfile | None, str, str]:
    if requested_seed is not None and type(requested_seed) is not int:
        return None, "PROFILE_MISMATCH", "seed must be an exact integer (bool rejected)"

    if requested_profile_id is not None:
        prof = voice_registry.get(requested_profile_id)
        if prof is None:
            return None, "PROFILE_MISMATCH", f"Unknown voice profile: {requested_profile_id}"
        if requested_seed is not None and prof.seed != requested_seed:
            return None, "PROFILE_MISMATCH", "Requested seed does not match requested voice profile"
        if not voice_registry.is_seed_allowed(
            prof.seed,
            feature_flags=flag_map,
            experimental_enabled=experimental_enabled,
        ):
            return None, "PROFILE_MISMATCH", f"Voice profile {prof.profile_id} is disabled by feature flags"
        return prof, "OK", ""

    if requested_seed is not None:
        prof = voice_registry.get_by_seed(requested_seed)
        if prof is None:
            return None, "PROFILE_MISMATCH", f"Unknown voice seed: {requested_seed}"
        if not voice_registry.is_seed_allowed(
            requested_seed,
            feature_flags=flag_map,
            experimental_enabled=experimental_enabled,
        ):
            return None, "PROFILE_MISMATCH", f"Experimental voice seed {requested_seed} is disabled by feature flags"
        return prof, "OK", ""

    baseline = voice_registry.baseline()
    if baseline.seed != LEYLA_BASELINE_SEED:
        return None, "PROFILE_MISMATCH", "Baseline Leyla seed 9 missing"
    return baseline, "OK", ""


def pin_frontend_snapshot(
    *,
    config_snapshot: ConfigSnapshot | None = None,
    model_registry: ModelRegistry | None = None,
    voice_registry: VoiceProfileRegistry | None = None,
    lexicon_registry: LexiconRegistry | None = None,
    requested_seed: int | None = None,
    requested_profile_id: str | None = None,
    experimental_seeds_enabled: bool = False,
    strict_enabled: bool = False,
    freya_vocab_path: str | None = None,
    max_input_chars: int = 4000,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    max_chunk_words: int = DEFAULT_MAX_CHUNK_WORDS,
    max_total_chunks: int = DEFAULT_MAX_TOTAL_CHUNKS,
    max_expanded_chars: int = DEFAULT_MAX_EXPANDED_CHARS,
) -> SnapshotPinResult:
    """
    Pin immutable M03 configuration, model, voice profile, and M05 lexicon snapshots.

    Missing or incompatible model/profile revisions fail explicitly without silent fallback.
    """
    cfg = config_snapshot
    if cfg is None:
        cfg = resolve_configuration().snapshot

    flags = FeatureFlagRegistry.from_snapshot(cfg)
    flag_map = flags.as_primitives()

    mreg = model_registry
    if mreg is None:
        vreg = voice_registry or DEFAULT_VOICE_PROFILE_REGISTRY
        mreg = ModelRegistry.from_snapshot(cfg, voice_profiles=vreg)
    else:
        vreg = voice_registry or mreg.voice_profiles

    tts_models = mreg.by_kind(ModelKind.TTS)
    if not tts_models:
        return SnapshotPinResult(
            ok=False,
            reason_code="MISSING_TTS_MODEL",
            safe_message="ModelRegistry contains no TTS model descriptor",
        )
    tts_desc: ModelDescriptor = tts_models[0]
    if not tts_desc.model_revision or tts_desc.model_revision == "unapproved":
        return SnapshotPinResult(
            ok=False,
            reason_code="INVALID_MODEL_REVISION",
            safe_message="TTS model revision is unapproved or missing",
        )

    if tts_desc.capability is not None and tts_desc.capability.state.value == "UNSUPPORTED":
        return SnapshotPinResult(
            ok=False,
            reason_code="UNSUPPORTED_MODEL_CAPABILITY",
            safe_message="TTS capability state is UNSUPPORTED",
        )

    # Resolve seed: explicit request takes precedence; otherwise honor configured default if non-baseline,
    # defaulting to Leyla baseline seed 9.
    effective_seed_req = requested_seed
    if effective_seed_req is None and requested_profile_id is None:
        cfg_seed = cfg.get("batched_ode_default_seed", LEYLA_BASELINE_SEED)
        if type(cfg_seed) is int and cfg_seed != LEYLA_BASELINE_SEED:
            effective_seed_req = cfg_seed

    profile, prof_code, prof_msg = _resolve_voice_profile(
        vreg,
        requested_seed=effective_seed_req,
        requested_profile_id=requested_profile_id,
        flag_map=flag_map,
        experimental_enabled=experimental_seeds_enabled,
    )
    if profile is None:
        return SnapshotPinResult(ok=False, reason_code=prof_code, safe_message=prof_msg)

    if lexicon_registry is None:
        return SnapshotPinResult(
            ok=False,
            reason_code="MISSING_LEXICON_SNAPSHOT",
            safe_message="M05 LexiconRegistry snapshot is required",
        )

    cap_ver = tts_desc.capability.version if tts_desc.capability and tts_desc.capability.version else tts_desc.version
    capability_revision = f"{tts_desc.model_id}:{cap_ver}:{mreg.model_registry_revision[:16]}"

    freya_path = str(cfg.get("freya_path", "vendor/FreyaTTS"))
    vocab_path = freya_vocab_path or "config/freya_vocab.json"
    morph_enabled = bool(cfg.get("morph_precheck_enabled", True))
    morph_pause_ms = int(cfg.get("morph_precheck_pause_ms", 35))

    pinned = PinnedFrontendSnapshot(
        config_revision=cfg.config_revision,
        model_registry_revision=mreg.model_registry_revision,
        lexicon_revision=lexicon_registry.lexicon_revision,
        capability_revision=capability_revision,
        model_revision=tts_desc.model_revision,
        voice_profile_id=profile.profile_id,
        speaker=profile.speaker,
        seed=profile.seed,
        language=profile.language,
        ode_steps=profile.ode_steps,
        sample_rate_hz=profile.sample_rate_hz,
        morph_precheck_enabled=morph_enabled,
        morph_precheck_pause_ms=morph_pause_ms,
        freya_path=freya_path,
        freya_vocab_path=vocab_path,
        max_input_chars=max_input_chars,
        max_chunk_chars=max_chunk_chars,
        max_chunk_words=max_chunk_words,
        max_total_chunks=max_total_chunks,
        max_expanded_chars=max_expanded_chars,
        strict_enabled=strict_enabled,
        lexicon_registry=lexicon_registry,
    )
    return SnapshotPinResult(ok=True, snapshot=pinned, reason_code="OK")
