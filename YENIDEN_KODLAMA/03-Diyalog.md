# Diyalog ve ses oturumu

Web kanalında kimliği doğrulanmış istemci POST /api/session-ticket ile 30 saniyelik bilet alır. /ws/voice açılırken bilet tüketilir. Süresi dolmuş bilete 1008 ticket_expired, meşgul hatta 1013 line_busy döner. İlk beş saniyede encoding=pcm_s16le, channels=1 ve sample_rate alanları gönderilir. Kabul edilen hızlar 8000, 16000, 24000, 44100 ve 48000 Hz’dir. İkili giriş paketi en fazla 192000 bayttır. Metin, DTMF ve yeniden kalibrasyon komutları JSON kullanır.

AudioSocket kanalında byte akışından çerçeve oluşturulur. TCP okuma sınırı ses paketi sınırı değildir. İki kanal aynı konuşma kurallarıyla çalışır. Kullanıcı asistanın sözünü kestiğinde eski turun sesinin sonradan çalınmasını önleyin. Bağlantı hangi noktada koparsa kopsun oturumu kapatın ve hat kilidini bırakın.

Aşağıdaki referansta Dialogue.answer tur önceliğini, handle_dtmf tuşların bağlama göre anlamını, _apply_extract katalog eşleşmesini ve eksik alan sorularını gösterir. VoiceSession ses ve metin yollarının birleştiği noktadır. Değişiklik ve iptal akışını yeni kayıt teyidinden ayrı izleyin.


## Davranış tarifi (kod dökümünden önce okuyun)

Bu bölüm aşağıdaki kodun ne yaptığını ve yeni sürümde neyin korunup neyin değişeceğini özetler. Kod ile bu bölüm çelişirse, 01 belgesindeki "Kopyalanmaması gereken davranışlar" tablosuna bakın; orada adı geçen davranışlar bilinçli olarak değiştirilecektir.

### Web ses protokolü

| Yön | Mesaj | Alanlar | Anlamı |
|---|---|---|---|
| İstemci → sunucu, ilk mesaj (5 s içinde) | JSON | `encoding: "pcm_s16le"`, `channels: 1`, `sample_rate` ∈ {8000, 16000, 24000, 44100, 48000} | Biçim uymazsa `error` gönderilir ve bağlantı kapanır |
| İstemci → sunucu | ikili | PCM16 LE mono, paket başına en çok 192.000 bayt | Mikrofon sesi |
| İstemci → sunucu | `{"type":"dtmf","digit":"1"}` | `digit` | Ekrandaki tuş takımı |
| İstemci → sunucu | `{"type":"recalibrate"}` | — | Oda gürültüsünü yeniden ölç |
| İstemci → sunucu | `{"type":"text"\|"text_input"\|"user_message","text":"…"}` | `text` | Yazılı tur; sesle aynı diyalog yolundan geçer |
| Sunucu → istemci | `session` | oturum kimliği | Oturum açıldı |
| Sunucu → istemci | `status` | `value`: `listening`, `synthesizing`, `speaking`, "Modeller hazırlanıyor..." | Panel durum etiketi |
| Sunucu → istemci | `transcript` | `role` (`user`/`assistant`), `text` | Canlı döküm |
| Sunucu → istemci | `playback` | `action`: `pause`, `resume`, `flush`; `turn_id` | Söz kesmede çalmayı duraklat, sürdür veya eski turun sesini at |
| Sunucu → istemci | ikili | PCM16, istemcinin hızında, 20 ms çerçeveler | Asistan sesi |
| Sunucu → istemci | `metrics` | `stt_ms`, `llm_first_token_ms`, `llm_total_ms`, `first_audio_ms`, `tts_ms`, `rtf` | Yalnız ölçülen alanlar gönderilir |
| Sunucu → istemci | `pipeline_event` | aşama F0–F6, durum, süre | Yalnız ölçülen süre yazılır (dürüstlük kuralı 1) |
| Sunucu → istemci | `calibration_start` / `calibration_done` | ortam dBFS, kapı eşiği | Gürültü kalibrasyonu |
| Sunucu → istemci | `dtmf_received`, `operator_transfer`, `error` | — | Bilgi |

Kapanış kodları: bilet geçersiz veya süresi dolmuş `1008 ticket_expired`; hat dolu `1013 line_busy`. Bağlantı önce kabul edilir, sonra kapatılır; aksi halde tarayıcı nedeni göremez (1006).

### Bir turun yolu

1. **Giriş:** Ses çerçevelenir. Kalibrasyon sürüyorsa çerçeve yalnız gürültü profiline gider. Ardından gürültü bastırma ve DTMF tonu algılama (Goertzel) çalışır; algılanan ton konuşma sayılmaz.
2. **Konuşma sonu:** Silero VAD ile tur sonu bulunur. Asistan konuşurken müşteri konuşursa çalma `pause` ile durur. Tanınan metin en çok iki sözcükten oluşuyor ve hepsi onay sesi listesindeyse ("evet", "hı hı", "tamam", "anladım", "peki", "efendim" vb., `backend/audiosocket_server.py:58`) `resume` ile sürer; değilse `flush` ile eski tur atılır ve yeni tur başlar. Eski turun sentezi bitse bile çalınmaz (tur numarası denetimi).
3. **Tanıma:** faster-whisper, Türkçe, ışın genişliği 1. Güveni düşük (konuşma yok olasılığı > 0,40, ortalama log olasılık < −0,85, sıkıştırma oranı > 2,2) bölümler atılır. Boş sonuç sessizlik sayılır. Katalog ipuçları ve enerji kapısı ayarla kapalıdır; açmadan önce akustik ölçüm yapın.
4. **Diyalog:** `Dialogue.answer(text)` tek bir Türkçe yanıt cümlesi döndürür (aşağıdaki öncelik sırası).
5. **Sentez:** Yanıt normalize edilir, yan cümlelere bölünür, her yan cümle ayrı sentezlenir. Bir yan cümle çalarken sonraki hazırlanır (kuyruk 2). Sabit cümleler açılışta önceden sentezlenir; karşılamanın ilk sesi bu yüzden ~15 ms'dir.
6. **Kayıt:** Her tur ve ölçüm `turns` tablosuna yazılır. Görüşme kapanınca durum `completed` (randevu onaylı) veya `follow_up` olur.
7. **Sessizlik:** Asistan konuşmuyor, sentez yok ve 15 s giriş yoksa boş bir tur işlenir (asistan yeniden sorar).
8. **Kapanış:** Bağlantı nerede koparsa kopsun görevler iptal edilir, oturum kapanır, hat kilidi bırakılır.

### Tur öncelik sırası (`Dialogue.answer`)

Yeni sürümde aynı sırayı tek bir tablo olarak kurun; her satır bir niyet tanımı ve en az bir test olsun.

| Sıra | Koşul | Davranış |
|---|---|---|
| 1 | Görüşme bitmiş (`confirmed` veya `done`) | **Referansta hatalı (K3).** Doğrusu: bitiş nedenine göre kısa kapanış cümlesi |
| 2 | Metin boş | `unclear`: 1. kez "Tekrar söyler misiniz?", 2. kez ipuçlu yeniden sorma, 3. kez operatöre aktarım veya geri arama kaydı |
| 3 | Metinde telefon veya plaka var | Taslağa al. Plaka düzeltmesi ("C değil, Denizli'nin D'si", "sonu 124") önceki plakayı değiştirir ve onayı yeniden ister |
| 4 | Konuşma işaretleri: "sizi duyuyorum", "henüz onaylamadım", "bir saniye", "size değildi", "tekrar eder misiniz" | Veritabanına dokunmadan kısa yanıt |
| 5 | Acil durum: motordan/kaputtan duman, fren tutmuyor/boşaldı, kaza (`backend/automotive_dispatch.py:34`) | Güvenlik mesajı; randevu akışı durur. Yeni sürümde bu satırı 1. sıraya alın: "bir saniye" gibi bir ifade acil durum cümlesinin içinde geçerse referans sürüm acil durumu kaçırır |
| 6 | Canlı temsilci isteği | Aktarım; AMI gerçek değilse geri arama kaydı ve dürüst yanıt |
| 7 | Giden arama modları (`outbound_reminder`, `outbound_diagnostic`) | Kendi akışları (aşağıda) |
| 8 | Randevu değiştirme/iptal akışı (gelen arama) | Aşağıdaki "Değişiklik ve iptal" |
| 9 | Onay bekleniyor (`awaiting`) | Yalnız açık onay ("evet", "onaylıyorum", "evet onaylıyorum") kayıt açar; diğer her yanıt kaydı açmaz ve başka saat önerir |
| 10 | Araç ve saat seçili, plaka geldi | Özet ve açık onay sorusu: plaka, araç, gerçek tarih ve saat, tanımlı fiyat |
| 11 | Garanti ve bakım geçmişi soruları | Arayan profilinden yanıt (K6/K7 düzeltilmeden açmayın) |
| 12 | Çoklu araç ("iki aracım var") | İlk araç onaylanınca ikinci araç için akış sıfırlanır |
| 13 | Otomotiv sevk niyetleri: lift durumu, OBD kodu, teknisyen diktesi, rapor gönderimi, araç değerleme | `backend/automotive_dispatch.py` |
| 14 | Seçenekler sunulmuş, ad ve araç belli | "Birinci seçenek", "2 numara" gibi seçim kural ile çözülür; LLM'e sorulmaz |
| 15 | Ad ve araç kuralla çıkarılabiliyor | LLM atlanır (gecikme ~1,4–3,2 s) |
| 16 | Selamlama, teşekkür gibi doğal ifadeler | Yapıcı yönlendirme; "anlayamadım" denmez |
| 17 | Hiçbiri | LLM (qwen2.5:7b) şemalı alan çıkarımı: ad, araç, seçenek. LLM veritabanına yazmaz; yalnız alan önerir (~6 s) |

### Randevu durumu

`BookingStatus`: `IDLE` → `CONFIRMING` → `CONFIRMED`; kayıt hatasında `UNKNOWN`. Geçişler `BookingStateMachine.transition` ile denetlenir; izinsiz geçiş hata verir.

Kayıt (`backend/db.py: book`) şu koşulları zorlar: açık onay bayrağı; görüşme kimliği işlem anahtarıdır (aynı anahtar aynı randevuyu döndürür, farklı içerikle kullanılırsa hata); araç ve saat var olmalı; geçmiş saate kayıt yok; saat başkasına ait olamaz (benzersiz kısıt). Kayıt hata verirse asistan "Randevu sonucunu doğrulayamadım. Tekrar kayıt oluşturmadan önce operatör kontrolü gerekiyor." der ve görüşme `follow_up` olur. Başarı mesajı yalnız kayıt kalıcılaştıktan sonra söylenir.

### Değişiklik ve iptal (gelen arama)

Bu akış referans sürümde düzeltilmiş ve doğru tasarımdır; olduğu gibi alın.

1. Niyet: iptal veya erteleme sözcükleri. Olumsuzluk ("hayır", "kalsın", "iptal etmeyin", "uygun değil") her adımda önce denetlenir ve "Mevcut randevunuz geçerlidir." ile akışı bitirir.
2. Doğrulama: **telefon ve plaka birlikte** istenir. Eksik bilgi bir kez sorulur; ikinci denemede yeni bilgi gelmezse operatöre geri arama kaydı açılır.
3. İptal: "Mevcut randevunuzu iptal etmek istediğinizi onaylıyor musunuz?" Yalnız olumlu yanıt iptal eder.
4. Erteleme: Eski randevu **silinmez**. Taşıma denetiminden (`MoveCheck`: saat boş, geçmiş değil, lift kapasitesi var) geçen en çok üç saat numaralı sunulur. Seçim sonrası onay istenir. Onay anında `BEGIN IMMEDIATE` ile randevu ve sürüm yeniden denetlenir; değiştiyse işlem yapılmaz.
5. Uygun saat yoksa: geri arama kaydı, mevcut randevu korunur.

### Tuş takımı (DTMF)

| Bağlam | Tuş | Anlamı |
|---|---|---|
| Her yerde | 0 | Operatöre aktarım (veya geri arama kaydı) |
| İptal/taşıma onayı bekleniyor | 1 / 2 | Evet / Hayır |
| Taşıma seçenekleri sunuldu | 1 / 2 / 3 | Seçenek |
| Çoklu araç sorusu | 1 / 2 | İkinci araç / Bitir |
| `outbound_reminder` | 1 / 2 | Randevuya geliyorum / Gelemiyorum (sonuç kaydedilir; kayıt başarısızsa farklı yanıt) |
| `outbound_diagnostic` | 1 / 2 | Servis randevusu iste / Uyarıyı not al |
| Randevu onayı bekleniyor | 1 / 2 | Onayla (kayıt açılır) / Onaylama |
| Diğer | herhangi | "Aracınızı söyleyebilir veya 0'ı tuşlayabilirsiniz" |

Tuş algılayıcı eşikleri sıkıdır (enerji oranı 0,60, baskınlık 4,0): 640 konuşma kaydında sahte tuş 0, 384 gerçek tonun 384'ü algılandı. Sahte tuş randevu onaylayabileceği için eşikleri gevşetmeyin.

### Ses ve metin kuralları

- Sentezde yan cümle 15 karakterden kısaysa kare sayısı karakter başına 1,8 ile sınırlanır; aksi halde model süreyi uydurma sesle doldurur.
- "Evet," gibi çok kısa parça bir sonrakiyle birleştirilir; tek başına sentezlenirse sözcük tekrarlanır.
- Tarihler ISO, para TRY; telefon kanalında ses 8 kHz'e indirgenir ve telefon eşitlemesi uygulanır.
- Ses tohumu sabittir (9, "Leyla"). Farklı tohum farklı ses kimliği üretir.


## backend/appointment_reschedule.py

````python
"""Shared read-only appointment move checks for preview and commit."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from backend.db import Appointment, BaySchedule, InspectionBay, InspectionLift, Slot
from backend.lift_bay_capacity_scheduler import check_multi_stage_bay_capacity
from backend.queue_lift import check_slot_lift_capacity


def slot_instant(slot: Slot) -> datetime:
    instant = datetime.fromisoformat(slot.starts_at)
    return instant if instant.utcoffset() is not None else instant.replace(tzinfo=timezone.utc)


def slot_summary(slot: Slot | None) -> dict | None:
    if slot is None:
        return None
    return {"id": slot.id, "starts_at": slot_instant(slot).isoformat(), "duration_minutes": slot.duration_minutes}


def version_for(appointment: Appointment, source: Slot | None, target: Slot) -> str:
    content = [appointment.id, appointment.status, appointment.confirmed, appointment.package_type,
               slot_summary(source), slot_summary(target)]
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


class MoveCheck:
    def __init__(self, db, appointment: Appointment, now: datetime):
        self.db = db
        self.appointment = appointment
        self.now = now
        self.simple_lifts = db.scalar(select(InspectionLift.id).limit(1)) is not None
        self.stations = db.scalar(select(InspectionBay.id).limit(1)) is not None
        self.has_assignment = (
            db.scalar(select(BaySchedule.id).where(
                BaySchedule.appointment_id == appointment.id,
                BaySchedule.status.in_(("scheduled", "in_progress")),
            ).limit(1)) is not None
            or db.scalar(select(InspectionLift.id).where(
                InspectionLift.current_appointment_id == appointment.id,
                InspectionLift.status == "busy",
            ).limit(1)) is not None
        )

    def evaluate(self, target: Slot) -> tuple[str, str, str]:
        if self.appointment.status != "confirmed" or not self.appointment.confirmed:
            return "appointment_inactive", "unchecked", "Yalnız onaylı randevular taşınabilir."
        if target.id is not None and target.id == self.appointment.slot_id:
            return "same_slot", "unchecked", "Randevu zaten bu saatte."
        if slot_instant(target) <= self.now:
            return "past", "unchecked", "Geçmiş saate randevu taşınamaz."
        if target.id is not None and self.db.scalar(select(Appointment.id).where(
            Appointment.slot_id == target.id, Appointment.id != self.appointment.id,
        ).limit(1)) is not None:
            return "occupied", "unchecked", "Hedef saat zaten dolu."
        if self.has_assignment:
            return "assigned", "conflict", "Randevunun aktif lift veya istasyon ataması var. Önce atamayı düzenleyin."
        if self.simple_lifts and not check_slot_lift_capacity(
            self.db, target.starts_at, target.duration_minutes,
            exclude_appointment_id=self.appointment.id, seed=False,
        ):
            return "capacity", "conflict", "Hedef saatte lift kapasitesi dolu veya liftler bakımda."
        if self.stations:
            result = check_multi_stage_bay_capacity(
                self.db, package_type=self.appointment.package_type, requested_start_iso=target.starts_at,
                lookahead_intervals=0, seed=False,
            )
            if not result.is_available:
                return "capacity", "conflict", result.bottleneck_reason or "İstasyon kapasitesi yetersiz."
        if self.simple_lifts or self.stations:
            return "available", "available", "Hedef saat ve tanımlı kapasite uygun."
        return "available", "unknown", "Hedef saat boş. Lift ve istasyon kapasitesi tanımlı değil."

    def alternatives(self, target: Slot) -> list[dict]:
        booked = select(Appointment.slot_id).where(Appointment.slot_id.is_not(None))
        start = func.julianday(Slot.starts_at)
        candidates = self.db.scalars(select(Slot).where(
            start > func.julianday(self.now.isoformat()), Slot.id != target.id, Slot.id.not_in(booked),
        ).order_by(func.abs(start - func.julianday(target.starts_at)), start, Slot.id).limit(32))
        choices = []
        for candidate in candidates:
            if self.evaluate(candidate)[0] == "available":
                choices.append(slot_summary(candidate))
                if len(choices) == 4:
                    break
        return choices
````

## backend/audio.py

````python
import asyncio
import time
import numpy as np
from scipy.signal import resample_poly
from backend.dsp import (
    apply_fade_and_comfort_noise as apply_fade_and_comfort_noise,
    apply_telephony_eq_and_downsample_8k as apply_telephony_eq_and_downsample_8k,
)
from math import gcd


def resample(samples, source, target=16000):
    g = gcd(source, target)
    return resample_poly(samples, target // g, source // g).astype(np.float32)


def pcm(samples):
    return (np.clip(samples, -1, 1) * 32767).round().astype("<i2").tobytes()


def frames(data, size=320):
    for i in range(0, len(data), size):
        yield data[i : i + size].ljust(size, b"\0")


async def pace(data, send, cancelled, clock=time.monotonic, sleep=asyncio.sleep):
    deadline = clock()
    for frame in frames(data):
        if cancelled():
            return
        await send(frame)
        deadline += 0.02
        if deadline < clock():
            deadline = clock() + 0.02
        await sleep(max(0, deadline - clock()))


class Endpoint:
    def __init__(self, model):
        self.model = model
        self.pending = np.zeros(0, np.float32)
        self.pre = []
        self.speech = []
        self.silence = 0
        self.active = False
        self.last_voice_at = None

    def feed(self, samples):
        import torch

        self.pending = np.concatenate((self.pending, samples))
        results = []
        started = False
        while len(self.pending) >= 512:
            block, self.pending = self.pending[:512], self.pending[512:]
            with torch.inference_mode():
                voiced = float(self.model(torch.from_numpy(block), 16000)) > 0.55
            if voiced:
                self.last_voice_at = time.monotonic()
            if voiced and not self.active:
                self.active = True
                self.speech = self.pre.copy()
                self.silence = 0
                started = True
            if self.active:
                self.speech.append(block)
                self.silence = 0 if voiced else self.silence + 512
                if self.silence >= 4800 or len(self.speech) >= 625:
                    results.append(np.concatenate(self.speech))
                    self.active = False
                    self.speech = []
            self.pre = (self.pre + [block])[-10:]
        return started, results
````

## backend/automotive_dispatch.py

````python
# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Otomotiv Eylem ve Niyet Sevk Motoru (Automotive Action Dispatch Engine).

Bu modül gelen ses/metin kullanıcı ifadelerini analiz ederek 6 temel otomotiv eylemini
ve M01-M11 acil durum güvenlik bariyerlerini sevk eder:
  1. Acil Durum / Yol Yardım Güvenlik Bariyeri (Roadside Emergency)
  2. Randevu Talebi (Booking / Reschedule / Cancel)
  3. Lift & İstasyon Kapasite Durumu (Lift Status)
  4. OBD-II DTC Arıza Analizi ve Teşhis (Diagnostics)
  5. Teknisyen Sesli Dikte İşleme (Technician Dictation)
  6. WhatsApp Ekspertiz Raporu Gönderimi (WhatsApp Delivery)
  7. Dinamik Araç Değerleme ve Paket Fiyatlandırma (Valuation & Pricing)
"""

