import React, { useState, useEffect, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { errorMessage } from "./ui";
import { createApi } from "./api";
import type { Appointment, Conversation, Health, Quote, Slot, Turn, Vehicle } from "./api";
import { MAIN_DATA_TABS, TABS } from "./nav";
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
  TechnicianDictationPanel,
} from "./lazyPanels";

function App() {
  const [password, setPassword] = useState(""),
    [logged, setLogged] = useState(false),
    [tab, setTab] = useState("Görüşme"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<Health>({}),
    [quotes, setQuotes] = useState<Quote[]>([]),
    [vehicles, setVehicles] = useState<Vehicle[]>([]),
    [slots, setSlots] = useState<Slot[]>([]),
    [appointments, setAppointments] = useState<Appointment[]>([]),
    [calls, setCalls] = useState<Conversation[]>([]),
    [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState(
      "Volkswagen Passat 1.5 TSI aracınızın tahmini değeri 1.250.000 TL.",
    ),
    [normalized, setNormalized] = useState(""),
    [audioUrl, setAudioUrl] = useState("");
  const { api, rawApi } = createApi(password);
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
    setTurns([]);
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
    <div className="layout">
      <aside>
        <div className="brand">
          f<span>reya</span>
          <small>OTOMOTİV ASİSTANI</small>
        </div>
        <nav>
          {TABS.map((t) => (
            <button
              key={t}
              className={tab === t ? "selected" : ""}
              aria-current={tab === t ? "page" : undefined}
              onClick={() => {
                setTab(t);
                setError("");
                if (MAIN_DATA_TABS.includes(t)) action(refresh);
              }}
            >
              {t}
            </button>
          ))}
        </nav>
        <div className="local">
          ● Modeller yerel<small>İstanbul</small>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <p className="eyebrow">EKSPERTİZ OPERASYONU</p>
            <h1>{tab}</h1>
          </div>
          <div className="inline" style={{ flex: "0 0 auto" }}>
            <button
              className="secondary"
              onClick={() => action(refresh)}
              disabled={busy}
            >
              Yenile ↻
            </button>
            <button className="secondary" onClick={logout}>
              Çıkış
            </button>
          </div>
        </header>
        {health.demo_mode && (
          <div role="status" className="demo-banner">
            <strong>DEMO MODU</strong> Bu paneldeki görüşmeler, gecikme değerleri
            ve kayıtlar örnek veridir; gerçek ölçüm veya müşteri kaydı değildir.
          </div>
        )}
        {error && (
          <div role="alert" className="error">
            {error}
          </div>
        )}
        {tab === "Görüşme" && (
          <VoiceTab
            busy={busy}
            health={health}
            appointments={appointments}
            vehicles={vehicles}
            voice={voice}
            onStart={() => action(voice.start)}
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
            turns={turns}
            setTurns={setTurns}
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
          {tab === "Operatör (6002)" && <OperatorPanel api={api} onError={setError} />}
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
        <footer>
          Freya Automotive · Yerel çalışma alanı · Fiyatlar yalnızca kayıtlı
          veriden aktarılır.
        </footer>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
