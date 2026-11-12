from typing import Literal

from backend.supervisor.contracts import CATALOGUE_VERSION, Contract, Intent


class IntentDefinition(Contract):
    intent_id: Intent
    domain: Literal["conversation", "service", "technical", "sales", "parts", "crm", "safety"]
    description: str
    positive: str
    negative: str
    agent: str
    minimum_slots: tuple[str, ...] = ()
    critical_write: bool = False
    safety_level: Literal["routine", "caution", "emergency"] = "routine"
    catalogue_version: Literal["intent-v1"] = CATALOGUE_VERSION


def _entry(intent, domain, description, positive, negative, agent, **options):
    return IntentDefinition(
        intent_id=intent, domain=domain, description=description,
        positive=positive, negative=negative, agent=agent, **options,
    )


CATALOGUE = {
    item.intent_id: item
    for item in (
        _entry(Intent.GREETING, "conversation", "Karşılama", "Merhaba", "Görüşürüz", "Conversation"),
        _entry(Intent.GOODBYE, "conversation", "Görüşmeyi bitirme", "Hoşça kalın", "Tekrar söyler misiniz?", "Conversation"),
        _entry(Intent.REPEAT_REQUEST, "conversation", "Önceki sözü yineleme", "Son söylediğinizi tekrarlayın", "Bu ne demek?", "Conversation"),
        _entry(Intent.CLARIFICATION_REQUEST, "conversation", "Anlamı açıklama", "Bu ne anlama geliyor?", "Tekrar eder misiniz?", "Conversation"),
        _entry(Intent.HUMAN_HANDOFF_REQUEST, "conversation", "İnsan temsilciye erişim", "Operatöre bağlar mısınız?", "Temsilci istemiyorum", "Operator"),
        _entry(Intent.BOOKING_CREATE, "service", "Yeni randevu", "Cuma servise gelebilir miyim?", "Mevcut randevum saat kaçta?", "ServiceBooking", minimum_slots=("verified_customer", "selected_slot"), critical_write=True),
        _entry(Intent.BOOKING_RESCHEDULE, "service", "Randevuyu taşıma", "Randevumu pazartesiye alalım", "Yeni randevu istiyorum", "ServiceBooking", minimum_slots=("verified_customer", "booking_id", "selected_slot"), critical_write=True),
        _entry(Intent.BOOKING_CANCEL, "service", "Randevuyu iptal etme", "Randevumu iptal edin", "Randevumu iptal etmek istemiyorum", "ServiceBooking", minimum_slots=("verified_customer", "booking_id"), critical_write=True),
        _entry(Intent.BOOKING_STATUS, "service", "Randevu durumunu öğrenme", "Randevumun saati nedir?", "Randevumu değiştirin", "ServiceBooking", minimum_slots=("verified_customer", "booking_id")),
        _entry(Intent.SERVICE_PRICE_ESTIMATE, "service", "Servis ücreti tahmini", "Ekspertiz ücreti ne kadar?", "Aracın satış fiyatı ne kadar?", "ServiceBooking", minimum_slots=("service_type",)),
        _entry(Intent.WARNING_LIGHT_QUESTION, "technical", "Gösterge uyarısını sorma", "Motor arıza ışığı yanıyor", "Fren tutmuyor, yoldayım", "AutomotiveExpert", minimum_slots=("vehicle_model",), safety_level="caution"),
        _entry(Intent.SYMPTOM_QUESTION, "technical", "Araç belirtisini açıklama", "Motordan tıkırtı geliyor", "Kaza yaptım, yaralı var", "AutomotiveExpert", minimum_slots=("symptom",), safety_level="caution"),
        _entry(Intent.MAINTENANCE_SCHEDULE_QUESTION, "technical", "Bakım aralığını sorma", "Periyodik bakım kaç kilometrede?", "Bakım için randevu istiyorum", "AutomotiveExpert", minimum_slots=("vehicle_model",)),
        _entry(Intent.VEHICLE_SPEC_QUESTION, "technical", "Araç özelliğini sorma", "3008 kaç beygir?", "3008 ile Tiguan'ı kıyasla", "AutomotiveExpert", minimum_slots=("vehicle_model",)),
        _entry(Intent.MODEL_COMPARISON, "sales", "Modelleri kıyaslama", "3008 ve Tiguan'ı karşılaştır", "3008 kaç beygir?", "VehicleSales", minimum_slots=("models",)),
        _entry(Intent.VEHICLE_PRICE_QUOTE, "sales", "Araç satış fiyatı", "3008 satış fiyatı nedir?", "Servis ücreti ne kadar?", "VehicleSales", minimum_slots=("vehicle_model",)),
        _entry(Intent.TEST_DRIVE_REQUEST, "sales", "Test sürüşü talebi", "Test sürüşü yapmak istiyorum", "Aracın çekişi nasıl?", "VehicleSales", minimum_slots=("vehicle_model",)),
        _entry(Intent.PART_COMPATIBILITY, "parts", "Parça uyumunu sorgulama", "Bu filtre aracıma uyar mı?", "Filtre stokta mı?", "Parts", minimum_slots=("part", "vehicle_model")),
        _entry(Intent.PART_AVAILABILITY, "parts", "Parça stok durumu", "Fren balatası stokta mı?", "Bu balata aracıma uyar mı?", "Parts", minimum_slots=("part",)),
        _entry(Intent.CUSTOMER_RECORD_QUESTION, "crm", "Müşteri kaydını sorgulama", "Servis geçmişimi görebilir miyim?", "Periyodik bakım ne zaman?", "CRM", minimum_slots=("verified_customer",)),
        _entry(Intent.COMPLAINT_CREATE, "crm", "Şikâyet kaydı açma", "Şikâyet kaydı oluşturun", "Randevumu iptal edin", "CRM", minimum_slots=("verified_customer", "complaint"), critical_write=True),
        _entry(Intent.ROADSIDE_EMERGENCY, "safety", "Devam eden yol tehlikesi", "Yoldayım, frenler tutmuyor", "Fren balatası stokta mı?", "Safety", safety_level="emergency"),
    )
}
