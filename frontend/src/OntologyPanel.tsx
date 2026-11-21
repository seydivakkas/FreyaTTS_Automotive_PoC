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

