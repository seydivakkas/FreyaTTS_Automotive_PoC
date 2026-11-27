# Türkçe operatör paneli

Sekme kimliği, görünen etiket, gezinme grubu, arama sözcükleri ve rozet ilişkileri aşağıdaki gezinme tarifinde bulunur. Ana bileşen oturum açma, seçili ekran, demo bandı ve ortak veri yenilemesini bağlar. CSS kurallarını sırasıyla uygulayın. Sonraki kurallar önceki değerleri geçersiz kılabilir.


### frontend/src/nav.ts

````tsx
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
````


### frontend/src/main.tsx

````tsx
import React, { useState, useEffect, useMemo, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { errorMessage } from "./ui";
import { createApi } from "./api";
import type { Appointment, Conversation, Health, Quote, Slot, Vehicle } from "./api";
import { MAIN_DATA_TABS, TABS, TabName } from "./nav";
import { SidebarNav } from "./SidebarNav";
import { CockpitHeader } from "./CockpitHeader";
import { FirstAppointmentGuide } from "./FirstAppointmentGuide";
import { useVoiceSession } from "./useVoiceSession";
import { LoginGate } from "./LoginGate";
import { VoiceTab } from "./tabs/VoiceTab";
import { VehiclesTab } from "./tabs/VehiclesTab";
import { AppointmentsTab } from "./tabs/AppointmentsTab";
import { HistoryTab } from "./tabs/HistoryTab";
import { LabTab } from "./tabs/LabTab";
import { SystemTab } from "./tabs/SystemTab";
import {
  ABTestingPanel,
  AnalyticsPanel,
  CarDenoiserPanel,
  DiagnosticPanel,
  InspectionPanel,
  LexiconPanel,
  MilestonePanel,
  NotificationPanel,
  OperatorPanel,
  OutboundPanel,
  QueueLiftPanel,
  SupervisorPanel,
  TechnicianDictationPanel,
  OntologyPanel,
} from "./lazyPanels";

function App() {
  const [password, setPassword] = useState(""),
    [logged, setLogged] = useState(false),
    [tab, setTab] = useState<TabName>("Görüşme"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<Health>({}),
    [quotes, setQuotes] = useState<Quote[]>([]),
    [vehicles, setVehicles] = useState<Vehicle[]>([]),
    [slots, setSlots] = useState<Slot[]>([]),
    [appointments, setAppointments] = useState<Appointment[]>([]),
    [calls, setCalls] = useState<Conversation[]>([]),
    [historyId, setHistoryId] = useState<string | null>(null),
    [refreshTick, setRefreshTick] = useState(0);
  const [qualityConversationId, setQualityConversationId] = useState<string>();
  const [text, setText] = useState(
      "Volkswagen Passat 1.5 TSI aracınızın tahmini değeri 1.250.000 TL.",
    ),
    [normalized, setNormalized] = useState(""),
    [audioUrl, setAudioUrl] = useState("");
  const { api, rawApi } = useMemo(() => createApi(password), [password]);
  const voice = useVoiceSession(api, setError);
  async function action(fn: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    const endpoints = [
      "readiness",
      "vehicles",
      "slots",
      "appointments",
      "conversations",
      "quotes",
    ] as const;
    const results = await Promise.allSettled(endpoints.map((x) => api(x)));
    const [h, v, s, a, c, q] = results;
    if (h.status === "fulfilled") setHealth(h.value as Health);
    if (v.status === "fulfilled") setVehicles(v.value as Vehicle[]);
    if (s.status === "fulfilled") setSlots(s.value as Slot[]);
    if (a.status === "fulfilled") setAppointments(a.value as Appointment[]);
    if (c.status === "fulfilled") setCalls(c.value as Conversation[]);
    if (q.status === "fulfilled") setQuotes(q.value as Quote[]);

    // Sadece tüm istekler birden başarısız olursa genel hata bildir
    const allRejected = results.every((r) => r.status === "rejected");
    if (allRejected && results.length > 0) {
      const firstError = (results[0] as PromiseRejectedResult).reason;
      setError(errorMessage(firstError));
    }
  }
  function openConversation(id: string) {
    setHistoryId(id);
    setTab("Geçmiş");
    void action(refresh);
  }
  useEffect(() => {
    if (logged) action(refresh);
  }, [logged]);
  function logout() {
    voice.reset();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setPassword("");
    setLogged(false);
    setTab("Görüşme");
    setError("");
    setHealth({});
    setQuotes([]);
    setVehicles([]);
    setSlots([]);
    setAppointments([]);
    setCalls([]);
    setHistoryId(null);
    setQualityConversationId(undefined);
    setNormalized("");
    setAudioUrl("");
  }
  if (!logged)
    return (
      <LoginGate
        password={password}
        setPassword={setPassword}
        busy={busy}
        error={error}
        action={action}
        api={api}
        onLogged={() => setLogged(true)}
      />
    );
  return (
    <div className="cockpit-layout">
      <SidebarNav
        activeTab={tab}
        onSelectTab={(t) => {
          setTab(t);
          if (t === "Supervisor Kalite") setQualityConversationId(undefined);
          setError("");
          setRefreshTick((tick) => tick + 1);
          if (MAIN_DATA_TABS.includes(t)) action(refresh);
        }}
        badgeCounts={{
          appointments: appointments.filter((a) => a.status === "confirmed").length,
          vehicles: vehicles.length,
          calls: calls.length,
        }}
      />
      <main className="cockpit-main-workspace">
        <CockpitHeader
          activeTabTitle={tab}
          health={health}
          busy={busy}
          onRefresh={() => {
            setRefreshTick((t) => t + 1);
            void action(refresh);
          }}
          onLogout={logout}
        />
        <FirstAppointmentGuide
          health={health}
          vehicles={vehicles}
          slots={slots}
          appointments={appointments}
          calls={calls}
          onNavigateToTab={(t) => setTab(t)}
          action={action}
          api={api}
          refresh={refresh}
          busy={busy}
          onStartVoice={() => action(voice.start)}
        />
        {error && (
          <div
            role="alert"
            className="error"
            style={{
              padding: "5px 12px",
              margin: "0 0 4px 0",
              fontSize: "12px",
              flexShrink: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "8px",
            }}
          >
            <span>{error}</span>
            <button
              type="button"
              onClick={() => setError("")}
              style={{
                background: "transparent",
                border: "none",
                color: "inherit",
                cursor: "pointer",
                padding: "0 4px",
                fontSize: "13px",
                fontWeight: "bold",
              }}
              title="Kapat"
            >
              ✕
            </button>
          </div>
        )}
        <div className="cockpit-content-viewport" key={`${tab}-${health.demo_mode ? "demo" : "reel"}-${refreshTick}`}>
          {tab === "Görüşme" && (
            <VoiceTab
              busy={busy}
              health={health}
              appointments={appointments}
              vehicles={vehicles}
              slots={slots}
              voice={voice}
              api={api}
              rawApi={rawApi}
              onStart={() => action(voice.start)}
              onNavigateToTab={(t) => setTab(t)}
            />
          )}
          {tab === "Araçlar ve fiyatlar" && (
            <VehiclesTab
              api={api}
              action={action}
              refresh={refresh}
              busy={busy}
              vehicles={vehicles}
              quotes={quotes}
            />
          )}
          {tab === "Randevular" && (
            <AppointmentsTab
              api={api}
              action={action}
              refresh={refresh}
              busy={busy}
              slots={slots}
              appointments={appointments}
            />
          )}
          {tab === "Geçmiş" && (
            <HistoryTab
              api={api}
              action={action}
              refresh={refresh}
              calls={calls}
              selectedId={historyId}
              onSelect={setHistoryId}
              onOpenQuality={(id) => {
                setQualityConversationId(id);
                setTab("Supervisor Kalite");
              }}
            />
          )}
          {tab === "Ses laboratuvarı" && (
            <LabTab
              api={api}
              rawApi={rawApi}
              action={action}
              text={text}
              setText={setText}
              normalized={normalized}
              setNormalized={setNormalized}
              audioUrl={audioUrl}
              setAudioUrl={setAudioUrl}
            />
          )}
          <Suspense fallback={<p className="muted">Panel yükleniyor…</p>}>
            {tab === "Operatör (6002)" && <OperatorPanel kvkkErasureEnabled={health.kvkk_erasure_enabled === true} autoPurgeTranscripts={health.auto_purge_transcripts === true} api={api} onError={setError} onOpenConversation={openConversation} />}
            {tab === "Supervisor Kalite" && <SupervisorPanel
              api={api}
              rawApi={rawApi}
              initialConversationId={qualityConversationId}
              onOpenConversation={openConversation}
            />}
            {tab === "Araç İçi DSP & Gürültü" && <CarDenoiserPanel api={api} rawApi={rawApi} />}
            {tab === "Sıra & Lift Durumu" && <QueueLiftPanel api={api} />}
            {tab === "A/B Test & İnce Ayar" && (
              <ABTestingPanel api={api} rawApi={rawApi} action={action} />
            )}
            {tab === "Analitik & KPI" && <AnalyticsPanel api={api} />}
            {tab === "Ekspertiz Raporları" && <InspectionPanel api={api} />}
            {tab === "Teknisyen Dikte" && <TechnicianDictationPanel api={api} />}
            {tab === "Araç Teşhis & OBD-II" && <DiagnosticPanel api={api} />}
            {tab === "Sözlük" && <LexiconPanel api={api} />}
            {tab === "Otomotiv Ontolojisi" && <OntologyPanel api={api} />}
            {tab === "Bildirimler" && <NotificationPanel api={api} rawApi={rawApi} />}
            {tab === "Giden Çağrılar" && <OutboundPanel api={api} />}
            {tab === "M01–M11" && <MilestonePanel api={api} />}
          </Suspense>
          {tab === "Sistem" && (
            <SystemTab
              api={api}
              action={action}
              refresh={refresh}
              busy={busy}
              health={health}
            />
          )}
        </div>
        <footer style={{ fontSize: "10px", color: "#64748b", textAlign: "center", padding: "3px 0", flexShrink: 0, margin: 0 }}>
          FreyaTTS Automotive · Otomotiv Operasyon Kokpiti
        </footer>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
````


### frontend/src/SidebarNav.tsx

````tsx
/**
 * FreyaTTS Automotive Cockpit V3 — Hiyerarşik Sidebar Navigasyonu
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useState, useMemo } from "react";
import { NAV_CATEGORIES, TabName, TabMeta, CategoryId } from "./nav";

interface Props {
  activeTab: TabName;
  onSelectTab: (tab: TabName) => void;
  badgeCounts?: {
    appointments?: number;
    vehicles?: number;
    calls?: number;
    quality?: number;
  };
}

export function SidebarNav({ activeTab, onSelectTab, badgeCounts = {} }: Props) {
  const [searchQuery, setSearchQuery] = useState("");
  const [collapsedCategories, setCollapsedCategories] = useState<Record<CategoryId, boolean>>({
    audio_ai: false,
    workshop: false,
    telephony: false,
    governance: false,
  });

  const toggleCategory = (catId: CategoryId) => {
    setCollapsedCategories((prev) => ({
      ...prev,
      [catId]: !prev[catId],
    }));
  };

  // Türkçe uyumlu büyük/küçük harf duyarsız arama
  const normalizedQuery = searchQuery.trim().toLocaleLowerCase("tr-TR");

  const filteredCategories = useMemo(() => {
    if (!normalizedQuery) return NAV_CATEGORIES;

    return NAV_CATEGORIES.map((cat) => {
      const matchingTabs = cat.tabs.filter((t) => {
        const textToSearch = [
          t.label,
          t.description,
          t.id,
          t.pipelineStage || "",
          ...t.keywords,
        ].join(" ").toLocaleLowerCase("tr-TR");

        return textToSearch.includes(normalizedQuery);
      });

      return {
        ...cat,
        tabs: matchingTabs,
      };
    }).filter((cat) => cat.tabs.length > 0);
  }, [normalizedQuery]);

  return (
    <aside className="cockpit-sidebar" aria-label="Operasyon Navigasyonu">
      <div className="sidebar-brand">
        <div className="brand-logo">
          <span className="brand-dot" />
          <span className="brand-text">freya<span className="brand-version">v3</span></span>
        </div>
        <div className="brand-subtitle">OTOMOTİV KOKPİTİ</div>
      </div>

      <div className="sidebar-search">
        <div className="search-input-wrapper">
          <span className="search-icon">🔍</span>
          <input
            type="search"
            placeholder="Sekme veya F0–F6 ara..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="search-input"
            aria-label="Sekme arama"
          />
          {searchQuery && (
            <button
              type="button"
              className="clear-search-btn"
              onClick={() => setSearchQuery("")}
              aria-label="Aramayı temizle"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      <nav className="sidebar-accordion">
        {filteredCategories.length === 0 ? (
          <div className="no-search-results">
            <p>"{searchQuery}" ile eşleşen sekme bulunamadı.</p>
            <button
              type="button"
              className="reset-search-btn"
              onClick={() => setSearchQuery("")}
            >
              Tüm sekmeleri göster
            </button>
          </div>
        ) : (
          filteredCategories.map((cat) => {
            const isCollapsed = !normalizedQuery && Boolean(collapsedCategories[cat.id]);
            const hasActiveTab = cat.tabs.some((t) => t.id === activeTab);

            return (
              <div key={cat.id} className={`nav-category ${hasActiveTab ? "contains-active" : ""}`}>
                <button
                  type="button"
                  className="category-header"
                  onClick={() => toggleCategory(cat.id)}
                  aria-expanded={!isCollapsed}
                >
                  <span className="category-title">
                    <span className="cat-icon">{cat.icon}</span>
                    <span className="cat-label">{cat.label}</span>
                  </span>
                  <span className="cat-chevron">{isCollapsed ? "▸" : "▾"}</span>
                </button>

                {!isCollapsed && (
                  <ul className="category-tabs" role="menu">
                    {cat.tabs.map((tab) => {
                      const isActive = tab.id === activeTab;
                      let badgeValue: number | undefined;

                      if (tab.id === "Randevular") badgeValue = badgeCounts.appointments;
                      if (tab.id === "Araçlar ve fiyatlar") badgeValue = badgeCounts.vehicles;
                      if (tab.id === "Geçmiş") badgeValue = badgeCounts.calls;
                      if (tab.id === "Supervisor Kalite") badgeValue = badgeCounts.quality;

                      return (
                        <li key={tab.id} role="none">
                          <button
                            type="button"
                            role="menuitem"
                            className={`nav-tab-btn ${isActive ? "active" : ""}`}
                            onClick={() => onSelectTab(tab.id)}
                            aria-current={isActive ? "page" : undefined}
                          >
                            <span className="tab-icon-and-name">
                              <span className="tab-icon">{tab.icon}</span>
                              <span className="tab-name">{tab.label}</span>
                            </span>

                            <span className="tab-tags">
                              {tab.pipelineStage && (
                                <span className={`stage-badge stage-${tab.pipelineStage.toLowerCase()}`}>
                                  {tab.pipelineStage}
                                </span>
                              )}
                              {badgeValue !== undefined && badgeValue > 0 && (
                                <span className="count-badge">{badgeValue}</span>
                              )}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            );
          })
        )}
      </nav>

      <div className="sidebar-footer">
        <div className="local-tag">
          <span className="live-pulse-dot" />
          <span>Yerel RTX 4070 · İstanbul</span>
        </div>
      </div>
    </aside>
  );
}
````


### frontend/src/CockpitHeader.tsx

````tsx
/**
 * FreyaTTS Automotive Cockpit V3 — Global Kontrol Çubuğu (Katman A)
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 * Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlıdır.
 */

import React from "react";
import type { Health } from "./api";

interface Props {
  activeTabTitle: string;
  health: Health;
  busy: boolean;
  onRefresh: () => void;
  onLogout: () => void;
}

export function CockpitHeader({
  activeTabTitle,
  health,
  busy,
  onRefresh,
  onLogout,
}: Props) {
  const isDemo = Boolean(health.demo_mode);
  const breakerState = health.circuit_breaker?.state || "CLOSED";

  return (
    <header className="cockpit-header">
      <div className="header-left" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <h1 className="tab-current-title" style={{ fontSize: 16, fontWeight: 800, margin: 0, color: "#f8fafc", whiteSpace: "nowrap" }}>
          {activeTabTitle}
        </h1>
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            padding: "2px 7px",
            borderRadius: 4,
            background: isDemo ? "rgba(245, 158, 11, 0.15)" : "rgba(16, 185, 129, 0.15)",
            color: isDemo ? "#fbbf24" : "#34d399",
            border: isDemo ? "1px solid rgba(245, 158, 11, 0.3)" : "1px solid rgba(16, 185, 129, 0.3)",
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            whiteSpace: "nowrap",
          }}
        >
          <span
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: isDemo ? "#fbbf24" : "#34d399",
            }}
          />
          {isDemo ? "DEMO MODU" : "CANLI REEL MOD"}
        </span>
      </div>

      <div className="header-center-health">
        <div className="health-pills-bar" title="Yapay Zekâ ve Donanım Sağlığı" style={{ padding: "2px 6px", gap: 6 }}>
          <div className={`health-pill ${health.stt?.status === "READY" ? "ready" : "blocked"}`} style={{ padding: "2px 7px", fontSize: 10.5 }}>
            <span className="pill-dot" style={{ width: 5, height: 5 }} />
            <span className="pill-text">ASR: {health.stt?.status === "READY" ? "Whisper" : "Kapalı"}</span>
          </div>

          <div className={`health-pill ${health.ollama?.status === "READY" ? "ready" : "blocked"}`} style={{ padding: "2px 7px", fontSize: 10.5 }}>
            <span className="pill-dot" style={{ width: 5, height: 5 }} />
            <span className="pill-text">LLM: {health.ollama?.status === "READY" ? "Qwen2.5" : "Kapalı"}</span>
          </div>

          <div className={`health-pill ${health.tts?.status === "READY" ? "ready" : "blocked"}`} style={{ padding: "2px 7px", fontSize: 10.5 }}>
            <span className="pill-dot" style={{ width: 5, height: 5 }} />
            <span className="pill-text">TTS: {health.tts?.status === "READY" ? "Leyla ODE" : "Kapalı"}</span>
          </div>

          <div className={`health-pill breaker-${breakerState.toLowerCase()}`} style={{ padding: "2px 7px", fontSize: 10.5 }}>
            <span className="pill-dot" style={{ width: 5, height: 5 }} />
            <span className="pill-text">VRAM: {breakerState}</span>
          </div>
        </div>
      </div>

      <div className="header-right-controls" style={{ gap: 8 }}>
        <button
          type="button"
          className="header-btn secondary"
          onClick={onRefresh}
          disabled={busy}
          title="Verileri ve bağlantıları tazele"
          style={{ padding: "4px 10px", fontSize: 11 }}
        >
          {busy ? "..." : "Yenile ↻"}
        </button>

        <button
          type="button"
          className="header-btn logout-btn"
          onClick={onLogout}
          title="Güvenli Çıkış"
          style={{ padding: "4px 10px", fontSize: 11 }}
        >
          Çıkış
        </button>
      </div>
    </header>
  );
}
````


