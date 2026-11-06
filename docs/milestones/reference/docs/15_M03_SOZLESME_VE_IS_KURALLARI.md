# M03 — Otomotiv Diyalog Politikası ve Randevu Durum Makinesi

## Amaç ve sınırlar

Bu iş paketi M01 ve M02 public API'lerini değiştirmeden otomotiv iş kararlarını deterministik bir katmana ayırır. M03 hiçbir gerçek TTS/STT, YouTube, SIP/Asterisk, telefon, GPU veya CRM bağlantısı çalıştırmaz. Tek bir Python prosesinde çalışan mock portlar kullanılır.

### Katmanlar

```text
M02 / REQUEST_LLM Effect (session + turn + generation + transcript_ref)
    -> DialogueCoordinator  [M02 güncel generation ve THINKING doğrula]
    -> ReferenceStore.get_input(session, transcript_ref)
    -> DialoguePolicy [kimlik/yetki + kurallı işlem + onay]
       -> CRMPort (VehicleRecord, PriceQuote, explicit case creation)
       -> InspectionBookingPort (availability, commit, lookup)
       -> BookingStateMachine (izin verilen durum geçişleri)
    -> ReferenceStore.put_response(session, text)
    -> M02 LLM_RESPONSE_READY(response_ref)  veya HANDOFF_REQUESTED
    -> M02 START_TTS effect (gerçek TTS daha sonra)
```

`REQUEST_LLM` adı M02 geriye dönük uyumluluk için korunur; M03'te gerçek LLM çalışmaz. İş-kritik sonuçları LLM üretmez.

## Kamuya açık Python modülleri

| Modül | Sözleşme |
|---|---|
| `dialogue.models` | `Intent`, `DialogueInput`, `AccessContext`, `AppointmentSlot`, `Availability`, `BookingStatus`, `Commitment`, `PriceQuote`, `BookingReceipt`, `CaseKind`, `CaseReceipt` |
| `dialogue.ports` | Asenkron `CRMPort`, `InspectionBookingPort`; yalnız in-memory fake implementasyonlar |
| `dialogue.storage` | Oturum-kapsamlı rastgele ref üreten, kapasite sınırlı `ReferenceStore` |
| `dialogue.booking_state` | `BookingStateMachine.transition(current,target)`; geçersiz geçişler reddedilir |
| `dialogue.policy` | `DialoguePolicy.handle(session, structured_input, access, is_current=...)` |
| `dialogue.coordinator` | `DialogueCoordinator.process(REQUEST_LLM_effect, access)`; eski tur/nesil reddi |

### Sözlük ve konuşma politikası

M03 henüz serbest Türkçe konuşmayı ayrıştırmaz; `DialogueInput` yapılandırılmış intent/slot verisi sahte NLU tarafından hazırlanır. Canlı ASR ve otomotiv telaffuz normalizasyonu sonraki paketlerdedir. `transcript_ref` yalnız session namespace içinde çözülür. Ham metin `ReferenceStore.put_transcript()` ile belleğe konabilir; M02 kontrol olaylarına veya audit mesajlarına eklenmez.

### Kimlik ve işleme yetkisi

`AccessContext.authenticated=true` ve `crm_processing_allowed=true` olmadan araç kaydı, kişisel değer, CRM takip kaydı veya rezervasyon kullanılmaz. Pazarlama izni farklı bir bayraktır ve CRM işlem yetkisi vermez. Bu bayraklar bir **mock** güvenlik girdisidir; gerçek kimlik ispatı, izin temeli, KVKK bilgilendirmesi ve veri saklama politikaları **uygulanmış değildir**.

### Fiyat

`PriceQuote` sadece mevcut, doğrulanmış, son geçerlilik tarihi geçmemiş ve araç kimliği eşleşen CRM kaynağından okunur. Hiçbir fiyat tahmin edilmez. Görünen rakam kesin satış taahhüdü olarak sunulmaz.

### Rezervasyon statüleri

| Statü | İş anlamı | Müşteriye onay denebilir mi? |
|---|---|---|
| `IDLE` | Rezervasyon yok | Hayır |
| `AWAITING_CONFIRMATION` | Yer bulundu, açık onay bekleniyor | Hayır |
| `CONFIRMING` | Backend kayıt adımı | Hayır |
| `CONFIRMED` | Backend `CONFIRMED` ve `reference_id` birlikte döndü | **Evet** |
| `UNAVAILABLE` | Yer uygun değil | Hayır |
| `UNKNOWN` | Yer veya işlem sonucu bilinmiyor | Hayır |
| `DECLINED` | Müşteri teklifi reddetti | Hayır |
| `HANDOFF` | Temsilciye yönlendirme | Hayır |

**İşlem sırası:** doğru araç + gelecek tarihli saat + müsaitlik (`AVAILABLE`) -> teklif -> kullanıcı `CONFIRM` -> idempotency anahtarıyla backend `commit` -> `CONFIRMED` ve ref -> onay metni. `UNKNOWN` kalan bir commit için yeni teklif bloklanır; `RECHECK_BOOKING` önceki anahtarla sonuç sorgular. Başka randevu eklemek için mevcut onaylı randevudan sonra manuel süreç gerekir. Aynı anahtar farklı araca/saate gönderildiğinde fake servis hata verir.

**CRM vaka kaydı:** `CREATE_CRM_CASE` yalnız açıkça seçilmiş `CaseKind` (geri arama / fiyat talebi / ekspertiz bilgisi) ve kimlik+işleme yetkisiyle kullanılır. Mock port işlemi deterministik idempotency anahtarıyla saklar; gerçek CRM'ye yazmaz.

### Barge-in / eski nesil korunması

Koordinatör `effect.turn_id`, `effect.generation_id` ve `M02.THINKING` durumunu hem işlem öncesinde hem de yanıt sinyalini üretmeden kontrol eder. İptal edilmiş tur için `LLM_RESPONSE_READY` göndermez. Rezervasyon `commit` çağrısı öncesi ayrıca güncellik kontrolü yapılır. **Sınır:** gerçek uzak CRM/rezervasyon commit'i ile M02 nesil değişimi arasında atomik bir dağıtık işlem bulunmaz. Bu riski üretimde idempotency, durable outbox, mutabakat (reconcile) ve servis tarafı iptal/timeout sözleşmeleriyle kapatmak gerekir.

### Veri ve güvenlik sınırları

- `ReferenceStore` RAM içinde, oturum-kapsamlı, sınırlı kapasitede; `erase_session()` sunar. **Şifreli veya kalıcı kasa değildir.**
- Ham transcript veya yanıt metni M02 sinyal, M01 event ve audit kayıtlarında saklanmaz; sadece rastgele ref vardır.
- `BookingStateMachine` tek süreç içindeki mantıksal geçişleri doğrular; DB transaction veya distributed lock sağlamaz.
- JSON şemaları: `contracts/dialogue_input.schema.json`, `policy_decision.schema.json`, `booking_receipt.schema.json`, `access_context.schema.json` (Draft 2020-12).
- M01/M02'nin volatile event kuyruğu ve kritik kapatmadaki audit teslim garantisizliği hâlâ aynıdır.

## Çalıştırma

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[validation]"
.\scripts\check_m03.ps1
```

Alternatif: `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v; python -m automotive_voice.m03_demo`.
