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

import math
import random
from dataclasses import dataclass
from typing import Any

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.neural_synthesis.config_adapter import PinnedSynthesisSnapshot
from backend.neural_synthesis.duration_guard import DurationDecision


class LatentInitializationError(ValueError):
    """Raised when RNG isolation, seed, shape, dtype, or finiteness checks fail."""

    def __init__(self, error_info: ErrorInfo) -> None:
        super().__init__(error_info.safe_message)
        self.error_info = error_info


@dataclass(frozen=True, slots=True)
class LatentDescriptor:
    """Safe metadata describing an initialized latent tensor (never logs latent values)."""

    rank: int
    shape: tuple[int, int, int]
    dtype: str
    device: str
    layout: str
    valid_lengths: tuple[int, ...]
    finite: bool
    seed: int
    rng_mode: str
    byte_size: int

    def __repr__(self) -> str:
        return (
            f"LatentDescriptor(shape={self.shape}, dtype={self.dtype!r}, "
            f"device={self.device!r}, seed={self.seed}, rng_mode={self.rng_mode!r}, finite={self.finite})"
        )


def _is_torch_tensor(obj: Any) -> bool:
    return type(obj).__module__.startswith("torch")


def _extract_array_meta(obj: Any) -> tuple[tuple[int, ...], str, str, bool]:
    """Inspect shape, dtype string, device string, and finiteness without copying or logging values."""
    if _is_torch_tensor(obj):
        import torch

        shape = tuple(int(d) for d in obj.shape)
        dtype = str(obj.dtype).replace("torch.", "")
        device = str(obj.device)
        finite = bool(torch.isfinite(obj).all().item())
        return shape, dtype, device, finite

    import numpy as np

    arr = np.asarray(obj)
    shape = tuple(int(d) for d in arr.shape)
    dtype = str(arr.dtype)
    finite = bool(np.isfinite(arr).all()) if arr.size > 0 else False
    return shape, dtype, "cpu", finite


class LatentInitializer:
    """
    Seeded latent noise initializer preserving Leyla voice identity and strict RNG isolation.

    - Uses isolated per-request generators (no process-global torch.manual_seed/random.seed).
    - Holds strict execution if provider reports unisolated global RNG state.
    - Validates shape (1, frames, latent_dim), float32 dtype, device, and finiteness.
    """

    def initialize(
        self,
        *,
        decision: DurationDecision,
        snapshot: PinnedSynthesisSnapshot,
        tts_model: Any = None,
        device: str = "cpu",
        rng_isolation_mode: str = "ISOLATED_GENERATOR",
        use_torch: bool | None = None,
        override_latent: Any = None,
    ) -> tuple[Any, LatentDescriptor]:
        if not decision.allowed or decision.estimate is None:
            raise LatentInitializationError(
                ErrorInfo(
                    code="DURATION_GUARD_NOT_PASSED",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Cannot initialize latent before DurationGuard passes",
                )
            )

        seed = snapshot.seed
        if type(seed) is not int or seed < 0:
            raise LatentInitializationError(
                ErrorInfo(
                    code="INVALID_SEED",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Latent initialization requires strict non-negative integer seed",
                    field_name="seed",
                )
            )

        if rng_isolation_mode == "UNISOLATED":
            raise LatentInitializationError(
                ErrorInfo(
                    code="UNISOLATED_RNG_HOLD",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="RNG isolation cannot be guaranteed on strict path; affected mode held",
                )
            )

        frames = decision.estimate.effective_frames
        latent_dim = snapshot.latent_dim
        expected_shape = (1, frames, latent_dim)
        expected_bytes = frames * latent_dim * 4

        if override_latent is not None:
            latent = override_latent
        elif tts_model is not None and hasattr(tts_model, "sample_initial_latent"):
            latent = tts_model.sample_initial_latent(
                batch_size=1,
                frames=frames,
                latent_dim=latent_dim,
                seed=seed,
                device=device,
            )
        elif use_torch:
            import torch

            gen = torch.Generator(device=device).manual_seed(int(seed))
            latent = torch.randn(1, frames, latent_dim, dtype=torch.float32, device=device, generator=gen)
        else:
            import numpy as np

            # Isolated deterministic per-request generator using seeded Box-Muller normal values
            rng = random.Random(seed)
            total = frames * latent_dim
            vals = [0.0] * total
            for idx in range(0, total, 2):
                u1 = max(1e-12, rng.random())
                u2 = rng.random()
                r = math.sqrt(-2.0 * math.log(u1))
                theta = 2.0 * math.pi * u2
                vals[idx] = r * math.cos(theta)
                if idx + 1 < total:
                    vals[idx + 1] = r * math.sin(theta)
            latent = np.array(vals, dtype=np.float32).reshape(1, frames, latent_dim)

        shape, dtype, actual_device, finite = _extract_array_meta(latent)
        if len(shape) != 3 or shape != expected_shape:
            raise LatentInitializationError(
                ErrorInfo(
                    code="INVALID_LATENT_SHAPE",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Latent shape {shape} != expected {expected_shape}",
                )
            )
        if dtype != "float32":
            raise LatentInitializationError(
                ErrorInfo(
                    code="INVALID_LATENT_DTYPE",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Latent dtype {dtype!r} != 'float32'",
                )
            )
        if not actual_device.startswith(device.split(":")[0]):
            raise LatentInitializationError(
                ErrorInfo(
                    code="INVALID_LATENT_DEVICE",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Latent device {actual_device!r} != expected {device!r}",
                )
            )
        if not finite:
            raise LatentInitializationError(
                ErrorInfo(
                    code="NONFINITE_LATENT",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message="Initialized latent tensor contains NaN or Inf",
                )
            )

        descriptor = LatentDescriptor(
            rank=3,
            shape=expected_shape,
            dtype="float32",
            device=actual_device,
            layout="BTC",
            valid_lengths=(frames,),
            finite=True,
            seed=seed,
            rng_mode=rng_isolation_mode,
            byte_size=expected_bytes,
        )
        return latent, descriptor


__all__ = [
    "LatentDescriptor",
    "LatentInitializationError",
    "LatentInitializer",
]
