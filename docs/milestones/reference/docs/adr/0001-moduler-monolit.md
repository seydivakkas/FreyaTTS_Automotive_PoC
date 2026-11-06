# ADR-0001 — Modüler monolit + port/adaptör
**Durum:** Kabul önerisi
**Karar:** Tek Python süreçli uygulama; `core/domain` dış kütüphanelerden bağımsız; medya, TTS, STT, LLM, telefon, CRM ayrı port adaptör. İlk sürüm mikroservis/broker/Kubernetes yok. **Gerekçe:** Tek geliştirici bakım maliyeti, offline-first Windows, yerel sözleşmelerin test edilebilirliği. **Sonuç:** Darboğaz ölçüldüğünde modül ayrı sürece çıkarılabilir. 
