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
from typing import Any, Sequence

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.neural_synthesis.latent_initializer import _is_torch_tensor

LAYOUT_REVISION = "f5b-layout-v1"
MASK_SEMANTICS_TRUE_IS_VALID = "TRUE_IS_VALID"


class BatchLayoutError(ValueError):
    """Raised when latent/batch layout, padding, or mask invariants are violated."""

    def __init__(self, error_info: ErrorInfo) -> None:
        super().__init__(error_info.safe_message)
        self.error_info = error_info


@dataclass(frozen=True, slots=True)
class LatentLayout:
    """Explicit true-length and padded-length layout for a single batch member."""

    member_id: str
    true_token_length: int
    true_latent_frames: int
    padded_latent_frames: int
    expected_waveform_samples: int
    latent_dim: int
    dtype: str = "float32"
    layout: str = "BTC"
    mask_semantics: str = MASK_SEMANTICS_TRUE_IS_VALID
    pad_value: float = 0.0

    @property
    def pad_frames(self) -> int:
        return self.padded_latent_frames - self.true_latent_frames


@dataclass(frozen=True, slots=True)
class BatchExecutionLayout:
    """Immutable batch execution layout mapping members, masks, and estimated padded peak."""

    batch_id: str
    member_ids: tuple[str, ...]
    layouts: tuple[LatentLayout, ...]
    padded_latent_frames: int
    padded_token_length: int
    latent_dim: int
    total_valid_latent_frames: int
    total_padded_latent_frames: int
    padding_fraction: float
    estimated_padded_latent_bytes: int
    compatibility_key: str
    layout_revision: str = LAYOUT_REVISION
    mask_semantics: str = MASK_SEMANTICS_TRUE_IS_VALID


