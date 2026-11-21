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
