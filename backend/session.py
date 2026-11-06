import asyncio
import json
import logging
import time
import wave
from pathlib import Path
import numpy as np
from sqlalchemy import select
from backend.audio import (
    Endpoint,
    resample,
    pcm,
    pace,
    apply_telephony_eq_and_downsample_8k,
)
from backend.models import models
from backend.db import Session, Conversation, Turn
from backend.dialogue import Dialogue
from backend.config import settings
from backend.milestones import LiveControl
from automotive_voice.audio.contracts import MediaFormat, Codec
from backend.batched_ode import ConcurrentCallController

logger = logging.getLogger("automotive_voice.session")

active = ConcurrentCallController(max_concurrent=settings.max_concurrent_calls)


def _metrics():
    """Panel toplayıcısını tembel yükler; metrik hatası çağrı akışını asla bozmaz."""
    try:
        from backend.realtime_dashboard_metrics import dashboard_metrics_collector
        return dashboard_metrics_collector
    except Exception:
        logger.debug("Metrik toplayıcı yüklenemedi", exc_info=True)
        return None


class VoiceSession:
    def __init__(
        self,
        channel,
        emit,
        send_audio,
        output_rate=16000,
        mode="inbound",
        appointment_id=None,
        call_id=None,
        diagnostic_id=None,
        caller_channel=None,
    ):
        if not models.vad:
            raise RuntimeError("Modeller hazır değil")
        self.emit = emit
        self.send_audio = send_audio
        self.output_rate = output_rate
        self.mode = mode
        self.appointment_id = appointment_id
        self.call_id = call_id
        self.diagnostic_id = diagnostic_id
        self.caller_channel = caller_channel
        self.media_format = MediaFormat(Codec.PCM_S16LE, output_rate)
        with Session() as db:
            c = Conversation(channel=channel)
            db.add(c)
            db.commit()
            self.id = c.id
            from backend.ab_testing import assign_conversation_variant
            variant_cfg = assign_conversation_variant(db, self.id)

        self.ab_experiment_id = variant_cfg.get("experiment_id")
        self.ab_variant_id = variant_cfg.get("variant_id")
        self.prompt_template = variant_cfg.get("prompt_template", "standard")
        self.tts_seed = variant_cfg.get("tts_seed", 9)
        self.greeting_template = variant_cfg.get("greeting_template", "standard")
        self.start_time = time.monotonic()
        self.first_audio_ms_val = None

        self.dialogue = Dialogue(
            self.id,
            mode=mode,
            appointment_id=appointment_id,
            call_id=call_id,
            diagnostic_id=diagnostic_id,
            prompt_template=self.prompt_template,
        )
        self.control = LiveControl(self.id)
        self.endpoint = Endpoint(models.vad)
        from backend.dtmf import GoertzelDetector
        self.goertzel_detector = GoertzelDetector(sample_rate=16000)
        from backend.car_denoiser import InboundCarDenoiser
        self.car_denoiser = InboundCarDenoiser(
            sample_rate=8000,
            hpf_cutoff_hz=settings.car_denoiser_hpf_cutoff,
            suppression_db=settings.car_denoiser_suppression_db,
            target_dbfs=settings.car_denoiser_target_dbfs,
            noise_gate_dbfs=settings.car_denoiser_noise_gate_dbfs,
            max_boost_db=settings.car_denoiser_max_boost_db,
            enabled=settings.car_denoiser_enabled,
        )
        from backend.audiosocket_server import LookbackBuffer, TwoStageBargeInController
        self.lookback_buffer = LookbackBuffer(capacity_frames=15, frame_bytes=320)
        self.bargein_controller = TwoStageBargeInController()
        models.vad.reset_states()
        self.generation = 0
        self.task = None
        self.playing = False
        self.generating = 0
        self.paused = False
        self.closed = False
        self.last_input = time.monotonic()
        self.recording = None
        self.input_buffer = b""
        self.resampler = None
        self.watchdog = None
        # DTMF görevleri: referans tutulur (GC'ye karşı), hataları loglanır, oturum başına sıralanır.
        self._dtmf_lock = asyncio.Lock()
        self._dtmf_tasks: set[asyncio.Task] = set()
        if settings.record_audio:
            recordings_dir = settings.data_dir / "recordings"
            recordings_dir.mkdir(parents=True, exist_ok=True)
            self.recording = wave.open(str(recordings_dir / f"{self.id}.wav"), "wb")
            self.recording.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        # Gerçek çağrı başlangıcı: yön, oturum modundan gelir (outbound aramalar mode="outbound").
        self._metrics_ended = False
        m = _metrics()
        if m is not None:
            m.record_call_start(direction="outbound" if mode == "outbound" else "inbound")

    def save(self, role, text, metrics=None):
        with Session() as db:
            db.add(
                Turn(
                    conversation_id=self.id,
                    role=role,
                    text=text,
                    metrics=json.dumps(metrics or {}),
                )
            )
            db.commit()

    async def start(self):
        await self.emit(
            {
                "type": "session",
                "id": self.id,
                "output_sample_rate": self.output_rate,
                "encoding": "pcm_s16le",
                "channels": 1,
            }
        )
        self.watchdog = asyncio.create_task(self.watch_silence())
        if self.mode == "outbound_reminder" and self.appointment_id:
            with Session() as db:
                from backend.db import Appointment, Slot, Vehicle
                from backend.notifications import format_appointment_datetime

                app = db.get(Appointment, self.appointment_id)
                veh = (
                    db.get(Vehicle, app.vehicle_id)
                    if (app and app.vehicle_id)
                    else None
                )
                slt = db.get(Slot, app.slot_id) if (app and app.slot_id) else None
                time_str = (
                    format_appointment_datetime(slt.starts_at) if slt else ""
                )
                veh_str = veh.description if veh else "aracınız"
                cust_str = app.customer if app else "Müşterimiz"
                greeting_text = (
                    f"İyi günler Sayın {cust_str}. Maslak Ekspertiz Merkezinden arıyorum. "
                    f"{veh_str} aracınız için {time_str} saatindeki ekspertiz randevunuzu teyit etmek amacıyla aradık. "
                    f"Randevunuza gelebilecek misiniz?"
                )
        elif self.mode == "outbound_diagnostic":
            with Session() as db:
                from backend.db import Appointment, Vehicle, VehicleDiagnostic

                diag = None
                if getattr(self, "diagnostic_id", None):
                    diag = db.get(VehicleDiagnostic, self.diagnostic_id)
                elif self.appointment_id:
                    # Başka müşterinin arıza kodu okunmasın: yalnızca randevunun aracına ait kayıt.
                    app = db.get(Appointment, self.appointment_id)
                    if app and app.vehicle_id:
                        diag = db.scalars(
                            select(VehicleDiagnostic)
                            .where(VehicleDiagnostic.vehicle_id == app.vehicle_id)
                            .order_by(VehicleDiagnostic.created_at.desc())
                        ).first()

                veh = (
                    db.get(Vehicle, diag.vehicle_id)
                    if (diag and diag.vehicle_id)
                    else None
                )
                cust_str = (
                    diag.owner_name
                    if (diag and diag.owner_name)
                    else "Müşterimiz"
                )
                veh_str = veh.description if veh else "aracınız"
                dtc_str = (
                    f"{diag.dtc_code} ({diag.description_tr})"
                    if diag
                    else "kritik motor arıza uyarısı"
                )
                greeting_text = (
                    f"İyi günler Sayın {cust_str}. Maslak Otomotiv Ekspertiz ve Servis Merkezinden arıyorum. "
                    f"OBD teşhis sistemimiz üzerinden {veh_str} aracınızda {dtc_str} algılandı. "
                    f"Sürüş güvenliğiniz için kontrol randevusu oluşturmak ister misiniz?"
                )
        else:
            from backend.ab_testing import get_greeting_text
            greeting_text = get_greeting_text(self.greeting_template)
        self.dialogue.record_turn("assistant", greeting_text)
        try:
            await self.reply(greeting_text)
        except Exception as e:
            await self.emit({"type": "error", "message": str(e)})

    async def watch_silence(self):
        while not self.closed:
            await asyncio.sleep(1)
            if (
                not self.playing
                and not self.generating
                and not self.endpoint.active
                and (not self.task or self.task.done())
                and time.monotonic() - self.last_input > 15
            ):
                self.last_input = time.monotonic()
                self.task = asyncio.create_task(self.process(np.zeros(0, np.float32)))

    async def input(self, data, rate):
        if self.closed:
            return
        if len(data) % 2:
            raise ValueError("Eksik PCM örneği")
        self.input_buffer += data
        size = rate // 10 * 2
        if len(self.input_buffer) < size:
            return
        count = len(self.input_buffer) // size * size
        raw, self.input_buffer = self.input_buffer[:count], self.input_buffer[count:]

        # 8 kHz Araç İçi Gürültü Bastırma (120 Hz HPF, -18 dB Spektral Denoise, Soft AGC)
        if hasattr(self, "car_denoiser") and self.car_denoiser is not None and self.car_denoiser.enabled:
            raw = self.car_denoiser.process_bytes(raw, sample_rate=rate)

        # 300 ms Lookback Tamponuna 8 kHz ham ses çerçevesini ekle (kelime başı koruması)
        if hasattr(self, "lookback_buffer") and self.lookback_buffer is not None:
            self.lookback_buffer.push(raw)

        import soxr

        if self.resampler is None:
            self.resampler = soxr.ResampleStream(
                rate, 16000, 1, dtype="float32", quality="HQ"
            )
        samples = self.resampler.resample_chunk(
            np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
        )
        # In-Band Goertzel DTMF tespiti ve tuş seslerini STT'den sessizleştirme (Audio Notch)
        feed_samples = samples
        if hasattr(self, "goertzel_detector") and self.goertzel_detector is not None:
            detected_digits, feed_samples = self.goertzel_detector.process_samples(samples)
            for d in detected_digits:
                self.schedule_dtmf(d)

        if self.recording:
            self.recording.writeframes(pcm(feed_samples))
        started, utterances = self.endpoint.feed(feed_samples)
        if started:
            signal_started = time.monotonic()
            self.last_input = time.monotonic()
            self.paused = True
            if hasattr(self, "bargein_controller") and self.bargein_controller is not None:
                self.bargein_controller.stage1_soft_pause()
            await self.emit(
                {"type": "playback", "action": "pause", "turn_id": self.generation}
            )
            if self.playing:
                self.save(
                    "metric",
                    "",
                    {"barge_in_signal_ms": (time.monotonic() - signal_started) * 1000},
                )
        for utterance in utterances:
            self.last_input = time.monotonic()
            if self.task and not self.task.done():
                self.task.cancel()
            self.task = asyncio.create_task(
                self.process(utterance, self.endpoint.last_voice_at)
            )

    async def process(self, audio, speech_end=None):
        start = time.monotonic()
        try:
            text = await models.transcribe(audio) if len(audio) else ""
            decision = (
                self.bargein_controller.stage2_evaluate(text)
                if hasattr(self, "bargein_controller") and self.bargein_controller is not None
                else ("rollback" if text.strip().lower().strip(".!") in {"", "evet", "hı hı", "anlıyorum"} else "commit")
            )
            if (
                self.playing
                and not self.dialogue.awaiting
                and decision == "rollback"
            ):
                self.paused = False
                await self.emit(
                    {"type": "playback", "action": "resume", "turn_id": self.generation}
                )
                return
            self.generation += 1
            self.paused = False
            await self.emit(
                {"type": "playback", "action": "flush", "turn_id": self.generation}
            )
            await self.control.move("thinking")
            stt_ms = (time.monotonic() - start) * 1000
            self.save(
                "user",
                text,
                {
                    "stt_ms": stt_ms,
                    "endpoint_ms": (start - speech_end) * 1000 if speech_end else None,
                },
            )
            await self.emit({"type": "transcript", "role": "user", "text": text})
            models.last_llm_metrics = {}
            answer = await self.dialogue.answer(text)
            self.save("metric", "", models.last_llm_metrics)
            # Arayüzün gecikme şeridi bu alanları bekler (tur başına tek metrics olayı).
            turn_metrics = {"stt_ms": stt_ms}
            for key in ("llm_first_token_ms", "llm_total_ms"):
                value = (models.last_llm_metrics or {}).get(key)
                if value is not None:
                    turn_metrics[key] = value
            await self.emit({"type": "metrics", **turn_metrics})
            await self.reply(answer, speech_end or start)
            if getattr(self.dialogue, "transfer_requested", False):
                ok = await self.trigger_operator_transfer()
                await self.emit(
                    {
                        "type": "completed",
                        "reason": "transferred" if ok else "follow_up",
                    }
                )
            elif self.dialogue.done:
                await self.emit(
                    {
                        "type": "completed",
                        "reason": "appointment"
                        if self.dialogue.confirmed
                        else "follow_up",
                    }
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.paused = False
            self.playing = False
            self.generation += 1
            await self.control.move("listening")
            await self.emit(
                {"type": "playback", "action": "flush", "turn_id": self.generation}
            )
            await self.emit({"type": "error", "message": str(e)})

    def schedule_dtmf(self, digit: str) -> asyncio.Task:
        """DTMF işlemini arka planda başlatır; referansı tutar ve hatayı loglar."""
        task = asyncio.create_task(self.handle_dtmf(digit))
        self._dtmf_tasks.add(task)

        def done(t: asyncio.Task):
            self._dtmf_tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                logger.error("DTMF işlenemedi", exc_info=t.exception())

        task.add_done_callback(done)
        return task

    async def handle_dtmf(self, digit: str):
        # Aynı oturumda tuşlar sırayla işlenir (üst üste binen yanıtları önler).
        async with self._dtmf_lock:
            await self._handle_dtmf_locked(digit)

    async def _handle_dtmf_locked(self, digit: str):
        if self.closed:
            return
        d = str(digit).strip().upper()
        if not d:
            return

        # Anında Barge-in: Mevcut ses çalmasını veya sentezi derhal sustur
        if self.playing or self.generating > 0:
            self.generation += 1
            self.playing = False
            self.paused = False
            await self.control.move("thinking")
            await self.emit(
                {"type": "playback", "action": "flush", "turn_id": self.generation}
            )

        # Devam eden STT/LLM görevini iptal et (Sıfır LLM Gecikmesi)
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

        self.save("user", f"[DTMF: {d}]", {"input_type": "dtmf", "digit": d})
        await self.emit({"type": "transcript", "role": "user", "text": f"[DTMF: {d}]"})
        await self.emit({"type": "dtmf_received", "digit": d})

        with Session() as db:
            reply_text = await self.dialogue.handle_dtmf(d, db)

        await self.reply(reply_text)
        if getattr(self.dialogue, "transfer_requested", False):
            ok = await self.trigger_operator_transfer()
            await self.emit(
                {
                    "type": "completed",
                    "reason": "transferred" if ok else "follow_up",
                }
            )
        elif self.dialogue.done:
            await self.emit(
                {
                    "type": "completed",
                    "reason": "appointment"
                    if self.dialogue.confirmed
                    else "follow_up",
                }
            )

    async def trigger_operator_transfer(self):
        from backend.transfer import initiate_operator_transfer
        plate = ""
        summary = ""
        channel_name = self.caller_channel or f"PJSIP/caller-{self.id[:8]}"
        with Session() as db:
            if self.dialogue.vehicle:
                from backend.db import Vehicle
                v = db.get(Vehicle, self.dialogue.vehicle)
                if v:
                    plate = v.plate or ""
            summary = self.dialogue.get_transfer_summary(db)
            transfer = await initiate_operator_transfer(
                db,
                conversation_id=self.id,
                caller_channel=channel_name,
                customer_name=self.dialogue.customer or "",
                vehicle_plate=plate,
                summary=summary,
            )
            self.dialogue.transfer_id = transfer.id

        if transfer.status == "failed":
            # AMI aktarımı başlatamadı: müşteriye "aktarıyorum" demiş olsak da gerçeği söyle.
            await self.reply(
                "Operatöre bağlanamadım; talebinizi kaydettim, sizi arayacağız."
            )
        await self.emit(
            {
                "type": "operator_transfer",
                "transfer_id": transfer.id,
                "status": transfer.status,
                "operator_extension": transfer.operator_extension,
                "whisper_text": transfer.whisper_text,
                "customer_name": transfer.customer_name,
                "vehicle_plate": transfer.vehicle_plate,
                "summary": transfer.summary,
            }
        )
        return transfer.status != "failed"

    async def reply(self, text, start=None):
        turn = self.generation
        control_generation = int((await self.control.move("speaking")).generation_id)
        start = start or time.monotonic()
        self.save("assistant", text)
        await self.emit({"type": "transcript", "role": "assistant", "text": text})
        await self.emit({"type": "status", "value": "synthesizing"})
        # Synthesize clause by clause; stale GPU jobs may finish but cannot play.
        from backend.text import normalize, clauses

        queue = asyncio.Queue(maxsize=2)

        async def produce():
            try:
                for part, pause in clauses(normalize(text)["normalized"]):
                    if self.closed or turn != self.generation:
                        break
                    began = time.monotonic()
                    cold = models.synth_count == 0
                    try:
                        w = await models.synth(part, seed=self.tts_seed)
                    except TypeError:
                        w = await models.synth(part)
                    if self.closed or turn != self.generation:
                        break
                    elapsed = time.monotonic() - began
                    # Cümle (clause) başına bir kez: kare başına yük yok
                    m = _metrics()
                    if m is not None and len(w) > 0:
                        m.record_tts_inference(len(w) / 48000, elapsed)
                    await queue.put(
                        (
                            w,
                            {
                                "tts_ms": elapsed * 1000,
                                "rtf": elapsed / (len(w) / 48000),
                                "cold_synthesis": cold,
                            },
                        )
                    )
                await queue.put(None)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await queue.put(e)

        self.generating += 1
        producer = asyncio.create_task(produce())
        first = True
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                if self.closed or turn != self.generation:
                    return
                w, metrics = item
                if first:
                    ms_val = (time.monotonic() - start) * 1000
                    metrics["first_audio_ms"] = ms_val
                    if self.first_audio_ms_val is None:
                        self.first_audio_ms_val = ms_val
                first = False
                self.save("metric", "", metrics)
                await self.emit({"type": "metrics", **metrics})
                if await self.control.accepts(control_generation):
                    await self.play_wave(w, turn)
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
            self.generating -= 1
        if self.closed or turn != self.generation:
            return
        self.playing = False
        await self.control.move("listening")
        self.last_input = time.monotonic()
        await self.emit({"type": "status", "value": "listening"})

    async def play_wave(self, w, turn):
        data = (
            apply_telephony_eq_and_downsample_8k(w).tobytes()
            if self.output_rate == 8000
            else pcm(resample(w, 48000, self.output_rate))
        )
        self.playing = True
        await self.emit({"type": "status", "value": "speaking", "turn_id": turn})

        async def send(frame):
            if len(frame) != self.media_format.expected_bytes(self.output_rate // 50):
                raise ValueError("20 ms ses çerçevesi sözleşmeye uymuyor")
            while self.paused and not self.closed and turn == self.generation:
                await asyncio.sleep(0.02)
            if not self.closed and turn == self.generation:
                await self.send_audio(frame)

        if self.output_rate == 8000:
            await pace(data, send, lambda: self.closed or turn != self.generation)
        else:
            from backend.audio import frames

            deadline = time.monotonic()
            for frame in frames(data, 640):
                if self.closed or turn != self.generation:
                    return
                await send(frame)
                deadline += 0.02
                if deadline < time.monotonic():
                    deadline = time.monotonic() + 0.02
                await asyncio.sleep(max(0, deadline - time.monotonic()))

    async def close(self):
        self.closed = True
        self.generation += 1
        for t in list(self._dtmf_tasks):
            t.cancel()
        if self._dtmf_tasks:
            await asyncio.gather(*self._dtmf_tasks, return_exceptions=True)
        if self.watchdog:
            self.watchdog.cancel()
            await asyncio.gather(self.watchdog, return_exceptions=True)
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.recording:
            self.recording.close()
        await self.control.close()
        if not getattr(self, "_metrics_ended", True):
            self._metrics_ended = True
            m = _metrics()
            if m is not None:
                m.record_call_end(
                    success=True,
                    duration_sec=time.monotonic() - getattr(self, "start_time", time.monotonic()),
                )
        with Session() as db:
            c = db.get(Conversation, self.id)
            if c:
                c.status = "completed" if self.dialogue.confirmed else "follow_up"
                db.commit()
            try:
                from backend.ab_testing import record_assignment_metrics
                duration = time.monotonic() - getattr(self, "start_time", time.monotonic())
                turns_cnt = len(getattr(self.dialogue, "history", []))
                record_assignment_metrics(
                    db,
                    self.id,
                    confirmed=self.dialogue.confirmed,
                    duration_seconds=round(duration, 2),
                    turns_count=turns_cnt,
                    first_audio_ms=getattr(self, "first_audio_ms_val", None),
                )
                if hasattr(self, "car_denoiser") and self.car_denoiser is not None:
                    self.save("dsp_metric", "", self.car_denoiser.get_summary_stats())
                if hasattr(self, "bargein_controller") and self.bargein_controller is not None:
                    self.save("bargein_metric", "", self.bargein_controller.get_stats())
            except Exception:
                pass
