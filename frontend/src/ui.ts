import { useEffect } from "react";

export type ApiFn = (path: string, method?: string, body?: unknown) => Promise<any>;
/** FormData / binary yanıtlar için: kimlik başlığını ana uygulamadan alır, ok-olmayan yanıtta hata fırlatır. */
export type RawApiFn = (path: string, method?: string, body?: unknown) => Promise<Response>;

/** Kullanıcı kimlik bilgisi Latin1 dışı karakter içerebilir; önce UTF-8 olarak kodla. */
export function basicAuthHeader(password: string): string {
  const bytes = new TextEncoder().encode("admin:" + password);
  let bin = "";
  bytes.forEach((b) => {
    bin += String.fromCharCode(b);
  });
  return "Basic " + btoa(bin);
}

/** Ölçülmemiş (null/undefined/NaN) değerler için "—", aksi halde biçimlenmiş değer. */
export function dash(v: unknown, suffix = "", digits?: number): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    return (digits === undefined ? String(v) : v.toFixed(digits)) + suffix;
  }
  return String(v) + suffix;
}

/** Modal açıkken Escape tuşuyla kapat. */
export function useEscape(onClose: () => void, active = true) {
  useEffect(() => {
    if (!active) return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [active, onClose]);
}

const METRIC_LABELS: Record<string, [string, string, number]> = {
  stt_ms: ["STT", " ms", 0],
  endpoint_ms: ["Konuşma sonu", " ms", 0],
  llm_total_ms: ["LLM", " ms", 0],
  llm_first_token_ms: ["LLM ilk token", " ms", 0],
  first_audio_ms: ["İlk ses", " ms", 0],
  tts_ms: ["TTS", " ms", 0],
  rtf: ["RTF", "", 2],
};

/** Tur metrik JSON'unu kullanıcıya ham JSON göstermeden okunur metne çevirir; boşsa "" döner. */
export function formatMetrics(raw: unknown): string {
  let obj: Record<string, unknown> | null = null;
  if (typeof raw === "string") {
    try {
      obj = JSON.parse(raw);
    } catch {
      return "";
    }
  } else if (raw && typeof raw === "object") {
    obj = raw as Record<string, unknown>;
  }
  if (!obj) return "";
  const parts: string[] = [];
  for (const [k, [label, unit, digits]] of Object.entries(METRIC_LABELS)) {
    const v = obj[k];
    if (typeof v === "number" && Number.isFinite(v)) parts.push(`${label}: ${v.toFixed(digits)}${unit}`);
  }
  return parts.join(" · ");
}
