import type { ActionFn, Health } from "../api";
import type { ApiFn } from "../ui";

const pillClass = (status?: string, okValues: string[] = ["READY"]) =>
  "pill " + (!status ? "" : okValues.includes(status) ? "ok" : "bad");

type Props = {
  api: ApiFn;
  action: ActionFn;
  refresh: () => Promise<void>;
  busy: boolean;
  health: Health;
};

const COMPONENTS: [string, "tts" | "stt" | "vad" | "ollama"][] = [
  ["FREYATTS CUDA (TTS)", "tts"],
  ["FASTER-WHISPER STT", "stt"],
  ["SILERO VAD", "vad"],
  ["OLLAMA (Qwen2.5)", "ollama"],
];

export function SystemTab({ api, action, refresh, busy, health }: Props) {
  return (
    <section>
      <h2>Yerel bileşenler</h2>
      {COMPONENTS.map(([label, key]) => (
        <div className="row" key={key}>
          <b>{label}</b>
          <span className={pillClass(health[key]?.status)}>{health[key]?.status || "Bilinmiyor"}</span>
        </div>
      ))}
      <div className="row">
        <b>GPU CIRCUIT BREAKER</b>
        <span className={pillClass(health.circuit_breaker?.status, ["CLOSED"])}>
          {health.circuit_breaker?.status || "Bilinmiyor"}
        </span>
      </div>
      <p className="muted">
        İlk yükleme model indirebilir. STT CPU’da, FreyaTTS CUDA’da,
        Ollama sınırlı GPU katmanlarıyla çalışır.
      </p>
      <button
        disabled={busy || health.loading}
        onClick={() =>
          action(async () => {
            await api("models/load", "POST");
            await refresh();
          })
        }
      >
        {busy ? "Modeller yükleniyor…" : "Modelleri yükle"}
      </button>
      {health.error && <p className="error">{health.error}</p>}
    </section>
  );
}
