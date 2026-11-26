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

# HF02: independent CI-only Python socket audit. Internal TestClient/mocks
# do not open network sockets; real service and external attempts are blocked.
# Synthetic loopback listeners bound by this process are the only TCP exception.
_NETWORK_GUARD = os.environ.get("FREYA_HERMETIC_NETWORK_GUARD") == "1"
_network_counts = {"allowed_synthetic": 0, "blocked": 0}
_network_denials = []
if _NETWORK_GUARD:
    import ipaddress
    import socket
    import sys
    import weakref

    _original_bind = socket.socket.bind
    _synthetic_listeners = weakref.WeakSet()
    _live_ports = {5038, 5060, 5061, 8088, 9092, 11434}

    def _loopback(host):
        if host in (None, "", "localhost"):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def _tracked_bind(sock, address):
        result = _original_bind(sock, address)
        if isinstance(address, tuple) and _loopback(address[0]):
            bound = sock.getsockname()
            if isinstance(bound, tuple) and bound[1] not in _live_ports:
                _synthetic_listeners.add(sock)
        return result

    socket.socket.bind = _tracked_bind

    def _deny(event):
        import traceback

        _network_counts["blocked"] += 1
        # Record only source coordinates; do not log network addresses or payloads.
        frames = traceback.extract_stack(limit=24)[:-1]
        coordinates = " -> ".join(
            f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in frames
        )
        _network_denials.append(f"HF02 denied {event}; test={os.environ.get('PYTEST_CURRENT_TEST', '<collection>')}; stack={coordinates}")
        raise RuntimeError("HF02: external/live network attempt blocked")

    def _audit_network(event, args):
        if event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex"):
            if not _loopback(args[0]):
                _deny(event)
        elif event in ("socket.connect", "socket.sendto"):
            address = args[1]
            if not isinstance(address, tuple) or not _loopback(address[0]):
                _deny(event)
            port = address[1]
            if port in _live_ports:
                _deny(event)
            # Only a still-open loopback socket bound by this test process.
            for listener in list(_synthetic_listeners):
                try:
                    bound = listener.getsockname()
                    if listener.fileno() >= 0 and isinstance(bound, tuple) and bound[1] == port:
                        _network_counts["allowed_synthetic"] += 1
                        return
                except OSError:
                    continue
            _deny(event)

    sys.addaudithook(_audit_network)


def pytest_sessionfinish(session, exitstatus):
    if _NETWORK_GUARD:
        print(
            "\nHF02 Python socket audit: "
            f"blocked_live_or_external_attempts={_network_counts['blocked']}; "
            f"allowed_synthetic_connections={_network_counts['allowed_synthetic']}"
        )
        for denial in _network_denials:
            print(denial)
        if _network_counts["blocked"]:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


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
