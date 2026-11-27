/**
 * FreyaTTS Automotive Cockpit V3 — Engineering Inspector Drawer (Bölüm 9)
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useState, useMemo } from "react";
import {
  StageId,
  STAGE_DEFINITIONS,
  PipelineTurnState,
} from "./pipeline/types";
import { TabName } from "./nav";
import { Sparkles, Volume2 } from "lucide-react";
import { runF4Pipeline, speakF4ChunksSequentially } from "./pipeline/f4Engine";

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
  const [f4InspectorInput, setF4InspectorInput] = useState(
    "Trabzon'da 61 TS 061 plakalı Peugeot 3008 OBD-II P0300 arıza tespiti ve DSG bakımı 14.500 TL."
  );
  const [f4Speaking, setF4Speaking] = useState(false);
  const f4InspectorResult = useMemo(
    () => runF4Pipeline(f4InspectorInput),
    [f4InspectorInput]
  );
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

            {(selectedStage === "F3" || selectedStage === "F4" || selectedStage === "F5") && (
              <div className="info-block">
                <h4>W3–W4 Hattı &amp; Prosodi Özeti (Salt Okunur)</h4>
                <p className="code-font">
                  {selectedStage === "F3" && "Hiyerarşik Niyet Yönlendirici (31 niyet) → M07 onaylı yazma kapısı"}
                  {selectedStage === "F4" && "Intent → Style → Prosody (31 niyet tablosu, tek-geçiş normalizasyon, kaynak-hizalı span)"}
                  {selectedStage === "F5" && "Leyla Seed #9 · Euler32 · Donanım / İnsan MOS: Ölçülmedi (NOT_RUN)"}
                </p>
              </div>
            )}
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
                    </>
                  )}
                  {selectedStage === "F3" && (
                    <>
                      <tr><td>LLM Modeli</td><td>Qwen2.5 7B (Ollama)</td><td><span className="tag-ro">Yerel GPU</span></td></tr>
                      <tr><td>Temperature</td><td>0.0 (Deterministik)</td><td><span className="tag-ro">Kilitli</span></td></tr>
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
                    </>
                  )}
                  {selectedStage === "F6" && (
                    <>
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
        {selectedStage === "F4" && (
          <div
            style={{
              marginTop: "14px",
              padding: "12px 14px",
              background: "#090d16",
              border: "1px solid #f59e0b",
              borderRadius: "8px",
              display: "flex",
              flexDirection: "column",
              gap: "10px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: "11px", fontWeight: "bold", color: "#fde68a", display: "flex", alignItems: "center", gap: "6px" }}>
                <Sparkles style={{ width: "14px", height: "14px" }} />
                CANLI F₄ SEZER G2P & CHUNKER ({f4InspectorResult.processingMs} ms)
              </span>
              <button
                type="button"
                onClick={() => {
                  setF4Speaking(true);
                  speakF4ChunksSequentially(f4InspectorResult, undefined, () => setF4Speaking(false));
                }}
                style={{
                  background: "#10b981",
                  color: "#0f172a",
                  fontWeight: "bold",
                  fontSize: "11px",
                  padding: "4px 10px",
                  borderRadius: "6px",
                  border: 0,
                  cursor: "pointer",
                }}
              >
                🔊 {f4Speaking ? "Çalıyor..." : "Seslendir"}
              </button>
            </div>
            <input
              type="text"
              value={f4InspectorInput}
              onChange={(e) => setF4InspectorInput(e.target.value)}
              style={{
                background: "#1e293b",
                border: "1px solid #334155",
                borderRadius: "6px",
                padding: "6px 10px",
                color: "#f8fafc",
                fontSize: "11px",
                fontFamily: "monospace",
              }}
            />
            <div style={{ fontSize: "11px", fontFamily: "monospace", color: "#6ee7b7", background: "#020617", padding: "8px", borderRadius: "6px" }}>
              <strong>Normalize:</strong> "{f4InspectorResult.phoneticText}"
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
              {f4InspectorResult.chunks.map((ch) => (
                <span
                  key={ch.index}
                  style={{
                    background: "rgba(56, 189, 248, 0.15)",
                    border: "1px solid rgba(56, 189, 248, 0.3)",
                    color: "#bae6fd",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    fontSize: "10px",
                    fontFamily: "monospace",
                  }}
                >
                  <strong>[#{ch.index}]</strong> {ch.text}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