class BatchLayoutBuilder:
    """
    Constructs verified padded latent batches & masks from true-length per-item latents,
    and extracts true unpadded per-member latents prior to VAE decoding.
    """

    def build_layout(
        self,
        *,
        batch_id: str,
        members: Sequence[tuple[str, int, int, int, int]],
        compatibility_key: str,
        max_batch_size: int = 8,
        max_padded_frames: int = 300,
    ) -> BatchExecutionLayout:
        """
        members: sequence of (member_id, true_token_len, true_latent_frames, expected_waveform_samples, latent_dim)
        """
        if not members:
            raise BatchLayoutError(
                ErrorInfo(
                    code="EMPTY_BATCH_LAYOUT",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="BatchExecutionLayout requires at least one member",
                )
            )
        if len(members) > max_batch_size:
            raise BatchLayoutError(
                ErrorInfo(
                    code="BATCH_SIZE_EXCEEDED",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Batch size {len(members)} exceeds max {max_batch_size}",
                )
            )

        seen_ids: set[str] = set()
        latent_dims: set[int] = set()
        max_lat = 0
        max_tok = 0
        for mid, tok_len, lat_frames, wav_samples, ldim in members:
            if not mid or mid in seen_ids:
                raise BatchLayoutError(
                    ErrorInfo(
                        code="DUPLICATE_OR_EMPTY_MEMBER_ID",
                        category=ErrorCategory.VALIDATION,
                        retryable=Retryability.NO,
                        safe_message="Batch member_id must be non-empty and unique",
                    )
                )
            if (
                type(tok_len) is not int
                or tok_len <= 0
                or type(lat_frames) is not int
                or lat_frames <= 0
                or type(wav_samples) is not int
                or wav_samples <= 0
                or type(ldim) is not int
                or ldim <= 0
            ):
                raise BatchLayoutError(
                    ErrorInfo(
                        code="INVALID_MEMBER_DIMENSIONS",
                        category=ErrorCategory.VALIDATION,
                        retryable=Retryability.NO,
                        safe_message="Member token, latent, waveform, and dim sizes must be positive integers",
                    )
                )
            seen_ids.add(mid)
            latent_dims.add(ldim)
            max_lat = max(max_lat, lat_frames)
            max_tok = max(max_tok, tok_len)

        if len(latent_dims) != 1:
            raise BatchLayoutError(
                ErrorInfo(
                    code="INCOMPATIBLE_LATENT_DIMS",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="All batch members must share the same latent_dim",
                )
            )
        if max_lat > max_padded_frames:
            raise BatchLayoutError(
                ErrorInfo(
                    code="PADDED_FRAMES_EXCEEDED",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Padded latent frames {max_lat} exceeds limit {max_padded_frames}",
                )
            )

        ldim = next(iter(latent_dims))
        layouts = tuple(
            LatentLayout(
                member_id=mid,
                true_token_length=tok_len,
                true_latent_frames=lat_frames,
                padded_latent_frames=max_lat,
                expected_waveform_samples=wav_samples,
                latent_dim=ldim,
            )
            for mid, tok_len, lat_frames, wav_samples, _ in members
        )
        total_valid = sum(l.true_latent_frames for l in layouts)
        total_padded = len(layouts) * max_lat
        padding_fraction = 1.0 - (float(total_valid) / float(total_padded))
        est_bytes = total_padded * ldim * 4

        return BatchExecutionLayout(
            batch_id=batch_id,
            member_ids=tuple(l.member_id for l in layouts),
            layouts=layouts,
            padded_latent_frames=max_lat,
            padded_token_length=max_tok,
            latent_dim=ldim,
            total_valid_latent_frames=total_valid,
            total_padded_latent_frames=total_padded,
            padding_fraction=padding_fraction,
            estimated_padded_latent_bytes=est_bytes,
            compatibility_key=compatibility_key,
        )

    def stack_and_mask(
        self,
        *,
        layout: BatchExecutionLayout,
        item_latents: Sequence[Any],
    ) -> tuple[Any, Any]:
        """
        Stack per-item true-length latents `(1, L_i, C)` into `(B, L_max, C)` with deterministic 0.0 padding,
        returning `(padded_latents, frame_mask)` where `frame_mask` has shape `(B, L_max)` bool (`True` = valid).
        """
        if len(item_latents) != len(layout.layouts):
            raise BatchLayoutError(
                ErrorInfo(
                    code="BATCH_LATENT_COUNT_MISMATCH",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Number of item latents does not match BatchExecutionLayout",
                )
            )

        use_torch = any(_is_torch_tensor(x) for x in item_latents)
        B = len(layout.layouts)
        L_max = layout.padded_latent_frames
        C = layout.latent_dim

        if use_torch:
            import torch

            device = item_latents[0].device
            padded = torch.zeros((B, L_max, C), dtype=torch.float32, device=device)
            frame_mask = torch.zeros((B, L_max), dtype=torch.bool, device=device)
            for row, (lat, mem) in enumerate(zip(item_latents, layout.layouts)):
                if tuple(lat.shape) != (1, mem.true_latent_frames, C):
                    raise BatchLayoutError(
                        ErrorInfo(
                            code="MEMBER_LATENT_SHAPE_MISMATCH",
                            category=ErrorCategory.VALIDATION,
                            retryable=Retryability.NO,
                            safe_message=f"Member {mem.member_id} latent shape {tuple(lat.shape)} != (1, {mem.true_latent_frames}, {C})",
                        )
                    )
                padded[row, : mem.true_latent_frames, :] = lat[0]
                frame_mask[row, : mem.true_latent_frames] = True
            return padded, frame_mask

        import numpy as np

        padded_np = np.zeros((B, L_max, C), dtype=np.float32)
        mask_np = np.zeros((B, L_max), dtype=bool)
        for row, (lat, mem) in enumerate(zip(item_latents, layout.layouts)):
            arr = np.asarray(lat, dtype=np.float32)
            if tuple(arr.shape) != (1, mem.true_latent_frames, C):
                raise BatchLayoutError(
                    ErrorInfo(
                        code="MEMBER_LATENT_SHAPE_MISMATCH",
                        category=ErrorCategory.VALIDATION,
                        retryable=Retryability.NO,
                        safe_message=f"Member {mem.member_id} latent shape {tuple(arr.shape)} != (1, {mem.true_latent_frames}, {C})",
                    )
                )
            padded_np[row, : mem.true_latent_frames, :] = arr[0]
            mask_np[row, : mem.true_latent_frames] = True
        return padded_np, mask_np

    def unpad_latents(
        self,
        *,
        layout: BatchExecutionLayout,
        solved_batch_latents: Any,
    ) -> list[tuple[str, Any]]:
        """Slice each member's solved latent back to `(1, true_latent_frames, C)`."""
        if _is_torch_tensor(solved_batch_latents):
            shape = tuple(int(d) for d in solved_batch_latents.shape)
        else:
            import numpy as np

            solved_batch_latents = np.asarray(solved_batch_latents)
            shape = tuple(int(d) for d in solved_batch_latents.shape)

        expected = (len(layout.layouts), layout.padded_latent_frames, layout.latent_dim)
        if shape != expected:
            raise BatchLayoutError(
                ErrorInfo(
                    code="SOLVED_BATCH_SHAPE_MISMATCH",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message=f"Solved batch latent shape {shape} != expected {expected}",
                )
            )

        out: list[tuple[str, Any]] = []
        for row, mem in enumerate(layout.layouts):
            slc = solved_batch_latents[row : row + 1, : mem.true_latent_frames, :]
            out.append((mem.member_id, slc))
        return out


__all__ = [
    "BatchExecutionLayout",
    "BatchLayoutBuilder",
    "BatchLayoutError",
    "LAYOUT_REVISION",
    "LatentLayout",
    "MASK_SEMANTICS_TRUE_IS_VALID",
]
