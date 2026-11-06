# ADR-0002 — Gerçek ses/saha testlerini M11'e ertele
**Durum:** Kabul önerisi
**Karar:** M00–M10'da yalnız sahte/sentetik ses metaverisi, text fixtures ve fake adapters. Gerçek Freya TTS WAV, YouTube klip, GPU ölçümü, MOS, WER, CER, fiziksel SIP aramaları M11'de. **İstisna:** Unit, contract, property testleri ve statik testler baştan zorunlu; “testleri en sona bırak” anlamına gelmez. **Risk:** Akustik uyumsuzluklar geç ortaya çıkabilir. **Azaltım:** AudioFormat schema, örnekleme meta verisi, 20 ms frame ve flush sözleşmeleri erken doğrulanır.
