import type { Appointment, Health, Vehicle, VoiceMessage, VoiceMetrics } from "../api";
import { dash } from "../ui";

type Props = {
  busy: boolean;
  health: Health;
  appointments: Appointment[];
  vehicles: Vehicle[];
  voice: {
    messages: VoiceMessage[];
    status: string;
    connected: boolean;
    metrics: VoiceMetrics | null;
    stop: () => void;
    sendDtmf: (digit: string) => void;
  };
  onStart: () => void;
};

export function VoiceTab({ busy, health, appointments, vehicles, voice, onStart }: Props) {
  const { messages, status, connected, metrics, stop, sendDtmf } = voice;
  return (
    <>
      <div className="stats">
        <article>
          <small>Ses motoru</small>
          <strong>
            {!health.tts?.status
              ? "Bilinmiyor"
              : health.tts.status === "READY"
                ? "Hazır"
                : "Model bekleniyor"}
          </strong>
        </article>
        <article>
          <small>Aktif randevu</small>
          <strong>{appointments.filter((x) => x.status === "confirmed").length}</strong>
        </article>
        <article>
          <small>Kayıtlı araç</small>
          <strong>{vehicles.length}</strong>
        </article>
      </div>
      <section className="voice">
        <div className={"orb " + (connected ? "live" : "")}>f</div>
        <span className="pill">{status}</span>
        <h2>Bir randevu ile başlayın.</h2>
        <p>
          Adınızı, aracınızın marka modelini söyleyin.
          <br />
          Asistan müsait saatleri sunar ve onayınızı ister.
        </p>
        <button disabled={busy} onClick={() => (connected ? stop() : onStart())}>
          {connected ? "Görüşmeyi bitir" : "Mikrofonla görüşme başlat"}
        </button>
        <small>
          Mikrofon izni gerekir. Ham ses kaydı varsayılan olarak
          kapalıdır.
        </small>
        {(connected || metrics) && (
          <div className="metrics" aria-label="Son tur gecikmeleri">
            <b>Son tur gecikmeleri</b>
            <span>İlk ses: {dash(metrics?.first_audio_ms, " ms", 0)}</span>
            <span>STT: {dash(metrics?.stt_ms, " ms", 0)}</span>
            <span>LLM: {dash(metrics?.llm_total_ms, " ms", 0)}</span>
            <span>TTS: {dash(metrics?.tts_ms, " ms", 0)}</span>
            <span>RTF: {dash(metrics?.rtf, "", 2)}</span>
          </div>
        )}
        {connected && (
          <div style={{ marginTop: "16px", padding: "12px", background: "#1e293b", borderRadius: "8px", maxWidth: "260px", margin: "16px auto 0" }}>
            <div style={{ fontSize: "12px", color: "#94a3b8", marginBottom: "8px", fontWeight: "bold" }}>📞 DTMF Tuş Takımı (Sıfır Gecikme)</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "6px" }}>
              {["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"].map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => sendDtmf(d)}
                  style={{
                    padding: "8px 0",
                    background: d === "1" ? "#1e3a8a" : d === "0" ? "#831843" : "#0f172a",
                    color: "#f8fafc",
                    border: "1px solid #475569",
                    borderRadius: "6px",
                    fontSize: "16px",
                    fontWeight: "bold",
                    cursor: "pointer",
                  }}
                >
                  {d}
                </button>
              ))}
            </div>
            <div style={{ fontSize: "10px", color: "#64748b", marginTop: "6px", textAlign: "center" }}>
              1: Onayla · 2: İptal / Değiştir · 0: Operatör · *: Tekrar
            </div>
          </div>
        )}
      </section>
      <section>
        <h2>Canlı konuşma</h2>
        {messages.length ? (
          messages.map((m, i) => (
            <p className={"bubble " + m.role} key={i}>
              <b>{m.role === "user" ? "Siz" : "Freya"}</b>
              {m.text}
            </p>
          ))
        ) : (
          <p className="muted">
            Görüşme başladığında konuşma burada görünecek.
          </p>
        )}
      </section>
    </>
  );
}
