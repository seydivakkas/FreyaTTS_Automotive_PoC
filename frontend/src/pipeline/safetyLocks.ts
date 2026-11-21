/**
 * FreyaTTS Automotive Cockpit V3 — M01–M11 Deterministik Emniyet Kilitleri Tanımları
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

export interface SafetyLock {
  id: string;
  name: string;
  stage: string;
  desc: string;
  trips: number;
  active: boolean;
  latency: string;
}

export const INITIAL_SAFETY_LOCKS: SafetyLock[] = [
  {
    id: 'M01',
    name: 'Halüsinasyon & Katalog Kilidi',
    stage: 'F3',
    desc: 'Veritabanında bulunmayan parça veya servis fiyatının uydurulmasını deterministik JSON şema ile engeller.',
    trips: 0,
    active: true,
    latency: '0.4 ms'
  },
  {
    id: 'M02',
    name: 'Fiyat & İskonto Yetki Sınırı',
    stage: 'F3',
    desc: 'Yetkisiz iskonto veya ±%0 sapma dışı fiyat telaffuzunu bloke eder.',
    trips: 1,
    active: true,
    latency: '0.2 ms'
  },
  {
    id: 'M03',
    name: 'KVKK & PII Maskeleme Kilidi',
    stage: 'F2/F3',
    desc: 'TCKN, kredi kartı ve açık adres verilerini log ve LLM bağlamından anında maskeler.',
    trips: 4,
    active: true,
    latency: '0.8 ms'
  },
  {
    id: 'M04',
    name: 'Barge-in Kesme Garantisi (<120ms)',
    stage: 'F1/F6',
    desc: 'Müşteri araya girdiğinde aktif F4/F5 chunk çıkışını 120ms içinde sıfırlar ve dinleme moduna döner.',
    trips: 12,
    active: true,
    latency: '1.1 ms'
  },
  {
    id: 'M05',
    name: 'Fonetik Marka, Plaka & Sezer Doğrulayıcı',
    stage: 'F4',
    desc: 'Peugeot, Qashqai, DSG, 61 TS 061 ve Trabzon/Ortahisar yer adlarının yanlış okunmasını G2P tablosuyla önler.',
    trips: 24,
    active: true,
    latency: '0.3 ms'
  },
  {
    id: 'M06',
    name: 'OBD-II Kritik Güvenlik Eskalasyonu',
    stage: 'F3',
    desc: 'Fren, hava yastığı veya yağ basıncı arıza kodlarında aracı yürütmeme uyarısı verir ve ustaya bağlar.',
    trips: 2,
    active: true,
    latency: '0.5 ms'
  },
  {
    id: 'M07',
    name: 'Spektral VAD & Masa Tıkırtısı Koruması',
    stage: 'F0/F1',
    desc: '300-3400Hz insan sesi oranı %55 altındaki darbeli gürültülerin (kapı, bardak sesi) Leyla’yı kesmesini önler.',
    trips: 9,
    active: true,
    latency: '1.4 ms'
  },
  {
    id: 'M08',
    name: 'Mükerrer Randevu Çakışma Kilidi',
    stage: 'F3',
    desc: 'Aynı lift ve teknisyen saatine çift rezervasyon yapılmasını ACID kilidiyle engeller.',
    trips: 0,
    active: true,
    latency: '0.9 ms'
  },
  {
    id: 'M09',
    name: 'Duygu & Öfke Tespiti Devir Kilidi',
    stage: 'F1/F3',
    desc: 'Müşteri ses tonunda yüksek stres/memnuniyetsizlik algılandığında Dahili 6002 Operatöre aktarır.',
    trips: 1,
    active: true,
    latency: '1.2 ms'
  },
  {
    id: 'M10',
    name: 'VRAM & Gecikme Sigortası (Circuit Breaker)',
    stage: 'F5',
    desc: 'TTFA > 350ms aşılırsa ODE adım sayısını 10’dan 6’ya düşürerek gerçek zamanlılığı korur.',
    trips: 3,
    active: true,
    latency: '0.1 ms'
  },
  {
    id: 'M11',
    name: 'TSE-HYB Ekspertiz Hukuki Sorumluluk Şerhi',
    stage: 'F3/F4',
    desc: 'Ekspertiz ön bilgilendirmelerinde yasal ekspertiz sınırlarını eksiksiz bildirir.',
    trips: 0,
    active: true,
    latency: '0.2 ms'
  }
];

