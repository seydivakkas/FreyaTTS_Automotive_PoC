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
os.environ["AUTO_LOAD_MODELS"] = "0"
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

Base.metadata.create_all(bind=engine)


def pytest_unconfigure(config):
    engine.dispose()
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture
def real_ami():
    """Gerçek Asterisk'e bağlıymış gibi davranan sahte AMI (MockAMIClient varsayılanı 'gerçek değil')."""
    from backend.ami import MockAMIClient, get_ami_client, set_ami_client

    previous = get_ami_client()
    fake = MockAMIClient()
    fake.is_real = True
    set_ami_client(fake)
    yield fake
    set_ami_client(previous)


@pytest.fixture(autouse=True)
def fake_llm(request, monkeypatch):
    """H01.01 (HF02): `llm` işaretli olmayan testlerde canlı Ollama'ya hiç gidilmez.

    `Models._chat` sahte LLM ile değiştirilir (varsayılan: erişilemez, yani
    Ollama'sız CI ile aynı davranış) ve LLM/TTS devre kesicileri her test için
    sıfırlanır; böylece bir testin bağlantı hataları diğerinin devre kesicisini
    açık bırakmaz. Yanıt gereken test `fake_llm.reply({...})` çağırır.
    """
    if request.node.get_closest_marker("llm"):
        yield None
        return
    from automotive_voice.adapters.lifecycle.breaker import CircuitBreaker
    from backend.models import models
    from tests.fakes.fake_llm import FakeLLM

    fake = FakeLLM()
    monkeypatch.setattr(models, "_chat", fake.chat)
    monkeypatch.setattr(
        models,
        "breakers",
        {name: CircuitBreaker(threshold=3, cooldown_ns=10_000_000_000) for name in ("tts", "llm")},
    )
    yield fake