import logging
import re
from typing import Any, Dict, Optional
from backend.db import Session
from backend.diagnostics import lookup_dtc
from backend.queue_lift import get_lift_capacity_status, PACKAGE_DEFINITIONS
from backend.technician_dictation import parse_technician_dictation
from backend.dynamic_valuation_calculator import (
    parse_spoken_valuation_query,
    calculate_dynamic_valuation,
)
from backend.ontology.grounding import AutomotiveGroundingEngine

logger = logging.getLogger("automotive_voice.dispatch")

# Acil Durum Güvenlik Bariyeri Regex'i
_EMERGENCY_RE = re.compile(
    r"\b(fren(?:ler|im)?\s*(?:tutmuyor|boşaldı|patladı)|"
    r"kaza\s*(?:yaptım|yapacağım|yapmak üzereyim|geçirdik)|"
    r"(?:araba|araç|motor)(?:m|ım)?\s*(?:yanıyor|alev aldı)|"
    r"(?:motor(?:dan|umdan)|kaput(?:tan|un altından))\s*duman\s*çıkıyor|"
    r"hararet\s*(?:kırmızıda|tavan yaptı|sonuna dayandı)|"
    r"direksiyon\s*kilitlendi|"
    r"can\s*güvenliği|acil\s*yardım|yolda\s*kaldım)\b",
    re.IGNORECASE,
)

# Lift & İstasyon Durumu Regex'i
_LIFT_STATUS_RE = re.compile(
    r"\b(lift|istasyon)\w*\b.*\b(durum\w*|doluluk\w*|müsait\w*|boş\w*|kapasite\w*|yer\s+var\s+mı)\b|"
    r"\b(boş\s+(?:lift|istasyon|yer)|liftler\s+dolu)\b",
    re.IGNORECASE,
)

# OBD-II DTC Kod Regex'i: P0300, C1234, B0001, U0100 vb.
_DTC_CODE_RE = re.compile(r"\b([PCBU][0-3]\d{3})\b", re.IGNORECASE)

# WhatsApp Rapor Gönderimi Regex'i
_WHATSAPP_REPORT_RE = re.compile(
    r"\b(whatsapp|whatsap|vatsap)\b.*\b(rapor|gönder|at|ilet|paylaş)\b|"
    r"\b(rapor(?:umu|umuzu)?\s*(?:whatsapp|whatsap|vatsap)(?:'tan|tan|'dan|dan| ile)?\s*(?:gönder|at|ilet|paylaş))\b",
    re.IGNORECASE,
)

# Teknisyen Dikte Belirteçleri
_DICTATION_KEYWORDS = (
    "mikron", "boyalı", "değişen", "lokal boya", "macun", "çamurluk",
    "kaput", "tavan", "bagaj", "podye", "şasi", "direk", "far ayağı",
    "kasa", "panel", "kaporta",
)

# Araç Değerleme Belirteçleri (Fiyat sorgusunu araç değerlemeden ayırmak için)
_VALUATION_KEYWORDS = (
    "değerleme", "piyasa değeri", "aracım ne kadar eder", "kaç para eder",
    "değeri nedir", "satmak istiyorum", "ikinci el değeri",
)


def dispatch_emergency(text: str) -> Optional[Dict[str, Any]]:
    """M01-M11 Can Güvenliği ve Acil Durum Kontrolü."""
    if not text:
        return None
    clean = text.strip()
    if _EMERGENCY_RE.search(clean) or ("fren" in clean.lower() and ("tutmuyor" in clean.lower() or "boşaldı" in clean.lower())) or ("kaza" in clean.lower() and "yapacağım" in clean.lower()):
        return {
            "intent": "roadside_emergency",
            "message": (
                "Acil durum uyarısı: Can güvenliğiniz için lütfen aracınızı derhal emniyetli bir alanda durdurun "
                "ve dörtlü flaşörlerinizi yakın. Sizi hemen acil yol yardım ve çekici ekibimize aktarıyorum."
            ),
            "transfer_required": True,
        }
    return None


def dispatch_lift_status(text: str, db=None) -> Optional[Dict[str, Any]]:
    """Ekspertiz lifti ve muayene istasyonu anlık kapasite durumu kontrolü."""
    if not text:
        return None
    if _LIFT_STATUS_RE.search(text) or ("lift" in text.lower() and any(w in text.lower() for w in ("durum", "müsait", "boş", "kapasite"))):
        close_db = False
        if db is None:
            db = Session()
            close_db = True
        try:
            status = get_lift_capacity_status(db)
            return {
                "intent": "lift_durumu",
                "message": status["spoken_message"],
                "data": status,
            }
        finally:
            if close_db:
                db.close()
    return None


def dispatch_obd_dtc(text: str) -> Optional[Dict[str, Any]]:
    """OBD-II DTC Arıza Kodu ve Ontolojik Semptom Teşhisi."""
    if not text:
        return None
    dtc_match = _DTC_CODE_RE.search(text)
    if dtc_match:
        code = dtc_match.group(1).upper()
        lookup = lookup_dtc(code)
        msg = (
            f"{lookup['dtc_code']} arıza kodu: {lookup['description_tr']}. "
            f"Sistem: {lookup['system_category']}, ciddiyet: {lookup['severity']}. "
            f"Önerilen işlem: {lookup['recommended_action']}"
        )
        return {
            "intent": "obd_dtc_ariza",
            "message": msg,
            "data": lookup,
        }

    # Belirti bazlı semptom sorgusu
    lowered = text.lower()
    if any(kw in lowered for kw in ("arıza lambası", "arıza kodu", "ikaz ışığı", "motor ışığı", "hararet", "tekleme")):
        faults = AutomotiveGroundingEngine.diagnose_symptom(text)
        if faults:
            f = faults[0]
            symptoms = ", ".join(f.common_symptoms[:2]) if getattr(f, "common_symptoms", None) else "Genel arıza"
            action = getattr(f, "suggested_action", "Yetkili servise danışınız.")
            msg = (
                f"Belirttiğiniz semptom için teşhis: {f.obd_code} - {f.description}. "
                f"Sistem: {f.system}, belirtiler: {symptoms}. Tavsiye: {action}"
            )
            return {
                "intent": "obd_dtc_ariza",
                "message": msg,
                "data": {"obd_code": f.obd_code, "description": f.description},
            }
    return None


def dispatch_technician_dictation(text: str) -> Optional[Dict[str, Any]]:
    """Teknisyen sesli diktesini yapılandırılmış ekspertiz bulgularına dönüştürür."""
    if not text:
        return None
    lowered = text.lower()
    # Dikte veya mikron/panel anahtar kelimeleri kontrolü
    has_keyword = any(kw in lowered for kw in _DICTATION_KEYWORDS)
    has_micron = bool(re.search(r"\b\d{2,4}\s*(?:mikron|um)?\b", lowered))

    if has_keyword and (has_micron or any(w in lowered for w in ("boyalı", "değişen", "orijinal", "lokal"))):
        parsed = parse_technician_dictation(text)
        if parsed.get("extracted_entities"):
            score = parsed.get("calculated_score")
            score_txt = f" (Hesaplanan Ekspertiz Puanı: {score}/100)" if score is not None else ""
            msg = f"Teknisyen diktesi kaydedildi: {parsed['generated_summary']}{score_txt}"
            return {
                "intent": "teknisyen_dikte",
                "message": msg,
                "data": parsed,
            }
    return None


def dispatch_whatsapp_report(
    text: str,
    phone: str = "",
    plate: str = "",
    customer: str = "",
    db=None,
) -> Optional[Dict[str, Any]]:
    """WhatsApp üzerinden dijital ekspertiz raporu gönderimini sevk eder."""
    if not text:
        return None
    if _WHATSAPP_REPORT_RE.search(text) or ("whatsapp" in text.lower() and "rapor" in text.lower()):
        target_phone = phone.strip()
        target_plate = plate.strip() or "aracınıza"
        target_cust = customer.strip() or "müşterimiz"

        if target_phone:
            # Bildirim kuyruğuna al
            if db is not None:
                try:
                    from backend.notifications import NotificationOutbox
                    from backend.db import uid, now
                    outbox_entry = NotificationOutbox(
                        id=uid(),
                        channel="whatsapp",
                        recipient=target_phone,
                        template_name="inspection_report_delivery",
                        payload_json=f'{{"plate": "{target_plate}", "customer": "{target_cust}"}}',
                        status="queued",
                        created_at=now(),
                    )
                    db.add(outbox_entry)
                    db.flush()
                except Exception:
                    logger.warning("WhatsApp bildirim outbox ekleme atlandı", exc_info=True)

            msg = (
                f"Sayın {target_cust}, {target_plate} ait ekspertiz raporunuz "
                f"WhatsApp üzerinden {target_phone} numaralı hattınıza iletilmek üzere sıraya alındı."
            )
            return {
                "intent": "whatsapp_rapor",
                "message": msg,
                "data": {"phone": target_phone, "plate": target_plate},
            }
        else:
            msg = "Ekspertiz raporunuzu WhatsApp üzerinden iletebilmemiz için lütfen cep telefonu numaranızı söyler misiniz?"
            return {
                "intent": "whatsapp_rapor",
                "message": msg,
                "data": {"missing": "phone"},
            }
    return None


def dispatch_valuation_or_pricing(text: str) -> Optional[Dict[str, Any]]:
    """Dinamik araç piyasa değerleme veya servis paketi fiyatlandırmasını ayırır ve sevk eder."""
    if not text:
        return None
    lowered = text.lower()

    # Araç değerleme sorgusu mu? (örneğin "Passat fiyatı ne kadar?", "2020 Passat ne kadar eder?", "aracımın değeri nedir?")
    is_valuation = any(kw in lowered for kw in _VALUATION_KEYWORDS) or (
        ("fiyat" in lowered or "kaç para" in lowered or "ne kadar" in lowered or "eder" in lowered)
        and any(brand.lower() in lowered for brand in ("passat", "golf", "clio", "megane", "corolla", "egea", "focus", "peugeot", "3008", "civic", "bmw", "mercedes", "audi", "volkswagen", "renault", "toyota", "fiat"))
    )

    if is_valuation:
        parsed_q = parse_spoken_valuation_query(text)
        brand = parsed_q.get("brand")
        model = parsed_q.get("model")
        year = parsed_q.get("model_year") or 2020
        km = parsed_q.get("mileage_km") or 100000

        if brand and model:
            val = calculate_dynamic_valuation(
                brand=brand,
                model=model,
                model_year=year,
                mileage_km=km,
                body_panels=parsed_q.get("body_panels", {}),
                tramer_amount_tl=parsed_q.get("tramer_amount_tl", 0.0),
                is_heavy_damage=parsed_q.get("is_heavy_damage", False),
            )
            est = f"{val.estimated_market_value_tl:,.0f}".replace(",", ".")
            min_p = f"{val.valuation_range_min_tl:,.0f}".replace(",", ".")
            max_p = f"{val.valuation_range_max_tl:,.0f}".replace(",", ".")
            msg = (
                f"{val.brand} {val.model} ({val.model_year}) aracınızın tahmini piyasa değeri "
                f"{est} TL'dir (Beklenen aralık: {min_p} - {max_p} TL). "
                f"Detaylı ekspertiz ve kesin değerleme randevusu oluşturmak ister misiniz?"
            )
            return {
                "intent": "fiyat_parca_sorgusu",
                "sub_type": "vehicle_valuation",
                "message": msg,
                "data": {
                    "brand": val.brand,
                    "model": val.model,
                    "estimated_value_tl": val.estimated_market_value_tl,
                    "price_range": {"min_tl": val.valuation_range_min_tl, "max_tl": val.valuation_range_max_tl},
                },
            }
        elif any(kw in lowered for kw in _VALUATION_KEYWORDS):
            msg = "Aracınızın güncel piyasa değerini hesaplayabilmem için marka, model, yıl ve yaklaşık kilometresini söyler misiniz?"
            return {
                "intent": "fiyat_parca_sorgusu",
                "sub_type": "vehicle_valuation",
                "message": msg,
                "data": {"missing": "vehicle_info"},
            }

    # Paket Fiyat Sorgusu
    if any(w in lowered for w in ("fiyat", "ücret", "kaç para", "ne kadar", "paket")):
        matched_pkg = None
        for k, p in PACKAGE_DEFINITIONS.items():
            if any(kw in lowered for kw in p.get("keywords", [])):
                matched_pkg = p
                break
        if matched_pkg:
            price_tl = f"{matched_pkg['base_price_kurus'] // 100:,}".replace(",", ".")
            msg = (
                f"{matched_pkg['name']} paketimiz {price_tl} TL'dir. "
                f"Yaklaşık {matched_pkg['duration_minutes']} dakika sürer ve {matched_pkg['description']} "
                f"Bu paket için randevu oluşturmak ister misiniz?"
            )
            return {
                "intent": "fiyat_parca_sorgusu",
                "sub_type": "service_packages",
                "message": msg,
                "data": {"package": matched_pkg["key"], "price": price_tl},
            }
        else:
            msg = (
                "Ekspertiz merkezimizde 4 ana paketimiz bulunmaktadır: "
                "Motor ve Mekanik 950 TL, Standart Ekspertiz 1.450 TL, Full Kapsamlı 1.950 TL ve VIP Premium 2.600 TL'dir. "
                "Hangi paketimiz için randevu oluşturmak istersiniz?"
            )
            return {
                "intent": "fiyat_parca_sorgusu",
                "sub_type": "service_packages",
                "message": msg,
                "data": {"packages": list(PACKAGE_DEFINITIONS.keys())},
            }

    return None
````

## backend/dialogue.py

````python
import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from backend.appointment_reschedule import MoveCheck, slot_instant, version_for
from backend.turkish_plate import TurkishPlateParser, extract_plate
from backend.db import (
    Session,
    Vehicle,
    Quote,
    Slot,
    Appointment,
    book,
    CorporateAccount,
    Conversation,
    InspectionReport,
    cancel_appointment,
)
from backend.config import settings
from backend.ami import is_real_ami
from backend.notifications import can_send_real_notifications
from backend.models import models
from backend.text import normalize
from backend.ab_testing import get_prompt_template_text
from backend.dtmf import format_stt_fallback_message
from automotive_voice.dialogue.booking_state import BookingStateMachine
from automotive_voice.dialogue.models import BookingStatus


logger = logging.getLogger("automotive_voice.dialogue")

# Giden aramada olumsuz yanıt kalıpları; onay kalıplarından ÖNCE denetlenir.
_NEGATIVE_RE = re.compile(
    r"\b(hayır|iptal|gelemiyorum|gelemeyeceğim|gelemem|gelmiyorum|gelmeyeceğim|vazgeçtim|istemiyorum)\b"
    r"|\b(uygun|müsait|gelecek\w*|gelebil\w*)\s+değil\w*\b"
)
_POSITIVE_RE = re.compile(
    r"\b(evet|geliyorum|oradayım|onaylıyorum|onay|tamam|uygun|kesinlikle)\b"
)
_CANCEL_INTENT_RE = re.compile(
    r"\b(randevu(?:mu|yu|muz|m)?\s+)?(iptal\s*(?:etmek|edin|edelim|istiyorum|edilsin)?|vazgeçtim|gelemeyeceğim|gelmiyorum)\b",
    re.I,
)
_RESCHEDULE_INTENT_RE = re.compile(
    r"\b(randevu(?:mu|yu|muz|m)?\s+)?(değiştir(?:mek|in|elim|istiyorum)?|saat(?:ini)?\s+değiştir|ertelemek|başka\s+(?:bir\s+)?(?:güne|saate|tarihe)|erteleyelim)\b",
    re.I,
)
_PRICE_INQUIRY_RE = re.compile(
    r"\b(fiyat|fiyatı|fiyatlar|fiyatları|ücret|ücreti|ücretler|kaç\s*para|ne\s*kadar|paketler|paketleri|hizmetler|hizmetleri)\b",
    re.I,
)
_MULTI_VEHICLE_RE = re.compile(
    r"\b(iki\s+ara[çc]\w*|2\s+ara[çc]\w*|iki\s+araba\w*|2\s+araba\w*|bir\s+ara[çc]\w*\s+daha|bir\s+araba\w*\s+daha|ikinci\s+ara[çc]\w*|ikinci\s+araba\w*|başka\s+(?:bir\s+)?ara[çc]\w*|başka\s+(?:bir\s+)?araba\w*|diğer\s+ara[çc]\w*|diğer\s+araba\w*)\b",
    re.I,
)


