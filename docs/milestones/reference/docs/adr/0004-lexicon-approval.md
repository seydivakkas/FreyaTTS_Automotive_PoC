# ADR-0004 — Kanıta dayalı sözlük
**Durum:** Kabul önerisi
**Karar:** A01-YT SQLite kayıtları yalnız `approved` + kaynak/zaman/izin + reviewer varsa Freya ön işlem sözlüğüne aktarılır. Kullanıcının sözlü izin beyanı üç video için kaynak meta verisi olabilir fakat gerçekten işlenmiş klip ve telaffuz kanıtı değildir. Fine-tuning yok; ses kimliğini korumak için checkpoint/seed profil sabit. 
