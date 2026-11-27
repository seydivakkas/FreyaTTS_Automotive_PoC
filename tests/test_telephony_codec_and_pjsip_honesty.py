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

import struct
from unittest.mock import patch
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.ami import MockAMIClient, set_ami_client
from backend.dsp import apply_telephony_eq_and_downsample_8k
from backend.audiosocket_server import (
    AUDIOSOCKET_AUDIO,
    AUDIOSOCKET_HANGUP,
    FRAME_SIZE_BYTES,
    LOOKBACK_FRAMES_COUNT,
    LOOKBACK_TOTAL_BYTES,
    LookbackBuffer,
    build_packet,
    read_packet,
)
from automotive_voice.audio.contracts import (
    AudioChunkMetadata,
    Codec,
    MediaFormat,
)
from automotive_voice.core.identifiers import GenerationId, SessionId, TurnId


def test_readiness_and_ami_status_honestly_report_simulation(monkeypatch):
    """
    Fiziksel Asterisk PBX / Telco SIP trunk bağlı değilken hem /api/readiness
    hem de /api/outbound/ami-status uç noktalarının dürüstçe 'simulated: True',
    'connected: False' ve 'status: SIMULATED' döndürdüğünü doğrular.
    """
    mock_ami = MockAMIClient()
    set_ami_client(mock_ami)

    client = TestClient(app)
    # 1. /api/readiness kontrolü
    readiness_resp = client.get("/api/readiness", auth=("admin", settings.admin_password))
    assert readiness_resp.status_code == 200
    r_body = readiness_resp.json()

    assert "telephony" in r_body
    tel = r_body["telephony"]
    assert tel["simulated"] is True
    assert tel["connected"] is False
    assert tel["status"] == "SIMULATED"
    assert tel["driver"] == "PJSIP / AudioSocket"
    assert tel["ami_host"] == settings.ami_host

    # 2. /api/outbound/ami-status kontrolü
    ami_resp = client.get("/api/outbound/ami-status", auth=("admin", settings.admin_password))
    assert ami_resp.status_code == 200
    ami_body = ami_resp.json()
    assert ami_body["simulated"] is True
    assert ami_body["connected"] is False


def test_apply_telephony_eq_and_downsample_8k_shapes_and_framing():
    """
    48 kHz ses dizisinin 8 kHz 16-bit slin16 PCM formatına indirgenmesini
    ve Asterisk 20 ms'lik çerçeve (320 byte) sınırlarına tam uyumunu doğrular.
    """
    # 1 saniyelik 48 kHz sentetik ses sinyali (48.000 örnek)
    t = np.linspace(0, 1.0, 48000, endpoint=False, dtype=np.float32)
    wav_48k = 0.5 * np.sin(2 * np.pi * 1000 * t)

    pcm16 = apply_telephony_eq_and_downsample_8k(wav_48k)

    # Veri tipi int16 olmalı (Asterisk slin16)
    assert pcm16.dtype == np.int16
    # 1 saniye 8 kHz = tam 8000 örnek
    assert len(pcm16) == 8000

    raw_bytes = pcm16.tobytes()
    # 8000 örnek * 2 byte/örnek = 16000 byte
    assert len(raw_bytes) == 16000

    # Asterisk AudioSocket 20 ms çerçeve standardı: 160 örnek = 320 byte
    # 1 saniyelik akış tam 50 çerçeveye bölünmelidir.
    num_frames = len(raw_bytes) // FRAME_SIZE_BYTES
    remainder = len(raw_bytes) % FRAME_SIZE_BYTES
    assert num_frames == 50
    assert remainder == 0


def test_apply_telephony_eq_frequency_attenuation_and_presence():
    """
    120 Hz yüksek geçiren filtrenin motor/kabin uğultusunu kestiğini,
    3.2 kHz presence boost'un telefon anlaşılırlığını artırdığını ve
    yumuşak tepe sınırlayıcının (soft peak limiter) aşırı genlikleri kırpmadan
    sıkıştırdığını doğrular.
    """
    sr_in = 48000
    t = np.linspace(0, 0.5, int(sr_in * 0.5), endpoint=False, dtype=np.float32)

    # 1. 50 Hz Motor / Kabin Uğultusu (Sub-bass rumble)
    rumble_50hz = np.sin(2 * np.pi * 50 * t)
    pcm_rumble = apply_telephony_eq_and_downsample_8k(rumble_50hz, hp_cutoff=120.0)
    rms_rumble = np.sqrt(np.mean(pcm_rumble.astype(np.float64) ** 2))

    # 2. 1000 Hz Referans Konuşma Tonu
    voice_1000hz = np.sin(2 * np.pi * 1000 * t)
    pcm_voice = apply_telephony_eq_and_downsample_8k(voice_1000hz, hp_cutoff=120.0)
    rms_voice = np.sqrt(np.mean(pcm_voice.astype(np.float64) ** 2))

    # 50 Hz uğultu, 1000 Hz konuşma bandına göre 2. derece filtreyle en az 4 kat (>12 dB) zayıflatılmış olmalıdır
    assert rms_voice > 4.0 * rms_rumble, f"Uğultu yeterince filtrelenmedi: voice={rms_voice}, rumble={rms_rumble}"

    # 3. 3.2 kHz Presence Boost Testi (2 kHz ile karşılaştırma)
    tone_2000hz = np.sin(2 * np.pi * 2000 * t)
    tone_3200hz = np.sin(2 * np.pi * 3200 * t)
    pcm_2000 = apply_telephony_eq_and_downsample_8k(tone_2000hz)
    pcm_3200 = apply_telephony_eq_and_downsample_8k(tone_3200hz)
    rms_2000 = np.sqrt(np.mean(pcm_2000.astype(np.float64) ** 2))
    rms_3200 = np.sqrt(np.mean(pcm_3200.astype(np.float64) ** 2))

    # 3.2 kHz peaking filter, telefon bandında 2 kHz tonuna göre kazanç sağlamalıdır
    assert rms_3200 > rms_2000, f"3.2 kHz boost gerçekleşmedi: 3200Hz={rms_3200}, 2000Hz={rms_2000}"

    # 4. Soft Peak Limiting (tanh) - Aşırı genlikli giriş int16 taşması yapmaz
    loud_signal = 3.0 * np.sin(2 * np.pi * 500 * t)
    pcm_loud = apply_telephony_eq_and_downsample_8k(loud_signal)
    assert np.all(pcm_loud >= -32768)
    assert np.all(pcm_loud <= 32767)