# extract_plate fonksiyonu ve TurkishPlateParser, backend.turkish_plate modülünden import edilir.


_CHANGE_DECLINED = re.compile(
    r"\b(hayır|kalsın|vazgeçtim|istemiyorum|onaylamıyorum)\b"
    r"|\b(uygun|müsait)\s+değil\w*\b"
    r"|\b(iptal|değişiklik)\s+(?:etme(?:yin|niz|yelim|sin)?|yapma(?:yın|nız|yalım|sın)?)\b"
    r"|\b(erteleme\w*|değiştirme\w*)\s+istemiyorum\b"
)


def _find_active_appointment(db, phone: str, plate: str) -> Appointment | None:
    normalized_phone = extract_phone_number(phone)
    if not normalized_phone or not plate:
        return None
    pairs = db.execute(
        select(Appointment, Vehicle.plate)
        .join(Vehicle, Appointment.vehicle_id == Vehicle.id)
        .where(Appointment.status.in_(("confirmed", "pending")))
    )
    matches = [
        app for app, stored_plate in pairs
        if extract_phone_number(app.customer_phone or "") == normalized_phone
        and "".join(stored_plate.upper().split()) == "".join(plate.upper().split())
    ]
    return matches[0] if len(matches) == 1 else None


class Extract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer: str | None = None
    corporate_name: str | None = None
    vehicle_description: str | None = None
    selected_option: int | None = None
    repeat_options: bool | None = None


_OPTION_WORDS = {
    "birinci": 1, "birincisi": 1, "ilk": 1, "ilki": 1, "1": 1,
    "ikinci": 2, "ikincisi": 2, "2": 2,
    "üçüncü": 3, "üçüncüsü": 3, "3": 3,
}
_OPTION_NUMBERED = {"bir": 1, "iki": 2, "üç": 3, "1": 1, "2": 2, "3": 3}
_OPTION_ALLOWED_WORDS = {
    "seçenek", "seçeneği", "seçeneğini", "seçeneğe", "saat", "saati", "saate",
    "randevu", "randevuyu", "numara", "numarayı", "olan", "olsun", "lütfen",
    "istiyorum", "alayım", "alalım", "seçiyorum", "seçelim", "tercih", "ediyorum",
    "uygun", "tamam",
}


# LLM'e yalnızca son 2 mesaj gider; uzun asistan metinleri kısaltılır (history kendi sınırını korur).
LLM_HISTORY_MESSAGES = 2
LLM_ASSISTANT_MAX_CHARS = 120

# Kural tabanlı çıkarımda "okunmuş" sayılan dolgu sözcükleri; geriye başka sözcük kalırsa LLM'e gidilir.
_FILLER_WORDS = {
    "benim", "aracım", "aracımın", "arabam", "arabamın", "araç", "araba", "marka", "model", "modeli",
    "markası", "bir", "ve", "ile", "için", "lütfen", "merhaba", "selam", "iyi", "günler", "tamam",
    "randevu", "ekspertiz", "istiyorum", "alacağım", "olan", "şu", "bu", "evet", "peki", "de", "da",
}
# Ad kuralında isim sözcüğü olamayacak yaygın sözcükler ("Adım atıyorum" gibi cümleler elenir).
_NAME_STOPWORDS = {
    "atıyorum", "atacağım", "atmak", "atıyoruz", "yok", "ne", "nedir", "bu", "şu", "o", "çok", "bir",
    "ve", "ile", "için", "değil", "kısa", "uzun", "ilk", "son", "yeni", "eski", "geliyor", "olarak",
    "ekspertiz", "randevu", "araç", "aracım", "arabam", "evet", "hayır", "tamam", "lütfen", "soyadım",
}
_NAME_WORD = r"[A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû]+"
_NAME_RE = re.compile(
    rf"^(?:[Bb]enim\s+)?(?:[Aa]dım|[İi]smim)\s+({_NAME_WORD}(?:\s+{_NAME_WORD}){{1,2}})$"
)


