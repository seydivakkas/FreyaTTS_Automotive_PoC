import { basicAuthHeader } from "./ui";
import type { ApiFn, RawApiFn } from "./ui";

/** Paneller için ortak prop tipleri. */
export type ApiProps = { api: ApiFn };
export type Props = ApiProps & { rawApi: RawApiFn };
/** Yükleniyor/hata durumunu yöneten ortak sarmalayıcı. */
export type ActionFn = (fn: () => Promise<void>) => Promise<void>;

// Backend (backend/db.py ve /api/readiness) yanıtlarına karşılık gelen tipler.
export interface Vehicle {
  id: string;
  description: string;
  plate: string;
  vin: string;
}
export interface Slot {
  id: string;
  starts_at: string;
  duration_minutes: number;
}
export interface Appointment {
  id: string;
  slot_id: string | null;
  vehicle_id: string;
  customer: string;
  customer_phone?: string;
  package_type?: string;
  status: string;
  confirmed: boolean;
  created_at: string;
}
export interface Conversation {
  id: string;
  channel: string;
  status: string;
  created_at: string;
}
export interface Quote {
  id: string;
  vehicle_id: string;
  amount_kurus: number;
}
export interface Turn {
  id: string;
  conversation_id: string;
  role: string;
  text: string;
  metrics: string;
  created_at: string;
}
export interface AnalysisRun {
  id: string;
  state: string;
  rule_version: string;
  created_at_ms: number;
  attempts: number;
  lease_expired: boolean;
}
export interface AnalysisSource {
  transport: string;
  origin: string;
}
export interface AnalysisQueue {
  intake_enabled: boolean;
  worker_status: string;
  physical_sip_status: string;
  store: "READY" | "UNAVAILABLE";
  counts: Record<string, number>;
  deferred_count: number | null;
  oldest_wait_ms: number | null;
  runs: (AnalysisRun & AnalysisSource & { conversation_id: string })[];
  deferred: (AnalysisSource & { conversation_id: string; ready_at_ms: number })[];
}
export interface ConversationDetail {
  conversation: Conversation;
  turns: Turn[];
  traces: { id: string; created_at: string; review_status: string; route_state: string;
    outcome: string; intents: string[]; reason_codes: string[] }[];
  transfers: { id: string; status: string; created_at: string; completed_at: string | null }[];
  appointment: { id: string; status: string; starts_at: string | null } | null;
  fqici: {
    store: "READY" | "UNAVAILABLE";
    scope: (AnalysisSource & { terminal_seen: boolean; ready_at_ms: number | null }) | null;
    runs: AnalysisRun[];
  };
}
export interface ComponentStatus {
  status?: string;
  reason?: string;
  device?: string;
  engine?: string;
  model?: string;
}
export interface Health {
  kvkk_erasure_enabled?: boolean;
  auto_purge_transcripts?: boolean;
  demo_mode?: boolean;
  tts?: ComponentStatus;
  stt?: ComponentStatus;
  vad?: ComponentStatus;
  telephony?: ComponentStatus & {
    connected?: boolean;
    simulated?: boolean;
    driver?: string;
    ami_host?: string;
    ami_port?: number;
  };
  ollama?: ComponentStatus;
  circuit_breaker?: ComponentStatus & { state?: string };
  loading?: boolean;
  error?: string | null;
  busy?: boolean;
  model_load_ms?: number | null;
  synth_count?: number;
}
export interface VoiceMessage {
  type: "transcript";
  role: string;
  text: string;
}
export interface VoiceMetrics {
  first_audio_ms?: number | null;
  stt_ms?: number | null;
  llm_total_ms?: number | null;
  tts_ms?: number | null;
  rtf?: number | null;
  [key: string]: unknown;
}

/**
 * Tek kimlik başlığı: JSON, FormData ve ikili (ses/PDF) yanıtlar aynı yardımcıyı kullanır.
 * Panellere "rawApi" olarak verilir; ok olmayan yanıtta Türkçe hata fırlatır, Response döner.
 */
export function createApi(password: string): { api: ApiFn; rawApi: RawApiFn } {
  const rawApi: RawApiFn = async (path, method = "GET", body) => {
    const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
    const h: Record<string, string> = { Authorization: basicAuthHeader(password) };
    if (body !== undefined && !isFormData) h["Content-Type"] = "application/json";
    const r = await fetch("/api/" + path, {
      method,
      headers: h,
      body: body === undefined ? undefined : isFormData ? (body as FormData) : JSON.stringify(body),
    });
    if (!r.ok) {
      if (r.status === 401) throw Error("Parola hatalı veya oturum yetkisi yok.");
      let detail;
      try {
        detail = (await r.json()).detail;
      } catch {
        detail = r.statusText;
      }
      throw Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return r;
  };
  const api: ApiFn = async (path, method = "GET", body) => (await rawApi(path, method, body)).json();
  return { api, rawApi };
}
