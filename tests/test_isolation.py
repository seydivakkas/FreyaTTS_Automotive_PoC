"""Test süitinin işletim verisine yazamayacağını doğrular."""

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_DATA = (Path(__file__).resolve().parents[1] / "data").resolve()


def _outside_project_data(path) -> bool:
    return not Path(path).resolve().is_relative_to(PROJECT_DATA)


def _conftest():
    return next(
        module
        for name, module in sys.modules.items()
        if name.endswith("conftest") and hasattr(module, "isolation_errors")
    )


def test_database_engine_is_outside_project_data():
    from backend.db import engine

    assert _outside_project_data(engine.url.database)


def test_runtime_file_defaults_are_outside_project_data():
    from backend.audio_archive_compliance import DEFAULT_ARCHIVE_DIR
    from backend.config import settings
    from backend.outbound_dialer import DEFAULT_SPOOL_BASE_DIR
    from backend.sft_leyla import DEFAULT_MANIFEST_PATH

    for path in (
        settings.data_dir,
        DEFAULT_ARCHIVE_DIR,
        DEFAULT_SPOOL_BASE_DIR,
        DEFAULT_MANIFEST_PATH,
    ):
        assert _outside_project_data(path), path


def test_session_journal_root_is_outside_project_data():
    from backend.milestones import runtime_root

    assert _outside_project_data(runtime_root())


def test_guard_passes_when_isolated():
    assert _conftest().isolation_errors() == []


def test_guard_rejects_real_database(monkeypatch):
    module = _conftest()
    real = SimpleNamespace(url=SimpleNamespace(database=str(PROJECT_DATA / "assistant.db")))
    monkeypatch.setattr(module, "engine", real)
    assert any("veritabanı" in error for error in module.isolation_errors())


def test_guard_rejects_real_data_dir(monkeypatch):
    module = _conftest()
    monkeypatch.setattr(module, "settings", SimpleNamespace(data_dir=PROJECT_DATA))
    assert any("veri dizini" in error for error in module.isolation_errors())
