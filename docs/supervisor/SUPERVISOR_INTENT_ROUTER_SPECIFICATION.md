# FREYA AI — Supervisor Agent / Intent Router
## Cursor'a sırayla verilecek geliştirme promptları (V1, 22 intent)

> Kullanım: Freya repo kökünü Cursor'da aç. Önce PROMPT 0'ı çalıştır. Çıktıyı incele; her sonraki promptu ayrı mesaj olarak uygula. Bir aşama PASS olmadan ötekine geçme. Bu belge tasarım ve uygulama talimatıdır; mevcut repo özelliklerinin tamamlandığını iddia etmez.

## Mimari kararlar

- **22 intent / 7 alan**: Conversation 5, Service 5, Technical 4, Sales 3, Parts 2, CRM 2, Safety 1.
- `UNKNOWN` / `OUT_OF_SCOPE` ayrıca abstain/route sonucu; eğitimde yersiz 23. niyet gibi kullanılmasın.
- Aynı kullanıcı turunda **çoklu niyet** desteklenir; tek etikete zorlanmaz.
- Niyet ≠ entity/slot ≠ eylem. Örn. `booking_create` niyeti, `preferred_date` slot'u ve `create_booking` tool çağrısı farklı nesnelerdir.
- V1: Rule/Safety Gate + TF-IDF word/char + OneVsRest LogisticRegression baseline + Context Resolver + Policy/Plan. XGBoost sadece aynı test setiyle challenger; LLM sadece düşük güven / çok karışık bağlam için yapılandırılmış fallback.
- Araç yetkisi Supervisor'a doğrudan verilmez; Action Executor / Tool Gateway kontrol eder. Yazma işlemleri yetki ve onay gerektirir.
- ASR final segmentiyle route belirle; partial ASR kullanımı yalnız güvenli erken uyarı/interrupt sinyali olabilir. 8 kHz telefon gerçek veri testleri en son.
- FQICI/Self-Evaluation yalnız izleme, hata analizi, insan onaylı veri toplama ve offline değerlendirme yapar. Canlı model ağırlıklarını otomatik güncellemez.

### Sabit V1 niyet sözlüğü

- Conversation: `greeting`, `goodbye`, `repeat_request`, `clarification_request`, `human_handoff_request`
- Service: `booking_create`, `booking_reschedule`, `booking_cancel`, `booking_status`, `service_price_estimate`
- Technical: `warning_light_question`, `symptom_question`, `maintenance_schedule_question`, `vehicle_spec_question`
- Sales: `model_comparison`, `vehicle_price_quote`, `test_drive_request`
- Parts: `part_compatibility`, `part_availability`
- CRM: `customer_record_question`, `complaint_create`
- Safety: `roadside_emergency`

---

## PROMPT 0 — Repo keşfi / sadece analiz

```text
Sen Freya AI projesinde kıdemli Python/ML ve telephony architect olarak çalışıyorsun.
Yeni modül: Supervisor Agent + Multi-Label Intent Router (V1: 22 intent, 7 alan).

BU AŞAMADA KOD DEĞİŞTİRME.
Gerçek repo dosyalarını incele: ASR, turn manager, agent/LLM, TTS, Asterisk AMI/ARI, FastAPI, SQLite, React, mevcut testler, FQICI kalite/değerlendirme sistemi. Varsa eski intent router'ı ve event emitter'ı tespit et. Var olmayan altyapıyı mevcutmiş gibi anlatma.

Hedef mimari: ASR_FINAL -> Safety/Rule Gate -> çoklu niyet sınıflandırıcı -> güvenilir konuşma bağlamı + slot resolver -> Policy Engine -> sıralı/koşullu Agent Execution Plan -> Tool Gateway -> tek ses kimliğiyle Response Composer.

Sınırlar: offline-first, Windows-first, RTX 4070 8 GB; gerçek telephony ve GPU benchmark deneylerini tamamlanmış sayma; müşteriye ait verileri dış sağlayıcıya gönderme; mevcut çalışan özellikleri bozma; bağımsız modül, feature flag, rollback ve sentetik test önceliği.

Rapor üret: A) Gerçek mevcut mimari ve dosya yolları B) Kanıtlı PASS/PENDING/HOLD durumları C) Minimum değişiklikli entegrasyon dosya planı D) Mevcut FQICI ile olay/etiket entegrasyonu E) Eksik bağımlılıklar F) Sadece sıradaki en küçük atomik görev. Ben onaylamadan kod yazma.
```

## PROMPT 1 — Niyet kataloğu ve typed sözleşmeler

```text
PROMPT 0'ın doğrulanmış repo bulgularına göre çalış. Sadece niyet sözlüğü, şema, validasyon ve testlerini ekle. Klasör/dosya isimlerini repo konvansiyonlarından türet; başka modülleri yeniden yazma.

V1 EXACT intent catalogue (22):
greeting, goodbye, repeat_request, clarification_request, human_handoff_request;
booking_create, booking_reschedule, booking_cancel, booking_status, service_price_estimate;
warning_light_question, symptom_question, maintenance_schedule_question, vehicle_spec_question;
model_comparison, vehicle_price_quote, test_drive_request;
part_compatibility, part_availability;
customer_record_question, complaint_create; roadside_emergency.

Her niyet için ID, domain, açıklama, pozitif ve karıştırılabilecek negatif örnekler, izinli hedef agent, minimum slotlar, kritik işlem gereği, güvenlik seviyesi, katalog sürümü tanımla.
`UNKNOWN` ve `OUT_OF_SCOPE` sıfır veya yetersiz niyet için route state olarak ayrı tut.

Pydantic/dataclass sözleşmeleri: IntentCandidate(intent_id, score, evidence), IntentDecision(intent_ids, scores, route_state, source, needs_clarification), Slot(name, value, evidence, verified), ConversationContext(session_id, active_task, last_confirmed_intents, verified_vehicle, pending_slots), ExecutionPlan(steps, priority, requires_confirmation, guardrails, model_version, catalogue_version, trace_id).

Şemalarda gizlilik kontrollü, opsiyonel metadata ve tip validasyonu kullan. Her olay için gerekçeyi ve model/policy versiyonunu kaydet. JSON örnekleri ve pytest testleri yaz. Model eğitme veya dış servis çağırma.

Çıktı: değişen dosyalar, kısa kullanım, pytest komutu ve gerçek test sonucu; PASS yoksa nedenini yaz.
```

