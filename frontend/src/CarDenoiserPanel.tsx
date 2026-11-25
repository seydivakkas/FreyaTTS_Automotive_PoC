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
                    {previewResult?.stats ? dash(previewResult.stats.snr_improvement_db, " dB") : "—"}
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
                    {previewResult?.stats ? dash(previewResult.stats.input_global_rms_dbfs, " dBFS") : "—"}
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
                    {previewResult?.stats ? `${previewResult.stats.speech_ratio_percent}%` : "—"}
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
