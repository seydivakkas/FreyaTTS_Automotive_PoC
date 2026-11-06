import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { MilestonePanel } from "./MilestonePanel";
import { LexiconPanel } from "./LexiconPanel";
import { NotificationPanel } from "./NotificationPanel";
import { OutboundPanel } from "./OutboundPanel";
import { InspectionPanel } from "./InspectionPanel";
import { AnalyticsPanel } from "./AnalyticsPanel";
import { DiagnosticPanel } from "./DiagnosticPanel";
import { TechnicianDictationPanel } from "./TechnicianDictationPanel";
import { QueueLiftPanel } from "./QueueLiftPanel";
import { ABTestingPanel } from "./ABTestingPanel";
import { OperatorPanel } from "./OperatorPanel";
import { CarDenoiserPanel } from "./CarDenoiserPanel";
type Row = Record<string, any>;
function App() {
  const [password, setPassword] = useState(""),
    [logged, setLogged] = useState(false),
    [tab, setTab] = useState("Görüşme"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<Row>({}),
    [quotes, setQuotes] = useState<Row[]>([]),
    [vehicles, setVehicles] = useState<Row[]>([]),
    [slots, setSlots] = useState<Row[]>([]),
    [appointments, setAppointments] = useState<Row[]>([]),
    [calls, setCalls] = useState<Row[]>([]),
    [turns, setTurns] = useState<Row[]>([]);
  const [messages, setMessages] = useState<Row[]>([]),
    [status, setStatus] = useState("Hazır"),
    [connected, setConnected] = useState(false),
    [text, setText] = useState(
      "Volkswagen Passat 1.5 TSI aracınızın tahmini değeri 1.250.000 TL.",
    ),
    [normalized, setNormalized] = useState(""),
    [audioUrl, setAudioUrl] = useState("");
  const playback = useRef<AudioContext | null>(null);
  const sock = useRef<WebSocket | null>(null),
    ctx = useRef<AudioContext | null>(null),
    stream = useRef<MediaStream | null>(null),
    node = useRef<AudioWorkletNode | null>(null),
    queue = useRef<AudioBufferSourceNode[]>([]),
    next = useRef(0),
    paused = useRef(false);
  const headers = () => ({
    Authorization: "Basic " + btoa("admin:" + password),
    "Content-Type": "application/json",
  });
  async function api(path: string, method = "GET", body?: unknown) {
    const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
    const h: Record<string, string> = {
      Authorization: "Basic " + btoa("admin:" + password),
    };
    if (!isFormData) {
      h["Content-Type"] = "application/json";
    }
    const r = await fetch("/api/" + path, {
      method,
      headers: h,
      body: body === undefined ? undefined : (isFormData ? (body as FormData) : JSON.stringify(body)),
    });
    if (!r.ok) {
      let detail;
      try {
        detail = (await r.json()).detail;
      } catch {
        detail = r.statusText;
      }
      throw Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return r.json();
  }
  async function action(fn: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    const [h, v, s, a, c, q] = await Promise.all(
      [
        "readiness",
        "vehicles",
        "slots",
        "appointments",
        "conversations",
        "quotes",
      ].map((x) => api(x)),
    );
    setHealth(h);
    setVehicles(v);
    setSlots(s);
    setAppointments(a);
    setCalls(c);
    setQuotes(q);
  }
  useEffect(() => {
    if (logged) action(refresh);
  }, [logged]);
  function flush() {
    for (const s of queue.current) {
      try {
        s.stop();
      } catch {}
    }
    queue.current = [];
    next.current = 0;
  }
  function stop() {
    sock.current?.close();
    sock.current = null;
    node.current?.disconnect();
    stream.current?.getTracks().forEach((t) => t.stop());
    flush();
    ctx.current?.close();
    ctx.current = null;
    playback.current?.close();
    playback.current = null;
    setConnected(false);
    setStatus("Görüşme sonlandı");
  }
  useEffect(() => () => stop(), []);
  async function start() {
    const ac = new AudioContext();
    const out = new AudioContext();
    ctx.current = ac;
    playback.current = out;
    const unlocked = Promise.all([ac.resume(), out.resume()]);
    setStatus("Bağlanıyor");
    try {
      await unlocked;
      const ticket = await api("session-ticket", "POST");
      stream.current = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      await ac.audioWorklet.addModule("/capture.js");
      const ws = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/voice?ticket=${encodeURIComponent(ticket.ticket)}`,
      );
      sock.current = ws;
      ws.binaryType = "arraybuffer";
      setMessages([]);
      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            sample_rate: ac.sampleRate,
            encoding: "pcm_s16le",
            channels: 1,
          }),
        );
        const n = new AudioWorkletNode(ac, "capture");
        node.current = n;
        ac.createMediaStreamSource(stream.current!).connect(n);
        const mute = ac.createGain();
        mute.gain.value = 0;
        n.connect(mute);
        mute.connect(ac.destination);
        n.port.onmessage = (e) => {
          if (ws.readyState === 1 && ws.bufferedAmount < 128000)
            ws.send(e.data);
        };
        setConnected(true);
        setStatus("Bağlandı");
      };
      ws.onmessage = async (e) => {
        if (typeof e.data === "string") {
          const m = JSON.parse(e.data);
          if (m.type === "completed") {
            stop();
            return;
          }
          if (m.type === "transcript") setMessages((x) => [...x, m]);
          if (m.type === "error") setError(m.message);
          if (m.type === "status")
            setStatus(
              (
                {
                  listening: "Dinliyor",
                  synthesizing: "Ses üretiyor",
                  speaking: "Konuşuyor",
                } as Row
              )[m.value] || m.value,
            );
          if (m.type === "playback") {
            if (m.action === "flush") flush();
            if (m.action === "pause") {
              paused.current = true;
              await out.suspend();
            } else if (m.action === "resume" || m.action === "flush") {
              paused.current = false;
              await out.resume();
            }
          }
        } else {
          const pcm = new Int16Array(e.data);
          const b = out.createBuffer(1, pcm.length, 16000);
          const d = b.getChannelData(0);
          for (let i = 0; i < pcm.length; i++) d[i] = pcm[i] / 32768;
          const s = out.createBufferSource();
          s.buffer = b;
          s.connect(out.destination);
          next.current = Math.max(out.currentTime + 0.025, next.current);
          s.start(next.current);
          next.current += b.duration;
          queue.current.push(s);
          s.onended = () => {
            queue.current = queue.current.filter((x) => x !== s);
          };
        }
      };
      ws.onerror = () =>
        setError(
          "Ses bağlantısı kurulamadı; model ve sunucu durumunu kontrol edin.",
        );
      ws.onclose = () => stop();
    } catch (e) {
      stop();
      throw e;
    }
  }
  const date = (s: string) =>
    new Date(s).toLocaleString("tr-TR", { timeZone: "Europe/Istanbul" });
  if (!logged)
    return (
      <main className="login">
        <div className="brand">
          f<span>reya</span>
          <small>OTOMOTİV ASİSTANI</small>
        </div>
        <h1>Yerel ses, doğal iletişim.</h1>
        <p>Yönetim paneline güvenli giriş yapın.</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            action(async () => {
              await api("readiness");
              setLogged(true);
            });
          }}
        >
          <label>
            Yönetici parolası
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button disabled={busy}>Panele giriş →</button>
        </form>
        {error && (
          <div role="alert" className="error">
            {error}
          </div>
        )}
      </main>
    );
  return (
    <div className="layout">
      <aside>
        <div className="brand">
          f<span>reya</span>
          <small>OTOMOTİV ASİSTANI</small>
        </div>
        <nav>
          {[
            "Görüşme",
            "Operatör (6002)",
            "Araç İçi DSP & Gürültü",
            "Randevular",
            "Sıra & Lift Durumu",
            "A/B Test & İnce Ayar",
            "Analitik & KPI",
            "Ekspertiz Raporları",
            "Teknisyen Dikte",
            "Araç Teşhis & OBD-II",
            "Araçlar ve fiyatlar",
            "Sözlük",
            "Bildirimler",
            "Giden Çağrılar",
            "Geçmiş",
            "Ses laboratuvarı",
            "Sistem",
            "M01–M11",
          ].map((t) => (
            <button
              key={t}
              className={tab === t ? "selected" : ""}
              onClick={() => {
                setTab(t);
                action(refresh);
              }}
            >
              {t}
            </button>
          ))}
        </nav>
        <div className="local">
          ● Tamamen yerel<small>Tek aktif görüşme · İstanbul</small>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <p className="eyebrow">EKSPERTİZ OPERASYONU</p>
            <h1>{tab}</h1>
          </div>
          <button
            className="secondary"
            onClick={() => action(refresh)}
            disabled={busy}
          >
            Yenile ↻
          </button>
        </header>
        {health.demo_mode && (
          <div role="status" className="demo-banner">
            <strong>DEMO MODU</strong> Bu paneldeki görüşmeler, gecikme değerleri
            ve kayıtlar örnek veridir; gerçek ölçüm veya müşteri kaydı değildir.
          </div>
        )}
        {error && (
          <div role="alert" className="error">
            {error}
          </div>
        )}
        {tab === "Görüşme" && (
          <>
            <div className="stats">
              <article>
                <small>Ses motoru</small>
                <strong>
                  {health.tts?.status === "READY"
                    ? "Hazır"
                    : "Model bekleniyor"}
                </strong>
              </article>
              <article>
                <small>Aktif randevu</small>
                <strong>
                  {appointments.filter((x) => x.status === "confirmed").length}
                </strong>
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
              <button
                disabled={busy}
                onClick={() => (connected ? stop() : action(start))}
              >
                {connected ? "Görüşmeyi bitir" : "Mikrofonla görüşme başlat"}
              </button>
              <small>
                Mikrofon izni gerekir. Ham ses kaydı varsayılan olarak
                kapalıdır.
              </small>
              {connected && (
                <div style={{ marginTop: "16px", padding: "12px", background: "#1e293b", borderRadius: "8px", maxWidth: "260px", margin: "16px auto 0" }}>
                  <div style={{ fontSize: "12px", color: "#94a3b8", marginBottom: "8px", fontWeight: "bold" }}>📞 DTMF Tuş Takımı (Sıfır Gecikme)</div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "6px" }}>
                    {["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"].map((d) => (
                      <button
                        key={d}
                        type="button"
                        onClick={() => {
                          if (sock.current && sock.current.readyState === WebSocket.OPEN) {
                            sock.current.send(JSON.stringify({ type: "dtmf", digit: d }));
                          }
                        }}
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
        )}
        {tab === "Araçlar ve fiyatlar" && (
          <>
            <section>
              <h2>Araç ekle</h2>
              <form
                className="inline"
                onSubmit={(e) => {
                  e.preventDefault();
                  const f = e.currentTarget,
                    d = new FormData(f);
                  action(async () => {
                    await api("vehicles", "POST", {
                      description: d.get("description"),
                      plate: d.get("plate"),
                    });
                    f.reset();
                    await refresh();
                  });
                }}
              >
                <label>
                  Marka ve model
                  <input
                    name="description"
                    required
                    placeholder="Volkswagen Passat"
                  />
                </label>
                <label>
                  Plaka
                  <input name="plate" placeholder="34 ABC 123" />
                </label>
                <button disabled={busy}>Kaydet</button>
              </form>
            </section>
            <section>
              <h2>Kayıtlı araçlar ve ekspertiz fiyatı</h2>
              {vehicles.length ? (
                vehicles.map((v) => (
                  <form
                    className="inline row"
                    key={v.id}
                    onSubmit={(e) => {
                      e.preventDefault();
                      const d = new FormData(e.currentTarget);
                      action(async () => {
                        await api("quotes", "POST", {
                          vehicle_id: v.id,
                          amount_kurus: Math.round(
                            Number(d.get("price")) * 100,
                          ),
                        });
                        await refresh();
                      });
                    }}
                  >
                    <div>
                      <b>{v.description}</b>
                      <small>{v.plate || "Plaka girilmedi"}</small>
                    </div>
                    <label>
                      Fiyat (TL)
                      <input
                        name="price"
                        defaultValue={
                          quotes.find((q) => q.vehicle_id === v.id)
                            ?.amount_kurus / 100 || undefined
                        }
                        type="number"
                        min="0.01"
                        step="0.01"
                        required
                      />
                    </label>
                    <button className="secondary">Fiyatı kaydet</button>
                  </form>
                ))
              ) : (
                <p className="muted">Henüz araç kaydı yok.</p>
              )}
            </section>
          </>
        )}
        {tab === "Randevular" && (
          <>
            <section>
              <h2>Müsait saat ekle</h2>
              <form
                className="inline"
                onSubmit={(e) => {
                  e.preventDefault();
                  const d = new FormData(e.currentTarget);
                  action(async () => {
                    await api("slots", "POST", {
                      starts_at: String(d.get("time")) + ":00+03:00",
                    });
                    await refresh();
                  });
                }}
              >
                <label>
                  İstanbul tarihi ve saati
                  <input type="datetime-local" name="time" required />
                </label>
                <button disabled={busy}>Saat ekle</button>
              </form>
            </section>
            <section>
              <h2>Randevu takvimi</h2>
              {slots.map((s) => {
                const a = appointments.find(
                  (x) => x.slot_id === s.id && x.status === "confirmed",
                );
                return (
                  <div className="row" key={s.id}>
                    <div>
                      <b>{date(s.starts_at)}</b>
                      <small>{a ? a.customer : "Müsait"}</small>
                    </div>
                    {a ? (
                      <button
                        className="secondary"
                        onClick={() =>
                          action(async () => {
                            await api(`appointments/${a.id}/cancel`, "POST");
                            await refresh();
                          })
                        }
                      >
                        İptal et
                      </button>
                    ) : (
                      <span className="pill">Müsait</span>
                    )}
                  </div>
                );
              })}
              {!slots.length && (
                <p className="muted">
                  Asistanın sunabilmesi için önce müsait saat ekleyin.
                </p>
              )}
            </section>
          </>
        )}
        {tab === "Geçmiş" && (
          <div className="two">
            <section>
              <h2>Görüşmeler</h2>
              {calls.map((c) => (
                <div className="row" key={c.id}>
                  <button
                    className="secondary"
                    onClick={() =>
                      action(async () =>
                        setTurns(await api("conversations/" + c.id)),
                      )
                    }
                  >
                    {date(c.created_at)}
                    <small>
                      {c.channel} · {c.status}
                    </small>
                  </button>
                  <button
                    className="danger"
                    onClick={() =>
                      action(async () => {
                        await api("conversations/" + c.id, "DELETE");
                        setTurns([]);
                        await refresh();
                      })
                    }
                  >
                    Sil
                  </button>
                </div>
              ))}
              {!calls.length && <p className="muted">Henüz görüşme yok.</p>}
            </section>
            <section>
              <h2>Transkript ve ölçümler</h2>
              {turns.map((t) => (
                <p className="bubble" key={t.id}>
                  <b>{t.role}</b>
                  {t.text || t.metrics}
                </p>
              ))}
            </section>
          </div>
        )}
        {tab === "Ses laboratuvarı" && (
          <section>
            <h2>Türkçe telaffuz denemesi</h2>
            <label>
              Kaynak metin
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={5}
              />
            </label>
            <div className="inline">
              <button
                onClick={() =>
                  action(async () =>
                    setNormalized(
                      (await api("normalize", "POST", { text })).normalized,
                    ),
                  )
                }
              >
                Normalizasyonu incele
              </button>
              <button
                className="secondary"
                onClick={() =>
                  action(async () => {
                    const r = await fetch("/api/synthesize", {
                      method: "POST",
                      headers: headers(),
                      body: JSON.stringify({ text }),
                    });
                    if (!r.ok) throw Error((await r.json()).detail);
                    if (audioUrl) URL.revokeObjectURL(audioUrl);
                    setAudioUrl(URL.createObjectURL(await r.blob()));
                  })
                }
              >
                Sesi üret
              </button>
            </div>
            {normalized && <p className="bubble">{normalized}</p>}
            {audioUrl && <audio controls src={audioUrl} />}
          </section>
        )}
        {tab === "Operatör (6002)" && <OperatorPanel api={api} onError={setError} />}
        {tab === "Araç İçi DSP & Gürültü" && <CarDenoiserPanel api={api} />}
        {tab === "Sıra & Lift Durumu" && <QueueLiftPanel api={api} />}
        {tab === "A/B Test & İnce Ayar" && <ABTestingPanel api={api} action={action} />}
        {tab === "Analitik & KPI" && <AnalyticsPanel api={api} />}
        {tab === "Ekspertiz Raporları" && <InspectionPanel api={api} />}
        {tab === "Teknisyen Dikte" && <TechnicianDictationPanel api={api} />}
        {tab === "Araç Teşhis & OBD-II" && <DiagnosticPanel api={api} />}
        {tab === "Sözlük" && <LexiconPanel api={api} />}
        {tab === "Bildirimler" && <NotificationPanel api={api} />}
        {tab === "Giden Çağrılar" && <OutboundPanel api={api} />}
        {tab === "M01–M11" && <MilestonePanel api={api} />}
        {tab === "Sistem" && (
          <section>
            <h2>Yerel bileşenler</h2>
            <div className="row">
              <b>FREYATTS CUDA (TTS)</b>
              <span className={"pill " + (health.tts?.status === "READY" ? "ok" : "")}>
                {health.tts?.status || "BLOCKED"}
              </span>
            </div>
            <div className="row">
              <b>FASTER-WHISPER STT</b>
              <span className={"pill " + (health.stt?.status === "READY" ? "ok" : "")}>
                {health.stt?.status || "BLOCKED"}
              </span>
            </div>
            <div className="row">
              <b>SILERO VAD</b>
              <span className={"pill " + (health.vad?.status === "READY" ? "ok" : "")}>
                {health.vad?.status || "BLOCKED"}
              </span>
            </div>
            <div className="row">
              <b>OLLAMA (Qwen2.5)</b>
              <span className={"pill " + (health.ollama?.status === "READY" ? "ok" : "")}>
                {health.ollama?.status || "BLOCKED"}
              </span>
            </div>
            <div className="row">
              <b>GPU CIRCUIT BREAKER</b>
              <span className="pill ok">
                {health.circuit_breaker?.status || "CLOSED (Normal)"}
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
        )}
        <footer>
          Freya Automotive · Yerel çalışma alanı · Fiyatlar yalnızca kayıtlı
          veriden aktarılır.
        </footer>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
