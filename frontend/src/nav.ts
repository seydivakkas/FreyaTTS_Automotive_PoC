export const TABS = [
  "Görüşme",
  "Operatör (6002)",
  "Supervisor Kalite",
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

export type TabName = (typeof TABS)[number];

export type CategoryId = "audio_ai" | "workshop" | "telephony" | "governance";

export interface TabMeta {
  id: TabName;
  label: string;
  category: CategoryId;
  icon: string;
  description: string;
  pipelineStage?: "F0" | "F1" | "F2" | "F3" | "F4" | "F5" | "F6" | "F0–F6" | "F1–F2" | "F5–F6" | string;
  keywords: string[];
}

export interface NavCategory {
  id: CategoryId;
  label: string;
  icon: string;
  badgeCountKey?: "appointments" | "vehicles" | "calls" | "quality";
  tabs: TabMeta[];
}

export const TAB_METADATA: Record<TabName, TabMeta> = {
  "Görüşme": {
    id: "Görüşme",
    label: "Görüşme Kokpiti",
    category: "audio_ai",
    icon: "🎙️",
    description: "Canlı ses oturumu, F0–F6 boru hattı ve spektrum",
    pipelineStage: "F0–F6",
    keywords: ["mikrofon", "konuşma", "canlı", "leyla", "ses", "stepper", "audio"],
  },
  "Araç İçi DSP & Gürültü": {
    id: "Araç İçi DSP & Gürültü",
    label: "Araç İçi DSP & Gürültü",
    category: "audio_ai",
    icon: "🛡️",
    description: "120 Hz Butterworth HPF, spektral gürültü bastırma & AGC",
    pipelineStage: "F0",
    keywords: ["dsp", "filtre", "hpf", "gürültü", "spectral", "agc", "f0"],
  },
  "A/B Test & İnce Ayar": {
    id: "A/B Test & İnce Ayar",
    label: "A/B Test & ASR Ayarı",
    category: "audio_ai",
    icon: "⚖️",
    description: "Silero VAD (F1) ve Faster-Whisper ASR (F2) akustik testleri",
    pipelineStage: "F1–F2",
    keywords: ["ab test", "varyant", "vad", "asr", "whisper", "f1", "f2", "z-test", "mos"],
  },
  "Sözlük": {
    id: "Sözlük",
    label: "Sözlük & Fonetik",
    category: "audio_ai",
    icon: "📖",
    description: "P0 Otomotiv Fonetik Sözlüğü & normalizasyon kuralları",
    pipelineStage: "F4",
    keywords: ["lexicon", "fonetik", "normalizer", "sözlük", "f4", "chunker"],
  },
  "Ses laboratuvarı": {
    id: "Ses laboratuvarı",
    label: "Ses Laboratuvarı",
    category: "audio_ai",
    icon: "🧪",
    description: "FreyaTTS ODE sentezleyici (F5) & WSOLA iletim (F6)",
    pipelineStage: "F5–F6",
    keywords: ["tts", "ode", "sentez", "leyla", "wsola", "f5", "f6", "hız"],
  },

  "Ekspertiz Raporları": {
    id: "Ekspertiz Raporları",
    label: "Ekspertiz Raporları",
    category: "workshop",
    icon: "📄",
    description: "Dijital teslim takibi, PDF üretim ve imza onayları",
    keywords: ["ekspertiz", "rapor", "pdf", "teslim", "muayene", "skor"],
  },
  "Randevular": {
    id: "Randevular",
    label: "Randevu Takvimi",
    category: "workshop",
    icon: "📅",
    description: "Servis takvimi, slot rezervasyonları ve teyitler",
    keywords: ["randevu", "slot", "takvim", "rezervasyon", "müşteri"],
  },
  "Sıra & Lift Durumu": {
    id: "Sıra & Lift Durumu",
    label: "Sıra & Lift Durumu",
    category: "workshop",
    icon: "🚗",
    description: "Atölye lift kapasitesi ve canlı araç bekleme kuyruğu",
    keywords: ["lift", "sıra", "kuyruk", "atölye", "kapasite", "istasyon"],
  },
  "Araç Teşhis & OBD-II": {
    id: "Araç Teşhis & OBD-II",
    label: "Araç Teşhis & OBD-II",
    category: "workshop",
    icon: "🔌",
    description: "DTC hata kodları, OBD-II telemetrisi ve sensör okuma",
    keywords: ["obd", "dtc", "teşhis", "arıza", "motor", "ecu", "sensör"],
  },
  "Araçlar ve fiyatlar": {
    id: "Araçlar ve fiyatlar",
    label: "Araç Kataloğu & Fiyatlar",
    category: "workshop",
    icon: "🏷️",
    description: "Kayıtlı model kataloğu, piyasa değerleri ve paket fiyatları",
    keywords: ["araç", "fiyat", "katalog", "paket", "değerleme", "model"],
  },
  "Teknisyen Dikte": {
    id: "Teknisyen Dikte",
    label: "Teknisyen Dikte",
    category: "workshop",
    icon: "🎙️",
    description: "Usta sesli bulgu kaydı, muayene dikte transkripsiyonu",
    keywords: ["dikte", "teknisyen", "usta", "bulgu", "ses kaydı"],
  },

  "Operatör (6002)": {
    id: "Operatör (6002)",
    label: "Operatör Kokpiti (6002)",
    category: "telephony",
    icon: "🎧",
    description: "Canlı çağrı izleme, fısıltı ve operatör aktarım masası",
    keywords: ["operatör", "6002", "transfer", "fısıltı", "dahili", "canlı"],
  },
  "Giden Çağrılar": {
    id: "Giden Çağrılar",
    label: "Giden Çağrılar (Outbound)",
    category: "telephony",
    icon: "📞",
    description: "Otomatik arama kampanyaları, randevu teyit ve anket aramaları",
    keywords: ["outbound", "giden", "arama", "kampanya", "teyit", "dialer"],
  },
  "Geçmiş": {
    id: "Geçmiş",
    label: "Görüşme Geçmişi",
    category: "telephony",
    icon: "📜",
    description: "Tam transkript arşivi, ses kayıtları ve gecikme dökümleri",
    keywords: ["geçmiş", "arşiv", "kayıt", "transkript", "çağrı"],
  },
  "Bildirimler": {
    id: "Bildirimler",
    label: "Bildirimler & WhatsApp",
    category: "telephony",
    icon: "💬",
    description: "Çift yönlü WhatsApp webhooks, SMS kuyruğu ve teslim raporları",
    keywords: ["whatsapp", "sms", "bildirim", "mesaj", "webhook"],
  },

  "Supervisor Kalite": {
    id: "Supervisor Kalite",
    label: "Supervisor & FQICI",
    category: "governance",
    icon: "🔍",
    description: "F3 Niyet Yönlendirici (22 Niyet), LLM planlama ve FQICI denetimi",
    pipelineStage: "F3",
    keywords: ["supervisor", "fqici", "kalite", "denetim", "puan", "politika", "f3", "intent", "router"],
  },
  "Analitik & KPI": {
    id: "Analitik & KPI",
    label: "Analitik & KPI",
    category: "governance",
    icon: "📊",
    description: "Gecikme bütçesi dağılımı (p50/p95/p99), SLA ve başarı oranları",
    keywords: ["analitik", "kpi", "gecikme", "sla", "metrik", "performans"],
  },
  "Sistem": {
    id: "Sistem",
    label: "Sistem & Donanım Sağlığı",
    category: "governance",
    icon: "🖥️",
    description: "RTX 4070 VRAM durumu, model circuit breaker ve servisler",
    keywords: ["sistem", "vram", "gpu", "rtx", "circuit breaker", "sağlık"],
  },
  "M01–M11": {
    id: "M01–M11",
    label: "M01–M11 Kalite Kapıları",
    category: "governance",
    icon: "🎯",
    description: "11 deterministik mühendislik kalite kapısı ve test kanıtları",
    keywords: ["m01", "m11", "milestone", "kalite kapısı", "kabul", "test"],
  },
};

export const NAV_CATEGORIES: NavCategory[] = [
  {
    id: "audio_ai",
    label: "Ses & Yapay Zekâ Hattı",
    icon: "🎛️",
    tabs: [
      TAB_METADATA["Görüşme"],
      TAB_METADATA["Araç İçi DSP & Gürültü"],
      TAB_METADATA["A/B Test & İnce Ayar"],
      TAB_METADATA["Supervisor Kalite"],
      TAB_METADATA["Sözlük"],
      TAB_METADATA["Ses laboratuvarı"],
    ],
  },
  {
    id: "workshop",
    label: "Ekspertiz & Atölye",
    icon: "🚗",
    tabs: [
      TAB_METADATA["Ekspertiz Raporları"],
      TAB_METADATA["Randevular"],
      TAB_METADATA["Sıra & Lift Durumu"],
      TAB_METADATA["Araç Teşhis & OBD-II"],
      TAB_METADATA["Araçlar ve fiyatlar"],
      TAB_METADATA["Teknisyen Dikte"],
    ],
  },
  {
    id: "telephony",
    label: "Telefoni & Santral",
    icon: "📞",
    tabs: [
      TAB_METADATA["Operatör (6002)"],
      TAB_METADATA["Giden Çağrılar"],
      TAB_METADATA["Geçmiş"],
      TAB_METADATA["Bildirimler"],
    ],
  },
  {
    id: "governance",
    label: "Gözetim & Sistem",
    icon: "🛡️",
    tabs: [
      TAB_METADATA["Supervisor Kalite"],
      TAB_METADATA["Analitik & KPI"],
      TAB_METADATA["Sistem"],
      TAB_METADATA["M01–M11"],
    ],
  },
];

// Ana veriyi (randevu, araç, sağlık...) kullanan sekmeler; diğer paneller kendi verisini çeker.
export const MAIN_DATA_TABS: readonly string[] = [
  "Görüşme",
  "Araçlar ve fiyatlar",
  "Randevular",
  "Geçmiş",
  "Sistem",
];
