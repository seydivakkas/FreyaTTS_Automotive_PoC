# M09 — Deterministik Sentetik Uçtan Uca Entegrasyon Mimarisi

## Tek oturum otoritesi

Her `ScenarioRunner` kendi `SessionManager(EventBus())` ve `ConversationReducer` örneğini oluşturur. **Aynı senaryo içindeki bütün oturumlar** bu tek M01/M02 durum otoritesini paylaşır. M03 `DialoguePolicy`, M04 `DeterministicNLU`/`NLUReferenceBridge`, M05 `ProsodyCoordinator`/`MockTTS`, M06 `MediaBuffer`/`MediaCoordinator`/`FakeTransport`, M07 `AdapterSupervisor`/`SyntheticStreamBridge` aynı otoriteye bağlanır.

M08 bir operatör kontrol katmanıdır. `/api/action {action:"run_scenario",scenario:<allowlisted>}` yeni izole bir `ScenarioRunner` çalıştırır, yalnızca PII içermeyen rapor projeksiyonu saklar. Bu izole oturumlar ana M08 oturum listesinde gerçek çağrı gibi gösterilmez. Senaryoların audit izleri ve güvenli sayaçları `scenario_reports` alanından izlenir.

## İşlem sırası

1. `SESSION_OPENED`: M02/M01 dinlemeye geçer.
2. M04 NLU sahte müşteri metnini **yerel ve geçici** yorumlar; M03 `ReferenceStore` içine tipli `DialogueInput` konur, olayda yalnızca opak `reference` bulunur.
3. `TRANSCRIPT_FINAL` M02'de `REQUEST_LLM` efekti üretir. M07 sanal saat ile sahte LLM sonucunu kabul eder; M03 `DialogueCoordinator` gerçek deterministik `DialoguePolicy` kararını üretir. **M07 sahte LLM metni karar otoritesi değildir.**
4. M03 yanıtı `LLM_RESPONSE_READY` ile M02'ye iletilir; `START_TTS` efektindeki yanıt referansı M04 normalizer ve M05 clause planner tarafından değerlendirilir.
5. M05 `review_required` döndürürse gerçek veya sahte medya gönderilmez. Bu durum ayrı tutulur. M09'daki `control_only_playout` yalnızca test oturumunu bir sonraki işe ilerletebilen **sözlü yanıt verilmediği bilinen** kontrol-plane simülasyonudur, tamamlanmış sesli etkileşim kabulü değildir.
6. Uygun metinler M07 sahte TTS adaptörü ve sanal saat üzerinden geçerek M06'da PCM16/16kHz 20 ms **yalnızca metaveri** oluşturur. Gerçek ses baytı `0`.
7. Söz kesilirse `VAD_SPEECH_STARTED` ile eski nesil iptal edilir, `FLUSH_MEDIA` M06'ya yönlendirilir. Sonraki durum `INTERRUPTING`; yalnızca `FakeTransport.confirm_flush` tarafından açıkça üretilen sahte ACK M02'nin dinlemeye geçmesini sağlar. Yanlış ACK ya da ACK yokluğu hâlinde dinlemeye dönülmez. Sanal watchdog timeout `FAILED` sonucuna götürür.
8. CRM/rezervasyon sadece M03 sahte portlarındadır; yalnızca `CONFIRMED` hizmet sonucu geçerli randevu statüsü yaratır. İdempotency denetimi korunur.

## Geriye uyumlulukta zorunlu küçük onarım

- M03 `DialogueCoordinator(..., clock_ns=...)` parametresi eklendi. Parametre verilmezse önceki davranış **aynen** sürer; M09'da M02/M07 sanal saati kullanılır. Önceden gerçek monoton saatle üretilen M03 olayları sanal M02 saatine göre regresyon yaratıyordu.
- M04 NLU'da `temsilciye`, `temsilciyi`, `temsilciyle`, `temsilcinin`, `temsilciden` varyantları tanınır; önceki `temsilci` eşleşmesi korunur.
- M08 yerel konsoluna allowlist ile korunan yeni senaryo kontrol ekranı eklenmiştir. SQLite bağlantıları explicit close edilir; eski salt-okunur kaynak ilkesi sürer.

## Güvenlik ve gözlemlenebilirlik

- Hiçbir ham transkript M02 olay zarflarında, M08 senaryo raporunda veya telemetride tutulmaz.
- Gerçek CRM, santral, mikrofon, video, model, GPU, internet çağrıları yok.
- M08 localhost, CSRF/Origin/Host kontrolleri korunmuştur.
- Fiziksel gecikme, MOS, WER veya ses kalitesi hakkında sonuç çıkarılmaz.
- Olay kuyruğu, snapshot ve senaryo raporları RAM içindedir. Çökme sonrası kurtarma ve kalıcı idempotency henüz garanti edilmez.
