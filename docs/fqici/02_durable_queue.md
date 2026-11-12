# FQICI Prompt 2 — Kalıcı kapanış kuyruğu

`023` revizyonu FQICI kapsamı, doğrulanmış olay ve analiz işi tablolarını ekler. Uygulamayı açmadan önce normal migration prosedürüyle `alembic upgrade head` çalıştırılır. Web için `FQICI_ENABLED=true` ile pilot açılır. Varsayılan kapalıdır. Uygulama yeniden başlatıldığında ayar okunur.

Web görüşmesi ve sunucu kodunun açıkça `synthetic=True` ile başlattığı AudioSocket adaptörü pilot kapsamına alınır. Üretim AudioSocket dinleyicisi bu işareti vermez. Bir taşıyıcı UUID’sinin veya istemci mesajının sentetik kaynak ilan etme yetkisi yoktur. Web kökeni demo modunda `DEMO`, diğer durumlarda `UNKNOWN` kalır.

## Veri akışı

1. Freya görüşmesi ile FQICI kapsamı aynı SQLite transaction’ında yazılır. Oturum denetleyicisi kapanışı mevcut M10 günlüğünde kalıcılaştırır.
2. Başlangıçta mevcut oturum kurtarması çalışır. FQICI daha sonra yerel event bus tarafından onaylanmış kayıtlar dahil, kalıcı terminal kayıtları okur. Çalışma sırasında okuyucu arka planda tekrar tarar. Kapsam kaydı var fakat başlangıçta kullanılabilir terminal kayıt yoksa kurtarma olayı sonuç durumunu `UNKNOWN` olarak taşır. Başlangıç kurtarması tek uygulama sunucusu varsayımını mevcut M10 akışıyla paylaşır.
3. FQICI alımı olay, ilk snapshot ve iş satırını tek transaction’da işler. 500 bekleyen iş sınırı doluysa olay ve bekleyen kapsam işareti kalıcılaşır. Yer açılınca tekrar kuyruğa alınır. Geç kanıtlar iki saniyelik sessizlik penceresinde, en fazla 30 saniyeye kadar birleştirilir. Bu değerler kapasite ölçümü değildir.
4. İşçiler işlem başına artan kira belirteci alır. Süresi dolan iş yeniden alınabilir. Eski belirteçle bitirme reddedilir. Üç deneme sonunda süresi dolan veya yeniden denenebilir hata alan iş terminal hata durumuna gider.
5. Saat alanı veya zaman bilgisi kanonik kanıta dahildir. Journal olayı saat alanını sağlayamadığında monotonic alan boş bırakılır. Olay gövdesi kapalı alan listesiyle doğrulanır. FQICI ham metin veya ses kopyalamaz. Mevcut periyodik saklama işi süresi dolan veya silinmiş olarak işaretlenmiş görüşmelerin FQICI kapsamını, olaylarını ve işlerini kaldırır.

Prompt 2, terminal olay üreticisini canlı web pilotuna ve sentetik AudioSocket test girişine bağlar. Araç timeout ve commit sözleşmeleri sentetik alım testlerinde kullanılır. İş sahipliği API’si kullanılabilir durumdadır. Bulguları hesaplayan worker, canlı araç olaylarının kapsamı ve dışa aktarma Prompt 3 ve sonraki aşamalara aittir. Fiziksel SIP kabulü HOLD.

## Doğrulama

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_fqici_queue.py tests/test_session.py tests/test_audiosocket_server.py tests/milestones/test_m10.py --basetemp data/pytest-fqici-p2
```

Testler SQLite üzerinde on tekrar ve iki eşzamanlı tüketici, gerçek alt süreçlerle yeniden teslim, yarım transaction geri alımı, kurtarılan oturum, kuyruk doluluğu, geç kanıt, ayrı kural sürümü, saat alanı, izinli alan doğrulaması ve yerel sentetik TCP AudioSocket kapanışını kapsar.
