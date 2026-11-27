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

import copy
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Protocol, runtime_checkable

import numpy as np

from backend.core.contracts.common import StreamRef
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock


class VADIsolationStrategy(StrEnum):
    """Supported VAD recurrent-state isolation mechanisms per ADR-F1-01 & F1-A."""

    STATE_PASSING = "STATE_PASSING"
    ISOLATED_CLONE = "ISOLATED_CLONE"
    UNSUPPORTED_HOLD = "UNSUPPORTED_HOLD"


class VADIsolationUnsupportedError(RuntimeError):
    """Raised when a VAD backend has mutable shared state without safe isolation."""


@dataclass(frozen=True, slots=True)
class VADObservation:
    """Result of evaluating one 512-sample 16 kHz VADWindow."""

    stream_ref: StreamRef
    window_index: int
    start_sample: int
    end_sample_exclusive: int
    valid_samples: int
    ok: bool
    score: float | None
    model_revision: str
    inference_start_ns: int
    inference_end_ns: int
    clock_domain: str
    padded_for_inference: bool = False
    error_code: str | None = None
    error_detail: str = ""


@runtime_checkable
class StatePassingVADBackend(Protocol):
    """Functional VAD backend with explicit immutable/isolated recurrent state passing."""

    model_revision: str

    def initial_state(self) -> Any: ...

    def infer_with_state(self, window_f32: np.ndarray, sample_rate_hz: int, state: Any) -> tuple[float, Any]: ...


@runtime_checkable
class CloneableVADBackend(Protocol):
    """Template VAD backend supporting independent per-stream isolated instances (ADR-F1-01)."""

    model_revision: str

    def clone_isolated(self) -> Any: ...


def validate_vad_score(raw_score: Any) -> float:
    """Validate finite probability-like score in [0.0, 1.0]; reject bool, NaN, Inf, or out-of-range."""
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float, np.floating, np.integer)):
        raise ValueError(f"Invalid VAD score type: {type(raw_score).__name__}")
    val = float(raw_score)
    if not math.isfinite(val) or val < 0.0 or val > 1.0:
        raise ValueError(f"VAD score out of [0, 1] or non-finite: {raw_score!r}")
    return val


def inspect_vad_backend_isolation(backend: Any) -> VADIsolationStrategy:
    """
    Audit a VAD backend for safe per-stream state isolation.
    Never falls back to shared mutable state; returns UNSUPPORTED_HOLD if unsafe.
    """
    if isinstance(backend, StatePassingVADBackend):
        return VADIsolationStrategy.STATE_PASSING
    if isinstance(backend, CloneableVADBackend):
        return VADIsolationStrategy.ISOLATED_CLONE
    if getattr(backend, "supports_isolated_clone", False) and callable(getattr(backend, "new_vad", None)):
        return VADIsolationStrategy.ISOLATED_CLONE
    return VADIsolationStrategy.UNSUPPORTED_HOLD


class SileroTemplateAdapter:
    """
    Wraps an existing CPU Silero TorchScript template (e.g. backend.models.Models.new_vad
    or torch.jit.ScriptModule) for ADR-F1-01 isolated per-stream instance creation.
    Imports torch lazily only when invoked so module import remains passive.
    """

    def __init__(
        self,
        *,
        template_model: Any | None = None,
        clone_fn: Callable[[], Any] | None = None,
        model_revision: str = "silero_vad_6.2.3",
    ) -> None:
        if template_model is None and clone_fn is None:
            raise ValueError("SileroTemplateAdapter requires template_model or clone_fn")
        self._template_model = template_model
        self._clone_fn = clone_fn
        self.model_revision = model_revision

    def clone_isolated(self) -> Any:
        if self._clone_fn is not None:
            inst = self._clone_fn()
        else:
            inst = copy.deepcopy(self._template_model)
        if hasattr(inst, "reset_states") and callable(inst.reset_states):
            inst.reset_states()
        return _SileroInstanceRunner(inst)


class _SileroInstanceRunner:
    """Isolated per-stream Silero TorchScript call wrapper with lazy torch import."""

    def __init__(self, model_instance: Any) -> None:
        self._model = model_instance

    def infer(self, window_f32: np.ndarray, sample_rate_hz: int) -> float:
        import torch

        tensor = torch.from_numpy(np.array(window_f32, dtype=np.float32, copy=True))
        with torch.inference_mode():
            out = self._model(tensor, sample_rate_hz)
        return validate_vad_score(float(out.item()) if hasattr(out, "item") else float(out))

    def reset_states(self) -> None:
        if hasattr(self._model, "reset_states") and callable(self._model.reset_states):
            self._model.reset_states()


class VADEngineAdapter:
    """
    Canonical VAD engine adapter validating backend isolation strategy before creating stream states.
    """

    def __init__(self, backend: Any, *, clock: Clock | None = None) -> None:
        self.strategy = inspect_vad_backend_isolation(backend)
        if self.strategy == VADIsolationStrategy.UNSUPPORTED_HOLD:
            raise VADIsolationUnsupportedError(
                "HOLD: VAD backend lacks documented state-passing or isolated-clone isolation API"
            )
        self._backend = backend
        self.clock: Clock = clock or SystemMonotonicClock()
        self.model_revision: str = getattr(backend, "model_revision", "unknown-vad-revision")

    def create_stream_slot(self) -> tuple[VADIsolationStrategy, Any]:
        """Create an isolated state token or independent model instance for one stream."""
        if self.strategy == VADIsolationStrategy.STATE_PASSING:
            return self.strategy, self._backend.initial_state()
        if isinstance(self._backend, CloneableVADBackend):
            return self.strategy, self._backend.clone_isolated()
        return self.strategy, self._backend.new_vad()

    def infer_slot(
        self,
        slot_state: Any,
        window_f32: np.ndarray,
        sample_rate_hz: int = 16000,
    ) -> tuple[float, Any]:
        """Execute inference on a single stream's isolated slot without touching other streams."""
        if window_f32.shape != (512,) or window_f32.dtype != np.float32:
            raise ValueError("VAD inference requires exact 512-sample float32 window")
        if sample_rate_hz != 16000:
            raise ValueError("VAD inference requires 16000 Hz")
        if not np.all(np.isfinite(window_f32)):
            raise ValueError("Non-finite input window rejected before VAD call")

        if self.strategy == VADIsolationStrategy.STATE_PASSING:
            raw_score, next_state = self._backend.infer_with_state(window_f32, sample_rate_hz, slot_state)
            return validate_vad_score(raw_score), next_state

        if hasattr(slot_state, "infer") and callable(slot_state.infer):
            raw_score = slot_state.infer(window_f32, sample_rate_hz)
        else:
            raw_score = slot_state(window_f32, sample_rate_hz)
        return validate_vad_score(raw_score), slot_state

    def reset_slot(self, slot_state: Any) -> Any:
        """Reset only this stream's isolated state slot."""
        if self.strategy == VADIsolationStrategy.STATE_PASSING:
            return self._backend.initial_state()
        if hasattr(slot_state, "reset_states") and callable(slot_state.reset_states):
            slot_state.reset_states()
            return slot_state
        return self.create_stream_slot()[1]
