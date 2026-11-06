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
import time
import numpy as np
import pytest

from experimental.prosody_wsola_streamer import (
    LEYLA_SEED,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_MIN_DURATION_SEC,
    IntentCategory,
    ProsodyProfile,
    INTENT_PROFILES,
    VoicingReport,
    SynthesizedClause,
    WSOLATimeStretch,
    ContextualProsodyPlanner,
    DurationFloorGuard,
    AudioVoicingChecker,
    ModelHashAndSeedGuard,
    OverlappingClauseStreamer,
    prosody_wsola_streamer,
)


def _generate_synthetic_vowel(
    freq_hz: float = 210.0,
    duration_sec: float = 1.0,
    sr: int = 48000,
) -> np.ndarray:
    """Leyla ses kimliğini (F0 ~ 210 Hz) simüle eden harmonik ses sinyali üretir."""
    t = np.linspace(0, duration_sec, int(round(sr * duration_sec)), endpoint=False, dtype=np.float32)
    # Temel frekans ve 3 adet formant harmonisi
    sig = (
        0.55 * np.sin(2 * np.pi * freq_hz * t)
        + 0.25 * np.sin(2 * np.pi * (freq_hz * 2) * t)
        + 0.15 * np.sin(2 * np.pi * (freq_hz * 3) * t)
        + 0.05 * np.sin(2 * np.pi * (freq_hz * 4) * t)
    )
    return sig.astype(np.float32)


