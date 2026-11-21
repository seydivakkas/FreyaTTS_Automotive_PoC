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
