/**
 * FreyaTTS Automotive Cockpit — VoiceWaveformBar
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 * 
 * Kompakt (28-32px), pasif ses dalgası görselleştiricisi.
 * Asla bağımsız getUserMedia çağırmaz; yalnızca sağlanan stream'i analiz eder
 * veya konuşma durumunda canlı nöral dalga formu üretir.
 */

import React, { useEffect, useRef } from "react";

interface Props {
  isConnected: boolean;
  isSpeaking: boolean;
  mediaStream?: MediaStream | null;
  className?: string;
}

export function VoiceWaveformBar({ isConnected, isSpeaking, mediaStream, className = "" }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);

  useEffect(() => {
    if (!mediaStream) {
      if (sourceRef.current) {
        try { sourceRef.current.disconnect(); } catch {}
        sourceRef.current = null;
      }
      return;
    }

    try {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = audioCtxRef.current || new AudioCtx();
      audioCtxRef.current = ctx;
      if (ctx.state === "suspended") {
        ctx.resume().catch(() => {});
      }

      const analyser = ctx.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.8;
      analyserRef.current = analyser;

      const source = ctx.createMediaStreamSource(mediaStream);
      source.connect(analyser);
      sourceRef.current = source;
    } catch (err) {
      console.warn("VoiceWaveformBar: AudioContext bağlanamadı:", err);
    }

    return () => {
      if (sourceRef.current) {
        try { sourceRef.current.disconnect(); } catch {}
        sourceRef.current = null;
      }
    };
  }, [mediaStream]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let phase = 0;

    const render = () => {
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      const isLive = isConnected || isSpeaking;
      let energy = 0;

      if (analyserRef.current && mediaStream) {
        const data = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(data);
        const sum = data.reduce((a, b) => a + b, 0);
        energy = sum / (data.length * 255);
      } else if (isSpeaking) {
        energy = 0.4 + 0.3 * Math.sin(phase * 4);
      } else if (isConnected) {
        energy = 0.12 + 0.08 * Math.sin(phase * 2);
      }

      // Bar tipi kompakt ekolayzer dalgası (24 bar)
      const numBars = 32;
      const barWidth = 3;
      const barSpacing = Math.max(2, (w - numBars * barWidth) / (numBars - 1));

      for (let i = 0; i < numBars; i++) {
        const centerDist = 1 - Math.abs(i - numBars / 2) / (numBars / 2);
        const wave = Math.sin(phase * 3 + i * 0.4);
        const barH = isLive
          ? Math.max(3, (energy * h * 0.85 * centerDist * (0.6 + 0.4 * wave)))
          : 2;

        const x = i * (barWidth + barSpacing);
        const y = (h - barH) / 2;

        if (isSpeaking) {
          // Leyla ses sentezi: Turkuaz - Mavi
          ctx.fillStyle = `rgba(56, 189, 248, ${0.4 + centerDist * 0.6})`;
        } else if (isConnected && energy > 0.15) {
          // Müşteri konuşuyor: Zümrüt Yeşili
          ctx.fillStyle = `rgba(52, 211, 153, ${0.4 + centerDist * 0.6})`;
        } else if (isConnected) {
          // Dinleme / bekleme: Yumuşak yeşil
          ctx.fillStyle = `rgba(16, 185, 129, 0.4)`;
        } else {
          // Bağlı değil: Koyu gri
          ctx.fillStyle = `rgba(71, 85, 105, 0.3)`;
        }

        ctx.beginPath();
        ctx.roundRect(x, y, barWidth, barH, 2);
        ctx.fill();
      }

      phase += 0.05;
      animRef.current = requestAnimationFrame(render);
    };

    render();

    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [isConnected, isSpeaking, mediaStream]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        background: "rgba(15, 23, 42, 0.75)",
        border: "1px solid rgba(255, 255, 255, 0.08)",
        borderRadius: "20px",
        padding: "3px 12px",
        height: "32px",
      }}
      className={className}
    >
      <span
        style={{
          width: "7px",
          height: "7px",
          borderRadius: "50%",
          background: isSpeaking ? "#38bdf8" : isConnected ? "#10b981" : "#64748b",
          boxShadow: isConnected ? (isSpeaking ? "0 0 8px #38bdf8" : "0 0 8px #10b981") : "none",
        }}
      />
      <canvas
        ref={canvasRef}
        width={180}
        height={24}
        style={{ width: "140px", height: "20px", display: "block" }}
      />
      <span
        style={{
          fontSize: "10.5px",
          fontFamily: "monospace",
          fontWeight: 600,
          color: isSpeaking ? "#38bdf8" : isConnected ? "#34d399" : "#64748b",
          whiteSpace: "nowrap",
        }}
      >
        {isSpeaking ? "LEYLA YANITLIYOR" : isConnected ? "CANLI DİNLİYOR" : "BEKLEMEDE"}
      </span>
    </div>
  );
}
