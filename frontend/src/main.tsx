import React, { useState, useEffect, useMemo, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { errorMessage } from "./ui";
import { createApi } from "./api";
import type { Appointment, Conversation, Health, Quote, Slot, Vehicle } from "./api";
import { MAIN_DATA_TABS, TABS, TabName } from "./nav";
import { SidebarNav } from "./SidebarNav";
import { CockpitHeader } from "./CockpitHeader";
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
    const [h, v, s, a, c, q] = await Promise.all(
      [
        "readiness",
        "vehicles",
        "slots",
        "appointments",
        "conversations",
        "quotes",
      ].map((x) => api(x)),
    );
    setHealth(h);
    setVehicles(v);
    setSlots(s);
    setAppointments(a);
    setCalls(c);
    setQuotes(q);
  }
  async function handleToggleMode(isDemo: boolean) {
    await action(async () => {
      // 1. Arka uçta veritabanını ve önbellekleri deterministik olarak değiştir
      await api("system/mode", "POST", { demo_mode: isDemo });
      // 2. Ana durum ve liste verilerini yeni veritabanından çek
      const [h, v, s, a, c, q] = await Promise.all(
        [
          "readiness",
          "vehicles",
          "slots",
          "appointments",
          "conversations",
          "quotes",
        ].map((x) => api(x)),
      );
      setHistoryId(null);
      setQualityConversationId(undefined);
      setHealth(h);
      setVehicles(v);
      setSlots(s);
      setAppointments(a);
      setCalls(c);
      setQuotes(q);
      // 3. En son refreshTick'i artırarak tüm aktif/pasif alt panellerin (Inspection, Analytics, Queue vb.)
      // unmount olup yeni veritabanından tertemiz verilerle remount edilmesini sağla
      setRefreshTick((t) => t + 1);
    });
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
          onToggleDemoMode={handleToggleMode}
          onRefresh={() => {
            setRefreshTick((t) => t + 1);
            void action(refresh);
          }}
          onLogout={logout}
        />
        {health.demo_mode ? (
          <div role="status" className="demo-banner">
            <strong>DEMO MODU</strong> Bu paneldeki görüşmeler, gecikme değerleri
            ve kayıtlar örnek veridir; gerçek ölçüm veya müşteri kaydı değildir.
          </div>
        ) : (
          <div
            role="status"
            style={{
              background: "rgba(6, 78, 59, 0.4)",
              color: "#6ee7b7",
              border: "1px solid #059669",
              padding: "8px 14px",
              borderRadius: "6px",
              margin: "0 0 16px 0",
              fontSize: "12px",
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <span
              style={{
                display: "inline-block",
                width: "8px",
                height: "8px",
                borderRadius: "50%",
                background: "#10b981",
                boxShadow: "0 0 8px #10b981",
              }}
            />
            <strong>REEL (CANLI) MOD</strong> Gerçek operasyon veritabanı aktif; yalnızca gerçek müşteri kayıtları ve canlı ölçümler listelenir.
          </div>
        )}
        {error && (
          <div role="alert" className="error">
            {error}
          </div>
        )}
        <div key={`${tab}-${health.demo_mode ? "demo" : "reel"}-${refreshTick}`}>
          {tab === "Görüşme" && (
            <VoiceTab
              busy={busy}
              health={health}
              appointments={appointments}
              vehicles={vehicles}
              voice={voice}
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
            {tab === "Operatör (6002)" && <OperatorPanel api={api} onError={setError} onOpenConversation={openConversation} />}
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
        <footer>
          Freya Automotive · Yerel çalışma alanı · Fiyatlar yalnızca kayıtlı
          veriden aktarılır.
        </footer>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
