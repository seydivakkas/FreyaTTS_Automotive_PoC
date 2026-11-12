/**
 * FreyaTTS Automotive Cockpit V3 — Global Kontrol Çubuğu (Katman A)
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React from "react";
import type { Health } from "./api";

interface Props {
  activeTabTitle: string;
  health: Health;
  busy: boolean;
  onToggleDemoMode: (isDemo: boolean) => void;
  onRefresh: () => void;
  onLogout: () => void;
}

export function CockpitHeader({
  activeTabTitle,
  health,
  busy,
  onToggleDemoMode,
  onRefresh,
  onLogout,
}: Props) {
  const isDemo = Boolean(health.demo_mode);
  const breakerState = health.circuit_breaker?.state || "CLOSED";
  const isHealthy = breakerState === "CLOSED" && health.tts?.status === "READY";

  return (
    <header className="cockpit-header">
      <div className="header-left">
        <div className="tab-eyebrow">EKSPERTİZ KOKPİTİ</div>
        <h1 className="tab-current-title">{activeTabTitle}</h1>
      </div>

      <div className="header-center-health">
        <div className="health-pills-bar" title="Yapay Zekâ ve Donanım Sağlığı">
          <div className={`health-pill ${health.stt?.status === "READY" ? "ready" : "blocked"}`}>
            <span className="pill-dot" />
            <span className="pill-text">ASR: {health.stt?.status === "READY" ? "Whisper" : "Kapalı"}</span>
          </div>

          <div className={`health-pill ${health.ollama?.status === "READY" ? "ready" : "blocked"}`}>
            <span className="pill-dot" />
            <span className="pill-text">LLM: {health.ollama?.status === "READY" ? "Qwen2.5" : "Kapalı"}</span>
          </div>

          <div className={`health-pill ${health.tts?.status === "READY" ? "ready" : "blocked"}`}>
            <span className="pill-dot" />
            <span className="pill-text">TTS: {health.tts?.status === "READY" ? "Leyla ODE" : "Kapalı"}</span>
          </div>

          <div className={`health-pill breaker-${breakerState.toLowerCase()}`}>
            <span className="pill-dot" />
            <span className="pill-text">VRAM / Sigorta: {breakerState}</span>
          </div>
        </div>
      </div>

      <div className="header-right-controls">
        <div className="mode-toggle-box" title="Reel (Canlı) veya Demo Modu">
          <span className={`mode-label ${!isDemo ? "mode-active-reel" : ""}`}>REEL</span>
          <label className="mode-switch" aria-label="Reel veya Demo Veritabanı Geçişi">
            <input
              type="checkbox"
              checked={isDemo}
              disabled={busy}
              onChange={(e) => onToggleDemoMode(e.target.checked)}
            />
            <span className="mode-slider round" />
          </label>
          <span className={`mode-label ${isDemo ? "mode-active-demo" : ""}`}>DEMO</span>
        </div>

        <button
          type="button"
          className="header-btn secondary"
          onClick={onRefresh}
          disabled={busy}
          title="Verileri ve bağlantıları tazele"
        >
          Yenile ↻
        </button>

        <button
          type="button"
          className="header-btn logout-btn"
          onClick={onLogout}
          title="Güvenli Çıkış"
        >
          Çıkış
        </button>
      </div>
    </header>
  );
}