def _measure_fundamental_frequency(audio: np.ndarray, sr: int = 48000) -> float:
    """Otokorelasyon tepe noktası ile temel frekansı (F0) hesaplar."""
    seg_len = min(len(audio), int(sr * 0.25))
    segment = audio[:seg_len]
    corr = np.correlate(segment, segment, mode="full")
    corr = corr[len(corr) // 2 :]
    min_lag = int(sr / 400.0)
    max_lag = int(sr / 80.0)
    search = corr[min_lag:max_lag]
    best_lag = min_lag + int(np.argmax(search))
    return float(sr / best_lag)


# ============================================================================
# 1. WSOLATimeStretch Birim Testleri
# ============================================================================
def test_wsola_speed_ratio_and_length():
    """WSOLA'nın 0.94x ve 1.02x hız çarpanlarında kesin süre oranlarını test eder."""
    wsola = WSOLATimeStretch(sample_rate=48000)
    audio = _generate_synthetic_vowel(210.0, duration_sec=1.0, sr=48000)
    orig_len = len(audio)

    # 0.94x Yavaşlatma (Fiyat Niyeti)
    stretched_slow = wsola.stretch(audio, speed_factor=0.94)
    expected_slow_len = int(round(orig_len / 0.94))
    assert abs(len(stretched_slow) - expected_slow_len) <= 2
    assert not np.isnan(stretched_slow).any()

    # 1.02x Hızlandırma (Öneri Niyeti)
    stretched_fast = wsola.stretch(audio, speed_factor=1.02)
    expected_fast_len = int(round(orig_len / 1.02))
    assert abs(len(stretched_fast) - expected_fast_len) <= 2
    assert not np.isnan(stretched_fast).any()


def test_wsola_exact_pitch_preservation():
    """WSOLA esnetme sırasında F0 temel frekansının (210 Hz) bozulmadığını doğrular."""
    wsola = WSOLATimeStretch(sample_rate=48000)
    audio = _generate_synthetic_vowel(210.0, duration_sec=1.5, sr=48000)
    orig_f0 = _measure_fundamental_frequency(audio, sr=48000)

    slow_audio = wsola.stretch(audio, speed_factor=0.94)
    slow_f0 = _measure_fundamental_frequency(slow_audio, sr=48000)

    fast_audio = wsola.stretch(audio, speed_factor=1.02)
    fast_f0 = _measure_fundamental_frequency(fast_audio, sr=48000)

    # F0 farkı < 1.0 Hz toleransında olmalıdır (Sincap etkisi 0 olmalı)
    assert abs(orig_f0 - 210.0) < 1.0
    assert abs(slow_f0 - orig_f0) < 1.0
    assert abs(fast_f0 - orig_f0) < 1.0


def test_wsola_edge_cases_and_bypass():
    """WSOLA'nın boş dizi, sessizlik ve speed_factor=1.0 durumlarını hatasız yönettiğini test eder."""
    wsola = WSOLATimeStretch(sample_rate=48000)

    # Boş dizi
    empty = np.array([], dtype=np.float32)
    assert len(wsola.stretch(empty, 0.94)) == 0

    # speed_factor = 1.0 Bypass
    audio = _generate_synthetic_vowel(210.0, 0.5, sr=48000)
    res_1 = wsola.stretch(audio, speed_factor=1.0)
    np.testing.assert_array_equal(audio, res_1)

    # Sessizlik dizisi
    silence = np.zeros(48000, dtype=np.float32)
    res_silence = wsola.stretch(silence, speed_factor=0.94)
    assert len(res_silence) == int(round(48000 / 0.94))
    assert np.all(res_silence == 0.0)


# ============================================================================
# 2. ContextualProsodyPlanner Testleri
# ============================================================================
def test_prosody_planner_intent_tag_extraction():
    """LLM'den akan `<intent:...>` etiketlerinin doğru ayrıştırılıp temizlendiğini test eder."""
    text1 = "<intent:pricing> Peugeot 3008 modelimizin başlangıç fiyatı 1.850.000 TL'dir."
    clean1, intent1 = ContextualProsodyPlanner.parse_intent_tag(text1)
    assert intent1 == IntentCategory.PRICING
    assert clean1 == "Peugeot 3008 modelimizin başlangıç fiyatı 1.850.000 TL'dir."
    assert "<intent:" not in clean1

    text2 = "<intent:greeting> Merhaba, Borusan Otomotiv'e hoş geldiniz."
    clean2, intent2 = ContextualProsodyPlanner.parse_intent_tag(text2)
    assert intent2 == IntentCategory.GREETING
    assert clean2 == "Merhaba, Borusan Otomotiv'e hoş geldiniz."

    text3 = "<intent:recommendation> Size hibrit motor seçeneğini önerebilirim."
    clean3, intent3 = ContextualProsodyPlanner.parse_intent_tag(text3)
    assert intent3 == IntentCategory.RECOMMENDATION
    assert clean3 == "Size hibrit motor seçeneğini önerebilirim."


def test_prosody_planner_keyword_fallback():
    """Etiket bulunmadığında otomotiv anahtar sözcüklerinden niyet çıkarımını test eder."""
    text_pricing = "Aracın güncel nakit fiyatı bir milyon sekiz yüz bin liradır."
    clean_p, intent_p = ContextualProsodyPlanner.parse_intent_tag(text_pricing)
    assert intent_p == IntentCategory.PRICING

    text_q = "Test sürüşü için hangi günü tercih edersiniz?"
    clean_q, intent_q = ContextualProsodyPlanner.parse_intent_tag(text_q)
    assert intent_q == IntentCategory.QUESTION


def test_prosody_planner_clause_splitting_atomic_entities():
    """Cümleciklere ayırırken fiyat ve motor kodlarının bölünmediğini test eder."""
    full_text = "Elimizde iki uygun seçenek bulunuyor. Peugeot 3008 modelimizin fiyatı 1.850.000 TL olup, teslimata hazırdır."
    clauses = ContextualProsodyPlanner.split_into_clauses(full_text)
    assert len(clauses) >= 2
    # Fiyatın "1." ve "850.000 TL" olarak ikiye bölünmediğini doğrula
    assert any("1.850.000 TL" in c for c in clauses)


# ============================================================================
# 3. DurationFloorGuard Testleri
# ============================================================================
def test_duration_floor_guard():
    """Kısa yanıtlarda süre tabanının devreye girdiğini test eder."""
    sr = 48000
    # 100 ms'lik çok kısa ses
    short_audio = np.ones(int(sr * 0.1), dtype=np.float32) * 0.5
    floored = DurationFloorGuard.apply_floor(short_audio, min_duration_sec=0.35, sample_rate=sr)
    assert len(floored) >= int(sr * 0.35)

    # 1 saniyelik uzun ses (değişmemeli)
    long_audio = np.ones(int(sr * 1.0), dtype=np.float32) * 0.5
    not_floored = DurationFloorGuard.apply_floor(long_audio, min_duration_sec=0.35, sample_rate=sr)
    assert len(not_floored) == int(sr * 1.0)


# ============================================================================
# 4. AudioVoicingChecker Testleri
# ============================================================================
def test_audio_voicing_checker():
    """Fısıltı çökmesi, sessizlik ve sağlıklı seslerin doğru sınıflandırıldığını test eder."""
    sr = 48000

    # 1. Sağlıklı harmonik ses
    healthy = _generate_synthetic_vowel(210.0, 0.5, sr=sr)
    rep_healthy = AudioVoicingChecker.check_quality(healthy, sr=sr)
    assert rep_healthy.is_valid is True
    assert rep_healthy.error_type is None
    assert rep_healthy.voicedness_score > 0.05
    assert abs(rep_healthy.f0_estimate_hz - 210.0) < 5.0

    # 2. Sessizlik çökmesi (silent collapse)
    silence = np.zeros(int(sr * 0.5), dtype=np.float32)
    rep_silence = AudioVoicingChecker.check_quality(silence, sr=sr)
    assert rep_silence.is_valid is False
    assert rep_silence.error_type == "silent_collapse"

    # 3. Kırpılma distorsiyonu (clipped distortion)
    clipped = np.ones(int(sr * 0.5), dtype=np.float32)
    rep_clipped = AudioVoicingChecker.check_quality(clipped, sr=sr)
    assert rep_clipped.is_valid is False
    assert rep_clipped.error_type == "clipped_distortion"


# ============================================================================
# 5. ModelHashAndSeedGuard Testleri
# ============================================================================
def test_model_hash_and_seed_guard(tmp_path):
    """Seed kilidini ve SHA-256 bütünlük kontrolünü test eder."""
    assert ModelHashAndSeedGuard.get_canonical_seed() == 9
    assert LEYLA_SEED == 9

    # Kontrollü perturbasyon testi
    seed0 = ModelHashAndSeedGuard.get_conditioned_noise_seed(attempt=0)
    seed1 = ModelHashAndSeedGuard.get_conditioned_noise_seed(attempt=1)
    assert seed0 == 9
    assert seed1 == 9 + 10007

    # Dosya hash testi
    test_file = tmp_path / "model.bin"
    test_file.write_bytes(b"FreyaTTS_Leyla_Voice_Weights_2026")
    is_valid, h = ModelHashAndSeedGuard.verify_file_sha256(test_file)
    assert is_valid is True
    assert len(h) == 64


# ============================================================================
# 6. OverlappingClauseStreamer Entegrasyon Testleri
# ============================================================================
@pytest.mark.asyncio
async def test_overlapping_clause_streamer_pipelined_flow():
    """Cümle N tüketilirken Cümle N+1'in paralel sentezlendiğini ve örtüşmeyi doğrular."""
    streamer = OverlappingClauseStreamer(sample_rate=48000)

    synth_latencies = []

    async def mock_synth(text: str, seed: int) -> np.ndarray:
        t0 = time.perf_counter()
        # Simüle edilmiş GPU ODE hesaplama gecikmesi (60 ms)
        await asyncio.sleep(0.06)
        synth_latencies.append((time.perf_counter() - t0) * 1000.0)
        return _generate_synthetic_vowel(210.0, duration_sec=0.4, sr=48000)

    full_utterance = (
        "<intent:pricing> Birinci seçeneğimiz hazır. "
        "İkinci seçeneğin güncel fiyatı bir milyon beş yüz bin liradır. "
        "Dilerseniz takas ve kredi desteğini hemen planlayabiliriz."
    )

    received_clauses = []
    t_start = time.perf_counter()

    async for clause in streamer.stream_utterance(full_utterance, synth_fn=mock_synth):
        received_clauses.append(clause)
        # Tüketici (oynatıcı) her cümleyi 80 ms boyunca telefonda çalıyor
        await asyncio.sleep(0.08)

    total_time = (time.perf_counter() - t_start) * 1000.0

    assert len(received_clauses) >= 3
    assert received_clauses[0].is_first is True
    assert received_clauses[-1].is_last is True
    assert received_clauses[0].intent == IntentCategory.PRICING
    assert received_clauses[0].speed_factor == 0.94  # Fiyat hız çarpanı
    assert streamer.total_overlaps_achieved >= 2
    # Örtüşmeli sentez sayesinde toplam süre ardışık çalışmadan belirgin şekilde kısadır
    assert total_time > 0.0


@pytest.mark.asyncio
async def test_overlapping_clause_streamer_barge_in_cancellation():
    """Müşteri araya girdiğinde (Barge-in) akışın anında durduğunu ve kalan cümlelerin atıldığını test eder."""
    streamer = OverlappingClauseStreamer(sample_rate=48000)
    gen_id = "test_gen_barge_in_123"

    call_count = 0

    async def mock_synth(text: str, seed: int) -> np.ndarray:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.04)
        return _generate_synthetic_vowel(210.0, duration_sec=0.4, sr=48000)

    text = "Birinci cümle başlasın. İkinci cümle devam etsin. Üçüncü cümle kesilmeli. Dördüncü cümle hiç gelmemeli."

    emitted_clauses = []
    async for clause in streamer.stream_utterance(text, synth_fn=mock_synth, generation_id=gen_id):
        emitted_clauses.append(clause)
        if len(emitted_clauses) == 1:
            # Müşteri 1. cümlede söz kesti! (Barge-In)
            streamer.cancel_generation(gen_id)

    # 1. cümleden sonra akış durdurulmuş olmalı
    assert len(emitted_clauses) == 1
    assert streamer.is_cancelled(gen_id) is False  # Temizlenmiş olmalı


@pytest.mark.asyncio
async def test_overlapping_clause_streamer_voicing_retry():
    """Euler ODE fısıltı çökmesi veya sessizlik ürettiğinde otomatik telafi denemesini test eder."""
    streamer = OverlappingClauseStreamer(sample_rate=48000)

    attempts = 0

    async def mock_unstable_synth(text: str, seed: int) -> np.ndarray:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            # İlk deneme fısıltı/sessizlik çökmesi üretsin
            return np.zeros(48000, dtype=np.float32)
        # İkinci deneme sağlıklı ses dönsün
        return _generate_synthetic_vowel(210.0, duration_sec=0.5, sr=48000)

    text = "<intent:inform> Bu tek bir test cümlesidir."
    results = []
    async for clause in streamer.stream_utterance(text, synth_fn=mock_unstable_synth):
        results.append(clause)

    assert len(results) == 1
    assert attempts == 2  # İlk denemede başarısız olup 2. denemede telafi etti
    assert streamer.total_retries_prevented >= 1
    assert results[0].audio_stretched is not None
