# M04 — AI Coding Agent Uygulama Talimatı

**Girdi:** Bu M03 ZIP'i, eski A00/A01 ve A01-YT golden test setleri, `docs/15_M03_SOZLESME_VE_IS_KURALLARI.md`.

**Değişmez sıra:** Önce çekirdek özellikler -> UI -> sentetik entegrasyon -> en son gerçek ses ve telefon kabulü. Gerçek FreyaTTS WAV, YouTube ses klibi, GPU, VAD mikrofon ve SIP testi çalıştırma.

**Kırılmaması gereken API:** `automotive_voice.core.*`, `conversation.*`, `dialogue.*`. Bir yerde sözleşme değişimi gerekiyorsa önce sürümlemeli migration dokümanı hazırla. Mevcut golden 320 metni değiştirme.

**Yapılacaklar:**

1. `src/automotive_voice/nlp/` altında deterministik, Unicode normalizasyonlu ve locale-aware Türkçe sayı/tarih/saat/fiyat ön işlem API'si oluştur.
2. `AutomotiveLexicon` için `(surface_form, normalized_form, suffix_rule, pronunciation, approved, source_ref, reviewer)` alanları ve yalnız onaylı rule export.
3. Qashqai/Peugeot/Citroën/Škoda / Türkçe ekler ve 16 sorunlu karakter vakası için fail-closed pozitif/negatif testler.
4. Serbest ASR transkriptini `DialogueInput`'a dönüştüren **mock deterministic NLU parser** sözleşmesini tanımla; belirsiz slotu uydurma, timezone sakla.
5. Sözlük override etki analizini 320 cümlede hesapla; ölçülmemiş ses kalitesini başarılı gösterme.
6. Önce API/testler, sonra M04 karar raporu ve M05 devir talimatı.

**Kabul:** M01/M02/M03 regresyon, yeni Unicode ve Türkçe morfoloji testleri, JSON Schema doğrulaması, ses kullanılmadan sentetik testler; hiçbir müşteri verisi audit'e yazılmayacak.
