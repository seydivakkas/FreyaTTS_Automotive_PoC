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

import asyncio
import os
import shutil
import sqlite3
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


class PathConfinementError(ValueError):
    """Raised when a path escapes the allowed root or traverses a symlink/reparse point."""


class SideEffectDeniedError(PermissionError):
    """Raised when test code attempts an unallowlisted outbound network or external provider call."""


FORBIDDEN_HEAVY_MODULES: frozenset[str] = frozenset({
    "torch",
    "torchaudio",
    "faster_whisper",
    "ctranslate2",
    "freyatts",
    "pyaudio",
    "sounddevice",
})


def resolve_confined_path(root: Path, candidate: str | Path, *, allow_missing: bool = False) -> Path:
    """Resolve `candidate` strictly beneath `root`, rejecting symlinks, reparse points, and traversal."""
    root_resolved = root.resolve(strict=True)
    raw = Path(candidate)
    if raw.is_absolute():
        joined = raw
    else:
        joined = root_resolved / raw

    # Reject any symlink or Windows reparse point along components beneath root
    parts = raw.parts
    if not raw.is_absolute():
        probe = root_resolved
        for part in parts:
            if part in ("", "."):
                continue
            if part == "..":
                raise PathConfinementError(f"Parent traversal rejected: {candidate!r}")
            probe = probe / part
            if probe.exists() and (probe.is_symlink() or _is_reparse_point(probe)):
                raise PathConfinementError(f"Symlink/reparse point rejected: {probe}")
    elif joined.exists() and (joined.is_symlink() or _is_reparse_point(joined)):
        raise PathConfinementError(f"Symlink/reparse point rejected: {joined}")

    resolved = joined.resolve(strict=not allow_missing)
    if not resolved.is_relative_to(root_resolved):
        raise PathConfinementError(f"Path {resolved} escapes confined root {root_resolved}")
    return resolved


def _is_reparse_point(path: Path) -> bool:
    try:
        st = os.lstat(path)
        attrs = getattr(st, "st_file_attributes", 0)
        return bool(attrs & 0x0400)  # FILE_ATTRIBUTE_REPARSE_POINT on Windows
    except OSError:
        return False


@dataclass(frozen=True, slots=True)
class BlockedAttempt:
    target: str
    reason_code: str
    channel: str


class OutboundGuard:
    """Explicit test-only network & endpoint policy guard (deny-by-default)."""

    def __init__(self, *, allowlisted_targets: Iterable[str] = ()) -> None:
        self._allowlist = frozenset(allowlisted_targets)
        self.blocked_attempts: list[BlockedAttempt] = []

    def check_target(self, url_or_host: str, *, channel: str = "network") -> None:
        parsed = urlparse(url_or_host if "://" in url_or_host else f"tcp://{url_or_host}")
        host = (parsed.hostname or "").lower()
        port = parsed.port
        host_port = f"{host}:{port}" if port is not None else host

        if host_port in self._allowlist or url_or_host in self._allowlist:
            return

        if host in {"127.0.0.1", "localhost", "::1"}:
            reason = "DENIED_UNALLOWLISTED_LOOPBACK"
        else:
            reason = "DENIED_OUTBOUND_EXTERNAL"

        self.blocked_attempts.append(BlockedAttempt(target=host_port or "<empty>", reason_code=reason, channel=channel))
        raise SideEffectDeniedError(f"{reason}: target={host_port!r}")


class IsolatedSQLiteHandle:
    """Isolated temporary SQLite database handle with WAL + foreign_keys pragmas."""

    def __init__(self, db_path: Path) -> None:
        raw = str(db_path).strip()
        if not raw or raw == ":memory:" or raw.startswith("file::memory:"):
            raise ValueError("IsolatedSQLiteHandle requires an on-disk temporary file path")
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connections: list[sqlite3.Connection] = []

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=FULL")
        self._connections.append(conn)
        return conn

    def close_all(self) -> int:
        closed = 0
        for conn in self._connections:
            try:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                conn.close()
                closed += 1
            except sqlite3.Error:
                pass
        self._connections.clear()
        return closed

    def active_connections(self) -> int:
        alive = 0
        for conn in self._connections:
            try:
                conn.execute("SELECT 1")
                alive += 1
            except sqlite3.Error:
                pass
        return alive


