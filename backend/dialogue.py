import asyncio
import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
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


def extract_plate(text: str) -> str | None:
    """Metin içindeki Türkiye araç plakasını (34 ABC 123, 06 ANK 99) çıkarır."""
    m = re.search(
        r"\b(0[1-9]|[1-7][0-9]|8[01])\s*([a-zA-ZçğıöşüÇĞİÖŞÜ]{1,3})\s*(\d{2,4})\b",
        text,
    )
    if m:
        return f"{m.group(1)} {m.group(2).upper()} {m.group(3)}"
    return None


def _find_active_appointment(
    db,
    customer_phone: str = "",
    plate: str = "",
    customer_name: str = "",
) -> Appointment | None:
    """Telefon numarası, plaka veya müşteri adı ile aktif randevuyu bulur."""
    apps = (
        db.scalars(
            select(Appointment)
            .where(Appointment.status.in_(["confirmed", "pending"]))
            .order_by(Appointment.created_at.desc())
        )
        .all()
    )
    # 1. Telefon ile
    if customer_phone:
        clean_target = "".join(c for c in customer_phone if c.isdigit())
        if len(clean_target) >= 7:
            for app in apps:
                app_p = "".join(c for c in (app.customer_phone or "") if c.isdigit())
                if app_p and (clean_target.endswith(app_p[-10:]) or app_p.endswith(clean_target[-10:])):
                    return app
                cust_p = "".join(c for c in (app.customer or "") if c.isdigit())
                if cust_p and (clean_target.endswith(cust_p[-10:]) or cust_p.endswith(clean_target[-10:])):
                    return app

    # 2. Plaka ile
    if plate:
        norm_plate = re.sub(r"\s+", "", plate).upper()
        for app in apps:
            if app.vehicle_id:
                v = db.get(Vehicle, app.vehicle_id)
                if v and v.plate and re.sub(r"\s+", "", v.plate).upper() == norm_plate:
                    return app

    # 3. İsim ile
    if customer_name and len(customer_name.strip()) >= 3:
        target_name = customer_name.strip().casefold()
        for app in apps:
            if target_name in (app.customer or "").casefold():
                return app

    return None


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
        self.history: list[dict[str, str]] = []
        self.max_history_turns = max_history_turns
        self.awaiting_multi_vehicle: bool = False
        self.multi_vehicle_planned: bool = False
        self.awaiting_cancel_confirmation: bool = False
        self.inbound_intent: str | None = None
        self.target_appointment_id: str | None = None

    def reset_for_next_vehicle(self):
        """Aynı müşterinin ikinci veya sonraki aracı için randevu durumunu sıfırlar."""
        self.vehicle = None
        self.slot = None
        self.options = []
        self.booking_status = BookingStatus.IDLE
        self.package_type = "standart_ekspertiz"
        self.awaiting_multi_vehicle = False
        self.awaiting_cancel_confirmation = False
        self.inbound_intent = None
        self.target_appointment_id = None
        self.done = False

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

    def record_callback_request(self, db=None, *, reason="AMI bağlı değil") -> None:
        """Aktarım yapılamadığında görüşmeyi 'follow_up' işaretleyip operatör notu ekler."""
        try:
            if db is None:
                with Session() as own:
                    self.record_callback_request(own, reason=reason)
                return
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
        except Exception:
            logger.exception("Geri arama kaydı oluşturulamadı: %s", self.id)

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

        # İptal Onayı Beklenirken Tuşlama
        if getattr(self, "awaiting_cancel_confirmation", False):
            if d == "1":
                app = db.get(Appointment, self.target_appointment_id) if self.target_appointment_id else None
                if app:
                    cancel_appointment(db, app)
                    try:
                        from backend.notifications import queue_cancellation_notification
                        queue_cancellation_notification(db, app)
                    except Exception:
                        pass
                self.done = True
                self.awaiting_cancel_confirmation = False
                ans = "1'i tuşladınız. Randevunuz talebiniz üzerine iptal edilmiştir. İyi günler dileriz."
                self.record_turn("user", f"[DTMF: {d}]")
                self.record_turn("assistant", ans)
                return ans
            elif d == "2":
                self.awaiting_cancel_confirmation = False
                self.target_appointment_id = None
                ans = "2'yi tuşladınız. İptal işlemi yapılmadı, mevcut randevunuz aynen geçerlidir."
                self.record_turn("user", f"[DTMF: {d}]")
                self.record_turn("assistant", ans)
                return ans

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

    async def answer(self, text):
        if not text.strip():
            ans = self.unclear()
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            return ans

        norm = _tr_lower(text.strip())
        clean = re.sub(r"[.,!?;:]", " ", norm)

        phone_in_text = extract_phone_number(text)
        if phone_in_text:
            self.customer_phone = phone_in_text

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

        # 1. İptal Onayı Beklenirken Sesli Yanıt
        if getattr(self, "awaiting_cancel_confirmation", False):
            if _POSITIVE_RE.search(clean) or re.search(r"\b(iptal\s*(?:et|edin|edilsin|istiyorum))\b", clean):
                with Session() as db:
                    app = db.get(Appointment, self.target_appointment_id) if self.target_appointment_id else None
                    if app:
                        cancel_appointment(db, app)
                        try:
                            from backend.notifications import queue_cancellation_notification
                            queue_cancellation_notification(db, app)
                        except Exception:
                            pass
                self.done = True
                self.awaiting_cancel_confirmation = False
                ans = f"Randevunuz başarıyla iptal edilmiştir.{self._sms_note('İptal onayını telefonunuza SMS olarak ilettim.')} Dilediğiniz zaman tekrar randevu oluşturabilirsiniz. İyi günler dileriz."
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans
            elif _NEGATIVE_RE.search(clean) or "kalsın" in clean or "vazgeçtim" in clean:
                self.awaiting_cancel_confirmation = False
                self.target_appointment_id = None
                ans = "İptal işlemi gerçekleştirilmedi, mevcut randevunuz geçerlidir. Size başka bir konuda yardımcı olabilir miyim?"
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

        # 4. İptal veya Değişiklik İçin Telefon/Plaka Belirtildiğinde
        if self.inbound_intent in ("cancel", "reschedule"):
            p_in = extract_phone_number(text) or self.customer_phone
            pl_in = extract_plate(text)
            with Session() as db:
                target_app = _find_active_appointment(db, customer_phone=p_in, plate=pl_in or "")
                if target_app:
                    act_intent = self.inbound_intent
                    self.inbound_intent = None
                    v = db.get(Vehicle, target_app.vehicle_id) if target_app.vehicle_id else None
                    v_desc = v.description if v else (v.plate if v else "aracınız")
                    if act_intent == "cancel":
                        self.target_appointment_id = target_app.id
                        self.awaiting_cancel_confirmation = True
                        s = db.get(Slot, target_app.slot_id) if target_app.slot_id else None
                        s_time = datetime.fromisoformat(s.starts_at).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y saat %H:%M") if s else "belirtilen"
                        ans = f"Sayın {target_app.customer}, {v_desc} aracınız için {s_time} tarihindeki randevunuzu iptal etmek istediğinizi onaylıyor musunuz? Onaylamak için 'evet onaylıyorum' diyebilirsiniz."
                        self.record_turn("user", text)
                        self.record_turn("assistant", ans)
                        return ans
                    else:
                        cancel_appointment(db, target_app, commit=True)
                        self.customer = target_app.customer
                        self.vehicle = target_app.vehicle_id
                        self.customer_phone = target_app.customer_phone or self.customer_phone
                        occupied = select(Appointment.slot_id).where(Appointment.slot_id.is_not(None))
                        slots = db.scalars(select(Slot).where(Slot.id.not_in(occupied)).order_by(Slot.starts_at)).all()
                        slots = [s for s in slots if datetime.fromisoformat(s.starts_at) > datetime.now(ZoneInfo("UTC"))][:3]
                        self.options = [(s.id, datetime.fromisoformat(s.starts_at).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y saat %H:%M")) for s in slots]
                        ans = f"Sayın {target_app.customer}, {v_desc} aracınızın mevcut randevusunu iptal ettim. Yeni randevunuz için seçeneklerimiz: {self.format_options(db)}"
                        self.record_turn("user", text)
                        self.record_turn("assistant", ans)
                        return ans
                else:
                    self.inbound_intent = None
                    ans = "Belirttiğiniz bilgilerle aktif bir randevu bulunamadı. Dilerseniz yeni bir randevu oluşturmak için adınızı ve aracınızı söyleyebilirsiniz."
                    self.record_turn("user", text)
                    self.record_turn("assistant", ans)
                    return ans

        # 5. Gelen Randevu İptal veya Değişiklik Talebi
        if _CANCEL_INTENT_RE.search(clean) or _RESCHEDULE_INTENT_RE.search(clean):
            is_cancel = bool(_CANCEL_INTENT_RE.search(clean))
            pl_found = extract_plate(text)
            with Session() as db:
                target_app = _find_active_appointment(
                    db,
                    customer_phone=self.customer_phone,
                    plate=pl_found or "",
                    customer_name=self.customer or "",
                )
                if target_app:
                    v = db.get(Vehicle, target_app.vehicle_id) if target_app.vehicle_id else None
                    v_desc = v.description if v else (v.plate if v else "aracınız")
                    if is_cancel:
                        self.target_appointment_id = target_app.id
                        self.awaiting_cancel_confirmation = True
                        s = db.get(Slot, target_app.slot_id) if target_app.slot_id else None
                        s_time = datetime.fromisoformat(s.starts_at).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y saat %H:%M") if s else "belirtilen"
                        ans = f"Sayın {target_app.customer}, {v_desc} aracınız için {s_time} tarihindeki randevunuzu iptal etmek istediğinizi onaylıyor musunuz? Onaylamak için 'evet onaylıyorum' diyebilirsiniz."
                        self.record_turn("user", text)
                        self.record_turn("assistant", ans)
                        return ans
                    else:
                        cancel_appointment(db, target_app, commit=True)
                        self.customer = target_app.customer
                        self.vehicle = target_app.vehicle_id
                        self.customer_phone = target_app.customer_phone or self.customer_phone
                        occupied = select(Appointment.slot_id).where(Appointment.slot_id.is_not(None))
                        slots = db.scalars(select(Slot).where(Slot.id.not_in(occupied)).order_by(Slot.starts_at)).all()
                        slots = [s for s in slots if datetime.fromisoformat(s.starts_at) > datetime.now(ZoneInfo("UTC"))][:3]
                        self.options = [(s.id, datetime.fromisoformat(s.starts_at).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y saat %H:%M")) for s in slots]
                        ans = f"Sayın {target_app.customer}, {v_desc} aracınızın mevcut randevusunu iptal ettim. Yeni randevunuz için seçeneklerimiz: {self.format_options(db)}"
                        self.record_turn("user", text)
                        self.record_turn("assistant", ans)
                        return ans
                else:
                    self.inbound_intent = "cancel" if is_cancel else "reschedule"
                    ans = "Telefon numaranıza kayıtlı aktif bir randevu bulamadım. Randevunuz hangi telefon numarası veya araç plakası ile kayıtlıydı?"
                    self.record_turn("user", text)
                    self.record_turn("assistant", ans)
                    return ans

        # 6. Fiyat ve Ekspertiz Paketleri Bilgilendirme
        if _PRICE_INQUIRY_RE.search(clean) and not self.awaiting and not self.options:
            from backend.queue_lift import PACKAGE_DEFINITIONS
            matched_pkg = None
            lower_text = text.lower()
            for k, p in PACKAGE_DEFINITIONS.items():
                if any(kw in lower_text for kw in p["keywords"]):
                    matched_pkg = p
                    break
            if matched_pkg:
                price_tl = f"{matched_pkg['base_price_kurus'] // 100:,}".replace(",", ".")
                self.package_type = matched_pkg["key"]
                ans = (
                    f"{matched_pkg['name']} paketimiz {price_tl} TL'dir. "
                    f"Yaklaşık {matched_pkg['duration_minutes']} dakika sürer ve {matched_pkg['description']} "
                    f"Bu paket için randevu oluşturmak ister misiniz?"
                )
            else:
                ans = (
                    "Ekspertiz merkezimizde 4 ana paketimiz bulunmaktadır: "
                    "Motor ve Mekanik 950 TL, Standart Ekspertiz 1.450 TL, Full Kapsamlı 1.950 TL ve VIP Premium 2.600 TL'dir. "
                    "Hangi paketimiz için randevu oluşturmak istersiniz?"
                )
            self.record_turn("user", text)
            self.record_turn("assistant", ans)
            return ans

        if self.awaiting:
            if re.fullmatch(
                r"\s*(evet|(?:evet\s+){0,2}onaylıyorum|tamam\s+onaylıyorum)\s*",
                re.sub(r"[.,!?;:]", " ", text),
                re.I,
            ):
                self.booking_status = BookingStateMachine.transition(
                    self.booking_status, BookingStatus.CONFIRMING
                )
                with Session() as db:
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
                        self.record_turn("user", text)
                        self.record_turn("assistant", ans)
                        return ans
                self.booking_status = BookingStateMachine.transition(
                    self.booking_status, BookingStatus.CONFIRMED
                )
                self.retries = 0
                if getattr(self, "multi_vehicle_planned", False):
                    ans = f"İlk aracınız için randevunuz oluşturuldu.{self._sms_note('Onay ve randevu detaylarını SMS olarak telefonunuza iletiyorum.')} Şimdi ikinci aracınızın marka ve modelini söyler misiniz?"
                    self.reset_for_next_vehicle()
                else:
                    self.done = True
                    if self.corporate_account_name:
                        ans = f"Randevunuz {self.corporate_account_name} kurumsal cari hesabınıza işlenerek oluşturuldu.{self._sms_note('Onay ve randevu detaylarını SMS ve WhatsApp ile iletiyorum.')} İyi günler dilerim."
                    else:
                        ans = f"Randevunuz oluşturuldu.{self._sms_note('Onay ve randevu detaylarını SMS olarak telefonunuza iletiyorum.')} İyi günler dilerim."
                self.record_turn("user", text)
                self.record_turn("assistant", ans)
                return ans
            self.awaiting = False
            self.slot = None
            ans = "Randevu oluşturmadım. Başka bir saat seçmek ister misiniz?"
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

        messages = self._llm_messages(text)

        chunks = []

        async def collect():
            async for chunk in models.chat(messages):
                chunks.append(chunk)

        try:
            await asyncio.wait_for(collect(), timeout=settings.llm_timeout_sec)
        except asyncio.TimeoutError:
            # models.chat bir async generator: wait_for iptali onu kapatır; yarım çıktı atılır.
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
