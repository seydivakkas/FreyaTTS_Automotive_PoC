"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from backend.core.configuration.contracts import ConfigSnapshot
from backend.core.contracts.common import CapabilityDescriptor, CapabilityState
from backend.core.model_registry.contracts import (
    ModelArtifactSpec,
    ModelDescriptor,
    ModelKind,
)
from backend.core.model_registry.voice_profiles import (
    DEFAULT_VOICE_PROFILE_REGISTRY,
    VoiceProfileRegistry,
)


def _compute_registry_revision(
    models: Mapping[str, ModelDescriptor],
    voice_registry: VoiceProfileRegistry,
) -> str:
    payload = {
        "models": [
            {
                "model_id": m.model_id,
                "kind": m.kind.value,
                "model_revision": m.model_revision,
                "version": m.version,
                "device": m.device,
                "external_ref": m.external_ref,
                "required": m.required,
                "artifact_path": m.artifact.relative_path if m.artifact else None,
                "artifact_sha256": m.artifact.expected_sha256 if m.artifact else None,
            }
            for _, m in sorted(models.items())
        ],
        "voice_registry_revision": voice_registry.registry_revision,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class ModelRegistry:
    """Passive, immutable registry of models and voice synthesis profiles."""

    def __init__(
        self,
        models: Iterable[ModelDescriptor] = (),
        *,
        voice_profiles: VoiceProfileRegistry = DEFAULT_VOICE_PROFILE_REGISTRY,
    ) -> None:
        by_id: dict[str, ModelDescriptor] = {}
        for desc in models:
            if desc.model_id in by_id:
                raise ValueError(f"Duplicate model_id: {desc.model_id}")
            by_id[desc.model_id] = desc
        self._models = MappingProxyType(by_id)
        self._voice_profiles = voice_profiles
        self._revision = _compute_registry_revision(self._models, self._voice_profiles)

    @property
    def models(self) -> Mapping[str, ModelDescriptor]:
        return self._models

    @property
    def voice_profiles(self) -> VoiceProfileRegistry:
        return self._voice_profiles

    @property
    def model_registry_revision(self) -> str:
        return self._revision

    def get(self, model_id: str) -> ModelDescriptor | None:
        return self._models.get(model_id)

    def by_kind(self, kind: ModelKind) -> tuple[ModelDescriptor, ...]:
        return tuple(m for m in self._models.values() if m.kind == kind)

    def register(self, descriptor: ModelDescriptor) -> "ModelRegistry":
        return ModelRegistry([*self._models.values(), descriptor], voice_profiles=self._voice_profiles)

    @classmethod
    def from_snapshot(
        cls,
        snapshot: ConfigSnapshot,
        *,
        voice_profiles: VoiceProfileRegistry = DEFAULT_VOICE_PROFILE_REGISTRY,
    ) -> "ModelRegistry":
        """Build a passive ModelRegistry from a ConfigSnapshot without importing torch/CUDA/DB."""
        tts_device = str(snapshot.get("tts_device", "cuda"))
        stt_device = str(snapshot.get("stt_device", "cuda"))
        stt_model = str(snapshot.get("stt_model", "large-v3-turbo"))
        stt_compute = str(snapshot.get("stt_compute_type", "float16"))
        ollama_model = str(snapshot.get("ollama_model", "qwen2.5:7b"))
        ollama_gpu_layers = int(snapshot.get("ollama_gpu_layers", 8))
        freya_path = str(snapshot.get("freya_path", "vendor/FreyaTTS"))
        auto_load = bool(snapshot.get("auto_load_models", True))

        sup_mode = str(snapshot.get("supervisor_mode", "off"))
        sup_path = snapshot.get("supervisor_model_path")
        sup_sha = str(snapshot.get("supervisor_model_sha256", "") or "")

        descriptors: list[ModelDescriptor] = [
            ModelDescriptor(
                model_id="tts-freya",
                kind=ModelKind.TTS,
                model_revision=f"freya-tts:{'batched-ode' if snapshot.get('batched_ode_enabled', True) else 'seq'}",
                version="freya-tts-v1",
                device=tts_device,
                external_ref=f"freyavoice/freya-tts@{freya_path}",
                required=auto_load,
                capability=CapabilityDescriptor(
                    name="tts-freya",
                    scope="TTS_SYNTHESIS",
                    state=CapabilityState.DECLARED,
                    version="48khz-ode",
                ),
            ),
            ModelDescriptor(
                model_id="stt-whisper",
                kind=ModelKind.STT,
                model_revision=f"{stt_model}:{stt_compute}",
                version=stt_model,
                device=stt_device,
                external_ref=stt_model,
                required=auto_load,
                capability=CapabilityDescriptor(
                    name="stt-whisper",
                    scope="ASR_TRANSCRIPTION",
                    state=CapabilityState.DECLARED,
                    version=stt_compute,
                ),
            ),
            ModelDescriptor(
                model_id="vad-silero",
                kind=ModelKind.VAD,
                model_revision="silero-vad-jit",
                version="silero-vad",
                device="cpu",
                external_ref="silero_vad.data/silero_vad.jit",
                required=auto_load,
                capability=CapabilityDescriptor(
                    name="vad-silero",
                    scope="VOICE_ACTIVITY_DETECTION",
                    state=CapabilityState.DECLARED,
                ),
            ),
            ModelDescriptor(
                model_id="llm-ollama",
                kind=ModelKind.LLM,
                model_revision=f"{ollama_model}:layers-{ollama_gpu_layers}",
                version=ollama_model,
                device=f"ollama:gpu_layers={ollama_gpu_layers}",
                external_ref=ollama_model,
                required=True,
                capability=CapabilityDescriptor(
                    name="llm-ollama",
                    scope="DIALOGUE_EXTRACTION",
                    state=CapabilityState.DECLARED,
                ),
            ),
        ]

        if sup_path is not None:
            rel_str = sup_path.as_posix() if isinstance(sup_path, Path) else str(sup_path)
            sup_artifact = ModelArtifactSpec(
                model_id="supervisor-ranker",
                kind=ModelKind.SUPERVISOR,
                version="supervisor-ranker-v1",
                relative_path=rel_str,
                expected_sha256=sup_sha or None,
                required=(sup_mode != "off"),
                device_preference="cpu",
            )
            descriptors.append(
                ModelDescriptor(
                    model_id="supervisor-ranker",
                    kind=ModelKind.SUPERVISOR,
                    model_revision=sup_sha or "unapproved",
                    version="supervisor-ranker-v1",
                    device="cpu",
                    artifact=sup_artifact,
                    required=(sup_mode != "off"),
                    capability=CapabilityDescriptor(
                        name="supervisor-ranker",
                        scope=f"SUPERVISOR_{sup_mode.upper()}",
                        state=CapabilityState.DECLARED,
                    ),
                )
            )

        return cls(descriptors, voice_profiles=voice_profiles)
