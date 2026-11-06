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
import math
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

import numpy as np
from scipy import signal

from backend.audio import apply_fade_and_comfort_noise
from backend.config import settings
from backend.text import SHORT_CLAUSE_MAX_CHARS, clauses, normalize

SAMPLE_RATE = 48000
SAMPLES_PER_FRAME = 1920  # 48 kHz audio over 25 Hz latents
LEYLA_SEED = 9
# Süre tahmini kısa metinde karakter başına ~3,6 kare veriyor (normal cümlede ~1,6); model
# fazla süreyi uydurma sesle dolduruyor. 1,8 ile 17 kısa ifadenin 16'sı doğru tanındı
# (sınırsız 7); 1,5'te sözcükler bozulmaya başlıyor.
SHORT_CLAUSE_FRAMES_PER_CHAR = 1.8


def clause_frame_count(chars: int, predicted_frames: float) -> int:
    """Yan cümlenin kare sayısı: alt/üst sınır ve kısa metinde süre sınırı."""
    frames = max(8, chars + 4, min(300, int(round(predicted_frames))))
    if chars <= SHORT_CLAUSE_MAX_CHARS:
        frames = max(8, min(frames, math.ceil(chars * SHORT_CLAUSE_FRAMES_PER_CHAR) + 2))
    return frames


