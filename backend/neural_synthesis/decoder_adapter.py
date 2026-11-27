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
from typing import Any

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.neural_synthesis.config_adapter import BASELINE_SAMPLE_RATE_HZ
from backend.neural_synthesis.duration_estimator import DurationEstimate
from backend.neural_synthesis.latent_initializer import _is_torch_tensor

MAX_RAW_WAVEFORM_BYTES = 48000 * 60 * 4  # M01 AudioChunk upper bound


class DecoderValidationError(ValueError):
    """Raised when AudioVAE output violates sample rate, layout, dtype, finiteness, or byte bounds."""

    def __init__(self, error_info: ErrorInfo) -> None:
        super().__init__(error_info.safe_message)
        self.error_info = error_info


@dataclass(frozen=True, slots=True)
class DecoderOutputDescriptor:
    """Verified raw decoder output metadata (48 kHz mono FLOAT32_LE, zero DSP)."""

    raw_shape: tuple[int, ...]
    sample_rate_hz: int
    channels: int
    channel_layout: str
    dtype: str
    sample_count: int
    valid_sample_count: int
    byte_length: int
    finite: bool
    contiguous: bool
    ownership: str
    device: str
    trimmed_from_samples: int | None = None


class DecoderAdapter:
    """
    AudioVAE decoder adapter enforcing raw 48 kHz mono FLOAT32_LE output without DSP or resampling.
    """

    def __init__(self, *, max_waveform_bytes: int = MAX_RAW_WAVEFORM_BYTES) -> None:
        self.max_waveform_bytes = max_waveform_bytes

    def decode(
        self,
        *,
        vae: Any,
        latents: Any,
        estimate: DurationEstimate,
        reported_sample_rate_hz: int | None = None,
        allow_baseline_frame_trim: bool = True,
    ) -> tuple[DecoderOutputDescriptor, bytes]:
        if vae is None or not hasattr(vae, "decode"):
            raise DecoderValidationError(
                ErrorInfo(
                    code="VAE_HANDLE_UNAVAILABLE",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message="AudioVAE decoder handle is unavailable",
                )
            )

        meta_rate = reported_sample_rate_hz
        if meta_rate is None:
            meta_rate = getattr(vae, "sample_rate_hz", getattr(vae, "sample_rate", BASELINE_SAMPLE_RATE_HZ))
        if type(meta_rate) is not int or meta_rate != BASELINE_SAMPLE_RATE_HZ:
            raise DecoderValidationError(
                ErrorInfo(
                    code="DECODER_SAMPLE_RATE_MISMATCH",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Decoder sample rate {meta_rate!r} != required 48000 Hz (no resampling in F5)",
                )
            )

        raw_out = self._invoke_decode(vae, latents)
        actual_rate = meta_rate
        if isinstance(raw_out, dict):
            if "sample_rate_hz" in raw_out and raw_out["sample_rate_hz"] != BASELINE_SAMPLE_RATE_HZ:
                raise DecoderValidationError(
                    ErrorInfo(
                        code="DECODER_SAMPLE_RATE_MISMATCH",
                        category=ErrorCategory.VALIDATION,
                        retryable=Retryability.NO,
                        safe_message=f"Decoder output sample rate {raw_out['sample_rate_hz']!r} != 48000 Hz",
                    )
                )
            actual_rate = int(raw_out.get("sample_rate_hz", meta_rate))
            waveform = raw_out["waveform"]
        else:
            waveform = raw_out

        return self.materialize_raw_waveform(
            waveform=waveform,
            sample_rate_hz=actual_rate,
            estimate=estimate,
            allow_baseline_frame_trim=allow_baseline_frame_trim,
        )

    @staticmethod
    def _invoke_decode(vae: Any, latents: Any) -> Any:
        if _is_torch_tensor(latents):
            import torch

            with torch.inference_mode():
                return vae.decode(latents.transpose(1, 2).float())
        # Fake/NumPy path: preserve (B, C, T) convention like VoxCPM2 AudioVAE
        import numpy as np

        arr = np.asarray(latents)
        if arr.ndim == 3:
            return vae.decode(arr.transpose(0, 2, 1))
        return vae.decode(arr)

    def materialize_raw_waveform(
        self,
        *,
        waveform: Any,
        sample_rate_hz: int,
        estimate: DurationEstimate,
        allow_baseline_frame_trim: bool = True,
    ) -> tuple[DecoderOutputDescriptor, bytes]:
        if type(sample_rate_hz) is not int or sample_rate_hz != BASELINE_SAMPLE_RATE_HZ:
            raise DecoderValidationError(
                ErrorInfo(
                    code="DECODER_SAMPLE_RATE_MISMATCH",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Decoder sample rate {sample_rate_hz!r} != 48000 Hz",
                )
            )

        if _is_torch_tensor(waveform):
            device = str(waveform.device)
            arr_raw = waveform.detach().cpu().numpy()
        else:
            import numpy as np

            device = "cpu"
            arr_raw = np.asarray(waveform)

        raw_shape = tuple(int(d) for d in arr_raw.shape)
        mono_1d = self._extract_strict_singleton_mono(arr_raw, raw_shape)

        import numpy as np

        if mono_1d.size == 0:
            raise DecoderValidationError(
                ErrorInfo(
                    code="EMPTY_DECODER_OUTPUT",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message="Decoder produced empty waveform",
                )
            )

        if mono_1d.dtype.kind not in {"f", "i"}:
            raise DecoderValidationError(
                ErrorInfo(
                    code="UNSUPPORTED_DECODER_DTYPE",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message=f"Unsupported decoder output dtype: {mono_1d.dtype}",
                )
            )

        if mono_1d.dtype.kind == "f":
            if not np.isfinite(mono_1d).all():
                raise DecoderValidationError(
                    ErrorInfo(
                        code="NONFINITE_WAVEFORM",
                        category=ErrorCategory.PROVIDER,
                        retryable=Retryability.NO,
                        safe_message="Decoder waveform contains NaN or Inf",
                    )
                )
            f32 = np.ascontiguousarray(mono_1d, dtype="<f4")
        else:
            # Explicit normalized integer -> float32 conversion preserving range semantics
            info = np.iinfo(mono_1d.dtype)
            scale = float(max(abs(info.min), abs(info.max)))
            f32 = np.ascontiguousarray(mono_1d.astype(np.float64) / scale, dtype="<f4")

        if not np.isfinite(f32).all():
            raise DecoderValidationError(
                ErrorInfo(
                    code="POST_CAST_NONFINITE_WAVEFORM",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message="Float32 conversion produced non-finite samples",
                )
            )

        trimmed_from: int | None = None
        if allow_baseline_frame_trim and f32.shape[0] > estimate.expected_samples:
            # Preserve exact existing FreyaTTS / BatchedODEEngine frame-aligned trim
            if f32.shape[0] - estimate.expected_samples < (estimate.samples_per_frame or 1920):
                trimmed_from = int(f32.shape[0])
                f32 = np.ascontiguousarray(f32[: estimate.expected_samples], dtype="<f4")

        sample_count = int(f32.shape[0])
        byte_length = sample_count * 4
        if byte_length > self.max_waveform_bytes:
            raise DecoderValidationError(
                ErrorInfo(
                    code="WAVEFORM_TOO_LARGE",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Decoded waveform bytes {byte_length} exceeds ceiling {self.max_waveform_bytes}",
                )
            )

        payload = f32.tobytes()
        if len(payload) != byte_length:
            raise DecoderValidationError(
                ErrorInfo(
                    code="WAVEFORM_BYTE_MISMATCH",
                    category=ErrorCategory.INTERNAL,
                    retryable=Retryability.NO,
                    safe_message="Serialized FLOAT32_LE byte length mismatch",
                )
            )

        desc = DecoderOutputDescriptor(
            raw_shape=raw_shape,
            sample_rate_hz=BASELINE_SAMPLE_RATE_HZ,
            channels=1,
            channel_layout="MONO",
            dtype="FLOAT32_LE",
            sample_count=sample_count,
            valid_sample_count=sample_count,
            byte_length=byte_length,
            finite=True,
            contiguous=True,
            ownership="OWNED_BYTES",
            device=device,
            trimmed_from_samples=trimmed_from,
        )
        return desc, payload

    def decode_batch_unpadded(
        self,
        *,
        vae: Any,
        unpadded_items: list[tuple[str, Any, DurationEstimate]],
        reported_sample_rate_hz: int | None = None,
        allow_baseline_frame_trim: bool = True,
    ) -> list[tuple[str, DecoderOutputDescriptor, bytes]]:
        """Decode each true unpadded latent independently to prevent cross-item convolutional leakage."""
        results: list[tuple[str, DecoderOutputDescriptor, bytes]] = []
        for member_id, item_latent, estimate in unpadded_items:
            desc, payload = self.decode(
                vae=vae,
                latents=item_latent,
                estimate=estimate,
                reported_sample_rate_hz=reported_sample_rate_hz,
                allow_baseline_frame_trim=allow_baseline_frame_trim,
            )
            results.append((member_id, desc, payload))
        return results

    @staticmethod
    def _extract_strict_singleton_mono(arr: Any, raw_shape: tuple[int, ...]) -> Any:
        """Accept only explicit singleton mono layouts: (T,), (1, T), or (1, 1, T)."""
        if len(raw_shape) == 1:
            return arr
        if len(raw_shape) == 2 and raw_shape[0] == 1:
            return arr[0]
        if len(raw_shape) == 3 and raw_shape[0] == 1 and raw_shape[1] == 1:
            return arr[0, 0]
        raise DecoderValidationError(
            ErrorInfo(
                code="AMBIGUOUS_DECODER_LAYOUT",
                category=ErrorCategory.PROVIDER,
                retryable=Retryability.NO,
                safe_message=f"Rejected ambiguous/multi-item/multi-channel decoder shape {raw_shape}",
            )
        )


__all__ = [
    "DecoderAdapter",
    "DecoderOutputDescriptor",
    "DecoderValidationError",
    "MAX_RAW_WAVEFORM_BYTES",
]
