# M04 — Türkçe NLP / Lexicon / NLU Sözleşmeleri

## Kapsam

M01/M02/M03 public API'leri değişmez. `automotive_voice.nlp` eklenmiştir. Ses/GPU/telefon işlemi yoktur. İki farklı metin temsilinin birbirine karıştırılması yasaktır:

- `display_text`: Kullanıcının/CRM'nin gördüğü kaynak yazım; marka isimleri, fiyat ve noktalama anlamı korunur.
- `spoken_text`: TTS'ye verilecek aday metin; yalnız deterministik kurallar ve kanıtlı sözlük etkileri. `review_required=True` ise doğrudan üretime geçiş engellenmelidir.

### `TurkishAutomotiveNormalizer`

`normalize(text, strict=False) -> NormalizationResult`:
`display_text`, `spoken_text`, `rules_applied`, `warnings`, `unsupported_chars`, `review_required`.

- Fiyat: `1.250.000 TL`, `1.250,50 TL`, `9,05 ₺`.
- Tarih: `2026-11-03` ve `03.11.2026`; takvim geçerliliği `datetime.date` ile doğrulanır.
- Saat: `14:30`, `09:00'da`, `15:00'te`; yanlış saat aynen tutulup incelemeye düşer.
- Motor: `1.5 TSI`, `1,6 TDI`; kilometre: `145.000 km`; model yılı: `2023 model`.
- Bilinmeyen para birimi, yabancı marka ve teknik kelime okunuşu **tahmin edilmez**.
- Tanımsız sayı biçimleri, Unicode kontrol karakterleri, Freya sözlüğünde olmayan karakterler uyarı üretir; strict mod reddeder.

Genel amaçlı telefon, VIN, plaka veya fiyat olmayan her tam sayıyı otomatik yazıya çevirme **kapsam dışıdır**. Yanlış bir sayıyı doğruymuş gibi söylemektense inceleme istemek tercih edilir.

### `AutomotiveLexicon`

`LexiconRule(canonical, spoken_tr, approved, source_ref, reviewer, evidence, aliases, suffix_map, context)`.

Yalnız `approved=True`, reviewer ve clip/source/annotation kanıtı bulunan kayıtları uygular. Aynı kelime için çelişen okunuşlar otomatik birleştirilmez. Türkçe ekler için tahmin yürütülmez; ör. `Peugeot'nun` ancak **tam eşleşen ve onaylı** suffix_map ile değiştirilir. Tek geçişli değiştirme, bir düzeltmenin başka bir kuralı zincirleme tetiklemesini engeller.

`Škoda`, `Qashqai`, `Citroën`, `Peugeot` gösterimlerini model sözlüğüne uydurmak için sessizce dönüştürmeyiz. Örn. Qashqai'nin okunuşunun hangi Türkçe varyantta doğru olduğu gerçek konuşma kanıtından belirlenecek.

### A01-YT bağlantısı

`A01YTReadOnlyAdapter(path).load() -> AutomotiveLexicon` yalnız `mode=ro` SQLite ile çalışır. Şunlar birlikte sağlanmadan kural çıkarılmaz:

- annotation `approved`, reviewer ve review timestamp,
- final transkript ve transkript reviewer,
- imported ses metadata'sı ve 64 haneli SHA-256,
- ilgili kaynağa özgü kullanım izni beyanı / veri işleme kapsamı,
- doğrudan hak sahibinden medya teslimi **veya** platform indirme yetkisi,
- çelişmeyen, bağlamdan bağımsız telaffuz.

**Sınır:** DB'nin klip hash alanı geçerli biçimde olsa bile bu katman dosya baytlarını açıp yeniden hash etmiyor. Gerçek dosyanın bütünlüğü A01-YT ses içe aktarma katmanının sorumluluğundadır. Sadece kaynak için sözlü izin kaydı, akustik telaffuz kanıtı anlamına gelmez.

### `DeterministicNLU` + `NLUReferenceBridge`

`parse(transcript, ParseContext) -> ParseResult` dönüşü M03 `DialogueInput` tipini taşır. `DialogueInput` şeması değişmedi. Güvenilir araç ve lokasyon eşlemeleri **uygulama kontekstinden** gelmek zorundadır; marka adı tek başına müşteri aracı kimliği değildir.

Randevu için geçerli **tek** tarih + **tek** saat + bilinen lokasyon + açık saat dilimi şarttır. `yarın` yalnız zaman dilimli `as_of` varsa çözülür. NLU randevu oluşturmaz, yalnız M03 politikasına doğrulanmış slot sunabilir. `evet` ancak bekleyen onay kontekstinde `CONFIRM` olur. Belirsizlikte `UNKNOWN`/eksik alan döner, iddia uydurmaz.

`NLUReferenceBridge.resolve` ham metni EventBus'a göndermez: `ReferenceStore.put_input` aracılığıyla opak ref oluşturur. `safe_diagnostics` yalnız niyet, bayraklar, hata kodları taşır. Gizli transkript başka bir arşivde tutulmaz.

## Geriye dönük uyumluluk

M01/M02/M03 kaynakları ve `contracts/dialogue_input.schema.json` değiştirilmedi. Tüm yeni şemalar ayrı isimlerde. Mevcut 320 test girdisi SHA-256 ile kilitlidir.
