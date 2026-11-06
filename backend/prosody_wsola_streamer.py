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
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import logging
import math
from pathlib import Path
import re
import time
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union
import uuid

import numpy as np

logger = logging.getLogger("prosody_wsola_streamer")

# ============================================================================
# Sabitler ve Model Kimlik Kilidi (Ajan 2 - HLS-01)
# ============================================================================
LEYLA_SEED: int = 9
DEFAULT_SAMPLE_RATE: int = 48000
DEFAULT_MIN_DURATION_SEC: float = 0.35  # Kısa ifadelerde süre tabanı


class IntentCategory(str, Enum):
    """Konuşma Niyetleri ve Diyalog Profilleri (HLS-04)."""
    GREETING = "greeting"              # Karşılama ve ilk tanışma (Sıcak, davetkâr)
    INFORM = "inform"                  # Donanım, motor, stok bilgisi (Net, dengeli)
    PRICING = "pricing"                # Fiyat, kredi, finansman (Sakin, rakam vurgulu)
    QUESTION = "question"              # İhtiyaç anlama soruları (Açık, meraklı)
    REASSURANCE = "reassurance"        # Garanti, servis, güvenlik (Güven verici, ölçülü)
    RECOMMENDATION = "recommendation"  # Model karşılaştırma, test sürüşü (Akıcı)


@dataclass(frozen=True)
class ProsodyProfile:
    """Niyet bazlı hız çarpanı ve duraksama planı."""
    intent: IntentCategory
    speed_factor: float      # WSOLA perde koruyucu hız çarpanı (0.94x - 1.02x)
    pre_pause_ms: int        # Cümlecik öncesi mikrosaniye duraksama
    post_pause_ms: int       # Cümlecik sonrası nefes/anlam duraksaması
    description: str


# HLS-04: Standart Otomotiv Niyet-Prozodi Eşleme Tablosu
INTENT_PROFILES: dict[IntentCategory, ProsodyProfile] = {
    IntentCategory.GREETING: ProsodyProfile(
        intent=IntentCategory.GREETING,
        speed_factor=1.00,
        pre_pause_ms=0,
        post_pause_ms=140,
        description="Karşılama ve ilk tanışma profili (1.00x)",
    ),
    IntentCategory.INFORM: ProsodyProfile(
        intent=IntentCategory.INFORM,
        speed_factor=0.97,
        pre_pause_ms=60,
        post_pause_ms=150,
        description="Teknik donanım ve genel bilgi profili (0.97x)",
    ),
    IntentCategory.PRICING: ProsodyProfile(
        intent=IntentCategory.PRICING,
        speed_factor=0.94,
        pre_pause_ms=180,
        post_pause_ms=200,
        description="Fiyat, kredi ve finansman sakinlik profili (0.94x)",
    ),
    IntentCategory.QUESTION: ProsodyProfile(
        intent=IntentCategory.QUESTION,
        speed_factor=1.00,
        pre_pause_ms=80,
        post_pause_ms=160,
        description="Soru ve ihtiyaç anlama profili (1.00x)",
    ),
    IntentCategory.REASSURANCE: ProsodyProfile(
        intent=IntentCategory.REASSURANCE,
        speed_factor=0.96,
        pre_pause_ms=120,
        post_pause_ms=160,
        description="Garanti, servis ve güven verme profili (0.96x)",
    ),
    IntentCategory.RECOMMENDATION: ProsodyProfile(
        intent=IntentCategory.RECOMMENDATION,
        speed_factor=1.02,
        pre_pause_ms=60,
        post_pause_ms=140,
        description="Tavsiye ve seçenek sunma akıcılık profili (1.02x)",
    ),
}


@dataclass
class VoicingReport:
    """Akustik seslilik ve bozukluk değerlendirme raporu."""
    is_valid: bool
    error_type: Optional[str]  # "silent_collapse", "whisper_collapse", "clipped_distortion", None
    voicedness_score: float
    rms_energy: float
    f0_estimate_hz: float
    clipping_ratio: float


