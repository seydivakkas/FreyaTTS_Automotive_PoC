# M02 Teknik Kabul / M03 Devri

## Bu pakette yapılanlar

- [x] Yeni `ConversationSignal` ve `Effect` sözleşmeleri + iki JSON şema.
- [x] `ConversationReducer`: VAD, STT final, LLM ready, TTS chunk, playout completed, flush ACK/timeout, handoff/hangup.
- [x] Barge-in: eski generation gecikmiş çıktılarını reddet, `FLUSH_MEDIA` ile ACK bariyeri koy.
- [x] Flush sırasında gelen `transcript_final` tutulur; onaylanmış ACK sonrası atomik yeni tur başlatılır.
- [x] Yanlış/tekrar olaylar ve input sıra atlamaları audit edilir; effect kuyruk doluluğunda state korunur.
- [x] Sentetik deadline ile timeout; emergency terminal close.
- [x] M01 public API geriye dönük uyumlu. Mevcut 320 test cümlesi korunur.
- [x] Unit/mock acceptance: M01 + M02 `python -m unittest discover -s tests -v`.

## M03’e devir sözleşmesi

`DialoguePolicy`: `transcript_ref` + session state bağlamı → tutarlı `response_ref` ve tool isteği üretir. Gerçek metin ayrı güvenli depoda tutulur; reducer'e ham transkript veya müşteri numarası eklenmez. Hedef: yalnız onaylı rezervasyon/CRM sonucu alındıktan sonra kesin onay cümlesi hazırlanması. Dönüş olayları sadece `llm_response_ready` olarak reducer'e gelmeli; `GenerationId` ve `TurnId` kontrolü yapılmalıdır. M01/M02 değiştirilmeden protokol adaptörleri uygulanmalıdır.

## Üretim öncesi kapalı konular

Kalıcı outbox/replay, en az bir kez teslim ve idempotent komut yürütme, gerçek PBX flush doğrulaması, canlı watchdog scheduler, gerçek TTS/STT/telefon testleri ve KVKK işleme/retention politikası henüz tamamlanmadı. Mevcut PASS kapsamı sadece mock kontrol düzlemini kapsar.
