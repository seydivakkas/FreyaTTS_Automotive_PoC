# M02 için AI Kodlama Ajanı — bağlayıcı görev

**Başlamadan:** `README.md`, `docs/07_M01_SOZLESMELER.md`, `docs/08_M01_KABUL_VE_M02_DEVIR.md`, `contracts/event.schema.json` ve `src/automotive_voice/core/*` dosyalarını oku. M01'in public API'sini bozma; `tests/test_core.py` ve `tests/test_m01.py` yeşil kalacak.

## Hedef

`ConversationStateMachine`/`ConversationReducer` kur: sahte VAD/STT/LLM/TTS/transport olaylarını al, `SessionManager`'ın geçiş metotlarını deterministik uygula. **Ses toplama, Freya GPU çıkarımı, gerçek SIP veya gerçek müşteri datası yok**. M11'e sakla.

## Minimum senaryolar

1. `session_started` → LISTENING; `transcript_final` → THINKING; mock LLM cevabı → SPEAKING; mock playout completed → LISTENING.
2. Barge-in: SPEAKING sırasında `vad_speech_started` → INTERRUPTING; önceki `GenerationId` derhal iptal edilir; `MediaOutput.flush()` istenir; **`media_flush_ack` gelmeden LISTENING'e geçme**.
3. Eski `generation_id` ile gelen audio chunk, geç kalan LLM/STT eventleri ve yanlış sıralı eventler etkisiz kalır; audit'e nedeni kaydedilir.
4. Session sonlanırken tekrar hangup/handoff işleminden ikinci yan etki çıkmaz; timeout durumlarında güvenli fallback.
5. Tüm deterministik akışlarda `event_id`, `turn_id`, `generation_id`, `sequence` ve UTC/mono saat doğrulanır.
6. Mock transport backpressure, sıra bozulması, duplicate callbacks ve cancellation yarışları için testler.

## Çıktılar

- `src/automotive_voice/core/conversation_reducer.py`
- gerekli port/olay tipleri ve bunlarla eşleşen `contracts` güncellemesi
- `tests/test_m02.py` ve sentetik CLI demo
- ADR, README/CHANGELOG, yeni PASS/FAIL matrisi

## Kabul

M01'in 28/28 testi + M02 testleri geçmeden, belge veya arayüz oluşturulmuş diye M02 tamamlandı yazma. M01'in RAM içi outbox'ını kalıcı kayıt sanma. Media flush ACK doğrudan `CancellationController`'ın yaptığı bir iş değildir; mock transport uyarlamasından doğrulanmalıdır.
