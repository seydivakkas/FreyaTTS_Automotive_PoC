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

import importlib.util
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from backend.audio_frontend.resampler import StatefulResampler
from backend.core.contracts.common import CapabilityDescriptor, CapabilityState


@dataclass(frozen=True, slots=True)
class RnnoiseCapability:
    """Explicit capability status for optional native RNNoise alternative."""

    state: CapabilityState
    backend_name: str
    native_rate_hz: int = 48000
    frame_samples: int = 480
    reason: str = "unprobed"

    def to_descriptor(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            name="f0_b_rnnoise_denoiser",
            scope="LOCAL_CPU",
            state=self.state,
            version=None if self.state != CapabilityState.VERIFIED else "native",
            evidence_ref=self.reason,
        )


def probe_rnnoise_capability() -> RnnoiseCapability:
    """
    Passively probe whether a supported RNNoise Python binding is installed.

    Never downloads, installs, or loads native DLLs/models during probe.
    """
    for mod_name in ("rnnoise", "pyrnnoise"):
        if importlib.util.find_spec(mod_name) is not None:
            return RnnoiseCapability(
                state=CapabilityState.DECLARED,
                backend_name=mod_name,
                reason=f"module_found:{mod_name}_unverified_abi",
            )
    return RnnoiseCapability(
        state=CapabilityState.UNSUPPORTED,
        backend_name="none",
        reason="rnnoise_library_not_installed",
    )


class RnnoiseProvider(Protocol):
    """Protocol for an isolated per-stream RNNoise provider (48 kHz, 480-sample frames)."""

    def process_frame_48k(self, frame_48k: np.ndarray) -> tuple[np.ndarray, float | None]: ...
    def reset(self) -> None: ...
    def close(self) -> None: ...


class RnnoiseDenoiserAdapter:
    """
    Optional RNNoise denoiser seam with stateful rate bridging (native <-> 48 kHz <-> native).

    If no verified provider is supplied, capability remains UNSUPPORTED/HOLD and
    never silently substitutes an unreviewed denoiser.
    """

    def __init__(
        self,
        *,
        sample_rate_hz: int,
        provider: RnnoiseProvider | None = None,
    ) -> None:
        self.sample_rate_hz = int(sample_rate_hz)
        self._provider = provider
        self.capability = (
            RnnoiseCapability(
                state=CapabilityState.VERIFIED,
                backend_name="injected_provider",
                reason="provider_injected",
            )
            if provider is not None
            else probe_rnnoise_capability()
        )
        self._up = StatefulResampler(self.sample_rate_hz, 48000, quality="HQ") if provider is not None else None
        self._down = StatefulResampler(48000, self.sample_rate_hz, quality="HQ") if provider is not None else None
        self._fifo_48k = np.zeros(0, dtype=np.float32)
        self._last_vad_prob: float | None = None
        self._closed = False

    @property
    def last_provider_vad_prob(self) -> float | None:
        """Provider-specific metadata only; never authoritative F1 speech state."""
        return self._last_vad_prob

    def reset(self) -> None:
        self._fifo_48k = np.zeros(0, dtype=np.float32)
        self._last_vad_prob = None
        if self._up is not None:
            self._up.reset()
        if self._down is not None:
            self._down.reset()
        if self._provider is not None:
            self._provider.reset()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._up is not None:
            self._up.close()
        if self._down is not None:
            self._down.close()
        if self._provider is not None:
            self._provider.close()

    def process(self, samples: np.ndarray) -> np.ndarray:
        if self._closed:
            raise RuntimeError("RnnoiseDenoiserAdapter is closed")
        arr = np.ascontiguousarray(samples, dtype=np.float32)
        if self._provider is None or self._up is None or self._down is None:
            raise RuntimeError(f"RNNoise unavailable: {self.capability.reason}")
        if len(arr) == 0:
            return arr.copy()

        upsampled = self._up.process(arr)
        self._fifo_48k = np.concatenate((self._fifo_48k, upsampled))
        out_48k_parts: list[np.ndarray] = []
        while len(self._fifo_48k) >= 480:
            block = self._fifo_48k[:480]
            self._fifo_48k = self._fifo_48k[480:]
            denoised_block, vad_prob = self._provider.process_frame_48k(block)
            self._last_vad_prob = vad_prob
            out_48k_parts.append(np.asarray(denoised_block, dtype=np.float32))

        if not out_48k_parts:
            return np.zeros(len(arr), dtype=np.float32)
        out_48k = np.concatenate(out_48k_parts)
        out_native = self._down.process(out_48k)
        if len(out_native) >= len(arr):
            return np.ascontiguousarray(out_native[: len(arr)], dtype=np.float32)
        pad = np.zeros(len(arr) - len(out_native), dtype=np.float32)
        return np.ascontiguousarray(np.concatenate((pad, out_native)), dtype=np.float32)
