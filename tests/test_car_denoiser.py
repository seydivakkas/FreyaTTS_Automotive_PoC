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

import io
from unittest.mock import patch
import numpy as np
import pytest
from scipy import signal
import soundfile as sf
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.car_denoiser import (
    CarNoiseFilter,
    SpectralNoiseSuppressor,
    SoftAGC,
    InboundCarDenoiser,
    process_audio_stream,
)
from backend.db import Base
from backend.main import app
import backend.session as session_module


def test_hpf_frequency_response():
    """120 Hz 4. derece Butterworth HPF'nin 60 Hz uğultuyu kesip 1 kHz konuşmayı koruduğunu doğrular."""
    fs = 8000
    hpf = CarNoiseFilter(cutoff_hz=120.0, sample_rate=fs, order=4)

    t = np.linspace(0, 0.5, int(fs * 0.5), endpoint=False)
    # 60 Hz motor uğultusu ve 1000 Hz konuşma frekansı
    hum_60 = 0.5 * np.sin(2 * np.pi * 60 * t).astype(np.float32)
    voice_1000 = 0.2 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)

    filtered_hum = hpf.process(hum_60)
    hpf.reset()
    filtered_voice = hpf.process(voice_1000)

    # Başlangıç geçişi sonrası (0.1 sn sonrası) RMS ölçümü
    steady_idx = int(fs * 0.1)
    hum_in_rms = np.sqrt(np.mean(hum_60[steady_idx:] ** 2))
    hum_out_rms = np.sqrt(np.mean(filtered_hum[steady_idx:] ** 2))
    hum_att_db = 20 * np.log10(hum_out_rms / hum_in_rms)

    voice_in_rms = np.sqrt(np.mean(voice_1000[steady_idx:] ** 2))
    voice_out_rms = np.sqrt(np.mean(filtered_voice[steady_idx:] ** 2))
    voice_att_db = 20 * np.log10(voice_out_rms / voice_in_rms)

    # 60 Hz en az 20 dB bastırılmalı
    assert hum_att_db <= -20.0, f"60 Hz zayıflatması yetersiz: {hum_att_db:.2f} dB"
    # 1000 Hz konuşma bandı neredeyse kayıpsız geçmeli
    assert abs(voice_att_db) < 2.5, f"1000 Hz konuşma zayıfladı: {voice_att_db:.2f} dB"


def test_hpf_frame_boundary_continuity():
    """20 ms bloklar halinde çağrıldığında durumun (zi) korunduğunu ve klik oluşmadığını doğrular."""
    fs = 8000
    chunk_size = 160  # 20 ms
    hpf = CarNoiseFilter(cutoff_hz=120.0, sample_rate=fs)

    t = np.linspace(0, 0.4, int(fs * 0.4), endpoint=False)
    test_sig = (0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)

    chunks = []
    for i in range(0, len(test_sig), chunk_size):
        chunk = test_sig[i : i + chunk_size]
        chunks.append(hpf.process(chunk))

    streamed_out = np.concatenate(chunks)

    # Tek seferde işlenen ile blok blok işlenen karşılaştırması
    hpf_mono = CarNoiseFilter(cutoff_hz=120.0, sample_rate=fs)
    mono_out = hpf_mono.process(test_sig)

    # Çerçeve sınırlarında sıçrama olmamalı, fark makine hassasiyetine yakın olmalı
    diff = np.max(np.abs(streamed_out[chunk_size:] - mono_out[chunk_size:]))
    assert diff < 1e-4, f"Çerçeve sınırlarında süreksizlik tespit edildi: {diff}"


def test_spectral_noise_suppression_floor():
    """Overlap-add spektral çıkarma motorunun rüzgâr/yol gürültüsünü -18 dB tabanında bastırdığını doğrular."""
    fs = 8000
    suppressor = SpectralNoiseSuppressor(sample_rate=fs, suppression_db=18.0)

    # 1.5 saniye pembe/yol gürültüsü
    np.random.seed(42)
    n_samples = int(fs * 1.5)
    noise_raw = np.random.randn(n_samples).astype(np.float32)
    b, a = signal.butter(2, 500 / (fs / 2), "low")
    car_noise = signal.lfilter(b, a, noise_raw).astype(np.float32) * 0.15

    chunk_size = 160
    out_chunks = []
    for i in range(0, len(car_noise), chunk_size):
        out_chunks.append(suppressor.process(car_noise[i : i + chunk_size]))

    cleaned_noise = np.concatenate(out_chunks)

    # Isınma (warmup) sonrası gürültü bastırma miktarını hesapla
    steady_start = int(fs * 0.5)
    in_rms = np.sqrt(np.mean(car_noise[steady_start:] ** 2))
    out_rms = np.sqrt(np.mean(cleaned_noise[steady_start:] ** 2))

    suppression_achieved_db = 20 * np.log10(out_rms / in_rms)
    # -18 dB tabanına yakın bir bastırma beklenir (-10 dB ile -20 dB arası)
    assert suppression_achieved_db <= -10.0, f"Gürültü bastırma yetersiz: {suppression_achieved_db:.2f} dB"


