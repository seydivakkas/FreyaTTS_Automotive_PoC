import { useEffect, useRef, useState } from "react";
import type { VoiceMessage, VoiceMetrics } from "./api";
import type { ApiFn } from "./ui";
import {
  PipelineTurnState,
  PipelineTelemetryEvent,
  createInitialTurnState,
} from "./pipeline/types";
import { DEMO_SCENARIOS } from "./pipeline/demoFixtures";

function micError(e: unknown) {
  const n = (e as { name?: string } | null)?.name;
  if (n === "NotAllowedError" || n === "SecurityError")
    return "Mikrofon izni verilmedi. Tarayıcı adres çubuğundan mikrofona izin verip tekrar deneyin.";
  if (n === "NotFoundError" || n === "OverconstrainedError")
    return "Mikrofon bulunamadı. Bir mikrofon bağlayıp tekrar deneyin.";
  if (n === "NotReadableError")
    return "Mikrofon başka bir uygulama tarafından kullanılıyor olabilir.";
  return null;
}

const STATUS_LABELS: Record<string, string> = {
  listening: "Dinliyor",
  synthesizing: "Ses üretiyor",
  speaking: "Konuşuyor",
};

/** Sesli görüşme: WebSocket, AudioWorklet yakalama, oynatma kuyruğu, DTMF ve metrikler. */
export function useVoiceSession(api: ApiFn, setError: (msg: string) => void) {
  const [messages, setMessages] = useState<VoiceMessage[]>([]),
    [status, setStatus] = useState("Hazır"),
    [connected, setConnected] = useState(false),
    [metrics, setMetrics] = useState<VoiceMetrics | null>(null),
    [calibrating, setCalibrating] = useState(false),
    [calibrationInfo, setCalibrationInfo] = useState<{
      ambient_dbfs?: number;
      noise_gate_dbfs?: number;
      suppression_db?: number;
      message?: string;
    } | null>(null),
    [pipelineState, setPipelineState] = useState<PipelineTurnState>(() =>
      createInitialTurnState(1, "", "live")
    );
  const playback = useRef<AudioContext | null>(null);
  const sock = useRef<WebSocket | null>(null),
    ctx = useRef<AudioContext | null>(null),
    stream = useRef<MediaStream | null>(null),
    node = useRef<AudioWorkletNode | null>(null),
    queue = useRef<AudioBufferSourceNode[]>([]),
    next = useRef(0),
    paused = useRef(false),
    closing = useRef(false),
    failed = useRef(false),
    wasConnected = useRef(false);

  function fail(msg: string) {
    failed.current = true;
    setError(msg);
  }
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
    closing.current = true;
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
    setStatus(failed.current ? "Hata" : "Görüşme sonlandı");
  }
  useEffect(() => () => stop(), []);
  async function start() {
    failed.current = false;
    closing.current = false;
    wasConnected.current = false;
    setMetrics(null);
    const ac = new AudioContext();
    const out = new AudioContext();
    ctx.current = ac;
    playback.current = out;
    const unlocked = Promise.all([ac.resume(), out.resume()]);
    setStatus("Bağlanıyor");
    try {
      await unlocked;
      try {
        stream.current = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
      } catch (e) {
        const m = micError(e);
        if (m) {
          fail(m);
          stop();
          return;
        }
        throw e;
      }
      await ac.audioWorklet.addModule("/capture.js");
      // Bilet yalnızca 30 sn geçerli: mikrofon izni ve worklet yüklemesinden SONRA alınır.
      const ticket = await api("session-ticket", "POST");
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
        wasConnected.current = true;
        setConnected(true);
        setStatus("Bağlandı");
      };
      ws.onmessage = async (e) => {
        if (typeof e.data === "string") {
          const m = JSON.parse(e.data);
          if (m.type === "calibration_start") {
            setCalibrating(true);
            setStatus("Gürültü Kalibre Ediliyor");
          }
          if (m.type === "calibration_done") {
            setCalibrating(false);
            setCalibrationInfo({
              ambient_dbfs: m.ambient_dbfs,
              noise_gate_dbfs: m.noise_gate_dbfs,
              suppression_db: m.suppression_db,
              message: m.message,
            });
            setStatus("Dinliyor");
          }
          if (m.type === "completed") {
            stop();
            return;
          }
          if (m.type === "pipeline_event" && m.event) {
            const ev = m.event as PipelineTelemetryEvent;
            setPipelineState((prev) => {
              const updatedStages = { ...prev.stages };
              updatedStages[ev.stage] = {
                stage: ev.stage,
                status: ev.status,
                durationMs:
                  ev.duration_ms !== undefined
                    ? ev.duration_ms
                    : updatedStages[ev.stage]?.durationMs ?? null,
                startedAt:
                  ev.status === "running" ? Date.now() : updatedStages[ev.stage]?.startedAt ?? null,
                completedAt:
                  ev.status === "completed"
                    ? Date.now()
                    : updatedStages[ev.stage]?.completedAt ?? null,
                metrics: { ...(updatedStages[ev.stage]?.metrics || {}), ...(ev.metrics || {}) },
                intermediateData:
                  ev.intermediate_data !== undefined
                    ? ev.intermediate_data
                    : updatedStages[ev.stage]?.intermediateData,
                errorCode: ev.error_code,
                errorMessage: ev.error_message,
              };
              return {
                ...prev,
                turnId: ev.turn_id,
                sessionId: ev.session_id,
                source: ev.source || "live",
                activeStage: ev.status === "running" ? ev.stage : prev.activeStage,
                stages: updatedStages,
                traces: [ev, ...prev.traces.slice(0, 49)],
              };
            });
          }
          if (m.type === "transcript") {
            if (m.role === "user") setMetrics(null);
            setMessages((x) => [...x, m]);
          }
          if (m.type === "metrics") {
            const { type: _t, ...rest } = m;
            setMetrics((prev) => ({ ...(prev || {}), ...rest }));
          }
          if (m.type === "error") fail(m.message);
          if (m.type === "status") setStatus(STATUS_LABELS[m.value] || m.value);
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
      ws.onerror = () => {
        if (!wasConnected.current)
          fail("Ses bağlantısı kurulamadı; model ve sunucu durumunu kontrol edin.");
      };
      ws.onclose = (ev) => {
        if (!closing.current && !failed.current)
          fail(
            // Sunucu kod/neden gönderir: 1013 line_busy = hat meşgul, 1008 = bilet süresi doldu.
            ev.reason === "line_busy" || ev.code === 1013
              ? "Hat şu anda meşgul. Birkaç saniye sonra tekrar deneyin."
              : ev.reason === "ticket_expired" || ev.code === 1008
                ? "Oturum bileti geçersiz veya süresi doldu. Aramayı yeniden başlatın."
                : wasConnected.current
                  ? "Ses bağlantısı beklenmedik şekilde kapandı."
                  : "Bağlantı reddedildi. Birkaç saniye sonra tekrar deneyin.",
          );
        stop();
      };
    } catch (e) {
      failed.current = true;
      stop();
      throw e;
    }
  }
  function sendDtmf(digit: string) {
    if (sock.current && sock.current.readyState === WebSocket.OPEN) {
      sock.current.send(JSON.stringify({ type: "dtmf", digit }));
    }
  }
  function recalibrate() {
    if (sock.current && sock.current.readyState === WebSocket.OPEN) {
      sock.current.send(JSON.stringify({ type: "recalibrate" }));
    }
  }
  function runDemoScenario(scenarioId: string) {
    const sc = DEMO_SCENARIOS.find((s) => s.id === scenarioId) || DEMO_SCENARIOS[0];
    const initial = createInitialTurnState(sc.events[0]?.turn_id || 1, sc.events[0]?.session_id || "demo-sim", "demo");
    initial.userText = sc.userSpeech;
    initial.assistantText = sc.botReply;
    setPipelineState(initial);
    setStatus("Simülasyon Çalışıyor");

    let delay = 50;
    sc.events.forEach((ev, idx) => {
      setTimeout(() => {
        setPipelineState((prev) => {
          const updatedStages = { ...prev.stages };
          updatedStages[ev.stage] = {
            stage: ev.stage,
            status: ev.status,
            durationMs: ev.duration_ms !== undefined ? ev.duration_ms : updatedStages[ev.stage]?.durationMs ?? null,
            startedAt: ev.status === "running" ? Date.now() : updatedStages[ev.stage]?.startedAt ?? null,
            completedAt: ev.status === "completed" ? Date.now() : updatedStages[ev.stage]?.completedAt ?? null,
            metrics: { ...(updatedStages[ev.stage]?.metrics || {}), ...(ev.metrics || {}) },
            intermediateData: ev.intermediate_data !== undefined ? ev.intermediate_data : updatedStages[ev.stage]?.intermediateData,
            errorCode: ev.error_code,
            errorMessage: ev.error_message,
          };
          return {
            ...prev,
            turnId: ev.turn_id,
            sessionId: ev.session_id,
            source: "demo",
            activeStage: ev.status === "running" ? ev.stage : prev.activeStage,
            stages: updatedStages,
            traces: [
              {
                ...ev,
                schema_version: "3.0",
                event_id: `demo-ev-${idx}`,
                timestamp: Date.now(),
              },
              ...prev.traces.slice(0, 49),
            ],
          };
        });
        if (idx === sc.events.length - 1) {
          setStatus("Hazır");
        }
      }, delay);
      delay += 140;
    });
  }

  /** Çıkışta: oturumu kapat ve görünür durumu başlangıca döndür. */
  function reset() {
    stop();
    setMessages([]);
    setMetrics(null);
    setCalibrating(false);
    setCalibrationInfo(null);
    setPipelineState(createInitialTurnState(1, "", "live"));
    setStatus("Hazır");
  }
  return {
    messages,
    status,
    connected,
    metrics,
    calibrating,
    calibrationInfo,
    pipelineState,
    runDemoScenario,
    start,
    stop,
    sendDtmf,
    recalibrate,
    reset,
  };
}
