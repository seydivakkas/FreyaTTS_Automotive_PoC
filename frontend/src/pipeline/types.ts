/**
 * FreyaTTS Automotive Cockpit V3 — F0–F6 Audio Intelligence Pipeline Telemetri Sözleşmesi
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

export type StageId = "F0" | "F1" | "F2" | "F3" | "F4" | "F5" | "F6";

export type StageStatus =
  | "idle"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "skipped"
  | "bypassed";

export const LIVE_MEASURED_STAGES: readonly StageId[] = ["F2", "F3", "F4", "F5"];

export type TelemetrySource = "live" | "demo" | "replay";

export interface StageDefinition {
  id: StageId;
  code: string;
  name: string;
  shortDesc: string;
  technology: string;
  inputDescription: string;
  outputDescription: string;
  inspectorTabs: readonly ("overview" | "parameters" | "intermediate" | "metrics" | "traces")[];
}

export const STAGE_DEFINITIONS: Record<StageId, StageDefinition> = {
  F0: {
    id: "F0",
    code: "F0",
    name: "Akustik DSP & Gürültü",
    shortDesc: "120Hz HPF + Spektral Bastırma + AGC",
    technology: "Butterworth 4. Derece + Sine Spectral (-18dB) + Soft AGC",
    inputDescription: "8 kHz SLIN16 / 16 kHz WebRTC ham ses çerçeveleri",
    outputDescription: "Gürültüden arındırılmış, normalize edilmiş PCM",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F1: {
    id: "F1",
    code: "F1",
    name: "VAD & 2-Aşamalı Barge-In",
    shortDesc: "Silero VAD + 300ms Ring Tampon",
    technology: "Silero VAD (0.55 eşik) + Goertzel DTMF + 2-Stage Soft/Hard Barge-in",
    inputDescription: "16 kHz filtrelenmiş ses blokları (512 örnek)",
    outputDescription: "Konuşma segmentleri, VAD olasılığı, barge-in durdurma sinyali",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F2: {
    id: "F2",
    code: "F2",
    name: "ASR / Faster-Whisper",
    shortDesc: "Türkçe Akustik Transkripsiyon",
    technology: "Faster-Whisper large-v3-turbo (CUDA) + RMS Enerji Kapısı",
    inputDescription: "Süreksizliği bitirilmiş (endpointed) ses segmenti",
    outputDescription: "Ham metin transkripti & segment güven olasılıkları",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F3: {
    id: "F3",
    code: "F3",
    name: "Niyet & LLM Çıkarımı",
    shortDesc: "Supervisor Router & Qwen2.5 7B",
    technology: "Supervisor Intent Router + Deterministik DB Kilidi + Ollama Qwen2.5",
    inputDescription: "Doğrulanmış müşteri konuşma transkripti",
    outputDescription: "Niyet, slotlar, veritabanı yanıtı ve diyalog metni",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F4: {
    id: "F4",
    code: "F4",
    name: "Normalizasyon & Chunker",
    shortDesc: "P0 Sözlük + İlk Cümlecik Kilidi",
    technology: "P0 Otomotiv Fonetik Sözlüğü + Atomik Chunker + Sıfır Markdown Kalkanı",
    inputDescription: "LLM tarafından üretilen ham diyalog yanıtı",
    outputDescription: "Telaffuz kuralları uygulanmış 4-7 kelimelik atomik cümle parçaları",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F5: {
    id: "F5",
    code: "F5",
    name: "FreyaTTS Akustik Sentez",
    shortDesc: "Batched ODE + Leyla Kadın Sesi",
    technology: "FreyaTTS Flow Matching + AudioVAE2 + Leyla Seed #9",
    inputDescription: "Fonetik olarak normalize edilmiş metin parçaları",
    outputDescription: "24 kHz / 16 kHz sentetik PCM dalga formu",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F6: {
    id: "F6",
    code: "F6",
    name: "Ses iletimi",
    shortDesc: "Asterisk / Web Çıkışı",
    technology: "Asterisk AudioSocket / Web Audio API",
    inputDescription: "Sentezlenmiş ham PCM parçaları",
    outputDescription: "Kulaklığa / telefon hattına akıtılan kesintisiz ses yayını",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
};

export interface StageRuntimeState {
  stage: StageId;
  status: StageStatus;
  durationMs: number | null;
  startedAt: number | null;
  completedAt: number | null;
  errorCode?: string;
  errorMessage?: string;
  metrics: Record<string, any>;
  intermediateData?: any;
}

export interface PipelineTurnState {
  turnId: number;
  sessionId: string;
  source: TelemetrySource;
  activeStage: StageId | null;
  totalDurationMs: number | null;
  userText?: string;
  assistantText?: string;
  stages: Record<StageId, StageRuntimeState>;
  traces: PipelineTelemetryEvent[];
}

export interface PipelineTelemetryEvent {
  schema_version: "3.0";
  event_id: string;
  session_id: string;
  turn_id: number;
  stage: StageId;
  status: StageStatus;
  source: TelemetrySource;
  timestamp: number;
  duration_ms?: number;
  metrics?: Record<string, any>;
  intermediate_data?: any;
  error_code?: string;
  error_message?: string;
}

export function createInitialTurnState(turnId: number, sessionId = "", source: TelemetrySource = "live"): PipelineTurnState {
  const stages = {} as Record<StageId, StageRuntimeState>;
  const ids: StageId[] = ["F0", "F1", "F2", "F3", "F4", "F5", "F6"];
  for (const id of ids) {
    stages[id] = {
      stage: id,
      status: "idle",
      durationMs: null,
      startedAt: null,
      completedAt: null,
      metrics: {},
    };
  }
  return {
    turnId,
    sessionId,
    source,
    activeStage: null,
    totalDurationMs: null,
    stages,
    traces: [],
  };
}

