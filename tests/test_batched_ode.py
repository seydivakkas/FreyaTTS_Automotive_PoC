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

import asyncio
from unittest.mock import patch
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.batched_ode import (
    LEYLA_SEED,
    SAMPLE_RATE,
    BatchedODEEngine,
    ConcurrentCallController,
    check_voicedness,
)
from backend.main import app
from backend.models import models
from backend.config import settings


@pytest.mark.asyncio
async def test_concurrent_call_controller():
    """Çoklu eşzamanlı çağrı havuzunun kapasite ve kilit mantığını test eder."""
    controller = ConcurrentCallController(max_concurrent=3)
    assert not controller.locked()
    assert controller.active_count == 0

    # 1. Çağrı
    await controller.acquire("call_1")
    assert controller.active_count == 1
    assert not controller.locked()

    # 2. ve 3. Çağrı
    await controller.acquire("call_2")
    await controller.acquire("call_3")
    assert controller.active_count == 3
    assert controller.locked() is True

    # 1 çağrı serbest bırakıldığında kilit açılmalı
    controller.release("call_2")
    assert controller.active_count == 2
    assert controller.locked() is False

    # async with context manager
    async with controller:
        assert controller.active_count == 3
        assert controller.locked() is True
    assert controller.active_count == 2


def test_check_voicedness():
    """Seslilik (voicedness) F0 olasılık kontrolünü test eder."""
    t = np.linspace(0, 0.2, int(SAMPLE_RATE * 0.2), endpoint=False)
    # Periyodik sesli sinyal (220 Hz Leyla F0 tonu)
    voiced_tone = (0.25 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    score_voiced = check_voicedness(voiced_tone, SAMPLE_RATE)
    assert score_voiced >= 0.06, f"Sesli sinyal tespit edilemedi: {score_voiced}"

    # Periyotsuz fısıltı / beyaz gürültü
    unvoiced_noise = (np.random.randn(int(SAMPLE_RATE * 0.2)) * 0.05).astype(np.float32)
    score_noise = check_voicedness(unvoiced_noise, SAMPLE_RATE)
    assert score_noise < 0.15, f"Gürültüye yüksek seslilik verildi: {score_noise}"


@pytest.mark.asyncio
async def test_batched_ode_micro_batching():
    """12 ms mikro-pencerede 8 eşzamanlı yan cümlenin tek bir GPU yığınında çözüldüğünü doğrular."""
    engine = BatchedODEEngine(
        batch_size=8,
        micro_window_ms=12.0,
        steps=32,
        enabled=True,
        allow_sine_fallback=True,
    )

    texts = [
        "Birinci çağrı cümlesi",
        "İkinci müşteri yanıtı",
        "Üçüncü randevu saati",
        "Dördüncü plaka sorgusu",
        "Beşinci ekspertiz paketi",
        "Altıncı lift kontrolü",
        "Yedinci onay mesajı",
        "Sekizinci kapanış selamı",
    ]

    # 8 çağrıyı eşzamanlı olarak kuyruğa gönder
    tasks = [engine.synthesize_clause(txt, seed=LEYLA_SEED) for txt in texts]
    results = await asyncio.gather(*tasks)

    assert len(results) == 8
    for r in results:
        assert isinstance(r, np.ndarray)
        assert len(r) > 0

    metrics = engine.get_metrics()
    # 8 yan cümlenin hepsi 1 tek GPU yığınında (batch_size=8) çözülmüş olmalı
    assert metrics["total_batches_processed"] == 1
    assert metrics["total_clauses_synthesized"] == 8
    assert metrics["peak_batch_utilization"] == 8
    assert metrics["total_audio_seconds"] > 1.0


@pytest.mark.asyncio
async def test_independent_seeds_preserve_f0():
    """Yığındaki her çağrının izole seed ile bağımsız F0 ses kararlılığına sahip olduğunu doğrular."""
    engine = BatchedODEEngine(batch_size=4, micro_window_ms=10.0, enabled=True, allow_sine_fallback=True)

    # Aynı metin iki farklı seed ile sentezlendiğinde
    w_seed9 = await engine.synthesize_clause("Test cümlesi", seed=9)
    w_seed42 = await engine.synthesize_clause("Test cümlesi", seed=42)

    assert len(w_seed9) > 0
    assert len(w_seed42) > 0
    # İki farklı seed ile üretilen dalga formları bağımsız olmalı (tamamen özdeş olmamalı)
    assert not np.array_equal(w_seed9, w_seed42)


@pytest.mark.asyncio
async def test_whisper_collapse_prevention():
    """Fısıltı telafisi seçili ses kimliğini korur."""
    attempts = []

    def mock_synth(text, seed):
        attempts.append(seed)
        # İlk denemede unvoiced gürültü döndür (fısıltı çökmesi simülasyonu)
        if len(attempts) == 1:
            return np.zeros(int(SAMPLE_RATE * 0.2), dtype=np.float32)
        # İkinci denemede sesli sinyal döndür
        t = np.linspace(0, 0.2, int(SAMPLE_RATE * 0.2), endpoint=False)
        return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    engine = BatchedODEEngine(
        batch_size=2,
        micro_window_ms=5.0,
        synth_fallback_fn=mock_synth,
        enabled=True,
    )

    wave = await engine.enqueue_clause("Fısıltı testi", seed=77)
    assert len(wave) > 0
    assert engine.whisper_collapses_prevented >= 1
    assert attempts == [77, 77]


@pytest.mark.asyncio
async def test_cancelled_queue_entry_never_reaches_solver(monkeypatch):
    engine = BatchedODEEngine(batch_size=2, micro_window_ms=100)
    synthesized = []

    def solve(batch):
        synthesized.extend(item.text for item in batch)
        return [np.ones(16, dtype=np.float32) for item in batch]

    monkeypatch.setattr(engine, "_solve_ode_batch", solve)
    stale = asyncio.create_task(engine.enqueue_clause("Eski parça"))
    await asyncio.sleep(0)
    stale.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stale

    await asyncio.wait_for(engine.enqueue_clause("Geçerli parça"), timeout=1)
    assert synthesized == ["Geçerli parça."]


def test_default_engine_and_controller_params():
    """Motor batch boyutu, eşzamanlılık kapasitesi ve Leyla tohum değerini doğrular."""
    engine = BatchedODEEngine(batch_size=8)
    ctrl = ConcurrentCallController(max_concurrent=50)
    assert engine.batch_size == 8
    assert ctrl.capacity == 50
    assert LEYLA_SEED == 9


def test_batched_ode_rest_api_endpoints():
    """FastAPI Batched ODE konfigürasyon, metrik ve benchmark uç noktalarını test eder."""
    client = TestClient(app)
    auth_headers = {"Authorization": "Basic YWRtaW46c2VjcmV0"}

    orig_batch_size = settings.batched_ode_batch_size
    orig_max_calls = settings.max_concurrent_calls
    orig_micro_window = settings.batched_ode_micro_window_ms
    orig_steps = settings.batched_ode_steps
    try:
        with patch("backend.main.settings.admin_password", "secret"):
            # 1. GET /api/batched-ode/config
            get_res = client.get("/api/batched-ode/config", headers=auth_headers)
            assert get_res.status_code == 200
            cfg = get_res.json()
            assert "batch_size" in cfg
            assert "max_concurrent_calls" in cfg
            assert cfg["batch_size"] == 8

            # 2. POST /api/batched-ode/config
            post_res = client.post(
                "/api/batched-ode/config",
                json={
                    "enabled": True,
                    "batch_size": 16,
                    "micro_window_ms": 15.0,
                    "max_concurrent_calls": 60,
                    "steps": 32,
                },
                headers=auth_headers,
            )
            assert post_res.status_code == 200
            data = post_res.json()
            assert data["config"]["batch_size"] == 16
            assert data["config"]["max_concurrent_calls"] == 60

            # 3. GET /api/batched-ode/metrics
            metrics_res = client.get("/api/batched-ode/metrics", headers=auth_headers)
            assert metrics_res.status_code == 200
            m = metrics_res.json()
            assert "total_batches_processed" in m
            assert "active_calls_count" in m

            # 4. POST /api/batched-ode/benchmark
            bench_res = client.post(
                "/api/batched-ode/benchmark",
                json={"concurrency": 4, "seed": 9},
                headers=auth_headers,
            )
            assert bench_res.status_code == 200
            b_data = bench_res.json()
            assert b_data["status"] == "success"
            assert b_data["concurrency"] == 4
            assert b_data["total_audio_seconds"] > 0.5
            assert "audio_seconds_per_wall_second" in b_data
    finally:
        settings.batched_ode_batch_size = orig_batch_size
        settings.max_concurrent_calls = orig_max_calls
        settings.batched_ode_micro_window_ms = orig_micro_window
        settings.batched_ode_steps = orig_steps


@pytest.mark.asyncio
async def test_models_synth_integration_with_batched_ode():
    """Models.synth çağrısının BatchedODEEngine üzerinden çalıştığını doğrular."""
    from backend.batched_ode import BatchedODEEngine

    engine = BatchedODEEngine(batch_size=4, micro_window_ms=5.0, enabled=True, allow_sine_fallback=True)
    orig_engine = getattr(models, "batched_ode_engine", None)
    try:
        models.batched_ode_engine = engine

        # models.synth çağrısı
        wav = await models.synth("Merhaba, ekspertiz randevunuz oluşturuldu.", seed=9)
        assert isinstance(wav, np.ndarray)
        assert len(wav) > 0
        assert engine.total_batches_processed >= 1
    finally:
        models.batched_ode_engine = orig_engine



@pytest.mark.asyncio
async def test_sinus_yedek_bayrak_olmadan_hata_verir():
    """Gerçek model yokken sinüs sesi konuşma diye üretilmez."""
    engine = BatchedODEEngine(batch_size=2, micro_window_ms=5.0, enabled=True)
    with pytest.raises(RuntimeError, match="yapay sinüs"):
        await engine.enqueue_clause("Merhaba", seed=9)


@pytest.mark.asyncio
async def test_yedek_fonksiyon_seed_anahtar_sozcukle_verilir():
    """Satıcı _synth_one(text, steps=32, seed=None) imzasında seed 'steps'e kaymamalı."""
    gorulen = {}

    def tek(text, steps=32, seed=None):
        gorulen["steps"] = steps
        gorulen["seed"] = seed
        t = np.linspace(0, 0.2, int(SAMPLE_RATE * 0.2), endpoint=False)
        return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    engine = BatchedODEEngine(batch_size=1, micro_window_ms=5.0, synth_fallback_fn=tek)
    await engine.enqueue_clause("Seed testi", seed=77)
    assert gorulen == {"steps": 32, "seed": 77}


@pytest.mark.asyncio
async def test_bozuk_oge_yigindaki_digerlerini_dusurmez():
    """Yığın hata verirse öğeler tek tek yeniden denenir; yalnızca bozuk olan hata alır."""

    def tek(text, seed=None):
        if "BOZUK" in text:
            raise ValueError("Model sözlüğünde olmayan karakterler: {'#'}")
        t = np.linspace(0, 0.2, int(SAMPLE_RATE * 0.2), endpoint=False)
        return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    engine = BatchedODEEngine(batch_size=3, micro_window_ms=5.0, synth_fallback_fn=tek)
    sonuc = await asyncio.gather(
        engine.enqueue_clause("iyi bir", seed=9),
        engine.enqueue_clause("BOZUK cümle", seed=9),
        engine.enqueue_clause("iyi iki", seed=9),
        return_exceptions=True,
    )
    assert isinstance(sonuc[0], np.ndarray)
    assert isinstance(sonuc[1], ValueError)
    assert isinstance(sonuc[2], np.ndarray)


@pytest.mark.asyncio
async def test_models_synth_batched_yol_devre_kesiciden_gecer():
    """Yığınlı yol TTS devre kesicisini (success/failure/allow) kullanır."""
    from backend.models import Models

    m = Models()

    class Motor:
        enabled = True
        hata = None

        async def synthesize_clause(self, text, seed=None):
            if self.hata:
                raise self.hata
            return np.ones(10, np.float32)

    m.batched_ode_engine = Motor()
    await m.synth("a")
    assert m.synth_count == 1 and m.breakers["tts"].failures == 0

    m.batched_ode_engine.hata = RuntimeError("gpu")
    for _ in range(3):
        with pytest.raises(RuntimeError, match="gpu"):
            await m.synth("a")
    # Eşik aşıldı: devre açık, motor çağrılmadan reddedilir.
    with pytest.raises(RuntimeError, match="beklemede"):
        await m.synth("a")
