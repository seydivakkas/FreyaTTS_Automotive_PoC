export const TABS = [
  "Görüşme",
  "Operatör (6002)",
  "Araç İçi DSP & Gürültü",
  "Randevular",
  "Sıra & Lift Durumu",
  "A/B Test & İnce Ayar",
  "Analitik & KPI",
  "Ekspertiz Raporları",
  "Teknisyen Dikte",
  "Araç Teşhis & OBD-II",
  "Araçlar ve fiyatlar",
  "Sözlük",
  "Bildirimler",
  "Giden Çağrılar",
  "Geçmiş",
  "Ses laboratuvarı",
  "Sistem",
  "M01–M11",
] as const;

// Ana veriyi (randevu, araç, sağlık...) kullanan sekmeler; diğer paneller kendi verisini çeker.
export const MAIN_DATA_TABS: readonly string[] = [
  "Görüşme",
  "Araçlar ve fiyatlar",
  "Randevular",
  "Geçmiş",
  "Sistem",
];
