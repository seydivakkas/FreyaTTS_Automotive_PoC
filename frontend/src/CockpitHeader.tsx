/**
 * FreyaTTS Automotive Cockpit V3 — Global Kontrol Çubuğu (Katman A)
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 * Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlıdır.
 */

import React from "react";
import type { Health } from "./api";
import { RolePerspective, ROLE_PERSPECTIVES } from "./nav";

interface Props {
  activeTabTitle: string;
  perspective?: RolePerspective;
  health: Health;
  busy: boolean;
  onRefresh: () => void;
  onLogout: () => void;
}

export function CockpitHeader({
  activeTabTitle,
  perspective,
  health,
  busy,
  onRefresh,
  onLogout,
}: Props) {
  const isDemo = Boolean(health.demo_mode);
  const breakerState = health.circuit_breaker?.state || "CLOSED";

  return (
    <header className="cockpit-header">
      <div className="header-left" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <h1 className="tab-current-title" style={{ fontSize: 16, fontWeight: 800, margin: 0, color: "#f8fafc", whiteSpace: "nowrap" }}>
          {activeTabTitle}
        </h1>
        {perspective && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 7px",
              borderRadius: 4,
              background: "rgba(56, 189, 248, 0.15)",
              color: "#38bdf8",
              border: "1px solid rgba(56, 189, 248, 0.3)",
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              whiteSpace: "nowrap",
            }}
            title={ROLE_PERSPECTIVES[perspective]?.description}
          >
            {ROLE_PERSPECTIVES[perspective]?.icon} {ROLE_PERSPECTIVES[perspective]?.label}
          </span>
        )}
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            padding: "2px 7px",
            borderRadius: 4,
            background: isDemo ? "rgba(245, 158, 11, 0.15)" : "rgba(16, 185, 129, 0.15)",
            color: isDemo ? "#fbbf24" : "#34d399",
            border: isDemo ? "1px solid rgba(245, 158, 11, 0.3)" : "1px solid rgba(16, 185, 129, 0.3)",
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            whiteSpace: "nowrap",
          }}
        >
          <span
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: isDemo ? "#fbbf24" : "#34d399",
            }}
          />
          {isDemo ? "DEMO MODU" : "CANLI REEL MOD"}
        </span>
      </div>

      <div className="header-center-health">
        <div className="health-pills-bar" title="Yapay Zekâ ve Donanım Sağlığı" style={{ padding: "2px 6px", gap: 6 }}>
          <div className={`health-pill ${health.stt?.status === "READY" ? "ready" : "blocked"}`} style={{ padding: "2px 7px", fontSize: 10.5 }}>
            <span className="pill-dot" style={{ width: 5, height: 5 }} />
            <span className="pill-text">ASR: {health.stt?.status === "READY" ? "Whisper" : "Kapalı"}</span>
          </div>

          <div className={`health-pill ${health.ollama?.status === "READY" ? "ready" : "blocked"}`} style={{ padding: "2px 7px", fontSize: 10.5 }}>
            <span className="pill-dot" style={{ width: 5, height: 5 }} />
            <span className="pill-text">LLM: {health.ollama?.status === "READY" ? "Qwen2.5" : "Kapalı"}</span>
          </div>

          <div className={`health-pill ${health.tts?.status === "READY" ? "ready" : "blocked"}`} style={{ padding: "2px 7px", fontSize: 10.5 }}>
            <span className="pill-dot" style={{ width: 5, height: 5 }} />
            <span className="pill-text">TTS: {health.tts?.status === "READY" ? "Leyla ODE" : "Kapalı"}</span>
          </div>

          <div
            className={`health-pill ${health.telephony?.simulated ? "simulated" : health.telephony?.connected ? "ready" : "blocked"}`}
            style={{ padding: "2px 7px", fontSize: 10.5 }}
            title={
              health.telephony?.simulated
                ? "Fiziksel Asterisk PBX bağlı değil (Mock AMI Simülasyonu)"
                : health.telephony?.connected
                  ? "Gerçek Asterisk PBX AMI Bağlı"
                  : "Santral Kapalı"
            }
          >
            <span className="pill-dot" style={{ width: 5, height: 5 }} />
            <span className="pill-text">
              PBX: {health.telephony?.simulated ? "Simüle" : health.telephony?.connected ? "Bağlı" : "Kapalı"}
            </span>
          </div>

          <div className={`health-pill breaker-${breakerState.toLowerCase()}`} style={{ padding: "2px 7px", fontSize: 10.5 }}>
            <span className="pill-dot" style={{ width: 5, height: 5 }} />
            <span className="pill-text">VRAM: {breakerState}</span>
          </div>
        </div>
      </div>

      <div className="header-right-controls" style={{ gap: 8 }}>
        <button
          type="button"
          className="header-btn secondary"
          onClick={onRefresh}
          disabled={busy}
          title="Verileri ve bağlantıları tazele"
          style={{ padding: "4px 10px", fontSize: 11 }}
        >
          {busy ? "..." : "Yenile ↻"}
        </button>

        <button
          type="button"
          className="header-btn logout-btn"
          onClick={onLogout}
          title="Güvenli Çıkış"
          style={{ padding: "4px 10px", fontSize: 11 }}
        >
          Çıkış
        </button>
      </div>
    </header>
  );
}
