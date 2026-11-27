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
from backend.neural_synthesis.latent_initializer import (
    LatentDescriptor,
    LatentInitializationError,
    _extract_array_meta,
)

RNG_PROFILE_REVISION = "f5b-rng-v1"
SUPPORTED_RNG_ALGORITHMS = frozenset({"box_muller_mt19937", "torch_generator"})


@dataclass(frozen=True, slots=True)
class ItemRngSpec:
    """Request-local RNG specification bound to true unpadded item shape."""

    attempt_ref: str
    seed: int
    algorithm: str
    device: str
    draw_order_revision: str
    true_latent_shape: tuple[int, int, int]
    dtype: str = "float32"
    rng_profile_revision: str = RNG_PROFILE_REVISION

    def __repr__(self) -> str:
        return (
            f"ItemRngSpec(attempt_ref={self.attempt_ref!r}, seed={self.seed}, "
            f"algorithm={self.algorithm!r}, device={self.device!r}, "
            f"true_latent_shape={self.true_latent_shape}, dtype={self.dtype!r})"
        )


class IsolatedRngAdapter:
    """
    F5-B request-local RNG adapter.

    Guarantees:
    - Never mutates process-global RNG state (`torch.manual_seed` or `random.seed`).
    - Draws initial latent noise using the item's TRUE validated shape before any padding or stacking.
    - Same item + same seed + same RNG profile + same true shape yields identical initial noise
      regardless of batch order, peer length, peer cancellation, or peer seed.
    """

    def build_spec(
        self,
        *,
        attempt_ref: str,
        seed: int,
        true_frames: int,
        latent_dim: int,
        device: str = "cpu",
        use_torch: bool = False,
        draw_order_revision: str = "btc-row-major-v1",
    ) -> ItemRngSpec:
        if type(seed) is not int or seed < 0 or seed > (2**31 - 1):
            raise LatentInitializationError(
                ErrorInfo(
                    code="INVALID_SEED",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="ItemRngSpec requires strict non-negative 31-bit integer seed",
                    field_name="seed",
                )
            )
        if type(true_frames) is not int or true_frames <= 0:
            raise LatentInitializationError(
                ErrorInfo(
                    code="INVALID_TRUE_FRAMES",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="true_frames must be a positive integer",
                )
            )
        if type(latent_dim) is not int or latent_dim <= 0:
            raise LatentInitializationError(
                ErrorInfo(
                    code="INVALID_LATENT_DIM",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="latent_dim must be a positive integer",
                )
            )
        algorithm = "torch_generator" if use_torch else "box_muller_mt19937"
        return ItemRngSpec(
            attempt_ref=attempt_ref,
            seed=seed,
            algorithm=algorithm,
            device=device,
            draw_order_revision=draw_order_revision,
            true_latent_shape=(1, true_frames, latent_dim),
            dtype="float32",
        )

    def draw_true_latent(
        self,
        *,
        spec: ItemRngSpec,
        decision: DurationDecision,
        snapshot: PinnedSynthesisSnapshot,
        tts_model: Any = None,
        rng_isolation_mode: str = "ISOLATED_GENERATOR",
        override_latent: Any = None,
    ) -> tuple[Any, LatentDescriptor]:
        if not decision.allowed or decision.estimate is None:
            raise LatentInitializationError(
                ErrorInfo(
                    code="DURATION_GUARD_NOT_PASSED",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Cannot draw latent before DurationGuard passes",
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
        if spec.seed != snapshot.seed:
            raise LatentInitializationError(
                ErrorInfo(
                    code="RNG_SEED_MISMATCH",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="ItemRngSpec seed does not match pinned snapshot seed",
                )
            )

        _, true_frames, latent_dim = spec.true_latent_shape
        if true_frames != decision.estimate.effective_frames or latent_dim != snapshot.latent_dim:
            raise LatentInitializationError(
                ErrorInfo(
                    code="RNG_SHAPE_MISMATCH",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="ItemRngSpec shape does not match DurationDecision/snapshot",
                )
            )

        if override_latent is not None:
            latent = override_latent
        elif tts_model is not None and hasattr(tts_model, "sample_initial_latent"):
            latent = tts_model.sample_initial_latent(
                batch_size=1,
                frames=true_frames,
                latent_dim=latent_dim,
                seed=spec.seed,
                device=spec.device,
            )
        elif spec.algorithm == "torch_generator":
            import torch

            gen = torch.Generator(device=spec.device).manual_seed(int(spec.seed))
            latent = torch.randn(1, true_frames, latent_dim, dtype=torch.float32, device=spec.device, generator=gen)
        else:
            import numpy as np

            rng = random.Random(spec.seed)
            total = true_frames * latent_dim
            vals = [0.0] * total
            for idx in range(0, total, 2):
                u1 = max(1e-12, rng.random())
                u2 = rng.random()
                r = math.sqrt(-2.0 * math.log(u1))
                theta = 2.0 * math.pi * u2
                vals[idx] = r * math.cos(theta)
                if idx + 1 < total:
                    vals[idx + 1] = r * math.sin(theta)
            latent = np.array(vals, dtype=np.float32).reshape(1, true_frames, latent_dim)

        shape, dtype, actual_device, finite = _extract_array_meta(latent)
        if shape != spec.true_latent_shape:
            raise LatentInitializationError(
                ErrorInfo(
                    code="INVALID_LATENT_SHAPE",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Latent shape {shape} != expected {spec.true_latent_shape}",
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
        if not actual_device.startswith(spec.device.split(":")[0]):
            raise LatentInitializationError(
                ErrorInfo(
                    code="INVALID_LATENT_DEVICE",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Latent device {actual_device!r} != expected {spec.device!r}",
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

        desc = LatentDescriptor(
            rank=3,
            shape=spec.true_latent_shape,
            dtype="float32",
            device=actual_device,
            layout="BTC",
            valid_lengths=(true_frames,),
            finite=True,
            seed=spec.seed,
            rng_mode=rng_isolation_mode,
            byte_size=true_frames * latent_dim * 4,
        )
        return latent, desc


__all__ = [
    "IsolatedRngAdapter",
    "ItemRngSpec",
    "RNG_PROFILE_REVISION",
    "SUPPORTED_RNG_ALGORITHMS",
]
