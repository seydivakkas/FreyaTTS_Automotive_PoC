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
