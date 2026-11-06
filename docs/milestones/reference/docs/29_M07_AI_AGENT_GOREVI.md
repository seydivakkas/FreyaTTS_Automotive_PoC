# M07 AI Agent görevi

**Yalnız bu M06 paketini temel al.** M01–M06 public API/320 golden SHA değişmeyecek.

1. Yaşam döngüsü sözleşmeleri: `AdapterState`, `HealthSnapshot`, `LifecyclePort`, `RetryPolicy`, `Deadline`, `CircuitBreaker`, `CancellationScope`.
2. M06 `TransportPort` ve `AudioBufferPort` üzerinden gerçek soket açmayan sahte STT/TTS/LLM/telefon adaptörleri geliştir.
3. Her oturum için konfigürasyon ve artan event sıra garantisini M01/M02 ile koru. Barge-in eski neslin tüm işlerini ve geç kalan callback'leri geçersiz kılsın.
4. Saniye yerine birimi açık `monotonic_ns` deadline kullan. Mock saatle deterministik hata, timeout, retry, reconnect testi yap.
5. İdempotency ve replay penceresi sınırlı olduğunda sınırları raporla; M02 flush ACK'i gerçek PBX tarafından kanıtlanmadıkça üretme.
6. Önce kod/test/mimari; sonra UI. Sentetik E2E ancak modüller tamamlanınca; gerçek Freya/Whisper/YouTube/telefon en son.
7. Windows PowerShell betiği, JSON Schema, eksiksiz eski+yenilerin testi, SHA manifesti, dürüst release kararı üret. Gerçek TTFA/MOS/WER/RTF ölçülmediğini belirt.
