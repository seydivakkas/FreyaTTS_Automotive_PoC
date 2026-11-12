# FREYA FQICI v2 — Kanıt Sözleşmesi, İdempotent Analiz ve Cursor Uygulama Planı

**Belge türü:** Önerilen mimari + Cursor uygulama promptları. **Bu belge kodun uygulandığını veya testlerin geçtiğini iddia etmez.**

**Kaynak durumu:** Aşağıdaki repo gözlemleri kullanıcı tarafından aktarılmıştır. Cursor, gerçek depodaki dosyaları yeniden açıp yerinde doğrulamalıdır. Bu belge yerel Windows yollarının doğrudan doğrulandığı anlamına gelmez.

## 0. Tasarım sınırları ve repo denetim noktaları

- Kod referansları: `backend/supervisor/quality.py` (Supervisor kalite/inceleme); `backend/milestones.py` (oturum günlüğü); `backend/session.py` (Turn kayıtları ve `close()`); `backend/audiosocket_server.py` (AudioSocket çağrı UUID'si); `backend/supervisor/gateway.py` (tool timeout); `backend/deps.py` (paylaşılan admin auth); `docs/ARCHITECTURE.md` (ses metrikleri); `data/m11/M11_ACCEPTANCE.json` (gerçek telefon kabulü).
- Kullanıcı incelemesindeki durum: Supervisor izleri web oturumlarıyla sınırlı; session-end kalite kontrolü yalnızca tekrarlanan açıklama isteklerini işaretliyor. Bu kapsam genişletilmeden önce olay sözleşmesi gerekli.
- Fiziksel Asterisk/SIP entegrasyonu kabulü `HOLD`; sentetik AudioSocket ile gerçek telefon testi birbirine karıştırılmayacak.
- FreyaTTS-small / Leyla voice lock, Windows-first, offline-first, canlı ses yolu ve mevcut servisler korunacak.
- FQICI çağrı SONRASINDA, düşük öncelikli çalışır; canlı çağrıda zorunlu LLM/analiz bloklaması yoktur.

## 1. Değişmez ilkeler

1. **Kanıt hiyerarşisi:** Doğrulanmış olaylar ve referans etiketler > insan inceleme kararı > yerel AI önerisi. Yapay zekâ önerisi tek başına kesin bulgu değildir.
2. **Mahremiyet kapsamı:** Varsayılan olarak FQICI deposu ham ses, ham ASR transkripti, asistanın tam metni, telefon, plaka, ad, VIN, token veya API cevabı saklamaz. Mevcut Freya `Turn` saklaması ayrı bir sistem olarak envanterlenir; FQICI politikası bunu otomatik olarak değiştirmiş sayılmaz. Tüm Freya genelinde ham transkript yasağı uygulanacaksa bu ayrı ürün kararı, migration ve güvenli saklama incelemesi gerektirir.
3. **Ayrı izinler:** `review_allowed`, `training_allowed`, `export_allowed` birbirinden bağımsızdır; kayıt/ses işleme hukuki dayanağı ve saklama süresi ayrıca yönetilir. `review_allowed=true`, `training_allowed=true` anlamına gelmez. Geçerli hukuki dayanak/rol/saklama yoksa ilgili işlem durdurulur.
4. **Olgu/yorum ayrımı:** `tool.timeout` yalnızca yanıtın belirtilen sürede alınmadığını kanıtlar; işin commit edilmediğini kanıtlamaz. `tts.synthesis_ready` kullanıcıya sesin ulaştığını kanıtlamaz. `barge_in.signal_emitted` oynatmanın gerçekten durduğunu kanıtlamaz.
5. **İdempotency:** Aynı kapanış olayı tekrarlandığında veya süreç yeniden başladığında aynı **analiz kapsamı + kanıt parmak izi + kural sürümü** için en fazla bir kalıcı analiz işi bulunur. Geç gelen olay veya kural değişimi yeni analiz sürümü oluşturabilir.
6. **İnceleme append-only:** İnsan kararları üzerine yazılmaz. Yeni kanıtla oluşan `run_id` eski onayı otomatik devralmaz; ilgili dataset manifestleri bağımlılık üzerinden yeniden değerlendirilir.
7. **Kimlik:** Kimliği doğrulanmayan paylaşılan `admin` ile çok kişi bazlı denetim iddiası kurulmaz. İlk fazda tek yetkili, sınırlandırılmış pilot kabul edilir veya doğrulanabilir kişi bazlı kimlik eklenir. Export yetkisi ayrı koruma ister.
8. **Başarı semantiği:** `session_closed` = oturum teknik olarak kapandı; `call_outcome` = telefon görüşmesinin durumu; `business_outcome` = randevu/işlemin sonucu. Hiçbiri diğerini otomatik olarak PASS yapmaz.
9. **Model güncellemesi yok:** AI Judge, XGBoost, sözlük veya LLM ağırlıklarını kendiliğinden güncellemez. Onaylı örnekler yalnızca sürümlü bir aday veri setine alınabilir.

## 2. Olay şeması (v1, uygulanmadan önce repo ile teyit edilecek)

Önerilen ortak zarf:

```json
{
  "schema_version": "fqici.event.v1",
  "event_id": "uuid-or-stable-producer-key",
  "producer": "web_session|audiosocket_adapter|supervisor|tool_gateway|tts|review",
  "source_event_id": "stable-within-producer",
  "source_mode": "WEB|AUDIOSOCKET_SYNTHETIC|SIP_REAL",
  "event_type": "tool.timeout",
  "session_id": "session-opaque",
  "call_id": null,
  "turn_id": "turn-opaque-or-null",
  "operation_id": "business-operation-or-null",
  "attempt_id": "attempt-or-null",
  "occurred_at_utc": "2026-11-10T01:00:00.000Z",
  "observed_at_utc": "2026-11-10T01:00:00.013Z",
  "clock_domain_id": "optional-monotonic-clock-domain",
  "monotonic_offset_ms": null,
  "privacy_policy_version": "policy-v1",
  "sanitized_payload": {"timeout_ms": 4000}
}
```

- `call_id` telefon bağlantısı kimliğidir; web oturumunda NULL olabilir. `session_id` Freya görüşme oturumu; `turn_id` kullanıcı/assistant turu; `operation_id` tek iş semantiği, `attempt_id` retry/deneme kimliği. `call_id` ile AudioSocket UUID eşleşmesi güvenilir adapter kaydıyla oluşturulmalı; yoksa **unmapped**.
- `event_id` kararlı/idempotent olmalıdır. UUID rastgele yeniden üretilerek aynı kaynak olayı iki farklı olay gibi kaydedilmemeli. DB benzersizliği en az `(producer, source_event_id)` üzerinde sağlanır.
- UTC duvar saati arşiv/sıralama içindir; ayrı süreçlerin monotonic saatleri doğrudan çıkarılamaz. Aynı `clock_domain_id` içinde geçerli monotonic ölçüm veya açıkça tanımlanmış ortak clock kalibrasyonu olmadan gecikme metrikleri hesaplanmaz.
- Kullanıcı metni serbest biçimde `sanitized_payload` içine koyulamaz. Alanlar event type için **allowlist** doğrulamasından geçirilir. Tanınmayan alanlar loglanmadan düşürülür veya reddedilir; redaksiyon tek savunma değildir.
- Ses oynatılma durumunu bildiren uç/telefon `playback_confirmed` olayı ancak gerçekten böyle bir geri bildirim kaynağı doğrulanırsa üretilebilir. Socket `send()` başarılı dönüşünü playback onayı olarak işaretleme.

### 2.1 Olay–kanıt matrisi (uygulanacak tablo)

| Olay | Aday üretici | İzinli payload örnekleri | Neyi destekler / neyi kanıtlamaz |
|---|---|---|---|
| `session.closed` | `backend/session.py` | `closure_reason`, `session_end_state` | Session kapanışı; iş başarısını kanıtlamaz |
| `transport.disconnected` | AudioSocket adapter | `disconnect_reason`, `transport_code` | Bağlantı kesildi; müşterinin isteği tamamlandı demek değil |
| `session.recovered` | startup/recovery | `recovery_reason`, `prior_run_key` | Yeniden başlatma kurtarması; yeni çağrı oluşturmaz |
| `asr.finalized` | ASR adapter | `turn_id`, `duration_ms`, `language_code`, `redaction_state` | ASR üretildi; WER ölçümü için referans yok |
| `supervisor.route_selected` | Supervisor | `intent_ids`, `router_version`, `score_bucket`, `decision_source` | Seçilen route; doğru niyetin kanıtı değil |
| `supervisor.clarification_requested` | Supervisor | `reason_code`, `turn_id` | Açıklama istendi; tek başına yanlış route değil |
| `tts.synthesis_ready` | TTS adapter | `segment_id`, `synthesis_ms`, `voice_id_hash` | Ses üretim hazır; duyulma değil |
| `audio.transport_write_accepted` | AudioSocket/web adapter | `segment_id`, `bytes`, `transport_id` | Taşıyıcıya aktarım denendi/kabul edildi; oynatıldı değil |
| `audio.playback_confirmed` | Yalnız doğrulanmış playback receiver | `segment_id`, `confirmation_type` | Oynatım kanıtı varsa; gerçek SIP'te destek yoksa `UNOBSERVABLE` |
| `barge_in.signal_emitted` | Turn Manager | `turn_id`, `signal_time_ms` | Durdur sinyali verildi; ses gerçekten kesildi değil |
| `barge_in.playback_stopped` | Doğrulanmış output adapter | `segment_id`, `stop_ack_type` | Adaptör durdu; uçtaki duyulma sonucu olmayabilir |
| `tool.attempt_started` | Tool Gateway | `operation_id`, `attempt_id`, `tool_name`, `timeout_ms` | Başlatılan deneme |
| `tool.timeout` | Tool Gateway | `operation_id`, `attempt_id`, `elapsed_ms` | Cevap gecikti; commit başarısızlığını kanıtlamaz |
| `tool.commit_observed` | Transactional backend | `operation_id`, `commit_state`, `record_ref_hash` | Commit durumuna ilişkin kaynak kanıtı; salt timeout yerine kullanılmalı |
| `tool.final_outcome_reconciled` | Gateway/DB verification | `operation_id`, `terminal_state`, `verified_at` | İş sonucu teyidi (başarılı/başarısız/bilinmiyor) |
| `assistant.outcome_claimed` | Response Composer | `operation_id`, `claim_type`, `message_ref` | Asistanın başarı beyanı oluşturuldu; müşteriye ulaştığı değil |
| `assistant.claim_delivery_confirmed` | Uç/transport kanıtı varsa | `operation_id`, `delivery_type` | Duyuruldu iddiasını destekleyebilir; yoksa belirsiz |
| `privacy.permission_changed` | Yetkili privacy kontrolü | `subject_key_hash`, `permission_type`, `allow`, `policy_version` | İzin durumu; izin iptalini datasetlere yaymak gerekir |
| `quality.review_decision_added` | Review API | `review_id`, `finding_id`, `decision`, `actor_id` | İnsan kararı; kaynak kanıtı revize olduğunda otomatik geçerli değildir |

Her satır için Cursor **gerçek kaynak sembolünü, WEB/SYNTHETIC/REAL destek düzeyini, timestamp üreticisini, saat alanını, storage izinlerini, gizlilik gerekçesini ve PASS/PENDING/HOLD** alanlarını ekleyerek ayrı `docs/fqici/event_evidence_matrix.md` dosyası hazırlamalıdır. Bu tablo nihai entegrasyonun kanıtı değil, başlangıç sözleşmesidir.

### 2.2 Kanıt → bulgu kuralları

| İddia | CONFIRMED için zorunlu kanıt | Diğer durumda |
|---|---|---|
| Yanlış intent routing | Referans intent etiketi/insan kararı + ilgili `route_selected` ve bağlam | `NEEDS_REVIEW`, `MISSING_REFERENCE` |
| TTS yanlış telaffuz | Sese erişim/uygun kayıt + yetkili fonetik değerlendirme veya güvenilir doğrulanmış akustik kıyas | `NEEDS_REVIEW`, `NEEDS_AUDIO_REVIEW` |
| ASR WER/CER | ASR çıktısı + aynı ses örneğine ait doğrulanmış referans transkript | `INSUFFICIENT_EVIDENCE`, `MISSING_ASR_REFERENCE` |
| Tool timeout | Aynı attempt için `tool.attempt_started` + `tool.timeout` | Timeout doğrulanır, iş başarısı bilinmez |
| Yanlış 'işlem başarılı' iddiası | `operation_id` eşleşen terminal `FAILED/NOT_COMMITTED` kanıtı + `assistant.outcome_claimed=SUCCESS`; gerçekten iletildi iddiası için ayrıca teslim kanıtı | Başarı beyanı uyuşmazlığı `SUSPECTED`/inceleme; timeout tek başına başarısızlık değildir |
| İlk ses gecikmesi | Aynı konuşma turu ve karşılaştırılabilir saat alanlarıyla açıkça tanımlanmış başlangıç/bitiş | Ölçüm dışı; değeri 0 yapma |
| Barge-in gecikmesi | Durdurma tetikleyicisi + gerçek durdurma ack'i, aynı saat domain'i | Sadece sinyal süresini ölç, uçta durdurma iddia etme |
| Gereksiz uzun yanıt | İşlem/tur süreleri + etiketli kalite kriteri | Yalnız 'review candidate', kesin kalite hatası değil |

**Durum sözleşmeleri:**

- `EvidenceStatus`: `CONFIRMED`, `SUSPECTED`, `NEEDS_REVIEW`, `INSUFFICIENT_EVIDENCE`.
- `reason_code`: `NEEDS_AUDIO_REVIEW`, `MISSING_REFERENCE`, `MISSING_ASR_REFERENCE`, `CLOCK_DOMAIN_MISMATCH`, `OUTCOME_UNKNOWN`, `MISSING_DELIVERY_PROOF`, `CONSENT_REQUIRED`, `UNSUPPORTED_SOURCE` vb.
- `ReviewState`: `PENDING`, `APPROVED`, `REJECTED`, `NEEDS_MORE_EVIDENCE`, `SUPERSEDED`.
- `EvaluationRunState`: `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED_RETRYABLE`, `FAILED_TERMINAL`, `SUPERSEDED`.
- Bu alanlar birbirine karışmayacak. Örnek: `EvidenceStatus=NEEDS_REVIEW, reason_code=NEEDS_AUDIO_REVIEW, ReviewState=PENDING, EvaluationRunState=SUCCEEDED`.

## 3. Minimum kalıcı veri modeli ve idempotency

```text
CallIdentityMap(session_id PK, call_id UNIQUE NULLABLE, source_mode,
                transport_uuid NULLABLE, mapping_provenance, created_at_utc)
CallEvent(event_id PK, producer, source_event_id, schema_version, event_type,
          session_id, call_id?, turn_id?, operation_id?, attempt_id?,
          occurred_at_utc, observed_at_utc, clock_domain_id?,
          monotonic_offset_ms?, privacy_policy_version, sanitized_payload)
UNIQUE(CallEvent.producer, CallEvent.source_event_id)

EvaluationRun(run_id PK, scope_id, event_set_hash, rule_version,
              run_state, created_at_utc, started_at_utc?, completed_at_utc?,
              attempt_count, worker_lease_until?)
UNIQUE(EvaluationRun.scope_id, EvaluationRun.event_set_hash, EvaluationRun.rule_version)

QualityFinding(finding_id PK, run_id FK, rule_id, category, severity,
               evidence_status, reason_code?, evidence_event_ids[],
               statement, suggested_action, created_at_utc)

ReviewDecision(review_id PK, finding_id FK, run_id FK, actor_id,
               decision, corrected_label?, justification,
               decision_at_utc, supersedes_review_id?)
# INSERT ONLY; geçmiş kararlar güncellenmez.

DatasetExample(example_id PK, source_run_id FK, finding_id FK,
               approved_review_id FK, data_scope, sanitized_data,
               permissions_snapshot, example_hash, created_at_utc,
               active_or_revoked)
DatasetManifest(manifest_id PK, dataset_version, sha256, item_count,
                created_at_utc, policy_version, status)
DatasetManifestItem(manifest_id FK, example_id FK, status)
```

- Eğer mevcut şema/ORM farklıysa aynı garantileri koruyarak adaptasyon yapılır; yeni bir DB zorunlu değildir.
- Event-set hash: **kanonik ve sıralı** listede yer alan `(event_id, normalized_payload_hash)` + gerekli kimlik ve kapsam alanlarının hash'i. Anlamsız ingestion sıra farkı yeniden analiz yaratmamalı. Kural sürümü (`rule_version`) immutable.
- Transactional insertion: event ekle, scope'daki kapanış durumunu güncelle, `EvaluationRun` için `INSERT ... ON CONFLICT DO NOTHING` / eşdeğer atomik işlem kullan. Eşzamanlı kapanışta `SELECT THEN INSERT` tek başına güvenli değildir.
- Worker için kalıcı job storage, sınırlı kuyruk, leased claim, crash recovery, retry politikası uygulanır. **Exactly once execution** vaat edilmez; tekrar yürütme mümkün, kalıcı run sonucu/idempotent yan etki **at most one** olacak.
- Geç gelen geçerli kanıt yeni `event_set_hash` ile yeni run oluşturur. İlgili eski bulgular `SUPERSEDED` ile ilişkilendirilir; eski onay yeni run'a taşınmaz. Yayımlanmış manifestler yeniden denetim için `REVALIDATION_REQUIRED` durumuna geçirilir.
- İzin iptalinde ilgili örnekler ve manifest öğeleri doğrudan izlenebilir olmalı; export engellenir, yeni manifest oluşturulur. Daha önce dışa aktarılmış dosyalar otomatik olarak geri alınamaz: export audit kayıtları üzerinden erişilebilen kopyalara silme/güncelleme prosedürü uygulanır; mümkün olmayanlar açıkça raporlanır.

## 4. Kabul kapıları (sürüm çıkışından önce sınırlar sabitlenecek)

### P0 kabul

1. **Duplicate close/restart:** Aynı kapanış olayı 10 kez iletilse, worker yeniden başlatılsa ve paralel 2 tüketici çalışsa bile aynı `(scope_id, event_set_hash, rule_version)` için veritabanında **tam 1 kalıcı EvaluationRun** (ve 1 mantıksal job) bulunmalı. Bu, idempotent insert testleriyle kanıtlanmalı.
2. **Outcome ayrımı:** `session.closed` tek başına `business_outcome=SUCCESS` üretmez. Normal kapanış, beklenmedik bağlantı kesintisi ve kurtarılan oturum ayrı fixture.
3. **Privacy:** İzinli alan listesinde olmayan serbest metin, telefon, VIN, plaka, token, ham ses event depoya veya uygulama loguna sızmaz. Mevcut `Turn` saklaması ayrıca incelenir; gizlilik politika değişikliği olmadan sessizce silinmez.
4. **Evidence:** Farklı `operation_id`/`attempt_id` değerleri birleştirilerek kesin hata üretilmez. `timeout` sonrası commit senaryosu yanlış 'işlem başarısız' hükmü üretmez.
5. **Audio:** `tts.synthesis_ready` ve `audio.transport_write_accepted` gerçek playback kanıtı sayılmaz. AudioSocket sentetik kabul fiziksel SIP kabulüne dönüştürülmez.
6. **Review:** Eski kararı ezme yok; `run_id` değişince önceki onay yeni veri setine otomatik taşınmaz. `review_allowed` ve `export_allowed` ayrı sınanır.
7. **Security:** Doğrulanmış kişi kimliği olmadan çok kullanıcılı review/export açılmaz. Tek yetkili pilot açıkça belgelenir; üretim rol kontrolü yoksa export `HOLD`.

### P1 performans kabul taslağı (ölçümlerden önce config'de sabitlenecek)

- Konfigürasyon başlangıç önerisi: `max_queue_jobs=500`, `max_wait_s=300`, `max_worker_concurrency=1`; bunlar **ölçülmüş kapasite değildir** ve hardware/iş yüküne göre incelenecektir.
- Live ses etkisi: Worker **kapalı / açık / dolu kuyruk** için karşılaştırılabilir sentetik yük testleri. Her koşulda en az 50 geçerli turn hedefi; sayılar ve dışlama nedenleri raporlanır. Önerilen ön kapı: p95 ilk-ses gecikme farkı **en fazla +%5 veya +50 ms (hangisi daha kısıtlayıcıysa)**. Bu eşikler projeye uygunluğu testle doğrulanmadan PASS değildir.
- Kuyruk bekleme metriğinde `N`, `N_valid`, `N_excluded` ve dışlama nedenleri zorunlu. Worker yoğunlukta canlı sesin önceliğini korumalı; limit doluysa fail-safe olarak FQICI işi ertelemeli veya kontrollü düşürme politikası uygulamalı, görüşmeyi bloklamamalı.
- Gözlem penceresi, CPU/GPU RAM kullanımı, örneklerin aynı donanım ve sıcaklık koşullarında toplanma yöntemi raporlanır. Gerçek RTX 4070 ölçülmediyse kaynak PASS yazılmaz.

## 5. Cursor prompt sırası ve duraklama kapıları

### PROMPT 0 — Repo gerçeklik denetimi / yalnız inceleme (TAMAMLANDI -> docs/fqici/00_repo_evidence_audit.md)
### PROMPT 1 — Web + sentetik AudioSocket olay–kanıt matrisi (TAMAMLANDI -> docs/fqici/event_evidence_matrix.md)
### PROMPT 2 — Kalıcı olay ve tekilleştirilmiş analiz işi (TAMAMLANDI -> backend/fqici/, tests/test_fqici_queue.py)
### PROMPT 3 — Deterministik Quality Analysis Engine (SIRADAKİ ADIM)
### PROMPT 4 — Append-only insan incelemesi ve kimlik politikası
### PROMPT 5 — Dataset provenance, izin iptali, manifest
### PROMPT 6 — React dashboard ve performans kabulü
### PROMPT 7 — İsteğe bağlı AI Judge (sonraya bırakılan araştırma)
### PROMPT 8 — Uçtan uca sentetik regresyon ve M11 ayrımı

