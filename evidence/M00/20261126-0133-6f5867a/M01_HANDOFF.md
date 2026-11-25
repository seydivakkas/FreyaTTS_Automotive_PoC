# M01 devri — sözleşme sınırlarının bugünkü karşılıkları

Planlanan sözleşmeler (`interfaces.md` C1–C15) için kodda bugün bulunan karşılıklar. Adlandırılmış tür yoksa bugünkü değer biçimi yazılır; uydurma sınıf yoktur. Statik tarama; çalışma ile doğrulanmadı.

| Sözleşme | Bugünkü karşılık | Konum |
| --- | --- | --- |
| C1 AudioFrame | `AudioFrame` sınıfı (automotive_voice) + `contracts/audio_frame.metadata.schema.json`; canlı `backend/session.py` yolu ham `bytes` (PCM16) kullanır | `automotive_voice/core/audio.py:36` |
| C3/C4 Utterance / SpeechEvent | Adlandırılmış tür yok; `backend/audio.py:38` `Endpoint` sınıfı ve `session.py` içindeki bölüm (segment) baytları | `backend/audio.py`, `backend/session.py` |
| C5 ASRResult | Adlandırılmış tür yok; `backend/models.py:303` `transcribe(audio)` yalnız metin döndürür | `backend/models.py` |
| C6 TurnContext | Adlandırılmış tür yok; `dialogue.py` içindeki durum alanları | `backend/dialogue.py` |
| C7 ResponsePlan / DialogueResponse | Adlandırılmış tür yok; `session.reply(text)` düz metin ve cümlecik listesi | `backend/session.py:721` |
| C15 ToolReceipt | `contracts/booking_receipt.schema.json`, `contracts/m07_stream_receipt.schema.json`; `supervisor_write_receipts` tablosu | `contracts/`, DB |
| C8 SynthesisPlan | Adlandırılmış tür yok; `contracts/tts_input.schema.json`, `contracts/clause_plan_diagnostics.schema.json`, `contracts/normalization_result.schema.json` | `contracts/` |
| C9 AudioChunk | `AudioChunk` (ports) + `contracts/m06_audio_chunk_metadata.schema.json`; canlı yol `models.synth()` | `automotive_voice/ports/contracts.py:7`, `backend/models.py:224` |
| C10/C11 RenderedFrame / PlaybackEvent | Adlandırılmış tür yok; `contracts/m06_flush_request|ack`, `m06_transport_control`, `m06_media_format` şemaları | `contracts/` |
| C13 EventEnvelope | `EventEnvelope` + `contracts/event.schema.json` | `automotive_voice/core/events.py:61` |
| C14 Oturum anlık görüntüsü | `contracts/session_snapshot.schema.json`, `contracts/m10_durable_snapshot.schema.json` | `contracts/` |

Not: Depoda iki paralel yapı var — canlı `backend/` yolu ve `automotive_voice/` (M01–M11 entegrasyonu). M01 kanonik sözleşmeleri `backend/core/contracts/` altında kurarken her iki yolu uyumluluk adaptörüyle bağlamalıdır.
