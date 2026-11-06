# M09 Ayrı Risk Kaydı

| Öğe | Etki | Kabul statüsü |
|---|---|---|
| M03 fiyat yanıtta `1.250.000 Türk lirasıdır` biçimi | M04 bu kalıbı güvenle normalize edemediğinde M05 üretimi bloke eder | HOLD — M10 metinsel onarım |
| M03 randevu teklifinde ham ISO 8601 damgası | TTS normalizer/karakter denetimi takılabilir | HOLD — M10 sunum metni sözleşmesi |
| Qashqai, Škoda vb. için onaylı telaffuz referansı 0 | Üretimde kaynağa dayalı sesletim düzeltmesi yapılamaz | HOLD — M11 izinli ses kanıtı |
| M09 kontrol-only `PLAYOUT_FINISHED` | Ses üretilmeden bir sonraki sentetik turu ilerletebilir; iş akışını test eder ama akustik E2E kanıtı değildir | Açıkça etiketli, fiziksel kabul sayılmaz |
| RAM içi outbox ve volatile M08 read-model | Çökme sonrası olay/audit kaybı | HOLD — M10 dayanıklılık |
| Sahte `FLUSH_MEDIA` ACK | PBX'in gerçekten temizlendiğini kanıtlamaz | HOLD — M11 PBX fiziksel kabul |
| Linux/Python 3.13 yürütmesi | Windows/Python 3.11/Edge doğrulanmamıştır | HOLD — hedef sistem kabulü |
