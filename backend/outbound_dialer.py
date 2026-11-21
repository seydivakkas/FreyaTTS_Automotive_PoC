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

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import time
from typing import Any, Literal
from uuid import uuid4

import numpy as np
from sqlalchemy import select

from backend.config import settings
from backend.db import OutboundCall, Appointment, Vehicle, now
from backend.ami import get_ami_client


def _ami_is_real(ami) -> bool:
    """backend.ami.is_real_ami() ile aynı kural, ama verilen istemci üzerinde: Mock AMI gerçek arama başlatmaz."""
    return bool(getattr(ami, "is_real", True))

logger = logging.getLogger("outbound_dialer")

# Varsayılan Dizinler
DEFAULT_SPOOL_BASE_DIR = settings.data_dir / "call_spool"
DEFAULT_OUTGOING_DIR = DEFAULT_SPOOL_BASE_DIR / "outgoing"
DEFAULT_TMP_DIR = DEFAULT_SPOOL_BASE_DIR / "tmp"

# AMD Eşikleri (Türkçe Telephony)
MAX_HUMAN_GREETING_SEC = 1.6   # Türkçe 'Alo/Efendim/Buyrun' genelde < 1.5s sürer
MIN_HUMAN_PAUSE_SEC = 0.35     # Selamlamadan sonra karşı tarafı dinleme sessizliği
MIN_MACHINE_GREETING_SEC = 2.0 # Telesekreter anonsu kesintisiz > 2s sürer
BEEP_DETECT_FREQ_HZ = 1000.0   # Standart telesekreter bip frekansı (800-1200 Hz)


@dataclass
class AMDResult:
    """Türkçe AMD (Answering Machine Detection) Karar Nesnesi."""
    classification: Literal["HUMAN", "MACHINE", "UNKNOWN"]
    confidence: float
    greeting_duration_sec: float
    silence_duration_sec: float
    beep_detected: bool
    reason: str
    analyzed_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "confidence": round(self.confidence, 3),
            "greeting_duration_sec": round(self.greeting_duration_sec, 3),
            "silence_duration_sec": round(self.silence_duration_sec, 3),
            "beep_detected": self.beep_detected,
            "reason": self.reason,
        }


def detect_voicemail_beep(
    samples: np.ndarray,
    sample_rate: int = 8000,
    target_freq: float = BEEP_DETECT_FREQ_HZ,
    tolerance_hz: float = 150.0,
    min_duration_ms: float = 150.0,
) -> bool:
    """
    Telesekreter bip sesini (800-1200 Hz saf ton) frekans enerjisi analiziyle yakalar.
    Sinyalin hedef frekanstaki tepe enerjisinin ortalama spektruma oranını kontrol eder.
    """
    if len(samples) < int(sample_rate * (min_duration_ms / 1000.0)):
        return False

    # 100 ms'lik pencerelerle FFT veya Goertzel gücü hesapla
    window_size = int(sample_rate * 0.10)  # 100 ms
    hop_size = window_size // 2

    freqs = np.fft.rfftfreq(window_size, 1.0 / sample_rate)
    target_mask = (freqs >= (target_freq - tolerance_hz)) & (freqs <= (target_freq + tolerance_hz))

    consecutive_beep_windows = 0
    required_windows = int(min_duration_ms / 50.0)

    for i in range(0, len(samples) - window_size + 1, hop_size):
        chunk = samples[i : i + window_size]
        # Hanning penceresi uygula
        windowed = chunk * np.hanning(len(chunk))
        spectrum = np.abs(np.fft.rfft(windowed))
        total_energy = np.sum(spectrum ** 2) + 1e-9
        beep_energy = np.sum(spectrum[target_mask] ** 2)

        # Eğer bip aralığındaki enerji toplam enerjinin %35'inden fazlaysa ve seviye yeterliyse
        energy_ratio = beep_energy / total_energy
        rms = np.sqrt(np.mean(chunk ** 2))

        if energy_ratio >= 0.35 and rms >= 0.05:
            consecutive_beep_windows += 1
            if consecutive_beep_windows >= required_windows:
                return True
        else:
            consecutive_beep_windows = 0

    return False