def _tr_lower(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def _tr_title(word: str) -> str:
    if word[:1].isupper():
        return word
    first = {"i": "İ", "ı": "I"}.get(word[:1], word[:1].upper())
    return first + _tr_lower(word[1:])


def parse_name_sentence(sentence: str) -> str | None:
    """"Adım Ada Yılmaz" / "Benim ismim Ada Yılmaz" kalıbı; yalnızca ad+soyad (2-3 sözcük).

    Sınırlar: tek sözcük ("Adım Ada"), sonunda başka söz olan cümle ve yaygın sözcükler
    (_NAME_STOPWORDS) eşleşmez; bu durumlar LLM'e kalır.
    """
    m = _NAME_RE.match(sentence.strip())
    if not m:
        return None
    words = m.group(1).split()
    if any(_tr_lower(w) in _NAME_STOPWORDS for w in words):
        return None
    return " ".join(_tr_title(w) for w in words)


def _squash(s: str) -> str:
    return re.sub(r"\W+", " ", s).strip()


def parse_selected_option(text: str) -> int | None:
    """Yalnızca açık ve tek anlamlı seçim ifadesini numaraya çevirir, gerisi LLM'e kalır."""
    lowered = text.replace("İ", "i").replace("I", "ı").lower()
    words = re.sub(r"[^\w\s]", " ", lowered).split()
    if words and words[0] in ("evet", "tamam", "peki"):
        words = words[1:]
    if not words or len(words) > 5:
        return None
    if len(words) >= 2 and words[1] == "numara" and words[0] in _OPTION_NUMBERED:
        option = _OPTION_NUMBERED[words[0]]
    else:
        option = _OPTION_WORDS.get(words[0])
    if option is None or not set(words[1:]) <= _OPTION_ALLOWED_WORDS:
        return None
    return option


def extract_phone_number(text: str) -> str | None:
    """Metin içindeki Türkiye telefon numarasını (05xx... veya 5xx...) çıkarır."""
    digits = re.findall(r"\d+", text)
    if digits:
        joined = "".join(digits)
        if len(joined) == 11 and joined.startswith("05"):
            return joined
        if len(joined) == 10 and joined.startswith("5"):
            return "0" + joined
        if len(joined) == 12 and joined.startswith("905"):
            return "0" + joined[2:]
        if len(joined) == 13 and joined.startswith("+905"):
            return "0" + joined[3:]

    # Türkçe sözlü sayılar ve basamak çözümleme
    units = {"bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9}
    tens = {"on": 10, "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50, "altmış": 60, "yetmiş": 70, "seksen": 80, "doksan": 90}

    lowered = text.replace("İ", "i").replace("I", "ı").lower()
    words = re.sub(r"[^\w\s]", " ", lowered).split()
    parsed_digits = []
    i = 0
    while i < len(words):
        w = words[i]
        if w == "sıfır":
            parsed_digits.append("0")
            i += 1
        elif w in units and i + 1 < len(words) and words[i + 1] == "yüz":
            val = units[w] * 100
            i += 2
            if i < len(words) and words[i] in tens:
                val += tens[words[i]]
                i += 1
            if i < len(words) and words[i] in units:
                val += units[words[i]]
                i += 1
            parsed_digits.append(str(val))
        elif w == "yüz":
            val = 100
            i += 1
            if i < len(words) and words[i] in tens:
                val += tens[words[i]]
                i += 1
            if i < len(words) and words[i] in units:
                val += units[words[i]]
                i += 1
            parsed_digits.append(str(val))
        elif w in tens:
            val = tens[w]
            i += 1
            if i < len(words) and words[i] in units:
                val += units[words[i]]
                i += 1
            parsed_digits.append(str(val))
        elif w in units:
            parsed_digits.append(str(units[w]))
            i += 1
        elif re.fullmatch(r"\d+", w):
            parsed_digits.append(w)
            i += 1
        else:
            i += 1

    joined_parsed = "".join(parsed_digits)
    if len(joined_parsed) == 11 and joined_parsed.startswith("05"):
        return joined_parsed
    if len(joined_parsed) == 10 and joined_parsed.startswith("5"):
        return "0" + joined_parsed
    if len(joined_parsed) == 12 and joined_parsed.startswith("905"):
        return "0" + joined_parsed[2:]
    return None



class Dialogue:
    def __init__(
        self,
        conversation_id,
        max_history_turns: int = 6,
        mode: str = "inbound",
        appointment_id: str | None = None,
        call_id: str | None = None,
        diagnostic_id: str | None = None,
        prompt_template: str = "standard",
        customer_phone: str = "",
    ):
        self.id = conversation_id
        self.mode = mode
        self.appointment_id = appointment_id
        self.call_id = call_id
        self.diagnostic_id = diagnostic_id
        self.prompt_template = prompt_template
        self.outbound_outcome = "pending"
        self.customer = None
        self.corporate_account_id = None
        self.corporate_account_name = None
        self.corporate_discount = 0
        self.vehicle = None
        self.slot = None
        self.package_type = "standart_ekspertiz"
        self.options = []
        self.booking_status = BookingStatus.IDLE
        self.done = False
        self.retries = 0
        self.transfer_requested = False
        self.transfer_id = None
        self.customer_phone = (customer_phone or "").strip()
        self.outbound_persisted: bool | None = None
        self.caller_profile = None
        if self.customer_phone:
            try:
                from backend.caller_memory import get_or_create_caller_profile
                with Session() as db:
                    self.caller_profile = get_or_create_caller_profile(db, phone=self.customer_phone)
                    if self.caller_profile and self.caller_profile.name and not self.customer:
                        self.customer = self.caller_profile.name
            except Exception:
                pass
        self.assigned_lift: str | None = None
        self.detected_action_metadata: dict = {}
        self.history: list[dict[str, str]] = []
        self.max_history_turns = max_history_turns
        self.awaiting_multi_vehicle: bool = False
        self.multi_vehicle_planned: bool = False
        self.awaiting_cancel_confirmation: bool = False
        self.inbound_intent: str | None = None
        self.target_appointment_id: str | None = None
        self.change_prompted = False
        self.change_plate = ""
        self.change_phone = ""
        self.move_choices: list[tuple[str, str, str]] = []
        self.move_choice: tuple[str, str, str] | None = None
        self.plate: str | None = None
        self.plate_draft: str | None = None
        self.plate_confirmed: bool = False
        self.last_turn_trace: dict | None = None
        self.mutations_before_confirmation: int = 0

    def reset_for_next_vehicle(self):
        """Aynı müşterinin ikinci veya sonraki aracı için randevu durumunu sıfırlar."""
        self.vehicle = None
        self.slot = None
        self.plate = None
        self.plate_draft = None
        self.plate_confirmed = False
        self.options = []
        self.booking_status = BookingStatus.IDLE
        self.package_type = "standart_ekspertiz"
        self.awaiting_multi_vehicle = False
        self._clear_appointment_change()
        self.done = False

    def _record_turn_trace(
        self,
        turn_id: str,
        text: str,
        intent: str,
        state_before: str,
        db_mutations: int = 0,
        plate_candidate: str | None = None,
        notes: str = "",
    ):
        if self.booking_status != BookingStatus.CONFIRMED and db_mutations > 0:
            self.mutations_before_confirmation += db_mutations
        self.last_turn_trace = {
            "turn_id": turn_id,
            "timestamp": datetime.now(ZoneInfo("UTC")).isoformat(),
            "input_text": text,
            "intent": intent,
            "plate_candidate": plate_candidate or self.plate or self.plate_draft,
            "state_before": state_before,
            "state_after": self.booking_status.value,
            "db_mutations": db_mutations,
            "mutations_before_confirmation": self.mutations_before_confirmation,
            "notes": notes,
        }

    def record_turn(self, role: str, content: str):
        if content and content.strip():
            self.history.append({"role": role, "content": content.strip()})
            if len(self.history) > self.max_history_turns:
                self.history = self.history[-self.max_history_turns :]

    def _choose_option(self, db, text: str, option: int) -> str:
        i = option - 1
        if i < 0 or i >= len(self.options):
            ans = "Sunulan seçeneklerden birini söyler misiniz?"
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            return ans
        self.slot = self.options[i][0]
        self.awaiting = True
        vehicle = db.get(Vehicle, self.vehicle)
        if vehicle is None:
            self.awaiting = False
            ans = "Araç kaydınız artık mevcut değil. Randevu oluşturmadım."
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            return ans
        ans = f"{self.customer}, {vehicle.description} aracınız için {self.options[i][1]} tarihinde ekspertiz randevusu oluşturulmasını onaylıyor musunuz? Onay için evet onaylıyorum diyebilirsiniz."
        self.record_turn("user", text)
        self.record_turn("assistant", ans)
        return ans

    def build_prompt(self) -> str:
        """Şablon başına sabit sistem istemi (LLM ön ek önbelleği için dinamik durum içermez)."""
        return get_prompt_template_text(self.prompt_template)

    def build_state_message(self) -> str | None:
        """Dinamik durum (müşteri, kurumsal hesap, sunulan seçenekler); son kullanıcı mesajından önce gider."""
        additions = []
        if self.customer:
            additions.append(f"Bilinen müşteri adı: {self.customer}.")
        if self.corporate_account_name:
            additions.append(f"Tanımlı kurumsal galeri: {self.corporate_account_name}.")
        if getattr(self, "caller_profile", None):
            try:
                from backend.caller_memory import format_caller_memory_context
                mem_ctx = format_caller_memory_context(self.caller_profile)
                if mem_ctx:
                    additions.append(f"Müşteri ve Araç Hafıza Bilgisi: {mem_ctx}")
            except Exception:
                pass
        if self.options:
            opts_text = " ".join(
                f"{i + 1}. seçenek {label}." for i, (_, label) in enumerate(self.options)
            )
            additions.append(f"Müşteriye sunulmuş mevcut seçenekler: {opts_text}")
        return "Durum: " + " ".join(additions) if additions else None

    def _llm_messages(self, text: str) -> list[dict[str, str]]:
        """LLM mesajları: sabit sistem istemi, son 2 mesaj, durum, kullanıcı metni (en sonda)."""
        messages = [{"role": "system", "content": self.build_prompt()}]
        for m in self.history[-LLM_HISTORY_MESSAGES:]:
            content = m["content"]
            if m["role"] == "assistant" and len(content) > LLM_ASSISTANT_MAX_CHARS:
                content = content[:LLM_ASSISTANT_MAX_CHARS]  # uzun seçenek metinleri yeniden gönderilmez
            messages.append({"role": m["role"], "content": content})
        state = self.build_state_message()
        if state:
            messages.append({"role": "system", "content": state})
        messages.append({"role": "user", "content": text})
        return messages

    def format_options(self, db):
        history_prefix = getattr(self, "inspection_history_note", "") or ""
        capacity_prefix = ""
        try:
            from backend.queue_lift import get_lift_capacity_status
            cap = get_lift_capacity_status(db)
            if cap.get("all_lifts_busy") and cap.get("busy_lifts", 0) > 0 and cap.get("earliest_available_time"):
                capacity_prefix = f"Şu an {cap['busy_lifts']} liftimiz dolu, en erken saat {cap['earliest_available_time']}'te alabiliyoruz. "
        except Exception:
            capacity_prefix = ""

        quote = db.scalars(select(Quote).where(Quote.vehicle_id == self.vehicle)).first()
        if quote:
            base_amount = quote.amount_kurus
            if self.corporate_account_id and self.corporate_discount > 0:
                discounted = base_amount - (base_amount * self.corporate_discount) // 100
                amount = f"{discounted // 100},{discounted % 100:02d}"
                price = f"{self.corporate_account_name} kurumsal anlaşmalı fiyatı {amount} TL. "
            else:
                amount = f"{base_amount // 100},{base_amount % 100:02d}"
                price = f"Kayıtlı ekspertiz fiyatı {amount} TL. "
        else:
            price = "Kayıtlı fiyat bulunmuyor. "

        if not self.options:
            return (
                history_prefix
                + capacity_prefix
                + price
                + "Şu anda müsait saat bulunmuyor. Daha sonra tekrar arayabilirsiniz."
            )
        return (
            history_prefix
            + capacity_prefix
            + price
            + " ".join(
                f"{i + 1}. seçenek {label}."
                for i, (_, label) in enumerate(self.options)
            )
            + " Hangi seçeneği tercih edersiniz?"
        )

    @property
    def awaiting(self):
        return self.booking_status == BookingStatus.AWAITING_CONFIRMATION

    @property
    def confirmed(self):
        return self.booking_status == BookingStatus.CONFIRMED

    @awaiting.setter
    def awaiting(self, value):
        if value:
            self.booking_status = BookingStateMachine.transition(
                self.booking_status, BookingStatus.AWAITING_CONFIRMATION
            )
        elif self.awaiting:
            self.booking_status = BookingStateMachine.transition(
                self.booking_status, BookingStatus.DECLINED
            )

    def get_transfer_summary(self, db=None) -> str:
        parts = []
        if self.customer:
            parts.append(f"Müşteri: {self.customer}")
        if self.vehicle:
            if db:
                from backend.db import Vehicle
                v = db.get(Vehicle, self.vehicle)
                if v:
                    parts.append(f"Araç: {v.description or v.plate}")
            else:
                parts.append("Araç seçimi yapıldı")
        if getattr(self, "package_type", None):
            parts.append(f"Paket: {self.package_type}")
        if not parts:
            return "Canlı operatör aktarım talebi"
        return " / ".join(parts)

    def _sms_note(self, text: str) -> str:
        """SMS/WhatsApp cümlesini yalnızca gerçek sağlayıcı varsa VE telefon biliniyorsa ekler."""
        if can_send_real_notifications() and self.customer_phone:
            return " " + text
        return ""

    def _begin_transfer(self, db=None) -> str | None:
        """Operatör aktarımını başlatır. AMI gerçek değilse aktarım yapılmaz.

        Gerçekse None döner (çağıran standart "aktarıyorum" metnini kullanır).
        Mock ise geri arama kaydı açılır ve müşteriye doğru metin döner.
        """
        self.done = True
        if is_real_ami():
            self.transfer_requested = True
            return None
        self.transfer_requested = False
        self.record_callback_request(db)
        return "Şu anda operatöre bağlayamıyorum; talebinizi kaydettim, sizi arayacağız."

    def record_callback_request(self, db=None, *, reason="AMI bağlı değil") -> bool:
        """Aktarım yapılamadığında görüşmeyi 'follow_up' işaretleyip operatör notu ekler."""
        try:
            if db is None:
                with Session() as own:
                    return self.record_callback_request(own, reason=reason)
            conv = db.get(Conversation, self.id)
            if conv and conv.status in {"active", "follow_up"}:
                conv.status = "follow_up"
                stamp = datetime.now(ZoneInfo("UTC")).isoformat()
                if conv.follow_up_kind != "callback":
                    conv.follow_up_at = stamp
                conv.follow_up_kind = "callback"
                note = (
                    f"[{stamp}] Operatör aktarımı yapılamadı ({reason}); "
                    f"müşteri geri aranacak. {self.get_transfer_summary(db)}"
                )
                conv.operator_notes = f"{conv.operator_notes or ''}\n{note}".strip()
                db.commit()
                return True
        except Exception:
            logger.exception("Geri arama kaydı oluşturulamadı: %s", self.id)
        return False

    def booking_follow_up_kind(self) -> str | None:
        if self.booking_status in {BookingStatus.UNKNOWN, BookingStatus.CONFIRMING}:
            return "booking_unknown"
        if self.awaiting or (self.booking_status == BookingStatus.IDLE and self.options and not self.done):
            return "booking_pending"
        return None

    def _persist_outbound(self, db, outcome: str) -> bool:
        """Giden arama sonucunu kaydeder. Başarısızlık yutulmaz: loglanır ve False döner."""
        try:
            if self.call_id:
                from backend.outbound import complete_outbound_call

                complete_outbound_call(db, call_id=self.call_id, outcome=outcome)
                return True
            if self.appointment_id:
                app = db.get(Appointment, self.appointment_id)
                if app is None:
                    return False
                if outcome == "cancelled":
                    cancel_appointment(db, app)
                elif outcome == "confirmed":
                    app.status = "confirmed"
                    db.commit()
                return True
            # call_id ve appointment_id yok: kaydedilecek yer yok.
            logger.warning("Giden arama sonucu kaydedilemedi (call_id/appointment_id yok): %s", self.id)
            return False
        except Exception:
            logger.exception("Giden arama sonucu kaydedilemedi: %s", self.call_id or self.appointment_id)
            try:
                db.rollback()
            except Exception:
                pass
            return False

    def _persist_reply(self, db, outcome: str, ok_text: str, fail_text: str) -> str:
        """Sonuç kaydı başarısızsa müşteriye başarı bildirmek yerine dürüst metin döner."""
        if db is None:
            with Session() as own:
                return self._persist_reply(own, outcome, ok_text, fail_text)
        ok = self._persist_outbound(db, outcome)
        self.outbound_persisted = ok
        return ok_text if ok else fail_text

    def unclear(self, db=None):
        self.retries += 1
        if self.retries >= 3:
            unavailable = self._begin_transfer(db)
            if unavailable:
                return f"Sizi anlayamadım. {unavailable}"
            return "Sizi daha iyi yardımcı olabilmesi için yetkili danışmanımıza aktarıyorum. Lütfen hattan ayrılmayın."
        if self.retries == 2:
            return format_stt_fallback_message(self)
        return "Sizi anlayamadım. Tekrar söyler misiniz?"

    async def handle_dtmf(self, digit: str, db) -> str:
        d = digit.strip().upper()

        # Operatöre aktarım tuşlaması (0) her durumda önceliklidir
        if d == "0":
            unavailable = self._begin_transfer(db)
            ans = (
                "0'ı tuşladınız. " + unavailable
                if unavailable
                else "0'ı tuşladınız. Sizi yetkili ekspertiz danışmanımıza aktarıyorum, lütfen hattan ayrılmayın."
            )
            self.record_turn("user", f"[DTMF: {d}]")
            self.record_turn("assistant", ans)
            return ans

        if self.awaiting_cancel_confirmation or self.move_choice:
            if d in {"1", "2"}:
                return await self.answer("Evet, onaylıyorum." if d == "1" else "Hayır, kalsın.")
        elif self.move_choices and d in {"1", "2", "3"}:
            return await self.answer(f"{d} numara")

        # Çoklu Araç Randevusu Sorusunda Tuşlama
        if getattr(self, "awaiting_multi_vehicle", False):
            if d == "1":
                self.reset_for_next_vehicle()
                ans = "1'i tuşladınız. Diğer aracınızın marka ve modelini söyler misiniz?"
                self.record_turn("user", f"[DTMF: {d}]")
                self.record_turn("assistant", ans)
                return ans
            elif d == "2":
                self.done = True
                self.awaiting_multi_vehicle = False
                ans = "2'yi tuşladınız. Teşekkür eder, iyi günler dileriz."
                self.record_turn("user", f"[DTMF: {d}]")
                self.record_turn("assistant", ans)
                return ans

        # 1. Giden Hatırlatma Araması Modu (Outbound Reminder)
        if self.mode == "outbound_reminder":
            if d == "1":
                self.outbound_outcome = "confirmed"
                self.done = True
                ans = self._persist_reply(
                    db,
                    "confirmed",
                    "1'i tuşladınız. Randevunuz teyit edildi, teşekkür ederiz. Belirtilen saatte görüşmek üzere iyi günler dileriz.",
                    "1'i tuşladınız. Teyidinizi aldım ancak sisteme kaydedemedim; operatörümüz sizi ayrıca arayacak. İyi günler dileriz.",
                )
                self.record_turn("user", f"[DTMF: {d}]")
                self.record_turn("assistant", ans)
                return ans
            elif d == "2":
                self.outbound_outcome = "cancelled"
                self.done = True
                ans = self._persist_reply(
                    db,
                    "cancelled",
                    "2'yi tuşladınız. Randevunuz talebiniz üzerine iptal edilmiştir. İyi günler dileriz.",
                    "2'yi tuşladınız. İptal talebinizi aldım ancak sisteme işleyemedim; operatörümüz sizinle ilgilenecek. İyi günler dileriz.",
                )
                self.record_turn("user", f"[DTMF: {d}]")
                self.record_turn("assistant", ans)
                return ans

        # 2. Giden Teşhis Araması Modu (Outbound Diagnostic)
        if self.mode == "outbound_diagnostic":
            if d == "1":
                self.mode = "inbound"
                ans = "1'i tuşladınız. Müsait servis saatlerimizi kontrol ediyorum. Adınızı ve randevu istediğiniz saati söyler misiniz?"
                self.record_turn("user", f"[DTMF: {d}]")
                self.record_turn("assistant", ans)
                return ans
            elif d == "2":
                self.done = True
                ans = "2'yi tuşladınız. Arıza uyarısını sistemimize not aldım. Güvenli sürüşler dileriz."
                self.record_turn("user", f"[DTMF: {d}]")
                self.record_turn("assistant", ans)
                return ans

        # 3. Randevu Onayı Beklenirken (Awaiting Confirmation)
        if self.awaiting:
            if d == "1":
                self.booking_status = BookingStateMachine.transition(
                    self.booking_status, BookingStatus.CONFIRMING
                )
                try:
                    book(
                        db,
                        slot_id=self.slot,
                        vehicle_id=self.vehicle,
                        customer=self.customer,
                        idempotency_key=self.id,
                        confirmed=True,
                        corporate_account_id=self.corporate_account_id,
                        customer_phone=self.customer_phone,
                        package_type=getattr(self, "package_type", "standart_ekspertiz"),
                    )
                except Exception:
                    db.rollback()
                    self.booking_status = BookingStateMachine.transition(
                        self.booking_status, BookingStatus.UNKNOWN
                    )
                    self.done = True
                    self.slot = None
                    ans = "Randevu sonucunu doğrulayamadım. Tekrar kayıt oluşturmadan önce operatör kontrolü gerekiyor."
                    self.record_turn("user", f"[DTMF: {d}]")
                    self.record_turn("assistant", ans)
                    return ans

                self.booking_status = BookingStateMachine.transition(
                    self.booking_status, BookingStatus.CONFIRMED
                )
                self.retries = 0
                if getattr(self, "multi_vehicle_planned", False):
                    ans = f"1'i tuşladınız. İlk aracınız için randevunuz oluşturuldu.{self._sms_note('Onay ve randevu detaylarını SMS olarak telefonunuza iletiyorum.')} Şimdi ikinci aracınızın marka ve modelini söyler misiniz?"
                    self.reset_for_next_vehicle()
                else:
                    self.done = True
                    if self.corporate_account_name:
                        ans = f"1'i tuşladınız. Randevunuz {self.corporate_account_name} kurumsal cari hesabınıza işlenerek onaylandı.{self._sms_note('SMS ve WhatsApp ile detayları iletiyorum.')} İyi günler dilerim."
                    else:
                        ans = f"1'i tuşladınız. Randevunuz onaylandı ve oluşturuldu.{self._sms_note('Onay ve randevu detaylarını SMS olarak telefonunuza iletiyorum.')} İyi günler dilerim."
                self.record_turn("user", f"[DTMF: {d}]")
                self.record_turn("assistant", ans)
                return ans
            elif d == "2":
                self.awaiting = False
                self.slot = None
                ans = "2'yi tuşladınız. Randevu onaylanmadı. Başka bir saat seçmek ister misiniz?"
                self.record_turn("user", f"[DTMF: {d}]")
                self.record_turn("assistant", ans)
                return ans

        # 4. Seçenekler Sunulmuşken Tuşlama (Slot Selection)
        if self.options and len(self.options) > 0:
            if d in ("1", "2", "3", "4", "5", "6"):
                idx = int(d) - 1
                if idx < len(self.options):
                    self.slot = self.options[idx][0]
                    slot_label = self.options[idx][1]
                    self.awaiting = True
                    ans = (
                        f"{d}. seçeneği seçtiniz: {slot_label}. Randevunuzu onaylıyor musunuz? "
                        "Onaylamak için 1'i, başka saat seçmek için 2'yi tuşlayabilirsiniz."
                    )
                    self.record_turn("user", f"[DTMF: {d}]")
                    self.record_turn("assistant", ans)
                    return ans
            elif d in ("*", "#"):
                ans = self.format_options(db)
                self.record_turn("user", f"[DTMF: {d}]")
                self.record_turn("assistant", ans)
                return ans

        # 5. Genel veya Tanımlanmamış Tuşlama
        ans = f"{d} tuşlamanız alındı. Randevu oluşturmak için aracınızı söyleyebilir veya danışmanımıza bağlanmak için 0'ı tuşlayabilirsiniz."
        self.record_turn("user", f"[DTMF: {d}]")
        self.record_turn("assistant", ans)
        return ans

    def _clear_appointment_change(self):
        self.awaiting_cancel_confirmation = False
        self.inbound_intent = None
        self.target_appointment_id = None
        self.change_phone = ""
        self.change_prompted = False
        self.change_plate = ""
        self.move_choices = []
        self.move_choice = None

    def _appointment_change(self, text: str, clean: str) -> str | None:
        if _CHANGE_DECLINED.search(clean):
            if self.inbound_intent:
                self._clear_appointment_change()
                return "Mevcut randevunuz geçerlidir."
            return None

        if self.awaiting_cancel_confirmation or self.move_choice:
            if not _POSITIVE_RE.search(clean) and not (
                self.awaiting_cancel_confirmation and re.search(r"\biptal\s+(?:edin|edilsin)\b", clean)
            ):
                return "İşlemi onaylıyor musunuz? Evet veya hayır diyebilirsiniz."
            return self._commit_appointment_change()

        if self.move_choices:
            option = parse_selected_option(text)
            if option is None or not 1 <= option <= len(self.move_choices):
                return "Lütfen sunduğum saatlerden birinin numarasını söyleyin."
            self.move_choice = self.move_choices[option - 1]
            return f"Randevunuzu {self.move_choice[2]} tarihine taşımayı onaylıyor musunuz?"

        if self.inbound_intent not in ("cancel", "reschedule"):
            if not (_CANCEL_INTENT_RE.search(clean) or _RESCHEDULE_INTENT_RE.search(clean)):
                return None
            self.inbound_intent = "cancel" if _CANCEL_INTENT_RE.search(clean) else "reschedule"

        plate = extract_plate(text)
        phone_text = text
        if plate:
            phone_text = re.sub(r"\b" + r"\s*".join(map(re.escape, plate.split())) + r"\b", "", text, flags=re.I)
        supplied_phone = extract_phone_number(phone_text)
        added_detail = bool((plate and not self.change_plate) or (supplied_phone and not self.change_phone))
        self.change_plate = plate or self.change_plate
        self.change_phone = supplied_phone or self.change_phone or self.customer_phone
        if not self.change_phone or not self.change_plate:
            if self.change_prompted and not added_detail:
                return self._appointment_verification_failed()
            self.change_prompted = True
            if self.change_phone:
                return "Randevuyu doğrulamak için araç plakanızı söyler misiniz?"
            if self.change_plate:
                return "Randevuyu doğrulamak için kayıtlı telefon numaranızı söyler misiniz?"
            return "Randevuyu doğrulamak için kayıtlı telefon numaranızı ve araç plakanızı söyler misiniz?"

        with Session() as db:
            appointment = _find_active_appointment(db, self.change_phone, self.change_plate)
            if appointment is None:
                return self._appointment_verification_failed(db)
            self.target_appointment_id = appointment.id
            source = db.get(Slot, appointment.slot_id)
            if self.inbound_intent == "cancel":
                self.awaiting_cancel_confirmation = True
                return "Mevcut randevunuzu iptal etmek istediğinizi onaylıyor musunuz?"

            now = datetime.now(ZoneInfo("UTC"))
            check = MoveCheck(db, appointment, now)
            occupied = select(Appointment.slot_id).where(Appointment.slot_id.is_not(None))
            candidates = db.scalars(
                select(Slot).where(
                    Slot.id.not_in(occupied), func.julianday(Slot.starts_at) > func.julianday(now.isoformat())
                ).order_by(func.julianday(Slot.starts_at), Slot.id)
            )
            for slot in candidates:
                if check.evaluate(slot)[0] == "available":
                    label = slot_instant(slot).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y saat %H:%M")
                    self.move_choices.append((slot.id, version_for(appointment, source, slot), label))
                    if len(self.move_choices) == 3:
                        break
            if not self.move_choices:
                self.record_callback_request(db, reason="Erteleme için uygun saat bulunamadı")
                self._clear_appointment_change()
                return "Uygun yeni saat bulunamadı. Mevcut randevunuz geçerlidir."
        options = " ".join(f"{i}. seçenek {choice[2]}." for i, choice in enumerate(self.move_choices, 1))
        return f"Mevcut randevunuz geçerlidir. {options} Hangi seçeneği tercih edersiniz?"

    def _appointment_verification_failed(self, db=None) -> str:
        recorded = self.record_callback_request(db, reason="Randevu telefon ve plaka ile doğrulanamadı")
        self._clear_appointment_change()
        if recorded:
            return "Randevuyu doğrulayamadım. Talebinizi operatöre ilettim."
        return "Randevuyu doğrulayamadım. Lütfen operatöre ulaşın."

    def _commit_appointment_change(self) -> str:
        appointment_id = self.target_appointment_id
        phone, plate = self.change_phone, self.change_plate
        choice = self.move_choice
        self._clear_appointment_change()
        with Session() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            appointment = _find_active_appointment(db, phone, plate)
            if appointment is None or appointment.id != appointment_id:
                return "Randevu bilgileri değişti. İşlem gerçekleştirilemedi."
            if choice is None:
                cancel_appointment(db, appointment)
                try:
                    from backend.notifications import queue_cancellation_notification
                    queue_cancellation_notification(db, appointment)
                except Exception:
                    logger.exception("İptal bildirimi kuyruğa alınamadı")
                self.done = True
                return "Randevunuz başarıyla iptal edilmiştir. İyi günler dileriz."

            slot_id, version, label = choice
            source = db.get(Slot, appointment.slot_id)
            target = db.get(Slot, slot_id)
            if (
                target is None or version != version_for(appointment, source, target)
                or MoveCheck(db, appointment, datetime.now(ZoneInfo("UTC"))).evaluate(target)[0] != "available"
            ):
                return "Yeni saat artık müsait değil. Mevcut randevunuz geçerlidir."
            appointment.slot_id = target.id
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return "Yeni saat artık müsait değil. Mevcut randevunuz geçerlidir."
            self.done = True
            return f"Randevunuz {label} tarihine taşındı."

    def _handle_automotive_inbound_appointment(
        self, text: str, clean: str, turn_id: str, initial_status: str
    ) -> str | None:
        """PoC Çekirdek Akış: Doğal dille ekspertiz randevusu, plaka ve takvim entegrasyonu."""
        is_poc_trigger = bool(
            re.search(
                r"\b(yarın|yarına|ekspertiz|randevu|randevusu|fiyat|fiyatı|ücret|ücreti|kaç\s*lira|kaç\s*para|ne\s*kadar|paket)\b",
                clean,
            )
            or any("modeli nedir" in m.get("content", "").lower() for m in self.history)
            or (extract_plate(text) is not None and any(w in clean for w in ("corolla", "passat", "peugeot", "egea", "megane", "toyota")))
        )
        if not is_poc_trigger:
            return None

        norm_text = normalize(text)["normalized"].lower()

        with Session() as db:
            vehicles = db.scalars(select(Vehicle)).all()
            matched_vehicle = None

            # Sadece marka söylendiyse (ör. "Toyota için yarına ekspertiz istiyorum")
            has_toyota = "toyota" in clean or "toyota" in norm_text
            has_corolla = "corolla" in clean or "korolla" in norm_text or "corolla" in norm_text
            if has_toyota and not has_corolla:
                ans = "Toyota’nın modeli nedir?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                self._record_turn_trace(turn_id, text, "car_model_inquiry", initial_status, db_mutations=0)
                return ans

            for v in vehicles:
                raw_lower = _tr_lower(v.description)
                norm_lower = _tr_lower(_squash(normalize(v.description)["normalized"]))
                words = set(raw_lower.split() + norm_lower.split())
                model_words = [w for w in words if len(w) >= 3 and w not in ("toyota", "renault", "volkswagen", "fiat")]
                if raw_lower in clean or norm_lower in norm_text or any(w in clean or w in norm_text for w in model_words):
                    matched_vehicle = v
                    break

            if not matched_vehicle:
                return None

            self.vehicle = matched_vehicle.id
            quote = db.scalars(select(Quote).where(Quote.vehicle_id == matched_vehicle.id)).first()
            if quote:
                price_str = f"{quote.amount_kurus // 100:,}".replace(",", ".") + " TL"
            else:
                price_str = "2.500 TL"

            # 1. Sadece Bilgi / Fiyat Sorgusu (Randevu istemiyorum)
            if re.search(r"\b(randevu\s+istemiyorum|şimdi(?:lik)?\s+randevu\s+istemiyorum|sadece\s+fiyat|bilgi\s+almak)\b", clean):
                ans = f"Standart paket {price_str}. Başka bir sorunuz var mı?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                self._record_turn_trace(turn_id, text, "info_quote", initial_status, db_mutations=0)
                return ans

            # Uygun saatleri takvimden bul
            occupied = select(Appointment.slot_id).where(Appointment.slot_id.is_not(None))
            slots = db.scalars(
                select(Slot).where(Slot.id.not_in(occupied)).order_by(Slot.starts_at)
            ).all()
            future_slots = [
                s for s in slots if datetime.fromisoformat(s.starts_at) > datetime.now(ZoneInfo("UTC"))
            ]
            if not future_slots:
                ans = "Şu anda müsait saat bulunmuyor. Daha sonra tekrar arayabilirsiniz."
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                self._record_turn_trace(turn_id, text, "no_slots", initial_status, db_mutations=0)
                return ans

            target_slot = future_slots[0]
            dt = datetime.fromisoformat(target_slot.starts_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("Europe/Istanbul"))
            else:
                dt = dt.astimezone(ZoneInfo("Europe/Istanbul"))
            slot_time = dt.strftime("%H.%M")
            self.slot = target_slot.id
            self.options = [(target_slot.id, f"yarın saat {slot_time}")]

            # 2. Dolu Saat Talebi ("saat dokuzda", "09.00", vb.)
            if re.search(r"\b(saat\s+(?:dokuz|09|9)|dokuzda|09\.00|09:00)\b", clean):
                ans = f"09.00 dolu, {slot_time} müsait. Uygun mu?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                self._record_turn_trace(turn_id, text, "slot_full_alternative", initial_status, db_mutations=0)
                return ans

            # 3. Fiyat Sorgusu + Randevu İstemi ("kaç lira? Uygunsa yarın geleyim")
            if re.search(r"\b(kaç\s*lira|kaç\s*para|ne\s*kadar|fiyat|fiyatı|ücret|ücreti)\b", clean) and any(
                w in clean for w in ("uygunsa", "geleyim", "gelelim", "yaparız", "yarın")
            ):
                ans = f"Standart paket {price_str}. Yarın {slot_time} müsait. Devam edelim mi?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                self._record_turn_trace(turn_id, text, "price_quote_offer", initial_status, db_mutations=0)
                return ans

            # 4. Plaka da bu turda verildiyse ("Plakam 34 AB 123", vb.)
            plate_candidate = extract_plate(text)
            if plate_candidate:
                self.plate_draft = plate_candidate
                self.plate = plate_candidate
                if any("modeli nedir" in m.get("content", "").lower() for m in self.history):
                    self.awaiting = True
                    ans = f"{self.plate} plakalı {matched_vehicle.description} için yarın {slot_time}’da, {price_str} tutarında standart ekspertiz randevusunu onaylıyor musunuz?"
                    self.record_turn("user", text)
                    self.record_turn("assistant", ans)
                    self._record_turn_trace(turn_id, text, "car_model_provided_ask_confirm", initial_status, db_mutations=0)
                    return ans
                ans = f"{plate_candidate} olarak duydum, doğru mu?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                self._record_turn_trace(turn_id, text, "plate_candidate_confirm", initial_status, db_mutations=0)
                return ans

            # 5. Standart Randevu Talebi (Plaka Henüz Yok)
            ans = f"Yarın {slot_time} uygun. Plakanızı söyler misiniz?"
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            self._record_turn_trace(turn_id, text, "slot_offered_ask_plate", initial_status, db_mutations=0)
            return ans

    async def answer(self, text):
        turn_id = f"{self.id}-{len(self.history) // 2 + 1}"
        initial_status = self.booking_status.value

        if self.confirmed or self.done:
            ref = "TEST-001" if (self.id.startswith(("NEW-", "PLATE-", "PRICE-", "FULL-", "CAR-", "MOVE-", "CANCEL-", "INFO-", "POC-")) or "test" in self.id.lower() or "demo" in self.id.lower()) else "TEST-001"
            ans = f"Randevunuz oluşturulmuştur. Referansınız {ref}."
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            self._record_turn_trace(turn_id, text, "already_confirmed", initial_status, db_mutations=0)
            return ans

        if not text.strip():
            ans = self.unclear()
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            self._record_turn_trace(turn_id, text, "unclear", initial_status, db_mutations=0)
            return ans

        norm = _tr_lower(text.strip())
        clean = re.sub(r"[.,!?;:]", " ", norm)

        phone_in_text = extract_phone_number(text)
        if phone_in_text:
            self.customer_phone = phone_in_text
            try:
                from backend.caller_memory import get_or_create_caller_profile
                with Session() as db:
                    self.caller_profile = get_or_create_caller_profile(db, phone=self.customer_phone)
                    if self.caller_profile and self.caller_profile.name and not self.customer:
                        self.customer = self.caller_profile.name
            except Exception:
                pass

        plate_in_text = extract_plate(text)
        if plate_in_text:
            self.plate_draft = plate_in_text
            if not self.plate:
                self.plate = plate_in_text
            if not getattr(self, "caller_profile", None):
                try:
                    from backend.caller_memory import get_or_create_caller_profile
                    with Session() as db:
                        self.caller_profile = get_or_create_caller_profile(db, plate=plate_in_text)
                        if self.caller_profile and self.caller_profile.name and not self.customer:
                            self.customer = self.caller_profile.name
                except Exception:
                    pass

        # Hedefe yönelik plaka düzeltmesi (ör. "C değil, Denizli’nin D’si" / "sonu 124")
        active_plate = self.plate or self.plate_draft or getattr(self, "change_plate", None)
        corr = None
        if active_plate:
            corr = TurkishPlateParser.correct_plate(active_plate, text)

        if corr and corr.is_correction:
            self.plate = corr.plate
            self.plate_draft = corr.plate
            self.plate_confirmed = False
            if self.vehicle and self.slot:
                self.awaiting = True
                with Session() as db:
                    vehicle = db.get(Vehicle, self.vehicle)
                    v_desc = vehicle.description if vehicle else "aracınız"
                    slot = db.get(Slot, self.slot)
                    if slot:
                        dt = datetime.fromisoformat(slot.starts_at)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=ZoneInfo("Europe/Istanbul"))
                        else:
                            dt = dt.astimezone(ZoneInfo("Europe/Istanbul"))
                        slot_time = dt.strftime("%H.%M")
                    else:
                        slot_time = "10.00"
                    quote = db.scalars(select(Quote).where(Quote.vehicle_id == self.vehicle)).first()
                    price_str = f"{quote.amount_kurus // 100:,}".replace(",", ".") + " TL" if quote else "2.500 TL"
                    ans = f"{self.plate} plakalı {v_desc} için yarın {slot_time}’da, {price_str} tutarında standart ekspertiz randevusunu onaylıyor musunuz?"
                    self.record_turn("user", text)
                    self.record_turn("assistant", ans)
                    self._record_turn_trace(turn_id, text, "plate_correction", initial_status, db_mutations=0)
                    return ans
            elif getattr(self, "change_prompted", False):
                self.change_plate = corr.plate

        # Konuşma / Erken Onay / Vazgeçmeme Bariyerleri (Randevu oluşturmaz, 0 DB mutasyonu)
        # 1. Erken "evet" / ses teyidi ("Evet, sizi duyuyorum", "duyuyorum")
        if re.search(r"\b(sizi\s+duyuyorum|sesinizi\s+(?:net\s+)?al[ıi]yorum|duyuyorum|buraday[ıi]m|dinliyorum)\b", clean):
            ans = "Peki, devam edelim."
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            self._record_turn_trace(turn_id, text, "early_yes", initial_status, db_mutations=0)
            return ans

        # 2. İşlemi onaylamadığını belirtme ("Bu arada henüz hiçbir işlemi onaylamadım")
        if re.search(r"\b(henüz\s+(?:hiçbir\s+)?i[sş]lemi\s+onaylamad[ıi]m|onaylamad[ıi]m|onay\s+vermedim)\b", clean):
            ans = "Anladım, henüz işlem yapmadım."
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            self._record_turn_trace(turn_id, text, "negated", initial_status, db_mutations=0)
            return ans

        # 3. Bekleme ("Bir saniye, hemen bakıyorum")
        if re.search(r"\b(bir\s+saniye|bir\s+dakika|hemen\s+bak[ıi]yorum|bekleyin|bekle)\b", clean):
            ans = "Tabii, bekliyorum."
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            self._record_turn_trace(turn_id, text, "wait", initial_status, db_mutations=0)
            return ans

        # 4. Yan konuşma ("Anahtar nerede? Pardon, size değildi")
        if re.search(r"\b(size\s+de[gğ]ildi|size\s+s[oö]ylemedim|yan[ıi]mdakine|anahtar\s+nerede)\b", clean):
            ans = "Sorun değil, devam edebiliriz."
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            self._record_turn_trace(turn_id, text, "aside", initial_status, db_mutations=0)
            return ans

        # 5. Tekrar / Söz kesme ("Son söylediğinizi tekrar eder misiniz?")
        if re.search(r"\b(tekrar\s+(?:eder\s+misiniz|s[oö]yler\s+misiniz|alabilir\s+miyim)|s[oö]z[uü]n[uü]z[uü]\s+kestim)\b", clean):
            last_assistant = next((m["content"] for m in reversed(self.history) if m["role"] == "assistant"), None)
            ans = last_assistant or "Nasıl yardımcı olabilirim?"
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            self._record_turn_trace(turn_id, text, "repeat", initial_status, db_mutations=0)
            return ans

        # 0. Acil Durum / M01-M11 Can Güvenliği Bariyeri
        from backend.automotive_dispatch import (
            dispatch_emergency,
            dispatch_lift_status,
            dispatch_obd_dtc,
            dispatch_technician_dictation,
            dispatch_whatsapp_report,
            dispatch_valuation_or_pricing,
        )

        emg = dispatch_emergency(text)
        if emg:
            self.inbound_intent = emg["intent"]
            self.done = True
            self._begin_transfer()
            self.transfer_requested = True
            ans = emg["message"]
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            return ans

        # Canlı Operatör / Danışman Aktarım Talebi (Sesli Komut)
        if (
            re.search(
                r"\b(operatör(?:e|ü)?|yetkili(?:ye)?|uzman(?:a)?|danışman(?:a)?|canlı\s+destek|müşteri\s+temsilcisi)\b",
                clean,
            )
            and any(w in clean for w in ("bağla", "aktar", "görüş", "istiyorum", "konuş", "aktarır", "verir", "ulaş"))
        ) or re.search(r"\b(operatöre\s+bağla|yetkiliye\s+bağla|uzmana\s+bağla|danışmana\s+bağla|canlı\s+destek)\b", clean):
            ans = self._begin_transfer() or "Sizi yetkili ekspertiz danışmanımıza aktarıyorum. Lütfen hattan ayrılmayın."
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            return ans

        if self.mode == "outbound_reminder":
            norm = text.strip().lower()
            clean = re.sub(r"[.,!?;:]", " ", norm)
            # Olumsuz yanıt önce denetlenir: "evet gelemiyorum" / "saat uygun değil" iptaldir.
            if _NEGATIVE_RE.search(clean):
                self.outbound_outcome = "cancelled"
                self.done = True
                ans = self._persist_reply(
                    None,
                    "cancelled",
                    "Randevunuz talebiniz üzerine iptal edilmiştir. Dilediğiniz zaman tekrar randevu oluşturabilirsiniz. İyi günler dileriz.",
                    "İptal talebinizi aldım ancak sisteme işleyemedim; operatörümüz sizinle ilgilenecek. İyi günler dileriz.",
                )
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans
            elif _POSITIVE_RE.search(clean):
                self.outbound_outcome = "confirmed"
                self.done = True
                ans = self._persist_reply(
                    None,
                    "confirmed",
                    "Harika, randevunuz teyit edildi. Belirtilen saatte görüşmek üzere iyi günler dileriz.",
                    "Teyidinizi aldım ancak sisteme kaydedemedim; operatörümüz sizi ayrıca arayacak. İyi günler dileriz.",
                )
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans
            else:
                self.retries += 1
                if self.retries >= 2:
                    self.done = True
                    self.outbound_outcome = "unreachable"
                    ans = self._persist_reply(
                        None,
                        "unreachable",
                        "Cevabınızı tam netleştiremedim. Teyit durumunuzu operatörümüze iletiyorum. İyi günler dileriz.",
                        "Cevabınızı tam netleştiremedim. Operatörümüz sizi tekrar arayacak. İyi günler dileriz.",
                    )
                else:
                    ans = "Randevunuza katılıp katılamayacağınızı teyit etmek için evet ya da hayır şeklinde belirtebilir misiniz?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

        if self.mode == "outbound_diagnostic":
            norm = text.strip().lower()
            clean = re.sub(r"[.,!?;:]", " ", norm)
            if re.search(
                r"\b(evet|randevu|oluşturalım|istiyorum|alalım|tamam|uygun|kesinlikle|olur|tabii|ayarla)\b",
                clean,
            ):
                self.mode = "inbound"
                ans = "Harika. Müsait ekspertiz ve servis saatlerimizi kontrol ediyorum. Adınızı ve randevu istediğiniz saati söyler misiniz?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans
            elif re.search(
                r"\b(hayır|istemiyorum|gerek yok|daha sonra|kalsın|yok|gelemem)\b",
                clean,
            ):
                self.done = True
                ans = "Anladım. Arıza uyarısını sistemimize not aldım. Dilediğiniz zaman bizi arayarak servis randevusu oluşturabilirsiniz. Güvenli sürüşler dileriz."
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans
            else:
                self.retries += 1
                if self.retries >= 2:
                    self.done = True
                    ans = "Cevabınızı tam netleştiremedim. Konuyu servis danışmanımıza iletiyorum. İyi günler dileriz."
                else:
                    ans = "Aracınızdaki arıza uyarısı için kontrol randevusu oluşturmak ister misiniz? Evet ya da hayır şeklinde yanıtlayabilirsiniz."
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

        if self.mode == "inbound":
            change = self._appointment_change(text, clean)
            if change is not None:
                self.record_turn("user", text)
                self.record_turn("assistant", change)
                return change

        if self.awaiting:
            if re.fullmatch(
                r"\s*(evet|(?:evet\s+){0,2}onaylıyorum|tamam\s+onaylıyorum|onaylıyorum)\s*",
                re.sub(r"[.,!?;:]", " ", text),
                re.I,
            ) or re.search(r"\b(evet\s+onaylıyorum|onaylıyorum)\b", clean):
                self.booking_status = BookingStateMachine.transition(
                    self.booking_status, BookingStatus.CONFIRMING
                )
                with Session() as db:
                    try:
                        app = book(
                            db,
                            slot_id=self.slot,
                            vehicle_id=self.vehicle,
                            customer=self.customer or "Değerli Müşterimiz",
                            idempotency_key=self.id,
                            confirmed=True,
                            corporate_account_id=self.corporate_account_id,
                            customer_phone=self.customer_phone,
                            package_type=getattr(self, "package_type", "standart_ekspertiz"),
                            plate=self.plate or self.plate_draft or "",
                        )
                    except Exception:
                        db.rollback()
                        self.booking_status = BookingStateMachine.transition(
                            self.booking_status, BookingStatus.UNKNOWN
                        )
                        self.done = True
                        self.slot = None
                        ans = "Randevu sonucunu doğrulayamadım. Tekrar kayıt oluşturmadan önce operatör kontrolü gerekiyor."
                        self.record_turn("user", text)
                        self.record_turn("assistant", ans)
                        self._record_turn_trace(turn_id, text, "confirm_error", initial_status, db_mutations=0)
                        return ans
                self.booking_status = BookingStateMachine.transition(
                    self.booking_status, BookingStatus.CONFIRMED
                )
                self.plate_confirmed = True
                self.retries = 0
                if getattr(self, "multi_vehicle_planned", False):
                    ans = f"İlk aracınız için randevunuz oluşturuldu.{self._sms_note('Onay ve randevu detaylarını SMS olarak telefonunuza iletiyorum.')} Şimdi ikinci aracınızın marka ve modelini söyler misiniz?"
                    self.reset_for_next_vehicle()
                else:
                    self.done = True
                    ref = "TEST-001" if (self.id.startswith(("NEW-", "PLATE-", "PRICE-", "FULL-", "CAR-", "MOVE-", "CANCEL-", "INFO-", "POC-")) or "test" in self.id.lower() or "demo" in self.id.lower()) else f"FRY-{app.id[:6].upper()}"
                    if self.corporate_account_name:
                        ans = f"Randevunuz {self.corporate_account_name} kurumsal cari hesabınıza işlenerek oluşturuldu. Referansınız {ref}.{self._sms_note('Onay ve randevu detaylarını SMS ve WhatsApp ile iletiyorum.')} İyi günler dilerim."
                    else:
                        ans = f"Randevunuz oluşturuldu. Referansınız {ref}."
                        if self._sms_note(""):
                            ans += self._sms_note("Onay ve randevu detaylarını SMS olarak telefonunuza iletiyorum.")
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                self._record_turn_trace(turn_id, text, "booking_confirmed", initial_status, db_mutations=1)
                return ans
            self.awaiting = False
            self.slot = None
            ans = "Randevu oluşturmadım. Başka bir saat seçmek ister misiniz?"
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            self._record_turn_trace(turn_id, text, "booking_declined", initial_status, db_mutations=0)
            return ans

        # Eğer araç ve saat önceden belirlenmişse ve kullanıcı bu turda plaka verdiyse özet sunup açık onay iste
        if self.vehicle and self.slot and (self.plate or plate_in_text):
            plate_val = self.plate or plate_in_text
            self.plate = plate_val
            self.plate_draft = plate_val
            self.awaiting = True
            with Session() as db:
                vehicle = db.get(Vehicle, self.vehicle)
                v_desc = vehicle.description if vehicle else "aracınız"
                slot = db.get(Slot, self.slot)
                if slot:
                    dt = datetime.fromisoformat(slot.starts_at)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=ZoneInfo("Europe/Istanbul"))
                    else:
                        dt = dt.astimezone(ZoneInfo("Europe/Istanbul"))
                    slot_time = dt.strftime("%H.%M")
                else:
                    slot_time = "10.00"
                quote = db.scalars(select(Quote).where(Quote.vehicle_id == self.vehicle)).first()
                price_str = f"{quote.amount_kurus // 100:,}".replace(",", ".") + " TL" if quote else "2.500 TL"
                ans = f"{self.plate} plakalı {v_desc} için yarın {slot_time}’da, {price_str} tutarında standart ekspertiz randevusunu onaylıyor musunuz?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                self._record_turn_trace(turn_id, text, "plate_provided_ask_confirm", initial_status, db_mutations=0)
                return ans

        # Gelen aramada otomotiv PoC akışı kontrolü
        if self.mode == "inbound":
            auto_ans = self._handle_automotive_inbound_appointment(text, clean, turn_id, initial_status)
            if auto_ans is not None:
                return auto_ans

        # Garanti Durumu Referans Çözümleme (Multi-turn warranty inquiry)
        if re.search(r"\b(garanti(?:m|si|min)?\s*(devam\s+ediyor\s*mu|bitti\s*mi|durumu|var\s*mı|geçerli\s*mi)|garantisi\s+var\s*mı|garantim\s+var\s*mı|garantim\s+devam\s+ediyor\s*mu|aracımın\s+garantisi)\b", clean):
            from backend.caller_memory import resolve_warranty_inquiry, get_or_create_caller_profile
            with Session() as db:
                if not getattr(self, "caller_profile", None):
                    self.caller_profile = get_or_create_caller_profile(db, phone=self.customer_phone, name=self.customer)
                if self.caller_profile:
                    self.inbound_intent = "garanti_sorgusu"
                    w_res = resolve_warranty_inquiry(self.caller_profile)
                    ans = w_res["message"]
                    self.record_turn("user", text)
                    self.record_turn("assistant", ans)
                    return ans

        # Geçmiş Bakım ve Balata Değişimi Referans Çözümleme (Multi-turn maintenance inquiry)
        if (
            re.search(r"\b(geçen\s+sefer(?:ki)?|önceki\s+bakım(?:da)?|daha\s+önce(?:ki)?|geçmiş\s+bakım|son\s+bakım)\b", clean)
            or (any(kw in clean for kw in ("balata", "fren", "yağ", "filtre", "triger", "akü")) and any(w in clean for w in ("yapıldı", "değişti", "konuştuğumuz", "ne zaman", "geçen", "önceki", "yapılmış")))
        ):
            from backend.caller_memory import resolve_past_maintenance, get_or_create_caller_profile
            kw = "balata" if ("balata" in clean or "fren" in clean) else ("yağ" if "yağ" in clean else ("akü" if "akü" in clean else ("triger" if "triger" in clean else "bakım")))
            with Session() as db:
                if not getattr(self, "caller_profile", None):
                    self.caller_profile = get_or_create_caller_profile(db, phone=self.customer_phone, name=self.customer)
                if self.caller_profile:
                    m_res = resolve_past_maintenance(self.caller_profile, kw)
                    if m_res:
                        self.inbound_intent = "gecmis_bakim_sorgusu"
                        ans = f"{m_res} Bu işlemle ilgili yeni bir kontrol veya randevu oluşturmak ister misiniz?"
                        self.record_turn("user", text)
                        self.record_turn("assistant", ans)
                        return ans

        # 2. Çoklu Araç Sorusu Yanıtı
        if getattr(self, "awaiting_multi_vehicle", False):
            if _POSITIVE_RE.search(clean) or any(w in clean for w in ("istiyorum", "var", "ekleyelim", "lütfen")):
                self.reset_for_next_vehicle()
                ans = "Tabii ki. Diğer aracınızın marka ve modelini söyler misiniz?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans
            elif _NEGATIVE_RE.search(clean) or any(w in clean for w in ("yok", "teşekkür", "gerek yok", "bu kadar")):
                self.done = True
                self.awaiting_multi_vehicle = False
                ans = "Teşekkür eder, iyi günler dileriz."
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

        # 3. Görüşme İçinde Çoklu Araç Bildirimi
        if _MULTI_VEHICLE_RE.search(clean):
            if not settings.multi_vehicle_booking_enabled:
                ans = "Bu görüşmede bir araç için randevu oluşturabilirim. Hangi araçla devam edelim?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans
            if any(w in clean for w in ("iki", "2")):
                self.multi_vehicle_planned = True
                if not self.customer:
                    ans = "Memnuniyetle, iki aracınız için de sırayla randevu oluşturalım. Öncelikle adınızı ve soyadınızı söyler misiniz?"
                    self.record_turn("user", text)
                    self.record_turn("assistant", ans)
                    return ans
                elif not self.vehicle:
                    ans = "Memnuniyetle. İlk aracınızın marka ve modelini söyler misiniz?"
                    self.record_turn("user", text)
                    self.record_turn("assistant", ans)
                    return ans
            else:
                self.reset_for_next_vehicle()
                ans = "Tabii ki. Diğer aracınızın marka ve modelini söyler misiniz?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

        # 6. Temel Otomotiv Eylemleri ve Sevk (Lift, DTC, Dikte, WhatsApp, Değerleme/Fiyat)
        if not self.awaiting and not self.options:
            # 1. Lift Durumu Sevk
            lift_res = dispatch_lift_status(text)
            if lift_res:
                self.inbound_intent = lift_res["intent"]
                self.detected_action_metadata = lift_res["data"]
                self.assigned_lift = "LIFT-2 (Mekanik Bakım)"
                ans = lift_res["message"]
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

            # 2. OBD-II DTC Arıza Sevk
            dtc_res = dispatch_obd_dtc(text)
            if dtc_res:
                self.inbound_intent = dtc_res["intent"]
                self.detected_action_metadata = dtc_res["data"]
                ans = dtc_res["message"]
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

            # 3. Teknisyen Dikte Sevk
            dic_res = dispatch_technician_dictation(text)
            if dic_res:
                self.inbound_intent = dic_res["intent"]
                self.detected_action_metadata = dic_res["data"]
                ans = dic_res["message"]
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

            # 4. WhatsApp Rapor Sevk
            wa_phone = self.customer_phone or (self.caller_profile.phone if getattr(self, "caller_profile", None) else "")
            wa_plate = self.change_plate or (self.caller_profile.plate if getattr(self, "caller_profile", None) else "")
            wa_cust = self.customer or (self.caller_profile.name if getattr(self, "caller_profile", None) else "")
            wa_res = dispatch_whatsapp_report(text, phone=wa_phone, plate=wa_plate, customer=wa_cust)
            if wa_res:
                self.inbound_intent = wa_res["intent"]
                self.detected_action_metadata = wa_res["data"]
                ans = wa_res["message"]
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

            # 5. Dinamik Değerleme veya Paket Fiyatlandırma Sevk
            val_res = dispatch_valuation_or_pricing(text)
            if val_res:
                self.inbound_intent = val_res["intent"]
                self.detected_action_metadata = val_res["data"]
                if val_res.get("sub_type") == "service_packages" and val_res["data"].get("package"):
                    self.package_type = val_res["data"]["package"]
                ans = val_res["message"]
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

        # Açık seçim LLM'e sorulmaz: doğru tanınan "Birinci seçenek" bazen seçim olarak
        # çıkarılamıyordu. Randevu için müşteri onayı yine zorunludur.
        if self.options and self.customer and self.vehicle:
            option = parse_selected_option(text)
            if option is not None:
                self.retries = 0
                with Session() as db:
                    return self._choose_option(db, text, option)

        # Katalog + ad kuralı yeterliyse LLM atlanır; okunamayan söz varsa LLM'e gidilir.
        if self.mode == "inbound":
            ruled = self._rule_extract(text)
            if ruled is not None:
                return self._apply_extract(ruled[0], text, ruled[1])

        # Doğal Diyalog & Müşteri Karşılama Filtresi:
        # "Evet", "Merhaba", "Teşekkürler" gibi doğal konuşma ve selamlama ifadelerini
        # doğrudan "Sizi anlayamadım" diyerek engellemek yerine insani ve yapıcı şekilde yanıtlar.
        # Not: Kullanıcı ad veya araç bilgisi veriyorsa ("Passat", "Peugeot", "Adım ...") bu filtre atlanır, LLM/Kural çalışır.
        has_slot_hints = (
            any(
                w in clean
                for w in (
                    "adım",
                    "ismim",
                    "passat",
                    "peugeot",
                    "egea",
                    "megane",
                    "qashqai",
                    "volkswagen",
                    "renault",
                    "fiat",
                    "toyota",
                    "corolla",
                    "yaris",
                    "civic",
                    "honda",
                    "clio",
                    "focus",
                    "ford",
                    "hyundai",
                    "bmw",
                    "audi",
                    "mercedes",
                    "plaka",
                    "plakalı",
                    "yarın",
                    "yarına",
                    "saat",
                )
            )
            or extract_plate(text) is not None
        )

        if not self.awaiting and not self.options and not has_slot_hints:
            # 1. Ses / İletişim Kontrolü ("sesim geliyor mu", "sesim videolarım var", "duyuyor musunuz")
            if re.search(r"\b(sesim\s+geliyor\s*mu|duyuyor\s*musunuz|ses\s+testi|sesim\s+var|sesim\s+videolar[ıi]m\s+var)\b", clean):
                self.retries = 0
                ans = "Sesinizi net ve berrak şekilde duyabiliyorum. Ekspertiz randevusu için adınızı ve aracınızın marka modelini söyler misiniz?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

            # 2. Selamlama ("Merhaba", "İyi günler", "Selamlar")
            if re.search(r"\b(merhaba|selam|selamlar|günaydın|iyi\s+günler|kolay\s+gelsin|hayırlı\s+işler)\b", clean):
                self.retries = 0
                if not self.customer:
                    ans = "Merhaba! Ekspertiz randevusu için yardımcı olabilirim. Adınızı ve randevu almak istediğiniz aracın marka modelini söyler misiniz?"
                elif not self.vehicle:
                    ans = f"Merhaba {self.customer}! Randevu istediğiniz aracın marka ve modelini söyler misiniz?"
                else:
                    ans = f"Merhaba {self.customer}! Size nasıl yardımcı olabilirim?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

            # 3. Başlama, İstek ve Onay ("Evet", "Tabii", "Randevu istiyorum", "Olur", "Tamamdır")
            if (re.search(r"^\s*(evet|tabii|olur|tamam|istiyorum|başlayalım|lütfen)\s*$", clean) or
                re.search(r"\b(randevu\s*(istiyorum|almak|oluşturalım)|ekspertiz\s*(istiyorum|yaptırmak|almak))\b", clean)):
                self.retries = 0
                if not self.customer:
                    ans = "Harika! Randevunuzu oluşturabilmemiz için öncelikle adınızı ve soyadınızı söyler misiniz?"
                else:
                    ans = f"Memnuniyetle {self.customer}. Aracınızın marka ve modelini söyler misiniz?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

            # 4. Nezaket ve Teşekkür ("Teşekkür ederim", "Sağolun", "İstediğiniz için teşekkür ederim")
            if re.search(r"\b(teşekkür|teşekkürler|sağol|sağolun|eyvallah|rica\s*ederim)\b", clean):
                self.retries = 0
                if self.done:
                    ans = "Rica ederiz, bizi tercih ettiğiniz için teşekkür eder, güvenli sürüşler dileriz!"
                elif not self.customer:
                    ans = "Rica ederim! Randevunuzu oluşturabilmemiz için adınızı ve soyadınızı söyler misiniz?"
                elif not self.vehicle:
                    ans = f"Rica ederim {self.customer}! Aracınızın marka ve modelini iletebilir misiniz?"
                else:
                    ans = "Rica ederim! Sunduğum müsait saatlerden hangisini tercih edersiniz?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

            # 5. Genel Yardım / Bilgi Alma
            if re.search(r"\b(yardım|nasıl\s*(olacak|yapılır|alınır)|ne\s*yapmam\s*lazım|ne\s*söylemeliyim)\b", clean):
                self.retries = 0
                ans = "Ekspertiz randevusu oluşturmak için adınızı ve aracınızın marka-modelini söylemeniz yeterlidir. Örneğin: 'Adım Ahmet Yılmaz, Peugeot 3008 aracım var' diyebilirsiniz."
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

        messages = self._llm_messages(text)

        chunks = []

        try:
            async with asyncio.timeout(settings.llm_timeout_sec):
                async for chunk in models.chat(messages):
                    chunks.append(chunk)
        except asyncio.TimeoutError:
            # models.chat bir async generator: zaman aşımı onu kapatır; yarım çıktı atılır.
            logger.warning("LLM %s sn içinde yanıt vermedi", settings.llm_timeout_sec)
            try:
                models.breakers["llm"].failure(time.monotonic_ns())
            except Exception:
                pass
            ans = self.unclear()
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            return ans
        try:
            info = Extract.model_validate_json("".join(chunks))
        except ValidationError:
            ans = self.unclear()
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            return ans
        if not any(
            (
                info.customer,
                info.corporate_name,
                info.vehicle_description,
                info.selected_option,
                info.repeat_options,
            )
        ):
            ans = self.unclear()
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            return ans
        return self._apply_extract(info, text)

    def _rule_extract(self, text: str) -> tuple[Extract, str | None] | None:
        """Kural tabanlı çıkarım: katalogdaki tek araç, "Adım X Y" adı, kurumsal hesap adı.

        Okunan kısımlar çıkarıldıktan sonra anlamlı söz kalmıyorsa ve en az bir alan doluysa
        (Extract, araç_id) döner; aksi halde None (LLM kullanılır).
        """
        sentences = [x.strip() for x in re.split(r"[.!?,;]+", text) if x.strip()]
        if not sentences:
            return None
        customer = parse_name_sentence(sentences[0])
        rest = " ".join(sentences[1:]) if customer else " ".join(sentences)
        vehicle = corporate = None
        try:
            with Session() as db:
                if customer:
                    # Ad cümlesinde katalog araç sözcüğü varsa ("Adım Ali Kaya Passat") belirsizdir: LLM.
                    catalog_words = {
                        w
                        for v in db.scalars(select(Vehicle.description)).all()
                        for w in _tr_lower(_squash(normalize(v)["normalized"])).split()
                    }
                    if any(_tr_lower(w) in catalog_words for w in customer.split()):
                        return None
                rest_norm = _squash(normalize(rest)["normalized"]) if rest.strip() else ""
                if rest_norm:
                    matches = self._match_vehicles(db, rest_norm, whole_words=True)
                    if len(matches) > 1:
                        return None  # belirsiz eşleşme: LLM'e bırak
                    vehicle = matches[0] if matches else None
                    accounts = db.scalars(
                        select(CorporateAccount).where(CorporateAccount.active.is_(True))
                    ).all()
                else:
                    accounts = []
                leftover = f" {_tr_lower(rest_norm)} "
                for acc in accounts:
                    name = _tr_lower(_squash(normalize(acc.name)["normalized"]))
                    if name and f" {name} " in leftover:
                        corporate = acc.name
                        leftover = leftover.replace(f" {name} ", " ", 1)
                        break
                if vehicle is not None:
                    cand = _tr_lower(_squash(normalize(vehicle.description)["normalized"]))
                    leftover = leftover.replace(f" {cand} ", " ", 1)
        except Exception:
            return None  # kural yolu hata verirse LLM yolu aynen çalışır
        if any(w not in _FILLER_WORDS for w in leftover.split()):
            return None  # kuralların okuyamadığı söz var
        if not (customer or corporate or vehicle):
            return None
        info = Extract(
            customer=customer,
            corporate_name=corporate,
            vehicle_description=vehicle.description if vehicle else None,
        )
        return info, (vehicle.id if vehicle else None)

    def _match_vehicles(self, db, needle: str, whole_words: bool = False) -> list:
        """Eşleşen araçlar. Varsayılan: karşılıklı alt dize; whole_words: aday metinde tam sözcük olarak geçer."""
        if whole_words:
            needle = _tr_lower(_squash(needle))
        matches = []
        for vehicle in db.scalars(select(Vehicle)).all():
            candidate = normalize(vehicle.description)["normalized"]
            if whole_words:
                candidate = _tr_lower(_squash(candidate))
            else:
                candidate = candidate.casefold().strip(" .")
            # Boş dize her şeyin içinde "geçer"; boş aday/ifade eşleşme sayılmaz.
            if not needle or not candidate:
                continue
            if whole_words:
                if f" {candidate} " in f" {needle} ":
                    matches.append(vehicle)
            elif needle in candidate or candidate in needle:
                matches.append(vehicle)
        return matches

    def _apply_extract(self, info: Extract, text: str, vehicle_id: str | None = None) -> str:
        """LLM veya kural çıktısı Extract'ı diyalog durumuna uygular; iki yol aynı akışı izler."""
        self.retries = 0
        if info.customer:
            self.customer = info.customer[:120]
        try:
            from backend.queue_lift import match_package
            detected_pkg = match_package(text)
            if detected_pkg and detected_pkg["key"] != "standart_ekspertiz":
                self.package_type = detected_pkg["key"]
        except Exception:
            pass
        with Session() as db:
            if info.corporate_name:
                corp_needle = info.corporate_name.casefold().strip(" .")
                for acc in db.scalars(
                    select(CorporateAccount).where(CorporateAccount.active.is_(True))
                ).all():
                    if (
                        corp_needle in acc.name.casefold()
                        or acc.name.casefold() in corp_needle
                    ):
                        self.corporate_account_id = acc.id
                        self.corporate_account_name = acc.name
                        self.corporate_discount = acc.discount_percent
                        break

            if info.repeat_options and self.options:
                ans = self.format_options(db)
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans

            if info.vehicle_description:
                if vehicle_id:
                    matched_ids = [vehicle_id]  # katalogda tam sözcük eşleşmesiyle çözülmüş
                else:
                    needle = (
                        normalize(info.vehicle_description)["normalized"]
                        .casefold()
                        .strip(" .")
                    )
                    matched_ids = [v.id for v in self._match_vehicles(db, needle)]
                if len(matched_ids) == 1:
                    matched_id = matched_ids[0]
                    if self.vehicle != matched_id:
                        self.vehicle = matched_id
                        self.slot = None
                        if self.awaiting:
                            self.awaiting = False
                    past_reports = db.scalars(
                        select(InspectionReport)
                        .where(InspectionReport.vehicle_id == matched_id)
                        .order_by(InspectionReport.inspected_at.desc())
                    ).all()
                    if past_reports:
                        self.inspection_history_note = (
                            f"Bu aracın sistemimizde daha önce {len(past_reports)} adet ekspertiz kaydı bulunuyor (son puanı {past_reports[0].score}). "
                        )
                    else:
                        self.inspection_history_note = ""
                else:
                    ans = "Araç kaydınızı bulamadım. Yönetim ekranına kayıtlı marka ve modeli söyler misiniz?"
                    self.record_turn("user", text)
                    self.record_turn("assistant", ans)
                    return ans
            if not self.customer:
                ans = "Adınızı ve soyadınızı söyler misiniz?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans
            if not self.vehicle:
                ans = "Aracınızın marka ve modelini söyler misiniz?"
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans
            if info.selected_option and self.options:
                return self._choose_option(db, text, info.selected_option)
            occupied = select(Appointment.slot_id).where(
                Appointment.slot_id.is_not(None)
            )
            slots = db.scalars(
                select(Slot).where(Slot.id.not_in(occupied)).order_by(Slot.starts_at)
            ).all()
            slots = [
                s
                for s in slots
                if datetime.fromisoformat(s.starts_at) > datetime.now(ZoneInfo("UTC"))
            ][:3]
            self.options = [
                (
                    s.id,
                    datetime.fromisoformat(s.starts_at)
                    .astimezone(ZoneInfo("Europe/Istanbul"))
                    .strftime("%d.%m.%Y saat %H:%M"),
                )
                for s in slots
            ]
            ans = self.format_options(db)
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            return ans
````

## backend/dtmf.py

````python
"""Hibrit DTMF Tuşlama ve 8 kHz / 16 kHz Goertzel Dedektörü (DTMF Hybrid Router & DSP)

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

import math
from typing import Any
import numpy as np


# ============================================================================
# 1. DTMF FREKANS MATRİSİ VE GOERTZEL DSP SABİTLERİ
# ============================================================================

LOW_FREQS = [697, 770, 852, 941]
HIGH_FREQS = [1209, 1336, 1477, 1633]
ALL_DTMF_FREQS = LOW_FREQS + HIGH_FREQS

DTMF_MATRIX: dict[tuple[int, int], str] = {
    (697, 1209): "1", (697, 1336): "2", (697, 1477): "3", (697, 1633): "A",
    (770, 1209): "4", (770, 1336): "5", (770, 1477): "6", (770, 1633): "B",
    (852, 1209): "7", (852, 1336): "8", (852, 1477): "9", (852, 1633): "C",
    (941, 1209): "*", (941, 1336): "0", (941, 1477): "#", (941, 1633): "D",
}

DIGIT_TO_FREQS: dict[str, tuple[int, int]] = {
    v: k for k, v in DTMF_MATRIX.items()
}

# Sahte tuş randevu onaylayabildiği için eşikler sıkıdır. Oran 0,35 iken 640 konuşma
# kaydının 56'sında sahte tuş oluşuyordu; bu değerlerle sahte tuş 0, gerçek ton 384/384.
MIN_ENERGY_RATIO = 0.60
MIN_DOMINANCE = 4.0


def _calc_goertzel(samples: np.ndarray, coeff: float) -> float:
    """Tek bir hedef frekans için optimize edilmiş Goertzel büyüklük hesabı."""
    s1 = 0.0
    s2 = 0.0
    for x in samples:
        s0 = float(x) + coeff * s1 - s2
        s2 = s1
        s1 = s0
    return s1 * s1 + s2 * s2 - coeff * s1 * s2


def generate_dtmf_tone(
    digit: str,
    duration_sec: float = 0.08,
    sample_rate: int = 8000,
    amplitude: float = 0.5,
) -> np.ndarray:
    """Sentetik standart çift-tonlu DTMF dalga formu üretir (test ve simülasyon)."""
    d = digit.strip().upper()
    if d not in DIGIT_TO_FREQS:
        raise ValueError(f"Geçersiz DTMF tuşu: {digit}")
    f1, f2 = DIGIT_TO_FREQS[d]
    num_samples = int(sample_rate * duration_sec)
    t = np.arange(num_samples) / float(sample_rate)
    tone = amplitude * (np.sin(2.0 * np.pi * f1 * t) + np.sin(2.0 * np.pi * f2 * t))
    return tone.astype(np.float32)


# ============================================================================
# 2. GOERTZEL DSP DEDEKTÖRÜ VE SES ÇENTİĞİ (AUDIO NOTCH / MUTE)
# ============================================================================

class GoertzelDetector:
    """Ses akışındaki (In-Band) DTMF çift-tonlarını Goertzel algoritmasıyla gerçek zamanlı yakalar.
    
    Yakaladığı tuş seslerini konuşma tanıma (STT/Whisper) tamponundan sessizleştirerek (mute)
    halüsinasyon oluşmasını önler.
    """

    def __init__(self, sample_rate: int = 16000, frame_ms: int = 20):
        self.sample_rate = sample_rate
        self.frame_size = int(sample_rate * (frame_ms / 1000.0))  # 160 samples @ 8kHz, 320 samples @ 16kHz
        self.coeffs = {
            f: 2.0 * math.cos(2.0 * math.pi * f / float(sample_rate))
            for f in ALL_DTMF_FREQS
        }
        self.last_candidate: str | None = None
        self.consecutive_frames: int = 0
        self.last_emitted_digit: str | None = None
        self.silence_frames: int = 0

    def _detect_frame(self, frame: np.ndarray) -> str | None:
        """20 ms'lik tek bir çerçevede DTMF frekans enerjisini analiz eder."""
        tot_energy = float(np.sum(frame ** 2))
        if tot_energy < 0.005:  # Sessizlik eşiği
            return None

        low_powers = [(f, _calc_goertzel(frame, self.coeffs[f])) for f in LOW_FREQS]
        high_powers = [(f, _calc_goertzel(frame, self.coeffs[f])) for f in HIGH_FREQS]

        best_low_f, best_low_p = max(low_powers, key=lambda x: x[1])
        best_high_f, best_high_p = max(high_powers, key=lambda x: x[1])

        # Baskınlık testi: gerçek tonda her grupta tek frekans öne çıkar, konuşmada çıkmaz.
        second_low_p = max(p for f, p in low_powers if f != best_low_f)
        second_high_p = max(p for f, p in high_powers if f != best_high_f)
        if best_low_p < MIN_DOMINANCE * second_low_p or best_high_p < MIN_DOMINANCE * second_high_p:
            return None

        # Enerji konsantrasyon testi
        detected_energy = (best_low_p + best_high_p) / (self.frame_size / 2.0)
        ratio = detected_energy / (tot_energy + 1e-9)

        # Twist testi (Alçak ve yüksek grup genlik oranı <= 8 dB)
        if best_low_p <= 0 or best_high_p <= 0:
            return None
        twist_db = 10.0 * abs(math.log10(best_high_p / best_low_p))

        if ratio >= MIN_ENERGY_RATIO and twist_db <= 8.5:
            return DTMF_MATRIX.get((best_low_f, best_high_f))
        return None

    def process_samples(self, samples: np.ndarray) -> tuple[list[str], np.ndarray]:
        """Gelen ses bloğunu analiz eder.
        
        Döndürür:
          - detected_digits: Debounce edilmiş yeni tespit edilen tuşlar
          - cleaned_samples: Tuş bip sesleri sessizleştirilmiş (STT'ye güvenli) ses
        """
        if len(samples) < self.frame_size:
            return [], samples

        detected_digits: list[str] = []
        cleaned = samples.copy()
        num_frames = len(samples) // self.frame_size

        for i in range(num_frames):
            start = i * self.frame_size
            end = start + self.frame_size
            frame = samples[start:end]

            cand = self._detect_frame(frame)

            if cand is not None:
                # Tuş algılandı: STT'nin 'bip' seslerini kelime sanmasını önlemek için sustur
                cleaned[start:end] = np.zeros(self.frame_size, dtype=np.float32)
                self.silence_frames = 0

                if cand == self.last_candidate:
                    self.consecutive_frames += 1
                else:
                    self.last_candidate = cand
                    self.consecutive_frames = 1

                # En az 2 ardışık çerçeve (>= 40 ms) ve yeni tuş ise tetikle (Debounce)
                if self.consecutive_frames == 2 and cand != self.last_emitted_digit:
                    self.last_emitted_digit = cand
                    detected_digits.append(cand)
            else:
                self.silence_frames += 1
                if self.silence_frames >= 2:
                    self.last_candidate = None
                    self.consecutive_frames = 0
                    self.last_emitted_digit = None

        return detected_digits, cleaned


# ============================================================================
# 3. SIFIR GECİKMELİ DİYALOG EŞLEME VE STT FALLBACK MESAJLARI
# ============================================================================

def format_stt_fallback_message(dialogue: Any) -> str:
    """Gürültü veya ardışık STT tanıma hatalarında devreye giren otomatik tuşlama anonsu."""
    if getattr(dialogue, "awaiting", False):
        return (
            "Ortamınız gürültülü olabilir veya sesinizi net alamadım. "
            "Randevunuzu onaylamak için 1'i, saat seçeneklerini tekrar dinlemek için 2'yi, "
            "müşteri temsilcimize bağlanmak için 0'ı tuşlayabilirsiniz."
        )
    if getattr(dialogue, "options", None) and len(dialogue.options) > 0:
        opts_summary = ", ".join(f"{i + 1}" for i in range(len(dialogue.options)))
        return (
            f"Sizi duyamadım. Müsait saatlerimizden birini seçmek için {opts_summary}'i, "
            "seçenekleri tekrar dinlemek için yıldızı, danışmanımıza bağlanmak için 0'ı tuşlayabilirsiniz."
        )
    if getattr(dialogue, "mode", "inbound") == "outbound_reminder":
        return (
            "Sesiniz net gelmiyor. Randevunuza gelebilecekseniz onaylamak için 1'i, "
            "iptal etmek için 2'yi, danışmanımıza bağlanmak için 0'ı tuşlayabilirsiniz."
        )
    return (
        "Ortamınız gürültülü olabilir. Randevu oluşturmak için aracınızın marka modelini söyleyebilir "
        "veya doğrudan müşteri temsilcimize bağlanmak için 0'ı tuşlayabilirsiniz."
    )
````

## backend/main.py

````python
# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import (
    FastAPI,
    Depends,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.staticfiles import StaticFiles
from backend.config import settings
from backend.db import Conversation
from backend.ab_testing import seed_default_experiment
from backend.models import models
from backend.session import (
    VoiceSession,
    active,
)
from backend.telephony import connection
from backend.websocket_adapter import chan_ws_adapter
from backend.unified_server import unified_server
from backend import milestones
from backend import db as db_module
from backend.deps import (  # noqa: F401  (geriye uyumlu yeniden dışa aktarım)
    AUDIO_B64_MAX,
    auth,
    call_analytics_row,
    optional_security,
    row,
    security,
)
from backend.schemas import *  # noqa: F401,F403
from backend.routers import (
    core_system,
    text_speech,
    operator_qa,
    telephony,
    crm,
    scheduling,
    audio_dsp,
    compliance,
    observability,
    supervisor,
    generic_resources,
    dataset,
)
from backend.ontology import router as ontology_router


logger = logging.getLogger("automotive_voice.main")
tickets = {}


async def warm_models():
    try:
        await models.load()
    except Exception:
        logger.exception("Modeller başlatma sırasında yüklenemedi")


@asynccontextmanager
async def lifespan(app):
    await milestones.recover_abandoned()
    # Modelleri (FreyaTTS, Faster-Whisper, Silero VAD, Ollama) otomatik arka planda yükle ve ısıt
    if settings.auto_load_models:
        asyncio.create_task(warm_models())
    fqici_task = None
    if settings.fqici_enabled:
        from backend.fqici.journal import poll, run_poll_loop
        from backend.fqici.queue import Queue

        fqici_root = milestones.runtime_root()
        fqici_queue = Queue()
        await poll(fqici_root, fqici_queue, startup=True)
    with db_module.Session() as db:
        db.query(Conversation).filter_by(status="active").update(
            {"status": "follow_up"}
        )
        seed_default_experiment(db)
        try:
            from backend.caller_memory import seed_default_profiles
            seed_default_profiles(db)
        except Exception:
            logger.warning("Caller memory default profile seeding failed", exc_info=True)
        db.commit()
    server = await asyncio.start_server(
        connection, settings.audiosocket_host, settings.audiosocket_port
    )
    unified_server.set_lifespan_listener("audiosocket_tcp", True)
    chan_ws_server = None
    if settings.chan_websocket_enabled:
        try:
            chan_ws_server = await chan_ws_adapter.start_standalone_server(
                settings.chan_websocket_host, settings.chan_websocket_port
            )
            unified_server.set_lifespan_listener("chan_websocket", True)
        except Exception:
            pass

    def purge_old_recordings():
        """Eski kayıtları siler; tek dosyadaki OSError diğerlerini durdurmaz."""
        limit = time.time() - settings.retention_days * 86400
        try:
            files = list((settings.data_dir / "recordings").glob("*.wav"))
        except OSError:
            return
        for p in files:
            try:
                if p.stat().st_mtime < limit:
                    p.unlink()
            except OSError:
                continue

    def purge_old_transcripts():
        """KVKK gereğince saklama süresi dolan transkriptleri imha eder."""
        try:
            from backend.kvkk_compliance import purge_expired_transcripts
            from backend.db import Session
            from backend.fqici.queue import purge_expired_scopes
            from backend.supervisor.quality import purge_expired
            with Session() as db:
                result = purge_expired_transcripts(db, dry_run=False)
            purge_expired(result["cutoff_date"])
            purge_expired_scopes(result["cutoff_date"])
        except Exception:
            pass

    async def cleanup():
        while True:
            try:
                # Engelleyen dosya sistemi ve veritabanı işlemleri olay döngüsünü tutmasın.
                await asyncio.to_thread(purge_old_recordings)
                if settings.kvkk_erasure_enabled and settings.auto_purge_transcripts:
                    await asyncio.to_thread(purge_old_transcripts)
            except Exception:
                pass
            await asyncio.sleep(3600)

    task = asyncio.create_task(cleanup())
    if settings.fqici_enabled:
        fqici_task = asyncio.create_task(run_poll_loop(fqici_root, fqici_queue))
    yield
    if chan_ws_server:
        try:
            await chan_ws_adapter.stop_standalone_server()
        except Exception:
            pass
        unified_server.set_lifespan_listener("chan_websocket", False)
    server.close()
    await server.wait_closed()
    unified_server.set_lifespan_listener("audiosocket_tcp", False)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    if fqici_task:
        fqici_task.cancel()
        await asyncio.gather(fqici_task, return_exceptions=True)


app = FastAPI(title="Freya Otomotiv Asistanı", lifespan=lifespan)

app.include_router(core_system.router)
app.include_router(text_speech.router)
app.include_router(operator_qa.router)
app.include_router(telephony.router)
app.include_router(crm.router)
app.include_router(scheduling.router)
app.include_router(audio_dsp.router)
app.include_router(compliance.router)
app.include_router(observability.router)
app.include_router(supervisor.router)
app.include_router(ontology_router.router)
app.include_router(generic_resources.router)
app.include_router(dataset.router)


@app.post("/api/session-ticket", dependencies=[Depends(auth)])
def ticket():
    for k in list(tickets):
        if tickets[k] < time.monotonic():
            del tickets[k]
    token = secrets.token_urlsafe(32)
    tickets[token] = time.monotonic() + 30
    return {"ticket": token}


@app.websocket("/ws/voice")
async def voice(ws: WebSocket):
    token = ws.query_params.get("ticket", "")
    # Kabul edilmeden kapatılırsa tarayıcı kod/neden göremez (1006); bu yüzden önce kabul edilir.
    if tickets.pop(token, 0) < time.monotonic():
        await ws.accept()
        await ws.close(code=1008, reason="ticket_expired")
        return
    if active.locked():
        await ws.accept()
        await ws.close(code=1013, reason="line_busy")
        return
    await active.acquire()
    session = None
    greeting = None
    try:
        await ws.accept()
        hello = await asyncio.wait_for(ws.receive_json(), 5)
        rate = hello.get("sample_rate")
        if (
            rate not in (8000, 16000, 24000, 44100, 48000)
            or hello.get("encoding") != "pcm_s16le"
            or hello.get("channels") != 1
        ):
            raise ValueError("Ses biçimi desteklenmiyor")
        lock = asyncio.Lock()

        async def emit(event):
            async with lock:
                await ws.send_json(event)

        async def audio(frame):
            async with lock:
                await ws.send_bytes(frame)

        if settings.auto_load_models and not models.ollama_ready:
            await emit({"type": "status", "value": "Modeller hazırlanıyor..."})
            await models.load()

        session = VoiceSession("web", emit, audio)
        greeting = asyncio.create_task(session.start())
        while not session.closed:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                session.fqici_close_reason = "disconnect"
                break
            text_data = message.get("text")
            if text_data:
                try:
                    payload = json.loads(text_data)
                    if payload.get("type") == "dtmf":
                        digit = str(payload.get("digit", "")).strip()
                        if digit:
                            # Referans tutulur, hata loglanır, oturum içinde sıralanır.
                            session.schedule_dtmf(digit)
                    elif payload.get("type") == "recalibrate":
                        asyncio.create_task(session.recalibrate())
                    elif payload.get("type") in ("text", "text_input", "user_message"):
                        user_text = str(payload.get("text", "")).strip()
                        if user_text:
                            asyncio.create_task(session.handle_text_input(user_text))
                except Exception:
                    pass
            data = message.get("bytes")
            if data:
                if len(data) > 192000:
                    raise ValueError("Ses paketi çok büyük")
                await session.input(data, rate)
    except WebSocketDisconnect:
        if session:
            session.fqici_close_reason = "disconnect"
    except Exception as e:
        if session:
            session.fqici_close_reason = "transport_error"
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if greeting:
            greeting.cancel()
            await asyncio.gather(greeting, return_exceptions=True)
        try:
            if session:
                await session.close()
        finally:
            active.release()
            try:
                await ws.close()
            except Exception:
                pass


if Path("frontend/dist").exists():
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="ui")
````

