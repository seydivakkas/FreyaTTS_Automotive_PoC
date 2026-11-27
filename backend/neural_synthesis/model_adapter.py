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
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from backend.core.model_registry.artifact_verifier import safe_resolve_under_root
from backend.neural_synthesis.config_adapter import (
    BASELINE_CHANNELS,
    BASELINE_LATENT_DIM,
    BASELINE_LATENT_RATE_HZ,
    BASELINE_SAMPLES_PER_FRAME,
    BASELINE_SAMPLE_RATE_HZ,
    PinnedSynthesisSnapshot,
)
from backend.runtime_resources.contracts import (
    HandleOwnership,
    ProviderKind,
    ResidencyState,
)
from backend.runtime_resources.residency import (
    ModelSpec,
    ResidencyHandle,
    ResidencyManager,
    ResidencyPin,
)

DEFAULT_VOCAB_RELATIVE_PATH = "config/freya_vocab.json"
VENDOR_VOCAB_RELATIVE_PATH = "vendor/FreyaTTS/freyatts/char_vocab.json"


@dataclass(frozen=True, slots=True)
class StaticVocabSnapshot:
    """Read-only character vocabulary metadata loaded without torch or model weights."""

    vocab_map: Mapping[str, int]
    vocab_revision: str
    source_path: str


def load_static_char_vocab(
    *,
    repo_root: Path | None = None,
    relative_path: str = DEFAULT_VOCAB_RELATIVE_PATH,
) -> StaticVocabSnapshot:
    """Load Freya character vocabulary passively from disk under confined repo root."""
    root = (repo_root or Path.cwd()).resolve(strict=True)
    resolved = safe_resolve_under_root(root, relative_path)
    raw_bytes = resolved.read_bytes()
    parsed = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("Static vocabulary JSON must be a non-empty mapping")
    clean = {str(k): int(v) for k, v in parsed.items()}
    digest = hashlib.sha256(raw_bytes).hexdigest()
    return StaticVocabSnapshot(
        vocab_map=MappingProxyType(clean),
        vocab_revision=digest,
        source_path=resolved.relative_to(root).as_posix(),
    )


@dataclass(frozen=True, slots=True)
class SynthesisModelHandles:
    """Borrowed or owned neural synthesis handle bundle (DiT + AudioVAE + vocab)."""

    model_id: str
    model_revision: str
    tts_model: Any
    vae: Any
    char_to_id: Mapping[str, int]
    vocab_revision: str
    ownership: HandleOwnership = HandleOwnership.BORROWED
    device: str = "cpu"
    dtype: str = "float32"
    sample_rate_hz: int | None = BASELINE_SAMPLE_RATE_HZ
    channels: int = BASELINE_CHANNELS
    latent_dim: int = BASELINE_LATENT_DIM
    latent_rate_hz: int | None = BASELINE_LATENT_RATE_HZ
    samples_per_frame: int | None = BASELINE_SAMPLES_PER_FRAME
    rng_isolation_mode: str = "ISOLATED_GENERATOR"
    supports_isolated_rng: bool = True

    @property
    def handle_identity(self) -> tuple[int, int]:
        return (id(self.tts_model), id(self.vae))


class ModelResidencyAdapter:
    """
    Single residency authority adapter bridging F5-A to M06 ResidencyManager.

    Preserves shared/borrowed ownership: releasing a session pin never unloads
    a BORROWED or EXTERNAL handle belonging to another session or global Models.
    """

    def __init__(
        self,
        residency_manager: ResidencyManager,
        *,
        model_id: str = "tts-freya",
    ) -> None:
        self._residency = residency_manager
        self.model_id = model_id

    def register_handles(
        self,
        handles: SynthesisModelHandles,
        *,
        vram_bytes: int = 0,
        ownership: HandleOwnership | None = None,
        unloader: Callable[[Any], None] | None = None,
    ) -> ResidencyHandle:
        existing = self._residency.get_handle(handles.model_id)
        if existing is not None:
            return existing
        eff_ownership = ownership or handles.ownership
        spec = ModelSpec(
            model_id=handles.model_id,
            ownership=eff_ownership,
            provider=ProviderKind.PYTORCH,
            vram_bytes=vram_bytes,
            loader=lambda: handles,
            unloader=None if eff_ownership in {HandleOwnership.BORROWED, HandleOwnership.EXTERNAL} else unloader,
        )
        return self._residency.register_model(spec)

    def register_loader(
        self,
        *,
        model_id: str | None = None,
        ownership: HandleOwnership = HandleOwnership.OWNED,
        vram_bytes: int = 0,
        loader: Callable[[], Any],
        unloader: Callable[[Any], None] | None = None,
    ) -> ResidencyHandle:
        mid = model_id or self.model_id
        existing = self._residency.get_handle(mid)
        if existing is not None:
            return existing
        spec = ModelSpec(
            model_id=mid,
            ownership=ownership,
            provider=ProviderKind.PYTORCH,
            vram_bytes=vram_bytes,
            loader=loader,
            unloader=None if ownership in {HandleOwnership.BORROWED, HandleOwnership.EXTERNAL} else unloader,
        )
        return self._residency.register_model(spec)

    async def borrow_pin(
        self,
        snapshot: PinnedSynthesisSnapshot,
    ) -> tuple[ResidencyPin, SynthesisModelHandles]:
        mid = snapshot.model_descriptor.model_id
        pin = await self._residency.acquire_pin(mid)
        handle = self._residency.get_handle(mid)
        if handle is None or handle.raw_handle is None:
            pin.release()
            raise RuntimeError(f"Residency handle unavailable for {mid}")
        raw = handle.raw_handle
        if isinstance(raw, SynthesisModelHandles):
            if raw.model_revision != snapshot.model_descriptor.model_revision:
                pin.release()
                raise ValueError(
                    f"Loaded handle revision {raw.model_revision!r} != pinned {snapshot.model_descriptor.model_revision!r}"
                )
            return pin, raw
        pin.release()
        raise TypeError(f"Unsupported residency raw_handle type: {type(raw).__name__}")

    def state(self, model_id: str | None = None) -> ResidencyState | None:
        return self._residency.get_state(model_id or self.model_id)

    async def release_session_pin(self, pin: ResidencyPin | None) -> bool:
        if pin is None:
            return False
        return pin.release()

    async def unload_if_owned(self, model_id: str | None = None) -> bool:
        mid = model_id or self.model_id
        handle = self._residency.get_handle(mid)
        if handle is None:
            return False
        if handle.spec.ownership in {HandleOwnership.BORROWED, HandleOwnership.EXTERNAL}:
            return False
        return await self._residency.unload(mid)


__all__ = [
    "DEFAULT_VOCAB_RELATIVE_PATH",
    "ModelResidencyAdapter",
    "StaticVocabSnapshot",
    "SynthesisModelHandles",
    "VENDOR_VOCAB_RELATIVE_PATH",
    "load_static_char_vocab",
]
