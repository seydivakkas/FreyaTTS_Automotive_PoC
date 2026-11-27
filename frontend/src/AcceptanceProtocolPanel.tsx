/**
 * FreyaTTS Automotive Cockpit V3 — Canlı Mikrofon Kabul Koşuları & Otomotiv Terim Doğrulama Protokolü
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Download,
  FileCheck2,
  Mic,
  Play,
  RefreshCw,
  Shield,
  Volume2,
  Wrench,
  XCircle,
} from "lucide-react";
import type { TabName } from "./nav";
import type { ApiFn } from "./ui";
import { errorMessage } from "./ui";

interface Props {
  api: ApiFn;
  onNavigateToTab?: (tab: TabName) => void;
  onRefreshMain?: () => Promise<void> | void;
}

const ACTIVE_RUN_STORAGE_KEY = "freya_active_acceptance_run_id";

function statusStyle(status?: string) {
  if (status === "PASS" || status === "READY") {
    return {
      bg: "rgba(16, 185, 129, 0.16)",
      color: "#34d399",
      border: "1px solid rgba(16, 185, 129, 0.45)",
    };
  }
  if (status === "FAIL" || status === "BLOCKED") {
    return {
      bg: "rgba(239, 68, 68, 0.16)",
      color: "#f87171",
      border: "1px solid rgba(239, 68, 68, 0.45)",
    };
  }
  if (status === "WARN" || status === "INCOMPLETE" || status === "HOLD") {
    return {
      bg: "rgba(245, 158, 11, 0.16)",
      color: "#fbbf24",
      border: "1px solid rgba(245, 158, 11, 0.45)",
    };
  }
  if (status === "IN_PROGRESS") {
    return {
      bg: "rgba(56, 189, 248, 0.16)",
      color: "#38bdf8",
      border: "1px solid rgba(56, 189, 248, 0.45)",
    };
  }
  return {
    bg: "rgba(100, 116, 139, 0.16)",
    color: "#94a3b8",
    border: "1px solid rgba(100, 116, 139, 0.35)",
  };
}

export function AcceptanceProtocolPanel({ api, onNavigateToTab, onRefreshMain }: Props) {
  const [subTab, setSubTab] = useState<"live_runs" | "terminology">("live_runs");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Live Acceptance State
  const [prereqs, setPrereqs] = useState<any>(null);
  const [scenarios, setScenarios] = useState<any[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>("run_1_plate_correction");
  const [speakerLabel, setSpeakerLabel] = useState("seydi");
  const [environment, setEnvironment] = useState<"quiet_room" | "in_car_noise" | "telephony_pbx" | "virtual_mic">("quiet_room");
  const [channel, setChannel] = useState<"web_mic" | "asterisk" | "text_input">("web_mic");
  const [notes, setNotes] = useState("");

  const [runs, setRuns] = useState<any[]>([]);
  const [activeRunId, setActiveRunId] = useState<string>(() => {
    try {
      return localStorage.getItem(ACTIVE_RUN_STORAGE_KEY) || "";
    } catch {
      return "";
    }
  });
  const [selectedRun, setSelectedRun] = useState<any>(null);
  const [kvkkMasked, setKvkkMasked] = useState(false);

  // Terminology Verification State
  const [termAudit, setTermAudit] = useState<any>(null);
  const [testAsrInput, setTestAsrInput] = useState(
    "Nisan Kaşkay 1.5 te se i için C değil Denizlinin Dsi"
  );
  const [testBasePlate, setTestBasePlate] = useState("34 ABC 123");
  const [testTtsInput, setTestTtsInput] = useState(
    "2023 model Nissan Qashqai 1.5 e-Power aracınız için yarın saat 14:30'da bedel 2.500 TL."
  );
  const [termTestResult, setTermTestResult] = useState<any>(null);

  async function runAction(fn: () => Promise<void>) {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function refreshAcceptanceData(loadRunId?: string, masked?: boolean) {
    const [pre, sc, rList, audit] = await Promise.all([
      api("acceptance/prerequisites"),
      api("acceptance/scenarios"),
      api("acceptance/runs"),
      api("acceptance/terminology/audit"),
    ]);
    setPrereqs(pre);
    setScenarios(sc?.scenarios || []);
    setRuns(rList?.runs || []);
    setTermAudit(audit);

    const targetId = loadRunId ?? activeRunId ?? rList?.runs?.[0]?.run_id;
    if (targetId) {
      try {
        const useMask = masked ?? kvkkMasked;
        const rep = await api(`acceptance/runs/${targetId}?masked=${useMask}`);
        setSelectedRun(rep);
        if (rep?.status === "IN_PROGRESS") {
          setActiveRunId(rep.run_id);
        }
      } catch {
        // Silinmiş/taşınmış eski ID varsa yoksay
      }
    }
  }

  useEffect(() => {
    void runAction(() => refreshAcceptanceData());
  }, []);

  const currentScenario =
    scenarios.find((s) => s.id === selectedScenarioId) || scenarios[0] || null;

  async function handlePrepareFixtures() {
    await runAction(async () => {
      const res = await api("acceptance/prepare-fixtures", "POST", { reset_existing: false });
      setNotice(
        `PoC fikstürü hazırlandı: ${res.vehicle?.description} (${(res.vehicle?.quote_kurus || 0) / 100} TL), açık slot ${res.open_slot?.starts_at}.`
      );
      await refreshAcceptanceData();
      if (onRefreshMain) await onRefreshMain();
    });
  }

  async function handleStartRun() {
    await runAction(async () => {
      const created = await api("acceptance/runs/start", "POST", {
        scenario_id: selectedScenarioId,
        speaker_label: speakerLabel,
        environment,
        notes,
        channel,
      });
      setActiveRunId(created.run_id);
      try {
        localStorage.setItem(ACTIVE_RUN_STORAGE_KEY, created.run_id);
      } catch {}
      setSelectedRun(created);
      setNotice(
        `Kabul koşusu başlatıldı (${created.run_id}). Şimdi 'Görüşme' sekmesinde konuşmayı gerçekleştirip ardından 'Koşuyu Değerlendir' butonuna basın.`
      );
      await refreshAcceptanceData(created.run_id);
    });
  }

  async function handleVerifyRun(runId: string) {
    await runAction(async () => {
      const verified = await api(`acceptance/runs/${runId}/verify`, "POST");
      try {
        if (localStorage.getItem(ACTIVE_RUN_STORAGE_KEY) === runId) {
          localStorage.removeItem(ACTIVE_RUN_STORAGE_KEY);
        }
      } catch {}
      if (activeRunId === runId) setActiveRunId("");
      setSelectedRun(verified);
      setNotice(`Koşu doğrulaması tamamlandı: Durum = ${verified.status}`);
      await refreshAcceptanceData(runId);
      if (onRefreshMain) await onRefreshMain();
    });
  }

  async function handleToggleMask(nextMask: boolean) {
    setKvkkMasked(nextMask);
    if (selectedRun?.run_id) {
      await runAction(async () => {
        const rep = await api(`acceptance/runs/${selectedRun.run_id}?masked=${nextMask}`);
        setSelectedRun(rep);
      });
    }
  }

  async function handleRunTermTest() {
    await runAction(async () => {
      const res = await api("acceptance/terminology/test", "POST", {
        asr_text: testAsrInput,
        tts_text: testTtsInput,
        base_plate: testBasePlate || null,
      });
      setTermTestResult(res);
    });
  }

  function handleDownloadRunJson() {
    if (!selectedRun) return;
    const blob = new Blob([JSON.stringify(selectedRun, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selectedRun.run_id}${kvkkMasked ? "_kvkk_masked" : ""}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const cardStyle: React.CSSProperties = {
    background: "#0f172a",
    border: "1px solid #1e293b",
    borderRadius: "10px",
    padding: "14px 16px",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "14px", padding: "4px 6px", overflowY: "auto" }}>
      {/* ÜST BAŞLIK & ALT SEKME SEÇİCİ */}
      <div
        style={{
          ...cardStyle,
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "12px",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
            <h2 style={{ margin: 0, fontSize: "16px", fontWeight: 800, color: "#f8fafc" }}>
              Canlı Mikrofon Kabul Koşuları & Otomotiv Terim Doğrulama Protokolü
            </h2>
            <span className="stage-badge brand">Adım 6 · F0–F6 Doğrulama</span>
          </div>
          <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#94a3b8" }}>
            Gerçek mikrofon görüşmeleri için öncesi/sonrası DB diff, EOS→İlk Ses gecikme kanıtı ve çift yönlü otomotiv terim denetimi.
          </p>
        </div>

        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={() => setSubTab("live_runs")}
            style={{
              padding: "7px 14px",
              borderRadius: "8px",
              fontSize: "12px",
              fontWeight: 700,
              cursor: "pointer",
              border: subTab === "live_runs" ? "1px solid #38bdf8" : "1px solid #334155",
              background: subTab === "live_runs" ? "rgba(56, 189, 248, 0.18)" : "#1e293b",
              color: subTab === "live_runs" ? "#38bdf8" : "#94a3b8",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <Mic size={14} /> Canlı Mikrofon Koşuları ({runs.length})
          </button>
          <button
            type="button"
            onClick={() => setSubTab("terminology")}
            style={{
              padding: "7px 14px",
              borderRadius: "8px",
              fontSize: "12px",
              fontWeight: 700,
              cursor: "pointer",
              border: subTab === "terminology" ? "1px solid #10b981" : "1px solid #334155",
              background: subTab === "terminology" ? "rgba(16, 185, 129, 0.18)" : "#1e293b",
              color: subTab === "terminology" ? "#34d399" : "#94a3b8",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <FileCheck2 size={14} /> Otomotiv Terim Doğrulama ({termAudit ? `${termAudit.passed}/${termAudit.total}` : "—"})
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void runAction(() => refreshAcceptanceData())}
            style={{
              padding: "7px 12px",
              borderRadius: "8px",
              fontSize: "12px",
              background: "#1e293b",
              border: "1px solid #334155",
              color: "#e2e8f0",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "5px",
            }}
          >
            <RefreshCw size={13} /> Yenile
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="error" style={{ margin: 0 }}>
          {error}
        </div>
      )}
      {notice && (
        <div
          role="status"
          style={{
            padding: "9px 14px",
            borderRadius: "8px",
            background: "rgba(16, 185, 129, 0.14)",
            border: "1px solid rgba(16, 185, 129, 0.4)",
            color: "#6ee7b7",
            fontSize: "12px",
          }}
        >
          {notice}
        </div>
      )}

      {/* BÖLÜM A: CANLI MİKROFON KABUL KOŞULARI */}
      {subTab === "live_runs" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
          {/* ÖN KOŞULLAR VE HAZIRLIK ŞERİDİ */}
          {prereqs && (
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "10px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <Activity size={16} color="#38bdf8" />
                  <strong style={{ fontSize: "13px", color: "#f1f5f9" }}>Ön Koşul Denetimi (Canlı Gerçek Durum)</strong>
                  {prereqs.demo_mode && (
                    <span style={{ ...statusStyle("WARN"), padding: "2px 8px", borderRadius: "4px", fontSize: "10px", fontWeight: 700 }}>
                      İZOLASYON / DEMO DB
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={handlePrepareFixtures}
                    style={{
                      padding: "6px 12px",
                      borderRadius: "6px",
                      fontSize: "12px",
                      fontWeight: 600,
                      background: "rgba(56, 189, 248, 0.18)",
                      border: "1px solid rgba(56, 189, 248, 0.45)",
                      color: "#38bdf8",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "5px",
                    }}
                  >
                    <Wrench size={13} /> PoC Fikstürünü Hazırla (Corolla + 09:00 Dolu / 10:00 Açık)
                  </button>
                  {onNavigateToTab && (
                    <button
                      type="button"
                      onClick={() => onNavigateToTab("Görüşme")}
                      style={{
                        padding: "6px 12px",
                        borderRadius: "6px",
                        fontSize: "12px",
                        fontWeight: 700,
                        background: "#059669",
                        border: "none",
                        color: "#ffffff",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: "5px",
                      }}
                    >
                      <Mic size={13} /> Görüşme Sekmesine Git
                    </button>
                  )}
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "8px" }}>
                {(["stt", "vad", "tts", "ollama"] as const).map((k) => {
                  const ok = prereqs.models_ready?.[k];
                  const st = statusStyle(ok ? "READY" : "BLOCKED");
                  return (
                    <div key={k} style={{ padding: "8px 10px", borderRadius: "6px", background: "#090d16", border: "1px solid #1e293b", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "12px" }}>
                      <span style={{ color: "#cbd5e1", fontWeight: 600 }}>{k.toUpperCase()}</span>
                      <span style={{ ...st, padding: "1px 6px", borderRadius: "4px", fontSize: "10px", fontWeight: 700 }}>
                        {ok ? "READY" : "YÜKLÜ DEĞİL"}
                      </span>
                    </div>
                  );
                })}
                <div style={{ padding: "8px 10px", borderRadius: "6px", background: "#090d16", border: "1px solid #1e293b", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "12px" }}>
                  <span style={{ color: "#cbd5e1", fontWeight: 600 }}>PoC Corolla + Fiyat</span>
                  <span style={{ ...statusStyle(prereqs.database?.has_poc_corolla && prereqs.database?.has_poc_quote ? "READY" : "WARN"), padding: "1px 6px", borderRadius: "4px", fontSize: "10px", fontWeight: 700 }}>
                    {prereqs.database?.has_poc_corolla ? (prereqs.database?.has_poc_quote ? "HAZIR" : "FİYAT EKSİK") : "EKSİK"}
                  </span>
                </div>
                <div style={{ padding: "8px 10px", borderRadius: "6px", background: "#090d16", border: "1px solid #1e293b", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "12px" }}>
                  <span style={{ color: "#cbd5e1", fontWeight: 600 }}>Açık Gelecek Slot</span>
                  <span style={{ ...statusStyle(prereqs.database?.open_future_slots_count > 0 ? "READY" : "WARN"), padding: "1px 6px", borderRadius: "4px", fontSize: "10px", fontWeight: 700 }}>
                    {prereqs.database?.open_future_slots_count ?? 0} açık / {prereqs.database?.occupied_future_slots_count ?? 0} dolu
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* AKTİF KOŞU BANNERI */}
          {activeRunId && (
            <div
              style={{
                padding: "12px 16px",
                borderRadius: "10px",
                background: "rgba(56, 189, 248, 0.12)",
                border: "1px solid rgba(56, 189, 248, 0.45)",
                display: "flex",
                flexWrap: "wrap",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "10px",
              }}
            >
              <div>
                <div style={{ fontSize: "13px", fontWeight: 700, color: "#7dd3fc" }}>
                  ● Aktif Kabul Koşusu Kaydı Açık: <code style={{ fontFamily: "monospace" }}>{activeRunId}</code>
                </div>
                <div style={{ fontSize: "12px", color: "#cbd5e1", marginTop: "2px" }}>
                  Web mikrofonuyla görüşmeyi tamamladıktan sonra doğrulama ve katman teşhisi için değerlendirin.
                </div>
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                {onNavigateToTab && (
                  <button
                    type="button"
                    onClick={() => onNavigateToTab("Görüşme")}
                    style={{
                      padding: "7px 12px",
                      borderRadius: "6px",
                      fontSize: "12px",
                      fontWeight: 600,
                      background: "#1e293b",
                      border: "1px solid #38bdf8",
                      color: "#38bdf8",
                      cursor: "pointer",
                    }}
                  >
                    🎙️ Görüşmeye Dön
                  </button>
                )}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleVerifyRun(activeRunId)}
                  style={{
                    padding: "7px 14px",
                    borderRadius: "6px",
                    fontSize: "12px",
                    fontWeight: 700,
                    background: "#059669",
                    border: "none",
                    color: "#ffffff",
                    cursor: "pointer",
                  }}
                >
                  ✅ Koşuyu Değerlendir (After DB Diff)
                </button>
              </div>
            </div>
          )}

          {/* 2 KOLONLU YERLEŞİM: SENARYO BAŞLAT + GEÇMİŞ KOŞULAR */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: "14px" }}>
            {/* Sol: Yeni Koşu Başlatma Konsolu */}
            <div style={cardStyle}>
              <h3 style={{ margin: "0 0 10px", fontSize: "14px", fontWeight: 700, color: "#f8fafc" }}>
                Yeni Canlı Kabul Koşusu Başlat
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                <div>
                  <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
                    Kabul Senaryosu
                  </label>
                  <select
                    value={selectedScenarioId}
                    onChange={(e) => setSelectedScenarioId(e.target.value)}
                    style={{ width: "100%", padding: "8px 10px", background: "#090d16", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "12px" }}
                  >
                    {scenarios.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.title}
                      </option>
                    ))}
                  </select>
                </div>

                {currentScenario && (
                  <div style={{ background: "#090d16", border: "1px solid #1e293b", borderRadius: "8px", padding: "10px 12px", fontSize: "12px" }}>
                    <div style={{ fontWeight: 700, color: "#38bdf8", marginBottom: "4px" }}>Konuşma Adımları:</div>
                    <ul style={{ margin: "0 0 8px", paddingLeft: "18px", color: "#cbd5e1", lineHeight: 1.5 }}>
                      {currentScenario.script_steps.map((st: string, i: number) => (
                        <li key={i}>{st}</li>
                      ))}
                    </ul>
                    <div style={{ fontWeight: 700, color: "#34d399", marginBottom: "4px" }}>Geçme Koşulları:</div>
                    <ul style={{ margin: 0, paddingLeft: "18px", color: "#94a3b8", lineHeight: 1.45 }}>
                      {currentScenario.pass_criteria.map((cr: string, i: number) => (
                        <li key={i}>{cr}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "8px" }}>
                  <div>
                    <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>Konuşmacı</label>
                    <input
                      type="text"
                      value={speakerLabel}
                      onChange={(e) => setSpeakerLabel(e.target.value)}
                      placeholder="Örn: seydi"
                      style={{ width: "100%", padding: "7px 8px", background: "#090d16", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "12px" }}
                    />
                  </div>
                  <div>
                    <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>Ortam</label>
                    <select
                      value={environment}
                      onChange={(e) => setEnvironment(e.target.value as any)}
                      style={{ width: "100%", padding: "7px 8px", background: "#090d16", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "12px" }}
                    >
                      <option value="quiet_room">Sessiz Oda</option>
                      <option value="in_car_noise">Araç İçi Gürültü</option>
                      <option value="telephony_pbx">Santral / 8kHz PBX</option>
                      <option value="virtual_mic">Sanal Mikrofon</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>Kanal</label>
                    <select
                      value={channel}
                      onChange={(e) => setChannel(e.target.value as any)}
                      style={{ width: "100%", padding: "7px 8px", background: "#090d16", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "12px" }}
                    >
                      <option value="web_mic">Web Mikrofon</option>
                      <option value="text_input">Metin Simülasyonu</option>
                      <option value="asterisk">Asterisk PBX</option>
                    </select>
                  </div>
                </div>

                <input
                  type="text"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Koşu notu (opsiyonel, örn. kulaklık mikrofonu, arka plan gürültüsü...)"
                  style={{ width: "100%", padding: "7px 10px", background: "#090d16", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "12px" }}
                />

                <button
                  type="button"
                  disabled={busy}
                  onClick={handleStartRun}
                  style={{
                    padding: "9px 14px",
                    borderRadius: "8px",
                    fontSize: "13px",
                    fontWeight: 700,
                    background: "#0284c7",
                    border: "none",
                    color: "#ffffff",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "6px",
                  }}
                >
                  <Play size={14} /> Koşuyu Başlat (Before DB Snapshot Al)
                </button>
              </div>
            </div>

            {/* Sağ: Kayıtlı Koşular Geçmişi */}
            <div style={cardStyle}>
              <h3 style={{ margin: "0 0 10px", fontSize: "14px", fontWeight: 700, color: "#f8fafc" }}>
                Kayıtlı Kabul Koşuları ({runs.length})
              </h3>
              {runs.length === 0 ? (
                <div style={{ padding: "24px 12px", textAlign: "center", color: "#64748b", fontSize: "12px" }}>
                  Henüz başlatılmış kabul koşusu kaydı yok. Soldaki konsoldan İlk Koşuyu başlatın.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "340px", overflowY: "auto" }}>
                  {runs.map((r) => {
                    const isSelected = selectedRun?.run_id === r.run_id;
                    const st = statusStyle(r.status);
                    return (
                      <div
                        key={r.run_id}
                        onClick={() =>
                          void runAction(async () => {
                            const rep = await api(`acceptance/runs/${r.run_id}?masked=${kvkkMasked}`);
                            setSelectedRun(rep);
                          })
                        }
                        style={{
                          padding: "10px 12px",
                          borderRadius: "8px",
                          background: isSelected ? "rgba(56, 189, 248, 0.1)" : "#090d16",
                          border: isSelected ? "1px solid #38bdf8" : "1px solid #1e293b",
                          cursor: "pointer",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          gap: "10px",
                        }}
                      >
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: "12px", fontWeight: 700, color: "#f1f5f9", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                            {r.scenario_title}
                          </div>
                          <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "2px" }}>
                            {r.speaker_label} · {r.environment} · Yeni Randevu: {r.net_new_appointments ?? "—"}
                            {r.warm_eos_p95_ms ? ` · p95: ${r.warm_eos_p95_ms} ms` : ""}
                          </div>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexShrink: 0 }}>
                          {r.status === "IN_PROGRESS" && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleVerifyRun(r.run_id);
                              }}
                              style={{ padding: "3px 8px", fontSize: "10px", fontWeight: 700, background: "#059669", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}
                            >
                              Doğrula
                            </button>
                          )}
                          <span style={{ ...st, padding: "2px 8px", borderRadius: "5px", fontSize: "11px", fontWeight: 700 }}>
                            {r.status}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* SEÇİLİ KOŞU DETAY RAPORU & KATMAN TEŞHİSİ */}
          {selectedRun && (
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", paddingBottom: "10px", borderBottom: "1px solid #1e293b" }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                    <h3 style={{ margin: 0, fontSize: "15px", fontWeight: 800, color: "#f8fafc" }}>
                      Kanıt Raporu: {selectedRun.scenario_title}
                    </h3>
                    <span style={{ ...statusStyle(selectedRun.status), padding: "2px 10px", borderRadius: "6px", fontSize: "11px", fontWeight: 800 }}>
                      {selectedRun.status}
                    </span>
                    {selectedRun.kvkk_masked && (
                      <span style={{ ...statusStyle("READY"), padding: "2px 8px", borderRadius: "6px", fontSize: "10px", fontWeight: 700 }}>
                        KVKK MASKELİ
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "3px", fontFamily: "monospace" }}>
                    ID: {selectedRun.run_id} · Konuşmacı: {selectedRun.speaker_label} · Ortam: {selectedRun.environment} · Kanal: {selectedRun.channel}
                  </div>
                </div>

                <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: "11.5px", color: "#cbd5e1", cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={kvkkMasked}
                      onChange={(e) => void handleToggleMask(e.target.checked)}
                    />
                    <Shield size={12} /> KVKK Maskele
                  </label>
                  <button
                    type="button"
                    onClick={handleDownloadRunJson}
                    style={{
                      padding: "6px 10px",
                      borderRadius: "6px",
                      fontSize: "11.5px",
                      fontWeight: 600,
                      background: "#1e293b",
                      border: "1px solid #334155",
                      color: "#e2e8f0",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      gap: "5px",
                    }}
                  >
                    <Download size={12} /> JSON Kanıt İndir
                  </button>
                </div>
              </div>

              {/* 6 Katmanlı Hata & Sağlık Ayrıştırması */}
              {selectedRun.layer_diagnostics && Object.keys(selectedRun.layer_diagnostics).length > 0 && (
                <div style={{ marginTop: "12px" }}>
                  <div style={{ fontSize: "12px", fontWeight: 700, color: "#cbd5e1", marginBottom: "8px" }}>
                    Katman Bazlı Hata Ayrıştırması (F0 → F6 → DB)
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px" }}>
                    {Object.entries(selectedRun.layer_diagnostics).map(([layerKey, info]: [string, any]) => {
                      const st = statusStyle(info.status);
                      return (
                        <div key={layerKey} style={{ padding: "8px 10px", borderRadius: "6px", background: "#090d16", border: "1px solid #1e293b" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                            <span style={{ fontFamily: "monospace", fontSize: "11px", fontWeight: 700, color: "#f1f5f9" }}>
                              {layerKey}
                            </span>
                            <span style={{ ...st, padding: "1px 6px", borderRadius: "4px", fontSize: "10px", fontWeight: 700 }}>
                              {info.status}
                            </span>
                          </div>
                          <div style={{ fontSize: "11px", color: "#94a3b8" }}>{info.detail}</div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Gecikme Özeti (EOS -> İlk Ses & STT) + Geçme Kriterleri */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "12px", marginTop: "12px" }}>
                <div style={{ padding: "10px 12px", borderRadius: "8px", background: "#090d16", border: "1px solid #1e293b" }}>
                  <div style={{ fontSize: "12px", fontWeight: 700, color: "#cbd5e1", marginBottom: "6px" }}>
                    Geçme Kriterleri Denetimi
                  </div>
                  {Object.keys(selectedRun.checks || {}).length === 0 ? (
                    <span style={{ fontSize: "11.5px", color: "#64748b" }}>Doğrulama henüz çalıştırılmadı.</span>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
                      {Object.entries(selectedRun.checks).map(([k, ok]) => (
                        <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "12px" }}>
                          <span style={{ fontFamily: "monospace", color: "#cbd5e1" }}>{k}</span>
                          {ok ? (
                            <span style={{ color: "#34d399", display: "flex", alignItems: "center", gap: "4px", fontWeight: 700 }}>
                              <CheckCircle2 size={13} /> PASS
                            </span>
                          ) : (
                            <span style={{ color: "#f87171", display: "flex", alignItems: "center", gap: "4px", fontWeight: 700 }}>
                              <XCircle size={13} /> FAIL
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div style={{ padding: "10px 12px", borderRadius: "8px", background: "#090d16", border: "1px solid #1e293b" }}>
                  <div style={{ fontSize: "12px", fontWeight: 700, color: "#cbd5e1", marginBottom: "6px" }}>
                    EOS → İlk Duyulur Yanıt & Gecikme Dağılımı
                  </div>
                  <div style={{ fontSize: "12px", color: "#94a3b8", display: "flex", flexDirection: "column", gap: "4px" }}>
                    <div>
                      Sıcak EOS → İlk Ses:{" "}
                      <b style={{ color: "#34d399", fontFamily: "monospace" }}>
                        {selectedRun.latency_summary?.warm_eos_to_first_audio
                          ? `p50=${selectedRun.latency_summary.warm_eos_to_first_audio.p50_ms}ms / p95=${selectedRun.latency_summary.warm_eos_to_first_audio.p95_ms}ms (n=${selectedRun.latency_summary.warm_eos_to_first_audio.count})`
                          : "— (Ölçüm yok)"}
                      </b>
                    </div>
                    <div>
                      Soğuk İlk Tur:{" "}
                      <b style={{ color: "#fbbf24", fontFamily: "monospace" }}>
                        {selectedRun.latency_summary?.cold_eos_to_first_audio
                          ? `${selectedRun.latency_summary.cold_eos_to_first_audio.avg_ms}ms (n=${selectedRun.latency_summary.cold_eos_to_first_audio.count})`
                          : "—"}
                      </b>
                    </div>
                    <div>
                      STT (F₂):{" "}
                      <b style={{ color: "#38bdf8", fontFamily: "monospace" }}>
                        {selectedRun.latency_summary?.stt
                          ? `avg=${selectedRun.latency_summary.stt.avg_ms}ms / p95=${selectedRun.latency_summary.stt.p95_ms}ms`
                          : "—"}
                      </b>
                    </div>
                    <div>
                      Takvim DB Farkı:{" "}
                      <b style={{ color: "#f8fafc", fontFamily: "monospace" }}>
                        {selectedRun.diff?.net_new_appointments ?? 0} yeni randevu
                      </b>
                    </div>
                  </div>
                </div>
              </div>

              {/* Tur Bazlı Kanıt Tablosu */}
              {selectedRun.turns_timeline && selectedRun.turns_timeline.length > 0 && (
                <div style={{ marginTop: "12px", overflowX: "auto" }}>
                  <div style={{ fontSize: "12px", fontWeight: 700, color: "#cbd5e1", marginBottom: "6px" }}>
                    Tur Bazlı Gerçek Ses & Niyet İzi ({selectedRun.turns_timeline.length} kayıt)
                  </div>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11.5px" }}>
                    <thead>
                      <tr style={{ textAlign: "left", borderBottom: "1px solid #1e293b", color: "#94a3b8" }}>
                        <th style={{ padding: "6px 8px" }}>Rol</th>
                        <th style={{ padding: "6px 8px" }}>Ham Metin / ASR</th>
                        <th style={{ padding: "6px 8px" }}>Kanonik Terim Çözümü</th>
                        <th style={{ padding: "6px 8px" }}>Plaka</th>
                        <th style={{ padding: "6px 8px" }}>Niyet / Durum</th>
                        <th style={{ padding: "6px 8px" }}>STT / EOS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedRun.turns_timeline.map((t: any, idx: number) => (
                        <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)", color: "#e2e8f0" }}>
                          <td style={{ padding: "6px 8px", fontWeight: 700, color: t.role === "user" ? "#38bdf8" : "#34d399" }}>
                            {t.role === "user" ? "Müşteri" : "Freya"}
                          </td>
                          <td style={{ padding: "6px 8px" }}>{t.raw_text}</td>
                          <td style={{ padding: "6px 8px", color: "#cbd5e1" }}>
                            {t.canonical_text !== t.raw_text ? t.canonical_text : "—"}
                          </td>
                          <td style={{ padding: "6px 8px", fontFamily: "monospace", color: "#fbbf24" }}>
                            {t.plate_state || t.extracted_plate || "—"}
                          </td>
                          <td style={{ padding: "6px 8px", fontFamily: "monospace", fontSize: "11px" }}>
                            {t.intent ? `${t.intent} → ${t.state_after || ""}` : "—"}
                          </td>
                          <td style={{ padding: "6px 8px", fontFamily: "monospace", fontSize: "11px" }}>
                            {t.stt_ms != null ? `${Math.round(t.stt_ms)}ms` : "—"}
                            {t.eos_to_first_audio_ms != null ? ` / EOS:${Math.round(t.eos_to_first_audio_ms)}ms` : ""}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* DB'de Oluşan Randevular */}
              {selectedRun.diff?.new_appointments && selectedRun.diff.new_appointments.length > 0 && (
                <div style={{ marginTop: "12px", padding: "10px 12px", borderRadius: "8px", background: "rgba(16, 185, 129, 0.08)", border: "1px solid rgba(16, 185, 129, 0.35)" }}>
                  <div style={{ fontSize: "12px", fontWeight: 700, color: "#34d399", marginBottom: "6px" }}>
                    Takvime İşlenen Yeni Randevular ({selectedRun.diff.new_appointments.length})
                  </div>
                  {selectedRun.diff.new_appointments.map((a: any) => (
                    <div key={a.id} style={{ fontSize: "12px", color: "#e2e8f0", fontFamily: "monospace" }}>
                      [{a.reference_code}] Araç: {a.vehicle_description || "—"} · Plaka: <b>{a.plate || "—"}</b> · Saat: {a.slot_starts_at} · Durum: {a.status}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* BÖLÜM B: OTOMOTİV TERİM DOĞRULAMA PROTOKOLÜ */}
      {subTab === "terminology" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
          {/* Akustik Katman Ayrıştırma Özeti */}
          {termAudit?.acoustic_attribution && (
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "10px" }}>
                <div>
                  <h3 style={{ margin: 0, fontSize: "14px", fontWeight: 700, color: "#f8fafc" }}>
                    Akustik Terim Doğruluğu & Hata Katman Ayrıştırması ({termAudit.acoustic_attribution.channel || "telephony_8k"})
                  </h3>
                  <p style={{ margin: "2px 0 0", fontSize: "11.5px", color: "#94a3b8" }}>
                    Ham ASR çıktısı ile kanonik fonetik kurtarma ayrı ölçülür; kalite kapısı sıkı ölçümü asla gizlemez.
                  </p>
                </div>
                {termAudit.acoustic_attribution.available && (
                  <span style={{ ...statusStyle((termAudit.acoustic_attribution.strict_term_accuracy_pct ?? 0) >= 95 ? "PASS" : "FAIL"), padding: "3px 10px", borderRadius: "6px", fontSize: "11px", fontWeight: 700 }}>
                    Kapı Eşiği %95 · Ham Ölçüm: %{termAudit.acoustic_attribution.strict_term_accuracy_pct}
                  </span>
                )}
              </div>

              {!termAudit.acoustic_attribution.available ? (
                <div style={{ padding: "12px", borderRadius: "6px", background: "#090d16", color: "#94a3b8", fontSize: "12px" }}>
                  <AlertTriangle size={14} style={{ verticalAlign: "middle", marginRight: "6px", color: "#fbbf24" }} />
                  Aktif veri klasöründe akustik rapor (`acoustic/latest.json`) yok. Tam 320 cümlelik ses ölçümü için{" "}
                  <code>.venv\Scripts\python -m scripts.acoustic_benchmark</code> çalıştırın.
                </div>
              ) : (
                <>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "8px", marginBottom: "12px" }}>
                    <div style={{ padding: "10px", borderRadius: "8px", background: "#090d16", border: "1px solid #1e293b" }}>
                      <div style={{ fontSize: "11px", color: "#94a3b8" }}>Sıkı (Ham ASR) Terim Doğruluğu</div>
                      <div style={{ fontSize: "18px", fontWeight: 800, color: "#f87171", fontFamily: "monospace" }}>
                        %{termAudit.acoustic_attribution.strict_term_accuracy_pct}
                      </div>
                      <div style={{ fontSize: "10.5px", color: "#64748b" }}>
                        {termAudit.acoustic_attribution.strict_correct}/{termAudit.acoustic_attribution.terms_total} terim
                      </div>
                    </div>
                    <div style={{ padding: "10px", borderRadius: "8px", background: "#090d16", border: "1px solid #1e293b" }}>
                      <div style={{ fontSize: "11px", color: "#94a3b8" }}>Kanonik Kurtarma Sonrası (F₂b)</div>
                      <div style={{ fontSize: "18px", fontWeight: 800, color: "#38bdf8", fontFamily: "monospace" }}>
                        %{termAudit.acoustic_attribution.post_canonical_accuracy_pct}
                      </div>
                      <div style={{ fontSize: "10.5px", color: "#34d399" }}>
                        +{termAudit.acoustic_attribution.asr_phonetic_recoverable_count} fonetik ASR yazımı kurtarıldı
                      </div>
                    </div>
                    <div style={{ padding: "10px", borderRadius: "8px", background: "#090d16", border: "1px solid #1e293b" }}>
                      <div style={{ fontSize: "11px", color: "#94a3b8" }}>Gerçek Telaffuz / 8k Akustik Kayıp</div>
                      <div style={{ fontSize: "18px", fontWeight: 800, color: "#fbbf24", fontFamily: "monospace" }}>
                        {termAudit.acoustic_attribution.true_pronunciation_or_acoustic_miss_count} terim
                      </div>
                      <div style={{ fontSize: "10.5px", color: "#64748b" }}>F4/F5 telaffuz & 8k bant iyileştirmesi gerektirir</div>
                    </div>
                  </div>

                  {/* Kaçan Terimler Dağılımı */}
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                    {Object.entries(termAudit.acoustic_attribution.per_term_breakdown || {}).map(([term, info]: [string, any]) => (
                      <span
                        key={term}
                        style={{
                          padding: "4px 8px",
                          borderRadius: "6px",
                          background: "#090d16",
                          border: "1px solid #334155",
                          fontSize: "11px",
                          fontFamily: "monospace",
                          color: "#cbd5e1",
                        }}
                        title={`Ham Kaçan: ${info.missed_raw} | Kanonik Kurtarma: ${info.recovered_by_canonical} | Gerçek Kayıp: ${info.true_acoustic_or_tts_miss}`}
                      >
                        <b style={{ color: "#fbbf24" }}>{term}</b>: {info.missed_raw} kaçtı
                        {info.recovered_by_canonical > 0 && (
                          <span style={{ color: "#34d399" }}> (+{info.recovered_by_canonical} kurtarıldı)</span>
                        )}
                      </span>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {/* CANLI ÇİFT YÖNLÜ TERİM & PLAKA TEST LABORATUVARI */}
          <div style={cardStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px", flexWrap: "wrap", gap: "8px" }}>
              <h3 style={{ margin: 0, fontSize: "14px", fontWeight: 700, color: "#f8fafc" }}>
                Canlı Çift Yönlü Terim, Plaka & Katalog Eşleşme Testi
              </h3>
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleRunTermTest()}
                style={{
                  padding: "6px 14px",
                  borderRadius: "6px",
                  fontSize: "12px",
                  fontWeight: 700,
                  background: "#0284c7",
                  border: "none",
                  color: "#ffffff",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "5px",
                }}
              >
                <Volume2 size={13} /> Çift Yönlü Sına
              </button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "10px" }}>
              <div>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
                  1. Gelen Müşteri / Whisper ASR Metni
                </label>
                <input
                  type="text"
                  value={testAsrInput}
                  onChange={(e) => setTestAsrInput(e.target.value)}
                  style={{ width: "100%", padding: "8px 10px", background: "#090d16", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "12px" }}
                />
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", margin: "6px 0 4px" }}>
                  Varsa Mevcut Taslak Plaka (Düzeltme Testi İçin)
                </label>
                <input
                  type="text"
                  value={testBasePlate}
                  onChange={(e) => setTestBasePlate(e.target.value)}
                  placeholder="34 ABC 123"
                  style={{ width: "100%", padding: "7px 10px", background: "#090d16", border: "1px solid #334155", borderRadius: "6px", color: "#fbbf24", fontFamily: "monospace", fontSize: "12px" }}
                />
              </div>

              <div>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
                  2. Giden Asistan / FreyaTTS F4 Çıkış Metni
                </label>
                <textarea
                  rows={3}
                  value={testTtsInput}
                  onChange={(e) => setTestTtsInput(e.target.value)}
                  style={{ width: "100%", padding: "8px 10px", background: "#090d16", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "12px" }}
                />
              </div>
            </div>

            {termTestResult && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "10px", marginTop: "10px" }}>
                {termTestResult.inbound_asr && (
                  <div style={{ padding: "10px", borderRadius: "8px", background: "#090d16", border: "1px solid #1e293b", fontSize: "12px" }}>
                    <div style={{ fontWeight: 700, color: "#38bdf8", marginBottom: "4px" }}>Gelen ASR Çözümü:</div>
                    <div style={{ color: "#e2e8f0" }}>
                      Kanonik: <b>{termTestResult.inbound_asr.canonical_text}</b>
                    </div>
                    <div style={{ color: "#fbbf24", marginTop: "3px", fontFamily: "monospace" }}>
                      Plaka: {termTestResult.inbound_asr.plate_correction?.plate || termTestResult.inbound_asr.plate_parsed || "—"}
                      {termTestResult.inbound_asr.plate_correction && ` (Düzeltme: ${termTestResult.inbound_asr.plate_correction.correction_target})`}
                    </div>
                    <div style={{ color: "#34d399", marginTop: "3px" }}>
                      Katalog Eşleşmesi: {termTestResult.inbound_asr.catalog_match?.description || (termTestResult.inbound_asr.brand_only_detected ? `Marka sorulacak (${termTestResult.inbound_asr.brand_only_detected})` : "Eşleşmedi")}
                    </div>
                  </div>
                )}
                {termTestResult.outbound_tts && (
                  <div style={{ padding: "10px", borderRadius: "8px", background: "#090d16", border: "1px solid #1e293b", fontSize: "12px" }}>
                    <div style={{ fontWeight: 700, color: "#34d399", marginBottom: "4px" }}>Giden F4 Normalizasyonu & Vocab:</div>
                    {termTestResult.outbound_tts.ok ? (
                      <div style={{ color: "#a7f3d0" }}>{termTestResult.outbound_tts.normalized}</div>
                    ) : (
                      <div style={{ color: "#f87171" }}>HATA: {termTestResult.outbound_tts.error}</div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* DETERMINİSTİK TERİM DENETİM MATRİSİ */}
          {termAudit && (
            <div style={cardStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px", marginBottom: "10px" }}>
                <h3 style={{ margin: 0, fontSize: "14px", fontWeight: 700, color: "#f8fafc" }}>
                  Otomatik Otomotiv Terim Doğrulama Matrisi ({termAudit.passed}/{termAudit.total} · %{termAudit.pass_rate_pct})
                </h3>
                <span style={{ fontSize: "11px", color: "#94a3b8" }}>
                  Aktif Sözlük Girdisi: <b>{termAudit.active_lexicon_count}</b> terim
                </span>
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginBottom: "10px" }}>
                {Object.entries(termAudit.categories || {}).map(([cat, stat]: [string, any]) => {
                  const st = statusStyle(stat.rate_pct >= 100 ? "PASS" : "WARN");
                  return (
                    <span key={cat} style={{ ...st, padding: "4px 10px", borderRadius: "6px", fontSize: "11px", fontWeight: 700 }}>
                      {cat}: {stat.passed}/{stat.total} (%{stat.rate_pct})
                    </span>
                  );
                })}
              </div>

              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11.5px" }}>
                  <thead>
                    <tr style={{ textAlign: "left", borderBottom: "1px solid #1e293b", color: "#94a3b8" }}>
                      <th style={{ padding: "6px 8px" }}>ID</th>
                      <th style={{ padding: "6px 8px" }}>Yön / Kategori</th>
                      <th style={{ padding: "6px 8px" }}>Girdi</th>
                      <th style={{ padding: "6px 8px" }}>Üretilen Çıktı</th>
                      <th style={{ padding: "6px 8px" }}>Durum</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(termAudit.cases || []).map((c: any) => (
                      <tr key={c.id} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)", color: "#e2e8f0" }}>
                        <td style={{ padding: "6px 8px", fontFamily: "monospace", color: "#38bdf8" }}>{c.id}</td>
                        <td style={{ padding: "6px 8px" }}>{c.category} · {c.direction}</td>
                        <td style={{ padding: "6px 8px" }}>{c.input}</td>
                        <td style={{ padding: "6px 8px", color: "#cbd5e1" }}>{c.actual}</td>
                        <td style={{ padding: "6px 8px" }}>
                          <span style={{ ...statusStyle(c.passed ? "PASS" : "FAIL"), padding: "1px 6px", borderRadius: "4px", fontSize: "10px", fontWeight: 700 }}>
                            {c.passed ? "PASS" : c.error || "FAIL"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
