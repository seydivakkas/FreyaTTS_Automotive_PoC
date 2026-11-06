# M10 AI Agent Uygulama Talimatı — Gerçek Adaptörlere Hazırlık (DRY RUN)

M09 ZIP içeriğini tek kod tabanı olarak al. M01–M09 sözleşmeleri ve 320 golden kaynak fikstürünü bozmadan geliştir.

1. `docs/40_M09_KABUL_VE_M10_DEVIR.md` ve `docs/39_M09_E2E_MIMARISI.md` içindeki açık HOLD noktalarını kaydet.
2. Outbox olay kalıcılığı, sessiz restart recovery, `TurnId`/`GenerationId` monotonicity ve idempotency anahtarları için SQLite temelli yerel tasarım yap; atomik yazma ve replay kurallarını doğrula.
3. FreyaTTS, STT, LLM, Asterisk/AudioSocket/WebSocket sağlayıcılarının **bağlantı kurulmadan** çalışan config/health/teardown arayüzlerini tanımla. Yetki kontrolü ve sır yönetimi gerçek API anahtarları olmadan denetlensin.
4. M03 fiyat ve randevu yanıtlarında ham ISO zaman/fiyat eki kaynaklı M04 normalizer bloklarını çöz. Kanıtsız marka okunuşu üretme. Güncellenen davranışları 320 vaka ile karşılaştır; revizyon sapmalarını raporla.
5. İşlev tamamlanınca M08 UI'ye M10 hazırlık göstergeleri ekle; sonra sahte entegrasyon ve regresyon çalıştır. **Gerçek ses/GPU/telefon/YouTube medya denemeleri yapma.**
6. `M10_ACCEPTANCE.md`, güvenlik değerlendirmesi ve Windows PowerShell kontrol betikleri oluştur; üretim hazır olmayı ölçülmeden iddia etme.