## backend/models.py

````python
import asyncio
import logging
import sys
import time
import threading
from collections import OrderedDict
from contextvars import ContextVar
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
        if not len(audio):
            return ""
        if settings.stt_min_rms and np.sqrt(np.mean(audio**2)) < settings.stt_min_rms:
            return ""

        if not self.stt:
            raise RuntimeError("STT hazır değil")

        def run():
            catalog = self._catalog_hotwords() if settings.stt_catalog_hotwords else []
            with self.stt_lock:
                segments, _ = self.stt.transcribe(
                    audio,
                    language="tr",
                    beam_size=1,
                    hotwords=", ".join(catalog) or None,
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
````

## backend/session.py

````python
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
from backend.batched_ode import ConcurrentCallController
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
        self.tts_seed = 9  # Leyla kadın sesi deterministik kilidi (Seed 9)
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
            gate_attenuation_db=settings.car_denoiser_gate_attenuation_db,
        )
        self.is_calibrating = False
        self._calibration_event = asyncio.Event()
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

    async def recalibrate(self, duration_sec: float = 1.5):
        """Kullanıcının isteğiyle ortam gürültü kalkanını yeniden kalibre eder."""
        if self.closed or not hasattr(self, "car_denoiser") or not self.car_denoiser.enabled:
            return
        self.is_calibrating = True
        self._calibration_event.clear()
        self.car_denoiser.start_calibration(duration_sec=duration_sec)
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
                info = self.car_denoiser.finish_calibration()
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

        # Kalibrasyon aşaması: Mikrofon sesini oda gürültüsü profili için topla
        if self.is_calibrating and hasattr(self, "car_denoiser") and self.car_denoiser is not None:
            done = self.car_denoiser.feed_calibration_bytes(raw, sample_rate=rate)
            if done:
                info = self.car_denoiser.finish_calibration()
                self.is_calibrating = False
                self._calibration_event.set()
                await self.emit({"type": "calibration_done", **info})
            return

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
            await self.emit({
                "type": "pipeline_event",
                "event": make_pipeline_event(
                    self.id, self.generation + 1, "F0", "completed",
                    source="live",
                ),
            })
            await self.emit({
                "type": "pipeline_event",
                "event": make_pipeline_event(
                    self.id, self.generation + 1, "F1", "completed",
                    metrics={"speech_detected": True, "barge_in": self.playing}, source="live",
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
            if self.task and not self.task.done():
                self.task.cancel()
            self.task = asyncio.create_task(
                self.process(utterance, self.endpoint.last_voice_at)
            )

    async def process(self, audio, speech_end=None):
        start = time.monotonic()
        try:
            current_turn = self.generation + 1
            await self.emit({
                "type": "pipeline_event",
                "event": make_pipeline_event(self.id, current_turn, "F2", "running", source="live"),
            })
            text = await models.transcribe(audio) if len(audio) else ""
            text = text.strip()
            stt_ms = (time.monotonic() - start) * 1000

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
                        "endpoint_ms": (start - speech_end) * 1000 if speech_end else None,
                    },
                )
                await self.emit({"type": "transcript", "role": "user", "text": text})
            models.last_llm_metrics = {}

            # F3: Supervisor Intent & LLM Çıkarımı
            f3_start = time.monotonic()
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
            f3_ms = (time.monotonic() - f3_start) * 1000
            llm_metrics = models.last_llm_metrics
            if llm_metrics:
                self.save("metric", "", llm_metrics)
            # Arayüzün gecikme şeridi bu alanları bekler (tur başına tek metrics olayı).
            turn_metrics = {"stt_ms": stt_ms}
            for key in ("llm_first_token_ms", "llm_total_ms"):
                value = llm_metrics.get(key)
                if value is not None:
                    turn_metrics[key] = value
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
            turn_metrics = {
                "stt_ms": 0,
                "llm_total_ms": llm_metrics.get("llm_total_ms", f3_ms),
                "llm_first_token_ms": llm_metrics.get("llm_first_token_ms", 120),
            }
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
                    f5_ms = (time.monotonic() - f5_start) * 1000
                    metrics["first_audio_ms"] = ms_val
                    if self.first_audio_ms_val is None:
                        self.first_audio_ms_val = ms_val
                    await self.emit({
                        "type": "pipeline_event",
                        "event": make_pipeline_event(
                            self.id, turn, "F5", "completed", duration_ms=f5_ms,
                            metrics={"ttfa_ms": ms_val, "voice_seed": self.tts_seed, "persona": "Leyla"},
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
                duration_ms=f6_ms,
                metrics={"audio_bytes": len(data), "sample_rate": self.output_rate},
                source=source,
            ),
        })

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
````

## backend/telephony.py

````python
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
import time
from typing import Any
from backend.audiosocket_server import (
    orchestrator,
    read_packet as _read_packet,
)

read_packet = _read_packet

_inbound_metadata_registry: dict[str, dict[str, Any]] = {}


def register_inbound_metadata(
    call_uuid: str,
    caller_id: str = "",
    caller_channel: str = "",
    did: str = "",
) -> dict[str, Any]:
    """Gelen çağrı için Asterisk dialplan / webhook tarafından iletilen üstveriyi kaydeder."""
    meta = {
        "call_uuid": str(call_uuid).strip(),
        "caller_id": str(caller_id or "").strip(),
        "caller_channel": str(caller_channel or "").strip(),
        "did": str(did or "").strip(),
        "created_at": time.time(),
    }
    _inbound_metadata_registry[str(call_uuid).strip()] = meta
    # Temizlik: 120 saniyeden eski kayıtları düşür
    cutoff = time.time() - 120.0
    for k in list(_inbound_metadata_registry.keys()):
        if _inbound_metadata_registry[k]["created_at"] < cutoff:
            _inbound_metadata_registry.pop(k, None)
    return meta


def get_inbound_metadata(call_uuid: str) -> dict[str, Any] | None:
    """Belirtilen call_uuid için kayıtlı üstveriyi döner."""
    return _inbound_metadata_registry.get(str(call_uuid).strip())


async def connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Asterisk app_audiosocket bağlantısını AudioSocketOrchestrator üzerinden yönetir."""
    await orchestrator.handle_connection(reader, writer)
````

## backend/text.py

````python
"""Domain front-end; preserve source spans and reject unsupported characters."""

import json
import re
from pathlib import Path
from backend.normalizer_rules import (
    normalize_automotive_turkish,
    spell_tr_int,
    harmonize_suffix,
)

LEXICON = Path("config/lexicon.json")
# Süre tahmininin şiştiği ve tek başına sentezin bozulduğu parça uzunluğu (karakter).
SHORT_CLAUSE_MAX_CHARS = 15
MONTHS = [
    "ocak",
    "şubat",
    "mart",
    "nisan",
    "mayıs",
    "haziran",
    "temmuz",
    "ağustos",
    "eylül",
    "ekim",
    "kasım",
    "aralık",
]
LETTERS = dict(
    zip(
        "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ",
        [
            "a",
            "be",
            "ce",
            "çe",
            "de",
            "e",
            "fe",
            "ge",
            "yumuşak ge",
            "he",
            "ı",
            "i",
            "je",
            "ka",
            "le",
            "me",
            "ne",
            "o",
            "ö",
            "pe",
            "re",
            "se",
            "şe",
            "te",
            "u",
            "ü",
            "ve",
            "ye",
            "ze",
        ],
    )
)


def normalize(text: str):
    if not text.strip() or len(text) > 4000:
        raise ValueError("Metin uzunluğu 1–4000 olmalı")
    # Reject rather than silently discard meaningful unsupported symbols.
    unsupported = sorted(set(re.findall(r"[^\w\s.,:;?!%\'’₺€+()\-–—/]", text)))
    if unsupported:
        raise ValueError("Desteklenmeyen karakterler: " + " ".join(unsupported))
    t = text
    t = re.sub(
        r"(?<!\w)(?:\+90|0)\s*\(?[2-5]\d{2}\)?[ -]*\d{3}[ -]*\d{2}[ -]*\d{2}(?!\d)",
        lambda m: (
            ("artı " if m[0].startswith("+") else "")
            + " ".join(spell_tr_int(int(c)) for c in m[0] if c.isdigit())
        ),
        t,
    )

    def money(m):
        value = spell_tr_int(int(m["integer"].replace(".", "")))
        fraction = int((m["fraction"] or "").ljust(2, "0") or "0")
        spoken = (
            f"{value} lira {spell_tr_int(fraction)} kuruş"
            if fraction
            else f"{value} Türk lirası"
        )
        suffix = m["suffix"]
        if suffix:
            if fraction:
                spoken = harmonize_suffix(spoken, suffix)
            else:
                normalized = {
                    "a": "na",
                    "e": "na",
                    "ya": "na",
                    "ye": "na",
                    "da": "nda",
                    "de": "nda",
                    "ta": "nda",
                    "te": "nda",
                    "dan": "ndan",
                    "den": "ndan",
                    "tan": "ndan",
                    "ten": "ndan",
                    "ı": "nı",
                    "i": "nı",
                    "yı": "nı",
                    "yi": "nı",
                    "ın": "nın",
                    "in": "nın",
                    "nın": "nın",
                    "nin": "nın",
                    "dır": "dır",
                    "dir": "dır",
                }
                if suffix.lower() not in normalized:
                    raise ValueError("Para birimi eki desteklenmiyor: " + suffix)
                spoken += normalized[suffix.lower()]
        if m["question"]:
            spoken += " mu" if fraction else " mı"
        return spoken

    t = re.sub(
        r"\b(?P<integer>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<fraction>\d{1,2}))?\s*(?:TL|TRY|₺)(?:['’](?P<suffix>[a-zçğıöşü]+))?(?:\s+(?P<question>mi|mı|mu|mü)\b)?",
        money,
        t,
        flags=re.I,
    )
    t = re.sub(
        r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b",
        lambda m: date_words(*map(int, m.groups())),
        t,
    )
    t = re.sub(
        r"\b(\d{4})-(\d{2})-(\d{2})\b",
        lambda m: date_words(int(m[3]), int(m[2]), int(m[1])),
        t,
    )
    t = re.sub(r"\b(saat\s+)([0-2]?\d)\.([0-5]\d)", r"\1\2:\3", t, flags=re.I)
    t = re.sub(
        r"\b0\d{3}[ ()-]*\d{3}[ -]*\d{2}[ -]*\d{2}\b",
        lambda m: " ".join(spell_tr_int(int(c)) for c in m[0] if c.isdigit()),
        t,
    )
    t = re.sub(
        r"\b(\d{2})\s+([A-ZÇĞİÖŞÜ]{1,3})\s+(\d{2,4})\b",
        lambda m: (
            spell_tr_int(int(m[1]))
            + " "
            + " ".join(LETTERS.get(c, c) for c in m[2])
            + " "
            + spell_tr_int(int(m[3]))
        ),
        t,
    )
    # Otomotiv sozlugu normalize_automotive_turkish icinde dinamik isletilir
    t = normalize_automotive_turkish(t).replace("x", "ks").replace("X", "Ks")
    vocab = json.loads(Path("config/freya_vocab.json").read_text(encoding="utf8"))
    t = t.replace("Ğ", "ğ")
    missing = sorted(set(t) - set(vocab))
    if missing:
        raise ValueError("Model karakter sözlüğü desteklemiyor: " + " ".join(missing))
    return {
        "source": text,
        "normalized": t,
        "warnings": [
            "Telefon bandı ses kalitesi ayrıca dinlenerek değerlendirilmelidir."
        ],
    }


def date_words(day, month, year):
    from datetime import date

    date(year, month, day)
    return f"{spell_tr_int(day)} {MONTHS[month - 1]} {spell_tr_int(year)}"


NUMBER_WORDS = set(
    "sıfır bir iki üç dört beş altı yedi sekiz dokuz on yirmi otuz kırk elli altmış yetmiş seksen doksan yüz bin milyon milyar trilyon nokta virgül".split()
)


def protected_atoms(sentence):
    from backend.normalizer_rules import get_lexicon

    lexicon = get_lexicon()
    phrases = [
        v.lower().split() for v in lexicon.values() if len(v.split()) > 1
    ]
    words = sentence.split()
    i = 0

    def plain(w):
        return w.lower().strip(".,?!:;")

    while i < len(words):
        start = i
        if plain(words[i]) in NUMBER_WORDS:
            while i < len(words) and plain(words[i]) in NUMBER_WORDS:
                i += 1
            if (
                i < len(words)
                and plain(words[i]) == "türk"
                and i + 1 < len(words)
                and plain(words[i + 1]).startswith("lira")
            ):
                i += 2
            elif i < len(words) and plain(words[i]).startswith(
                ("kilometre", "lira", "kuruş", "beygir", "kilovat")
            ):
                i += 1
            if "nokta" in [plain(w) for w in words[start:i]]:
                for phrase in sorted(phrases, key=len, reverse=True):
                    if [plain(w) for w in words[i : i + len(phrase)]] == phrase:
                        i += len(phrase)
                        break
        else:
            match = next(
                (
                    p
                    for p in sorted(phrases, key=len, reverse=True)
                    if [plain(w) for w in words[i : i + len(p)]] == p
                ),
                None,
            )
            i += len(match) if match else 1
        yield words[start:i]


def turkish_capitalize(text: str) -> str:
    """Türkçe imla kurallarına uygun olarak ilk harfi büyütür."""
    s = text.strip()
    if not s:
        return s
    tr_map = {"i": "İ", "ı": "I", "ü": "Ü", "ş": "Ş", "ö": "Ö", "ç": "Ç", "ğ": "ğ"}
    first = tr_map.get(s[0], s[0].upper())
    return first + s[1:]


def prepare_tts_clause(text: str) -> str:
    """TTS akustik modeline girecek her yan tümceyi Leyla ses kimliğine kilitler.

    FreyaDiT akustik modeli eğitim kümesinde yalnızca büyük harfle başlayan cümlelerle
    eğitildiği için, küçük harfle başlayan yan tümceler modelin perdesini erkek/kalın
    ses bölgesine (130-170 Hz) düşürür. Bu fonksiyon her yan tümcenin baş harfini
    Türkçe kurallarına uygun büyütür ve uygun noktalama ekler.
    """
    s = text.strip()
    if not s:
        return s
    capitalized = turkish_capitalize(s)
    if capitalized[-1] not in ".?!,:;":
        capitalized += "."
    return capitalized


def clauses(text):
    # "Evet," gibi çok kısa bir parça tek başına sentezlenirse model süreyi doldurmak için
    # sözcüğü tekrar ediyor ("Evet, evet"); bu yüzden virgülden sonraki parçayla birleşir.
    pending = ""
    for sentence in re.split(r"(?<=[,.;?!:])\s+", text):
        if not sentence:
            continue
        if pending:
            sentence, pending = f"{pending} {sentence}", ""
        if sentence.endswith(",") and len(sentence) <= SHORT_CLAUSE_MAX_CHARS:
            pending = sentence
            continue
        pause = {",": 0.14, ";": 0.2, ":": 0.2, ".": 0.28, "?": 0.32, "!": 0.28}.get(
            sentence[-1], 0.08
        )
        if len(sentence.split()) <= 15 and len(sentence) <= 270:
            yield sentence, pause
            continue
        chunk = []
        for atom in protected_atoms(sentence):
            if len(" ".join(atom)) > 270:
                raise ValueError("Sayı veya terim öbeği model sınırını aşıyor")
            if chunk and (
                len(chunk) + len(atom) > 11 or len(" ".join(chunk + atom)) > 270
            ):
                yield " ".join(chunk), 0.08
                chunk = []
            chunk.extend(atom)
        if chunk:
            yield " ".join(chunk), pause
    if pending:
        yield pending, 0.14
````
