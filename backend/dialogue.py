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
        # Telefon numarası bilinmiyorsa (sesli görüşmede genelde bilinmez) SMS vaadi verilmez.
        self.customer_phone = ""
        self.outbound_persisted: bool | None = None
        self.history: list[dict[str, str]] = []
        self.max_history_turns = max_history_turns

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
        prompt = get_prompt_template_text(self.prompt_template)
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
        if additions:
            prompt += " " + " ".join(additions)
        return prompt

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
        self._record_callback_request(db)
        return "Şu anda operatöre bağlayamıyorum; talebinizi kaydettim, sizi arayacağız."

    def _record_callback_request(self, db=None) -> None:
        """Aktarım yapılamadığında görüşmeyi 'follow_up' işaretleyip operatör notu ekler."""
        try:
            if db is None:
                with Session() as own:
                    self._record_callback_request(own)
                return
            conv = db.get(Conversation, self.id)
            if conv:
                conv.status = "follow_up"
                stamp = datetime.now(ZoneInfo("UTC")).isoformat()
                note = (
                    f"[{stamp}] Operatör aktarımı yapılamadı (AMI bağlı değil); "
                    f"müşteri geri aranacak. {self.get_transfer_summary(db)}"
                )
                conv.operator_notes = f"{conv.operator_notes or ''}\n{note}".strip()
                db.commit()
        except Exception:
            logger.exception("Geri arama kaydı oluşturulamadı: %s", self.id)

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

    def unclear(self):
        self.retries += 1
        if self.retries >= 3:
            self.done = True
            return "Sizi anlayamadım. Görüşmeyi takip için kaydediyorum. İyi günler."
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
                self.done = True
                self.retries = 0
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

        norm = text.strip().lower()
        clean = re.sub(r"[.,!?;:]", " ", norm)

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
                self.done = True
                self.retries = 0
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

        prompt = self.build_prompt()
        messages = [{"role": "system", "content": prompt}]
        messages.extend(self.history[-self.max_history_turns :])
        messages.append({"role": "user", "content": text})

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
                needle = (
                    normalize(info.vehicle_description)["normalized"]
                    .casefold()
                    .strip(" .")
                )
                matches = []
                for vehicle in db.scalars(select(Vehicle)).all():
                    candidate = (
                        normalize(vehicle.description)["normalized"]
                        .casefold()
                        .strip(" .")
                    )
                    # Boş dize her şeyin içinde "geçer"; boş aday/ifade eşleşme sayılmaz.
                    if not needle or not candidate:
                        continue
                    if needle in candidate or candidate in needle:
                        matches.append(vehicle)
                if len(matches) == 1:
                    matched_id = matches[0].id
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