def test_soft_agc_gain_and_noise_gate():
    """Soft AGC'nin kısık sesi yükselttiğini, gürültü kapısı altını ise yükseltmediğini doğrular."""
    fs = 8000
    agc = SoftAGC(target_dbfs=-16.0, noise_gate_dbfs=-42.0, max_boost_db=12.0, sample_rate=fs)

    # 1. Test: Kısık konuşma sinyali (~ -28 dBFS)
    t = np.linspace(0, 0.4, int(fs * 0.4), endpoint=False)
    quiet_voice = (0.04 * np.sin(2 * np.pi * 500 * t)).astype(np.float32)
    in_rms = np.sqrt(np.mean(quiet_voice**2))
    in_dbfs = 20 * np.log10(in_rms)

    boosted = agc.process(quiet_voice)
    out_rms = np.sqrt(np.mean(boosted[int(fs * 0.1):] ** 2))
    out_dbfs = 20 * np.log10(out_rms)

    gain_applied = out_dbfs - in_dbfs
    assert gain_applied > 4.0, f"Kısık ses yeterince yükseltilmedi: {gain_applied:.2f} dB"
    assert agc.is_speech is True

    # 2. Test: Gürültü kapısı altı sinyal (~ -55 dBFS)
    agc.reset()
    low_noise = (0.0015 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    noise_out = agc.process(low_noise)
    noise_gain = 20 * np.log10(np.sqrt(np.mean(noise_out**2)) / np.sqrt(np.mean(low_noise**2)))
    # Gürültü kapısı altında kazanç 1.0 (0 dB) civarında kalmalı, kabartılmamalı
    assert noise_gain < 2.0, f"Gürültü kapısı çalışmadı, dip gürültü yükseltildi: {noise_gain:.2f} dB"
    assert agc.is_speech is False


def test_soft_limiter_prevents_clipping():
    """Soft limiter'ın aşırı genlikte bile clipping yapmadığını doğrular."""
    agc = SoftAGC(target_dbfs=-16.0, max_boost_db=12.0)
    # 1.5 genlikli aşırı yüksek sinyal
    excessive_sig = np.full(160, 1.5, dtype=np.float32)
    out = agc.process(excessive_sig)
    assert np.all(out <= 1.0) and np.all(out >= -1.0)


def test_inbound_car_denoiser_barge_in_prevention():
    """Ağır motor uğultusunun sahte barge-in tetiklemesini başarıyla engellediğini doğrular."""
    fs = 8000
    denoiser = InboundCarDenoiser(sample_rate=fs, enabled=True)

    t = np.linspace(0, 0.6, int(fs * 0.6), endpoint=False)
    # 60 Hz + 90 Hz yüksek seviyeli motor devri uğultusu (~ -12 dBFS)
    engine_rumble = (
        0.35 * np.sin(2 * np.pi * 60 * t) + 0.20 * np.sin(2 * np.pi * 90 * t)
    ).astype(np.float32)

    chunk_size = 160
    barge_in_candidates = []
    for i in range(0, len(engine_rumble), chunk_size):
        chunk = engine_rumble[i : i + chunk_size]
        _, diag = denoiser.process_frame(chunk)
        barge_in_candidates.append(diag["is_barge_in_candidate"])

    stats = denoiser.get_summary_stats()
    # Motor uğultusu barge-in tetiklememeli
    assert not any(barge_in_candidates), "Motor uğultusu sahte barge-in adayı olarak algılandı!"
    # Sahte barge-in engelleme sayacı artmış olmalı
    assert stats["false_barge_in_prevented"] > 0


def test_process_bytes_slin16():
    """Asterisk AudioSocket 16-bit slin16 byte dizisinin doğru işlendiğini doğrular."""
    denoiser = InboundCarDenoiser(sample_rate=8000)
    # 160 örnek int16 = 320 byte
    raw_int16 = (np.random.randn(160) * 1000).astype("<i2")
    raw_bytes = raw_int16.tobytes()

    cleaned_bytes = denoiser.process_bytes(raw_bytes, sample_rate=8000)
    assert len(cleaned_bytes) == len(raw_bytes)
    assert isinstance(cleaned_bytes, bytes)


def test_denoiser_and_filter_constructor_params():
    """Denoiser ve filtre kurucu parametrelerinin özniteliklere yansıdığını doğrular."""
    d = InboundCarDenoiser(sample_rate=8000)
    f = CarNoiseFilter(cutoff_hz=120.0)
    assert d.sample_rate == 8000
    assert f.cutoff_hz == 120.0


def test_process_audio_stream_helper():
    """process_audio_stream yardımcı fonksiyonunun tam akış özetini ürettiğini doğrular."""
    fs = 8000
    t = np.linspace(0, 0.5, int(fs * 0.5), endpoint=False)
    sig = (0.2 * np.sin(2 * np.pi * 400 * t)).astype(np.float32)

    cleaned, stats = process_audio_stream(sig, sample_rate=fs)
    assert len(cleaned) == len(sig)
    assert "avg_noise_suppression_db" in stats
    assert "snr_improvement_db" in stats


def test_dsp_rest_endpoints():
    """FastAPI /api/dsp/config ve /api/dsp/denoise-preview uç noktalarını test eder."""
    client = TestClient(app)
    auth_headers = {"Authorization": "Basic YWRtaW46c2VjcmV0"}

    with patch("backend.main.settings.admin_password", "secret"):
        # 1. GET /api/dsp/config
        get_res = client.get("/api/dsp/config", headers=auth_headers)
        assert get_res.status_code == 200
        cfg = get_res.json()
        assert cfg["enabled"] is True
        assert cfg["hpf_cutoff"] == 120.0
        assert cfg["suppression_db"] == 18.0

        # 2. POST /api/dsp/config
        post_res = client.post(
            "/api/dsp/config",
            json={
                "enabled": True,
                "hpf_cutoff": 130.0,
                "suppression_db": 20.0,
                "target_dbfs": -15.0,
                "noise_gate_dbfs": -40.0,
                "max_boost_db": 10.0,
            },
            headers=auth_headers,
        )
        assert post_res.status_code == 200
        updated = post_res.json()
        assert updated["status"] == "updated"
        assert updated["config"]["hpf_cutoff"] == 130.0

        # 3. POST /api/dsp/denoise-preview
        fs = 8000
        t = np.linspace(0, 0.4, int(fs * 0.4), endpoint=False)
        test_wav = (0.2 * np.sin(2 * np.pi * 500 * t)).astype(np.float32)
        buf = io.BytesIO()
        sf.write(buf, test_wav, fs, format="WAV", subtype="PCM_16")
        wav_bytes = buf.getvalue()

        preview_res = client.post(
            "/api/dsp/denoise-preview",
            files={"file": ("test.wav", wav_bytes, "audio/wav")},
            data={"hpf_cutoff": "120.0", "suppression_db": "18.0"},
            headers=auth_headers,
        )
        assert preview_res.status_code == 200
        data = preview_res.json()
        assert data["status"] == "success"
        assert "audio_base64" in data
        assert "stats" in data
        assert data["stats"]["total_frames_processed"] > 0


@pytest.mark.asyncio
async def test_session_denoiser_integration(tmp_path, monkeypatch):
    """VoiceSession oturumunda CarDenoiser'ın devrede olduğunu ve çalıştığını doğrular."""
    # H01.01: Endpoint.feed Silero VAD için torch kullanır; torch yoksa atlanır.
    pytest.importorskip("torch")
    test_db = str(tmp_path / "session_dsp_test.db")
    engine = create_engine(f"sqlite:///{test_db}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(session_module, "Session", TestSession)

    class MockVad:
        def reset_states(self):
            pass

        def __call__(self, x, sr):
            return 0.1

    monkeypatch.setattr(session_module.models, "vad", MockVad())

    async def dummy_emit(event):
        pass

    async def dummy_send(frame):
        pass

    session = session_module.VoiceSession("test_dsp", dummy_emit, dummy_send)
    assert hasattr(session, "car_denoiser")
    assert session.car_denoiser.enabled is True

    # 8 kHz'de 800 örnek (1600 byte / 100 ms) ham PCM gönder
    raw_frame = (np.ones(800, dtype="<i2") * 1000).tobytes()
    await session.input(raw_frame, rate=8000)

    # Denoiser'ın bu çerçeveyi işlediğini doğrula
    assert session.car_denoiser.total_frames_processed >= 1

    await session.close()
    engine.dispose()


def test_soft_agc_downward_expander_attenuates_noise():
    """SoftAGC'nin kapı altındaki gürültüyü (Downward Expander) güçlü bir şekilde sönümlediğini doğrular."""
    fs = 8000
    agc = SoftAGC(
        target_dbfs=-16.0,
        noise_gate_dbfs=-40.0,
        max_boost_db=12.0,
        gate_attenuation_db=30.0,
        sample_rate=fs,
    )
    # -52 dBFS gürültü sinyali (kapının 12 dB altında)
    t = np.linspace(0, 0.4, int(fs * 0.4), endpoint=False)
    noise_sig = (0.0025 * np.sin(2 * np.pi * 350 * t)).astype(np.float32)
    in_rms = np.sqrt(np.mean(noise_sig**2))

    out_chunks = []
    chunk_size = 160
    for i in range(0, len(noise_sig), chunk_size):
        out_chunks.append(agc.process(noise_sig[i : i + chunk_size]))

    out_sig = np.concatenate(out_chunks)
    out_rms = np.sqrt(np.mean(out_sig[int(fs * 0.1):] ** 2))
    attenuation_db = 20 * np.log10(out_rms / in_rms)

    # Kapı altındaki gürültü en az 10 dB zayıflatılmalıdır
    assert attenuation_db <= -10.0, f"Gürültü yeterince sönümlenmedi: {attenuation_db:.2f} dB"
    assert agc.is_speech is False


def test_inbound_car_denoiser_ambient_calibration():
    """Ortam gürültüsü kalibrasyonunun oda gürültüsünü doğru profilleyip dinamik kapı belirlediğini doğrular."""
    fs = 8000
    denoiser = InboundCarDenoiser(sample_rate=fs, noise_gate_dbfs=-42.0)
    denoiser.start_calibration(duration_sec=0.5, target_frames=25)
    assert denoiser.is_calibrating is True

    # -35 dBFS seviyesinde 25 çerçeve oda gürültüsü besle
    t = np.linspace(0, 0.020, 160, endpoint=False)
    ambient_frame = (0.018 * np.sin(2 * np.pi * 400 * t)).astype(np.float32)

    done = False
    for _ in range(25):
        done = denoiser.feed_calibration_frame(ambient_frame)

    assert done is True
    info = denoiser.finish_calibration()
    assert info["calibrated"] is True
    assert denoiser.is_calibrating is False
    assert denoiser.calibrated is True
    # -35 dBFS gürültü için dinamik kapı yaklaşık -31 dBFS civarına çekilmelidir
    assert -38.0 <= info["ambient_dbfs"] <= -32.0
    assert info["noise_gate_dbfs"] > info["ambient_dbfs"]
    assert denoiser.agc.noise_gate_dbfs == info["noise_gate_dbfs"]


@pytest.mark.asyncio
async def test_stt_confidence_and_configurable_energy_gate(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from backend.models import Models

    model = Models()
    text = "Randevu almak istiyorum."
    segments = [
        SimpleNamespace(text=text, no_speech_prob=0.9),
        SimpleNamespace(text=text, avg_logprob=-1.2),
        SimpleNamespace(text=text, compression_ratio=3.0),
    ]
    decoder = Mock(return_value=(segments, None))
    model.stt = SimpleNamespace(transcribe=decoder)
    quiet_audio = np.full(3200, 0.001, dtype=np.float32)

    monkeypatch.setattr(settings, "stt_min_rms", 0.0075)
    assert await model.transcribe(quiet_audio) == ""
    decoder.assert_not_called()

    monkeypatch.setattr(settings, "stt_min_rms", 0.0)
    monkeypatch.setattr(settings, "stt_catalog_hotwords", False)
    assert await model.transcribe(quiet_audio) == ""
    assert decoder.call_args.kwargs["hotwords"] is None
    assert "log_prob_threshold" in decoder.call_args.kwargs

    segments.append(SimpleNamespace(text=text))
    monkeypatch.setattr(settings, "stt_catalog_hotwords", True)
    monkeypatch.setattr(model, "_catalog_hotwords", lambda: ["Volkswagen Golf"])
    assert await model.transcribe(quiet_audio) == text
    assert decoder.call_args.kwargs["hotwords"] == "Volkswagen Golf"
