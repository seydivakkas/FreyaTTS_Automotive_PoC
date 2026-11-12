import asyncio
import logging
import sys
import time
import threading
from collections import OrderedDict
from pathlib import Path
import numpy as np
import httpx
from backend.config import settings
from backend.text import normalize, clauses, prepare_tts_clause
from backend.audio import apply_fade_and_comfort_noise
from automotive_voice.adapters.lifecycle.breaker import CircuitBreaker
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from backend.db import Session, Vehicle

logger = logging.getLogger("automotive_voice.models")

# Sabit cümle önbelleği sınırı ve hotword önbelleği ömrü.
SYNTH_CACHE_MAX = 32
HOTWORDS_TTL_SEC = 60.0
# Sabit sistem cümleleri (Dialogue/unclear metinleriyle aynı olmalı).
PREWARM_PHRASES = (
    "Aracınızın marka ve modelini söyler misiniz?",
    "Adınızı ve soyadınızı söyler misiniz?",
    "Sizi anlayamadım. Tekrar söyler misiniz?",
)


class Models:
    def __init__(self):
        self.tts = None
        self.stt = None
        self.vad = None
        self.lock = asyncio.Lock()
        self.worker_lock = threading.Lock()
        self.stt_lock = threading.Lock()
        self.error = None
        self.loading = False
        self.load_lock = asyncio.Lock()
        self.pending = 0
        self.load_ms = None
        self.synth_count = 0
        self.last_llm_metrics = {}
        self.ollama_ready = False
        self.custom_hotwords: list[str] = []
        # (normalize edilmiş cümle, kullanılan seed) -> dalga; yalnızca ön ısıtmada dolar.
        self._synth_cache: OrderedDict[tuple[str, int], np.ndarray] = OrderedDict()
        self._hotwords_cache: tuple[float, list[str]] | None = None
        self.batched_ode_engine = None
        self.breakers = {
            name: CircuitBreaker(threshold=3, cooldown_ns=10_000_000_000)
            for name in ("tts", "llm")
        }

    async def load(self):
        async with self.load_lock:
            return await self._load_once()

    async def _load_once(self):
        if (
            self.tts is not None
            and self.stt is not None
            and self.vad is not None
            and self.ollama_ready
        ):
            return
        if self.loading:
            return
        self.loading = True
        start = time.monotonic()
        try:
            await asyncio.to_thread(self._load)
            async for _ in self.chat(
                [
                    {"role": "system", "content": "Yalnızca JSON döndür."},
                    {"role": "user", "content": '{"ready":true} döndür.'},
                ]
            ):
                pass
            self.ollama_ready = True
            await self._prewarm_tts()
            self.load_ms = (time.monotonic() - start) * 1000
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            raise
        finally:
            self.loading = False

    @staticmethod
    def _cache_key(text, seed):
        try:
            prepared = prepare_tts_clause(text)
            return normalize(prepared)["normalized"], seed if seed is not None else 9
        except ValueError:
            return None

    def _cache_put(self, key, wave):
        self._synth_cache[key] = np.array(wave, copy=True)
        self._synth_cache.move_to_end(key)
        while len(self._synth_cache) > SYNTH_CACHE_MAX:
            self._synth_cache.popitem(last=False)

    def _prewarm_targets(self) -> list[tuple[str, int]]:
        """Ön ısıtılacak (cümle, seed) çiftleri: sabit karşılamalar + sabit istemler."""
        from backend.ab_testing import GREETING_TEMPLATES

        seeds = {9}
        pairs = [(t["text"], 9) for t in GREETING_TEMPLATES.values()]
        try:
            import json
            from backend.db import ABExperiment

            with Session() as db:
                for exp in db.scalars(
                    select(ABExperiment).where(ABExperiment.status == "active")
                ).all():
                    for v in json.loads(exp.variants_json or "[]"):
                        seed = int(v.get("tts_seed", 9))
                        seeds.add(seed)
                        tpl = GREETING_TEMPLATES.get(v.get("greeting_template", "standard"))
                        if tpl:
                            pairs.append((tpl["text"], seed))
        except Exception:
            logger.warning("A/B deney seed'leri okunamadı; yalnızca seed 9 ısıtılacak", exc_info=True)
        pairs += [(p, sd) for p in PREWARM_PHRASES for sd in sorted(seeds)]
        return pairs

    async def _prewarm_tts(self):
        """İlk sentez (ölçülen ~10.7 sn) ve sabit cümleler yükleme sırasında ısıtılır.

        Cümleler oturumdaki gibi yan tümce (clause) bazında sentezlenir. Hata yüklemeyi
        başarısız kılmaz; ilk hatada ısıtma bırakılır (devre kesiciyi zorlamamak için).
        """
        try:
            await self.synth("Merhaba.")  # yalnızca ısınma; önbelleğe girmez
            from backend.text import clauses

            seen = set()
            for text, seed in self._prewarm_targets():
                for raw_part, _ in clauses(normalize(text)["normalized"]):
                    part = prepare_tts_clause(raw_part)
                    key = self._cache_key(part, seed)
                    if key is None or key in seen:
                        continue
                    seen.add(key)
                    wave = await self.synth(part, seed=seed)  # önbellek boşken gerçek sentez
                    self._cache_put(key, wave)
        except Exception:
            logger.warning("TTS ön ısıtma başarısız; yükleme devam ediyor", exc_info=True)

    def invalidate_hotwords(self):
        """Araç kataloğu değişince STT ipucu önbelleğini düşürür."""
        self._hotwords_cache = None

    def _catalog_hotwords(self) -> list[str]:
        cached = self._hotwords_cache
        if cached and time.monotonic() - cached[0] < HOTWORDS_TTL_SEC:
            return cached[1]
        try:
            with Session() as db:
                names = list(
                    db.scalars(
                        select(Vehicle.description).order_by(Vehicle.id).limit(50)
                    ).all()
                )
        except SQLAlchemyError:
            return []  # hata önbelleğe alınmaz; sonraki çağrı yeniden dener
        self._hotwords_cache = (time.monotonic(), names)
        return names

    def _load(self):
        import torch

        if "cuda" in (settings.tts_device, settings.stt_device) and not torch.cuda.is_available():
            raise RuntimeError("CUDA kullanılamıyor")
        root = Path(settings.freya_path).resolve()
        if not (root / "freyatts").exists():
            raise RuntimeError("FreyaTTS kaynakları hazırlanmadı")
        sys.path.insert(0, str(root))
        from freyatts import FreyaTTS
        from faster_whisper import WhisperModel
        from silero_vad import load_silero_vad

        if self.tts is None:
            self.tts = FreyaTTS.from_pretrained(
                "freyavoice/freya-tts", device=settings.tts_device
            )
        if self.stt is None:
            self.stt = WhisperModel(
                settings.stt_model,
                device=settings.stt_device,
                compute_type=settings.stt_compute_type,
            )
        if self.vad is None:
            self.vad = load_silero_vad()
        if self.batched_ode_engine is None:
            from backend.batched_ode import BatchedODEEngine

            self.batched_ode_engine = BatchedODEEngine(
                tts_model=getattr(self.tts, "model", None),
                vae=getattr(self.tts, "vae", None),
                char_to_id=getattr(self.tts, "char_to_id", None),
                batch_size=settings.batched_ode_batch_size,
                micro_window_ms=settings.batched_ode_micro_window_ms,
                steps=settings.batched_ode_steps,
                device=settings.tts_device,
                enabled=settings.batched_ode_enabled,
                synth_fallback_fn=getattr(self.tts, "_synth_one", None),
            )
        self.error = None

    async def synth(self, text, seed: int | None = None):
        text = prepare_tts_clause(text)
        key = self._cache_key(text, seed)
        hit = self._synth_cache.get(key) if key is not None else None
        if hit is not None:
            return hit.copy()  # çağıran önbelleği değiştiremesin
        if self.batched_ode_engine and self.batched_ode_engine.enabled:
            # Yığınlı yol da aynı TTS devre kesicisinden geçer (_guarded_synth ile aynı kurallar).
            breaker = self.breakers["tts"]
            if not breaker.allow(time.monotonic_ns()):
                raise RuntimeError("TTS geçici hata sonrasında beklemede")
            try:
                result = await self.batched_ode_engine.synthesize_clause(text, seed=seed)
            except (ValueError, asyncio.CancelledError):
                breaker.abandon_probe()
                raise
            except Exception:
                breaker.failure(time.monotonic_ns())
                raise
            breaker.success()
            self.synth_count += 1
            return result
        if not self.tts:
            raise RuntimeError("TTS hazır değil; modelleri yükleyin")
        if self.pending >= 2:
            raise RuntimeError("Sentez kuyruğu dolu")
        self.pending += 1
        try:
            async with self.lock:
                work = asyncio.create_task(
                    asyncio.to_thread(self._guarded_synth, text, seed)
                )
                try:
                    return await asyncio.shield(work)
                except asyncio.CancelledError:
                    await asyncio.shield(work)
                    raise
        finally:
            self.pending -= 1

    def _guarded_synth(self, text, seed: int | None = None):
        with self.worker_lock:
            breaker = self.breakers["tts"]
            if not breaker.allow(time.monotonic_ns()):
                raise RuntimeError("TTS geçici hata sonrasında beklemede")
            try:
                try:
                    result = self._synth(text, seed=seed)
                except TypeError:
                    result = self._synth(text)
            except ValueError:
                breaker.abandon_probe()
                raise
            except Exception:
                breaker.failure(time.monotonic_ns())
                raise
            breaker.success()
            self.synth_count += 1
            return result

    def _synth(self, text, seed: int | None = None):
        t = normalize(text)["normalized"]
        parts = []
        used_seed = seed if seed is not None else 9
        for part, pause in clauses(t):
            missing = set(part) - set(self.tts.char_to_id)
            if missing:
                raise ValueError(f"Model sözlüğünde olmayan karakterler: {missing}")
            w = self.tts._synth_one(part, steps=32, seed=used_seed)
            if not np.isfinite(w).all() or np.max(np.abs(w), initial=0) < 1e-5:
                raise RuntimeError("Geçersiz veya sessiz model çıktısı")
            parts.extend(
                [
                    apply_fade_and_comfort_noise(w.astype(np.float32)),
                    np.zeros(int(pause * 48000), np.float32),
                ]
            )
        return np.concatenate(parts)

    async def transcribe(self, audio):
        # 1. Ses Enerjisi Ön Kontrolü: Ortam gürültüsü, nefes veya sessizlikte Whisper çağrılmaz
        if len(audio) < 1600:  # 100 ms'den kısa
            return ""
        rms = float(np.sqrt(np.mean(audio**2)))
        max_amp = float(np.max(np.abs(audio)))
        # RMS < -42 dBFS (~0.0075) veya tepe genlik < 0.025 ise doğrudan boş transkript dön
        if rms < 0.0075 or max_amp < 0.025:
            return ""

        if not self.stt:
            raise RuntimeError("STT hazır değil")

        def run():
            with self.stt_lock:
                # DİKKAT: hotwords parametresi faster-whisper'da doğrudan decoder prompt'una eklenir (prompt.extend).
                # Ortamda gürültü, araba uğultusu veya fısıltı varken Whisper Turbo decoder bu prompt'u
                # müşteri konuşmuş gibi halüsinasyon olarak döker ("Context, VTEC, Volkswagen Golf...").
                # Bu sebeple hotwords=None tutulur; Whisper Turbo'nun yerel Türkçe akustik modeline güvenilir.
                segments, _ = self.stt.transcribe(
                    audio,
                    language="tr",
                    beam_size=1,
                    hotwords=None,
                    condition_on_previous_text=False,
                    no_speech_threshold=0.50,
                    log_prob_threshold=-0.80,
                    compression_ratio_threshold=2.2,
                    repetition_penalty=1.2,
                    no_repeat_ngram_size=3,
                    hallucination_silence_threshold=2.0,
                )

                accepted_texts = []
                for s in segments:
                    if getattr(s, "no_speech_prob", 0.0) > 0.40:
                        continue
                    if getattr(s, "avg_logprob", 0.0) < -0.85:
                        continue
                    if getattr(s, "compression_ratio", 1.0) > 2.2:
                        continue
                    txt = s.text.strip()
                    if txt:
                        accepted_texts.append(txt)

                raw_result = " ".join(accepted_texts).strip()
                if not raw_result:
                    return ""

                # 2. Tipik Halüsinasyon ve İngilizce Kalıntı Taraması
                lowered = raw_result.lower()
                hallucination_tokens = (
                    "let's see", "lets see", "biddyo", "thank you for watching",
                    "subtitles by", "amara.org", "subscribe", "bye bye",
                    "watching", "mbc", "izlediğiniz için teşekkürler", "context,",
                    "thank you", "video", "see you", "all right,", "alright,",
                    "you for watching", "abone olmayı unutmayın"
                )
                for h in hallucination_tokens:
                    if h in lowered:
                        return ""

                # 3. Yalnızca İngilizce / non-tr kelimelerden oluşan kalıntı filtresi (örn: "IF, LET'S SEE")
                import re
                if re.search(r"\b(let's see|lets see|biddyo|context|subtitles)\b", lowered):
                    return ""

                # 4. Tekrarlı kelime döngüsü filtresi (örn: "IF, LET'S SEE, LET'S SEE...")
                words = raw_result.split()
                if len(words) >= 4:
                    from collections import Counter
                    counts = Counter([w.lower().strip(".,!?:") for w in words])
                    most_common_word, count = counts.most_common(1)[0]
                    if count >= 3 and count / len(words) > 0.35:
                        return ""

                # 5. İki veya daha fazla virgülle ayrılmış araç modelleri dökümü tespit edilirse:
                if raw_result.count(",") >= 2:
                    catalog_names = self._catalog_hotwords()
                    matches = sum(1 for n in catalog_names if n.lower() in lowered)
                    if matches >= 2:
                        return ""

                return raw_result

        work = asyncio.create_task(asyncio.to_thread(run))
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            await asyncio.shield(work)
            raise

    async def chat(self, messages, *, response_schema=None):
        breaker = self.breakers["llm"]
        if not breaker.allow(time.monotonic_ns()):
            raise RuntimeError("LLM geçici hata sonrasında beklemede")
        try:
            stream = self._chat(messages) if response_schema is None else self._chat(
                messages, response_schema=response_schema,
            )
            async for part in stream:
                yield part
        except asyncio.CancelledError:
            breaker.abandon_probe()
            raise
        except Exception:
            breaker.failure(time.monotonic_ns())
            raise
        else:
            breaker.success()

    async def _chat(self, messages, *, response_schema=None):
        import json

        start = time.monotonic()
        first = None
        async with httpx.AsyncClient(timeout=90, trust_env=response_schema is None) as client:
            async with client.stream(
                "POST",
                settings.ollama_url + "/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": messages,
                    "stream": True,
                    "keep_alive": -1,
                    "format": response_schema if response_schema is not None else "json",
                    "options": {
                        "temperature": 0,
                        "num_gpu": settings.ollama_gpu_layers,
                        "num_ctx": 4096,
                        "num_predict": 256,
                    },
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    obj = json.loads(line)
                    if obj.get("error"):
                        raise RuntimeError(obj["error"])
                    content = obj.get("message", {}).get("content", "")
                    if content and first is None:
                        first = (time.monotonic() - start) * 1000
                    yield content
        self.last_llm_metrics = {
            "llm_first_token_ms": first,
            "llm_total_ms": (time.monotonic() - start) * 1000,
        }


models = Models()
