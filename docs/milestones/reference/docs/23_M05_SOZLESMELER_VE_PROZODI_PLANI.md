# M05 — Prosody / Clause Planner & TTS Input Contract

## Kapsam ve değişmezler

- M01–M04 public API ve 320 cümle değişmedi. Modüller `automotive_voice.prosody` altında **eklendi**.
- M04 `NormalizationResult` dışında ham ASR ile doğrudan TTS planı oluşturulmaz.
- `NormalizationResult.review_required=True` veya M05 güvenlik incelemesi durumunda `ClausePlan.tts_inputs()` **boş**.
- A01-YT `approved` olmayan marka okunuşları tahmin edilmez. 3 sözlü izin beyanı **0 akustik anotasyon** anlamına gelir; onaylı aktif kural: 0.
- Her plan ve TTS girdisi **M01 güçlü kimlikleri** `SessionId`, `TurnId`, `GenerationId` taşır.
- `TTSInput.text` yalnızca bellek içi yerel servis sınırıdır; `EventEnvelope` ve telemetriye konulamaz. Loglarda yalnız `safe_metadata()` kullanılmalı.

## Sözleşmeler

| Nesne | Veri | Değişmez |
|---|---|---|
| `PhraseBoundary` | `start`, `end`, `kind`, `evidence` | Unicode karakter ofsetleri, `[start,end)`; tek clause içinde |
| `Clause` | `index`, `start`, `end`, `text`, `break_kind`, `pause_after_ms`, `delivery_hint` | Normalleştirilmiş metinden kayıpsız parça, immutable |
| `ClausePlan` | kimlikler, `spoken_text`, `status`, `clauses`, `protected_spans`, `warning_codes` | Kayıpsız bölme, onay kapısı |
| `TTSInput` | kimlikler, indeks, metin SHA-256, pause ve delivery ipuçları | Yalnız `READY` plandan üretilebilir, bellek içi |
| `PlanningResult` | durum, neden, kaç parça kuyruğa alındı | Müşteri metni içermez |

### Korunan ifade türleri

1. **Para**: `bir milyon iki yüz elli bin Türk lirası` ve kuruşlu biçimler.
2. **Tarih**: `üç kasım iki bin yirmi altı`, ay ve sayı kelimeleri.
3. **Saat**: `saat on dört otuzda`; ayrıca M04 kaynak metninden `14:30` tespit edilirse dönüşmüş karşılığı.
4. **Motor**: `bir nokta beş TSI`, farklı motor kısaltmaları; `TSI` için Türkçe büyük-I eşleşme hatası giderildi.
5. **Mesafe ve model yılı**: `yüz kırk beş bin kilometre`, `iki bin yirmi dört model`.
6. **Marka/model/ek**: `Nissan Qashqai'nin`, `Škoda` gibi adların **yazımı** korunur. Bu eşleştirme fonetik onay değildir. Onaylı sözlük okunuşları ayrıca korunur.

Korunan aralıklar üst üste biniyorsa birleştirilir; bunların içine clause sınırı yerleştirilemez. Çok uzun atomik aralık bölünmeden bırakılır, `overlong_atomic_span` inceleme koduyla TTS bloke edilir.

### Parçalama ve prozodi

Nokta/soru işareti cümle sonu; virgül/noktalı virgül/iki nokta yumuşak sınır; karakter ve kelime limiti son çare sınırıdır. Parantez içi noktalama dış clause yaratmaz. `pause_after_ms` ve `delivery_hint` **akustik çıktı değil**, sonraki TTS adaptörünün kullanacağı metinsel kontrol işaretleridir. SSML ve motor seed'ine müdahale edilmez.

### M02/M03 ile bağlantı

```text
M03 ReferenceStore.put_response(session, text, category)
    ↓ yalnız response_ref; M02 START_TTS effect
ProsodyCoordinator.process(EffectKind.START_TTS)
    ↓ M01 SessionManager state/turn/generation doğrulaması
ReferenceStore.get_response(session, ref)  [oturum izolasyonu]
    ↓ M04 NormalizationResult, A01-YT approval gate
ProsodyClausePlanner.plan(...)
    ↓ READY ise TTSInput[]
MockTTS.enqueue / pop_next()  [yeniden kuyruk/çıkış kontrolü]
    ↓ M06 gelecekteki ses transport/adapter portu
```

M01 `SPEAKING` ve aynı turn/generation **olmadan** kuyruğa alma ya da kuyruktan alma mümkün değildir. Barge-in önceki generation'ı geçersiz kılar. İki farklı metin aynı `(session,turn,generation,clause_index)` anahtarıyla gelirse `conflicting_replay` reddedilir; aynı metin yinelenirse `duplicate_ignored` olur.

### JSON şemaları

- `contracts/phrase_boundary.schema.json`
- `contracts/tts_input.schema.json` (**özel bellek sınırı**)
- `contracts/clause_plan_diagnostics.schema.json` (**loglanabilir metaveri**)

Hepsi Draft 2020-12. `tts_input` şemasının varlığı **ham metnin M02 EventEnvelope içine taşınmasını meşrulaştırmaz**.

## Bilinen riskler

- M01/M02 outbox kalıcı değil. M05 replay filtresi yalnız RAM ve sınırlı pencere kullanıyor; yeniden başlatma sonrası exactly-once garanti edilmez.
- Mock kuyruktan çıkan metin, gerçek adaptör tarafından uygulanmadan önce tekrar `GenerationId` kontrolü gerektirir. Kontrol ile dış medya çıkışı arasında donanım/transport yarışını M05 kanıtlamaz.
- Cümle noktalaması motorun gerçek sesletim davranışını garanti etmez.
- 29/320 vakanın manuel inceleme kapısı açık; gerçek YouTube anotasyonu ve kalite ölçümü henüz yapılmadı.
