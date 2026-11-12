import re
import unicodedata
from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from backend.supervisor.catalogue import CATALOGUE
from backend.supervisor.contracts import (
    ConversationContext, ExecutionPlan, Intent, IntentCandidate, IntentDecision, PlanStep,
    RouteState, Slot,
)

WRITE_GUARDS = (
    "tool_authorization", "customer_verified", "explicit_confirmation",
    "state_recheck", "idempotency",
)
PRIVATE_READS = {Intent.BOOKING_STATUS, Intent.CUSTOMER_RECORD_QUESTION}
TURKISH_I = str.maketrans({"I": "ı", "İ": "i"})


def normalize_utterance(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(TURKISH_I).lower()
    return " ".join(text.split())


EMERGENCY = re.compile(
    r"\bfren(?:ler|im)? (?:tutmuyor|boşaldı|patladı)\b"
    r"|\b(?:kaza yaptım|kaza geçirdik|yaralı var|biri yaralandı)\b"
    r"|\b(?:araba|araç|motor)(?:m|ım)? (?:yanıyor|alev aldı)\b"
    r"|\b(?:motor(?:dan|umdan)|kaput(?:tan|un altından)) duman çıkıyor\b"
    r"|\bhararet (?:kırmızıda|kırmızıya çıktı|sonuna dayandı)\b"
)
HAZARD = re.compile(r"\b(?:duman|yangın|kaza|hararet|yaralı|fren kaybı)\b")
HAZARD_CONTEXT = re.compile(r"\b(?:yoldayım|yoldayız|seyir halindeyim|şu an|arabada|araçta)\b")
HYPOTHETICAL = re.compile(r"\b(?:olursa|çıkarsa|yaparsam|tutmazsa|örneğin|varsayalım)\b")
HISTORICAL = re.compile(r"\b(?:geçen yıl|geçen sene|geçen ay|geçen hafta|dün|daha önce)\b")
HANDOFF = re.compile(r"\b(?:operatör|temsilci|insan|yetkili|müşteri hizmetleri)\w*\b.*\b(?:bağla\w*|aktar\w*|görüş\w*|konuş\w*|istiyorum)\b")
HANDOFF_DENIED = re.compile(r"\b(?:istemiyorum|bağlamayın|aktarmayın|görüşmeyeyim)\b")
WRITE_DENIED = re.compile(
    r"\b(?:istemiyorum|istemem|vazgeçtim|etme(?:yin)?|yapma(?:yın)?|"
    r"alma(?:yın)?|açma(?:yın)?|oluşturma(?:yın)?|değiştirme(?:yin)?|"
    r"erteleme(?:yin)?|taşıma(?:yın)?|düşünmüyorum|gerekmiyor|olmasın|etmeyeceğim)\b"
)
RULES = {
    Intent.GREETING: r"\b(?:merhaba|selam|günaydın|iyi günler)\b",
    Intent.GOODBYE: r"\b(?:görüşürüz|hoşça kal\w*|iyi akşamlar)\b",
    Intent.REPEAT_REQUEST: r"\b(?:tekrar (?:eder|söyler|söyle\w*)|tekrarla\w*)\b",
    Intent.CLARIFICATION_REQUEST: r"\b(?:ne demek|ne anlama geliyor|açıklar mısınız)\b",
    Intent.BOOKING_CREATE: r"\b(?:randevu (?:al\w*|istiyorum|oluştur\w*)|servise gel\w*|servis için gün)\b",
    Intent.BOOKING_RESCHEDULE: r"\brandevu\w*\b.*\b(?:ertele\w*|değiştir\w*|taşı\w*|pazartesiye al\w*)\b",
    Intent.BOOKING_CANCEL: r"\brandevu\w*\b.*\biptal\b",
    Intent.BOOKING_STATUS: r"\brandevu\w*\b.*\b(?:saat\w*|ne zaman|durum\w*|hangi gün)\b",
    Intent.SERVICE_PRICE_ESTIMATE: r"\b(?:servis|ekspertiz|bakım)\b.*\b(?:ücret\w*|fiyat\w*|ne kadar)\b",
    Intent.WARNING_LIGHT_QUESTION: r"\b(?:arıza|motor|uyarı|ikaz|abs) (?:ışığ\w*|lamba\w*)\b",
    Intent.SYMPTOM_QUESTION: r"\b(?:tıkırtı|titriyor|tekliyor|sarsılıyor|çekmiyor|ses geliyor)\b",
    Intent.MAINTENANCE_SCHEDULE_QUESTION: r"\bbakım\b.*\b(?:kaç kilometre\w*|ne zaman|aralığ\w*)\b",
    Intent.VEHICLE_SPEC_QUESTION: r"\b(?:kaç beygir|motor hacmi|yakıt tüketimi|kaç litre yakar)\b",
    Intent.MODEL_COMPARISON: r"\b(?:karşılaştır\w*|kıyasla\w*|hangisi daha iyi)\b",
    Intent.VEHICLE_PRICE_QUOTE: r"\b(?:satış fiyatı|araç fiyatı|sıfır fiyatı)\b",
    Intent.TEST_DRIVE_REQUEST: r"\btest sürüş\w*\b",
    Intent.PART_COMPATIBILITY: r"\b(?:uyar mı|uyumlu mu|parça uyumu)\b",
    Intent.PART_AVAILABILITY: r"\b(?:stokta mı|stok durum\w*|elinizde var mı)\b",
    Intent.CUSTOMER_RECORD_QUESTION: r"\b(?:servis geçmiş\w*|müşteri kayd\w*|kişisel bilgi\w*)\b",
    Intent.COMPLAINT_CREATE: r"\b(?:şikâyet|şikayet)\b.*\b(?:kaydı|oluştur\w*|aç\w*)\b",
}
OUT_OF_SCOPE = re.compile(r"\b(?:hava durumu|yemek tarifi|matematik ödevi|maç skoru)\b")
CORRECTION = re.compile(r"\b(?:yanlış anladınız|öyle demedim|onu kastetmedim|düzelteyim)\b")


def rule_candidates(text: str) -> tuple[tuple[IntentCandidate, ...], tuple[str, ...]]:
    found = []
    reasons = []
    if CORRECTION.search(text):
        reasons.append("dialogue.customer_correction")
    clauses = re.split(r"[,;.!?]|\b(?:ama|fakat|ancak)\b", text)
    if any(
        EMERGENCY.search(clause) and not HYPOTHETICAL.search(clause)
        and (not HISTORICAL.search(clause) or HAZARD_CONTEXT.search(clause))
        for clause in clauses
    ):
        found.append(Intent.ROADSIDE_EMERGENCY)
    elif HAZARD.search(text) and HAZARD_CONTEXT.search(text) and not HYPOTHETICAL.search(text):
        reasons.append("safety.clarify")
    if HANDOFF.search(text) and not HANDOFF_DENIED.search(text):
        found.append(Intent.HUMAN_HANDOFF_REQUEST)

    denied = bool(WRITE_DENIED.search(text))
    for intent, pattern in RULES.items():
        if re.search(pattern, text):
            if denied and CATALOGUE[intent].critical_write:
                reasons.append("policy.negated_write")
            else:
                found.append(intent)
    return (
        tuple(IntentCandidate(intent_id=intent, evidence=f"rule.{intent.value}") for intent in found),
        tuple(dict.fromkeys(reasons)),
    )


def rule_decision(text: str) -> IntentDecision:
    candidates, reasons = rule_candidates(text)
    out_of_scope = bool(OUT_OF_SCOPE.search(text)) and not candidates and not reasons
    if candidates:
        state = RouteState.ROUTED
    else:
        state = RouteState.OUT_OF_SCOPE if out_of_scope else RouteState.UNKNOWN
        reasons = reasons or (("scope.excluded",) if out_of_scope else ("intent.insufficient_evidence",))
    return IntentDecision(
        candidates=candidates, route_state=state, source="rule" if candidates or out_of_scope else "none",
        reason_codes=reasons, needs_clarification=state == RouteState.UNKNOWN or "safety.clarify" in reasons,
    )


WEEKDAYS = ("pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar")
RELATIVE_DATE = re.compile(r"\b(" + "|".join((*WEEKDAYS, "bugün", "yarın")) + r")\b")
YEAR = re.compile(r"\b(?:19[5-9]\d|20[0-3]\d)\b")
BARE_DATE = re.compile(r"(?:(?:bu|gelecek hafta) )?(?:" + "|".join((*WEEKDAYS, "bugün", "yarın")) + r")[.!?]*")


def resolve_slots(
    text: str, context: ConversationContext, *, vehicles: tuple[tuple[str, str], ...] = (),
) -> tuple[Slot, ...]:
    slots = {slot.name: slot for slot in context.verified_vehicle}
    for slot in context.pending_slots:
        if slot.name in {"preferred_date", "service_type"} and not slot.verified:
            slots.setdefault(slot.name, slot)
    if year := YEAR.search(text):
        slots.setdefault("vehicle_year", Slot(name="vehicle_year", value=int(year[0]), evidence="asr_final"))
    matches = {
        (brand, model) for brand, model in vehicles
        if re.search(r"(?<!\w)" + re.escape(normalize_utterance(f"{brand} {model}")) + r"(?!\w)", text)
    }
    if len(matches) == 1:
        brand, model = matches.pop()
        for name, value in (("vehicle_brand", brand), ("vehicle_model", model)):
            slots.setdefault(name, Slot(name=name, value=value, evidence="asr_final"))
    date_words = set(RELATIVE_DATE.findall(text))
    if len(date_words) == 1:
        day = next(iter(date_words))
        today = context.turn_at.astimezone(ZoneInfo("Europe/Istanbul")).date()
        if day in WEEKDAYS:
            offset = (WEEKDAYS.index(day) - today.weekday()) % 7
            if "gelecek hafta" in text:
                offset = 7 - today.weekday() + WEEKDAYS.index(day)
        else:
            offset = int(day == "yarın")
        slots["preferred_date"] = Slot(
            name="preferred_date", value=(today + timedelta(days=offset)).isoformat(),
            evidence="relative_date",
        )
    elif date_words:
        slots.pop("preferred_date", None)
    return tuple(slots.values())


def build_plan(
    intents: tuple[Intent, ...], reasons: tuple[str, ...], trace_id: UUID, model_version: str,
) -> ExecutionPlan:
    priority = "normal"
    steps = []
    writes = False
    if Intent.ROADSIDE_EMERGENCY in intents:
        priority = "emergency"
        steps = [
            PlanStep(step_id="safety", agent="Safety", action="urgent_safety_message",
                     intent_id=Intent.ROADSIDE_EMERGENCY, guardrails=("no_diagnosis", "no_driving_guarantee")),
            PlanStep(step_id="handoff", agent="Operator", action="request_handoff", depends_on=("safety",)),
        ]
    elif "safety.clarify" in reasons:
        steps = [PlanStep(step_id="clarify_safety", agent="Safety", action="clarify_urgent_risk")]
    else:
        ordered = sorted(intents, key=lambda intent: (
            intent != Intent.HUMAN_HANDOFF_REQUEST,
            CATALOGUE[intent].domain != "technical",
        ))
        for intent in ordered:
            entry = CATALOGUE[intent]
            if intent == Intent.HUMAN_HANDOFF_REQUEST:
                priority = "handoff"
            guards = ()
            if entry.critical_write:
                writes = True
                guards = WRITE_GUARDS
                action = "clarify_date_and_check_availability" if intent == Intent.BOOKING_CREATE else "verify_write_request"
            elif intent in PRIVATE_READS:
                action = "verify_identity_before_lookup"
                guards = ("customer_verified", "tool_authorization")
            elif entry.domain == "technical":
                action = "answer_with_verified_sources"
                guards = ("verified_sources", "no_diagnosis", "no_driving_guarantee")
            else:
                action = "request_handoff" if intent == Intent.HUMAN_HANDOFF_REQUEST else intent.value
            steps.append(PlanStep(
                step_id=intent.value, agent=entry.agent, action=action,
                intent_id=intent, guardrails=guards,
                depends_on=(steps[-1].step_id,) if steps else (),
            ))
    if not steps:
        steps.append(PlanStep(step_id="clarify", agent="Conversation", action="clarify_intent"))
    return ExecutionPlan(
        steps=tuple(steps), priority=priority, requires_confirmation=writes,
        guardrails=WRITE_GUARDS if writes else (), model_version=model_version, trace_id=trace_id,
    )