def detect_turkish_amd(
    audio_bytes_or_samples: bytes | np.ndarray,
    sample_rate: int = 8000,
    energy_threshold: float = 0.02,
) -> AMDResult:
    """
    Gelen ses üzerinde Türkçe AMD (İnsan vs Telesekreter) analizi uygular:
    - Alo/Efendim gibi kısa Türkçe karşılama (< 1.6s) ve ardından sessizlik -> HUMAN (< 1 saniyede kesinleşir).
    - Uzun anons (> 2.0s) ve ardından 1000 Hz bip sesi -> MACHINE.
    """
    if isinstance(audio_bytes_or_samples, bytes):
        if len(audio_bytes_or_samples) % 2:
            audio_bytes_or_samples = audio_bytes_or_samples[:-1]
        samples = np.frombuffer(audio_bytes_or_samples, dtype="<i2").astype(np.float32) / 32768.0
    else:
        samples = audio_bytes_or_samples

    total_duration = len(samples) / sample_rate
    if total_duration < 0.2:
        return AMDResult(
            classification="UNKNOWN",
            confidence=0.5,
            greeting_duration_sec=total_duration,
            silence_duration_sec=0.0,
            beep_detected=False,
            reason="Analiz için yetersiz ses süresi (< 200 ms)",
        )

    # 20 ms'lik çerçevelerle konuşma / sessizlik segmentasyonu
    frame_len = int(sample_rate * 0.02)
    energies = []
    for i in range(0, len(samples) - frame_len + 1, frame_len):
        chunk = samples[i : i + frame_len]
        energies.append(float(np.sqrt(np.mean(chunk ** 2))))

    # Konuşma çerçeveleri tespiti
    voiced_frames = [e >= energy_threshold for e in energies]
    first_voice_idx = next((i for i, v in enumerate(voiced_frames) if v), None)

    if first_voice_idx is None:
        # Tamamen sessiz hat
        return AMDResult(
            classification="UNKNOWN",
            confidence=0.6,
            greeting_duration_sec=0.0,
            silence_duration_sec=total_duration,
            beep_detected=False,
            reason="Hatta hiç ses algılanmadı (Sessizlik)",
        )

    # İlk konuşma bloğunun süresi ve ardından gelen sessizlik
    greeting_frames = 0
    silence_after_frames = 0
    passed_greeting = False

    for v in voiced_frames[first_voice_idx:]:
        if v and not passed_greeting:
            greeting_frames += 1
        elif not v and not passed_greeting:
            # 200 ms sessizlik olursa konuşma bitti kabul et
            silence_after_frames += 1
            if silence_after_frames >= 10:  # 200 ms
                passed_greeting = True
        elif passed_greeting and not v:
            silence_after_frames += 1

    greeting_sec = greeting_frames * 0.02
    silence_after_sec = silence_after_frames * 0.02

    # Bip sesi kontrolü
    beep_found = detect_voicemail_beep(samples, sample_rate=sample_rate)

    # 1. Kural: Bip sesi varsa kesinlikle telesekreter
    if beep_found:
        return AMDResult(
            classification="MACHINE",
            confidence=0.98,
            greeting_duration_sec=greeting_sec,
            silence_duration_sec=silence_after_sec,
            beep_detected=True,
            reason="Telesekreter bip sesi (1000 Hz) ve uzun anons algılandı.",
        )

    # 2. Kural: Konuşma süresi çok uzunsa (> 2.0 saniye kesintisiz anons) -> MACHINE
    if greeting_sec >= MIN_MACHINE_GREETING_SEC:
        return AMDResult(
            classification="MACHINE",
            confidence=0.92,
            greeting_duration_sec=greeting_sec,
            silence_duration_sec=silence_after_sec,
            beep_detected=False,
            reason=f"Uzun kesintisiz telesekreter anonsu algılandı ({greeting_sec:.2f}s > 2.0s).",
        )

    # 3. Kural: Kısa Türkçe selamlama (Alo/Efendim <= 1.6s) ve ardından dinleme sessizliği -> HUMAN
    if greeting_sec <= MAX_HUMAN_GREETING_SEC and silence_after_sec >= MIN_HUMAN_PAUSE_SEC:
        return AMDResult(
            classification="HUMAN",
            confidence=0.95,
            greeting_duration_sec=greeting_sec,
            silence_duration_sec=silence_after_sec,
            beep_detected=False,
            reason=f"Kısa Türkçe selamlama ({greeting_sec:.2f}s) ve dinleme beklemesi algılandı.",
        )

    # Ara durum (Tek kelimelik çok kısa ses)
    if greeting_sec <= 0.6:
        return AMDResult(
            classification="HUMAN",
            confidence=0.85,
            greeting_duration_sec=greeting_sec,
            silence_duration_sec=silence_after_sec,
            beep_detected=False,
            reason="Hızlı 'Alo' selamlaması algılandı.",
        )

    return AMDResult(
        classification="UNKNOWN",
        confidence=0.55,
        greeting_duration_sec=greeting_sec,
        silence_duration_sec=silence_after_sec,
        beep_detected=False,
        reason=f"Belirsiz konuşma paterni (Konuşma: {greeting_sec:.2f}s, Sessizlik: {silence_after_sec:.2f}s)",
    )


