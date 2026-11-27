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
from typing import Any

from backend.audio_frontend.dispatcher import F1BoundaryDispatcher
from backend.audio_frontend.stream_state import StreamAudioState, StreamStateRegistry
from backend.core.contracts.common import StreamRef
from backend.core.runtime.resource_ledger import LeaseState


@dataclass(frozen=True, slots=True)
class CorePreflightResult:
    """Result of verifying accepted M08/Core Integration prerequisites before F0-A execution."""

    ok: bool
    status: str  # "PASS", "HOLD", "FAIL"
    core_run_id: str | None
    errors: tuple[str, ...] = ()


def verify_core_integration_preflight(
    repo_root: Path,
    *,
    core_run_id: str | None = "20261126T004342Z",
) -> CorePreflightResult:
    """
    Verify accepted Core Foundation Integration Gate (CG00-CG11 PASS, core_integration_ready=true)
    and evidence SHA-256 integrity without starting services or models.
    """
    if not core_run_id:
        return CorePreflightResult(False, "HOLD", None, ("CORE_RUN_ID_MISSING",))

    root = Path(repo_root).resolve()
    acc_path = root / "docs" / "freya2" / "core_integration" / core_run_id / "CORE_ACCEPTANCE_MATRIX.json"
    ev_dir = root / "evidence" / "core_integration" / core_run_id
    hashes_path = ev_dir / "artifact_hashes.json"
    manifest_path = ev_dir / "manifest.json"

    if not acc_path.exists() or not hashes_path.exists() or not manifest_path.exists():
        return CorePreflightResult(False, "HOLD", core_run_id, ("CORE_EVIDENCE_MISSING",))

    try:
        acc = json.loads(acc_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return CorePreflightResult(False, "FAIL", core_run_id, (f"CORE_MATRIX_UNREADABLE:{type(exc).__name__}",))

    errors: list[str] = []
    if acc.get("core_integration_status") != "PASS" or acc.get("core_integration_ready") is not True:
        errors.append("CORE_INTEGRATION_NOT_READY")
    gates = acc.get("gates", {})
    for idx in range(12):
        gid = f"CG{idx:02d}"
        if gates.get(gid) != "PASS":
            errors.append(f"CORE_GATE_NOT_PASS:{gid}")

    try:
        hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
        for rel, expected_sha in hashes.items():
            target = (root / rel).resolve()
            if not target.is_relative_to(root):
                errors.append(f"CORE_HASH_PATH_ESCAPE:{rel}")
                continue
            if not target.is_file():
                errors.append(f"CORE_HASH_TARGET_MISSING:{rel}")
                continue
            h = hashlib.sha256()
            with target.open("rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
            if h.hexdigest() != expected_sha:
                errors.append(f"CORE_HASH_MISMATCH:{rel}")
    except Exception as exc:
        errors.append(f"CORE_HASH_VERIFY_ERROR:{type(exc).__name__}")

    if errors:
        return CorePreflightResult(False, "FAIL", core_run_id, tuple(errors))
    return CorePreflightResult(True, "PASS", core_run_id, ())


class AudioFrontendLifecycle:
    """
    Coordinates M02 ResourceLease in-flight tracking, quarantine-on-close,
    exact-once cleanup, and idempotent stream/session shutdown.
    """

    def __init__(
        self,
        registry: StreamStateRegistry,
        dispatcher: F1BoundaryDispatcher,
    ) -> None:
        self.registry = registry
        self.dispatcher = dispatcher

    def enter_in_flight(self, state: StreamAudioState) -> bool:
        """Mark worker in-flight on stream lease; returns False if stream closed."""
        with state._lock:
            if state.closed or state.quarantined:
                return False
            state.in_flight_count += 1
            self.registry.session_ctx.ledger.mark_in_flight(state.lease_id)
            return True

    def exit_in_flight(self, state: StreamAudioState) -> None:
        """
        Complete worker turn; if stream closed while in-flight and last worker finishes,
        perform exact-once release of quarantined resources.
        """
        should_release = False
        with state._lock:
            state.in_flight_count = max(0, state.in_flight_count - 1)
            if state.closed and state.in_flight_count == 0 and not state.release_completed:
                should_release = True
        if should_release:
            self.registry.session_ctx.ledger.release(state.lease_id)
        elif not state.closed and state.in_flight_count == 0:
            # Return lease from IN_FLIGHT back to OWNED while stream remains open
            lease = self.registry.session_ctx.ledger._leases.get(state.lease_id)
            if lease is not None and lease.state == LeaseState.IN_FLIGHT:
                lease.state = LeaseState.OWNED

    def close_stream(self, stream_ref: StreamRef, *, reason: str = "normal_close") -> bool:
        """Idempotent close for one stream epoch; quarantines lease if worker is still in-flight."""
        self.dispatcher.clear_stream_epoch(stream_ref)
        return self.registry.close_stream(stream_ref, reason=reason)

    def close_all(self, *, reason: str = "session_close") -> int:
        """Idempotent cleanup across all streams in session."""
        self.dispatcher.clear_all()
        return self.registry.close_all(reason=reason)
