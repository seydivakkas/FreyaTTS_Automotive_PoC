/**
 * FreyaTTS Automotive Cockpit V3 — Görüşme ve Ses Operasyon Kokpiti
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useState, useEffect, useRef } from "react";
import {
  MessageSquare,
  Car,
  Cpu,
  Clock,
  ShieldCheck,
  Zap,
  Activity,
  PhoneCall,
  PhoneOff,
  Volume2,
  RefreshCw,
  Send,
  Database,
  Download,
  History,
  Wrench,
  CheckCircle2,
  AlertCircle,
  FileText,
  UserCheck,
} from "lucide-react";
import type { Appointment, Health, Slot, Vehicle, VoiceMessage, VoiceMetrics } from "../api";
import { dash, ApiFn, RawApiFn } from "../ui";
import { AudioPipelineStepper } from "../AudioPipelineStepper";
import { LIVE_MEASURED_STAGES } from "../pipeline/types";
import { AudioPipelineInspector } from "../AudioPipelineInspector";
import { VoiceWaveformBar } from "../VoiceWaveformBar";
import { DatasetGeneratorPanel } from "../DatasetGeneratorPanel";
import { StageId, PipelineTurnState } from "../pipeline/types";
import { TabName, RolePerspective } from "../nav";
import { runF4Pipeline } from "../pipeline/f4Engine";

type Props = {
  busy: boolean;
  health: Health;
  perspective?: RolePerspective;
  appointments: Appointment[];
  vehicles: Vehicle[];
  slots?: Slot[];
  voice: {
    messages: VoiceMessage[];
    status: string;
    connected: boolean;
    partialText: string;
    transmitting: boolean;
    dialogueState?: any;
    talk: (active: boolean) => void;
    mediaStream?: MediaStream | null;
    metrics: VoiceMetrics | null;
    calibrating: boolean;
    calibrationInfo: {
      ambient_dbfs?: number;
      noise_gate_dbfs?: number;
      suppression_db?: number;
      message?: string;
    } | null;
    pipelineState?: PipelineTurnState;
    runDemoScenario?: (scenarioId: string) => void;
    stop: () => void;
    sendDtmf: (digit: string) => void;
    sendTextInput?: (text: string) => boolean;
    recalibrate?: () => void;
    interruptBargeIn?: () => void;
  };
  api?: ApiFn;
  rawApi?: RawApiFn;
  onStart: () => void;
  onNavigateToTab?: (tab: TabName) => void;
};

interface LocalTranscript {
  id: string | number;
  speaker: string;
  time: string;
  text: string;
  fxMs: string;
  isAssistant: boolean;
}

const DEFAULT_TRANSCRIPTS: LocalTranscript[] = [];

function getIntentLabel(slotIntent: string, dialogueState: string | undefined, transcriptCount: number): string {
  if (slotIntent && slotIntent !== "bekleniyor") {
    if (slotIntent === "greeting") return "Karşılama / Randevu Başlangıcı";
    if (slotIntent === "car_type") return "Araç ve Randevu Talebi";
    if (slotIntent === "slot_selection") return "Randevu Saati Belirleme";
    if (slotIntent === "confirmation") return "Randevu Teyidi / Onayı";
    if (slotIntent === "booked") return "Randevu Tamamlandı";
    if (slotIntent === "operator_transfer") return "Operatöre Aktarım Talebi";
    return slotIntent;
  }
  if (dialogueState) {
    if (dialogueState === "greeting") return "Karşılama / Randevu Başlangıcı";
    if (dialogueState === "car_type") return "Araç ve Randevu Talebi";
    if (dialogueState === "slot_selection") return "Randevu Saati Belirleme";
    if (dialogueState === "confirmation") return "Randevu Teyidi / Onayı";
    if (dialogueState === "booked") return "Randevu Tamamlandı";
    return dialogueState;
  }
  return transcriptCount > 0 ? "Müşteri Talebi Dinleniyor..." : "Görüşme Bekleniyor";
}

function getActionPlan(dialogueState: string | undefined, plate: string, saat: string, transcriptCount: number): string {
  if (dialogueState === "booked") {
    return "Randevu Veritabanına Yazıldı, Referans İletildi";
  }
  if (dialogueState === "confirmation") {
    return "Teyit Özeti Okundu, Müşteriden Açık Onay Bekleniyor";
  }
  if (dialogueState === "slot_selection" || saat !== "—") {
    return "Saat Belirlendi, Plaka ve Müşteri Özeti Çıkarılıyor";
  }
  if (dialogueState === "car_type" || plate !== "—") {
    return "Araç Bilgisi Alındı, Müsait Saat Seçenekleri Sunulacak";
  }
  return transcriptCount > 0 ? "Araç Marka/Model ve Randevu Saati Dinleniyor" : "Görüşme Başlatılması Bekleniyor";
}

export function VoiceTab({
  busy,
  health,
  perspective = "operator",
  appointments,
  vehicles,
  slots = [],
  voice,
  api,
  rawApi,
  onStart,
  onNavigateToTab,
}: Props) {
  const {
    messages,
    status,
    connected,
    metrics,
    calibrating,
    calibrationInfo,
    pipelineState,
    runDemoScenario,
    stop,
    sendDtmf,
    sendTextInput,
    recalibrate,
  } = voice;

  const [selectedStage, setSelectedStage] = useState<StageId | null>(null);
  const [showEngineerDetails, setShowEngineerDetails] = useState(false);
  const [callSeconds, setCallSeconds] = useState(0);
  const [sessionId] = useState(() => "cockpit-" + Math.random().toString(36).substring(2, 10));
  const [transcripts, setTranscripts] = useState<LocalTranscript[]>(DEFAULT_TRANSCRIPTS);
  const [chatInputText, setChatInputText] = useState("");
  const [isLlmLoading, setIsLlmLoading] = useState(false);

  const [detectedSlotInfo, setDetectedSlotInfo] = useState({
    intent: "bekleniyor",
    plaka: "—",
    islem: [] as string[],
    fiyat_kilitli: "—",
    atanan_lift: "—",
    saat: "—",
  });

  // Caller Memory (Kullanıcı & Görüşme Hafızası) Durumu
  const [callerProfile, setCallerProfile] = useState<{
    name: string;
    phone: string;
    plate: string;
    vehicle_model: string;
    warranty_status: "active" | "expired" | "void" | "unknown";
    warranty_expires_at: string;
    notes: string;
    maintenance_history: Array<{
      date: string;
      km?: number;
      item: string;
      notes?: string;
    }>;
  }>({
    name: "",
    phone: "",
    plate: "",
    vehicle_model: "",
    warranty_status: "unknown",
    warranty_expires_at: "",
    notes: "",
    maintenance_history: [],
  });

  const chatFeedRef = useRef<HTMLDivElement | null>(null);

  // Call timer when connected
  useEffect(() => {
    if (!connected) return;
    const interval = setInterval(() => {
      setCallSeconds((s) => s + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [connected]);

  // Perspective değiştiğinde mühendis görünümü için detayları otomatik aç
  useEffect(() => {
    if (perspective === "engineer") {
      setShowEngineerDetails(true);
    }
  }, [perspective]);

  // WebSocket canlı oturumundan gelen diyalog durumunu ve çıkarılan parametreleri anlık senkronize et
  useEffect(() => {
    if (voice.dialogueState) {
      const ds = voice.dialogueState;
      setDetectedSlotInfo((prev) => ({
        ...prev,
        ...(ds.plate ? { plaka: ds.plate } : {}),
        ...(ds.state ? { intent: ds.state } : {}),
        ...(ds.slot_time ? { saat: ds.slot_time } : {}),
        ...(ds.price ? { fiyat_kilitli: ds.price } : {}),
        ...(ds.reference_code ? { referans: ds.reference_code } : {}),
      }));
      if (ds.plate || ds.customer || ds.vehicle) {
        setCallerProfile((prev) => ({
          ...prev,
          ...(ds.plate ? { plate: ds.plate } : {}),
          ...(ds.customer ? { name: ds.customer } : {}),
          ...(ds.vehicle ? { vehicle_model: ds.vehicle } : {}),
        }));
      }
    }
  }, [voice.dialogueState]);

  // Sync incoming real messages from WebSocket voice session
  useEffect(() => {
    if (messages.length > 0) {
      const nowStr = new Date().toLocaleTimeString("tr-TR", { hour12: false });
      const mapped: LocalTranscript[] = messages.map((m, idx) => ({
        id: `msg_${idx}`,
        speaker: m.role === "assistant" ? "Leyla (FreyaTTS)" : "Müşteri (Canlı Ses)",
        time: nowStr,
        text: m.text,
        fxMs:
          m.role === "assistant"
            ? `TTFA: ${metrics?.first_audio_ms ? `${Math.round(metrics.first_audio_ms)}ms` : "—"} | F5: ${metrics?.tts_ms ? `${Math.round(metrics.tts_ms)}ms` : "—"}`
            : `ASR: ${metrics?.stt_ms ? `${Math.round(metrics.stt_ms)}ms` : "—"}`,
        isAssistant: m.role === "assistant",
      }));
      setTranscripts(mapped);
    }
  }, [messages, metrics]);

  // Auto scroll chat feed to bottom
  useEffect(() => {
    if (chatFeedRef.current) {
      chatFeedRef.current.scrollTop = chatFeedRef.current.scrollHeight;
    }
  }, [transcripts]);

  const fallbackPipelineState: PipelineTurnState = pipelineState || {
    turnId: 1,
    sessionId: "active-call",
    source: health.demo_mode ? "demo" : "live",
    activeStage: null,
    totalDurationMs: null,
    stages: {
      F0: { stage: "F0", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F1: { stage: "F1", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F2: { stage: "F2", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F3: { stage: "F3", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F4: { stage: "F4", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F5: { stage: "F5", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F6: { stage: "F6", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
    },
    traces: [],
  };

  const isSpeaking = status === "Konuşuyor" || status === "synthesizing";

  const formatCallDuration = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  // Gerçek LLM Çıkarımı ve Müşteri Mesajı İşleme Fonksiyonu (Qwen2.5 + Leyla Sentez)
  const preview = useRef<HTMLAudioElement | null>(null);
  const generation = useRef(0);
  function stopPreview() {
    generation.current++;
    const audio = preview.current;
    if (audio) {
      audio.pause();
      URL.revokeObjectURL(audio.src);
      preview.current = null;
    }
  }
  useEffect(() => stopPreview, []);
  const handleCustomerQuery = async (queryText: string) => {
    const text = queryText.trim();
    if (!text || isLlmLoading) return;
    stopPreview();
    const turn = generation.current;

    const nowStr = new Date().toLocaleTimeString("tr-TR", { hour12: false });

    const custMsg: LocalTranscript = {
      id: `cust_${Date.now()}`,
      speaker: callerProfile.name ? `Müşteri (${callerProfile.name})` : "Müşteri",
      time: nowStr,
      text: text,
      fxMs: "Metin Girişi",
      isAssistant: false,
    };

    setTranscripts((prev) => [...prev, custMsg]);
    setChatInputText("");

    // 1. Eğer canlı ses oturumu açıksa, metni WebSocket üzerinden oturuma ilet
    if (connected && sendTextInput) {
      const sent = sendTextInput(text);
      if (sent) return;
    }

    // 2. Canlı WebSocket kapalıysa, arka plandaki gerçek Ollama Qwen2.5 LLM servisini çağır
    setIsLlmLoading(true);
    let leylaReply = "";
    let llmDurationMs = 175;

    try {
      if (api) {
        const res = await api("voice/chat-turn", "POST", {
          text,
          session_id: sessionId,
        });
        if (res && res.reply) {
          leylaReply = res.reply;
          if (res.metrics?.llm_total_ms) llmDurationMs = Math.round(res.metrics.llm_total_ms);
          if (res.slot_info) {
            setDetectedSlotInfo((prev) => ({
              ...prev,
              ...res.slot_info,
            }));
          }
          if (res.customer) {
            setCallerProfile((prev) => ({ ...prev, name: res.customer }));
          }
          if (res.plate) {
            setCallerProfile((prev) => ({ ...prev, plate: res.plate }));
          }
          if (res.vehicle) {
            setCallerProfile((prev) => ({ ...prev, vehicle_model: res.vehicle }));
          }
        }
      }
    } catch (err) {
      console.warn("Backend LLM endpoint hatası:", err);
    } finally {
      setIsLlmLoading(false);
    }

    if (!leylaReply) {
      leylaReply =
        "Diyalog servisinden yanıt alınamadı. Lütfen sistem durumunu ve bağlantıyı kontrol edin.";
    }

    const leylaMsg: LocalTranscript = {
      id: `leyla_${Date.now() + 1}`,
      speaker: "Leyla (FreyaTTS)",
      time: new Date().toLocaleTimeString("tr-TR", { hour12: false }),
      text: leylaReply,
      fxMs: `F3 LLM: ${llmDurationMs}ms`,
      isAssistant: true,
    };

    setTranscripts((prev) => [...prev, leylaMsg]);

    // FreyaTTS-small (CUDA) üzerinden gerçek nöral ses sentezi:
    if (connected && voice.sendTextInput) {
      // Canlı WebSocket görüşmesi açıksa, mesaj doğrudan oturuma gönderilir ve FreyaTTS PCM akışı döner
      voice.sendTextInput(text);
    } else if (rawApi && leylaReply) {
      // Bağımsız testte FreyaTTS modelinden WAV sesini al ve çal (sıfır Web Speech API)
      try {
        const resp = await rawApi("synthesize", "POST", { text: leylaReply });
        const blob = await resp.blob();
        if (generation.current !== turn) return;
        const audioUrl = URL.createObjectURL(blob);
        const audio = new Audio(audioUrl);
        preview.current = audio;
        audio.onended = () => { if (preview.current === audio) stopPreview(); };
        audio.play().catch((e) => console.warn("FreyaTTS ses oynatma hatası:", e));
      } catch (err) {
        console.warn("FreyaTTS sentez API hatası:", err);
      }
    }
  };

  const primaryVehicle = vehicles[0];
  const currentPlate = callerProfile.plate || voice.dialogueState?.plate || (detectedSlotInfo.plaka !== "—" ? detectedSlotInfo.plaka : "—");
  const appointmentId = voice.dialogueState?.appointment_id || (detectedSlotInfo as any).referans;
  const currentRef = appointmentId
    ? (appointmentId.startsWith("FRY-") ? appointmentId : `FRY-${appointmentId.slice(0, 6).toUpperCase()}`)
    : "— (Onay Sonrası)";
  const isTransferNeeded = Boolean(
    voice.dialogueState?.transfer_requested ||
    detectedSlotInfo.intent === "operator_transfer"
  );
  let activeAcceptanceRunId = "";
  try {
    activeAcceptanceRunId = localStorage.getItem("freya_active_acceptance_run_id") || "";
  } catch {}

  return (
    <div className="cockpit-view-container">
      {/* Aktif Kabul Koşusu Bilgilendirmesi */}
      {activeAcceptanceRunId && (
        <div
          role="status"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "8px",
            padding: "6px 12px",
            background: "rgba(56, 189, 248, 0.14)",
            border: "1px solid rgba(56, 189, 248, 0.35)",
            borderRadius: "8px",
            color: "#bae6fd",
            fontSize: "12px",
            flexShrink: 0,
          }}
        >
          <span>
            🎙️ <b>Aktif Kabul Koşusu Kaydediliyor:</b>{" "}
            <code style={{ fontFamily: "monospace" }}>{activeAcceptanceRunId}</code>
          </span>
          {onNavigateToTab && (
            <button
              type="button"
              onClick={() => onNavigateToTab("Kabul & Terim")}
              style={{
                padding: "4px 10px",
                fontSize: "11px",
                fontWeight: 700,
                background: "#0284c7",
                color: "#fff",
                border: "none",
                borderRadius: "5px",
                cursor: "pointer",
              }}
            >
              ✅ Koşuyu Değerlendir / Kapat →
            </button>
          )}
        </div>
      )}
      {/* İlk Randevu Ön Koşul Uyarısı (Eğer araç veya slot henüz yoksa) */}
      {(!primaryVehicle || slots.length === 0) && (
        <div
          role="status"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "8px",
            padding: "8px 12px",
            background: "rgba(245, 158, 11, 0.12)",
            border: "1px solid rgba(245, 158, 11, 0.3)",
            borderRadius: "8px",
            color: "#fef3c7",
            fontSize: "12px",
            flexShrink: 0,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0" />
            <span>
              {!primaryVehicle
                ? "Henüz tanımlı araç yok. Randevu oluşturulabilmesi için araç modeli gereklidir."
                : "Henüz takvimde müsait saat yok. Asistanın randevu verebilmesi için slot tanımlayın."}
            </span>
          </div>
          <div style={{ display: "flex", gap: "6px" }}>
            {!primaryVehicle && onNavigateToTab && (
              <button
                type="button"
                className="secondary"
                style={{ fontSize: "11px", padding: "3px 8px" }}
                onClick={() => onNavigateToTab("Araçlar ve fiyatlar")}
              >
                Araç Tanımla →
              </button>
            )}
            {slots.length === 0 && onNavigateToTab && (
              <button
                type="button"
                className="secondary"
                style={{ fontSize: "11px", padding: "3px 8px" }}
                onClick={() => onNavigateToTab("Randevular")}
              >
                Müsait Saat Ekle →
              </button>
            )}
          </div>
        </div>
      )}

      {/* Sleek Top Call Control & Waveform Bar (~38px height) */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "8px",
          padding: "4px 10px",
          background: "rgba(15, 23, 42, 0.9)",
          border: "1px solid rgba(255, 255, 255, 0.08)",
          borderRadius: "8px",
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <button
            type="button"
            onClick={connected ? stop : () => { stopPreview(); onStart(); }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "5px 14px",
              borderRadius: "6px",
              fontWeight: 700,
              fontSize: "12px",
              background: connected ? "#e11d48" : "#059669",
              color: "#ffffff",
              border: "none",
              cursor: "pointer",
              boxShadow: connected ? "0 0 10px rgba(225, 29, 72, 0.4)" : "0 0 10px rgba(5, 150, 105, 0.4)",
            }}
          >
            {connected ? <PhoneOff className="w-3.5 h-3.5" /> : <PhoneCall className="w-3.5 h-3.5" />}
            <span>{connected ? "Görüşmeyi Bitir" : "Görüşmeyi Başlat"}</span>
          </button>

          {connected && voice.mediaStream && <div>
            <button type="button" style={{touchAction:"none"}} aria-pressed={voice.transmitting}
              onPointerDown={e => { e.currentTarget.setPointerCapture(e.pointerId); voice.talk(true); }}
              onPointerUp={() => voice.talk(false)} onLostPointerCapture={() => voice.talk(false)}>
              {voice.transmitting ? "Mikrofon açık" : "Basılı tut ve konuş"}
            </button>
            <small> {voice.mediaStream.getAudioTracks()[0]?.label} · Boşluk tuşuyla da konuşabilirsiniz</small>
          </div>}
          <span
            style={{
              fontSize: "11px",
              fontFamily: "monospace",
              color: connected ? "#34d399" : "#94a3b8",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <span
              style={{
                width: "7px",
                height: "7px",
                borderRadius: "50%",
                background: connected ? (health.telephony?.simulated ? "#fbbf24" : "#34d399") : "#64748b",
                boxShadow: connected ? `0 0 8px ${health.telephony?.simulated ? "#fbbf24" : "#34d399"}` : "none",
              }}
            />
            {connected ? (
              <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
                <span>SIP/6001 • {formatCallDuration(callSeconds)}</span>
                {health.telephony?.simulated && (
                  <span
                    style={{
                      fontSize: "9px",
                      padding: "1px 5px",
                      borderRadius: "3px",
                      background: "rgba(245, 158, 11, 0.2)",
                      color: "#fbbf24",
                      border: "1px solid rgba(245, 158, 11, 0.4)",
                      fontWeight: 700,
                    }}
                    title="Fiziksel Asterisk PBX bağlı değil; Mock AMI ve Web Audio simülasyonu devrede."
                  >
                    SİMÜLASYON
                  </span>
                )}
              </span>
            ) : (
              `Durum: ${status}`
            )}
          </span>
        </div>

        {/* Center: Passive Waveform Visualizer */}
        <VoiceWaveformBar
          isConnected={connected}
          isSpeaking={isSpeaking}
          mediaStream={voice.mediaStream}
        />

        {/* Right: Telemetry & Engineering Drawer Toggle */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {metrics?.stt_ms !== undefined && metrics?.stt_ms !== null && (
            <span
              style={{
                fontSize: "10.5px",
                fontFamily: "monospace",
                background: "rgba(30, 41, 59, 0.7)",
                padding: "3px 8px",
                borderRadius: "4px",
                color: "#a78bfa",
                border: "1px solid rgba(167, 139, 250, 0.2)",
              }}
              title="ASR Faster-Whisper Transkripsiyon Gecikmesi"
            >
              F2 ASR: <b>{Math.round(metrics.stt_ms)}ms</b>
            </span>
          )}

          {metrics?.llm_total_ms !== undefined && metrics?.llm_total_ms !== null && (
            <span
              style={{
                fontSize: "10.5px",
                fontFamily: "monospace",
                background: "rgba(30, 41, 59, 0.7)",
                padding: "3px 8px",
                borderRadius: "4px",
                color: "#34d399",
                border: "1px solid rgba(52, 211, 153, 0.2)",
              }}
              title="Diyalog Durum Makinesi & LLM Çıkarım Gecikmesi"
            >
              F3 LLM: <b>{Math.round(metrics.llm_total_ms)}ms</b>
            </span>
          )}

          <span
            style={{
              fontSize: "10.5px",
              fontFamily: "monospace",
              background: "rgba(30, 41, 59, 0.7)",
              padding: "3px 8px",
              borderRadius: "4px",
              color: "#fbbf24",
              border: "1px solid rgba(251, 191, 36, 0.2)",
            }}
            title="E2E İlk Ses Gecikmesi (Time to First Audio)"
          >
            TTFA: <b>{metrics?.first_audio_ms ? `${Math.round(metrics.first_audio_ms)}ms` : "—"}</b>
          </span>

          <span
            style={{
              fontSize: "10.5px",
              fontFamily: "monospace",
              background: "rgba(30, 41, 59, 0.7)",
              padding: "3px 8px",
              borderRadius: "4px",
              color: "#38bdf8",
              border: "1px solid rgba(56, 189, 248, 0.2)",
            }}
            title="FreyaTTS Neural Audio Synthesizer Gecikmesi"
          >
            F5 ODE: <b>{metrics?.tts_ms ? `${Math.round(metrics.tts_ms)}ms` : "—"}</b>
          </span>

          <button
            type="button"
            onClick={() => setShowEngineerDetails((prev) => !prev)}
            style={{
              padding: "3px 10px",
              fontSize: "10.5px",
              background: showEngineerDetails ? "#1e293b" : "transparent",
              color: showEngineerDetails ? "#38bdf8" : "#94a3b8",
              border: "1px solid #334155",
              borderRadius: "4px",
              cursor: "pointer",
            }}
            title="F0-F6 Mühendislik Boru Hattını ve Detaylı Telemetriyi Aç/Kapat"
          >
            🛠️ F0–F6 Detay {showEngineerDetails ? "▲" : "▼"}
          </button>
        </div>
      </div>

      {/* İsteğe Bağlı Açılan F0–F6 Mühendislik Hattı (Varsayılan: Gizli) */}
      {showEngineerDetails && (
        <div style={{ flexShrink: 0, marginBottom: "4px" }}>
          <AudioPipelineStepper
            pipelineState={fallbackPipelineState}
            selectedStage={selectedStage}
            onSelectStage={(stage) => setSelectedStage((prev) => (prev === stage ? null : stage))}
            onRunDemoScenario={runDemoScenario}
            isStreaming={connected}
          />
        </div>
      )}

      {/* İKİ SÜTUNLU ANA KOKPİT GÖRÜNÜMÜ: Sol (Canlı Akış + Metin Girişi) + Sağ (Müşteri & Slot) */}
      <div className="cockpit-main-grid" style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        {/* SOL 2 SÜTUN: Canlı Diyalog & Transkript Akışı (Tam Yükseklik) */}
        <div className="cockpit-chat-card" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          <div className="cockpit-chat-header" style={{ flexShrink: 0 }}>
            <span className="cockpit-chat-title">
              <MessageSquare className="w-4 h-4 text-emerald-400" />
              CANLI GÖRÜŞME AKIŞI (STREAMING ASR F₂ & FREYATTS LEYLA F₅)
            </span>
            <span className="cockpit-chat-channel">
              {connected || isSpeaking
                ? `Kanal: SIP/6001 (${health.telephony?.simulated ? "WebRTC Simülasyonu" : "PJSIP Canlı Hat"}) • Ses Sentezi: Leyla Kadın Sesi #9`
                : `Santral: ${health.telephony?.simulated ? "Simülasyon Modu (Fiziksel PBX Yok)" : "Hazır (Metin ve Ses Destekli)"}`}
            </span>
          </div>

          {connected && voice.partialText && <div role="status" className="cockpit-msg-bubble customer">
            <small>Canlı yazım</small><div>{voice.partialText}</div>
          </div>}
          <div className="cockpit-chat-feed" ref={chatFeedRef} style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
            {transcripts.map((msg) => (
              <div
                key={msg.id}
                className={`cockpit-msg-bubble ${msg.isAssistant ? "leyla" : "customer"}`}
              >
                <div className="cockpit-msg-top">
                  <span
                    className={
                      msg.isAssistant
                        ? "cockpit-msg-speaker-leyla"
                        : "cockpit-msg-speaker-customer"
                    }
                  >
                    {msg.speaker}
                  </span>
                  <span className="cockpit-msg-meta">
                    {msg.time} • {msg.fxMs}
                  </span>
                </div>
                <p className="cockpit-msg-text">{msg.text}</p>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "6px", flexShrink: 0, marginTop: "6px" }}>
            {/* Hızlı Müşteri Sorusu Simülasyon Çipleri */}
            <div className="cockpit-quick-chips">
              <span className="cockpit-chips-label">Hızlı Müşteri Sorusu Simüle Et:</span>
              <div className="cockpit-chips-list">
                {[
                  "Fren balatası değişimi ne kadar sürer?",
                  "Aracım P0300 hatası veriyor, yürütmeli miyim?",
                  "Ekspertiz randevusu almak istiyorum",
                  "Yarın saat 10:00 için randevuyu onaylıyorum",
                ].map((sample, idx) => (
                  <button
                    key={idx}
                    type="button"
                    disabled={isLlmLoading} onClick={() => handleCustomerQuery(sample)}
                    className="cockpit-chip-btn"
                  >
                    "{sample}"
                  </button>
                ))}
              </div>
            </div>

            {/* Canlı Görüşme Akışı Doğrudan Metin Girişi Formu */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleCustomerQuery(chatInputText);
              }}
              className="cockpit-chat-input-form"
            >
              <input
                type="text"
                value={chatInputText}
                onChange={(e) => setChatInputText(e.target.value)}
                placeholder="Müşteri mesajını buraya yazın (Örn: Yarın 10:00 Corolla için ekspertiz randevusu almak istiyorum)..."
                className="cockpit-chat-input-field"
                disabled={isLlmLoading}
              />
              <button
                type="submit"
                disabled={!chatInputText.trim() || isLlmLoading}
                className="cockpit-chat-send-btn"
              >
                {isLlmLoading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
                <span>{isLlmLoading ? "LLM Çıkarımı..." : "Gönder"}</span>
              </button>
            </form>
          </div>
        </div>

        {/* SAĞ SÜTUN: 5 Temel İşlem Sorusu, Caller Memory, DTMF & Mühendislik Çekmecesi */}
        <div className="cockpit-sidebar-col">
          {/* Kart 1: 5 TEMEL İŞLEM SORUSU (OPERATÖR ODAĞI) */}
          <div className="cockpit-card" style={{ border: "1px solid rgba(56, 189, 248, 0.3)", background: "rgba(15, 23, 42, 0.95)" }}>
            <div className="cockpit-card-header" style={{ borderBottom: "1px solid rgba(56, 189, 248, 0.2)" }}>
              <span className="cockpit-card-title" style={{ color: "#38bdf8", display: "flex", alignItems: "center", gap: "6px" }}>
                <CheckCircle2 className="w-4 h-4 text-sky-400" />
                5 TEMEL İŞLEM SORUSU (OPERATÖR ODAĞI)
              </span>
              <span
                style={{
                  fontSize: "9.5px",
                  fontWeight: 700,
                  padding: "2px 6px",
                  borderRadius: "4px",
                  background: health.demo_mode ? "rgba(245, 158, 11, 0.2)" : "rgba(16, 185, 129, 0.2)",
                  color: health.demo_mode ? "#fbbf24" : "#34d399",
                  border: `1px solid ${health.demo_mode ? "rgba(245, 158, 11, 0.4)" : "rgba(16, 185, 129, 0.4)"}`,
                }}
              >
                {health.demo_mode ? "DEMO" : "CANLI CRM"}
              </span>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "9px", marginTop: "2px" }}>
              {/* Soru 1: Kim Arıyor? */}
              <div style={{ background: "rgba(30, 41, 59, 0.45)", borderRadius: "6px", padding: "8px 10px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "3px" }}>
                  <span style={{ fontSize: "11px", fontWeight: 700, color: "#94a3b8", display: "flex", alignItems: "center", gap: "5px" }}>
                    <span style={{ background: "#0284c7", color: "#fff", width: "16px", height: "16px", borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: "10px" }}>1</span>
                    KİM ARIYOR?
                  </span>
                  <span style={{ fontSize: "10px", color: callerProfile.name ? "#34d399" : "#94a3b8" }}>
                    {callerProfile.name ? "● Doğrulandı" : "○ Bilgi Bekleniyor"}
                  </span>
                </div>
                <div style={{ fontSize: "13px", fontWeight: 700, color: callerProfile.name ? "#f8fafc" : "#94a3b8" }}>
                  {callerProfile.name || voice.dialogueState?.customer || "Henüz Doğrulanmadı"}
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                  <span>Tel: {callerProfile.phone || (connected ? "Dahili / SIP Arayan" : "—")}</span>
                  <span>{callerProfile.warranty_status === "active" ? "🛡️ Garanti Aktif" : "👤 Müşteri"}</span>
                </div>
              </div>

              {/* Soru 2: Ne İstiyor? */}
              <div style={{ background: "rgba(30, 41, 59, 0.45)", borderRadius: "6px", padding: "8px 10px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "3px" }}>
                  <span style={{ fontSize: "11px", fontWeight: 700, color: "#94a3b8", display: "flex", alignItems: "center", gap: "5px" }}>
                    <span style={{ background: "#0284c7", color: "#fff", width: "16px", height: "16px", borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: "10px" }}>2</span>
                    NE İSTİYOR?
                  </span>
                  <span style={{ fontSize: "10px", color: "#38bdf8" }}>Niyet (F₃)</span>
                </div>
                <div style={{ fontSize: "12.5px", fontWeight: 600, color: "#f8fafc" }}>
                  {getIntentLabel(detectedSlotInfo.intent, voice.dialogueState?.state, transcripts.length)}
                </div>
                <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "2px" }}>
                  Talep: {detectedSlotInfo.islem.length > 0 ? detectedSlotInfo.islem.join(", ") : "Otomotiv Ekspertiz Randevusu"}
                </div>
              </div>

              {/* Soru 3: Sistem Ne Anladı? */}
              <div style={{ background: "rgba(30, 41, 59, 0.45)", borderRadius: "6px", padding: "8px 10px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "3px" }}>
                  <span style={{ fontSize: "11px", fontWeight: 700, color: "#94a3b8", display: "flex", alignItems: "center", gap: "5px" }}>
                    <span style={{ background: "#0284c7", color: "#fff", width: "16px", height: "16px", borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: "10px" }}>3</span>
                    SİSTEM NE ANLADI?
                  </span>
                  <span style={{ fontSize: "10px", color: currentPlate !== "—" ? "#34d399" : "#94a3b8" }}>
                    {currentPlate !== "—" ? "● Plaka Yakalandı" : "○ Parametreler"}
                  </span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginTop: "4px" }}>
                  <div>
                    <div style={{ fontSize: "10px", color: "#94a3b8" }}>ARAÇ</div>
                    <div style={{ fontSize: "12px", fontWeight: 600, color: "#7dd3fc" }}>
                      {callerProfile.vehicle_model || voice.dialogueState?.vehicle || "—"}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: "10px", color: "#94a3b8" }}>PLAKA</div>
                    <div style={{ fontSize: "12px", fontWeight: 700, color: "#fbbf24", fontFamily: "monospace" }}>
                      {currentPlate}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: "10px", color: "#94a3b8" }}>RANDEVU SAATİ</div>
                    <div style={{ fontSize: "12px", fontWeight: 600, color: "#e2e8f0" }}>
                      {detectedSlotInfo.saat !== "—" ? detectedSlotInfo.saat : (voice.dialogueState?.slot_id ? "Slot belirlendi" : "—")}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: "10px", color: "#94a3b8" }}>LİFT / İSTASYON</div>
                    <div style={{ fontSize: "12px", fontWeight: 600, color: "#cbd5e1" }}>
                      {detectedSlotInfo.atanan_lift}
                    </div>
                  </div>
                </div>
              </div>

              {/* Soru 4: Hangi İşlemi Yapacak? */}
              <div style={{ background: "rgba(30, 41, 59, 0.45)", borderRadius: "6px", padding: "8px 10px", border: "1px solid rgba(255, 255, 255, 0.05)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "3px" }}>
                  <span style={{ fontSize: "11px", fontWeight: 700, color: "#94a3b8", display: "flex", alignItems: "center", gap: "5px" }}>
                    <span style={{ background: "#0284c7", color: "#fff", width: "16px", height: "16px", borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: "10px" }}>4</span>
                    HANGİ İŞLEMİ YAPACAK?
                  </span>
                  <span style={{ fontSize: "10px", color: "#a855f7" }}>Aksiyon Planı</span>
                </div>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "#c084fc" }}>
                  {getActionPlan(voice.dialogueState?.state, currentPlate, detectedSlotInfo.saat, transcripts.length)}
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#94a3b8", marginTop: "4px" }}>
                  <span>Fiyat: <b style={{ color: "#34d399" }}>{detectedSlotInfo.fiyat_kilitli}</b></span>
                  <span>Ref: <b style={{ color: "#38bdf8", fontFamily: "monospace" }}>{currentRef}</b></span>
                </div>
              </div>

              {/* Soru 5: İnsan Müdahalesi Gerekiyor mu? */}
              <div style={{ background: isTransferNeeded ? "rgba(239, 68, 68, 0.15)" : "rgba(16, 185, 129, 0.1)", borderRadius: "6px", padding: "10px", border: `1px solid ${isTransferNeeded ? "rgba(239, 68, 68, 0.4)" : "rgba(16, 185, 129, 0.3)"}` }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                  <span style={{ fontSize: "11px", fontWeight: 700, color: isTransferNeeded ? "#f87171" : "#34d399", display: "flex", alignItems: "center", gap: "5px" }}>
                    <span style={{ background: isTransferNeeded ? "#ef4444" : "#10b981", color: "#fff", width: "16px", height: "16px", borderRadius: "50%", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: "10px" }}>5</span>
                    İNSAN MÜDAHALESİ GEREKİYOR MU?
                  </span>
                  <span style={{ fontSize: "10px", fontWeight: 700, color: isTransferNeeded ? "#f87171" : "#34d399" }}>
                    {isTransferNeeded ? "⚠️ GEREKİYOR" : "✓ GEREKMİYOR"}
                  </span>
                </div>
                <div style={{ fontSize: "11px", color: "#e2e8f0", marginBottom: "8px" }}>
                  {isTransferNeeded
                    ? "Müşteri operatör aktarımı talep etti veya asistan belirsizliğe düştü. Çağrıyı devralmanız önerilir."
                    : "Asistan otomotiv diyalog akışını kurallar dahilinde güvenle yönetiyor."}
                </div>
                {/* Hızlı Müdahale Butonları */}
                <div style={{ display: "flex", gap: "6px" }}>
                  <button
                    type="button"
                    onClick={() => {
                      if (onNavigateToTab) onNavigateToTab("Operatör (6002)");
                    }}
                    style={{
                      flex: 1,
                      padding: "6px 8px",
                      fontSize: "11px",
                      fontWeight: 700,
                      background: isTransferNeeded ? "#ef4444" : "#3b82f6",
                      color: "#ffffff",
                      border: "none",
                      borderRadius: "5px",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "4px",
                    }}
                    title="Operatör Masasına (Dahili 6002) aktar"
                  >
                    <PhoneCall className="w-3.5 h-3.5" />
                    <span>Dahili 6002'ye Aktar</span>
                  </button>
                  {connected && (
                    <button
                      type="button"
                      onClick={() => voice.interruptBargeIn?.()}
                      style={{
                        padding: "6px 10px",
                        fontSize: "11px",
                        fontWeight: 600,
                        background: "#334155",
                        color: "#f8fafc",
                        border: "1px solid #475569",
                        borderRadius: "5px",
                        cursor: "pointer",
                      }}
                      title="Asistanın sesini anında kes (Barge-In)"
                    >
                      Sustur
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Kart 2: Kullanıcı & Görüşme Hafıza Kartı (Caller Memory Card) */}
          <div className="cockpit-card">
            <div className="cockpit-card-header">
              <span className="cockpit-card-title">
                <UserCheck className="w-4 h-4 text-sky-400" />
                Kullanıcı & Görüşme Hafızası (Caller Memory)
              </span>
              <span className="cockpit-badge-plate">
                {currentPlate}
              </span>
            </div>
            <div className="cockpit-info-rows">
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Aktif Profil:</span>
                <span className="cockpit-info-val" style={{ color: "#38bdf8", fontWeight: 600 }}>
                  {callerProfile.name || "Henüz doğrulanmadı"}
                </span>
              </div>
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Telefon Numarası:</span>
                <span className="cockpit-info-val" style={{ fontFamily: "monospace" }}>
                  {callerProfile.phone || "—"}
                </span>
              </div>
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Araç Plakası:</span>
                <span className="cockpit-info-val" style={{ fontFamily: "monospace", color: "#fbbf24" }}>
                  {callerProfile.plate || "—"}
                </span>
              </div>
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Araç Modeli:</span>
                <span className="cockpit-info-val" style={{ color: "#7dd3fc", fontFamily: "monospace" }}>
                  {callerProfile.vehicle_model || "—"}
                </span>
              </div>
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Garanti Durumu:</span>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "4px",
                    padding: "2px 8px",
                    borderRadius: "4px",
                    fontSize: "11px",
                    fontWeight: 600,
                    background:
                      callerProfile.warranty_status === "active"
                        ? "rgba(16, 185, 129, 0.2)"
                        : callerProfile.warranty_status === "expired"
                        ? "rgba(244, 63, 94, 0.2)"
                        : "rgba(148, 163, 184, 0.2)",
                    color:
                      callerProfile.warranty_status === "active"
                        ? "#34d399"
                        : callerProfile.warranty_status === "expired"
                        ? "#fb7185"
                        : "#94a3b8",
                    border:
                      callerProfile.warranty_status === "active"
                        ? "1px solid rgba(16, 185, 129, 0.4)"
                        : callerProfile.warranty_status === "expired"
                        ? "1px solid rgba(244, 63, 94, 0.4)"
                        : "1px solid rgba(148, 163, 184, 0.4)",
                  }}
                >
                  <ShieldCheck className="w-3 h-3" />
                  {callerProfile.warranty_status === "active"
                    ? `Aktif (${callerProfile.warranty_expires_at || "—"})`
                    : callerProfile.warranty_status === "expired"
                    ? `Sona Erdi (${callerProfile.warranty_expires_at || "—"})`
                    : "Bilinmiyor"}
                </span>
              </div>
            </div>

            {/* Geçmiş Bakım Kayıtları */}
            <div style={{ marginTop: "8px", borderTop: "1px solid rgba(255, 255, 255, 0.08)", paddingTop: "8px" }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  fontSize: "11px",
                  fontWeight: 600,
                  color: "#cbd5e1",
                  marginBottom: "6px",
                }}
              >
                <History className="w-3.5 h-3.5 text-amber-400" />
                <span>Geçmiş Bakım Kayıtları ({callerProfile.maintenance_history.length})</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
                {callerProfile.maintenance_history.length === 0 ? (
                  <span style={{ color: "#64748b", fontSize: "11px", fontStyle: "italic", padding: "4px 0" }}>
                    Henüz doğrulanmış geçmiş kayıt bulunmuyor.
                  </span>
                ) : (
                  callerProfile.maintenance_history.map((item, idx) => (
                  <div
                    key={idx}
                    style={{
                      background: "rgba(30, 41, 59, 0.5)",
                      borderRadius: "4px",
                      padding: "5px 8px",
                      border: "1px solid rgba(255, 255, 255, 0.04)",
                      fontSize: "11px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", color: "#94a3b8", marginBottom: "2px" }}>
                      <span style={{ fontWeight: 600, color: "#e2e8f0" }}>{item.item}</span>
                      <span style={{ fontFamily: "monospace", color: "#38bdf8" }}>{item.date}</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", color: "#64748b", fontSize: "10px" }}>
                      <span>{item.notes}</span>
                      {item.km && <span style={{ fontFamily: "monospace" }}>{item.km.toLocaleString("tr-TR")} km</span>}
                    </div>
                  </div>
                )))}
              </div>
            </div>
          </div>

          {/* Kart 3: DTMF Tuş Takımı (Canlı SIP / AudioSocket) */}
          {connected && (
            <div className="cockpit-card">
              <div className="cockpit-card-header">
                <span className="cockpit-card-title">
                  <PhoneCall className="w-4 h-4 text-emerald-400" />
                  📞 DTMF Tuş Takımı (Sıfır Gecikme)
                </span>
              </div>
              <div className="cockpit-dtmf-grid">
                {["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"].map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => sendDtmf(d)}
                    className="cockpit-dtmf-btn"
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Kart 4: Son Tur Gecikmeleri (E2E Telemetri) */}
          {(connected || metrics) && (
            <div className="cockpit-card">
              <div className="cockpit-card-header">
                <span className="cockpit-card-title">
                  <Activity className="w-4 h-4 text-sky-400" />
                  Son Tur Gecikmeleri
                </span>
              </div>
              <div className="cockpit-latency-grid">
                <div className="cockpit-latency-item">
                  <span style={{ color: "#94a3b8" }}>İlk ses:</span>
                  <span style={{ color: "#34d399", fontWeight: "bold" }}>
                    {dash(metrics?.first_audio_ms, " ms", 0)}
                  </span>
                </div>
                <div className="cockpit-latency-item">
                  <span style={{ color: "#94a3b8" }}>STT (F₂):</span>
                  <span style={{ color: "#38bdf8", fontWeight: "bold" }}>
                    {dash(metrics?.stt_ms, " ms", 0)}
                  </span>
                </div>
                <div className="cockpit-latency-item">
                  <span style={{ color: "#94a3b8" }}>LLM (F₃):</span>
                  <span style={{ color: "#fbbf24", fontWeight: "bold" }}>
                    {dash(metrics?.llm_total_ms, " ms", 0)}
                  </span>
                </div>
                <div className="cockpit-latency-item">
                  <span style={{ color: "#94a3b8" }}>TTS (F₅):</span>
                  <span style={{ color: "#c084fc", fontWeight: "bold" }}>
                    {dash(metrics?.tts_ms, " ms", 0)}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Kart 5: Mühendislik & Model Çıktıları (Açılır Çekmece) */}
          <div className="cockpit-card" style={{ border: showEngineerDetails ? "1px solid rgba(245, 158, 11, 0.3)" : undefined }}>
            <div
              className="cockpit-card-header"
              style={{ cursor: "pointer", marginBottom: showEngineerDetails ? "10px" : 0, borderBottom: showEngineerDetails ? "1px solid rgba(255, 255, 255, 0.08)" : "none" }}
              onClick={() => setShowEngineerDetails((v) => !v)}
            >
              <span className="cockpit-card-title" style={{ color: showEngineerDetails ? "#fbbf24" : undefined }}>
                <Cpu className="w-4 h-4 text-amber-400" />
                🔬 Mühendislik ve Model Çıktıları {showEngineerDetails ? "▲" : "▼"}
              </span>
              <span style={{ fontSize: "10px", color: "#94a3b8" }}>
                {perspective === "engineer" ? "Mühendis Modu" : showEngineerDetails ? "Gizle" : "Genişlet"}
              </span>
            </div>

            {showEngineerDetails && (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {/* Otomotiv LLM Fine-Tuning Veriseti Paneli */}
                <DatasetGeneratorPanel api={api} rawApi={rawApi} />

                {/* F3 Deterministik Slot & Fonksiyon Çıktısı (Raw JSON) */}
                <div>
                  <div style={{ fontSize: "11px", fontWeight: 600, color: "#cbd5e1", marginBottom: "4px" }}>
                    F₃ Deterministik Slot & Fonksiyon Çıktısı
                  </div>
                  <pre className="cockpit-json-block">
                    {JSON.stringify({ ...detectedSlotInfo, dialogue_state: voice.dialogueState }, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Katman C: Inspector Drawer */}
      {selectedStage && (fallbackPipelineState.source !== "live" || LIVE_MEASURED_STAGES.includes(selectedStage)) && (
        <AudioPipelineInspector
          selectedStage={selectedStage}
          pipelineState={fallbackPipelineState}
          onClose={() => setSelectedStage(null)}
          onNavigateToTab={onNavigateToTab}
        />
      )}
    </div>
  );
}