@dataclass
class OwnedResourceTracker:
    """Tracks only harness-owned tasks, threads, DB handles, and temp dirs for clean teardown."""

    tasks: list[asyncio.Task[Any]] = field(default_factory=list)
    threads: list[threading.Thread] = field(default_factory=list)
    db_handles: list[IsolatedSQLiteHandle] = field(default_factory=list)
    temp_dirs: list[Path] = field(default_factory=list)
    leases: list[Any] = field(default_factory=list)

    def register_task(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        self.tasks.append(task)
        return task

    def register_thread(self, thread: threading.Thread) -> threading.Thread:
        self.threads.append(thread)
        return thread

    def register_db(self, db: IsolatedSQLiteHandle) -> IsolatedSQLiteHandle:
        self.db_handles.append(db)
        return db

    def register_temp_dir(self, path: Path) -> Path:
        self.temp_dirs.append(path)
        return path

    def register_lease(self, lease: Any) -> Any:
        self.leases.append(lease)
        return lease

    async def cleanup_async(self) -> dict[str, Any]:
        for task in self.tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
        surviving_tasks = sum(1 for t in self.tasks if not t.done())
        self.tasks.clear()
        sync_report = self.cleanup_sync()
        sync_report["surviving_tasks"] = surviving_tasks
        sync_report["clean"] = (
            surviving_tasks == 0
            and sync_report["surviving_threads"] == 0
            and sync_report["surviving_db_connections"] == 0
            and sync_report["surviving_leases"] == 0
        )
        return sync_report

    def cleanup_sync(self) -> dict[str, Any]:
        for lease in self.leases:
            if hasattr(lease, "release_physical") and not getattr(lease, "is_released", False):
                try:
                    lease.release_physical()
                except Exception:
                    pass
        surviving_leases = sum(
            1 for lease in self.leases if hasattr(lease, "is_released") and not getattr(lease, "is_released")
        )
        self.leases.clear()

        for db in self.db_handles:
            db.close_all()
        surviving_db = sum(db.active_connections() for db in self.db_handles)
        self.db_handles.clear()

        for th in self.threads:
            if th.is_alive():
                th.join(timeout=1.0)
        surviving_threads = sum(1 for th in self.threads if th.is_alive())
        self.threads.clear()

        for td in self.temp_dirs:
            if td.exists():
                shutil.rmtree(td, ignore_errors=True)
        self.temp_dirs.clear()

        return {
            "surviving_tasks": 0,
            "surviving_threads": surviving_threads,
            "surviving_db_connections": surviving_db,
            "surviving_leases": surviving_leases,
            "clean": surviving_threads == 0 and surviving_db == 0 and surviving_leases == 0,
        }


class IsolationSandbox:
    """Per-run isolated sandbox holding confined temp root, DB factory, outbound guard, and cleanup tracker."""

    def __init__(
        self,
        *,
        run_id: str,
        base_dir: Path | None = None,
        allowlisted_targets: Iterable[str] = (),
        production_db_paths: Iterable[Path] = (),
    ) -> None:
        self.run_id = run_id
        if base_dir is not None:
            base_dir.mkdir(parents=True, exist_ok=True)
            self.root = Path(tempfile.mkdtemp(prefix=f"freya-m08-{run_id}-", dir=str(base_dir))).resolve()
        else:
            self.root = Path(tempfile.mkdtemp(prefix=f"freya-m08-{run_id}-")).resolve()
        self.guard = OutboundGuard(allowlisted_targets=allowlisted_targets)
        self.tracker = OwnedResourceTracker()
        self.tracker.register_temp_dir(self.root)
        self._production_db_paths = tuple(p.resolve() for p in production_db_paths)

    def path(self, relative_path: str | Path, *, allow_missing: bool = True) -> Path:
        return resolve_confined_path(self.root, relative_path, allow_missing=allow_missing)

    def create_isolated_db(self, filename: str = "test_isolated.db") -> IsolatedSQLiteHandle:
        db_path = self.path(filename, allow_missing=True)
        resolved = db_path.resolve()
        for prod in self._production_db_paths:
            if resolved == prod:
                raise PathConfinementError(f"Refusing to open production DB path: {prod}")
        handle = IsolatedSQLiteHandle(db_path)
        self.tracker.register_db(handle)
        return handle

    def cleanup(self) -> dict[str, Any]:
        return self.tracker.cleanup_sync()

    async def cleanup_async(self) -> dict[str, Any]:
        return await self.tracker.cleanup_async()


def audit_import_closure(
    loaded_module_names: Iterable[str],
    *,
    forbidden: frozenset[str] = FORBIDDEN_HEAVY_MODULES,
) -> list[str]:
    """Return any forbidden heavy/network/GPU modules present in an import closure."""
    loaded = set(loaded_module_names)
    return sorted(mod for mod in forbidden if mod in loaded or any(m.startswith(f"{mod}.") for m in loaded))