def generate_call_file_content(
    *,
    channel: str,
    callerid: str,
    context: str,
    exten: str,
    priority: int = 1,
    max_retries: int = 3,
    retry_time: int = 300,
    wait_time: int = 30,
    variables: dict[str, str] | None = None,
) -> str:
    """Asterisk .call dosyası içeriğini standart anahtar-değer formatında üretir."""
    lines = [
        f"Channel: {channel}",
        f"CallerID: {callerid}",
        f"MaxRetries: {max_retries}",
        f"RetryTime: {retry_time}",
        f"WaitTime: {wait_time}",
        f"Context: {context}",
        f"Extension: {exten}",
        f"Priority: {priority}",
    ]
    if variables:
        for k, v in variables.items():
            clean_k = str(k).strip()
            clean_v = str(v).replace("\n", " ").strip()
            lines.append(f"Set: {clean_k}={clean_v}")
    return "\n".join(lines) + "\n"


def write_atomic_call_file(
    content: str,
    outgoing_dir: Path | str = DEFAULT_OUTGOING_DIR,
    tmp_dir: Path | str = DEFAULT_TMP_DIR,
    filename_prefix: str = "outbound",
) -> Path:
    """
    Asterisk yarım dosya okuma hatasını (race condition) önlemek için atomik dosya yazımı:
    1. Geçici dizine `.call.tmp` olarak yazılır ve fsync edilir.
    2. Atomik `os.replace` ile hedef `outgoing` dizinine taşınır.
    """
    out_dir = Path(outgoing_dir)
    t_dir = Path(tmp_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    t_dir.mkdir(parents=True, exist_ok=True)

    call_id = f"{filename_prefix}-{uuid4().hex[:12]}"
    tmp_file = t_dir / f"{call_id}.call.tmp"
    target_file = out_dir / f"{call_id}.call"

    # 1. Geçici dosyaya yaz ve diske senkronize et
    with open(tmp_file, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

    # 2. Atomik olarak hedef dizine taşı
    os.replace(tmp_file, target_file)
    logger.info(f"Atomik .call dosyası oluşturuldu: {target_file}")
    return target_file


class OutboundCampaignDialer:
    """
    Giden Arama, AMI/CallFile ve Türkçe AMD Kampanya Yöneticisi:
    - AMI Originate (Port 5038) ve Atomik Call File (`/var/spool/asterisk/outgoing`) desteği
    - OUTBOUND_UUID ile plaka, fiyat ve müşteri verilerini çağrıya bağlama
    - Türkçe AMD (İnsan vs Telesekreter) ve Voicemail Drop
    - Meşgul/Cevapsız aramalar için otomatik yeniden arama (Auto-Retry)
    """

    def __init__(
        self,
        outgoing_spool_dir: Path | str = DEFAULT_OUTGOING_DIR,
        tmp_spool_dir: Path | str = DEFAULT_TMP_DIR,
        max_retries: int = 3,
        retry_interval_min: int = 15,
    ):
        self.outgoing_spool_dir = Path(outgoing_spool_dir)
        self.tmp_spool_dir = Path(tmp_spool_dir)
        self.max_retries = max_retries
        self.retry_interval_min = retry_interval_min

        # Metrikler
        self.total_originated_ami = 0
        self.total_simulated_ami = 0  # Mock AMI ile "başlatılan" (gerçekte aranmayan) denemeler
        self.total_originated_callfile = 0
        self.total_amd_human = 0
        self.total_amd_machine = 0
        self.total_voicemail_dropped = 0
        self.total_retries_scheduled = 0
        self.total_retries_executed = 0

    async def originate_call_ami(
        self,
        db,
        *,
        appointment_id: str,
        phone: str | None = None,
        call_type: str = "reminder",
        vehicle_plate: str = "",
        quote_price: str = "",
    ) -> OutboundCall:
        """Asterisk AMI Originate (TCP 5038) üzerinden dış arama başlatır."""
        app = db.get(Appointment, appointment_id)
        if not app:
            raise ValueError("Randevu bulunamadı")
        if app.status == "cancelled":
            raise ValueError("İptal edilmiş randevu için arama başlatılamaz")

        target_phone = (phone or app.customer or "").strip()
        if not target_phone:
            raise ValueError("Geçerli bir telefon numarası gerekli")

        # Plaka ve müşteri bilgisi tespiti
        plate = vehicle_plate
        price = quote_price
        if not plate and app.vehicle_id:
            veh = db.get(Vehicle, app.vehicle_id)
            if veh:
                plate = veh.plate or veh.description

        clean_digits = "".join(c for c in target_phone if c.isdigit())
        dial_str = clean_digits if len(clean_digits) >= 7 else target_phone
        channel = f"{settings.ami_channel_prefix}/{dial_str}@{settings.ami_trunk}"

        call_record = OutboundCall(
            appointment_id=appointment_id,
            phone=target_phone,
            customer=app.customer,
            call_type=call_type,
            status="originating",
            outcome="pending",
        )
        db.add(call_record)
        db.flush()

        ami = get_ami_client()
        variables = {
            "OUTBOUND_UUID": str(call_record.id),
            "APPOINTMENT_ID": str(app.id),
            "VEHICLE_PLATE": plate,
            "VEHICLE_PRICE": price,
            "CUSTOMER_NAME": app.customer,
            "CALL_TYPE": call_type,
        }

        try:
            call_record.attempts += 1
            res = await ami.originate(
                channel=channel,
                context=settings.ami_context,
                exten=settings.ami_exten,
                callerid=settings.ami_callerid,
                variables=variables,
                timeout_ms=30000,
            )
            call_record.action_id = res.get("action_id", "")
            # Mock AMI gerçek arama başlatmaz; "in-progress" denirse operatör yanılır.
            if _ami_is_real(ami):
                call_record.status = "in-progress"
                self.total_originated_ami += 1
            else:
                call_record.status = "simulated"
                self.total_simulated_ami += 1
        except Exception as e:
            logger.error(f"AMI Originate hatası: {e}")
            call_record.status = "failed"
            call_record.last_error = str(e)
            db.commit()
            raise RuntimeError(f"Giden arama başlatılamadı: {e}")

        db.commit()
        return call_record

    def originate_call_file(
        self,
        db,
        *,
        appointment_id: str,
        phone: str | None = None,
        call_type: str = "reminder",
        vehicle_plate: str = "",
        quote_price: str = "",
    ) -> tuple[OutboundCall, Path]:
        """Asterisk spool dizinine atomik .call dosyası bırakarak paralel arama başlatır."""
        app = db.get(Appointment, appointment_id)
        if not app:
            raise ValueError("Randevu bulunamadı")
        if app.status == "cancelled":
            raise ValueError("İptal edilmiş randevu için arama başlatılamaz")

        target_phone = (phone or app.customer or "").strip()
        if not target_phone:
            raise ValueError("Geçerli bir telefon numarası gerekli")

        plate = vehicle_plate
        price = quote_price
        if not plate and app.vehicle_id:
            veh = db.get(Vehicle, app.vehicle_id)
            if veh:
                plate = veh.plate or veh.description

        clean_digits = "".join(c for c in target_phone if c.isdigit())
        dial_str = clean_digits if len(clean_digits) >= 7 else target_phone
        channel = f"{settings.ami_channel_prefix}/{dial_str}@{settings.ami_trunk}"

        call_record = OutboundCall(
            appointment_id=appointment_id,
            phone=target_phone,
            customer=app.customer,
            call_type=call_type,
            status="originating",
            outcome="pending",
        )
        db.add(call_record)
        db.flush()

        variables = {
            "OUTBOUND_UUID": str(call_record.id),
            "APPOINTMENT_ID": str(app.id),
            "VEHICLE_PLATE": plate,
            "VEHICLE_PRICE": price,
            "CUSTOMER_NAME": app.customer,
            "CALL_TYPE": call_type,
        }

        call_file_body = generate_call_file_content(
            channel=channel,
            callerid=settings.ami_callerid,
            context=settings.ami_context,
            exten=settings.ami_exten,
            max_retries=self.max_retries,
            retry_time=self.retry_interval_min * 60,
            variables=variables,
        )

        file_path = write_atomic_call_file(
            call_file_body,
            outgoing_dir=self.outgoing_spool_dir,
            tmp_dir=self.tmp_spool_dir,
            filename_prefix=f"outbound_{call_record.id[:8]}",
        )

        call_record.action_id = f"callfile:{file_path.name}"
        call_record.status = "in-progress"
        call_record.attempts += 1
        self.total_originated_callfile += 1

        db.commit()
        return call_record, file_path

    def process_amd_result(
        self,
        db,
        call_id: str,
        amd_result: AMDResult,
    ) -> OutboundCall:
        """
        AMD analiz sonucunu işler:
        - HUMAN: Çağrıyı canlı asistana bağlar.
        - MACHINE: Telesekretere sesli mesaj bırakır (Voicemail Drop).
        """
        call = db.get(OutboundCall, call_id)
        if not call:
            raise ValueError("Arama kaydı bulunamadı")

        if amd_result.classification == "HUMAN":
            self.total_amd_human += 1
            call.status = "in-progress"
            call.outcome = "human_connected"
            logger.info(f"AMD Sonucu: İNSAN algılandı ({call.id}), canlı diyaloğa bağlandı.")

        elif amd_result.classification == "MACHINE":
            self.total_amd_machine += 1
            self.total_voicemail_dropped += 1
            call.status = "completed"
            call.outcome = "voicemail_dropped"
            call.completed_at = now()
            logger.info(f"AMD Sonucu: TELESEKRETER algılandı ({call.id}), sesli mesaj bırakıldı.")

        else:
            call.status = "in-progress"
            call.outcome = "unknown"

        db.commit()
        return call

    def schedule_auto_retry(
        self,
        db,
        call_id: str,
        reason: Literal["busy", "no_answer", "failed"],
    ) -> tuple[OutboundCall, bool]:
        """
        Meşgul (BUSY) veya cevapsız (NOANSWER) aramalarda otomatik yeniden arama planlar.
        Max deneme (3) dolduysa 'unreachable' olarak kapatır.
        """
        call = db.get(OutboundCall, call_id)
        if not call:
            raise ValueError("Arama kaydı bulunamadı")

        if call.attempts >= self.max_retries:
            call.status = "completed"
            call.outcome = "unreachable"
            call.completed_at = now()
            call.last_error = f"Maksimum deneme ({self.max_retries}) aşıldı. Sonuç: {reason}"
            db.commit()
            return call, False

        # Randevu iptal edildiyse yeniden arama yapma
        app = db.get(Appointment, call.appointment_id)
        if app and app.status == "cancelled":
            call.status = "cancelled"
            call.outcome = "cancelled"
            call.completed_at = now()
            db.commit()
            return call, False

        call.status = "retry_scheduled"
        call.outcome = reason
        call.last_error = f"Yeniden arama planlandı ({call.attempts}/{self.max_retries}). Neden: {reason}"
        self.total_retries_scheduled += 1
        db.commit()
        return call, True

    async def process_retry_queue(self, db, limit: int = 10) -> list[OutboundCall]:
        """Yeniden aranması gereken çağrıları bulup tekrar arar."""
        query = (
            select(OutboundCall)
            .where(OutboundCall.status == "retry_scheduled")
            .order_by(OutboundCall.created_at.asc())
            .limit(limit)
        )
        scheduled_calls = db.scalars(query).all()
        retried = []

        for call in scheduled_calls:
            # Randevu durumunu kontrol et
            app = db.get(Appointment, call.appointment_id)
            if not app or app.status in ("cancelled", "confirmed"):
                call.status = "completed"
                call.outcome = "cancelled" if not app or app.status == "cancelled" else "already_confirmed"
                call.completed_at = now()
                continue

            try:
                call.attempts += 1
                call.status = "originating"
                # AMI üzerinden tekrar ara
                clean_digits = "".join(c for c in call.phone if c.isdigit())
                dial_str = clean_digits if len(clean_digits) >= 7 else call.phone
                channel = f"{settings.ami_channel_prefix}/{dial_str}@{settings.ami_trunk}"

                ami = get_ami_client()
                variables = {
                    "OUTBOUND_UUID": str(call.id),
                    "APPOINTMENT_ID": str(app.id),
                    "CUSTOMER_NAME": app.customer,
                    "RETRY_ATTEMPT": str(call.attempts),
                }

                res = await ami.originate(
                    channel=channel,
                    context=settings.ami_context,
                    exten=settings.ami_exten,
                    callerid=settings.ami_callerid,
                    variables=variables,
                    timeout_ms=30000,
                )
                call.action_id = res.get("action_id", "")
                if _ami_is_real(ami):
                    call.status = "in-progress"
                    self.total_retries_executed += 1
                else:
                    call.status = "simulated"
                    self.total_simulated_ami += 1
                retried.append(call)
            except Exception as e:
                logger.error(f"Auto-retry arama hatası ({call.id}): {e}")
                call.last_error = str(e)
                if call.attempts >= self.max_retries:
                    call.status = "failed"
                    call.completed_at = now()

        db.commit()
        return retried

    def get_metrics(self) -> dict[str, Any]:
        """Kampanya ve AMD metriklerini döndürür."""
        return {
            "total_originated_ami": self.total_originated_ami,
            "total_simulated_ami": self.total_simulated_ami,
            "total_originated_callfile": self.total_originated_callfile,
            "total_amd_human": self.total_amd_human,
            "total_amd_machine": self.total_amd_machine,
            "total_voicemail_dropped": self.total_voicemail_dropped,
            "total_retries_scheduled": self.total_retries_scheduled,
            "total_retries_executed": self.total_retries_executed,
            "max_retries": self.max_retries,
            "retry_interval_min": self.retry_interval_min,
        }


# Modül düzeyinde tekil kampanya yöneticisi
campaign_dialer = OutboundCampaignDialer()

