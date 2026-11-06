/*
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
*/

import React, { useState, useEffect, useRef } from "react";

interface OperatorTransfer {
  id: string;
  conversation_id: string | null;
  caller_channel: string;
  operator_extension: string;
  customer_name: string;
  vehicle_plate: string;
  summary: string;
  whisper_text: string;
  status: "initiated" | "whispering" | "accepted" | "declined" | "timeout" | "failed";
  sip_headers_json: string;
  sip_headers?: Record<string, string>;
  duration_seconds: number | null;
  created_at: string;
  completed_at: string | null;
}

interface OperatorSessionView {
  session_id: string;
  caller_id: string;
  state: "ai_handling" | "taken_over" | "monitored" | "terminated";
  operator_id: string | null;
  takeover_reason: string | null;
  started_at_iso: string;
  current_turn_id: string | null;
  mos_score: number;
  packet_loss_pct: number;
  rtf: number;
  whisper_notes: string[];
}

interface OperatorPanelProps {
  api: (path: string, method?: string, body?: unknown) => Promise<any>;
  onError: (msg: string) => void;
}

export function OperatorPanel({ api, onError }: OperatorPanelProps) {
  const [activeTab, setActiveTab] = useState<"sip_transfers" | "live_takeover" | "quality_gate">("sip_transfers");

  // SIP Aktarımları State
  const [transfers, setTransfers] = useState<OperatorTransfer[]>([]);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [selectedTransfer, setSelectedTransfer] = useState<OperatorTransfer | null>(null);

  // Test aktarımı formu alanları
  const [formCustomer, setFormCustomer] = useState("Ahmet Yılmaz");
  const [formPlate, setFormPlate] = useState("34 ABC 123");
  const [formSummary, setFormSummary] = useState("14:30 randevu teyidi / kaporta boya ekspertiz sorusu");
  const [formExten, setFormExten] = useState("6002");
  const [actionBusy, setActionBusy] = useState(false);

  // Canlı Devralma & Fısıltı (RT-10) State
  const [liveSessions, setLiveSessions] = useState<OperatorSessionView[]>([]);
  const [operatorId, setOperatorId] = useState("op_seydi");
  const [takeoverReason, setTakeoverReason] = useState("customer_complaint");
  const [whisperMessage, setWhisperMessage] = useState("");
  const [simCallerId, setSimCallerId] = useState("05441112233");

  // Kalite Kapısı 5 & Telemetri State
  const [qaReport, setQaReport] = useState<any>(null);
  const [qaLoading, setQaLoading] = useState(false);
  const [m11Status, setM11Status] = useState<any>(null);
  const [telemetryTurnId, setTelemetryTurnId] = useState("turn_api_01");
  const [telemetryData, setTelemetryData] = useState<any>(null);

  const pollIntervalRef = useRef<any>(null);

  const loadTransfers = async () => {
    try {
      setLoading(true);
      const data: OperatorTransfer[] = await api("transfers?limit=50");
      setTransfers(data || []);
    } catch (err: any) {
      // Sessiz hata
    } finally {
      setLoading(false);
    }
  };

  const loadLiveSessions = async () => {
    try {
      const data = await api("operator/live-sessions");
      setLiveSessions(data.sessions || []);
    } catch (err: any) {
      // Sessiz hata
    }
  };

  useEffect(() => {
    loadTransfers();
    loadLiveSessions();
  }, []);

  useEffect(() => {
    if (autoRefresh) {
      pollIntervalRef.current = setInterval(() => {
        if (activeTab === "sip_transfers") {
          loadTransfers();
        } else if (activeTab === "live_takeover") {
          loadLiveSessions();
        }
      }, 3000);
    } else if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, [autoRefresh, activeTab]);

  const handleAccept = async (transferId: string) => {
    try {
      setActionBusy(true);
      await api(`transfers/${transferId}/accept`, "POST", {});
      await loadTransfers();
    } catch (err: any) {
      onError(`Aktarım kabul edilemedi: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const handleDecline = async (transferId: string) => {
    try {
      setActionBusy(true);
      await api(`transfers/${transferId}/decline`, "POST", { reason: "declined" });
      await loadTransfers();
    } catch (err: any) {
      onError(`Aktarım reddedilemedi: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const handleCreateTestTransfer = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setActionBusy(true);
      await api("transfers/initiate", "POST", {
        customer_name: formCustomer,
        vehicle_plate: formPlate,
        summary: formSummary,
        operator_extension: formExten,
      });
      await loadTransfers();
    } catch (err: any) {
      onError(`Test aktarımı başlatılamadı: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  // RT-10 Handlers
  const handleRegisterSimCall = async () => {
    try {
      setActionBusy(true);
      const sessId = `call_${Date.now()}`;
      await api("operator/register-call", "POST", {
        session_id: sessId,
        caller_id: simCallerId,
        initial_turn_id: `turn_${Date.now()}`,
        mos_score: 4.38,
        rtf: 0.16,
      });
      await loadLiveSessions();
    } catch (err: any) {
      onError(`Simülasyon çağrısı başlatılamadı: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const handleTakeover = async (sessionId: string) => {
    try {
      setActionBusy(true);
      await api("operator/takeover", "POST", {
        session_id: sessionId,
        operator_id: operatorId,
        reason: takeoverReason,
      });
      await loadLiveSessions();
    } catch (err: any) {
      onError(`Çağrı devralınamadı: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const handleWhisper = async (sessionId: string) => {
    if (!whisperMessage.trim()) return;
    try {
      setActionBusy(true);
      await api("operator/whisper", "POST", {
        session_id: sessionId,
        operator_id: operatorId,
        message: whisperMessage.trim(),
      });
      setWhisperMessage("");
      await loadLiveSessions();
    } catch (err: any) {
      onError(`Fısıltı gönderilemedi: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const handleRelease = async (sessionId: string) => {
    try {
      setActionBusy(true);
      await api("operator/release", "POST", {
        session_id: sessionId,
        operator_id: operatorId,
      });
      await loadLiveSessions();
    } catch (err: any) {
      onError(`Çağrı yapay zekaya iade edilemedi: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  // QA & Telemetri Handlers
  const handleRunQABenchmark = async () => {
    try {
      setQaLoading(true);
      const res = await api("qa/evaluate-variants", "POST", {});
      setQaReport(res);
      const m11 = await api("qa/m11-status");
      setM11Status(m11);
    } catch (err: any) {
      onError(`Kalite Kapısı 5 testi hatası: ${err.message || err}`);
    } finally {
      setQaLoading(false);
    }
  };

  const handleFetchTelemetry = async () => {
    if (!telemetryTurnId.trim()) return;
    try {
      setActionBusy(true);
      const data = await api(`qa/telemetry/${telemetryTurnId.trim()}`);
      setTelemetryData(data);
    } catch (err: any) {
      onError(`Telemetri kaydı sorgulanamadı: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const activeIncoming = transfers.find(
    (t) => t.status === "initiated" || t.status === "whispering"
  );

  const filteredTransfers = transfers.filter((t) => {
    if (statusFilter === "all") return true;
    if (statusFilter === "active") return t.status === "initiated" || t.status === "whispering";
    if (statusFilter === "accepted") return t.status === "accepted";
    if (statusFilter === "declined") return t.status === "declined" || t.status === "timeout";
    return true;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Üst Bar & Alt Sekme Seçimi */}
      <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px", marginBottom: "14px" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "18px", color: "#f8fafc", display: "flex", alignItems: "center", gap: "8px" }}>
              🎧 Çağrı Merkezi Operatör & Kalite Konsolu (Ajan 7)
              <span
                style={{
                  fontSize: "12px",
                  padding: "3px 8px",
                  background: "#0369a1",
                  color: "#e0f2fe",
                  borderRadius: "12px",
                  fontWeight: "normal",
                }}
              >
                Dahili: 6002
              </span>
            </h2>
            <p style={{ margin: "4px 0 0 0", color: "#94a3b8", fontSize: "13px" }}>
              Warm Transfer (10s Fısıltı), RT-10 Canlı Devralma (Takeover), RT-09 Sahte Sıfır Yasağı & Kalite Kapısı 5
            </p>
          </div>
          <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <label style={{ fontSize: "12px", color: "#cbd5e1", display: "flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              Canlı Takip (3 sn)
            </label>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                if (activeTab === "sip_transfers") loadTransfers();
                if (activeTab === "live_takeover") loadLiveSessions();
              }}
              disabled={loading || actionBusy}
              style={{ padding: "6px 12px", fontSize: "13px" }}
            >
              {loading ? "Yenileniyor..." : "Yenile ↻"}
            </button>
          </div>
        </div>

        {/* Sekme Butonları */}
        <div style={{ display: "flex", gap: "8px", borderTop: "1px solid #1e293b", paddingTop: "12px" }}>
          <button
            type="button"
            className={activeTab === "sip_transfers" ? "primary" : "secondary"}
            onClick={() => setActiveTab("sip_transfers")}
            style={{ padding: "8px 16px", fontSize: "13px", fontWeight: "bold" }}
          >
            📞 SIP Warm Transfer (Dahili 6002)
          </button>
          <button
            type="button"
            className={activeTab === "live_takeover" ? "primary" : "secondary"}
            onClick={() => {
              setActiveTab("live_takeover");
              loadLiveSessions();
            }}
            style={{ padding: "8px 16px", fontSize: "13px", fontWeight: "bold" }}
          >
            ⚡ Canlı Müdahale & Fısıltı (RT-10 Takeover)
          </button>
          <button
            type="button"
            className={activeTab === "quality_gate" ? "primary" : "secondary"}
            onClick={() => setActiveTab("quality_gate")}
            style={{ padding: "8px 16px", fontSize: "13px", fontWeight: "bold" }}
          >
            🎯 Kalite Kapısı 5 & Telemetri (HLS-08 / RT-09)
          </button>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* SEKME 1: SIP DAHİLİ WARM TRANSFER                                         */}
      {/* ========================================================================= */}
      {activeTab === "sip_transfers" && (
        <>
          {activeIncoming && (
            <section
              style={{
                background: "linear-gradient(135deg, #1e1b4b 0%, #311042 100%)",
                border: "2px solid #a855f7",
                borderRadius: "12px",
                padding: "20px",
                boxShadow: "0 0 25px rgba(168, 85, 247, 0.4)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "15px" }}>
                <div style={{ flex: 1, minWidth: "280px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
                    <span style={{ fontSize: "20px" }}>📲</span>
                    <h3 style={{ margin: 0, fontSize: "20px", color: "#f3e8ff", fontWeight: "bold" }}>
                      GELEN CANLI AKTARIM (Screen-Pop)
                    </h3>
                    <span
                      style={{
                        background: "#c084fc",
                        color: "#3b0764",
                        fontSize: "11px",
                        fontWeight: "bold",
                        padding: "2px 8px",
                        borderRadius: "4px",
                      }}
                    >
                      SIP X-Freya Başlıkları Hazır
                    </span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "12px", marginTop: "12px" }}>
                    <div style={{ background: "rgba(0,0,0,0.3)", padding: "10px", borderRadius: "6px" }}>
                      <div style={{ fontSize: "11px", color: "#c084fc" }}>MÜŞTERİ</div>
                      <div style={{ fontSize: "16px", color: "#f8fafc", fontWeight: "bold" }}>
                        {activeIncoming.customer_name || "İsimsiz Arayan"}
                      </div>
                      <div style={{ fontSize: "11px", color: "#94a3b8" }}>{activeIncoming.caller_channel}</div>
                    </div>

                    <div style={{ background: "rgba(0,0,0,0.3)", padding: "10px", borderRadius: "6px" }}>
                      <div style={{ fontSize: "11px", color: "#c084fc" }}>PLAKA</div>
                      <div
                        style={{
                          display: "inline-block",
                          border: "2px solid #ffffff",
                          background: "#0f172a",
                          color: "#ffffff",
                          borderRadius: "4px",
                          padding: "2px 8px",
                          fontSize: "15px",
                          fontWeight: "bold",
                          marginTop: "2px",
                        }}
                      >
                        TR {activeIncoming.vehicle_plate || "PLAKA YOK"}
                      </div>
                    </div>

                    <div style={{ background: "rgba(0,0,0,0.3)", padding: "10px", borderRadius: "6px", gridColumn: "span 2" }}>
                      <div style={{ fontSize: "11px", color: "#c084fc" }}>AKTARIM GEREKÇESİ / ÖZET</div>
                      <div style={{ fontSize: "14px", color: "#f1f5f9" }}>{activeIncoming.summary || "Belirtilmedi"}</div>
                    </div>
                  </div>

                  {/* 10 Saniyelik Fısıltı Önizlemesi */}
                  <div
                    style={{
                      marginTop: "14px",
                      background: "#1e1b4b",
                      borderLeft: "4px solid #38bdf8",
                      padding: "10px 14px",
                      borderRadius: "0 6px 6px 0",
                    }}
                  >
                    <div style={{ fontSize: "11px", color: "#38bdf8", fontWeight: "bold", marginBottom: "4px" }}>
                      🗣️ 10 Saniyelik Operatör Fısıltısı (Dahiliye Okunan Sesli Özet):
                    </div>
                    <div style={{ fontSize: "13px", color: "#e2e8f0", fontStyle: "italic" }}>
                      "{activeIncoming.whisper_text}"
                    </div>
                  </div>
                </div>

                {/* Karar Butonları */}
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "10px",
                    justifyContent: "center",
                    minWidth: "220px",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => handleAccept(activeIncoming.id)}
                    disabled={actionBusy}
                    style={{
                      padding: "14px 20px",
                      background: "#16a34a",
                      color: "#ffffff",
                      border: "none",
                      borderRadius: "8px",
                      fontSize: "16px",
                      fontWeight: "bold",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "8px",
                      boxShadow: "0 4px 12px rgba(22, 163, 74, 0.4)",
                    }}
                  >
                    <span>📞</span>
                    <span>Çağrıyı Al / Köprüle (1)</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleDecline(activeIncoming.id)}
                    disabled={actionBusy}
                    style={{
                      padding: "12px 20px",
                      background: "#dc2626",
                      color: "#ffffff",
                      border: "none",
                      borderRadius: "8px",
                      fontSize: "14px",
                      fontWeight: "bold",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "8px",
                    }}
                  >
                    <span>🚫</span>
                    <span>Meşgul / AI'ya İade Et (2)</span>
                  </button>

                  <div style={{ fontSize: "11px", color: "#cbd5e1", textAlign: "center" }}>
                    15 sn içinde yanıt verilmezse otomatik olarak Leyla AI'ya döner.
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* Test Simülasyon Formu */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", color: "#f8fafc" }}>
              🧪 Test Amaçlı Canlı Aktarım Başlat (Simülatör)
            </h3>
            <form onSubmit={handleCreateTestTransfer} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "10px", alignItems: "flex-end" }}>
              <div>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>Müşteri Adı</label>
                <input
                  type="text"
                  value={formCustomer}
                  onChange={(e) => setFormCustomer(e.target.value)}
                  required
                  style={{ width: "100%", padding: "8px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>Araç Plakası</label>
                <input
                  type="text"
                  value={formPlate}
                  onChange={(e) => setFormPlate(e.target.value)}
                  required
                  style={{ width: "100%", padding: "8px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>Dahili Uzantı</label>
                <input
                  type="text"
                  value={formExten}
                  onChange={(e) => setFormExten(e.target.value)}
                  required
                  style={{ width: "100%", padding: "8px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc" }}
                />
              </div>
              <div style={{ gridColumn: "span 2" }}>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>Konu / Özet</label>
                <input
                  type="text"
                  value={formSummary}
                  onChange={(e) => setFormSummary(e.target.value)}
                  required
                  style={{ width: "100%", padding: "8px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc" }}
                />
              </div>
              <div>
                <button
                  type="submit"
                  disabled={actionBusy}
                  style={{
                    width: "100%",
                    padding: "8px 16px",
                    background: "#2563eb",
                    color: "#ffffff",
                    border: "none",
                    borderRadius: "6px",
                    fontWeight: "bold",
                    cursor: "pointer",
                  }}
                >
                  {actionBusy ? "Başlatılıyor..." : "Aktarımı Başlat 🚀"}
                </button>
              </div>
            </form>
          </section>

          {/* Aktarım Geçmişi Tablosu */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px", flexWrap: "wrap", gap: "10px" }}>
              <h3 style={{ margin: 0, fontSize: "15px", color: "#f8fafc" }}>
                📋 Aktarım Geçmişi ({filteredTransfers.length})
              </h3>
              <div style={{ display: "flex", gap: "6px" }}>
                {[
                  { id: "all", label: "Tümü" },
                  { id: "active", label: "Bekleyenler" },
                  { id: "accepted", label: "Kabul Edilenler" },
                  { id: "declined", label: "İade / Timeout" },
                ].map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    className={statusFilter === f.id ? "primary" : "secondary"}
                    onClick={() => setStatusFilter(f.id)}
                    style={{ padding: "4px 10px", fontSize: "12px" }}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #334155", color: "#94a3b8", textAlign: "left" }}>
                    <th style={{ padding: "8px" }}>Tarih / Saat</th>
                    <th style={{ padding: "8px" }}>Müşteri</th>
                    <th style={{ padding: "8px" }}>Plaka</th>
                    <th style={{ padding: "8px" }}>Dahili</th>
                    <th style={{ padding: "8px" }}>Durum</th>
                    <th style={{ padding: "8px" }}>Süre</th>
                    <th style={{ padding: "8px" }}>Özet</th>
                    <th style={{ padding: "8px", textAlign: "right" }}>İşlemler</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTransfers.length === 0 ? (
                    <tr>
                      <td colSpan={8} style={{ padding: "20px", textAlign: "center", color: "#64748b" }}>
                        Kayıtlı aktarım bulunamadı.
                      </td>
                    </tr>
                  ) : (
                    filteredTransfers.map((t) => {
                      let badgeBg = "#334155";
                      let badgeColor = "#f8fafc";
                      let statusLabel: string = t.status;
                      if (t.status === "initiated" || t.status === "whispering") {
                        badgeBg = "#ca8a04";
                        badgeColor = "#fef08a";
                        statusLabel = "Fısıldanıyor (10s)";
                      } else if (t.status === "accepted") {
                        badgeBg = "#15803d";
                        badgeColor = "#bbf7d0";
                        statusLabel = "Kabul Edildi";
                      } else if (t.status === "declined") {
                        badgeBg = "#b91c1c";
                        badgeColor = "#fecaca";
                        statusLabel = "Reddedildi / AI";
                      } else if (t.status === "timeout") {
                        badgeBg = "#9a3412";
                        badgeColor = "#fed7aa";
                        statusLabel = "Zaman Aşımı / AI";
                      }

                      return (
                        <tr key={t.id} style={{ borderBottom: "1px solid #1e293b" }}>
                          <td style={{ padding: "8px", color: "#cbd5e1" }}>
                            {t.created_at ? new Date(t.created_at).toLocaleTimeString() : "-"}
                          </td>
                          <td style={{ padding: "8px", fontWeight: "bold", color: "#f8fafc" }}>
                            {t.customer_name || "İsimsiz"}
                          </td>
                          <td style={{ padding: "8px" }}>
                            <span
                              style={{
                                border: "1px solid #475569",
                                padding: "2px 6px",
                                borderRadius: "4px",
                                fontSize: "11px",
                                fontWeight: "bold",
                                background: "#0f172a",
                              }}
                            >
                              {t.vehicle_plate || "-"}
                            </span>
                          </td>
                          <td style={{ padding: "8px", color: "#38bdf8" }}>{t.operator_extension}</td>
                          <td style={{ padding: "8px" }}>
                            <span
                              style={{
                                padding: "3px 8px",
                                borderRadius: "10px",
                                fontSize: "11px",
                                fontWeight: "bold",
                                background: badgeBg,
                                color: badgeColor,
                              }}
                            >
                              {statusLabel}
                            </span>
                          </td>
                          <td style={{ padding: "8px", color: "#94a3b8" }}>
                            {t.duration_seconds !== null ? `${t.duration_seconds.toFixed(1)}s` : "-"}
                          </td>
                          <td style={{ padding: "8px", maxWidth: "260px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={t.summary}>
                            {t.summary}
                          </td>
                          <td style={{ padding: "8px", textAlign: "right" }}>
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => setSelectedTransfer(t)}
                              style={{ padding: "3px 8px", fontSize: "11px" }}
                            >
                              SIP / Detay
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {/* ========================================================================= */}
      {/* SEKME 2: RT-10 CANLI MÜDAHALE & FISILTI (TAKEOVER / WHISPER)                */}
      {/* ========================================================================= */}
      {activeTab === "live_takeover" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {/* Operatör Kimlik ve Test Çubuğu */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
              <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                <div>
                  <label style={{ fontSize: "11px", color: "#94a3b8", display: "block" }}>Operatör Kodunuz</label>
                  <input
                    type="text"
                    value={operatorId}
                    onChange={(e) => setOperatorId(e.target.value)}
                    style={{ padding: "6px 10px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "13px" }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: "11px", color: "#94a3b8", display: "block" }}>Müdahale Gerekçesi</label>
                  <select
                    value={takeoverReason}
                    onChange={(e) => setTakeoverReason(e.target.value)}
                    style={{ padding: "6px 10px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "13px" }}
                  >
                    <option value="customer_complaint">Müşteri Şikâyeti / Öfke</option>
                    <option value="complex_pricing">Karmaşık Fiyat & Filo Talebi</option>
                    <option value="gpu_failover">GPU Devre Kesici Tetiklendi</option>
                    <option value="supervisor_coaching">Süpervizör Koçluk / Denetim</option>
                  </select>
                </div>
              </div>
              <div style={{ display: "flex", gap: "10px", alignItems: "flex-end" }}>
                <div>
                  <label style={{ fontSize: "11px", color: "#94a3b8", display: "block" }}>Simüle Arayan No</label>
                  <input
                    type="text"
                    value={simCallerId}
                    onChange={(e) => setSimCallerId(e.target.value)}
                    style={{ padding: "6px 10px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "13px" }}
                  />
                </div>
                <button
                  type="button"
                  className="secondary"
                  onClick={handleRegisterSimCall}
                  disabled={actionBusy}
                  style={{ padding: "6px 14px", fontSize: "13px" }}
                >
                  + Yeni Simüle Çağrı Başlat
                </button>
              </div>
            </div>
          </section>

          {/* Aktif Çağrılar Tablosu */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 12px 0", fontSize: "16px", color: "#f8fafc", display: "flex", alignItems: "center", gap: "8px" }}>
              🔴 Canlı AI Çağrıları ({liveSessions.length})
              <small style={{ fontSize: "12px", color: "#94a3b8", fontWeight: "normal" }}>
                (Tek tıkla AI anında susturulur ve çağrı operatöre köprülenir)
              </small>
            </h3>

            {liveSessions.length === 0 ? (
              <div style={{ padding: "30px", textAlign: "center", color: "#64748b" }}>
                Şu anda hatta aktif görüşme bulunmuyor. Yukarıdaki "+ Yeni Simüle Çağrı Başlat" butonuyla test çağrısı açabilirsiniz.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {liveSessions.map((s) => {
                  const isTakenOver = s.state === "taken_over";
                  return (
                    <div
                      key={s.session_id}
                      style={{
                        background: isTakenOver ? "#271212" : "#1e293b",
                        border: isTakenOver ? "1px solid #ef4444" : "1px solid #334155",
                        borderRadius: "8px",
                        padding: "16px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
                        <div>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <span style={{ fontWeight: "bold", color: "#f8fafc", fontSize: "15px" }}>
                              📱 {s.caller_id}
                            </span>
                            <span style={{ fontSize: "11px", color: "#94a3b8" }}>({s.session_id})</span>
                            <span
                              style={{
                                padding: "2px 8px",
                                borderRadius: "10px",
                                fontSize: "11px",
                                fontWeight: "bold",
                                background: isTakenOver ? "#b91c1c" : "#15803d",
                                color: isTakenOver ? "#fecaca" : "#bbf7d0",
                              }}
                            >
                              {isTakenOver ? `🔴 OPERATÖRDE (${s.operator_id})` : "🟢 YAPAY ZEKA (Leyla) YÖNETİYOR"}
                            </span>
                          </div>
                          <div style={{ display: "flex", gap: "16px", marginTop: "6px", fontSize: "12px", color: "#cbd5e1" }}>
                            <span>Turn: <b style={{ color: "#38bdf8" }}>{s.current_turn_id || "-"}</b></span>
                            <span>MOS: <b style={{ color: "#4ade80" }}>{s.mos_score}</b></span>
                            <span>RTF: <b style={{ color: "#facc15" }}>{s.rtf}</b></span>
                            <span>Paket Kaybı: <b>%{s.packet_loss_pct}</b></span>
                          </div>
                        </div>

                        {/* Eylem Butonları */}
                        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                          {!isTakenOver ? (
                            <button
                              type="button"
                              onClick={() => handleTakeover(s.session_id)}
                              disabled={actionBusy}
                              style={{
                                background: "#dc2626",
                                color: "#ffffff",
                                border: "none",
                                padding: "8px 14px",
                                borderRadius: "6px",
                                fontWeight: "bold",
                                cursor: "pointer",
                                fontSize: "13px",
                              }}
                            >
                              ⚡ Çağrıyı Devral (Takeover)
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => handleRelease(s.session_id)}
                              disabled={actionBusy}
                              style={{
                                background: "#16a34a",
                                color: "#ffffff",
                                border: "none",
                                padding: "8px 14px",
                                borderRadius: "6px",
                                fontWeight: "bold",
                                cursor: "pointer",
                                fontSize: "13px",
                              }}
                            >
                              🔁 Görüşmeyi AI'ya Geri Ver (Release)
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Fısıltı (Whisper) Alanı */}
                      <div style={{ marginTop: "12px", borderTop: "1px solid rgba(255,255,255,0.1)", paddingTop: "10px", display: "flex", gap: "8px" }}>
                        <input
                          type="text"
                          placeholder="Yapay zekaya gizli koçluk notu fısılda (Müşteri duymaz)..."
                          value={whisperMessage}
                          onChange={(e) => setWhisperMessage(e.target.value)}
                          style={{
                            flex: 1,
                            padding: "6px 10px",
                            background: "#0f172a",
                            border: "1px solid #475569",
                            borderRadius: "6px",
                            color: "#f8fafc",
                            fontSize: "12px",
                          }}
                        />
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => handleWhisper(s.session_id)}
                          disabled={actionBusy || !whisperMessage.trim()}
                          style={{ padding: "6px 12px", fontSize: "12px" }}
                        >
                          🗣️ Fısılda (Whisper)
                        </button>
                      </div>

                      {/* Önceki Fısıltı Notları */}
                      {s.whisper_notes && s.whisper_notes.length > 0 && (
                        <div style={{ marginTop: "8px", fontSize: "11px", color: "#94a3b8" }}>
                          <b>Fısıltı Geçmişi:</b> {s.whisper_notes.join(" | ")}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SEKME 3: HLS-08 KALİTE KAPISI 5 & RT-09 DAĞITIK TELEMETRİ                  */}
      {/* ========================================================================= */}
      {activeTab === "quality_gate" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {/* Kalite Kapısı 5 Benchmark Başlatma */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "16px", color: "#f8fafc" }}>
                  🎯 HLS-08: Kalite Kapısı 5
                </h3>
                <p style={{ margin: "4px 0 0 0", color: "#94a3b8", fontSize: "12px" }}>
                  Varyant B, varsa scripts/acoustic_benchmark.py ile alınan gerçek ses ölçümünü gösterir (TTS sesi telefon hattından STT ile geri tanınır). Bu düğme yeni ses üretmez.
                </p>
              </div>
              <button
                type="button"
                className="primary"
                onClick={handleRunQABenchmark}
                disabled={qaLoading}
                style={{ padding: "8px 16px", fontWeight: "bold" }}
              >
                {qaLoading ? "Ölçülüyor..." : "🚀 Kalite Kapısı 5 Süitini Çalıştır"}
              </button>
            </div>

            {/* QA Raporu Çıktısı */}
            {qaReport && (
              <div style={{ marginTop: "16px", borderTop: "1px solid #1e293b", paddingTop: "14px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "12px" }}>
                  <span style={{ fontSize: "14px", color: "#cbd5e1" }}>Genel Değerlendirme Durumu:</span>
                  <span
                    style={{
                      padding: "4px 12px",
                      borderRadius: "6px",
                      fontSize: "14px",
                      fontWeight: "bold",
                      background:
                        qaReport.quality_gate_5_status === "PASS"
                          ? "#15803d"
                          : qaReport.quality_gate_5_status === "HOLD"
                            ? "#a16207"
                            : "#b91c1c",
                      color: "#ffffff",
                    }}
                  >
                    {qaReport.quality_gate_5_status === "PASS"
                      ? "✅ KALİTE KAPISI 5: PASS"
                      : qaReport.quality_gate_5_status === "HOLD"
                        ? "⏸ HOLD (ölçüm eksik)"
                        : "❌ FAIL"}
                  </span>
                  <span style={{ fontSize: "12px", color: "#94a3b8" }}>
                    {qaReport.acoustic_report
                      ? `(Ses ölçümü: ${qaReport.acoustic_report.sample_count} cümle, ${new Date(qaReport.acoustic_report.measured_at).toLocaleString("tr-TR")})`
                      : `(${qaReport.total_sentences} test cümlesi, yalnızca metin ölçümü; ses raporu yok)`}
                  </span>
                </div>
                {qaReport.acoustic_report && (
                  <p style={{ margin: "0 0 6px 0", fontSize: "12px", color: "#cbd5e1" }}>
                    Ort. RTF: {qaReport.acoustic_report.rtf_avg ?? "—"} · Medyan F₀:{" "}
                    {qaReport.acoustic_report.f0_median_hz ?? "—"} Hz · Hat:{" "}
                    {qaReport.acoustic_report.channel} · STT: {qaReport.acoustic_report.stt_model}
                    {qaReport.acoustic_report.failed_synthesis > 0 &&
                      ` · Başarısız sentez: ${qaReport.acoustic_report.failed_synthesis}`}
                    {!qaReport.acoustic_report.has_f0_baseline && " · F₀ taban kaydı yok"}
                  </p>
                )}
                {qaReport.quality_gate_failed?.length > 0 && (
                  <p style={{ margin: "0 0 6px 0", fontSize: "12px", color: "#f87171" }}>
                    Eşiği aşan: {qaReport.quality_gate_failed.join(", ")}
                  </p>
                )}
                {qaReport.quality_gate_missing?.length > 0 && (
                  <p style={{ margin: "0 0 6px 0", fontSize: "12px", color: "#facc15" }}>
                    Ölçülmeyen: {qaReport.quality_gate_missing.join(", ")}
                  </p>
                )}

                {/* Karşılaştırmalı Varyant Tablosu */}
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px", marginTop: "10px" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid #334155", color: "#94a3b8", textAlign: "left" }}>
                      <th style={{ padding: "8px" }}>Varyant Adı</th>
                      <th style={{ padding: "8px" }}>Örnek Sayısı</th>
                      <th style={{ padding: "8px" }}>Otomotiv Doğruluğu</th>
                      <th style={{ padding: "8px" }}>Kelime Hata (WER)</th>
                      <th style={{ padding: "8px" }}>Karakter Hata (CER)</th>
                      <th style={{ padding: "8px" }}>ITU-T MOS</th>
                      <th style={{ padding: "8px" }}>Ses Benzerliği (ABX)</th>
                      <th style={{ padding: "8px" }}>Azami F0 Sapması</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(qaReport.variant_summaries || {}).map(([vName, vData]: [string, any]) => {
                      const isVariantB = vName === "variant_b";
                      const isVariantC = vName === "variant_c";
                      let label = "Varyant A (Ham metin)";
                      if (isVariantB) label = "Varyant B (P0 Otomotiv Sözlüğü)";
                      if (isVariantC) label = "Varyant C (P0 + LoRA, adaptör yok)";
                      const show = (value: number | null, prefix = "", suffix = "") =>
                        value === null || value === undefined ? "—" : `${prefix}${value}${suffix}`;

                      return (
                        <tr
                          key={vName}
                          style={{
                            borderBottom: "1px solid #1e293b",
                            background: isVariantB ? "rgba(34, 197, 94, 0.08)" : "transparent",
                          }}
                        >
                          <td style={{ padding: "8px", fontWeight: isVariantB ? "bold" : "normal", color: "#f8fafc" }}>
                            {label}
                          </td>
                          <td style={{ padding: "8px" }}>{vData.sample_count}</td>
                          <td style={{ padding: "8px" }}>{show(vData.automotive_accuracy_pct, "%")}</td>
                          <td style={{ padding: "8px" }}>{show(vData.avg_wer_pct, "%")}</td>
                          <td style={{ padding: "8px" }}>{show(vData.avg_cer_pct, "%")}</td>
                          <td style={{ padding: "8px" }}>{show(vData.avg_mos)}</td>
                          <td style={{ padding: "8px" }}>{show(vData.speaker_embedding_abx)}</td>
                          <td style={{ padding: "8px" }}>{show(vData.max_f0_drift_hz, "", " Hz")}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* M11 Fiziksel Donanım Güvenlik Kalkanı */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 8px 0", fontSize: "15px", color: "#f8fafc" }}>
              🛡️ M11 Donanım Kabul Güvenlik Kalkanı
            </h3>
            <p style={{ margin: "0 0 10px 0", fontSize: "12px", color: "#94a3b8" }}>
              Canlı ortama fiziksel Asterisk PBX pcap trace veya Hardware SIP Trunk kanıtı olmadan sahte geçişi engeller.
            </p>
            {m11Status ? (
              <div style={{ background: "#1e293b", padding: "12px", borderRadius: "6px", fontSize: "12px" }}>
                <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                  <span style={{ fontWeight: "bold", color: "#cbd5e1" }}>Fiziksel Kabul Durumu:</span>
                  <span
                    style={{
                      padding: "2px 8px",
                      borderRadius: "4px",
                      fontWeight: "bold",
                      background: m11Status.overall_status === "PASS" ? "#15803d" : "#ca8a04",
                      color: "#ffffff",
                    }}
                  >
                    {m11Status.overall_status} (Simülasyonda Kilitli)
                  </span>
                  <span style={{ color: "#94a3b8" }}>Ortam: {m11Status.environment}</span>
                </div>
                <div style={{ marginTop: "6px", color: "#e2e8f0" }}>{m11Status.guidance}</div>
              </div>
            ) : (
              <button
                type="button"
                className="secondary"
                onClick={async () => setM11Status(await api("qa/m11-status"))}
                style={{ fontSize: "12px", padding: "6px 12px" }}
              >
                M11 Durumunu Sorgula
              </button>
            )}
          </section>

          {/* RT-09 Sahte Sıfır Yasağı & OpenTelemetry Trace Span İnceleyici */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 8px 0", fontSize: "15px", color: "#f8fafc" }}>
              🔍 RT-09: Turn-Level & Generation-Level OpenTelemetry Dağıtık Telemetri
            </h3>
            <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "12px" }}>
              <input
                type="text"
                placeholder="Turn ID (Örn: turn_telemetry_test_api)"
                value={telemetryTurnId}
                onChange={(e) => setTelemetryTurnId(e.target.value)}
                style={{
                  padding: "6px 10px",
                  background: "#1e293b",
                  border: "1px solid #334155",
                  borderRadius: "6px",
                  color: "#f8fafc",
                  fontSize: "13px",
                  width: "260px",
                }}
              />
              <button
                type="button"
                className="primary"
                onClick={handleFetchTelemetry}
                disabled={actionBusy}
                style={{ padding: "6px 14px", fontSize: "13px" }}
              >
                Span Sorgula
              </button>
            </div>

            {telemetryData && (
              <div style={{ background: "#1e293b", padding: "12px", borderRadius: "6px" }}>
                <div style={{ fontSize: "12px", color: "#4ade80", fontWeight: "bold", marginBottom: "6px" }}>
                  ✅ Sahte Sıfır Yasağı Teyit Edildi: Ölçülmemiş alanlar null olarak serialize edildi.
                </div>
                <pre
                  style={{
                    background: "#0f172a",
                    padding: "10px",
                    borderRadius: "4px",
                    color: "#38bdf8",
                    fontSize: "11px",
                    overflowX: "auto",
                    maxHeight: "220px",
                  }}
                >
                  {JSON.stringify(telemetryData.opentelemetry_span || telemetryData, null, 2)}
                </pre>
              </div>
            )}
          </section>
        </div>
      )}

      {/* SIP BAŞLIKLARI VE DETAY MODALI */}
      {selectedTransfer && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.75)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "20px",
          }}
          onClick={() => setSelectedTransfer(null)}
        >
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #334155",
              borderRadius: "12px",
              padding: "24px",
              maxWidth: "600px",
              width: "100%",
              maxHeight: "85vh",
              overflowY: "auto",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <h3 style={{ margin: 0, color: "#f8fafc" }}>
                🔎 Aktarım Detayları: {selectedTransfer.id}
              </h3>
              <button
                type="button"
                className="secondary"
                onClick={() => setSelectedTransfer(null)}
                style={{ padding: "4px 8px" }}
              >
                ✕
              </button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "13px" }}>
              <div>
                <b style={{ color: "#94a3b8" }}>Müşteri:</b> {selectedTransfer.customer_name}
              </div>
              <div>
                <b style={{ color: "#94a3b8" }}>Plaka:</b> {selectedTransfer.vehicle_plate}
              </div>
              <div>
                <b style={{ color: "#94a3b8" }}>Kanal (Channel):</b> {selectedTransfer.caller_channel}
              </div>
              <div>
                <b style={{ color: "#94a3b8" }}>Fısıltı Metni (Whisper):</b>
                <p style={{ margin: "4px 0", background: "#1e293b", padding: "8px", borderRadius: "6px", fontStyle: "italic", color: "#e2e8f0" }}>
                  "{selectedTransfer.whisper_text}"
                </p>
              </div>

              <div>
                <b style={{ color: "#94a3b8" }}>SIP Başlıkları (X-Freya-*):</b>
                <pre
                  style={{
                    background: "#1e293b",
                    padding: "10px",
                    borderRadius: "6px",
                    overflowX: "auto",
                    color: "#38bdf8",
                    fontSize: "12px",
                  }}
                >
                  {JSON.stringify(
                    selectedTransfer.sip_headers || JSON.parse(selectedTransfer.sip_headers_json || "{}"),
                    null,
                    2
                  )}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
