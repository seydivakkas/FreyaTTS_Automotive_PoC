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

import json
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.session_context import SessionContext


class PrerequisiteCheckStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class F1PreflightResult:
    status: PrerequisiteCheckStatus
    core_gate_run_id: str | None
    f0_gate_run_id: str | None
    missing_or_failed: tuple[str, ...]
    note: str = ""


def check_f1_a_prerequisites(
    repo_root: Path,
    *,
    core_run_id: str,
    f0_run_id: str | None = None,
    require_f0_gate: bool = True,
) -> F1PreflightResult:
    """
    Validate Core Integration Gate (CG00-CG11) and F0-A acceptance gate (G00-G15)
    before authorizing F1-A execution. Returns HOLD on missing/stale prerequisites without writing.
    """
    issues: list[str] = []
    core_matrix = repo_root / "docs" / "freya2" / "core_integration" / core_run_id / "CORE_ACCEPTANCE_MATRIX.json"
    if not core_matrix.exists():
        issues.append(f"MISSING_CORE_GATE:{core_matrix.as_posix()}")
    else:
        data = json.loads(core_matrix.read_text(encoding="utf-8"))
        if data.get("core_integration_ready") is not True or data.get("core_integration_status") != "PASS":
            issues.append("CORE_INTEGRATION_NOT_READY")
        gates = data.get("gates", {})
        for idx in range(12):
            gid = f"CG{idx:02d}"
            if gates.get(gid) != "PASS":
                issues.append(f"CORE_GATE_NOT_PASS:{gid}")

    resolved_f0_run = f0_run_id
    if require_f0_gate:
        f0_root = repo_root / "docs" / "freya2" / "f0_a"
        if resolved_f0_run is None:
            if f0_root.exists():
                dirs = sorted(p.name for p in f0_root.iterdir() if p.is_dir())
                if len(dirs) == 1:
                    resolved_f0_run = dirs[0]
                elif len(dirs) > 1:
                    issues.append("CONFLICTING_F0_A_RUNS")
                else:
                    issues.append("MISSING_F0_A_ACCEPTANCE_RUN")
            else:
                issues.append("MISSING_F0_A_DOC_ROOT")

        if resolved_f0_run is not None:
            f0_matrix = f0_root / resolved_f0_run / "ACCEPTANCE_MATRIX.json"
            if not f0_matrix.exists():
                issues.append(f"MISSING_F0_A_MATRIX:{f0_matrix.as_posix()}")
            else:
                fdata = json.loads(f0_matrix.read_text(encoding="utf-8"))
                if fdata.get("f0_a_ready") is not True:
                    issues.append("F0_A_READY_FALSE")
                fgates = fdata.get("gates", {})
                for idx in range(16):
                    gid = f"G{idx:02d}"
                    if fgates.get(gid) != "PASS":
                        issues.append(f"F0_A_GATE_NOT_PASS:{gid}")

    if issues:
        return F1PreflightResult(
            status=PrerequisiteCheckStatus.HOLD,
            core_gate_run_id=core_run_id,
            f0_gate_run_id=resolved_f0_run,
            missing_or_failed=tuple(issues),
            note="HOLD: prerequisites incomplete; zero source writes performed",
        )
    return F1PreflightResult(
        status=PrerequisiteCheckStatus.ACCEPTED,
        core_gate_run_id=core_run_id,
        f0_gate_run_id=resolved_f0_run,
        missing_or_failed=(),
        note="ACCEPTED",
    )


class F1StreamLifecycle:
    """
    M02-bridged input stream lifecycle manager.

    Distinguishes output generation cancellation (which NEVER resets active input VAD state)
    from input revocation / disconnect / idempotent stream close.
    """

    def __init__(
        self,
        *,
        session_context: SessionContext | None = None,
        input_scope: CancellationScope | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._session_context = session_context
        self._input_scope = input_scope or (
            session_context.root_scope.child_scope("f1.input") if session_context is not None else None
        )
        self._output_cancellations: int = 0
        self._input_revoked: bool = False
        self._closed: bool = False
        self._close_reason: str | None = None

    @property
    def is_input_active(self) -> bool:
        with self._lock:
            if self._closed or self._input_revoked:
                return False
            if self._input_scope is not None and self._input_scope.is_cancel_requested:
                return False
            if self._session_context is not None and self._session_context.root_scope.is_cancel_requested:
                return False
            return True

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def output_cancellations(self) -> int:
        with self._lock:
            return self._output_cancellations

    def notify_output_generation_cancelled(self) -> None:
        """
        Record output TTS/playback cancellation.
        Intentionally does NOT reset or revoke the active input VAD stream.
        """
        with self._lock:
            self._output_cancellations += 1

    def revoke_input(self, reason: str = "input_revoked") -> None:
        with self._lock:
            self._input_revoked = True
            if self._input_scope is not None:
                self._input_scope.request_cancel(reason)

    def close(self, reason: str = "normal_close") -> bool:
        """Idempotent stream close; returns True on first close, False on subsequent calls."""
        with self._lock:
            if self._closed:
                return False
            self._closed = True
            self._input_revoked = True
            self._close_reason = reason
            if self._input_scope is not None:
                self._input_scope.request_cancel(reason)
            return True