### frontend/src/LoginGate.tsx

````tsx
import type { ActionFn } from "./api";
import type { ApiFn } from "./ui";

type Props = {
  password: string;
  setPassword: (v: string) => void;
  busy: boolean;
  error: string;
  action: ActionFn;
  api: ApiFn;
  onLogged: () => void;
};

export function LoginGate({ password, setPassword, busy, error, action, api, onLogged }: Props) {
  return (
    <main className="login">
      <div className="brand">
        f<span>reya</span>
        <small>OTOMOTİV ASİSTANI</small>
      </div>
      <h1>Yerel ses, doğal iletişim.</h1>
      <p>Yönetim paneline güvenli giriş yapın.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          action(async () => {
            await api("readiness");
            onLogged();
          });
        }}
      >
        <label>
          Yönetici parolası
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button disabled={busy}>Panele giriş →</button>
      </form>
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
    </main>
  );
}
````


### frontend/src/ui.ts

````tsx
import { useEffect } from "react";

export type ApiFn = (path: string, method?: string, body?: unknown) => Promise<any>;
/** FormData / binary yanıtlar için: kimlik başlığını ana uygulamadan alır, ok-olmayan yanıtta hata fırlatır. */
export type RawApiFn = (path: string, method?: string, body?: unknown) => Promise<Response>;

