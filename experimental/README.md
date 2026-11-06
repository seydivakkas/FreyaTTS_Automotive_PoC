# experimental/

Bu klasördeki kod canlı çağrı yoluna (`backend.main` -> `app`) BAĞLI DEĞİLDİR.
`backend.main` içe aktarım grafiği çıkarılarak doğrulandı: aşağıdaki modüller
çalışma zamanında hiçbir yerden içe aktarılmıyor, yalnızca kendi testleri ve
birbirleri tarafından kullanılıyor.

| Modül | Not |
|---|---|
| `five_cuts_bargein_controller.py` | Beş kesimli barge-in denetleyicisi; canlı yolda `backend.audiosocket_server.TwoStageBargeInController` kullanılıyor. |
| `prosody_wsola_streamer.py` | WSOLA tabanlı örtüşmeli cümlecik akışı; canlı TTS yolunda çağrılmıyor. |
| `streaming_chunker_guard.py` | Akış parçalayıcı/çifte normalizasyon koruması; canlı yolda kullanılmıyor. |
| `asr_mapper.py` | ASR çıktısı kanonikleştirme; canlı yolda kullanılmıyor. |
| `normalizer.py` | Eski TTS normalleştiricisi; canlı yolda kullanılmıyor (canlı metin işleme `backend.text` ve `backend.automotive_frontend` içinde). |
| `legacy_src/` | Eski `src/` yeniden dışa aktarım (shim) dosyaları; her biri yalnızca `backend.*` modülünü yeniden dışa aktarıyordu, hiçbir canlı kod bunları içe aktarmıyor. |

Testler `experimental/tests/` altındadır ve `pyproject.toml` içindeki `testpaths`
ile toplanmaya devam eder. İçe aktarım yolu `experimental.<modül>` biçimindedir.

Bu modüller üretim davranışının kanıtı sayılmamalıdır. Bir modülü canlı yola almak
için önce `backend/` altına taşıyın ve ilgili testleri `tests/` altına geri alın.

Not: `backend.qa_telemetry_operator` canlı yoldadır (`backend.main` ve
`backend.acoustic_evaluation` içe aktarır) ve burada DEĞİLDİR; `compute_itu_mos`
canlı yolda çağrılmaz ve bir ölçüm değildir (bkz. işlevin docstring'i).
