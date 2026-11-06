# M09_ACCEPTANCE_REPORT — Synthetic End-to-End Integration

As-of: 2026-10-31. Değerlendirme türü: **OFFLINE / METADATA-ONLY / MOCK**.

## Ölçülebilen gerçek test sonucu

| Kapı | Sonuç |
|---|---|
| M01–M08 regresyon | **362/362 PASS** |
| Yeni M09 otomatik testler | **49/49 PASS** |
| Toplam unittest | **411/411 PASS** (Linux/Python 3.13) |
| Senaryo çalıştırıcısı | **20/20** |
| M09 JSON Schema Draft 2020-12 | **20/20 doğrulandı** |
| Legacy golden veri bütünlüğü | **SHA-256 aynı** (7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e) |
| Önceki Python kaynakları | **65** dosyanın **5** tanesinde geriye uyumlu M09 entegrasyon onarımı var |
| Yeni M09 ile kaynak modülü sayısı | **68** |
| M05 `review_required` dönüşü | **10** sentetik yanıt; ses çıkışına hazır değil |
| M06 sahte medya metaverisi | **22** parçanın sentetik teslimi (testler arası toplam) |
| Gerçek Freya ses baytı / GPU / PBX / CRM | **0 / kullanılmadı / bağlanmadı / bağlanmadı** |
| M08 API kontrolü | CSRF, Host, Origin ve allowlist testi PASS |
| M09 Chromium görsel önizleme | PASS; statik fixture ile JS hata yok, canlı localhost browser navigation test ortamında engellendi |
| Windows/Edge fiziksel kabul | **HOLD** |

Kabul statüsü: **PASS_WITH_WARNINGS** — iş mantığı ve sentetik kontrol/mocked media güvenliği PASS, uçtan uca gerçek ses hazırlığı HOLD. Üretim hazır değil.

## Değiştirilen eski modüller

- `src/automotive_voice/nlp/nlu.py`
- `src/automotive_voice/operator/server.py`
- `src/automotive_voice/operator/runtime.py`
- `src/automotive_voice/operator/review_store.py`
- `src/automotive_voice/dialogue/coordinator.py`

## Açık teknik blokajlar

1. Doğrulanmış fiyat cümlesinde `1.250.000 Türk lirasıdır` biçimi normalizer'dan ham geçerse M05 bloklar. Bu senaryo fiyat iş politikasını geçer ama **ses çıktı hazırlığı geçmez**.
2. M03 randevu cümlesindeki ham ISO 8601 zaman damgası için sunum katmanı düzeltmesi gerekir. İşte bu nedenle M09 testindeki kontrol-only `PLAYOUT_FINISHED` akustik onay değildir.
3. Qashqai/Škoda/Peugeot/Citroën gibi telaffuzlarda gerçek onaylı ses kanıtı yoktur; sözlük kendiliğinden okunuş üretmez.
4. RAM içi outbox/audit/replay, crash recovery ve gerçek adaptör transaction idempotency HOLD.
5. Sunucu loopback-only; gerçek telefon/PBX buffering veya codec dönüşümü kanıtlanmadı.
6. Python 3.13 testleri sırasında önceki uygulama test yardımcılarının bazı SQLite bağlantı ve event-loop ResourceWarning çıktıları bulunabilir; test başarısı bunları üretim güvenilirliğinin kanıtı yapmaz. M10'da yaşam döngüsü kapatma denetimi gerekir.

## Devir

`docs/40_M09_KABUL_VE_M10_DEVIR.md`, `docs/41_M10_AGENT_GOREVI.md`, `docs/42_M09_KALAN_RISKLER.md`.

M09 sonuçları `data/reports/m09_synthetic_suite.json` ve `data/reports/m09_scenario_matrix.csv` içinde saklanır. Kaynak test fikstürü 320 satır saklanır; gerçek WAV, eğitim kaydı veya dış CRM erişimi yoktur.
