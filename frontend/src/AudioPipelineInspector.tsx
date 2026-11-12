/**
 * FreyaTTS Automotive Cockpit V3 — Engineering Inspector Drawer (Bölüm 9)
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useState } from "react";
import {
  StageId,
  STAGE_DEFINITIONS,
  PipelineTurnState,
} from "./pipeline/types";
import { TabName } from "./nav";

interface Props {
  selectedStage: StageId;
  pipelineState: PipelineTurnState;
  onClose: () => void;
  onNavigateToTab?: (tab: TabName) => void;
}

type InspectorTab = "overview" | "parameters" | "intermediate" | "metrics" | "traces";

export function AudioPipelineInspector({
  selectedStage,
  pipelineState,
  onClose,
  onNavigateToTab,
}: Props) {
  const [activeTab, setActiveTab] = useState<InspectorTab>("overview");
  const def = STAGE_DEFINITIONS[selectedStage];
  const runtime = pipelineState.stages[selectedStage] || {
    status: "idle",
    durationMs: null,
    metrics: {},
  };

  const getRelatedTab = (stage: StageId): TabName | null => {
    switch (stage) {
      case "F0":
        return "Araç İçi DSP & Gürültü";
      case "F1":
      case "F2":
        return "A/B Test & İnce Ayar";
      case "F3":
        return "Supervisor Kalite";
      case "F4":
        return "Sözlük";
      case "F5":
      case "F6":
        return "Ses laboratuvarı";
      default:
        return null;
    }
  };

  const relatedTab = getRelatedTab(selectedStage);

  return (
    <aside className="pipeline-inspector-drawer" aria-label={`${def.code} Mühendislik Çekmecesi`}>
      <div className="inspector-header">
        <div className="inspector-title-group">
          <span className="inspector-code-pill">{def.code}</span>
          <div className="inspector-titles">
            <h3 className="inspector-title">{def.name}</h3>
            <p className="inspector-subtitle">{def.technology}</p>
          </div>
        </div>

        <div className="inspector-header-actions">
          {relatedTab && onNavigateToTab && (
            <button
              type="button"
              className="btn-jump-tab"
              onClick={() => onNavigateToTab(relatedTab)}
              title={`${relatedTab} sekmesine git`}
            >
              Paneli Aç ↗
            </button>
          )}
          <button
            type="button"
            className="inspector-close-btn"
            onClick={onClose}
            aria-label="Çekmeceyi Kapat"
          >
            ✕
          </button>
        </div>
      </div>

      <nav className="inspector-subtabs">
        <button
          type="button"
          className={activeTab === "overview" ? "active" : ""}
          onClick={() => setActiveTab("overview")}
        >
          Genel Bakış
        </button>
        <button
          type="button"
          className={activeTab === "parameters" ? "active" : ""}
          onClick={() => setActiveTab("parameters")}
        >
          Parametreler
        </button>
        <button
          type="button"
          className={activeTab === "intermediate" ? "active" : ""}
          onClick={() => setActiveTab("intermediate")}
        >
          Ara Veri
        </button>
        <button
          type="button"
          className={activeTab === "metrics" ? "active" : ""}
          onClick={() => setActiveTab("metrics")}
        >
          Metrikler
        </button>
        <button
          type="button"
          className={activeTab === "traces" ? "active" : ""}
          onClick={() => setActiveTab("traces")}
        >
          İzler & Loglar
        </button>
      </nav>

      <div className="inspector-content">
        {activeTab === "overview" && (
          <div className="tab-pane overview-pane">
            <div className="inspector-stat-grid">
              <div className="stat-card">
                <span className="stat-label">Durum</span>
                <span className={`stat-value status-${runtime.status}`}>
                  {runtime.status.toUpperCase()}
                </span>
              </div>
              <div className="stat-card">
                <span className="stat-label">Ölçülen Süre</span>
                <span className="stat-value">
                  {runtime.durationMs !== null ? `${runtime.durationMs.toFixed(1)} ms` : "—"}
                </span>
              </div>
              <div className="stat-card">
                <span className="stat-label">SLA Hedefi</span>
                <span className="stat-value">{def.targetLatencyMs} ms</span>
              </div>
              <div className="stat-card">
                <span className="stat-label">Kaynak</span>
                <span className="stat-value">{pipelineState.source.toUpperCase()}</span>
              </div>
            </div>

            <div className="info-block">
              <h4>Girdi Sözleşmesi</h4>
              <p className="code-font">{def.inputDescription}</p>
            </div>

            <div className="info-block">
              <h4>Çıktı Sözleşmesi</h4>
              <p className="code-font">{def.outputDescription}</p>
            </div>
          </div>
        )}

        {activeTab === "parameters" && (
          <div className="tab-pane parameters-pane">
            <h4>Aktif Aşama Konfigürasyonu</h4>
            <div className="params-table-wrapper">
              <table className="params-table">
                <thead>
                  <tr>
                    <th>Parametre</th>
                    <th>Değer</th>
                    <th>Erişim</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedStage === "F0" && (
                    <>
                      <tr><td>HPF Kesim Frekansı</td><td>120 Hz (24 dB/oct)</td><td><span className="tag-ro">Kilitli</span></td></tr>
                      <tr><td>Spektral Gürültü Tabanı</td><td>-18 dBFS</td><td><span className="tag-ro">Kilitli</span></td></tr>
                      <tr><td>Soft AGC Hedef Seviyesi</td><td>-16 dBFS</td><td><span className="tag-ro">Kilitli</span></td></tr>
                      <tr><td>Örnekleme Hızı</td><td>8 kHz SLIN16 ➔ 16 kHz</td><td><span className="tag-ro">Sabit</span></td></tr>
                    </>
                  )}
                  {selectedStage === "F1" && (
                    <>
                      <tr><td>VAD Eşik Değeri</td><td>0.55</td><td><span className="tag-ro">Kilitli</span></td></tr>
                      <tr><td>Lookback Tamponu</td><td>300 ms (Ring Buffer)</td><td><span className="tag-ro">Kilitli</span></td></tr>
                      <tr><td>Barge-In Kesim Mekanizması</td><td>2-Aşamalı Soft/Commit</td><td><span className="tag-ro">Kilitli</span></td></tr>
                      <tr><td>DTMF Filtresi</td><td>Goertzel In-Band Notch</td><td><span className="tag-ro">Aktif</span></td></tr>
                    </>
                  )}
                  {selectedStage === "F2" && (
                    <>
                      <tr><td>ASR Akustik Model</td><td>Faster-Whisper large-v3-turbo</td><td><span className="tag-ro">CUDA</span></td></tr>
                      <tr><td>Dil Parametresi</td><td>"tr" (Türkçe)</td><td><span className="tag-ro">Zorunlu</span></td></tr>
                      <tr><td>Repetition Penalty</td><td>1.2</td><td><span className="tag-ro">Kilitli</span></td></tr>
                      <tr><td>No Repeat N-Gram</td><td>3</td><td><span className="tag-ro">Kilitli</span></td></tr>
                      <tr><td>RMS Enerji Kapısı</td><td>&gt; 0.008 (-42 dBFS)</td><td><span className="tag-ro">Aktif</span></td></tr>
                    </>
                  )}
                  {selectedStage === "F3" && (
                    <>
                      <tr><td>LLM Modeli</td><td>Qwen2.5 7B (Ollama)</td><td><span className="tag-ro">Yerel GPU</span></td></tr>
                      <tr><td>Temperature</td><td>0.0 (Deterministik)</td><td><span className="tag-ro">Kilitli</span></td></tr>
                      <tr><td>Supervisor Modu</td><td>Guarded Intent Router</td><td><span className="tag-ro">Aktif</span></td></tr>
                      <tr><td>Veritabanı Kilidi</td><td>SQLite Deterministik</td><td><span className="tag-ro">Zorunlu</span></td></tr>
                    </>
                  )}
                  {selectedStage === "F4" && (
                    <>
                      <tr><td>Sözlük Sürümü</td><td>P0 Otomotiv Fonetik v3.2</td><td><span className="tag-ro">64+ Terim</span></td></tr>
                      <tr><td>Sıfır Markdown Kalkanı</td><td>Aktif (Regex Arındırma)</td><td><span className="tag-ro">Zorunlu</span></td></tr>
                      <tr><td>İlk Cümlecik Sınırı</td><td>4–7 Kelime</td><td><span className="tag-ro">Kilitli</span></td></tr>
                    </>
                  )}
                  {selectedStage === "F5" && (
                    <>
                      <tr><td>Sentez Motoru</td><td>FreyaTTS Batched Flow ODE</td><td><span className="tag-ro">CUDA</span></td></tr>
                      <tr><td>Ses Kimliği (Persona)</td><td>Leyla Kurumsal Kadın Sesi</td><td><span className="tag-ro">Seed #9</span></td></tr>
                      <tr><td>ODE Adım Sayısı</td><td>32 Adım</td><td><span className="tag-ro">Sabit</span></td></tr>
                      <tr><td>LoRA Katmanı</td><td>DiT Cross-Attention</td><td><span className="tag-ro">Yüklü</span></td></tr>
                    </>
                  )}
                  {selectedStage === "F6" && (
                    <>
                      <tr><td>WSOLA Hız Oranı</td><td>0.98x (Doğal Konuşma Akışı)</td><td><span className="tag-ro">Kilitli</span></td></tr>
                      <tr><td>Comfort Noise</td><td>-54 dBFS Gaussian Dither</td><td><span className="tag-ro">Aktif</span></td></tr>
                      <tr><td>Santral Arayüzü</td><td>Asterisk 20+ AudioSocket</td><td><span className="tag-ro">8 kHz SLIN16</span></td></tr>
                    </>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === "intermediate" && (
          <div className="tab-pane intermediate-pane">
            <h4>Aşama Ara Çıktıları</h4>
            {runtime.intermediateData ? (
              <pre className="json-box">
                {JSON.stringify(runtime.intermediateData, null, 2)}
              </pre>
            ) : (
              <div className="empty-notice">
                Bu aşama için son konuşma turunda kaydedilmiş ara veri bulunmuyor.
              </div>
            )}
          </div>
        )}

        {activeTab === "metrics" && (
          <div className="tab-pane metrics-pane">
            <h4>Canlı Telemetri Ölçümleri</h4>
            {Object.keys(runtime.metrics).length > 0 ? (
              <div className="metrics-list">
                {Object.entries(runtime.metrics).map(([k, v]) => (
                  <div key={k} className="metric-row">
                    <span className="metric-key">{k}</span>
                    <span className="metric-val">{String(v)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-notice">Henüz aşama metriği toplanmadı.</div>
            )}
          </div>
        )}

        {activeTab === "traces" && (
          <div className="tab-pane traces-pane">
            <h4>Olay Zaman Çizgisi</h4>
            <div className="traces-timeline">
              {pipelineState.traces.length > 0 ? (
                pipelineState.traces
                  .filter((t) => t.stage === selectedStage)
                  .map((t, idx) => (
                    <div key={idx} className="trace-item">
                      <span className="trace-time">{new Date(t.timestamp).toLocaleTimeString()}</span>
                      <span className={`trace-status status-${t.status}`}>{t.status}</span>
                      {t.duration_ms !== undefined && (
                        <span className="trace-dur">{t.duration_ms.toFixed(1)} ms</span>
                      )}
                    </div>
                  ))
              ) : (
                <div className="empty-notice">Bu aşama için olay kaydı yok.</div>
              )}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

