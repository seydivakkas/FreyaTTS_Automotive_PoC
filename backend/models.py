import asyncio
import logging
import sys
import time
import threading
from collections import OrderedDict
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
import numpy as np
import httpx
from backend.config import settings
from backend.batched_ode import LEYLA_SEED
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
        self._last_llm_metrics = ContextVar("last_llm_metrics", default=None)
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

    @property
    def last_llm_metrics(self):
        return self._last_llm_metrics.get() or {}

    @last_llm_metrics.setter
    def last_llm_metrics(self, value):
        self._last_llm_metrics.set(value)

    def new_vad(self):
        """Create an independent CPU detector from the loaded Silero template."""
        if self.vad is None:
            raise RuntimeError("Modeller hazır değil")
        detector = deepcopy(self.vad)
        detector.reset_states()
        return detector

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
            await self._prewarm_tts()
            self.ollama_ready = True
            self.load_ms = (time.monotonic() - start) * 1000
            self.error = None
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            raise
        finally:
            self.loading = False

    @staticmethod
    def _cache_key(text, seed: int):
        try:
            prepared = prepare_tts_clause(text)
            return normalize(prepared)["normalized"], seed
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

        seeds = {LEYLA_SEED}
        pairs = [(t["text"], 9) for t in GREETING_TEMPLATES.values()]
        try:
            import json
            from backend.db import ABExperiment

            with Session() as db:
                for exp in db.scalars(
                    select(ABExperiment).where(ABExperiment.status == "active")
                ).all():
                    for v in json.loads(exp.variants_json or "[]"):
                        seed = int(v.get("tts_seed", LEYLA_SEED))
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
        from importlib.resources import files

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
            # Python opens Unicode Windows paths before handing the stream to Torch.
            with files("silero_vad.data").joinpath("silero_vad.jit").open("rb") as model:
                self.vad = torch.jit.load(model, map_location="cpu").eval()
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
        seed = LEYLA_SEED if seed is None else seed
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

    def _guarded_synth(self, text, seed: int):
        with self.worker_lock:
            breaker = self.breakers["tts"]
            if not breaker.allow(time.monotonic_ns()):
                raise RuntimeError("TTS geçici hata sonrasında beklemede")
            try:
                result = self._synth(text, seed=seed)
            except ValueError:
                breaker.abandon_probe()
                raise
            except Exception:
                breaker.failure(time.monotonic_ns())
                raise
            breaker.success()
            self.synth_count += 1
            return result

    def _synth(self, text, seed: int):
        t = normalize(text)["normalized"]
        parts = []
        for part, pause in clauses(t):
            missing = set(part) - set(self.tts.char_to_id)
            if missing:
                raise ValueError(f"Model sözlüğünde olmayan karakterler: {missing}")
            w = self.tts._synth_one(part, steps=32, seed=seed)
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
        if not len(audio):
            return ""
        if settings.stt_min_rms and np.sqrt(np.mean(audio**2)) < settings.stt_min_rms:
            return ""

        if not self.stt:
            raise RuntimeError("STT hazır değil")

        def run():
            catalog = list(self._catalog_hotwords()) if settings.stt_catalog_hotwords else []
            combined_hotwords = list(dict.fromkeys([*catalog, *(self.custom_hotwords or [])]))
            with self.stt_lock:
                segments, _ = self.stt.transcribe(
                    audio,
                    language="tr",
                    beam_size=1,
                    hotwords=", ".join(combined_hotwords) or None,
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

                return " ".join(accepted_texts)

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
