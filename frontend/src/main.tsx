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