/** Kullanıcı kimlik bilgisi Latin1 dışı karakter içerebilir; önce UTF-8 olarak kodla. */
export function basicAuthHeader(password: string): string {
  const bytes = new TextEncoder().encode("admin:" + password);
  let bin = "";
  bytes.forEach((b) => {
    bin += String.fromCharCode(b);
  });
  return "Basic " + btoa(bin);
}

/** Ölçülmemiş (null/undefined/NaN) değerler için "—", aksi halde biçimlenmiş değer. */
export function dash(v: unknown, suffix = "", digits?: number): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    return (digits === undefined ? String(v) : v.toFixed(digits)) + suffix;
  }
  return String(v) + suffix;
}

/** Modal açıkken Escape tuşuyla kapat. */
export function useEscape(onClose: () => void, active = true) {
  useEffect(() => {
    if (!active) return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [active, onClose]);
}

const METRIC_LABELS: Record<string, [string, string, number]> = {
  stt_ms: ["STT", " ms", 0],
  endpoint_ms: ["Konuşma sonu", " ms", 0],
  llm_total_ms: ["LLM", " ms", 0],
  llm_first_token_ms: ["LLM ilk token", " ms", 0],
  first_audio_ms: ["İlk ses (sunucuda hazır)", " ms", 0],
  tts_ms: ["TTS", " ms", 0],
  rtf: ["RTF", "", 2],
};

/** Tur metrik JSON'unu kullanıcıya ham JSON göstermeden okunur metne çevirir; boşsa "" döner. */
export function formatMetrics(raw: unknown): string {
  let obj: Record<string, unknown> | null = null;
  if (typeof raw === "string") {
    try {
      obj = JSON.parse(raw);
    } catch {
      return "";
    }
  } else if (raw && typeof raw === "object") {
    obj = raw as Record<string, unknown>;
  }
  if (!obj) return "";
  const parts: string[] = [];
  for (const [k, [label, unit, digits]] of Object.entries(METRIC_LABELS)) {
    const v = obj[k];
    if (typeof v === "number" && Number.isFinite(v)) parts.push(`${label}: ${v.toFixed(digits)}${unit}`);
  }
  return parts.join(" · ");
}

/** `catch (e)` bloklarında güvenli hata iletisi. */
export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export const formatDate = (s: string) =>
  new Date(s).toLocaleString("tr-TR", { timeZone: "Europe/Istanbul" });
````


### frontend/src/style.css

````tsx
/* Ana renk değişkenleri (koyu tema). */
:root {
  --bg: #0d111b;
  --surface: #151c2b;
  --surface-2: #121825;
  --surface-3: #202a3d;
  --input-bg: #0e1522;
  --border: #2a3344;
  --border-strong: #354056;
  --text: #e6e9f2;
  --text-strong: #eff5ff;
  --muted: #98a5ba;
  --accent: #a7f3ce;
  --accent-ink: #13382b;
  --ok-border: #3e7061;
  --danger-bg: #432632;
  --danger-border: #a55d66;
  --danger-text: #ffd2d2;
  --warn: #facc15;
  --info: #38bdf8;
}
:root {
  font-family:
    Inter,
    Segoe UI,
    sans-serif;
  color: var(--text);
  background: var(--bg);
  font-synthesis: none;
}
html, body, #root {
  height: 100dvh;
  max-height: 100dvh;
  overflow: hidden;
  margin: 0;
  padding: 0;
}
* {
  box-sizing: border-box;
  scrollbar-width: thin;
  scrollbar-color: #2a374f #090e17;
}
*::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}
*::-webkit-scrollbar-track {
  background: #090e17;
}
*::-webkit-scrollbar-thumb {
  background: #2a374f;
  border-radius: 4px;
}
*::-webkit-scrollbar-thumb:hover {
  background: #3b4c6c;
}
body {
  margin: 0;
}
button,
input,
textarea {
  font: inherit;
}
button {
  cursor: pointer;
  border: 0;
  border-radius: 6px;
  padding: 7px 14px;
  background: var(--accent);
  color: var(--accent-ink);
  font-weight: 650;
  font-size: 12.5px;
  transition: all 150ms ease-out;
}
button:disabled {
  opacity: 0.5;
  cursor: wait;
}
button:focus-visible,
input:focus-visible,
textarea:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
}
.secondary {
  background: #252e40;
  color: #dae2f1;
  border: 1px solid #354058;
}
.danger {
  background: #442c35;
  color: #ffc1c1;
}
.layout {
  display: grid;
  grid-template-columns: 248px 1fr;
  min-height: 100vh;
}
aside {
  padding: 36px 22px;
  background: var(--surface-2);
  border-right: 1px solid #252d3c;
  display: flex;
  flex-direction: column;
}
.brand {
  font-size: 42px;
  letter-spacing: -3px;
  font-weight: 750;
  color: var(--accent);
}
.brand span {
  color: #fff;
}
.brand small {
  font-size: 9px;
  letter-spacing: 3px;
  margin-top: 5px;
  color: #93a0b5;
}
small {
  display: block;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.7;
}
nav {
  display: grid;
  gap: 3px;
  margin-top: 20px;
}
nav button {
  text-align: left;
  background: transparent;
  color: #aab4c7;
  font-weight: 500;
  padding: 8px 12px;
  font-size: 13px;
  border-radius: 6px;
}
.selected {
  background: #26382f !important;
  color: #b6f6d7 !important;
}
.local {
  margin-top: auto;
  padding-top: 15px;
  color: #b6f6d7;
  font-size: 11px;
}
.local small {
  margin-top: 4px;
}
main {
  padding: 36px 5vw;
  max-width: 1550px;
  width: 100%;
}
header {
  flex-wrap: wrap;
  gap: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 30px;
}
h1 {
  font-size: 30px;
  letter-spacing: -1px;
  margin: 8px 0;
}
h2 {
  font-size: 20px;
  letter-spacing: -0.4px;
}
.eyebrow {
  font-size: 10px;
  letter-spacing: 2.8px;
  color: #96a6bc;
}
.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}
article,
section {
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: 8px;
  padding: 10px 14px;
}
article strong {
  font-size: 23px;
  display: block;
  margin-top: 12px;
}
section {
  margin-top: 8px;
}
.voice {
  text-align: center;
  padding: 44px 20px;
  background: radial-gradient(ellipse at 50% 20%, #233c3a, var(--surface) 65%);
}
.orb {
  margin: 0 auto 20px;
  width: 100px;
  height: 100px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 65px;
  font-weight: 700;
  color: #b8ffdc;
  background: radial-gradient(circle at 35% 30%, #79bba0, #315851 55%, #172e32);
  box-shadow: 0 0 60px var(--accent)12;
}
.live {
  box-shadow: 0 0 60px var(--accent)40;
}
.voice p {
  color: #a7b5c8;
  line-height: 1.9;
}
.voice small {
  margin-top: 16px;
}
.pill {
  display: inline-block;
  padding: 5px 10px;
  border: 1px solid #3e4b60;
  border-radius: 20px;
  color: #bcc7d8;
  font-size: 11px;
}
.ok {
  color: var(--accent);
  border-color: var(--ok-border);
}
.muted {
  color: #96a5bc;
  line-height: 1.8;
}
.demo-banner {
  margin-bottom: 16px;
  padding: 12px 15px;
  border: 1px solid #b8923a;
  background: #3d3218;
  color: #ffe6ad;
  border-radius: 9px;
  overflow-wrap: anywhere;
}
.demo-banner strong {
  margin-right: 8px;
}
.error {
  padding: 15px;
  border: 1px solid var(--danger-border);
  background: var(--danger-bg);
  color: var(--danger-text);
  border-radius: 9px;
  overflow-wrap: anywhere;
}
.bubble {
  background: var(--surface-3);
  padding: 16px;
  border-radius: 10px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.bubble b {
  display: block;
  color: var(--accent);
  font-size: 11px;
  text-transform: uppercase;
  margin-bottom: 7px;
}
.user {
  background: #26372f;
}
.inline {
  display: flex;
  gap: 14px;
  align-items: end;
  flex-wrap: wrap;
}
label {
  display: grid;
  gap: 9px;
  color: #b8c4d7;
  font-size: 13px;
  flex: 1;
}
input,
textarea {
  background: var(--input-bg);
  border: 1px solid var(--border-strong);
  padding: 12px;
  color: var(--text-strong);
  border-radius: 8px;
  min-width: 0;
  width: 100%;
}
textarea {
  resize: vertical;
  margin-bottom: 18px;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 15px;
  border-bottom: 1px solid var(--border);
  padding: 18px 0;
}
.row:last-child {
  border: 0;
}
.two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
footer {
  font-size: 11px;
  color: #76869e;
  padding: 30px 0;
}
.login {
  max-width: 500px;
  margin: 10vh auto;
}
.login h1 {
  margin-top: 45px;
}
.login form {
  display: grid;
  gap: 20px;
  margin: 30px 0;
}
audio {
  margin-top: 20px;
  width: 100%;
}
@media (max-width: 800px) {
  .layout {
    grid-template-columns: 1fr;
  }
  aside {
    padding: 18px 20px;
  }
  .brand {
    font-size: 32px;
  }
  nav {
    margin-top: 20px;
    display: flex;
    overflow: auto;
    gap: 6px;
  }
  nav button {
    white-space: nowrap;
    font-size: 12px;
    padding: 10px;
  }
  .local {
    display: none;
  }
  main {
    padding: 22px 18px;
  }
  .stats {
    gap: 8px;
  }
  article {
    padding: 14px;
  }
  article strong {
    font-size: 16px;
  }
  .two {
    grid-template-columns: 1fr;
  }
  .inline {
    flex-direction: column;
    align-items: stretch;
  }
  section {
    padding: 18px;
  }
  .row {
    flex-wrap: wrap;
  }
  .login {
    padding: 24px;
  }
  .voice {
    padding: 30px 15px;
  }
}
select {
  font: inherit;
  background: var(--input-bg);
  color: var(--text-strong);
  border: 1px solid var(--border-strong);
  padding: 12px;
  border-radius: 8px;
  width: 100%;
  min-width: 0;
}
.layout {
  grid-template-columns: minmax(0, 248px) minmax(0, 1fr);
}
.two {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}
aside,
main,
section {
  min-width: 0;
}
@media (max-width: 800px) {
  .layout,
  .two {
    grid-template-columns: minmax(0, 1fr);
  }
}

.lexicon-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 15px;
}
.lexicon-table th,
.lexicon-table td {
  padding: 12px 14px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.lexicon-table th {
  font-size: 11px;
  text-transform: uppercase;
  color: #93a0b5;
  letter-spacing: 1px;
}
.badge-override {
  background: #3d3420;
  color: #fed7aa;
  border: 1px solid #78521a;
  padding: 3px 8px;
  border-radius: 12px;
  font-size: 11px;
}
.badge-custom {
  background: #1c353a;
  color: #99f6e4;
  border: 1px solid #115e59;
  padding: 3px 8px;
  border-radius: 12px;
  font-size: 11px;
}
.badge-base {
  background: #1f2937;
  color: #9ca3af;
  border: 1px solid #374151;
  padding: 3px 8px;
  border-radius: 12px;
  font-size: 11px;
}
.badge-cat {
  background: #252e40;
  color: #a5b4fc;
  border: 1px solid #374151;
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10px;
  text-transform: uppercase;
}

/* ---- Ortak bileşenler ---- */
.card {
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: 14px;
  padding: 24px;
  min-width: 0;
}
.card h2 {
  margin: 6px 0;
}

.supervisor-panel {
  min-width: 0;
  overflow-wrap: anywhere;
}
.supervisor-panel .row {
  flex-wrap: wrap;
}
.supervisor-panel label,
.supervisor-panel select {
  max-width: 100%;
}
.supervisor-panel table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
}
.supervisor-panel th,
.supervisor-panel td {
  padding: 8px 4px;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--border);
}
.supervisor-panel details,
.supervisor-panel form {
  margin-block: 12px;
}
.supervisor-panel form label {
  display: block;
  margin-block: 8px;
}
.supervisor-panel input[type="checkbox"] {
  width: auto;
}

.analysis-queue {
  padding-block: 8px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.analysis-facts,
.conversation-linked {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 155px), 1fr));
  gap: 10px;
}
.analysis-facts > div,
.conversation-linked > section {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
}
.analysis-facts dd {
  margin: 4px 0 0;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.conversation-history {
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
}
.conversation-detail {
  min-width: 0;
  overflow-wrap: anywhere;
}
.conversation-detail .row {
  flex-wrap: wrap;
}
.conversation-linked {
  margin-bottom: 20px;
}
.conversation-linked ul {
  padding-inline-start: 18px;
}
.operator-today {
  min-width: 0;
  overflow-wrap: anywhere;
}
.operator-today .row,
.operator-work-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.operator-work-list {
  list-style: none;
  padding: 0;
}
.operator-work-list small {
  display: block;
  margin-top: 4px;
}
.appointment-move-dialog {
  width: min(560px, calc(100% - 28px));
  max-height: calc(100dvh - 28px);
  overflow: auto;
  padding: 20px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: 12px;
}
.appointment-move-dialog::backdrop {
  background: rgb(4 8 15 / 70%);
}
.appointment-move-dialog select {
  max-width: 100%;
}
.appointment-move-dialog ul {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  list-style: none;
  padding: 0;
}
.appointment-move-dialog .row,
.appointment-row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
@media (max-width: 800px) {
  .conversation-history {
    grid-template-columns: minmax(0, 1fr);
  }
}
.section-container {
  display: block;
  min-width: 0;
}
.alert-box {
  padding: 15px;
  border: 1px solid var(--border-strong);
  border-radius: 9px;
  margin-bottom: 14px;
  overflow-wrap: anywhere;
}
.alert-box.error {
  border-color: var(--danger-border);
  background: var(--danger-bg);
  color: var(--danger-text);
}
.alert-box.success {
  border-color: #347458;
  background: #1c382f;
  color: #c9f7df;
}
.pill.green {
  color: var(--accent);
  border-color: var(--ok-border);
  background: #173026;
}
.pill.yellow {
  color: #fde68a;
  border-color: #8a6b1f;
  background: #3d3218;
}
.pill.red,
.pill.bad {
  color: #ffc1c1;
  border-color: #8f4450;
  background: #3a2029;
}
.pill.blue {
  color: #bfdbfe;
  border-color: #2f5a9e;
  background: #172a4a;
}
button.primary {
  background: var(--accent);
  color: var(--accent-ink);
}
.table-wrap {
  width: 100%;
  overflow-x: auto;
}
.table-wrap table {
  min-width: 520px;
}
.metrics {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px 16px;
  margin-top: 16px;
  font-size: 12px;
  color: #a7b5c8;
}
.metrics b {
  flex-basis: 100%;
  color: var(--muted);
  font-size: 11px;
  letter-spacing: 1px;
  text-transform: uppercase;
}
.grid-2,
.grid-3,
.grid-1-2,
.kpi-grid-3,
.kpi-grid-4 {
  display: grid;
  gap: 18px;
}
.grid-2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.grid-3,
.kpi-grid-3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.grid-1-2 {
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
}
.kpi-grid-4 {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
@media (max-width: 1000px) {
  .kpi-grid-4 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 800px) {
  .grid-3,
  .kpi-grid-3,
  .grid-1-2 {
    grid-template-columns: minmax(0, 1fr);
  }
  .card {
    padding: 14px;
  }
}
@media (max-width: 600px) {
  .grid-2,
  .kpi-grid-4 {
    grid-template-columns: minmax(0, 1fr);
  }
  .layout main {
    padding: 22px 16px;
  }
}

/* ==========================================================================
   FreyaTTS Automotive Cockpit V3 — Cockpit Layout & Components
   Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
   ========================================================================== */

.cockpit-layout {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  height: 100dvh;
  max-height: 100dvh;
  overflow: hidden;
  background: var(--bg);
}

.cockpit-sidebar {
  background: #090e17;
  border-right: 1px solid #1a2333;
  display: flex;
  flex-direction: column;
  height: 100dvh;
  max-height: 100dvh;
  overflow-y: auto;
  z-index: 20;
}

.sidebar-brand {
  padding: 22px 20px 14px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.brand-logo {
  display: flex;
  align-items: center;
  gap: 8px;
}

.brand-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 10px #10b981;
}

.brand-text {
  font-size: 22px;
  font-weight: 800;
  color: #fff;
  letter-spacing: -0.5px;
}

.brand-version {
  font-size: 10px;
  background: #059669;
  color: #fff;
  padding: 2px 6px;
  border-radius: 4px;
  margin-left: 6px;
  font-weight: 700;
  vertical-align: middle;
}

.brand-subtitle {
  font-size: 10px;
  letter-spacing: 2px;
  color: var(--muted);
  margin-top: 4px;
  text-transform: uppercase;
  font-weight: 600;
}

.sidebar-search {
  padding: 12px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.search-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 10px;
  font-size: 12px;
  opacity: 0.6;
}

.search-input {
  width: 100%;
  background: #0d1522;
  border: 1px solid #222f44;
  border-radius: 7px;
  padding: 8px 28px 8px 30px;
  font-size: 12px;
  color: var(--text);
  outline: none;
  transition: border-color 0.15s;
}

.search-input:focus {
  border-color: #38bdf8;
}

.clear-search-btn {
  position: absolute;
  right: 6px;
  background: transparent;
  border: none;
  color: var(--muted);
  padding: 2px 6px;
  font-size: 11px;
  cursor: pointer;
}

.sidebar-accordion {
  padding: 10px 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}

.nav-category {
  margin-bottom: 2px;
}

.category-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: transparent;
  padding: 7px 10px;
  border-radius: 6px;
  color: #8da2be;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  border: none;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.category-header:hover {
  background: rgba(255, 255, 255, 0.04);
  color: #cbd5e1;
}

.category-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cat-icon {
  font-size: 13px;
}

.cat-chevron {
  font-size: 10px;
  opacity: 0.7;
}

.category-tabs {
  list-style: none;
  margin: 3px 0 6px 0;
  padding: 0 0 0 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-tab-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: transparent;
  padding: 7px 10px;
  border-radius: 6px;
  color: #94a3b8;
  font-size: 12.5px;
  font-weight: 500;
  border: none;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s ease;
}

.nav-tab-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #e2e8f0;
}

