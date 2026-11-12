"""Small smoke-test dataset with independent scenario groups per split."""

from backend.supervisor.contracts import Intent
from backend.supervisor.dataset import TrainingExample

PHRASES = {
    Intent.GREETING: ("Selamlar", "Merhaba kolay gelsin", "Günaydın orada mısınız", "İyi günler nasılsınız"),
    Intent.GOODBYE: ("Hoşça kal", "Görüşmek üzere", "İyi akşamlar görüşürüz", "Ben kapatıyorum hoşça kalın"),
    Intent.REPEAT_REQUEST: ("Bir daha söyler misin", "Tekrarlar mısınız", "Son cümleyi yeniden söyleyin", "Ne dediniz tekrar eder misiniz"),
    Intent.CLARIFICATION_REQUEST: ("Ne demek bu", "Biraz açabilir misin", "Tam olarak ne anlama geliyor", "Bunu daha açık anlatır mısın"),
    Intent.HUMAN_HANDOFF_REQUEST: ("Canlı temsilciye bağla", "Bir yetkiliyle görüşmek istiyorum", "Operatöre aktarır mısınız", "İnsanla konuşabilir miyim"),
    Intent.BOOKING_CREATE: ("Servis için randevu almak istiyorum", "Ekspertize yer ayırabilir miyiz", "Cuma servise gelebilir miyim", "Bana yeni bir servis randevusu açar mısınız"),
    Intent.BOOKING_RESCHEDULE: ("Randevuyu ertele", "Servis randevumun gününü değiştirelim", "Randevumu başka güne taşı", "Pazartesiye alabilir miyiz randevuyu"),
    Intent.BOOKING_CANCEL: ("Randevumu iptal edin", "Rezervasyonu kaldırır mısınız", "Servis randevusunu iptal et", "Ayırdığımız servis saatini iptal edelim"),
    Intent.BOOKING_STATUS: ("Randevum saat kaçtaydı", "Rezervasyonum onaylandı mı", "Randevum hangi gün görünüyor", "Servis randevumun durumunu öğreneyim"),
    Intent.SERVICE_PRICE_ESTIMATE: ("Ekspertiz ücreti kaç para", "Servis tahminen ne tutar", "Bakım ücretini öğrenebilir miyim", "Periyodik servis fiyatınız nedir"),
    Intent.WARNING_LIGHT_QUESTION: ("Motor arıza ışığı yandı", "ABS ikaz lambası yanıyor", "Gösterge panelinde sarı uyarı işareti çıktı", "Lastik basınç ışığı niye sönmüyor"),
    Intent.SYMPTOM_QUESTION: ("Motor tekliyor", "Önden tıkırtı geliyor", "Frene basınca direksiyon titriyor", "Araba hızlanırken sarsılıyor"),
    Intent.MAINTENANCE_SCHEDULE_QUESTION: ("Bakım kaç kilometrede bir", "Triger ne zaman değişmeli", "Yağ değişim aralığı ne", "Sıradaki periyodik bakım ne zaman"),
    Intent.VEHICLE_SPEC_QUESTION: ("Bu motor kaç beygir", "Bagaj hacmi kaç litre", "Tiguan ne kadar yakar", "Bu aracın tork değeri nedir"),
    Intent.MODEL_COMPARISON: ("İki modeli kıyaslayalım", "Clio ile Polo hangisi daha iyi", "Corolla ve Civic farkları neler", "Kuga ile Sportage karşılaştırır mısınız"),
    Intent.VEHICLE_PRICE_QUOTE: ("Civic satış fiyatı nedir", "Sıfır araç kaç para", "Tiguan için fiyat teklifi verin", "Polo bayide kaç liraya satılıyor"),
    Intent.TEST_DRIVE_REQUEST: ("Test sürüşü yapmak istiyorum", "Aracı deneme sürüşüne çıkaralım", "Test sürüşüne yer var mı", "Bir deneme turu ayarlar mısınız"),
    Intent.PART_COMPATIBILITY: ("Bu yağ filtresi aracıma uyar mı", "Balata bu kasa ile uyumlu mu", "Bu aküyü benim modele takabilir miyiz", "Jantın uyumluluğunu kontrol edin"),
    Intent.PART_AVAILABILITY: ("Fren balatası stokta mı", "Elinizde buji var mı", "Yağ filtresini hemen alabilir miyim", "Akünün stok durumu nedir"),
    Intent.CUSTOMER_RECORD_QUESTION: ("Servis geçmişimi görmek istiyorum", "Müşteri kaydımda ne var", "Önceki işlemlerimin listesini görebilir miyim", "Kişisel bilgilerimi kontrol etmek istiyorum"),
    Intent.COMPLAINT_CREATE: ("Şikâyet kaydı oluşturun", "Yaşadığım sorun için şikayet açın", "Şikayetimi resmen kayda alın", "Servis deneyimim için şikâyet bırakmak istiyorum"),
    Intent.ROADSIDE_EMERGENCY: ("Fren tutmuyor yoldayım", "Aracım alev aldı", "Kaputun altından duman çıkıyor", "Yolda kaza yaptım yaralı var"),
}

EDGE_CASES = {
    "train": (
        ("Fren ses yapıyor ve servis randevusu istiyorum", (Intent.SYMPTOM_QUESTION, Intent.BOOKING_CREATE)),
        ("Pizza hamuru nasıl yapılır", ()),
        ("Radyo kanalı açık kalmış", ()),
    ),
    "validation": (
        ("Randevuyu iptal etmeyin sadece saatini söyleyin", (Intent.BOOKING_STATUS,)),
        ("Motır ışığı yanıyor bir de servis ücreti ne kadar", (Intent.WARNING_LIGHT_QUESTION, Intent.SERVICE_PRICE_ESTIMATE)),
        ("Hava durumu yağmurlu mu", ()),
        ("Eee yani şey", ()),
    ),
    "test": (
        ("Araba titriyo randevu alalım filtre de stokta mı", (Intent.SYMPTOM_QUESTION, Intent.BOOKING_CREATE, Intent.PART_AVAILABILITY)),
        ("Randevumu değiştirmek istemiyorum", ()),
        ("Maç skoru kaç", ()),
        ("Alo cızırtı geliyor", ()),
    ),
}


def synthetic_examples() -> list[TrainingExample]:
    examples = []
    for intent, phrases in PHRASES.items():
        for index, (split, phrase) in enumerate(zip(("train", "train", "validation", "test"), phrases, strict=True)):
            examples.append(TrainingExample(
                text=phrase, intents=(intent,), group_id=f"{intent}-{index}", split=split, source="synthetic",
            ))
    for split, rows in EDGE_CASES.items():
        for index, (phrase, intents) in enumerate(rows):
            examples.append(TrainingExample(
                text=phrase, intents=intents, group_id=f"edge-{split}-{index}", split=split, source="synthetic",
            ))
    return examples
