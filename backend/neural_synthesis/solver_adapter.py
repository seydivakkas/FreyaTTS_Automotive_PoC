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
from backend.neural_synthesis.config_adapter import BASELINE_ODE_STEPS, BASELINE_SOLVER
from backend.neural_synthesis.encoder_adapter import EncodedCondition
from backend.neural_synthesis.latent_initializer import LatentDescriptor, _extract_array_meta, _is_torch_tensor


class SolverValidationError(ValueError):
    """Raised when solver configuration violates approved Euler32 baseline policy."""

    def __init__(self, error_info: ErrorInfo) -> None:
        super().__init__(error_info.safe_message)
        self.error_info = error_info


class SolverExecutionError(RuntimeError):
    """Raised when ODE integration fails or produces partial/non-finite latents."""

    def __init__(self, error_info: ErrorInfo, *, uncertain_device_state: bool = False) -> None:
        super().__init__(error_info.safe_message)
        self.error_info = error_info
        self.uncertain_device_state = uncertain_device_state


@dataclass(frozen=True, slots=True)
class SolverProfile:
    """Immutable baseline/discrete Euler ODE solver profile."""

    solver_name: str = BASELINE_SOLVER
    steps: int = BASELINE_ODE_STEPS
    time_grid_mode: str = "uniform_0_to_1"
    integration_direction: str = "forward_0_to_1"
    guidance_scale: float | None = None
    numeric_precision: str = "float32"
    nfe_expected: int = BASELINE_ODE_STEPS
    approved_for_strict: bool = True
    profile_id: str = "euler_32"
    profile_revision: str = "f5a-baseline-v1"
    calibration_status: str = "BASELINE_PINNED"
    active_for_live: bool = True

    def time_grid(self) -> tuple[float, ...]:
        return tuple(i / self.steps for i in range(self.steps))


BASELINE_SOLVER_PROFILE = SolverProfile()


@dataclass(frozen=True, slots=True)
class SolverExecutionResult:
    """Result of completed ODE integration (never returned for partial solver work)."""

    latents: Any
    profile: SolverProfile
    nfe_evaluated: int
    completed_steps: int
    finite: bool


def validate_solver_profile(
    solver_name: str = BASELINE_SOLVER,
    steps: int = BASELINE_ODE_STEPS,
    *,
    strict: bool = True,
    legacy_alternative_approved: bool = False,
) -> SolverProfile:
    """Validate ODE solver profile; strict mode permits only baseline Euler 32-step."""
    if not isinstance(solver_name, str) or not solver_name.strip():
        raise SolverValidationError(
            ErrorInfo(
                code="INVALID_SOLVER_NAME",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Solver name must be non-empty string",
                field_name="solver",
            )
        )
    if type(steps) is not int or steps < 1 or steps > 256:
        raise SolverValidationError(
            ErrorInfo(
                code="INVALID_SOLVER_STEPS",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Solver steps must be an integer in [1, 256]",
                field_name="ode_steps",
            )
        )

    is_baseline = solver_name == BASELINE_SOLVER and steps == BASELINE_ODE_STEPS
    if strict and not is_baseline:
        raise SolverValidationError(
            ErrorInfo(
                code="UNAPPROVED_SOLVER_PROFILE",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message=f"Strict baseline permits Euler/32 only (requested {solver_name}/{steps})",
                field_name="solver",
            )
        )
    if not strict and not is_baseline and not legacy_alternative_approved:
        raise SolverValidationError(
            ErrorInfo(
                code="UNAPPROVED_LEGACY_SOLVER",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Alternative legacy solver requires explicit legacy authorization",
                field_name="solver",
            )
        )

    return SolverProfile(
        solver_name=solver_name,
        steps=steps,
        time_grid_mode="uniform_0_to_1",
        integration_direction="forward_0_to_1",
        guidance_scale=None,
        numeric_precision="float32",
        nfe_expected=steps,
        approved_for_strict=is_baseline,
    )