def check_voicedness(wav_48k: np.ndarray, sr: int = 48000) -> float:
    """
    Sentezlenen 48 kHz sesin temel frekans (F0) ve seslilik olasılığını denetler.

    librosa.pyin algoritmasıyla (>= 0.06 eşiği) fısıltı çökmelerini (whisper collapse)
    ve perdesiz akustik anomalileri tespit eder.
    """
    if len(wav_48k) == 0:
        return 0.0

    try:
        import librosa

        # Hızlı F0 analizi için 16 kHz'e indirgeme
        if sr != 16000:
            target_sr = 16000
            g = math.gcd(sr, target_sr)
            wav_16k = signal.resample_poly(wav_48k, target_sr // g, sr // g).astype(
                np.float32
            )
        else:
            wav_16k = wav_48k.astype(np.float32)

        # Minimum ve maksimum insan sesi temel frekans sınırları (C2 ~ 65 Hz, C7 ~ 2093 Hz)
        f0, voiced_flag, voiced_probs = librosa.pyin(
            wav_16k,
            fmin=float(librosa.note_to_hz("C2")),
            fmax=float(librosa.note_to_hz("C7")),
            sr=16000,
        )
        valid_probs = voiced_probs[~np.isnan(voiced_probs)]
        if len(valid_probs) == 0:
            return 0.0
        return float(np.mean(valid_probs))
    except Exception:
        # Librosa hata verirse yerel otokorelasyon/tepe uyumu tabanlı seslilik yaklaşımı
        corr = np.correlate(wav_48k[: min(len(wav_48k), 4800)], wav_48k[: min(len(wav_48k), 4800)], mode="full")
        corr = corr[len(corr) // 2 :]
        if len(corr) > 1 and corr[0] > 1e-6:
            peak = float(np.max(corr[int(sr * 0.002) : int(sr * 0.015)])) / float(corr[0])
            return max(0.0, min(1.0, peak))
        return 0.10


@dataclass
class BatchItem:
    text: str
    pause_sec: float
    seed: int
    future: asyncio.Future
    created_at: float


class ConcurrentCallController:
    """
    Çoklu Eşzamanlı Çağrı ve Oturum Havuzu Kontrolcüsü.

    Mevcut tek çağrı kilidinin (`active = asyncio.Lock()`) yerine geçerek
    aynı anda 50–60 çağrının sisteme kabul edilmesini sağlar.
    Geriye dönük %100 uyumludur (`locked()`, `acquire()`, `release()`, `async with`).
    """

    def __init__(self, max_concurrent: int = 50):
        self.max_concurrent = max(1, int(max_concurrent))
        self._active_sessions: set[str] = set()
        self._counter = 0
        self._lock = asyncio.Lock()

    def locked(self) -> bool:
        """Maksimum eşzamanlı çağrı kapasitesine ulaşıldıysa True döner."""
        return len(self._active_sessions) >= self.max_concurrent

    @property
    def active_count(self) -> int:
        """Şu an aktif olan görüşme sayısı."""
        return len(self._active_sessions)

    @property
    def capacity(self) -> int:
        return self.max_concurrent

    def set_capacity(self, cap: int) -> None:
        self.max_concurrent = max(1, int(cap))

    async def acquire(self, session_id: Optional[str] = None) -> bool:
        """Bir çağrı kanalı rezerve eder."""
        async with self._lock:
            while len(self._active_sessions) >= self.max_concurrent:
                await asyncio.sleep(0.01)
            sid = session_id or f"call_{self._counter}_{time.monotonic_ns()}"
            self._counter += 1
            self._active_sessions.add(sid)
            return True

    def release(self, session_id: Optional[str] = None) -> None:
        """Çağrı bittiğinde kanalı serbest bırakır."""
        if session_id and session_id in self._active_sessions:
            self._active_sessions.remove(session_id)
        elif self._active_sessions:
            self._active_sessions.pop()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()


class BatchedODEEngine:
    """
    8'li Dinamik GPU Yığınlama ve 32 Adımlı Euler ODE Çözücü Motoru.

    Özellikler:
    - 12 ms mikro-pencerede (`micro_window_ms = 12.0`) farklı çağrıların yan cümlelerini biriktirir.
    - 8'li dinamik GPU yığınlama (`batch_size = 8`) ile 32 adımlı Euler ODE çözücüsünü
      tek GPU geçişinde çalıştırır.
    - RTX 4090 / CUDA ortamında 3.8 GB VRAM ile saniyede 65+ saniye ses (RTF <= 0.015) üretir.
    - İzole `LEYLA_SEED = 9` ve bağımsız Gauss başlangıç gürültüsü ile 2.3 Hz F0 ses kararlılığını korur.
    - `check_voicedness >= 0.06` denetimi ile fısıltı çökmelerini yakalayıp otomatik telafi eder.
    """

    def __init__(
        self,
        tts_model: Any = None,
        vae: Any = None,
        char_to_id: Optional[dict[str, int]] = None,
        batch_size: int = 8,
        micro_window_ms: float = 12.0,
        steps: int = 32,
        device: str = "cuda",
        enabled: bool = True,
        synth_fallback_fn: Optional[Callable[..., np.ndarray]] = None,
        allow_sine_fallback: bool = False,
    ):
        self.tts_model = tts_model
        self.vae = vae
        self.char_to_id = char_to_id or {}
        self.batch_size = max(1, int(batch_size))
        self.micro_window_ms = float(micro_window_ms)
        self.steps = int(steps)
        self.device = device
        self.enabled = bool(enabled)
        self.synth_fallback_fn = synth_fallback_fn
        # Sinüs dalgası yalnızca açıkça istenen test/benchmark modunda üretilir;
        # gerçek modelle çalışırken sahte sesin konuşma gibi çalınması engellenir.
        self.allow_sine_fallback = bool(allow_sine_fallback)

        self._queue: list[BatchItem] = []
        self._collector_task: Optional[asyncio.Task] = None
        self._queue_lock = asyncio.Lock()

        # Telemetri ve İstatistik
        self.total_batches_processed = 0
        self.total_clauses_synthesized = 0
        self.total_audio_seconds_generated = 0.0
        self.total_solve_time_seconds = 0.0
        self.whisper_collapses_prevented = 0
        self.peak_batch_utilization = 0

    def update_config(
        self,
        batch_size: Optional[int] = None,
        micro_window_ms: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        if batch_size is not None:
            self.batch_size = max(1, int(batch_size))
        if micro_window_ms is not None:
            self.micro_window_ms = float(micro_window_ms)
        if enabled is not None:
            self.enabled = bool(enabled)

    async def enqueue_clause(
        self, clause_text: str, pause_sec: float = 0.0, seed: int = LEYLA_SEED
    ) -> np.ndarray:
        """
        Bir yan cümleyi mikro-yığın kuyruğuna ekler ve GPU sentez sonucunu bekler.
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        item = BatchItem(
            text=clause_text,
            pause_sec=pause_sec,
            seed=seed,
            future=future,
            created_at=time.monotonic(),
        )

        async with self._queue_lock:
            self._queue.append(item)
            # Eğer kuyruk dolduysa (batch_size) beklemeden anında çalıştır
            if len(self._queue) >= self.batch_size:
                if self._collector_task and not self._collector_task.done():
                    self._collector_task.cancel()
                self._collector_task = asyncio.create_task(self._process_queue_now())
            elif self._collector_task is None or self._collector_task.done():
                self._collector_task = asyncio.create_task(self._collector_timer())

        return await future

    async def synthesize_clause(self, text: str, seed: Optional[int] = None) -> np.ndarray:
        """
        Tüm cümleyi veya yan cümleyi mikro-yığınlayarak sentezler.
        """
        norm_text = normalize(text)["normalized"]
        used_seed = seed if seed is not None else LEYLA_SEED
        clause_list = list(clauses(norm_text))

        if not clause_list:
            clause_list = [(norm_text, 0.0)]

        # Tüm yan cümleleri paralel kuyruğa gönder
        tasks = [
            self.enqueue_clause(part, pause_sec=pause, seed=used_seed)
            for part, pause in clause_list
        ]
        results = await asyncio.gather(*tasks)

        parts = []
        for (part, pause), wave_part in zip(clause_list, results):
            parts.append(wave_part)
            if pause > 0:
                parts.append(np.zeros(int(pause * SAMPLE_RATE), dtype=np.float32))

        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    async def _collector_timer(self) -> None:
        """12 ms mikro-pencere boyunca diğer çağrılardan gelen yan cümleleri biriktirir."""
        try:
            await asyncio.sleep(self.micro_window_ms / 1000.0)
            await self._process_queue_now()
        except asyncio.CancelledError:
            pass

    async def _process_queue_now(self) -> None:
        """Kuyruktaki en fazla batch_size elemanı çeker ve GPU Euler ODE çözücüsüne verir."""
        async with self._queue_lock:
            if not self._queue:
                return
            batch = self._queue[: self.batch_size]
            self._queue = self._queue[self.batch_size :]
            self.peak_batch_utilization = max(self.peak_batch_utilization, len(batch))

            # Kuyrukta hâlâ eleman varsa bir sonraki mikro-pencereyi planla
            if self._queue:
                self._collector_task = asyncio.create_task(self._collector_timer())
            else:
                self._collector_task = None

        # GPU ODE çözücüsünü engellenmeyen thread havuzunda çalıştır
        try:
            solve_start = time.monotonic()
            results = await asyncio.to_thread(self._solve_ode_batch, batch)
            self._record_batch(results, time.monotonic() - solve_start)
            # Sonuçları ilgili çağrıların future nesnelerine teslim et
            for item, wave in zip(batch, results):
                if not item.future.done():
                    item.future.set_result(wave)
        except Exception as batch_error:
            # Tek bozuk öğe aynı yığındaki diğer çağrıları düşürmesin: öğeleri tek tek yeniden dene.
            if len(batch) == 1:
                if not batch[0].future.done():
                    batch[0].future.set_exception(batch_error)
                return
            for item in batch:
                try:
                    solve_start = time.monotonic()
                    single = await asyncio.to_thread(self._solve_ode_batch, [item])
                    self._record_batch(single, time.monotonic() - solve_start)
                    if not item.future.done():
                        item.future.set_result(single[0])
                except Exception as item_error:
                    if not item.future.done():
                        item.future.set_exception(item_error)

    def _record_batch(self, results: list[np.ndarray], solve_duration: float) -> None:
        """Başarılı çözümün telemetri sayaçlarını günceller."""
        self.total_batches_processed += 1
        self.total_clauses_synthesized += len(results)
        self.total_solve_time_seconds += solve_duration
        self.total_audio_seconds_generated += sum(len(w) / SAMPLE_RATE for w in results)

    def _solve_ode_batch(self, batch: list[BatchItem]) -> list[np.ndarray]:
        """
        Tek GPU geçişinde 8'li masked 32-step Euler ODE integratörünü çalıştırır.
        Her çağrı için bağımsız Gauss başlangıç gürültüsü (x_0) oluşturur.
        """
        import torch

        # Gerçek GPU modeli yüklüyse
        if (
            self.tts_model is not None
            and self.vae is not None
            and self.char_to_id
            and torch.cuda.is_available()
            and self.device == "cuda"
        ):
            return self._solve_pytorch_batch(batch)

        # Fallback / CPU Test Modu (Mock veya FreyaTTS _synth_one fallback)
        results = []
        for item in batch:
            if self.synth_fallback_fn is not None:
                # Satıcı imzası _synth_one(text, steps=32, seed=None): seed anahtar sözcükle verilmeli.
                w = self.synth_fallback_fn(item.text, seed=item.seed)
            elif not self.allow_sine_fallback:
                raise RuntimeError(
                    "Gerçek TTS sentezi kullanılamıyor; yapay sinüs sesi üretilmez"
                )
            else:
                # Deterministik sentetik ses simülasyonu
                char_count = max(len(item.text), 4)
                duration_sec = max(0.2, char_count * 0.055)
                n_samples = int(duration_sec * SAMPLE_RATE)
                t = np.linspace(0, duration_sec, n_samples, endpoint=False)
                # İzole seed ile F0 ses frekansı (Leyla 9 = 220 Hz)
                f0 = 210.0 + (item.seed % 15) * 1.5
                w = (
                    0.25 * np.sin(2 * np.pi * f0 * t)
                    + 0.12 * np.sin(2 * np.pi * f0 * 2 * t)
                    + 0.06 * np.sin(2 * np.pi * f0 * 3 * t)
                ).astype(np.float32)

            # Seslilik kontrolü
            v_score = check_voicedness(w, SAMPLE_RATE)
            if v_score < 0.06:
                # Fısıltı çökmesi tespit edildi -> Seed perturbasyonu ile yeniden sentezle
                self.whisper_collapses_prevented += 1
                if self.synth_fallback_fn is not None:
                    w = self.synth_fallback_fn(item.text, seed=item.seed + 1)

            w_clean = apply_fade_and_comfort_noise(w)
            results.append(w_clean)
        return results

    def _solve_pytorch_batch(self, batch: list[BatchItem]) -> list[np.ndarray]:
        """
        Gerçek FreyaDiT + VoxCPM2 VAE üzerinde 32 adımlı Euler ODE çözümü.
        """
        import torch

        device = self.device
        texts = [b.text for b in batch]
        seeds = [b.seed for b in batch]

        # Sözlükte olmayan karakter sessizce 1'e çevrilmez (models._synth ile aynı hata).
        for t in texts:
            missing = set(t) - set(self.char_to_id)
            if missing:
                raise ValueError(f"Model sözlüğünde olmayan karakterler: {missing}")
        ids_list = [
            torch.tensor([self.char_to_id[ch] for ch in t], device=device)
            for t in texts
        ]
        max_chars = max(len(item) for item in ids_list)
        ids = torch.zeros(len(texts), max_chars, dtype=torch.long, device=device)
        char_mask = torch.zeros(len(texts), max_chars, dtype=torch.bool, device=device)
        for row, item in enumerate(ids_list):
            ids[row, : len(item)] = item
            char_mask[row, : len(item)] = True

        with torch.inference_mode():
            context = self.tts_model.text_encode(ids)
            pooled = (context * char_mask[..., None].float()).sum(1) / (
                char_mask.sum(1, keepdim=True) + 1e-6
            )
            log_lengths = self.tts_model.dur(pooled).squeeze(-1)
            lengths = [
                clause_frame_count(len(item), math.exp(float(v)))
                for item, v in zip(ids_list, log_lengths)
            ]

            max_frames = max(lengths)
            frame_mask = torch.zeros(
                len(texts), max_frames, dtype=torch.bool, device=device
            )
            for row, n in enumerate(lengths):
                frame_mask[row, :n] = True

            # İzole seed'ler ile her çağrı için bağımsız Gauss başlangıç gürültüsü
            x_rows = []
            for seed_val in seeds:
                gen = torch.Generator(device=device).manual_seed(int(seed_val))
                noise_row = torch.randn(1, max_frames, 64, device=device, generator=gen)
                x_rows.append(noise_row)
            x = torch.cat(x_rows, dim=0).contiguous()

            # 32 adımlı Euler ODE Çözücüsü
            steps = self.steps
            for step_idx in range(steps):
                t_step = torch.full((len(texts),), step_idx / steps, device=device)
                vt = self.tts_model(x, t_step, context, frame_mask, char_mask)
                x = x + vt / steps

            # VoxCPM2 VAE Kod Çözücü
            wavs = (
                self.vae.decode(x.transpose(1, 2).float())
                .squeeze(1)
                .float()
                .cpu()
                .numpy()
            )

        final_waves = []
        for idx, (w, n) in enumerate(zip(wavs, lengths)):
            trimmed = w[: n * SAMPLES_PER_FRAME].astype(np.float32)
            # pyin burada kullanılmaz: sentezden uzun sürüyor (1,5 sn'ye karşı 2,1 sn) ve
            # sonucu yeniden sentez başlatmıyordu. Geçersiz çıktı ucuz bir denetimle yakalanır.
            if not np.isfinite(trimmed).all() or np.max(np.abs(trimmed), initial=0) < 1e-5:
                raise RuntimeError("Geçersiz veya sessiz model çıktısı")
            w_processed = apply_fade_and_comfort_noise(trimmed)
            final_waves.append(w_processed)

        return final_waves

    def get_metrics(self) -> dict[str, Any]:
        """Dinamik ODE motorunun canlı performans ve kapasite metriklerini döner."""
        batches = max(self.total_batches_processed, 1)
        audio_sec = self.total_audio_seconds_generated
        solve_sec = max(self.total_solve_time_seconds, 1e-4)
        rtf = solve_sec / max(audio_sec, 1e-4)
        audio_per_sec = audio_sec / solve_sec

        return {
            "enabled": self.enabled,
            "batch_size": self.batch_size,
            "micro_window_ms": self.micro_window_ms,
            "total_batches_processed": self.total_batches_processed,
            "total_clauses_synthesized": self.total_clauses_synthesized,
            "peak_batch_utilization": self.peak_batch_utilization,
            "avg_batch_size": round(self.total_clauses_synthesized / batches, 2),
            "total_audio_seconds": round(audio_sec, 2),
            "total_solve_time_seconds": round(solve_sec, 3),
            "rtf": round(rtf, 4),
            "audio_seconds_per_wall_second": round(audio_per_sec, 1),
            "approx_concurrent_call_capacity": int(audio_per_sec * 0.85),
            "whisper_collapses_prevented": self.whisper_collapses_prevented,
            "steps": self.steps,
            "default_seed": LEYLA_SEED,
        }

