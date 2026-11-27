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
  "Otomotiv Ontolojisi",
  "Bildirimler",
  "Giden Çağrılar",
  "Geçmiş",
  "Ses laboratuvarı",
  "Sistem",
  "M01–M11",
  "Kabul & Terim",
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
    category: "workshop",
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
  "Otomotiv Ontolojisi": {
    id: "Otomotiv Ontolojisi",
    label: "Otomotiv Ontolojisi",
    category: "audio_ai",
    icon: "🌐",
    description: "NVIDIA Auto-Ontology: Semantik şema, OBD-II teşhis & tek kaynak fiyatlandırma",
    pipelineStage: "F3–F4",
    keywords: ["ontoloji", "ontology", "şema", "mcp", "obd", "nvidia", "graf", "kurallar"],
  },
  "Ses laboratuvarı": {
    id: "Ses laboratuvarı",
    label: "Ses Laboratuvarı",
    category: "audio_ai",
    icon: "🧪",
    description: "FreyaTTS ODE sentezleyici (F5) ve ses iletimi (F6)",
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
  "Kabul & Terim": {
    id: "Kabul & Terim",
    label: "Kabul & Terim Protokolü",
    category: "governance",
    icon: "✅",
    description: "Canlı mikrofon kabul koşuları, DB diff ve çift yönlü otomotiv terim doğrulama",
    pipelineStage: "F0–F6",
    keywords: ["kabul", "mikrofon", "terim", "plaka", "doğrulama", "qa", "acceptance", "f0", "f6"],
  },
};

export const NAV_CATEGORIES: NavCategory[] = [
  {
    id: "workshop",
    label: "Operasyon & Atölye",
    icon: "🚗",
    badgeCountKey: "appointments",
    tabs: [
      TAB_METADATA["Görüşme"],
      TAB_METADATA["Randevular"],
      TAB_METADATA["Sıra & Lift Durumu"],
      TAB_METADATA["Ekspertiz Raporları"],
      TAB_METADATA["Araçlar ve fiyatlar"],
      TAB_METADATA["Teknisyen Dikte"],
      TAB_METADATA["Araç Teşhis & OBD-II"],
    ],
  },
  {
    id: "telephony",
    label: "Telefoni & Santral",
    icon: "📞",
    badgeCountKey: "calls",
    tabs: [
      TAB_METADATA["Bildirimler"],
      TAB_METADATA["Geçmiş"],
      TAB_METADATA["Operatör (6002)"],
      TAB_METADATA["Giden Çağrılar"],
    ],
  },
  {
    id: "audio_ai",
    label: "Ses & Yapay Zekâ Hattı",
    icon: "🎛️",
    tabs: [
      TAB_METADATA["Araç İçi DSP & Gürültü"],
      TAB_METADATA["A/B Test & İnce Ayar"],
      TAB_METADATA["Sözlük"],
      TAB_METADATA["Otomotiv Ontolojisi"],
      TAB_METADATA["Ses laboratuvarı"],
    ],
  },
  {
    id: "governance",
    label: "Gözetim & Kalite Kapıları",
    icon: "🛡️",
    badgeCountKey: "quality",
    tabs: [
      TAB_METADATA["Supervisor Kalite"],
      TAB_METADATA["Analitik & KPI"],
      TAB_METADATA["Sistem"],
      TAB_METADATA["M01–M11"],
      TAB_METADATA["Kabul & Terim"],
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

export type RolePerspective = "operator" | "manager" | "engineer" | "all";

export interface PerspectiveMeta {
  id: RolePerspective;
  label: string;
  icon: string;
  badge: string;
  description: string;
  defaultTab: TabName;
  tabs: TabName[];
}

export const ROLE_PERSPECTIVES: Record<RolePerspective, PerspectiveMeta> = {
  operator: {
    id: "operator",
    label: "Operatör",
    icon: "🎧",
    badge: "Canlı Çağrı Masası",
    description: "Canlı konuşmalar, müşteri bilgisi, randevu onayı ve hızlı müdahale masası",
    defaultTab: "Görüşme",
    tabs: [
      "Görüşme",
      "Operatör (6002)",
      "Geçmiş",
    ],
  },
  manager: {
    id: "manager",
    label: "Yönetici",
    icon: "📊",
    badge: "Takvim & Kapasite",
    description: "Randevu takvimi, lift kapasitesi, araç kataloğu, fiyatlar, raporlar ve bildirimler",
    defaultTab: "Randevular",
    tabs: [
      "Randevular",
      "Sıra & Lift Durumu",
      "Araçlar ve fiyatlar",
      "Ekspertiz Raporları",
      "Bildirimler",
      "Giden Çağrılar",
      "Analitik & KPI",
    ],
  },
  engineer: {
    id: "engineer",
    label: "AI Mühendisi",
    icon: "🔬",
    badge: "F0–F6 & Kalite Kapıları",
    description: "F0–F6 telemetrisi, VAD, ASR, FreyaTTS ODE, Sözlük, Ontoloji, M01–M11 ve sistem sağlığı",
    defaultTab: "Görüşme",
    tabs: [
      "Görüşme",
      "Araç İçi DSP & Gürültü",
      "A/B Test & İnce Ayar",
      "Supervisor Kalite",
      "Sözlük",
      "Otomotiv Ontolojisi",
      "Ses laboratuvarı",
      "Araç Teşhis & OBD-II",
      "Teknisyen Dikte",
      "M01–M11",
      "Kabul & Terim",
      "Sistem",
    ],
  },
  all: {
    id: "all",
    label: "Tümü",
    icon: "🌐",
    badge: "Tüm 21 Sekme",
    description: "FreyaTTS Automotive sistemindeki tüm ekranlar ve yönetim panelleri",
    defaultTab: "Görüşme",
    tabs: [...TABS],
  },
};
