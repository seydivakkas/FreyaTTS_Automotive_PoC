# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.

import base64
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.pause_breath_cleaner import (
    PauseBreathCleaner,
    TelephonyAudioCachePool,
    TOP_25_AUTOMOTIVE_PHRASES,
    pause_breath_cleaner,
    telephony_audio_cache,
)


@pytest.fixture
def test_cleaner() -> PauseBreathCleaner:
    return PauseBreathCleaner(
        sample_rate=8000,
        fade_ms=10.0,
        comfort_noise_dbfs=-58.0,
        breath_threshold_ratio=0.15,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret")
    creds = base64.b64encode(b"admin:secret").decode("ascii")
    return {"Authorization": f"Basic {creds}"}


def test_clean_waveform_edges_normal(test_cleaner: PauseBreathCleaner):
    sr = 8000
    t = np.linspace(0, 0.5, int(sr * 0.5), endpoint=False)
    # Sine wave
    wav = 0.5 * np.sin(2 * np.pi * 440 * t)
    # Add a high-amplitude spike at the very beginning (simulating breath puff)
    wav[:10] = 0.95

    res = test_cleaner.clean_waveform_edges(wav, sample_rate=sr, fade_ms=10.0)

    assert res.sample_rate == sr
    assert len(res.cleaned_audio) > 0
    assert len(res.cleaned_audio) <= len(wav)
    assert res.breath_spike_detected is True
    # Edges should be smoothly tapered (close to 0 at the boundaries)
    assert abs(res.cleaned_audio[0]) < 0.1
    assert abs(res.cleaned_audio[-1]) < 0.1


def test_clean_waveform_edges_short_and_empty(test_cleaner: PauseBreathCleaner):
    empty_wav = np.array([], dtype=np.float32)
    res_empty = test_cleaner.clean_waveform_edges(empty_wav)
    assert len(res_empty.cleaned_audio) == 0

    short_wav = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    res_short = test_cleaner.clean_waveform_edges(short_wav)
    assert len(res_short.cleaned_audio) == 3


def test_splice_clauses_with_clean_pause(test_cleaner: PauseBreathCleaner):
    sr = 8000
    c1 = np.ones(800, dtype=np.float32) * 0.3  # 100 ms
    c2 = np.ones(800, dtype=np.float32) * 0.3  # 100 ms

    pause_ms = 150.0  # 150 ms = 1200 samples
    spliced = test_cleaner.splice_clauses_with_clean_pause(
        [c1, c2], pause_duration_ms=pause_ms, sample_rate=sr, add_comfort_noise=True
    )

    expected_len = len(c1) + int(sr * pause_ms / 1000.0) + len(c2)
    assert len(spliced) == expected_len

    # Middle pause region should contain comfort noise with very low energy (-58 dBFS is ~0.0012)
    pause_region = spliced[len(c1) : len(c1) + int(sr * pause_ms / 1000.0)]
    rms = np.sqrt(np.mean(pause_region**2))
    assert 0.0001 < rms < 0.02


def test_splice_clauses_empty_and_single(test_cleaner: PauseBreathCleaner):
    empty_spliced = test_cleaner.splice_clauses_with_clean_pause([])
    assert len(empty_spliced) == 0

    single = np.ones(400, dtype=np.float32) * 0.2
    single_spliced = test_cleaner.splice_clauses_with_clean_pause([single])
    assert len(single_spliced) == len(single)


def test_telephony_audio_cache_pool():
    pool = TelephonyAudioCachePool(sample_rate=8000)
    # Sentezleyici yokken sahte (sinüs) içerik konmaz: önbellek dürüstçe boş kalır
    assert pool.warm_cache_with_phrases() == 0
    assert len(pool.cache) == 0
    assert pool.get_metrics()["hit_rate_percent"] is None
    # Gerçek sentezleyici (test için basit sabit dalga) verilirse 25 cümle yüklenir
    pool.warm_cache_with_phrases(lambda text, seed: np.full(1600, 0.1, dtype=np.float32))
    assert len(pool.cache) >= 25

    # Check top 25 automotive phrases
    first_phrase = TOP_25_AUTOMOTIVE_PHRASES[0]
    assert pool.has(first_phrase) is True

    audio_bytes = pool.get(first_phrase)
    assert audio_bytes is not None
    assert len(audio_bytes) > 0
    # Frame slicing test (20 ms at 8000 Hz, 16-bit = 320 bytes per frame)
    frames = pool.get_20ms_frames(first_phrase)
    assert len(frames) > 0
    for f in frames[:-1]:  # all frames except possibly the last remainder
        assert len(f) == 320

    # Cache hit metrics check
    initial_hits = pool.hit_count
    _ = pool.get(first_phrase)
    assert pool.hit_count == initial_hits + 1

    # Cache miss metrics check
    initial_misses = pool.miss_count
    missing = pool.get("Bilinmeyen rastgele bir cümle.")
    assert missing is None
    assert pool.miss_count == initial_misses + 1

    # Custom put test
    custom_pcm = b"\x00\x00" * 160  # 20 ms
    pool.put("Özel test kalıbı", custom_pcm)
    assert pool.has("Özel test kalıbı") is True
    assert pool.get("Özel test kalıbı") == custom_pcm


def test_api_clean_audio_endpoint(client: TestClient, auth_headers: dict):
    # Prepare 100 ms of dummy int16 PCM audio (800 samples * 2 bytes = 1600 bytes)
    t = np.linspace(0, 0.1, 800, endpoint=False)
    wav = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    audio_b64 = base64.b64encode(wav.tobytes()).decode("ascii")

    resp = client.post(
        "/api/pause-cleaner/clean-audio",
        headers=auth_headers,
        json={"audio_base64": audio_b64, "sample_rate": 8000, "fade_ms": 10.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "cleaned_audio_base64" in data
    assert "duration_ms" in data
    assert data["sample_rate"] == 8000

    cleaned_pcm = base64.b64decode(data["cleaned_audio_base64"])
    assert len(cleaned_pcm) > 0


def test_api_clean_audio_invalid(client: TestClient, auth_headers: dict):
    resp = client.post(
        "/api/pause-cleaner/clean-audio",
        headers=auth_headers,
        json={"audio_base64": "!!!invalid-base64", "sample_rate": 8000},
    )
    assert resp.status_code == 400


def test_api_audio_cache_endpoints(client: TestClient, auth_headers: dict):
    # 1. Metrics endpoint
    m_resp = client.get("/api/audio-cache/metrics", headers=auth_headers)
    assert m_resp.status_code == 200
    metrics = m_resp.json()
    assert "cached_phrases_count" in metrics
    assert "hit_count" in metrics

    # 2. Phrases endpoint
    p_resp = client.get("/api/audio-cache/phrases", headers=auth_headers)
    assert p_resp.status_code == 200
    phrases = p_resp.json()
    assert len(phrases) == 25
    # Import anında ısıtma yok: global önbellek boş
    assert phrases[0]["cached"] is False

    # 3. Lookup endpoint (önbellek boş → bulunamaz; önce put ile gerçek içerik ekle)
    telephony_audio_cache.put(TOP_25_AUTOMOTIVE_PHRASES[0], b"\x01\x00" * 800)
    l_resp = client.post(
        "/api/audio-cache/lookup",
        headers=auth_headers,
        json={"text": TOP_25_AUTOMOTIVE_PHRASES[0]},
    )
    assert l_resp.status_code == 200
    look_data = l_resp.json()
    assert look_data["found"] is True
    assert look_data["num_frames_20ms"] > 0

    # 4. Lookup endpoint (not found)
    l_miss = client.post(
        "/api/audio-cache/lookup",
        headers=auth_headers,
        json={"text": "Hiç kaydedilmemiş bir cümle"},
    )
    assert l_miss.status_code == 200
    assert l_miss.json()["found"] is False

    # 5. Warmup endpoint
    w_resp = client.post("/api/audio-cache/warmup", headers=auth_headers)
    assert w_resp.status_code == 200
    # Sentezleyici bağlı olmadığı için sahte ses konmaz
    assert w_resp.json()["status"] == "not_warmed"
    assert w_resp.json()["simulated"] is False
    telephony_audio_cache.clear()
