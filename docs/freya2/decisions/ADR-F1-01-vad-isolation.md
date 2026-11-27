# ADR-F1-01 · Silero oturum izolasyonu

**Karar:** Ultra F1.03 seçenek A. Başlatmada diskteki mevcut Silero TorchScript
artefaktı CPU üzerinde bir kez şablon olarak yüklenir. Her VoiceSession şablonun
bağımsız bir kopyasını oluşturur ve yalnızca kendi kopyasının durumunu sıfırlar.
Oturum sonlanana kadar Endpoint bu kopyayı kullanır.

Bu yol mevcut TorchScript artefaktını ve 16 kHz / 512 örnek giriş sözleşmesini
kullanır. ONNX Runtime eklenmesi ile ağırlıkları paylaşan açık RNN durum
sözleşmesi ayrı bir mimari değerlendirme gerektirir. Her oturumun kendi model
kopyasını tutması ek CPU belleği gerektirir. Kapasite kararı yük testiyle verilir.

T20 regresyonu yerel Silero modeliyle 2, 4 ve 8 görüşmeyi iç içe çalıştırır.
Yarısı akış devam ederken açılır. Her olasılık akışı yalıtılmış referansla
`1e-6` mutlak toleransta karşılaştırılır.
