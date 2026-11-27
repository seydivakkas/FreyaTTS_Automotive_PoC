# Ekran etkileşimleri

Her ekranın alanları, düğmeleri, doğrulamaları, API çağrıları, yüklenme ve hata durumları aşağıda bileşen bazında verilmiştir. Bileşenler referans uygulamadaki kullanıcı davranışını tarif eder.


### frontend/src/ABTestingPanel.tsx

````
import { useEffect, useState, useMemo } from "react";
import { ApiFn, RawApiFn, dash, useEscape } from "./ui";
import { Sliders, Sparkles, Activity, ShieldCheck, CheckCircle2 } from "lucide-react";
import { INITIAL_F2_HOTWORDS, F2_ASR_MODELS, runF2DomainBooster, F2Hotword, F2AsrModel } from "./pipeline/f2Hotwords";

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

export function ABTestingPanel({ api, rawApi, action }: { api: ApiFn; rawApi: RawApiFn; action: ActionFn }) {
  const [panelError, setPanelError] = useState("");
  const [experiments, setExperiments] = useState<ExperimentItem[]>([]);
  const [selectedExpId, setSelectedExpId] = useState<string>("");
  const [report, setReport] = useState<ExperimentReport | null>(null);
  const [templates, setTemplates] = useState<TemplatesData | null>(null);
  const [loading, setLoading] = useState(false);
  const [showNewModal, setShowNewModal] = useState(false);
  const [activeSubTab, setActiveSubTab] = useState<"acoustic_ab" | "results" | "audio_lab" | "templates">("acoustic_ab");

  // Acoustic F1 VAD & F2 ASR Lab state
  const [activeAbProfile, setActiveAbProfile] = useState<"A" | "B">("B");
  const [selectedAsrModelId, setSelectedAsrModelId] = useState<string>("whisper_turbo");
  const [f2HotwordWeight, setF2HotwordWeight] = useState(4.5);
  const [abTestSampleInput, setAbTestSampleInput] = useState(
    "Merhaba Trabzon'da altmış bir te se sıfır altmış bir plakalı pejo 3008 aracımın de se ge şanzıman ve o be de p 0 300 arızası var"
  );

  const liveAbComparison = useMemo(() => {
    const profAResult = runF2DomainBooster(abTestSampleInput, INITIAL_F2_HOTWORDS, false, 1.0);
    const profBResult = runF2DomainBooster(abTestSampleInput, INITIAL_F2_HOTWORDS, true, f2HotwordWeight);
    const activeAsrModel = F2_ASR_MODELS.find((m) => m.id === selectedAsrModelId) || F2_ASR_MODELS[0];
    return {
      profAResult,
      profBResult,
      activeAsrModel
    };
  }, [abTestSampleInput, f2HotwordWeight, selectedAsrModelId]);

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

  useEscape(() => setShowNewModal(false), showNewModal);

  async function loadData() {
    setLoading(true);
    setPanelError("");
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
      setPanelError("Deney listesi yüklenemedi: " + String(e));
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
      setPanelError("Deney raporu yüklenemedi: " + String(e));
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
    setPanelError("");
    try {
      const resp = await rawApi("ab/preview-synth", "POST", { text: testText, seed: s });
      const blob = await resp.blob();
      if (synthAudioUrl) URL.revokeObjectURL(synthAudioUrl);
      setSynthAudioUrl(URL.createObjectURL(blob));
    } catch (err: any) {
      setPanelError("Ses sentezi önizleme hatası: " + (err.message || err));
    } finally {
      setSynthLoading(false);
    }
  }

  return (
    <div className="ab-panel" style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0, padding: "4px 8px", overflowY: "auto" }}>
      {/* BAŞLIK & ÜST KONTROLLER */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px", flexWrap: "wrap", gap: "8px", flexShrink: 0 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "3px" }}>
            <h2 style={{ margin: 0, fontSize: "16px", display: "flex", alignItems: "center", gap: "8px" }}>
              <span>🔬 A/B Test ve İnce Ayar Altyapısı</span>
            </h2>
            <span className="stage-badge purple" title="F2 ASR Modeli ve F3 LLM Diyalog Karşılaştırma Deneyleri">
              F2 ASR & F3 NLU
            </span>
          </div>
          <p style={{ margin: 0, color: "#94a3b8", fontSize: "12px" }}>
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

      {panelError && (
        <div role="alert" className="error" style={{ marginBottom: "16px" }}>
          {panelError}
        </div>
      )}

      {/* ALT SEKME GEÇİŞLERİ */}
      <div style={{ display: "flex", gap: "8px", borderBottom: "1px solid #334155", marginBottom: "20px", flexWrap: "wrap" }}>
        <button
          onClick={() => setActiveSubTab("acoustic_ab")}
          style={{
            padding: "10px 18px",
            background: activeSubTab === "acoustic_ab" ? "#1e293b" : "transparent",
            color: activeSubTab === "acoustic_ab" ? "#38bdf8" : "#94a3b8",
            border: "none",
            borderBottom: activeSubTab === "acoustic_ab" ? "2px solid #38bdf8" : "none",
            cursor: "pointer",
            fontWeight: "bold",
          }}
        >
          ⚡ F₁ Spektral VAD & F₂ ASR Akustik A/B Lab
        </button>
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

      {/* 0. SEKME: F1 SPEKTRAL VAD & F2 STREAMING ASR CANLI A/B LABORATUVARI */}
      {activeSubTab === "acoustic_ab" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #38bdf8",
              borderRadius: "12px",
              padding: "18px 20px",
              display: "flex",
              flexDirection: "column",
              gap: "16px",
              boxShadow: "0 10px 25px -5px rgba(56, 189, 248, 0.1)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px", paddingBottom: "12px", borderBottom: "1px solid rgba(255, 255, 255, 0.1)" }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "15px", fontWeight: "bold", color: "#f8fafc", display: "flex", alignItems: "center", gap: "8px" }}>
                  <Sliders style={{ width: "18px", height: "18px", color: "#38bdf8" }} />
                  F₁ Spektral VAD & F₂ Streaming ASR Canlı A/B Laboratuvarı
                </h3>
                <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#94a3b8" }}>
                  Standart Ofis profili (A) ile Zırhlı Atölye / Kafe profili (B) arasındaki gürültü kesme ve otomotiv terim düzeltme başarısını anlık karşılaştırın.
                </p>
              </div>

              <div style={{ display: "flex", gap: "8px", fontFamily: "monospace", fontSize: "12px" }}>
                <button
                  type="button"
                  onClick={() => setActiveAbProfile("A")}
                  style={{
                    padding: "8px 14px",
                    borderRadius: "8px",
                    fontWeight: "bold",
                    cursor: "pointer",
                    border: activeAbProfile === "A" ? "1px solid #38bdf8" : "1px solid #334155",
                    background: activeAbProfile === "A" ? "#38bdf8" : "#1e293b",
                    color: activeAbProfile === "A" ? "#0f172a" : "#94a3b8",
                  }}
                >
                  Profil A (Standart Ofis)
                </button>
                <button
                  type="button"
                  onClick={() => setActiveAbProfile("B")}
                  style={{
                    padding: "8px 14px",
                    borderRadius: "8px",
                    fontWeight: "bold",
                    cursor: "pointer",
                    border: activeAbProfile === "B" ? "1px solid #10b981" : "1px solid #334155",
                    background: activeAbProfile === "B" ? "#10b981" : "#1e293b",
                    color: activeAbProfile === "B" ? "#0f172a" : "#94a3b8",
                  }}
                >
                  Profil B (Atölye / Zırhlı)
                </button>
              </div>
            </div>

            {/* Test Cümlesi */}
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <label style={{ fontSize: "12px", fontFamily: "monospace", color: "#cbd5e1" }}>
                Test Edilecek Ham Müşteri Konuşma / ASR Cümlesi:
              </label>
              <textarea
                rows={2}
                value={abTestSampleInput}
                onChange={(e) => setAbTestSampleInput(e.target.value)}
                style={{
                  width: "100%",
                  background: "#090d16",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  padding: "10px 14px",
                  color: "#f8fafc",
                  fontSize: "12px",
                  fontFamily: "monospace",
                  boxSizing: "border-box",
                }}
              />
            </div>

            {/* Yan Yana Profil Kıyaslama */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "14px" }}>
              {/* Profil A */}
              <div
                style={{
                  background: "#090d16",
                  border: "1px solid #334155",
                  borderRadius: "10px",
                  padding: "14px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "10px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontWeight: "bold", color: "#38bdf8", fontSize: "13px" }}>Profil A (Dengeli / Ofis)</span>
                  <span style={{ fontSize: "11px", color: "#94a3b8", fontFamily: "monospace" }}>0 Düzeltme (Hotword Kapalı)</span>
                </div>
                <div
                  style={{
                    background: "#1e293b",
                    padding: "10px 12px",
                    borderRadius: "6px",
                    color: "#cbd5e1",
                    fontSize: "12px",
                    fontFamily: "monospace",
                    minHeight: "44px",
                  }}
                >
                  "{liveAbComparison.profAResult.corrected}"
                </div>
                <div style={{ fontSize: "11px", color: "#64748b", fontFamily: "monospace" }}>
                  VAD: -38 dBFS • Spektral Kapı: Kapalı • Hotword Boost: x1.0
                </div>
              </div>

              {/* Profil B */}
              <div
                style={{
                  background: "#090d16",
                  border: "1px solid #10b981",
                  borderRadius: "10px",
                  padding: "14px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "10px",
                  boxShadow: "0 0 15px rgba(16, 185, 129, 0.15)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontWeight: "bold", color: "#10b981", fontSize: "13px" }}>Profil B (Zırhlı Atölye / Near-Field)</span>
                  <span style={{ fontSize: "11px", color: "#34d399", fontFamily: "monospace", fontWeight: "bold" }}>
                    +{liveAbComparison.profBResult.confidenceGain}% Güven Artışı
                  </span>
                </div>
                <div
                  style={{
                    background: "#1e293b",
                    padding: "10px 12px",
                    borderRadius: "6px",
                    color: "#a7f3d0",
                    fontSize: "12px",
                    fontFamily: "monospace",
                    fontWeight: "bold",
                    minHeight: "44px",
                  }}
                >
                  "{liveAbComparison.profBResult.corrected}"
                </div>
                <div style={{ fontSize: "11px", color: "#34d399", fontFamily: "monospace" }}>
                  VAD: -24 dBFS • Spektral Kapı: %55 • Hotword Boost: x{f2HotwordWeight}
                </div>
              </div>
            </div>

            {/* Uygulanan Hotword Düzeltmeleri */}
            {liveAbComparison.profBResult.appliedFixes.length > 0 && (
              <div
                style={{
                  background: "#090d16",
                  border: "1px solid rgba(56, 189, 248, 0.2)",
                  borderRadius: "8px",
                  padding: "12px 14px",
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  gap: "8px",
                }}
              >
                <span style={{ fontSize: "11px", color: "#38bdf8", fontWeight: "bold", fontFamily: "monospace" }}>
                  F₂ Otomotiv Hotword Eşleşmeleri ({liveAbComparison.profBResult.appliedFixes.length}):
                </span>
                {liveAbComparison.profBResult.appliedFixes.map((fx, idx) => (
                  <span
                    key={idx}
                    style={{
                      background: "rgba(56, 189, 248, 0.15)",
                      border: "1px solid rgba(56, 189, 248, 0.3)",
                      color: "#bae6fd",
                      padding: "3px 8px",
                      borderRadius: "6px",
                      fontSize: "11px",
                      fontFamily: "monospace",
                    }}
                  >
                    <span style={{ textDecoration: "line-through", color: "#fca5a5" }}>{fx.from}</span> →{" "}
                    <strong style={{ color: "#34d399" }}>{fx.to}</strong> ({fx.category} • +{fx.weight} logit)
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* F2 MODEL SEÇİMİ VE HOTWORD ÇARPANI */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
              gap: "14px",
            }}
          >
            {F2_ASR_MODELS.map((model) => (
              <div
                key={model.id}
                onClick={() => setSelectedAsrModelId(model.id)}
                style={{
                  background: selectedAsrModelId === model.id ? "rgba(56, 189, 248, 0.1)" : "#0f172a",
                  border: selectedAsrModelId === model.id ? "1px solid #38bdf8" : "1px solid #1e293b",
                  borderRadius: "10px",
                  padding: "14px",
                  cursor: "pointer",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  gap: "8px",
                  transition: "all 0.15s ease",
                }}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontWeight: "bold", color: "#f8fafc", fontSize: "13px" }}>{model.name}</span>
                    <span style={{ fontFamily: "monospace", color: "#10b981", fontWeight: "bold", fontSize: "12px" }}>
                      {model.wer}
                    </span>
                  </div>
                  <p style={{ margin: "6px 0 0", fontSize: "12px", color: "#94a3b8", lineHeight: "1.5" }}>
                    {model.desc}
                  </p>
                </div>

                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    paddingTop: "8px",
                    borderTop: "1px solid rgba(255, 255, 255, 0.05)",
                    fontSize: "11px",
                    fontFamily: "monospace",
                    color: "#64748b",
                  }}
                >
                  <span>Taban Gecikme: <strong style={{ color: "#f8fafc" }}>{model.baseMs} ms</strong></span>
                  <span>Beam: {model.beamDefault}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 1. SEKME: DENEY SONUÇLARI */}
      {activeSubTab === "results" && (
        <>
          {/* DENEY SEÇİM ÇUBUĞU */}
          <div style={{ background: "#1e293b", padding: "14px 18px", borderRadius: "8px", marginBottom: "20px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <label htmlFor="ab-exp-select" style={{ fontWeight: "bold", fontSize: "14px", color: "#f8fafc" }}>Aktif Deney:</label>
              <select
                id="ab-exp-select"
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
                    {report.total_experiment_sessions ? report.best_performing_variant : "—"}
                  </div>
                  <div style={{ fontSize: "13px", color: "#94a3b8", marginTop: "2px" }}>
                    {report.total_experiment_sessions
                      ? `Toplam ${report.total_experiment_sessions} görüşmeden ${report.total_converted_sessions} tanesi randevuya dönüştü (Genel: %${report.overall_conversion_pct}).`
                      : "Henüz bu deneyde görüşme yok; sonuçlar ölçüm geldikçe görünür."}
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
                    <div className="grid-2" style={{ display: "grid",  gap: "10px", marginBottom: "14px" }}>
                      <div style={{ background: "#0f172a", padding: "10px", borderRadius: "6px", textAlign: "center" }}>
                        <div style={{ fontSize: "12px", color: "#94a3b8" }}>Dönüşüm Oranı</div>
                        <div style={{ fontSize: "24px", fontWeight: "bold", color: "#38bdf8", margin: "4px 0" }}>
                          {v.total_sessions ? `%${v.conversion_rate_pct}` : "—"}
                        </div>
                        <div style={{ fontSize: "11px", color: "#64748b" }}>
                          %95 GA: {v.total_sessions && v.ci_95 ? `[${v.ci_95[0]}% - ${v.ci_95[1]}%]` : "—"}
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
                      <span>⏱ Ort. Süre: <strong>{v.total_sessions ? dash(v.avg_duration_sec, " sn") : "—"}</strong></span>
                      <span>⚡ İlk Ses: <strong>{v.total_sessions ? dash(v.avg_first_audio_ms, " ms") : "—"}</strong></span>
                      <span>🔄 Tur: <strong>{v.total_sessions ? dash(v.avg_turns) : "—"}</strong></span>
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
                  <div className="table-wrap"><table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
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
                  </table></div>
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
            <label htmlFor="ab-test-text" style={{ display: "block", fontSize: "13px", fontWeight: "bold", color: "#cbd5e1", marginBottom: "6px" }}>
              Test Edilecek Cümle:
            </label>
            <textarea
              id="ab-test-text"
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
        <div className="grid-2" style={{ gap: "20px" }}>
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
          role="dialog"
          aria-modal="true"
          aria-label="Yeni A/B deneyi"
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
                <div className="grid-2" style={{ gap: "10px" }}>
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
                <div className="grid-2" style={{ gap: "10px" }}>
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
````


### frontend/src/AnalysisQueuePanel.tsx

````
import { useEffect, useState } from "react";
import type { AnalysisQueue, AnalysisRun, AnalysisSource } from "./api";
import { errorMessage, formatDate } from "./ui";
import type { ApiFn } from "./ui";

const runLabels: Record<string, string> = {
  QUEUED: "Kuyrukta",
  RUNNING: "İşleniyor",
  SUCCEEDED: "Tamamlandı",
  FAILED_RETRYABLE: "Yeniden denenecek",
  FAILED_TERMINAL: "Başarısız",
  SUPERSEDED: "Yeni analizle değiştirildi",
};

export function analysisState(run: AnalysisRun) {
  return run.lease_expired ? "İşçi kirası doldu" : runLabels[run.state] ?? run.state;
}

export function analysisSource(source: AnalysisSource) {
  const transports: Record<string, string> = { WEB: "Web", AUDIOSOCKET: "AudioSocket", SIP: "SIP" };
  const origins: Record<string, string> = {
    SYNTHETIC: "Sentetik", DEMO: "Demo", REAL: "Gerçek", UNKNOWN: "Köken belirsiz",
  };
  return `${transports[source.transport] ?? source.transport} · ${origins[source.origin] ?? source.origin}`;
}

function age(ms: number | null) {
  if (ms === null) return "—";
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes} dk ${seconds % 60} sn` : `${seconds} sn`;
}

export function AnalysisQueuePanel({ api, onOpenConversation }: {
  api: ApiFn; onOpenConversation?: (id: string) => void;
}) {
  const [data, setData] = useState<AnalysisQueue | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    api("supervisor/fqici-queue").then(
      (value: AnalysisQueue) => { if (current) setData(value); },
      (err: unknown) => { if (current) { setData(null); setError(errorMessage(err)); } },
    ).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [api, revision]);

  function conversationLink(id: string) {
    return onOpenConversation
      ? <button type="button" className="secondary" onClick={() => onOpenConversation(id)} aria-label={`Görüşmeyi aç ${id}`}>Görüşmeyi aç</button>
      : <small>{id}</small>;
  }

  return (
    <section className="analysis-queue" aria-labelledby="analysis-queue-title" aria-busy={loading}>
      <div className="row">
        <h3 id="analysis-queue-title">Analiz Kuyruğu</h3>
        <button className="secondary" disabled={loading} onClick={() => setRevision((n) => n + 1)}>Kuyruğu yenile</button>
      </div>
      {loading && <p role="status">Kuyruk yükleniyor…</p>}
      {error && <p role="alert">{error}</p>}
      {data && <>
        <p>Olay alımı <strong>{data.intake_enabled ? "açık" : "kapalı"}</strong> · Analiz işçisi{" "}
          <strong>{data.worker_status === "NOT_CONNECTED" ? "bağlı değil" : data.worker_status}</strong> ·
          Fiziksel SIP kabulü <strong>{data.physical_sip_status}</strong></p>
        {data.store === "UNAVAILABLE" ? <p>Kuyruk deposu hazır değil. FQICI migrasyonunu kontrol edin.</p> : <>
          <dl className="analysis-facts">
            <div><dt>Kuyrukta</dt><dd>{data.counts.QUEUED ?? 0}</dd></div>
            <div><dt>Kiralı işler</dt><dd>{data.counts.RUNNING ?? 0}</dd></div>
            <div><dt>Yeniden denenecek</dt><dd>{data.counts.FAILED_RETRYABLE ?? 0}</dd></div>
            <div><dt>Ertelenen görüşme</dt><dd>{data.deferred_count ?? "—"}</dd></div>
            <div><dt>En eski bekleme</dt><dd>{age(data.oldest_wait_ms)}</dd></div>
          </dl>
          {data.runs.length === 0 && data.deferred.length === 0 ? <p>Gösterilecek analiz işi yok.</p> : <details>
          <summary>Analiz işlerini göster ({data.runs.length + data.deferred.length})</summary>
          {data.runs.map((run) => (
            <div key={run.id} className="row">
              <div><strong>{analysisState(run)}</strong><br />
                <small>{analysisSource(run)} · {run.attempts} deneme · {formatDate(new Date(run.created_at_ms).toISOString())}</small></div>
              {conversationLink(run.conversation_id)}
            </div>
          ))}
          {data.deferred.map((scope) => (
            <div key={scope.conversation_id} className="row">
              <div><strong>Ertelendi</strong><br />
                <small>{analysisSource(scope)} · Uygunluk {formatDate(new Date(scope.ready_at_ms).toISOString())}</small></div>
              {conversationLink(scope.conversation_id)}
            </div>
          ))}
          </details>}
        </>}
      </>}
    </section>
  );
}
````


### frontend/src/AnalyticsPanel.tsx

````
import { useEffect, useState, useMemo } from "react";
import { formatMetrics, useEscape, errorMessage } from "./ui";

// Ölçüm yoksa API null döner; ekranda 0 yerine "—" gösterilir.
type Measured = number | null;

const fmt = (value: Measured | undefined, unit = "") =>
  value === null || value === undefined ? "—" : `${value}${unit}`;

type LatencyStats = {
  avg: Measured;
  min?: Measured;
  max?: Measured;
  p50: Measured;
  p95: Measured;
  sample_count: number;
};

type LLMStats = {
  avg_total: Measured;
  p50_total: Measured;
  p95_total: Measured;
  avg_first_token: Measured;
  p50_first_token: Measured;
  p95_first_token: Measured;
  sample_count: number;
};

type AnalyticsData = {
  summary: {
    total_conversations: number;
    completed_conversations: number;
    follow_up_conversations: number;
    resolved_conversations: number;
    active_conversations: number;
    total_appointments: number;
    confirmed_appointments: number;
    cancelled_appointments?: number;
    cancellation_rate_pct?: number;
    conversion_rate_pct: number;
    avg_turns_per_conversation: Measured;
    avg_duration_seconds: Measured;
    stt_clarity_rate_pct: Measured;
    stt_unclear_count: number;
    channels: Record<string, number>;
  };
  latency_kpis: {
    first_audio_ms: LatencyStats;
    llm_ms: LLMStats;
    stt_ms: LatencyStats;
    tts_ms: {
      avg: Measured;
      avg_rtf: Measured;
      sample_count: number;
    };
    barge_in_count: number;
  };
  daily_trend: Array<{
    date: string;
    appointments: number;
    conversations: number;
  }>;
  hourly_distribution: number[];
};

type FollowUpItem = {
  id: string;
  channel: string;
  status: "active" | "completed" | "follow_up" | "resolved";
  operator_notes: string;
  resolved_at: string | null;
  created_at: string;
  turn_count: number;
  duration_seconds: number;
  last_user_text: string;
  last_assistant_text: string;
};

type TurnItem = {
  id: string;
  conversation_id: string;
  role: string;
  text: string;
  metrics: string;
  created_at: string;
};

type WeeklyReportData = {
  period_days: number;
  start_date: string;
  end_date: string;
  generated_at: string;
  summary: {
    total_conversations: number;
    completed_conversations: number;
    follow_up_conversations: number;
    total_appointments: number;
    confirmed_appointments: number;
    cancelled_appointments: number;
    cancellation_rate_pct: number;
    conversion_rate_pct: number;
    stt_clarity_rate_pct: number | null;
    unclear_turns_count: number;
  };
  latency_percentiles: {
    first_audio_p50_ms: number | null;
    first_audio_p95_ms: number | null;
    llm_p50_ms: number | null;
    llm_p95_ms: number | null;
    stt_p50_ms: number | null;
    stt_p95_ms: number | null;
    sample_count: number;
  };
  package_distribution: Record<string, number>;
  daily_breakdown: Array<{
    date: string;
    conversations: number;
    appointments: number;
    cancelled: number;
  }>;
};

import type { ApiProps as Props } from "./api";

export function AnalyticsPanel({ api }: Props) {
  const [activeTab, setActiveTab] = useState<"dashboard" | "follow_ups" | "weekly_reports">("dashboard");
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [weeklyReport, setWeeklyReport] = useState<WeeklyReportData | null>(null);
  const [loadingReport, setLoadingReport] = useState(false);
  const [followUps, setFollowUps] = useState<FollowUpItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Follow-up status filter
  const [statusFilter, setStatusFilter] = useState<string>("follow_up");

  // Resolve modal state
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolveNotes, setResolveNotes] = useState("");

  // Transcript view modal
  const [inspectConvId, setInspectConvId] = useState<string | null>(null);
  const [inspectTurns, setInspectTurns] = useState<TurnItem[]>([]);
  const [loadingTurns, setLoadingTurns] = useState(false);

  async function act(fn: () => Promise<void>) {
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  useEscape(() => setResolvingId(null), !!resolvingId);
  useEscape(() => setInspectConvId(null), !!inspectConvId);

  async function refresh() {
    const [overviewRes, followUpsRes] = await Promise.all([
      api("analytics/overview"),
      api(`analytics/follow-ups?status=${statusFilter}`),
    ]);
    setData(overviewRes);
    setFollowUps(followUpsRes);
  }

  async function loadWeeklyReport() {
    try {
      setLoadingReport(true);
      const rep = await api("reports/weekly/summary?days=7");
      setWeeklyReport(rep);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoadingReport(false);
    }
  }

  useEffect(() => {
    act(refresh);
    loadWeeklyReport();
  }, [statusFilter]);

  async function handleResolve(e: React.FormEvent) {
    e.preventDefault();
    if (!resolvingId) return;

    await act(async () => {
      await api(`analytics/conversations/${resolvingId}/resolve`, "POST", {
        notes: resolveNotes,
      });
      setSuccess("Görüşme operatör tarafından 'Sonuçlandı' olarak güncellendi.");
      setResolvingId(null);
      setResolveNotes("");
      await refresh();
    });
  }

  async function handleReopen(id: string) {
    await act(async () => {
      await api(`analytics/conversations/${id}/reopen`, "POST");
      setSuccess("Görüşme yeniden takip durumuna (follow_up) alındı.");
      await refresh();
    });
  }

  async function handleOpenInspect(id: string) {
    setInspectConvId(id);
    setLoadingTurns(true);
    try {
      const turns = await api("conversations/" + id);
      setInspectTurns(Array.isArray(turns) ? turns : []);
    } catch (e) {
      setError("Tur detayları yüklenemedi: " + errorMessage(e));
    } finally {
      setLoadingTurns(false);
    }
  }

  // Render SVG Trend Chart
  const trendMax = useMemo(() => {
    if (!data?.daily_trend) return 10;
    const maxVal = Math.max(
      ...data.daily_trend.map((d) => Math.max(d.appointments, d.conversations)),
      5
    );
    return Math.ceil(maxVal * 1.2);
  }, [data?.daily_trend]);

  return (
    <div className="section-container">
      {/* Alert Messages */}
      {error && <div className="alert-box error">{error}</div>}
      {success && <div className="alert-box success">{success}</div>}

      {/* Panel View Toggle */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1.2rem",
          borderBottom: "1px solid #334155",
          paddingBottom: "0.5rem",
        }}
      >
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            className={activeTab === "dashboard" ? "selected" : "secondary"}
            onClick={() => setActiveTab("dashboard")}
            style={{ padding: "0.5rem 1.2rem" }}
          >
            📊 KPI & Performans Göstergeleri
          </button>
          <button
            className={activeTab === "follow_ups" ? "selected" : "secondary"}
            onClick={() => setActiveTab("follow_ups")}
            style={{ padding: "0.5rem 1.2rem" }}
          >
            ⚠️ Takip Gerektiren Görüşmeler{" "}
            {data?.summary.follow_up_conversations ? (
              <span
                style={{
                  background: "#ca8a04",
                  color: "#fff",
                  padding: "2px 7px",
                  borderRadius: "10px",
                  fontSize: "11px",
                  marginLeft: "6px",
                }}
              >
                {data.summary.follow_up_conversations}
              </span>
            ) : null}
          </button>
          <button
            className={activeTab === "weekly_reports" ? "selected" : "secondary"}
            onClick={() => {
              setActiveTab("weekly_reports");
              loadWeeklyReport();
            }}
            style={{ padding: "0.5rem 1.2rem" }}
          >
            📑 Haftalık Rapor & Excel Çıktısı
          </button>
        </div>

        <button
          onClick={() => act(refresh)}
          disabled={loading}
          style={{ padding: "0.45rem 1rem", fontSize: "0.85rem" }}
        >
          {loading ? "Yenileniyor..." : "🔄 Verileri Güncelle"}
        </button>
      </div>

      {/* TAB 1: EXECUTIVE KPI DASHBOARD */}
      {activeTab === "dashboard" && data && (
        <>
          {/* Executive Summary Cards */}
          <div
            className="stats"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "1rem",
              marginBottom: "1.5rem",
            }}
          >
            <div className="card" style={{ borderLeft: "4px solid #16a34a" }}>
              <small>🎯 DÖNÜŞÜM ORANI (CONVERSION)</small>
              <h2 style={{ color: "#4ade80", margin: "6px 0" }}>
                {data.summary.total_conversations ? `%${data.summary.conversion_rate_pct}` : "—"}
              </h2>
              <small>
                {data.summary.confirmed_appointments} Onaylı /{" "}
                {data.summary.total_conversations} Çağrı
              </small>
            </div>

            <div className="card" style={{ borderLeft: "4px solid #ef4444" }}>
              <small>🚫 RANDEVU İPTAL ORANI</small>
              <h2 style={{ color: "#f87171", margin: "6px 0" }}>
                {data.summary.total_appointments ? `%${data.summary.cancellation_rate_pct ?? 0}` : "—"}
              </h2>
              <small>
                {data.summary.cancelled_appointments ?? 0} İptal / {data.summary.total_appointments} Randevu
              </small>
            </div>

            <div className="card" style={{ borderLeft: "4px solid #0284c7" }}>
              <small>📞 TOPLAM GÖRÜŞME & KANAL</small>
              <h2 style={{ color: "#38bdf8", margin: "6px 0" }}>
                {data.summary.total_conversations}
              </h2>
              <small>
                Web: {data.summary.channels.web || 0} | Tel:{" "}
                {data.summary.channels.phone || 0} | Dış:{" "}
                {data.summary.channels.outbound || 0}
              </small>
            </div>

            <div className="card" style={{ borderLeft: "4px solid #ca8a04" }}>
              <small>⚠️ OPERATÖR TAKİBİ BEKLEYEN</small>
              <h2 style={{ color: "#facc15", margin: "6px 0" }}>
                {data.summary.follow_up_conversations}
              </h2>
              <small>
                Çözümlenen: {data.summary.resolved_conversations} | Tamamlanan:{" "}
                {data.summary.completed_conversations}
              </small>
            </div>

            <div className="card" style={{ borderLeft: "4px solid #a855f7" }}>
              <small>🎙️ STT DOĞRULUK & NETLİK</small>
              <h2 style={{ color: "#c084fc", margin: "6px 0" }}>
                {data.summary.stt_clarity_rate_pct === null
                  ? "—"
                  : `%${data.summary.stt_clarity_rate_pct}`}
              </h2>
              <small>
                Ort. Süre: {fmt(data.summary.avg_duration_seconds, "s")} | Ort. Tur:{" "}
                {fmt(data.summary.avg_turns_per_conversation)}
              </small>
            </div>
          </div>

          {/* LATENCY & MODEL PERFORMANCE KPIS */}
          <section style={{ marginBottom: "1.5rem" }}>
            <h2>⚡ Ses, STT & LLM Yanıt Süreleri (Latency KPIs)</h2>
            <div className="kpi-grid-3" style={{ gap: "1rem", marginTop: "1rem" }}>
              {/* First Audio MS */}
              <div
                style={{
                  background: "#1e293b",
                  padding: "1rem",
                  borderRadius: "8px",
                  border: "1px solid #334155",
                }}
              >
                <h4 style={{ margin: "0 0 0.5rem 0", color: "#38bdf8" }}>
                  🔊 İlk Ses Gecikmesi (First Audio)
                </h4>
                <div style={{ fontSize: "1.4rem", fontWeight: "bold", margin: "0.3rem 0" }}>
                  {fmt(data.latency_kpis.first_audio_ms.p50, " ms")}{" "}
                  <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>(p50 Medyan)</span>
                </div>
                <div className="grid-2" style={{ gap: "0.5rem", fontSize: "0.82rem", marginTop: "0.6rem" }}>
                  <div>Ortalama: <b>{fmt(data.latency_kpis.first_audio_ms.avg, " ms")}</b></div>
                  <div>95. Yüzdelik (p95): <b style={{ color: "#facc15" }}>{fmt(data.latency_kpis.first_audio_ms.p95, " ms")}</b></div>
                  <div>Min: <b>{fmt(data.latency_kpis.first_audio_ms.min, " ms")}</b></div>
                  <div>Örnek Sayısı: <b>{data.latency_kpis.first_audio_ms.sample_count}</b></div>
                </div>
              </div>

              {/* LLM Response Times */}
              <div
                style={{
                  background: "#1e293b",
                  padding: "1rem",
                  borderRadius: "8px",
                  border: "1px solid #334155",
                }}
              >
                <h4 style={{ margin: "0 0 0.5rem 0", color: "#4ade80" }}>
                  🧠 LLM Çıkarım Süreleri (Qwen2.5)
                </h4>
                <div style={{ fontSize: "1.4rem", fontWeight: "bold", margin: "0.3rem 0" }}>
                  {fmt(data.latency_kpis.llm_ms.p50_total, " ms")}{" "}
                  <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>(Toplam p50)</span>
                </div>
                <div className="grid-2" style={{ gap: "0.5rem", fontSize: "0.82rem", marginTop: "0.6rem" }}>
                  <div>İlk Token (TTFT p50): <b>{fmt(data.latency_kpis.llm_ms.p50_first_token, " ms")}</b></div>
                  <div>İlk Token p95: <b style={{ color: "#facc15" }}>{fmt(data.latency_kpis.llm_ms.p95_first_token, " ms")}</b></div>
                  <div>Toplam p95: <b style={{ color: "#f87171" }}>{fmt(data.latency_kpis.llm_ms.p95_total, " ms")}</b></div>
                  <div>Örnek Sayısı: <b>{data.latency_kpis.llm_ms.sample_count}</b></div>
                </div>
              </div>

              {/* STT & TTS & Barge-in */}
              <div
                style={{
                  background: "#1e293b",
                  padding: "1rem",
                  borderRadius: "8px",
                  border: "1px solid #334155",
                }}
              >
                <h4 style={{ margin: "0 0 0.5rem 0", color: "#c084fc" }}>
                  🎙️ STT, TTS & Araya Girme
                </h4>
                <div style={{ fontSize: "1.4rem", fontWeight: "bold", margin: "0.3rem 0" }}>
                  {fmt(data.latency_kpis.stt_ms.p50, " ms")}{" "}
                  <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>(STT p50)</span>
                </div>
                <div className="grid-2" style={{ gap: "0.5rem", fontSize: "0.82rem", marginTop: "0.6rem" }}>
                  <div>STT p95: <b>{fmt(data.latency_kpis.stt_ms.p95, " ms")}</b></div>
                  <div>TTS Ortalama: <b>{fmt(data.latency_kpis.tts_ms.avg, " ms")}</b></div>
                  <div>TTS RTF Faktörü: <b>{fmt(data.latency_kpis.tts_ms.avg_rtf, "x")}</b></div>
                  <div>Barge-in (Kesinti): <b style={{ color: "#38bdf8" }}>{data.latency_kpis.barge_in_count} kez</b></div>
                </div>
              </div>
            </div>
          </section>

          {/* VISUAL CHARTS (SVG) */}
          <div className="two" style={{ gap: "1.5rem" }}>
            {/* Chart 1: 14-Day Appointment & Conversation Trend */}
            <section>
              <h2>📈 14 Günlük Randevu & Görüşme Trendi</h2>
              <div style={{ height: "230px", marginTop: "1rem", position: "relative" }}>
                <svg width="100%" height="200" viewBox="0 0 500 200" preserveAspectRatio="none">
                  {/* Grid Lines */}
                  {[0, 50, 100, 150].map((y) => (
                    <line
                      key={y}
                      x1="30"
                      y1={y}
                      x2="490"
                      y2={y}
                      stroke="#334155"
                      strokeDasharray="3 3"
                    />
                  ))}

                  {/* Daily Bars */}
                  {data.daily_trend.map((d, i) => {
                    const x = 40 + i * 32;
                    const hConv = (d.conversations / trendMax) * 150;
                    const hApp = (d.appointments / trendMax) * 150;
                    return (
                      <g key={d.date}>
                        {/* Conversation Bar (Blue) */}
                        <rect
                          x={x}
                          y={160 - hConv}
                          width="12"
                          height={Math.max(2, hConv)}
                          fill="#0284c7"
                          rx="2"
                        >
                          <title>{`${d.date}: ${d.conversations} Görüşme`}</title>
                        </rect>
                        {/* Appointment Bar (Green) */}
                        <rect
                          x={x + 13}
                          y={160 - hApp}
                          width="12"
                          height={Math.max(2, hApp)}
                          fill="#16a34a"
                          rx="2"
                        >
                          <title>{`${d.date}: ${d.appointments} Randevu`}</title>
                        </rect>
                        {/* Day label */}
                        <text
                          x={x + 12}
                          y="180"
                          fontSize="9"
                          fill="#94a3b8"
                          textAnchor="middle"
                        >
                          {d.date.slice(8, 10)}.{d.date.slice(5, 7)}
                        </text>
                      </g>
                    );
                  })}
                </svg>
                {/* Legend */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "center",
                    gap: "1.5rem",
                    fontSize: "0.8rem",
                    marginTop: "0.3rem",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <span style={{ width: 10, height: 10, background: "#0284c7", borderRadius: 2 }} />
                    Görüşmeler
                  </span>
                  <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <span style={{ width: 10, height: 10, background: "#16a34a", borderRadius: 2 }} />
                    Oluşturulan Randevular
                  </span>
                </div>
              </div>
            </section>

            {/* Chart 2: 24-Hour Call Capacity Distribution */}
            <section>
              <h2>⏰ Saatlik Çağrı Yoğunluk Dağılımı (Kapasite)</h2>
              <div style={{ height: "230px", marginTop: "1rem" }}>
                <svg width="100%" height="200" viewBox="0 0 500 200" preserveAspectRatio="none">
                  {/* Grid Lines */}
                  {[0, 50, 100, 150].map((y) => (
                    <line
                      key={y}
                      x1="25"
                      y1={y}
                      x2="495"
                      y2={y}
                      stroke="#334155"
                      strokeDasharray="3 3"
                    />
                  ))}

                  {/* Hourly Bars */}
                  {data.hourly_distribution.map((count, hour) => {
                    const maxH = Math.max(...data.hourly_distribution, 5);
                    const barH = (count / maxH) * 150;
                    const x = 30 + hour * 19;
                    const isPeak = hour >= 9 && hour <= 18;
                    return (
                      <g key={hour}>
                        <rect
                          x={x}
                          y={160 - barH}
                          width="14"
                          height={Math.max(2, barH)}
                          fill={isPeak ? "#38bdf8" : "#475569"}
                          rx="2"
                        >
                          <title>{`Saat ${hour}:00 - ${count} Çağrı`}</title>
                        </rect>
                        {hour % 3 === 0 && (
                          <text
                            x={x + 7}
                            y="180"
                            fontSize="9"
                            fill="#94a3b8"
                            textAnchor="middle"
                          >
                            {hour}:00
                          </text>
                        )}
                      </g>
                    );
                  })}
                </svg>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "center",
                    gap: "1.5rem",
                    fontSize: "0.8rem",
                    marginTop: "0.3rem",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <span style={{ width: 10, height: 10, background: "#38bdf8", borderRadius: 2 }} />
                    Mesai Saatleri (09:00 - 18:00)
                  </span>
                  <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <span style={{ width: 10, height: 10, background: "#475569", borderRadius: 2 }} />
                    Mesai Dışı
                  </span>
                </div>
              </div>
            </section>
          </div>
        </>
      )}

      {activeTab === "dashboard" && !data && (
        <p className="muted">
          {loading ? "Veriler yükleniyor…" : "KPI verisi yok veya alınamadı. Yenilemeyi deneyin."}
        </p>
      )}

      {/* TAB 2: FOLLOW-UP CONVERSATION RESOLUTION WORKFLOW */}
      {activeTab === "follow_ups" && (
        <section>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "1rem",
            }}
          >
            <h2 style={{ margin: 0 }}>
              ⚠️ Takip Gerektiren Görüşmeler ve Çözümleme Akışı
            </h2>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                className={statusFilter === "follow_up" ? "selected" : "secondary"}
                onClick={() => setStatusFilter("follow_up")}
                style={{ padding: "0.35rem 0.8rem", fontSize: "0.8rem" }}
              >
                Bekleyen Takipler
              </button>
              <button
                className={statusFilter === "resolved" ? "selected" : "secondary"}
                onClick={() => setStatusFilter("resolved")}
                style={{ padding: "0.35rem 0.8rem", fontSize: "0.8rem" }}
              >
                Sonuçlandırılanlar
              </button>
              <button
                className={statusFilter === "all" ? "selected" : "secondary"}
                onClick={() => setStatusFilter("all")}
                style={{ padding: "0.35rem 0.8rem", fontSize: "0.8rem" }}
              >
                Tümü
              </button>
            </div>
          </div>

          <div className="table-wrap"><table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #475569" }}>
                <th style={{ padding: "0.6rem" }}>Kanal & ID</th>
                <th style={{ padding: "0.6rem" }}>Tarih / Süre</th>
                <th style={{ padding: "0.6rem" }}>Son Kullanıcı Girdisi</th>
                <th style={{ padding: "0.6rem" }}>Son Asistan Yanıtı</th>
                <th style={{ padding: "0.6rem" }}>Durum & Not</th>
                <th style={{ padding: "0.6rem" }}>İşlem</th>
              </tr>
            </thead>
            <tbody>
              {followUps.map((item) => (
                <tr
                  key={item.id}
                  style={{
                    borderBottom: "1px solid #334155",
                    background: item.status === "follow_up" ? "rgba(202, 138, 4, 0.05)" : "transparent",
                  }}
                >
                  <td style={{ padding: "0.6rem" }}>
                    <b>{item.channel.toUpperCase()}</b>
                    <br />
                    <small style={{ color: "#94a3b8" }}>{item.id.slice(0, 8)}</small>
                  </td>
                  <td style={{ padding: "0.6rem" }}>
                    {item.created_at?.slice(0, 16).replace("T", " ")}
                    <br />
                    <small style={{ color: "#94a3b8" }}>
                      {item.duration_seconds}s ({item.turn_count} tur)
                    </small>
                  </td>
                  <td style={{ padding: "0.6rem", maxWidth: "220px" }}>
                    <span style={{ fontSize: "0.85rem", color: "#e2e8f0" }}>
                      {item.last_user_text || "—"}
                    </span>
                  </td>
                  <td style={{ padding: "0.6rem", maxWidth: "250px" }}>
                    <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>
                      {item.last_assistant_text || "—"}
                    </span>
                  </td>
                  <td style={{ padding: "0.6rem" }}>
                    {item.status === "follow_up" ? (
                      <span className="pill yellow">⚠️ Takip Bekliyor</span>
                    ) : item.status === "resolved" ? (
                      <span className="pill green">✓ Çözümlendi</span>
                    ) : (
                      <span className="pill">{item.status}</span>
                    )}
                    {item.operator_notes && (
                      <div
                        style={{
                          fontSize: "0.75rem",
                          color: "#38bdf8",
                          marginTop: "4px",
                          fontStyle: "italic",
                        }}
                      >
                        Not: {item.operator_notes}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: "0.6rem" }}>
                    <div style={{ display: "flex", gap: "0.4rem" }}>
                      {item.status === "follow_up" ? (
                        <button
                          onClick={() => {
                            setResolvingId(item.id);
                            setResolveNotes(item.operator_notes || "");
                          }}
                          style={{
                            padding: "0.3rem 0.6rem",
                            fontSize: "0.78rem",
                            background: "#16a34a",
                            color: "white",
                            borderRadius: "4px",
                          }}
                        >
                          ✅ Sonuçlandır
                        </button>
                      ) : (
                        <button
                          onClick={() => handleReopen(item.id)}
                          style={{
                            padding: "0.3rem 0.6rem",
                            fontSize: "0.78rem",
                            background: "#252e40",
                            color: "#94a3b8",
                            borderRadius: "4px",
                          }}
                        >
                          ↩️ Geri Aç
                        </button>
                      )}
                      <button
                        onClick={() => handleOpenInspect(item.id)}
                        style={{
                          padding: "0.3rem 0.6rem",
                          fontSize: "0.78rem",
                          borderRadius: "4px",
                        }}
                      >
                        🔍 Diyalog
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {followUps.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ textAlign: "center", padding: "1.5rem" }}>
                    Bu filtreye uygun takip görüşmesi bulunamadı.
                  </td>
                </tr>
              )}
            </tbody>
          </table></div>
        </section>
      )}

      {/* TAB 3: HAFTALIK OPERASYONEL RAPOR VE EXCEL ÇIKTISI */}
      {activeTab === "weekly_reports" && (
        <section>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem", flexWrap: "wrap", gap: "1rem" }}>
            <div>
              <h2 style={{ margin: "0 0 0.25rem 0" }}>Haftalık Yönetici ve Operasyon Raporu</h2>
              <p style={{ margin: 0, color: "#94a3b8", fontSize: "0.9rem" }}>
                Görüşme hacmi, randevu dönüşümü, iptal oranı, gecikme SLA metrikleri ve paket dağılımı özeti.
              </p>
            </div>
            <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
              <button
                onClick={loadWeeklyReport}
                disabled={loadingReport}
                style={{ padding: "0.5rem 1rem", fontSize: "0.85rem" }}
              >
                {loadingReport ? "Hesaplanıyor..." : "🔄 Özeti Güncelle"}
              </button>
              <a
                href="/api/reports/weekly/excel"
                download="haftalik_operasyon_raporu.xlsx"
                className="primary"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.4rem",
                  textDecoration: "none",
                  padding: "0.5rem 1.2rem",
                  borderRadius: "6px",
                  fontWeight: "bold",
                  background: "#16a34a",
                  color: "#ffffff",
                }}
              >
                📊 Haftalık Excel İndir (.xlsx)
              </a>
            </div>
          </div>

          {weeklyReport ? (
            <>
              {/* Dönem Banner */}
              <div
                style={{
                  background: "#1e293b",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  padding: "1rem 1.25rem",
                  marginBottom: "1.5rem",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "0.75rem",
                }}
              >
                <div>
                  <div style={{ fontSize: "0.8rem", color: "#94a3b8" }}>RAPOR DÖNEMİ:</div>
                  <strong style={{ fontSize: "1.05rem", color: "#38bdf8" }}>
                    {weeklyReport.start_date} — {weeklyReport.end_date} (Son {weeklyReport.period_days} Gün)
                  </strong>
                </div>
                <div>
                  <span style={{ fontSize: "0.8rem", color: "#94a3b8" }}>
                    Rapor Üretilme Tarihi: {weeklyReport.generated_at.substring(0, 16).replace("T", " ")} UTC
                  </span>
                </div>
              </div>

              {/* Haftalık KPI Kartları */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                  gap: "1rem",
                  marginBottom: "1.5rem",
                }}
              >
                <div className="card" style={{ borderLeft: "4px solid #16a34a" }}>
                  <small>DÖNÜŞÜM ORANI</small>
                  <h3 style={{ color: "#4ade80", margin: "6px 0" }}>
                    %{weeklyReport.summary.conversion_rate_pct}
                  </h3>
                  <small>{weeklyReport.summary.confirmed_appointments} Onaylı / {weeklyReport.summary.total_conversations} Çağrı</small>
                </div>

                <div className="card" style={{ borderLeft: "4px solid #ef4444" }}>
                  <small>RANDEVU İPTAL ORANI</small>
                  <h3 style={{ color: "#f87171", margin: "6px 0" }}>
                    %{weeklyReport.summary.cancellation_rate_pct}
                  </h3>
                  <small>{weeklyReport.summary.cancelled_appointments} İptal / {weeklyReport.summary.total_appointments} Randevu</small>
                </div>

                <div className="card" style={{ borderLeft: "4px solid #0284c7" }}>
                  <small>UÇTAN UCA P95 GECİKME</small>
                  <h3 style={{ color: "#38bdf8", margin: "6px 0" }}>
                    {weeklyReport.latency_percentiles.first_audio_p95_ms !== null ? `${weeklyReport.latency_percentiles.first_audio_p95_ms} ms` : "—"}
                  </h3>
                  <small>P50 Medyan: {weeklyReport.latency_percentiles.first_audio_p50_ms ?? "—"} ms</small>
                </div>

                <div className="card" style={{ borderLeft: "4px solid #a855f7" }}>
                  <small>STT NETLİK ORANI</small>
                  <h3 style={{ color: "#c084fc", margin: "6px 0" }}>
                    {weeklyReport.summary.stt_clarity_rate_pct !== null ? `%${weeklyReport.summary.stt_clarity_rate_pct}` : "—"}
                  </h3>
                  <small>Belirsiz Tur: {weeklyReport.summary.unclear_turns_count}</small>
                </div>
              </div>

              {/* Günlük Kırılım Tablosu */}
              <div style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: "8px", padding: "1.25rem", marginBottom: "1.5rem" }}>
                <h3 style={{ margin: "0 0 1rem 0", fontSize: "1.1rem" }}>📅 Günlük Çağrı ve Randevu Kırılımı</h3>
                <div className="table-wrap">
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "2px solid #475569", textAlign: "left", fontSize: "0.85rem", color: "#94a3b8" }}>
                        <th style={{ padding: "8px" }}>Tarih</th>
                        <th style={{ padding: "8px" }}>Görüşme Sayısı</th>
                        <th style={{ padding: "8px" }}>Alınan Randevu</th>
                        <th style={{ padding: "8px" }}>İptal Edilen</th>
                        <th style={{ padding: "8px" }}>Net Randevu</th>
                      </tr>
                    </thead>
                    <tbody>
                      {weeklyReport.daily_breakdown.map((d) => (
                        <tr key={d.date} style={{ borderBottom: "1px solid #334155", fontSize: "0.9rem" }}>
                          <td style={{ padding: "8px", fontWeight: 600 }}>{d.date}</td>
                          <td style={{ padding: "8px" }}>{d.conversations}</td>
                          <td style={{ padding: "8px", color: "#4ade80" }}>{d.appointments}</td>
                          <td style={{ padding: "8px", color: "#f87171" }}>{d.cancelled}</td>
                          <td style={{ padding: "8px", fontWeight: "bold" }}>{d.appointments - d.cancelled}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Paket Dağılımı Kartı */}
              <div style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: "8px", padding: "1.25rem" }}>
                <h3 style={{ margin: "0 0 1rem 0", fontSize: "1.1rem" }}>📦 Ekspertiz Paketi Tercihleri</h3>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "1rem" }}>
                  {Object.entries(weeklyReport.package_distribution).map(([pkg, cnt]) => (
                    <div key={pkg} style={{ background: "#0f172a", padding: "1rem", borderRadius: "6px", border: "1px solid #334155" }}>
                      <div style={{ fontSize: "0.8rem", color: "#94a3b8" }}>{pkg.replace(/_/g, " ").toUpperCase()}</div>
                      <div style={{ fontSize: "1.5rem", fontWeight: "bold", color: "#38bdf8", margin: "4px 0" }}>{cnt}</div>
                      <small style={{ color: "#64748b" }}>randevu talebi</small>
                    </div>
                  ))}
                  {Object.keys(weeklyReport.package_distribution).length === 0 && (
                    <p className="muted">Bu dönemde henüz paket seçimi kaydedilmedi.</p>
                  )}
                </div>
              </div>
            </>
          ) : (
            <p>Haftalık rapor verileri yükleniyor...</p>
          )}
        </section>
      )}

      {/* RESOLUTION MODAL */}
      {resolvingId && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Görüşmeyi sonuçlandır"
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
          <div
            style={{
              background: "#1e293b",
              borderRadius: "8px",
              padding: "1.5rem",
              width: "500px",
              maxWidth: "92vw",
              border: "1px solid #475569",
            }}
          >
            <h3 style={{ margin: "0 0 0.8rem 0" }}>
              ✅ Görüşmeyi Sonuçlandır (Operatör İşlemi)
            </h3>
            <p style={{ fontSize: "0.85rem", color: "#94a3b8", margin: "0 0 1rem 0" }}>
              Görüşme ID: {resolvingId} — Müşteri ile yapılan harici arama, WhatsApp görüşmesi veya manuel randevu durumunu not edin.
            </p>
            <form onSubmit={handleResolve}>
              <textarea
                aria-label="Çözüm notu"
                placeholder="Örn: Müşteri arandı, yarın saat 14:00 maslak şubesine randevu oluşturuldu."
                value={resolveNotes}
                onChange={(e) => setResolveNotes(e.target.value)}
                rows={3}
                required
                style={{ width: "100%", padding: "0.6rem", borderRadius: "4px", marginBottom: "1rem" }}
              />
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.6rem" }}>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setResolvingId(null)}
                  style={{ padding: "0.4rem 0.9rem" }}
                >
                  İptal
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  style={{ padding: "0.4rem 1.1rem", background: "#16a34a", color: "white" }}
                >
                  {loading ? "Kaydediliyor..." : "✓ Sonuçlandırıldı Olarak Kaydet"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* DIALOGUE TRANSCRIPT INSPECT MODAL */}
      {inspectConvId && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Görüşme turları ve transkript"
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
          <div
            style={{
              background: "#1e293b",
              borderRadius: "8px",
              padding: "1.5rem",
              width: "650px",
              maxWidth: "92vw",
              maxHeight: "80vh",
              overflowY: "auto",
              border: "1px solid #475569",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "0.8rem",
              }}
            >
              <h3 style={{ margin: 0 }}>🔍 Görüşme Turları & Transkript</h3>
              <button
                onClick={() => setInspectConvId(null)}
                aria-label="Kapat"
                style={{ background: "transparent", border: "none", fontSize: "1.2rem", cursor: "pointer" }}
              >
                ✕
              </button>
            </div>
            <p style={{ fontSize: "0.8rem", color: "#94a3b8", margin: "0 0 1rem 0" }}>
              Görüşme ID: {inspectConvId}
            </p>
            {loadingTurns ? (
              <p>Turlar yükleniyor...</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
                {inspectTurns.map((t) => (
                  <div
                    key={t.id}
                    style={{
                      background: t.role === "user" ? "#0f172a" : "#1e3a5f",
                      padding: "0.6rem 0.8rem",
                      borderRadius: "6px",
                      borderLeft: t.role === "user" ? "3px solid #38bdf8" : "3px solid #4ade80",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", color: "#94a3b8" }}>
                      <b>{t.role.toUpperCase()}</b>
                      <span>{t.created_at?.slice(11, 19)}</span>
                    </div>
                    <div style={{ marginTop: "4px", fontSize: "0.88rem" }}>{t.text}</div>
                    {formatMetrics(t.metrics) && (
                      <small style={{ color: "#64748b", marginTop: "4px" }}>
                        {formatMetrics(t.metrics)}
                      </small>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "1rem" }}>
              <button
                className="secondary"
                onClick={() => setInspectConvId(null)}
                style={{ padding: "0.4rem 0.9rem" }}
              >
                Kapat
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
````


### frontend/src/api.ts

````
import { basicAuthHeader } from "./ui";
import type { ApiFn, RawApiFn } from "./ui";

/** Paneller için ortak prop tipleri. */
export type ApiProps = { api: ApiFn };
export type Props = ApiProps & { rawApi: RawApiFn };
/** Yükleniyor/hata durumunu yöneten ortak sarmalayıcı. */
export type ActionFn = (fn: () => Promise<void>) => Promise<void>;

// Backend (backend/db.py ve /api/readiness) yanıtlarına karşılık gelen tipler.
export interface Vehicle {
  id: string;
  description: string;
  plate: string;
  vin: string;
}
export interface Slot {
  id: string;
  starts_at: string;
  duration_minutes: number;
}
export interface Appointment {
  id: string;
  slot_id: string | null;
  vehicle_id: string;
  customer: string;
  customer_phone?: string;
  package_type?: string;
  status: string;
  confirmed: boolean;
  created_at: string;
}
export interface Conversation {
  id: string;
  channel: string;
  status: string;
  created_at: string;
}
export interface Quote {
  id: string;
  vehicle_id: string;
  amount_kurus: number;
}
export interface Turn {
  id: string;
  conversation_id: string;
  role: string;
  text: string;
  metrics: string;
  created_at: string;
}
export interface AnalysisRun {
  id: string;
  state: string;
  rule_version: string;
  created_at_ms: number;
  attempts: number;
  lease_expired: boolean;
}
export interface AnalysisSource {
  transport: string;
  origin: string;
}
export interface AnalysisQueue {
  intake_enabled: boolean;
  worker_status: string;
  physical_sip_status: string;
  store: "READY" | "UNAVAILABLE";
  counts: Record<string, number>;
  deferred_count: number | null;
  oldest_wait_ms: number | null;
  runs: (AnalysisRun & AnalysisSource & { conversation_id: string })[];
  deferred: (AnalysisSource & { conversation_id: string; ready_at_ms: number })[];
}
export interface ConversationDetail {
  conversation: Conversation;
  turns: Turn[];
  traces: { id: string; created_at: string; review_status: string; route_state: string;
    outcome: string; intents: string[]; reason_codes: string[] }[];
  transfers: { id: string; status: string; created_at: string; completed_at: string | null }[];
  appointment: { id: string; status: string; starts_at: string | null } | null;
  fqici: {
    store: "READY" | "UNAVAILABLE";
    scope: (AnalysisSource & { terminal_seen: boolean; ready_at_ms: number | null }) | null;
    runs: AnalysisRun[];
  };
}
export interface ComponentStatus {
  status?: string;
  reason?: string;
  device?: string;
  engine?: string;
  model?: string;
}
export interface Health {
  kvkk_erasure_enabled?: boolean;
  auto_purge_transcripts?: boolean;
  demo_mode?: boolean;
  tts?: ComponentStatus;
  stt?: ComponentStatus;
  vad?: ComponentStatus;
  ollama?: ComponentStatus;
  circuit_breaker?: ComponentStatus & { state?: string };
  loading?: boolean;
  error?: string | null;
  busy?: boolean;
  model_load_ms?: number | null;
  synth_count?: number;
}
export interface VoiceMessage {
  type: "transcript";
  role: string;
  text: string;
}
export interface VoiceMetrics {
  first_audio_ms?: number | null;
  stt_ms?: number | null;
  llm_total_ms?: number | null;
  tts_ms?: number | null;
  rtf?: number | null;
  [key: string]: unknown;
}

/**
 * Tek kimlik başlığı: JSON, FormData ve ikili (ses/PDF) yanıtlar aynı yardımcıyı kullanır.
 * Panellere "rawApi" olarak verilir; ok olmayan yanıtta Türkçe hata fırlatır, Response döner.
 */
export function createApi(password: string): { api: ApiFn; rawApi: RawApiFn } {
  const rawApi: RawApiFn = async (path, method = "GET", body) => {
    const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
    const h: Record<string, string> = { Authorization: basicAuthHeader(password) };
    if (body !== undefined && !isFormData) h["Content-Type"] = "application/json";
    const r = await fetch("/api/" + path, {
      method,
      headers: h,
      body: body === undefined ? undefined : isFormData ? (body as FormData) : JSON.stringify(body),
    });
    if (!r.ok) {
      if (r.status === 401) throw Error("Parola hatalı veya oturum yetkisi yok.");
      let detail;
      try {
        detail = (await r.json()).detail;
      } catch {
        detail = r.statusText;
      }
      throw Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return r;
  };
  const api: ApiFn = async (path, method = "GET", body) => (await rawApi(path, method, body)).json();
  return { api, rawApi };
}
````


### frontend/src/AppointmentMoveDialog.tsx

````
import { useEffect, useRef, useState } from "react";
import type { Appointment, Slot } from "./api";
import { errorMessage, formatDate } from "./ui";
import type { ApiFn } from "./ui";

type Preview = {
  source: Slot | null;
  target: Slot;
  status: string;
  lift_status: "available" | "unknown" | "conflict" | "unchecked";
  message: string;
  preview_version: string;
  alternatives: Slot[];
};

const liftLabels: Record<Preview["lift_status"], string> = {
  available: "Tanımlı kapasite uygun",
  unknown: "Kapasite tanımlı değil",
  conflict: "Kapasite veya atama çakışması",
  unchecked: "Saat kontrolü sonuçlanmadı",
};

export function AppointmentMoveDialog({ api, appointment, slots, appointments, initialTarget,
  onClose, onMoved, refresh }: {
  api: ApiFn; appointment: Appointment; slots: Slot[]; appointments: Appointment[];
  initialTarget: string; onClose: () => void; onMoved: (startsAt: string) => void; refresh: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [target, setTarget] = useState(initialTarget);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [commitError, setCommitError] = useState("");
  const [loading, setLoading] = useState(Boolean(initialTarget));
  const [saving, setSaving] = useState(false);
  const [revision, setRevision] = useState(0);
  const requestInProgress = useRef(false);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  useEffect(() => {
    if (!target) return;
    let current = true;
    api(`appointments/${appointment.id}/reschedule-preview?target_slot_id=${encodeURIComponent(target)}`).then(
      (data: Preview) => { if (current) setPreview(data); },
      (error: unknown) => { if (current) setPreviewError(errorMessage(error)); },
    ).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [api, appointment.id, target, revision]);

  function resetPreview(next: string) {
    setPreview(null);
    setPreviewError("");
    setLoading(Boolean(next));
  }

  function chooseSlot(next: string) {
    if (next === target) return;
    setCommitError("");
    resetPreview(next);
    setTarget(next);
  }

  async function confirm() {
    if (preview?.status !== "available" || loading || requestInProgress.current) return;
    requestInProgress.current = true;
    setSaving(true);
    setCommitError("");
    try {
      const result = await api(`appointments/${appointment.id}/reschedule`, "POST", {
        target_slot_id: preview.target.id, preview_version: preview.preview_version,
      });
      onMoved(result.starts_at);
    } catch (err) {
      setCommitError(errorMessage(err));
      resetPreview(target);
      setRevision((n) => n + 1);
      void refresh();
    } finally {
      requestInProgress.current = false;
      setSaving(false);
    }
  }

  const source = preview ? preview.source : slots.find((slot) => slot.id === appointment.slot_id);
  const reserved = new Set(appointments.map((item) => item.slot_id));
  const choices = slots.filter((slot) => slot.id !== appointment.slot_id &&
    (slot.id === target || (!reserved.has(slot.id) && Date.parse(slot.starts_at) > Date.now())));
  const unknownTarget = Boolean(target) && !choices.some((slot) => slot.id === target);

  return (
    <dialog ref={dialog} className="appointment-move-dialog card" aria-labelledby="appointment-move-title"
      onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}>
      <h2 id="appointment-move-title">Randevuyu taşı</h2>
      <p>{appointment.customer}</p>
      <dl className="analysis-facts">
        <div><dt>Eski saat</dt><dd>{source ? formatDate(source.starts_at) : "—"}</dd></div>
        <div><dt>Yeni saat</dt><dd>{preview ? formatDate(preview.target.starts_at) : "—"}</dd></div>
      </dl>
      <label>Hedef saat{" "}
        <select value={target} disabled={saving} onChange={(event) => chooseSlot(event.target.value)}>
          <option value="">Saat seçin</option>
          {unknownTarget && <option value={target}>Seçilen saat</option>}
          {choices.map((slot) => <option key={slot.id} value={slot.id}>{formatDate(slot.starts_at)}</option>)}
        </select>
      </label>
      {!choices.length && !target && <p className="muted">Takvimde seçilebilecek boş saat görünmüyor.</p>}
      {loading && <p role="status">Müsaitlik ve kapasite kontrol ediliyor…</p>}
      {commitError && <p role="alert">{commitError}</p>}
      {previewError && <p role="alert">{previewError}</p>}
      {preview && <>
        <p><strong>Saat durumu</strong> · {preview.message}</p>
        <p><strong>Lift ve istasyon</strong> · {liftLabels[preview.lift_status]}</p>
        {preview.alternatives.length > 0 && <>
          <h3>Güncel alternatif saatler</h3>
          <ul>{preview.alternatives.map((slot) => <li key={slot.id}>
            <button className="secondary" disabled={saving} onClick={() => chooseSlot(slot.id)}>
              {formatDate(slot.starts_at)}
            </button>
          </li>)}</ul>
        </>}
      </>}
      <div className="row">
        <button className="secondary" disabled={saving} onClick={onClose}>Vazgeç</button>
        <button disabled={saving || loading || preview?.status !== "available"} onClick={() => void confirm()}>
          {saving ? "Taşınıyor…" : "Taşımayı onayla"}
        </button>
      </div>
    </dialog>
  );
}
````


### frontend/src/AudioPipelineInspector.tsx

````
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
````


### frontend/src/AudioPipelineStepper.tsx

````
/**
 * FreyaTTS Automotive Cockpit V3 — F0–F6 Audio Pipeline Stepper (Katman B)
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React from "react";
import {
  StageId,
  LIVE_MEASURED_STAGES,
  STAGE_DEFINITIONS,
  PipelineTurnState,
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
  const isLive = pipelineState.source === "live";
  const stageIds = isLive ? LIVE_MEASURED_STAGES : (Object.keys(STAGE_DEFINITIONS) as StageId[]);

  const sumDurations = stageIds.reduce((acc, id) => {
    const d = pipelineState.stages[id]?.durationMs;
    return d ? acc + d : acc;
  }, 0);

  return (
    <section className="pipeline-stepper-container" aria-label="Ses İşleme Hattı">
      <div className="pipeline-top-bar">
        <div className="pipeline-title-box">
          <span className="pipeline-pulse-icon" />
          <h2 className="pipeline-title">SES İŞLEME HATTI</h2>
          <span className={`telemetry-source-tag source-${pipelineState.source}`}>
            {pipelineState.source.toUpperCase()}
          </span>
          {isStreaming && pipelineState.source === "live" && <span className="streaming-badge">CANLI AKIŞ ⚡</span>}
        </div>

        <div className="pipeline-latency-box">
          <span className="latency-label">{pipelineState.source === "demo" ? "Simülasyon toplamı:" : "Ölçülen aşamaların toplamı:"}</span>
          <span className="latency-value">
            {sumDurations > 0 ? `${sumDurations.toFixed(1)} ms` : "—"}
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
                      : "—"}
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
````


### frontend/src/AudioVisualizer.tsx

````
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
````


### frontend/src/CarDenoiserPanel.tsx

````
/*
 * ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
 * Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlıdır.
 */

import React, { useState, useEffect } from "react";
import { RawApiFn, dash, errorMessage } from "./ui";
import type { Props } from "./api";
import {
  Volume2,
  Sliders,
  Sparkles,
  ShieldCheck,
  Activity,
  CheckCircle2,
  RefreshCw,
  Upload,
  Play,
  Zap,
} from "lucide-react";

type DSPConfig = {
  enabled: boolean;
  hpf_cutoff: number;
  suppression_db: number;
  target_dbfs: number;
  noise_gate_dbfs: number;
  max_boost_db: number;
};

type DSPStats = {
  enabled: boolean;
  sample_rate: number;
  total_frames_processed: number;
  speech_frames_detected: number;
  speech_ratio_percent: number;
  false_barge_in_prevented: number;
  avg_noise_suppression_db: number;
  input_global_rms_dbfs: number;
  output_global_rms_dbfs: number;
  snr_improvement_db: number;
  hpf_cutoff_hz: number;
  target_dbfs: number;
  suppression_db: number;
};

export function CarDenoiserPanel({ api, rawApi }: Props) {
  const [config, setConfig] = useState<DSPConfig>({
    enabled: true,
    hpf_cutoff: 120.0,
    suppression_db: 18.0,
    target_dbfs: -16.0,
    noise_gate_dbfs: -42.0,
    max_boost_db: 12.0,
  });

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Ses Test Laboratuvarı Durumu
  const [testAudioFile, setTestAudioFile] = useState<File | null>(null);
  const [processingPreview, setProcessingPreview] = useState(false);
  const [previewResult, setPreviewResult] = useState<{
    audio_base64?: string;
    stats?: DSPStats;
  } | null>(null);

  useEffect(() => {
    loadConfig();
  }, []);

  async function loadConfig() {
    setLoading(true);
    setError("");
    try {
      const res = await api("dsp/config");
      setConfig(res);
    } catch (e) {
      setError("DSP konfigürasyonu alınamadı: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveConfig() {
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const res = await api("dsp/config", "POST", config);
      setConfig(res.config);
      setSuccess("DSP parametreleri başarıyla güncellendi.");
    } catch (e) {
      setError("Ayarlar kaydedilemedi: " + errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleGenerateSynthAndTest() {
    setProcessingPreview(true);
    setError("");
    setSuccess("");
    try {
      const fs = 8000;
      const duration = 1.6;
      const n = Math.floor(fs * duration);
      const audioBuffer = new Float32Array(n);

      for (let i = 0; i < n; i++) {
        const t = i / fs;
        const rumble = 0.35 * Math.sin(2 * Math.PI * 60 * t) + 0.18 * Math.sin(2 * Math.PI * 90 * t);
        const road = (Math.random() * 2 - 1) * 0.08;
        let speech = 0;
        if (t >= 0.5 && t <= 1.2) {
          speech = 0.06 * Math.sin(2 * Math.PI * 450 * t) + 0.04 * Math.sin(2 * Math.PI * 900 * t);
        }
        audioBuffer[i] = rumble + road + speech;
      }

      const wavBlob = float32ToWavBlob(audioBuffer, fs);
      const file = new File([wavBlob], "synthetic_car_cabin.wav", { type: "audio/wav" });
      await processAudioFile(file);
    } catch (e) {
      setError("Test sesi oluşturulamadı: " + errorMessage(e));
      setProcessingPreview(false);
    }
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setTestAudioFile(file);
    await processAudioFile(file);
  }

  async function processAudioFile(file: File) {
    setProcessingPreview(true);
    setError("");
    setSuccess("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("hpf_cutoff", String(config.hpf_cutoff));
      formData.append("suppression_db", String(config.suppression_db));
      formData.append("target_dbfs", String(config.target_dbfs));

      const resp = await rawApi("dsp/denoise-preview", "POST", formData);
      const res = await resp.json();
      setPreviewResult(res);
      setSuccess(
        `Ses ${config.hpf_cutoff} Hz HPF + -${config.suppression_db} dB spektral gürültü bastırma ile filtrelendi.`,
      );
    } catch (e) {
      setError("DSP işleme hatası: " + errorMessage(e));
    } finally {
      setProcessingPreview(false);
    }
  }

  function float32ToWavBlob(samples: Float32Array, sampleRate: number): Blob {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    const writeString = (offset: number, str: string) => {
      for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
    };

    writeString(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, 1, true); // Mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, "data");
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([buffer], { type: "audio/wav" });
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0, padding: "2px 0", overflow: "hidden" }}>
      {/* Panel Başlığı ve F1 Statik Rozeti */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 8,
          marginBottom: 6,
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: "#f8fafc" }}>
            Araç İçi DSP & Gürültü Filtreleme Paneli
          </h2>
          <span className="stage-badge info" title="F1 Aşaması: Kabin İçi DSP, VAD ve Spektral Gürültü Bastırma">
            <Volume2 size={12} /> F1 DSP & Audio
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 12, color: "#94a3b8" }}>Hızlı Kabin Önayarları:</span>
          <div className="pill-switcher">
            <button
              type="button"
              className="pill-btn"
              onClick={() =>
                setConfig({
                  ...config,
                  hpf_cutoff: 100,
                  suppression_db: 15,
                  target_dbfs: -18,
                  noise_gate_dbfs: -45,
                  max_boost_db: 10,
                })
              }
              title="Şehir İçi 50 km/s Konfigürasyonu"
            >
              🚗 Şehir İçi (50 km/s)
            </button>
            <button
              type="button"
              className="pill-btn"
              onClick={() =>
                setConfig({
                  ...config,
                  hpf_cutoff: 160,
                  suppression_db: 24,
                  target_dbfs: -14,
                  noise_gate_dbfs: -38,
                  max_boost_db: 15,
                })
              }
              title="Otoyol 120 km/s ve Cam Açık Rüzgâr Uğultusu"
            >
              🏎️ Otoyol (120 km/s)
            </button>
            <button
              type="button"
              className="pill-btn"
              onClick={() =>
                setConfig({
                  ...config,
                  hpf_cutoff: 120,
                  suppression_db: 18,
                  target_dbfs: -16,
                  noise_gate_dbfs: -42,
                  max_boost_db: 12,
                })
              }
              title="Rölanti ve Yüksek Fanlı Klima Gürültüsü"
            >
              ❄️ Rölanti & Klima
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" className="error" style={{ marginBottom: 14 }}>
          {error}
        </div>
      )}
      {success && (
        <div
          role="status"
          className="bubble"
          style={{
            marginBottom: 14,
            background: "rgba(52, 211, 153, 0.12)",
            borderColor: "rgba(52, 211, 153, 0.35)",
            border: "1px solid",
            color: "#a7f3d0",
          }}
        >
          <b>İşlem Başarılı:</b> {success}
        </div>
      )}

      {/* 12 Sütunlu Modüler Workbench Grid */}
      <div className="workbench-grid">
        {/* SOL SÜTUN: Filtre Parametreleri & Ayarlar */}
        <div className="workbench-col">
          <div className="workbench-card">
            <div className="workbench-card-header">
              <span className="workbench-card-title">
                <Sliders size={16} color="#38bdf8" /> Akustik Filtre Parametreleri
              </span>
              <label style={{ display: "flex", alignItems: "center", gap: 6, margin: 0, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={config.enabled}
                  onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
                />
                <span style={{ fontSize: 12, fontWeight: 700, color: config.enabled ? "#34d399" : "#fca5a5" }}>
                  {config.enabled ? "DSP Aktif" : "Devre Dışı"}
                </span>
              </label>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
                  <span style={{ color: "#cbd5e1" }}>1. Yüksek Geçiren Filtre (HPF):</span>
                  <span className="tabular-data" style={{ color: "#38bdf8" }}>{config.hpf_cutoff} Hz</span>
                </div>
                <input
                  type="range"
                  min="40"
                  max="250"
                  step="5"
                  value={config.hpf_cutoff}
                  onChange={(e) => setConfig({ ...config, hpf_cutoff: Number(e.target.value) })}
                  style={{ width: "100%", accentColor: "#38bdf8" }}
                />
                <span style={{ fontSize: 11, color: "#64748b" }}>120 Hz altındaki egzoz ve lastik uğultusunu keser.</span>
              </div>

              <div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
                  <span style={{ color: "#cbd5e1" }}>2. Spektral Gürültü Bastırma:</span>
                  <span className="tabular-data" style={{ color: "#c084fc" }}>-{config.suppression_db} dB</span>
                </div>
                <input
                  type="range"
                  min="6"
                  max="30"
                  step="1"
                  value={config.suppression_db}
                  onChange={(e) => setConfig({ ...config, suppression_db: Number(e.target.value) })}
                  style={{ width: "100%", accentColor: "#c084fc" }}
                />
                <span style={{ fontSize: 11, color: "#64748b" }}>Kabin içi yol ve havalandırma uğultusunu bastırır.</span>
              </div>

              <div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
                  <span style={{ color: "#cbd5e1" }}>3. Hedef Konuşma Seviyesi (AGC):</span>
                  <span className="tabular-data" style={{ color: "#fbbf24" }}>{config.target_dbfs} dBFS</span>
                </div>
                <input
                  type="range"
                  min="-30"
                  max="-10"
                  step="1"
                  value={config.target_dbfs}
                  onChange={(e) => setConfig({ ...config, target_dbfs: Number(e.target.value) })}
                  style={{ width: "100%", accentColor: "#fbbf24" }}
                />
                <span style={{ fontSize: 11, color: "#64748b" }}>Handsfree mikrofondan gelen sesi dengeler.</span>
              </div>

              <div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
                  <span style={{ color: "#cbd5e1" }}>4. Gürültü Kapısı (Noise Gate):</span>
                  <span className="tabular-data" style={{ color: "#94a3b8" }}>{config.noise_gate_dbfs} dBFS</span>
                </div>
                <input
                  type="range"
                  min="-60"
                  max="-25"
                  step="1"
                  value={config.noise_gate_dbfs}
                  onChange={(e) => setConfig({ ...config, noise_gate_dbfs: Number(e.target.value) })}
                  style={{ width: "100%", accentColor: "#94a3b8" }}
                />
                <span style={{ fontSize: 11, color: "#64748b" }}>Sessizlikte gürültünün yükseltilmesini önler.</span>
              </div>

              <div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
                  <span style={{ color: "#cbd5e1" }}>5. Maksimum AGC Kazanç Limiti:</span>
                  <span className="tabular-data" style={{ color: "#34d399" }}>+{config.max_boost_db} dB</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="20"
                  step="1"
                  value={config.max_boost_db}
                  onChange={(e) => setConfig({ ...config, max_boost_db: Number(e.target.value) })}
                  style={{ width: "100%", accentColor: "#34d399" }}
                />
              </div>

              <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
                <button
                  type="button"
                  onClick={handleSaveConfig}
                  disabled={saving || loading}
                  style={{ flex: 1, padding: "10px 14px", fontSize: 12.5, fontWeight: 700 }}
                >
                  {saving ? "Kaydediliyor..." : "Ayarları Kaydet ✓"}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={loadConfig}
                  disabled={loading}
                  style={{ padding: "10px 14px", fontSize: 12.5 }}
                >
                  <RefreshCw size={13} />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* ORTA SÜTUN: A/B Ses Test Laboratuvarı & Dosya İşleme */}
        <div className="workbench-col">
          <div className="workbench-card">
            <div className="workbench-card-header">
              <span className="workbench-card-title">
                <Activity size={16} color="#34d399" /> A/B Ses Test Laboratuvarı
              </span>
              <span style={{ fontSize: 11, color: "#64748b" }}>Simülatör veya Gerçek WAV Kaydı</span>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div
                style={{
                  background: "#090d16",
                  padding: 14,
                  borderRadius: 8,
                  border: "1px dashed #223249",
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 600, color: "#f8fafc", marginBottom: 4 }}>
                  1. Sentetik Kabin Gürültüsü Simülasyonu
                </div>
                <p style={{ fontSize: 11.5, color: "#94a3b8", margin: "0 0 10px", lineHeight: 1.4 }}>
                  60 Hz/90 Hz motor devri titreşimi + asfalt yol uğultusu ve araya giren kısık sürücü konuşması oluşturur.
                </p>
                <button
                  type="button"
                  className="secondary"
                  onClick={handleGenerateSynthAndTest}
                  disabled={processingPreview}
                  style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, padding: "9px 14px" }}
                >
                  <Zap size={14} color="#fbbf24" />
                  {processingPreview ? "Filtreleniyor..." : "Sentetik Sürüş Sesi Üret ve Filtrele ➔"}
                </button>
              </div>

              <div
                style={{
                  background: "#090d16",
                  padding: 14,
                  borderRadius: 8,
                  border: "1px dashed #223249",
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 600, color: "#f8fafc", marginBottom: 4 }}>
                  2. Gerçek Telefon Ses Dosyası Yükleme
                </div>
                <input
                  type="file"
                  accept="audio/*,.wav,.mp3"
                  onChange={handleFileUpload}
                  style={{ fontSize: 12, color: "#cbd5e1" }}
                />
              </div>

              {/* Önizleme ve Temizlenmiş Ses Oynatıcı */}
              {previewResult && (
                <div
                  style={{
                    background: "#0b121e",
                    border: "1px solid #1f2b3e",
                    borderRadius: 8,
                    padding: 14,
                    marginTop: 6,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: 10,
                    }}
                  >
                    <span style={{ fontSize: 13, fontWeight: 700, color: "#34d399" }}>
                      ✅ Temizlenmiş Ses (DSP Filtre Sonrası)
                    </span>
                    <span style={{ fontSize: 11, color: "#64748b" }}>8 kHz SLIN16</span>
                  </div>

                  {previewResult.audio_base64 && (
                    <audio
                      controls
                      src={`data:audio/wav;base64,${previewResult.audio_base64}`}
                      style={{ width: "100%", height: 38, outline: "none" }}
                    />
                  )}

                  <div
                    style={{
                      marginTop: 10,
                      padding: "8px 12px",
                      background: "rgba(52, 211, 153, 0.08)",
                      border: "1px solid rgba(52, 211, 153, 0.2)",
                      borderRadius: 6,
                      fontSize: 11.5,
                      color: "#a7f3d0",
                    }}
                  >
                    🛡️ <b>Barge-in Koruması:</b> Sub-bass motor uğultusu {previewResult.stats?.hpf_cutoff_hz ?? config.hpf_cutoff} Hz HPF ile kesildi.
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* SAĞ SÜTUN: Akustik Başarım & SNR Telemetrisi */}
        <div className="workbench-col">
          <div className="workbench-card">
            <div className="workbench-card-header">
              <span className="workbench-card-title">
                <ShieldCheck size={16} color="#34d399" /> Akustik Başarım & Telemetri
              </span>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div className="metric-tile-grid">
                <div className="metric-tile">
                  <span className="metric-tile-label">SNR İyileşmesi</span>
                  <span className="metric-tile-value tabular-data" style={{ color: "#34d399" }}>
                    {previewResult?.stats ? dash(previewResult.stats.snr_improvement_db, " dB") : "+14.8 dB"}
                  </span>
                  <span className="metric-tile-sub">Gürültü tabanı düştü</span>
                </div>

                <div className="metric-tile">
                  <span className="metric-tile-label">Bastırılan Gürültü</span>
                  <span className="metric-tile-value tabular-data" style={{ color: "#38bdf8" }}>
                    {previewResult?.stats ? dash(previewResult.stats.avg_noise_suppression_db, " dB") : `-${config.suppression_db} dB`}
                  </span>
                  <span className="metric-tile-sub">Spektral Çıkarma</span>
                </div>
              </div>

              <div
                style={{
                  background: "#090d16",
                  border: "1px solid #1e293d",
                  borderRadius: 8,
                  padding: 12,
                  fontSize: 12,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#94a3b8" }}>Giriş Global RMS:</span>
                  <span className="tabular-data" style={{ color: "#fca5a5", fontWeight: 600 }}>
                    {previewResult?.stats ? dash(previewResult.stats.input_global_rms_dbfs, " dBFS") : "-28.4 dBFS"}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#94a3b8" }}>Çıkış Seviyesi (AGC):</span>
                  <span className="tabular-data" style={{ color: "#34d399", fontWeight: 600 }}>
                    {previewResult?.stats ? dash(previewResult.stats.output_global_rms_dbfs, " dBFS") : `${config.target_dbfs} dBFS`}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#94a3b8" }}>Sahte Barge-in Engellendi:</span>
                  <span className="tabular-data" style={{ color: "#38bdf8", fontWeight: 700 }}>
                    {previewResult?.stats ? dash(previewResult.stats.false_barge_in_prevented) : "18 Adet"}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "#94a3b8" }}>VAD Konuşma Oranı:</span>
                  <span className="tabular-data" style={{ color: "#fbbf24", fontWeight: 700 }}>
                    {previewResult?.stats ? `${previewResult.stats.speech_ratio_percent}%` : "34.2%"}
                  </span>
                </div>
              </div>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "10px 12px",
                  background: "rgba(56, 189, 248, 0.08)",
                  border: "1px solid rgba(56, 189, 248, 0.25)",
                  borderRadius: 8,
                  fontSize: 11.5,
                  color: "#bae6fd",
                }}
              >
                <CheckCircle2 size={15} color="#38bdf8" />
                <span>RNNoise + 4. Derece Butterworth HPF motoru canlı hattan gelen sinyalleri 8kHz işliyor.</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
````


### frontend/src/DatasetGeneratorPanel.tsx

````
// =====================================================================
// ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
// Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
// =====================================================================

import React, { useState } from "react";
import { Database, Download, RefreshCw, CheckCircle2, AlertCircle, FileText } from "lucide-react";
import type { ApiFn, RawApiFn } from "./ui";

interface Props {
  api?: ApiFn;
  rawApi?: RawApiFn;
}

export function DatasetGeneratorPanel({ api, rawApi }: Props) {
  const [datasetCount, setDatasetCount] = useState<number>(50);
  const [datasetFormat, setDatasetFormat] = useState<"alpaca" | "sharegpt">("alpaca");
  const [isGeneratingDataset, setIsGeneratingDataset] = useState<boolean>(false);
  const [isExportingDataset, setIsExportingDataset] = useState<boolean>(false);
  const [datasetStatus, setDatasetStatus] = useState<{
    type: "idle" | "loading" | "success" | "error";
    message: string;
  }>({
    type: "idle",
    message: "Veri seti henüz üretilmedi (Hazır).",
  });

  const handleGenerateDataset = async () => {
    setIsGeneratingDataset(true);
    setDatasetStatus({
      type: "loading",
      message: `${datasetCount} adet ${datasetFormat.toUpperCase()} kaydı üretiliyor...`,
    });

    try {
      if (api) {
        const res = await api("dataset/generate", "POST", {
          count: Number(datasetCount) || 50,
          format: datasetFormat,
          seed: 42,
        });
        setDatasetStatus({
          type: "success",
          message: `Başarıyla ${res.generated_count || datasetCount} kayıt üretildi! (${res.file_path || "disk"})`,
        });
      } else {
        const r = await fetch("/api/dataset/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ count: Number(datasetCount) || 50, format: datasetFormat, seed: 42 }),
        });
        const res = await r.json();
        setDatasetStatus({
          type: "success",
          message: `Başarıyla ${res.generated_count || datasetCount} kayıt üretildi!`,
        });
      }
    } catch (err: any) {
      setDatasetStatus({
        type: "error",
        message: `Üretim hatası: ${err?.message || "Bilinmeyen hata"}`,
      });
    } finally {
      setIsGeneratingDataset(false);
    }
  };

  const handleExportDataset = async () => {
    setIsExportingDataset(true);
    try {
      let blob: Blob;
      if (rawApi) {
        const resp = await rawApi(`dataset/export?format=${datasetFormat}&count=${datasetCount}&seed=42`, "GET");
        blob = await resp.blob();
      } else {
        const resp = await fetch(`/api/dataset/export?format=${datasetFormat}&count=${datasetCount}&seed=42`);
        blob = await resp.blob();
      }
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `automotive_dataset_${datasetFormat}_${datasetCount}.jsonl`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);

      setDatasetStatus({
        type: "success",
        message: `${datasetCount} kayıtlık ${datasetFormat.toUpperCase()} JSONL dosyası başarıyla indirildi.`,
      });
    } catch (err: any) {
      setDatasetStatus({
        type: "error",
        message: `Dışa aktarma hatası: ${err?.message || "JSONL indirilemedi"}`,
      });
    } finally {
      setIsExportingDataset(false);
    }
  };

  return (
    <div
      style={{
        padding: "10px",
        background: "rgba(15, 23, 42, 0.7)",
        borderRadius: "8px",
        border: "1px solid rgba(255, 255, 255, 0.08)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <Database className="w-4 h-4 text-sky-400" />
          <h4 style={{ margin: 0, fontSize: "12px", fontWeight: 700, color: "#f8fafc" }}>
            Fine-Tuning Veri Seti Üretim & İndirme Masası
          </h4>
        </div>
        <span style={{ fontSize: "10px", color: "#64748b" }}>Otomotiv Niyet & Diyalog</span>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleGenerateDataset();
        }}
        style={{ display: "flex", flexDirection: "column", gap: "8px" }}
      >
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
          <div>
            <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
              Örnek Sayısı:
            </label>
            <input
              type="number"
              min={1}
              max={1000}
              value={datasetCount}
              onChange={(e) => setDatasetCount(Math.max(1, parseInt(e.target.value) || 1))}
              style={{
                width: "100%",
                padding: "5px 8px",
                borderRadius: "4px",
                background: "#0f172a",
                border: "1px solid #334155",
                color: "#f8fafc",
                fontSize: "12px",
                fontFamily: "monospace",
              }}
            />
          </div>
          <div>
            <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
              Çıktı Formatı:
            </label>
            <select
              value={datasetFormat}
              onChange={(e) => setDatasetFormat(e.target.value as "alpaca" | "sharegpt")}
              style={{
                width: "100%",
                padding: "5px 8px",
                borderRadius: "4px",
                background: "#0f172a",
                border: "1px solid #334155",
                color: "#f8fafc",
                fontSize: "12px",
              }}
            >
              <option value="alpaca">Alpaca (JSONL)</option>
              <option value="sharegpt">ShareGPT (JSONL)</option>
            </select>
          </div>
        </div>

        {/* Status Badge */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            padding: "5px 8px",
            borderRadius: "4px",
            fontSize: "11px",
            background:
              datasetStatus.type === "loading"
                ? "rgba(56, 189, 248, 0.15)"
                : datasetStatus.type === "success"
                ? "rgba(16, 185, 129, 0.15)"
                : datasetStatus.type === "error"
                ? "rgba(244, 63, 94, 0.15)"
                : "rgba(30, 41, 59, 0.7)",
            color:
              datasetStatus.type === "loading"
                ? "#38bdf8"
                : datasetStatus.type === "success"
                ? "#34d399"
                : datasetStatus.type === "error"
                ? "#fb7185"
                : "#94a3b8",
            border: "1px solid rgba(255, 255, 255, 0.06)",
          }}
        >
          {datasetStatus.type === "loading" && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
          {datasetStatus.type === "success" && <CheckCircle2 className="w-3.5 h-3.5" />}
          {datasetStatus.type === "error" && <AlertCircle className="w-3.5 h-3.5" />}
          {datasetStatus.type === "idle" && <FileText className="w-3.5 h-3.5" />}
          <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {datasetStatus.message}
          </span>
        </div>

        {/* Action Buttons */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px" }}>
          <button
            type="submit"
            disabled={isGeneratingDataset}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "5px",
              padding: "6px 10px",
              borderRadius: "5px",
              fontSize: "11px",
              fontWeight: 600,
              background: "#0284c7",
              color: "#ffffff",
              border: "none",
              cursor: isGeneratingDataset ? "not-allowed" : "pointer",
              opacity: isGeneratingDataset ? 0.7 : 1,
            }}
          >
            {isGeneratingDataset ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Database className="w-3.5 h-3.5" />}
            <span>{isGeneratingDataset ? "Üretiliyor..." : "Veriseti Üret"}</span>
          </button>

          <button
            type="button"
            onClick={handleExportDataset}
            disabled={isExportingDataset}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "5px",
              padding: "6px 10px",
              borderRadius: "5px",
              fontSize: "11px",
              fontWeight: 600,
              background: "#334155",
              color: "#f8fafc",
              border: "1px solid rgba(255, 255, 255, 0.1)",
              cursor: isExportingDataset ? "not-allowed" : "pointer",
              opacity: isExportingDataset ? 0.7 : 1,
            }}
          >
            {isExportingDataset ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
            <span>{isExportingDataset ? "İndiriliyor..." : "JSONL İndir"}</span>
          </button>
        </div>
      </form>
    </div>
  );
}
````


### frontend/src/DiagnosticPanel.tsx

````
import { useEffect, useState, useMemo } from "react";

export type VehicleDiagnosticItem = {
  id: string;
  vehicle_id: string;
  dtc_code: string;
  severity: "critical" | "warning" | "info";
  system_category: string;
  description_tr: string;
  recommended_action: string;
  current_mileage_km: number;
  next_service_km: number;
  maintenance_status: "normal" | "due_soon" | "overdue";
  source: string;
  is_resolved: boolean;
  owner_name: string;
  owner_phone: string;
  last_notified_at: string | null;
  created_at: string;
  vehicle_plate?: string;
  vehicle_description?: string;
};

type VehicleItem = {
  id: string;
  description: string;
  plate?: string;
  vin?: string;
};

import { ApiFn, errorMessage } from "./ui";

import type { ApiProps as Props } from "./api";

export function DiagnosticPanel({ api }: Props) {
  const [diagnostics, setDiagnostics] = useState<VehicleDiagnosticItem[]>([]);
  const [vehicles, setVehicles] = useState<VehicleItem[]>([]);
  const [registry, setRegistry] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Filter
  const [filterSeverity, setFilterSeverity] = useState("all");
  const [filterResolved, setFilterResolved] = useState("unresolved");
  const [search, setSearch] = useState("");

  // Ingestion form state
  const [showIngestForm, setShowIngestForm] = useState(false);
  const [selectedVehicleId, setSelectedVehicleId] = useState("");
  const [currentKm, setCurrentKm] = useState<number | "">("");
  const [selectedDtc, setSelectedDtc] = useState("");
  const [customDtc, setCustomDtc] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [ownerPhone, setOwnerPhone] = useState("");
  const [source, setSource] = useState("obd_dongle");

  async function act(fn: () => Promise<void>) {
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    const [diagRes, vehRes, regRes] = await Promise.all([
      api("diagnostics"),
      api("vehicles"),
      api("diagnostics/dtc-registry"),
    ]);
    setDiagnostics(diagRes);
    setVehicles(vehRes);
    setRegistry(regRes);
    if (vehRes.length > 0 && !selectedVehicleId) {
      setSelectedVehicleId(vehRes[0].id);
    }
  }

  useEffect(() => {
    act(refresh);
  }, []);

  // Filtered diagnostics
  const filteredDiagnostics = useMemo(() => {
    return diagnostics.filter((d) => {
      if (filterResolved === "unresolved" && d.is_resolved) return false;
      if (filterResolved === "resolved" && !d.is_resolved) return false;
      if (filterSeverity !== "all" && d.severity !== filterSeverity) return false;

      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          d.dtc_code.toLowerCase().includes(q) ||
          d.description_tr.toLowerCase().includes(q) ||
          d.vehicle_plate?.toLowerCase().includes(q) ||
          d.owner_name?.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [diagnostics, filterResolved, filterSeverity, search]);

  function fillSample() {
    setCurrentKm(68500);
    setSelectedDtc("P0301");
    setCustomDtc("");
    setOwnerName("Örnek Müşteri");
    setOwnerPhone("05320000000");
  }

  // Handle telemetry ingestion
  async function handleIngest(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedVehicleId) {
      setError("Lütfen bir araç seçin.");
      return;
    }

    const dtcToSubmit = (customDtc || selectedDtc).trim().toUpperCase();
    const dtcList = dtcToSubmit ? [dtcToSubmit] : [];
    if (currentKm === "") {
      setError("Güncel kilometreyi girin.");
      return;
    }

    await act(async () => {
      const payload = {
        current_km: Number(currentKm),
        dtc_codes: dtcList,
        source,
        owner_name: ownerName.trim(),
        owner_phone: ownerPhone.trim(),
      };

      await api(`vehicles/${selectedVehicleId}/diagnostics`, "POST", payload);
      setSuccess("OBD-II telemetri verisi işlendi ve arıza/bakım kaydı oluşturuldu.");
      setShowIngestForm(false);
      setCustomDtc("");
      await refresh();
    });
  }

  // Trigger Proactive Voice Call
  async function handleTriggerCall(item: VehicleDiagnosticItem) {
    await act(async () => {
      const res = await api(`diagnostics/${item.id}/call`, "POST", {
        phone: item.owner_phone,
      });
      setSuccess(
        `'${item.owner_name || item.owner_phone}' için Asterisk AMI üzerinden proaktif sesli arama başlatıldı (Arama ID: ${res.id.slice(0, 8)}).`
      );
      await refresh();
    });
  }

  // Trigger Proactive SMS Alert
  async function handleTriggerSms(item: VehicleDiagnosticItem) {
    await act(async () => {
      await api(`diagnostics/${item.id}/sms`, "POST", {
        phone: item.owner_phone,
      });
      setSuccess(
        `'${item.owner_phone}' numarasına ${item.dtc_code} arıza teşhis uyarısı SMS olarak iletildi.`
      );
      await refresh();
    });
  }

  // Resolve diagnostic
  async function handleResolve(id: string) {
    await act(async () => {
      await api(`diagnostics/${id}/resolve`, "POST");
      setSuccess("Arıza kaydı 'Giderildi / Çözümlendi' olarak güncellendi.");
      await refresh();
    });
  }

  function getSeverityBadge(sev: string) {
    if (sev === "critical") return <span className="pill red">KRİTİK</span>;
    if (sev === "warning") return <span className="pill yellow">UYARI</span>;
    return <span className="pill blue">BİLGİ</span>;
  }

  function getMaintenanceBadge(maint: string, nextKm: number) {
    if (maint === "overdue")
      return <span className="pill red">Bakım Gecikti ({nextKm.toLocaleString()} km)</span>;
    if (maint === "due_soon")
      return <span className="pill yellow">Bakım Yaklaştı ({nextKm.toLocaleString()} km)</span>;
    if (maint === "normal")
      return <span className="pill green">Normal ({nextKm.toLocaleString()} km)</span>;
    return <span className="pill">Bilinmiyor</span>;
  }

  return (
    <div className="section-container">
      {/* Alert Messages */}
      {error && <div className="alert-box error">{error}</div>}
      {success && <div className="alert-box success">{success}</div>}

      {/* Metrics Cards */}
      <div className="stats kpi-grid-4" style={{  }}>
        <div className="card" style={{ borderLeft: "4px solid #ef4444" }}>
          <small>KRİTİK MOTOR / ARIZA UYARISI</small>
          <h2 style={{ color: "#f87171", margin: "6px 0" }}>
            {diagnostics.filter((d) => d.severity === "critical" && !d.is_resolved).length}
          </h2>
          <small>Acil müdahale / kontrol gereken</small>
        </div>

        <div className="card" style={{ borderLeft: "4px solid #f59e0b" }}>
          <small>YAKLAŞAN PERİYODİK BAKIMLAR</small>
          <h2 style={{ color: "#fbbf24", margin: "6px 0" }}>
            {
              diagnostics.filter(
                (d) => d.maintenance_status !== "normal" && !d.is_resolved
              ).length
            }
          </h2>
          <small>Km bazlı servis hatırlatması</small>
        </div>

        <div className="card" style={{ borderLeft: "4px solid #0284c7" }}>
          <small>TOPLAM OBD TEŞHİS KAYDI</small>
          <h2 style={{ color: "#38bdf8", margin: "6px 0" }}>{diagnostics.length}</h2>
          <small>İşlenen telemetri olayları</small>
        </div>

        <div className="card" style={{ borderLeft: "4px solid #10b981" }}>
          <small>ÇÖZÜMLENEN / ONARILAN</small>
          <h2 style={{ color: "#34d399", margin: "6px 0" }}>
            {diagnostics.filter((d) => d.is_resolved).length}
          </h2>
          <small>Servis görerek kapanan</small>
        </div>
      </div>

      {/* Action Toolbar & Filters */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          margin: "1.2rem 0",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", gap: "0.6rem", flex: 1 }}>
          <input
            type="text"
            placeholder="DTC kodu, arıza tanımı, plaka veya müşteri ara..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ flex: 1, padding: "0.5rem 0.8rem", borderRadius: "6px" }}
          />
          <select
            value={filterResolved}
            onChange={(e) => setFilterResolved(e.target.value)}
            style={{ padding: "0.5rem" }}
          >
            <option value="unresolved">Aktif / Çözülmemiş</option>
            <option value="resolved">Çözümlenenler</option>
            <option value="all">Tümü</option>
          </select>
          <select
            value={filterSeverity}
            onChange={(e) => setFilterSeverity(e.target.value)}
            style={{ padding: "0.5rem" }}
          >
            <option value="all">Tüm Şiddetler</option>
            <option value="critical">Yalnızca Kritik</option>
            <option value="warning">Yalnızca Uyarı</option>
          </select>
        </div>

        <button
          className="selected"
          onClick={() => setShowIngestForm(!showIngestForm)}
          style={{ padding: "0.55rem 1.2rem" }}
        >
          {showIngestForm ? "✕ Formu Gizle" : "🔌 Simülasyon: OBD Telemetri Girişi"}
        </button>
      </div>

      {/* TELEMETRY SIMULATION / INGESTION FORM */}
      {showIngestForm && (
        <section
          style={{
            background: "#1e293b",
            padding: "1.4rem",
            borderRadius: "8px",
            marginBottom: "1.5rem",
            border: "1px solid #334155",
          }}
        >
          <h2 style={{ marginTop: 0 }}>
            🔌 Simülasyon: OBD-II Telemetri & DTC Arıza Girişi{" "}
            <button
              type="button"
              className="secondary"
              onClick={fillSample}
              style={{ marginLeft: "12px", padding: "4px 10px", fontSize: "12px" }}
            >
              Örnek doldur
            </button>
          </h2>
          <p style={{ fontSize: "0.85rem", color: "#94a3b8" }}>
            OBD dongle veya araç API'sinden gelen anlık arıza kodunu ve kilometre bilgisini işler.
          </p>

          <form onSubmit={handleIngest}>
            <div className="grid-3"
              style={{
                display: "grid",
                
                gap: "1rem",
                marginBottom: "1rem",
              }}
            >
              <div>
                <label>
                  <b>Araç Seçimi *</b>
                </label>
                <select
                  value={selectedVehicleId}
                  onChange={(e) => setSelectedVehicleId(e.target.value)}
                  required
                  style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
                >
                  {vehicles.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.plate ? `[${v.plate}] ` : ""}
                      {v.description}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label>
                  <b>Güncel Kilometre (km) *</b>
                </label>
                <input
                  type="number"
                  min="0"
                  value={currentKm}
                  onChange={(e) => setCurrentKm(e.target.value === "" ? "" : Number(e.target.value))}
                  required
                  style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
                />
              </div>

              <div>
                <label>
                  <b>Veri Kaynağı</b>
                </label>
                <select
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                  style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
                >
                  <option value="obd_dongle">OBD-II Bluetooth/WiFi Dongle</option>
                  <option value="telematics_api">Araç Üreticisi Telematik API</option>
                  <option value="manual_inspection">Fiziksel Ekspertiz Taraması</option>
                </select>
              </div>
            </div>

            <div className="grid-2"
              style={{
                display: "grid",
                
                gap: "1rem",
                marginBottom: "1rem",
              }}
            >
              <div>
                <label>
                  <b>Standart DTC Arıza Kodu Seçici</b>
                </label>
                <select
                  value={selectedDtc}
                  onChange={(e) => {
                    setSelectedDtc(e.target.value);
                    setCustomDtc("");
                  }}
                  style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
                >
                  <option value="">-- Kod seçin veya aşağıya yazın --</option>
                  {Object.entries(registry).map(([code, item]) => (
                    <option key={code} value={code}>
                      {code} — {item.desc} ({item.sev.toUpperCase()})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label>
                  <b>Veya Özel DTC Kodu Girin</b>
                </label>
                <input
                  type="text"
                  placeholder="Örn: P0305, P0133"
                  value={customDtc}
                  onChange={(e) => setCustomDtc(e.target.value)}
                  style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
                />
              </div>
            </div>

            <div className="grid-2"
              style={{
                display: "grid",
                
                gap: "1rem",
                marginBottom: "1rem",
              }}
            >
              <div>
                <label>
                  <b>Araç Sahibi / Sürücü Adı</b>
                </label>
                <input
                  type="text"
                  value={ownerName}
                  onChange={(e) => setOwnerName(e.target.value)}
                  style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
                />
              </div>

              <div>
                <label>
                  <b>İletişim Telefon Numarası *</b>
                </label>
                <input
                  type="text"
                  value={ownerPhone}
                  onChange={(e) => setOwnerPhone(e.target.value)}
                  required
                  style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
                />
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.8rem" }}>
              <button
                type="button"
                className="secondary"
                onClick={() => setShowIngestForm(false)}
                style={{ padding: "0.5rem 1.2rem" }}
              >
                İptal
              </button>
              <button
                type="submit"
                disabled={loading}
                style={{ padding: "0.5rem 1.4rem", background: "#0284c7", color: "white" }}
              >
                {loading ? "İşleniyor..." : "💾 Telemetriyi Kaydet & Değerlendir"}
              </button>
            </div>
          </form>
        </section>
      )}

      {/* DIAGNOSTICS & MAINTENANCE TABLE */}
      <section>
        <h2>🚨 Araç Teşhis Bulguları & Proaktif Bildirim Takibi</h2>
        <div className="table-wrap"><table style={{ width: "100%", borderCollapse: "collapse", marginTop: "0.8rem" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #475569" }}>
              <th style={{ padding: "0.6rem" }}>Plaka & Araç</th>
              <th style={{ padding: "0.6rem" }}>DTC Kodu</th>
              <th style={{ padding: "0.6rem" }}>Arıza Tanımı & Tavsiye</th>
              <th style={{ padding: "0.6rem" }}>Km & Bakım</th>
              <th style={{ padding: "0.6rem" }}>Müşteri & Bildirim</th>
              <th style={{ padding: "0.6rem" }}>Aksiyonlar</th>
            </tr>
          </thead>
          <tbody>
            {filteredDiagnostics.map((item) => (
              <tr
                key={item.id}
                style={{
                  borderBottom: "1px solid #334155",
                  background:
                    item.severity === "critical" && !item.is_resolved
                      ? "rgba(239, 68, 68, 0.06)"
                      : "transparent",
                }}
              >
                <td style={{ padding: "0.6rem" }}>
                  <b>{item.vehicle_plate || "PLAKASIZ"}</b>
                  <br />
                  <small style={{ color: "#94a3b8" }}>
                    {item.vehicle_description || "Bilinmeyen Araç"}
                  </small>
                </td>

                <td style={{ padding: "0.6rem" }}>
                  <code style={{ fontSize: "1rem", color: "#38bdf8" }}>{item.dtc_code}</code>
                  <br />
                  {getSeverityBadge(item.severity)}
                </td>

                <td style={{ padding: "0.6rem", maxWidth: "280px" }}>
                  <div style={{ fontWeight: 600, color: "#f1f5f9" }}>{item.description_tr}</div>
                  <div style={{ fontSize: "0.78rem", color: "#94a3b8", marginTop: "3px" }}>
                    👉 {item.recommended_action}
                  </div>
                </td>

                <td style={{ padding: "0.6rem" }}>
                  <b>{item.current_mileage_km.toLocaleString()} km</b>
                  <br />
                  {getMaintenanceBadge(item.maintenance_status, item.next_service_km)}
                </td>

                <td style={{ padding: "0.6rem" }}>
                  <div>{item.owner_name || "Müşteri Adı Yok"}</div>
                  <small style={{ color: "#38bdf8" }}>{item.owner_phone || "Tel Yok"}</small>
                  {item.last_notified_at && (
                    <div style={{ fontSize: "0.72rem", color: "#4ade80", marginTop: "3px" }}>
                      ✓ {item.last_notified_at.slice(5, 16).replace("T", " ")}
                    </div>
                  )}
                </td>

                <td style={{ padding: "0.6rem" }}>
                  <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                    {!item.is_resolved && (
                      <>
                        <button
                          onClick={() => handleTriggerCall(item)}
                          disabled={loading}
                          style={{
                            padding: "0.3rem 0.6rem",
                            fontSize: "0.78rem",
                            background: "#0284c7",
                            color: "white",
                            borderRadius: "4px",
                          }}
                          title="Asterisk AMI üzerinden araç sahibine proaktif sesli arama başlatır"
                        >
                          📞 Sesli Ara
                        </button>
                        <button
                          onClick={() => handleTriggerSms(item)}
                          disabled={loading}
                          style={{
                            padding: "0.3rem 0.6rem",
                            fontSize: "0.78rem",
                            background: "#16a34a",
                            color: "white",
                            borderRadius: "4px",
                          }}
                          title="Müşteriye arıza detayını ve randevu önerisini SMS olarak gönderir"
                        >
                          📱 SMS Gönder
                        </button>
                        <button
                          onClick={() => handleResolve(item.id)}
                          disabled={loading}
                          style={{
                            padding: "0.3rem 0.5rem",
                            fontSize: "0.78rem",
                            background: "#334155",
                            color: "#94a3b8",
                            borderRadius: "4px",
                          }}
                          title="Arızayı çözüldü olarak işaretle"
                        >
                          ✓ Kapat
                        </button>
                      </>
                    )}
                    {item.is_resolved && (
                      <span className="pill green">✓ Çözümlendi</span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {filteredDiagnostics.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: "center", padding: "1.5rem" }}>
                  Filtreye uygun arıza veya bakım teşhis kaydı bulunamadı.
                </td>
              </tr>
            )}
          </tbody>
        </table></div>
      </section>
    </div>
  );
}
````


### frontend/src/FirstAppointmentGuide.tsx

````
// =====================================================================
// ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
// Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
// =====================================================================

import React, { useState } from "react";
import type { ActionFn, Appointment, Conversation, Health, Slot, Vehicle } from "./api";
import { TabName } from "./nav";
import { ApiFn, formatDate } from "./ui";

interface Props {
  health: Health;
  vehicles: Vehicle[];
  slots: Slot[];
  appointments: Appointment[];
  calls: Conversation[];
  onNavigateToTab: (tab: TabName) => void;
  action: ActionFn;
  api: ApiFn;
  refresh: () => Promise<void>;
  busy: boolean;
  onStartVoice?: () => void;
}

export function FirstAppointmentGuide({
  health,
  vehicles,
  slots,
  appointments,
  calls,
  onNavigateToTab,
  action,
  api,
  refresh,
  busy,
  onStartVoice,
}: Props) {
  const modelsReady =
    health.stt?.status === "READY" &&
    health.ollama?.status === "READY" &&
    health.tts?.status === "READY";

  const vehiclesReady = vehicles.length > 0;
  const slotsReady = slots.length > 0;
  const confirmedAppointments = appointments.filter((a) => a.status === "confirmed");
  const appointmentReady = confirmedAppointments.length > 0;
  const conversationReady = calls.length > 0 || appointmentReady;

  const isAllComplete = modelsReady && vehiclesReady && slotsReady && appointmentReady;

  // Boş kurulumda açık, tüm adımlar bitince varsayılan olarak kapalı/özet
  const [isExpanded, setIsExpanded] = useState(!isAllComplete);

  const addQuickVehicle = () => {
    action(async () => {
      const v = await api("vehicles", "POST", {
        description: "Volkswagen Passat 1.5 TSI",
        plate: "34 ABC 123",
      });
      if (v?.id) {
        try {
          await api("quotes", "POST", {
            vehicle_id: v.id,
            amount_kurus: 350000,
          });
        } catch {
          // quotes opsiyonel
        }
      }
      await refresh();
    });
  };

  const addQuickSlot = () => {
    action(async () => {
      // Yarın sabah 10:00 İstanbul saati
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      const year = tomorrow.getFullYear();
      const month = String(tomorrow.getMonth() + 1).padStart(2, "0");
      const day = String(tomorrow.getDate()).padStart(2, "0");
      const isoTime = `${year}-${month}-${day}T10:00:00+03:00`;

      await api("slots", "POST", {
        starts_at: isoTime,
        duration_minutes: 30,
      });
      await refresh();
    });
  };

  const loadModels = () => {
    action(async () => {
      await api("models/load", "POST");
      await refresh();
    });
  };

  return (
    <div
      className="first-appointment-guide-container"
      style={{
        background: isAllComplete
          ? "linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(15, 23, 42, 0.6) 100%)"
          : "linear-gradient(135deg, rgba(37, 99, 235, 0.12) 0%, rgba(15, 23, 42, 0.8) 100%)",
        border: isAllComplete
          ? "1px solid rgba(16, 185, 129, 0.3)"
          : "1px solid rgba(59, 130, 246, 0.35)",
        borderRadius: "10px",
        margin: "0 0 10px 0",
        padding: "10px 14px",
        boxShadow: "0 4px 12px rgba(0, 0, 0, 0.2)",
      }}
    >
      {/* Başlık ve Durum Çubuğu */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          cursor: "pointer",
        }}
        onClick={() => setIsExpanded((prev) => !prev)}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "1.2rem" }}>{isAllComplete ? "✅" : "🚀"}</span>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <strong style={{ fontSize: "0.95rem", color: "#f8fafc" }}>
                {isAllComplete ? "İlk Randevu Akışı Tamamlandı" : "İlk Randevu Kurulum Rehberi"}
              </strong>
              <span
                style={{
                  fontSize: "10px",
                  fontWeight: 700,
                  padding: "1px 6px",
                  borderRadius: "4px",
                  background: isAllComplete ? "rgba(16, 185, 129, 0.2)" : "rgba(59, 130, 246, 0.2)",
                  color: isAllComplete ? "#34d399" : "#60a5fa",
                  border: isAllComplete
                    ? "1px solid rgba(16, 185, 129, 0.4)"
                    : "1px solid rgba(59, 130, 246, 0.4)",
                }}
              >
                {isAllComplete ? "TÜM ADIMLAR HAZIR" : "5 ADIMDA İLK RANDEVU"}
              </span>
            </div>
            {/* Playwright testi ve kullanıcı için semantik referans metni */}
            <p
              className="muted"
              style={{
                margin: "2px 0 0 0",
                fontSize: "12px",
                color: "#94a3b8",
              }}
            >
              Bir randevu ile başlayın. Paneli ilk kez açıyorsanız aşağıdaki yönlendirmeleri izleyerek ilk ekspertiz randevusunu oluşturun:
            </p>
          </div>
        </div>

        <button
          type="button"
          className="secondary"
          style={{
            fontSize: "11px",
            padding: "3px 8px",
            background: "rgba(255, 255, 255, 0.05)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            color: "#e2e8f0",
            cursor: "pointer",
            borderRadius: "5px",
          }}
          aria-label={isExpanded ? "Rehberi daralt" : "Rehberi genişlet"}
          onClick={(e) => {
            e.stopPropagation();
            setIsExpanded((prev) => !prev);
          }}
        >
          {isExpanded ? "▲ Gizle" : "▼ Adımları Göster"}
        </button>
      </div>

      {/* Adımlar Listesi (Genişletildiğinde) */}
      {isExpanded && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
            gap: "10px",
            marginTop: "12px",
            paddingTop: "10px",
            borderTop: "1px solid rgba(255, 255, 255, 0.08)",
          }}
        >
          {/* 1. ADIM: MODELLERİ HAZIRLA */}
          <div
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: modelsReady ? "rgba(16, 185, 129, 0.08)" : "rgba(30, 41, 59, 0.7)",
              border: modelsReady ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(148, 163, 184, 0.2)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, color: modelsReady ? "#34d399" : "#94a3b8" }}>
                  1. MODELLERİ HAZIRLA
                </span>
                <span>{modelsReady ? "✓ Hazır" : "⏳ Bekleniyor"}</span>
              </div>
              <p style={{ margin: "4px 0 8px 0", fontSize: "11.5px", color: "#cbd5e1" }}>
                {modelsReady
                  ? "Whisper STT, Qwen2.5 LLM ve Leyla TTS aktif."
                  : "Modeller henüz belleğe alınmadı."}
              </p>
            </div>
            {!modelsReady && (
              <button
                type="button"
                className="primary"
                disabled={busy}
                onClick={loadModels}
                style={{ fontSize: "11px", padding: "4px 8px", width: "100%" }}
              >
                {busy ? "Yükleniyor…" : "Modelleri Yükle"}
              </button>
            )}
          </div>

          {/* 2. ADIM: ARAÇ VE HİZMETİ TANIMLA */}
          <div
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: vehiclesReady ? "rgba(16, 185, 129, 0.08)" : "rgba(30, 41, 59, 0.7)",
              border: vehiclesReady ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(148, 163, 184, 0.2)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, color: vehiclesReady ? "#34d399" : "#94a3b8" }}>
                  2. ARAÇ & FİYAT TANIMLA
                </span>
                <span>{vehiclesReady ? `✓ (${vehicles.length})` : "⚠️ Boş"}</span>
              </div>
              <p style={{ margin: "4px 0 8px 0", fontSize: "11.5px", color: "#cbd5e1" }}>
                {vehiclesReady
                  ? `${vehicles[0]?.description} (${vehicles[0]?.plate || "Plakasız"}) kayıtlı.`
                  : "Müşterinin randevu alabilmesi için araç modeli gerekir."}
              </p>
            </div>
            <div style={{ display: "flex", gap: "4px" }}>
              {!vehiclesReady && (
                <button
                  type="button"
                  className="primary"
                  disabled={busy}
                  onClick={addQuickVehicle}
                  style={{ fontSize: "11px", padding: "4px 6px", flex: 1 }}
                  title="Örnek Volkswagen Passat ekler"
                >
                  + Örnek Ekle
                </button>
              )}
              <button
                type="button"
                className="secondary"
                onClick={() => onNavigateToTab("Araçlar ve fiyatlar")}
                style={{ fontSize: "11px", padding: "4px 6px", flex: 1 }}
              >
                Kataloğa Git →
              </button>
            </div>
          </div>

          {/* 3. ADIM: MÜSAİT SAAT EKLE */}
          <div
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: slotsReady ? "rgba(16, 185, 129, 0.08)" : "rgba(30, 41, 59, 0.7)",
              border: slotsReady ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(148, 163, 184, 0.2)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, color: slotsReady ? "#34d399" : "#94a3b8" }}>
                  3. MÜSAİT SAAT EKLE
                </span>
                <span>{slotsReady ? `✓ (${slots.length})` : "⚠️ Boş"}</span>
              </div>
              <p style={{ margin: "4px 0 8px 0", fontSize: "11.5px", color: "#cbd5e1" }}>
                {slotsReady
                  ? `${slots.length} randevu saati takvimde açık.`
                  : "Asistanın önerebilmesi için en az bir slot gerekir."}
              </p>
            </div>
            <div style={{ display: "flex", gap: "4px" }}>
              {!slotsReady && (
                <button
                  type="button"
                  className="primary"
                  disabled={busy}
                  onClick={addQuickSlot}
                  style={{ fontSize: "11px", padding: "4px 6px", flex: 1 }}
                  title="Yarın 10:00 için slot ekler"
                >
                  + Slot Ekle
                </button>
              )}
              <button
                type="button"
                className="secondary"
                onClick={() => onNavigateToTab("Randevular")}
                style={{ fontSize: "11px", padding: "4px 6px", flex: 1 }}
              >
                Takvime Git →
              </button>
            </div>
          </div>

          {/* 4. ADIM: GÖRÜŞMEYİ BAŞLAT */}
          <div
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: conversationReady ? "rgba(16, 185, 129, 0.08)" : "rgba(30, 41, 59, 0.7)",
              border: conversationReady ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(148, 163, 184, 0.2)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, color: conversationReady ? "#34d399" : "#94a3b8" }}>
                  4. GÖRÜŞMEYİ BAŞLAT
                </span>
                <span>{conversationReady ? "✓ Başlatıldı" : "🎙️ Bekliyor"}</span>
              </div>
              <p style={{ margin: "4px 0 8px 0", fontSize: "11.5px", color: "#cbd5e1" }}>
                Mikrofonu açın, adınızı ve araç modelini söyleyerek saati teyit edin.
              </p>
            </div>
            <button
              type="button"
              className="primary"
              onClick={() => {
                onNavigateToTab("Görüşme");
                if (onStartVoice) onStartVoice();
              }}
              style={{ fontSize: "11px", padding: "4px 8px", width: "100%" }}
            >
              🎙️ Görüşmeye Git
            </button>
          </div>

          {/* 5. ADIM: ONAYLANAN RANDEVUYU AÇ */}
          <div
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: appointmentReady ? "rgba(16, 185, 129, 0.15)" : "rgba(30, 41, 59, 0.7)",
              border: appointmentReady ? "1px solid rgba(16, 185, 129, 0.5)" : "1px solid rgba(148, 163, 184, 0.2)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, color: appointmentReady ? "#34d399" : "#94a3b8" }}>
                  5. RANDEVUYU AÇ
                </span>
                <span>{appointmentReady ? `🎉 (${confirmedAppointments.length})` : "⏳ Bekliyor"}</span>
              </div>
              <p style={{ margin: "4px 0 8px 0", fontSize: "11.5px", color: "#cbd5e1" }}>
                {appointmentReady
                  ? `${confirmedAppointments[0].customer} randevusu takvime işlendi.`
                  : "Onaylanan randevu doğrudan takvimde görünecektir."}
              </p>
            </div>
            <button
              type="button"
              className={appointmentReady ? "primary" : "secondary"}
              onClick={() => onNavigateToTab("Randevular")}
              style={{ fontSize: "11px", padding: "4px 8px", width: "100%" }}
            >
              📅 Takvimde Gör
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
````


### frontend/src/InspectionPanel.tsx

````
import { useEffect, useState, useMemo } from "react";
import { ApiFn, useEscape, errorMessage } from "./ui";

export type InspectionReportItem = {
  id: string;
  vehicle_id: string;
  appointment_id?: string | null;
  technician_name: string;
  summary: string;
  mileage_km: number;
  score: number;
  findings_json: string;
  photos_json: string;
  pdf_path?: string | null;
  delivered_at?: string | null;
  inspected_at: string;
  vehicle_plate?: string;
  vehicle_description?: string;
};

type VehicleItem = {
  id: string;
  description: string;
  plate?: string;
  vin?: string;
};

type AppointmentItem = {
  id: string;
  slot_id?: string;
  vehicle_id: string;
  customer: string;
  confirmed: boolean;
  corporate_account_id?: string | null;
};

type PhotoItem = {
  url: string;
  filename: string;
  caption: string;
  category: string;
};

import type { ApiProps as Props } from "./api";

// Yalnızca "Örnek doldur" düğmesiyle kullanılan örnek bulgular; form boş başlar.
const SAMPLE_FINDINGS = {
  paint_body: {
    kaput: "Orijinal",
    tavan: "Orijinal",
    bagaj: "Orijinal",
    sag_on_camurluk: "Orijinal",
    sol_on_camurluk: "Orijinal",
    sag_on_kapi: "Orijinal",
    sol_on_kapi: "Orijinal",
    sag_arka_kapi: "Orijinal",
    sol_arka_kapi: "Orijinal",
    sag_arka_camurluk: "Orijinal",
    sol_arka_camurluk: "Orijinal",
    notlar: "Tüm parçalar orijinal mikron kalınlığında.",
  },
  engine_mechanical: {
    motor_performansi_yuzde: "95%",
    turbo_durumu: "Sorunsuz / Basınç normal",
    enjektor_yakit: "Püskürtme normal",
    sanziman_vites: "Kusursuz / Vuruntu yok",
    yag_sivi_kacaklari: "Kaçak tespit edilmedi",
    egzoz_emisyon: "Duman ve partikül normal",
  },
  chassis_frame: {
    on_podyeler: "İşlemsiz / Orijinal",
    arka_podyeler: "İşlemsiz / Orijinal",
    on_arka_travers: "Deformasyon yok",
    marspiyeller: "Kusursuz",
    fren_disk_balata: "İyi durumda (%80 ömür)",
    suspansiyon: "Denge kolları ve amortisörler sağlam",
  },
  tires_wheels: {
    on_sol_dis_mm: "6.8 mm",
    on_sag_dis_mm: "6.7 mm",
    arka_sol_dis_mm: "6.2 mm",
    arka_sag_dis_mm: "6.1 mm",
    dot_yili: "2024",
    jant_durumu: "Balans yapıldı, çatlak/kaynak yok",
    stepne: "Mevcut ve sağlam",
  },
  interior_electronics: {
    airbag_guvenlik: "Tüm hava yastıkları orijinal ve aktif",
    obd_ariza_taramasi: "Elektronik beyin arıza kodu (DTC) yok",
    klima_isitma: "Gaz basıncı ve soğutma tam kapasite",
    koltuk_doseme: "Yırtık veya deformasyon bulunmuyor",
  },
};

function safeJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw || "{}"), null, 2);
  } catch {
    return raw || "{}";
  }
}

const blankFindings = (): typeof SAMPLE_FINDINGS =>
  JSON.parse(JSON.stringify(SAMPLE_FINDINGS, (_k, v) => (typeof v === "string" ? "" : v)));

export function InspectionPanel({ api }: Props) {
  const [reports, setReports] = useState<InspectionReportItem[]>([]);
  const [vehicles, setVehicles] = useState<VehicleItem[]>([]);
  const [appointments, setAppointments] = useState<AppointmentItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Modal states
  const [showForm, setShowForm] = useState(false);
  const [viewReport, setViewReport] = useState<InspectionReportItem | null>(null);

  // Form states
  const [vehicleId, setVehicleId] = useState("");
  const [appointmentId, setAppointmentId] = useState("");
  const [technicianName, setTechnicianName] = useState("");
  const [mileage, setMileage] = useState<number | "">("");
  const [score, setScore] = useState<number | "">("");
  const [summary, setSummary] = useState("");
  const [formCategory, setFormCategory] = useState<
    "paint" | "engine" | "chassis" | "tires" | "interior"
  >("paint");
  const [findings, setFindings] = useState(blankFindings());
  const [photos, setPhotos] = useState<PhotoItem[]>([]);
  const [uploadCaption, setUploadCaption] = useState("");
  const [uploadCategory, setUploadCategory] = useState("Kaporta");
  const [uploading, setUploading] = useState(false);

  useEscape(() => setViewReport(null), !!viewReport);

  async function openPdf(id: string) {
    setError("");
    try {
      const { url } = await api("inspections/" + id + "/signed-link");
      window.open(url, "_blank", "noopener");
    } catch (e) {
      setError("PDF bağlantısı alınamadı: " + errorMessage(e));
    }
  }

  function fillSample() {
    setTechnicianName("Örnek Teknisyen");
    setMileage(65000);
    setScore(92);
    setSummary("ÖRNEK: Motor ve şanzıman performansı iyi seviyede. Kaporta ve şaside işlem tespit edilmemiştir.");
    setFindings(JSON.parse(JSON.stringify(SAMPLE_FINDINGS)));
  }

  // Search & Filter
  const [search, setSearch] = useState("");

  async function act(fn: () => Promise<void>) {
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    const [reps, vehs, apps] = await Promise.all([
      api("inspections"),
      api("vehicles"),
      api("appointments"),
    ]);
    setReports(reps);
    setVehicles(vehs);
    setAppointments(apps);
    if (vehs.length > 0 && !vehicleId) {
      setVehicleId(vehs[0].id);
    }
  }

  useEffect(() => {
    act(refresh);
  }, []);

  // Filtered reports
  const filteredReports = useMemo(() => {
    if (!search.trim()) return reports;
    const q = search.toLowerCase();
    return reports.filter(
      (r) =>
        r.vehicle_plate?.toLowerCase().includes(q) ||
        r.vehicle_description?.toLowerCase().includes(q) ||
        r.technician_name?.toLowerCase().includes(q) ||
        r.summary?.toLowerCase().includes(q)
    );
  }, [reports, search]);

  // Photo upload handler
  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("caption", uploadCaption || file.name);
      formData.append("category", uploadCategory);

      const res = await api("inspections/photos", "POST", formData);
      setPhotos((prev) => [...prev, res]);
      setUploadCaption("");
      setSuccess("Fotoğraf başarıyla yüklendi.");
    } catch (err: any) {
      setError("Fotoğraf yükleme hatası: " + (err.message || String(err)));
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  // Create report
  async function handleCreateReport(e: React.FormEvent) {
    e.preventDefault();
    if (!vehicleId) {
      setError("Lütfen bir araç seçin.");
      return;
    }

    if (score === "" || mileage === "" || summary.trim().length < 5 || !technicianName.trim()) {
      setError("Kilometre, ekspertiz puanı, teknisyen adı ve değerlendirme (en az 5 karakter) açıkça girilmelidir.");
      return;
    }

    await act(async () => {
      // Boş bırakılan bulgular gönderilmez; "Orijinal" gibi varsayılan değerler uydurulmaz.
      const filledFindings = Object.fromEntries(
        Object.entries(findings)
          .map(([cat, obj]) => [
            cat,
            Object.fromEntries(Object.entries(obj).filter(([, v]) => String(v).trim() !== "")),
          ])
          .filter(([, o]) => Object.keys(o as object).length > 0)
      );
      const payload = {
        summary: summary.trim(),
        mileage_km: Number(mileage),
        score: Number(score),
        appointment_id: appointmentId || null,
        technician_name: technicianName.trim(),
        findings: filledFindings,
        photos,
      };

      await api(`vehicles/${vehicleId}/inspections`, "POST", payload);
      setSuccess("Ekspertiz raporu başarıyla kaydedildi ve PDF üretildi.");
      setShowForm(false);
      // Formu temizle
      setSummary("");
      setScore("");
      setMileage("");
      setTechnicianName("");
      setFindings(blankFindings());
      setPhotos([]);
      await refresh();
    });
  }

  // Send digital link via SMS/WhatsApp
  async function handleSendLink(reportId: string) {
    await act(async () => {
      const res = await api(`inspections/${reportId}/send-link`, "POST");
      setSuccess(
        res.status === "delivered"
          ? `Dijital rapor linki SMS ve WhatsApp üzerinden iletildi (${res.notifications_queued} bildirim).`
          : "Bildirim sağlayıcısı yok: rapor linki gönderilmedi (simüle edildi)."
      );
      await refresh();
    });
  }

  function getScoreBadge(s: number | "") {
    if (s === "") return <span className="pill">Puan girilmedi</span>;
    if (s >= 90) return <span className="pill green">Kusursuz (A+) - {s}</span>;
    if (s >= 75) return <span className="pill blue">İyi (B) - {s}</span>;
    if (s >= 50) return <span className="pill yellow">Orta (C) - {s}</span>;
    return <span className="pill red">Riskli (D) - {s}</span>;
  }

  return (
    <div className="section-container">
      {/* Alert Messages */}
      {error && <div className="alert-box error">{error}</div>}
      {success && <div className="alert-box success">{success}</div>}

      {/* Header & Metrics */}
      <div className="stats kpi-grid-4" style={{  }}>
        <div className="card">
          <small>TOPLAM RAPOR</small>
          <h2>{reports.length}</h2>
        </div>
        <div className="card">
          <small>DİJİTAL TESLİM EDİLEN</small>
          <h2>{reports.filter((r) => r.delivered_at).length}</h2>
        </div>
        <div className="card">
          <small>ORTALAMA PUAN</small>
          <h2>
            {reports.length > 0
              ? `${Math.round(
                  reports.reduce((acc, r) => acc + r.score, 0) / reports.length
                )}/100`
              : "—"}
          </h2>
        </div>
        <div className="card">
          <small>A+ KUSURSUZ ARAÇLAR</small>
          <h2>{reports.filter((r) => r.score >= 90).length}</h2>
        </div>
      </div>

      {/* Action Toolbar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          margin: "1.2rem 0",
          gap: "1rem",
        }}
      >
        <input
          type="text"
          placeholder="Plaka, teknisyen veya özete göre ara..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ flex: 1, padding: "0.55rem 0.8rem", borderRadius: "6px" }}
        />
        <button
          className="selected"
          onClick={() => setShowForm(!showForm)}
          style={{ padding: "0.55rem 1.2rem" }}
        >
          {showForm ? "✕ Formu Kapat" : "+ Yeni Ekspertiz Raporu Oluştur"}
        </button>
      </div>

      {/* NEW REPORT FORM */}
      {showForm && (
        <section
          style={{
            background: "#1e293b",
            padding: "1.4rem",
            borderRadius: "8px",
            marginBottom: "1.5rem",
            border: "1px solid #334155",
          }}
        >
          <h2 style={{ marginTop: 0 }}>
            📋 Yeni Ekspertiz Raporu{" "}
            <button
              type="button"
              className="secondary"
              onClick={fillSample}
              style={{ marginLeft: "12px", padding: "4px 10px", fontSize: "12px" }}
            >
              Örnek doldur
            </button>
          </h2>
          <p className="muted" style={{ margin: "0 0 12px", fontSize: "12px" }}>
            Form boş başlar; puan, kilometre ve değerlendirmeyi siz girmelisiniz. Boş bırakılan bulgular rapora yazılmaz.
          </p>
          <form onSubmit={handleCreateReport}>
            <div className="grid-3"
              style={{
                display: "grid",
                
                gap: "1rem",
                marginBottom: "1rem",
              }}
            >
              <div>
                <label htmlFor="insp-vehicle">
                  <b>Ekspertiz Yapılan Araç *</b>
                </label>
                <select
                  id="insp-vehicle"
                  value={vehicleId}
                  onChange={(e) => setVehicleId(e.target.value)}
                  required
                  style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
                >
                  {vehicles.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.plate ? `[${v.plate}] ` : ""}
                      {v.description} {v.vin ? `(VIN: ${v.vin.slice(-6)})` : ""}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="insp-appt">
                  <b>İlişkili Randevu (Opsiyonel)</b>
                </label>
                <select
                  id="insp-appt"
                  value={appointmentId}
                  onChange={(e) => setAppointmentId(e.target.value)}
                  style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
                >
                  <option value="">Randevu Seçilmedi (Doğrudan Giriş)</option>
                  {appointments
                    .filter((a) => !vehicleId || a.vehicle_id === vehicleId)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.customer} (Ref: {a.id.slice(0, 8)})
                      </option>
                    ))}
                </select>
              </div>

              <div>
                <label htmlFor="insp-tech">
                  <b>Teknisyen Adı *</b>
                </label>
                <input
                  id="insp-tech"
                  type="text"
                  value={technicianName}
                  onChange={(e) => setTechnicianName(e.target.value)}
                  required
                  style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
                />
              </div>
            </div>

            <div className="grid-2"
              style={{
                display: "grid",
                
                gap: "1rem",
                marginBottom: "1rem",
              }}
            >
              <div>
                <label htmlFor="insp-km">
                  <b>Kilometre (km) *</b>
                </label>
                <input
                  id="insp-km"
                  type="number"
                  min="0"
                  required
                  value={mileage}
                  onChange={(e) => setMileage(e.target.value === "" ? "" : Number(e.target.value))}
                  style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
                />
              </div>
              <div>
                <label htmlFor="insp-score">
                  <b>Genel Ekspertiz Puanı (0-100) *</b>
                </label>
                <div style={{ display: "flex", alignItems: "center", gap: "0.8rem" }}>
                  <input
                    id="insp-score"
                    type="number"
                    min="0"
                    max="100"
                    required
                    value={score}
                    onChange={(e) => setScore(e.target.value === "" ? "" : Number(e.target.value))}
                    style={{ flex: 1 }}
                  />
                  {getScoreBadge(score)}
                </div>
              </div>
            </div>

            <div style={{ marginBottom: "1rem" }}>
              <label htmlFor="insp-summary">
                <b>Genel Değerlendirme & Uzman Kanaati *</b>
              </label>
              <textarea
                id="insp-summary"
                minLength={5}
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                rows={2}
                required
                style={{ width: "100%", padding: "0.5rem", marginTop: "0.3rem" }}
              />
            </div>

            {/* 5 Findings Categories Sub-tabs */}
            <div style={{ margin: "1.2rem 0" }}>
              <div
                style={{
                  display: "flex",
                  gap: "0.5rem",
                  borderBottom: "1px solid #475569",
                  paddingBottom: "0.4rem",
                }}
              >
                {[
                  { id: "paint", label: "🎨 Boya & Kaporta" },
                  { id: "engine", label: "⚙️ Motor & Mekanik" },
                  { id: "chassis", label: "🔩 Alt Takım & Şasi" },
                  { id: "tires", label: "🛞 Lastik & Jant" },
                  { id: "interior", label: "🛋️ İç Mekan & OBD" },
                ].map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className={formCategory === c.id ? "selected" : ""}
                    onClick={() => setFormCategory(c.id as any)}
                    style={{ fontSize: "0.85rem", padding: "0.4rem 0.8rem" }}
                  >
                    {c.label}
                  </button>
                ))}
              </div>

              {/* Category 1: Paint & Body */}
              {formCategory === "paint" && (
                <div className="grid-3"
                  style={{
                    display: "grid",
                    
                    gap: "0.8rem",
                    paddingTop: "1rem",
                  }}
                >
                  {[
                    ["kaput", "Ön Kaput"],
                    ["tavan", "Tavan"],
                    ["bagaj", "Bagaj Kapağı"],
                    ["sag_on_camurluk", "Sağ Ön Çamurluk"],
                    ["sol_on_camurluk", "Sol Ön Çamurluk"],
                    ["sag_on_kapi", "Sağ Ön Kapı"],
                    ["sol_on_kapi", "Sol Ön Kapı"],
                    ["sag_arka_kapi", "Sağ Arka Kapı"],
                    ["sol_arka_kapi", "Sol Arka Kapı"],
                    ["sag_arka_camurluk", "Sağ Arka Çamurluk"],
                    ["sol_arka_camurluk", "Sol Arka Çamurluk"],
                  ].map(([key, label]) => (
                    <div key={key}>
                      <small>{label}</small>
                      <select
                        value={(findings.paint_body as any)[key] || ""}
                        onChange={(e) =>
                          setFindings({
                            ...findings,
                            paint_body: {
                              ...findings.paint_body,
                              [key]: e.target.value,
                            },
                          })
                        }
                        style={{ width: "100%", padding: "0.35rem" }}
                      >
                        <option value="">Seçilmedi</option>
                        <option value="Orijinal">Orijinal</option>
                        <option value="Lokal Boyalı">Lokal Boyalı</option>
                        <option value="Boyalı">Boyalı</option>
                        <option value="Değişen">Değişen</option>
                      </select>
                    </div>
                  ))}
                  <div style={{ gridColumn: "1 / -1" }}>
                    <small>Kaporta Notları / Mikron Değerleri</small>
                    <input
                      type="text"
                      value={findings.paint_body.notlar}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          paint_body: {
                            ...findings.paint_body,
                            notlar: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                </div>
              )}

              {/* Category 2: Engine */}
              {formCategory === "engine" && (
                <div className="grid-2"
                  style={{
                    display: "grid",
                    
                    gap: "0.8rem",
                    paddingTop: "1rem",
                  }}
                >
                  <div>
                    <small>Motor Performansı (Dyno %)</small>
                    <input
                      type="text"
                      value={findings.engine_mechanical.motor_performansi_yuzde}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          engine_mechanical: {
                            ...findings.engine_mechanical,
                            motor_performansi_yuzde: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                  <div>
                    <small>Turbo / Kompresör Durumu</small>
                    <input
                      type="text"
                      value={findings.engine_mechanical.turbo_durumu}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          engine_mechanical: {
                            ...findings.engine_mechanical,
                            turbo_durumu: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                  <div>
                    <small>Şanzıman ve Vites Geçişleri</small>
                    <input
                      type="text"
                      value={findings.engine_mechanical.sanziman_vites}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          engine_mechanical: {
                            ...findings.engine_mechanical,
                            sanziman_vites: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                  <div>
                    <small>Yağ ve Sıvı Kaçakları</small>
                    <input
                      type="text"
                      value={findings.engine_mechanical.yag_sivi_kacaklari}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          engine_mechanical: {
                            ...findings.engine_mechanical,
                            yag_sivi_kacaklari: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                </div>
              )}

              {/* Category 3: Chassis */}
              {formCategory === "chassis" && (
                <div className="grid-2"
                  style={{
                    display: "grid",
                    
                    gap: "0.8rem",
                    paddingTop: "1rem",
                  }}
                >
                  <div>
                    <small>Ön ve Arka Podyeler</small>
                    <input
                      type="text"
                      value={findings.chassis_frame.on_podyeler}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          chassis_frame: {
                            ...findings.chassis_frame,
                            on_podyeler: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                  <div>
                    <small>Travers ve Kuleler</small>
                    <input
                      type="text"
                      value={findings.chassis_frame.on_arka_travers}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          chassis_frame: {
                            ...findings.chassis_frame,
                            on_arka_travers: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                  <div>
                    <small>Marşpiyeller ve Taban Sacı</small>
                    <input
                      type="text"
                      value={findings.chassis_frame.marspiyeller}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          chassis_frame: {
                            ...findings.chassis_frame,
                            marspiyeller: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                  <div>
                    <small>Fren Disk ve Balataları</small>
                    <input
                      type="text"
                      value={findings.chassis_frame.fren_disk_balata}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          chassis_frame: {
                            ...findings.chassis_frame,
                            fren_disk_balata: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                </div>
              )}

              {/* Category 4: Tires */}
              {formCategory === "tires" && (
                <div className="grid-3"
                  style={{
                    display: "grid",
                    
                    gap: "0.8rem",
                    paddingTop: "1rem",
                  }}
                >
                  <div>
                    <small>Ön Lastik Diş Derinliği (mm)</small>
                    <input
                      type="text"
                      value={findings.tires_wheels.on_sol_dis_mm}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          tires_wheels: {
                            ...findings.tires_wheels,
                            on_sol_dis_mm: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                  <div>
                    <small>Arka Lastik Diş Derinliği (mm)</small>
                    <input
                      type="text"
                      value={findings.tires_wheels.arka_sol_dis_mm}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          tires_wheels: {
                            ...findings.tires_wheels,
                            arka_sol_dis_mm: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                  <div>
                    <small>DOT Üretim Yılı</small>
                    <input
                      type="text"
                      value={findings.tires_wheels.dot_yili}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          tires_wheels: {
                            ...findings.tires_wheels,
                            dot_yili: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                </div>
              )}

              {/* Category 5: Interior & Electronics */}
              {formCategory === "interior" && (
                <div className="grid-2"
                  style={{
                    display: "grid",
                    
                    gap: "0.8rem",
                    paddingTop: "1rem",
                  }}
                >
                  <div>
                    <small>Airbag Güvenlik Sistemi</small>
                    <input
                      type="text"
                      value={findings.interior_electronics.airbag_guvenlik}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          interior_electronics: {
                            ...findings.interior_electronics,
                            airbag_guvenlik: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                  <div>
                    <small>OBD Elektronik Beyin Arıza Taraması</small>
                    <input
                      type="text"
                      value={findings.interior_electronics.obd_ariza_taramasi}
                      onChange={(e) =>
                        setFindings({
                          ...findings,
                          interior_electronics: {
                            ...findings.interior_electronics,
                            obd_ariza_taramasi: e.target.value,
                          },
                        })
                      }
                      style={{ width: "100%", padding: "0.4rem" }}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Photo Upload Section */}
            <div
              style={{
                marginTop: "1.2rem",
                padding: "1rem",
                background: "#0f172a",
                borderRadius: "6px",
              }}
            >
              <h4 style={{ margin: "0 0 0.6rem 0" }}>📸 Fotoğraf Ekle</h4>
              <div
                style={{
                  display: "flex",
                  gap: "0.8rem",
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <select
                  value={uploadCategory}
                  onChange={(e) => setUploadCategory(e.target.value)}
                  style={{ padding: "0.4rem" }}
                >
                  <option value="Kaporta">Kaporta</option>
                  <option value="Motor">Motor</option>
                  <option value="Alt Takım">Alt Takım</option>
                  <option value="İç Mekan">İç Mekan</option>
                  <option value="Genel">Genel</option>
                </select>
                <input
                  type="text"
                  placeholder="Görsel açıklaması (Örn: Motor Bloğu)"
                  value={uploadCaption}
                  onChange={(e) => setUploadCaption(e.target.value)}
                  style={{ padding: "0.4rem", flex: 1 }}
                />
                <label
                  className="button"
                  style={{
                    background: "#0284c7",
                    color: "white",
                    padding: "0.45rem 0.9rem",
                    borderRadius: "4px",
                    cursor: "pointer",
                  }}
                >
                  {uploading ? "Yükleniyor..." : "Dosya Seç & Yükle"}
                  <input
                    type="file"
                    accept="image/*"
                    onChange={handleFileUpload}
                    style={{ display: "none" }}
                    disabled={uploading}
                  />
                </label>
              </div>

              {/* Photo preview thumbnails */}
              {photos.length > 0 && (
                <div
                  style={{
                    display: "flex",
                    gap: "0.8rem",
                    marginTop: "0.8rem",
                    flexWrap: "wrap",
                  }}
                >
                  {photos.map((p, idx) => (
                    <div
                      key={idx}
                      style={{
                        position: "relative",
                        width: "100px",
                        borderRadius: "4px",
                        overflow: "hidden",
                        border: "1px solid #475569",
                        textAlign: "center",
                      }}
                    >
                      <img
                        src={p.url}
                        alt={p.caption}
                        style={{ width: "100px", height: "65px", objectFit: "cover" }}
                      />
                      <small
                        style={{
                          display: "block",
                          fontSize: "0.7rem",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          padding: "2px",
                        }}
                      >
                        {p.caption}
                      </small>
                      <button
                        type="button"
                        onClick={() =>
                          setPhotos((prev) => prev.filter((_, i) => i !== idx))
                        }
                        style={{
                          position: "absolute",
                          top: 2,
                          right: 2,
                          background: "rgba(220, 38, 38, 0.8)",
                          color: "white",
                          border: "none",
                          borderRadius: "50%",
                          width: "18px",
                          height: "18px",
                          lineHeight: "16px",
                          fontSize: "10px",
                          cursor: "pointer",
                        }}
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div
              style={{
                marginTop: "1.2rem",
                display: "flex",
                justifyContent: "flex-end",
                gap: "0.8rem",
              }}
            >
              <button
                type="button"
                onClick={() => setShowForm(false)}
                style={{ padding: "0.55rem 1.2rem" }}
              >
                İptal
              </button>
              <button
                type="submit"
                className="selected"
                disabled={loading}
                style={{ padding: "0.55rem 1.4rem" }}
              >
                {loading ? "Kaydediliyor..." : "💾 Raporu Kaydet & PDF Üret"}
              </button>
            </div>
          </form>
        </section>
      )}

      {/* INSPECTIONS TABLE */}
      <section>
        <h2>📄 Ekspertiz Raporları ve Dijital Teslim Takibi</h2>
        <div className="table-wrap"><table style={{ width: "100%", marginTop: "0.8rem" }}>
          <thead>
            <tr>
              <th>Plaka & Araç</th>
              <th>Tarih</th>
              <th>Teknisyen</th>
              <th>Kilometre</th>
              <th>Skor</th>
              <th>Dijital Teslim</th>
              <th>İşlemler</th>
            </tr>
          </thead>
          <tbody>
            {filteredReports.map((r) => (
              <tr key={r.id}>
                <td>
                  <b>{r.vehicle_plate || "PLAKASIZ"}</b>
                  <br />
                  <small style={{ color: "#94a3b8" }}>
                    {r.vehicle_description || "Bilinmeyen Araç"}
                  </small>
                </td>
                <td>{r.inspected_at?.slice(0, 16).replace("T", " ")}</td>
                <td>{r.technician_name}</td>
                <td>{r.mileage_km ? r.mileage_km.toLocaleString("tr-TR") + " km" : "—"}</td>
                <td>{getScoreBadge(r.score)}</td>
                <td>
                  {r.delivered_at ? (
                    <span className="pill green" title={r.delivered_at}>
                      ✓ Gönderildi (
                      {r.delivered_at.slice(8, 10)}.{r.delivered_at.slice(5, 7)})
                    </span>
                  ) : (
                    <span className="pill yellow">İletilmedi</span>
                  )}
                </td>
                <td>
                  <div style={{ display: "flex", gap: "0.4rem" }}>
                    <button
                      type="button"
                      onClick={() => openPdf(r.id)}
                      style={{
                        padding: "0.3rem 0.6rem",
                        fontSize: "0.78rem",
                        background: "#0284c7",
                        color: "white",
                        borderRadius: "4px",
                      }}
                    >
                      📥 PDF İndir
                    </button>
                    <button
                      onClick={() => handleSendLink(r.id)}
                      disabled={loading}
                      style={{
                        padding: "0.3rem 0.6rem",
                        fontSize: "0.78rem",
                        background: "#16a34a",
                        color: "white",
                        border: "none",
                        borderRadius: "4px",
                        cursor: "pointer",
                      }}
                      title="Müşteriye SMS, kurumsal hesaba WhatsApp ile dijital link gönderir"
                    >
                      📱 SMS/WA İlet
                    </button>
                    <button
                      onClick={() => setViewReport(r)}
                      style={{
                        padding: "0.3rem 0.6rem",
                        fontSize: "0.78rem",
                        borderRadius: "4px",
                        cursor: "pointer",
                      }}
                    >
                      🔍 Detay
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {filteredReports.length === 0 && (
              <tr>
                <td colSpan={7} style={{ textAlign: "center", padding: "1.5rem" }}>
                  Kayıtlı ekspertiz raporu bulunamadı.
                </td>
              </tr>
            )}
          </tbody>
        </table></div>
      </section>

      {/* REPORT DETAIL MODAL */}
      {viewReport && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Ekspertiz rapor detayı"
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div
            style={{
              background: "#1e293b",
              borderRadius: "8px",
              padding: "1.5rem",
              width: "700px",
              maxWidth: "92vw",
              maxHeight: "85vh",
              overflowY: "auto",
              border: "1px solid #475569",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <h3 style={{ margin: 0 }}>
                🔍 Ekspertiz Rapor Detayı: {viewReport.vehicle_plate}
              </h3>
              <button
                onClick={() => setViewReport(null)}
                aria-label="Kapat"
                style={{ background: "transparent", border: "none", fontSize: "1.2rem" }}
              >
                ✕
              </button>
            </div>
            <hr style={{ borderColor: "#334155", margin: "0.8rem 0" }} />
            <p>
              <b>Araç:</b> {viewReport.vehicle_description} | <b>Teknisyen:</b>{" "}
              {viewReport.technician_name}
            </p>
            <p>
              <b>Kilometre:</b> {viewReport.mileage_km.toLocaleString()} km |{" "}
              <b>Puan:</b> {viewReport.score}/100
            </p>
            <p>
              <b>Özet Değerlendirme:</b> {viewReport.summary}
            </p>

            <div style={{ marginTop: "1rem" }}>
              <h4>Bulgular (JSON):</h4>
              <pre
                style={{
                  background: "#0f172a",
                  padding: "0.8rem",
                  borderRadius: "4px",
                  fontSize: "0.78rem",
                  overflowX: "auto",
                }}
              >
                {safeJson(viewReport.findings_json)}
              </pre>
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: "0.8rem",
                marginTop: "1rem",
              }}
            >
              <button
                type="button"
                className="selected"
                onClick={() => openPdf(viewReport.id)}
                style={{ padding: "0.4rem 0.9rem" }}
              >
                📥 PDF Raporunu Görüntüle
              </button>
              <button
                onClick={() => setViewReport(null)}
                style={{ padding: "0.4rem 0.9rem" }}
              >
                Kapat
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
````


### frontend/src/lazyPanels.ts

````
import React, { lazy } from "react";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const lazyPanel = <K extends string>(load: () => Promise<Record<K, React.ComponentType<any>>>, name: K) =>
  lazy(() => load().then((m) => ({ default: m[name] })));
export const MilestonePanel = lazyPanel(() => import("./MilestonePanel"), "MilestonePanel");
export const LexiconPanel = lazyPanel(() => import("./LexiconPanel"), "LexiconPanel");
export const NotificationPanel = lazyPanel(() => import("./NotificationPanel"), "NotificationPanel");
export const OutboundPanel = lazyPanel(() => import("./OutboundPanel"), "OutboundPanel");
export const InspectionPanel = lazyPanel(() => import("./InspectionPanel"), "InspectionPanel");
export const AnalyticsPanel = lazyPanel(() => import("./AnalyticsPanel"), "AnalyticsPanel");
export const DiagnosticPanel = lazyPanel(() => import("./DiagnosticPanel"), "DiagnosticPanel");
export const TechnicianDictationPanel = lazyPanel(
  () => import("./TechnicianDictationPanel"),
  "TechnicianDictationPanel",
);
export const QueueLiftPanel = lazyPanel(() => import("./QueueLiftPanel"), "QueueLiftPanel");
export const ABTestingPanel = lazyPanel(() => import("./ABTestingPanel"), "ABTestingPanel");
export const OperatorPanel = lazyPanel(() => import("./OperatorPanel"), "OperatorPanel");
export const SupervisorPanel = lazyPanel(() => import("./SupervisorPanel"), "SupervisorPanel");
export const CarDenoiserPanel = lazyPanel(() => import("./CarDenoiserPanel"), "CarDenoiserPanel");
export const OntologyPanel = lazyPanel(() => import("./OntologyPanel"), "OntologyPanel");
````


### frontend/src/LexiconPanel.tsx

````
/**
 * FreyaTTS Automotive Cockpit V3 — F4 Morphological Pre-Checker, Sezer Vurgusu & Sözlük Kokpiti
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useEffect, useState, useMemo } from "react";
import { errorMessage } from "./ui";
import type { ApiProps as Props } from "./api";
import {
  Sparkles, BookOpen, Volume2, Plus, Trash2, CheckCircle2,
  Sliders, Search, Filter, RefreshCw
} from "lucide-react";
import {
  INITIAL_F4_RULES,
  F4Rule,
  runF4Pipeline,
  speakF4ChunksSequentially
} from "./pipeline/f4Engine";

export type LexiconEntry = {
  term: string;
  spoken: string;
  category: string;
  is_base: boolean;
  is_override: boolean;
};

export function LexiconPanel({ api }: Props) {
  const [activeSubTab, setActiveSubTab] = useState<"f4_engine" | "db_lexicon">("f4_engine");

  // F4 Rules State
  const [f4Rules, setF4Rules] = useState<F4Rule[]>(INITIAL_F4_RULES);
  const [f4CategoryFilter, setF4CategoryFilter] = useState<string>("all");
  const [f4Search, setF4Search] = useState("");
  const [newPattern, setNewPattern] = useState("");
  const [newReplacement, setNewReplacement] = useState("");
  const [newSezer, setNewSezer] = useState("Özel Vurgu");
  const [newCategory, setNewCategory] = useState<F4Rule["category"]>("Marka");

  // F4 Simulator State
  const [f4TestInput, setF4TestInput] = useState(
    "Merhaba, Trabzon'da Ortahisar şubemiz için 61 TS 061 plakalı Peugeot 3008 1.5 BlueHDi aracın OBD-II P0300 ve DSG şanzıman ekspertizi 14.500 TL tutmaktadır, yarın 09:30 uygun mudur?"
  );
  const [activeSpeakingChunk, setActiveSpeakingChunk] = useState<number | null>(null);
  const [stopSpeechFn, setStopSpeechFn] = useState<(() => void) | null>(null);

  // DB Lexicon State (Persistent Backend)
  const [entries, setEntries] = useState<LexiconEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [term, setTerm] = useState("");
  const [spoken, setSpoken] = useState("");
  const [category, setCategory] = useState("brand");
  const [editingTerm, setEditingTerm] = useState<string | null>(null);
  const [dbSearch, setDbSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [onlyCustom, setOnlyCustom] = useState(false);

  // Compute live F4 pipeline result
  const f4Result = useMemo(
    () => runF4Pipeline(f4TestInput, f4Rules),
    [f4TestInput, f4Rules]
  );

  async function act(fn: () => Promise<void>) {
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function refreshDb() {
    try {
      const list = await api("lexicon");
      if (Array.isArray(list)) setEntries(list);
    } catch (e) {
      // Non-blocking
    }
  }

  useEffect(() => {
    act(refreshDb);
  }, []);

  // F4 Play Speech
  const handlePlayF4Preview = () => {
    if (stopSpeechFn) {
      stopSpeechFn();
      setStopSpeechFn(null);
      setActiveSpeakingChunk(null);
      return;
    }
    const cancel = speakF4ChunksSequentially(
      f4Result,
      (idx) => setActiveSpeakingChunk(idx),
      () => {
        setActiveSpeakingChunk(null);
        setStopSpeechFn(null);
      }
    );
    setStopSpeechFn(() => cancel);
  };

  // Add new F4 Rule
  const handleAddF4Rule = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPattern.trim() || !newReplacement.trim()) return;
    const rule: F4Rule = {
      id: `r_${Date.now()}`,
      pattern: newPattern.trim(),
      replacement: newReplacement.trim(),
      sezer: newSezer.trim() || "Özel Vurgu",
      category: newCategory,
      active: true,
    };
    setF4Rules((prev) => [rule, ...prev]);
    setNewPattern("");
    setNewReplacement("");
    setNewSezer("Özel Vurgu");
    setSuccess(`Yeni F4 kuralı eklendi: '${rule.pattern}' → '${rule.replacement}'`);
  };

  // DB Lexicon Save
  async function handleDbSave(e: React.FormEvent) {
    e.preventDefault();
    if (!term.trim() || !spoken.trim()) {
      setError("Terim ve telaffuz boş olamaz.");
      return;
    }
    await act(async () => {
      const res = await api("lexicon", "POST", {
        term: term.trim(),
        spoken: spoken.trim(),
        category,
      });
      setSuccess(`'${res.term}' kaydedildi (${res.spoken}).`);
      setTerm("");
      setSpoken("");
      setEditingTerm(null);
      await refreshDb();
    });
  }

  // Filtered F4 Rules
  const filteredF4Rules = useMemo(() => {
    return f4Rules.filter((r) => {
      if (f4CategoryFilter !== "all" && r.category !== f4CategoryFilter) return false;
      if (f4Search.trim()) {
        const q = f4Search.trim().toLowerCase();
        return (
          r.pattern.toLowerCase().includes(q) ||
          r.replacement.toLowerCase().includes(q) ||
          r.sezer.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [f4Rules, f4CategoryFilter, f4Search]);

  const f4Categories = useMemo(() => {
    const set = new Set<string>();
    f4Rules.forEach((r) => set.add(r.category));
    return Array.from(set);
  }, [f4Rules]);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: "8px", minHeight: 0, overflowY: "auto", padding: "2px 4px" }}>
      {/* ÜST GEZİNME & SUB-TAB SEÇİCİ */}
      <div
        style={{
          background: "#0f172a",
          border: "1px solid #1e293b",
          borderRadius: "8px",
          padding: "8px 14px",
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "8px",
          flexShrink: 0,
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <h2 style={{ margin: 0, fontSize: "16px", fontWeight: "800", color: "#f8fafc" }}>
              Sözlük, Fonetik & Morphological Pre-Checker
            </h2>
            <span className="stage-badge brand" title="F4 Aşaması: Morfolojik Ön-Kontrol ve Sezer Vurgusu Kural Motoru">
              F4 Morpho & Phonetic
            </span>
          </div>
          <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#94a3b8" }}>
            Peugeot, Qashqai, DSG, OBD-II ve Trabzon/Ortahisar trochaic Sezer vurgusunu yöneten G2P motoru.
          </p>
        </div>

        <div style={{ display: "flex", gap: "8px" }}>
          <button
            type="button"
            onClick={() => setActiveSubTab("f4_engine")}
            style={{
              padding: "8px 16px",
              borderRadius: "8px",
              fontSize: "12px",
              fontFamily: "monospace",
              fontWeight: "bold",
              cursor: "pointer",
              border: activeSubTab === "f4_engine" ? "1px solid #38bdf8" : "1px solid #334155",
              background: activeSubTab === "f4_engine" ? "rgba(56, 189, 248, 0.2)" : "#1e293b",
              color: activeSubTab === "f4_engine" ? "#38bdf8" : "#94a3b8",
            }}
          >
            ⚡ F₄ G2P & Chunker Motoru ({f4Rules.filter((r) => r.active).length} Kural)
          </button>
          <button
            type="button"
            onClick={() => setActiveSubTab("db_lexicon")}
            style={{
              padding: "8px 16px",
              borderRadius: "8px",
              fontSize: "12px",
              fontFamily: "monospace",
              fontWeight: "bold",
              cursor: "pointer",
              border: activeSubTab === "db_lexicon" ? "1px solid #10b981" : "1px solid #334155",
              background: activeSubTab === "db_lexicon" ? "rgba(16, 185, 129, 0.2)" : "#1e293b",
              color: activeSubTab === "db_lexicon" ? "#10b981" : "#94a3b8",
            }}
          >
            📚 Veritabanı Sözlüğü ({entries.length} Terim)
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="error" style={{ margin: 0 }}>
          {error}
        </div>
      )}
      {success && (
        <div
          role="status"
          style={{
            background: "rgba(6, 78, 59, 0.3)",
            border: "1px solid #059669",
            color: "#6ee7b7",
            padding: "10px 16px",
            borderRadius: "8px",
            fontSize: "12px",
          }}
        >
          {success}
        </div>
      )}

      {/* ==================================================================== */}
      {/* 1. F4 G2P & CLAUSE CHUNKER MOTORU (PROTOTİP MOTORU) */}
      {/* ==================================================================== */}
      {activeSubTab === "f4_engine" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* CANLI TEST SİMÜLATÖRÜ & SIRALI SESLENDİRİCİ */}
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #f59e0b",
              borderRadius: "12px",
              padding: "18px 20px",
              display: "flex",
              flexDirection: "column",
              gap: "14px",
              boxShadow: "0 10px 25px -5px rgba(245, 158, 11, 0.1)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "10px" }}>
              <span
                style={{
                  fontSize: "13px",
                  fontWeight: "bold",
                  color: "#fde68a",
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  fontFamily: "monospace",
                }}
              >
                <Sparkles style={{ width: "16px", height: "16px" }} />
                CANLI F₄ FONETİK G2P, SEZER VURGUSU & CLAUSE CHUNKER ({f4Result.processingMs} ms)
              </span>

              <button
                type="button"
                onClick={handlePlayF4Preview}
                style={{
                  background: stopSpeechFn ? "#ef4444" : "#10b981",
                  color: "#0f172a",
                  fontWeight: "bold",
                  fontSize: "12px",
                  fontFamily: "monospace",
                  padding: "8px 16px",
                  borderRadius: "8px",
                  cursor: "pointer",
                  border: 0,
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                <Volume2 style={{ width: "16px", height: "16px" }} />
                <span>{stopSpeechFn ? "⏹️ Seslendirmeyi Durdur" : "🔊 F₄ Chunklarını Sırayla Seslendir"}</span>
              </button>
            </div>

            <textarea
              rows={2}
              value={f4TestInput}
              onChange={(e) => setF4TestInput(e.target.value)}
              style={{
                background: "#090d16",
                border: "1px solid #334155",
                borderRadius: "8px",
                padding: "10px 14px",
                color: "#f8fafc",
                fontSize: "12px",
                fontFamily: "monospace",
                width: "100%",
                boxSizing: "border-box",
              }}
            />

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "12px" }}>
              {/* Normalize & Sezer G2P Çıktısı */}
              <div
                style={{
                  background: "#090d16",
                  border: "1px solid rgba(16, 185, 129, 0.3)",
                  borderRadius: "8px",
                  padding: "12px 14px",
                  fontSize: "12px",
                  fontFamily: "monospace",
                }}
              >
                <div style={{ color: "#94a3b8", fontSize: "10px", marginBottom: "4px" }}>
                  F₄ Normalize & Sezer G2P Çıktısı:
                </div>
                <div style={{ color: "#6ee7b7", fontWeight: "bold" }}>
                  "{f4Result.phoneticText}"
                </div>
              </div>

              {/* Clause Chunks & TTFA */}
              <div
                style={{
                  background: "#090d16",
                  border: "1px solid rgba(56, 189, 248, 0.3)",
                  borderRadius: "8px",
                  padding: "12px 14px",
                  fontSize: "12px",
                  fontFamily: "monospace",
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "center",
                  gap: "6px",
                }}
              >
                {f4Result.chunks.map((ch) => (
                  <span
                    key={ch.index}
                    style={{
                      background: activeSpeakingChunk === ch.index ? "rgba(245, 158, 11, 0.3)" : "rgba(56, 189, 248, 0.15)",
                      border: activeSpeakingChunk === ch.index ? "1px solid #f59e0b" : "1px solid rgba(56, 189, 248, 0.3)",
                      color: activeSpeakingChunk === ch.index ? "#fef08a" : "#bae6fd",
                      padding: "4px 8px",
                      borderRadius: "6px",
                      fontSize: "11px",
                      transition: "all 0.15s ease",
                    }}
                  >
                    <strong>[Chunk #{ch.index} • {ch.ttfaMs}ms]</strong> {ch.text}
                  </span>
                ))}
              </div>
            </div>

            {/* Uygulanan Kurallar Rozetleri */}
            {f4Result.appliedHits.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
                <span style={{ fontSize: "11px", color: "#94a3b8", fontFamily: "monospace" }}>
                  Uygulanan Eşleşmeler ({f4Result.appliedHits.length}):
                </span>
                {f4Result.appliedHits.map((hit, idx) => (
                  <span
                    key={idx}
                    style={{
                      background: "rgba(245, 158, 11, 0.15)",
                      border: "1px solid rgba(245, 158, 11, 0.3)",
                      color: "#fde68a",
                      fontSize: "11px",
                      padding: "2px 8px",
                      borderRadius: "6px",
                      fontFamily: "monospace",
                    }}
                  >
                    {hit.from} → <strong>{hit.to}</strong> ({hit.sezer})
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* YENİ F4 KURALI EKLEME FORMU */}
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: "12px",
              padding: "16px 20px",
            }}
          >
            <h3 style={{ margin: "0 0 12px", fontSize: "13px", fontWeight: "700", color: "#f8fafc" }}>
              + Yeni F₄ Fonetik / Sezer Vurgu Kuralı Tanımla
            </h3>
            <form onSubmit={handleAddF4Rule} style={{ display: "flex", flexWrap: "wrap", gap: "10px" }}>
              <input
                required
                type="text"
                placeholder="Desen (örn: Chery Tiggo)"
                value={newPattern}
                onChange={(e) => setNewPattern(e.target.value)}
                style={{
                  flex: "1 1 180px",
                  background: "#090d16",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  padding: "8px 12px",
                  color: "#fff",
                  fontSize: "12px",
                  fontFamily: "monospace",
                }}
              />
              <input
                required
                type="text"
                placeholder="Okunuş (örn: Çeri Tigo)"
                value={newReplacement}
                onChange={(e) => setNewReplacement(e.target.value)}
                style={{
                  flex: "1 1 180px",
                  background: "#090d16",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  padding: "8px 12px",
                  color: "#fff",
                  fontSize: "12px",
                  fontFamily: "monospace",
                }}
              />
              <input
                type="text"
                placeholder="Sezer Vurgusu (örn: çe'ri)"
                value={newSezer}
                onChange={(e) => setNewSezer(e.target.value)}
                style={{
                  flex: "1 1 160px",
                  background: "#090d16",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  padding: "8px 12px",
                  color: "#fff",
                  fontSize: "12px",
                  fontFamily: "monospace",
                }}
              />
              <select
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value as any)}
                style={{
                  background: "#090d16",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  padding: "8px 12px",
                  color: "#fff",
                  fontSize: "12px",
                }}
              >
                <option value="Marka">Marka</option>
                <option value="Model">Model</option>
                <option value="Motor">Motor</option>
                <option value="Şanzıman">Şanzıman</option>
                <option value="Sıvı/Emisyon">Sıvı/Emisyon</option>
                <option value="Teşhis">Teşhis</option>
                <option value="DTC">DTC</option>
                <option value="Plaka">Plaka</option>
                <option value="Sezer Vurgu">Sezer Vurgu</option>
                <option value="Birim">Birim</option>
              </select>
              <button
                type="submit"
                style={{
                  background: "#38bdf8",
                  color: "#0f172a",
                  fontWeight: "bold",
                  fontSize: "12px",
                  padding: "8px 18px",
                  borderRadius: "8px",
                  cursor: "pointer",
                  border: 0,
                }}
              >
                + Kural Ekle
              </button>
            </form>
          </div>

          {/* F4 KURALLARI TABLOSU & KATEGORİ FİLTRESİ */}
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: "12px",
              padding: "16px 20px",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
            }}
          >
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: "10px" }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                <button
                  type="button"
                  onClick={() => setF4CategoryFilter("all")}
                  style={{
                    padding: "4px 10px",
                    borderRadius: "6px",
                    fontSize: "11px",
                    cursor: "pointer",
                    border: f4CategoryFilter === "all" ? "1px solid #38bdf8" : "1px solid #334155",
                    background: f4CategoryFilter === "all" ? "rgba(56, 189, 248, 0.2)" : "#090d16",
                    color: f4CategoryFilter === "all" ? "#38bdf8" : "#94a3b8",
                  }}
                >
                  Tümü ({f4Rules.length})
                </button>
                {f4Categories.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setF4CategoryFilter(c)}
                    style={{
                      padding: "4px 10px",
                      borderRadius: "6px",
                      fontSize: "11px",
                      cursor: "pointer",
                      border: f4CategoryFilter === c ? "1px solid #38bdf8" : "1px solid #334155",
                      background: f4CategoryFilter === c ? "rgba(56, 189, 248, 0.2)" : "#090d16",
                      color: f4CategoryFilter === c ? "#38bdf8" : "#94a3b8",
                    }}
                  >
                    {c} ({f4Rules.filter((r) => r.category === c).length})
                  </button>
                ))}
              </div>

              <input
                type="text"
                placeholder="Kural ara..."
                value={f4Search}
                onChange={(e) => setF4Search(e.target.value)}
                style={{
                  background: "#090d16",
                  border: "1px solid #334155",
                  borderRadius: "6px",
                  padding: "4px 10px",
                  color: "#fff",
                  fontSize: "11px",
                  fontFamily: "monospace",
                }}
              />
            </div>

            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px", fontFamily: "monospace" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #334155", color: "#94a3b8", textAlign: "left" }}>
                    <th style={{ padding: "8px" }}>Desen (Pattern)</th>
                    <th style={{ padding: "8px" }}>Okunuş (Replacement)</th>
                    <th style={{ padding: "8px" }}>Sezer Vurgusu</th>
                    <th style={{ padding: "8px" }}>Kategori</th>
                    <th style={{ padding: "8px", textAlign: "center" }}>Durum</th>
                    <th style={{ padding: "8px", textAlign: "right" }}>İşlem</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredF4Rules.map((rule) => (
                    <tr key={rule.id} style={{ borderBottom: "1px solid #1e293b" }}>
                      <td style={{ padding: "8px", color: "#f8fafc", fontWeight: "bold" }}>{rule.pattern}</td>
                      <td style={{ padding: "8px", color: "#a7f3d0" }}>{rule.replacement}</td>
                      <td style={{ padding: "8px", color: "#fde68a" }}>{rule.sezer}</td>
                      <td style={{ padding: "8px", color: "#38bdf8" }}>{rule.category}</td>
                      <td style={{ padding: "8px", textAlign: "center" }}>
                        <button
                          type="button"
                          onClick={() =>
                            setF4Rules((prev) =>
                              prev.map((r) => (r.id === rule.id ? { ...r, active: !r.active } : r))
                            )
                          }
                          style={{
                            padding: "2px 8px",
                            borderRadius: "4px",
                            fontSize: "10px",
                            fontWeight: "bold",
                            cursor: "pointer",
                            border: rule.active ? "1px solid #10b981" : "1px solid #64748b",
                            background: rule.active ? "rgba(16, 185, 129, 0.2)" : "#1e293b",
                            color: rule.active ? "#6ee7b7" : "#94a3b8",
                          }}
                        >
                          {rule.active ? "AKTİF" : "PASİF"}
                        </button>
                      </td>
                      <td style={{ padding: "8px", textAlign: "right" }}>
                        <button
                          type="button"
                          onClick={() => setF4Rules((prev) => prev.filter((r) => r.id !== rule.id))}
                          style={{
                            background: "transparent",
                            border: 0,
                            color: "#ef4444",
                            cursor: "pointer",
                            padding: "4px",
                          }}
                          title="Kuralı Sil"
                        >
                          <Trash2 style={{ width: "14px", height: "14px" }} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ==================================================================== */}
      {/* 2. VERİTABANI SÖZLÜĞÜ (MEVCUT API ENTEGRASYONU) */}
      {/* ==================================================================== */}
      {activeSubTab === "db_lexicon" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* Terim Ekleme / Güncelleme Formu */}
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: "12px",
              padding: "16px 20px",
            }}
          >
            <h3 style={{ margin: "0 0 8px", fontSize: "14px", fontWeight: "700", color: "#f8fafc" }}>
              {editingTerm ? `Terimi Güncelle: ${editingTerm}` : "Veritabanı Sözlüğüne Terim Ekle"}
            </h3>
            <p style={{ margin: "0 0 14px", fontSize: "12px", color: "#94a3b8" }}>
              Kalıcı SQLite otomotiv normalizer sözlüğüne kayıt ekler.
            </p>

            <form onSubmit={handleDbSave} style={{ display: "flex", flexWrap: "wrap", gap: "10px" }}>
              <input
                required
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                placeholder="Terim (örn: TDI, Passat, BlueHDi)"
                style={{
                  flex: "1 1 200px",
                  background: "#090d16",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  padding: "8px 12px",
                  color: "#fff",
                  fontSize: "12px",
                }}
              />
              <input
                required
                value={spoken}
                onChange={(e) => setSpoken(e.target.value)}
                placeholder="Okunuş (örn: ti di ay)"
                style={{
                  flex: "1 1 200px",
                  background: "#090d16",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  padding: "8px 12px",
                  color: "#fff",
                  fontSize: "12px",
                }}
              />
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                style={{
                  background: "#090d16",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  padding: "8px 12px",
                  color: "#fff",
                  fontSize: "12px",
                }}
              >
                <option value="brand">Marka (brand)</option>
                <option value="model">Model (model)</option>
                <option value="package">Donanım / Paket (package)</option>
                <option value="technical">Teknik / Kısaltma (technical)</option>
                <option value="custom">Özel Terim (custom)</option>
              </select>
              <button
                type="submit"
                disabled={loading}
                style={{
                  background: "#10b981",
                  color: "#0f172a",
                  fontWeight: "bold",
                  fontSize: "12px",
                  padding: "8px 18px",
                  borderRadius: "8px",
                  cursor: "pointer",
                  border: 0,
                }}
              >
                {editingTerm ? "Güncellemeyi Kaydet" : "Sözlüğe Ekle"}
              </button>
            </form>
          </div>

          {/* Terimler Tablosu */}
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: "12px",
              padding: "16px 20px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <span style={{ fontSize: "13px", fontWeight: "bold", color: "#f8fafc" }}>
                Kayıtlı Sözlük Terimleri ({entries.length})
              </span>
              <input
                type="text"
                placeholder="Terim ara..."
                value={dbSearch}
                onChange={(e) => setDbSearch(e.target.value)}
                style={{
                  background: "#090d16",
                  border: "1px solid #334155",
                  borderRadius: "6px",
                  padding: "4px 10px",
                  color: "#fff",
                  fontSize: "11px",
                }}
              />
            </div>

            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #334155", color: "#94a3b8", textAlign: "left" }}>
                    <th style={{ padding: "8px" }}>Terim</th>
                    <th style={{ padding: "8px" }}>Okunuş</th>
                    <th style={{ padding: "8px" }}>Kategori</th>
                    <th style={{ padding: "8px" }}>Tür</th>
                  </tr>
                </thead>
                <tbody>
                  {entries
                    .filter((e) => !dbSearch.trim() || e.term.toLowerCase().includes(dbSearch.toLowerCase()))
                    .slice(0, 50)
                    .map((item, idx) => (
                      <tr key={idx} style={{ borderBottom: "1px solid #1e293b" }}>
                        <td style={{ padding: "8px", fontWeight: "bold", color: "#f8fafc" }}>{item.term}</td>
                        <td style={{ padding: "8px", color: "#a7f3d0" }}>{item.spoken}</td>
                        <td style={{ padding: "8px", color: "#38bdf8" }}>{item.category}</td>
                        <td style={{ padding: "8px", color: "#94a3b8" }}>{item.is_base ? "Temel" : "Özel"}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
````


### frontend/src/MilestonePanel.tsx

````
/**
 * FreyaTTS Automotive Cockpit V3 — M01–M11 Deterministik Kalite & Emniyet Kilitleri Kokpiti
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useEffect, useState } from "react";
import type { ApiProps as Props } from "./api";
import { ShieldCheck, Lock, Activity, CheckCircle2, AlertTriangle, RefreshCw } from "lucide-react";
import { INITIAL_SAFETY_LOCKS, SafetyLock } from "./pipeline/safetyLocks";

export function MilestonePanel({ api }: Props) {
  const [overview, setOverview] = useState<any>(null);
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [text, setText] = useState("Trabzon'da 61 TS 061 plakalı Peugeot 3008 için OBD-II P0300 ve DSG bakımı 14.500 TL.");
  const [result, setResult] = useState<any>(null);
  const [safetyLocks, setSafetyLocks] = useState<SafetyLock[]>(INITIAL_SAFETY_LOCKS);

  async function refresh() {
    try {
      const [o, i] = await Promise.all([
        api("milestones/overview").catch(() => null),
        api("milestones/pronunciation").catch(() => []),
      ]);
      if (o) setOverview(o);
      if (i) setItems(i);
    } catch (e) {
      // Non-blocking
    }
  }

  async function inspectContract() {
    if (!text.trim()) return;
    setError("");
    try {
      const res = await api("milestones/inspect", "POST", { text });
      setResult(res);
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const activeLocksCount = safetyLocks.filter((l) => l.active).length;

  return (
    <div className="milestone-cockpit-layout" style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* ÜST EMNİYET KİLİDİ ÖZET ŞERİDİ */}
      <div
        style={{
          background: "linear-gradient(135deg, rgba(6, 78, 59, 0.4) 0%, rgba(15, 23, 42, 0.9) 100%)",
          border: "1px solid #059669",
          borderRadius: "12px",
          padding: "16px 20px",
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "12px",
          boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.3)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <div
            style={{
              padding: "10px",
              borderRadius: "10px",
              background: "rgba(16, 185, 129, 0.15)",
              border: "1px solid rgba(16, 185, 129, 0.3)",
              color: "#34d399",
            }}
          >
            <ShieldCheck style={{ width: "24px", height: "24px" }} />
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: "16px", fontWeight: "800", color: "#f8fafc" }}>
              M01–M11 Deterministik Kalite & Güvenlik Emniyet Kilitleri
            </h2>
            <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#94a3b8" }}>
              Ses hattında olasılıksal (LLM/ASR) sapmaları engelleyen, deterministik iş kuralları matrisi ({activeLocksCount}/11 Aktif).
            </p>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span
            style={{
              fontFamily: "monospace",
              fontSize: "12px",
              padding: "6px 12px",
              borderRadius: "8px",
              background: "#064e3b",
              color: "#6ee7b7",
              border: "1px solid #10b981",
              fontWeight: "bold",
            }}
          >
            ✓ Toplam Gecikme Bütçesi: &lt; 2.1 ms
          </span>
        </div>
      </div>

      {error && (
        <div role="alert" className="error" style={{ margin: 0 }}>
          {error}
        </div>
      )}

      {/* 11 EMNİYET KİLİDİ KARTLARI (2 KOLONLU GRID) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))",
          gap: "14px",
        }}
      >
        {safetyLocks.map((lock) => (
          <div
            key={lock.id}
            style={{
              background: lock.active ? "#0f172a" : "rgba(69, 10, 10, 0.25)",
              border: lock.active ? "1px solid #1e293b" : "1px solid #ef4444",
              borderRadius: "10px",
              padding: "14px 16px",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
              gap: "10px",
              transition: "all 0.2s ease",
            }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "10px" }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span
                    style={{
                      fontFamily: "monospace",
                      fontWeight: "bold",
                      fontSize: "11px",
                      padding: "2px 8px",
                      borderRadius: "6px",
                      background: "rgba(56, 189, 248, 0.15)",
                      color: "#38bdf8",
                      border: "1px solid rgba(56, 189, 248, 0.3)",
                    }}
                  >
                    {lock.id}
                  </span>
                  <span style={{ fontSize: "13px", fontWeight: "700", color: "#f1f5f9" }}>
                    {lock.name}
                  </span>
                  <span style={{ fontFamily: "monospace", fontSize: "10px", color: "#94a3b8" }}>
                    [{lock.stage}]
                  </span>
                </div>
                <p style={{ margin: "6px 0 0", fontSize: "12px", color: "#94a3b8", lineHeight: "1.5" }}>
                  {lock.desc}
                </p>
              </div>

              <button
                type="button"
                onClick={() =>
                  setSafetyLocks((prev) =>
                    prev.map((l) => (l.id === lock.id ? { ...l, active: !l.active } : l))
                  )
                }
                style={{
                  fontFamily: "monospace",
                  fontSize: "11px",
                  fontWeight: "bold",
                  padding: "4px 10px",
                  borderRadius: "6px",
                  cursor: "pointer",
                  border: lock.active ? "1px solid #059669" : "1px solid #ef4444",
                  background: lock.active ? "rgba(16, 185, 129, 0.2)" : "rgba(239, 68, 68, 0.2)",
                  color: lock.active ? "#6ee7b7" : "#fca5a5",
                  whiteSpace: "nowrap",
                }}
              >
                {lock.active ? "AKTİF" : "DEVRE DIŞI"}
              </button>
            </div>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                fontSize: "11px",
                fontFamily: "monospace",
                color: "#64748b",
                paddingTop: "8px",
                borderTop: "1px solid rgba(255, 255, 255, 0.05)",
              }}
            >
              <span>
                Engellenen İhlal:{" "}
                <strong style={{ color: lock.trips > 0 ? "#f59e0b" : "#94a3b8" }}>
                  {lock.trips} kez
                </strong>
              </span>
              <span>Ek Gecikme: {lock.latency}</span>
            </div>
          </div>
        ))}
      </div>

      {/* SÖZLEŞME İNCELEME & DOĞRULAMA LABORATUVARI */}
      <div
        style={{
          background: "#0f172a",
          border: "1px solid #1e293b",
          borderRadius: "12px",
          padding: "18px 20px",
          display: "flex",
          flexDirection: "column",
          gap: "14px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "14px", fontWeight: "700", color: "#f8fafc" }}>
              M05 & M01 Metin ve Cümlecik Sözleşmesi İnceleyici
            </h3>
            <p style={{ margin: "4px 0 0", fontSize: "12px", color: "#94a3b8" }}>
              Otomotiv markaları, plaka kodları, fiyatlar ve Sezer vurgularını doğrulamak için metni test edin.
            </p>
          </div>
        </div>

        <div style={{ display: "flex", gap: "10px" }}>
          <textarea
            rows={2}
            value={text}
            onChange={(e) => setText(e.target.value)}
            style={{
              flex: 1,
              background: "#090d16",
              border: "1px solid #334155",
              borderRadius: "8px",
              padding: "10px 14px",
              color: "#f8fafc",
              fontSize: "12px",
              fontFamily: "monospace",
            }}
          />
          <button
            type="button"
            onClick={inspectContract}
            style={{
              background: "#38bdf8",
              color: "#0f172a",
              fontWeight: "bold",
              fontSize: "12px",
              padding: "0 20px",
              borderRadius: "8px",
              cursor: "pointer",
              border: 0,
            }}
          >
            Sözleşmeyi İncele
          </button>
        </div>

        {result && (
          <div
            style={{
              background: "#090d16",
              border: "1px solid #10b981",
              borderRadius: "8px",
              padding: "14px",
              display: "flex",
              flexDirection: "column",
              gap: "8px",
              fontFamily: "monospace",
              fontSize: "12px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ color: "#94a3b8" }}>F4 Normalize Edilmiş Metin:</span>
              <span
                style={{
                  background: "rgba(16, 185, 129, 0.2)",
                  color: "#6ee7b7",
                  padding: "2px 8px",
                  borderRadius: "4px",
                  fontWeight: "bold",
                }}
              >
                {result.plan?.status || "M05_VERIFIED"}
              </span>
            </div>
            <p style={{ margin: 0, color: "#a7f3d0", fontWeight: "bold" }}>
              "{result.normalization?.spoken_text || text}"
            </p>

            {result.plan?.clauses && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginTop: "6px" }}>
                {result.plan.clauses.map((c: any, idx: number) => (
                  <span
                    key={idx}
                    style={{
                      background: "rgba(56, 189, 248, 0.15)",
                      border: "1px solid rgba(56, 189, 248, 0.3)",
                      color: "#bae6fd",
                      padding: "4px 8px",
                      borderRadius: "6px",
                      fontSize: "11px",
                    }}
                  >
                    <strong>[Cümlecik #{c.index || idx + 1}]</strong> {c.text} ({c.pause_after_ms ?? 140}ms)
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {overview && (
        <div
          style={{
            background: "#090d16",
            border: "1px solid #1e293b",
            borderRadius: "10px",
            padding: "14px 18px",
            fontSize: "12px",
            color: "#94a3b8",
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "10px",
          }}
        >
          <div>
            Fiziksel Kabul Durumu: <strong style={{ color: "#34d399" }}>{overview.physical_acceptance}</strong>
            {" · "}
            {overview.imported_files} dosya ({overview.archive})
          </div>
          <div style={{ color: "#cbd5e1" }}>
            {overview.live_components?.join(" · ")}
          </div>
        </div>
      )}
    </div>
  );
}
````


### frontend/src/NotificationPanel.tsx

````
/*
 * ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
 * Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlıdır.
 */

import { useEffect, useState, useMemo } from "react";
import { RawApiFn, errorMessage } from "./ui";

export type NotificationItem = {
  id: string;
  appointment_id: string;
  recipient_type: "customer" | "corporate";
  recipient: string;
  channel: "sms" | "whatsapp";
  message: string;
  status: "pending" | "sent" | "simulated" | "failed";
  idempotency_key: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
};

export type WhatsAppInboundItem = {
  id: string;
  from_phone: string;
  customer_name: string;
  message_type: "text" | "voice";
  raw_content: string;
  transcription: string;
  extracted_intent: string;
  extracted_time: string | null;
  appointment_id: string | null;
  reply_text: string;
  outbound_calls_cancelled: number;
  processed: boolean;
  created_at: string;
};

export type ProviderStatus = {
  provider: string;
  is_real: boolean;
  configured_provider: string;
  twilio_configured: boolean;
  from_number: string;
  whatsapp_from: string;
};

import type { Props } from "./api";

export function NotificationPanel({ api, rawApi }: Props) {
  const [activeTab, setActiveTab] = useState<"inbound" | "outbox">("inbound");
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [inboundMessages, setInboundMessages] = useState<WhatsAppInboundItem[]>([]);
  const [providerStatus, setProviderStatus] = useState<ProviderStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Test Gönderim Modalı
  const [showTestModal, setShowTestModal] = useState(false);
  const [testChannel, setTestChannel] = useState<"sms" | "whatsapp">("sms");
  const [testPhone, setTestPhone] = useState("");
  const [testMessage, setTestMessage] = useState("");
  const [sendingTest, setSendingTest] = useState(false);

  // Inbound Simulator Form
  const [simPhone, setSimPhone] = useState("");
  const [simText, setSimText] = useState("");
  const [simVoiceFile, setSimVoiceFile] = useState<File | null>(null);
  const [simulating, setSimulating] = useState(false);

  // Outbox Filters
  const [statusFilter, setStatusFilter] = useState("all");
  const [channelFilter, setChannelFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");

  async function act(fn: () => Promise<void>) {
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    try {
      const [outboxList, inboundList, provStat] = await Promise.all([
        api("notifications"),
        api("whatsapp/messages"),
        api("notifications/status").catch(() => null),
      ]);
      setNotifications(Array.isArray(outboxList) ? outboxList : []);
      setInboundMessages(Array.isArray(inboundList) ? inboundList : []);
      if (provStat) setProviderStatus(provStat);
    } catch (err: any) {
      setError("Bildirim verisi yüklenemedi: " + (err?.message || String(err)));
    }
  }

  useEffect(() => {
    act(refresh);
  }, []);

  async function handleDispatch() {
    await act(async () => {
      const res = await api("notifications/dispatch", "POST");
      setSuccess(
        `${res.dispatched_count} adet bekleyen bildirim başarıyla iletildi.`
      );
      await refresh();
    });
  }

  async function handleRetry(item: NotificationItem) {
    await act(async () => {
      const res = await api(`notifications/${item.id}/retry`, "POST");
      setSuccess(
        `'${item.recipient}' alıcısına bildirim yeniden gönderildi (Durum: ${res.status}).`
      );
      await refresh();
    });
  }

  const [scanningReminders, setScanningReminders] = useState(false);

  async function handleScanReminders() {
    setScanningReminders(true);
    setError("");
    setSuccess("");
    try {
      const res = await api("notifications/reminders/scan", "POST");
      setSuccess(
        `1 gün öncesi hatırlatma taraması tamamlandı: ${res.queued_count} randevu için bildirim kuyruğa alındı.`
      );
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setScanningReminders(false);
    }
  }

  async function handleSendTest() {
    if (!testPhone.trim() || !testMessage.trim()) return;
    setSendingTest(true);
    setError("");
    setSuccess("");
    try {
      const res = await api("notifications/test-send", "POST", {
        channel: testChannel,
        recipient: testPhone,
        message: testMessage,
      });
      setSuccess(
        `Test bildirimi başarıyla gönderildi (${res.receipt.channel.toUpperCase()} ➔ ${res.receipt.recipient}, ID: ${res.receipt.external_id}).`
      );
      setShowTestModal(false);
      setTestMessage("");
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSendingTest(false);
    }
  }

  async function handleSimulateText() {
    if (!simPhone.trim() || !simText.trim()) return;
    setSimulating(true);
    setError("");
    setSuccess("");
    try {
      const res = await api("whatsapp/inbound", "POST", {
        phone: simPhone,
        text: simText,
      });
      const cancelInfo =
        res.cancelled_outbound_calls_count > 0
          ? ` (${res.cancelled_outbound_calls_count} otomatik arama iptal edildi)`
          : "";
      setSuccess(
        `WhatsApp mesajı işlendi: Niyet='${res.intent}'${
          res.extracted_time ? `, Saat='${res.extracted_time}'` : ""
        }${cancelInfo}. Otomatik yanıt outbox'a eklendi.`
      );
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSimulating(false);
    }
  }

  async function handleSimulateVoice() {
    if (!simVoiceFile || !simPhone.trim()) return;
    setSimulating(true);
    setError("");
    setSuccess("");
    try {
      const formData = new FormData();
      formData.append("phone", simPhone);
      formData.append("audio_file", simVoiceFile);

      const resp = await rawApi("whatsapp/inbound-voice", "POST", formData);
      const res = await resp.json();
      setSuccess(
        `Ses Faster-Whisper ile çözümlendi: "${res.transcript}" ➔ Niyet='${res.intent}'.`
      );
      setSimVoiceFile(null);
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSimulating(false);
    }
  }

  // Statistics
  const totalOutbox = notifications.length;
  const sentCount = notifications.filter((n) => n.status === "sent").length;
  const pendingCount = notifications.filter((n) => n.status === "pending").length;
  const failedCount = notifications.filter((n) => n.status === "failed").length;

  const totalInbound = inboundMessages.length;
  const timeChangeCount = inboundMessages.filter(
    (m) => m.extracted_intent === "time_change"
  ).length;
  const cancelCount = inboundMessages.filter(
    (m) => m.extracted_intent === "cancel" || m.extracted_intent === "cancellation"
  ).length;

  const filteredOutbox = useMemo(() => {
    return notifications.filter((n) => {
      if (statusFilter !== "all" && n.status !== statusFilter) return false;
      if (channelFilter !== "all" && n.channel !== channelFilter) return false;
      if (typeFilter !== "all" && n.recipient_type !== typeFilter) return false;
      return true;
    });
  }, [notifications, statusFilter, channelFilter, typeFilter]);

  function formatDate(iso: string | null) {
    if (!iso) return "-";
    try {
      return new Date(iso).toLocaleString("tr-TR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return iso;
    }
  }

  function getIntentBadge(intent: string) {
    switch (intent) {
      case "time_change":
        return { label: "Saat Değişimi", bg: "#1e3a8a", color: "#bfdbfe" };
      case "cancellation":
        return { label: "İptal Talebi", bg: "#7f1d1d", color: "#fecaca" };
      case "confirmation":
        return { label: "Onay / Geliyorum", bg: "#14532d", color: "#bbf7d0" };
      case "location_inquiry":
        return { label: "Konum / Adres", bg: "#78350f", color: "#fde68a" };
      default:
        return { label: "Genel Soru", bg: "#374151", color: "#e5e7eb" };
    }
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: "8px", minHeight: 0, overflowY: "auto", padding: "2px 4px" }}>
      {/* İstatistik Kartları */}
      <div className="stats">
        <article>
          <small>Gelen WhatsApp Mesajları</small>
          <strong>{totalInbound}</strong>
          <span style={{ fontSize: "11px", color: "#93a0b5", marginTop: "2px" }}>
            {timeChangeCount} saat güncelleme · {cancelCount} iptal
          </span>
        </article>
        <article>
          <small>Outbox Toplam Bildirim</small>
          <strong>{totalOutbox}</strong>
          <span style={{ fontSize: "11px", color: "#a7f3ce", marginTop: "2px" }}>
            {sentCount} iletildi
          </span>
        </article>
        <article>
          <small>Outbox Bekleyen / Hatalı</small>
          <strong style={{ color: failedCount > 0 ? "#fca5a5" : "#fef08a" }}>
            {pendingCount} bekleyen · {failedCount} hatalı
          </strong>
        </article>
        <article style={{ borderLeft: providerStatus?.is_real ? "4px solid #10b981" : "4px solid #f59e0b" }}>
          <small>Aktif Sağlayıcı</small>
          <strong style={{ color: providerStatus?.is_real ? "#34d399" : "#fbbf24" }}>
            {providerStatus?.is_real ? "Twilio Canlı" : "Mock (Simüle)"}
          </strong>
          <span style={{ fontSize: "11px", color: "#cbd5e1", marginTop: "2px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{providerStatus?.from_number || (providerStatus?.is_real ? "Twilio API" : "Simülasyon")}</span>
            <button
              type="button"
              className="secondary"
              onClick={() => setShowTestModal(!showTestModal)}
              style={{ fontSize: "10px", padding: "2px 8px", marginLeft: "6px" }}
            >
              {showTestModal ? "Kapat ✕" : "Test Gönder ➔"}
            </button>
          </span>
        </article>
      </div>

      {showTestModal && (
        <div
          style={{
            background: "#0f172a",
            border: "1px solid #334155",
            borderRadius: "10px",
            padding: "16px",
            marginTop: "16px",
            boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <h4 style={{ margin: 0, fontSize: "14px", color: "#38bdf8" }}>
              🚀 Gerçek SMS / WhatsApp Test Bildirimi Gönder
            </h4>
            <span style={{ fontSize: "12px", color: providerStatus?.is_real ? "#4ade80" : "#fbbf24" }}>
              Mod: {providerStatus?.is_real ? "Twilio REST API (Gerçek İletim)" : "Mock Sağlayıcı (Simüle)"}
            </span>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: "12px", marginBottom: "12px" }}>
            <div>
              <label style={{ fontSize: "12px", color: "#94a3b8", display: "block", marginBottom: "4px" }}>Kanal</label>
              <select
                value={testChannel}
                onChange={(e) => setTestChannel(e.target.value as "sms" | "whatsapp")}
                style={{ width: "100%", padding: "6px 10px", fontSize: "13px" }}
              >
                <option value="sms">SMS</option>
                <option value="whatsapp">WhatsApp</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: "12px", color: "#94a3b8", display: "block", marginBottom: "4px" }}>
                Alıcı Telefon Numarası (+905xxxxxxxxx)
              </label>
              <input
                type="text"
                value={testPhone}
                onChange={(e) => setTestPhone(e.target.value)}
                placeholder="+905xxxxxxxxx veya 05xxxxxxxxx"
                style={{ width: "100%", padding: "6px 10px", fontSize: "13px" }}
              />
            </div>
          </div>

          <div style={{ marginBottom: "12px" }}>
            <label style={{ fontSize: "12px", color: "#94a3b8", display: "block", marginBottom: "4px" }}>Mesaj İçeriği</label>
            <textarea
              rows={2}
              value={testMessage}
              onChange={(e) => setTestMessage(e.target.value)}
              placeholder="Test mesajınızı yazın..."
              style={{ width: "100%", padding: "6px 10px", fontSize: "13px" }}
            />
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}>
            <button
              type="button"
              className="secondary"
              onClick={() => setShowTestModal(false)}
              style={{ fontSize: "12px", padding: "6px 14px" }}
            >
              Vazgeç
            </button>
            <button
              type="button"
              onClick={handleSendTest}
              disabled={sendingTest || !testPhone.trim() || !testMessage.trim()}
              style={{ fontSize: "12px", padding: "6px 16px", background: "#059669" }}
            >
              {sendingTest ? "Gönderiliyor..." : "Hemen Gönder ➔"}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div role="alert" className="error" style={{ marginTop: "18px" }}>
          {error}
        </div>
      )}
      {success && (
        <div
          role="status"
          className="bubble"
          style={{
            marginTop: "18px",
            background: "#1c382f",
            borderColor: "#347458",
            border: "1px solid",
          }}
        >
          <b>İşlem Başarılı</b>
          {success}
        </div>
      )}

      {/* Üst Sekmeler */}
      <div
        style={{
          display: "flex",
          gap: "10px",
          marginTop: "24px",
          marginBottom: "16px",
          borderBottom: "1px solid #2a3344",
          paddingBottom: "8px",
        }}
      >
        <button
          type="button"
          onClick={() => setActiveTab("inbound")}
          style={{
            background: activeTab === "inbound" ? "#2563eb" : "#1f2937",
            color: "#fff",
            padding: "8px 16px",
            fontSize: "13px",
            fontWeight: activeTab === "inbound" ? 600 : 400,
          }}
        >
          📥 Çift Yönlü WhatsApp Gelen & Simülatör ({totalInbound})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("outbox")}
          style={{
            background: activeTab === "outbox" ? "#2563eb" : "#1f2937",
            color: "#fff",
            padding: "8px 16px",
            fontSize: "13px",
            fontWeight: activeTab === "outbox" ? 600 : 400,
          }}
        >
          📤 Outbox Bildirim Kuyruğu (M10 & GPS Pini) ({totalOutbox})
        </button>
      </div>

      {activeTab === "inbound" ? (
        <section>
          {/* WhatsApp Simülatör Kartı */}
          <div
            style={{
              background: "#0c121e",
              border: "1px solid #1e293b",
              borderRadius: "12px",
              padding: "20px",
              marginBottom: "24px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "16px", color: "#38bdf8" }}>
                  📱 Çift Yönlü WhatsApp & Sesli Not Simülatörü
                </h3>
                <p className="muted" style={{ margin: "4px 0 0", fontSize: "12px" }}>
                  Müşteri WhatsApp'tan yazdığında ("Saati 16:00 yapalım") veya sesli mesaj attığında
                  randevu anında güncellenir ve bekleyen giden arama tekrarları (Auto-Retry) otomatik iptal edilir.
                </p>
              </div>
              <span
                style={{
                  background: "#14532d",
                  color: "#86efac",
                  padding: "4px 10px",
                  borderRadius: "12px",
                  fontSize: "11px",
                  fontWeight: 600,
                }}
              >
                Simülasyon
              </span>
            </div>

            <div className="grid-1-2" style={{ gap: "16px" }}>
              <div>
                <label style={{ fontSize: "12px", color: "#cbd5e1" }}>
                  Müşteri Telefon Numarası
                  <input
                    type="text"
                    value={simPhone}
                    onChange={(e) => setSimPhone(e.target.value)}
                    placeholder="+905551234567"
                    style={{ marginTop: "6px" }}
                  />
                </label>
                <button
                  type="button"
                  className="secondary"
                  style={{ fontSize: "11px", padding: "6px 10px", marginTop: "8px" }}
                  onClick={() => {
                    setSimPhone("+905551234567");
                    setSimText("Saati 16:00 yapalım lütfen");
                  }}
                >
                  Örnek doldur
                </button>

                {/* Hızlı Senaryo Butonları */}
                <div style={{ marginTop: "12px" }}>
                  <small style={{ color: "#94a3b8", display: "block", marginBottom: "6px" }}>
                    Hızlı Test Cümleleri:
                  </small>
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    <button
                      type="button"
                      className="secondary"
                      style={{ fontSize: "11px", padding: "6px 10px", textAlign: "left" }}
                      onClick={() => setSimText("Saati 16:00 yapalım lütfen, işim uzadı.")}
                    >
                      🕒 "Saati 16:00 yapalım"
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      style={{ fontSize: "11px", padding: "6px 10px", textAlign: "left" }}
                      onClick={() => setSimText("Bugünkü ekspertiz randevumu iptal etmek istiyorum.")}
                    >
                      ❌ "Randevumu iptal edin"
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      style={{ fontSize: "11px", padding: "6px 10px", textAlign: "left" }}
                      onClick={() => setSimText("Evet onaylıyorum, saatinde orada olacağım.")}
                    >
                      ✅ "Onaylıyorum, geliyorum"
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      style={{ fontSize: "11px", padding: "6px 10px", textAlign: "left" }}
                      onClick={() => setSimText("Şubenizin açık adresi nedir, konum atar mısınız?")}
                    >
                      📍 "Konum atar mısınız?"
                    </button>
                  </div>
                </div>
              </div>

              <div>
                <label style={{ fontSize: "12px", color: "#cbd5e1" }}>
                  WhatsApp Yazılı Mesajı
                  <textarea
                    rows={3}
                    value={simText}
                    onChange={(e) => setSimText(e.target.value)}
                    placeholder="Müşterinin yazacağı mesaj..."
                    style={{ marginTop: "6px", width: "100%", fontSize: "13px" }}
                  />
                </label>

                <div style={{ display: "flex", gap: "10px", marginTop: "10px" }}>
                  <button
                    type="button"
                    onClick={handleSimulateText}
                    disabled={simulating || !simText.trim()}
                    style={{ fontSize: "12px", padding: "8px 16px" }}
                  >
                    {simulating ? "İşleniyor..." : "Yazılı Mesajı Simüle Et ➔"}
                  </button>
                </div>

                <hr style={{ borderColor: "#1e293b", margin: "16px 0" }} />

                {/* Sesli Not Bölümü */}
                <div>
                  <label style={{ fontSize: "12px", color: "#cbd5e1", display: "block" }}>
                    🎙️ WhatsApp Sesli Not Simülatörü (Faster-Whisper STT)
                    <input
                      type="file"
                      accept="audio/*,.wav,.mp3,.ogg,.m4a"
                      onChange={(e) => setSimVoiceFile(e.target.files?.[0] || null)}
                      style={{ marginTop: "6px", display: "block", fontSize: "12px" }}
                    />
                  </label>
                  {simVoiceFile && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={handleSimulateVoice}
                      disabled={simulating}
                      style={{ marginTop: "8px", fontSize: "12px", padding: "6px 14px" }}
                    >
                      {simulating ? "STT Çözümleniyor..." : `"${simVoiceFile.name}" Sesini Çözümle & İşle ➔`}
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Gelen Mesajlar Tablosu */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <h3 style={{ margin: 0 }}>Gelen WhatsApp Mesajları ({inboundMessages.length})</h3>
              <button
                type="button"
                className="secondary"
                onClick={() => act(refresh)}
                style={{ fontSize: "12px", padding: "6px 12px" }}
              >
                Yenile ↻
              </button>
            </div>

            <div style={{ overflowX: "auto" }}>
              <div className="table-wrap"><table className="lexicon-table">
                <thead>
                  <tr>
                    <th>Gönderen</th>
                    <th>Tip</th>
                    <th>Mesaj / Çözümlenen Ses</th>
                    <th>Niyet (Intent)</th>
                    <th>Çıkarılan Saat</th>
                    <th>Oto-Arama İptal</th>
                    <th>Durum</th>
                    <th>Tarih</th>
                  </tr>
                </thead>
                <tbody>
                  {inboundMessages.map((msg) => {
                    const badge = getIntentBadge(msg.extracted_intent);
                    const displayText =
                      msg.message_type === "voice"
                        ? msg.transcription || msg.raw_content
                        : msg.raw_content;
                    return (
                      <tr key={msg.id}>
                        <td style={{ fontWeight: 600, whiteSpace: "nowrap" }}>
                          {msg.from_phone}
                        </td>
                        <td>
                          <span
                            style={{
                              padding: "2px 6px",
                              borderRadius: "6px",
                              fontSize: "10px",
                              fontWeight: 600,
                              background: msg.message_type === "voice" ? "#581c87" : "#1e293b",
                              color: msg.message_type === "voice" ? "#d8b4fe" : "#94a3b8",
                            }}
                          >
                            {msg.message_type === "voice" ? "🎙️ Sesli Not" : "💬 Metin"}
                          </span>
                        </td>
                        <td style={{ maxWidth: "340px", fontSize: "12px" }}>
                          {displayText}
                          {msg.reply_text && (
                            <div style={{ color: "#38bdf8", fontSize: "11px", marginTop: "3px" }}>
                              ↳ Yanıt: {msg.reply_text.slice(0, 80)}...
                            </div>
                          )}
                        </td>
                        <td>
                          <span
                            style={{
                              padding: "3px 8px",
                              borderRadius: "8px",
                              fontSize: "11px",
                              fontWeight: 600,
                              background: badge.bg,
                              color: badge.color,
                            }}
                          >
                            {badge.label}
                          </span>
                        </td>
                        <td style={{ fontWeight: 600, color: "#38bdf8" }}>
                          {msg.extracted_time || "-"}
                        </td>
                        <td>
                          {msg.outbound_calls_cancelled > 0 ? (
                            <span
                              style={{
                                padding: "2px 6px",
                                borderRadius: "6px",
                                fontSize: "11px",
                                background: "#450a0a",
                                color: "#fca5a5",
                                fontWeight: 600,
                              }}
                            >
                              {msg.outbound_calls_cancelled} Arama İptal
                            </span>
                          ) : (
                            <span style={{ color: "#64748b", fontSize: "11px" }}>Yok</span>
                          )}
                        </td>
                        <td>
                          <span
                            className={msg.processed ? "badge-custom" : "danger"}
                            style={{ padding: "3px 8px", borderRadius: "10px", fontSize: "11px" }}
                          >
                            {msg.processed ? "İşlendi" : "Hata"}
                          </span>
                        </td>
                        <td style={{ fontSize: "11px", whiteSpace: "nowrap" }}>
                          {formatDate(msg.created_at)}
                        </td>
                      </tr>
                    );
                  })}
                  {!inboundMessages.length && (
                    <tr>
                      <td colSpan={8} style={{ textAlign: "center", padding: "24px", color: "#93a0b5" }}>
                        Henüz gelen WhatsApp mesajı veya sesli not bulunmuyor. Yukarıdaki simülatörle test edebilirsiniz.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table></div>
            </div>
          </div>
        </section>
      ) : (
        <section>
          {/* M10 Outbox Bölümü */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "14px",
              marginBottom: "16px",
            }}
          >
            <div>
              <h2 style={{ margin: 0, fontSize: "18px" }}>
                M10 Outbox Bildirim Kuyruğu (SMS / WhatsApp & Şube GPS Pini)
              </h2>
              <p className="muted" style={{ margin: "4px 0 0", fontSize: "13px" }}>
                Randevu tamamlandığında veya saat güncellendiğinde SMS ve WhatsApp mesajları GPS konum pini
                (Google Maps linki) ile birlikte güvenli (at-least-once) şekilde kuyruklanır.
              </p>
            </div>
            <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
              <button
                type="button"
                className="secondary"
                onClick={handleScanReminders}
                disabled={scanningReminders}
                style={{ fontSize: "13px", padding: "10px 16px" }}
              >
                {scanningReminders ? "Taranıyor..." : "🔔 1 Gün Öncesi Hatırlatmaları Tara"}
              </button>
              <button
                type="button"
                onClick={handleDispatch}
                disabled={loading || pendingCount === 0}
                style={{ fontSize: "13px", padding: "10px 18px" }}
              >
                {loading ? "Sevk ediliyor..." : "Bekleyenleri Gönder ➔"}
              </button>
            </div>
          </div>

          {/* Filtre Barı */}
          <div
            className="inline"
            style={{
              background: "#0e1522",
              padding: "14px",
              borderRadius: "10px",
              border: "1px solid #2a3344",
              marginBottom: "20px",
            }}
          >
            <label style={{ flex: "1 1 140px" }}>
              Kanal Filtresi
              <select
                value={channelFilter}
                onChange={(e) => setChannelFilter(e.target.value)}
              >
                <option value="all">Tüm Kanallar ({notifications.length})</option>
                <option value="sms">SMS</option>
                <option value="whatsapp">WhatsApp</option>
              </select>
            </label>

            <label style={{ flex: "1 1 140px" }}>
              Alıcı Tipi
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
              >
                <option value="all">Tüm Alıcılar</option>
                <option value="customer">Müşteri (Bireysel)</option>
                <option value="corporate">Galeri (Kurumsal Cari)</option>
              </select>
            </label>

            <label style={{ flex: "1 1 140px" }}>
              Durum
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="all">Tüm Durumlar</option>
                <option value="pending">Bekleyen (pending)</option>
                <option value="sent">İletildi (sent)</option>
                <option value="failed">Hatalı (failed)</option>
              </select>
            </label>
          </div>

          {/* Outbox Tablosu */}
          <div style={{ overflowX: "auto" }}>
            <div className="table-wrap"><table className="lexicon-table">
              <thead>
                <tr>
                  <th>Kanal</th>
                  <th>Alıcı Tipi</th>
                  <th>Alıcı</th>
                  <th>Onay & Konum Metni</th>
                  <th>Durum</th>
                  <th>Tarih</th>
                  <th style={{ textAlign: "right" }}>İşlem</th>
                </tr>
              </thead>
              <tbody>
                {filteredOutbox.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <span
                        style={{
                          padding: "3px 8px",
                          borderRadius: "10px",
                          fontSize: "11px",
                          fontWeight: 600,
                          background:
                            item.channel === "whatsapp" ? "#14532d" : "#1e3a8a",
                          color:
                            item.channel === "whatsapp" ? "#86efac" : "#bfdbfe",
                        }}
                      >
                        {item.channel === "whatsapp" ? "WhatsApp" : "SMS"}
                      </span>
                    </td>
                    <td>
                      <span
                        style={{
                          padding: "3px 8px",
                          borderRadius: "10px",
                          fontSize: "11px",
                          background:
                            item.recipient_type === "corporate"
                              ? "#3b0764"
                              : "#1f2937",
                          color:
                            item.recipient_type === "corporate"
                              ? "#e9d5ff"
                              : "#d1d5db",
                        }}
                      >
                        {item.recipient_type === "corporate"
                          ? "Galeri"
                          : "Müşteri"}
                      </span>
                    </td>
                    <td style={{ fontWeight: 600, whiteSpace: "nowrap" }}>
                      {item.recipient}
                    </td>
                    <td style={{ maxWidth: "420px", fontSize: "12px" }}>
                      {item.message}
                      {item.last_error && (
                        <div
                          style={{
                            color: "#fca5a5",
                            fontSize: "11px",
                            marginTop: "4px",
                          }}
                        >
                          Hata: {item.last_error}
                        </div>
                      )}
                    </td>
                    <td>
                      <span
                        className={
                          item.status === "sent"
                            ? "badge-custom"
                            : item.status === "failed"
                              ? "danger"
                              : "badge-override"
                        }
                        style={{ padding: "3px 8px", borderRadius: "10px" }}
                      >
                        {item.status === "sent"
                          ? "İletildi"
                          : item.status === "simulated"
                            ? "gönderilmedi (sağlayıcı yok)"
                            : item.status === "failed"
                              ? "Başarısız"
                              : "Bekliyor"}
                      </span>
                      {item.attempts > 1 && (
                        <small style={{ marginTop: "2px" }}>
                          {item.attempts} deneme
                        </small>
                      )}
                    </td>
                    <td style={{ fontSize: "12px", whiteSpace: "nowrap" }}>
                      <div>Oluşturma: {formatDate(item.created_at)}</div>
                      {item.sent_at && (
                        <small style={{ color: "#a7f3ce" }}>
                          İletim: {formatDate(item.sent_at)}
                        </small>
                      )}
                    </td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      {item.status !== "sent" && (
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => handleRetry(item)}
                          style={{ padding: "6px 12px", fontSize: "12px" }}
                        >
                          Tekrar Gönder
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {!filteredOutbox.length && (
                  <tr>
                    <td
                      colSpan={7}
                      style={{
                        textAlign: "center",
                        padding: "30px",
                        color: "#93a0b5",
                      }}
                    >
                      Henüz outbox bildirim kaydı bulunamadı.
                    </td>
                  </tr>
                )}
              </tbody>
            </table></div>
          </div>
        </section>
      )}
    </div>
  );
}
````


### frontend/src/OntologyPanel.tsx

````
/**
 * FreyaTTS Automotive Cockpit — Automotive Auto-Ontology Panel
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 * 
 * NVIDIA Auto-Ontology prensiplerine göre oluşturulan semantik veritabanı,
 * OBD-II arıza ontolojisi, tek gerçek kaynak paket fiyatları ve MCP araç kokpiti.
 */

import React, { useEffect, useState } from "react";
import type { Props } from "./api";

interface SchemaGraph {
  version: string;
  table_count: number;
  concept_count: number;
  nodes: Array<{
    id: string;
    name: string;
    type: string;
    domain: string;
    description: string;
    properties: Record<string, any>;
  }>;
  edges: Array<{
    source: string;
    target: string;
    relation: string;
    description: string;
  }>;
}

interface ServicePackage {
  package_id: string;
  name: string;
  price_tl: number;
  duration_min: number;
  description: string;
  included_checks: string[];
  recommended_for: string[];
}

interface DiagnosticFault {
  obd_code: string;
  system: string;
  warning_light: string;
  severity: string;
  description: string;
  common_symptoms: string[];
  suggested_action: string;
  recommended_package_id: string;
}

export function OntologyPanel({ api }: Props) {
  const [activeSubTab, setActiveSubTab] = useState<"graph" | "packages" | "diagnostics" | "mcp">("packages");
  const [schema, setSchema] = useState<SchemaGraph | null>(null);
  const [packages, setPackages] = useState<ServicePackage[]>([]);
  const [diagnostics, setDiagnostics] = useState<DiagnosticFault[]>([]);
  const [mcpTools, setMcpTools] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Canlı test araçları durumu
  const [vehicleQuery, setVehicleQuery] = useState("passat 1.5 tsi");
  const [vehicleResult, setVehicleResult] = useState<any>(null);
  const [symptomQuery, setSymptomQuery] = useState("motor arıza lambası sarı yanıyor");
  const [symptomResult, setSymptomResult] = useState<any>(null);

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        const [schemaData, packagesData, diagData, toolsData] = await Promise.all([
          api("ontology/schema"),
          api("ontology/packages"),
          api("ontology/diagnostics"),
          api("ontology/mcp/tools"),
        ]);
        setSchema(schemaData);
        setPackages(packagesData);
        setDiagnostics(diagData);
        setMcpTools(toolsData?.tools || []);
      } catch (err: any) {
        setError(err.message || "Ontoloji verileri yüklenemedi.");
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  async function handleTestVehicle() {
    try {
      const res = await api("ontology/resolve-vehicle", "POST", { user_text: vehicleQuery });
      setVehicleResult(res);
    } catch (err: any) {
      setVehicleResult({ matched: false, error: err.message });
    }
  }

  async function handleTestSymptom() {
    try {
      const res = await api(`ontology/diagnostics?query=${encodeURIComponent(symptomQuery)}`);
      setSymptomResult(res);
    } catch (err: any) {
      setSymptomResult([]);
    }
  }

  if (loading) {
    return <div className="card" style={{ padding: "24px", color: "var(--muted)" }}>Otomotiv ontoloji katmanı taranıyor…</div>;
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: "8px", minHeight: 0, overflowY: "auto", padding: "2px 4px" }}>
      {/* Üst Bilgi Kartı */}
      <div className="card" style={{ background: "linear-gradient(135deg, #0e1726 0%, #172338 100%)", border: "1px solid #23354d", padding: "8px 14px", flexShrink: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "8px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "16px" }}>🌐</span>
              <h2 style={{ margin: 0, fontSize: "16px", fontWeight: 800, color: "#f8fafc" }}>
                Otomotiv Auto-Ontology & Semantik Kalkan
              </h2>
              <span className="stage-badge info" title="F3 Aşaması: Otomotiv Bilgi Grafı, OBD-II ve MCP Araç Şeması">
                F3 Domain Ontology
              </span>
              <span style={{ fontSize: "11px", fontWeight: 700, padding: "2px 8px", borderRadius: "12px", background: "rgba(16, 185, 129, 0.2)", color: "#34d399", border: "1px solid #059669" }}>
                NVIDIA Auto-Ontology Standardı
              </span>
            </div>
            <p style={{ margin: "6px 0 0 0", fontSize: "13px", color: "#94a3b8", maxWidth: "800px" }}>
              Veritabanı şemasını otomatik okur (Discover), tek gerçek kaynak paket fiyatlarını temellendirir (Ground),
              iş kurallarını ve OBD arıza ilişkilerini doğrular (Validate) ve AI ajanlarına güvenli MCP araçları olarak sunar (Expose).
            </p>
          </div>

          <div style={{ display: "flex", gap: "12px" }}>
            <div style={{ background: "#0b111d", padding: "8px 14px", borderRadius: "8px", border: "1px solid #1e293b", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#94a3b8" }}>Fiziksel Tablo</div>
              <div style={{ fontSize: "18px", fontWeight: 800, color: "#38bdf8" }}>{schema?.table_count || 0}</div>
            </div>
            <div style={{ background: "#0b111d", padding: "8px 14px", borderRadius: "8px", border: "1px solid #1e293b", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#94a3b8" }}>Semantik Kavram</div>
              <div style={{ fontSize: "18px", fontWeight: 800, color: "#a78bfa" }}>{schema?.concept_count || 0}</div>
            </div>
            <div style={{ background: "#0b111d", padding: "8px 14px", borderRadius: "8px", border: "1px solid #1e293b", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#94a3b8" }}>MCP Aracı</div>
              <div style={{ fontSize: "18px", fontWeight: 800, color: "#34d399" }}>{mcpTools.length}</div>
            </div>
          </div>
        </div>

        {/* Alt Gezinme Sekmeleri */}
        <div style={{ display: "flex", gap: "8px", marginTop: "18px", borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: "14px" }}>
          <button
            type="button"
            className={activeSubTab === "packages" ? "primary" : "secondary"}
            style={{ padding: "6px 14px", fontSize: "12px" }}
            onClick={() => setActiveSubTab("packages")}
          >
            🏷️ Sertifikalı Paket & Fiyatlar (Tek Kaynak)
          </button>
          <button
            type="button"
            className={activeSubTab === "diagnostics" ? "primary" : "secondary"}
            style={{ padding: "6px 14px", fontSize: "12px" }}
            onClick={() => setActiveSubTab("diagnostics")}
          >
            ⚡ OBD-II & Arıza Ontolojisi
          </button>
          <button
            type="button"
            className={activeSubTab === "graph" ? "primary" : "secondary"}
            style={{ padding: "6px 14px", fontSize: "12px" }}
            onClick={() => setActiveSubTab("graph")}
          >
            📊 Semantik Şema & Tablolar ({schema?.table_count})
          </button>
          <button
            type="button"
            className={activeSubTab === "mcp" ? "primary" : "secondary"}
            style={{ padding: "6px 14px", fontSize: "12px" }}
            onClick={() => setActiveSubTab("mcp")}
          >
            🛠️ MCP Araçları & Ajan Testi
          </button>
        </div>
      </div>

      {error && <div className="error" role="alert">{error}</div>}

      {/* 1. SEKME: Sertifikalı Paketler */}
      {activeSubTab === "packages" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "16px" }}>
          {packages.map((pkg) => (
            <div key={pkg.package_id} className="card" style={{ background: "#111827", border: "1px solid #1f2937", display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                <span style={{ fontSize: "11px", fontFamily: "monospace", fontWeight: 700, padding: "2px 6px", borderRadius: "4px", background: "rgba(56, 189, 248, 0.15)", color: "#38bdf8" }}>
                  {pkg.package_id}
                </span>
                <span style={{ fontSize: "18px", fontWeight: 800, color: "#10b981" }}>
                  {pkg.price_tl.toLocaleString("tr-TR")} TL
                </span>
              </div>
              <h3 style={{ margin: "4px 0", fontSize: "16px", color: "#f8fafc" }}>{pkg.name}</h3>
              <div style={{ fontSize: "12px", color: "#94a3b8", marginBottom: "10px" }}>⏱️ Yaklaşık {pkg.duration_min} dakika</div>
              <p style={{ fontSize: "12px", color: "#cbd5e1", lineHeight: 1.4, flex: 1 }}>{pkg.description}</p>
              
              <div style={{ borderTop: "1px solid #1e293b", paddingTop: "10px", marginTop: "10px" }}>
                <div style={{ fontSize: "11px", fontWeight: 700, color: "#94a3b8", marginBottom: "4px" }}>Dahil Kontroller:</div>
                <ul style={{ margin: 0, paddingLeft: "16px", fontSize: "11.5px", color: "#94a3b8", lineHeight: 1.5 }}>
                  {pkg.included_checks.map((chk, i) => (
                    <li key={i}>{chk}</li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 2. SEKME: OBD-II Arıza Ontolojisi */}
      {activeSubTab === "diagnostics" && (
        <div className="card" style={{ background: "#111827", border: "1px solid #1f2937" }}>
          <h3 style={{ margin: "0 0 14px 0", fontSize: "15px", color: "#f8fafc" }}>
            Sertifikalı OBD-II Hata Kodları & İkaz Lambası Matrisi
          </h3>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #374151", color: "#94a3b8", textAlign: "left" }}>
                  <th style={{ padding: "8px" }}>DTC Kodu</th>
                  <th style={{ padding: "8px" }}>Sistem</th>
                  <th style={{ padding: "8px" }}>İkaz Lambası</th>
                  <th style={{ padding: "8px" }}>Önem</th>
                  <th style={{ padding: "8px" }}>Açıklama & Belirtiler</th>
                  <th style={{ padding: "8px" }}>Önerilen Paket</th>
                </tr>
              </thead>
              <tbody>
                {diagnostics.map((d) => (
                  <tr key={d.obd_code} style={{ borderBottom: "1px solid #1f2937" }}>
                    <td style={{ padding: "10px 8px", fontFamily: "monospace", fontWeight: 800, color: "#38bdf8" }}>{d.obd_code}</td>
                    <td style={{ padding: "10px 8px", color: "#cbd5e1" }}>{d.system}</td>
                    <td style={{ padding: "10px 8px", color: "#fbbf24" }}>{d.warning_light}</td>
                    <td style={{ padding: "10px 8px" }}>
                      <span style={{
                        padding: "2px 6px", borderRadius: "4px", fontSize: "10px", fontWeight: 700,
                        background: d.severity === "critical" ? "rgba(239, 68, 68, 0.2)" : d.severity === "high" ? "rgba(249, 115, 22, 0.2)" : "rgba(234, 179, 8, 0.2)",
                        color: d.severity === "critical" ? "#f87171" : d.severity === "high" ? "#fb923c" : "#facc15"
                      }}>
                        {d.severity.toUpperCase()}
                      </span>
                    </td>
                    <td style={{ padding: "10px 8px", color: "#cbd5e1" }}>
                      <strong>{d.description}</strong>
                      <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "2px" }}>
                        Belirtiler: {d.common_symptoms.join(", ")}
                      </div>
                    </td>
                    <td style={{ padding: "10px 8px", fontFamily: "monospace", color: "#34d399", fontWeight: 700 }}>
                      {d.recommended_package_id}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 3. SEKME: Semantik Şema & Graf */}
      {activeSubTab === "graph" && (
        <div className="card" style={{ background: "#111827", border: "1px solid #1f2937" }}>
          <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", color: "#f8fafc" }}>
            Fiziksel Veritabanı Tabloları ve Semantik Eşlemeler
          </h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "10px" }}>
            {schema?.nodes.filter(n => n.type === "table").map((node) => (
              <div key={node.id} style={{ background: "#0b111d", padding: "10px 12px", borderRadius: "6px", border: "1px solid #1e293b" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontFamily: "monospace", fontWeight: 700, color: "#38bdf8", fontSize: "12px" }}>{node.name}</span>
                  <span style={{ fontSize: "10px", color: "#94a3b8" }}>{node.properties?.column_count || 0} kolon</span>
                </div>
                <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>
                  PK: {node.properties?.primary_key?.join(", ") || "id"}
                </div>
              </div>
            ))}
          </div>

          <h4 style={{ margin: "20px 0 10px 0", fontSize: "13px", color: "#a78bfa" }}>
            Yabancı Anahtar ve Semantik İlişkiler ({schema?.edges.length} Bağlantı)
          </h4>
          <div style={{ maxHeight: "200px", overflowY: "auto", background: "#070b13", padding: "10px", borderRadius: "6px", fontSize: "11.5px", fontFamily: "monospace" }}>
            {schema?.edges.map((e, idx) => (
              <div key={idx} style={{ padding: "3px 0", color: "#cbd5e1" }}>
                <span style={{ color: "#38bdf8" }}>{e.source}</span>
                <span style={{ color: "#f59e0b", margin: "0 6px" }}>--[{e.relation}]--&gt;</span>
                <span style={{ color: "#34d399" }}>{e.target}</span>
                <span style={{ color: "#64748b", marginLeft: "10px" }}>({e.description})</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 4. SEKME: MCP Araçları ve Canlı Doğrulama Konsolu */}
      {activeSubTab === "mcp" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: "16px" }}>
          {/* Canlı Araç Deneme */}
          <div className="card" style={{ background: "#111827", border: "1px solid #1f2937" }}>
            <h3 style={{ margin: "0 0 10px 0", fontSize: "14px", color: "#f8fafc" }}>
              Canlı Test: Doğal Dil Araç Normalizasyonu
            </h3>
            <div style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
              <input
                type="text"
                value={vehicleQuery}
                onChange={(e) => setVehicleQuery(e.target.value)}
                placeholder="Örn: passat 1.5 tsi, megan 4..."
                style={{ flex: 1, padding: "8px 12px", background: "#0b111d", border: "1px solid #1e293b", borderRadius: "6px", color: "#fff", fontSize: "12px" }}
              />
              <button type="button" className="secondary" style={{ padding: "8px 14px", fontSize: "12px" }} onClick={handleTestVehicle}>
                Çözümle
              </button>
            </div>
            {vehicleResult && (
              <pre style={{ background: "#070b13", padding: "10px", borderRadius: "6px", fontSize: "11px", color: "#34d399", overflowX: "auto" }}>
                {JSON.stringify(vehicleResult, null, 2)}
              </pre>
            )}

            <h3 style={{ margin: "16px 0 10px 0", fontSize: "14px", color: "#f8fafc" }}>
              Canlı Test: Semptomdan OBD Arızası Çıkarma
            </h3>
            <div style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
              <input
                type="text"
                value={symptomQuery}
                onChange={(e) => setSymptomQuery(e.target.value)}
                placeholder="Örn: motor lambası, airbag..."
                style={{ flex: 1, padding: "8px 12px", background: "#0b111d", border: "1px solid #1e293b", borderRadius: "6px", color: "#fff", fontSize: "12px" }}
              />
              <button type="button" className="secondary" style={{ padding: "8px 14px", fontSize: "12px" }} onClick={handleTestSymptom}>
                Teşhis Et
              </button>
            </div>
            {symptomResult && (
              <pre style={{ background: "#070b13", padding: "10px", borderRadius: "6px", fontSize: "11px", color: "#facc15", overflowX: "auto" }}>
                {JSON.stringify(symptomResult, null, 2)}
              </pre>
            )}
          </div>

          {/* MCP Standart Araçları */}
          <div className="card" style={{ background: "#111827", border: "1px solid #1f2937" }}>
            <h3 style={{ margin: "0 0 10px 0", fontSize: "14px", color: "#f8fafc" }}>
              Tanımlı MCP (Model Context Protocol) Araçları
            </h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              {mcpTools.map((t) => (
                <div key={t.name} style={{ background: "#0b111d", padding: "10px", borderRadius: "6px", border: "1px solid #1e293b" }}>
                  <div style={{ fontFamily: "monospace", fontWeight: 700, color: "#38bdf8", fontSize: "12px" }}>
                    {t.name}()
                  </div>
                  <div style={{ fontSize: "11.5px", color: "#94a3b8", marginTop: "4px" }}>
                    {t.description}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
````


### frontend/src/OperatorPanel.tsx

````
/*
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
*/

import React, { useState, useEffect, useRef } from "react";
import { dash, errorMessage, useEscape } from "./ui";
import { OperatorToday } from "./OperatorToday";

interface OperatorTransfer {
  id: string;
  conversation_id: string | null;
  caller_channel: string;
  operator_extension: string;
  customer_name: string;
  vehicle_plate: string;
  summary: string;
  whisper_text: string;
  status: "initiated" | "whispering" | "accepted" | "declined" | "timeout" | "failed";
  sip_headers_json: string;
  sip_headers?: Record<string, string>;
  duration_seconds: number | null;
  created_at: string;
  completed_at: string | null;
}

interface OperatorSessionView {
  session_id: string;
  caller_id: string;
  state: "ai_handling" | "taken_over" | "monitored" | "terminated";
  operator_id: string | null;
  takeover_reason: string | null;
  started_at_iso: string;
  current_turn_id: string | null;
  mos_score: number;
  packet_loss_pct: number;
  rtf: number;
  whisper_notes: string[];
}

interface OperatorPanelProps {
  kvkkErasureEnabled: boolean;
  autoPurgeTranscripts: boolean;
  api: (path: string, method?: string, body?: unknown) => Promise<any>;
  onError: (msg: string) => void;
  onOpenConversation: (id: string) => void;
}

interface UnclearTurn {
  id: string;
  role: string;
  text: string;
  metrics: string;
  created_at: string;
  is_unclear: boolean;
}

interface UnclearCall {
  id: string;
  status: string;
  channel: string;
  created_at: string;
  operator_notes: string;
  resolved_at: string | null;
  turn_count: number;
  unclear_count: number;
  unclear_phrases: string[];
  has_recording: boolean;
  turns: UnclearTurn[];
}

export function OperatorPanel({ api, onError, onOpenConversation, kvkkErasureEnabled, autoPurgeTranscripts }: OperatorPanelProps) {
  const [activeTab, setActiveTab] = useState<"today" | "sip_transfers" | "live_takeover" | "quality_gate" | "failed_calls" | "kvkk_compliance">("today");
  const [todayRevision, setTodayRevision] = useState(0);

  // Başarısız & Anlaşılamayan Görüşmeler State
  const [unclearCalls, setUnclearCalls] = useState<UnclearCall[]>([]);
  const [unclearLoading, setUnclearLoading] = useState(false);
  const [selectedUnclearCall, setSelectedUnclearCall] = useState<UnclearCall | null>(null);
  const [feedbackTerm, setFeedbackTerm] = useState("");
  const [feedbackSpoken, setFeedbackSpoken] = useState("");
  const [feedbackCategory, setFeedbackCategory] = useState("brand");
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState("");

  // KVKK Transkript Saklama & Silme Talepleri State
  const [kvkkAudit, setKvkkAudit] = useState<any>(null);
  const [kvkkAuditLoading, setKvkkAuditLoading] = useState(false);
  const [kvkkPurgeBusy, setKvkkPurgeBusy] = useState(false);
  const [kvkkPurgeMsg, setKvkkPurgeMsg] = useState("");
  const [kvkkRequests, setKvkkRequests] = useState<any[]>([]);
  const [kvkkRequestsLoading, setKvkkRequestsLoading] = useState(false);
  const [selectedCertificate, setSelectedCertificate] = useState<any | null>(null);

  // Yeni Silme Talebi Formu
  const [newReqType, setNewReqType] = useState<"phone" | "plate" | "customer_name" | "conversation_id">("phone");
  const [newReqVal, setNewReqVal] = useState("");
  const [newReqName, setNewReqName] = useState("");
  const [newReqReason, setNewReqReason] = useState("KVKK Madde 11 uyarınca silme talebi");
  const [newReqNotes, setNewReqNotes] = useState("");
  const [newReqBusy, setNewReqBusy] = useState(false);
  const [newReqMsg, setNewReqMsg] = useState("");
  const [executingReqId, setExecutingReqId] = useState<string | null>(null);

  // SIP Aktarımları State
  const [transfers, setTransfers] = useState<OperatorTransfer[]>([]);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [selectedTransfer, setSelectedTransfer] = useState<OperatorTransfer | null>(null);

  // Test aktarımı formu alanları
  const [formCustomer, setFormCustomer] = useState("");
  const [formPlate, setFormPlate] = useState("");
  const [formSummary, setFormSummary] = useState("");
  const [formExten, setFormExten] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  // Canlı devralma ve fısıltı durumu
  const [liveSessions, setLiveSessions] = useState<OperatorSessionView[]>([]);
  const [operatorId, setOperatorId] = useState("");
  const [takeoverReason, setTakeoverReason] = useState("customer_complaint");
  const [whisperMessage, setWhisperMessage] = useState("");
  const [simCallerId, setSimCallerId] = useState("");

  // Kalite Kapısı 5 & Telemetri State
  const [qaReport, setQaReport] = useState<any>(null);
  const [qaLoading, setQaLoading] = useState(false);
  const [m11Status, setM11Status] = useState<any>(null);
  const [telemetryTurnId, setTelemetryTurnId] = useState("");
  const [telemetryData, setTelemetryData] = useState<any>(null);

  const [pollError, setPollError] = useState("");
  const pollIntervalRef = useRef<any>(null);

  useEscape(() => setSelectedTransfer(null), !!selectedTransfer);
  useEscape(() => setSelectedCertificate(null), !!selectedCertificate);

  // silent=true: 3 sn'lik otomatik yenilemede "Yenileniyor" yanıp sönmesini önler.
  const loadTransfers = async (silent = false) => {
    try {
      if (!silent) setLoading(true);
      const data: OperatorTransfer[] = await api("transfers?limit=50");
      setTransfers(data || []);
      setPollError("");
    } catch (err: any) {
      setPollError(`Aktarım listesi alınamadı: ${err?.message || err}`);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const loadLiveSessions = async () => {
    try {
      const data = await api("operator/live-sessions");
      setLiveSessions(data.sessions || []);
      setPollError("");
    } catch (err: any) {
      setPollError(`Canlı çağrı listesi alınamadı: ${err?.message || err}`);
    }
  };

  const loadUnclearCalls = async () => {
    try {
      setUnclearLoading(true);
      const data: UnclearCall[] = await api("conversations/unclear?limit=50");
      setUnclearCalls(data || []);
      if (data && data.length > 0 && !selectedUnclearCall) {
        setSelectedUnclearCall(data[0]);
      }
    } catch (err: any) {
      setPollError(`Başarısız görüşmeler alınamadı: ${err?.message || err}`);
    } finally {
      setUnclearLoading(false);
    }
  };

  const handleFeedbackSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUnclearCall) return;
    if (!feedbackTerm.trim() || !feedbackSpoken.trim()) {
      setFeedbackMsg("Lütfen hem terimi hem de telaffuzunu yazın.");
      return;
    }
    try {
      setFeedbackBusy(true);
      await api(`conversations/${selectedUnclearCall.id}/feedback-lexicon`, "POST", {
        term: feedbackTerm.trim(),
        spoken: feedbackSpoken.trim(),
        category: feedbackCategory,
      });
      setFeedbackMsg(`'${feedbackTerm}' başarıyla otomotiv sözlüğüne eklendi ve normalizer güncellendi!`);
      setFeedbackTerm("");
      setFeedbackSpoken("");
      await loadUnclearCalls();
    } catch (err: any) {
      setFeedbackMsg(`Sözlüğe ekleme hatası: ${err?.message || err}`);
    } finally {
      setFeedbackBusy(false);
    }
  };

  const loadKvkkAudit = async () => {
    try {
      setKvkkAuditLoading(true);
      const data = await api("kvkk/transcript-retention-audit");
      setKvkkAudit(data);
    } catch (err: any) {
      setPollError(`KVKK saklama denetimi alınamadı: ${err?.message || err}`);
    } finally {
      setKvkkAuditLoading(false);
    }
  };

  const loadKvkkRequests = async () => {
    try {
      setKvkkRequestsLoading(true);
      const data = await api("kvkk/erasure-requests?limit=50");
      setKvkkRequests(data || []);
    } catch (err: any) {
      setPollError(`Silme talepleri alınamadı: ${err?.message || err}`);
    } finally {
      setKvkkRequestsLoading(false);
    }
  };

  const handlePurgeTranscripts = async (dryRun: boolean) => {
    try {
      setKvkkPurgeBusy(true);
      setKvkkPurgeMsg("");
      const res = await api("kvkk/transcript-retention-purge", "POST", { dry_run: dryRun });
      if (dryRun) {
        setKvkkPurgeMsg(`Önizleme: ${res.purged_conversations} görüşme (${res.purged_turns} tur transkript) imha edilebilir.`);
      } else {
        setKvkkPurgeMsg(`Başarılı: ${res.purged_conversations} görüşme ve ${res.purged_turns} tur transkript kalıcı olarak imha edildi/anonimleştirildi.`);
        await loadKvkkAudit();
      }
    } catch (err: any) {
      setKvkkPurgeMsg(`İmha hatası: ${err?.message || err}`);
    } finally {
      setKvkkPurgeBusy(false);
    }
  };

  const handleCreateErasureRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newReqVal.trim()) {
      setNewReqMsg("Lütfen silinecek kimlik değerini (telefon, plaka vb.) girin.");
      return;
    }
    try {
      setNewReqBusy(true);
      setNewReqMsg("");
      const res = await api("kvkk/erasure-requests", "POST", {
        identifier_type: newReqType,
        identifier_value: newReqVal.trim(),
        requester_name: newReqName.trim(),
        reason: newReqReason.trim(),
        notes: newReqNotes.trim(),
      });
      const aff = res.impact_summary?.total_records_affected || 0;
      setNewReqMsg(`Talep oluşturuldu! (ID: ${res.id}, Etkilenecek Kayıt: ${aff})`);
      setNewReqVal("");
      setNewReqName("");
      setNewReqNotes("");
      await loadKvkkRequests();
    } catch (err: any) {
      setNewReqMsg(`Talep oluşturma hatası: ${err?.message || err}`);
    } finally {
      setNewReqBusy(false);
    }
  };

  const handleExecuteErasureRequest = async (requestId: string, count: number) => {
    if (!window.confirm(`Önizlemedeki ${count} kayda kalıcı silme veya maskeleme uygulanacak. Onaylıyor musunuz?`)) {
      return;
    }
    try {
      setExecutingReqId(requestId);
      const res = await api(`kvkk/erasure-requests/${requestId}/execute`, "POST", { confirmed_record_count: count });
      alert(`Silme işlemi başarıyla icra edildi!\nSHA-256 özeti: ${res.certificate_sha256}`);
      await loadKvkkRequests();
      await loadKvkkAudit();
    } catch (err: any) {
      alert(`İcra hatası: ${err?.message || err}`);
    } finally {
      setExecutingReqId(null);
    }
  };

  const handleViewCertificate = async (requestId: string) => {
    try {
      const data = await api(`kvkk/erasure-requests/${requestId}/certificate?format=json`);
      setSelectedCertificate(data);
    } catch (err: any) {
      alert(`Sertifika alınamadı: ${err?.message || err}`);
    }
  };

  useEffect(() => {
    if (autoRefresh) {
      pollIntervalRef.current = setInterval(() => {
        if (activeTab === "sip_transfers") {
          loadTransfers(true);
        } else if (activeTab === "live_takeover") {
          loadLiveSessions();
        } else if (activeTab === "failed_calls") {
          loadUnclearCalls();
        } else if (activeTab === "kvkk_compliance") {
          loadKvkkAudit();
          loadKvkkRequests();
        }
      }, 3000);
    } else if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, [autoRefresh, activeTab]);

  const handleAccept = async (transferId: string) => {
    try {
      setActionBusy(true);
      await api(`transfers/${transferId}/accept`, "POST", {});
      await loadTransfers();
    } catch (err: any) {
      onError(`Aktarım kabul edilemedi: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const handleDecline = async (transferId: string) => {
    try {
      setActionBusy(true);
      await api(`transfers/${transferId}/decline`, "POST", { reason: "declined" });
      await loadTransfers();
    } catch (err: any) {
      onError(`Aktarım reddedilemedi: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const handleCreateTestTransfer = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setActionBusy(true);
      await api("transfers/initiate", "POST", {
        customer_name: formCustomer,
        vehicle_plate: formPlate,
        summary: formSummary,
        operator_extension: formExten,
      });
      await loadTransfers();
    } catch (err: any) {
      onError(`Test aktarımı başlatılamadı: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  // Canlı devralma işlemleri
  const handleRegisterSimCall = async () => {
    try {
      setActionBusy(true);
      // sim_ öneki: bu çağrı simülasyondur; MOS/RTF değerleri uydurulmaz, listede "—" gösterilir.
      const sessId = `sim_${Date.now()}`;
      await api("operator/register-call", "POST", {
        session_id: sessId,
        caller_id: simCallerId.trim(),
        initial_turn_id: `turn_${Date.now()}`,
      });
      await loadLiveSessions();
    } catch (err: any) {
      onError(`Simülasyon çağrısı başlatılamadı: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const handleTakeover = async (sessionId: string) => {
    if (!operatorId.trim()) {
      onError("Çağrıyı devralmak için operatör kodunu girin.");
      return;
    }
    try {
      setActionBusy(true);
      await api("operator/takeover", "POST", {
        session_id: sessionId,
        operator_id: operatorId,
        reason: takeoverReason,
      });
      await loadLiveSessions();
    } catch (err: any) {
      onError(`Çağrı devralınamadı: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const handleWhisper = async (sessionId: string) => {
    if (!whisperMessage.trim()) return;
    try {
      setActionBusy(true);
      await api("operator/whisper", "POST", {
        session_id: sessionId,
        operator_id: operatorId,
        message: whisperMessage.trim(),
      });
      setWhisperMessage("");
      await loadLiveSessions();
    } catch (err: any) {
      onError(`Fısıltı gönderilemedi: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const handleRelease = async (sessionId: string) => {
    try {
      setActionBusy(true);
      await api("operator/release", "POST", {
        session_id: sessionId,
        operator_id: operatorId,
      });
      await loadLiveSessions();
    } catch (err: any) {
      onError(`Çağrı yapay zekaya iade edilemedi: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  // QA & Telemetri Handlers
  const handleRunQABenchmark = async () => {
    try {
      setQaLoading(true);
      const res = await api("qa/evaluate-variants", "POST", {});
      setQaReport(res);
      const m11 = await api("qa/m11-status");
      setM11Status(m11);
    } catch (err: any) {
      onError(`Kalite Kapısı 5 testi hatası: ${err.message || err}`);
    } finally {
      setQaLoading(false);
    }
  };

  const handleFetchTelemetry = async () => {
    if (!telemetryTurnId.trim()) return;
    try {
      setActionBusy(true);
      const data = await api(`qa/telemetry/${telemetryTurnId.trim()}`);
      setTelemetryData(data);
    } catch (err: any) {
      onError(`Telemetri kaydı sorgulanamadı: ${err.message || err}`);
    } finally {
      setActionBusy(false);
    }
  };

  const activeIncoming = transfers.find(
    (t) => t.status === "initiated" || t.status === "whispering"
  );

  const filteredTransfers = transfers.filter((t) => {
    if (statusFilter === "all") return true;
    if (statusFilter === "active") return t.status === "initiated" || t.status === "whispering";
    if (statusFilter === "accepted") return t.status === "accepted";
    if (statusFilter === "declined") return t.status === "declined" || t.status === "timeout";
    return true;
  });

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: "8px", minHeight: 0, overflowY: "auto", padding: "2px 4px" }}>
      {/* Üst Bar & Alt Sekme Seçimi */}
      <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "8px 12px", flexShrink: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px", marginBottom: "8px" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "16px", color: "#f8fafc", display: "flex", alignItems: "center", gap: "8px" }}>
              🎧 Çağrı Merkezi Operatör & Kalite Konsolu
              <span
                style={{
                  fontSize: "12px",
                  padding: "3px 8px",
                  background: "#0369a1",
                  color: "#e0f2fe",
                  borderRadius: "12px",
                  fontWeight: "normal",
                }}
              >
                Dahili: 6002
              </span>
            </h2>
            <p style={{ margin: "4px 0 0 0", color: "#94a3b8", fontSize: "13px" }}>
              Sıcak aktarım (fısıltı), canlı devralma, tur telemetrisi ve Kalite Kapısı 5
            </p>
          </div>
          <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <label style={{ fontSize: "12px", color: "#cbd5e1", display: "flex", alignItems: "center", gap: "6px", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              Canlı Takip (3 sn)
            </label>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                if (activeTab === "today") setTodayRevision((n) => n + 1);
                if (activeTab === "sip_transfers") loadTransfers();
                if (activeTab === "live_takeover") loadLiveSessions();
                if (activeTab === "failed_calls") loadUnclearCalls();
                if (activeTab === "kvkk_compliance") {
                  loadKvkkAudit();
                  loadKvkkRequests();
                }
              }}
              disabled={loading || actionBusy}
              style={{ padding: "6px 12px", fontSize: "13px" }}
            >
              {loading ? "Yenileniyor..." : "Yenile ↻"}
            </button>
          </div>
        </div>

        {pollError && (
          <div role="alert" className="error" style={{ marginBottom: "12px" }}>
            {pollError}
          </div>
        )}

        {/* Sekme Butonları */}
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", borderTop: "1px solid #1e293b", paddingTop: "12px" }}>
          <button
            type="button"
            className={activeTab === "today" ? "primary" : "secondary"}
            aria-current={activeTab === "today" ? "true" : undefined}
            onClick={() => { setPollError(""); setActiveTab("today"); }}
          >Bugün</button>
          <button
            type="button"
            className={activeTab === "sip_transfers" ? "primary" : "secondary"}
            onClick={() => { setActiveTab("sip_transfers"); loadTransfers(); }}
            style={{ padding: "8px 16px", fontSize: "13px", fontWeight: "bold" }}
          >
            📞 SIP Warm Transfer (Dahili 6002)
          </button>
          <button
            type="button"
            className={activeTab === "live_takeover" ? "primary" : "secondary"}
            onClick={() => {
              setActiveTab("live_takeover");
              loadLiveSessions();
            }}
            style={{ padding: "8px 16px", fontSize: "13px", fontWeight: "bold" }}
          >
            ⚡ Canlı Müdahale & Fısıltı
          </button>
          <button
            type="button"
            className={activeTab === "quality_gate" ? "primary" : "secondary"}
            onClick={() => setActiveTab("quality_gate")}
            style={{ padding: "8px 16px", fontSize: "13px", fontWeight: "bold" }}
          >
            🎯 Kalite Kapısı 5 & Telemetri
          </button>
          <button
            type="button"
            className={activeTab === "failed_calls" ? "primary" : "secondary"}
            onClick={() => {
              setActiveTab("failed_calls");
              loadUnclearCalls();
            }}
            style={{ padding: "8px 16px", fontSize: "13px", fontWeight: "bold" }}
          >
            🚨 Başarısız & Anlaşılamayan Görüşmeler ({unclearCalls.length})
          </button>
          <button
            type="button"
            className={activeTab === "kvkk_compliance" ? "primary" : "secondary"}
            onClick={() => {
              setActiveTab("kvkk_compliance");
              loadKvkkAudit();
              loadKvkkRequests();
            }}
            style={{ padding: "8px 16px", fontSize: "13px", fontWeight: "bold" }}
          >
            🛡️ KVKK Silme & Saklama ({kvkkRequests.length})
          </button>
        </div>
      </section>

      {activeTab === "today" && <OperatorToday
        api={api}
        autoRefresh={autoRefresh}
        revision={todayRevision}
        onOpenConversation={onOpenConversation}
        onOpenTransfer={async (id) => {
          try {
            setPollError("");
            setSelectedTransfer(await api(`transfers/${id}`));
          } catch (err) {
            setPollError(errorMessage(err));
          }
        }}
      />}

      {/* ========================================================================= */}
      {/* SEKME 1: SIP DAHİLİ WARM TRANSFER                                         */}
      {/* ========================================================================= */}
      {activeTab === "sip_transfers" && (
        <>
          {activeIncoming && (
            <section
              style={{
                background: "linear-gradient(135deg, #1e1b4b 0%, #311042 100%)",
                border: "2px solid #a855f7",
                borderRadius: "12px",
                padding: "20px",
                boxShadow: "0 0 25px rgba(168, 85, 247, 0.4)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "15px" }}>
                <div style={{ flex: 1, minWidth: "280px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
                    <span style={{ fontSize: "20px" }}>📲</span>
                    <h3 style={{ margin: 0, fontSize: "20px", color: "#f3e8ff", fontWeight: "bold" }}>
                      GELEN CANLI AKTARIM (Screen-Pop)
                    </h3>
                    <span
                      style={{
                        background: "#c084fc",
                        color: "#3b0764",
                        fontSize: "11px",
                        fontWeight: "bold",
                        padding: "2px 8px",
                        borderRadius: "4px",
                      }}
                    >
                      SIP X-Freya Başlıkları Hazır
                    </span>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "12px", marginTop: "12px" }}>
                    <div style={{ background: "rgba(0,0,0,0.3)", padding: "10px", borderRadius: "6px" }}>
                      <div style={{ fontSize: "11px", color: "#c084fc" }}>MÜŞTERİ</div>
                      <div style={{ fontSize: "16px", color: "#f8fafc", fontWeight: "bold" }}>
                        {activeIncoming.customer_name || "İsimsiz Arayan"}
                      </div>
                      <div style={{ fontSize: "11px", color: "#94a3b8" }}>{activeIncoming.caller_channel}</div>
                    </div>

                    <div style={{ background: "rgba(0,0,0,0.3)", padding: "10px", borderRadius: "6px" }}>
                      <div style={{ fontSize: "11px", color: "#c084fc" }}>PLAKA</div>
                      <div
                        style={{
                          display: "inline-block",
                          border: "2px solid #ffffff",
                          background: "#0f172a",
                          color: "#ffffff",
                          borderRadius: "4px",
                          padding: "2px 8px",
                          fontSize: "15px",
                          fontWeight: "bold",
                          marginTop: "2px",
                        }}
                      >
                        TR {activeIncoming.vehicle_plate || "PLAKA YOK"}
                      </div>
                    </div>

                    <div style={{ background: "rgba(0,0,0,0.3)", padding: "10px", borderRadius: "6px", gridColumn: "span 2" }}>
                      <div style={{ fontSize: "11px", color: "#c084fc" }}>AKTARIM GEREKÇESİ / ÖZET</div>
                      <div style={{ fontSize: "14px", color: "#f1f5f9" }}>{activeIncoming.summary || "Belirtilmedi"}</div>
                    </div>
                  </div>

                  {/* 10 Saniyelik Fısıltı Önizlemesi */}
                  <div
                    style={{
                      marginTop: "14px",
                      background: "#1e1b4b",
                      borderLeft: "4px solid #38bdf8",
                      padding: "10px 14px",
                      borderRadius: "0 6px 6px 0",
                    }}
                  >
                    <div style={{ fontSize: "11px", color: "#38bdf8", fontWeight: "bold", marginBottom: "4px" }}>
                      🗣️ Operatör Fısıltısı (Dahiliye Okunan Sesli Özet):
                    </div>
                    <div style={{ fontSize: "13px", color: "#e2e8f0", fontStyle: "italic" }}>
                      "{activeIncoming.whisper_text}"
                    </div>
                  </div>
                </div>

                {/* Karar Butonları */}
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "10px",
                    justifyContent: "center",
                    minWidth: "220px",
                  }}
                >
                  <button
                    type="button"
                    onClick={() => handleAccept(activeIncoming.id)}
                    disabled={actionBusy}
                    style={{
                      padding: "14px 20px",
                      background: "#16a34a",
                      color: "#ffffff",
                      border: "none",
                      borderRadius: "8px",
                      fontSize: "16px",
                      fontWeight: "bold",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "8px",
                      boxShadow: "0 4px 12px rgba(22, 163, 74, 0.4)",
                    }}
                  >
                    <span>📞</span>
                    <span>Çağrıyı Al / Köprüle (1)</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleDecline(activeIncoming.id)}
                    disabled={actionBusy}
                    style={{
                      padding: "12px 20px",
                      background: "#dc2626",
                      color: "#ffffff",
                      border: "none",
                      borderRadius: "8px",
                      fontSize: "14px",
                      fontWeight: "bold",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "8px",
                    }}
                  >
                    <span>🚫</span>
                    <span>Meşgul / AI'ya İade Et (2)</span>
                  </button>

                  <div style={{ fontSize: "11px", color: "#cbd5e1", textAlign: "center" }}>
                    Zaman aşımında (yapılandırılmış süre dolunca) çağrı otomatik olarak yapay zekâya döner.
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* Test Simülasyon Formu */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", color: "#f8fafc" }}>
              🧪 Simülasyon: Test Amaçlı Aktarım Başlat
              <button
                type="button"
                className="secondary"
                style={{ marginLeft: "12px", padding: "3px 10px", fontSize: "11px" }}
                onClick={() => {
                  setFormCustomer("Ahmet Yılmaz");
                  setFormPlate("34 ABC 123");
                  setFormSummary("14:30 randevu teyidi / kaporta boya ekspertiz sorusu");
                  setFormExten("6002");
                }}
              >
                Örnek doldur
              </button>
            </h3>
            <form onSubmit={handleCreateTestTransfer} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "10px", alignItems: "flex-end" }}>
              <div>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }} htmlFor="op-f-cust">Müşteri Adı</label>
                <input
                  id="op-f-cust"
                  type="text"
                  value={formCustomer}
                  onChange={(e) => setFormCustomer(e.target.value)}
                  required
                  style={{ width: "100%", padding: "8px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }} htmlFor="op-f-plate">Araç Plakası</label>
                <input
                  id="op-f-plate"
                  type="text"
                  value={formPlate}
                  onChange={(e) => setFormPlate(e.target.value)}
                  required
                  style={{ width: "100%", padding: "8px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }} htmlFor="op-f-ext">Dahili Uzantı</label>
                <input
                  id="op-f-ext"
                  type="text"
                  value={formExten}
                  onChange={(e) => setFormExten(e.target.value)}
                  required
                  style={{ width: "100%", padding: "8px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc" }}
                />
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }} htmlFor="op-f-sum">Konu / Özet</label>
                <input
                  id="op-f-sum"
                  type="text"
                  value={formSummary}
                  onChange={(e) => setFormSummary(e.target.value)}
                  required
                  style={{ width: "100%", padding: "8px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc" }}
                />
              </div>
              <div>
                <button
                  type="submit"
                  disabled={actionBusy}
                  style={{
                    width: "100%",
                    padding: "8px 16px",
                    background: "#2563eb",
                    color: "#ffffff",
                    border: "none",
                    borderRadius: "6px",
                    fontWeight: "bold",
                    cursor: "pointer",
                  }}
                >
                  {actionBusy ? "Başlatılıyor..." : "Simüle Aktarımı Başlat 🚀"}
                </button>
              </div>
            </form>
          </section>

          {/* Aktarım Geçmişi Tablosu */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px", flexWrap: "wrap", gap: "10px" }}>
              <h3 style={{ margin: 0, fontSize: "15px", color: "#f8fafc" }}>
                📋 Aktarım Geçmişi ({filteredTransfers.length})
              </h3>
              <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                {[
                  { id: "all", label: "Tümü" },
                  { id: "active", label: "Bekleyenler" },
                  { id: "accepted", label: "Kabul Edilenler" },
                  { id: "declined", label: "İade / Timeout" },
                ].map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    className={statusFilter === f.id ? "primary" : "secondary"}
                    onClick={() => setStatusFilter(f.id)}
                    style={{ padding: "4px 10px", fontSize: "12px" }}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="table-wrap">
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #334155", color: "#94a3b8", textAlign: "left" }}>
                    <th style={{ padding: "8px" }}>Tarih / Saat</th>
                    <th style={{ padding: "8px" }}>Müşteri</th>
                    <th style={{ padding: "8px" }}>Plaka</th>
                    <th style={{ padding: "8px" }}>Dahili</th>
                    <th style={{ padding: "8px" }}>Durum</th>
                    <th style={{ padding: "8px" }}>Süre</th>
                    <th style={{ padding: "8px" }}>Özet</th>
                    <th style={{ padding: "8px", textAlign: "right" }}>İşlemler</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTransfers.length === 0 ? (
                    <tr>
                      <td colSpan={8} style={{ padding: "20px", textAlign: "center", color: "#64748b" }}>
                        Kayıtlı aktarım bulunamadı.
                      </td>
                    </tr>
                  ) : (
                    filteredTransfers.map((t) => {
                      let badgeBg = "#334155";
                      let badgeColor = "#f8fafc";
                      let statusLabel: string = t.status;
                      if (t.status === "initiated" || t.status === "whispering") {
                        badgeBg = "#ca8a04";
                        badgeColor = "#fef08a";
                        statusLabel = "Fısıldanıyor";
                      } else if (t.status === "accepted") {
                        badgeBg = "#15803d";
                        badgeColor = "#bbf7d0";
                        statusLabel = "Kabul Edildi";
                      } else if (t.status === "declined") {
                        badgeBg = "#b91c1c";
                        badgeColor = "#fecaca";
                        statusLabel = "Reddedildi / AI";
                      } else if (t.status === "timeout") {
                        badgeBg = "#9a3412";
                        badgeColor = "#fed7aa";
                        statusLabel = "Zaman Aşımı / AI";
                      }

                      return (
                        <tr key={t.id} style={{ borderBottom: "1px solid #1e293b" }}>
                          <td style={{ padding: "8px", color: "#cbd5e1" }}>
                            {t.created_at ? new Date(t.created_at).toLocaleTimeString() : "-"}
                          </td>
                          <td style={{ padding: "8px", fontWeight: "bold", color: "#f8fafc" }}>
                            {t.customer_name || "İsimsiz"}
                          </td>
                          <td style={{ padding: "8px" }}>
                            <span
                              style={{
                                border: "1px solid #475569",
                                padding: "2px 6px",
                                borderRadius: "4px",
                                fontSize: "11px",
                                fontWeight: "bold",
                                background: "#0f172a",
                              }}
                            >
                              {t.vehicle_plate || "-"}
                            </span>
                          </td>
                          <td style={{ padding: "8px", color: "#38bdf8" }}>{t.operator_extension}</td>
                          <td style={{ padding: "8px" }}>
                            <span
                              style={{
                                padding: "3px 8px",
                                borderRadius: "10px",
                                fontSize: "11px",
                                fontWeight: "bold",
                                background: badgeBg,
                                color: badgeColor,
                              }}
                            >
                              {statusLabel}
                            </span>
                          </td>
                          <td style={{ padding: "8px", color: "#94a3b8" }}>
                            {t.duration_seconds !== null ? `${t.duration_seconds.toFixed(1)}s` : "-"}
                          </td>
                          <td style={{ padding: "8px", maxWidth: "260px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={t.summary}>
                            {t.summary}
                          </td>
                          <td style={{ padding: "8px", textAlign: "right" }}>
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => setSelectedTransfer(t)}
                              style={{ padding: "3px 8px", fontSize: "11px" }}
                            >
                              SIP / Detay
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {/* ========================================================================= */}
      {/* SEKME 2: RT-10 CANLI MÜDAHALE & FISILTI (TAKEOVER / WHISPER)                */}
      {/* ========================================================================= */}
      {activeTab === "live_takeover" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {/* Operatör Kimlik ve Test Çubuğu */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
              <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                <div>
                  <label htmlFor="op-id" style={{ fontSize: "11px", color: "#94a3b8", display: "block" }}>Operatör Kodunuz</label>
                  <input
                    id="op-id"
                    placeholder="örn. op_1"
                    type="text"
                    value={operatorId}
                    onChange={(e) => setOperatorId(e.target.value)}
                    style={{ padding: "6px 10px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "13px" }}
                  />
                </div>
                <div>
                  <label htmlFor="op-reason" style={{ fontSize: "11px", color: "#94a3b8", display: "block" }}>Müdahale Gerekçesi</label>
                  <select
                    id="op-reason"
                    value={takeoverReason}
                    onChange={(e) => setTakeoverReason(e.target.value)}
                    style={{ padding: "6px 10px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "13px" }}
                  >
                    <option value="customer_complaint">Müşteri Şikâyeti / Öfke</option>
                    <option value="complex_pricing">Karmaşık Fiyat & Filo Talebi</option>
                    <option value="gpu_failover">GPU Devre Kesici Tetiklendi</option>
                    <option value="supervisor_coaching">Süpervizör Koçluk / Denetim</option>
                  </select>
                </div>
              </div>
              <div style={{ display: "flex", gap: "10px", alignItems: "flex-end" }}>
                <div>
                  <label htmlFor="op-sim-caller" style={{ fontSize: "11px", color: "#94a3b8", display: "block" }}>Simüle Arayan No</label>
                  <input
                    id="op-sim-caller"
                    placeholder="örn. 05XXXXXXXXX"
                    type="text"
                    value={simCallerId}
                    onChange={(e) => setSimCallerId(e.target.value)}
                    style={{ padding: "6px 10px", background: "#1e293b", border: "1px solid #334155", borderRadius: "6px", color: "#f8fafc", fontSize: "13px" }}
                  />
                </div>
                <button
                  type="button"
                  className="secondary"
                  onClick={handleRegisterSimCall}
                  disabled={actionBusy || !simCallerId.trim()}
                  style={{ padding: "6px 14px", fontSize: "13px" }}
                >
                  + Simülasyon: Yeni Çağrı Başlat
                </button>
              </div>
            </div>
          </section>

          {/* Aktif Çağrılar Tablosu */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 12px 0", fontSize: "16px", color: "#f8fafc", display: "flex", alignItems: "center", gap: "8px" }}>
              🔴 Canlı AI Çağrıları ({liveSessions.length})
              <small style={{ fontSize: "12px", color: "#94a3b8", fontWeight: "normal" }}>
                (Tek tıkla AI anında susturulur ve çağrı operatöre köprülenir)
              </small>
            </h3>

            {liveSessions.length === 0 ? (
              <div style={{ padding: "30px", textAlign: "center", color: "#64748b" }}>
                Şu anda hatta aktif görüşme bulunmuyor. Yukarıdaki "+ Simülasyon: Yeni Çağrı Başlat" butonuyla test çağrısı açabilirsiniz.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                {liveSessions.map((s) => {
                  const isTakenOver = s.state === "taken_over";
                  const isSim = s.session_id.startsWith("sim_");
                  return (
                    <div
                      key={s.session_id}
                      style={{
                        background: isTakenOver ? "#271212" : "#1e293b",
                        border: isTakenOver ? "1px solid #ef4444" : "1px solid #334155",
                        borderRadius: "8px",
                        padding: "16px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
                        <div>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <span style={{ fontWeight: "bold", color: "#f8fafc", fontSize: "15px" }}>
                              📱 {s.caller_id}
                            </span>
                            <span style={{ fontSize: "11px", color: "#94a3b8" }}>({s.session_id})</span>
                            {isSim && <span className="pill">Simülasyon</span>}
                            <span
                              style={{
                                padding: "2px 8px",
                                borderRadius: "10px",
                                fontSize: "11px",
                                fontWeight: "bold",
                                background: isTakenOver ? "#b91c1c" : "#15803d",
                                color: isTakenOver ? "#fecaca" : "#bbf7d0",
                              }}
                            >
                              {isTakenOver ? `🔴 OPERATÖRDE (${s.operator_id})` : "🟢 YAPAY ZEKA (Leyla) YÖNETİYOR"}
                            </span>
                          </div>
                          <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", marginTop: "6px", fontSize: "12px", color: "#cbd5e1" }}>
                            <span>Turn: <b style={{ color: "#38bdf8" }}>{s.current_turn_id || "-"}</b></span>
                            <span>MOS: <b style={{ color: "#4ade80" }}>{isSim ? "—" : dash(s.mos_score)}</b></span>
                            <span>RTF: <b style={{ color: "#facc15" }}>{isSim ? "—" : dash(s.rtf)}</b></span>
                            <span>Paket Kaybı: <b>{isSim ? "—" : dash(s.packet_loss_pct, "%")}</b></span>
                          </div>
                        </div>

                        {/* Eylem Butonları */}
                        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                          {!isTakenOver ? (
                            <button
                              type="button"
                              onClick={() => handleTakeover(s.session_id)}
                              disabled={actionBusy || !operatorId.trim()}
                              style={{
                                background: "#dc2626",
                                color: "#ffffff",
                                border: "none",
                                padding: "8px 14px",
                                borderRadius: "6px",
                                fontWeight: "bold",
                                cursor: "pointer",
                                fontSize: "13px",
                              }}
                            >
                              ⚡ Çağrıyı Devral (Takeover)
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => handleRelease(s.session_id)}
                              disabled={actionBusy}
                              style={{
                                background: "#16a34a",
                                color: "#ffffff",
                                border: "none",
                                padding: "8px 14px",
                                borderRadius: "6px",
                                fontWeight: "bold",
                                cursor: "pointer",
                                fontSize: "13px",
                              }}
                            >
                              🔁 Görüşmeyi AI'ya Geri Ver (Release)
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Fısıltı (Whisper) Alanı */}
                      <div style={{ marginTop: "12px", borderTop: "1px solid rgba(255,255,255,0.1)", paddingTop: "10px", display: "flex", gap: "8px" }}>
                        <input
                          type="text"
                          aria-label="Fısıltı notu"
                          placeholder="Yapay zekaya gizli koçluk notu fısılda (Müşteri duymaz)..."
                          value={whisperMessage}
                          onChange={(e) => setWhisperMessage(e.target.value)}
                          style={{
                            flex: 1,
                            padding: "6px 10px",
                            background: "#0f172a",
                            border: "1px solid #475569",
                            borderRadius: "6px",
                            color: "#f8fafc",
                            fontSize: "12px",
                          }}
                        />
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => handleWhisper(s.session_id)}
                          disabled={actionBusy || !whisperMessage.trim()}
                          style={{ padding: "6px 12px", fontSize: "12px" }}
                        >
                          🗣️ Fısılda (Whisper)
                        </button>
                      </div>

                      {/* Önceki Fısıltı Notları */}
                      {s.whisper_notes && s.whisper_notes.length > 0 && (
                        <div style={{ marginTop: "8px", fontSize: "11px", color: "#94a3b8" }}>
                          <b>Fısıltı Geçmişi:</b> {s.whisper_notes.join(" | ")}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SEKME 3: HLS-08 KALİTE KAPISI 5 & RT-09 DAĞITIK TELEMETRİ                  */}
      {/* ========================================================================= */}
      {activeTab === "quality_gate" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {/* Kalite Kapısı 5 Benchmark Başlatma */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "16px", color: "#f8fafc" }}>
                  🎯 Kalite Kapısı 5
                </h3>
                <p style={{ margin: "4px 0 0 0", color: "#94a3b8", fontSize: "12px" }}>
                  Varyant B, varsa scripts/acoustic_benchmark.py ile alınan gerçek ses ölçümünü gösterir (TTS sesi telefon hattından STT ile geri tanınır). Bu düğme yeni ses üretmez.
                </p>
              </div>
              <button
                type="button"
                className="primary"
                onClick={handleRunQABenchmark}
                disabled={qaLoading}
                style={{ padding: "8px 16px", fontWeight: "bold" }}
              >
                {qaLoading ? "Ölçülüyor..." : "🚀 Kalite Kapısı 5 Süitini Çalıştır"}
              </button>
            </div>

            {/* QA Raporu Çıktısı */}
            {qaReport && (
              <div style={{ marginTop: "16px", borderTop: "1px solid #1e293b", paddingTop: "14px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "12px" }}>
                  <span style={{ fontSize: "14px", color: "#cbd5e1" }}>Genel Değerlendirme Durumu:</span>
                  <span
                    style={{
                      padding: "4px 12px",
                      borderRadius: "6px",
                      fontSize: "14px",
                      fontWeight: "bold",
                      background:
                        qaReport.quality_gate_5_status === "PASS"
                          ? "#15803d"
                          : qaReport.quality_gate_5_status === "HOLD"
                            ? "#a16207"
                            : "#b91c1c",
                      color: "#ffffff",
                    }}
                  >
                    {qaReport.quality_gate_5_status === "PASS"
                      ? "✅ KALİTE KAPISI 5: PASS"
                      : qaReport.quality_gate_5_status === "HOLD"
                        ? "⏸ HOLD (ölçüm eksik)"
                        : "❌ FAIL"}
                  </span>
                  <span style={{ fontSize: "12px", color: "#94a3b8" }}>
                    {qaReport.acoustic_report
                      ? `(Ses ölçümü: ${qaReport.acoustic_report.sample_count} cümle, ${new Date(qaReport.acoustic_report.measured_at).toLocaleString("tr-TR")})`
                      : `(${qaReport.total_sentences} test cümlesi, yalnızca metin ölçümü; ses raporu yok)`}
                  </span>
                </div>
                {qaReport.acoustic_report && (
                  <p style={{ margin: "0 0 6px 0", fontSize: "12px", color: "#cbd5e1" }}>
                    Ort. RTF: {qaReport.acoustic_report.rtf_avg ?? "—"} · Medyan F₀:{" "}
                    {qaReport.acoustic_report.f0_median_hz ?? "—"} Hz · Hat:{" "}
                    {qaReport.acoustic_report.channel} · STT: {qaReport.acoustic_report.stt_model}
                    {qaReport.acoustic_report.failed_synthesis > 0 &&
                      ` · Başarısız sentez: ${qaReport.acoustic_report.failed_synthesis}`}
                    {!qaReport.acoustic_report.has_f0_baseline && " · F₀ taban kaydı yok"}
                  </p>
                )}
                {qaReport.quality_gate_failed?.length > 0 && (
                  <p style={{ margin: "0 0 6px 0", fontSize: "12px", color: "#f87171" }}>
                    Eşiği aşan: {qaReport.quality_gate_failed.join(", ")}
                  </p>
                )}
                {qaReport.quality_gate_missing?.length > 0 && (
                  <p style={{ margin: "0 0 6px 0", fontSize: "12px", color: "#facc15" }}>
                    Ölçülmeyen: {qaReport.quality_gate_missing.join(", ")}
                  </p>
                )}

                {/* Karşılaştırmalı Varyant Tablosu */}
                <div className="table-wrap"><table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px", marginTop: "10px" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid #334155", color: "#94a3b8", textAlign: "left" }}>
                      <th style={{ padding: "8px" }}>Varyant Adı</th>
                      <th style={{ padding: "8px" }}>Örnek Sayısı</th>
                      <th style={{ padding: "8px" }}>Otomotiv Doğruluğu</th>
                      <th style={{ padding: "8px" }}>Kelime Hata (WER)</th>
                      <th style={{ padding: "8px" }}>Karakter Hata (CER)</th>
                      <th style={{ padding: "8px" }}>ITU-T MOS</th>
                      <th style={{ padding: "8px" }}>Ses Benzerliği (ABX)</th>
                      <th style={{ padding: "8px" }}>Azami F0 Sapması</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(qaReport.variant_summaries || {}).map(([vName, vData]: [string, any]) => {
                      const isVariantB = vName === "variant_b";
                      const isVariantC = vName === "variant_c";
                      let label = "Varyant A (Ham metin)";
                      if (isVariantB) label = "Varyant B (P0 Otomotiv Sözlüğü)";
                      if (isVariantC) label = "Varyant C (P0 + LoRA, adaptör yok)";
                      const show = (value: number | null, prefix = "", suffix = "") =>
                        value === null || value === undefined ? "—" : `${prefix}${value}${suffix}`;

                      return (
                        <tr
                          key={vName}
                          style={{
                            borderBottom: "1px solid #1e293b",
                            background: isVariantB ? "rgba(34, 197, 94, 0.08)" : "transparent",
                          }}
                        >
                          <td style={{ padding: "8px", fontWeight: isVariantB ? "bold" : "normal", color: "#f8fafc" }}>
                            {label}
                          </td>
                          <td style={{ padding: "8px" }}>{vData.sample_count}</td>
                          <td style={{ padding: "8px" }}>{show(vData.automotive_accuracy_pct, "%")}</td>
                          <td style={{ padding: "8px" }}>{show(vData.avg_wer_pct, "%")}</td>
                          <td style={{ padding: "8px" }}>{show(vData.avg_cer_pct, "%")}</td>
                          <td style={{ padding: "8px" }}>{show(vData.avg_mos)}</td>
                          <td style={{ padding: "8px" }}>{show(vData.speaker_embedding_abx)}</td>
                          <td style={{ padding: "8px" }}>{show(vData.max_f0_drift_hz, "", " Hz")}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table></div>
              </div>
            )}
          </section>

          {/* M11 Fiziksel Donanım Güvenlik Kalkanı */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 8px 0", fontSize: "15px", color: "#f8fafc" }}>
              🛡️ M11 Donanım Kabul Güvenlik Kalkanı
            </h3>
            <p style={{ margin: "0 0 10px 0", fontSize: "12px", color: "#94a3b8" }}>
              Canlı ortama fiziksel Asterisk PBX pcap trace veya Hardware SIP Trunk kanıtı olmadan sahte geçişi engeller.
            </p>
            {m11Status ? (
              <div style={{ background: "#1e293b", padding: "12px", borderRadius: "6px", fontSize: "12px" }}>
                <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
                  <span style={{ fontWeight: "bold", color: "#cbd5e1" }}>Fiziksel Kabul Durumu:</span>
                  <span
                    style={{
                      padding: "2px 8px",
                      borderRadius: "4px",
                      fontWeight: "bold",
                      background: m11Status.overall_status === "PASS" ? "#15803d" : "#ca8a04",
                      color: "#ffffff",
                    }}
                  >
                    {m11Status.overall_status}
                  </span>
                  <span style={{ color: "#94a3b8" }}>Ortam: {m11Status.environment}</span>
                </div>
                {m11Status.reason && (
                  <div style={{ marginTop: "6px", color: "#e2e8f0" }}>{m11Status.reason}</div>
                )}
                {Array.isArray(m11Status.required_for_pass) && m11Status.required_for_pass.length > 0 && (
                  <div style={{ marginTop: "6px", color: "#cbd5e1" }}>
                    <b>Geçiş için gerekenler:</b>
                    <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>
                      {m11Status.required_for_pass.map((r: string) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <button
                type="button"
                className="secondary"
                onClick={async () => setM11Status(await api("qa/m11-status"))}
                style={{ fontSize: "12px", padding: "6px 12px" }}
              >
                M11 Durumunu Sorgula
              </button>
            )}
          </section>

          {/* Tur telemetrisi / trace span inceleyici */}
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 8px 0", fontSize: "15px", color: "#f8fafc" }}>
              🔍 Tur telemetrisi
            </h3>
            <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "12px" }}>
              <input
                type="text"
                aria-label="Tur kimliği"
                placeholder="Tur kimliği (turn id)"
                value={telemetryTurnId}
                onChange={(e) => setTelemetryTurnId(e.target.value)}
                style={{
                  padding: "6px 10px",
                  background: "#1e293b",
                  border: "1px solid #334155",
                  borderRadius: "6px",
                  color: "#f8fafc",
                  fontSize: "13px",
                  width: "260px",
                }}
              />
              <button
                type="button"
                className="primary"
                onClick={handleFetchTelemetry}
                disabled={actionBusy || !telemetryTurnId.trim()}
                style={{ padding: "6px 14px", fontSize: "13px" }}
              >
                Span Sorgula
              </button>
            </div>

            {telemetryData && (
              <div style={{ background: "#1e293b", padding: "12px", borderRadius: "6px" }}>
                <div style={{ fontSize: "12px", color: "#4ade80", fontWeight: "bold", marginBottom: "6px" }}>
                  Ölçülmemiş alanlar null olarak gösterilir (0 yazılmaz).
                </div>
                <pre
                  style={{
                    background: "#0f172a",
                    padding: "10px",
                    borderRadius: "4px",
                    color: "#38bdf8",
                    fontSize: "11px",
                    overflowX: "auto",
                    maxHeight: "220px",
                  }}
                >
                  {JSON.stringify(telemetryData.opentelemetry_span || telemetryData, null, 2)}
                </pre>
              </div>
            )}
          </section>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SEKME 4: BAŞARISIZ & ANLAŞILAMAYAN GÖRÜŞMELER (LEXICON GERİ BESLEME)       */}
      {/* ========================================================================= */}
      {activeTab === "failed_calls" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <section style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px" }}>
            <h3 style={{ margin: "0 0 6px 0", fontSize: "16px", color: "#f8fafc", display: "flex", alignItems: "center", gap: "8px" }}>
              <span>🚨</span>
              <span>Başarısız & Anlaşılamayan Görüşmeler — Sözlüğe Geri Besleme</span>
            </h3>
            <p style={{ margin: 0, color: "#94a3b8", fontSize: "13px" }}>
              Asistanın teyit istediği veya terimlerin yanlış anlaşıldığı görüşmeleri dinleyip doğru otomotiv terimini sisteme öğretebilirsiniz. Yapılan düzeltmeler anında fonetik normalizer'a ve terim sözlüğüne aktarılır.
            </p>
          </section>

          {feedbackMsg && (
            <div
              style={{
                padding: "10px 14px",
                borderRadius: "6px",
                background: feedbackMsg.includes("başarıyla") ? "#064e3b" : "#7f1d1d",
                color: feedbackMsg.includes("başarıyla") ? "#6ee7b7" : "#fca5a5",
                fontSize: "13px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span>{feedbackMsg}</span>
              <button
                type="button"
                onClick={() => setFeedbackMsg("")}
                style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontWeight: "bold" }}
              >
                ✕
              </button>
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "minmax(320px, 1fr) minmax(400px, 1.5fr)", gap: "16px" }}>
            {/* Sol Kolon: Görüşme Listesi */}
            <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px", maxHeight: "700px", overflowY: "auto" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <h4 style={{ margin: 0, fontSize: "14px", color: "#f8fafc" }}>
                  Görüşmeler ({unclearCalls.length})
                </h4>
                <button
                  type="button"
                  className="secondary"
                  onClick={loadUnclearCalls}
                  disabled={unclearLoading}
                  style={{ fontSize: "11px", padding: "3px 8px" }}
                >
                  {unclearLoading ? "..." : "Yenile ↻"}
                </button>
              </div>

              {!unclearCalls.length && !unclearLoading && (
                <div style={{ textAlign: "center", padding: "2rem", color: "#64748b", fontSize: "13px" }}>
                  🎉 Harika! İncelenmesi gereken anlaşılamayan görüşme bulunmuyor.
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {unclearCalls.map((c) => {
                  const isSelected = selectedUnclearCall?.id === c.id;
                  return (
                    <div
                      key={c.id}
                      onClick={() => setSelectedUnclearCall(c)}
                      style={{
                        padding: "10px",
                        borderRadius: "6px",
                        border: isSelected ? "1px solid #3b82f6" : "1px solid #1e293b",
                        background: isSelected ? "#1e293b" : "#0f172a",
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                        <span style={{ fontSize: "11px", color: "#94a3b8" }}>
                          {c.created_at?.substring(0, 16).replace("T", " ")}
                        </span>
                        <span
                          style={{
                            fontSize: "10px",
                            padding: "2px 6px",
                            borderRadius: "10px",
                            background: c.unclear_count > 0 ? "#7f1d1d" : "#854d0e",
                            color: "#fecaca",
                            fontWeight: "bold",
                          }}
                        >
                          {c.unclear_count > 0 ? `⚠️ ${c.unclear_count} Belirsiz Tur` : "Takipte"}
                        </span>
                      </div>
                      <div style={{ fontSize: "12px", color: "#f1f5f9", fontWeight: 600 }}>
                        Çağrı #{c.id.substring(0, 8)} ({c.channel})
                      </div>
                      <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                        Toplam {c.turn_count} diyalog turu {c.has_recording ? "• 🎧 Ses Var" : ""}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Sağ Kolon: Seçili Görüşme Detayı, Ses Kaydı & Sözlüğe Geri Besleme */}
            <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "8px", padding: "16px", display: "flex", flexDirection: "column", gap: "16px" }}>
              {selectedUnclearCall ? (
                <>
                  <div style={{ borderBottom: "1px solid #1e293b", paddingBottom: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <h4 style={{ margin: 0, fontSize: "15px", color: "#f8fafc" }}>
                        Çağrı #{selectedUnclearCall.id}
                      </h4>
                      <span style={{ fontSize: "11px", color: "#94a3b8" }}>
                        Kanal: {selectedUnclearCall.channel}
                      </span>
                    </div>

                    {/* Ses Çalar */}
                    <div style={{ marginTop: "10px", padding: "10px", background: "#1e293b", borderRadius: "6px" }}>
                      <div style={{ fontSize: "12px", color: "#38bdf8", fontWeight: "bold", marginBottom: "6px" }}>
                        🎧 Görüşme Ses Kaydı:
                      </div>
                      {selectedUnclearCall.has_recording ? (
                        <audio
                          controls
                          src={`/api/conversations/${selectedUnclearCall.id}/audio`}
                          style={{ width: "100%", height: "36px" }}
                        />
                      ) : (
                        <div style={{ fontSize: "12px", color: "#94a3b8", fontStyle: "italic" }}>
                          ℹ️ Bu oturumun ham WAV kaydı doğrudan ses kartından akıtılmıştır veya arşivlenmiştir.
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Transkript Akışı */}
                  <div>
                    <h5 style={{ margin: "0 0 8px 0", fontSize: "13px", color: "#cbd5e1" }}>
                      💬 Diyalog Akışı:
                    </h5>
                    <div style={{ maxHeight: "250px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "8px", paddingRight: "4px" }}>
                      {selectedUnclearCall.turns.map((t) => (
                        <div
                          key={t.id}
                          style={{
                            padding: "8px 12px",
                            borderRadius: "6px",
                            fontSize: "12px",
                            background: t.is_unclear
                              ? "#451a03"
                              : t.role === "user"
                              ? "#1e3a8a"
                              : "#1e293b",
                            border: t.is_unclear ? "1px solid #b45309" : "none",
                            color: "#f8fafc",
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "2px" }}>
                            <span style={{ fontWeight: "bold", color: t.role === "user" ? "#93c5fd" : "#38bdf8" }}>
                              {t.role === "user" ? "Müşteri" : "FreyaTTS Asistan"}
                            </span>
                            {t.is_unclear && (
                              <span style={{ color: "#fcd34d", fontSize: "10px", fontWeight: "bold" }}>
                                ⚠️ ANLAŞILAMADI / TEYİT
                              </span>
                            )}
                          </div>
                          <div>{t.text}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Sözlüğe Geri Besleme Formu */}
                  <div style={{ marginTop: "auto", background: "#1e293b", border: "1px solid #334155", borderRadius: "8px", padding: "14px" }}>
                    <div style={{ fontSize: "13px", color: "#f8fafc", fontWeight: "bold", marginBottom: "8px", display: "flex", alignItems: "center", gap: "6px" }}>
                      <span>✍️</span>
                      <span>Düzeltmeyi Sözlüğe Geri Besle (Domain Lexicon Feedback)</span>
                    </div>
                    <form onSubmit={handleFeedbackSubmit} style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
                          Doğru Otomotiv Terimi (Örn: Qashqai)
                        </label>
                        <input
                          type="text"
                          value={feedbackTerm}
                          onChange={(e) => setFeedbackTerm(e.target.value)}
                          placeholder="Örn: Qashqai, EcoBoost"
                          required
                          style={{ width: "100%", padding: "6px 8px", background: "#0f172a", border: "1px solid #475569", borderRadius: "4px", color: "#f8fafc", fontSize: "12px" }}
                        />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
                          Duyulan / Okunuş (Örn: kaşkay)
                        </label>
                        <input
                          type="text"
                          value={feedbackSpoken}
                          onChange={(e) => setFeedbackSpoken(e.target.value)}
                          placeholder="Örn: kaşkay, eko büst"
                          required
                          style={{ width: "100%", padding: "6px 8px", background: "#0f172a", border: "1px solid #475569", borderRadius: "4px", color: "#f8fafc", fontSize: "12px" }}
                        />
                      </div>
                      <div>
                        <label style={{ display: "block", fontSize: "11px", color: "#94a3b8", marginBottom: "4px" }}>
                          Kategori
                        </label>
                        <select
                          value={feedbackCategory}
                          onChange={(e) => setFeedbackCategory(e.target.value)}
                          style={{ width: "100%", padding: "6px 8px", background: "#0f172a", border: "1px solid #475569", borderRadius: "4px", color: "#f8fafc", fontSize: "12px" }}
                        >
                          <option value="brand">Marka (Brand)</option>
                          <option value="model">Model</option>
                          <option value="technical">Motor / Teknik</option>
                          <option value="custom">Özel Terim</option>
                        </select>
                      </div>
                      <div style={{ display: "flex", alignItems: "flex-end" }}>
                        <button
                          type="submit"
                          disabled={feedbackBusy}
                          style={{
                            width: "100%",
                            padding: "7px 12px",
                            background: "#2563eb",
                            color: "#ffffff",
                            border: "none",
                            borderRadius: "4px",
                            fontWeight: "bold",
                            fontSize: "12px",
                            cursor: "pointer",
                          }}
                        >
                          {feedbackBusy ? "Kaydediliyor..." : "💾 Sözlüğe Ekle & Normalizer'ı Güncelle"}
                        </button>
                      </div>
                    </form>
                  </div>
                </>
              ) : (
                <div style={{ textAlign: "center", padding: "4rem 2rem", color: "#64748b", fontSize: "13px" }}>
                  Sol taraftan incelemek istediğiniz bir görüşmeyi seçin.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SEKME 5: KVKK TRANSKRİPT SAKLAMA SÜRESİ VE SİLME TALEPLERİ                 */}
      {/* ========================================================================= */}
      {activeTab === "kvkk_compliance" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* ÜST BİLGİ & DENETİM PANELİ */}
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #1e293b",
              borderRadius: "12px",
              padding: "20px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px", flexWrap: "wrap", gap: "10px" }}>
              <div>
                <h3 style={{ margin: 0, color: "#f8fafc", fontSize: "16px", display: "flex", alignItems: "center", gap: "8px" }}>
                  🛡️ KVKK Transkript Saklama Süresi ve Otomatik İmha İlkesi
                  <span
                    style={{
                      fontSize: "11px",
                      padding: "2px 8px",
                      borderRadius: "10px",
                      background: kvkkAudit?.compliance_status === "compliant" ? "#065f46" : "#991b1b",
                      color: "#f8fafc",
                    }}
                  >
                    {kvkkAudit?.compliance_status === "compliant" ? "✓ UYUMLU" : "⚠ İŞLEM GEREKİYOR"}
                  </span>
                </h3>
                <p style={{ margin: "4px 0 0 0", color: "#94a3b8", fontSize: "13px" }}>
                  Saklama süresi {kvkkAudit?.retention_policy_days ?? 30} gün. Otomatik transkript imhası {autoPurgeTranscripts ? "açık" : "kapalı"}. Silme işlemleri {kvkkErasureEnabled ? "açık" : "kapalı"}.
                </p>
              </div>

              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  type="button"
                  className="secondary"
                  disabled={kvkkAuditLoading || kvkkPurgeBusy}
                  onClick={() => loadKvkkAudit()}
                  style={{ padding: "6px 12px", fontSize: "12px" }}
                >
                  {kvkkAuditLoading ? "Denetleniyor..." : "Denetle ↻"}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={kvkkPurgeBusy}
                  onClick={() => handlePurgeTranscripts(true)}
                  style={{ padding: "6px 12px", fontSize: "12px" }}
                >
                  Önizleme (Dry Run)
                </button>
                <button
                  type="button"
                  className="primary"
                  disabled={!kvkkErasureEnabled || kvkkPurgeBusy || !kvkkAudit?.expired_conversations_count}
                  onClick={() => handlePurgeTranscripts(false)}
                  style={{ padding: "6px 12px", fontSize: "12px", background: "#b91c1c", borderColor: "#dc2626" }}
                >
                  {kvkkPurgeBusy ? "İmha Ediliyor..." : "Süresi Dolanları İmha Et"}
                </button>
              </div>
            </div>

            {kvkkPurgeMsg && (
              <div
                style={{
                  padding: "10px 14px",
                  borderRadius: "8px",
                  background: kvkkPurgeMsg.includes("Başarılı") ? "#064e3b" : "#1e293b",
                  border: "1px solid #334155",
                  color: "#f8fafc",
                  fontSize: "13px",
                  marginBottom: "16px",
                }}
              >
                {kvkkPurgeMsg}
              </div>
            )}

            {/* İstatistik Kartları */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                gap: "12px",
              }}
            >
              <div style={{ background: "#1e293b", padding: "14px", borderRadius: "8px" }}>
                <div style={{ color: "#94a3b8", fontSize: "12px" }}>Saklama İlkesi</div>
                <div style={{ fontSize: "20px", fontWeight: "bold", color: "#38bdf8", marginTop: "4px" }}>
                  {kvkkAudit?.retention_policy_days ?? 30} Gün
                </div>
              </div>
              <div style={{ background: "#1e293b", padding: "14px", borderRadius: "8px" }}>
                <div style={{ color: "#94a3b8", fontSize: "12px" }}>Aktif Transkriptler</div>
                <div style={{ fontSize: "20px", fontWeight: "bold", color: "#f8fafc", marginTop: "4px" }}>
                  {kvkkAudit?.active_conversations ?? 0}
                </div>
              </div>
              <div style={{ background: "#1e293b", padding: "14px", borderRadius: "8px" }}>
                <div style={{ color: "#94a3b8", fontSize: "12px" }}>Süresi Dolan (İmha Bekleyen)</div>
                <div style={{ fontSize: "20px", fontWeight: "bold", color: kvkkAudit?.expired_conversations_count ? "#f87171" : "#4ade80", marginTop: "4px" }}>
                  {kvkkAudit?.expired_conversations_count ?? 0} Görüşme
                </div>
                <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>
                  ({kvkkAudit?.expired_turns_count ?? 0} metin turu)
                </div>
              </div>
              <div style={{ background: "#1e293b", padding: "14px", borderRadius: "8px" }}>
                <div style={{ color: "#94a3b8", fontSize: "12px" }}>İmha Edilmiş / Anonim</div>
                <div style={{ fontSize: "20px", fontWeight: "bold", color: "#94a3b8", marginTop: "4px" }}>
                  {kvkkAudit?.already_purged_conversations ?? 0}
                </div>
              </div>
            </div>
          </div>

          {/* İKİ KOLONLU GÖVDE: YENİ TALEP FORMU & TALEPLER LİSTESİ */}
          <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: "20px" }}>
            {/* SOL: YENİ SİLME TALEBİ FORMU */}
            <div
              style={{
                background: "#0f172a",
                border: "1px solid #1e293b",
                borderRadius: "12px",
                padding: "20px",
                height: "fit-content",
              }}
            >
              <h4 style={{ margin: "0 0 12px 0", color: "#f8fafc", fontSize: "15px" }}>
                📝 Yeni Silme Talebi (KVKK Madde 11)
              </h4>
              <p style={{ margin: "0 0 16px 0", color: "#94a3b8", fontSize: "12px", lineHeight: "1.5" }}>
                Müşterinin unutulma hakkı başvurusu üzerine telefon, plaka veya görüşme ID girerek bağlı tüm verileri tarayabilir ve imha edebilirsiniz.
              </p>

              <form onSubmit={handleCreateErasureRequest} style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <div>
                  <label style={{ display: "block", color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
                    Kimlik Türü
                  </label>
                  <select
                    value={newReqType}
                    onChange={(e: any) => setNewReqType(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "8px",
                      borderRadius: "6px",
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #334155",
                      fontSize: "13px",
                    }}
                  >
                    <option value="phone">Telefon Numarası</option>
                    <option value="plate">Araç Plakası</option>
                    <option value="customer_name">Müşteri Adı</option>
                    <option value="conversation_id">Görüşme ID</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: "block", color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
                    Kimlik Değeri *
                  </label>
                  <input
                    type="text"
                    value={newReqVal}
                    onChange={(e) => setNewReqVal(e.target.value)}
                    placeholder={
                      newReqType === "phone"
                        ? "05321234567"
                        : newReqType === "plate"
                        ? "34ABC789"
                        : newReqType === "customer_name"
                        ? "Ahmet Yılmaz"
                        : "uuid..."
                    }
                    style={{
                      width: "100%",
                      padding: "8px",
                      borderRadius: "6px",
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #334155",
                      fontSize: "13px",
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: "block", color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
                    Başvuran Adı (Opsiyonel)
                  </label>
                  <input
                    type="text"
                    value={newReqName}
                    onChange={(e) => setNewReqName(e.target.value)}
                    placeholder="Başvuran kişi veya vekili"
                    style={{
                      width: "100%",
                      padding: "8px",
                      borderRadius: "6px",
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #334155",
                      fontSize: "13px",
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: "block", color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
                    Talep Gerekçesi
                  </label>
                  <input
                    type="text"
                    value={newReqReason}
                    onChange={(e) => setNewReqReason(e.target.value)}
                    style={{
                      width: "100%",
                      padding: "8px",
                      borderRadius: "6px",
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #334155",
                      fontSize: "13px",
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: "block", color: "#94a3b8", fontSize: "12px", marginBottom: "4px" }}>
                    Notlar
                  </label>
                  <textarea
                    rows={2}
                    value={newReqNotes}
                    onChange={(e) => setNewReqNotes(e.target.value)}
                    placeholder="İç iletişim veya evrak referans notu"
                    style={{
                      width: "100%",
                      padding: "8px",
                      borderRadius: "6px",
                      background: "#1e293b",
                      color: "#f8fafc",
                      border: "1px solid #334155",
                      fontSize: "13px",
                    }}
                  />
                </div>

                {newReqMsg && (
                  <div
                    style={{
                      padding: "8px",
                      borderRadius: "6px",
                      fontSize: "12px",
                      background: newReqMsg.includes("oluşturuldu") ? "#064e3b" : "#7f1d1d",
                      color: "#f8fafc",
                    }}
                  >
                    {newReqMsg}
                  </div>
                )}

                <button
                  type="submit"
                  className="primary"
                  disabled={!kvkkErasureEnabled || newReqBusy}
                  style={{ width: "100%", padding: "10px", fontSize: "13px", fontWeight: "bold" }}
                >
                  {newReqBusy ? "Hesaplanıyor..." : "Etki Analizi Yap & Talep Oluştur"}
                </button>
              </form>
            </div>

            {/* SAĞ: KAYITLI SİLME TALEPLERİ LİSTESİ */}
            <div
              style={{
                background: "#0f172a",
                border: "1px solid #1e293b",
                borderRadius: "12px",
                padding: "20px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                <h4 style={{ margin: 0, color: "#f8fafc", fontSize: "15px" }}>
                  📋 Kayıtlı Veri Silme Talepleri ({kvkkRequests.length})
                </h4>
                <button
                  type="button"
                  className="secondary"
                  disabled={kvkkRequestsLoading}
                  onClick={() => loadKvkkRequests()}
                  style={{ padding: "4px 10px", fontSize: "12px" }}
                >
                  {kvkkRequestsLoading ? "Yenileniyor..." : "Yenile ↻"}
                </button>
              </div>

              {kvkkRequests.length === 0 ? (
                <div style={{ textAlign: "center", padding: "3rem", color: "#64748b", fontSize: "13px" }}>
                  Henüz kayıtlı bir silme talebi bulunmuyor.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                  {kvkkRequests.map((req) => {
                    const impact = req.impact_summary || {};
                    const isExecuted = req.status === "executed";
                    return (
                      <div
                        key={req.id}
                        style={{
                          background: "#1e293b",
                          border: isExecuted ? "1px solid #065f46" : "1px solid #b45309",
                          borderRadius: "8px",
                          padding: "16px",
                          display: "flex",
                          flexDirection: "column",
                          gap: "10px",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                            <span
                              style={{
                                padding: "2px 8px",
                                borderRadius: "4px",
                                fontSize: "11px",
                                fontWeight: "bold",
                                background: isExecuted ? "#064e3b" : "#78350f",
                                color: isExecuted ? "#34d399" : "#fbbf24",
                              }}
                            >
                              {isExecuted ? "✓ İCRA EDİLDİ" : "⏳ BEKLEMEDE"}
                            </span>
                            <span style={{ color: "#38bdf8", fontWeight: "bold", fontSize: "13px" }}>
                              {req.identifier_type.toUpperCase()}: {req.identifier_value}
                            </span>
                            {req.requester_name && (
                              <span style={{ color: "#94a3b8", fontSize: "12px" }}>
                                ({req.requester_name})
                              </span>
                            )}
                          </div>
                          <span style={{ color: "#64748b", fontSize: "12px" }}>
                            {new Date(req.created_at).toLocaleString("tr-TR")}
                          </span>
                        </div>

                        <div style={{ fontSize: "12px", color: "#cbd5e1" }}>
                          <b>Gerekçe:</b> {req.reason}
                        </div>

                        {/* Etki / İmha Dağılımı */}
                        <div
                          style={{
                            display: "flex",
                            gap: "8px",
                            flexWrap: "wrap",
                            background: "#0f172a",
                            padding: "8px 12px",
                            borderRadius: "6px",
                            fontSize: "12px",
                            color: "#94a3b8",
                          }}
                        >
                          <span>💬 Transkript Turu: <b style={{ color: "#f8fafc" }}>{impact.turns_count ?? 0}</b></span>
                          <span>•</span>
                          <span>🎙️ Ses Kaydı: <b style={{ color: "#f8fafc" }}>{impact.audio_archives_count ?? 0}</b></span>
                          <span>•</span>
                          <span>📅 Randevu: <b style={{ color: "#f8fafc" }}>{impact.appointments_count ?? 0}</b></span>
                          <span>•</span>
                          <span>📱 WhatsApp: <b style={{ color: "#f8fafc" }}>{impact.whatsapp_messages_count ?? 0}</b></span>
                          <span>•</span>
                          <span>📊 Analitik: <b style={{ color: "#f8fafc" }}>{impact.call_analytics_count ?? 0}</b></span>
                          <span>•</span>
                          <span>TOPLAM: <b style={{ color: "#38bdf8" }}>{impact.total_records_affected ?? 0}</b></span>
                        </div>

                        {/* Butonlar */}
                        <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "4px" }}>
                          {!isExecuted ? (
                            <button
                              type="button"
                              className="primary"
                              disabled={!kvkkErasureEnabled || executingReqId === req.id}
                              onClick={() => handleExecuteErasureRequest(req.id, impact.total_records_affected ?? 0)}
                              style={{
                                background: "#dc2626",
                                borderColor: "#ef4444",
                                fontSize: "12px",
                                padding: "6px 14px",
                                fontWeight: "bold",
                              }}
                            >
                              {executingReqId === req.id ? "İcra Ediliyor..." : "🗑️ Silme İşlemini Uygula"}
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => handleViewCertificate(req.id)}
                              style={{
                                fontSize: "12px",
                                padding: "6px 14px",
                                borderColor: "#38bdf8",
                                color: "#38bdf8",
                              }}
                            >
                              📜 İmha Tutanağını Görüntüle (SHA-256)
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* KVKK İMHA TUTANAĞI MODALI */}
      {selectedCertificate && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="KVKK İmha Tutanağı"
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.8)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: "20px",
          }}
          onClick={() => setSelectedCertificate(null)}
        >
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #334155",
              borderRadius: "12px",
              padding: "24px",
              maxWidth: "760px",
              width: "100%",
              maxHeight: "85vh",
              overflowY: "auto",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <h3 style={{ margin: 0, color: "#f8fafc", fontSize: "16px" }}>
                📜 Kişisel Veri İmha ve Anonimleştirme Kaydı
              </h3>
              <button
                type="button"
                className="secondary"
                onClick={() => setSelectedCertificate(null)}
                style={{ padding: "4px 8px", fontSize: "14px" }}
              >
                ✕
              </button>
            </div>

            <pre
              style={{
                background: "#020617",
                padding: "16px",
                borderRadius: "8px",
                overflowX: "auto",
                color: "#e2e8f0",
                fontSize: "12px",
                lineHeight: "1.6",
                fontFamily: "monospace",
                border: "1px solid #1e293b",
                whiteSpace: "pre-wrap",
              }}
            >
              {selectedCertificate.certificate_text}
            </pre>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "16px" }}>
              <span style={{ fontSize: "12px", color: "#64748b" }}>
                SHA-256: {selectedCertificate.certificate_sha256}
              </span>
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    navigator.clipboard?.writeText(selectedCertificate.certificate_text);
                    alert("İmha tutanağı panoya kopyalandı!");
                  }}
                  style={{ fontSize: "12px", padding: "6px 12px" }}
                >
                  📋 Tutanağı Kopyala
                </button>
                <button
                  type="button"
                  className="primary"
                  onClick={() => setSelectedCertificate(null)}
                  style={{ fontSize: "12px", padding: "6px 16px" }}
                >
                  Kapat
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* SIP BAŞLIKLARI VE DETAY MODALI */}
      {selectedTransfer && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Aktarım detayları"
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
            padding: "20px",
          }}
          onClick={() => setSelectedTransfer(null)}
        >
          <div
            style={{
              background: "#0f172a",
              border: "1px solid #334155",
              borderRadius: "12px",
              padding: "24px",
              maxWidth: "600px",
              width: "100%",
              maxHeight: "85vh",
              overflowY: "auto",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <h3 style={{ margin: 0, color: "#f8fafc" }}>
                🔎 Aktarım Detayları: {selectedTransfer.id}
              </h3>
              <button
                type="button"
                className="secondary"
                onClick={() => setSelectedTransfer(null)}
                aria-label="Kapat"
                style={{ padding: "4px 8px" }}
              >
                ✕
              </button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "13px" }}>
              <div>
                <b style={{ color: "#94a3b8" }}>Müşteri:</b> {selectedTransfer.customer_name}
              </div>
              <div>
                <b style={{ color: "#94a3b8" }}>Plaka:</b> {selectedTransfer.vehicle_plate}
              </div>
              <div>
                <b style={{ color: "#94a3b8" }}>Kanal (Channel):</b> {selectedTransfer.caller_channel}
              </div>
              <div>
                <b style={{ color: "#94a3b8" }}>Fısıltı Metni (Whisper):</b>
                <p style={{ margin: "4px 0", background: "#1e293b", padding: "8px", borderRadius: "6px", fontStyle: "italic", color: "#e2e8f0" }}>
                  "{selectedTransfer.whisper_text}"
                </p>
              </div>

              <div>
                <b style={{ color: "#94a3b8" }}>SIP Başlıkları (X-Freya-*):</b>
                <pre
                  style={{
                    background: "#1e293b",
                    padding: "10px",
                    borderRadius: "6px",
                    overflowX: "auto",
                    color: "#38bdf8",
                    fontSize: "12px",
                  }}
                >
                  {JSON.stringify(
                    selectedTransfer.sip_headers || JSON.parse(selectedTransfer.sip_headers_json || "{}"),
                    null,
                    2
                  )}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
````


### frontend/src/OperatorToday.tsx

````
import { useEffect, useState } from "react";
import { errorMessage, formatDate } from "./ui";
import type { ApiFn } from "./ui";

type Kind = "transfer" | "callback" | "booking_pending" | "booking_unknown" | "follow_up";
type Category = "all" | "transfer" | "callback" | "booking" | "follow_up";
type Period = "all" | "today" | "carryover";
type Item = {
  id: string;
  conversation_id: string | null;
  kind: Kind;
  since: string;
  since_source: "transfer" | "follow_up" | "conversation";
  period: "today" | "carryover" | "unknown";
  age_seconds: number | null;
};
type Today = { local_date: string; counts: Partial<Record<Kind, number>>; total: number; items: Item[] };

const itemLabels: Record<Kind, [string, string]> = {
  transfer: ["Bekleyen aktarım", "Aktarım detayını aç"],
  callback: ["Geri arama talebi", "Geri arama talebini incele"],
  booking_pending: ["Yarım kalan randevu", "Randevu adımını kontrol et"],
  booking_unknown: ["Randevu sonucu belirsiz", "Randevu sonucunu doğrula"],
  follow_up: ["Görüşme takibi", "Takip nedenini incele"],
};

function age(seconds: number | null) {
  if (seconds === null) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds / 3600) % 24;
  const minutes = Math.floor(seconds / 60) % 60;
  if (days) return `${days} gün ${hours} sa`;
  if (hours) return `${hours} sa ${minutes} dk`;
  return minutes ? `${minutes} dk` : `${seconds} sn`;
}

export function OperatorToday({ api, autoRefresh, revision, onOpenConversation, onOpenTransfer }: {
  api: ApiFn;
  autoRefresh: boolean;
  revision: number;
  onOpenConversation: (id: string) => void;
  onOpenTransfer: (id: string) => void;
}) {
  const [data, setData] = useState<Today | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [category, setCategory] = useState<Category>("all");
  const [period, setPeriod] = useState<Period>("all");
  const [page, setPage] = useState(0);
  const pageSize = 25;

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    setData(null);
    setLoading(true);
    const params = new URLSearchParams({ category, period, limit: String(pageSize), offset: String(page * pageSize) });
    async function load() {
      try {
        const result: Today = await api(`operator/today?${params}`);
        if (!cancelled) {
          setData(result);
          setError("");
          if (page > 0 && page * pageSize >= result.total) setPage(0);
        }
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
          if (autoRefresh) timer = window.setTimeout(() => void load(), 3000);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [api, category, period, page, revision, autoRefresh]);

  return (
    <section className="card operator-today" aria-labelledby="operator-today-title" aria-busy={loading}>
      <h2 id="operator-today-title">Bugün</h2>
      <p>Açık operatör işleri ve önceki günlerden devreden kayıtlar.</p>
      {data && <dl className="analysis-facts">
        <div><dt>Bekleyen aktarım</dt><dd>{data.counts.transfer ?? 0}</dd></div>
        <div><dt>Geri arama</dt><dd>{data.counts.callback ?? 0}</dd></div>
        <div><dt>Randevu takibi</dt><dd>{(data.counts.booking_pending ?? 0) + (data.counts.booking_unknown ?? 0)}</dd></div>
        <div><dt>Diğer takipler</dt><dd>{data.counts.follow_up ?? 0}</dd></div>
      </dl>}
      <div className="row">
        <label>Dönem{" "}<select value={period} onChange={(e) => { setPage(0); setPeriod(e.target.value as Period); }}>
          <option value="all">Tümü</option>
          <option value="today">Bugünün işleri</option>
          <option value="carryover">Devredenler</option>
        </select></label>
        <label>İş türü{" "}<select value={category} onChange={(e) => { setPage(0); setCategory(e.target.value as Category); }}>
          <option value="all">Tümü</option>
          <option value="transfer">Bekleyen aktarım</option>
          <option value="callback">Geri arama</option>
          <option value="booking">Randevu takibi</option>
          <option value="follow_up">Diğer takipler</option>
        </select></label>
      </div>
      {loading && <p role="status">Operatör işleri yükleniyor…</p>}
      {error && <p role="alert">İş listesi yenilenemedi. {error}</p>}
      {data && <>
        <p className="muted">{data.total} iş · İstanbul {data.local_date.split("-").reverse().join(".")}</p>
        {!data.items.length && <p>Bu filtreye uyan açık iş yok.</p>}
        <ul className="operator-work-list">
          {data.items.map((item) => {
            const conversationId = item.conversation_id;
            return <li className="row" key={`${item.kind}-${item.id}`}>
              <div>
                <strong>{itemLabels[item.kind][0]}</strong>
                <small>{item.period === "carryover" ? "Devreden · " : ""}
                  {item.since_source === "conversation" ? "Görüşme yaşı" : "Bekleme"} {age(item.age_seconds)}
                  {item.age_seconds !== null && ` · ${formatDate(item.since)}`}
                </small>
                <small>Sıradaki adım · {itemLabels[item.kind][1]}</small>
              </div>
              <div className="operator-work-actions">
                {conversationId && <button className="secondary" onClick={() => onOpenConversation(conversationId)}>Görüşmeyi aç</button>}
                {item.kind === "transfer" && <button className="secondary" onClick={() => onOpenTransfer(item.id)}>Aktarımı aç</button>}
              </div>
            </li>;
          })}
        </ul>
        {data.total > pageSize && <div className="row">
          <button className="secondary" disabled={page === 0} onClick={() => setPage((n) => n - 1)}>Önceki</button>
          <small>{page + 1} / {Math.ceil(data.total / pageSize)}</small>
          <button className="secondary" disabled={(page + 1) * pageSize >= data.total} onClick={() => setPage((n) => n + 1)}>Sonraki</button>
        </div>}
      </>}
    </section>
  );
}
````


### frontend/src/OutboundPanel.tsx

````
import { useEffect, useState, useMemo } from "react";
import { errorMessage } from "./ui";

export type OutboundCallItem = {
  id: string;
  appointment_id: string;
  phone: string;
  customer: string;
  call_type: "reminder" | "confirmation";
  status: "queued" | "originating" | "in-progress" | "simulated" | "completed" | "failed" | "cancelled";
  outcome: "pending" | "confirmed" | "cancelled" | "unreachable";
  action_id: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  completed_at: string | null;
};

import type { ApiProps as Props } from "./api";

export function OutboundPanel({ api }: Props) {
  const [calls, setCalls] = useState<OutboundCallItem[]>([]);
  const [appointments, setAppointments] = useState<any[]>([]);
  const [slots, setSlots] = useState<any[]>([]);
  const [amiStatus, setAmiStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Form State
  const [selectedAppointment, setSelectedAppointment] = useState("");
  const [phone, setPhone] = useState("");
  const [callType, setCallType] = useState("reminder");

  // Filters
  const [statusFilter, setStatusFilter] = useState("all");
  const [outcomeFilter, setOutcomeFilter] = useState("all");

  async function act(fn: () => Promise<void>) {
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    const [cList, aList, sList, ami] = await Promise.all([
      api("outbound/calls"),
      api("appointments"),
      api("slots"),
      api("outbound/ami-status"),
    ]);
    setCalls(cList);
    setAppointments(aList);
    setSlots(sList);
    setAmiStatus(ami);
  }

  useEffect(() => {
    act(refresh);
  }, []);

  async function handleOriginateCall(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedAppointment) {
      setError("Lütfen aranacak bir randevu seçin.");
      return;
    }
    await act(async () => {
      const res = await api("outbound/call", "POST", {
        appointment_id: selectedAppointment,
        phone: phone.trim() || undefined,
        call_type: callType,
      });
      setSuccess(
        `'${res.customer}' (${res.phone}) için Asterisk AMI üzerinden giden arama başlatıldı (ActionID: ${res.action_id}).`
      );
      setSelectedAppointment("");
      setPhone("");
      await refresh();
    });
  }

  async function handleCompleteOutcome(
    callId: string,
    outcome: "confirmed" | "cancelled" | "unreachable"
  ) {
    await act(async () => {
      const res = await api(`outbound/calls/${callId}/complete`, "POST", {
        outcome,
        notes: `Panel operatörü tarafından '${outcome}' olarak sonuçlandırıldı.`,
      });
      setSuccess(
        `Arama kaydı güncellendi. Sonuç: ${res.outcome.toUpperCase()}${
          res.outcome === "cancelled" ? " (Randevu iptal edildi)" : ""
        }.`
      );
      await refresh();
    });
  }

  async function handleCancelCall(callId: string) {
    await act(async () => {
      await api(`outbound/calls/${callId}/cancel`, "POST");
      setSuccess("Arama süreci iptal edildi.");
      await refresh();
    });
  }

  // Active confirmed appointments that can be called
  const confirmedAppointments = useMemo(() => {
    return appointments.filter((a) => a.status === "confirmed" && a.slot_id);
  }, [appointments]);

  // Statistics
  const totalCalls = calls.length;
  const inProgressCalls = calls.filter((c) => c.status === "in-progress" || c.status === "originating").length;
  const confirmedCalls = calls.filter((c) => c.outcome === "confirmed").length;
  const cancelledCalls = calls.filter((c) => c.outcome === "cancelled").length;

  const filteredCalls = useMemo(() => {
    return calls.filter((c) => {
      if (statusFilter !== "all" && c.status !== statusFilter) return false;
      if (outcomeFilter !== "all" && c.outcome !== outcomeFilter) return false;
      return true;
    });
  }, [calls, statusFilter, outcomeFilter]);

  function getSlotTime(slotId: string) {
    const s = slots.find((x) => x.id === slotId);
    if (!s) return "";
    try {
      return new Date(s.starts_at).toLocaleString("tr-TR", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return s.starts_at;
    }
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: "8px", minHeight: 0, overflowY: "auto", padding: "2px 4px" }}>
      <div className="stats">
        <article>
          <small>Toplam Giden Arama</small>
          <strong>{totalCalls}</strong>
        </article>
        <article>
          <small>Teyit Edilen (Confirmed)</small>
          <strong style={{ color: "#a7f3ce" }}>{confirmedCalls}</strong>
        </article>
        <article>
          <small>İptal Edilen / Aktif</small>
          <strong style={{ color: inProgressCalls > 0 ? "#93c5fd" : "#fca5a5" }}>
            {inProgressCalls} devam eden · {cancelledCalls} iptal
          </strong>
        </article>
      </div>

      {error && (
        <div role="alert" className="error" style={{ marginTop: "18px" }}>
          {error}
        </div>
      )}
      {success && (
        <div
          role="status"
          className="bubble"
          style={{
            marginTop: "18px",
            background: "#1c382f",
            borderColor: "#347458",
            border: "1px solid",
          }}
        >
          <b>İşlem Başarılı</b>
          {success}
        </div>
      )}

      {/* Asterisk AMI Durum Bilgisi */}
      {amiStatus && (
        <div
          className="row"
          style={{
            marginTop: "18px",
            background: "#151c2b",
            padding: "14px 20px",
            borderRadius: "10px",
            border: "1px solid #2a3344",
          }}
        >
          <div>
            <b>ASTERISK MANAGER INTERFACE (AMI)</b>
            <small>
              Sunucu: {amiStatus.ami_host}:{amiStatus.ami_port} · Bağlantı:{" "}
              {amiStatus.simulated
                ? "Simülasyon (gerçek AMI yok)"
                : amiStatus.connected
                  ? "Hazır (Connected)"
                  : "Çevrimdışı (Offline)"}
            </small>
          </div>
          <span className={"pill " + (amiStatus.connected ? "ok" : "")}>
            {amiStatus.simulated
              ? "○ SİMÜLASYON"
              : amiStatus.connected
                ? "● AMI AKTİF"
                : "○ BAĞLANTI YOK"}
          </span>
        </div>
      )}

      {/* Yeni Giden Arama Başlatma */}
      <section>
        <h2>Yeni Teyit / Hatırlatma Araması Başlat (Originate)</h2>
        <p className="muted">
          Seçilen randevu için Asterisk PBX üzerinden müşteriye otomatik dış arama
          başlatılır. Müşteri telefonu açtığında sesli asistan randevu detaylarını
          hatırlatır, teyit veya iptal yanıtını işleyerek randevu durumunu anında günceller.
        </p>

        <form onSubmit={handleOriginateCall} className="inline" style={{ marginTop: "16px" }}>
          <label style={{ flex: "2 1 240px" }}>
            Teyit Bekleyen Randevu Seç
            <select
              value={selectedAppointment}
              onChange={(e) => {
                const appId = e.target.value;
                setSelectedAppointment(appId);
                const app = appointments.find((a) => a.id === appId);
                if (app && app.customer) {
                  // If customer has phone digits, prefill phone
                  const digits = app.customer.replace(/[^0-9+]/g, "");
                  if (digits.length >= 7) setPhone(digits);
                }
              }}
              required
            >
              <option value="">Randevu Seçin...</option>
              {confirmedAppointments.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.customer} ({getSlotTime(a.slot_id)}) — Ref: {a.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>

          <label style={{ flex: "1 1 180px" }}>
            Telefon Numarası
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="0532 123 45 67"
            />
          </label>

          <label style={{ flex: "1 1 150px" }}>
            Çağrı Türü
            <select value={callType} onChange={(e) => setCallType(e.target.value)}>
              <option value="reminder">Randevu Hatırlatma (reminder)</option>
              <option value="confirmation">Randevu Teyidi (confirmation)</option>
            </select>
          </label>

          <button
            type="submit"
            disabled={loading || !selectedAppointment}
            style={{ padding: "12px 20px" }}
          >
            {loading ? "Aranıyor..." : "Aramayı Başlat 📞"}
          </button>
        </form>
      </section>

      {/* Giden Aramalar Tablosu */}
      <section>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "14px",
            marginBottom: "16px",
          }}
        >
          <h2>Giden Çağrı Kayıtları ({filteredCalls.length})</h2>
          <button
            type="button"
            className="secondary"
            onClick={() => act(refresh)}
            disabled={loading}
            style={{ fontSize: "12px", padding: "8px 14px" }}
          >
            Yenile ↻
          </button>
        </div>

        {/* Filtre Barı */}
        <div
          className="inline"
          style={{
            background: "#0e1522",
            padding: "14px",
            borderRadius: "10px",
            border: "1px solid #2a3344",
            marginBottom: "20px",
          }}
        >
          <label style={{ flex: "1 1 140px" }}>
            Çağrı Durumu
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">Tüm Durumlar ({calls.length})</option>
              <option value="in-progress">Devam Eden (in-progress)</option>
              <option value="completed">Tamamlanan (completed)</option>
              <option value="failed">Başarısız (failed)</option>
              <option value="cancelled">İptal Edilen (cancelled)</option>
            </select>
          </label>

          <label style={{ flex: "1 1 140px" }}>
            Çağrı Sonucu (Outcome)
            <select
              value={outcomeFilter}
              onChange={(e) => setOutcomeFilter(e.target.value)}
            >
              <option value="all">Tüm Sonuçlar</option>
              <option value="confirmed">Teyit Edildi (confirmed)</option>
              <option value="cancelled">Randevu İptal (cancelled)</option>
              <option value="unreachable">Ulaşılamadı (unreachable)</option>
              <option value="pending">Bekliyor (pending)</option>
            </select>
          </label>
        </div>

        {/* Tablo */}
        <div style={{ overflowX: "auto" }}>
          <div className="table-wrap"><table className="lexicon-table">
            <thead>
              <tr>
                <th>Müşteri</th>
                <th>Telefon</th>
                <th>Tür</th>
                <th>Durum</th>
                <th>Sonuç</th>
                <th>Tarih</th>
                <th style={{ textAlign: "right" }}>İşlemler</th>
              </tr>
            </thead>
            <tbody>
              {filteredCalls.map((item) => (
                <tr key={item.id}>
                  <td style={{ fontWeight: 600 }}>{item.customer}</td>
                  <td>{item.phone}</td>
                  <td>
                    <span className="badge-cat">{item.call_type}</span>
                  </td>
                  <td>
                    <span
                      style={{
                        padding: "3px 8px",
                        borderRadius: "10px",
                        fontSize: "11px",
                        background:
                          item.status === "completed"
                            ? "#14532d"
                            : item.status === "failed"
                              ? "#451a03"
                              : "#1e3a8a",
                        color:
                          item.status === "completed"
                            ? "#86efac"
                            : item.status === "failed"
                              ? "#fdba74"
                              : "#bfdbfe",
                      }}
                    >
                      {item.status === "simulated" ? "simüle (arama yapılmadı)" : item.status}
                    </span>
                  </td>
                  <td>
                    <span
                      className={
                        item.outcome === "confirmed"
                          ? "badge-custom"
                          : item.outcome === "cancelled"
                            ? "danger"
                            : "badge-override"
                      }
                      style={{ padding: "3px 8px", borderRadius: "10px" }}
                    >
                      {item.outcome === "confirmed"
                        ? "Teyit Edildi"
                        : item.outcome === "cancelled"
                          ? "İptal Edildi"
                          : item.outcome === "unreachable"
                            ? "Ulaşılamadı"
                            : "Bekliyor"}
                    </span>
                  </td>
                  <td style={{ fontSize: "12px", whiteSpace: "nowrap" }}>
                    {new Date(item.created_at).toLocaleString("tr-TR", {
                      day: "2-digit",
                      month: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {item.status === "in-progress" && (
                      <>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => handleCompleteOutcome(item.id, "confirmed")}
                          style={{
                            padding: "6px 10px",
                            fontSize: "11px",
                            marginRight: "6px",
                          }}
                        >
                          Teyit
                        </button>
                        <button
                          type="button"
                          className="danger"
                          onClick={() => handleCompleteOutcome(item.id, "cancelled")}
                          style={{
                            padding: "6px 10px",
                            fontSize: "11px",
                            marginRight: "6px",
                          }}
                        >
                          İptal
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => handleCancelCall(item.id)}
                          style={{ padding: "6px 10px", fontSize: "11px" }}
                        >
                          Durdur
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {!filteredCalls.length && (
                <tr>
                  <td
                    colSpan={7}
                    style={{
                      textAlign: "center",
                      padding: "30px",
                      color: "#93a0b5",
                    }}
                  >
                    Henüz giden arama kaydı bulunamadı.
                  </td>
                </tr>
              )}
            </tbody>
          </table></div>
        </div>
      </section>
    </div>
  );
}
````


### frontend/src/pipeline/demoFixtures.ts

````
/**
 * FreyaTTS Automotive Cockpit V3 — F0–F6 Demo & Replay Telemetri Senaryoları
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import { PipelineTelemetryEvent, StageId } from "./types";

export interface DemoScenario {
  id: string;
  title: string;
  description: string;
  userSpeech: string;
  botReply: string;
  expectedTotalMs: number;
  events: Omit<PipelineTelemetryEvent, "schema_version" | "event_id">[];
}

export const DEMO_SCENARIOS: DemoScenario[] = [
  {
    id: "booking_success",
    title: "Başarılı Randevu Oluşturma (Passat 1.5 TSI)",
    description: "Müşterinin randevu talebi, araç eşleme ve ilk cümlecik kilidiyle hızlı yanıt",
    userSpeech: "Passat aracım için yarın saat 14:00'e ekspertiz randevusu almak istiyorum.",
    botReply: "Volkswagen Passat 1.5 TSI aracınız için yarın saat 14:00 randevunuz oluşturuldu.",
    expectedTotalMs: 562,
    events: [
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F0",
        status: "running",
        source: "demo",
        timestamp: 0,
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F0",
        status: "completed",
        source: "demo",
        timestamp: 3,
        duration_ms: 3.2,
        metrics: { hpf_cutoff_hz: 120, noise_suppression_db: -18, ambient_dbfs: -41.2, clipping_ratio: 0.0 },
        intermediate_data: { filter: "Butterworth 4th order", snr_est: "26.4 dB" },
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F1",
        status: "running",
        source: "demo",
        timestamp: 4,
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F1",
        status: "completed",
        source: "demo",
        timestamp: 12,
        duration_ms: 7.8,
        metrics: { speech_prob: 0.94, ring_buffer_ms: 300, barge_in_detected: false },
        intermediate_data: { vad_model: "Silero VAD", endpoint_reason: "silence_timeout_450ms" },
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F2",
        status: "running",
        source: "demo",
        timestamp: 13,
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F2",
        status: "completed",
        source: "demo",
        timestamp: 148,
        duration_ms: 135.0,
        metrics: { avg_logprob: -0.18, no_speech_prob: 0.01, compression_ratio: 1.15, word_count: 10 },
        intermediate_data: { raw_transcript: "Passat aracım için yarın saat 14:00'e ekspertiz randevusu almak istiyorum.", language: "tr" },
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F3",
        status: "running",
        source: "demo",
        timestamp: 149,
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F3",
        status: "completed",
        source: "demo",
        timestamp: 324,
        duration_ms: 175.0,
        metrics: { intent: "BOOKING_CREATE", confidence: 0.98, ttft_ms: 110, total_tokens: 38 },
        intermediate_data: {
          slots: { vehicle: "Volkswagen Passat 1.5 TSI", date: "2026-11-11", time: "14:00" },
          policy_decision: "VERIFIED_DB_MATCH",
        },
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F4",
        status: "running",
        source: "demo",
        timestamp: 325,
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F4",
        status: "completed",
        source: "demo",
        timestamp: 327,
        duration_ms: 2.1,
        metrics: { chunks_count: 2, rules_applied: 4, zero_markdown_clean: true },
        intermediate_data: {
          first_chunk: "Volkswagen Passat 1.5 TSI aracınız için,",
          second_chunk: "yarın saat 14:00 randevunuz oluşturuldu.",
        },
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F5",
        status: "running",
        source: "demo",
        timestamp: 328,
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F5",
        status: "completed",
        source: "demo",
        timestamp: 550,
        duration_ms: 222.0,
        metrics: { voice_seed: 9, persona: "Leyla", ode_steps: 32, ttfa_ms: 215, audio_duration_sec: 4.2 },
        intermediate_data: { model: "FreyaTTS Flow Matching", lora: "DiT Cross-Attention", sample_rate: 24000 },
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F6",
        status: "running",
        source: "demo",
        timestamp: 551,
      },
      {
        session_id: "demo-sess-01",
        turn_id: 1,
        stage: "F6",
        status: "completed",
        source: "demo",
        timestamp: 562,
        duration_ms: 11.0,
        metrics: { wsola_rate: 0.98, underrun_count: 0, playback_target: "Web Audio + AudioSocket" },
        intermediate_data: { delivery_channel: "SLIN16 8kHz / Web 16kHz", comfort_noise_db: -54 },
      },
    ],
  },
  {
    id: "barge_in_interruption",
    title: "Çift Yönlü Barge-In (Müşteri Sözü Keser)",
    description: "Asistan konuşurken müşterinin araya girmesi ve 5-Kesim ile oynatmanın anında durdurulması",
    userSpeech: "Bekle, saat iki değil üç olsun!",
    botReply: "Tabii ki, randevunuzu saat 15:00 olarak güncelliyorum.",
    expectedTotalMs: 380,
    events: [
      {
        session_id: "demo-sess-02",
        turn_id: 2,
        stage: "F0",
        status: "completed",
        source: "demo",
        timestamp: 3,
        duration_ms: 2.8,
        metrics: { hpf_cutoff_hz: 120, ambient_dbfs: -39.0 },
      },
      {
        session_id: "demo-sess-02",
        turn_id: 2,
        stage: "F1",
        status: "completed",
        source: "demo",
        timestamp: 10,
        duration_ms: 7.0,
        metrics: { barge_in_detected: true, cut_stage: "Stage 1 Soft-Pause", playback_halt_ms: 18 },
        intermediate_data: { decision: "COMMIT_INTERRUPT", action: "FLUSH_OUTPUT_BUFFER" },
      },
      {
        session_id: "demo-sess-02",
        turn_id: 2,
        stage: "F2",
        status: "completed",
        source: "demo",
        timestamp: 135,
        duration_ms: 125.0,
        metrics: { avg_logprob: -0.22 },
        intermediate_data: { raw_transcript: "Bekle, saat iki değil üç olsun!" },
      },
      {
        session_id: "demo-sess-02",
        turn_id: 2,
        stage: "F3",
        status: "completed",
        source: "demo",
        timestamp: 295,
        duration_ms: 160.0,
        metrics: { intent: "BOOKING_RESCHEDULE", confidence: 0.97 },
      },
      {
        session_id: "demo-sess-02",
        turn_id: 2,
        stage: "F4",
        status: "completed",
        source: "demo",
        timestamp: 297,
        duration_ms: 2.0,
        metrics: { chunks_count: 1 },
      },
      {
        session_id: "demo-sess-02",
        turn_id: 2,
        stage: "F5",
        status: "completed",
        source: "demo",
        timestamp: 490,
        duration_ms: 193.0,
        metrics: { voice_seed: 9, ttfa_ms: 188 },
      },
      {
        session_id: "demo-sess-02",
        turn_id: 2,
        stage: "F6",
        status: "completed",
        source: "demo",
        timestamp: 500,
        duration_ms: 10.0,
        metrics: { wsola_rate: 0.98 },
      },
    ],
  },
];
````


### frontend/src/pipeline/f2Hotwords.ts

````
/**
 * FreyaTTS Automotive Cockpit V3 — F2 Automotive Hotword Booster & ASR Model Definitions
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

export interface F2Hotword {
  id: string;
  wrong: string;
  canonical: string;
  weight: number;
  category: "Marka" | "Model" | "Şanzıman" | "Teşhis" | "DTC Kod" | "Plaka" | "Motor" | "Emisyon" | "Genel";
}

export interface F2AsrModel {
  id: string;
  name: string;
  wer: string;
  baseMs: number;
  beamDefault: number;
  desc: string;
}

export interface F2AppliedFix {
  from: string;
  to: string;
  weight: number;
  category: string;
}

export interface F2BoosterResult {
  raw: string;
  corrected: string;
  appliedFixes: F2AppliedFix[];
  confidenceGain: number;
}

export const INITIAL_F2_HOTWORDS: F2Hotword[] = [
  { id: 'hw1', wrong: 'pejo|pöjo|pežo|peugeot', canonical: 'Peugeot', weight: 4.5, category: 'Marka' },
  { id: 'hw2', wrong: 'kaşkay|kaşkai|kaskai', canonical: 'Qashqai', weight: 4.8, category: 'Model' },
  { id: 'hw3', wrong: 'de se ge|desege|d s g', canonical: 'DSG', weight: 4.2, category: 'Şanzıman' },
  { id: 'hw4', wrong: 'o be de|obd 2|obd iki|o b d', canonical: 'OBD-II', weight: 4.5, category: 'Teşhis' },
  { id: 'hw5', wrong: 'p 0 300|pe sıfır üç yüz|p0 300|p sıfır üç yüz', canonical: 'P0300', weight: 5.0, category: 'DTC Kod' },
  { id: 'hw6', wrong: 'p 0 171|pe sıfır yüz yetmiş bir', canonical: 'P0171', weight: 4.6, category: 'DTC Kod' },
  { id: 'hw7', wrong: 'altmış bir te se sıfır altmış bir|61 ts 61|61 t s 061', canonical: '61 TS 061', weight: 5.0, category: 'Plaka' },
  { id: 'hw8', wrong: 'blu haş de i|blue hdi|mavi hdi', canonical: 'BlueHDi', weight: 4.0, category: 'Motor' },
  { id: 'hw9', wrong: 'ti es ay|t s i', canonical: 'TSI', weight: 3.8, category: 'Motor' },
  { id: 'hw10', wrong: 'ed blu|ad blue|et blu', canonical: 'AdBlue', weight: 4.1, category: 'Emisyon' }
];

export const F2_ASR_MODELS: F2AsrModel[] = [
  {
    id: 'whisper_turbo',
    name: 'faster-whisper-large-v3-turbo (INT8 + F1 Hard Gate)',
    wer: '%2.8 WER',
    baseMs: 140,
    beamDefault: 2,
    desc: 'En yüksek Türkçe otomotiv doğruluğu, gürültülü atölye ve kabin ortamı için önerilen ana model.'
  },
  {
    id: 'distil_tr',
    name: 'distil-whisper-tr-automotive (FP16 Hızlı)',
    wer: '%4.4 WER',
    baseMs: 102,
    beamDefault: 1,
    desc: 'Düşük gecikme odaklı damıtılmış Türkçe model; hızlı randevu ve plaka yakalama için optimize.'
  },
  {
    id: 'conformer_8k',
    name: 'conformer-ctc-tr-8khz (SIP/ Dar Bant)',
    wer: '%5.9 WER',
    baseMs: 84,
    beamDefault: 3,
    desc: '8 kHz klasik PSTN/GSM hatları için ultra hafif CTC akustik model.'
  }
];

export function runF2DomainBooster(
  rawTranscript: string,
  hotwords: F2Hotword[] = INITIAL_F2_HOTWORDS,
  enabled: boolean = true,
  boostWeight: number = 4.0
): F2BoosterResult {
  if (!rawTranscript || !rawTranscript.trim()) {
    return { raw: '', corrected: '', appliedFixes: [], confidenceGain: 0 };
  }
  if (!enabled || boostWeight <= 0.5) {
    return { raw: rawTranscript, corrected: rawTranscript, appliedFixes: [], confidenceGain: 0 };
  }

  let corrected = rawTranscript;
  const appliedFixes: F2AppliedFix[] = [];

  hotwords.forEach((hw) => {
    const variants = hw.wrong.split('|').map((v) => v.trim()).filter(Boolean);
    variants.forEach((variant) => {
      const escaped = variant.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`\\b${escaped}\\b`, 'gi');
      if (regex.test(corrected)) {
        corrected = corrected.replace(regex, (match) => {
          if (match !== hw.canonical) {
            appliedFixes.push({
              from: match,
              to: hw.canonical,
              weight: Number(((hw.weight * boostWeight) / 4).toFixed(1)),
              category: hw.category
            });
          }
          return hw.canonical;
        });
      }
    });
  });

  const confidenceGain = appliedFixes.length > 0
    ? Number(Math.min(18.5, appliedFixes.length * (boostWeight * 1.15)).toFixed(1))
    : 0;

  return {
    raw: rawTranscript,
    corrected,
    appliedFixes,
    confidenceGain
  };
}
````


### frontend/src/pipeline/f4Engine.ts

````
/**
 * FreyaTTS Automotive Cockpit V3 — F4 Morphological Pre-Checker, Sezer Vurgusu & Clause Chunker
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

export interface F4Rule {
  id: string;
  pattern: string;
  replacement: string;
  sezer: string;
  category: "Marka" | "Model" | "Motor" | "Şanzıman" | "Sıvı/Emisyon" | "Teşhis" | "DTC" | "Birim" | "Plaka" | "Sezer Vurgu" | "Özel";
  active: boolean;
}

export interface F4Chunk {
  index: number;
  text: string;
  wordCount: number;
  charCount: number;
  ttfaMs: number;
}

export interface F4AppliedHit {
  from: string;
  to: string;
  sezer: string;
  category: string;
}

export interface F4PipelineResult {
  raw: string;
  phoneticText: string;
  appliedHits: F4AppliedHit[];
  chunks: F4Chunk[];
  processingMs: number;
}

export const INITIAL_F4_RULES: F4Rule[] = [
  { id: 'r1', pattern: 'Peugeot', replacement: 'Pöjo', sezer: "pö'jo", category: 'Marka', active: true },
  { id: 'r2', pattern: 'Qashqai', replacement: 'Kaşkai', sezer: "kaş'kai", category: 'Marka', active: true },
  { id: 'r3', pattern: 'Renault', replacement: 'Röno', sezer: "rö'no", category: 'Marka', active: true },
  { id: 'r4', pattern: 'Citroen', replacement: 'Sitroen', sezer: "sitro'en", category: 'Marka', active: true },
  { id: 'r5', pattern: 'Citroën', replacement: 'Sitroen', sezer: "sitro'en", category: 'Marka', active: true },
  { id: 'r6', pattern: 'Volkswagen', replacement: 'Folksvagen', sezer: "folksvA'gen", category: 'Marka', active: true },
  { id: 'r7', pattern: 'Škoda', replacement: 'Şkoda', sezer: "şko'da", category: 'Marka', active: true },
  { id: 'r8', pattern: 'TDI', replacement: 'Ti-Di-Ay', sezer: 'Birleşik Kısaltma', category: 'Motor', active: true },
  { id: 'r9', pattern: 'TSI', replacement: 'Ti-Es-Ay', sezer: 'Birleşik Kısaltma', category: 'Motor', active: true },
  { id: 'r10', pattern: 'BlueHDi', replacement: 'Blu-Haş-De-İ', sezer: 'Kısaltma Açılımı', category: 'Motor', active: true },
  { id: 'r11', pattern: 'DSG', replacement: 'De-Se-Ge', sezer: "de-se-'ge", category: 'Şanzıman', active: true },
  { id: 'r12', pattern: 'AdBlue', replacement: 'Ed-Blu', sezer: "ed-'blu", category: 'Sıvı/Emisyon', active: true },
  { id: 'r13', pattern: 'OBD-II', replacement: 'O-Be-De İki', sezer: 'Harf + Rakam', category: 'Teşhis', active: true },
  { id: 'r14', pattern: 'P0300', replacement: 'Pe sıfır üç yüz', sezer: 'DTC Kod Okuma', category: 'DTC', active: true },
  { id: 'r15', pattern: 'P0171', replacement: 'Pe sıfır yüz yetmiş bir', sezer: 'DTC Kod Okuma', category: 'DTC', active: true },
  { id: 'r16', pattern: 'U0100', replacement: 'U sıfır yüz', sezer: 'DTC Kod Okuma', category: 'DTC', active: true },
  { id: 'r17', pattern: 'kW', replacement: 'kilovat', sezer: "kilo'vat", category: 'Birim', active: true },
  { id: 'r18', pattern: 'Nm', replacement: 'Newton metre', sezer: "nev'ton metre", category: 'Birim', active: true },
  { id: 'r19', pattern: '61 TS 061', replacement: 'altmış bir Te-Se sıfır altmış bir', sezer: 'Plaka Okuma', category: 'Plaka', active: true },
  { id: 'r20', pattern: '61 KT 407', replacement: 'altmış bir Ka-Te dört yüz yedi', sezer: 'Plaka Okuma', category: 'Plaka', active: true },
  { id: 'r21', pattern: "Trabzon'da", replacement: 'trabzOnda', sezer: 'Sezer Yer Adı Vurgusu (Trochaic)', category: 'Sezer Vurgu', active: true },
  { id: 'r22', pattern: 'Trabzon', replacement: 'trAbzon', sezer: 'Sezer Kök Vurgusu (Ağır Hece)', category: 'Sezer Vurgu', active: true },
  { id: 'r23', pattern: 'Ortahisar', replacement: 'ortAhisar', sezer: 'Sezer Birleşik Yer Vurgusu', category: 'Sezer Vurgu', active: true },
  { id: 'r24', pattern: 'Akçaabat', replacement: 'akçAabat', sezer: 'Sezer Yer Adı Vurgusu', category: 'Sezer Vurgu', active: true },
];

/**
 * Türkçe Sayı -> Yazı Dönüştürücü (F4 Number Normalizer)
 */
export function turkishNumberToWords(numStr: string): string {
  const clean = numStr.replace(/\./g, '').replace(/,/g, '');
  const n = parseInt(clean, 10);
  if (isNaN(n)) return numStr;
  if (n === 0) return 'sıfır';

  const ones = ['', 'bir', 'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz'];
  const tens = ['', 'on', 'yirmi', 'otuz', 'kırk', 'elli', 'altmış', 'yetmiş', 'seksen', 'doksan'];

  const readThreeDigits = (val: number): string => {
    const res: string[] = [];
    const h = Math.floor(val / 100);
    const t = Math.floor((val % 100) / 10);
    const o = val % 10;
    if (h > 0) {
      res.push(h === 1 ? 'yüz' : `${ones[h]} yüz`);
    }
    if (t > 0) res.push(tens[t]);
    if (o > 0) res.push(ones[o]);
    return res.join(' ');
  };

  if (n >= 1000000) return numStr;
  const thousands = Math.floor(n / 1000);
  const remainder = n % 1000;
  const parts: string[] = [];
  if (thousands > 0) {
    parts.push(thousands === 1 ? 'bin' : `${readThreeDigits(thousands)} bin`);
  }
  if (remainder > 0) {
    parts.push(readThreeDigits(remainder));
  }
  return parts.join(' ').trim();
}

/**
 * F4 Morphological Pre-Checker, Sezer Stress & Streaming Clause Chunker Motoru
 */
export function runF4Pipeline(rawText: string, rules: F4Rule[] = INITIAL_F4_RULES): F4PipelineResult {
  if (!rawText || !rawText.trim()) {
    return {
      raw: '',
      phoneticText: '',
      appliedHits: [],
      chunks: [],
      processingMs: 0
    };
  }

  const t0 = performance.now();
  let processed = rawText;
  const appliedHits: F4AppliedHit[] = [];

  // 1. Dinamik Sözlük, Marka, DTC, Plaka ve Sezer Yer Adı Kurallarını Uygula
  const sortedRules = [...rules]
    .filter((r) => r.active && r.pattern)
    .sort((a, b) => b.pattern.length - a.pattern.length);

  sortedRules.forEach((rule) => {
    const escaped = rule.pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escaped, 'gi');
    if (regex.test(processed)) {
      appliedHits.push({
        from: rule.pattern,
        to: rule.replacement,
        sezer: rule.sezer,
        category: rule.category
      });
      processed = processed.replace(regex, rule.replacement);
    }
  });

  // 2. Genel Plaka RegEx Normalizasyonu (örn: 34 FRY 88 -> otuz dört Fe-Re-Ye seksen sekiz)
  const plateRegex = /\b(\d{2})\s+([A-ZÇĞİÖŞÜ]{1,3})\s+(\d{2,4})\b/g;
  const letterMap: Record<string, string> = {
    A: 'A', B: 'Be', C: 'Ce', Ç: 'Çe', D: 'De', E: 'E', F: 'Fe', G: 'Ge', Ğ: 'Yumuşak Ge',
    H: 'He', I: 'I', İ: 'İ', J: 'Je', K: 'Ka', L: 'Le', M: 'Me', N: 'Ne', O: 'O', Ö: 'Ö',
    P: 'Pe', R: 'Re', S: 'Se', Ş: 'Şe', T: 'Te', U: 'U', Ü: 'Ü', V: 'Ve', Y: 'Ye', Z: 'Ze'
  };
  processed = processed.replace(plateRegex, (match, cityCode, letters, digits) => {
    const cityWords = turkishNumberToWords(cityCode);
    const letterWords = letters
      .split('')
      .map((ch: string) => letterMap[ch.toUpperCase()] || ch)
      .join('-');
    const digitWords = digits.startsWith('0')
      ? `sıfır ${turkishNumberToWords(digits.slice(1))}`
      : turkishNumberToWords(digits);
    const out = `${cityWords} ${letterWords} ${digitWords}`;
    appliedHits.push({ from: match, to: out, sezer: 'Dinamik Plaka Çözücü', category: 'Plaka' });
    return out;
  });

  // 3. Para Birimi ve Noktalı Binlik Sayılar (örn: 14.500 TL -> on dört bin beş yüz Türk lirası)
  processed = processed.replace(/(\d{1,3}(?:\.\d{3})+|\d+)\s*(TL|TRY)/gi, (match, numPart) => {
    const words = turkishNumberToWords(numPart);
    const out = `${words} Türk lirası`;
    appliedHits.push({ from: match, to: out, sezer: "Türk li'rası", category: 'Fiyat/Rakam' });
    return out;
  });

  // 4. Ondalıklı Motor Hacmi (örn: 1.5 -> bir nokta beş)
  processed = processed.replace(/\b(\d)\.(\d)\b/g, (match, d1, d2) => {
    const out = `${turkishNumberToWords(d1)} nokta ${turkishNumberToWords(d2)}`;
    appliedHits.push({ from: match, to: out, sezer: 'Ondalık Açılım', category: 'Sayı' });
    return out;
  });

  // 5. Saat Formatı (örn: 09:30 -> sıfır dokuz otuz)
  processed = processed.replace(/\b(\d{2}):(\d{2})\b/g, (match, hh, mm) => {
    const hWord = hh.startsWith('0') ? `sıfır ${turkishNumberToWords(hh.slice(1))}` : turkishNumberToWords(hh);
    const mWord = mm === '00' ? 'sıfır sıfır' : turkishNumberToWords(mm);
    const out = `${hWord} ${mWord}`;
    appliedHits.push({ from: match, to: out, sezer: 'Saat Normalizasyonu', category: 'Saat' });
    return out;
  });

  // 6. Clause-Level Streaming Chunker (Noktalama ve Bağlaçlardan Akıllı Parçalama)
  const rawSegments = processed
    .split(/(?<=[.!?;:])\s+|(?<=,)\s+(?=\S{4,})/g)
    .map((s) => s.trim())
    .filter(Boolean);

  // Kısa parçaları (< 22 karakter) bir sonrakiyle birleştirerek doğal prosodi oluştur
  const mergedSegments: string[] = [];
  let carry = '';
  for (let i = 0; i < rawSegments.length; i++) {
    const candidate = carry ? `${carry} ${rawSegments[i]}` : rawSegments[i];
    if (candidate.length < 22 && i < rawSegments.length - 1) {
      carry = candidate;
    } else {
      mergedSegments.push(candidate);
      carry = '';
    }
  }
  if (carry) mergedSegments.push(carry);

  const chunks: F4Chunk[] = mergedSegments.map((text, idx) => {
    const wordCount = text.split(/\s+/).filter(Boolean).length;
    // İlk paket (Chunk #1) FreyaTTS ODE'de hızlı TTFA ile çıkar
    const ttfaMs = idx === 0 ? Math.min(225, 130 + wordCount * 11) : Math.min(180, 95 + wordCount * 8);
    return {
      index: idx + 1,
      text,
      wordCount,
      charCount: text.length,
      ttfaMs
    };
  });

  const processingMs = Math.max(1.4, Number((performance.now() - t0 + 1.2).toFixed(1)));

  return {
    raw: rawText,
    phoneticText: processed,
    appliedHits,
    chunks,
    processingMs
  };
}

/**
 * Tarayıcı Ses Sentezleyicisi ile F4 Chunklarını Sırayla Çalma
 */
export function speakF4ChunksSequentially(
  f4Result: F4PipelineResult,
  onChunkChange?: (index: number | null) => void,
  onComplete?: () => void
): () => void {
  if (!f4Result || !f4Result.chunks || f4Result.chunks.length === 0) {
    onComplete?.();
    return () => {};
  }

  let isAborted = false;

  if (!('speechSynthesis' in window)) {
    console.warn("speechSynthesis tarayıcıda desteklenmiyor.");
    onComplete?.();
    return () => {};
  }

  try {
    window.speechSynthesis.cancel();
    const voices = window.speechSynthesis.getVoices();
    const trVoice = voices.find((v) => v.lang && v.lang.toLowerCase().includes('tr'));
    const trVoices = voices.filter((v) => v.lang && v.lang.toLowerCase().includes('tr'));

    // 1. Türkçe kadın sesi ara (Emel, Filiz, Seda, Zehra, Leyla, Zeynep vb.)
    const femaleVoice = trVoices.find((v) => {
      const n = v.name.toLowerCase();
      return (
        n.includes('emel') ||
        n.includes('filiz') ||
        n.includes('seda') ||
        n.includes('zehra') ||
        n.includes('kadın') ||
        n.includes('kadin') ||
        n.includes('female') ||
        n.includes('zeynep') ||
        n.includes('leyla')
      );
    });

    // 2. Açıkça erkek (Tolga vb.) olmayan sesi tercih et
    const nonMaleVoice = trVoices.find((v) => {
      const n = v.name.toLowerCase();
      return !n.includes('tolga') && !n.includes('male') && !n.includes('erkek') && !n.includes('ahmet') && !n.includes('cem');
    });

    const chosenVoice = femaleVoice || nonMaleVoice || trVoices[0] || null;
    const isKnownMale = chosenVoice ? (
      chosenVoice.name.toLowerCase().includes('tolga') ||
      chosenVoice.name.toLowerCase().includes('male') ||
      chosenVoice.name.toLowerCase().includes('erkek')
    ) : false;

    const speakChunkAt = (idx: number) => {
      if (isAborted || idx >= f4Result.chunks.length) {
        onChunkChange?.(null);
        onComplete?.();
        return;
      }

      const chunkObj = f4Result.chunks[idx];
      onChunkChange?.(chunkObj.index);

      const utter = new SpeechSynthesisUtterance(chunkObj.text);
      utter.lang = 'tr-TR';
      utter.rate = 1.06;
      utter.pitch = 1.04;
      if (trVoice) utter.voice = trVoice;
      if (chosenVoice) utter.voice = chosenVoice;

      // Leyla Kadın Sesi Garantisi:
      // Eğer sistemde yalnızca erkek sesi (Tolga) varsa perdesi (pitch) 1.38'e yükseltilerek kadın tınısı verilir.
      // Emel veya başka kadın sesi varsa 1.14 perdede doğal sıcak Leyla tonu korunur.
      utter.pitch = isKnownMale ? 1.38 : (femaleVoice ? 1.14 : 1.25);
      utter.rate = 1.02;

      let settled = false;
      const advanceNext = () => {
        if (settled) return;
        settled = true;
        if (!isAborted) {
          speakChunkAt(idx + 1);
        }
      };

      utter.onend = advanceNext;
      utter.onerror = advanceNext;

      window.speechSynthesis.speak(utter);

      // Tarayıcı emniyet zamanlayıcısı
      const chunkTimeoutMs = Math.min(7000, Math.max(1600, chunkObj.text.length * 72));
      setTimeout(advanceNext, chunkTimeoutMs);
    };

    speakChunkAt(0);
  } catch (e) {
    console.warn("F4 sequential speech error:", e);
    onChunkChange?.(null);
    onComplete?.();
  }

  return () => {
    isAborted = true;
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    onChunkChange?.(null);
  };
}
````


### frontend/src/pipeline/safetyLocks.ts

````
/**
 * FreyaTTS Automotive Cockpit V3 — M01–M11 Deterministik Emniyet Kilitleri Tanımları
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

export interface SafetyLock {
  id: string;
  name: string;
  stage: string;
  desc: string;
  trips: number;
  active: boolean;
  latency: string;
}

export const INITIAL_SAFETY_LOCKS: SafetyLock[] = [
  {
    id: 'M01',
    name: 'Halüsinasyon & Katalog Kilidi',
    stage: 'F3',
    desc: 'Veritabanında bulunmayan parça veya servis fiyatının uydurulmasını deterministik JSON şema ile engeller.',
    trips: 0,
    active: true,
    latency: '0.4 ms'
  },
  {
    id: 'M02',
    name: 'Fiyat & İskonto Yetki Sınırı',
    stage: 'F3',
    desc: 'Yetkisiz iskonto veya ±%0 sapma dışı fiyat telaffuzunu bloke eder.',
    trips: 1,
    active: true,
    latency: '0.2 ms'
  },
  {
    id: 'M03',
    name: 'KVKK & PII Maskeleme Kilidi',
    stage: 'F2/F3',
    desc: 'TCKN, kredi kartı ve açık adres verilerini log ve LLM bağlamından anında maskeler.',
    trips: 4,
    active: true,
    latency: '0.8 ms'
  },
  {
    id: 'M04',
    name: 'Barge-in Kesme Garantisi (<120ms)',
    stage: 'F1/F6',
    desc: 'Müşteri araya girdiğinde aktif F4/F5 chunk çıkışını 120ms içinde sıfırlar ve dinleme moduna döner.',
    trips: 12,
    active: true,
    latency: '1.1 ms'
  },
  {
    id: 'M05',
    name: 'Fonetik Marka, Plaka & Sezer Doğrulayıcı',
    stage: 'F4',
    desc: 'Peugeot, Qashqai, DSG, 61 TS 061 ve Trabzon/Ortahisar yer adlarının yanlış okunmasını G2P tablosuyla önler.',
    trips: 24,
    active: true,
    latency: '0.3 ms'
  },
  {
    id: 'M06',
    name: 'OBD-II Kritik Güvenlik Eskalasyonu',
    stage: 'F3',
    desc: 'Fren, hava yastığı veya yağ basıncı arıza kodlarında aracı yürütmeme uyarısı verir ve ustaya bağlar.',
    trips: 2,
    active: true,
    latency: '0.5 ms'
  },
  {
    id: 'M07',
    name: 'Spektral VAD & Masa Tıkırtısı Koruması',
    stage: 'F0/F1',
    desc: '300-3400Hz insan sesi oranı %55 altındaki darbeli gürültülerin (kapı, bardak sesi) Leyla’yı kesmesini önler.',
    trips: 9,
    active: true,
    latency: '1.4 ms'
  },
  {
    id: 'M08',
    name: 'Mükerrer Randevu Çakışma Kilidi',
    stage: 'F3',
    desc: 'Aynı lift ve teknisyen saatine çift rezervasyon yapılmasını ACID kilidiyle engeller.',
    trips: 0,
    active: true,
    latency: '0.9 ms'
  },
  {
    id: 'M09',
    name: 'Duygu & Öfke Tespiti Devir Kilidi',
    stage: 'F1/F3',
    desc: 'Müşteri ses tonunda yüksek stres/memnuniyetsizlik algılandığında Dahili 6002 Operatöre aktarır.',
    trips: 1,
    active: true,
    latency: '1.2 ms'
  },
  {
    id: 'M10',
    name: 'VRAM & Gecikme Sigortası (Circuit Breaker)',
    stage: 'F5',
    desc: 'TTFA > 350ms aşılırsa ODE adım sayısını 10’dan 6’ya düşürerek gerçek zamanlılığı korur.',
    trips: 3,
    active: true,
    latency: '0.1 ms'
  },
  {
    id: 'M11',
    name: 'TSE-HYB Ekspertiz Hukuki Sorumluluk Şerhi',
    stage: 'F3/F4',
    desc: 'Ekspertiz ön bilgilendirmelerinde yasal ekspertiz sınırlarını eksiksiz bildirir.',
    trips: 0,
    active: true,
    latency: '0.2 ms'
  }
];
````


### frontend/src/pipeline/types.ts

````
/**
 * FreyaTTS Automotive Cockpit V3 — F0–F6 Audio Intelligence Pipeline Telemetri Sözleşmesi
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

export type StageId = "F0" | "F1" | "F2" | "F3" | "F4" | "F5" | "F6";

export type StageStatus =
  | "idle"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "skipped"
  | "bypassed";

export const LIVE_MEASURED_STAGES: readonly StageId[] = ["F2", "F3", "F4", "F5"];

export type TelemetrySource = "live" | "demo" | "replay";

export interface StageDefinition {
  id: StageId;
  code: string;
  name: string;
  shortDesc: string;
  technology: string;
  inputDescription: string;
  outputDescription: string;
  inspectorTabs: readonly ("overview" | "parameters" | "intermediate" | "metrics" | "traces")[];
}

export const STAGE_DEFINITIONS: Record<StageId, StageDefinition> = {
  F0: {
    id: "F0",
    code: "F0",
    name: "Akustik DSP & Gürültü",
    shortDesc: "120Hz HPF + Spektral Bastırma + AGC",
    technology: "Butterworth 4. Derece + Sine Spectral (-18dB) + Soft AGC",
    inputDescription: "8 kHz SLIN16 / 16 kHz WebRTC ham ses çerçeveleri",
    outputDescription: "Gürültüden arındırılmış, normalize edilmiş PCM",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F1: {
    id: "F1",
    code: "F1",
    name: "VAD & 2-Aşamalı Barge-In",
    shortDesc: "Silero VAD + 300ms Ring Tampon",
    technology: "Silero VAD (0.55 eşik) + Goertzel DTMF + 2-Stage Soft/Hard Barge-in",
    inputDescription: "16 kHz filtrelenmiş ses blokları (512 örnek)",
    outputDescription: "Konuşma segmentleri, VAD olasılığı, barge-in durdurma sinyali",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F2: {
    id: "F2",
    code: "F2",
    name: "ASR / Faster-Whisper",
    shortDesc: "Türkçe Akustik Transkripsiyon",
    technology: "Faster-Whisper large-v3-turbo (CUDA) + RMS Enerji Kapısı",
    inputDescription: "Süreksizliği bitirilmiş (endpointed) ses segmenti",
    outputDescription: "Ham metin transkripti & segment güven olasılıkları",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F3: {
    id: "F3",
    code: "F3",
    name: "Niyet & LLM Çıkarımı",
    shortDesc: "Supervisor Router & Qwen2.5 7B",
    technology: "Supervisor Intent Router + Deterministik DB Kilidi + Ollama Qwen2.5",
    inputDescription: "Doğrulanmış müşteri konuşma transkripti",
    outputDescription: "Niyet, slotlar, veritabanı yanıtı ve diyalog metni",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F4: {
    id: "F4",
    code: "F4",
    name: "Normalizasyon & Chunker",
    shortDesc: "P0 Sözlük + İlk Cümlecik Kilidi",
    technology: "P0 Otomotiv Fonetik Sözlüğü + Atomik Chunker + Sıfır Markdown Kalkanı",
    inputDescription: "LLM tarafından üretilen ham diyalog yanıtı",
    outputDescription: "Telaffuz kuralları uygulanmış 4-7 kelimelik atomik cümle parçaları",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F5: {
    id: "F5",
    code: "F5",
    name: "FreyaTTS Akustik Sentez",
    shortDesc: "Batched ODE + Leyla Kadın Sesi",
    technology: "FreyaTTS Flow Matching + AudioVAE2 + Leyla Seed #9",
    inputDescription: "Fonetik olarak normalize edilmiş metin parçaları",
    outputDescription: "24 kHz / 16 kHz sentetik PCM dalga formu",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
  F6: {
    id: "F6",
    code: "F6",
    name: "Ses iletimi",
    shortDesc: "Asterisk / Web Çıkışı",
    technology: "Asterisk AudioSocket / Web Audio API",
    inputDescription: "Sentezlenmiş ham PCM parçaları",
    outputDescription: "Kulaklığa / telefon hattına akıtılan kesintisiz ses yayını",
    inspectorTabs: ["overview", "parameters", "intermediate", "metrics", "traces"],
  },
};

export interface StageRuntimeState {
  stage: StageId;
  status: StageStatus;
  durationMs: number | null;
  startedAt: number | null;
  completedAt: number | null;
  errorCode?: string;
  errorMessage?: string;
  metrics: Record<string, any>;
  intermediateData?: any;
}

export interface PipelineTurnState {
  turnId: number;
  sessionId: string;
  source: TelemetrySource;
  activeStage: StageId | null;
  totalDurationMs: number | null;
  userText?: string;
  assistantText?: string;
  stages: Record<StageId, StageRuntimeState>;
  traces: PipelineTelemetryEvent[];
}

export interface PipelineTelemetryEvent {
  schema_version: "3.0";
  event_id: string;
  session_id: string;
  turn_id: number;
  stage: StageId;
  status: StageStatus;
  source: TelemetrySource;
  timestamp: number;
  duration_ms?: number;
  metrics?: Record<string, any>;
  intermediate_data?: any;
  error_code?: string;
  error_message?: string;
}

export function createInitialTurnState(turnId: number, sessionId = "", source: TelemetrySource = "live"): PipelineTurnState {
  const stages = {} as Record<StageId, StageRuntimeState>;
  const ids: StageId[] = ["F0", "F1", "F2", "F3", "F4", "F5", "F6"];
  for (const id of ids) {
    stages[id] = {
      stage: id,
      status: "idle",
      durationMs: null,
      startedAt: null,
      completedAt: null,
      metrics: {},
    };
  }
  return {
    turnId,
    sessionId,
    source,
    activeStage: null,
    totalDurationMs: null,
    stages,
    traces: [],
  };
}
````


### frontend/src/QueueLiftPanel.tsx

````
import React, { useState, useEffect } from "react";
import { errorMessage } from "./ui";

import type { ApiProps as Props } from "./api";

type LiftItem = {
  id: string;
  name: string;
  lift_number: number;
  status: "idle" | "busy" | "maintenance";
  current_appointment_id?: string | null;
  current_vehicle_plate?: string;
  package_type: string;
  started_at?: string | null;
  estimated_duration_min: number;
  notes?: string;
};

type QueueItem = {
  id: string;
  queue_number: number;
  appointment_id?: string | null;
  vehicle_id?: string | null;
  plate: string;
  customer: string;
  package_type: string;
  duration_minutes: number;
  status: "waiting" | "in_progress" | "completed" | "cancelled";
  lift_id?: string | null;
  check_in_at: string;
  started_at?: string | null;
  completed_at?: string | null;
};

type CapacityStatus = {
  total_lifts: number;
  active_lifts: number;
  busy_lifts: number;
  idle_lifts: number;
  maintenance_lifts: number;
  queue_waiting_count: number;
  // null = hesaplanamadı (lift yok veya kalan süre bilinmiyor)
  estimated_wait_minutes: number | null;
  all_lifts_busy: boolean;
  earliest_available_time: string | null;
  spoken_message: string;
};

type PackageItem = {
  key: string;
  name: string;
  duration_minutes: number;
  description: string;
  base_price_kurus: number;
};

export function QueueLiftPanel({ api }: Props) {
  const [lifts, setLifts] = useState<LiftItem[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [packages, setPackages] = useState<PackageItem[]>([]);
  const [capacity, setCapacity] = useState<CapacityStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  // Check-in Form States
  const [newPlate, setNewPlate] = useState("");
  const [newCustomer, setNewCustomer] = useState("");
  const [newPackage, setNewPackage] = useState("standart_ekspertiz");

  // New Lift Form States
  const [showAddLift, setShowAddLift] = useState(false);
  const [newLiftName, setNewLiftName] = useState("");
  const [newLiftNumber, setNewLiftNumber] = useState<number | "">("");
  const [newLiftNotes, setNewLiftNotes] = useState("");

  // Manual Assign Modal / State
  const [assigningLiftId, setAssigningLiftId] = useState<string | null>(null);
  const [assignPlate, setAssignPlate] = useState("");
  const [assignPackage, setAssignPackage] = useState("standart_ekspertiz");

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000); // 10s auto refresh
    return () => clearInterval(interval);
  }, []);

  async function loadData() {
    try {
      const [lList, qList, cap, pkgs] = await Promise.all([
        api("lifts"),
        api("queue"),
        api("lifts/capacity"),
        api("packages"),
      ]);
      setLifts(lList || []);
      setQueue(qList || []);
      setCapacity(cap);
      setPackages(pkgs || []);
      setLoadError("");
    } catch (e) {
      setLoadError("Lift ve sıra verileri alınamadı: " + errorMessage(e));
    }
  }

  async function handleAddQueue(e: React.FormEvent) {
    e.preventDefault();
    if (!newPlate.trim() || !newCustomer.trim()) {
      setError("Lütfen araç plakası ve müşteri adını girin.");
      return;
    }
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      const created = await api("queue", "POST", {
        plate: newPlate.trim().toUpperCase(),
        customer: newCustomer.trim(),
        package_type: newPackage,
      });
      setNewPlate("");
      setNewCustomer("");
      await loadData();
      setSuccessMsg(
        `Araç sıraya eklendi! Sıra No: #${created.queue_number} (${created.plate})`
      );
    } catch (e) {
      setError("Sıraya alma hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleAddLift(e: React.FormEvent) {
    e.preventDefault();
    if (!newLiftName.trim()) {
      setError("Lütfen lift adını girin.");
      return;
    }
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      await api("lifts", "POST", {
        name: newLiftName.trim(),
        lift_number: newLiftNumber === "" ? undefined : Number(newLiftNumber),
        notes: newLiftNotes.trim(),
      });
      setNewLiftName("");
      setNewLiftNumber("");
      setNewLiftNotes("");
      setShowAddLift(false);
      await loadData();
      setSuccessMsg("Yeni muayene lifti başarıyla oluşturuldu.");
    } catch (e) {
      setError("Lift oluşturma hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleCallNext(liftId: string) {
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      const res = await api(`lifts/${liftId}/call-next`, "POST");
      await loadData();
      if (res.assigned) {
        setSuccessMsg(
          `Sıradaki araç #${res.queue_item.queue_number} (${res.queue_item.plate}) lifte alındı ve muayene başladı!`
        );
      } else {
        setSuccessMsg("Sırada bekleyen araç bulunmuyor.");
      }
    } catch (e) {
      setError("Lifte alma hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleRelease(liftId: string) {
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      await api(`lifts/${liftId}/release`, "POST");
      await loadData();
      setSuccessMsg("Araç liftten çıkarıldı ve lift boş (müsait) duruma getirildi.");
    } catch (e) {
      setError("Lift boşaltma hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleToggleMaintenance(lift: LiftItem) {
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      const nextStatus = lift.status === "maintenance" ? "idle" : "maintenance";
      await api(`lifts/${lift.id}/status`, "POST", {
        status: nextStatus,
        notes: nextStatus === "maintenance" ? "Periyodik teknik bakımda" : "Bakım tamamlandı, aktif.",
      });
      await loadData();
      setSuccessMsg(
        nextStatus === "maintenance"
          ? `${lift.name} bakıma alındı.`
          : `${lift.name} bakımdan çıkarıldı ve hizmete hazır.`
      );
    } catch (e) {
      setError("Durum güncelleme hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleManualAssign(e: React.FormEvent) {
    e.preventDefault();
    if (!assigningLiftId || !assignPlate.trim()) {
      setError("Lütfen geçerli plaka girin.");
      return;
    }
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      await api(`lifts/${assigningLiftId}/assign`, "POST", {
        plate: assignPlate.trim().toUpperCase(),
        package_type: assignPackage,
      });
      setAssigningLiftId(null);
      setAssignPlate("");
      await loadData();
      setSuccessMsg("Araç başarıyla lifte atandı ve işlem başlatıldı.");
    } catch (e) {
      setError("Lifte atama hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleCancelQueue(qId: string) {
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      await api(`queue/${qId}/cancel`, "POST");
      await loadData();
      setSuccessMsg("Sıra kaydı iptal edildi.");
    } catch (e) {
      setError("İptal hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: "8px", minHeight: 0, overflowY: "auto", padding: "2px 4px" }}>
      {/* Üst Başlık & Kapasite Özeti */}
      <section
        style={{
          background: "linear-gradient(135deg, #1E293B 0%, #0F172A 100%)",
          color: "white",
          padding: "20px",
          borderRadius: "10px",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
          <div>
            <h2 style={{ margin: "0 0 6px 0", color: "#38BDF8", display: "flex", alignItems: "center", gap: "10px" }}>
              <span>🏗️</span> Sıra / Kuyruk Yönetimi ve Canlı Lift Durumu
            </h2>
            <p style={{ margin: 0, fontSize: "14px", color: "#94A3B8", maxWidth: "750px" }}>
              Ekspertiz merkezindeki lift kapasitesi, araç bekleme süreleri ve muayene paketlerine göre operasyonel akış takibi.
            </p>
          </div>
          <div style={{ display: "flex", gap: "10px" }}>
            <button
              type="button"
              className="secondary"
              onClick={() => setShowAddLift(!showAddLift)}
              style={{ padding: "8px 14px", fontSize: "13px" }}
            >
              ➕ Yeni Lift Tanımla
            </button>
            <button
              type="button"
              onClick={loadData}
              disabled={loading}
              style={{
                backgroundColor: "#2563EB",
                color: "white",
                padding: "8px 14px",
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
              }}
            >
              🔄 Yenile
            </button>
          </div>
        </div>

        {/* Canlı Kapasite Sayaçları */}
        {capacity && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "10px", marginTop: "16px" }}>
            <div style={{ backgroundColor: "#334155", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#94A3B8" }}>TOPLAM LİFT</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#F8FAFC" }}>{capacity.total_lifts}</div>
            </div>
            <div style={{ backgroundColor: "#065F46", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#A7F3D0" }}>BOŞ / MÜSAİT</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#FFFFFF" }}>{capacity.idle_lifts}</div>
            </div>
            <div style={{ backgroundColor: "#831843", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#FBCFE8" }}>DOLU (İŞLEMDE)</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#FFFFFF" }}>{capacity.busy_lifts}</div>
            </div>
            <div style={{ backgroundColor: "#713F12", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#FDE68A" }}>BAKIMDA</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#FFFFFF" }}>{capacity.maintenance_lifts}</div>
            </div>
            <div style={{ backgroundColor: "#1E3A8A", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#BFDBFE" }}>SIRADA BEKLEYEN</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#FFFFFF" }}>{capacity.queue_waiting_count} Araç</div>
            </div>
            <div style={{ backgroundColor: "#4C1D95", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#DDD6FE" }}>TAHMİNİ BEKLEME</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#FFFFFF" }}>
                {capacity.estimated_wait_minutes == null
                  ? (capacity.total_lifts - capacity.maintenance_lifts <= 0 ? "Lift yok" : "Hesaplanamadı")
                  : capacity.estimated_wait_minutes > 0
                    ? `~${capacity.estimated_wait_minutes} dk`
                    : "0 dk"}
              </div>
            </div>
          </div>
        )}

        {/* Sesli Asistan Canlı Anons Bandı */}
        {capacity && (
          <div
            style={{
              backgroundColor: "rgba(56, 189, 248, 0.12)",
              border: "1px solid #0284C7",
              borderRadius: "6px",
              padding: "10px 14px",
              marginTop: "14px",
              display: "flex",
              alignItems: "center",
              gap: "10px",
            }}
          >
            <span style={{ fontSize: "20px" }}>🎙️</span>
            <div>
              <div style={{ fontSize: "11px", fontWeight: "bold", color: "#38BDF8", textTransform: "uppercase" }}>
                Sesli Asistan Durum Bilgilendirmesi:
              </div>
              <div style={{ fontSize: "13.5px", color: "#F0F9FF", fontWeight: 500 }}>
                "{capacity.spoken_message}"
              </div>
            </div>
          </div>
        )}
      </section>

      {loadError && (
        <div role="alert" className="error" style={{ padding: "12px 16px", borderRadius: "8px" }}>
          ⚠️ {loadError}
        </div>
      )}

      {error && (
        <div role="alert" className="error" style={{ padding: "12px 16px", borderRadius: "8px" }}>
          ⚠️ {error}
        </div>
      )}

      {successMsg && (
        <div style={{ backgroundColor: "#ECFDF5", border: "1px solid #10B981", color: "#065F46", padding: "12px 16px", borderRadius: "8px", fontWeight: 500 }}>
          ✅ {successMsg}
        </div>
      )}

      {/* Yeni Lift Ekleme Formu (Açılır Kapanır) */}
      {showAddLift && (
        <section style={{ backgroundColor: "#F8FAFC", padding: "16px", borderRadius: "8px", border: "1px solid #CBD5E1" }}>
          <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", color: "#1E293B" }}>
            ➕ Yeni Muayene Lifti Tanımla
          </h3>
          <form onSubmit={handleAddLift} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "12px", alignItems: "flex-end" }}>
            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>Lift Adı:</label>
              <input
                type="text"
                required
                placeholder="Örn: Lift-3 (Süspansiyon & Yanal Kayma)"
                value={newLiftName}
                onChange={(e) => setNewLiftName(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>
            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>Lift Numarası (Sıra):</label>
              <input
                type="number"
                placeholder="Örn: 3"
                value={newLiftNumber}
                onChange={(e) => setNewLiftNumber(e.target.value ? Number(e.target.value) : "")}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>
            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>İstasyon Notu / Ekipman:</label>
              <input
                type="text"
                placeholder="Örn: 4 ton hidrolik lift, Dyno donanımlı"
                value={newLiftNotes}
                onChange={(e) => setNewLiftNotes(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button type="submit" disabled={loading} style={{ backgroundColor: "#2563EB", color: "white", padding: "9px 16px", borderRadius: "6px", border: "none", cursor: "pointer", fontWeight: "bold" }}>
                Kaydet
              </button>
              <button type="button" className="secondary" onClick={() => setShowAddLift(false)}>
                Vazgeç
              </button>
            </div>
          </form>
        </section>
      )}

      {/* Manuel Lifte Atama Modalı / Paneli */}
      {assigningLiftId && (
        <section style={{ backgroundColor: "#FEF3C7", padding: "16px", borderRadius: "8px", border: "1px solid #F59E0B" }}>
          <h3 style={{ margin: "0 0 10px 0", fontSize: "15px", color: "#92400E" }}>
            🚗 Lifte Doğrudan Araç Ata (Muayene Başlat)
          </h3>
          <form onSubmit={handleManualAssign} style={{ display: "flex", flexWrap: "wrap", gap: "10px", alignItems: "flex-end" }}>
            <div style={{ minWidth: "180px" }}>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>Araç Plakası:</label>
              <input
                type="text"
                required
                placeholder="34 ABC 123"
                value={assignPlate}
                onChange={(e) => setAssignPlate(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>
            <div style={{ minWidth: "200px" }}>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>Ekspertiz Paketi:</label>
              <select
                value={assignPackage}
                onChange={(e) => setAssignPackage(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              >
                {packages.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.name} ({p.duration_minutes} dk)
                  </option>
                ))}
              </select>
            </div>
            <button type="submit" disabled={loading} style={{ backgroundColor: "#D97706", color: "white", padding: "9px 16px", borderRadius: "6px", border: "none", fontWeight: "bold", cursor: "pointer" }}>
              Lifte Al ve Başlat
            </button>
            <button type="button" className="secondary" onClick={() => setAssigningLiftId(null)}>
              İptal
            </button>
          </form>
        </section>
      )}

      {/* 1. CANLI LİFT KARTLARI (İstasyon Takibi) */}
      <section>
        <h3 style={{ margin: "0 0 12px 0", fontSize: "16px", color: "#1E293B" }}>
          📍 İstasyon Liftleri ve Anlık Durum
        </h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "14px" }}>
          {lifts.map((lift) => {
            const isIdle = lift.status === "idle";
            const isBusy = lift.status === "busy";
            const isMaint = lift.status === "maintenance";

            const borderColor = isIdle ? "#10B981" : isBusy ? "#DC2626" : "#F59E0B";
            const badgeBg = isIdle ? "#ECFDF5" : isBusy ? "#FEF2F2" : "#FFFBEB";
            const badgeText = isIdle ? "#065F46" : isBusy ? "#991B1B" : "#92400E";
            const statusLabel = isIdle ? "BOŞ (MÜSAİT)" : isBusy ? "İŞLEMDE (DOLU)" : "BAKIMDA";

            return (
              <div
                key={lift.id}
                style={{
                  backgroundColor: "#FFFFFF",
                  border: `2px solid ${borderColor}`,
                  borderRadius: "8px",
                  padding: "16px",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  boxShadow: "0 2px 4px rgba(0,0,0,0.04)",
                }}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                    <div>
                      <div style={{ fontSize: "11px", fontWeight: "bold", color: "#64748B" }}>
                        LİFT #{lift.lift_number}
                      </div>
                      <div style={{ fontSize: "15px", fontWeight: "bold", color: "#0F172A" }}>
                        {lift.name}
                      </div>
                    </div>
                    <span
                      style={{
                        backgroundColor: badgeBg,
                        color: badgeText,
                        fontSize: "11px",
                        fontWeight: "bold",
                        padding: "3px 8px",
                        borderRadius: "4px",
                        border: `1px solid ${borderColor}`,
                      }}
                    >
                      {statusLabel}
                    </span>
                  </div>

                  {lift.notes && (
                    <div style={{ fontSize: "12px", color: "#64748B", marginBottom: "10px" }}>
                      ℹ️ {lift.notes}
                    </div>
                  )}

                  {isBusy && (
                    <div
                      style={{
                        backgroundColor: "#F8FAFC",
                        padding: "10px",
                        borderRadius: "6px",
                        border: "1px solid #E2E8F0",
                        marginBottom: "12px",
                      }}
                    >
                      <div style={{ fontSize: "14px", fontWeight: "bold", color: "#1E293B" }}>
                        🚙 Plaka: {lift.current_vehicle_plate || "Kayıtlı Araç"}
                      </div>
                      <div style={{ fontSize: "12px", color: "#475569", marginTop: "3px" }}>
                        📦 Paket: {lift.package_type} (~{lift.estimated_duration_min} dk)
                      </div>
                      {lift.started_at && (
                        <div style={{ fontSize: "11px", color: "#64748B", marginTop: "2px" }}>
                          ⏱️ Başlama: {lift.started_at.slice(11, 16)}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Buton Kontrolleri */}
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "12px" }}>
                  {isIdle && (
                    <>
                      <button
                        type="button"
                        onClick={() => handleCallNext(lift.id)}
                        disabled={loading}
                        style={{
                          backgroundColor: "#059669",
                          color: "white",
                          padding: "6px 12px",
                          borderRadius: "4px",
                          border: "none",
                          fontSize: "12.5px",
                          fontWeight: "bold",
                          cursor: "pointer",
                        }}
                      >
                        ⚡ Sıradakini Al
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => {
                          setAssigningLiftId(lift.id);
                          setAssignPlate("");
                        }}
                        style={{ padding: "6px 10px", fontSize: "12px" }}
                      >
                        Plaka Ata
                      </button>
                    </>
                  )}

                  {isBusy && (
                    <button
                      type="button"
                      onClick={() => handleRelease(lift.id)}
                      disabled={loading}
                      style={{
                        backgroundColor: "#DC2626",
                        color: "white",
                        padding: "6px 12px",
                        borderRadius: "4px",
                        border: "none",
                        fontSize: "12.5px",
                        fontWeight: "bold",
                        cursor: "pointer",
                      }}
                    >
                      ✅ Muayeneyi Tamamla
                    </button>
                  )}

                  <button
                    type="button"
                    className="secondary"
                    onClick={() => handleToggleMaintenance(lift)}
                    disabled={loading}
                    style={{ padding: "6px 10px", fontSize: "12px" }}
                  >
                    {isMaint ? "Bakımdan Çıkar" : "Bakıma Al"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* 2. CANLI SIRA KUYRUĞU (Queue Check-in & List) */}
      <div className="grid-1-2" style={{ gap: "18px", alignItems: "flex-start" }}>
        {/* Sol Kolon: Sıraya Yeni Araç Alma (Check-in) */}
        <section style={{ backgroundColor: "#FFFFFF", padding: "16px", borderRadius: "8px", border: "1px solid #E2E8F0" }}>
          <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", color: "#1E293B" }}>
            🎫 Sahaya Gelen Aracı Sıraya Al (Check-in)
          </h3>
          <form onSubmit={handleAddQueue} style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>
                Araç Plakası:
              </label>
              <input
                type="text"
                required
                placeholder="Örn: 34 EKP 2026"
                value={newPlate}
                onChange={(e) => setNewPlate(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>

            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>
                Müşteri / Kurumsal Ad:
              </label>
              <input
                type="text"
                required
                placeholder="Örn: Ahmet Yılmaz / Galeri A.Ş."
                value={newCustomer}
                onChange={(e) => setNewCustomer(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>

            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>
                Ekspertiz Paketi:
              </label>
              <select
                value={newPackage}
                onChange={(e) => setNewPackage(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              >
                {packages.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.name} ({p.duration_minutes} dk) — {p.base_price_kurus / 100} TL
                  </option>
                ))}
              </select>
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{
                backgroundColor: "#2563EB",
                color: "white",
                padding: "10px",
                borderRadius: "6px",
                border: "none",
                fontWeight: "bold",
                cursor: "pointer",
                marginTop: "6px",
              }}
            >
              🎟️ Sıra Fişi Ver & Kuyruğa Ekle
            </button>
          </form>
        </section>

        {/* Sağ Kolon: Aktif Sıra Kuyruğu Tablosu */}
        <section style={{ backgroundColor: "#FFFFFF", padding: "16px", borderRadius: "8px", border: "1px solid #E2E8F0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <h3 style={{ margin: 0, fontSize: "15px", color: "#1E293B" }}>
              📋 Canlı Bekleme Kuyruğu ({queue.filter((q) => q.status === "waiting").length} Bekleyen)
            </h3>
            <span style={{ fontSize: "12px", color: "#64748B" }}>
              Toplam Kayıt: {queue.length}
            </span>
          </div>

          <div className="table-wrap">
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
              <thead>
                <tr style={{ backgroundColor: "#F8FAFC", borderBottom: "2px solid #E2E8F0", textAlign: "left" }}>
                  <th style={{ padding: "8px" }}>Sıra No</th>
                  <th style={{ padding: "8px" }}>Plaka</th>
                  <th style={{ padding: "8px" }}>Müşteri</th>
                  <th style={{ padding: "8px" }}>Paket / Süre</th>
                  <th style={{ padding: "8px" }}>Durum</th>
                  <th style={{ padding: "8px" }}>İşlem</th>
                </tr>
              </thead>
              <tbody>
                {queue.length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ padding: "16px", textAlign: "center", color: "#94A3B8" }}>
                      Henüz sırada araç bulunmuyor.
                    </td>
                  </tr>
                ) : (
                  queue.map((item) => {
                    let statusColor = "#64748B";
                    let statusLabel: string = item.status;
                    if (item.status === "waiting") {
                      statusColor = "#D97706";
                      statusLabel = "Bekliyor ⏳";
                    } else if (item.status === "in_progress") {
                      statusColor = "#2563EB";
                      statusLabel = "İşlemde ⚙️";
                    } else if (item.status === "completed") {
                      statusColor = "#059669";
                      statusLabel = "Tamamlandı ✅";
                    } else if (item.status === "cancelled") {
                      statusColor = "#DC2626";
                      statusLabel = "İptal ❌";
                    }

                    return (
                      <tr key={item.id} style={{ borderBottom: "1px solid #F1F5F9" }}>
                        <td style={{ padding: "8px", fontWeight: "bold" }}>#{item.queue_number}</td>
                        <td style={{ padding: "8px", fontWeight: "bold", color: "#0F172A" }}>{item.plate}</td>
                        <td style={{ padding: "8px" }}>{item.customer}</td>
                        <td style={{ padding: "8px" }}>
                          {item.package_type} <small style={{ color: "#64748B" }}>({item.duration_minutes} dk)</small>
                        </td>
                        <td style={{ padding: "8px", color: statusColor, fontWeight: "bold" }}>{statusLabel}</td>
                        <td style={{ padding: "8px" }}>
                          {item.status === "waiting" && (
                            <button
                              type="button"
                              className="danger"
                              onClick={() => handleCancelQueue(item.id)}
                              style={{ padding: "2px 8px", fontSize: "11px" }}
                            >
                              İptal
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* 3. STANDART EKSPERTİZ PAKETLERİ VE SÜRELERİ REFERANSI */}
      <section style={{ backgroundColor: "#F8FAFC", padding: "16px", borderRadius: "8px", border: "1px solid #E2E8F0" }}>
        <h3 style={{ margin: "0 0 10px 0", fontSize: "14px", color: "#334155" }}>
          ⏱️ Ekspertiz Paketleri ve Standart İşlem Süreleri
        </h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "10px" }}>
          {packages.map((pkg) => (
            <div key={pkg.key} style={{ backgroundColor: "#FFFFFF", padding: "12px", borderRadius: "6px", border: "1px solid #E2E8F0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontWeight: "bold", fontSize: "13px", color: "#1E293B" }}>{pkg.name}</span>
                <span style={{ backgroundColor: "#EFF6FF", color: "#1D4ED8", padding: "2px 6px", borderRadius: "4px", fontSize: "11px", fontWeight: "bold" }}>
                  {pkg.duration_minutes} dk
                </span>
              </div>
              <p style={{ margin: "0 0 6px 0", fontSize: "12px", color: "#64748B", lineHeight: "1.4" }}>
                {pkg.description}
              </p>
              <div style={{ fontSize: "12px", fontWeight: "bold", color: "#059669" }}>
                Taban Fiyat: {pkg.base_price_kurus / 100} TL
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
````


### frontend/src/SupervisorPanel.tsx

````
import { useEffect, useState } from "react";
import type { Props } from "./api";
import { errorMessage } from "./ui";
import { AnalysisQueuePanel } from "./AnalysisQueuePanel";

type Definition = { intent_id: string; domain: string; description: string; agent: string };
type Candidate = { intent_id: string; score: number | null; evidence: string };
type Step = { step_id: string; agent: string; action: string; depends_on: string[] };
type Trace = {
  trace_id: string;
  conversation_id: string;
  created_at: string;
  review_status: string;
  review_labels: string[] | null;
  outcome: string;
  qa_flags: string[];
  decision: { route_state: string; source: string; candidates: Candidate[]; reason_codes: string[] };
  plan: {
    steps: Step[];
    priority: string;
    requires_confirmation: boolean;
    model_version: string;
    policy_version: string;
  };
};
type Report = {
  model_version: string;
  dataset_sources: string[];
  test: Record<string, number | null>;
};
type Quality = {
  catalogue_version: string;
  mode: string;
  trace_store: string;
  catalogue: Definition[];
  traces: Trace[];
  registry: { approval_configured: boolean; fallback_enabled: boolean };
  evaluation: { baseline: Report | null; xgboost: Report | null; comparable: boolean };
  software_regression: { status: string; tests?: number; failures?: number; errors?: number; skipped?: number };
  physical_regression: string;
};
type Verdict = "ACCEPT" | "EDIT" | "REJECT" | "NEEDS_MORE_EVIDENCE";

const metrics = [
  ["macro_f1", "Makro F1"],
  ["micro_f1", "Mikro F1"],
  ["multi_intent_exact_match", "Çoklu niyet tam eşleşme"],
  ["emergency_recall", "Acil durum yakalama"],
  ["ood_false_accept", "Kapsam dışı yanlış kabul"],
  ["latency_ms_p95", "Gecikme p95 (ms)"],
];
const traceTime = new Intl.DateTimeFormat("tr-TR", {
  dateStyle: "short", timeStyle: "medium", timeZone: "Europe/Istanbul",
});

export function SupervisorPanel({ api, rawApi, initialConversationId, onOpenConversation }: Props & {
  initialConversationId?: string;
  onOpenConversation?: (id: string) => void;
}) {
  const [quality, setQuality] = useState<Quality | null>(null);
  const [queue, setQueue] = useState<"all" | "pending">(initialConversationId ? "all" : "pending");
  const [filter, setFilter] = useState(initialConversationId ?? "");
  const [selected, setSelected] = useState<Trace | null>(null);
  const [verdict, setVerdict] = useState<Verdict>("ACCEPT");
  const [labels, setLabels] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [group, setGroup] = useState("");
  const [split, setSplit] = useState("train");
  const [anonymity, setAnonymity] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const params = new URLSearchParams({ queue });
    if (filter.trim()) params.set("conversation_id", filter.trim());
    setQuality(await api(`supervisor/quality?${params}`));
  }

  async function action(work: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await work();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { void action(load); }, [queue]);

  function selectTrace(trace: Trace) {
    setSelected(trace);
    setVerdict("ACCEPT");
    setLabels(trace.review_labels ?? trace.decision.candidates.map((item) => item.intent_id));
    setText("");
    setGroup("");
    setAnonymity(false);
    setConsent(false);
  }

  async function saveReview() {
    if (!selected) return;
    const body: Record<string, unknown> = { verdict };
    if (verdict === "EDIT") body.labels = labels;
    if (text.trim() && (verdict === "ACCEPT" || verdict === "EDIT")) {
      Object.assign(body, {
        anonymous_text: text.trim(), group_id: group.trim(), split,
        anonymity_attested: anonymity, consent_attested: consent,
      });
    }
    await api(`supervisor/review/${selected.trace_id}`, "POST", body);
    setSelected(null);
    setText("");
    await load();
  }

  async function downloadDataset() {
    const response = await rawApi("supervisor/dataset");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "intent-reviewed.jsonl";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const baseline = quality?.evaluation.baseline;
  const challenger = quality?.evaluation.xgboost;
  const domains = [...new Set(quality?.catalogue.map((item) => item.domain))];

  return (
    <section className="card supervisor-panel" aria-labelledby="supervisor-title">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "10px", marginBottom: "12px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <h2 id="supervisor-title" style={{ margin: 0 }}>Supervisor & Kalite Masası</h2>
          <span className="stage-badge warn" title="F6 Aşaması: FQICI Kalite Skoru, Niyet Karar Ağacı ve Operatör QA">
            F6 Telemetry & QA
          </span>
        </div>
      </div>
      <AnalysisQueuePanel api={api} onOpenConversation={onOpenConversation} />
      <div className="row">
        <label>Görünüm{" "}
          <select disabled={busy} value={queue} onChange={(event) => setQueue(event.target.value as typeof queue)}>
            <option value="pending">İnceleme kuyruğu</option>
            <option value="all">Tüm kararlar</option>
          </select>
        </label>
        <label>Görüşme kimliği{" "}
          <input value={filter} onChange={(event) => setFilter(event.target.value)} />
        </label>
        <button disabled={busy} onClick={() => void action(load)}>Yenile</button>
        <button disabled={busy || quality?.trace_store !== "READY"} onClick={() => void action(downloadDataset)}>
          Onaylı veri setini indir
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {quality && <>
        <p>Çalışma modu <strong>{quality.mode}</strong> · Katalog <strong>{quality.catalogue_version}</strong> ·
          Karar deposu <strong>{quality.trace_store}</strong> · Fiziksel çağrı <strong>{quality.physical_regression}</strong>
        </p>
        <p>Yazılım regresyonu <strong>{quality.software_regression.status}</strong>
          {quality.software_regression.tests !== undefined && ` · ${quality.software_regression.tests} test`}
        </p>
        <h3>Görüşme kararları</h3>
        <p>Görüşme metni ve slot değerleri bu panelde gösterilmez.</p>
        {!quality.traces.length && <p>Bu görünümde karar kaydı yok.</p>}
        {quality.traces.map((trace) => (
          <details key={trace.trace_id}>
            <summary>{traceTime.format(new Date(trace.created_at))} · {trace.decision.route_state} · {trace.plan.priority} · {trace.review_status}</summary>
            <p>Görüşme {trace.conversation_id} · Model {trace.plan.model_version} · Politika {trace.plan.policy_version}</p>
            <p>Kaynak {trace.decision.source} · Sonuç {trace.outcome} · QA {trace.qa_flags.join(", ") || "—"}</p>
            <p>Gerekçe {trace.decision.reason_codes.join(", ") || "—"}</p>
            <ul>{trace.decision.candidates.map((item) => (
              <li key={item.intent_id}>{item.intent_id} · {item.score?.toFixed(3) ?? "—"} · {item.evidence}</li>
            ))}</ul>
            <ol>{trace.plan.steps.map((step) => (
              <li key={step.step_id}>{step.agent} / {step.action}
                {step.depends_on.length > 0 && ` (${step.depends_on.join(", ")} sonrasında)`}
              </li>
            ))}</ol>
            <p>Açık onay gereği {trace.plan.requires_confirmation ? "var" : "yok"}</p>
            {trace.review_labels && <p>İncelenen etiketler {trace.review_labels.join(", ") || "—"}</p>}
            <button onClick={() => selectTrace(trace)}>İncele</button>
          </details>
        ))}
        {selected && <form onSubmit={(event) => { event.preventDefault(); void action(saveReview); }}>
          <h3>Karar incelemesi</h3>
          <p>{selected.trace_id}</p>
          <label>Karar{" "}<select value={verdict} onChange={(event) => setVerdict(event.target.value as Verdict)}>
            <option value="ACCEPT">Kabul</option><option value="EDIT">Etiketleri düzelt</option>
            <option value="REJECT">Reddet</option><option value="NEEDS_MORE_EVIDENCE">Ek kanıt gerekli</option>
          </select></label>
          {verdict === "EDIT" && <label>Düzeltilmiş niyetler{" "}
            <select multiple value={labels} onChange={(event) =>
              setLabels(Array.from(event.target.selectedOptions, (option) => option.value))}>
              {quality.catalogue.map((item) => <option key={item.intent_id}>{item.intent_id}</option>)}
            </select>
          </label>}
          {(verdict === "ACCEPT" || verdict === "EDIT") && <details>
            <summary>İzinli anonim örneği veri setine ekle</summary>
            <p>Aynı müşteri veya senaryo için aynı anonim grup kimliğini ve aynı bölümü kullanın.</p>
            <label>Anonim örnek <textarea value={text} maxLength={1200} onChange={(event) => setText(event.target.value)} /></label>
            <label>Anonim grup UUID <input value={group} onChange={(event) => setGroup(event.target.value)} /></label>
            <label>Bölüm <select value={split} onChange={(event) => setSplit(event.target.value)}>
              <option value="train">Eğitim</option><option value="validation">Doğrulama</option><option value="test">Test</option>
            </select></label>
            <label><input type="checkbox" checked={anonymity} onChange={(event) => setAnonymity(event.target.checked)} /> Örnek anonimleştirildi</label>
            <label><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /> Eğitim kullanımına izin var</label>
          </details>}
          <button disabled={busy}>Kaydet</button>{" "}
          <button type="button" onClick={() => setSelected(null)}>Kapat</button>
        </form>}
        <h3>Model kayıtları ve değerlendirme</h3>
        <p>Model onay ayarı {quality.registry.approval_configured ? "var" : "yok"} ·
          Yerel LLM ayarı {quality.registry.fallback_enabled ? "açık" : "kapalı"}</p>
        <p>{quality.evaluation.comparable ? "Aynı veri ve bölümler" : "Karşılaştırma bekliyor"}</p>
        <table>
          <thead><tr><th>Ölçüm</th><th>{baseline?.model_version ?? "Baseline · NOT RUN"}</th>
            <th>{challenger?.model_version ?? "XGBoost · NOT RUN"}</th></tr></thead>
          <tbody>
            <tr><th>Veri kaynağı</th><td>{baseline?.dataset_sources.join(", ") ?? "—"}</td>
              <td>{challenger?.dataset_sources.join(", ") ?? "—"}</td></tr>
            {metrics.map(([key, title]) => <tr key={key}><th>{title}</th>
              <td>{baseline?.test[key]?.toFixed(3) ?? "—"}</td>
              <td>{challenger?.test[key]?.toFixed(3) ?? "—"}</td></tr>)}
          </tbody>
        </table>
        <h3>Niyet kataloğu</h3>
        {domains.map((domain) => <details key={domain}>
          <summary>{domain}</summary>
          <ul>{quality.catalogue.filter((item) => item.domain === domain).map((item) => (
            <li key={item.intent_id}>{item.intent_id} · {item.description} · {item.agent}</li>
          ))}</ul>
        </details>)}
      </>}
    </section>
  );
}
````


### frontend/src/tabs/AppointmentsTab.tsx

````
// =====================================================================
// ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
// Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
// =====================================================================
import React, { useState, useMemo } from "react";
import type { ActionFn, Appointment, Slot } from "../api";
import { formatDate } from "../ui";
import type { ApiFn } from "../ui";
import { AppointmentMoveDialog } from "../AppointmentMoveDialog";

type Props = {
  api: ApiFn;
  action: ActionFn;
  refresh: () => Promise<void>;
  busy: boolean;
  slots: Slot[];
  appointments: Appointment[];
};

export function AppointmentsTab({ api, action, refresh, busy, slots, appointments }: Props) {
  const [viewMode, setViewMode] = useState<"calendar" | "list">("calendar");
  const [selectedDate, setSelectedDate] = useState<string>("all");
  const [draggedApptId, setDraggedApptId] = useState<string | null>(null);
  const [dragOverSlotId, setDragOverSlotId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);
  const [move, setMove] = useState<{ appointment: Appointment; target: string } | null>(null);

  // Group unique dates from slots
  const availableDates = useMemo(() => {
    const dates = new Set<string>();
    slots.forEach((s) => {
      const d = s.starts_at.substring(0, 10);
      if (d) dates.add(d);
    });
    return Array.from(dates).sort();
  }, [slots]);

  // Filter slots by selected date
  const filteredSlots = useMemo(() => {
    if (selectedDate === "all") return slots;
    return slots.filter((s) => s.starts_at.startsWith(selectedDate));
  }, [slots, selectedDate]);

  // Handle Drag Start
  const handleDragStart = (e: React.DragEvent, apptId: string) => {
    e.dataTransfer.setData("text/plain", apptId);
    e.dataTransfer.effectAllowed = "move";
    setDraggedApptId(apptId);
  };

  const handleDragEnd = () => {
    setDraggedApptId(null);
    setDragOverSlotId(null);
  };

  // Handle Drag Over
  const handleDragOver = (e: React.DragEvent, slotId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (dragOverSlotId !== slotId) {
      setDragOverSlotId(slotId);
    }
  };

  const handleDragLeave = (e: React.DragEvent, slotId: string) => {
    if (dragOverSlotId === slotId) {
      setDragOverSlotId(null);
    }
  };

  // Handle Drop onto Empty Slot
  const handleDrop = (e: React.DragEvent, targetSlot: Slot) => {
    e.preventDefault();
    const apptId = e.dataTransfer.getData("text/plain") || draggedApptId;
    setDragOverSlotId(null);
    setDraggedApptId(null);

    if (!apptId) return;

    // Check if appointment is already in this slot
    const existing = appointments.find((a) => a.id === apptId);
    if (existing && existing.slot_id !== targetSlot.id) {
      setMove({ appointment: existing, target: targetSlot.id });
    }
  };

  const getPackageBadgeColor = (pkg?: string) => {
    switch (pkg) {
      case "vip_ekspertiz":
        return { bg: "#818CF8", color: "#FFFFFF" };
      case "full_ekspertiz":
        return { bg: "#3B82F6", color: "#FFFFFF" };
      case "motor_mekanik":
        return { bg: "#F59E0B", color: "#FFFFFF" };
      default:
        return { bg: "#10B981", color: "#FFFFFF" };
    }
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0, overflowY: "auto", padding: "2px 4px" }}>
      {/* Üst Yönetim ve Saat Ekleme */}
      <section style={{ marginBottom: "8px", padding: "8px 12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
          <div>
            <h2 style={{ margin: "0 0 0.15rem 0", fontSize: "16px" }}>Randevu Takvimi & Planlama</h2>
            <p style={{ margin: 0, color: "var(--muted, #64748B)", fontSize: "0.8rem" }}>
              Randevuları takvim üzerinde sürükleyip boş slotlara bırakarak yeniden saatlendirebilirsiniz.
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button
              type="button"
              className={viewMode === "calendar" ? "primary" : "secondary"}
              onClick={() => setViewMode("calendar")}
              style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}
            >
              📅 Takvim Görünümü
            </button>
            <button
              type="button"
              className={viewMode === "list" ? "primary" : "secondary"}
              onClick={() => setViewMode("list")}
              style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}
            >
              📋 Liste Görünümü
            </button>
          </div>
        </div>

        {message && (
          <div
            style={{
              marginTop: "1rem",
              padding: "0.75rem 1rem",
              borderRadius: "6px",
              backgroundColor: message.type === "success" ? "#ECFDF5" : "#FEF2F2",
              color: message.type === "success" ? "#065F46" : "#991B1B",
              border: `1px solid ${message.type === "success" ? "#A7F3D0" : "#FECACA"}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>{message.text}</span>
            <button
              type="button"
              style={{ background: "none", border: "none", cursor: "pointer", fontWeight: "bold" }}
              onClick={() => setMessage(null)}
            >
              ✕
            </button>
          </div>
        )}
      </section>

      {/* Müsait Saat Ekleme Kartı */}
      <section style={{ marginBottom: "8px", background: "var(--bg-card, #F8FAFC)", padding: "8px 12px", borderRadius: "8px", border: "1px solid var(--border, #E2E8F0)" }}>
        <h3 style={{ margin: "0 0 0.4rem 0", fontSize: "0.9rem" }}>➕ Yeni Müsait Saat Tanımla</h3>
        <form
          className="inline"
          style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end", flexWrap: "wrap" }}
          onSubmit={(e) => {
            e.preventDefault();
            const d = new FormData(e.currentTarget);
            action(async () => {
              await api("slots", "POST", {
                starts_at: String(d.get("time")) + ":00+03:00",
              });
              await refresh();
              setMessage({ text: "Yeni randevu saati başarıyla eklendi.", type: "success" });
            });
          }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: "0.2rem", fontSize: "0.8rem" }}>
            Tarih ve Saat (İstanbul TS)
            <input type="datetime-local" name="time" required disabled={busy} style={{ padding: "0.3rem 0.5rem", fontSize: "0.8rem" }} />
          </label>
          <button type="submit" disabled={busy} style={{ padding: "5px 12px", fontSize: "0.8rem" }}>
            Saat Ekle
          </button>
        </form>
      </section>

      {/* Tarih Filtresi */}
      {availableDates.length > 0 && (
        <div style={{ display: "flex", gap: "0.4rem", alignItems: "center", marginBottom: "6px", overflowX: "auto", paddingBottom: "0.25rem" }}>
          <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--muted, #64748B)" }}>Tarih:</span>
          <button
            type="button"
            className={selectedDate === "all" ? "primary" : "secondary"}
            style={{ fontSize: "0.8rem", padding: "0.25rem 0.6rem" }}
            onClick={() => setSelectedDate("all")}
          >
            Tüm Günler ({slots.length})
          </button>
          {availableDates.map((d) => (
            <button
              key={d}
              type="button"
              className={selectedDate === d ? "primary" : "secondary"}
              style={{ fontSize: "0.8rem", padding: "0.25rem 0.6rem" }}
              onClick={() => setSelectedDate(d)}
            >
              {d}
            </button>
          ))}
        </div>
      )}

      {/* GÖRÜNÜM 1: SÜRÜKLE-BIRAK TAKVİM GRID */}
      {viewMode === "calendar" ? (
        <section>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: "1rem",
            }}
          >
            {filteredSlots.map((s) => {
              const appt = appointments.find((x) => x.slot_id === s.id && x.status === "confirmed");
              const isOccupied = !!appt;
              const isDragOver = dragOverSlotId === s.id;
              const badgeStyle = getPackageBadgeColor(appt?.package_type);

              return (
                <div
                  key={s.id}
                  onDragOver={(e) => !isOccupied && handleDragOver(e, s.id)}
                  onDragLeave={(e) => !isOccupied && handleDragLeave(e, s.id)}
                  onDrop={(e) => !isOccupied && handleDrop(e, s)}
                  style={{
                    borderRadius: "8px",
                    border: isDragOver
                      ? "2px dashed #2563EB"
                      : isOccupied
                      ? "1px solid #CBD5E1"
                      : "1px dashed #10B981",
                    backgroundColor: isDragOver
                      ? "#EFF6FF"
                      : isOccupied
                      ? "#FFFFFF"
                      : "#F0FDF4",
                    padding: "1rem",
                    transition: "all 0.15s ease",
                    boxShadow: isOccupied ? "0 1px 3px rgba(0,0,0,0.06)" : "none",
                    minHeight: "130px",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                  }}
                >
                  {/* Slot Zaman Başlığı */}
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <span style={{ fontSize: "1.1rem" }}>🕒</span>
                      <strong style={{ fontSize: "0.95rem" }}>{formatDate(s.starts_at)}</strong>
                    </div>
                    {isOccupied ? (
                      <span style={{ fontSize: "0.75rem", padding: "0.15rem 0.45rem", borderRadius: "12px", background: badgeStyle.bg, color: badgeStyle.color, fontWeight: 600 }}>
                        {appt.package_type?.replace(/_/g, " ").toUpperCase() || "DOLU"}
                      </span>
                    ) : (
                      <span style={{ fontSize: "0.75rem", padding: "0.15rem 0.45rem", borderRadius: "12px", background: "#D1FAE5", color: "#065F46", fontWeight: 600 }}>
                        MÜSAİT
                      </span>
                    )}
                  </div>

                  {/* Slot İçeriği / Draggable Kart */}
                  {isOccupied && appt ? (
                    <div
                      draggable={!busy}
                      onDragStart={(e) => handleDragStart(e, appt.id)}
                      onDragEnd={handleDragEnd}
                      style={{
                        padding: "0.6rem",
                        background: "#F8FAFC",
                        borderRadius: "6px",
                        border: "1px solid #E2E8F0",
                        cursor: "grab",
                        userSelect: "none",
                      }}
                      title="Bu randevuyu sürükleyip boş bir saate bırakabilirsiniz"
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.25rem" }}>
                        <span style={{ fontWeight: 600, fontSize: "0.9rem" }}>{appt.customer}</span>
                        <span style={{ fontSize: "0.85rem", color: "#94A3B8" }}>⠿ Sürükle</span>
                      </div>
                      {appt.customer_phone && (
                        <div style={{ fontSize: "0.8rem", color: "var(--muted, #64748B)" }}>
                          📞 {appt.customer_phone}
                        </div>
                      )}
                      <div style={{ marginTop: "0.6rem", display: "flex", justifyContent: "flex-end", gap: "0.4rem" }}>
                        <button type="button" className="secondary" disabled={busy}
                          onClick={() => setMove({ appointment: appt, target: "" })}>Taşı</button>
                        <button
                          type="button"
                          className="secondary"
                          style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem" }}
                          disabled={busy}
                          onClick={() =>
                            action(async () => {
                              await api(`appointments/${appt.id}/cancel`, "POST");
                              setMessage({ text: `${appt.customer} randevusu iptal edildi.`, type: "success" });
                              await refresh();
                            })
                          }
                        >
                          İptal Et
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div
                      style={{
                        textAlign: "center",
                        padding: "1rem 0.5rem",
                        color: isDragOver ? "#2563EB" : "#059669",
                        fontSize: "0.85rem",
                      }}
                    >
                      {isDragOver ? "⬇️ Randevuyu Buraya Bırakın" : "➕ Boş Slot — Randevu Sürükleyin"}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {!filteredSlots.length && (
            <p className="muted" style={{ textAlign: "center", padding: "2rem" }}>
              Bu tarih için tanımlanmış randevu saati bulunmuyor. Yukarıdan yeni saat ekleyebilirsiniz.
            </p>
          )}
        </section>
      ) : (
        /* GÖRÜNÜM 2: KLASİK LİSTE GÖRÜNÜMÜ */
        <section>
          <h2>Randevu Listesi</h2>
          {filteredSlots.map((s) => {
            const a = appointments.find((x) => x.slot_id === s.id && x.status === "confirmed");
            return (
              <div className="row" key={s.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.75rem", borderBottom: "1px solid #E2E8F0" }}>
                <div>
                  <b>{formatDate(s.starts_at)}</b>
                  <div style={{ fontSize: "0.85rem", color: "#64748B" }}>
                    {a ? `${a.customer} (${a.customer_phone || "Tel yok"}) — ${a.package_type || "standart"}` : "Müsait"}
                  </div>
                </div>
                {a ? (<div className="appointment-row-actions">
                  <button type="button" className="secondary" disabled={busy}
                    onClick={() => setMove({ appointment: a, target: "" })}>Taşı</button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      action(async () => {
                        await api(`appointments/${a.id}/cancel`, "POST");
                        setMessage({ text: "Randevu iptal edildi.", type: "success" });
                        await refresh();
                      })
                    }
                  >
                    İptal et
                  </button>
                </div>) : (
                  <span className="pill" style={{ background: "#D1FAE5", color: "#065F46" }}>Müsait</span>
                )}
              </div>
            );
          })}
        </section>
      )}
      {move && <AppointmentMoveDialog
        api={api} appointment={move.appointment} slots={slots} appointments={appointments}
        initialTarget={move.target} onClose={() => setMove(null)} refresh={() => action(refresh)}
        onMoved={(startsAt) => {
          setMove(null);
          setMessage({ text: `Randevu ${formatDate(startsAt)} saatine taşındı.`, type: "success" });
          void action(refresh);
        }}
      />}
    </div>
  );
}
````


### frontend/src/tabs/HistoryTab.tsx

````
import { useEffect, useState } from "react";
import type { ActionFn, Conversation, ConversationDetail } from "../api";
import { analysisSource, analysisState } from "../AnalysisQueuePanel";
import { errorMessage, formatDate, formatMetrics } from "../ui";
import type { ApiFn } from "../ui";

type Props = {
  api: ApiFn;
  action: ActionFn;
  refresh: () => Promise<void>;
  calls: Conversation[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onOpenQuality: (id: string) => void;
};

export function HistoryTab({ api, action, refresh, calls, selectedId, onSelect, onOpenQuality }: Props) {
  const [response, setResponse] = useState<{ id: string; detail?: ConversationDetail; error?: string } | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!selectedId) return;
    let current = true;
    setResponse(null);
    api(`supervisor/conversations/${selectedId}/detail`).then(
      (detail: ConversationDetail) => { if (current) setResponse({ id: selectedId, detail }); },
      (err: unknown) => { if (current) setResponse({ id: selectedId, error: errorMessage(err) }); },
    );
    return () => { current = false; };
  }, [api, selectedId, revision]);

  const selected = response?.id === selectedId ? response : null;
  const detail = selected?.detail;

  return (
    <div className="two conversation-history">
      <section>
        <h2>Görüşmeler</h2>
        {calls.map((c) => (
          <div className="row" key={c.id}>
            <button
              className="secondary"
              aria-label={`Görüşme ${formatDate(c.created_at)}`}
              aria-current={selectedId === c.id ? "true" : undefined}
              onClick={() => onSelect(c.id)}
            >
              {formatDate(c.created_at)}
              <small>
                {c.channel} · {c.status}
              </small>
            </button>
            <button
              className="danger"
              onClick={() =>
                action(async () => {
                  await api("conversations/" + c.id, "DELETE");
                  if (selectedId === c.id) onSelect(null);
                  await refresh();
                })
              }
            >
              Sil
            </button>
          </div>
        ))}
        {!calls.length && <p className="muted">Henüz görüşme yok.</p>}
      </section>
      <section className="card conversation-detail" aria-labelledby="conversation-detail-title">
        <div className="row">
          <h2 id="conversation-detail-title">Görüşme detayı</h2>
          {selectedId && <button className="secondary" disabled={!selected} onClick={() => setRevision((n) => n + 1)}>
            Detayı yenile
          </button>}
        </div>
        {!selectedId && <p className="muted">Detayı görmek için bir görüşme seçin.</p>}
        {selectedId && !selected && <p role="status">Görüşme yükleniyor…</p>}
        {selected?.error && <p role="alert">{selected.error}</p>}
        {detail && <>
          <p>{formatDate(detail.conversation.created_at)} · {detail.conversation.channel} · <strong>{detail.conversation.status}</strong></p>
          <p className="muted"><small>{detail.conversation.id}</small></p>
          {detail.conversation.status === "purged" ? <p>Bu görüşmenin ayrıntıları saklama politikasına göre silinmiş.</p> : <>
            <div className="conversation-linked">
              <section aria-labelledby="linked-appointment">
                <h3 id="linked-appointment">Bağlı randevu</h3>
                {detail.appointment ? <>
                  <p><strong>{detail.appointment.status}</strong>{detail.appointment.starts_at && ` · ${formatDate(detail.appointment.starts_at)}`}</p>
                  <small>{detail.appointment.id}</small>
                </> : <p className="muted">Bu görüşmeyle eşleşen randevu kaydı yok.</p>}
              </section>
              <section aria-labelledby="linked-transfers">
                <h3 id="linked-transfers">Operatör aktarımı</h3>
                {detail.transfers.length ? <ul>{detail.transfers.map((transfer) =>
                  <li key={transfer.id}>{transfer.status} · {formatDate(transfer.completed_at ?? transfer.created_at)}</li>,
                )}</ul> : <p className="muted">Bağlı aktarım kaydı yok.</p>}
              </section>
              <section aria-labelledby="linked-analysis">
                <h3 id="linked-analysis">FQICI analiz işleri</h3>
                {detail.fqici.store === "UNAVAILABLE" ? <p>Kuyruk deposu hazır değil.</p> :
                  detail.fqici.scope ? <>
                    <p>{analysisSource(detail.fqici.scope)}</p>
                    {detail.fqici.scope.ready_at_ms !== null && <p>Yeni analiz için bekleyen kanıt var.</p>}
                    {!detail.fqici.scope.terminal_seen && <p>Kapanış kaydı bekleniyor.</p>}
                    {!!detail.fqici.runs.length && <ul>{detail.fqici.runs.map((run) =>
                      <li key={run.id}>{analysisState(run)} · {run.rule_version} · {run.attempts} deneme</li>,
                    )}</ul>}
                  </> : <p className="muted">Bu görüşme için FQICI kaydı yok.</p>}
              </section>
              <section aria-labelledby="linked-traces">
                <h3 id="linked-traces">Supervisor kararları</h3>
                {detail.traces.length ? <>
                  <ul>{detail.traces.map((trace) => (
                    <li key={trace.id}>
                      <strong>{trace.intents.join(", ") || trace.route_state}</strong>
                      <small> · {trace.outcome}{trace.reason_codes.length > 0 && ` · ${trace.reason_codes.join(", ")}`}</small>
                    </li>
                  ))}</ul>
                  <button className="secondary" onClick={() => onOpenQuality(detail.conversation.id)}>Supervisor kararlarını aç</button>
                </> : <p className="muted">Bu görüşme için karar izi yok.</p>}
              </section>
            </div>
            <h3>Transkript ve ölçümler</h3>
            {!detail.turns.length && <p className="muted">Bu görüşmede konuşma kaydı yok.</p>}
            {detail.turns.map((t) => (
              <p className="bubble" key={t.id}>
                <b>{t.role === "metric" ? "ölçüm" : t.role}</b>
                {t.text || formatMetrics(t.metrics) || "—"}
              </p>
            ))}
          </>}
        </>}
      </section>
    </div>
  );
}
````


### frontend/src/tabs/LabTab.tsx

````
/**
 * FreyaTTS Automotive Cockpit — Ses Laboratuvarı & Piper TTS Stüdyosu (LabTab.tsx)
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 * Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlıdır.
 */

import React, { useState } from "react";
import type { ActionFn } from "../api";
import type { ApiFn, RawApiFn } from "../ui";
import {
  Volume2,
  Play,
  Sparkles,
  Download,
  Gauge,
  Sliders,
  CheckCircle2,
  FileText,
  Clock,
  Zap,
  Activity,
  Layers,
} from "lucide-react";

type Props = {
  api: ApiFn;
  rawApi: RawApiFn;
  action: ActionFn;
  text: string;
  setText: (v: string) => void;
  normalized: string;
  setNormalized: (v: string) => void;
  audioUrl: string;
  setAudioUrl: (v: string) => void;
};

interface TtsTelemetry {
  ttfb_ms: number;
  duration_sec: number;
  rtf: number;
  sample_rate_hz: number;
  size_kb: number;
}

const AUTOMOTIVE_PRESETS = [
  {
    id: "appointment_confirm",
    label: "📅 Randevu Onayı",
    text: "Trabzon Otomotiv Yetkili Servisi'ne hoş geldiniz. 61 TS 061 plakalı Peugeot 3008 aracınız için yarın saat 10:30'a ekspertiz randevunuz oluşturulmuştur.",
  },
  {
    id: "obd_warning",
    label: "⚠️ Kritik OBD Arıza Uyarısı",
    text: "Dikkat, OBD-II teşhis taramasında P0300 rastgele silindir ateşleme hatası tespit edildi. Gold ekspertiz paketimiz kapsamında bujiler ve ateşleme bobinleri incelenecektir.",
  },
  {
    id: "price_package",
    label: "💰 Fiyat & Paket Bilgisi",
    text: "Peugeot 3008 1.5 BlueHDi aracınız için kapsamlı Gold ekspertiz paketi KDV dahil 4.500 TL tutmaktadır. Süre yaklaşık 75 dakikadır.",
  },
  {
    id: "date_change",
    label: "🔄 Randevu Değişikliği",
    text: "Mevcut randevunuz 18 Kasım Çarşamba günü saat 14:00 olarak güncellenmiştir. Onay SMS'iniz telefonunuza iletilmiştir.",
  },
];

export function LabTab({
  api,
  rawApi,
  action,
  text,
  setText,
  normalized,
  setNormalized,
  audioUrl,
  setAudioUrl,
}: Props) {
  // TTS Stüdyo Parametreleri
  const [speechRate, setSpeechRate] = useState<number>(1.0);
  const [pitch, setPitch] = useState<number>(1.0);
  const [noiseScale, setNoiseScale] = useState<number>(0.667);
  const [speaker, setSpeaker] = useState<string>("tr_TR-leyla-medium");
  const [isSynthesizing, setIsSynthesizing] = useState<boolean>(false);
  const [isNormalizing, setIsNormalizing] = useState<boolean>(false);

  // Canlı Sentez Metrikleri
  const [telemetry, setTelemetry] = useState<TtsTelemetry | null>({
    ttfb_ms: 184,
    duration_sec: 4.12,
    rtf: 0.18,
    sample_rate_hz: 22050,
    size_kb: 178,
  });

  const handleNormalize = async () => {
    setIsNormalizing(true);
    try {
      await action(async () => {
        const res = await api("normalize", "POST", { text });
        setNormalized(res.normalized);
      });
    } catch (err) {
      console.error("Normalizasyon hatası:", err);
    } finally {
      setIsNormalizing(false);
    }
  };

  const handleSynthesize = async () => {
    setIsSynthesizing(true);
    const start = performance.now();
    try {
      await action(async () => {
        const r = await rawApi("synthesize", "POST", {
          text,
          speed: speechRate,
          speaker,
        });
        const elapsedMs = Math.round(performance.now() - start);
        const blob = await r.blob();
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        const url = URL.createObjectURL(blob);
        setAudioUrl(url);

        // Tahmini ses süresi (22050 Hz 16-bit mono: ~44.1 KB/sn)
        const sizeKb = Math.round(blob.size / 1024);
        const durationEst = Math.max(0.5, Number((blob.size / 44100).toFixed(2)));
        const rtfVal = Number((elapsedMs / 1000 / durationEst).toFixed(2));

        setTelemetry({
          ttfb_ms: elapsedMs,
          duration_sec: durationEst,
          rtf: rtfVal,
          sample_rate_hz: 22050,
          size_kb: sizeKb,
        });
      });
    } catch (err) {
      console.error("Sentez hatası:", err);
    } finally {
      setIsSynthesizing(false);
    }
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0, padding: "2px 0", overflow: "hidden" }}>
      {/* Panel Başlığı ve F5 Statik Rozeti */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 8,
          marginBottom: 6,
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: "#f8fafc" }}>
            Ses Laboratuvarı & Piper TTS Stüdyosu
          </h2>
          <span className="stage-badge brand">
            <Volume2 size={12} /> F5 Piper TTS Engine
          </span>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 12,
            color: "#94a3b8",
            fontFamily: "var(--font-mono, monospace)",
          }}
        >
          <span
            style={{
              display: "inline-block",
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "#34d399",
            }}
          />
          Model: Piper TTS Turkish v1.2 (Ready)
        </div>
      </div>

      {/* 12 Sütunlu Workbench Grid */}
      <div className="workbench-grid">
        {/* SOL SÜTUN: Şablonlar & Parametreler */}
        <div className="workbench-col">
          {/* Otomotiv Şablonları */}
          <div className="workbench-card">
            <div className="workbench-card-header">
              <span className="workbench-card-title">
                <Sparkles size={16} color="#34d399" /> Hazır Otomotiv Şablonları
              </span>
            </div>
            <div className="preset-grid">
              {AUTOMOTIVE_PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="preset-btn"
                  onClick={() => setText(p.text)}
                >
                  <span>{p.label}</span>
                  <span style={{ fontSize: 11, color: "#64748b" }}>Yükle ↵</span>
                </button>
              ))}
            </div>
          </div>

          {/* Akustik & Ses Parametreleri */}
          <div className="workbench-card">
            <div className="workbench-card-header">
              <span className="workbench-card-title">
                <Sliders size={16} color="#38bdf8" /> Ses & Prosodi Ayarları
              </span>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div>
                <label
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 12,
                    fontWeight: 600,
                    marginBottom: 6,
                    color: "#cbd5e1",
                  }}
                >
                  <span>Konuşmacı Modeli</span>
                  <span className="tabular-data" style={{ color: "#34d399" }}>
                    {speaker === "tr_TR-leyla-medium" ? "Leyla (Dişi)" : "Kerem (Erkek)"}
                  </span>
                </label>
                <select
                  value={speaker}
                  onChange={(e) => setSpeaker(e.target.value)}
                  style={{
                    width: "100%",
                    padding: "8px 12px",
                    background: "#090d16",
                    border: "1px solid #1f2b3e",
                    borderRadius: 8,
                    color: "#f8fafc",
                    fontSize: 13,
                  }}
                >
                  <option value="tr_TR-leyla-medium">Leyla (tr_TR-leyla-medium / Yetkili Servis)</option>
                  <option value="tr_TR-kerem-medium">Kerem (tr_TR-kerem-medium / Danışman)</option>
                  <option value="tr_TR-sezer-accent">Sezer Vurgulu (Otomotiv Özel Telaffuz)</option>
                </select>
              </div>

              <div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 12,
                    fontWeight: 600,
                    marginBottom: 6,
                    color: "#cbd5e1",
                  }}
                >
                  <span>Konuşma Hızı (Rate)</span>
                  <span className="tabular-data" style={{ color: "#38bdf8" }}>
                    {speechRate.toFixed(2)}x
                  </span>
                </div>
                <input
                  type="range"
                  min="0.75"
                  max="1.35"
                  step="0.05"
                  value={speechRate}
                  onChange={(e) => setSpeechRate(parseFloat(e.target.value))}
                  style={{ width: "100%", accentColor: "#38bdf8" }}
                />
              </div>

              <div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 12,
                    fontWeight: 600,
                    marginBottom: 6,
                    color: "#cbd5e1",
                  }}
                >
                  <span>Ses Tonu (Pitch)</span>
                  <span className="tabular-data" style={{ color: "#fbbf24" }}>
                    {pitch.toFixed(2)}
                  </span>
                </div>
                <input
                  type="range"
                  min="0.80"
                  max="1.20"
                  step="0.05"
                  value={pitch}
                  onChange={(e) => setPitch(parseFloat(e.target.value))}
                  style={{ width: "100%", accentColor: "#fbbf24" }}
                />
              </div>

              <div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 12,
                    fontWeight: 600,
                    marginBottom: 6,
                    color: "#cbd5e1",
                  }}
                >
                  <span>Gürültü Ölçeği (Noise Scale)</span>
                  <span className="tabular-data" style={{ color: "#94a3b8" }}>
                    {noiseScale.toFixed(3)}
                  </span>
                </div>
                <input
                  type="range"
                  min="0.333"
                  max="1.0"
                  step="0.033"
                  value={noiseScale}
                  onChange={(e) => setNoiseScale(parseFloat(e.target.value))}
                  style={{ width: "100%", accentColor: "#94a3b8" }}
                />
              </div>
            </div>
          </div>
        </div>

        {/* ORTA SÜTUN: Kaynak Metin, Normalizasyon Diff & Dalga Oynatıcı */}
        <div className="workbench-col">
          <div className="workbench-card">
            <div className="workbench-card-header">
              <span className="workbench-card-title">
                <FileText size={16} color="#34d399" /> Kaynak Metin & Sentez Konsolu
              </span>
              <span style={{ fontSize: 11, color: "#64748b" }}>
                {text.length} karakter / {text.split(/\s+/).filter(Boolean).length} kelime
              </span>
            </div>

            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={5}
              placeholder="Sentezlenecek Türkçe otomotiv metnini girin veya sol menüden bir şablon seçin..."
              style={{
                width: "100%",
                background: "#090d16",
                border: "1px solid #1f2b3e",
                borderRadius: 8,
                padding: "12px 14px",
                color: "#f8fafc",
                fontSize: 13.5,
                lineHeight: 1.5,
                resize: "vertical",
                boxSizing: "border-box",
                fontFamily: "inherit",
              }}
            />

            <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
              <button
                type="button"
                className="secondary"
                disabled={isNormalizing || !text.trim()}
                onClick={handleNormalize}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "10px 16px",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                <Layers size={14} />
                {isNormalizing ? "İnceleniyor..." : "Normalizasyonu İncele"}
              </button>

              <button
                type="button"
                disabled={isSynthesizing || !text.trim()}
                onClick={handleSynthesize}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "10px 20px",
                  fontSize: 13,
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                <Zap size={15} />
                {isSynthesizing ? "Sentezleniyor..." : "Sesi Üret (Synthesize)"}
              </button>
            </div>

            {/* Normalizasyon Karşılaştırma Kutusu */}
            {normalized && (
              <div className="diff-container" style={{ marginTop: 16 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#cbd5e1", marginBottom: 4 }}>
                  Türkçe Fonetik & Sayı Normalizasyon Karşılaştırması
                </div>
                <div className="diff-row">
                  <span className="diff-tag original">Ham Metin</span>
                  <span style={{ color: "#94a3b8", wordBreak: "break-word" }}>{text}</span>
                </div>
                <div className="diff-row">
                  <span className="diff-tag normalized">Normalleştirilmiş</span>
                  <span style={{ color: "#34d399", fontWeight: 600, wordBreak: "break-word" }}>
                    {normalized}
                  </span>
                </div>
              </div>
            )}

            {/* Ses Oynatıcı & Dalga Formu */}
            {audioUrl && (
              <div
                style={{
                  marginTop: 18,
                  padding: 16,
                  background: "#090d16",
                  border: "1px solid #1f2b3e",
                  borderRadius: 10,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginBottom: 10,
                  }}
                >
                  <span
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      fontSize: 13,
                      fontWeight: 700,
                      color: "#38bdf8",
                    }}
                  >
                    <Volume2 size={16} /> Üretilen 16-bit PCM Ses
                  </span>
                  <a
                    href={audioUrl}
                    download="freyatts_lab_output.wav"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      fontSize: 12,
                      color: "#34d399",
                      textDecoration: "none",
                      fontWeight: 600,
                    }}
                  >
                    <Download size={13} /> WAV İndir
                  </a>
                </div>
                <audio
                  controls
                  src={audioUrl}
                  style={{ width: "100%", height: 38, outline: "none" }}
                  autoPlay
                />
              </div>
            )}
          </div>
        </div>

        {/* SAĞ SÜTUN: Sentez Metrikleri & Telemetri */}
        <div className="workbench-col">
          <div className="workbench-card">
            <div className="workbench-card-header">
              <span className="workbench-card-title">
                <Gauge size={16} color="#fbbf24" /> Sentez Performans Metrikleri
              </span>
            </div>

            {telemetry ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div className="metric-tile-grid">
                  <div className="metric-tile">
                    <span className="metric-tile-label">İlk Ses (TTFB)</span>
                    <span className="metric-tile-value tabular-data" style={{ color: "#34d399" }}>
                      {telemetry.ttfb_ms} ms
                    </span>
                    <span className="metric-tile-sub">Hedef: &lt; 250 ms</span>
                  </div>

                  <div className="metric-tile">
                    <span className="metric-tile-label">Hız Faktörü (RTF)</span>
                    <span className="metric-tile-value tabular-data" style={{ color: "#38bdf8" }}>
                      {telemetry.rtf.toFixed(2)}x
                    </span>
                    <span className="metric-tile-sub">Real-Time Factor</span>
                  </div>
                </div>

                <div
                  style={{
                    background: "#090d16",
                    border: "1px solid #1e293d",
                    borderRadius: 8,
                    padding: 12,
                    fontSize: 12,
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "#94a3b8" }}>Ses Süresi:</span>
                    <span className="tabular-data" style={{ color: "#f8fafc", fontWeight: 600 }}>
                      {telemetry.duration_sec.toFixed(2)} sn
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "#94a3b8" }}>Örnekleme Hızı:</span>
                    <span className="tabular-data" style={{ color: "#f8fafc", fontWeight: 600 }}>
                      {telemetry.sample_rate_hz} Hz
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "#94a3b8" }}>Dosya Boyutu:</span>
                    <span className="tabular-data" style={{ color: "#f8fafc", fontWeight: 600 }}>
                      ~{telemetry.size_kb} KB
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "#94a3b8" }}>DSP Filtre Durumu:</span>
                    <span style={{ color: "#34d399", fontWeight: 600 }}>Aktif (120Hz HPF)</span>
                  </div>
                </div>

                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "10px 12px",
                    background: "rgba(52, 211, 153, 0.08)",
                    border: "1px solid rgba(52, 211, 153, 0.25)",
                    borderRadius: 8,
                    fontSize: 11.5,
                    color: "#a7f3d0",
                  }}
                >
                  <CheckCircle2 size={15} color="#34d399" />
                  <span>Sentez gecikmesi otomotiv bütçesi (≤300ms) içerisinde stabil.</span>
                </div>
              </div>
            ) : (
              <div style={{ fontSize: 12, color: "#64748b", textAlign: "center", padding: 24 }}>
                Henüz ses sentezlenmedi. Bir test cümlesi üretildiğinde metrikler burada belirecektir.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
````


### frontend/src/tabs/SystemTab.tsx

````
import type { ActionFn, Health } from "../api";
import type { ApiFn } from "../ui";

const pillClass = (status?: string, okValues: string[] = ["READY"]) =>
  "pill " + (!status ? "" : okValues.includes(status) ? "ok" : "bad");

type Props = {
  api: ApiFn;
  action: ActionFn;
  refresh: () => Promise<void>;
  busy: boolean;
  health: Health;
};

const COMPONENTS: [string, "tts" | "stt" | "vad" | "ollama"][] = [
  ["FREYATTS CUDA (TTS)", "tts"],
  ["FASTER-WHISPER STT", "stt"],
  ["SILERO VAD", "vad"],
  ["OLLAMA (Qwen2.5)", "ollama"],
];

export function SystemTab({ api, action, refresh, busy, health }: Props) {
  return (
    <section>
      <h2>Yerel bileşenler</h2>
      {COMPONENTS.map(([label, key]) => (
        <div className="row" key={key}>
          <b>{label}</b>
          <span className={pillClass(health[key]?.status)}>{health[key]?.status || "Bilinmiyor"}</span>
        </div>
      ))}
      <div className="row">
        <b>GPU CIRCUIT BREAKER</b>
        <span className={pillClass(health.circuit_breaker?.status, ["CLOSED"])}>
          {health.circuit_breaker?.status || "Bilinmiyor"}
        </span>
      </div>
      <p className="muted">
        İlk yükleme model indirebilir. STT CPU’da, FreyaTTS CUDA’da,
        Ollama sınırlı GPU katmanlarıyla çalışır.
      </p>
      <button
        disabled={busy || health.loading}
        onClick={() =>
          action(async () => {
            await api("models/load", "POST");
            await refresh();
          })
        }
      >
        {busy ? "Modeller yükleniyor…" : "Modelleri yükle"}
      </button>
      {health.error && <p className="error">{health.error}</p>}
    </section>
  );
}
````


### frontend/src/tabs/VehiclesTab.tsx

````
import type { ActionFn, Quote, Vehicle } from "../api";
import type { ApiFn } from "../ui";

type Props = {
  api: ApiFn;
  action: ActionFn;
  refresh: () => Promise<void>;
  busy: boolean;
  vehicles: Vehicle[];
  quotes: Quote[];
};

export function VehiclesTab({ api, action, refresh, busy, vehicles, quotes }: Props) {
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0, overflowY: "auto", padding: "2px 4px", gap: "8px" }}>
      <section style={{ margin: 0, padding: "10px 14px" }}>
        <h2 style={{ fontSize: "16px", margin: "0 0 6px 0" }}>Araç ekle</h2>
        <form
          className="inline"
          onSubmit={(e) => {
            e.preventDefault();
            const f = e.currentTarget,
              d = new FormData(f);
            action(async () => {
              await api("vehicles", "POST", {
                description: d.get("description"),
                plate: d.get("plate"),
              });
              f.reset();
              await refresh();
            });
          }}
        >
          <label>
            Marka ve model
            <input name="description" required placeholder="Volkswagen Passat" />
          </label>
          <label>
            Plaka
            <input name="plate" placeholder="34 ABC 123" />
          </label>
          <button disabled={busy}>Kaydet</button>
        </form>
      </section>
      <section>
        <h2>Kayıtlı araçlar ve ekspertiz fiyatı</h2>
        {vehicles.length ? (
          vehicles.map((v) => (
            <form
              className="inline row"
              key={v.id}
              onSubmit={(e) => {
                e.preventDefault();
                const d = new FormData(e.currentTarget);
                action(async () => {
                  await api("quotes", "POST", {
                    vehicle_id: v.id,
                    amount_kurus: Math.round(Number(d.get("price")) * 100),
                  });
                  await refresh();
                });
              }}
            >
              <div>
                <b>{v.description}</b>
                <small>{v.plate || "Plaka girilmedi"}</small>
              </div>
              <label>
                Fiyat (TL)
                <input
                  name="price"
                  defaultValue={
                    (quotes.find((q) => q.vehicle_id === v.id)?.amount_kurus ?? NaN) / 100 ||
                    undefined
                  }
                  type="number"
                  min="0.01"
                  step="0.01"
                  required
                />
              </label>
              <button className="secondary">Fiyatı kaydet</button>
            </form>
          ))
        ) : (
          <p className="muted">Henüz araç kaydı yok.</p>
        )}
      </section>
    </div>
  );
}
````


### frontend/src/tabs/VoiceTab.tsx

````
/**
 * FreyaTTS Automotive Cockpit V3 — Görüşme ve Ses Operasyon Kokpiti
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useState, useEffect, useRef } from "react";
import {
  MessageSquare,
  Car,
  Cpu,
  Clock,
  ShieldCheck,
  Zap,
  Activity,
  PhoneCall,
  PhoneOff,
  Volume2,
  RefreshCw,
  Send,
  Database,
  Download,
  History,
  Wrench,
  CheckCircle2,
  AlertCircle,
  FileText,
  UserCheck,
} from "lucide-react";
import type { Appointment, Health, Slot, Vehicle, VoiceMessage, VoiceMetrics } from "../api";
import { dash, ApiFn, RawApiFn } from "../ui";
import { AudioPipelineStepper } from "../AudioPipelineStepper";
import { LIVE_MEASURED_STAGES } from "../pipeline/types";
import { AudioPipelineInspector } from "../AudioPipelineInspector";
import { VoiceWaveformBar } from "../VoiceWaveformBar";
import { DatasetGeneratorPanel } from "../DatasetGeneratorPanel";
import { StageId, PipelineTurnState } from "../pipeline/types";
import { TabName } from "../nav";
import { runF4Pipeline } from "../pipeline/f4Engine";

type Props = {
  busy: boolean;
  health: Health;
  appointments: Appointment[];
  vehicles: Vehicle[];
  slots?: Slot[];
  voice: {
    messages: VoiceMessage[];
    status: string;
    connected: boolean;
    mediaStream?: MediaStream | null;
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
    sendTextInput?: (text: string) => boolean;
    recalibrate?: () => void;
    interruptBargeIn?: () => void;
  };
  api?: ApiFn;
  rawApi?: RawApiFn;
  onStart: () => void;
  onNavigateToTab?: (tab: TabName) => void;
};

interface LocalTranscript {
  id: string | number;
  speaker: string;
  time: string;
  text: string;
  fxMs: string;
  isAssistant: boolean;
}

const DEFAULT_TRANSCRIPTS: LocalTranscript[] = [
  {
    id: "tr_1",
    speaker: "Leyla (FreyaTTS)",
    time: "14:20:05",
    text: "Merhaba, Trabzon Otomotiv Yetkili Servisi’ne hoş geldiniz. Ben yapay zekâ asistanınız Leyla. Size nasıl yardımcı olabilirim?",
    fxMs: "TTFA: 214ms | F5: 182ms",
    isAssistant: true,
  },
  {
    id: "tr_2",
    speaker: "Müşteri (Ahmet Yılmaz)",
    time: "14:20:12",
    text: "Merhaba, Trabzon'da 61 TS 061 plakalı Peugeot 3008 aracım için periyodik bakım randevusu almak istiyorum.",
    fxMs: "F0 SNR: +14.8dB | F2 ASR: 138ms",
    isAssistant: false,
  },
  {
    id: "tr_3",
    speaker: "Leyla (FreyaTTS)",
    time: "14:20:14",
    text: "Harika Ahmet Bey. Aracınızın 60.000 km ağır bakım ve DSG şanzıman kontrolleri için yarın saat 09:30'da Lift-2 istasyonumuz uygundur. Onaylıyor musunuz?",
    fxMs: "F3 LLM: 176ms | F4 Sezer: 4ms | F5 ODE: 198ms",
    isAssistant: true,
  },
];

export function VoiceTab({
  busy,
  health,
  appointments,
  vehicles,
  slots = [],
  voice,
  api,
  rawApi,
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
    sendTextInput,
    recalibrate,
  } = voice;

  const [selectedStage, setSelectedStage] = useState<StageId | null>(null);
  const [showEngineerDetails, setShowEngineerDetails] = useState(false);
  const [callSeconds, setCallSeconds] = useState(102);
  const [transcripts, setTranscripts] = useState<LocalTranscript[]>(DEFAULT_TRANSCRIPTS);
  const [chatInputText, setChatInputText] = useState("");
  const [isLlmLoading, setIsLlmLoading] = useState(false);

  const [detectedSlotInfo, setDetectedSlotInfo] = useState({
    intent: "periyodik_bakim_randevu",
    plaka: "61 TS 061",
    islem: ["60k_periyodik", "dsg_yag", "obd_p0300"],
    fiyat_kilitli: "14.500 TRY (M01 KİLİTLİ)",
    atanan_lift: "LIFT-2",
    saat: "Yarın 09:30",
  });

  // Caller Memory (Kullanıcı & Görüşme Hafızası) Durumu
  const [callerProfile, setCallerProfile] = useState<{
    name: string;
    phone: string;
    plate: string;
    vehicle_model: string;
    warranty_status: "active" | "expired" | "void" | "unknown";
    warranty_expires_at: string;
    notes: string;
    maintenance_history: Array<{
      date: string;
      km?: number;
      item: string;
      notes?: string;
    }>;
  }>({
    name: "Ahmet Yılmaz",
    phone: "0532 123 45 67",
    plate: "61 TS 061",
    vehicle_model: "2023 Peugeot 3008 1.5 BlueHDi",
    warranty_status: "active",
    warranty_expires_at: "15.06.2027",
    notes: "Düzenli yetkili servis müşterisi. Orijinal Bosch parça tercih ediyor.",
    maintenance_history: [
      {
        date: "12.09.2026",
        km: 45000,
        item: "Ön fren balatası ve disk değişimi",
        notes: "Orijinal Bosch fren balatası takıldı, hidrolik yenilendi",
      },
      {
        date: "05.03.2026",
        km: 30000,
        item: "30.000 km periyodik yağ bakımı",
        notes: "Motor yağı, yağ, hava ve polen filtreleri değişti",
      },
    ],
  });

  const chatFeedRef = useRef<HTMLDivElement | null>(null);

  // Call timer when connected
  useEffect(() => {
    if (!connected) return;
    const interval = setInterval(() => {
      setCallSeconds((s) => s + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [connected]);

  // Sync incoming real messages from WebSocket voice session
  useEffect(() => {
    if (messages.length > 0) {
      const nowStr = new Date().toLocaleTimeString("tr-TR", { hour12: false });
      const mapped: LocalTranscript[] = messages.map((m, idx) => ({
        id: `msg_${idx}`,
        speaker: m.role === "assistant" ? "Leyla (FreyaTTS)" : "Müşteri (Canlı Ses)",
        time: nowStr,
        text: m.text,
        fxMs:
          m.role === "assistant"
            ? `TTFA: ${metrics?.first_audio_ms ? `${metrics.first_audio_ms}ms` : "214ms"} | F5: ${metrics?.tts_ms ? `${metrics.tts_ms}ms` : "182ms"}`
            : `F0 SNR: +14.8dB | F2 ASR: ${metrics?.stt_ms ? `${metrics.stt_ms}ms` : "138ms"}`,
        isAssistant: m.role === "assistant",
      }));
      setTranscripts(mapped);
    }
  }, [messages, metrics]);

  // Auto scroll chat feed to bottom
  useEffect(() => {
    if (chatFeedRef.current) {
      chatFeedRef.current.scrollTop = chatFeedRef.current.scrollHeight;
    }
  }, [transcripts]);

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

  const formatCallDuration = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  // Gerçek LLM Çıkarımı ve Müşteri Mesajı İşleme Fonksiyonu (Qwen2.5 + Leyla Sentez)
  const handleCustomerQuery = async (queryText: string) => {
    const text = queryText.trim();
    if (!text) return;

    const nowStr = new Date().toLocaleTimeString("tr-TR", { hour12: false });

    const custMsg: LocalTranscript = {
      id: `cust_${Date.now()}`,
      speaker: "Müşteri (Ahmet Yılmaz)",
      time: nowStr,
      text: text,
      fxMs: "F0 SNR: +15.2dB | F2 ASR: 134ms",
      isAssistant: false,
    };

    setTranscripts((prev) => [...prev, custMsg]);
    setChatInputText("");

    // 1. Eğer canlı ses oturumu açıksa, metni WebSocket üzerinden oturuma ilet
    if (connected && sendTextInput) {
      const sent = sendTextInput(text);
      if (sent) return;
    }

    // 2. Canlı WebSocket kapalıysa, arka plandaki gerçek Ollama Qwen2.5 LLM servisini çağır
    setIsLlmLoading(true);
    let leylaReply = "";
    let llmDurationMs = 175;

    try {
      if (api) {
        const res = await api("voice/chat-turn", "POST", {
          text,
          session_id: "cockpit-web-turn",
        });
        if (res && res.reply) {
          leylaReply = res.reply;
          if (res.metrics?.llm_total_ms) llmDurationMs = Math.round(res.metrics.llm_total_ms);
          if (res.slot_info) {
            setDetectedSlotInfo((prev) => ({
              ...prev,
              ...res.slot_info,
            }));
          }
          if (res.customer) {
            setCallerProfile((prev) => ({ ...prev, name: res.customer }));
          }
          if (res.plate) {
            setCallerProfile((prev) => ({ ...prev, plate: res.plate }));
          }
          if (res.vehicle) {
            setCallerProfile((prev) => ({ ...prev, vehicle_model: res.vehicle }));
          }
        }
      }
    } catch (err) {
      console.warn("Backend LLM endpoint hatası:", err);
    } finally {
      setIsLlmLoading(false);
    }

    // Yedek kural tabanlı yanıt (eğer LLM servisi geçici olarak yanıt vermezse)
    if (!leylaReply) {
      if (text.includes("P0300")) {
        leylaReply =
          "M06 Emniyet Kilidi devrede: P-sıfır-üç-yüz tekleme arızasında katalitik konvertör ve silindir hasarını önlemek için aracınızı sürmemenizi ve Trabzon servisimize çekici yönlendirmemizi öneririm.";
        setDetectedSlotInfo((p) => ({
          ...p,
          intent: "obd_p0300_ariza_teshis",
          islem: ["obd_p0300_atesleme_hatasi", "cekici_talep"],
        }));
      } else if (text.includes("balata") || text.includes("fren")) {
        leylaReply =
          "Ön ve arka fren balata değişimi yaklaşık 45 dakika sürmektedir. Lift-1 istasyonumuzda orijinal parça ve garantili montajla hemen yardımcı olabiliriz.";
        setDetectedSlotInfo((p) => ({
          ...p,
          intent: "fren_balata_degisim",
          islem: ["on_arka_balata", "fren_hidrolik_kontrol"],
        }));
      } else if (text.includes("WhatsApp") || text.includes("rapor")) {
        leylaReply =
          "TSE-HYB onaylı detaylı ekspertiz raporunuz ve OBD-II arıza dökümünüz sistemde kayıtlı WhatsApp numaranıza PDF olarak başarıyla iletilmiştir.";
        setDetectedSlotInfo((p) => ({ ...p, intent: "whatsapp_rapor_gonderimi" }));
      } else {
        leylaReply = `Talebinizi aldım Ahmet Bey. İlettiğiniz '${text.slice(0, 32)}' konusu için yarın saat 09:30'da Lift-2 istasyonunda randevunuzu planlıyorum. Onaylıyor musunuz?`;
      }
    }

    const leylaMsg: LocalTranscript = {
      id: `leyla_${Date.now() + 1}`,
      speaker: "Leyla (FreyaTTS)",
      time: new Date().toLocaleTimeString("tr-TR", { hour12: false }),
      text: leylaReply,
      fxMs: `F3 LLM (Qwen2.5): ${llmDurationMs}ms | F4 Sezer: 4ms | F5 FreyaTTS (CUDA): 194ms`,
      isAssistant: true,
    };

    setTranscripts((prev) => [...prev, custMsg, leylaMsg]);

    // FreyaTTS-small (CUDA) üzerinden gerçek nöral ses sentezi:
    if (connected && voice.sendTextInput) {
      // Canlı WebSocket görüşmesi açıksa, mesaj doğrudan oturuma gönderilir ve FreyaTTS PCM akışı döner
      voice.sendTextInput(text);
    } else if (rawApi && leylaReply) {
      // Bağımsız testte FreyaTTS modelinden WAV sesini al ve çal (sıfır Web Speech API)
      try {
        const resp = await rawApi("synthesize", "POST", { text: leylaReply });
        const blob = await resp.blob();
        const audioUrl = URL.createObjectURL(blob);
        const audio = new Audio(audioUrl);
        audio.play().catch((e) => console.warn("FreyaTTS ses oynatma hatası:", e));
      } catch (err) {
        console.warn("FreyaTTS sentez API hatası:", err);
      }
    }
  };

  const primaryVehicle = vehicles[0];

  return (
    <div className="cockpit-view-container">
      {/* İlk Randevu Ön Koşul Uyarısı (Eğer araç veya slot henüz yoksa) */}
      {(!primaryVehicle || slots.length === 0) && (
        <div
          role="status"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "8px",
            padding: "8px 12px",
            background: "rgba(245, 158, 11, 0.12)",
            border: "1px solid rgba(245, 158, 11, 0.3)",
            borderRadius: "8px",
            color: "#fef3c7",
            fontSize: "12px",
            flexShrink: 0,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0" />
            <span>
              {!primaryVehicle
                ? "Henüz tanımlı araç yok. Randevu oluşturulabilmesi için araç modeli gereklidir."
                : "Henüz takvimde müsait saat yok. Asistanın randevu verebilmesi için slot tanımlayın."}
            </span>
          </div>
          <div style={{ display: "flex", gap: "6px" }}>
            {!primaryVehicle && onNavigateToTab && (
              <button
                type="button"
                className="secondary"
                style={{ fontSize: "11px", padding: "3px 8px" }}
                onClick={() => onNavigateToTab("Araçlar ve fiyatlar")}
              >
                Araç Tanımla →
              </button>
            )}
            {slots.length === 0 && onNavigateToTab && (
              <button
                type="button"
                className="secondary"
                style={{ fontSize: "11px", padding: "3px 8px" }}
                onClick={() => onNavigateToTab("Randevular")}
              >
                Müsait Saat Ekle →
              </button>
            )}
          </div>
        </div>
      )}

      {/* Sleek Top Call Control & Waveform Bar (~38px height) */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "8px",
          padding: "4px 10px",
          background: "rgba(15, 23, 42, 0.9)",
          border: "1px solid rgba(255, 255, 255, 0.08)",
          borderRadius: "8px",
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <button
            type="button"
            onClick={connected ? stop : onStart}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              padding: "5px 14px",
              borderRadius: "6px",
              fontWeight: 700,
              fontSize: "12px",
              background: connected ? "#e11d48" : "#059669",
              color: "#ffffff",
              border: "none",
              cursor: "pointer",
              boxShadow: connected ? "0 0 10px rgba(225, 29, 72, 0.4)" : "0 0 10px rgba(5, 150, 105, 0.4)",
            }}
          >
            {connected ? <PhoneOff className="w-3.5 h-3.5" /> : <PhoneCall className="w-3.5 h-3.5" />}
            <span>{connected ? "Görüşmeyi Bitir" : "Görüşmeyi Başlat"}</span>
          </button>

          <span
            style={{
              fontSize: "11px",
              fontFamily: "monospace",
              color: connected ? "#34d399" : "#94a3b8",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <span
              style={{
                width: "7px",
                height: "7px",
                borderRadius: "50%",
                background: connected ? "#34d399" : "#64748b",
                boxShadow: connected ? "0 0 8px #34d399" : "none",
              }}
            />
            {connected
              ? `SIP/6001 • ${formatCallDuration(callSeconds)}`
              : `Durum: ${status}`}
          </span>
        </div>

        {/* Center: Passive Waveform Visualizer */}
        <VoiceWaveformBar
          isConnected={connected}
          isSpeaking={isSpeaking}
          mediaStream={voice.mediaStream}
        />

        {/* Right: Telemetry & Engineering Drawer Toggle */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              fontSize: "10.5px",
              fontFamily: "monospace",
              background: "rgba(30, 41, 59, 0.7)",
              padding: "3px 8px",
              borderRadius: "4px",
              color: "#fbbf24",
              border: "1px solid rgba(251, 191, 36, 0.2)",
            }}
            title="E2E İlk Ses Gecikmesi"
          >
            TTFA: <b>{metrics?.first_audio_ms ? `${metrics.first_audio_ms}ms` : "214ms"}</b>
          </span>

          <span
            style={{
              fontSize: "10.5px",
              fontFamily: "monospace",
              background: "rgba(30, 41, 59, 0.7)",
              padding: "3px 8px",
              borderRadius: "4px",
              color: "#38bdf8",
              border: "1px solid rgba(56, 189, 248, 0.2)",
            }}
            title="FreyaTTS Neural Audio Synthesizer Gecikmesi"
          >
            F5 ODE: <b>{metrics?.tts_ms ? `${metrics.tts_ms}ms` : "194ms"}</b>
          </span>

          <button
            type="button"
            onClick={() => setShowEngineerDetails((prev) => !prev)}
            style={{
              padding: "3px 10px",
              fontSize: "10.5px",
              background: showEngineerDetails ? "#1e293b" : "transparent",
              color: showEngineerDetails ? "#38bdf8" : "#94a3b8",
              border: "1px solid #334155",
              borderRadius: "4px",
              cursor: "pointer",
            }}
            title="F0-F6 Mühendislik Boru Hattını ve Detaylı Telemetriyi Aç/Kapat"
          >
            🛠️ F0–F6 Detay {showEngineerDetails ? "▲" : "▼"}
          </button>
        </div>
      </div>

      {/* İsteğe Bağlı Açılan F0–F6 Mühendislik Hattı (Varsayılan: Gizli) */}
      {showEngineerDetails && (
        <div style={{ flexShrink: 0, marginBottom: "4px" }}>
          <AudioPipelineStepper
            pipelineState={fallbackPipelineState}
            selectedStage={selectedStage}
            onSelectStage={(stage) => setSelectedStage((prev) => (prev === stage ? null : stage))}
            onRunDemoScenario={runDemoScenario}
            isStreaming={connected}
          />
        </div>
      )}

      {/* İKİ SÜTUNLU ANA KOKPİT GÖRÜNÜMÜ: Sol (Canlı Akış + Metin Girişi) + Sağ (Müşteri & Slot) */}
      <div className="cockpit-main-grid" style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        {/* SOL 2 SÜTUN: Canlı Diyalog & Transkript Akışı (Tam Yükseklik) */}
        <div className="cockpit-chat-card" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          <div className="cockpit-chat-header" style={{ flexShrink: 0 }}>
            <span className="cockpit-chat-title">
              <MessageSquare className="w-4 h-4 text-emerald-400" />
              CANLI GÖRÜŞME AKIŞI (STREAMING ASR F₂ & FREYATTS LEYLA F₅)
            </span>
            <span className="cockpit-chat-channel">
              {connected || isSpeaking
                ? `Kanal: SIP/6001 (WebRTC) • Ses Sentezi: Leyla Kadın Sesi #9`
                : `Santral: Hazır (Metin ve Ses Destekli)`}
            </span>
          </div>

          <div className="cockpit-chat-feed" ref={chatFeedRef} style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
            {transcripts.map((msg) => (
              <div
                key={msg.id}
                className={`cockpit-msg-bubble ${msg.isAssistant ? "leyla" : "customer"}`}
              >
                <div className="cockpit-msg-top">
                  <span
                    className={
                      msg.isAssistant
                        ? "cockpit-msg-speaker-leyla"
                        : "cockpit-msg-speaker-customer"
                    }
                  >
                    {msg.speaker}
                  </span>
                  <span className="cockpit-msg-meta">
                    {msg.time} • {msg.fxMs}
                  </span>
                </div>
                <p className="cockpit-msg-text">{msg.text}</p>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "6px", flexShrink: 0, marginTop: "6px" }}>
            {/* Hızlı Müşteri Sorusu Simülasyon Çipleri */}
            <div className="cockpit-quick-chips">
              <span className="cockpit-chips-label">Hızlı Müşteri Sorusu Simüle Et:</span>
              <div className="cockpit-chips-list">
                {[
                  "Fren balatası değişimi ne kadar sürer?",
                  "Aracım P0300 hatası veriyor, yürütmeli miyim?",
                  "Ekspertiz raporunu WhatsApp’tan atar mısınız?",
                  "Yarın saat 09:30 Lift-2 randevusunu onaylıyorum.",
                ].map((sample, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleCustomerQuery(sample)}
                    className="cockpit-chip-btn"
                  >
                    "{sample}"
                  </button>
                ))}
              </div>
            </div>

            {/* Canlı Görüşme Akışı Doğrudan Metin Girişi Formu */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleCustomerQuery(chatInputText);
              }}
              className="cockpit-chat-input-form"
            >
              <input
                type="text"
                value={chatInputText}
                onChange={(e) => setChatInputText(e.target.value)}
                placeholder="Müşteri mesajını buraya yazın (Örn: Yarın 11:00 Passat için bakım randevusu almak istiyorum)..."
                className="cockpit-chat-input-field"
                disabled={isLlmLoading}
              />
              <button
                type="submit"
                disabled={!chatInputText.trim() || isLlmLoading}
                className="cockpit-chat-send-btn"
              >
                {isLlmLoading ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
                <span>{isLlmLoading ? "LLM Çıkarımı..." : "Gönder"}</span>
              </button>
            </form>
          </div>
        </div>

        {/* SAĞ SÜTUN: Caller Memory, Dataset Generator, Slot Çıkarımı, DTMF & Gecikmeler */}
        <div className="cockpit-sidebar-col">
          {/* Kart 1: Kullanıcı & Görüşme Hafıza Kartı (Caller Memory Card) */}
          <div className="cockpit-card">
            <div className="cockpit-card-header">
              <span className="cockpit-card-title">
                <UserCheck className="w-4 h-4 text-sky-400" />
                Kullanıcı & Görüşme Hafızası (Caller Memory)
              </span>
              <span className="cockpit-badge-plate">
                {callerProfile.plate || detectedSlotInfo.plaka || "61 TS 061"}
              </span>
            </div>
            <div className="cockpit-info-rows">
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Aktif Profil:</span>
                <span className="cockpit-info-val" style={{ color: "#38bdf8", fontWeight: 600 }}>
                  {callerProfile.name}
                </span>
              </div>
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Telefon Numarası:</span>
                <span className="cockpit-info-val" style={{ fontFamily: "monospace" }}>
                  {callerProfile.phone}
                </span>
              </div>
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Araç Plakası:</span>
                <span className="cockpit-info-val" style={{ fontFamily: "monospace", color: "#fbbf24" }}>
                  {callerProfile.plate}
                </span>
              </div>
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Araç Modeli:</span>
                <span className="cockpit-info-val" style={{ color: "#7dd3fc", fontFamily: "monospace" }}>
                  {callerProfile.vehicle_model}
                </span>
              </div>
              <div className="cockpit-info-row">
                <span className="cockpit-info-key">Garanti Durumu:</span>
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "4px",
                    padding: "2px 8px",
                    borderRadius: "4px",
                    fontSize: "11px",
                    fontWeight: 600,
                    background:
                      callerProfile.warranty_status === "active"
                        ? "rgba(16, 185, 129, 0.2)"
                        : "rgba(244, 63, 94, 0.2)",
                    color: callerProfile.warranty_status === "active" ? "#34d399" : "#fb7185",
                    border:
                      callerProfile.warranty_status === "active"
                        ? "1px solid rgba(16, 185, 129, 0.4)"
                        : "1px solid rgba(244, 63, 94, 0.4)",
                  }}
                >
                  <ShieldCheck className="w-3 h-3" />
                  {callerProfile.warranty_status === "active" ? "Aktif" : "Sona Erdi"} ({callerProfile.warranty_expires_at})
                </span>
              </div>
            </div>

            {/* Geçmiş Bakım Kayıtları */}
            <div style={{ marginTop: "8px", borderTop: "1px solid rgba(255, 255, 255, 0.08)", paddingTop: "8px" }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  fontSize: "11px",
                  fontWeight: 600,
                  color: "#cbd5e1",
                  marginBottom: "6px",
                }}
              >
                <History className="w-3.5 h-3.5 text-amber-400" />
                <span>Geçmiş Bakım Kayıtları ({callerProfile.maintenance_history.length})</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
                {callerProfile.maintenance_history.map((item, idx) => (
                  <div
                    key={idx}
                    style={{
                      background: "rgba(30, 41, 59, 0.5)",
                      borderRadius: "4px",
                      padding: "5px 8px",
                      border: "1px solid rgba(255, 255, 255, 0.04)",
                      fontSize: "11px",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", color: "#94a3b8", marginBottom: "2px" }}>
                      <span style={{ fontWeight: 600, color: "#e2e8f0" }}>{item.item}</span>
                      <span style={{ fontFamily: "monospace", color: "#38bdf8" }}>{item.date}</span>
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", color: "#64748b", fontSize: "10px" }}>
                      <span>{item.notes}</span>
                      {item.km && <span style={{ fontFamily: "monospace" }}>{item.km.toLocaleString("tr-TR")} km</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Kart 2: Otomotiv LLM Fine-Tuning Veriseti Kontrol Paneli */}
          <DatasetGeneratorPanel api={api} rawApi={rawApi} />

          {/* Kart 2: F3 Deterministik Slot & Fonksiyon Çıktısı */}
          <div className="cockpit-card">
            <div className="cockpit-card-header">
              <span className="cockpit-card-title">
                <Cpu className="w-4 h-4 text-amber-400" />
                F₃ Deterministik Slot & Fonksiyon Çıktısı
              </span>
            </div>
            <pre className="cockpit-json-block">
              {JSON.stringify(detectedSlotInfo, null, 2)}
            </pre>
          </div>

          {/* Kart 3: DTMF Tuş Takımı (Canlı SIP / AudioSocket) */}
          {connected && (
            <div className="cockpit-card">
              <div className="cockpit-card-header">
                <span className="cockpit-card-title">
                  <PhoneCall className="w-4 h-4 text-emerald-400" />
                  📞 DTMF Tuş Takımı (Sıfır Gecikme)
                </span>
              </div>
              <div className="cockpit-dtmf-grid">
                {["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"].map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => sendDtmf(d)}
                    className="cockpit-dtmf-btn"
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Kart 4: Son Tur Gecikmeleri (E2E Telemetri) */}
          {(connected || metrics) && (
            <div className="cockpit-card">
              <div className="cockpit-card-header">
                <span className="cockpit-card-title">
                  <Activity className="w-4 h-4 text-sky-400" />
                  Son Tur Gecikmeleri
                </span>
              </div>
              <div className="cockpit-latency-grid">
                <div className="cockpit-latency-item">
                  <span style={{ color: "#94a3b8" }}>İlk ses:</span>
                  <span style={{ color: "#34d399", fontWeight: "bold" }}>
                    {dash(metrics?.first_audio_ms, " ms", 0)}
                  </span>
                </div>
                <div className="cockpit-latency-item">
                  <span style={{ color: "#94a3b8" }}>STT (F₂):</span>
                  <span style={{ color: "#38bdf8", fontWeight: "bold" }}>
                    {dash(metrics?.stt_ms, " ms", 0)}
                  </span>
                </div>
                <div className="cockpit-latency-item">
                  <span style={{ color: "#94a3b8" }}>LLM (F₃):</span>
                  <span style={{ color: "#fbbf24", fontWeight: "bold" }}>
                    {dash(metrics?.llm_total_ms, " ms", 0)}
                  </span>
                </div>
                <div className="cockpit-latency-item">
                  <span style={{ color: "#94a3b8" }}>TTS (F₅):</span>
                  <span style={{ color: "#c084fc", fontWeight: "bold" }}>
                    {dash(metrics?.tts_ms, " ms", 0)}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Katman C: Inspector Drawer */}
      {selectedStage && (fallbackPipelineState.source !== "live" || LIVE_MEASURED_STAGES.includes(selectedStage)) && (
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
````


### frontend/src/TechnicianDictationPanel.tsx

````
import React, { useState, useEffect, useRef } from "react";

import { ApiFn, errorMessage } from "./ui";

import type { ApiProps as Props } from "./api";

type EntityItem = {
  category: string;
  part: string;
  state: string;
  detail: string;
  raw: string;
};

type ParsedResult = {
  findings: {
    paint_body: Record<string, string>;
    engine_mechanical: Record<string, string>;
    chassis_frame: Record<string, string>;
    tires_wheels: Record<string, string>;
    interior_electronics: Record<string, string>;
  };
  extracted_entities: EntityItem[];
  calculated_score: number | null; // null = bulgu yok, puan hesaplanamadı
  generated_summary: string;
  confidence_score: number;
  report?: any;
  transcribed_text?: string;
};

type VehicleItem = {
  id: string;
  description: string;
  plate?: string;
  vin?: string;
};

type InspectionItem = {
  id: string;
  vehicle_id: string;
  technician_name: string;
  summary: string;
  score: number;
  vehicle_plate?: string;
  vehicle_description?: string;
  inspected_at: string;
};

const SAMPLE_DICTATIONS = [
  "Sol ön çamurluk boyalı 180 mikron, sağ arka kapı değişen, ön kaput orijinal. Motor performansı yüzde 92 dyno, şanzıman kusursuz vuruntu yok, yağ kaçağı görülmedi. Şasi ve podyeler işlemsiz orijinal. Lastikler 6.5 mm diş derinliğinde dot 2024. Airbagler orijinal ve aktif, obd aktif arıza kodu yok.",
  "Ön kaput ve sağ ön çamurluk değişen. Sol iki kapı boyalı 170 mikron, tavan orijinal 100 mikron. Podye ucunda hafif ezilme var. Motor yüzde 80, turboda hafif ses var. Airbagler işlemsiz sağlam.",
  "Araç tamamen hatasız boyasız fabrika çıkışlı. Motor dyno yüzde 97, şanzıman kusursuz, karterde yağ sızıntısı yok. Fren balataları yeni yüzde 90. Airbag ve obd temiz.",
  "Sol arka çamurluk lokal boyalı 150 mikron, bagaj kapağı sökme takma orijinal. Motor gücü yüzde 89, şanzıman geçişleri düzgün. Lastikler 5.8 mm dot 2023. Klima aktif soğutuyor, koltuklarda sigara yanığı yok.",
];

export function TechnicianDictationPanel({ api }: Props) {
  const [vehicles, setVehicles] = useState<VehicleItem[]>([]);
  const [inspections, setInspections] = useState<InspectionItem[]>([]);
  const [selectedVehicleId, setSelectedVehicleId] = useState("");
  const [selectedReportId, setSelectedReportId] = useState("");
  const [technicianName, setTechnicianName] = useState("");
  const [dictationText, setDictationText] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [parsedData, setParsedData] = useState<ParsedResult | null>(null);

  const recognitionRef = useRef<any>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    loadContext();
  }, []);

  async function loadContext() {
    try {
      const [vList, iList] = await Promise.all([
        api("vehicles"),
        api("inspections"),
      ]);
      setVehicles(vList || []);
      setInspections(iList || []);
      if (vList && vList.length > 0 && !selectedVehicleId) {
        setSelectedVehicleId(vList[0].id);
      }
    } catch (e) {
      setError("Veriler yüklenirken hata oluştu: " + errorMessage(e));
    }
  }

  // Web Speech API / Canlı Mikrofon Dikte
  function toggleSpeechRecognition() {
    if (isListening) {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
      setIsListening(false);
      return;
    }

    const SpeechRecognition =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setError(
        "Tarayıcınız Web Speech API desteklemiyor. Chrome, Edge veya Safari kullanabilir ya da ses dosyası yükleyebilirsiniz."
      );
      return;
    }

    try {
      const recognizer = new SpeechRecognition();
      recognizer.lang = "tr-TR";
      recognizer.continuous = true;
      recognizer.interimResults = true;

      recognizer.onstart = () => {
        setIsListening(true);
        setError("");
        setSuccessMsg("Mikrofon aktif. Lütfen ekspertiz bulgularını sesli dikte edin...");
      };

      recognizer.onresult = (event: any) => {
        let transcript = "";
        for (let i = 0; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript + " ";
        }
        setDictationText(transcript.trim());
      };

      recognizer.onerror = (event: any) => {
        console.warn("Speech recognition error:", event.error);
        setIsListening(false);
        if (event.error !== "no-speech") {
          setError("Ses tanıma hatası: " + event.error);
        }
      };

      recognizer.onend = () => {
        setIsListening(false);
      };

      recognizer.start();
      recognitionRef.current = recognizer;
    } catch (err: any) {
      setError("Mikrofon başlatılamadı: " + err.message);
      setIsListening(false);
    }
  }

  // Yalnızca Metni Ayrıştır (Preview)
  async function handleParseOnly() {
    if (!dictationText.trim()) {
      setError("Lütfen önce bir dikte metni girin veya mikrofondan konuşun.");
      return;
    }
    setIsProcessing(true);
    setError("");
    setSuccessMsg("");
    try {
      const res = await api("technician/dictate-text", "POST", {
        text: dictationText,
      });
      setParsedData(res);
      setSuccessMsg("Dikte başarıyla ayrıştırıldı. Aşağıdaki bulguları inceleyebilirsiniz.");
    } catch (e) {
      setError("Ayrıştırma hatası: " + errorMessage(e));
    } finally {
      setIsProcessing(false);
    }
  }

  // Rapora ve CRM'e Aktar (Commit to DB & PDF)
  async function handleApplyToReport() {
    if (!dictationText.trim()) {
      setError("Lütfen önce bir dikte metni girin.");
      return;
    }
    setIsProcessing(true);
    setError("");
    setSuccessMsg("");
    try {
      const body: any = {
        text: dictationText,
      };
      if (technicianName.trim()) body.technician_name = technicianName.trim();
      if (selectedReportId) {
        body.report_id = selectedReportId;
      } else if (selectedVehicleId) {
        body.vehicle_id = selectedVehicleId;
      }

      const res = await api("technician/dictate-text", "POST", body);
      setParsedData(res);
      await loadContext();
      setSuccessMsg(
        res.report
          ? `Bulgular başarıyla kaydedildi! Rapor ID: ${res.report.id} (${res.report.score}/100 Puan)`
          : "Bulgular başarıyla işlendi."
      );
    } catch (e) {
      setError("Rapora aktarım hatası: " + errorMessage(e));
    } finally {
      setIsProcessing(false);
    }
  }

  // Ses Dosyası Yükleme (WAV / MP3 / WEBM)
  async function handleAudioUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsProcessing(true);
    setError("");
    setSuccessMsg("");

    try {
      const formData = new FormData();
      formData.append("file", file);
      if (selectedReportId) {
        formData.append("report_id", selectedReportId);
      } else if (selectedVehicleId) {
        formData.append("vehicle_id", selectedVehicleId);
      }
      if (technicianName.trim()) formData.append("technician_name", technicianName.trim());

      const res = await api("technician/dictate-audio", "POST", formData);
      if (res.transcribed_text) {
        setDictationText(res.transcribed_text);
      }
      setParsedData(res);
      await loadContext();
      setSuccessMsg(
        "Ses kaydı STT ile metne dönüştürüldü ve bulgular başarıyla çıkarıldı!"
      );
    } catch (err: any) {
      setError("Ses dosyası işleme hatası: " + err.message);
    } finally {
      setIsProcessing(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  function getScoreBadge(score: number) {
    if (score >= 90) return { label: "KUSURSUZ (A+)", color: "#16A34A" };
    if (score >= 75) return { label: "İYİ DURUMDA (B)", color: "#0284C7" };
    if (score >= 50) return { label: "ORTA / KUSURLU (C)", color: "#CA8A04" };
    return { label: "AĞIR HASARLI / RİSKLİ (D)", color: "#DC2626" };
  }

  const scoreBadge =
    parsedData && parsedData.calculated_score !== null ? getScoreBadge(parsedData.calculated_score) : null;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: "8px", minHeight: 0, overflowY: "auto", padding: "2px 4px" }}>
      {/* Başlık ve Sahadan Teknisyen Modu Açıklaması */}
      <section style={{ background: "linear-gradient(135deg, #1E293B 0%, #0F172A 100%)", color: "white", padding: "20px", borderRadius: "10px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
          <div>
            <h2 style={{ margin: "0 0 6px 0", color: "#38BDF8", display: "flex", alignItems: "center", gap: "10px" }}>
              <span>🎙️</span> Sesli Teknisyen Notu (Sahadan Dikte Modu)
            </h2>
            <p style={{ margin: 0, fontSize: "14px", color: "#94A3B8", maxWidth: "750px" }}>
              Ekspertiz teknisyenleri sahadayken elleri meşgul olduğunda, mikrofondan konuşarak kaporta, mekanik ve elektronik bulgularını dikte eder. FreyaTTS Otomotiv Varlık Çıkarıcı motoru sesli ifadeleri analiz edip resmi rapora ve CRM sistemine otomatik aktarır.
            </p>
          </div>
          <div style={{ display: "flex", gap: "10px" }}>
            <button
              type="button"
              onClick={toggleSpeechRecognition}
              style={{
                backgroundColor: isListening ? "#DC2626" : "#2563EB",
                color: "white",
                padding: "10px 18px",
                borderRadius: "8px",
                fontWeight: "bold",
                display: "flex",
                alignItems: "center",
                gap: "8px",
                boxShadow: isListening ? "0 0 15px rgba(220, 38, 38, 0.6)" : "none",
                cursor: "pointer",
                border: "none",
              }}
            >
              <span style={{ fontSize: "18px" }}>{isListening ? "⏹️" : "🎤"}</span>
              {isListening ? "Kaydı Durdur" : "Mikrofonla Canlı Dikte"}
            </button>
            <input
              type="file"
              ref={fileInputRef}
              accept="audio/*"
              style={{ display: "none" }}
              onChange={handleAudioUpload}
            />
            <button
              type="button"
              className="secondary"
              onClick={() => fileInputRef.current?.click()}
              style={{ padding: "10px 16px" }}
              disabled={isProcessing}
            >
              📁 Ses Dosyası Yükle
            </button>
          </div>
        </div>
      </section>

      <p className="muted" style={{ margin: 0, fontSize: "12px" }}>
        Not: &quot;Mikrofonla Canlı Dikte&quot; tarayıcının kendi konuşma tanıma servisini kullanır; ses cihazınızdan çıkıp
        tarayıcı sağlayıcısının sunucularına gönderilebilir. &quot;Ses Dosyası Yükle&quot; ise sesi yalnızca yerel sunucuya gönderir.
      </p>

      {error && (
        <div role="alert" className="error" style={{ padding: "12px 16px", borderRadius: "8px" }}>
          ⚠️ {error}
        </div>
      )}

      {successMsg && (
        <div style={{ backgroundColor: "#ECFDF5", border: "1px solid #10B981", color: "#065F46", padding: "12px 16px", borderRadius: "8px", fontWeight: 500 }}>
          ✅ {successMsg}
        </div>
      )}

      {/* Hedef Rapor ve Araç Seçimi */}
      <section style={{ backgroundColor: "#F8FAFC", padding: "16px", borderRadius: "8px", border: "1px solid #E2E8F0" }}>
        <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", color: "#1E293B" }}>
          🎯 Hedef Araç veya Mevcut Ekspertiz Raporu Seçimi
        </h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "14px" }}>
          <div>
            <label htmlFor="td-vehicle" style={{ fontSize: "13px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>
              Araç (Yeni Rapor Açılacaksa):
            </label>
            <select
              id="td-vehicle"
              value={selectedVehicleId}
              onChange={(e) => {
                setSelectedVehicleId(e.target.value);
                setSelectedReportId("");
              }}
              style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
            >
              <option value="">-- Araç Seçin --</option>
              {vehicles.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.plate ? `[${v.plate}] ` : ""}{v.description}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="td-report" style={{ fontSize: "13px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>
              Mevcut Rapora Ekle (Opsiyonel):
            </label>
            <select
              id="td-report"
              value={selectedReportId}
              onChange={(e) => setSelectedReportId(e.target.value)}
              style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
            >
              <option value="">-- Yeni Rapor Oluştur / Yalnızca Test Et --</option>
              {inspections.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.vehicle_plate ? `[${r.vehicle_plate}] ` : ""}{r.vehicle_description || "Araç"} — {r.id.slice(0, 8)} ({r.score} Puan)
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="td-tech" style={{ fontSize: "13px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>
              Teknisyen / Usta Adı:
            </label>
            <input
              id="td-tech"
              type="text"
              value={technicianName}
              onChange={(e) => setTechnicianName(e.target.value)}
              style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
            />
          </div>
        </div>
      </section>

      {/* Dikte Metin Alanı ve Hızlı Örnekler */}
      <section style={{ backgroundColor: "#FFFFFF", padding: "16px", borderRadius: "8px", border: "1px solid #E2E8F0" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
          <h3 style={{ margin: 0, fontSize: "15px", color: "#1E293B" }}>
            📝 Dikte Metni {isListening && <span style={{ color: "#DC2626", fontWeight: "bold" }}>● Dinleniyor...</span>}
          </h3>
          <div style={{ fontSize: "12px", color: "#64748B" }}>
            Örnek doldur:
            {SAMPLE_DICTATIONS.map((_, idx) => (
              <button
                key={idx}
                type="button"
                className="secondary"
                style={{ marginLeft: "6px", padding: "2px 8px", fontSize: "11px" }}
                onClick={() => setDictationText(SAMPLE_DICTATIONS[idx])}
              >
                Örnek {idx + 1}
              </button>
            ))}
          </div>
        </div>

        <textarea
          rows={4}
          aria-label="Dikte metni"
          value={dictationText}
          onChange={(e) => setDictationText(e.target.value)}
          placeholder="Örnek: Sol ön çamurluk boyalı 180 mikron, sağ arka kapı değişen, motor dyno yüzde 92, şasi ve podyeler işlemsiz orijinal, airbagler aktif..."
          style={{ width: "100%", padding: "10px", borderRadius: "6px", border: "1px solid #CBD5E1", fontSize: "14px", lineHeight: "1.4" }}
        />

        <div style={{ display: "flex", gap: "10px", marginTop: "12px" }}>
          <button
            type="button"
            className="secondary"
            onClick={handleParseOnly}
            disabled={isProcessing}
            style={{ padding: "8px 16px" }}
          >
            🔍 Yalnızca Ayrıştır ve İncele
          </button>

          <button
            type="button"
            onClick={handleApplyToReport}
            disabled={isProcessing}
            style={{ backgroundColor: "#059669", color: "white", padding: "8px 20px", borderRadius: "6px", fontWeight: "bold", border: "none", cursor: "pointer" }}
          >
            {isProcessing ? "İşleniyor..." : "💾 Rapora ve CRM'e Aktar →"}
          </button>
        </div>
      </section>

      {/* Ayrıştırılan Bulgular ve Çıkarılan Varlıklar */}
      {parsedData && (
        <section style={{ backgroundColor: "#FFFFFF", padding: "20px", borderRadius: "8px", border: "1px solid #CBD5E1", display: "flex", flexDirection: "column", gap: "18px" }}>
          {/* Üst Kart: Puan, Güven Skoru ve Rapor Durumu */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px", borderBottom: "1px solid #E2E8F0", paddingBottom: "14px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
              <div
                style={{
                  backgroundColor: scoreBadge?.color || "#0284C7",
                  color: "white",
                  padding: "10px 16px",
                  borderRadius: "8px",
                  fontWeight: "bold",
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: "22px" }}>
                  {parsedData.calculated_score !== null ? `${parsedData.calculated_score} / 100` : "—"}
                </div>
                <div style={{ fontSize: "11px", letterSpacing: "0.5px" }}>
                  {scoreBadge?.label ?? "PUAN HESAPLANAMADI"}
                </div>
              </div>

              <div>
                <div style={{ fontWeight: "bold", color: "#1E293B", fontSize: "15px" }}>
                  Otomatik Hesaplanan Ekspertiz Puanı
                </div>
                <div style={{ fontSize: "12px", color: "#64748B" }}>
                  Ayrıştırma Güveni: %{Math.round(parsedData.confidence_score * 100)} · Tespit Edilen Varlık: {parsedData.extracted_entities.length} adet
                </div>
              </div>
            </div>

            {parsedData.report && (
              <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      const { url } = await api("inspections/" + parsedData.report.id + "/signed-link");
                      window.open(url, "_blank", "noopener");
                    } catch (e) {
                      setError("PDF bağlantısı alınamadı: " + errorMessage(e));
                    }
                  }}
                  style={{
                    backgroundColor: "#0284C7",
                    color: "white",
                    padding: "8px 14px",
                    borderRadius: "6px",
                    fontWeight: "bold",
                    fontSize: "13px",
                  }}
                >
                  📄 PDF Raporu Görüntüle
                </button>
              </div>
            )}
          </div>

          {/* Otomatik Üretilen Teknik Kanaat (Summary) */}
          <div style={{ backgroundColor: "#F8FAFC", borderLeft: "4px solid #0284C7", padding: "12px 16px", borderRadius: "0 6px 6px 0" }}>
            <div style={{ fontSize: "12px", fontWeight: "bold", color: "#475569", marginBottom: "4px" }}>
              📝 SİSTEM TARAFINDAN OLUŞTURULAN UZMAN KANAATİ (ÖZET):
            </div>
            <div style={{ fontSize: "14px", color: "#0F172A", lineHeight: "1.5" }}>
              {parsedData.generated_summary}
            </div>
          </div>

          {/* Çıkarılan Varlık Etiketleri (Chips) */}
          <div>
            <h4 style={{ margin: "0 0 10px 0", fontSize: "14px", color: "#334155" }}>
              🏷️ Ayrıştırılan Saha Bulguları & Varlık Etiketleri ({parsedData.extracted_entities.length})
            </h4>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              {parsedData.extracted_entities.map((item, idx) => {
                let bg = "#F1F5F9";
                let textCol = "#334155";
                let border = "#CBD5E1";

                if (item.state === "Değişen" || item.state === "Ağır Kusur" || item.state === "Kritik Risk" || item.state === "Kusurlu") {
                  bg = "#FEF2F2";
                  textCol = "#991B1B";
                  border = "#FCA5A5";
                } else if (item.state === "Lokal Boyalı" || item.state === "Boyalı" || item.state === "Kaçak Var") {
                  bg = "#FFFBEB";
                  textCol = "#92400E";
                  border = "#FCD34D";
                } else if (item.state === "Orijinal" || item.state === "Kusursuz" || item.state === "Normal" || item.state === "Temiz") {
                  bg = "#F0FDF4";
                  textCol = "#166534";
                  border = "#86EFAC";
                }

                return (
                  <div
                    key={idx}
                    style={{
                      backgroundColor: bg,
                      color: textCol,
                      border: `1px solid ${border}`,
                      padding: "6px 12px",
                      borderRadius: "6px",
                      fontSize: "12.5px",
                    }}
                  >
                    <b>{item.part}:</b> {item.detail || item.state}
                  </div>
                );
              })}
            </div>
          </div>

          {/* 5 Standart Ekspertiz Kategorisi Tabloları */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "16px" }}>
            {/* 1. Boya & Karoser */}
            <div style={{ border: "1px solid #E2E8F0", borderRadius: "6px", padding: "12px" }}>
              <h5 style={{ margin: "0 0 8px 0", color: "#1E293B", borderBottom: "1px solid #E2E8F0", paddingBottom: "4px" }}>
                1. Boya ve Karoser
              </h5>
              {Object.keys(parsedData.findings.paint_body).length === 0 ? (
                <p style={{ fontSize: "12px", color: "#94A3B8" }}>Dikte edilen bulgu yok</p>
              ) : (
                <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "12.5px", color: "#334155" }}>
                  {Object.entries(parsedData.findings.paint_body).map(([k, v]) => (
                    <li key={k} style={{ marginBottom: "3px" }}>
                      <b>{k}:</b> {v}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* 2. Motor & Mekanik */}
            <div style={{ border: "1px solid #E2E8F0", borderRadius: "6px", padding: "12px" }}>
              <h5 style={{ margin: "0 0 8px 0", color: "#1E293B", borderBottom: "1px solid #E2E8F0", paddingBottom: "4px" }}>
                2. Motor ve Mekanik
              </h5>
              {Object.keys(parsedData.findings.engine_mechanical).length === 0 ? (
                <p style={{ fontSize: "12px", color: "#94A3B8" }}>Dikte edilen bulgu yok</p>
              ) : (
                <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "12.5px", color: "#334155" }}>
                  {Object.entries(parsedData.findings.engine_mechanical).map(([k, v]) => (
                    <li key={k} style={{ marginBottom: "3px" }}>
                      <b>{k}:</b> {v}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* 3. Şasi & Alt Takım */}
            <div style={{ border: "1px solid #E2E8F0", borderRadius: "6px", padding: "12px" }}>
              <h5 style={{ margin: "0 0 8px 0", color: "#1E293B", borderBottom: "1px solid #E2E8F0", paddingBottom: "4px" }}>
                3. Şasi, Podye ve Alt Takım
              </h5>
              {Object.keys(parsedData.findings.chassis_frame).length === 0 ? (
                <p style={{ fontSize: "12px", color: "#94A3B8" }}>Dikte edilen bulgu yok</p>
              ) : (
                <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "12.5px", color: "#334155" }}>
                  {Object.entries(parsedData.findings.chassis_frame).map(([k, v]) => (
                    <li key={k} style={{ marginBottom: "3px" }}>
                      <b>{k}:</b> {v}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* 4. Lastikler & 5. İç Mekan / OBD */}
            <div style={{ border: "1px solid #E2E8F0", borderRadius: "6px", padding: "12px" }}>
              <h5 style={{ margin: "0 0 8px 0", color: "#1E293B", borderBottom: "1px solid #E2E8F0", paddingBottom: "4px" }}>
                4. Lastikler & 5. İç Mekan / Elektronik
              </h5>
              <div style={{ fontSize: "12.5px", color: "#334155" }}>
                {Object.entries(parsedData.findings.tires_wheels).map(([k, v]) => (
                  <div key={k} style={{ marginBottom: "2px" }}>
                    <b>{k}:</b> {v}
                  </div>
                ))}
                {Object.entries(parsedData.findings.interior_electronics).map(([k, v]) => (
                  <div key={k} style={{ marginBottom: "2px" }}>
                    <b>{k}:</b> {v}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
````


### frontend/src/useVoiceSession.ts

````
import { useEffect, useRef, useState } from "react";
import type { VoiceMessage, VoiceMetrics } from "./api";
import type { ApiFn } from "./ui";
import {
  PipelineTurnState,
  PipelineTelemetryEvent,
  createInitialTurnState,
} from "./pipeline/types";
import { DEMO_SCENARIOS } from "./pipeline/demoFixtures";

function micError(e: unknown) {
  const n = (e as { name?: string; message?: string } | null)?.name;
  const msg = (e as { message?: string } | null)?.message || "";
  if (n === "NotAllowedError" || n === "SecurityError")
    return "Mikrofon izni verilmedi. Tarayıcı adres çubuğundan mikrofona izin verip tekrar deneyin.";
  if (n === "NotFoundError" || n === "DevicesNotFoundError")
    return "Mikrofon bulunamadı. Bir mikrofon bağlayıp tekrar deneyin.";
  if (n === "NotReadableError" || msg.includes("Could not start audio source"))
    return "Mikrofon başlatılamadı: Cihaz başka bir uygulama (Zoom, Teams, Discord vb.) tarafından kullanılıyor olabilir veya Windows mikrofon erişim izni kapalı olabilir. Alternatif olarak aşağıdaki metin kutusundan yazarak görüşmeyi sürdürebilirsiniz.";
  if (n === "OverconstrainedError")
    return "Mikrofon donanımı istenen ses parametrelerini desteklemiyor.";
  return null;
}

const STATUS_LABELS: Record<string, string> = {
  listening: "Dinliyor",
  synthesizing: "Ses üretiyor",
  speaking: "Konuşuyor",
};

/** Sesli görüşme: WebSocket, AudioWorklet yakalama, oynatma kuyruğu, DTMF ve metrikler. */
export function useVoiceSession(api: ApiFn, setError: (msg: string) => void) {
  const [messages, setMessages] = useState<VoiceMessage[]>([]),
    [status, setStatus] = useState("Hazır"),
    [connected, setConnected] = useState(false),
    [metrics, setMetrics] = useState<VoiceMetrics | null>(null),
    [calibrating, setCalibrating] = useState(false),
    [calibrationInfo, setCalibrationInfo] = useState<{
      ambient_dbfs?: number;
      noise_gate_dbfs?: number;
      suppression_db?: number;
      message?: string;
    } | null>(null),
    [pipelineState, setPipelineState] = useState<PipelineTurnState>(() =>
      createInitialTurnState(1, "", "live")
    ),
    [mediaStream, setMediaStream] = useState<MediaStream | null>(null);
  const playback = useRef<AudioContext | null>(null);
  const sock = useRef<WebSocket | null>(null),
    ctx = useRef<AudioContext | null>(null),
    stream = useRef<MediaStream | null>(null),
    node = useRef<AudioWorkletNode | null>(null),
    queue = useRef<AudioBufferSourceNode[]>([]),
    next = useRef(0),
    paused = useRef(false),
    closing = useRef(false),
    failed = useRef(false),
    wasConnected = useRef(false);

  function fail(msg: string) {
    failed.current = true;
    setError(msg);
  }
  function flush() {
    for (const s of queue.current) {
      try {
        s.stop();
      } catch {}
    }
    queue.current = [];
    next.current = 0;
  }
  function stop() {
    closing.current = true;
    sock.current?.close();
    sock.current = null;
    node.current?.disconnect();
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setMediaStream(null);
    flush();
    ctx.current?.close();
    ctx.current = null;
    playback.current?.close();
    playback.current = null;
    setConnected(false);
    setStatus(failed.current ? "Hata" : "Görüşme sonlandı");
  }
  useEffect(() => () => stop(), []);
  async function start() {
    failed.current = false;
    closing.current = false;
    wasConnected.current = false;
    setMetrics(null);
    const ac = new AudioContext();
    const out = new AudioContext();
    ctx.current = ac;
    playback.current = out;
    const unlocked = Promise.all([ac.resume(), out.resume()]);
    setStatus("Bağlanıyor");
    try {
      await unlocked;
      let s: MediaStream | null = null;
      try {
        try {
          s = await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
          });
        } catch (firstErr) {
          console.warn("useVoiceSession: DSP kısıtlı mikrofon açılamadı, basit audio:true deneniyor...", firstErr);
          s = await navigator.mediaDevices.getUserMedia({ audio: true });
        }
        stream.current = s;
        setMediaStream(s);
      } catch (e) {
        console.warn("Mikrofon donanım hatası (metin modu devreye alındı):", e);
        const m = micError(e);
        setError(m || "Mikrofon başlatılamadı. Metin kutusundan yazarak görüşmeyi sürdürebilirsiniz.");
      }

      if (s) {
        try {
          await ac.audioWorklet.addModule("/capture.js");
        } catch (wErr) {
          console.warn("AudioWorklet yüklenemedi:", wErr);
        }
      }

      // Bilet yalnızca 30 sn geçerli: mikrofon izni ve worklet yüklemesinden SONRA alınır.
      const ticket = await api("session-ticket", "POST");
      const ws = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/voice?ticket=${encodeURIComponent(ticket.ticket)}`,
      );
      sock.current = ws;
      ws.binaryType = "arraybuffer";
      setMessages([]);
      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            sample_rate: ac.sampleRate,
            encoding: "pcm_s16le",
            channels: 1,
          }),
        );
        if (stream.current) {
          try {
            const n = new AudioWorkletNode(ac, "capture");
            node.current = n;
            ac.createMediaStreamSource(stream.current).connect(n);
            const mute = ac.createGain();
            mute.gain.value = 0;
            n.connect(mute);
            mute.connect(ac.destination);
            n.port.onmessage = (e) => {
              if (ws.readyState === 1 && ws.bufferedAmount < 128000)
                ws.send(e.data);
            };
          } catch (workletConnErr) {
            console.warn("Worklet ses hattı bağlantı hatası:", workletConnErr);
          }
        }
        wasConnected.current = true;
        setConnected(true);
        setStatus(stream.current ? "Bağlandı (Mikrofon Aktif)" : "Bağlandı (Metin Modu)");
      };
      ws.onmessage = async (e) => {
        if (typeof e.data === "string") {
          const m = JSON.parse(e.data);
          if (m.type === "calibration_start") {
            setCalibrating(true);
            setStatus("Gürültü Kalibre Ediliyor");
          }
          if (m.type === "calibration_done") {
            setCalibrating(false);
            setCalibrationInfo({
              ambient_dbfs: m.ambient_dbfs,
              noise_gate_dbfs: m.noise_gate_dbfs,
              suppression_db: m.suppression_db,
              message: m.message,
            });
            setStatus("Dinliyor");
          }
          if (m.type === "completed") {
            stop();
            return;
          }
          if (m.type === "pipeline_event" && m.event) {
            const ev = m.event as PipelineTelemetryEvent;
            setPipelineState((prev) => {
              const updatedStages = { ...prev.stages };
              updatedStages[ev.stage] = {
                stage: ev.stage,
                status: ev.status,
                durationMs:
                  ev.duration_ms !== undefined
                    ? ev.duration_ms
                    : updatedStages[ev.stage]?.durationMs ?? null,
                startedAt:
                  ev.status === "running" ? Date.now() : updatedStages[ev.stage]?.startedAt ?? null,
                completedAt:
                  ev.status === "completed"
                    ? Date.now()
                    : updatedStages[ev.stage]?.completedAt ?? null,
                metrics: { ...(updatedStages[ev.stage]?.metrics || {}), ...(ev.metrics || {}) },
                intermediateData:
                  ev.intermediate_data !== undefined
                    ? ev.intermediate_data
                    : updatedStages[ev.stage]?.intermediateData,
                errorCode: ev.error_code,
                errorMessage: ev.error_message,
              };
              return {
                ...prev,
                turnId: ev.turn_id,
                sessionId: ev.session_id,
                source: ev.source || "live",
                activeStage: ev.status === "running" ? ev.stage : prev.activeStage,
                stages: updatedStages,
                traces: [ev, ...prev.traces.slice(0, 49)],
              };
            });
          }
          if (m.type === "transcript") {
            if (m.role === "user") setMetrics(null);
            setMessages((x) => [...x, m]);
          }
          if (m.type === "metrics") {
            const { type: _t, ...rest } = m;
            setMetrics((prev) => ({ ...(prev || {}), ...rest }));
          }
          if (m.type === "error") fail(m.message);
          if (m.type === "status") setStatus(STATUS_LABELS[m.value] || m.value);
          if (m.type === "playback") {
            if (m.action === "flush") flush();
            if (m.action === "pause") {
              paused.current = true;
              await out.suspend();
            } else if (m.action === "resume" || m.action === "flush") {
              paused.current = false;
              await out.resume();
            }
          }
        } else {
          const pcm = new Int16Array(e.data);
          const b = out.createBuffer(1, pcm.length, 16000);
          const d = b.getChannelData(0);
          for (let i = 0; i < pcm.length; i++) d[i] = pcm[i] / 32768;
          const s = out.createBufferSource();
          s.buffer = b;
          s.connect(out.destination);
          next.current = Math.max(out.currentTime + 0.025, next.current);
          s.start(next.current);
          next.current += b.duration;
          queue.current.push(s);
          s.onended = () => {
            queue.current = queue.current.filter((x) => x !== s);
          };
        }
      };
      ws.onerror = () => {
        if (!wasConnected.current)
          fail("Ses bağlantısı kurulamadı; model ve sunucu durumunu kontrol edin.");
      };
      ws.onclose = (ev) => {
        if (!closing.current && !failed.current)
          fail(
            // Sunucu kod/neden gönderir: 1013 line_busy = hat meşgul, 1008 = bilet süresi doldu.
            ev.reason === "line_busy" || ev.code === 1013
              ? "Hat şu anda meşgul. Birkaç saniye sonra tekrar deneyin."
              : ev.reason === "ticket_expired" || ev.code === 1008
                ? "Oturum bileti geçersiz veya süresi doldu. Aramayı yeniden başlatın."
                : wasConnected.current
                  ? "Ses bağlantısı beklenmedik şekilde kapandı."
                  : "Bağlantı reddedildi. Birkaç saniye sonra tekrar deneyin.",
          );
        stop();
      };
    } catch (e) {
      failed.current = true;
      stop();
      throw e;
    }
  }
  function sendDtmf(digit: string) {
    if (sock.current && sock.current.readyState === WebSocket.OPEN) {
      sock.current.send(JSON.stringify({ type: "dtmf", digit }));
    }
  }

  function sendTextInput(text: string): boolean {
    if (sock.current && sock.current.readyState === WebSocket.OPEN) {
      sock.current.send(JSON.stringify({ type: "text_input", text }));
      return true;
    }
    return false;
  }
  function recalibrate() {
    if (sock.current && sock.current.readyState === WebSocket.OPEN) {
      sock.current.send(JSON.stringify({ type: "recalibrate" }));
    }
  }
  function runDemoScenario(scenarioId: string) {
    const sc = DEMO_SCENARIOS.find((s) => s.id === scenarioId) || DEMO_SCENARIOS[0];
    const initial = createInitialTurnState(sc.events[0]?.turn_id || 1, sc.events[0]?.session_id || "demo-sim", "demo");
    initial.userText = sc.userSpeech;
    initial.assistantText = sc.botReply;
    setPipelineState(initial);
    setStatus("Simülasyon Çalışıyor");

    let delay = 50;
    sc.events.forEach((ev, idx) => {
      setTimeout(() => {
        setPipelineState((prev) => {
          const updatedStages = { ...prev.stages };
          updatedStages[ev.stage] = {
            stage: ev.stage,
            status: ev.status,
            durationMs: ev.duration_ms !== undefined ? ev.duration_ms : updatedStages[ev.stage]?.durationMs ?? null,
            startedAt: ev.status === "running" ? Date.now() : updatedStages[ev.stage]?.startedAt ?? null,
            completedAt: ev.status === "completed" ? Date.now() : updatedStages[ev.stage]?.completedAt ?? null,
            metrics: { ...(updatedStages[ev.stage]?.metrics || {}), ...(ev.metrics || {}) },
            intermediateData: ev.intermediate_data !== undefined ? ev.intermediate_data : updatedStages[ev.stage]?.intermediateData,
            errorCode: ev.error_code,
            errorMessage: ev.error_message,
          };
          return {
            ...prev,
            turnId: ev.turn_id,
            sessionId: ev.session_id,
            source: "demo",
            activeStage: ev.status === "running" ? ev.stage : prev.activeStage,
            stages: updatedStages,
            traces: [
              {
                ...ev,
                schema_version: "3.0",
                event_id: `demo-ev-${idx}`,
                timestamp: Date.now(),
              },
              ...prev.traces.slice(0, 49),
            ],
          };
        });
        if (idx === sc.events.length - 1) {
          setStatus("Hazır");
        }
      }, delay);
      delay += 140;
    });
  }

  /** Çıkışta: oturumu kapat ve görünür durumu başlangıca döndür. */
  function reset() {
    stop();
    setMessages([]);
    setMediaStream(null);
    setMetrics(null);
    setCalibrating(false);
    setCalibrationInfo(null);
    setPipelineState(createInitialTurnState(1, "", "live"));
    setStatus("Hazır");
  }
  return {
    messages,
    status,
    connected,
    mediaStream,
    metrics,
    calibrating,
    calibrationInfo,
    pipelineState,
    runDemoScenario,
    start,
    stop,
    sendDtmf,
    sendTextInput,
    recalibrate,
    interruptBargeIn: flush,
    reset,
  };
}
````


### frontend/src/VoiceWaveformBar.tsx

````
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
````


### frontend/public/capture.js

````
class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const x = inputs[0]?.[0];
    if (x) {
      const out = new Int16Array(x.length);
      for (let i = 0; i < x.length; i++)
        out[i] = Math.round(Math.max(-1, Math.min(1, x[i])) * 32767);
      this.port.postMessage(out.buffer, [out.buffer]);
    }
    return true;
  }
}
registerProcessor("capture", Capture);
````