.nav-tab-btn.active {
  background: #13382b;
  color: #6ee7b7;
  font-weight: 600;
  border-left: 3px solid #10b981;
}

.tab-icon-and-name {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tab-icon {
  font-size: 13px;
  flex-shrink: 0;
}

.tab-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tab-tags {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.stage-badge {
  font-size: 9.5px;
  font-family: monospace;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(56, 189, 248, 0.12);
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.25);
}

.count-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 10px;
  background: #253348;
  color: #f1f5f9;
}

.sidebar-footer {
  padding: 14px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 11px;
  color: var(--muted);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.local-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #10b981;
  font-weight: 600;
}

.indicator-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
}

.sidebar-version {
  font-size: 10px;
  opacity: 0.7;
}

.no-search-results {
  padding: 16px 12px;
  text-align: center;
  font-size: 12px;
  color: var(--muted);
}

.reset-search-btn {
  margin-top: 8px;
  padding: 5px 10px;
  font-size: 11px;
  background: #222f44;
  color: #cbd5e1;
  border: 1px solid #334460;
  border-radius: 6px;
  cursor: pointer;
}

.cockpit-main-workspace {
  flex: 1;
  height: 100dvh;
  max-height: 100dvh;
  padding: 8px 16px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.cockpit-content-viewport {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Layer A — Cockpit Header */
.cockpit-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 0 6px 0;
  border-bottom: 1px solid var(--border);
  margin-bottom: 6px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  flex-direction: column;
}

.tab-eyebrow {
  font-size: 10px;
  letter-spacing: 2px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
  margin: 0 0 4px 0;
}

.tab-current-title {
  font-size: 26px;
  font-weight: 800;
  margin: 0;
  color: var(--text-strong);
  letter-spacing: -0.5px;
}

.header-center-health {
  display: flex;
  align-items: center;
}

.health-pills-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid #1f2c42;
  padding: 4px 8px;
  border-radius: 20px;
}

