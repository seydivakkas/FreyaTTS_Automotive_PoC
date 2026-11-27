"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from backend.core.configuration.contracts import ConfigSnapshot
from backend.core.contracts.common import MetricSample, MetricStatus
from backend.core.model_registry.artifact_verifier import (
    PathEscapeError,
    safe_resolve_under_root,
    verify_artifact,
)
from backend.core.model_registry.contracts import (
    ArtifactStatus,
    ModelKind,
    PreflightCheckItem,
    PreflightReport,
    PreflightState,
)
from backend.core.model_registry.registry import ModelRegistry

_OPTIONAL_PACKAGE_BY_MODEL = {
    "tts-freya": "faster_whisper",  # checked passively via find_spec only when requested
}


def _check_freya_source_tree(snapshot: ConfigSnapshot, base_dir: Path) -> PreflightCheckItem:
    raw_freya_path = str(snapshot.get("freya_path", "vendor/FreyaTTS"))
    auto_load = bool(snapshot.get("auto_load_models", True))
    try:
        resolved = safe_resolve_under_root(base_dir, raw_freya_path)
    except PathEscapeError as exc:
        return PreflightCheckItem(
            target_id="tts-freya-source",
            kind=ModelKind.TTS,
            state=PreflightState.BLOCKED,
            artifact_status=ArtifactStatus.PATH_REJECTED,
            reason=str(exc),
        )

    pkg_dir = resolved / "freyatts"
    if pkg_dir.exists() and pkg_dir.is_dir():
        return PreflightCheckItem(
            target_id="tts-freya-source",
            kind=ModelKind.TTS,
            state=PreflightState.READY,
            artifact_status=ArtifactStatus.VERIFIED,
            reason="FreyaTTS source tree present (read-only check; no weights loaded)",
        )

    return PreflightCheckItem(
        target_id="tts-freya-source",
        kind=ModelKind.TTS,
        state=PreflightState.BLOCKED if auto_load else PreflightState.DEGRADED,
        artifact_status=ArtifactStatus.MISSING,
        reason=f"FreyaTTS source tree missing at {resolved.as_posix()}",
    )


def run_offline_preflight(
    snapshot: ConfigSnapshot,
    registry: ModelRegistry | None = None,
    *,
    base_dir: Path | str | None = None,
    check_packages: bool = False,
) -> PreflightReport:
    """
    Execute read-only offline preflight checks against configuration and registered models.

    Guarantees:
    - Never loads model weights (torch, joblib, Whisper, FreyaTTS are never imported or executed).
    - Never opens network connections or database sessions.
    """
    reg = registry if registry is not None else ModelRegistry.from_snapshot(snapshot)
    root = Path(base_dir) if base_dir is not None else Path.cwd()

    items: list[PreflightCheckItem] = [_check_freya_source_tree(snapshot, root)]

    for model in sorted(reg.models.values(), key=lambda m: m.model_id):
        if model.artifact is not None:
            res = verify_artifact(
                model_id=model.model_id,
                base_dir=root,
                relative_path=model.artifact.relative_path,
                expected_sha256=model.artifact.expected_sha256,
                require_digest=model.required,
            )
            if res.is_valid:
                state = PreflightState.READY
                reason = "Artifact SHA-256 verified offline without loading weights"
            elif res.status in {
                ArtifactStatus.PATH_REJECTED,
                ArtifactStatus.HASH_MISMATCH,
                ArtifactStatus.UNAPPROVED,
            }:
                state = PreflightState.BLOCKED
                reason = res.error.safe_message if res.error else res.status.value
            else:
                state = PreflightState.BLOCKED if model.required else PreflightState.DEGRADED
                reason = res.error.safe_message if res.error else res.status.value

            metrics: tuple[MetricSample, ...] = ()
            if res.size_bytes is not None:
                metrics = (
                    MetricSample(
                        name="artifact_size_bytes",
                        value=float(res.size_bytes),
                        unit="bytes",
                        observation_scope="SERVER",
                        status=MetricStatus.MEASURED,
                    ),
                )
            items.append(
                PreflightCheckItem(
                    target_id=model.model_id,
                    kind=model.kind,
                    state=state,
                    artifact_status=res.status,
                    reason=reason,
                    metrics=metrics,
                )
            )
            continue

        if check_packages:
            pkg_name = {
                ModelKind.STT: "faster_whisper",
                ModelKind.VAD: "silero_vad",
            }.get(model.kind)
            if pkg_name is not None:
                found = importlib.util.find_spec(pkg_name) is not None
                items.append(
                    PreflightCheckItem(
                        target_id=model.model_id,
                        kind=model.kind,
                        state=PreflightState.READY if found else PreflightState.DEGRADED,
                        artifact_status=ArtifactStatus.NOT_CHECKED,
                        reason=f"Package {pkg_name!r} spec {'found' if found else 'not found'}",
                    )
                )
                continue

        items.append(
            PreflightCheckItem(
                target_id=model.model_id,
                kind=model.kind,
                state=PreflightState.READY,
                artifact_status=ArtifactStatus.NOT_CHECKED,
                reason="Passive descriptor registered (external/lazy dependency)",
            )
        )

    states = {item.state for item in items}
    if PreflightState.BLOCKED in states:
        overall = PreflightState.BLOCKED
    elif PreflightState.DEGRADED in states:
        overall = PreflightState.DEGRADED
    else:
        overall = PreflightState.READY

    return PreflightReport(
        overall_state=overall,
        config_revision=snapshot.config_revision,
        model_registry_revision=reg.model_registry_revision,
        items=tuple(items),
        checked_offline=True,
        weights_loaded=False,
    )
