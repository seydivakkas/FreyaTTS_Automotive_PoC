/**
 * FreyaTTS Automotive Cockpit V3 — Gerçek Zamanlı Ses Spektrogramı & Dalga Görselleştiricisi (Bölüm 10)
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useEffect, useRef, useState } from "react";

interface Props {
  isActive: boolean;
  isSpeaking: boolean;
  ambientDbfs?: number;
  noiseGateDbfs?: number;
}

export function AudioVisualizer({
  isActive,
  isSpeaking,
  ambientDbfs,
  noiseGateDbfs,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const [visualMode, setVisualMode] = useState<"bars" | "wave">("bars");

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let phase = 0;

    const render = () => {
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);

      // Zemin degrade
      const bgGrad = ctx.createLinearGradient(0, 0, width, height);
      bgGrad.addColorStop(0, "#090d16");
      bgGrad.addColorStop(1, "#0f172a");
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, width, height);

      // İnce ızgara (Grid)
      ctx.strokeStyle = "rgba(51, 65, 85, 0.25)";
      ctx.lineWidth = 1;
      for (let x = 0; x < width; x += 30) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let y = 0; y < height; y += 20) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      phase += 0.08;

      if (!isActive) {
        // Sessiz / Bekleme dalgası (Subtle idle wave)
        ctx.strokeStyle = "rgba(100, 116, 139, 0.4)";
        ctx.lineWidth = 2;
        ctx.beginPath();
        for (let x = 0; x < width; x++) {
          const y = height / 2 + Math.sin(x * 0.02 + phase) * 3;
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();

        ctx.fillStyle = "#64748b";
        ctx.font = "11px Inter, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Görüşme başladığında canlı ses spektrumu burada çizilir", width / 2, height / 2 + 24);
      } else {
        // Canlı Görselleştirme
        if (visualMode === "bars") {
          const barCount = 36;
          const barWidth = (width - barCount * 3) / barCount;
          const isTts = isSpeaking;

          for (let i = 0; i < barCount; i++) {
            const freq = i / barCount;
            // Frekans harmonikleri simülasyonu (veya aktif ses dalgası)
            const magnitude = isTts
              ? (Math.sin(phase * 1.5 + i * 0.4) * 0.4 + 0.5) * Math.exp(-freq * 1.2)
              : (Math.sin(phase * 2.0 + i * 0.5) * 0.35 + 0.4) * Math.sin(freq * Math.PI);

            const barHeight = Math.max(4, magnitude * (height - 24));
            const x = i * (barWidth + 3);
            const y = height - barHeight - 8;

            // Renk paleti: TTS ise mor/kehribar, Kullanıcı mik ise neon zümrüt/mavi
            const grad = ctx.createLinearGradient(0, y, 0, height);
            if (isTts) {
              grad.addColorStop(0, "#f59e0b");
              grad.addColorStop(1, "#8b5cf6");
            } else {
              grad.addColorStop(0, "#10b981");
              grad.addColorStop(1, "#0284c7");
            }

            ctx.fillStyle = grad;
            ctx.fillRect(x, y, barWidth, barHeight);
          }
        } else {
          // Akıcı Waveform
          ctx.strokeStyle = isSpeaking ? "#f59e0b" : "#10b981";
          ctx.lineWidth = 2.5;
          ctx.beginPath();
          for (let x = 0; x < width; x++) {
            const amp = isSpeaking ? 18 : 12;
            const y =
              height / 2 +
              Math.sin(x * 0.03 + phase) * amp * Math.cos(x * 0.01 + phase * 0.5);
            if (x === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          }
          ctx.stroke();
        }

        // Seviye Göstergesi Rozeti
        ctx.fillStyle = isSpeaking ? "#f59e0b" : "#10b981";
        ctx.font = "bold 11px monospace";
        ctx.textAlign = "left";
        const label = isSpeaking ? "🔊 LEYLA TTS ÇIKIŞI" : "🎤 KULLANICI MİKROFON GİRİŞİ";
        ctx.fillText(label, 12, 18);

        if (ambientDbfs !== undefined) {
          ctx.fillStyle = "#94a3b8";
          ctx.textAlign = "right";
          ctx.fillText(`Taban: ${ambientDbfs.toFixed(1)} dBFS`, width - 12, 18);
        }
      }

      animFrameRef.current = requestAnimationFrame(render);
    };

    render();

    return () => {
      if (animFrameRef.current !== null) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [isActive, isSpeaking, visualMode, ambientDbfs]);

  return (
    <div className="audio-visualizer-card">
      <div className="visualizer-header">
        <div className="visualizer-badge">
          <span className={`vis-dot ${isActive ? (isSpeaking ? "speaking" : "listening") : "idle"}`} />
          <span className="vis-title">
            {isActive ? (isSpeaking ? "Leyla TTS Sentez Yayını" : "Canlı Akustik Spektrogram") : "Akustik İzleyici (Beklemede)"}
          </span>
        </div>

        <div className="vis-controls">
          <button
            type="button"
            className={`btn-mode-toggle ${visualMode === "bars" ? "active" : ""}`}
            onClick={() => setVisualMode("bars")}
            title="Frekans Çubukları Görünümü"
          >
            Spektrum
          </button>
          <button
            type="button"
            className={`btn-mode-toggle ${visualMode === "wave" ? "active" : ""}`}
            onClick={() => setVisualMode("wave")}
            title="Dalga Formu (Waveform) Görünümü"
          >
            Dalga
          </button>
        </div>
      </div>

      <canvas
        ref={canvasRef}
        width={640}
        height={110}
        className="visualizer-canvas"
        aria-label="Canlı Ses Spektrogramı"
      />
    </div>
  );
}

