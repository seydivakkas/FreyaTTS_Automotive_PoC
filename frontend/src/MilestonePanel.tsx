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
    <div className="milestone-cockpit-layout" style={{ display: "flex", flexDirection: "column", gap: "20px", minWidth: 0, minHeight: 0, flex: 1, overflowY: "auto", overflowX: "hidden", overflowWrap: "anywhere" }}>
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
              Emniyet kuralları yerel önizlemesi (SİMÜLASYON). {activeLocksCount}/11 seçili; bu seçimler sunucu politikasını değiştirmez.
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
            Toplam gecikme: — (ölçüm yok)
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
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 360px), 1fr))",
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
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", justifyContent: "space-between", gap: "10px" }}>
              <div>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px" }}>
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
                {lock.active ? "ÖNİZLEME AÇIK" : "ÖNİZLEME KAPALI"}
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
                <strong style={{ color: "#94a3b8" }}>
                  —
                </strong>
              </span>
              <span>Ek gecikme: — (ölçüm yok)</span>
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

        <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", minWidth: 0 }}>
          <textarea
            rows={2}
            aria-label="Sözleşme metni"
            value={text}
            onChange={(e) => setText(e.target.value)}
            style={{
              flex: "1 1 180px",
              minWidth: 0,
              maxWidth: "100%",
              boxSizing: "border-box",
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
              padding: "10px 16px",
              flex: "0 1 auto",
              maxWidth: "100%",
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
                {result.plan?.status ?? "Doğrulama durumu yok"}
              </span>
            </div>
            <p data-testid="contract-normalized-text" style={{ margin: 0, color: "#a7f3d0", fontWeight: "bold" }}>
              {result.normalization?.spoken_text ?? "Normalizasyon sonucu yok"}
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
                    <strong>[Cümlecik #{c.index || idx + 1}]</strong> {c.text} ({c.pause_after_ms == null ? "—" : `${c.pause_after_ms} ms`})
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
