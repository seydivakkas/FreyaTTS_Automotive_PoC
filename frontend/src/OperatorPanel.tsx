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
import { dash, errorMessage, useEscape } from "./ui";
import { OperatorToday } from "./OperatorToday";

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
  onOpenConversation: (id: string) => void;
}

interface UnclearTurn {
  id: string;
  role: string;
  text: string;
  metrics: string;
  created_at: string;
  is_unclear: boolean;
}

interface UnclearCall {
  id: string;
  status: string;
  channel: string;
  created_at: string;
  operator_notes: string;
  resolved_at: string | null;
  turn_count: number;
  unclear_count: number;
  unclear_phrases: string[];
  has_recording: boolean;
  turns: UnclearTurn[];
}

export function OperatorPanel({ api, onError, onOpenConversation }: OperatorPanelProps) {
  const [activeTab, setActiveTab] = useState<"today" | "sip_transfers" | "live_takeover" | "quality_gate" | "failed_calls" | "kvkk_compliance">("today");
  const [todayRevision, setTodayRevision] = useState(0);

  // Başarısız & Anlaşılamayan Görüşmeler State
  const [unclearCalls, setUnclearCalls] = useState<UnclearCall[]>([]);
  const [unclearLoading, setUnclearLoading] = useState(false);
  const [selectedUnclearCall, setSelectedUnclearCall] = useState<UnclearCall | null>(null);
  const [feedbackTerm, setFeedbackTerm] = useState("");
  const [feedbackSpoken, setFeedbackSpoken] = useState("");
  const [feedbackCategory, setFeedbackCategory] = useState("brand");
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState("");

  // KVKK Transkript Saklama & Silme Talepleri State
  const [kvkkAudit, setKvkkAudit] = useState<any>(null);
  const [kvkkAuditLoading, setKvkkAuditLoading] = useState(false);
  const [kvkkPurgeBusy, setKvkkPurgeBusy] = useState(false);
  const [kvkkPurgeMsg, setKvkkPurgeMsg] = useState("");
  const [kvkkRequests, setKvkkRequests] = useState<any[]>([]);
  const [kvkkRequestsLoading, setKvkkRequestsLoading] = useState(false);
  const [selectedCertificate, setSelectedCertificate] = useState<any | null>(null);

  // Yeni Silme Talebi Formu
  const [newReqType, setNewReqType] = useState<"phone" | "plate" | "customer_name" | "conversation_id">("phone");
  const [newReqVal, setNewReqVal] = useState("");
  const [newReqName, setNewReqName] = useState("");
  const [newReqReason, setNewReqReason] = useState("KVKK Madde 11 uyarınca silme talebi");
  const [newReqNotes, setNewReqNotes] = useState("");
  const [newReqBusy, setNewReqBusy] = useState(false);
  const [newReqMsg, setNewReqMsg] = useState("");
  const [executingReqId, setExecutingReqId] = useState<string | null>(null);

  // SIP Aktarımları State
  const [transfers, setTransfers] = useState<OperatorTransfer[]>([]);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [selectedTransfer, setSelectedTransfer] = useState<OperatorTransfer | null>(null);

  // Test aktarımı formu alanları
  const [formCustomer, setFormCustomer] = useState("");
  const [formPlate, setFormPlate] = useState("");
  const [formSummary, setFormSummary] = useState("");
  const [formExten, setFormExten] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  // Canlı devralma ve fısıltı durumu
  const [liveSessions, setLiveSessions] = useState<OperatorSessionView[]>([]);
  const [operatorId, setOperatorId] = useState("");
  const [takeoverReason, setTakeoverReason] = useState("customer_complaint");
  const [whisperMessage, setWhisperMessage] = useState("");
  const [simCallerId, setSimCallerId] = useState("");

  // Kalite Kapısı 5 & Telemetri State
  const [qaReport, setQaReport] = useState<any>(null);
  const [qaLoading, setQaLoading] = useState(false);
  const [m11Status, setM11Status] = useState<any>(null);
  const [telemetryTurnId, setTelemetryTurnId] = useState("");
  const [telemetryData, setTelemetryData] = useState<any>(null);

  const [pollError, setPollError] = useState("");
  const pollIntervalRef = useRef<any>(null);

  useEscape(() => setSelectedTransfer(null), !!selectedTransfer);
  useEscape(() => setSelectedCertificate(null), !!selectedCertificate);

  // silent=true: 3 sn'lik otomatik yenilemede "Yenileniyor" yanıp sönmesini önler.
  const loadTransfers = async (silent = false) => {
    try {
      if (!silent) setLoading(true);
      const data: OperatorTransfer[] = await api("transfers?limit=50");
      setTransfers(data || []);
      setPollError("");
    } catch (err: any) {
      setPollError(`Aktarım listesi alınamadı: ${err?.message || err}`);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const loadLiveSessions = async () => {
    try {
      const data = await api("operator/live-sessions");
      setLiveSessions(data.sessions || []);
      setPollError("");
    } catch (err: any) {
      setPollError(`Canlı çağrı listesi alınamadı: ${err?.message || err}`);
    }
  };

  const loadUnclearCalls = async () => {
    try {
      setUnclearLoading(true);
      const data: UnclearCall[] = await api("conversations/unclear?limit=50");
      setUnclearCalls(data || []);
      if (data && data.length > 0 && !selectedUnclearCall) {
        setSelectedUnclearCall(data[0]);
      }
    } catch (err: any) {
      setPollError(`Başarısız görüşmeler alınamadı: ${err?.message || err}`);
    } finally {
      setUnclearLoading(false);
    }
  };

  const handleFeedbackSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUnclearCall) return;
    if (!feedbackTerm.trim() || !feedbackSpoken.trim()) {
      setFeedbackMsg("Lütfen hem terimi hem de telaffuzunu yazın.");
      return;
    }
    try {
      setFeedbackBusy(true);
      await api(`conversations/${selectedUnclearCall.id}/feedback-lexicon`, "POST", {
        term: feedbackTerm.trim(),
        spoken: feedbackSpoken.trim(),
        category: feedbackCategory,
      });
      setFeedbackMsg(`'${feedbackTerm}' başarıyla otomotiv sözlüğüne eklendi ve normalizer güncellendi!`);
      setFeedbackTerm("");
      setFeedbackSpoken("");
      await loadUnclearCalls();
    } catch (err: any) {
      setFeedbackMsg(`Sözlüğe ekleme hatası: ${err?.message || err}`);
    } finally {
      setFeedbackBusy(false);
    }
  };

  const loadKvkkAudit = async () => {
    try {
      setKvkkAuditLoading(true);
      const data = await api("kvkk/transcript-retention-audit");
      setKvkkAudit(data);
    } catch (err: any) {
      setPollError(`KVKK saklama denetimi alınamadı: ${err?.message || err}`);
    } finally {
      setKvkkAuditLoading(false);
    }
  };

  const loadKvkkRequests = async () => {
    try {
      setKvkkRequestsLoading(true);
      const data = await api("kvkk/erasure-requests?limit=50");
      setKvkkRequests(data || []);
    } catch (err: any) {
      setPollError(`Silme talepleri alınamadı: ${err?.message || err}`);
    } finally {
      setKvkkRequestsLoading(false);
    }
  };

  const handlePurgeTranscripts = async (dryRun: boolean) => {
    try {
      setKvkkPurgeBusy(true);
      setKvkkPurgeMsg("");
      const res = await api("kvkk/transcript-retention-purge", "POST", { dry_run: dryRun });
      if (dryRun) {
        setKvkkPurgeMsg(`Önizleme: ${res.purged_conversations} görüşme (${res.purged_turns} tur transkript) imha edilebilir.`);
      } else {
        setKvkkPurgeMsg(`Başarılı: ${res.purged_conversations} görüşme ve ${res.purged_turns} tur transkript kalıcı olarak imha edildi/anonimleştirildi.`);
        await loadKvkkAudit();
      }
    } catch (err: any) {
      setKvkkPurgeMsg(`İmha hatası: ${err?.message || err}`);
    } finally {
      setKvkkPurgeBusy(false);
    }
  };

  const handleCreateErasureRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newReqVal.trim()) {
      setNewReqMsg("Lütfen silinecek kimlik değerini (telefon, plaka vb.) girin.");
      return;
    }
    try {
      setNewReqBusy(true);
      setNewReqMsg("");
      const res = await api("kvkk/erasure-requests", "POST", {
        identifier_type: newReqType,
        identifier_value: newReqVal.trim(),
        requester_name: newReqName.trim(),
        reason: newReqReason.trim(),
        notes: newReqNotes.trim(),
      });
      const aff = res.impact_summary?.total_records_affected || 0;
      setNewReqMsg(`Talep oluşturuldu! (ID: ${res.id}, Etkilenecek Kayıt: ${aff})`);
      setNewReqVal("");
      setNewReqName("");
      setNewReqNotes("");
      await loadKvkkRequests();
    } catch (err: any) {
      setNewReqMsg(`Talep oluşturma hatası: ${err?.message || err}`);
    } finally {
      setNewReqBusy(false);
    }
  };

  const handleExecuteErasureRequest = async (requestId: string) => {
    if (!window.confirm("Bu talep kapsamında bulunan tüm kişisel veriler (transkript, ses kaydı, randevu, whatsapp) kalıcı olarak imha edilecek ve SHA-256 imzalı İmha Tutanağı üretilecektir. Onaylıyor musunuz?")) {
      return;
    }
    try {
      setExecutingReqId(requestId);
      const res = await api(`kvkk/erasure-requests/${requestId}/execute`, "POST", {});
      alert(`Silme işlemi başarıyla icra edildi!\nSHA-256 Sertifika: ${res.certificate_sha256}`);
      await loadKvkkRequests();
      await loadKvkkAudit();
    } catch (err: any) {
      alert(`İcra hatası: ${err?.message || err}`);
    } finally {
      setExecutingReqId(null);
    }
  };

  const handleViewCertificate = async (requestId: string) => {
    try {
      const data = await api(`kvkk/erasure-requests/${requestId}/certificate?format=json`);
      setSelectedCertificate(data);
    } catch (err: any) {
      alert(`Sertifika alınamadı: ${err?.message || err}`);
    }
  };

  useEffect(() => {
    if (autoRefresh) {
      pollIntervalRef.current = setInterval(() => {
        if (activeTab === "sip_transfers") {
          loadTransfers(true);
        } else if (activeTab === "live_takeover") {
          loadLiveSessions();
        } else if (activeTab === "failed_calls") {
          loadUnclearCalls();
        } else if (activeTab === "kvkk_compliance") {
          loadKvkkAudit();
          loadKvkkRequests();
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

  // Canlı devralma işlemleri
  const handleRegisterSimCall = async () => {
    try {
      setActionBusy(true);
      // sim_ öneki: bu çağrı simülasyondur; MOS/RTF değerleri uydurulmaz, listede "—" gösterilir.
      const sessId = `sim_${Date.now()}`;
      await api("operator/register-call", "POST", {
        session_id: sessId,
        caller_id: simCallerId.trim(),
        initial_turn_id: `turn_${Date.now()}`,
      });
      await loadLiveSessions();
    } catch (err: any) {
      onError(`Simülasyon çağrısı başlatılamadı: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const handleTakeover = async (sessionId: string) => {
    if (!operatorId.trim()) {
      onError("Çağrıyı devralmak için operatör kodunu girin.");
      return;
    }
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
              🎧 Çağrı Merkezi Operatör & Kalite Konsolu
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
              Sıcak aktarım (fısıltı), canlı devralma, tur telemetrisi ve Kalite Kapısı 5
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
                if (activeTab === "today") setTodayRevision((n) => n + 1);
                if (activeTab === "sip_transfers") loadTransfers();
                if (activeTab === "live_takeover") loadLiveSessions();
                if (activeTab === "failed_calls") loadUnclearCalls();
                if (activeTab === "kvkk_compliance") {
                  loadKvkkAudit();
                  loadKvkkRequests();
                }
              }}
              disabled={loading || actionBusy}
              style={{ padding: "6px 12px", fontSize: "13px" }}
            >
              {loading ? "Yenileniyor..." : "Yenile ↻"}
            </button>
          </div>
        </div>

        {pollError && (
          <div role="alert" className="error" style={{ marginBottom: "12px" }}>
            {pollError}
          </div>
        )}

        {/* Sekme Butonları */}
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", borderTop: "1px solid #1e293b", paddingTop: "12px" }}>
          <button
            type="button"
            className={activeTab === "today" ? "primary" : "secondary"}
            aria-current={activeTab === "today" ? "true" : undefined}
            onClick={() => { setPollError(""); setActiveTab("today"); }}
          >Bugün</button>
          <button
            type="button"
            className={activeTab === "sip_transfers" ? "primary" : "secondary"}
            onClick={() => { setActiveTab("sip_transfers"); loadTransfers(); }}
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
            ⚡ Canlı Müdahale & Fısıltı
          </button>
          <button
            type="button"
            className={activeTab === "quality_gate" ? "primary" : "secondary"}
            onClick={() => setActiveTab("quality_gate")}
            style={{ padding: "8px 16px", fontSize: "13px", fontWeight: "bold" }}
          >
            🎯 Kalite Kapısı 5 & Telemetri
          </button>
          <button
            type="button"
            className={activeTab === "failed_calls" ? "primary" : "secondary"}
            onClick={() => {
              setActiveTab("failed_calls");
              loadUnclearCalls();
            }}
            style={{ padding: "8px 16px", fontSize: "13px", fontWeight: "bold" }}
          >
            🚨 Başarısız & Anlaşılamayan Görüşmeler ({unclearCalls.length})
          </button>
          <button
            type="button"
            className={activeTab === "kvkk_compliance" ? "primary" : "secondary"}
            onClick={() => {
              setActiveTab("kvkk_compliance");
              loadKvkkAudit();
              loadKvkkRequests();
            }}
            style={{ padding: "8px 16px", fontSize: "13px", fontWeight: "bold" }}
          >
            🛡️ KVKK Silme & Saklama ({kvkkRequests.length})
          </button>
        </div>
      </section>

      {activeTab === "today" && <OperatorToday
        api={api}
        autoRefresh={autoRefresh}
        revision={todayRevision}
        onOpenConversation={onOpenConversation}
        onOpenTransfer={async (id) => {
          try {
            setPollError("");
            setSelectedTransfer(await api(`transfers/${id}`));
          } catch (err) {
            setPollError(errorMessage(err));
          }
        }}
      />}

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
                      🗣️ Operatör Fısıltısı (Dahiliye Okunan Sesli Özet):
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
                    Zaman aşımında (yapılandırılmış süre dolunca) çağrı otomatik olarak yapay zekâya döner.
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* Test Simülasyon Formu */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", color: "#f8fafc" }}>
              🧪 Simülasyon: Test Amaçlı Aktarım Başlat
              <button
                type="button"
                className="secondary"
                style={{ marginLeft: "12px", padding: "3px 10px", fontSize: "11px" }}
                onClick={() => {
                  setFormCustomer("Ahmet Yılmaz");
                  setFormPlate("34 ABC 123");
                  setFormSummary("14:30 randevu teyidi / kaporta boya ekspertiz sorusu");
                  setFormExten("6002");
                }}
              >
                Örnek doldur
              </button>
            </h3>
            <form onSubmit={handleCreateTestTransfer} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "10px", alignItems: "flex-end" }}>
              <div>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }} htmlFor="op-f-cust">Müşteri Adı</label>
                <input
                  id="op-f-cust"
                  type="text"
                  value={formCustomer}
                  onChange={(e) => setFormCustomer(e.target.value)}
                  required
                  style={{ width: "100%", padding: "8px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }} htmlFor="op-f-plate">Araç Plakası</label>
                <input
                  id="op-f-plate"
                  type="text"
                  value={formPlate}
                  onChange={(e) => setFormPlate(e.target.value)}
                  required
                  style={{ width: "100%", padding: "8px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }} htmlFor="op-f-ext">Dahili Uzantı</label>
                <input
                  id="op-f-ext"
                  type="text"
                  value={formExten}
                  onChange={(e) => setFormExten(e.target.value)}
                  required
                  style={{ width: "100%", padding: "8px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc" }}
                />
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }} htmlFor="op-f-sum">Konu / Özet</label>
                <input
                  id="op-f-sum"
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
                  {actionBusy ? "Başlatılıyor..." : "Simüle Aktarımı Başlat 🚀"}
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
              <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
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

            <div className="table-wrap">
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
                        statusLabel = "Fısıldanıyor";
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
                  <label htmlFor="op-id" style={{ fontSize: "11px", color: "#94a3b8", display: "block" }}>Operatör Kodunuz</label>
                  <input
                    id="op-id"
                    placeholder="örn. op_1"
                    type="text"
                    value={operatorId}
                    onChange={(e) => setOperatorId(e.target.value)}
                    style={{ padding: "6px 10px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "13px" }}
                  />
                </div>
                <div>
                  <label htmlFor="op-reason" style={{ fontSize: "11px", color: "#94a3b8", display: "block" }}>Müdahale Gerekçesi</label>
                  <select
                    id="op-reason"
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
                  <label htmlFor="op-sim-caller" style={{ fontSize: "11px", color: "#94a3b8", display: "block" }}>Simüle Arayan No</label>
                  <input
                    id="op-sim-caller"
                    placeholder="örn. 05XXXXXXXXX"
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
                  disabled={actionBusy || !simCallerId.trim()}
                  style={{ padding: "6px 14px", fontSize: "13px" }}
                >
                  + Simülasyon: Yeni Çağrı Başlat
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
                Şu anda hatta aktif görüşme bulunmuyor. Yukarıdaki "+ Simülasyon: Yeni Çağrı Başlat" butonuyla test çağrısı açabilirsiniz.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {liveSessions.map((s) => {
                  const isTakenOver = s.state === "taken_over";
                  const isSim = s.session_id.startsWith("sim_");
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
                            {isSim && <span className="pill">Simülasyon</span>}
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
                          <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", marginTop: "6px", fontSize: "12px", color: "#cbd5e1" }}>
                            <span>Turn: <b style={{ color: "#38bdf8" }}>{s.current_turn_id || "-"}</b></span>
                            <span>MOS: <b style={{ color: "#4ade80" }}>{isSim ? "—" : dash(s.mos_score)}</b></span>
                            <span>RTF: <b style={{ color: "#facc15" }}>{isSim ? "—" : dash(s.rtf)}</b></span>
                            <span>Paket Kaybı: <b>{isSim ? "—" : dash(s.packet_loss_pct, "%")}</b></span>
                          </div>
                        </div>

                        {/* Eylem Butonları */}
                        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                          {!isTakenOver ? (
                            <button
                              type="button"
                              onClick={() => handleTakeover(s.session_id)}
                              disabled={actionBusy || !operatorId.trim()}
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
                          aria-label="Fısıltı notu"
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
                  🎯 Kalite Kapısı 5
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
                <div className="table-wrap"><table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px", marginTop: "10px" }}>
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
                </table></div>
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
                    {m11Status.overall_status}
                  </span>
                  <span style={{ color: "#94a3b8" }}>Ortam: {m11Status.environment}</span>
                </div>
                {m11Status.reason && (
                  <div style={{ marginTop: "6px", color: "#e2e8f0" }}>{m11Status.reason}</div>
                )}
                {Array.isArray(m11Status.required_for_pass) && m11Status.required_for_pass.length > 0 && (
                  <div style={{ marginTop: "6px", color: "#cbd5e1" }}>
                    <b>Geçiş için gerekenler:</b>
                    <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>
                      {m11Status.required_for_pass.map((r: string) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  </div>
                )}
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

          {/* Tur telemetrisi / trace span inceleyici */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 8px 0", fontSize: "15px", color: "#f8fafc" }}>
              🔍 Tur telemetrisi
            </h3>
            <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "12px" }}>
              <input
                type="text"
                aria-label="Tur kimliği"
                placeholder="Tur kimliği (turn id)"
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
                disabled={actionBusy || !telemetryTurnId.trim()}
                style={{ padding: "6px 14px", fontSize: "13px" }}
              >
                Span Sorgula
              </button>
            </div>

            {telemetryData && (
              <div style={{ background: "#1e293b", padding: "12px", borderRadius: "6px" }}>
                <div style={{ fontSize: "12px", color: "#4ade80", fontWeight: "bold", marginBottom: "6px" }}>
                  Ölçülmemiş alanlar null olarak gösterilir (0 yazılmaz).
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

      {/* ========================================================================= */}
      {/* SEKME 4: BAŞARISIZ & ANLAŞILAMAYAN GÖRÜŞMELER (LEXICON GERİ BESLEME)       */}
      {/* ========================================================================= */}
      {activeTab === "failed_calls" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 6px 0", fontSize: "16px", color: "#f8fafc", display: "flex", alignItems: "center", gap: "8px" }}>
              <span>🚨</span>
              <span>Başarısız & Anlaşılamayan Görüşmeler — Sözlüğe Geri Besleme</span>
            </h3>
            <p style={{ margin: 0, color: "#94a3b8", fontSize: "13px" }}>
              Asistanın teyit istediği veya terimlerin yanlış anlaşıldığı görüşmeleri dinleyip doğru otomotiv terimini sisteme öğretebilirsiniz. Yapılan düzeltmeler anında fonetik normalizer'a ve terim sözlüğüne aktarılır.
            </p>
          </section>

          {feedbackMsg && (
            <div
              style={{
                padding: "10px 14px",
                borderRadius: "6px",
                background: feedbackMsg.includes("başarıyla") ? "#064e3b" : "#7f1d1d",
                color: feedbackMsg.includes("başarıyla") ? "#6ee7b7" : "#fca5a5",
                fontSize: "13px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span>{feedbackMsg}</span>
              <button
                type="button"
                onClick={() => setFeedbackMsg("")}
                style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontWeight: "bold" }}
              >
                ✕
              </button>
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "minmax(320px, 1fr) minmax(400px, 1.5fr)", gap: "16px" }}>
            {/* Sol Kolon: Görüşme Listesi */}
            <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px", maxHeight: "700px", overflowY: "auto" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <h4 style={{ margin: 0, fontSize: "14px", color: "#f8fafc" }}>
                  Görüşmeler ({unclearCalls.length})
                </h4>
                <button
                  type="button"
                  className="secondary"
                  onClick={loadUnclearCalls}
                  disabled={unclearLoading}
                  style={{ fontSize: "11px", padding: "3px 8px" }}
                >
                  {unclearLoading ? "..." : "Yenile ↻"}
                </button>
              </div>

              {!unclearCalls.length && !unclearLoading && (
                <div style={{ textAlign: "center", padding: "2rem", color: "#64748b", fontSize: "13px" }}>
                  🎉 Harika! İncelenmesi gereken anlaşılamayan görüşme bulunmuyor.
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {unclearCalls.map((c) => {
                  const isSelected = selectedUnclearCall?.id === c.id;
                  return (
                    <div
                      key={c.id}
                      onClick={() => setSelectedUnclearCall(c)}
                      style={{
                        padding: "10px",
                        borderRadius: "6px",
                        border: isSelected ? "1px solid #3b82f6" : "1px solid #1e293b",
                        background: isSelected ? "#1e293b" : "#0f172a",
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                        <span style={{ fontSize: "11px", color: "#94a3b8" }}>
                          {c.created_at?.substring(0, 16).replace("T", " ")}
                        </span>
                        <span
                          style={{
                            fontSize: "10px",
                            padding: "2px 6px",
                            borderRadius: "10px",
                            background: c.unclear_count > 0 ? "#7f1d1d" : "#854d0e",
                            color: "#fecaca",
                            fontWeight: "bold",
                          }}
                        >
                          {c.unclear_count > 0 ? `⚠️ ${c.unclear_count} Belirsiz Tur` : "Takipte"}
                        </span>
                      </div>
                      <div style={{ fontSize: "12px", color: "#f1f5f9", fontWeight: 600 }}>
                        Çağrı #{c.id.substring(0, 8)} ({c.channel})
                      </div>
                      <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                        Toplam {c.turn_count} diyalog turu {c.has_recording ? "• 🎧 Ses Var" : ""}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Sağ Kolon: Seçili Görüşme Detayı, Ses Kaydı & Sözlüğe Geri Besleme */}
            <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px", display: "flex", flexDirection: "column", gap: "16px" }}>
              {selectedUnclearCall ? (
                <>
                  <div style={{ borderBottom: "1px solid #1e293b", paddingBottom: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <h4 style={{ margin: 0, fontSize: "15px", color: "#f8fafc" }}>
                        Çağrı #{selectedUnclearCall.id}
                      </h4>
                      <span style={{ fontSize: "11px", color: "#94a3b8" }}>
                        Kanal: {selectedUnclearCall.channel}
                      </span>
                    </div>

                    {/* Ses Çalar */}
                    <div style={{ marginTop: "10px", padding: "10px", background: "#1e293b", borderRadius: "6px" }}>
                      <div style={{ fontSize: "12px", color: "#38bdf8", fontWeight: "bold", marginBottom: "6px" }}>
                        🎧 Görüşme Ses Kaydı:
                      </div>
                      {selectedUnclearCall.has_recording ? (
                        <audio
                          controls
                          src={`/api/conversations/${selectedUnclearCall.id}/audio`}
                          style={{ width: "100%", height: "36px" }}
                        />
                      ) : (
                        <div style={{ fontSize: "12px", color: "#94a3b8", fontStyle: "italic" }}>
                          ℹ️ Bu oturumun ham WAV kaydı doğrudan ses kartından akıtılmıştır veya arşivlenmiştir.
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Transkript Akışı */}
                  <div>
                    <h5 style={{ margin: "0 0 8px 0", fontSize: "13px", color: "#cbd5e1" }}>
                      💬 Diyalog Akışı:
                    </h5>
                    <div style={{ maxHeight: "250px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "8px", paddingRight: "4px" }}>
                      {selectedUnclearCall.turns.map((t) => (
                        <div
                          key={t.id}
                          style={{
                            padding: "8px 12px",
                            borderRadius: "6px",
                            fontSize: "12px",
                            background: t.is_unclear
                              ? "#451a03"
                              : t.role === "user"
                              ? "#1e3a8a"
                              : "#1e293b",
                            border: t.is_unclear ? "1px solid #b45309" : "none",
                            color: "#f8fafc",
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "2px" }}>
                            <span style={{ fontWeight: "bold", color: t.role === "user" ? "#93c5fd" : "#38bdf8" }}>
                              {t.role === "user" ? "Müşteri" : "FreyaTTS Asistan"}
                            </span>
                            {t.is_unclear && (
                              <span style={{ color: "#fcd34d", fontSize: "10px", fontWeight: "bold" }}>
                                ⚠️ ANLAŞILAMADI / TEYİT
                              </span>
                            )}
                          </div>
                          <div>{t.text}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Sözlüğe Geri Besleme Formu */}
                  <div style={{ marginTop: "auto", background: "#1e293b", border: "1px solid #334155", borderRadius: "8px", padding: "14px" }}>
                    <div style={{ fontSize: "13px", color: "#f8fafc", fontWeight: "bold", marginBottom: "8px", display: "flex", alignItems: "center", gap: "6px" }}>
                      <span>✍️</span>
                      <span>Düzeltmeyi Sözlüğe Geri Besle (Domain Lexicon Feedback)</span>
                    </div>
                    <form onSubmit={handleFeedbackSubmit} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
                          Doğru Otomotiv Terimi (Örn: Qashqai)
                        </label>
                        <input
                          type="text"
                          value={feedbackTerm}
                          onChange={(e) => setFeedbackTerm(e.target.value)}
                          placeholder="Örn: Qashqai, EcoBoost"
                          required
                          style={{ width: "100%", padding: "6px 8px", background: "#0f172a", border: "1px solid #475569", borderRadius: "4px", color: "#f8fafc", fontSize: "12px" }}
                        />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
                          Duyulan / Okunuş (Örn: kaşkay)
                        </label>
                        <input
                          type="text"
                          value={feedbackSpoken}
                          onChange={(e) => setFeedbackSpoken(e.target.value)}
                          placeholder="Örn: kaşkay, eko büst"
                          required
                          style={{ width: "100%", padding: "6px 8px", background: "#0f172a", border: "1px solid #475569", borderRadius: "4px", color: "#f8fafc", fontSize: "12px" }}
                        />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
                          Kategori
                        </label>
                        <select
                          value={feedbackCategory}
                          onChange={(e) => setFeedbackCategory(e.target.value)}
                          style={{ width: "100%", padding: "6px 8px", background: "#0f172a", border: "1px solid #475569", borderRadius: "4px", color: "#f8fafc", fontSize: "12px" }}
                        >
                          <option value="brand">Marka (Brand)</option>
                          <option value="model">Model</option>
                          <option value="technical">Motor / Teknik</option>
                          <option value="custom">Özel Terim</option>
                        </select>
                      </div>
                      <div style={{ display: "flex", alignItems: "flex-end" }}>
                        <button
                          type="submit"
                          disabled={feedbackBusy}
                          style={{
                            width: "100%",
                            padding: "7px 12px",
                            background: "#2563eb",
                            color: "#ffffff",
                            border: "none",
                            borderRadius: "4px",
                            fontWeight: "bold",
                            fontSize: "12px",
                            cursor: "pointer",
                          }}
                        >
                          {feedbackBusy ? "Kaydediliyor..." : "💾 Sözlüğe Ekle & Normalizer'ı Güncelle"}
                        </button>
                      </div>
                    </form>
                  </div>
                </>
              ) : (
                <div style={{ textAlign: "center", padding: "4rem 2rem", color: "#64748b", fontSize: "13px" }}>
                  Sol taraftan incelemek istediğiniz bir görüşmeyi seçin.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SEKME 5: KVKK TRANSKRİPT SAKLAMA SÜRESİ VE SİLME TALEPLERİ                 */}
      {/* ========================================================================= */}
      {activeTab === "kvkk_compliance" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* ÜST BİLGİ & DENETİM PANELİ */}
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: "12px",
              padding: "20px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", flexWrap: "wrap", gap: "10px" }}>
              <div>
                <h3 style={{ margin: 0, color: "#f8fafc", fontSize: "16px", display: "flex", alignItems: "center", gap: "8px" }}>
                  🛡️ KVKK Transkript Saklama Süresi ve Otomatik İmha İlkesi
                  <span
                    style={{
                      fontSize: "11px",
                      padding: "2px 8px",
                      borderRadius: "10px",
                      background: kvkkAudit?.compliance_status === "compliant" ? "#065f46" : "#991b1b",
                      color: "#f8fafc",
                    }}
                  >
                    {kvkkAudit?.compliance_status === "compliant" ? "✓ UYUMLU" : "⚠ İŞLEM GEREKİYOR"}
                  </span>
                </h3>
                <p style={{ margin: "4px 0 0 0", color: "#94a3b8", fontSize: "13px" }}>
                  6698 sayılı KVKK Madde 7 gereğince {kvkkAudit?.retention_policy_days ?? 30} günü aşan konuşma transkriptleri periyodik olarak anonimleştirilerek imha edilir.
                </p>
              </div>

              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  type="button"
                  className="secondary"
                  disabled={kvkkAuditLoading || kvkkPurgeBusy}
                  onClick={() => loadKvkkAudit()}
                  style={{ padding: "6px 12px", fontSize: "12px" }}
                >
                  {kvkkAuditLoading ? "Denetleniyor..." : "Denetle ↻"}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={kvkkPurgeBusy}
                  onClick={() => handlePurgeTranscripts(true)}
                  style={{ padding: "6px 12px", fontSize: "12px" }}
                >
                  Önizleme (Dry Run)
                </button>
                <button
                  type="button"
                  className="primary"
                  disabled={kvkkPurgeBusy || !kvkkAudit?.expired_conversations_count}
                  onClick={() => handlePurgeTranscripts(false)}
                  style={{ padding: "6px 12px", fontSize: "12px", background: "#b91c1c", borderColor: "#dc2626" }}
                >
                  {kvkkPurgeBusy ? "İmha Ediliyor..." : "Süresi Dolanları İmha Et"}
                </button>
              </div>
            </div>

            {kvkkPurgeMsg && (
              <div
                style={{
                  padding: "10px 14px",
                  borderRadius: "8px",
                  background: kvkkPurgeMsg.includes("Başarılı") ? "#064e3b" : "#1e293b",
                  border: "1px solid #334155",
                  color: "#f8fafc",
                  fontSize: "13px",
                  marginBottom: "16px",
                }}
              >
                {kvkkPurgeMsg}
              </div>
            )}

            {/* İstatistik Kartları */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                gap: "12px",
              }}
            >
              <div style={{ background: "#1e293b", padding: "14px", borderRadius: "8px" }}>
                <div style={{ color: "#94a3b8", fontSize: "12px" }}>Saklama İlkesi</div>
                <div style={{ fontSize: "20px", fontWeight: "bold", color: "#38bdf8", marginTop: "4px" }}>
                  {kvkkAudit?.retention_policy_days ?? 30} Gün
                </div>
              </div>
              <div style={{ background: "#1e293b", padding: "14px", borderRadius: "8px" }}>
                <div style={{ color: "#94a3b8", fontSize: "12px" }}>Aktif Transkriptler</div>
                <div style={{ fontSize: "20px", fontWeight: "bold", color: "#f8fafc", marginTop: "4px" }}>
                  {kvkkAudit?.active_conversations ?? 0}
                </div>
              </div>
              <div style={{ background: "#1e293b", padding: "14px", borderRadius: "8px" }}>
                <div style={{ color: "#94a3b8", fontSize: "12px" }}>Süresi Dolan (İmha Bekleyen)</div>
                <div style={{ fontSize: "20px", fontWeight: "bold", color: kvkkAudit?.expired_conversations_count ? "#f87171" : "#4ade80", marginTop: "4px" }}>
                  {kvkkAudit?.expired_conversations_count ?? 0} Görüşme
                </div>
                <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                  ({kvkkAudit?.expired_turns_count ?? 0} metin turu)
                </div>
              </div>
              <div style={{ background: "#1e293b", padding: "14px", borderRadius: "8px" }}>
                <div style={{ color: "#94a3b8", fontSize: "12px" }}>İmha Edilmiş / Anonim</div>
                <div style={{ fontSize: "20px", fontWeight: "bold", color: "#94a3b8", marginTop: "4px" }}>
                  {kvkkAudit?.already_purged_conversations ?? 0}
                </div>
              </div>
            </div>
          </div>

          {/* İKİ KOLONLU GÖVDE: YENİ TALEP FORMU & TALEPLER LİSTESİ */}
          <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: "20px" }}>
            {/* SOL: YENİ SİLME TALEBİ FORMU */}
            <div
              style={{
                background: "#0f172a",
                border: "1px solid #1e293b",
                borderRadius: "12px",
                padding: "20px",
                height: "fit-content",
              }}
            >
              <h4 style={{ margin: "0 0 12px 0", color: "#f8fafc", fontSize: "15px" }}>
                📝 Yeni Silme Talebi (KVKK Madde 11)
              </h4>
              <p style={{ margin: "0 0 16px 0", color: "#94a3b8", fontSize: "12px", lineHeight: "1.5" }}>
                Müşterinin unutulma hakkı başvurusu üzerine telefon, plaka veya görüşme ID girerek bağlı tüm verileri tarayabilir ve imha edebilirsiniz.
              </p>

              <form onSubmit={handleCreateErasureRequest} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <div>
                  <label style={{ display: "block", color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
                    Kimlik Türü
                  </label>
                  <select
                    value={newReqType}
                    onChange={(e: any) => setNewReqType(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "8px",
                      borderRadius: "6px",
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #334155",
                      fontSize: "13px",
                    }}
                  >
                    <option value="phone">Telefon Numarası</option>
                    <option value="plate">Araç Plakası</option>
                    <option value="customer_name">Müşteri Adı</option>
                    <option value="conversation_id">Görüşme ID</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: "block", color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
                    Kimlik Değeri *
                  </label>
                  <input
                    type="text"
                    value={newReqVal}
                    onChange={(e) => setNewReqVal(e.target.value)}
                    placeholder={
                      newReqType === "phone"
                        ? "05321234567"
                        : newReqType === "plate"
                        ? "34ABC789"
                        : newReqType === "customer_name"
                        ? "Ahmet Yılmaz"
                        : "uuid..."
                    }
                    style={{
                      width: "100%",
                      padding: "8px",
                      borderRadius: "6px",
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #334155",
                      fontSize: "13px",
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: "block", color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
                    Başvuran Adı (Opsiyonel)
                  </label>
                  <input
                    type="text"
                    value={newReqName}
                    onChange={(e) => setNewReqName(e.target.value)}
                    placeholder="Başvuran kişi veya vekili"
                    style={{
                      width: "100%",
                      padding: "8px",
                      borderRadius: "6px",
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #334155",
                      fontSize: "13px",
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: "block", color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
                    Talep Gerekçesi
                  </label>
                  <input
                    type="text"
                    value={newReqReason}
                    onChange={(e) => setNewReqReason(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "8px",
                      borderRadius: "6px",
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #334155",
                      fontSize: "13px",
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: "block", color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
                    Notlar
                  </label>
                  <textarea
                    rows={2}
                    value={newReqNotes}
                    onChange={(e) => setNewReqNotes(e.target.value)}
                    placeholder="İç iletişim veya evrak referans notu"
                    style={{
                      width: "100%",
                      padding: "8px",
                      borderRadius: "6px",
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #334155",
                      fontSize: "13px",
                    }}
                  />
                </div>

                {newReqMsg && (
                  <div
                    style={{
                      padding: "8px",
                      borderRadius: "6px",
                      fontSize: "12px",
                      background: newReqMsg.includes("oluşturuldu") ? "#064e3b" : "#7f1d1d",
                      color: "#f8fafc",
                    }}
                  >
                    {newReqMsg}
                  </div>
                )}

                <button
                  type="submit"
                  className="primary"
                  disabled={newReqBusy}
                  style={{ width: "100%", padding: "10px", fontSize: "13px", fontWeight: "bold" }}
                >
                  {newReqBusy ? "Hesaplanıyor..." : "Etki Analizi Yap & Talep Oluştur"}
                </button>
              </form>
            </div>

            {/* SAĞ: KAYITLI SİLME TALEPLERİ LİSTESİ */}
            <div
              style={{
                background: "#0f172a",
                border: "1px solid #1e293b",
                borderRadius: "12px",
                padding: "20px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                <h4 style={{ margin: 0, color: "#f8fafc", fontSize: "15px" }}>
                  📋 Kayıtlı Veri Silme Talepleri ({kvkkRequests.length})
                </h4>
                <button
                  type="button"
                  className="secondary"
                  disabled={kvkkRequestsLoading}
                  onClick={() => loadKvkkRequests()}
                  style={{ padding: "4px 10px", fontSize: "12px" }}
                >
                  {kvkkRequestsLoading ? "Yenileniyor..." : "Yenile ↻"}
                </button>
              </div>

              {kvkkRequests.length === 0 ? (
                <div style={{ textAlign: "center", padding: "3rem", color: "#64748b", fontSize: "13px" }}>
                  Henüz kayıtlı bir silme talebi bulunmuyor.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  {kvkkRequests.map((req) => {
                    const impact = req.impact_summary || {};
                    const isExecuted = req.status === "executed";
                    return (
                      <div
                        key={req.id}
                        style={{
                          background: "#1e293b",
                          border: isExecuted ? "1px solid #065f46" : "1px solid #b45309",
                          borderRadius: "8px",
                          padding: "16px",
                          display: "flex",
                          flexDirection: "column",
                          gap: "10px",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                            <span
                              style={{
                                padding: "2px 8px",
                                borderRadius: "4px",
                                fontSize: "11px",
                                fontWeight: "bold",
                                background: isExecuted ? "#064e3b" : "#78350f",
                                color: isExecuted ? "#34d399" : "#fbbf24",
                              }}
                            >
                              {isExecuted ? "✓ İCRA EDİLDİ" : "⏳ BEKLEMEDE"}
                            </span>
                            <span style={{ color: "#38bdf8", fontWeight: "bold", fontSize: "13px" }}>
                              {req.identifier_type.toUpperCase()}: {req.identifier_value}
                            </span>
                            {req.requester_name && (
                              <span style={{ color: "#94a3b8", fontSize: "12px" }}>
                                ({req.requester_name})
                              </span>
                            )}
                          </div>
                          <span style={{ color: "#64748b", fontSize: "12px" }}>
                            {new Date(req.created_at).toLocaleString("tr-TR")}
                          </span>
                        </div>

                        <div style={{ fontSize: "12px", color: "#cbd5e1" }}>
                          <b>Gerekçe:</b> {req.reason}
                        </div>

                        {/* Etki / İmha Dağılımı */}
                        <div
                          style={{
                            display: "flex",
                            gap: "8px",
                            flexWrap: "wrap",
                            background: "#0f172a",
                            padding: "8px 12px",
                            borderRadius: "6px",
                            fontSize: "12px",
                            color: "#94a3b8",
                          }}
                        >
                          <span>💬 Transkript Turu: <b style={{ color: "#f8fafc" }}>{impact.turns_count ?? 0}</b></span>
                          <span>•</span>
                          <span>🎙️ Ses Kaydı: <b style={{ color: "#f8fafc" }}>{impact.audio_archives_count ?? 0}</b></span>
                          <span>•</span>
                          <span>📅 Randevu: <b style={{ color: "#f8fafc" }}>{impact.appointments_count ?? 0}</b></span>
                          <span>•</span>
                          <span>📱 WhatsApp: <b style={{ color: "#f8fafc" }}>{impact.whatsapp_messages_count ?? 0}</b></span>
                          <span>•</span>
                          <span>📊 Analitik: <b style={{ color: "#f8fafc" }}>{impact.call_analytics_count ?? 0}</b></span>
                          <span>•</span>
                          <span>TOPLAM: <b style={{ color: "#38bdf8" }}>{impact.total_records_affected ?? 0}</b></span>
                        </div>

                        {/* Butonlar */}
                        <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "4px" }}>
                          {!isExecuted ? (
                            <button
                              type="button"
                              className="primary"
                              disabled={executingReqId === req.id}
                              onClick={() => handleExecuteErasureRequest(req.id)}
                              style={{
                                background: "#dc2626",
                                borderColor: "#ef4444",
                                fontSize: "12px",
                                padding: "6px 14px",
                                fontWeight: "bold",
                              }}
                            >
                              {executingReqId === req.id ? "İcra Ediliyor..." : "🗑️ Kalıcı İcra Et & İmha Tutanağı İmzala"}
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => handleViewCertificate(req.id)}
                              style={{
                                fontSize: "12px",
                                padding: "6px 14px",
                                borderColor: "#38bdf8",
                                color: "#38bdf8",
                              }}
                            >
                              📜 İmha Tutanağını Görüntüle (SHA-256)
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* KVKK İMHA TUTANAĞI MODALI */}
      {selectedCertificate && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="KVKK İmha Tutanağı"
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.8)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "20px",
          }}
          onClick={() => setSelectedCertificate(null)}
        >
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #334155",
              borderRadius: "12px",
              padding: "24px",
              maxWidth: "760px",
              width: "100%",
              maxHeight: "85vh",
              overflowY: "auto",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <h3 style={{ margin: 0, color: "#f8fafc", fontSize: "16px" }}>
                📜 Resmi KVKK Kişisel Veri İmha ve Anonimleştirme Tutanağı
              </h3>
              <button
                type="button"
                className="secondary"
                onClick={() => setSelectedCertificate(null)}
                style={{ padding: "4px 8px", fontSize: "14px" }}
              >
                ✕
              </button>
            </div>

            <pre
              style={{
                background: "#020617",
                padding: "16px",
                borderRadius: "8px",
                overflowX: "auto",
                color: "#e2e8f0",
                fontSize: "12px",
                lineHeight: "1.6",
                fontFamily: "monospace",
                border: "1px solid #1e293b",
                whiteSpace: "pre-wrap",
              }}
            >
              {selectedCertificate.certificate_text}
            </pre>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "16px" }}>
              <span style={{ fontSize: "12px", color: "#64748b" }}>
                SHA-256: {selectedCertificate.certificate_sha256}
              </span>
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    navigator.clipboard?.writeText(selectedCertificate.certificate_text);
                    alert("İmha tutanağı panoya kopyalandı!");
                  }}
                  style={{ fontSize: "12px", padding: "6px 12px" }}
                >
                  📋 Tutanağı Kopyala
                </button>
                <button
                  type="button"
                  className="primary"
                  onClick={() => setSelectedCertificate(null)}
                  style={{ fontSize: "12px", padding: "6px 16px" }}
                >
                  Kapat
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SIP BAŞLIKLARI VE DETAY MODALI */}
      {selectedTransfer && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Aktarım detayları"
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
                aria-label="Kapat"
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
