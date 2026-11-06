"""Test süitini işletim verisinden yalıtır.

Bu dosya tüm test modüllerinden önce yüklenir. Ortam değişkenleri `backend` içe
aktarılmadan önce ayarlanmalıdır; çünkü veritabanı motoru ve varsayılan dizinler
içe aktarma anında belirlenir. Yalıtım kurulamazsa testler hiç çalıştırılmaz.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="freya-tests-")).resolve()
TEST_DB = TEST_ROOT / "assistant.db"

os.environ["DATABASE_URL"] = "sqlite:///" + TEST_DB.as_posix()
os.environ["DATA_DIR"] = str(TEST_ROOT)
os.environ["DEMO_MODE"] = "0"
# Yalnızca test amaçlı gizli değerler (kodda varsayılan gizli anahtar yoktur).
os.environ["WHATSAPP_WEBHOOK_TOKEN"] = "test-webhook-token"
os.environ["AMI_SECRET"] = "test-ami-secret"
os.environ["AUDIO_ARCHIVE_MASTER_KEY"] = "test-archive-master-key"
os.environ["LINK_SIGNING_KEY"] = "test-link-signing-key"

from backend.config import settings  # noqa: E402
from backend.db import Base, engine  # noqa: E402


def isolation_errors() -> list[str]:
    """Testlerin işletim verisine ulaşabileceği yolları döndürür."""
    errors = []
    database = Path(engine.url.database or "").resolve()
    if not database.is_relative_to(TEST_ROOT):
        errors.append(f"veritabanı geçici klasörde değil: {database}")
    data_dir = Path(settings.data_dir).resolve()
    if not data_dir.is_relative_to(TEST_ROOT):
        errors.append(f"veri dizini geçici klasörde değil: {data_dir}")
    return errors


_errors = isolation_errors()
if _errors:
    pytest.exit("Test yalıtımı kurulamadı: " + "; ".join(_errors), returncode=3)

Base.metadata.create_all(engine)


def pytest_unconfigure(config):
    engine.dispose()
    shutil.rmtree(TEST_ROOT, ignore_errors=True)
