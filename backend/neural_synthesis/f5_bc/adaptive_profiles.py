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
from dataclasses import dataclass
from typing import Mapping, Sequence

from backend.core.contracts.common import CapabilityState, ErrorCategory, ErrorInfo, Retryability
from backend.neural_synthesis.config_adapter import BASELINE_ODE_STEPS, BASELINE_SOLVER
from backend.neural_synthesis.solver_adapter import BASELINE_SOLVER_PROFILE, SolverProfile

PROFILE_SELECTOR_REVISION = "f5c-selector-v1"
COST_MODEL_REVISION = "f5c-cost-v1"

CANDIDATE_STEP_COUNTS: tuple[int, ...] = (8, 16, 24, 32, 48)


@dataclass(frozen=True, slots=True)
class DiscreteSolverDescriptor:
    """F5-C discrete ODE profile metadata preserving Euler32 as baseline reference."""

    profile_id: str
    profile_revision: str
    profile: SolverProfile
    capability_state: CapabilityState
    calibration_status: str  # "BASELINE_PINNED" | "CALIBRATED" | "NOT_RUN"
    active_for_live: bool
    quality_floor_score: float | None = None
    max_allowed_for_critical_speech: bool = False


def build_default_profile_catalog() -> dict[str, DiscreteSolverDescriptor]:
    """Return F5-C discrete solver catalog with only Euler32 active by default."""
    catalog: dict[str, DiscreteSolverDescriptor] = {}
    for steps in CANDIDATE_STEP_COUNTS:
        is_base = steps == BASELINE_ODE_STEPS
        pid = f"euler_{steps}"
        prof = (
            BASELINE_SOLVER_PROFILE
            if is_base
            else SolverProfile(
                solver_name=BASELINE_SOLVER,
                steps=steps,
                time_grid_mode="uniform_0_to_1",
                integration_direction="forward_0_to_1",
                guidance_scale=None,
                numeric_precision="float32",
                nfe_expected=steps,
                approved_for_strict=False,
                profile_id=pid,
                profile_revision="f5c-profile-v1",
                calibration_status="NOT_RUN",
                active_for_live=False,
            )
        )
        catalog[pid] = DiscreteSolverDescriptor(
            profile_id=pid,
            profile_revision="f5c-profile-v1",
            profile=prof,
            capability_state=CapabilityState.VERIFIED if is_base else CapabilityState.DECLARED,
            calibration_status="BASELINE_PINNED" if is_base else "NOT_RUN",
            active_for_live=is_base,
            quality_floor_score=1.0 if is_base else None,
            max_allowed_for_critical_speech=is_base,
        )
    return catalog


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Conservative predicted resource/latency estimate (never labeled as measured)."""

    profile_id: str
    latent_frames: int
    batch_size: int
    calibration_version: str
    predicted_queue_ms: float
    predicted_inference_ms: float
    predicted_decoder_ms: float
    predicted_transfer_ms: float
    predicted_peak_bytes: int
    confidence_status: str  # "CALIBRATED_ESTIMATE" | "CONSERVATIVE_HEURISTIC" | "UNAVAILABLE"
    is_estimate: bool = True

    @property
    def total_predicted_ms(self) -> float:
        return (
            self.predicted_queue_ms
            + self.predicted_inference_ms
            + self.predicted_decoder_ms
            + self.predicted_transfer_ms
        )


@dataclass(frozen=True, slots=True)
class ProfileSelection:
    """Deterministic ODE profile selection outcome."""

    requested_profile_id: str | None
    effective_descriptor: DiscreteSolverDescriptor
    candidate_ids: tuple[str, ...]
    cost_estimate: CostEstimate | None
    reason: str
    mode: str  # "BASELINE_ONLY" | "SHADOW" | "ADAPTIVE_OPT_IN"
    shadow_recommended_id: str | None = None


@dataclass(frozen=True, slots=True)
class ControlDisposition:
    """Explicit F4-C -> F5-C/F6-C control ownership disposition without silent clipping."""

    control_id: str
    requested_value: float | str | None
    capability_status: CapabilityState
    assigned_owner: str  # "F5" | "F6" | "NONE"
    planned_effective_value: float | str | None
    applied_setting: float | str | None
    reason: str


class AdaptiveProfileSelector:
    """
    F5-C discrete calibrated ODE profile selector.

    - Preserves Euler32 baseline by default (`mode="BASELINE_ONLY"`).
    - `mode="SHADOW"` computes bounded metadata comparison without extra inference/cache writes.
    - `mode="ADAPTIVE_OPT_IN"` selects lowest predicted completion cost among calibrated,
      live-active profiles that meet quality floor and deadline; critical speech acts
      (e.g. protected values, confirmations, safety) never downgrade below baseline.
    """

    def __init__(
        self,
        *,
        catalog: Mapping[str, DiscreteSolverDescriptor] | None = None,
        mode: str = "BASELINE_ONLY",
        policy_revision: str = PROFILE_SELECTOR_REVISION,
        per_step_ms_per_frame: float = 0.04,
        decoder_ms_per_frame: float = 0.15,
    ) -> None:
        if mode not in {"BASELINE_ONLY", "SHADOW", "ADAPTIVE_OPT_IN"}:
            raise ValueError(f"Unsupported selector mode: {mode!r}")
        self.catalog = dict(catalog) if catalog is not None else build_default_profile_catalog()
        self.mode = mode
        self.policy_revision = policy_revision
        self.per_step_ms_per_frame = per_step_ms_per_frame
        self.decoder_ms_per_frame = decoder_ms_per_frame

    def estimate_cost(
        self,
        *,
        descriptor: DiscreteSolverDescriptor,
        latent_frames: int,
        batch_size: int = 1,
        latent_dim: int = 64,
        queue_ms: float = 0.0,
    ) -> CostEstimate:
        frames = max(1, int(latent_frames))
        bsize = max(1, int(batch_size))
        inf_ms = descriptor.profile.steps * frames * self.per_step_ms_per_frame * (1.0 + 0.15 * (bsize - 1))
        dec_ms = frames * self.decoder_ms_per_frame * bsize
        xfer_ms = 1.0 * bsize
        latent_bytes = bsize * frames * latent_dim * 4
        wav_bytes = bsize * frames * 1920 * 4
        peak_bytes = (8 * 1024 * 1024) + (latent_bytes * 16) + (wav_bytes * 2)
        conf = "CALIBRATED_ESTIMATE" if descriptor.calibration_status in {"BASELINE_PINNED", "CALIBRATED"} else "CONSERVATIVE_HEURISTIC"
        return CostEstimate(
            profile_id=descriptor.profile_id,
            latent_frames=frames,
            batch_size=bsize,
            calibration_version=COST_MODEL_REVISION,
            predicted_queue_ms=max(0.0, float(queue_ms)),
            predicted_inference_ms=inf_ms,
            predicted_decoder_ms=dec_ms,
            predicted_transfer_ms=xfer_ms,
            predicted_peak_bytes=peak_bytes,
            confidence_status=conf,
        )

    def select(
        self,
        *,
        latent_frames: int,
        requested_profile_id: str | None = None,
        is_critical_speech: bool = False,
        remaining_deadline_ms: float | None = None,
        min_quality_floor: float | None = None,
        batch_size: int = 1,
    ) -> ProfileSelection:
        baseline = self.catalog["euler_32"]
        baseline_cost = self.estimate_cost(
            descriptor=baseline,
            latent_frames=latent_frames,
            batch_size=batch_size,
        )

        if self.mode == "BASELINE_ONLY":
            return ProfileSelection(
                requested_profile_id=requested_profile_id,
                effective_descriptor=baseline,
                candidate_ids=("euler_32",),
                cost_estimate=baseline_cost,
                reason="BASELINE_PINNED_DEFAULT",
                mode=self.mode,
            )

        eligible: list[tuple[float, str, DiscreteSolverDescriptor, CostEstimate]] = []
        for pid, desc in self.catalog.items():
            if is_critical_speech and not desc.max_allowed_for_critical_speech:
                continue
            if self.mode == "ADAPTIVE_OPT_IN":
                if not desc.active_for_live or desc.calibration_status not in {"BASELINE_PINNED", "CALIBRATED"}:
                    continue
                if desc.capability_state != CapabilityState.VERIFIED:
                    continue
            if min_quality_floor is not None:
                if desc.quality_floor_score is None or desc.quality_floor_score < min_quality_floor:
                    continue
            cost = self.estimate_cost(descriptor=desc, latent_frames=latent_frames, batch_size=batch_size)
            if remaining_deadline_ms is not None and cost.total_predicted_ms > remaining_deadline_ms:
                continue
            # Tie-break: lowest predicted cost, then prefer baseline, then profile_id
            tie_is_not_base = 0 if pid == "euler_32" else 1
            eligible.append((cost.total_predicted_ms, f"{tie_is_not_base}:{pid}", desc, cost))

        eligible.sort(key=lambda item: (item[0], item[1]))
        cand_ids = tuple(item[2].profile_id for item in eligible) or ("euler_32",)

        if self.mode == "SHADOW":
            shadow_pick = eligible[0][2].profile_id if eligible else "euler_32"
            return ProfileSelection(
                requested_profile_id=requested_profile_id,
                effective_descriptor=baseline,
                candidate_ids=cand_ids,
                cost_estimate=baseline_cost,
                reason="SHADOW_METADATA_COMPARISON_ONLY",
                mode=self.mode,
                shadow_recommended_id=shadow_pick,
            )

        if not eligible:
            return ProfileSelection(
                requested_profile_id=requested_profile_id,
                effective_descriptor=baseline,
                candidate_ids=("euler_32",),
                cost_estimate=baseline_cost,
                reason="NO_ELIGIBLE_CANDIDATE_BASELINE_RETAINED",
                mode=self.mode,
            )

        best_desc = eligible[0][2]
        best_cost = eligible[0][3]
        return ProfileSelection(
            requested_profile_id=requested_profile_id,
            effective_descriptor=best_desc,
            candidate_ids=cand_ids,
            cost_estimate=best_cost,
            reason=f"ADAPTIVE_SELECTED_{best_desc.profile_id.upper()}",
            mode=self.mode,
        )

    @staticmethod
    def resolve_speed_control(
        *,
        requested_speed: float | None,
        native_speed_supported: bool = False,
        f6_wsola_supported: bool = True,
    ) -> ControlDisposition:
        """Assign requested speed to F5, F6, or NONE without double-applying or silent clipping."""
        if requested_speed is None:
            return ControlDisposition(
                control_id="speed_hint",
                requested_value=None,
                capability_status=CapabilityState.VERIFIED,
                assigned_owner="NONE",
                planned_effective_value=None,
                applied_setting=None,
                reason="NO_SPEED_OVERRIDE_REQUESTED",
            )
        if not math.isfinite(float(requested_speed)) or float(requested_speed) <= 0.0:
            return ControlDisposition(
                control_id="speed_hint",
                requested_value=requested_speed,
                capability_status=CapabilityState.UNKNOWN,
                assigned_owner="NONE",
                planned_effective_value=None,
                applied_setting=None,
                reason="INVALID_SPEED_VALUE",
            )
        if native_speed_supported:
            return ControlDisposition(
                control_id="speed_hint",
                requested_value=float(requested_speed),
                capability_status=CapabilityState.VERIFIED,
                assigned_owner="F5",
                planned_effective_value=float(requested_speed),
                applied_setting=float(requested_speed),
                reason="NATIVE_F5_DURATION_CONTROL",
            )
        if f6_wsola_supported and 0.94 <= float(requested_speed) <= 1.06:
            return ControlDisposition(
                control_id="speed_hint",
                requested_value=float(requested_speed),
                capability_status=CapabilityState.DECLARED,
                assigned_owner="F6",
                planned_effective_value=float(requested_speed),
                applied_setting=None,
                reason="DEFERRED_TO_F6_WSOLA",
            )
        return ControlDisposition(
            control_id="speed_hint",
            requested_value=float(requested_speed),
            capability_status=CapabilityState.UNKNOWN,
            assigned_owner="NONE",
            planned_effective_value=None,
            applied_setting=None,
            reason="NO_VERIFIED_NATIVE_OR_F6_RANGE_SUPPORT",
        )


__all__ = [
    "AdaptiveProfileSelector",
    "CANDIDATE_STEP_COUNTS",
    "COST_MODEL_REVISION",
    "ControlDisposition",
    "CostEstimate",
    "DiscreteSolverDescriptor",
    "PROFILE_SELECTOR_REVISION",
    "ProfileSelection",
    "build_default_profile_catalog",
]
