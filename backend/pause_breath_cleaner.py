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

import hashlib
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger("pause_breath_cleaner")

LEYLA_SEED = 9
FRAME_BYTES_8K_20MS = 320  # 8000 Hz * 0.02 s * 2 bytes = 320 bytes (slin16)

# 1. En Sık Kullanılan 25 Kurumsal Otomotiv Çağrı Cümlesi (Top 25 Automotive Phrases)
TOP_25_AUTOMOTIVE_PHRASES: List[str] = [
    "Freya Ekspertiz merkezimize hoş geldiniz, ben dijital asistanınız Leyla. Size nasıl yardımcı olabilirim?",
    "Tabii ki, size memnuniyetle yardımcı olayım.",
    "Lütfen randevu almak istediğiniz aracın plakasını söyler misiniz?",
    "Plakanızı sisteme kaydediyorum, lütfen bir saniye bekleyin.",
    "Hangi ekspertiz paketimizi tercih edersiniz? Standart, motor mekanik veya full paketimiz bulunmaktadır.",
    "Standart ekspertiz paketimiz kaporta, boya mikron testi ve OBD arıza taramasını kapsar.",
    "Full kapsamlı paketimiz beş yüz nokta detaylı kontrol, kaporta, motor dyno ve yol testini içerir.",
    "Motor mekanik paketimiz dinamometre güç testi, şanzıman ve alt takım kontrollerini kapsar.",
    "Randevunuz için hangi gün ve saat dilimini tercih edersiniz?",
    "Şu anda tüm liftlerimiz müsaittir, aracınızı hemen muayeneye alabiliyoruz.",
    "Şu an iki liftimiz dolu, en erken saat on dört otuzda randevu verebiliyoruz.",
    "Seçtiğiniz tarih ve saat için randevunuz başarıyla oluşturuldu.",
    "Randevu detaylarınızı ve konumu SMS olarak cep telefonunuza iletiyorum.",
    "Aracınızda boyalı veya değişen parça bulunuyor mu?",
    "Tramer hasar kaydı veya ağır hasar durumu var mıdır?",
    "Tahmini piyasa değerini ve takas desteğimizi hesaplıyorum, lütfen bekleyin.",
    "Sizi çok iyi anlıyorum, fiyat ve paket içeriğimizle ilgili yardımcı olayım.",
    "Haklısınız, zamanınızı en iyi şekilde değerlendirmek için uygun saati planlayalım.",
    "Kararınızı rahatça vermeniz için detayları memnuniyetle paylaşabilirim.",
    "Sizi ekspertiz uzmanımıza ve canlı müşteri temsilcimize aktarıyorum, lütfen hattan ayrılmayın.",
    "Müşteri temsilcimiz hatta bağlandı, iyi günler dilerim.",
    "Söylediğinizi tam anlayamadım, rica etsem tekrar eder misiniz?",
    "Başka bir konuda yardımcı olabilir miyim?",
    "Bizi tercih ettiğiniz için teşekkür ederiz, ekspertiz şubemize bekleriz.",
    "İyi günler dilerim, güvenli sürüşler.",
]


def normalize_cache_key(text: str) -> str:
    """Metni noktalama ve boşluklardan arındırarak standart önbellek anahtarına dönüştürür."""
    t = text.lower().strip()
    t = re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]", "", t)
    return t


def find_nearest_zero_crossing(signal: np.ndarray, index: int, window: int = 120) -> int:
    """
    Belirtilen indeks civarında sıfır geçişi (zero-crossing) noktasını bulur.
    Böylece ses birleştirmelerinde dijital tıklama/patlama (click/pop) engellenir.
    """
    if len(signal) == 0:
        return 0
    start = max(0, index - window)
    end = min(len(signal) - 1, index + window)
    if start >= end:
        return index

    sub = signal[start:end]
    zero_crossings = np.where(np.diff(np.signbit(sub)))[0]
    if len(zero_crossings) == 0:
        # Minimum mutlak değer noktasını bul
        best_local = int(np.argmin(np.abs(sub)))
        return start + best_local

    best_local = zero_crossings[np.argmin(np.abs(zero_crossings - (index - start)))]
    return start + int(best_local)


@dataclass
class BreathCleaningResult:
    cleaned_samples: np.ndarray
    original_length: int
    cleaned_length: int
    leading_fade_samples: int
    trailing_fade_samples: int
    breath_spikes_detected: int
    comfort_noise_added_samples: int
    sample_rate: int = 8000

    @property
    def cleaned_audio(self) -> np.ndarray:
        return self.cleaned_samples

    @property
    def breath_spike_detected(self) -> bool:
        return self.breath_spikes_detected > 0

    @property
    def leading_trimmed_samples(self) -> int:
        return self.leading_fade_samples

    @property
    def trailing_trimmed_samples(self) -> int:
        return self.trailing_fade_samples

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_length": self.original_length,
            "cleaned_length": self.cleaned_length,
            "leading_fade_samples": self.leading_fade_samples,
            "trailing_fade_samples": self.trailing_fade_samples,
            "breath_spikes_detected": self.breath_spikes_detected,
            "comfort_noise_added_samples": self.comfort_noise_added_samples,
            "sample_rate": self.sample_rate,
        }