@dataclass
class SynthesizedClause:
    """Tek bir sentezlenmiş ve esnetilmiş cümlecik veri paketi."""
    clause_index: int
    raw_text: str
    clean_text: str
    intent: IntentCategory
    speed_factor: float
    audio_48k: np.ndarray
    audio_stretched: np.ndarray
    duration_ms: float
    pre_pause_ms: int
    post_pause_ms: int
    generation_id: str
    synth_latency_ms: float
    stretch_latency_ms: float
    voicedness_score: float
    f0_hz: float
    is_first: bool
    is_last: bool


# ============================================================================
# 1. Perde Koruyucu WSOLA Zaman Esnetme Motoru (Ajan 2 - HLS-03)
# ============================================================================
class WSOLATimeStretch:
    """
    Waveform Similarity Overlap-Add (WSOLA) Tabanlı Perde Koruyucu Zaman Esnetici.

    FreyaTTS-small modelinde çalışma zamanı konuşma hızı parametresi bulunmadığından;
    48 kHz ses çıktısının temel frekansını (F0 ~ 210 Hz Leyla kimliği) ve formantlarını
    birebir koruyarak konuşma hızını 0.94x - 1.02x arasında esnetir.
    Sincap (chipmunk) etkisi veya faz distorsiyonu yaratmaz.
    """

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        window_ms: float = 25.0,
        search_ms: float = 10.0,
    ):
        self.sample_rate = int(sample_rate)
        # 25 ms pencere boyutu (48 kHz'de 1200 örnek)
        self.win_size = int(round(self.sample_rate * (window_ms / 1000.0)))
        if self.win_size % 2 != 0:
            self.win_size += 1
        self.syn_hop = self.win_size // 2
        # Arama penceresi (10 ms ~ 480 örnek @ 48k; F0 > 100 Hz için yeterlidir)
        self.delta_max = int(round(self.sample_rate * (search_ms / 1000.0)))
        self.window = np.hanning(self.win_size).astype(np.float32)

    def stretch(
        self,
        audio: np.ndarray,
        speed_factor: float,
        sample_rate: Optional[int] = None,
    ) -> np.ndarray:
        """
        Giriş ses dizisini perdeyi değiştirmeden hız çarpanına (speed_factor) göre esnetir.

        - speed_factor < 1.0: Yavaşlatır (örneğin 0.94x -> süre ~%6.4 uzar).
        - speed_factor > 1.0: Hızlandırır (örneğin 1.02x -> süre ~%2.0 kısalır).
        - speed_factor == 1.0: Giriş dizisini doğrudan kopyalar.
        """
        sr = int(sample_rate or self.sample_rate)
        if audio is None or len(audio) == 0:
            return np.array([], dtype=np.float32)

        # Tek boyutlu float32 dizisi sağlama
        audio_1d = np.squeeze(audio).astype(np.float32)
        if audio_1d.ndim > 1:
            audio_1d = np.mean(audio_1d, axis=-1).astype(np.float32)

        # Hız 1.0 ise veya dizi çok kısaysa doğrudan dön
        if abs(speed_factor - 1.0) < 1e-4 or len(audio_1d) <= self.win_size * 2:
            return audio_1d.copy()

        # Zaman genişleme faktörü (alpha = 1 / speed)
        alpha = 1.0 / float(speed_factor)
        syn_hop = self.syn_hop
        ana_hop = int(round(syn_hop / alpha))
        if ana_hop <= 0:
            ana_hop = 1

        delta_max = self.delta_max
        win_size = self.win_size
        window = self.window

        # Hedef uzunluk ve tampon hazırlığı
        target_len = int(round(len(audio_1d) * alpha))
        if target_len <= 0:
            return audio_1d.copy()

        # Sınır taşmalarını önlemek için sonuna yansıtmalı padding ekle
        pad_len = win_size + delta_max + ana_hop * 2
        padded_audio = np.pad(audio_1d, (0, pad_len), mode="reflect")

        out_len = target_len + win_size * 2
        output = np.zeros(out_len, dtype=np.float32)
        norm = np.zeros(out_len, dtype=np.float32)

        # İlk tahılın (grain) yerleştirilmesi
        grain = padded_audio[:win_size] * window
        output[:win_size] += grain
        norm[:win_size] += window

        out_pos = syn_hop
        in_pos = ana_hop
        last_actual_in = 0

        # WSOLA döngüsü
        while out_pos < target_len and in_pos + win_size <= len(padded_audio):
            # Önceki tahılın doğal sentez devamı
            target_pos = min(len(padded_audio) - win_size, max(0, last_actual_in + syn_hop))
            target = padded_audio[target_pos:target_pos + win_size] * window

            # Nominal analiz konumu etrafında benzerlik araması
            search_start = max(0, in_pos - delta_max)
            search_end = min(len(padded_audio) - win_size, in_pos + delta_max)
            candidates = padded_audio[search_start:search_end + win_size]

            actual_in = in_pos
            if len(candidates) >= win_size:
                # Çapraz korelasyon ile en uyumlu faz kaymasını bul
                corrs = np.correlate(candidates, target, mode="valid")
                if len(corrs) > 0:
                    best_offset = int(np.argmax(corrs))
                    actual_in = search_start + best_offset

            last_actual_in = actual_in
            grain = padded_audio[actual_in:actual_in + win_size] * window
            output[out_pos:out_pos + win_size] += grain
            norm[out_pos:out_pos + win_size] += window

            out_pos += syn_hop
            in_pos += ana_hop

        # Örtüşen pencerelerin normalizasyonu
        mask = norm > 1e-6
        output[mask] /= norm[mask]

        result = output[:target_len]
        return result


