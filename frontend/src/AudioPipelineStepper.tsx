/**
 * FreyaTTS Automotive Cockpit V3 — F0–F6 Audio Pipeline Stepper (Katman B)
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React from "react";
import {
  StageId,
  STAGE_DEFINITIONS,
  PipelineTurnState,
  TelemetrySource,
} from "./pipeline/types";

interface Props {
  pipelineState: PipelineTurnState;
  selectedStage: StageId | null;
  onSelectStage: (stage: StageId) => void;
  onRunDemoScenario?: (scenarioId: string) => void;
  isStreaming?: boolean;
}

export function AudioPipelineStepper({
  pipelineState,
  selectedStage,
  onSelectStage,
  onRunDemoScenario,
  isStreaming = false,
}: Props) {
  const stageIds: StageId[] = ["F0", "F1", "F2", "F3", "F4", "F5", "F6"];

  const sumDurations = stageIds.reduce((acc, id) => {
    const d = pipelineState.stages[id]?.durationMs;
    return d ? acc + d : acc;
  }, 0);

  return (
    <section className="pipeline-stepper-container" aria-label="F0–F6 Ses İşleme Hattı">
      <div className="pipeline-top-bar">
        <div className="pipeline-title-box">
          <span className="pipeline-pulse-icon" />
          <h2 className="pipeline-title">F0–F6 SES İŞLEME VE YAPAY ZEKÂ HATTI</h2>
          <span className={`telemetry-source-tag source-${pipelineState.source}`}>
            {pipelineState.source.toUpperCase()}
          </span>
          {isStreaming && <span className="streaming-badge">CANLI AKIŞ ⚡</span>}
        </div>

        <div className="pipeline-latency-box">
          <span className="latency-label">Ölçülen Tur Süresi:</span>
          <span className="latency-value">
            {sumDurations > 0 ? `${sumDurations.toFixed(1)} ms` : "—"}
          </span>
          <span className="latency-target" title="SLA Gecikme Bütçesi Hedefi">
            (SLA: &lt;600 ms)
          </span>

          {onRunDemoScenario && (
            <div className="scenario-quick-actions">
              <button
                type="button"
                className="btn-scenario"
                onClick={() => onRunDemoScenario("booking_success")}
                title="Başarılı randevu oluşturma F0–F6 telemetrisini simüle et"
              >
                🎬 Test: Randevu
              </button>
              <button
                type="button"
                className="btn-scenario"
                onClick={() => onRunDemoScenario("barge_in_interruption")}
                title="Barge-In söz kesme ve bellek budama telemetrisini simüle et"
              >
                ⚡ Test: Barge-In
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="pipeline-stages-track">
        {stageIds.map((id, index) => {
          const def = STAGE_DEFINITIONS[id];
          const runtime = pipelineState.stages[id] || { status: "idle", durationMs: null };
          const isSelected = selectedStage === id;
          const status = runtime.status;

          return (
            <React.Fragment key={id}>
              <button
                type="button"
                className={`stage-card status-${status} ${isSelected ? "selected" : ""}`}
                onClick={() => onSelectStage(id)}
                aria-selected={isSelected}
                title={`${def.code} ${def.name}: ${def.technology}. İncelemek için tıklayın.`}
              >
                <div className="stage-card-header">
                  <span className="stage-code">{def.code}</span>
                  <span className={`status-led led-${status}`} />
                </div>

                <div className="stage-card-name">{def.name}</div>
                <div className="stage-card-desc">{def.shortDesc}</div>

                <div className="stage-card-footer">
                  <span className="stage-latency">
                    {runtime.durationMs !== null
                      ? `${runtime.durationMs.toFixed(1)} ms`
                      : status === "running"
                      ? "..."
                      : `~${def.targetLatencyMs} ms`}
                  </span>
                  <span className="inspector-hint">🔍 İncele</span>
                </div>
              </button>

              {index < stageIds.length - 1 && (
                <div className={`stage-connector ${status === "completed" ? "completed" : ""}`}>
                  <span className="connector-arrow">→</span>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </section>
  );
}