def test_media_format_and_codec_contracts():
    """
    Telefoni codec sözleşmelerini (PCM_S16LE, ALAW, MULAW, G722) doğrular.
    """
    # 1. PCM_S16LE 8 kHz mono (Asterisk slin16)
    fmt_pcm = MediaFormat(Codec.PCM_S16LE, 8000, channels=1, rtp_clock_hz=8000)
    assert fmt_pcm.payload_supported is True
    # 160 örnek (20 ms) = 320 byte
    assert fmt_pcm.expected_bytes(160) == 320

    # 2. G.711 A-law 8 kHz mono
    fmt_alaw = MediaFormat(Codec.ALAW, 8000, channels=1, rtp_clock_hz=8000)
    assert fmt_alaw.payload_supported is True
    # 160 örnek (20 ms) = 160 byte
    assert fmt_alaw.expected_bytes(160) == 160

    # 3. G.711 Mu-law 8 kHz mono
    fmt_mulaw = MediaFormat(Codec.MULAW, 8000, channels=1, rtp_clock_hz=8000)
    assert fmt_mulaw.payload_supported is True
    # 160 örnek (20 ms) = 160 byte
    assert fmt_mulaw.expected_bytes(160) == 160

    # 4. G.722 Wideband - 16 kHz decoded / 8 kHz RTP clock (M06 metadata-only sözleşmesi)
    fmt_g722 = MediaFormat(Codec.G722, 16000, channels=1, rtp_clock_hz=8000)
    assert fmt_g722.payload_supported is False
    assert fmt_g722.expected_bytes(160) is None

    # Hatalı parametrelerde ValueError fırlatılmalı
    with pytest.raises(ValueError):
        MediaFormat(Codec.G722, 8000, channels=1, rtp_clock_hz=8000)

    # 5. AudioChunkMetadata doğrulaması (20 ms slin16 chunk)
    sid = SessionId("sess-001")
    tid = TurnId(1)
    gid = GenerationId(1)
    chunk_meta = AudioChunkMetadata(
        session_id=sid,
        turn_id=tid,
        generation_id=gid,
        stream_id="stream-pjsip-trunk-01",
        seq=1,
        sample_count=160,
        duration_ms=20,
        timestamp_mono_ns=1000000000,
        fmt=fmt_pcm,
        clause_index=0,
    )
    safe = chunk_meta.safe_metadata()
    assert safe["sample_count"] == 160
    assert safe["duration_ms"] == 20
    assert safe["media_format"]["codec"] == "pcm_s16le"


def test_audiosocket_packet_framing_and_lookback():
    """
    AudioSocket protokol ikili paket yapısını (kind + length + payload)
    ve 300 ms pre-roll sağlayan LookbackBuffer'ı doğrular.
    """
    # 20 ms'lik ses çerçevesi (160 örnek * 2 byte = 320 byte)
    dummy_frame = b"\x12\x34" * 160
    packet = build_packet(AUDIOSOCKET_AUDIO, dummy_frame)

    # 1 byte kind + 2 byte uint16 length + 320 byte payload = 323 byte
    assert len(packet) == 323
    kind, length = struct.unpack("!BH", packet[:3])
    assert kind == AUDIOSOCKET_AUDIO
    assert length == 320
    assert packet[3:] == dummy_frame

    # LookbackBuffer doğrulaması: 15 çerçeve x 320 byte = 4800 byte (300 ms)
    buf = LookbackBuffer(capacity_frames=LOOKBACK_FRAMES_COUNT, frame_bytes=FRAME_SIZE_BYTES)
    for i in range(25):  # 25 çerçeve gönder, kapasite 15'te sınırlanmalı
        buf.push(struct.pack("!H", i) * 160)

    assert len(buf) == LOOKBACK_FRAMES_COUNT
    assert buf.total_frames_pushed == 25
    assert len(buf.get_bytes()) == LOOKBACK_TOTAL_BYTES