class SolverAdapter:
    """Executes baseline Euler32 ODE integration on the borrowed/owned DiT model handle."""

    def solve(
        self,
        *,
        tts_model: Any,
        latent: Any,
        latent_desc: LatentDescriptor,
        encoded: EncodedCondition,
        profile: SolverProfile = BASELINE_SOLVER_PROFILE,
        strict: bool = True,
        frame_mask: Any = None,
    ) -> SolverExecutionResult:
        if strict and not profile.approved_for_strict:
            raise SolverValidationError(
                ErrorInfo(
                    code="UNAPPROVED_SOLVER_PROFILE",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Strict execution requires approved Euler32 baseline profile",
                )
            )
        if not latent_desc.finite:
            raise SolverValidationError(
                ErrorInfo(
                    code="NONFINITE_LATENT",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Cannot run ODE solver on non-finite initial latent",
                )
            )

        if hasattr(tts_model, "solve_ode"):
            try:
                out = tts_model.solve_ode(
                    latent=latent,
                    encoded=encoded,
                    profile=profile,
                )
            except Exception as exc:
                uncertain = bool(getattr(exc, "uncertain_device_state", False))
                raise SolverExecutionError(
                    ErrorInfo(
                        code="UNCERTAIN_DEVICE_STATE" if uncertain else "ODE_PROVIDER_FAILURE",
                        category=ErrorCategory.PROVIDER,
                        retryable=Retryability.NO if uncertain else Retryability.UNKNOWN,
                        safe_message=f"ODE integration failed before completion: {type(exc).__name__}",
                    ),
                    uncertain_device_state=uncertain,
                ) from exc
            if isinstance(out, dict):
                latents = out["latents"]
                nfe = int(out.get("nfe_evaluated", profile.steps))
                completed = int(out.get("completed_steps", profile.steps))
            else:
                latents = out
                nfe = profile.steps
                completed = profile.steps
        elif _is_torch_tensor(latent) and callable(tts_model):
            import torch

            x = latent
            steps = profile.steps
            nfe = 0
            completed = 0
            try:
                with torch.inference_mode():
                    for step_idx in range(steps):
                        t_step = torch.full((latent_desc.shape[0],), step_idx / steps, device=x.device)
                        vt = tts_model(x, t_step, encoded.context, frame_mask, encoded.char_mask)
                        nfe += 1
                        x = x + vt / steps
                        completed += 1
                latents = x
            except Exception as exc:
                uncertain = bool(getattr(exc, "uncertain_device_state", False))
                raise SolverExecutionError(
                    ErrorInfo(
                        code="UNCERTAIN_DEVICE_STATE" if uncertain else "ODE_PROVIDER_FAILURE",
                        category=ErrorCategory.PROVIDER,
                        retryable=Retryability.NO if uncertain else Retryability.UNKNOWN,
                        safe_message=f"PyTorch Euler ODE failed at step {completed}/{steps}: {type(exc).__name__}",
                    ),
                    uncertain_device_state=uncertain,
                ) from exc
        else:
            raise SolverExecutionError(
                ErrorInfo(
                    code="SOLVER_HANDLE_UNSUPPORTED",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message="TTS model handle supports neither solve_ode nor PyTorch forward integration",
                )
            )

        if completed != profile.steps:
            raise SolverExecutionError(
                ErrorInfo(
                    code="PARTIAL_ODE_RESULT_REJECTED",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message=f"Partial ODE output rejected ({completed}/{profile.steps} steps)",
                )
            )

        shape, dtype, _, finite = _extract_array_meta(latents)
        if shape != latent_desc.shape or dtype != "float32" or not finite:
            raise SolverExecutionError(
                ErrorInfo(
                    code="INVALID_SOLVER_OUTPUT",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message="Solved latent failed shape, float32 dtype, or finiteness verification",
                )
            )

        return SolverExecutionResult(
            latents=latents,
            profile=profile,
            nfe_evaluated=nfe,
            completed_steps=completed,
            finite=True,
        )


__all__ = [
    "BASELINE_SOLVER_PROFILE",
    "SolverAdapter",
    "SolverExecutionError",
    "SolverExecutionResult",
    "SolverProfile",
    "SolverValidationError",
    "validate_solver_profile",
]