## PROMPT 2 — Safety Gate + deterministik politika + durumsal bağlam

```text
PROMPT 1 sözleşmelerini kullanarak Supervisor için kurallı güvenlik/yönlendirme katmanını uygula.

Güvenli davranışlar:
- Yol üstünde duman, yangın, fren kaybı, ciddi hararet, kaza, yaralanma vb. sinyaller için `roadside_emergency` değerlendirmesini yükselt; tek anahtar kelimeye körü körüne dayanma; belirsizlikte soru veya insan aktarımı.
- Açık insan temsilcisi isteğini `human_handoff_request` olarak ele al.
- 'İptal etmek istemiyorum' gibi olumsuzlamalarda `booking_cancel` eylemi planlanmasın.
- `booking_cancel`, `booking_create`, `booking_reschedule`, CRM yazmaları için zorunlu açık kullanıcı onayı, erişim doğrulama, idempotency, durum yeniden sorgulama ve Tool Gateway yetkisi iste.
- Teknik güvenlik uyarılarını, otomatik kesin arıza teşhisi ve sürüş güvenliği garantisi olarak sunma.
- ASR partial metninden kritik işlem başlatma; final transcript + state ile değerlendir.
- Tek görüşmede birden çok niyeti öncelik ve bağımlılıkla sırala; kritik tehlike varsa önce güvenlik ve insan yönlendirmesi.

Context Resolver yalnız izinli ve doğrulanmış konuşma alanlarını kullanmalı. 'Cuma' gibi göreli tarihleri görüşme tarihine ve Europe/Istanbul saat dilimine göre çözümlerken belirsizliği sakla; tarih kesinleşmediyse yazma işlemi yapma. Kişi ve araç bilgilerini müşteri doğrulaması olmadan ifşa etme.

Bağımsız pytest: negation, acil ve normal vaka ayrımı, human handoff, çoklu niyet sırası, izin kontrolü, timeout/fallback, bağlam izolasyonu. Her kural için gerekçe kodu döndür.
```

## PROMPT 3 — Çok etiketli Türkçe ML baseline (deneysel)

```text
PROMPT 1–2 sonucunu bozmadan offline ML pipeline ekle. İlk model XGBoost değil, ölçülebilir baseline:
- Türkçe için Unicode/Türkçe I/İ/ı/i bakımından kontrollü normalizasyon (orijinal metin ayrıca korunur).
- scikit-learn TF-IDF word n-gram (1,2) + character char_wb n-gram (3,5) FeatureUnion.
- 22 boyutlu multi-hot y, OneVsRestClassifier(LogisticRegression), sabit random_seed ve reproducible training CLI.
- Az veri / bazı sınıflar eğitimde hiç pozitif örnek içermiyorsa eğitim başarısızlığını açıklıkla raporla, uydurma test skoru üretme; yetersiz veri varsa yalnız rule-only mode çalışsın.
- Sentetik Türkçe utterance, konuşma dili, ek almış kelimeler, ASR hatası simülasyonları, negation, multi-intent ve OOD örneklerini ayrı seed/fixture olarak hazırla. Sentetik sonuçları gerçek performans diye sunma.
- İnsan onaylı eğitim verisi şeması ve PII maskeleme; etiket listesi ve katalog version'u zorunlu olsun.
- Train/validation/test ayrımı örnek bazlı değil, müşteri/konuşma/senaryo grup sızıntısını engelleyecek group split; tüm preprocessing sadece train verisine fit edilir.
- Her intent için eşik ayarı validation üzerinde; unknown/abstain; sınıf bazlı PR/F1, macro/micro F1, exact-match, OOD reject, latency p50/p95. Test setinde threshold ayarı yapma.
- Eğitim çıktısı model, pipeline, version, manifest, label index, dataset fingerprint, training seed; artefaktı insan onayı olmadan production'a alma.
- Devre dışı bırakılabilir feature flag.
```

## PROMPT 4 — Supervisor Orchestrator, Response Composer & Tool Gateway

```text
Supervisor'ı diyalog akışına bağla:
Input -> ASR Final -> Supervisor.classify() -> Policy/ExecutionPlan -> ToolGateway (guarded execution) -> Response Composer -> TTS.
Web ve AudioSocket entegrasyonu için kontrollü feature flag: SUPERVISOR_MODE=off|shadow|guarded.
```

## PROMPT 5 — React Supervisor Yönetim Paneli

```text
Operatör paneline Supervisor Kararları, Niyet Kataloğu, Karar İnceleme (Review/Accept/Reject) ve İnsan Onaylı Veri Seti Dışa Aktarma ekranı ekle.
```

