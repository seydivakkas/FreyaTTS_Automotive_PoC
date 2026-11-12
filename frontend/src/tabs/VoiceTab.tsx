/**
 * FreyaTTS Automotive Cockpit V3 — Görüşme ve Ses Operasyon Kokpiti
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useState } from "react";
import type { Appointment, Health, Vehicle, VoiceMessage, VoiceMetrics } from "../api";
import { dash } from "../ui";
import { AudioPipelineStepper } from "../AudioPipelineStepper";
import { AudioPipelineInspector } from "../AudioPipelineInspector";
import { AudioVisualizer } from "../AudioVisualizer";
import { StageId, PipelineTurnState } from "../pipeline/types";
import { TabName } from "../nav";

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
    calibrating: boolean;
    calibrationInfo: {
      ambient_dbfs?: number;
      noise_gate_dbfs?: number;
      suppression_db?: number;
      message?: string;
    } | null;
    pipelineState?: PipelineTurnState;
    runDemoScenario?: (scenarioId: string) => void;
    stop: () => void;
    sendDtmf: (digit: string) => void;
    recalibrate?: () => void;
  };
  onStart: () => void;
  onNavigateToTab?: (tab: TabName) => void;
};

export function VoiceTab({
  busy,
  health,
  appointments,
  vehicles,
  voice,
  onStart,
  onNavigateToTab,
}: Props) {
  const {
    messages,
    status,
    connected,
    metrics,
    calibrating,
    calibrationInfo,
    pipelineState,
    runDemoScenario,
    stop,
    sendDtmf,
    recalibrate,
  } = voice;

  const [selectedStage, setSelectedStage] = useState<StageId | null>(null);

  const fallbackPipelineState: PipelineTurnState = pipelineState || {
    turnId: 1,
    sessionId: "active-call",
    source: health.demo_mode ? "demo" : "live",
    activeStage: null,
    totalDurationMs: null,
    stages: {
      F0: { stage: "F0", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F1: { stage: "F1", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F2: { stage: "F2", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F3: { stage: "F3", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F4: { stage: "F4", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F5: { stage: "F5", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
      F6: { stage: "F6", status: "idle", durationMs: null, startedAt: null, completedAt: null, metrics: {} },
    },
    traces: [],
  };

  const isSpeaking = status === "Konuşuyor" || status === "synthesizing";

  return (
    <div className="voice-cockpit-layout">
      {/* Katman B: F0–F6 Audio Pipeline Stepper */}
      <AudioPipelineStepper
        pipelineState={fallbackPipelineState}
        selectedStage={selectedStage}
        onSelectStage={(stage) => setSelectedStage((prev) => (prev === stage ? null : stage))}
        onRunDemoScenario={runDemoScenario}
        isStreaming={connected}
      />

      <div className="stats" style={{ marginTop: "14px" }}>
        <article>
          <small>Ses motoru</small>
          <strong>
            {!health.tts?.status
              ? "Bilinmiyor"
              : health.tts.status === "READY"
                ? "Hazır (Leyla #9)"
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

      <div className="voice-main-grid">
        <section className="voice">
          <AudioVisualizer
            isActive={connected}
            isSpeaking={isSpeaking}
            ambientDbfs={calibrationInfo?.ambient_dbfs}
            noiseGateDbfs={calibrationInfo?.noise_gate_dbfs}
          />

          <div className={"orb " + (connected ? "live" : "")}>f</div>
          <span className="pill">{status}</span>
          <h2>Bir randevu ile başlayın.</h2>
          <p>
            Adınızı, aracınızın marka modelini söyleyin.
            <br />
            Asistan müsait saatleri sunar ve onayınızı ister.
          </p>

          <div className="actions">
            {!connected ? (
              <button
                type="button"
                className="primary"
                onClick={onStart}
                disabled={busy || health.tts?.status !== "READY"}
              >
                Mikrofonla görüşme başlat
              </button>
            ) : (
              <button type="button" className="danger" onClick={stop}>
                Görüşmeyi sonlandır
              </button>
            )}
          </div>
          <small className="muted">
            Mikrofon izni gerekir. Ham ses kaydı varsayılan olarak kapalıdır.
          </small>

          {connected && calibrating && (
            <div
              style={{
                margin: "14px auto 0",
                padding: "10px 16px",
                background: "rgba(2, 132, 199, 0.15)",
                border: "1px solid #0284c7",
                borderRadius: "8px",
                maxWidth: "460px",
                textAlign: "center",
              }}
            >
              <div
                style={{
                  fontWeight: "bold",
                  fontSize: "14px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "8px",
                }}
              >
                <span
                  style={{
                    display: "inline-block",
                    width: "10px",
                    height: "10px",
                    borderRadius: "50%",
                    background: "#38bdf8",
                    animation: "pulse 1.5s infinite",
                  }}
                />
                🛡️ Ortam Gürültüsü Kalibre Ediliyor...
              </div>
              <p style={{ margin: "6px 0 0", fontSize: "12px", color: "#bae6fd" }}>
                Lütfen 1-2 saniye sessiz kalın. Oda ses profili çıkarılıyor ve gürültü kalkanı
                kilitleniyor.
              </p>
            </div>
          )}

          {connected && !calibrating && calibrationInfo && (
            <div
              style={{
                margin: "14px auto 0",
                padding: "8px 14px",
                background: "#1e293b",
                border: "1px solid #334155",
                borderRadius: "8px",
                maxWidth: "420px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "8px",
                fontSize: "12px",
                color: "#94a3b8",
              }}
            >
              <div>
                <span style={{ color: "#22c55e", fontWeight: "bold" }}>
                  🛡️ Gürültü Kalkanı Aktif
                </span>
                <div style={{ fontSize: "11px", color: "#64748b" }}>
                  Oda Tabanı: {calibrationInfo.ambient_dbfs?.toFixed(1) ?? "-"} dBFS · Eşik:{" "}
                  {calibrationInfo.noise_gate_dbfs?.toFixed(1) ?? "-"} dBFS
                </div>
              </div>
              {recalibrate && (
                <button
                  type="button"
                  onClick={recalibrate}
                  style={{
                    padding: "4px 8px",
                    fontSize: "11px",
                    background: "#334155",
                    color: "#f8fafc",
                    border: "1px solid #475569",
                    borderRadius: "4px",
                    cursor: "pointer",
                  }}
                >
                  🔄 Yeniden Kalibre Et
                </button>
              )}
            </div>
          )}

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
            <div
              style={{
                marginTop: "16px",
                padding: "12px",
                background: "#1e293b",
                borderRadius: "8px",
                maxWidth: "260px",
                margin: "16px auto 0",
              }}
            >
              <div
                style={{
                  fontSize: "12px",
                  color: "#94a3b8",
                  marginBottom: "8px",
                  fontWeight: "bold",
                }}
              >
                📞 DTMF Tuş Takımı (Sıfır Gecikme)
              </div>
              <div
                style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "6px" }}
              >
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
            </div>
          )}
        </section>

        <section className="feed" aria-label="Görüşme akışı">
          <h2>Canlı konuşma</h2>
          {messages.length === 0 && (
            <p className="muted">Görüşme başladığında konuşma burada görünecek.</p>
          )}
          {messages.map((m, i) => (
            <div key={i} className={"bubble " + m.role}>
              <span className="role">{m.role === "user" ? "siz" : "FREYA"}</span>
              <p>{m.text}</p>
            </div>
          ))}
        </section>
      </div>

      {/* Katman C: Inspector Drawer */}
      {selectedStage && (
        <AudioPipelineInspector
          selectedStage={selectedStage}
          pipelineState={fallbackPipelineState}
          onClose={() => setSelectedStage(null)}
          onNavigateToTab={onNavigateToTab}
        />
      )}
    </div>
  );
}