.health-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 14px;
  font-size: 11px;
  font-weight: 600;
}

.health-pill.ready,
.health-pill.breaker-closed {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.health-pill.blocked,
.health-pill.breaker-open {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.health-pill.breaker-half_open {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.header-right-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mode-toggle-box {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #111a28;
  border: 1px solid #233146;
  padding: 4px 12px;
  border-radius: 8px;
}

.mode-label {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  letter-spacing: 0.5px;
}

.mode-active-reel {
  color: #10b981;
  text-shadow: 0 0 8px rgba(16, 185, 129, 0.4);
}

.mode-active-demo {
  color: #f59e0b;
  text-shadow: 0 0 8px rgba(245, 158, 11, 0.4);
}

.mode-switch {
  position: relative;
  display: inline-block;
  width: 44px;
  height: 22px;
}

.mode-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.mode-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: #059669;
  transition: 0.3s;
  border-radius: 22px;
}

.mode-slider:before {
  position: absolute;
  content: ;
 height: 16px;
 width: 16px;
 left: 3px;
 bottom: 3px;
 background: white;
 transition: 0.3s;
 border-radius: 50%;
}

.mode-switch input:checked + .mode-slider {
 background: #d97706;
}

.mode-switch input:checked + .mode-slider:before {
 transform: translateX(22px);
}

.header-btn {
 padding: 8px 16px;
 font-size: 12px;
 border-radius: 7px;
 font-weight: 600;
 cursor: pointer;
}

.header-btn.secondary {
 background: #192334;
 color: #d1d9e7;
 border: 1px solid #28374e;
}

.header-btn.secondary:hover {
 background: #223046;
}

.header-btn.logout-btn {
 background: transparent;
 color: #f87171;
 border: 1px solid rgba(239, 68, 68, 0.3);
}

.header-btn.logout-btn:hover {
 background: rgba(239, 68, 68, 0.1);
}

/* Layer B — Audio Pipeline Stepper */
.pipeline-stepper-container {
  background: linear-gradient(180deg, #131b2e 0%, #0e1524 100%);
  border: 1px solid #1e293b;
  border-radius: 8px;
  padding: 6px 10px;
  margin-bottom: 6px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
}

.pipeline-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 4px;
  padding-bottom: 4px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.pipeline-title-box {
 display: flex;
 align-items: center;
 gap: 10px;
}

.pipeline-pulse-icon {
 width: 8px;
 height: 8px;
 border-radius: 50%;
 background: #38bdf8;
 box-shadow: 0 0 10px #38bdf8;
 animation: pulse 2s infinite;
}

.pipeline-title {
 font-size: 12.5px;
 font-weight: 800;
 letter-spacing: 0.8px;
 color: #e2e8f0;
 margin: 0;
 text-transform: uppercase;
}

.telemetry-source-tag {
 font-size: 9.5px;
 font-weight: 800;
 padding: 2px 7px;
 border-radius: 4px;
 letter-spacing: 0.5px;
}

.telemetry-source-tag.source-live {
 background: rgba(16, 185, 129, 0.2);
 color: #34d399;
 border: 1px solid #059669;
}

.telemetry-source-tag.source-demo {
 background: rgba(245, 158, 11, 0.2);
 color: #fbbf24;
 border: 1px solid #d97706;
}

.telemetry-source-tag.source-replay {
 background: rgba(139, 92, 246, 0.2);
 color: #a78bfa;
 border: 1px solid #7c3aed;
}

.streaming-badge {
 font-size: 9.5px;
 font-weight: 700;
 padding: 2px 6px;
 border-radius: 4px;
 background: rgba(56, 189, 248, 0.2);
 color: #38bdf8;
 animation: pulse 1.5s infinite;
}

.pipeline-latency-box {
 display: flex;
 align-items: center;
 gap: 10px;
}

.latency-label {
 font-size: 11px;
 color: var(--muted);
}

.latency-value {
 font-size: 14px;
 font-weight: 800;
 color: #38bdf8;
 font-family: monospace;
}

.latency-target {
 font-size: 11px;
 color: #64748b;
}

.scenario-quick-actions {
 display: flex;
 align-items: center;
 gap: 6px;
 margin-left: 10px;
}

.btn-scenario {
 background: rgba(51, 65, 85, 0.6);
 color: #cbd5e1;
 border: 1px solid #475569;
 padding: 4px 10px;
 font-size: 11px;
 border-radius: 6px;
 font-weight: 600;
 cursor: pointer;
 transition: all 0.15s;
}

.btn-scenario:hover {
 background: #3b82f6;
 color: white;
 border-color: #3b82f6;
}

.pipeline-stages-track {
 display: flex;
 align-items: stretch;
 gap: 6px;
 overflow-x: auto;
 padding: 4px 0;
}

.stage-card {
  flex: 1;
  min-width: 95px;
  background: #141d2e;
  border: 1px solid #202d42;
  border-radius: 6px;
  padding: 5px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s ease;
  position: relative;
}

.stage-card:hover {
 border-color: #38bdf8;
 transform: translateY(-2px);
 box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.stage-card.selected {
 border-color: #38bdf8;
 background: #19253c;
 box-shadow: 0 0 0 1px #38bdf8;
}

.stage-card.status-running {
 border-color: #f59e0b;
 background: rgba(245, 158, 11, 0.08);
}

.stage-card.status-completed {
 border-color: #10b981;
}

.stage-card.status-failed {
 border-color: #ef4444;
 background: rgba(239, 68, 68, 0.08);
}

.stage-card-header {
 display: flex;
 align-items: center;
 justify-content: space-between;
}

.stage-code {
 font-size: 12px;
 font-family: monospace;
 font-weight: 800;
 color: #38bdf8;
}

.status-led {
 width: 8px;
 height: 8px;
 border-radius: 50%;
}

.status-led.led-idle { background: #475569; }
.status-led.led-queued { background: #94a3b8; }
.status-led.led-running { background: #f59e0b; box-shadow: 0 0 8px #f59e0b; }
.status-led.led-completed { background: #10b981; box-shadow: 0 0 8px #10b981; }
.status-led.led-failed { background: #ef4444; box-shadow: 0 0 8px #ef4444; }
.status-led.led-cancelled { background: #f97316; }
.status-led.led-skipped { background: #64748b; }
.status-led.led-bypassed { background: #06b6d4; }

.stage-card-name {
 font-size: 12px;
 font-weight: 700;
 color: #f1f5f9;
 white-space: nowrap;
 overflow: hidden;
 text-overflow: ellipsis;
}

.stage-card-desc {
 font-size: 10px;
 color: #94a3b8;
 line-height: 1.3;
 height: 26px;
 overflow: hidden;
}

.stage-card-footer {
 display: flex;
 align-items: center;
 justify-content: space-between;
 margin-top: auto;
 padding-top: 6px;
 border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.stage-latency {
 font-size: 11px;
 font-family: monospace;
 font-weight: 700;
 color: #38bdf8;
}

.inspector-hint {
 font-size: 9.5px;
 color: #64748b;
}

.stage-connector {
 display: flex;
 align-items: center;
 justify-content: center;
 color: #27364d;
 font-size: 14px;
 user-select: none;
 padding: 0 2px;
}

.stage-connector.completed {
 color: #10b981;
}

/* Layer C — Engineering Inspector Drawer */
.pipeline-inspector-drawer {
 position: fixed;
 top: 0;
 right: 0;
 width: 440px;
 max-width: 90vw;
 height: 100vh;
 background: #0d1424;
 border-left: 1px solid #1e293b;
 box-shadow: -8px 0 30px rgba(0, 0, 0, 0.6);
 z-index: 1000;
 display: flex;
 flex-direction: column;
 overflow: hidden;
 animation: slideInRight 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideInRight {
 from {
 transform: translateX(100%);
 }
 to {
 transform: translateX(0);
 }
}

.inspector-header {
 display: flex;
 align-items: center;
 justify-content: space-between;
 padding: 16px 20px;
 border-bottom: 1px solid #1e293b;
 background: #080d18;
}

.inspector-title-group {
 display: flex;
 align-items: center;
 gap: 12px;
}

.inspector-code-pill {
 font-size: 14px;
 font-weight: 800;
 font-family: monospace;
 background: rgba(56, 189, 248, 0.15);
 color: #38bdf8;
 padding: 4px 10px;
 border-radius: 6px;
 border: 1px solid #0284c7;
}

.inspector-titles {
 display: flex;
 flex-direction: column;
}

.inspector-title {
 font-size: 15px;
 font-weight: 700;
 margin: 0;
 color: #f8fafc;
}

.inspector-subtitle {
 font-size: 11px;
 color: #94a3b8;
 margin: 2px 0 0 0;
}

.inspector-header-actions {
 display: flex;
 align-items: center;
 gap: 8px;
}

.btn-jump-tab {
 background: rgba(56, 189, 248, 0.15);
 color: #38bdf8;
 border: 1px solid #0284c7;
 padding: 6px 12px;
 font-size: 11px;
 border-radius: 6px;
 font-weight: 600;
 cursor: pointer;
}

.btn-jump-tab:hover {
 background: #0284c7;
 color: #fff;
}

.inspector-close-btn {
 background: transparent;
 border: none;
 color: #94a3b8;
 font-size: 16px;
 padding: 6px 10px;
 cursor: pointer;
 border-radius: 6px;
}

.inspector-close-btn:hover {
 color: #fff;
 background: rgba(255, 255, 255, 0.06);
}

.inspector-subtabs {
 display: flex;
 border-bottom: 1px solid #1e293b;
 background: #080d18;
 padding: 0 12px;
}

.inspector-subtabs button {
 background: transparent;
 border: none;
 color: #94a3b8;
 padding: 10px 14px;
 font-size: 12px;
 font-weight: 600;
 cursor: pointer;
 border-bottom: 2px solid transparent;
 border-radius: 0;
}

.inspector-subtabs button:hover {
 color: #f1f5f9;
}

.inspector-subtabs button.active {
 color: #38bdf8;
 border-bottom-color: #38bdf8;
}

.inspector-content {
 flex: 1;
 overflow-y: auto;
 padding: 18px 20px;
 display: flex;
 flex-direction: column;
 gap: 16px;
}

.params-table {
 width: 100%;
 border-collapse: collapse;
 font-size: 12px;
}

.params-table th,
.params-table td {
 padding: 8px 10px;
 text-align: left;
 border-bottom: 1px solid #1e293b;
}

.params-table th {
 color: #94a3b8;
 font-weight: 600;
}

.params-table td {
 color: #e2e8f0;
 font-family: monospace;
}

.metric-card {
 background: #141c2c;
 padding: 12px;
 border-radius: 8px;
 border: 1px solid #233046;
}

.trace-log {
 background: #060a12;
 padding: 12px;
 border-radius: 6px;
 font-family: monospace;
 font-size: 11px;
 color: #a5f3fc;
 overflow-x: auto;
 white-space: pre-wrap;
}

/* Audio Visualizer Card */
.audio-visualizer-card {
 background: #0b1120;
 border: 1px solid #1e293b;
 border-radius: 10px;
 padding: 14px 18px;
 margin-bottom: 20px;
}

.visualizer-header {
 display: flex;
 align-items: center;
 justify-content: space-between;
 margin-bottom: 10px;
}

.visualizer-title {
 font-size: 12px;
 font-weight: 700;
 color: #cbd5e1;
 text-transform: uppercase;
 letter-spacing: 0.5px;
}

.visualizer-controls {
 display: flex;
 align-items: center;
 gap: 8px;
}

.visualizer-mode-btn {
 background: #1e293b;
 border: 1px solid #334155;
 color: #94a3b8;
 font-size: 11px;
 padding: 3px 8px;
 border-radius: 4px;
 cursor: pointer;
}

.visualizer-mode-btn.active {
 background: #38bdf8;
 color: #0b1120;
 font-weight: 700;
 border-color: #38bdf8;
}

.visualizer-canvas {
 width: 100%;
 height: 110px;
 border-radius: 6px;
 display: block;
}

.visualizer-footer {
 display: flex;
 align-items: center;
 justify-content: space-between;
 margin-top: 10px;
 font-size: 11px;
 color: #94a3b8;
}

.calibration-pill {
 display: inline-flex;
 align-items: center;
 gap: 6px;
 padding: 3px 8px;
 border-radius: 12px;
 background: rgba(16, 185, 129, 0.15);
 color: #34d399;
 border: 1px solid rgba(16, 185, 129, 0.3);
}

.btn-recalibrate {
 background: #1e293b;
 border: 1px solid #334155;
 color: #cbd5e1;
 padding: 4px 10px;
 font-size: 11px;
 border-radius: 6px;
 cursor: pointer;
}

.btn-recalibrate:hover {
 background: #334155;
}

@keyframes pulse {
 0%, 100% { opacity: 1; }
 50% { opacity: 0.4; }
}

@keyframes borderGlow {
 0%, 100% { border-color: #f59e0b; }
 50% { border-color: #d97706; }
}



/* ============================================================================
   Enhanced AudioVisualizer & Acoustic Cockpit Controls
   ============================================================================ */
.av-card-wrapper {
  background: rgba(15, 23, 42, 0.95);
  border: 1px solid rgba(56, 189, 248, 0.3);
  border-radius: 8px;
  padding: 6px 10px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  gap: 4px;
  backdrop-filter: blur(8px);
  flex-shrink: 0;
}

.av-top-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.av-btn-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.av-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s ease;
  user-select: none;
}

.av-btn-primary {
  background: linear-gradient(135deg, #0284c7 0%, #10b981 100%);
  color: #020617;
  box-shadow: 0 4px 12px rgba(2, 132, 199, 0.25);
}
.av-btn-primary:hover {
  filter: brightness(1.1);
}

.av-btn-danger {
  background: #ef4444;
  color: #fff;
  border-color: #f87171;
  box-shadow: 0 0 15px rgba(239, 68, 68, 0.4);
  animation: pulse 1.5s infinite;
}

.av-btn-active-emerald {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
  border-color: rgba(16, 185, 129, 0.6);
}

.av-btn-active-sky {
  background: rgba(56, 189, 248, 0.2);
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.6);
}

.av-btn-active-amber {
  background: #f59e0b;
  color: #0f172a;
  border-color: #fbbf24;
  box-shadow: 0 4px 15px rgba(245, 158, 11, 0.35);
  transform: scale(0.98);
}

.av-btn-outline {
  background: #090d16;
  color: #94a3b8;
  border-color: rgba(255, 255, 255, 0.12);
}
.av-btn-outline:hover {
  color: #f8fafc;
  border-color: rgba(255, 255, 255, 0.25);
}

.av-gate-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 8px;
  font-family: monospace;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid;
}

.av-gate-badge.gate-open {
  background: rgba(16, 185, 129, 0.2);
  border-color: rgba(16, 185, 129, 0.5);
  color: #6ee7b7;
}

.av-gate-badge.gate-locked {
  background: rgba(245, 158, 11, 0.15);
  border-color: rgba(245, 158, 11, 0.4);
  color: #fde68a;
}

.gate-led {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.av-alert-error {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: #fef08a;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 12px;
}

.av-meters-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}

.av-meter-box {
  background: #090d16;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 8px;
}

.av-meter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.av-meter-label {
  color: #94a3b8;
}

.av-meter-val {
  color: #38bdf8;
  font-weight: bold;
}

.av-progress-track {
  width: 100%;
  height: 6px;
  background: #1e293b;
  border-radius: 9999px;
  overflow: hidden;
}

.av-progress-bar {
  height: 100%;
  border-radius: 9999px;
  transition: width 0.08s ease;
}

.av-sliders-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.av-slider-header {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: #94a3b8;
  margin-bottom: 2px;
}

.av-range-slider {
  width: 100%;
  height: 4px;
  accent-color: #38bdf8;
  cursor: pointer;
}

.av-log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.av-test-btn-group {
  display: flex;
  gap: 4px;
}

.av-test-btn {
  background: #1e293b;
  color: #cbd5e1;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 10px;
  cursor: pointer;
}
.av-test-btn:hover {
  background: #334155;
  color: #fff;
}

.av-log-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 52px;
  overflow-y: auto;
}

.av-log-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(245, 158, 11, 0.2);
  border-radius: 6px;
  padding: 3px 8px;
  font-size: 10px;
}

.av-input-form {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.av-text-input {
  flex: 1;
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 11px;
  color: #f8fafc;
  font-family: monospace;
}
.av-text-input:focus {
  outline: none;
  border-color: #38bdf8;
}

.av-send-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #38bdf8;
  color: #020617;
  border: 0;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
}

.av-canvas-container {
  position: relative;
  background: #090d16;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 10px;
  overflow: hidden;
}

.av-canvas {
  width: 100%;
  height: 44px;
  display: block;
}

.av-canvas-badge-top {
  position: absolute;
  top: 8px;
  left: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(2, 6, 23, 0.85);
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 3px 8px;
  border-radius: 6px;
  font-family: monospace;
  font-size: 10px;
  color: #6ee7b7;
}

.av-canvas-badge-bottom {
  position: absolute;
  bottom: 8px;
  left: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(2, 6, 23, 0.85);
  border: 1px solid rgba(56, 189, 248, 0.3);
  padding: 3px 8px;
  border-radius: 6px;
  font-family: monospace;
  font-size: 10px;
  color: #7dd3fc;
}

.av-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.av-barge-in-banner {
  position: absolute;
  top: 8px;
  right: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(245, 158, 11, 0.25);
  border: 1px solid #f59e0b;
  padding: 4px 10px;
  border-radius: 6px;
  font-family: monospace;
  font-size: 11px;
  font-weight: bold;
  color: #fde68a;
  animation: pulse 1.2s infinite;
}


/* ============================================================================
   KOKPİT GÖRÜŞME & ÇİFT SÜTUN AKIŞI (VoiceTab V3)
   ============================================================================ */
.cockpit-view-container {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  height: 100%;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

.cockpit-top-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  flex-shrink: 0;
}

.cockpit-stat-card {
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  padding: 4px 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
}

.cockpit-stat-label {
  font-size: 10px;
  font-family: monospace;
  color: #94a3b8;
  text-transform: uppercase;
}

.cockpit-stat-value {
  font-size: 12.5px;
  font-weight: 700;
  color: #f8fafc;
}

.cockpit-main-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 8px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.cockpit-chat-card {
  background: rgba(15, 23, 42, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 6px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.cockpit-chat-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.cockpit-chat-title {
  font-size: 13px;
  font-weight: 700;
  color: #e2e8f0;
  display: flex;
  align-items: center;
  gap: 8px;
  letter-spacing: 0.3px;
}

.cockpit-chat-channel {
  font-size: 11px;
  font-family: monospace;
  color: #34d399;
}

.cockpit-chat-feed {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px 8px 6px 2px;
}

.cockpit-msg-bubble {
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid transparent;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all 0.2s ease;
}

.cockpit-msg-bubble.leyla {
  background: rgba(6, 78, 59, 0.28);
  border-color: rgba(16, 185, 129, 0.35);
  margin-left: 20px;
}

.cockpit-msg-bubble.customer {
  background: rgba(12, 74, 110, 0.28);
  border-color: rgba(14, 165, 233, 0.35);
  margin-right: 20px;
}

.cockpit-msg-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  font-family: monospace;
}

.cockpit-msg-speaker-leyla {
  color: #34d399;
  font-weight: 700;
}

.cockpit-msg-speaker-customer {
  color: #38bdf8;
  font-weight: 700;
}

.cockpit-msg-meta {
  color: #94a3b8;
}

.cockpit-msg-text {
  font-size: 13.5px;
  color: #f1f5f9;
  line-height: 1.55;
  margin: 0;
}

.cockpit-quick-chips {
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cockpit-chips-label {
  font-size: 11px;
  font-family: monospace;
  color: #94a3b8;
}

.cockpit-chips-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.cockpit-chip-btn {
  background: #1e293b;
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #7dd3fc;
  font-size: 12px;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: inherit;
}

.cockpit-chip-btn:hover {
  background: #334155;
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.4);
}

.cockpit-sidebar-col {
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  max-height: 100%;
  min-height: 0;
  padding-right: 2px;
}

.cockpit-card {
  background: rgba(15, 23, 42, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 6px 10px;
  box-shadow: 0 4px 15px -3px rgba(0, 0, 0, 0.3);
}

.cockpit-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.cockpit-card-title {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #cbd5e1;
  display: flex;
  align-items: center;
  gap: 6px;
}

.cockpit-badge-plate {
  padding: 3px 8px;
  border-radius: 6px;
  background: rgba(16, 185, 129, 0.2);
  color: #6ee7b7;
  font-family: monospace;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid rgba(16, 185, 129, 0.4);
}

.cockpit-info-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 12px;
}

.cockpit-info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.cockpit-info-row:last-child {
  border-bottom: none;
}

.cockpit-info-key {
  color: #94a3b8;
}

.cockpit-info-val {
  color: #f8fafc;
  font-weight: 600;
}

.cockpit-json-block {
  font-family: monospace;
  font-size: 11px;
  color: #7dd3fc;
  background: #090d16;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  margin: 0;
  overflow-x: auto;
  line-height: 1.5;
}

.cockpit-dtmf-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  margin-top: 10px;
}

.cockpit-dtmf-btn {
  padding: 8px 0;
  background: #090d16;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  color: #f8fafc;
  font-family: monospace;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}

.cockpit-dtmf-btn:hover {
  background: #1e293b;
  border-color: #38bdf8;
  color: #38bdf8;
}

.cockpit-latency-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  font-family: monospace;
  font-size: 11px;
  margin-top: 8px;
}

.cockpit-latency-item {
  background: #090d16;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  justify-content: space-between;
}


/* Canlı Görüşme Akışı Doğrudan Metin Girişi */
.cockpit-chat-input-form {
  display: flex;
  gap: 10px;
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.cockpit-chat-input-field {
  flex: 1;
  background: #090d16;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 8px;
  padding: 10px 14px;
  color: #f8fafc;
  font-size: 13px;
  outline: none;
  transition: all 0.2s ease;
  font-family: inherit;
}

.cockpit-chat-input-field:focus {
  border-color: #38bdf8;
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
}

.cockpit-chat-send-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: linear-gradient(135deg, #0284c7, #0369a1);
  border: 1px solid #38bdf8;
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
  padding: 10px 18px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.cockpit-chat-send-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #0ea5e9, #0284c7);
  box-shadow: 0 0 14px rgba(56, 189, 248, 0.4);
}

.cockpit-chat-send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ==========================================================================
   MISSION CONTROL / STUDIO WORKBENCH — SES & YAPAY ZEKÂ HATTI (F0–F6)
   baseline-ui, Frontend Design & web-design-reviewer standartları
   Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
   ========================================================================== */

/* Statik Aşama Rozeti (Static Header Stage Badge) */
.stage-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  font-family: var(--font-mono, 'JetBrains Mono', 'Segoe UI', monospace);
  border: 1px solid currentColor;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}
.stage-badge.brand {
  color: #34d399;
  background: rgba(52, 211, 153, 0.12);
  border-color: rgba(52, 211, 153, 0.35);
}
.stage-badge.info {
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.12);
  border-color: rgba(56, 189, 248, 0.35);
}
.stage-badge.warn {
  color: #fbbf24;
  background: rgba(251, 191, 36, 0.12);
  border-color: rgba(251, 191, 36, 0.35);
}
.stage-badge.purple {
  color: #c084fc;
  background: rgba(192, 132, 252, 0.12);
  border-color: rgba(192, 132, 252, 0.35);
}

/* Tabular Rakamlar (baseline-ui gereksinimi) */
.tabular-data {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum";
  font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
}

/* 12 Sütunlu Modüler Workbench Izgarası */
.workbench-grid {
  display: grid;
  grid-template-columns: 3.5fr 5fr 3.5fr;
  gap: 10px;
  align-items: stretch;
  flex: 1;
  min-height: 0;
  height: calc(100% - 36px);
  margin-top: 6px;
  overflow: hidden;
}
@media (max-width: 1280px) {
  .workbench-grid {
    grid-template-columns: 1fr 1fr;
  }
  .workbench-grid > .workbench-col:last-child {
    grid-column: 1 / -1;
  }
}
@media (max-width: 768px) {
  .workbench-grid {
    grid-template-columns: 1fr;
  }
}

/* Workbench Sütun Kartları */
.workbench-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  height: 100%;
  overflow-y: auto;
  padding-right: 3px;
}
.workbench-card {
  background: #111827;
  border: 1px solid #232f45;
  border-radius: 8px;
  padding: 10px 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
  transition: border-color 150ms ease-out;
  flex-shrink: 0;
}
.workbench-card:hover {
  border-color: #354769;
}
.workbench-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid #1f2a3e;
}
.workbench-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0;
}

/* Segmented Control / Pill Switcher */
.pill-switcher {
  display: inline-flex;
  background: #090e17;
  border: 1px solid #222e42;
  border-radius: 8px;
  padding: 3px;
  gap: 3px;
}
.pill-btn {
  background: transparent;
  border: 0;
  color: #94a3b8;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 150ms ease-out;
}
.pill-btn:hover {
  color: #f8fafc;
  background: rgba(255, 255, 255, 0.05);
}
.pill-btn.active {
  background: #1e293b;
  color: #34d399;
  font-weight: 700;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
}

/* Telemetri / Metrik Kartları */
.metric-tile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 10px;
}
.metric-tile {
  background: #0b111d;
  border: 1px solid #1e293d;
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.metric-tile-label {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
}
.metric-tile-value {
  font-size: 18px;
  font-weight: 800;
  color: #38bdf8;
}
.metric-tile-sub {
  font-size: 10.5px;
  color: #64748b;
}

/* Şablon / Önayar Düğme Izgarası */
.preset-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.preset-btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  text-align: left;
  background: #0b111d;
  border: 1px solid #1e2a3f;
  color: #e2e8f0;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 150ms ease-out;
}
.preset-btn:hover {
  background: #141e30;
  border-color: #34d399;
  color: #ffffff;
}

/* Normalizasyon Diff Görselleştirici */
.diff-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #090e17;
  border: 1px solid #1f2b3e;
  border-radius: 8px;
  padding: 12px;
  margin-top: 10px;
}
.diff-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 12.5px;
}
.diff-tag {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  text-transform: uppercase;
  flex-shrink: 0;
}
.diff-tag.original {
  background: rgba(248, 113, 113, 0.15);
  color: #f87171;
  border: 1px solid rgba(248, 113, 113, 0.3);
}
.diff-tag.normalized {
  background: rgba(52, 211, 153, 0.15);
  color: #34d399;
  border: 1px solid rgba(52, 211, 153, 0.3);
}
````
