# M02 Yerel Doğrulama Raporu

**2026-10-31 — mock kontrol düzlemi; gerçek model/ses/telefon kullanılmadı.**

## Komutlar

```bash
PYTHONPATH=src python -m unittest discover -s tests -q
PYTHONPATH=src python -m automotive_voice.m02_demo
```

## Gerçekleştirilen doğrulamalar

| Doğrulama | Sonuç |
|---|---|
| M01 geriye dönük otomatik regresyon | 28 / 28 PASS |
| M02 reducer, barge-in, ack, handoff, duplicate, watchdog ve backpressure | 24 / 24 PASS |
| Toplam otomatik test | 52 / 52 PASS |
| JSON Schema Draft 2020-12 metadata: signal/effect | Şema ve örnek instance PASS (`jsonschema` ile) |
| JSON Schema Draft 2020-12 metadata: M01 event | Şema PASS |
| Sentetik CLI akışı | PASS |
| Eski 320 cümlelik JSON test verisinin SHA-256 korunması | PASS: `7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e` |
| Gerçek Freya ses/YouTube/GPU/Asterisk | NOT RUN — M11 |
| Windows Python 3.11 | NOT RUN (yerel Linux Python 3.13 ile doğrulandı) |

## Testlerin anlamı

Yalnız **state ve command oluşturma mantığı**, eşzamanlı işlemler, sıralama, tampon taşıma gereksinimi ve hata durumları doğrulanmıştır. M02 `FLUSH_MEDIA` mesajı üretir; gerçek Asterisk tamponunun temizlendiğine dair kanıt üretmez. Gerçek adaptör ACK'i, kalıcı transaction log, crash recovery, dedup sonrası kesin teslim garantisi ve güvenli restart ayrıca gereklidir.

## İşlem sırası

`session_opened -> vad_speech_started -> transcript_final -> llm_response_ready -> audio_chunk_ready -> vad_speech_started (barge-in) -> transcript_final (deferred) -> media_flush_ack -> llm_response_ready -> playout_finished -> hangup`.

**Karar:** `M02_MOCK_CORE_PASS / M01_REGRESSION_PASS / TELEPHONY_HOLD / REAL_AUDIO_HOLD / PRODUCTION_HOLD`. M03 diyaloğa geçiş için kabul.