# ============================================================================
# 2. Bağlamsal Prozodi Planlayıcı (Ajan 2 - HLS-02, HLS-04)
# ============================================================================
class ContextualProsodyPlanner:
    """
    LLM Niyet Etiketlerini (<intent:...>) Ayrıştıran ve Otomotiv Cümleciklerini
    Doğal Duraksamalarla Planlayan Motor.
    """

    INTENT_REGEX = re.compile(r"^\s*<intent:([a-z_]+)>\s*", re.IGNORECASE)

    # Niyet tahmin anahtar sözcükleri (LLM etiket basmazsa fallback için)
    KEYWORD_INTENTS: list[tuple[set[str], IntentCategory]] = [
        (
            {"tl", "lira", "fiyat", "fiyatı", "taksit", "kredi", "ötv", "kdv", "maliyet", "indirim", "kampanya", "bin", "milyon"},
            IntentCategory.PRICING,
        ),
        (
            {"?", "mi", "mı", "mu", "mü", "nasıl", "hangi", "ister misiniz", "tercih eder misiniz"},
            IntentCategory.QUESTION,
        ),
        (
            {"merhaba", "günaydın", "hoş geldiniz", "hoşgeldiniz", "selam", "iyi günler"},
            IntentCategory.GREETING,
        ),
        (
            {"garanti", "güvenlik", "servis", "kasko", "yetkili", "orijinal", "bakım", "rahat olun"},
            IntentCategory.REASSURANCE,
        ),
        (
            {"tavsiye", "öneri", "öneririm", "karşılaştır", "seçenek", "fırsat", "alternatif", "test sürüşü"},
            IntentCategory.RECOMMENDATION,
        ),
    ]

    @classmethod
    def parse_intent_tag(cls, text: str, default_intent: IntentCategory = IntentCategory.INFORM) -> tuple[str, IntentCategory]:
        """
        Metin başındaki `<intent:...>` etiketini ayıklar ve temiz konuşma metnini döndürür.
        Böylece etiket FreyaTTS tarafından asla seslendirilmez.
        """
        match = cls.INTENT_REGEX.match(text)
        if match:
            raw_tag = match.group(1).lower()
            clean_text = text[match.end():].strip()
            try:
                intent = IntentCategory(raw_tag)
            except ValueError:
                intent = default_intent
            return clean_text, intent

        # Etiket yoksa metin içeriğinden niyet tahminle
        lower_text = text.lower()
        for keywords, category in cls.KEYWORD_INTENTS:
            if any(kw in lower_text for kw in keywords):
                return text.strip(), category

        return text.strip(), default_intent

    @classmethod
    def get_profile(cls, intent: Union[str, IntentCategory]) -> ProsodyProfile:
        """Belirtilen niyet için prosodi profilini döndürür."""
        if isinstance(intent, str):
            try:
                cat = IntentCategory(intent.lower())
            except ValueError:
                cat = IntentCategory.INFORM
        else:
            cat = intent
        return INTENT_PROFILES.get(cat, INTENT_PROFILES[IntentCategory.INFORM])

    @classmethod
    def split_into_clauses(cls, text: str) -> list[str]:
        """
        Metni otomotiv varlıklarını (fiyat, model kodu, vb.) bölmeyecek şekilde
        anlamlı cümlecik sınırlarından (nokta, virgül, bağlaç) böler.
        """
        if not text:
            return []

        # Korunması gereken kalıplar: "1.250.000 TL", "1.5 TSI", "Peugeot 3008" vb.
        # Sayı ve birim arasındaki boşluk veya noktaları geçici koru
        protected = re.sub(r"(\d+)\.(\d+)", r"\1__DOT__\2", text)

        # Cümlecik ayırıcılar: ., !, ?, ;, iki nokta ve yan cümle virgülleri
        raw_parts = re.split(r"(?<=[.!?;\n])\s+|(?<=,)\s+", protected)

        clauses: list[str] = []
        for part in raw_parts:
            cleaned = part.replace("__DOT__", ".").strip()
            if cleaned:
                clauses.append(cleaned)

        return clauses if clauses else [text.strip()]


