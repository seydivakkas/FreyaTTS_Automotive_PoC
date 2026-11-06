import { useEffect, useState, useRef } from "react";

type ApiFn = (path: string, method?: string, body?: unknown) => Promise<any>;
type ActionFn = (fn: () => Promise<void>) => void;

interface Variant {
  id?: string;
  variant_id?: string;
  name: string;
  weight: number;
  prompt_template: string;
  tts_seed: number;
  greeting_template: string;
  description?: string;
  is_control?: boolean;
  total_sessions?: number;
  converted_sessions?: number;
  abandoned_sessions?: number;
  pending_sessions?: number;
  conversion_rate_pct?: number;
  ci_95?: [number, number];
  avg_duration_sec?: number;
  avg_first_audio_ms?: number;
  avg_turns?: number;
}

interface Comparison {
  variant_id: string;
  variant_name: string;
  relative_lift_pct: number;
  z_score: number;
  p_value: number;
  is_significant: boolean;
  confidence_level: string;
  verdict: string;
}

interface ExperimentReport {
  experiment_id: string;
  experiment_name: string;
  status: string;
  target_metric: string;
  total_experiment_sessions: number;
  total_converted_sessions: number;
  overall_conversion_pct: number;
  best_performing_variant: string;
  variants: Variant[];
  comparisons: Comparison[];
}

interface ExperimentItem {
  id: string;
  name: string;
  description: string;
  experiment_type: string;
  status: string;
  target_metric: string;
  variants_count: number;
  total_sessions: number;
  converted_sessions: number;
  conversion_rate: number;
  created_at: string;
}

interface TemplatesData {
  prompt_templates: Array<{ id: string; name: string; description: string; prompt: string }>;
  greeting_templates: Array<{ id: string; name: string; description: string; text: string }>;
  tts_seed_presets: Array<{ seed: number; name: string; description: string; tone: string }>;
}

