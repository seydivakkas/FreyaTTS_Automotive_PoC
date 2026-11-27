import asyncio
import json
import logging
import time
import wave
import numpy as np
from sqlalchemy import case, func, select, update
from backend.audio import (
    Endpoint,
    resample,
    pcm,
    pace,
    apply_telephony_eq_and_downsample_8k,
)
from backend.models import models
from backend.db import Session, Conversation, FqiciScope, Turn, now
from backend.dialogue import Dialogue
from backend.config import settings
from backend.milestones import LiveControl
from automotive_voice.audio.contracts import MediaFormat, Codec
from backend.batched_ode import ConcurrentCallController, LEYLA_SEED
from backend.pipeline_telemetry import make_pipeline_event

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
        customer_phone="",
        synthetic_audiosocket_id=None,
    ):
        detector = models.new_vad()
        self.emit = emit
        self.send_audio = send_audio
        self.output_rate = output_rate
        self.mode = mode
        self.appointment_id = appointment_id
        self.call_id = call_id
        self.diagnostic_id = diagnostic_id
        self.caller_channel = caller_channel
        self.customer_phone = (customer_phone or "").strip()
        self.media_format = MediaFormat(Codec.PCM_S16LE, output_rate)
        self.fqici_enrolled = settings.fqici_enabled and (
            channel == "web" or (channel == "asterisk" and synthetic_audiosocket_id is not None)
        )
        self.fqici_close_reason = "normal"
        with Session() as db:
            c = Conversation(channel=channel)
            db.add(c)
            if self.fqici_enrolled:
                db.flush()
                db.add(FqiciScope(
                    id=c.id, transport="WEB" if channel == "web" else "AUDIOSOCKET",
                    origin=("DEMO" if settings.demo_mode else "UNKNOWN") if channel == "web" else "SYNTHETIC",
                    transport_id=synthetic_audiosocket_id,
                ))
            db.commit()
            self.id = c.id
            from backend.ab_testing import assign_conversation_variant
            variant_cfg = assign_conversation_variant(db, self.id)

        self.ab_experiment_id = variant_cfg.get("experiment_id")
        self.ab_variant_id = variant_cfg.get("variant_id")
        self.prompt_template = variant_cfg.get("prompt_template", "standard")
        self.tts_seed = variant_cfg.get("tts_seed", LEYLA_SEED)
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
            customer_phone=self.customer_phone,
        )
        self.control = LiveControl(self.id)
        self.supervisor = None
        if channel == "web" and mode == "inbound" and settings.supervisor_mode != "off":
            from backend.supervisor.runtime import WebSupervisor

            self.supervisor = WebSupervisor(self.id, settings.supervisor_mode)
        self.live_captions = channel == "web"
        self.caption_task = None
        self.caption_blocks = 0
        self.caption_epoch = 0
        self.endpoint = Endpoint(detector)
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
            gate_attenuation_db=settings.car_denoiser_gate_attenuation_db,
        )
        self.is_calibrating = False
        self._calibration_event = asyncio.Event()
        from backend.audiosocket_server import LookbackBuffer, TwoStageBargeInController
        self.lookback_buffer = LookbackBuffer(capacity_frames=15, frame_bytes=320)
        self.bargein_controller = TwoStageBargeInController()
        self.generation = 0
        self.task = None
        self._pending_utterances: list[tuple[np.ndarray, float | None]] | None = None
        self.playing = False
        self.generating = 0
        self.paused = False
        self.closed = False
        self.last_input = time.monotonic()
        self.recording = None
        self.input_buffer = b""
        self.resampler = None
        self.watchdog = None
        self.last_f0_ms: float | None = None
        self.last_f1_ms: float | None = None
        self.last_eos_to_first_audio_ms: float | None = None
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

    def _build_dialogue_state_payload(self) -> dict:
        """Görüşme durum makinesinden 5-soru kartı ve kabul protokolü için tek kaynaklı özet üretir."""
        diag = self.dialogue
        vehicle_id = None
        vehicle_desc = None
        price_label = None
        slot_id = getattr(diag, "slot", None)
        slot_time_label = None

        raw_veh = getattr(diag, "vehicle", None)
        if raw_veh:
            if isinstance(raw_veh, str):
                vehicle_id = raw_veh
                try:
                    from backend.db import Quote, Vehicle

                    with Session() as db:
                        veh_obj = db.get(Vehicle, raw_veh)
                        vehicle_desc = veh_obj.description if veh_obj else raw_veh
                        q_obj = db.scalars(select(Quote).where(Quote.vehicle_id == raw_veh)).first()
                        if q_obj and q_obj.amount_kurus:
                            price_label = f"{q_obj.amount_kurus // 100:,}".replace(",", ".") + " TL"
                except Exception:
                    vehicle_desc = raw_veh
            else:
                vehicle_id = getattr(raw_veh, "id", None)
                vehicle_desc = getattr(raw_veh, "description", str(raw_veh))

        opts = getattr(diag, "options", None) or []
        if slot_id and opts:
            for opt_id, opt_label in opts:
                if opt_id == slot_id:
                    slot_time_label = str(opt_label)
                    break

        if getattr(diag, "transfer_requested", False):
            ui_state = "operator_transfer"
        elif getattr(diag, "confirmed", False) or (getattr(diag, "done", False) and getattr(diag, "appointment_id", None)):
            ui_state = "booked"
        elif getattr(diag, "awaiting", False):
            ui_state = "confirmation"
        elif slot_id or opts:
            ui_state = "slot_selection"
        elif vehicle_id or vehicle_desc:
            ui_state = "car_type"
        else:
            ui_state = "greeting"

        b_status = getattr(diag, "booking_status", None)
        return {
            "state": ui_state,
            "booking_status": getattr(b_status, "value", str(b_status or "idle")),
            "plate": getattr(diag, "plate", None) or getattr(diag, "plate_draft", None),
            "plate_confirmed": bool(getattr(diag, "plate_confirmed", False)),
            "customer": getattr(diag, "customer", None),
            "vehicle": vehicle_desc,
            "vehicle_id": vehicle_id,
            "slot_id": slot_id,
            "slot_time": slot_time_label,
            "price": price_label,
            "appointment_id": getattr(diag, "appointment_id", None),
            "reference_code": getattr(diag, "reference_code", None),
            "transfer_requested": bool(getattr(diag, "transfer_requested", False)),
            "inbound_intent": getattr(diag, "inbound_intent", None),
            "canonical": getattr(diag, "last_asr_canonical", None),
            "trace": getattr(diag, "last_turn_trace", None),
            "eos_to_first_audio_ms": self.last_eos_to_first_audio_ms,
        }

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
                self._pending_utterances = None
                self.task = asyncio.create_task(self.process(np.zeros(0, np.float32)))

    async def recalibrate(self, duration_sec: float = 1.5):
        """Kullanıcının isteğiyle ortam gürültü kalkanını yeniden kalibre eder."""
        denoiser = getattr(self, "car_denoiser", None)
        if self.closed or self.is_calibrating or denoiser is None or not denoiser.enabled:
            return
        self.is_calibrating = True
        self._calibration_event.clear()
        denoiser.start_calibration(duration_sec=duration_sec)
        await self.emit(
            {
                "type": "calibration_start",
                "duration_sec": duration_sec,
                "message": "Ortam gürültüsü yeniden kalibre ediliyor... Lütfen 1-2 saniye sessiz kalın.",
            }
        )
        try:
            await asyncio.wait_for(self._calibration_event.wait(), timeout=duration_sec + 1.0)
        except asyncio.TimeoutError:
            if self.is_calibrating:
                info = denoiser.finish_calibration()
                self.is_calibrating = False
                await self.emit({"type": "calibration_done", **info})

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

        calibration_pcm = raw if self.is_calibrating else None
        f0_start = time.monotonic()
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
        detected_digits = ()
        if hasattr(self, "goertzel_detector") and self.goertzel_detector is not None:
            detected_digits, feed_samples = self.goertzel_detector.process_samples(samples)
            for d in detected_digits:
                self.schedule_dtmf(d)

        f0_ms = (time.monotonic() - f0_start) * 1000
        self.last_f0_ms = f0_ms

        if self.recording:
            self.recording.writeframes(pcm(feed_samples))

        f1_start = time.monotonic()
        was_speaking = self.endpoint.active if calibration_pcm is not None else False
        started, utterances = self.endpoint.feed(feed_samples)
        f1_ms = (time.monotonic() - f1_start) * 1000
        self.last_f1_ms = f1_ms

        # Only use batches the endpoint observed as quiet. Playback can leak into the mic.
        if (
            calibration_pcm is not None
            and len(feed_samples)
            and not (was_speaking or started or utterances or self.endpoint.active)
            and not (self.playing or detected_digits)
            and self.car_denoiser.feed_calibration_bytes(calibration_pcm, sample_rate=rate)
        ):
            info = self.car_denoiser.finish_calibration()
            self.is_calibrating = False
            self._calibration_event.set()
            await self.emit({"type": "calibration_done", **info})

        if self.live_captions:
            await self.update_live_caption(bool(utterances))
        if started:
            signal_started = time.monotonic()
            self.last_input = time.monotonic()
            self.paused = True
            if hasattr(self, "bargein_controller") and self.bargein_controller is not None:
                self.bargein_controller.stage1_soft_pause()
            await self.emit(
                {"type": "playback", "action": "pause", "turn_id": self.generation}
            )
            rms = float(np.sqrt(np.mean(feed_samples**2))) if len(feed_samples) else 0.0
            dbfs = float(20 * np.log10(max(rms, 1e-5)))
            await self.emit({
                "type": "pipeline_event",
                "event": make_pipeline_event(
                    self.id, self.generation + 1, "F0", "completed",
                    duration_ms=round(f0_ms, 2),
                    metrics={
                        "input_rate": rate,
                        "resampled_rate": 16000,
                        "rms": round(rms, 4),
                        "dbfs": round(dbfs, 1),
                        "denoiser_active": bool(getattr(self, "car_denoiser", None) and self.car_denoiser.enabled),
                    },
                    source="live",
                ),
            })
            await self.emit({
                "type": "pipeline_event",
                "event": make_pipeline_event(
                    self.id, self.generation + 1, "F1", "completed",
                    duration_ms=round(f1_ms, 2),
                    metrics={"speech_detected": True, "barge_in": self.playing},
                    source="live",
                ),
            })
            if self.playing:
                self.save(
                    "metric",
                    "",
                    {"barge_in_signal_ms": (time.monotonic() - signal_started) * 1000},
                )
        for utterance in utterances:
            self.last_input = time.monotonic()
            speech_end = self.endpoint.last_voice_at
            if self.task and not self.task.done():
                if self._pending_utterances is not None and not self.task.cancelling():
                    self._pending_utterances.append((utterance, speech_end))
                    continue
                self.task.cancel()
            self._pending_utterances = [(utterance, speech_end)]
            self.task = asyncio.create_task(self.process(utterance, speech_end))

    async def update_live_caption(self, ended):
        if ended:
            self.caption_epoch += 1
            self.caption_blocks = 0
            await self.emit({"type": "partial_transcript", "text": ""})
        blocks = len(self.endpoint.speech)
        if not self.endpoint.active or blocks - self.caption_blocks < 32:
            return
        if self.caption_task and not self.caption_task.done():
            return
        self.caption_blocks = blocks
        audio = np.concatenate(self.endpoint.speech)
        epoch = self.caption_epoch

        async def preview():
            try:
                text = await models.transcribe(audio)
                if text and not self.closed and epoch == self.caption_epoch:
                    await self.emit({"type": "partial_transcript", "text": text.strip()})
            except Exception:
                logger.warning("Ara konuşma metni alınamadı", exc_info=True)

        self.caption_task = asyncio.create_task(preview())

    async def process(self, audio, speech_end=None):
        start = time.monotonic()
        stt_start = time.perf_counter()
        pending = self._pending_utterances if asyncio.current_task() is self.task else None
        try:
            current_turn = self.generation + 1
            await self.emit({
                "type": "pipeline_event",
                "event": make_pipeline_event(self.id, current_turn, "F2", "running", source="live"),
            })
            while True:
                segment_count = len(pending) if pending is not None else 0
                if pending:
                    audio, speech_end = pending[-1]
                    if segment_count > 1:
                        audio = np.concatenate([segment for segment, _ in pending])
                decode_start = time.monotonic()
                text = (await models.transcribe(audio)).strip() if len(audio) else ""
                if pending is None or len(pending) == segment_count:
                    break
            stt_ms = (time.perf_counter() - stt_start) * 1000
            # Finalize before publishing the transcript and starting the dialogue.
            if pending is not None and self._pending_utterances is pending:
                self._pending_utterances = None

            await self.emit({
                "type": "pipeline_event",
                "event": make_pipeline_event(
                    self.id, current_turn, "F2", "completed",
                    duration_ms=stt_ms,
                    metrics={
                        "char_count": len(text),
                        "word_count": len(text.split()),
                        "stt_unrecognized": not text,
                    },
                    intermediate_data={"raw_transcript": text},
                    source="live",
                ),
            })

            if not text:
                self.save("metric", "", {"stt_unrecognized": 1})

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
            if text:
                self.save(
                    "user",
                    text,
                    {
                        "stt_ms": stt_ms,
                        "endpoint_ms": (decode_start - speech_end) * 1000 if speech_end else None,
                    },
                )
                await self.emit({"type": "transcript", "role": "user", "text": text})
            models.last_llm_metrics = {}

            # F3: Supervisor Intent & LLM Çıkarımı
            f3_start = time.perf_counter()
            await self.emit({
                "type": "pipeline_event",
                "event": make_pipeline_event(self.id, self.generation, "F3", "running", source="live"),
            })
            answer = None
            if self.supervisor is not None and text:
                try:
                    answer = await self.supervisor.process_final(text)
                except Exception:
                    logger.warning("Supervisor routing failed")
                    if self.supervisor.mode == "guarded":
                        answer = "Talebinizi güvenle doğrulayamıyorum. Lütfen tekrar söyler misiniz?"
            if answer is None:
                answer = await self.dialogue.answer(text)
            f3_ms = (time.perf_counter() - f3_start) * 1000
            llm_metrics = models.last_llm_metrics or {}
            if llm_metrics:
                self.save("metric", "", llm_metrics)
            # Arayüzün gecikme şeridi bu alanları bekler (tur başına tek metrics olayı).
            turn_metrics = {"stt_ms": round(stt_ms, 1)}
            for key in ("llm_first_token_ms", "llm_total_ms"):
                value = llm_metrics.get(key)
                if value is not None:
                    turn_metrics[key] = round(float(value), 1)
            await self.emit({"type": "metrics", **turn_metrics})
            await self.emit({
                "type": "pipeline_event",
                "event": make_pipeline_event(
                    self.id, self.generation, "F3", "completed",
                    duration_ms=f3_ms, metrics=turn_metrics,
                    intermediate_data={"answer": answer},
                    source="live",
                ),
            })
            await self.reply(answer, speech_end or start)

            # Diyalog durumunu ve çıkarılan parametreleri tek yardımcıyla yayınla + kalıcı iz kaydet
            dialogue_info = self._build_dialogue_state_payload()
            self.save(
                "metric",
                "",
                {
                    "dialogue_state": dialogue_info,
                    "eos_to_first_audio_ms": self.last_eos_to_first_audio_ms,
                    "last_turn_trace": dialogue_info.get("trace"),
                },
            )
            await self.emit({"type": "dialogue_state", "data": dialogue_info})

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
        finally:
            if pending is not None and self._pending_utterances is pending:
                self._pending_utterances = None

    async def handle_text_input(self, text: str):
        """Web arayüzünden doğrudan metin şeklinde gelen kullanıcı mesajını işler."""
        if not text or self.closed:
            return
        clean_text = text.strip()
        if not clean_text:
            return

        # 1. Devam eden ses çalımı veya sentezi varsa derhal sustur (Barge-in)
        if self.playing or self.generating > 0:
            self.playing = False
            self.paused = False
            await self.control.move("thinking")
            await self.emit(
                {"type": "playback", "action": "flush", "turn_id": self.generation}
            )

        # 2. Arka planda çalışan STT/işlem görevi varsa iptal et
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

        self.last_input = time.monotonic()
        self.generation += 1

        # 3. DB'ye Turn kaydet ve kullanıcı transkripti yay (dialogue.answer kendi içinde record_turn yapar)
        self.save("user", clean_text, {"input_type": "text", "source": "text_input"})
        await self.emit({"type": "transcript", "role": "user", "text": clean_text})

        # 4. F0, F1, F2: Ses aşamalarını "bypassed" olarak telemetriye ilet
        for stage in ("F0", "F1", "F2"):
            await self.emit({
                "type": "pipeline_event",
                "event": make_pipeline_event(
                    self.id,
                    self.generation,
                    stage,
                    "bypassed",
                    source="text_input",
                    duration_ms=0.0,
                    metrics={"input_mode": "text"},
                    intermediate_data={"reason": "direct_text_input"},
                ),
            })

        # 5. F3: Niyet & LLM Çıkarımı
        f3_start = time.monotonic()
        await self.emit({
            "type": "pipeline_event",
            "event": make_pipeline_event(self.id, self.generation, "F3", "running", source="text_input"),
        })

        try:
            answer = None
            if self.supervisor is not None:
                try:
                    answer = await self.supervisor.process_final(clean_text)
                except Exception:
                    logger.warning("Supervisor routing failed in text input", exc_info=True)
                    if getattr(self.supervisor, "mode", "") == "guarded":
                        answer = "Talebinizi güvenle doğrulayamıyorum. Lütfen tekrar iletir misiniz?"
            if answer is None:
                answer = await self.dialogue.answer(clean_text)

            f3_ms = (time.monotonic() - f3_start) * 1000
            llm_metrics = models.last_llm_metrics or {}
            turn_metrics = {"stt_ms": 0}
            for key in ("llm_first_token_ms", "llm_total_ms"):
                value = llm_metrics.get(key)
                if value is not None:
                    turn_metrics[key] = round(float(value), 1)
            await self.emit({"type": "metrics", **turn_metrics})
            await self.emit({
                "type": "pipeline_event",
                "event": make_pipeline_event(
                    self.id,
                    self.generation,
                    "F3",
                    "completed",
                    duration_ms=f3_ms,
                    metrics=turn_metrics,
                    intermediate_data={"answer": answer},
                    source="text_input",
                ),
            })

            await self.reply(answer, source="text_input")

            # Diyalog durumunu ve çıkarılan parametreleri tek yardımcıyla yayınla + kalıcı iz kaydet
            dialogue_info = self._build_dialogue_state_payload()
            self.save(
                "metric",
                "",
                {
                    "dialogue_state": dialogue_info,
                    "eos_to_first_audio_ms": self.last_eos_to_first_audio_ms,
                    "last_turn_trace": dialogue_info.get("trace"),
                },
            )
            await self.emit({"type": "dialogue_state", "data": dialogue_info})

            # 6. Tamamlanma veya operatöre aktarım kontrolleri
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
                        if getattr(self.dialogue, "confirmed", False)
                        else "follow_up",
                    }
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Metin girdisi işleme hatası", exc_info=True)
            self.paused = False
            self.playing = False
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
            self.dialogue.record_callback_request(reason="aktarım başlatılamadı")
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

    async def reply(self, text, start=None, source="live"):
        turn = self.generation
        control_generation = int((await self.control.move("speaking")).generation_id)
        has_voice_eos = source == "live" and start is not None
        start = start or time.monotonic()
        self.save("assistant", text)
        await self.emit({"type": "transcript", "role": "assistant", "text": text})
        await self.emit({"type": "status", "value": "synthesizing"})
        # Synthesize clause by clause; stale GPU jobs may finish but cannot play.
        from backend.text import normalize, clauses, prepare_tts_clause

        # F4: Normalizasyon ve Cümlecik Bölme
        f4_start = time.monotonic()
        await self.emit({
            "type": "pipeline_event",
            "event": make_pipeline_event(self.id, turn, "F4", "running", source=source),
        })
        norm_result = normalize(text)["normalized"]
        clause_list = list(clauses(norm_result))
        f4_ms = (time.monotonic() - f4_start) * 1000
        await self.emit({
            "type": "pipeline_event",
            "event": make_pipeline_event(
                self.id, turn, "F4", "completed", duration_ms=f4_ms,
                metrics={"chunks_count": len(clause_list)},
                intermediate_data={"normalized_text": norm_result},
                source=source,
            ),
        })

        # F5: FreyaTTS Sentezi Başlangıcı
        f5_start = time.monotonic()
        await self.emit({
            "type": "pipeline_event",
            "event": make_pipeline_event(self.id, turn, "F5", "running", source=source),
        })

        queue = asyncio.Queue(maxsize=2)

        async def produce():
            try:
                for raw_part, pause in clause_list:
                    part = prepare_tts_clause(raw_part)
                    if self.closed or turn != self.generation:
                        break
                    began = time.monotonic()
                    cold = models.synth_count == 0
                    w = await models.synth(part, seed=self.tts_seed)
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
                    ms_val = round((time.monotonic() - start) * 1000, 1)
                    f5_ms = round((time.monotonic() - f5_start) * 1000, 1)
                    metrics["first_audio_ms"] = ms_val
                    if has_voice_eos:
                        metrics["eos_to_first_audio_ms"] = ms_val
                        self.last_eos_to_first_audio_ms = ms_val
                    else:
                        self.last_eos_to_first_audio_ms = None
                    if self.first_audio_ms_val is None:
                        self.first_audio_ms_val = ms_val
                    await self.emit({
                        "type": "pipeline_event",
                        "event": make_pipeline_event(
                            self.id, turn, "F5", "completed", duration_ms=f5_ms,
                            metrics={
                                "ttfa_ms": ms_val,
                                "eos_to_first_audio_ms": ms_val if has_voice_eos else None,
                                "cold_synthesis": metrics.get("cold_synthesis"),
                                "voice_seed": self.tts_seed,
                                "persona": "Leyla",
                            },
                            source=source,
                        ),
                    })
                first = False
                self.save("metric", "", metrics)
                await self.emit({"type": "metrics", **metrics})
                if await self.control.accepts(control_generation):
                    try:
                        await self.play_wave(w, turn, source=source)
                    except TypeError:
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

    async def play_wave(self, w, turn, source="live"):
        data = (
            apply_telephony_eq_and_downsample_8k(w).tobytes()
            if self.output_rate == 8000
            else pcm(resample(w, 48000, self.output_rate))
        )
        self.playing = True
        await self.emit({"type": "status", "value": "speaking", "turn_id": turn})

        f6_start = time.monotonic()
        await self.emit({
            "type": "pipeline_event",
            "event": make_pipeline_event(self.id, turn, "F6", "running", source=source),
        })

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

        f6_ms = (time.monotonic() - f6_start) * 1000
        await self.emit({
            "type": "pipeline_event",
            "event": make_pipeline_event(
                self.id,
                turn,
                "F6",
                "completed",
                duration_ms=round(f6_ms, 1),
                metrics={"audio_bytes": len(data), "sample_rate": self.output_rate, "playback_ms": round(f6_ms, 1)},
                source=source,
            ),
        })
        await self.emit({
            "type": "metrics",
            "playback_ms": round(f6_ms, 1),
        })

    async def close(self):
        self.closed = True
        if self.caption_task:
            self.caption_task.cancel()
            await asyncio.gather(self.caption_task, return_exceptions=True)
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
        if self.fqici_enrolled:
            await self.control.close(closure_reason=self.fqici_close_reason)
        else:
            await self.control.close()
        if self.supervisor is not None:
            from backend.supervisor.quality import finalize_conversation

            try:
                await asyncio.to_thread(finalize_conversation, self.id)
            except Exception:
                logger.warning("Supervisor conversation QA could not be finalized")
        if not getattr(self, "_metrics_ended", True):
            self._metrics_ended = True
            m = _metrics()
            if m is not None:
                m.record_call_end(
                    success=True,
                    duration_sec=time.monotonic() - getattr(self, "start_time", time.monotonic()),
                )
        with Session() as db:
            callback = Conversation.follow_up_kind == "callback"
            follow_up = callback if self.dialogue.confirmed else True
            db.execute(update(Conversation).where(
                Conversation.id == self.id, Conversation.status.in_(("active", "follow_up")),
            ).values(
                status=case((follow_up, "follow_up"), else_="completed"),
                follow_up_kind=case((callback, "callback"), else_=self.dialogue.booking_follow_up_kind()),
                follow_up_at=case((follow_up, func.coalesce(Conversation.follow_up_at, now())), else_=None),
            ))
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