# ============================================================================
# 3. Kısa İfadeler İçin Süre Tabanı Kalkanı (Ajan 2 - HLS-05)
# ============================================================================
class DurationFloorGuard:
    """
    Kısa Yanıtların (Evet, Tamam, Anladım vb.) Süre Tahminleyicisi (Duration Predictor)
    Çökmesi Sonucu Metalik Kesik Ses Üretmesini Önleyen Taban Denetçisi.
    """

    @classmethod
    def apply_floor(
        cls,
        audio: np.ndarray,
        min_duration_sec: float = DEFAULT_MIN_DURATION_SEC,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> np.ndarray:
        """
        Süre eşiğinin altındaki seslere yumuşak konfor sönümlemesi ve minimum süre kazandırır.
        """
        if audio is None or len(audio) == 0:
            return np.array([], dtype=np.float32)

        min_samples = int(round(min_duration_sec * sample_rate))
        if len(audio) >= min_samples:
            return audio

        # Kısa sese yumuşak bir fade-out uygula ve gereken kadar konfor sessizliği ekle
        diff = min_samples - len(audio)
        fade_len = min(len(audio), int(round(0.015 * sample_rate)))  # 15 ms fade-out
        processed = audio.copy().astype(np.float32)
        if fade_len > 0:
            fade_curve = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
            processed[-fade_len:] *= fade_curve

        comfort_noise = (np.random.randn(diff).astype(np.float32) * 1e-5)
        padded = np.concatenate([processed, comfort_noise])
        return padded


# ============================================================================
# 4. Akustik Seslilik ve Bozukluk Denetleyicisi (Ajan 3)
# ============================================================================
class AudioVoicingChecker:
    """
    FreyaTTS Euler ODE Çözümünde Meydana Gelebilecek Fısıltı Çökmelerini (Whisper Collapse),
    Tam Sessizlikleri veya Kırpılma (Clipping) Bozulmalarını Tespit Eden Analizör.
    """

    @classmethod
    def check_quality(
        cls,
        audio: np.ndarray,
        sample_rate: Optional[int] = None,
        sr: Optional[int] = None,
    ) -> VoicingReport:
        effective_sr = int(sr or sample_rate or DEFAULT_SAMPLE_RATE)
        if audio is None or len(audio) == 0:
            return VoicingReport(
                is_valid=False,
                error_type="silent_collapse",
                voicedness_score=0.0,
                rms_energy=0.0,
                f0_estimate_hz=0.0,
                clipping_ratio=0.0,
            )

        audio_1d = np.squeeze(audio).astype(np.float32)
        total_samples = len(audio_1d)

        # 1. RMS Enerji Hesabı
        rms = float(np.sqrt(np.mean(np.square(audio_1d))))
        if rms < 1e-4:
            return VoicingReport(
                is_valid=False,
                error_type="silent_collapse",
                voicedness_score=0.0,
                rms_energy=rms,
                f0_estimate_hz=0.0,
                clipping_ratio=0.0,
            )

        # 2. Kırpılma (Clipping) Oranı
        clip_count = int(np.sum(np.abs(audio_1d) >= 0.99))
        clipping_ratio = clip_count / total_samples
        if clipping_ratio > 0.05:
            return VoicingReport(
                is_valid=False,
                error_type="clipped_distortion",
                voicedness_score=0.0,
                rms_energy=rms,
                f0_estimate_hz=0.0,
                clipping_ratio=clipping_ratio,
            )

        # 3. Otokorelasyon Tabanlı Seslilik (Voicedness) ve F0 Tahmini
        # Hızlı kontrol için ilk 10.000 örneği kullan
        inspect_len = min(total_samples, int(effective_sr * 0.25))
        segment = audio_1d[:inspect_len]
        corr = np.correlate(segment, segment, mode="full")
        corr = corr[len(corr) // 2 :]

        voicedness = 0.0
        f0_hz = 0.0
        if len(corr) > 1 and corr[0] > 1e-6:
            # 80 Hz - 400 Hz insan ses frekans aralığı
            min_lag = int(effective_sr / 400.0)
            max_lag = int(effective_sr / 80.0)
            if max_lag < len(corr):
                search_band = corr[min_lag:max_lag]
                peak_idx = int(np.argmax(search_band))
                peak_val = float(search_band[peak_idx])
                voicedness = max(0.0, min(1.0, peak_val / float(corr[0])))
                actual_lag = min_lag + peak_idx
                f0_hz = float(effective_sr / actual_lag) if actual_lag > 0 else 0.0

        if voicedness < 0.04 and rms > 1e-3:
            return VoicingReport(
                is_valid=False,
                error_type="whisper_collapse",
                voicedness_score=voicedness,
                rms_energy=rms,
                f0_estimate_hz=f0_hz,
                clipping_ratio=clipping_ratio,
            )

        return VoicingReport(
            is_valid=True,
            error_type=None,
            voicedness_score=voicedness,
            rms_energy=rms,
            f0_estimate_hz=f0_hz,
            clipping_ratio=clipping_ratio,
        )


# ============================================================================
# 5. Model Ağırlık ve Tohum Koruması (Ajan 2 - HLS-01 & Ajan 3)
# ============================================================================
class ModelHashAndSeedGuard:
    """
    LEYLA_SEED = 9 Sabitini Koruyan, Bozuk Çözümde Kimliği Bozmayan
    Kontrollü Mikro-Pertürbasyon Sağlayan Güvenlik Katmanı.
    """

    @classmethod
    def get_canonical_seed(cls) -> int:
        return LEYLA_SEED

    @classmethod
    def get_conditioned_noise_seed(cls, base_seed: int = LEYLA_SEED, attempt: int = 0) -> int:
        """
        Bozuk üretim durumunda Leyla ses kimliğini koruyarak küçük bir perturbasyon üretir.
        Rastgele seed kullanmaz (seed=None yasaktır).
        """
        if attempt == 0:
            return base_seed
        # Deterministik mikro kaydırma (Leyla latent manifoldunun yakın komşuluğunda kalır)
        return int(base_seed + attempt * 10007)

    @classmethod
    def verify_file_sha256(cls, file_path: Union[str, Path], expected_hash: Optional[str] = None) -> tuple[bool, str]:
        """Dosyanın SHA-256 özetini hesaplar ve doğrular."""
        p = Path(file_path)
        if not p.is_file():
            return False, ""
        hasher = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        calc_hash = hasher.hexdigest()
        is_match = (calc_hash == expected_hash) if expected_hash else True
        return is_match, calc_hash


# ============================================================================
# 6. Örtüşmeli Cümlecik Sentez ve Akış Motoru (Ajan 3 - RT-04, RT-05)
# ============================================================================
class OverlappingClauseStreamer:
    """
    Cümle N Telefonda Oynatılırken Cümle N+1'i Paralel Sentezleyen (Overlapping Synthesis),
    WSOLA İle Hızını ve Prozodisini Uyarlayan Boru Hattı.

    Özellikler:
    - Cümleler arası boşluğu 500 ms'den <120 ms'ye indirir.
    - Kesinti (Barge-in) anında stale generation_id kalkanıyla bekleyen tüm kuyruğu temizler.
    - Ses bozulması (whisper collapse) anında LEYLA_SEED kimliğini koruyarak otomatik telafi eder.
    """

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        wsola: Optional[WSOLATimeStretch] = None,
        planner: Optional[ContextualProsodyPlanner] = None,
        duration_guard: Optional[DurationFloorGuard] = None,
        voicing_checker: Optional[AudioVoicingChecker] = None,
    ):
        self.sample_rate = int(sample_rate)
        self.wsola = wsola or WSOLATimeStretch(sample_rate=self.sample_rate)
        self.planner = planner or ContextualProsodyPlanner()
        self.duration_guard = duration_guard or DurationFloorGuard()
        self.voicing_checker = voicing_checker or AudioVoicingChecker()

        # Aktif nesil ve iptal izleyicisi
        self._cancelled_generations: set[str] = set()
        self._lock = asyncio.Lock()

        # Telemetri
        self.total_utterances_processed = 0
        self.total_clauses_streamed = 0
        self.total_retries_prevented = 0
        self.total_overlaps_achieved = 0

    def cancel_generation(self, generation_id: str) -> None:
        """Belirtilen generation_id akışını anında iptal eder (Kesim 3)."""
        if generation_id:
            self._cancelled_generations.add(generation_id)
            logger.info(f"OverlappingClauseStreamer iptal sinyali alındı: {generation_id}")

    def is_cancelled(self, generation_id: str) -> bool:
        return generation_id in self._cancelled_generations

    def clear_cancelled(self, generation_id: str) -> None:
        self._cancelled_generations.discard(generation_id)

    async def _synthesize_single_clause(
        self,
        raw_clause_text: str,
        clause_index: int,
        intent: IntentCategory,
        profile: ProsodyProfile,
        generation_id: str,
        synth_fn: Callable[[str, int], Awaitable[np.ndarray]],
        is_first: bool,
        is_last: bool,
    ) -> Optional[SynthesizedClause]:
        """Tek bir yan cümleyi sentezler, denetler ve WSOLA ile esnetir."""
        if self.is_cancelled(generation_id):
            return None

        clean_clause = raw_clause_text.strip()
        if not clean_clause:
            return None

        t0_synth = time.perf_counter()
        attempt = 0
        max_attempts = 2
        audio_48k: Optional[np.ndarray] = None
        voicing_rep = None

        while attempt < max_attempts:
            seed = ModelHashAndSeedGuard.get_conditioned_noise_seed(attempt=attempt)
            try:
                raw_audio = await synth_fn(clean_clause, seed)
            except Exception as e:
                logger.error(f"Sentez hatası (cümlecik={clause_index}, deneme={attempt}): {e}")
                raw_audio = np.zeros(int(self.sample_rate * 0.5), dtype=np.float32)

            voicing_rep = self.voicing_checker.check_quality(raw_audio, self.sample_rate)
            if voicing_rep.is_valid:
                audio_48k = raw_audio
                if attempt > 0:
                    self.total_retries_prevented += 1
                break
            elif attempt == max_attempts - 1:
                audio_48k = raw_audio
                break
            else:
                self.total_retries_prevented += 1
                attempt += 1

        synth_ms = (time.perf_counter() - t0_synth) * 1000.0

        if self.is_cancelled(generation_id):
            return None

        # Süre tabanı uygula (tek kelimelik çöküşleri önle)
        audio_floored = self.duration_guard.apply_floor(
            audio_48k,
            min_duration_sec=DEFAULT_MIN_DURATION_SEC,
            sample_rate=self.sample_rate,
        )

        # WSOLA perde koruyucu zaman esnetme uygula
        t0_stretch = time.perf_counter()
        audio_stretched = self.wsola.stretch(
            audio_floored,
            speed_factor=profile.speed_factor,
            sample_rate=self.sample_rate,
        )
        stretch_ms = (time.perf_counter() - t0_stretch) * 1000.0

        dur_ms = (len(audio_stretched) / float(self.sample_rate)) * 1000.0

        return SynthesizedClause(
            clause_index=clause_index,
            raw_text=raw_clause_text,
            clean_text=clean_clause,
            intent=intent,
            speed_factor=profile.speed_factor,
            audio_48k=audio_floored,
            audio_stretched=audio_stretched,
            duration_ms=dur_ms,
            pre_pause_ms=profile.pre_pause_ms,
            post_pause_ms=profile.post_pause_ms,
            generation_id=generation_id,
            synth_latency_ms=synth_ms,
            stretch_latency_ms=stretch_ms,
            voicedness_score=voicing_rep.voicedness_score if voicing_rep else 1.0,
            f0_hz=voicing_rep.f0_estimate_hz if voicing_rep else 210.0,
            is_first=is_first,
            is_last=is_last,
        )

    async def stream_utterance(
        self,
        text: str,
        synth_fn: Callable[[str, int], Awaitable[np.ndarray]],
        generation_id: Optional[str] = None,
        forced_intent: Optional[Union[str, IntentCategory]] = None,
    ) -> AsyncGenerator[SynthesizedClause, None]:
        """
        Gelen metni cümleciklere bölerek örtüşmeli (pipelined) biçimde üretir ve yield eder.

        Cümlecik 0 oynatılırken Cümlecik 1 GPU'da paralel sentezlenir.
        """
        gen_id = generation_id or f"gen_{uuid.uuid4().hex[:8]}"
        self.clear_cancelled(gen_id)

        clean_text, detected_intent = self.planner.parse_intent_tag(text)
        intent = forced_intent or detected_intent
        profile = self.planner.get_profile(intent)

        clauses = self.planner.split_into_clauses(clean_text)
        if not clauses:
            return

        total_clauses = len(clauses)
        self.total_utterances_processed += 1

        # İlk cümleciği (N=0) derhal sentezle
        first_clause = await self._synthesize_single_clause(
            raw_clause_text=clauses[0],
            clause_index=0,
            intent=profile.intent,
            profile=profile,
            generation_id=gen_id,
            synth_fn=synth_fn,
            is_first=True,
            is_last=(total_clauses == 1),
        )

        if first_clause is None or self.is_cancelled(gen_id):
            return

        current_clause = first_clause
        next_task: Optional[asyncio.Task] = None

        try:
            for i in range(total_clauses):
                if self.is_cancelled(gen_id):
                    break

                # Eğer bir sonraki cümlecik varsa, GPU'da ÖRTÜŞMELİ (paralel) başlat
                if i + 1 < total_clauses:
                    next_task = asyncio.create_task(
                        self._synthesize_single_clause(
                            raw_clause_text=clauses[i + 1],
                            clause_index=i + 1,
                            intent=profile.intent,
                            profile=profile,
                            generation_id=gen_id,
                            synth_fn=synth_fn,
                            is_first=False,
                            is_last=(i + 1 == total_clauses - 1),
                        )
                    )
                    self.total_overlaps_achieved += 1

                # Mevcut cümleciği tüketiciye (oynatıcıya / Asterisk'e) sun
                self.total_clauses_streamed += 1
                yield current_clause

                # Tüketici mevcut cümleyi dinletirken next_task arka planda tamamlanır
                if next_task is not None:
                    next_clause = await next_task
                    if next_clause is None or self.is_cancelled(gen_id):
                        break
                    current_clause = next_clause
                    next_task = None
        finally:
            if next_task and not next_task.done():
                next_task.cancel()
            self.clear_cancelled(gen_id)


# Global Tekil Örnek
prosody_wsola_streamer = OverlappingClauseStreamer()

__all__ = [
    "LEYLA_SEED",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_MIN_DURATION_SEC",
    "IntentCategory",
    "ProsodyProfile",
    "INTENT_PROFILES",
    "VoicingReport",
    "SynthesizedClause",
    "WSOLATimeStretch",
    "ContextualProsodyPlanner",
    "DurationFloorGuard",
    "AudioVoicingChecker",
    "ModelHashAndSeedGuard",
    "OverlappingClauseStreamer",
    "prosody_wsola_streamer",
]