export function ABTestingPanel({ api, action }: { api: ApiFn; action: ActionFn }) {
  const [experiments, setExperiments] = useState<ExperimentItem[]>([]);
  const [selectedExpId, setSelectedExpId] = useState<string>("");
  const [report, setReport] = useState<ExperimentReport | null>(null);
  const [templates, setTemplates] = useState<TemplatesData | null>(null);
  const [loading, setLoading] = useState(false);
  const [showNewModal, setShowNewModal] = useState(false);
  const [activeSubTab, setActiveSubTab] = useState<"results" | "audio_lab" | "templates">("results");

  // Audio Lab state
  const [testText, setTestText] = useState("Merhaba, Maslak Ekspertiz merkezinden arıyorum. Aracınız için randevunuzu teyit etmek amacıyla aradık.");
  const [testSeed, setTestSeed] = useState(9);
  const [synthAudioUrl, setSynthAudioUrl] = useState<string>("");
  const [synthLoading, setSynthLoading] = useState(false);

  // New experiment form state
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newType, setNewType] = useState("composite");
  const [ctrlPrompt, setCtrlPrompt] = useState("standard");
  const [ctrlSeed, setCtrlSeed] = useState(9);
  const [ctrlGreeting, setCtrlGreeting] = useState("standard");
  const [varPrompt, setVarPrompt] = useState("friendly");
  const [varSeed, setVarSeed] = useState(42);
  const [varGreeting, setVarGreeting] = useState("friendly");
  const [varName, setVarName] = useState("Varyant B (Samimi)");

  async function loadData() {
    setLoading(true);
    try {
      const [exps, tpls] = await Promise.all([
        api("ab/experiments"),
        api("ab/templates"),
      ]);
      setExperiments(exps || []);
      setTemplates(tpls || null);
      if (exps && exps.length > 0 && !selectedExpId) {
        setSelectedExpId(exps[0].id);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  async function loadReport(expId: string) {
    if (!expId) return;
    try {
      const rep = await api(`ab/experiments/${expId}/report`);
      setReport(rep);
    } catch (e) {
      console.error("Report loading error:", e);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (selectedExpId) {
      loadReport(selectedExpId);
    }
  }, [selectedExpId]);

  async function handleToggleStatus(newStatus: string) {
    if (!selectedExpId) return;
    action(async () => {
      await api(`ab/experiments/${selectedExpId}/status`, "POST", { status: newStatus });
      await loadData();
      await loadReport(selectedExpId);
    });
  }

  async function handleCreateExperiment(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;

    const payload = {
      name: newName.trim(),
      description: newDesc.trim(),
      experiment_type: newType,
      variants: [
        {
          id: "control",
          name: "Kontrol (A)",
          weight: 50,
          prompt_template: ctrlPrompt,
          tts_seed: Number(ctrlSeed),
          greeting_template: ctrlGreeting,
          description: "Mevcut standart akış",
        },
        {
          id: "variant_b",
          name: varName.trim() || "Varyant B",
          weight: 50,
          prompt_template: varPrompt,
          tts_seed: Number(varSeed),
          greeting_template: varGreeting,
          description: "Alternatif test akışı",
        },
      ],
      target_metric: "conversion_rate",
    };

    action(async () => {
      const created = await api("ab/experiments", "POST", payload);
      setShowNewModal(false);
      setNewName("");
      setNewDesc("");
      await loadData();
      if (created && created.id) {
        setSelectedExpId(created.id);
      }
    });
  }

  async function handleAudioPreview(seedValue?: number) {
    const s = seedValue !== undefined ? seedValue : testSeed;
    setSynthLoading(true);
    try {
      const token = localStorage.getItem("admin_password") || "";
      const resp = await fetch("/api/ab/preview-synth", {
        method: "POST",
        headers: {
          Authorization: "Basic " + btoa("admin:" + token),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          text: testText,
          seed: s,
        }),
      });
      if (!resp.ok) {
        throw new Error("Sentez hatası: " + resp.statusText);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      setSynthAudioUrl(url);
    } catch (err: any) {
      alert("Ses sentezi önizleme hatası: " + (err.message || err));
    } finally {
      setSynthLoading(false);
    }
  }

  return (
    <div className="ab-panel" style={{ padding: "16px", maxWidth: "1280px", margin: "0 auto" }}>
      {/* BAŞLIK & ÜST KONTROLLER */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "20px", flexWrap: "wrap", gap: "12px" }}>
        <div>
          <h2 style={{ margin: "0 0 6px 0", display: "flex", alignItems: "center", gap: "8px" }}>
            <span>🔬 A/B Test ve İnce Ayar Altyapısı</span>
            <span style={{ fontSize: "12px", background: "#3b82f6", color: "#fff", padding: "2px 8px", borderRadius: "12px" }}>
              Özellik 15
            </span>
          </h2>
          <p style={{ margin: 0, color: "#94a3b8", fontSize: "14px" }}>
            Farklı LLM prompt şablonları, FreyaTTS ses tohumları (seed) ve karşılama metinlerini canlı müşteri görüşmelerinde test edin.
          </p>
        </div>

        <div style={{ display: "flex", gap: "10px" }}>
          <button
            onClick={() => {
              loadData();
              if (selectedExpId) loadReport(selectedExpId);
            }}
            disabled={loading}
            style={{ padding: "8px 14px", background: "#334155", color: "#f8fafc", border: "1px solid #475569", borderRadius: "6px", cursor: "pointer" }}
          >
            {loading ? "Yenileniyor..." : "🔄 Yenile"}
          </button>
          <button
            onClick={() => setShowNewModal(true)}
            style={{ padding: "8px 16px", background: "#2563eb", color: "#fff", border: "none", borderRadius: "6px", fontWeight: "bold", cursor: "pointer" }}
          >
            + Yeni A/B Deneyi Başlat
          </button>
        </div>
      </div>

      {/* ALT SEKME GEÇİŞLERİ */}
      <div style={{ display: "flex", gap: "8px", borderBottom: "1px solid #334155", marginBottom: "20px" }}>
        <button
          onClick={() => setActiveSubTab("results")}
          style={{
            padding: "10px 18px",
            background: activeSubTab === "results" ? "#1e293b" : "transparent",
            color: activeSubTab === "results" ? "#38bdf8" : "#94a3b8",
            border: "none",
            borderBottom: activeSubTab === "results" ? "2px solid #38bdf8" : "none",
            cursor: "pointer",
            fontWeight: "bold",
          }}
        >
          📊 Deney Sonuçları & Rapor
        </button>
        <button
          onClick={() => setActiveSubTab("audio_lab")}
          style={{
            padding: "10px 18px",
            background: activeSubTab === "audio_lab" ? "#1e293b" : "transparent",
            color: activeSubTab === "audio_lab" ? "#38bdf8" : "#94a3b8",
            border: "none",
            borderBottom: activeSubTab === "audio_lab" ? "2px solid #38bdf8" : "none",
            cursor: "pointer",
            fontWeight: "bold",
          }}
        >
          🎙️ Ses Karşılaştırma Laboratuvarı (TTS Seed Lab)
        </button>
        <button
          onClick={() => setActiveSubTab("templates")}
          style={{
            padding: "10px 18px",
            background: activeSubTab === "templates" ? "#1e293b" : "transparent",
            color: activeSubTab === "templates" ? "#38bdf8" : "#94a3b8",
            border: "none",
            borderBottom: activeSubTab === "templates" ? "2px solid #38bdf8" : "none",
            cursor: "pointer",
            fontWeight: "bold",
          }}
        >
          📑 Prompt & Şablon Kataloğu
        </button>
      </div>

      {/* 1. SEKME: DENEY SONUÇLARI */}
      {activeSubTab === "results" && (
        <>
          {/* DENEY SEÇİM ÇUBUĞU */}
          <div style={{ background: "#1e293b", padding: "14px 18px", borderRadius: "8px", marginBottom: "20px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <label style={{ fontWeight: "bold", fontSize: "14px", color: "#f8fafc" }}>Aktif Deney:</label>
              <select
                value={selectedExpId}
                onChange={(e) => setSelectedExpId(e.target.value)}
                style={{ padding: "6px 12px", background: "#0f172a", color: "#f8fafc", border: "1px solid #475569", borderRadius: "6px", minWidth: "260px" }}
              >
                {experiments.map((exp) => (
                  <option key={exp.id} value={exp.id}>
                    {exp.name} ({exp.status === "active" ? "🟢 Aktif" : exp.status === "paused" ? "🟡 Duraklatıldı" : "⚪ Tamamlandı"})
                  </option>
                ))}
              </select>
            </div>

            {report && (
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span style={{ fontSize: "13px", color: "#94a3b8" }}>Durum:</span>
                <span
                  style={{
                    padding: "4px 10px",
                    borderRadius: "12px",
                    fontSize: "12px",
                    fontWeight: "bold",
                    background: report.status === "active" ? "#14532d" : report.status === "paused" ? "#713f12" : "#334155",
                    color: report.status === "active" ? "#4ade80" : report.status === "paused" ? "#facc15" : "#cbd5e1",
                  }}
                >
                  {report.status === "active" ? "Canlı Testte (Aktif)" : report.status === "paused" ? "Duraklatıldı" : "Sonuçlandı"}
                </span>

                {report.status === "active" ? (
                  <button
                    onClick={() => handleToggleStatus("paused")}
                    style={{ padding: "4px 10px", background: "#854d0e", color: "#fff", border: "none", borderRadius: "4px", fontSize: "12px", cursor: "pointer" }}
                  >
                    ⏸ Duraklat
                  </button>
                ) : (
                  <button
                    onClick={() => handleToggleStatus("active")}
                    style={{ padding: "4px 10px", background: "#16a34a", color: "#fff", border: "none", borderRadius: "4px", fontSize: "12px", cursor: "pointer" }}
                  >
                    ▶️ Devam Ettir
                  </button>
                )}
                <button
                  onClick={() => handleToggleStatus("completed")}
                  style={{ padding: "4px 10px", background: "#475569", color: "#fff", border: "none", borderRadius: "4px", fontSize: "12px", cursor: "pointer" }}
                >
                  🏁 Tamamla
                </button>
              </div>
            )}
          </div>

          {report && (
            <>
              {/* ÖZET BANNER'I & KAZANAN TESPİTİ */}
              <div
                style={{
                  background: "linear-gradient(90deg, #1e293b 0%, #0f172a 100%)",
                  border: "1px solid #334155",
                  borderLeft: "5px solid #38bdf8",
                  padding: "16px 20px",
                  borderRadius: "8px",
                  marginBottom: "24px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "16px",
                }}
              >
                <div>
                  <div style={{ fontSize: "12px", color: "#38bdf8", fontWeight: "bold", textTransform: "uppercase", letterSpacing: "1px" }}>
                    🏆 Mevcut En Başarılı Varyant
                  </div>
                  <div style={{ fontSize: "20px", fontWeight: "bold", color: "#f8fafc", marginTop: "4px" }}>
                    {report.best_performing_variant}
                  </div>
                  <div style={{ fontSize: "13px", color: "#94a3b8", marginTop: "2px" }}>
                    Toplam {report.total_experiment_sessions} görüşmeden {report.total_converted_sessions} tanesi randevuya dönüştü (Genel: %{report.overall_conversion_pct}).
                  </div>
                </div>

                {report.comparisons.length > 0 && (
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: "13px", color: "#cbd5e1" }}>
                      İstatistiksel Anlamlılık: <strong style={{ color: report.comparisons[0].is_significant ? "#4ade80" : "#facc15" }}>{report.comparisons[0].confidence_level}</strong>
                    </div>
                    <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "2px" }}>
                      p-değeri: {report.comparisons[0].p_value} | Z-Skoru: {report.comparisons[0].z_score}
                    </div>
                  </div>
                )}
              </div>

              {/* VARYANT KARTLARI (YAN YANA KARŞILAŞTIRMA) */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "20px", marginBottom: "28px" }}>
                {report.variants.map((v, i) => (
                  <div
                    key={v.variant_id}
                    style={{
                      background: "#1e293b",
                      border: v.is_control ? "1px solid #475569" : "2px solid #3b82f6",
                      borderRadius: "10px",
                      padding: "18px",
                      position: "relative",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                      <span
                        style={{
                          fontSize: "12px",
                          fontWeight: "bold",
                          padding: "2px 8px",
                          borderRadius: "4px",
                          background: v.is_control ? "#334155" : "#1d4ed8",
                          color: "#fff",
                        }}
                      >
                        {v.is_control ? "KONTROL (A)" : `VARYANT ${String.fromCharCode(66 + i - 1)}`}
                      </span>
                      <span style={{ fontSize: "12px", color: "#94a3b8" }}>Trafik: %{v.weight}</span>
                    </div>

                    <h3 style={{ margin: "0 0 10px 0", fontSize: "18px", color: "#f8fafc" }}>{v.name}</h3>

                    {/* Parametre Konfigürasyonu */}
                    <div style={{ background: "#0f172a", padding: "10px", borderRadius: "6px", fontSize: "12px", color: "#cbd5e1", marginBottom: "16px" }}>
                      <div>💬 <strong>Prompt:</strong> {v.prompt_template}</div>
                      <div style={{ marginTop: "4px" }}>🎙️ <strong>TTS Seed:</strong> Leyla #{v.tts_seed}</div>
                      <div style={{ marginTop: "4px" }}>👋 <strong>Karşılama:</strong> {v.greeting_template}</div>
                    </div>

                    {/* Temel Metrikler */}
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginBottom: "14px" }}>
                      <div style={{ background: "#0f172a", padding: "10px", borderRadius: "6px", textAlign: "center" }}>
                        <div style={{ fontSize: "12px", color: "#94a3b8" }}>Dönüşüm Oranı</div>
                        <div style={{ fontSize: "24px", fontWeight: "bold", color: "#38bdf8", margin: "4px 0" }}>
                          %{v.conversion_rate_pct}
                        </div>
                        <div style={{ fontSize: "11px", color: "#64748b" }}>
                          %95 GA: [{v.ci_95?.[0]}% - {v.ci_95?.[1]}%]
                        </div>
                      </div>

                      <div style={{ background: "#0f172a", padding: "10px", borderRadius: "6px", textAlign: "center" }}>
                        <div style={{ fontSize: "12px", color: "#94a3b8" }}>Görüşme Sayısı</div>
                        <div style={{ fontSize: "24px", fontWeight: "bold", color: "#f8fafc", margin: "4px 0" }}>
                          {v.total_sessions}
                        </div>
                        <div style={{ fontSize: "11px", color: "#4ade80" }}>
                          {v.converted_sessions} randevu oluşturuldu
                        </div>
                      </div>
                    </div>

                    {/* Gecikme ve Süre Detayları */}
                    <div style={{ fontSize: "12px", color: "#94a3b8", display: "flex", justifyContent: "space-between", borderTop: "1px solid #334155", paddingTop: "10px" }}>
                      <span>⏱ Ort. Süre: <strong>{v.avg_duration_sec} sn</strong></span>
                      <span>⚡ İlk Ses: <strong>{v.avg_first_audio_ms} ms</strong></span>
                      <span>🔄 Tur: <strong>{v.avg_turns}</strong></span>
                    </div>
                  </div>
                ))}
              </div>

              {/* İSTATİSTİKSEL ANLAMLILIK & KARŞILAŞTIRMA TABLOSU */}
              {report.comparisons.length > 0 && (
                <div style={{ background: "#1e293b", borderRadius: "8px", padding: "18px", marginBottom: "20px" }}>
                  <h3 style={{ margin: "0 0 14px 0", fontSize: "16px", color: "#f8fafc" }}>
                    📐 İki Oranlı Z-Testi ve İstatistiksel Çıkarım
                  </h3>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid #334155", color: "#94a3b8", textAlign: "left" }}>
                        <th style={{ padding: "8px" }}>Varyant</th>
                        <th style={{ padding: "8px" }}>Relatif Artış (Lift)</th>
                        <th style={{ padding: "8px" }}>Z-Skoru</th>
                        <th style={{ padding: "8px" }}>p-Değeri</th>
                        <th style={{ padding: "8px" }}>Anlamlılık Düzeyi</th>
                        <th style={{ padding: "8px" }}>Karar ve Tavsiye</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.comparisons.map((c) => (
                        <tr key={c.variant_id} style={{ borderBottom: "1px solid #2d3748" }}>
                          <td style={{ padding: "10px 8px", fontWeight: "bold", color: "#f8fafc" }}>{c.variant_name}</td>
                          <td style={{ padding: "10px 8px" }}>
                            <span style={{ color: c.relative_lift_pct >= 0 ? "#4ade80" : "#f87171", fontWeight: "bold" }}>
                              {c.relative_lift_pct >= 0 ? "+" : ""}{c.relative_lift_pct}%
                            </span>
                          </td>
                          <td style={{ padding: "10px 8px", color: "#cbd5e1" }}>{c.z_score}</td>
                          <td style={{ padding: "10px 8px", color: "#cbd5e1" }}>{c.p_value}</td>
                          <td style={{ padding: "10px 8px" }}>
                            <span
                              style={{
                                padding: "2px 8px",
                                borderRadius: "4px",
                                fontSize: "11px",
                                background: c.is_significant ? "#14532d" : "#334155",
                                color: c.is_significant ? "#4ade80" : "#94a3b8",
                              }}
                            >
                              {c.confidence_level}
                            </span>
                          </td>
                          <td style={{ padding: "10px 8px", color: "#e2e8f0" }}>{c.verdict}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* 2. SEKME: SES KARŞILAŞTIRMA LABORATUVARI (AUDIO LAB) */}
      {activeSubTab === "audio_lab" && (
        <div style={{ background: "#1e293b", padding: "20px", borderRadius: "8px" }}>
          <h3 style={{ margin: "0 0 8px 0", color: "#f8fafc" }}>🎙️ FreyaTTS Ses Tohumu (Seed) Karşılaştırma Laboratuvarı</h3>
          <p style={{ margin: "0 0 20px 0", color: "#94a3b8", fontSize: "14px" }}>
            Farklı seed değerleri (Leyla 9, 42, 77, 123) modelin entonasyonunu ve duygu tonunu değiştirir. Canlı sentezleyip yan yana dinleyin.
          </p>

          <div style={{ marginBottom: "16px" }}>
            <label style={{ display: "block", fontSize: "13px", fontWeight: "bold", color: "#cbd5e1", marginBottom: "6px" }}>
              Test Edilecek Cümle:
            </label>
            <textarea
              rows={3}
              value={testText}
              onChange={(e) => setTestText(e.target.value)}
              style={{ width: "100%", padding: "10px", background: "#0f172a", color: "#f8fafc", border: "1px solid #475569", borderRadius: "6px", fontSize: "14px" }}
            />
          </div>

          <div style={{ marginBottom: "20px" }}>
            <label style={{ display: "block", fontSize: "13px", fontWeight: "bold", color: "#cbd5e1", marginBottom: "8px" }}>
              Hızlı Ses Tohumu Önayarı Seçin:
            </label>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "12px" }}>
              {templates?.tts_seed_presets.map((p) => (
                <div
                  key={p.seed}
                  onClick={() => {
                    setTestSeed(p.seed);
                    handleAudioPreview(p.seed);
                  }}
                  style={{
                    padding: "12px",
                    background: testSeed === p.seed ? "#1e3a8a" : "#0f172a",
                    border: testSeed === p.seed ? "2px solid #38bdf8" : "1px solid #334155",
                    borderRadius: "8px",
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  <div style={{ fontWeight: "bold", color: "#f8fafc", fontSize: "14px" }}>{p.name}</div>
                  <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "4px" }}>{p.description}</div>
                  <div style={{ marginTop: "8px", fontSize: "11px", color: "#38bdf8" }}>▶️ Dinle ve Test Et</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "16px", background: "#0f172a", padding: "16px", borderRadius: "8px", border: "1px solid #334155" }}>
            <button
              onClick={() => handleAudioPreview()}
              disabled={synthLoading}
              style={{ padding: "10px 20px", background: "#2563eb", color: "#fff", border: "none", borderRadius: "6px", fontWeight: "bold", cursor: "pointer" }}
            >
              {synthLoading ? "Sentezleniyor..." : `🔊 Seed ${testSeed} ile Sentezle`}
            </button>

            {synthAudioUrl && (
              <audio controls autoPlay src={synthAudioUrl} style={{ flex: 1 }} />
            )}
          </div>
        </div>
      )}

      {/* 3. SEKME: ŞABLON & KATALOG REHBERİ */}
      {activeSubTab === "templates" && templates && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
          <div style={{ background: "#1e293b", padding: "18px", borderRadius: "8px" }}>
            <h3 style={{ margin: "0 0 14px 0", color: "#38bdf8" }}>💬 LLM Prompt Şablonları</h3>
            {templates.prompt_templates.map((p) => (
              <div key={p.id} style={{ background: "#0f172a", padding: "12px", borderRadius: "6px", marginBottom: "12px" }}>
                <div style={{ fontWeight: "bold", color: "#f8fafc" }}>{p.name} ({p.id})</div>
                <div style={{ fontSize: "12px", color: "#94a3b8", margin: "4px 0 8px 0" }}>{p.description}</div>
                <pre style={{ margin: 0, padding: "8px", background: "#1e293b", borderRadius: "4px", fontSize: "11px", color: "#cbd5e1", whiteSpace: "pre-wrap" }}>
                  {p.prompt}
                </pre>
              </div>
            ))}
          </div>

          <div style={{ background: "#1e293b", padding: "18px", borderRadius: "8px" }}>
            <h3 style={{ margin: "0 0 14px 0", color: "#38bdf8" }}>👋 Karşılama Metinleri (Greetings)</h3>
            {templates.greeting_templates.map((g) => (
              <div key={g.id} style={{ background: "#0f172a", padding: "12px", borderRadius: "6px", marginBottom: "12px" }}>
                <div style={{ fontWeight: "bold", color: "#f8fafc" }}>{g.name} ({g.id})</div>
                <div style={{ fontSize: "12px", color: "#94a3b8", margin: "4px 0 6px 0" }}>{g.description}</div>
                <div style={{ fontStyle: "italic", fontSize: "13px", color: "#e2e8f0" }}>"{g.text}"</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* YENİ DENEY OLUŞTURMA MODALI */}
      {showNewModal && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.75)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div style={{ background: "#1e293b", padding: "24px", borderRadius: "10px", width: "600px", maxWidth: "90%", maxHeight: "90vh", overflowY: "auto", border: "1px solid #475569" }}>
            <h3 style={{ margin: "0 0 14px 0", color: "#f8fafc" }}>🧪 Yeni A/B Deneyi Yapılandır</h3>

            <form onSubmit={handleCreateExperiment}>
              <div style={{ marginBottom: "14px" }}>
                <label style={{ display: "block", fontSize: "13px", fontWeight: "bold", color: "#cbd5e1", marginBottom: "4px" }}>
                  Deney Adı:
                </label>
                <input
                  type="text"
                  required
                  placeholder="Örn: Samimi vs Standart Karşılama Testi"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  style={{ width: "100%", padding: "8px", background: "#0f172a", color: "#f8fafc", border: "1px solid #475569", borderRadius: "6px" }}
                />
              </div>

              <div style={{ marginBottom: "14px" }}>
                <label style={{ display: "block", fontSize: "13px", fontWeight: "bold", color: "#cbd5e1", marginBottom: "4px" }}>
                  Açıklama:
                </label>
                <textarea
                  rows={2}
                  placeholder="Deneyin amacı ve beklenen hipotez..."
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  style={{ width: "100%", padding: "8px", background: "#0f172a", color: "#f8fafc", border: "1px solid #475569", borderRadius: "6px" }}
                />
              </div>

              {/* KONTROL GRUBU AYARLARI */}
              <div style={{ background: "#0f172a", padding: "14px", borderRadius: "8px", marginBottom: "14px", border: "1px solid #334155" }}>
                <h4 style={{ margin: "0 0 10px 0", color: "#94a3b8", fontSize: "14px" }}>🅰️ Kontrol Grubu (Standart - %50 Trafik)</h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                  <div>
                    <label style={{ fontSize: "12px", color: "#cbd5e1" }}>Prompt Şablonu:</label>
                    <select
                      value={ctrlPrompt}
                      onChange={(e) => setCtrlPrompt(e.target.value)}
                      style={{ width: "100%", padding: "6px", background: "#1e293b", color: "#fff", border: "1px solid #475569", borderRadius: "4px" }}
                    >
                      <option value="standard">Standart Çıkarım</option>
                      <option value="concise">Kısa ve Doğrudan</option>
                      <option value="friendly">Samimi ve Nezaketli</option>
                      <option value="expert">Uzman ve Titiz</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: "12px", color: "#cbd5e1" }}>TTS Ses Tohumu:</label>
                    <select
                      value={ctrlSeed}
                      onChange={(e) => setCtrlSeed(Number(e.target.value))}
                      style={{ width: "100%", padding: "6px", background: "#1e293b", color: "#fff", border: "1px solid #475569", borderRadius: "4px" }}
                    >
                      <option value={9}>Leyla Seed 9 (Standart)</option>
                      <option value={42}>Leyla Seed 42 (Samimi)</option>
                      <option value={77}>Leyla Seed 77 (Dinamik)</option>
                      <option value={123}>Leyla Seed 123 (Resmi)</option>
                    </select>
                  </div>
                </div>
              </div>

              {/* VARYANT B AYARLARI */}
              <div style={{ background: "#0f172a", padding: "14px", borderRadius: "8px", marginBottom: "20px", border: "1px solid #2563eb" }}>
                <h4 style={{ margin: "0 0 10px 0", color: "#38bdf8", fontSize: "14px" }}>🅱️ Test Grubu (Varyant B - %50 Trafik)</h4>
                <div style={{ marginBottom: "8px" }}>
                  <label style={{ fontSize: "12px", color: "#cbd5e1" }}>Varyant Adı:</label>
                  <input
                    type="text"
                    value={varName}
                    onChange={(e) => setVarName(e.target.value)}
                    style={{ width: "100%", padding: "6px", background: "#1e293b", color: "#fff", border: "1px solid #475569", borderRadius: "4px" }}
                  />
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                  <div>
                    <label style={{ fontSize: "12px", color: "#cbd5e1" }}>Prompt Şablonu:</label>
                    <select
                      value={varPrompt}
                      onChange={(e) => setVarPrompt(e.target.value)}
                      style={{ width: "100%", padding: "6px", background: "#1e293b", color: "#fff", border: "1px solid #475569", borderRadius: "4px" }}
                    >
                      <option value="friendly">Samimi ve Nezaketli</option>
                      <option value="concise">Kısa ve Doğrudan</option>
                      <option value="standard">Standart Çıkarım</option>
                      <option value="expert">Uzman ve Titiz</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: "12px", color: "#cbd5e1" }}>TTS Ses Tohumu:</label>
                    <select
                      value={varSeed}
                      onChange={(e) => setVarSeed(Number(e.target.value))}
                      style={{ width: "100%", padding: "6px", background: "#1e293b", color: "#fff", border: "1px solid #475569", borderRadius: "4px" }}
                    >
                      <option value={42}>Leyla Seed 42 (Samimi)</option>
                      <option value={77}>Leyla Seed 77 (Dinamik)</option>
                      <option value={9}>Leyla Seed 9 (Standart)</option>
                      <option value={123}>Leyla Seed 123 (Resmi)</option>
                    </select>
                  </div>
                </div>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
                <button
                  type="button"
                  onClick={() => setShowNewModal(false)}
                  style={{ padding: "8px 16px", background: "#475569", color: "#fff", border: "none", borderRadius: "6px", cursor: "pointer" }}
                >
                  İptal
                </button>
                <button
                  type="submit"
                  style={{ padding: "8px 20px", background: "#2563eb", color: "#fff", border: "none", borderRadius: "6px", fontWeight: "bold", cursor: "pointer" }}
                >
                  Deneyi Başlat 🚀
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
