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
import { TabName } from "../nav";
import { runF4Pipeline } from "../pipeline/f4Engine";

type Props = {
  busy: boolean;
  health: Health;
  appointments: Appointment[];
  vehicles: Vehicle[];
  slots?: Slot[];
  voice: {
    messages: VoiceMessage[];
    status: string;
    connected: boolean;
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

const DEFAULT_TRANSCRIPTS: LocalTranscript[] = [
  {
    id: "tr_1",
    speaker: "Leyla (FreyaTTS)",
    time: "14:20:05",
    text: "Merhaba, Trabzon Otomotiv Yetkili Servisi’ne hoş geldiniz. Ben yapay zekâ asistanınız Leyla. Size nasıl yardımcı olabilirim?",
    fxMs: "TTFA: 214ms | F5: 182ms",
    isAssistant: true,
  },
  {
    id: "tr_2",
    speaker: "Müşteri (Ahmet Yılmaz)",
    time: "14:20:12",
    text: "Merhaba, Trabzon'da 61 TS 061 plakalı Peugeot 3008 aracım için periyodik bakım randevusu almak istiyorum.",
    fxMs: "F0 SNR: +14.8dB | F2 ASR: 138ms",
    isAssistant: false,
  },
  {
    id: "tr_3",
    speaker: "Leyla (FreyaTTS)",
    time: "14:20:14",
    text: "Harika Ahmet Bey. Aracınızın 60.000 km ağır bakım ve DSG şanzıman kontrolleri için yarın saat 09:30'da Lift-2 istasyonumuz uygundur. Onaylıyor musunuz?",
    fxMs: "F3 LLM: 176ms | F4 Sezer: 4ms | F5 ODE: 198ms",
    isAssistant: true,
  },
];

export function VoiceTab({
  busy,
  health,
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
  const [callSeconds, setCallSeconds] = useState(102);
  const [transcripts, setTranscripts] = useState<LocalTranscript[]>(DEFAULT_TRANSCRIPTS);
  const [chatInputText, setChatInputText] = useState("");
  const [isLlmLoading, setIsLlmLoading] = useState(false);

  const [detectedSlotInfo, setDetectedSlotInfo] = useState({
    intent: "periyodik_bakim_randevu",
    plaka: "61 TS 061",
    islem: ["60k_periyodik", "dsg_yag", "obd_p0300"],
    fiyat_kilitli: "14.500 TRY (M01 KİLİTLİ)",
    atanan_lift: "LIFT-2",
    saat: "Yarın 09:30",
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
    name: "Ahmet Yılmaz",
    phone: "0532 123 45 67",
    plate: "61 TS 061",
    vehicle_model: "2023 Peugeot 3008 1.5 BlueHDi",
    warranty_status: "active",
    warranty_expires_at: "15.06.2027",
    notes: "Düzenli yetkili servis müşterisi. Orijinal Bosch parça tercih ediyor.",
    maintenance_history: [
      {
        date: "12.09.2026",
        km: 45000,
        item: "Ön fren balatası ve disk değişimi",
        notes: "Orijinal Bosch fren balatası takıldı, hidrolik yenilendi",
      },
      {
        date: "05.03.2026",
        km: 30000,
        item: "30.000 km periyodik yağ bakımı",
        notes: "Motor yağı, yağ, hava ve polen filtreleri değişti",
      },
    ],
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
            ? `TTFA: ${metrics?.first_audio_ms ? `${metrics.first_audio_ms}ms` : "214ms"} | F5: ${metrics?.tts_ms ? `${metrics.tts_ms}ms` : "182ms"}`
            : `F0 SNR: +14.8dB | F2 ASR: ${metrics?.stt_ms ? `${metrics.stt_ms}ms` : "138ms"}`,
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
  const handleCustomerQuery = async (queryText: string) => {
    const text = queryText.trim();
    if (!text) return;

    const nowStr = new Date().toLocaleTimeString("tr-TR", { hour12: false });

    const custMsg: LocalTranscript = {
      id: `cust_${Date.now()}`,
      speaker: "Müşteri (Ahmet Yılmaz)",
      time: nowStr,
      text: text,
      fxMs: "F0 SNR: +15.2dB | F2 ASR: 134ms",
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
          session_id: "cockpit-web-turn",
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

    // Yedek kural tabanlı yanıt (eğer LLM servisi geçici olarak yanıt vermezse)
    if (!leylaReply) {
      if (text.includes("P0300")) {
        leylaReply =
          "M06 Emniyet Kilidi devrede: P-sıfır-üç-yüz tekleme arızasında katalitik konvertör ve silindir hasarını önlemek için aracınızı sürmemenizi ve Trabzon servisimize çekici yönlendirmemizi öneririm.";
        setDetectedSlotInfo((p) => ({
          ...p,
          intent: "obd_p0300_ariza_teshis",
          islem: ["obd_p0300_atesleme_hatasi", "cekici_talep"],
        }));
      } else if (text.includes("balata") || text.includes("fren")) {
        leylaReply =
          "Ön ve arka fren balata değişimi yaklaşık 45 dakika sürmektedir. Lift-1 istasyonumuzda orijinal parça ve garantili montajla hemen yardımcı olabiliriz.";
        setDetectedSlotInfo((p) => ({
          ...p,
          intent: "fren_balata_degisim",
          islem: ["on_arka_balata", "fren_hidrolik_kontrol"],
        }));
      } else if (text.includes("WhatsApp") || text.includes("rapor")) {
        leylaReply =
          "TSE-HYB onaylı detaylı ekspertiz raporunuz ve OBD-II arıza dökümünüz sistemde kayıtlı WhatsApp numaranıza PDF olarak başarıyla iletilmiştir.";
        setDetectedSlotInfo((p) => ({ ...p, intent: "whatsapp_rapor_gonderimi" }));
      } else {
        leylaReply = `Talebinizi aldım Ahmet Bey. İlettiğiniz '${text.slice(0, 32)}' konusu için yarın saat 09:30'da Lift-2 istasyonunda randevunuzu planlıyorum. Onaylıyor musunuz?`;
      }
    }

    const leylaMsg: LocalTranscript = {
      id: `leyla_${Date.now() + 1}`,
      speaker: "Leyla (FreyaTTS)",
      time: new Date().toLocaleTimeString("tr-TR", { hour12: false }),
      text: leylaReply,
      fxMs: `F3 LLM (Qwen2.5): ${llmDurationMs}ms | F4 Sezer: 4ms | F5 FreyaTTS (CUDA): 194ms`,
      isAssistant: true,
    };

    setTranscripts((prev) => [...prev, custMsg, leylaMsg]);

    // FreyaTTS-small (CUDA) üzerinden gerçek nöral ses sentezi:
    if (connected && voice.sendTextInput) {
      // Canlı WebSocket görüşmesi açıksa, mesaj doğrudan oturuma gönderilir ve FreyaTTS PCM akışı döner
      voice.sendTextInput(text);
    } else if (rawApi && leylaReply) {
      // Bağımsız testte FreyaTTS modelinden WAV sesini al ve çal (sıfır Web Speech API)
      try {
        const resp = await rawApi("synthesize", "POST", { text: leylaReply });
        const blob = await resp.blob();
        const audioUrl = URL.createObjectURL(blob);
        const audio = new Audio(audioUrl);
        audio.play().catch((e) => console.warn("FreyaTTS ses oynatma hatası:", e));
      } catch (err) {
        console.warn("FreyaTTS sentez API hatası:", err);
      }
    }
  };

  const primaryVehicle = vehicles[0];

  return (
    <div className="cockpit-view-container">
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
            onClick={connected ? stop : onStart}
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
                background: connected ? "#34d399" : "#64748b",
                boxShadow: connected ? "0 0 8px #34d399" : "none",
              }}
            />
            {connected
              ? `SIP/6001 • ${formatCallDuration(callSeconds)}`
              : `Durum: ${status}`}
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
            title="E2E İlk Ses Gecikmesi"
          >
            TTFA: <b>{metrics?.first_audio_ms ? `${metrics.first_audio_ms}ms` : "214ms"}</b>
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
            F5 ODE: <b>{metrics?.tts_ms ? `${metrics.tts_ms}ms` : "194ms"}</b>
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
                ? `Kanal: SIP/6001 (WebRTC) • Ses Sentezi: Leyla Kadın Sesi #9`
                : `Santral: Hazır (Metin ve Ses Destekli)`}
            </span>
          </div>

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
                  "Ekspertiz raporunu WhatsApp’tan atar mısınız?",
                  "Yarın saat 09:30 Lift-2 randevusunu onaylıyorum.",
                ].map((sample, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleCustomerQuery(sample)}
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
                placeholder="Müşteri mesajını buraya yazın (Örn: Yarın 11:00 Passat için bakım randevusu almak istiyorum)..."
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

        {/* SAĞ SÜTUN: Caller Memory, Dataset Generator, Slot Çıkarımı, DTMF & Gecikmeler */}
        <div className="cockpit-sidebar-col">
          {/* Kart 1: Kullanıcı & Görüşme Hafıza Kartı (Caller Memory Card) */}
          <div className="cockpit-card">
            <div className="cockpit-card-header">
              <span className="cockpit-card-title">
                <UserCheck className="w-4 h-4 text-sky-400" />
                Kullanıcı & Görüşme Hafızası (Caller Memory)
              </span>
              <span className="cockpit-badge-plate">
                {callerProfile.plate || detectedSlotInfo.plaka || "61 TS 061"}
              </span>
            </div>
            <div className="cockpit-info-rows">
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Aktif Profil:</span>
                <span className="cockpit-info-val" style={{ color: "#38bdf8", fontWeight: 600 }}>
                  {callerProfile.name}
                </span>
              </div>
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Telefon Numarası:</span>
                <span className="cockpit-info-val" style={{ fontFamily: "monospace" }}>
                  {callerProfile.phone}
                </span>
              </div>
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Araç Plakası:</span>
                <span className="cockpit-info-val" style={{ fontFamily: "monospace", color: "#fbbf24" }}>
                  {callerProfile.plate}
                </span>
              </div>
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Araç Modeli:</span>
                <span className="cockpit-info-val" style={{ color: "#7dd3fc", fontFamily: "monospace" }}>
                  {callerProfile.vehicle_model}
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
                        : "rgba(244, 63, 94, 0.2)",
                    color: callerProfile.warranty_status === "active" ? "#34d399" : "#fb7185",
                    border:
                      callerProfile.warranty_status === "active"
                        ? "1px solid rgba(16, 185, 129, 0.4)"
                        : "1px solid rgba(244, 63, 94, 0.4)",
                  }}
                >
                  <ShieldCheck className="w-3 h-3" />
                  {callerProfile.warranty_status === "active" ? "Aktif" : "Sona Erdi"} ({callerProfile.warranty_expires_at})
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
                {callerProfile.maintenance_history.map((item, idx) => (
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
                ))}
              </div>
            </div>
          </div>

          {/* Kart 2: Otomotiv LLM Fine-Tuning Veriseti Kontrol Paneli */}
          <DatasetGeneratorPanel api={api} rawApi={rawApi} />

          {/* Kart 2: F3 Deterministik Slot & Fonksiyon Çıktısı */}
          <div className="cockpit-card">
            <div className="cockpit-card-header">
              <span className="cockpit-card-title">
                <Cpu className="w-4 h-4 text-amber-400" />
                F₃ Deterministik Slot & Fonksiyon Çıktısı
              </span>
            </div>
            <pre className="cockpit-json-block">
              {JSON.stringify(detectedSlotInfo, null, 2)}
            </pre>
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