class PauseBreathCleaner:
    """
    Duraksama Nefes Temizleyici ve Akustik Eklem Yumuşatıcı (DSP).
    - Cümle başı ve sonundaki nefes/aspirasyon tepeciklerini (inhalation noise) bastırır.
    - Sıfır geçişi (zero-crossing) ile pürüzsüz birleştirme yapar.
    - Cümle arası duraksama boşluklarına -58 dBFS konfor gürültüsü enjekte eder.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 8000,
        fade_ms: float = 12.0,
        breath_threshold_ratio: float = 0.22,
        comfort_noise_dbfs: float = -58.0,
    ):
        self.sample_rate = sample_rate
        self.fade_ms = fade_ms
        self.breath_threshold_ratio = breath_threshold_ratio
        self.comfort_noise_dbfs = comfort_noise_dbfs
        self.comfort_noise_rms = 10.0 ** (comfort_noise_dbfs / 20.0)

    def clean_waveform_edges(
        self,
        waveform: np.ndarray,
        sample_rate: Optional[int] = None,
        fade_ms: Optional[float] = None,
    ) -> BreathCleaningResult:
        """
        Tek bir ses dalga formunun baş ve sonundaki olası nefes/klik patlamalarını temizler.
        """
        sr = sample_rate or self.sample_rate
        orig_len = len(waveform)
        if orig_len == 0:
            return BreathCleaningResult(
                cleaned_samples=np.zeros(0, dtype=np.float32),
                original_length=0,
                cleaned_length=0,
                leading_fade_samples=0,
                trailing_fade_samples=0,
                breath_spikes_detected=0,
                comfort_noise_added_samples=0,
                sample_rate=sr,
            )

        audio = waveform.copy().astype(np.float32)
        active_fade_ms = fade_ms if fade_ms is not None else self.fade_ms
        fade_samples = max(8, int((active_fade_ms / 1000.0) * sr))
        breath_spikes = 0

        # 1. Başlangıç Nefes Taraması (Leading Inhalation Spike)
        head_window = min(len(audio), int(0.08 * sr))  # İlk 80 ms
        if head_window > fade_samples:
            head_chunk = audio[:head_window]
            rms_head = np.sqrt(np.mean(head_chunk ** 2))
            rms_total = np.sqrt(np.mean(audio ** 2))
            if rms_total > 1e-4 and (rms_head / rms_total) > self.breath_threshold_ratio:
                breath_spikes += 1

        # Başlangıca yumuşak kosinüs fade-in
        fade_in_len = min(fade_samples, len(audio) // 2)
        if fade_in_len > 0:
            fade_in = 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, fade_in_len)))
            audio[:fade_in_len] *= fade_in

        # 2. Bitiş Nefes Taraması (Trailing Aspiration Spike)
        tail_window = min(len(audio), int(0.12 * sr))  # Son 120 ms
        if tail_window > fade_samples:
            tail_chunk = audio[-tail_window:]
            rms_tail = np.sqrt(np.mean(tail_chunk ** 2))
            rms_total = np.sqrt(np.mean(audio ** 2))
            if rms_total > 1e-4 and (rms_tail / rms_total) > self.breath_threshold_ratio:
                breath_spikes += 1

        # Bitişe yumuşak kosinüs fade-out
        fade_out_len = min(fade_samples, len(audio) // 2)
        if fade_out_len > 0:
            fade_out = 0.5 * (1.0 + np.cos(np.linspace(0, np.pi, fade_out_len)))
            audio[-fade_out_len:] *= fade_out

        return BreathCleaningResult(
            cleaned_samples=audio,
            original_length=orig_len,
            cleaned_length=len(audio),
            leading_fade_samples=fade_in_len,
            trailing_fade_samples=fade_out_len,
            breath_spikes_detected=breath_spikes,
            comfort_noise_added_samples=0,
            sample_rate=sr,
        )

    def splice_clauses_with_clean_pause(
        self,
        clause_waves: List[np.ndarray],
        pause_durations_sec: Optional[Union[List[float], float]] = None,
        sample_rate: Optional[int] = None,
        add_comfort_noise: bool = True,
        pause_duration_ms: Optional[float] = None,
    ) -> np.ndarray:
        """
        Birden çok yan cümleyi sıfır geçişiyle ve gürültü kapılı temiz duraksamalarla bağlar.
        """
        sr = sample_rate or self.sample_rate
        if not clause_waves:
            return np.zeros(0, dtype=np.float32)

        parts: List[np.ndarray] = []
        rng = np.random.default_rng(LEYLA_SEED)

        # Duraksama süresini normalize et
        default_pause = 0.15
        if pause_duration_ms is not None:
            default_pause = pause_duration_ms / 1000.0
        elif isinstance(pause_durations_sec, (int, float)):
            default_pause = float(pause_durations_sec)

        for idx, wave in enumerate(clause_waves):
            clean_res = self.clean_waveform_edges(wave, sample_rate=sr)
            cleaned = clean_res.cleaned_samples
            parts.append(cleaned)

            if idx < len(clause_waves) - 1:
                if isinstance(pause_durations_sec, list) and idx < len(pause_durations_sec):
                    pause_sec = pause_durations_sec[idx]
                else:
                    pause_sec = default_pause

                if pause_sec > 0.001:
                    pause_samples_len = int(pause_sec * sr)
                    if add_comfort_noise:
                        # Duraksama aralığına hafif konfor gürültüsü (-58 dBFS)
                        noise = rng.normal(0.0, self.comfort_noise_rms, pause_samples_len).astype(np.float32)
                        # Gürültü kenarlarına 5 ms fade
                        edge_len = min(int(0.005 * sr), pause_samples_len // 2)
                        if edge_len > 0:
                            noise[:edge_len] *= np.linspace(0, 1, edge_len)
                            noise[-edge_len:] *= np.linspace(1, 0, edge_len)
                        parts.append(noise)
                    else:
                        parts.append(np.zeros(pause_samples_len, dtype=np.float32))

        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


@dataclass
class CacheEntry:
    phrase_id: str
    original_text: str
    normalized_key: str
    slin16_bytes: bytes
    duration_seconds: float
    frame_count_20ms: int
    hit_count: int = 0
    created_at: float = field(default_factory=time.monotonic)


class TelephonyAudioCachePool:
    """
    Sık Kullanılan 25 Kurumsal Cümleyi RAM'de 8 kHz slin16 Formatında Saklayan
    Sıfır Gecikmeli Önbellek Havuzu (Zero Inference Latency Cache).
    """

    def __init__(self, seed: int = LEYLA_SEED, sample_rate: int = 8000):
        self.seed = seed
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._cache: Dict[str, CacheEntry] = {}
        self.total_lookups: int = 0
        self.hit_count: int = 0
        self.miss_count: int = 0

    @property
    def cache(self) -> Dict[str, CacheEntry]:
        return self._cache

    def has(self, text: str) -> bool:
        key = normalize_cache_key(text)
        with self._lock:
            return key in self._cache

    def warm_cache_with_phrases(
        self,
        synthesize_func_or_phrases: Optional[Union[Callable[[str, int], np.ndarray], List[str]]] = None,
        synthesize_func: Optional[Callable[[str, int], np.ndarray]] = None,
    ) -> int:
        """
        En sık kullanılan 25 kurumsal otomotiv cümlesini önbelleğe yükler.
        synthesize_func None ise temiz yapay ses sinyali ile ısıtma simüle edilir.
        """
        loaded = 0
        sr = self.sample_rate

        # Parametre kontrolü (hem phrases listesi hem callable kabul eder)
        if isinstance(synthesize_func_or_phrases, list):
            phrases = synthesize_func_or_phrases
            synth = synthesize_func
        elif callable(synthesize_func_or_phrases):
            phrases = TOP_25_AUTOMOTIVE_PHRASES
            synth = synthesize_func_or_phrases
        else:
            phrases = TOP_25_AUTOMOTIVE_PHRASES
            synth = synthesize_func

        for idx, phrase in enumerate(phrases, start=1):
            key = normalize_cache_key(phrase)
            if key in self._cache:
                continue

            if synth is not None:
                try:
                    pcm_float = synth(phrase, self.seed)
                except Exception as e:
                    logger.warning("Cümle sentezlenemedi, yapay sinyalle ısıtılıyor: %s (%s)", phrase, e)
                    pcm_float = self._generate_synthetic_speech_wave(phrase, sr)
            else:
                pcm_float = self._generate_synthetic_speech_wave(phrase, sr)

            # float32 -> int16 slin16 PCM baytları
            int16_arr = np.clip(pcm_float * 32767.0, -32768.0, 32767.0).astype(np.int16)
            slin16 = int16_arr.tobytes()

            dur = len(int16_arr) / float(sr)
            frame_cnt = len(slin16) // FRAME_BYTES_8K_20MS

            entry = CacheEntry(
                phrase_id=f"leyla-cache-{idx:02d}",
                original_text=phrase,
                normalized_key=key,
                slin16_bytes=slin16,
                duration_seconds=round(dur, 3),
                frame_count_20ms=frame_cnt,
            )

            with self._lock:
                self._cache[key] = entry
            loaded += 1

        logger.info("TelephonyAudioCachePool: %d kurumsal cümle RAM'e yüklendi.", loaded)
        return loaded

    def _generate_synthetic_speech_wave(self, text: str, sample_rate: int = 8000) -> np.ndarray:
        """Test ve soğuk açılış için stabil yapay Leyla tonu üretir."""
        dur = max(0.6, len(text) * 0.055)
        t = np.linspace(0, dur, int(sample_rate * dur), endpoint=False)
        # 210 Hz temel frekans (Leyla kadın sesi armonikleri)
        f0 = 210.0
        wave = (
            0.35 * np.sin(2 * np.pi * f0 * t)
            + 0.18 * np.sin(2 * np.pi * (2 * f0) * t)
            + 0.08 * np.sin(2 * np.pi * (3 * f0) * t)
        ).astype(np.float32)

        # 15 ms başlangıç/bitiş yumuşatma
        fade_len = int(0.015 * sample_rate)
        if fade_len > 0 and len(wave) > 2 * fade_len:
            wave[:fade_len] *= np.linspace(0, 1, fade_len)
            wave[-fade_len:] *= np.linspace(1, 0, fade_len)

        return wave

    def get(self, text: str) -> Optional[bytes]:
        """Metin önbellekte varsa 8 kHz slin16 baytlarını döndürür (0 ms gecikme)."""
        key = normalize_cache_key(text)
        with self._lock:
            self.total_lookups += 1
            if key in self._cache:
                self.hit_count += 1
                entry = self._cache[key]
                entry.hit_count += 1
                return entry.slin16_bytes
            else:
                self.miss_count += 1
                return None

    def get_20ms_frames(self, text: str) -> Optional[List[bytes]]:
        """AudioSocket veya chan_websocket için önceden dilimlenmiş 320-baytlık çerçeveler döndürür."""
        slin16 = self.get(text)
        if not slin16:
            return None

        frames: List[bytes] = []
        for i in range(0, len(slin16) - FRAME_BYTES_8K_20MS + 1, FRAME_BYTES_8K_20MS):
            frames.append(slin16[i : i + FRAME_BYTES_8K_20MS])
        return frames

    def put(self, text: str, slin16_bytes: bytes) -> CacheEntry:
        """Harici olarak sentezlenen bir cümleyi önbelleğe ekler."""
        key = normalize_cache_key(text)
        dur = len(slin16_bytes) / (8000.0 * 2.0)
        frame_cnt = len(slin16_bytes) // FRAME_BYTES_8K_20MS

        entry = CacheEntry(
            phrase_id=f"custom-{hashlib.md5(key.encode('utf-8')).hexdigest()[:8]}",
            original_text=text,
            normalized_key=key,
            slin16_bytes=slin16_bytes,
            duration_seconds=round(dur, 3),
            frame_count_20ms=frame_cnt,
        )
        with self._lock:
            self._cache[key] = entry
        return entry

    def get_metrics(self) -> Dict[str, Any]:
        """Önbellek kullanım ve bellek metriklerini döndürür."""
        with self._lock:
            total_bytes = sum(len(e.slin16_bytes) for e in self._cache.values())
            hit_rate = (
                round((self.hit_count / self.total_lookups) * 100, 2)
                if self.total_lookups > 0
                else 0.0
            )
            entries_summary = [
                {
                    "phrase_id": e.phrase_id,
                    "text": e.original_text,
                    "duration_seconds": e.duration_seconds,
                    "frame_count_20ms": e.frame_count_20ms,
                    "hit_count": e.hit_count,
                }
                for e in self._cache.values()
            ]

        return {
            "cached_phrases_count": len(self._cache),
            "total_cached_bytes": total_bytes,
            "total_cached_megabytes": round(total_bytes / (1024 * 1024), 3),
            "total_lookups": self.total_lookups,
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "hit_rate_percent": hit_rate,
            "seed": self.seed,
            "entries": entries_summary,
        }

    def clear(self):
        """Önbelleği temizler."""
        with self._lock:
            self._cache.clear()
            self.total_lookups = 0
            self.hit_count = 0
            self.miss_count = 0


# Global Singleton Instances
pause_breath_cleaner = PauseBreathCleaner()
telephony_audio_cache = TelephonyAudioCachePool()

# Başlangıçta 25 cümleyi RAM'e ısıt
telephony_audio_cache.warm_cache_with_phrases()
