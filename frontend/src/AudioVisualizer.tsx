/**
 * FreyaTTS Automotive Cockpit V3 — Gerçek Zamanlı Ses Spektrogramı & F0/F1 Akustik Kapı Görselleştiricisi
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  Mic, MicOff, Radio, Lock, Headphones, ShieldCheck, Zap, AlertTriangle, Send
} from "lucide-react";

export interface RejectedNoiseEvent {
  id: string;
  time: string;
  reason: string;
  text: string;
  metrics: string;
}

interface AudioVisualizerProps {
  isActive: boolean;
  isSpeaking: boolean;
  mediaStream?: MediaStream | null;
  ambientDbfs?: number;
  noiseGateDbfs?: number;
  onVoiceInputSubmit?: (text: string) => void;
  onBargeIn?: () => void;
  activeStageCode?: string;
  onToggleSession?: () => void;
}

export function AudioVisualizer({
  isActive,
  isSpeaking,
  mediaStream,
  ambientDbfs,
  noiseGateDbfs,
  onVoiceInputSubmit,
  onBargeIn,
  activeStageCode = "F0",
  onToggleSession,
}: AudioVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animFrameRef = useRef<number | null>(null);

  // F0 & F1 DSP Controls State
  const [nearFieldMode, setNearFieldMode] = useState(true);
  const [hardGateEnabled, setHardGateEnabled] = useState(true);
  const [isPushToTalk, setIsPushToTalk] = useState(false);
  const [vadThresholdDb, setVadThresholdDb] = useState(noiseGateDbfs ?? -24);
  const [spectralThreshold, setSpectralThreshold] = useState(55);
  const [spectralVoiceRatio, setSpectralVoiceRatio] = useState(68);
  const [rmsDb, setRmsDb] = useState(ambientDbfs ?? -48.0);
  const [hangoverMs, setHangoverMs] = useState(850);
  const [hangoverProgress, setHangoverProgress] = useState(0);
  const [isGateOpenWindow, setIsGateOpenWindow] = useState(false);
  const [bargeInFlash, setBargeInFlash] = useState(false);
  const [manualInput, setManualInput] = useState("");
  const [micActiveLocal, setMicActiveLocal] = useState(false);
  const [micError, setMicError] = useState("");

  const [rejectedEvents, setRejectedEvents] = useState<RejectedNoiseEvent[]>([
    {
      id: "rej_1",
      time: "14:21:54",
      reason: "Düşük dBFS (Uzak Konuşma)",
      text: "yan masadaki müşteri sesleri...",
      metrics: "-36.4 dBFS | %61 Spektral"
    }
  ]);

  // Audio Context & Analyser Refs
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const isLocalStreamRef = useRef(false);
  const isPushToTalkRef = useRef(false);
  const lastGateOpenTimeRef = useRef(0);
  const hangoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hangoverIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    isPushToTalkRef.current = isPushToTalk;
  }, [isPushToTalk]);

  // Setup / teardown Web Audio API for Near-Field DSP + FFT
  const startMicCapture = useCallback(async (externalStream?: MediaStream | null) => {
    try {
      setMicError("");
      let stream: MediaStream;
      if (externalStream) {
        stream = externalStream;
        isLocalStreamRef.current = false;
      } else if (mediaStream) {
        stream = mediaStream;
        isLocalStreamRef.current = false;
      } else {
        // Asla harici oturumdan bağımsız mikrofonu meşgul etme
        return;
      }
      mediaStreamRef.current = stream;

      const AudioCtxClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const audioCtx = new AudioCtxClass();
      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }
      audioCtxRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.72;

      if (nearFieldMode) {
        // F0 120Hz HPF + 2.1kHz presence peak + 3.8kHz LPF + compressor
        const hpf = audioCtx.createBiquadFilter();
        hpf.type = "highpass";
        hpf.frequency.value = 120;

        const presence = audioCtx.createBiquadFilter();
        presence.type = "peaking";
        presence.frequency.value = 2100;
        presence.Q.value = 1.25;
        presence.gain.value = 5.0;

        const lpf = audioCtx.createBiquadFilter();
        lpf.type = "lowpass";
        lpf.frequency.value = 3800;

        const compressor = audioCtx.createDynamicsCompressor();
        compressor.threshold.value = -24;
        compressor.knee.value = 8;
        compressor.ratio.value = 4;
        compressor.attack.value = 0.003;
        compressor.release.value = 0.15;

        source.connect(hpf);
        hpf.connect(presence);
        presence.connect(lpf);
        lpf.connect(compressor);
        compressor.connect(analyser);
      } else {
        source.connect(analyser);
      }

      analyserRef.current = analyser;
      setMicActiveLocal(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      let userFriendlyMsg = msg;
      if (msg.includes("Could not start audio source") || msg.includes("NotReadableError")) {
        userFriendlyMsg = "Cihaz meşgul veya başka bir uygulama (Teams, Zoom, Discord vb.) tarafından kullanılıyor olabilir. Windows mikrofon izinlerini kontrol edin veya aşağıdaki metin kutusundan yazarak teste devam edin.";
      } else if (msg.includes("Permission denied") || msg.includes("NotAllowedError")) {
        userFriendlyMsg = "Mikrofon erişim izni verilmedi. Tarayıcı adres çubuğundaki kilit simgesinden izin verin.";
      } else if (msg.includes("NotFoundError") || msg.includes("DevicesNotFoundError")) {
        userFriendlyMsg = "Sistemde mikrofon bulunamadı. Lütfen bir ses giriş cihazı bağlayın.";
      }
      setMicError(`Mikrofon erişimi sağlanamadı: ${userFriendlyMsg}`);
      setMicActiveLocal(false);
    }
  }, [mediaStream, nearFieldMode]);

  const stopMicCapture = useCallback(() => {
    if (mediaStreamRef.current) {
      if (isLocalStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      }
      mediaStreamRef.current = null;
    }
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    analyserRef.current = null;
    setMicActiveLocal(false);
  }, []);

  // When mediaStream prop changes or parent isActive changes
  useEffect(() => {
    if (mediaStream) {
      startMicCapture(mediaStream);
    } else if (isActive && !micActiveLocal) {
      startMicCapture();
    } else if (!isActive && !mediaStream && micActiveLocal) {
      stopMicCapture();
    }
    return () => {
      stopMicCapture();
    };
  }, [isActive, mediaStream]);

  // Telemetry & Gate calculation timer
  useEffect(() => {
    const timer = setInterval(() => {
      if (analyserRef.current && micActiveLocal) {
        const pcm = new Float32Array(analyserRef.current.fftSize);
        analyserRef.current.getFloatTimeDomainData(pcm);
        let sumSq = 0;
        for (let i = 0; i < pcm.length; i++) {
          sumSq += pcm[i] * pcm[i];
        }
        const rms = Math.sqrt(sumSq / pcm.length);
        const db = Math.max(-60, Math.min(0, Math.round(20 * Math.log10(rms + 1e-6) * 10) / 10));
        setRmsDb(db);

        // Calculate 300Hz - 3400Hz Human Voice Band Spectral Ratio
        const freqBins = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(freqBins);
        const sampleRate = audioCtxRef.current?.sampleRate || 48000;
        const binHz = sampleRate / analyserRef.current.fftSize;
        const startBin = Math.max(1, Math.floor(300 / binHz));
        const endBin = Math.min(freqBins.length - 1, Math.ceil(3400 / binHz));

        let voiceEnergy = 0;
        let totalEnergy = 0;
        for (let i = 1; i < freqBins.length; i++) {
          totalEnergy += freqBins[i];
          if (i >= startBin && i <= endBin) voiceEnergy += freqBins[i];
        }

        const rawRatio = totalEnergy > 0 ? Math.round((voiceEnergy / totalEnergy) * 100) : 0;
        const ratio = db > -48 ? Math.min(98, Math.max(15, rawRatio)) : 62;
        setSpectralVoiceRatio(ratio);

        const energyPassed = db > vadThresholdDb;
        const spectralPassed = ratio >= spectralThreshold;

        if (energyPassed && spectralPassed) {
          lastGateOpenTimeRef.current = Date.now();
          setIsGateOpenWindow(true);

          // Barge-in check while synthetic voice is speaking
          if (isSpeaking) {
            setBargeInFlash(true);
            onBargeIn?.();
            setTimeout(() => setBargeInFlash(false), 1800);
          }
        } else {
          const windowStillOpen = Date.now() - lastGateOpenTimeRef.current <= 1500;
          setIsGateOpenWindow(windowStillOpen);
        }
      } else {
        // Idle ambient variation
        setRmsDb((prev) => (isActive ? -32.5 + Math.sin(Date.now() / 400) * 4 : -52.0));
        setSpectralVoiceRatio((prev) => (isActive ? 68 + Math.round(Math.sin(Date.now() / 300) * 8) : 58));
        setIsGateOpenWindow(isPushToTalkRef.current || !hardGateEnabled);
      }
    }, 100);

    return () => clearInterval(timer);
  }, [isActive, micActiveLocal, vadThresholdDb, spectralThreshold, hardGateEnabled, isSpeaking, onBargeIn]);

  // Keyboard [SPACE] PTT Listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const tag = (document.activeElement as HTMLElement)?.tagName;
      const isTyping = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
      if (e.code === "Space" && !isTyping) {
        e.preventDefault();
        if (!e.repeat && !isPushToTalkRef.current) {
          setIsPushToTalk(true);
          lastGateOpenTimeRef.current = Date.now();
          setIsGateOpenWindow(true);
          if (!micActiveLocal) startMicCapture();
        }
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      const tag = (document.activeElement as HTMLElement)?.tagName;
      const isTyping = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
      if (e.code === "Space" && !isTyping && isPushToTalkRef.current) {
        e.preventDefault();
        setIsPushToTalk(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [micActiveLocal, startMicCapture]);

  // 60FPS HTML5 Canvas Drawing Loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let phase = 0;

    const resize = () => {
      const rect = canvas.parentElement?.getBoundingClientRect();
      if (!rect) return;
      canvas.width = rect.width * (window.devicePixelRatio || 1);
      canvas.height = 140 * (window.devicePixelRatio || 1);
      ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
    };
    resize();
    window.addEventListener("resize", resize);

    const freqArray = new Uint8Array(128);
    const timeArray = new Uint8Array(128);

    const render = () => {
      const dpr = window.devicePixelRatio || 1;
      const width = canvas.width / dpr;
      const height = canvas.height / dpr;
      phase += 0.065;

      // Deep dark background
      ctx.fillStyle = "#090d16";
      ctx.fillRect(0, 0, width, height);

      // Acoustic Grid
      ctx.strokeStyle = "rgba(148, 163, 184, 0.08)";
      ctx.lineWidth = 1;
      for (let x = 0; x < width; x += 36) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let y = 0; y < height; y += 28) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      // 300Hz-3400Hz Human Voice Formant Band Highlight
      ctx.fillStyle = isGateOpenWindow ? "rgba(16, 185, 129, 0.06)" : "rgba(2, 132, 199, 0.04)";
      ctx.fillRect(width * 0.08, 0, width * 0.58, height);

      const active = isActive || micActiveLocal || isSpeaking;
      if (analyserRef.current && micActiveLocal) {
        analyserRef.current.getByteFrequencyData(freqArray);
        analyserRef.current.getByteTimeDomainData(timeArray);
      }

      // Dual-Channel FFT Bars
      const barCount = 42;
      const barWidth = (width - 32) / barCount;
      const maxBarH = height * 0.42;

      for (let i = 0; i < barCount; i++) {
        let custAmp = 0.05;
        let leylaAmp = 0.05;

        if (active) {
          if (analyserRef.current && micActiveLocal) {
            custAmp = Math.max(0.06, (freqArray[i * 2] || 10) / 255);
          } else {
            custAmp = Math.abs(Math.sin(phase * 1.3 + i * 0.25) * Math.cos(phase * 0.7 - i * 0.12)) * 0.6 + 0.05;
          }

          if (isSpeaking) {
            leylaAmp = Math.abs(Math.cos(phase * 2.1 - i * 0.22) * Math.sin(phase * 1.4 + i * 0.18)) * 0.8 + 0.08;
          }
        }

        const x = 16 + i * barWidth;

        // Top half: Leyla FreyaTTS Output (Neon Emerald #10b981)
        const hLeyla = leylaAmp * maxBarH;
        const gradEmerald = ctx.createLinearGradient(0, height / 2 - hLeyla, 0, height / 2);
        gradEmerald.addColorStop(0, "#34d399");
        gradEmerald.addColorStop(1, "rgba(16, 185, 129, 0.16)");
        ctx.fillStyle = gradEmerald;
        ctx.fillRect(x, height / 2 - hLeyla, barWidth - 3, hLeyla);

        // Bottom half: Customer Mic & F0 DSP Input (Sky Blue #38bdf8)
        const hCust = custAmp * maxBarH;
        const gradSky = ctx.createLinearGradient(0, height / 2, 0, height / 2 + hCust);
        gradSky.addColorStop(0, "rgba(56, 189, 248, 0.18)");
        gradSky.addColorStop(1, isGateOpenWindow ? "#38bdf8" : "#0284c7");
        ctx.fillStyle = gradSky;
        ctx.fillRect(x, height / 2 + 1, barWidth - 3, hCust);
      }

      // Smooth Oscilloscope Waveform
      ctx.beginPath();
      ctx.strokeStyle = bargeInFlash ? "#f59e0b" : isSpeaking ? "#10b981" : isGateOpenWindow ? "#38bdf8" : "#0284c7";
      ctx.lineWidth = 2.2;

      if (analyserRef.current && micActiveLocal) {
        const sliceWidth = width / timeArray.length;
        let x = 0;
        for (let i = 0; i < timeArray.length; i++) {
          const v = timeArray[i] / 128.0;
          const y = (v * height) / 2;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
          x += sliceWidth;
        }
      } else {
        for (let x = 0; x < width; x += 4) {
          const amp = active ? (isSpeaking ? 22 : 14) : 2.5;
          const y = height / 2 + Math.sin(x * 0.035 + phase * 2.2) * Math.cos(x * 0.015 - phase) * amp;
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
      }
      ctx.stroke();

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", resize);
    };
  }, [isActive, micActiveLocal, isSpeaking, isGateOpenWindow, bargeInFlash]);

  const handleSimulateNoise = (type: "babble" | "knock") => {
    const nowStr = new Date().toLocaleTimeString("tr-TR", { hour12: false });
    if (type === "babble") {
      setRejectedEvents((prev) => [
        {
          id: `rej_${Date.now()}`,
          time: nowStr,
          reason: "F₁ Düşük Enerji (Arka Plan Konuşması)",
          text: "yan masadaki müşteri sesleri...",
          metrics: `-35.2 dBFS < ${vadThresholdDb} dBFS`,
        },
        ...prev.slice(0, 5)
      ]);
    } else {
      setRejectedEvents((prev) => [
        {
          id: `rej_${Date.now()}`,
          time: nowStr,
          reason: "F₁ Düşük Spektral Oran (Masa/Bardak Tıkırtısı)",
          text: "[Darbeli Gürültü / Tıkırtı]",
          metrics: `-18.4 dBFS | %27 Spektral < %${spectralThreshold}`,
        },
        ...prev.slice(0, 5)
      ]);
    }
  };

  const handleManualSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualInput.trim()) return;
    onVoiceInputSubmit?.(manualInput.trim());
    setManualInput("");
  };

  return (
    <div className="av-card-wrapper">
      {/* ÜST MİKROFON, KALABALIK ORTAM DSP & F1 SERT KAPI KONTROL BARI */}
      <div className="av-top-bar">
        <div className="av-btn-group">
          {/* Ana Mikrofon Başlat/Durdur */}
          <button
            type="button"
            onClick={() => {
              if (onToggleSession) {
                onToggleSession();
              } else {
                if (micActiveLocal || isActive) {
                  stopMicCapture();
                } else {
                  startMicCapture();
                }
              }
            }}
            className={`av-btn ${(isActive || micActiveLocal) ? "av-btn-danger" : "av-btn-primary"}`}
            title="Mikrofon girişini başlat / durdur"
          >
            {(isActive || micActiveLocal) ? <Mic className="w-4 h-4" /> : <MicOff className="w-4 h-4" />}
            <span>{(isActive || micActiveLocal) ? "GÖRÜŞMEYİ DURDUR" : "🎙️ MİKROFONU BAŞLAT"}</span>
          </button>

          {/* Kalabalık Ortam / Yakın Mikrofon DSP */}
          <button
            type="button"
            onClick={() => setNearFieldMode((p) => !p)}
            className={`av-btn ${nearFieldMode ? "av-btn-active-emerald" : "av-btn-outline"}`}
            title="F0 120Hz HPF + 2.1kHz Formant Güçlendirme + Dinamik Kompresör"
          >
            <Headphones className="w-3.5 h-3.5" />
            <span>{nearFieldMode ? "🎧 Kalabalık DSP: AKTİF" : "🎧 Kalabalık DSP: KAPALI"}</span>
          </button>

          {/* F1 Sert Akustik Kapı Kilidi */}
          <button
            type="button"
            onClick={() => setHardGateEnabled((p) => !p)}
            className={`av-btn ${hardGateEnabled ? "av-btn-active-sky" : "av-btn-outline"}`}
            title="Sadece enerji eşiği VE insan sesi spektral oranı (%55) geçilirse kapı açılır"
          >
            <Lock className="w-3.5 h-3.5" />
            <span>{hardGateEnabled ? "🛡️ F₁ Sert Kapı: AKTİF" : "🔓 F₁ Sert Kapı: PASİF"}</span>
          </button>

          {/* Bas-Konuş (PTT / Space) */}
          <button
            type="button"
            onMouseDown={() => {
              setIsPushToTalk(true);
              lastGateOpenTimeRef.current = Date.now();
              setIsGateOpenWindow(true);
              if (!micActiveLocal) startMicCapture();
            }}
            onMouseUp={() => setIsPushToTalk(false)}
            onTouchStart={() => {
              setIsPushToTalk(true);
              lastGateOpenTimeRef.current = Date.now();
              setIsGateOpenWindow(true);
              if (!micActiveLocal) startMicCapture();
            }}
            onTouchEnd={() => setIsPushToTalk(false)}
            className={`av-btn ${isPushToTalk ? "av-btn-active-amber" : "av-btn-outline"}`}
            title="Fareyle basılı tutun veya klavyeden [SPACE] tuşuna basılı tutarak konuşun"
          >
            <Radio className="w-3.5 h-3.5" />
            <span>{isPushToTalk ? "🔴 PTT BASILI (ŞİMDİ KONUŞUN)" : "⌨️ [SPACE] BAS-KONUŞ"}</span>
          </button>
        </div>

        {/* Canlı F1 Akustik Kapı Durum Rozeti */}
        <div className={`av-gate-badge ${isGateOpenWindow || isPushToTalk || !hardGateEnabled ? "gate-open" : "gate-locked"}`}>
          <span className="gate-led" />
          <span>
            F₁ Kapısı: {isPushToTalk ? "PTT AÇIK" : !hardGateEnabled ? "BYPASS" : isGateOpenWindow ? "AÇIK (1.5sn Pencere)" : "KİLİTLİ (Gürültü Koruması)"}
          </span>
        </div>
      </div>

      {micError && (
        <div className="av-alert-error" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "10px", padding: "10px 14px", borderRadius: "8px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", flex: 1 }}>
            <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400" />
            <span style={{ fontSize: "12.5px", lineHeight: 1.4 }}>{micError}</span>
          </div>
          <button
            type="button"
            onClick={() => {
              setMicError("");
              if (onToggleSession && !isActive) {
                onToggleSession();
              } else {
                startMicCapture();
              }
            }}
            style={{
              padding: "6px 12px",
              background: "#1e293b",
              color: "#38bdf8",
              border: "1px solid #334155",
              borderRadius: "6px",
              fontSize: "12px",
              fontWeight: 600,
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            Yeniden Dene ↻
          </button>
        </div>
      )}

      {/* CANLI METRELER, HASSASİYET SÜRGÜLERİ & GÜRÜLTÜ RED LOGU */}
      <div className="av-meters-grid">
        {/* Sol Kolon: RMS Enerji & Spektral Oran */}
        <div className="av-meter-box">
          <div className="av-meter-row">
            <span className="av-meter-label">Mikrofon Girişi (RMS):</span>
            <span className="av-meter-val font-mono">
              {rmsDb.toFixed(1)} dBFS (Eşik: {vadThresholdDb} dBFS)
            </span>
          </div>
          <div className="av-progress-track">
            <div
              className="av-progress-bar bg-sky-500"
              style={{ width: `${Math.min(100, Math.max(5, ((rmsDb + 60) / 60) * 100))}%` }}
            />
          </div>

          <div className="av-meter-row" style={{ marginTop: "8px" }}>
            <span className="av-meter-label">F₁ İnsan Sesi Formant Oranı (300–3400Hz):</span>
            <span className="av-meter-val font-mono">
              %{spectralVoiceRatio} (Hedef: ≥ %{spectralThreshold})
            </span>
          </div>
          <div className="av-progress-track">
            <div
              className={`av-progress-bar ${spectralVoiceRatio >= spectralThreshold ? "bg-emerald-500" : "bg-amber-500"}`}
              style={{ width: `${Math.min(100, Math.max(5, spectralVoiceRatio))}%` }}
            />
          </div>

          {/* Sürgüler */}
          <div className="av-sliders-row">
            <div>
              <div className="av-slider-header">
                <span>VAD Eşik</span>
                <span className="font-mono">{vadThresholdDb} dB</span>
              </div>
              <input
                type="range"
                min={-52}
                max={-14}
                value={vadThresholdDb}
                onChange={(e) => setVadThresholdDb(Number(e.target.value))}
                className="av-range-slider"
              />
            </div>
            <div>
              <div className="av-slider-header">
                <span>Spektral %</span>
                <span className="font-mono">%{spectralThreshold}</span>
              </div>
              <input
                type="range"
                min={30}
                max={80}
                step={5}
                value={spectralThreshold}
                onChange={(e) => setSpectralThreshold(Number(e.target.value))}
                className="av-range-slider"
              />
            </div>
            <div>
              <div className="av-slider-header">
                <span>Hangover</span>
                <span className="font-mono">{hangoverMs} ms</span>
              </div>
              <input
                type="range"
                min={300}
                max={1500}
                step={50}
                value={hangoverMs}
                onChange={(e) => setHangoverMs(Number(e.target.value))}
                className="av-range-slider"
              />
            </div>
          </div>
        </div>

        {/* Sağ Kolon: Reddedilen Gürültü Logu & Test Tetikleyicileri */}
        <div className="av-meter-box">
          <div className="av-log-header">
            <span className="font-bold flex items-center gap-1.5 text-amber-300">
              <ShieldCheck className="w-4 h-4 text-amber-400" />
              F₁ Kapısı Reddedilen Gürültüler ({rejectedEvents.length}):
            </span>
            <div className="av-test-btn-group">
              <button
                type="button"
                onClick={() => handleSimulateNoise("babble")}
                className="av-test-btn"
                title="Kısık sesli uzak konuşma gürültüsünü simüle et"
              >
                +Test: Uzak Konuşma
              </button>
              <button
                type="button"
                onClick={() => handleSimulateNoise("knock")}
                className="av-test-btn"
                title="Düşük spektral oranlı masa tıkırtısı gürültüsünü simüle et"
              >
                +Test: Masa Tıkırtısı
              </button>
            </div>
          </div>

          <div className="av-log-list">
            {rejectedEvents.slice(0, 3).map((ev) => (
              <div key={ev.id} className="av-log-item">
                <span className="text-amber-200 truncate">⛔ {ev.reason}: "{ev.text}"</span>
                <span className="text-slate-500 font-mono shrink-0 ml-1">{ev.metrics}</span>
              </div>
            ))}
          </div>

          {/* Test Cümlesi Girişi */}
          <form onSubmit={handleManualSubmit} className="av-input-form">
            <input
              type="text"
              value={manualInput}
              onChange={(e) => setManualInput(e.target.value)}
              placeholder="Mikrofonla konuşun veya test cümlesi yazıp gönderin..."
              className="av-text-input"
            />
            <button type="submit" className="av-send-btn">
              <Send className="w-3.5 h-3.5" />
              <span>Gönder (F₀→F₆)</span>
            </button>
          </form>
        </div>
      </div>

      {/* 60FPS CANLI DUAL-CHANNEL SPEKTROGRAM & WAVEFORM KARTI */}
      <div className="av-canvas-container">
        <canvas ref={canvasRef} className="av-canvas" aria-label="Canlı Ses Spektrogramı" />

        <div className="av-canvas-badge-top">
          <span className={`av-dot ${isSpeaking ? "animate-ping bg-emerald-400" : "bg-emerald-500"}`} />
          <span>CH-OUT: FreyaTTS Leyla (Sıralı F₄ Chunk Çıkışı)</span>
        </div>

        <div className="av-canvas-badge-bottom">
          <span className={`av-dot ${isGateOpenWindow ? "animate-ping bg-emerald-400" : "bg-sky-400"}`} />
          <span>CH-IN: F₀ DSP & F₁ Spektral Oran: %{spectralVoiceRatio} (300–3400Hz Formant)</span>
        </div>

        {bargeInFlash && (
          <div className="av-barge-in-banner">
            <Zap className="w-4 h-4 text-amber-300" />
            <span>F₁ SPEKTRAL BARGE-IN KESME (Aktif F₄ Chunk Durduruldu)</span>
          </div>
        )}
      </div>
    </div>
  );
}
