/*
 * ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
 * Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlıdır.
 */

import { useState, useEffect } from "react";
import { RawApiFn, dash, errorMessage } from "./ui";

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

import type { Props } from "./api";

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
      // 8 kHz simülasyonu için istemci tarafında gürültülü araç sesi sentezle (120 Hz motor uğultusu + yol gürültüsü + konuşma tonu)
      const fs = 8000;
      const duration = 1.6;
      const n = Math.floor(fs * duration);
      const audioBuffer = new Float32Array(n);

      for (let i = 0; i < n; i++) {
        const t = i / fs;
        // 60 Hz motor devir titreşimi + 90 Hz egzoz
        const rumble = 0.35 * Math.sin(2 * Math.PI * 60 * t) + 0.18 * Math.sin(2 * Math.PI * 90 * t);
        // Kabin rüzgar / yol tıslaması
        const road = (Math.random() * 2 - 1) * 0.08;
        // 0.5s - 1.2s arasında sürücü sesi (kısık)
        let speech = 0;
        if (t >= 0.5 && t <= 1.2) {
          speech = 0.06 * Math.sin(2 * Math.PI * 450 * t) + 0.04 * Math.sin(2 * Math.PI * 900 * t);
        }
        audioBuffer[i] = rumble + road + speech;
      }

      // WAV formatına çevir
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
        `Ses ${config.hpf_cutoff} Hz HPF + -${config.suppression_db} dB spektral gürültü bastırma + ${config.target_dbfs} dBFS hedefli AGC ile işlendi.`,
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
    <>
      <div className="stats">
        <article>
          <small>DSP Motoru Durumu</small>
          <strong style={{ color: config.enabled ? "#a7f3ce" : "#fca5a5" }}>
            {config.enabled ? "● Aktif (8 kHz SLIN16)" : "○ Devre Dışı"}
          </strong>
        </article>
        <article>
          <small>Motor Uğultusu Kesici</small>
          <strong style={{ color: "#38bdf8" }}>{config.hpf_cutoff} Hz HPF</strong>
          <span style={{ fontSize: "11px", color: "#94a3b8" }}>4. Derece Butterworth (24 dB/oct)</span>
        </article>
        <article>
          <small>Kabin Gürültü Bastırma</small>
          <strong style={{ color: "#c084fc" }}>-{config.suppression_db} dB Taban</strong>
          <span style={{ fontSize: "11px", color: "#94a3b8" }}>Sine Penceresi & Spektral Çıkarma</span>
        </article>
        <article>
          <small>Bluetooth Soft AGC</small>
          <strong style={{ color: "#fde047" }}>{config.target_dbfs} dBFS</strong>
          <span style={{ fontSize: "11px", color: "#94a3b8" }}>Kapı: {config.noise_gate_dbfs} dBFS · Max: +{config.max_boost_db} dB</span>
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

      {/* Ana Grid: Ayarlar ve Canlı Test Laboratuvarı */}
      <div className="grid-2" style={{ gap: "20px", marginTop: "24px" }}>
        {/* Sol Kolon: DSP Parametreleri */}
        <section style={{ margin: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
            <h3 style={{ margin: 0, fontSize: "16px" }}>⚙️ Akustik Filtre ve Kazanç Ayarları</h3>
            <label style={{ display: "flex", alignItems: "center", gap: "8px", margin: 0, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={config.enabled}
                onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
              />
              <span style={{ fontSize: "13px", fontWeight: 600 }}>DSP Devrede</span>
            </label>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
            <label style={{ fontSize: "12px", color: "#cbd5e1" }}>
              1. Motor & Yol Uğultusu Kesici (High-Pass Cutoff): <b>{config.hpf_cutoff} Hz</b>
              <p className="muted" style={{ margin: "2px 0 6px", fontSize: "11px" }}>
                120 Hz altındaki egzoz ve lastik titreşimlerini keserek Silero VAD'ın sahte barge-in tetiklemesini önler.
              </p>
              <input
                type="range"
                min="40"
                max="250"
                step="5"
                value={config.hpf_cutoff}
                onChange={(e) => setConfig({ ...config, hpf_cutoff: Number(e.target.value) })}
                style={{ width: "100%" }}
              />
            </label>

            <label style={{ fontSize: "12px", color: "#cbd5e1" }}>
              2. Spektral Gürültü Bastırma Tabanı: <b>-{config.suppression_db} dB</b>
              <p className="muted" style={{ margin: "2px 0 6px", fontSize: "11px" }}>
                Kabin fanı ve asfalt sürtünmesini müzikal ses bozulması (chattering) yaratmadan bastırır.
              </p>
              <input
                type="range"
                min="6"
                max="30"
                step="1"
                value={config.suppression_db}
                onChange={(e) => setConfig({ ...config, suppression_db: Number(e.target.value) })}
                style={{ width: "100%" }}
              />
            </label>

            <label style={{ fontSize: "12px", color: "#cbd5e1" }}>
              3. Bluetooth Soft AGC Hedef Konuşma Seviyesi: <b>{config.target_dbfs} dBFS</b>
              <p className="muted" style={{ margin: "2px 0 6px", fontSize: "11px" }}>
                Sürücünün handsfree mikrofondan gelen kısık sesini ideal telefon anlaşılırlığına çıkarır.
              </p>
              <input
                type="range"
                min="-30"
                max="-10"
                step="1"
                value={config.target_dbfs}
                onChange={(e) => setConfig({ ...config, target_dbfs: Number(e.target.value) })}
                style={{ width: "100%" }}
              />
            </label>

            <label style={{ fontSize: "12px", color: "#cbd5e1" }}>
              4. Gürültü Kapısı Eşiği (Noise Gate): <b>{config.noise_gate_dbfs} dBFS</b>
              <p className="muted" style={{ margin: "2px 0 6px", fontSize: "11px" }}>
                Bu seviyenin altındaki sesler konuşma sayılmaz ve yol gürültüsünün yükseltilmesi engellenir.
              </p>
              <input
                type="range"
                min="-60"
                max="-25"
                step="1"
                value={config.noise_gate_dbfs}
                onChange={(e) => setConfig({ ...config, noise_gate_dbfs: Number(e.target.value) })}
                style={{ width: "100%" }}
              />
            </label>

            <label style={{ fontSize: "12px", color: "#cbd5e1" }}>
              5. Maksimum AGC Kazanç Limiti: <b>+{config.max_boost_db} dB</b>
              <p className="muted" style={{ margin: "2px 0 6px", fontSize: "11px" }}>
                Kısık sesler için izin verilen azami yükseltme çarpanı.
              </p>
              <input
                type="range"
                min="0"
                max="20"
                step="1"
                value={config.max_boost_db}
                onChange={(e) => setConfig({ ...config, max_boost_db: Number(e.target.value) })}
                style={{ width: "100%" }}
              />
            </label>
          </div>

          <div style={{ marginTop: "18px", display: "flex", gap: "10px" }}>
            <button type="button" onClick={handleSaveConfig} disabled={saving || loading}>
              {saving ? "Kaydediliyor..." : "Ayarları Uygula & Kaydet ✓"}
            </button>
            <button type="button" className="secondary" onClick={loadConfig} disabled={loading}>
              Sıfırla ↻
            </button>
          </div>
        </section>

        {/* Sağ Kolon: Akustik Simülatör ve Önizleme */}
        <section style={{ margin: 0 }}>
          <div style={{ marginBottom: "16px" }}>
            <h3 style={{ margin: 0, fontSize: "16px", color: "#38bdf8" }}>
              🎙️ Akustik Simülatör & Önizleme Laboratuvarı
            </h3>
            <p className="muted" style={{ margin: "4px 0 0", fontSize: "12px" }}>
              Seyir halindeki araç içi gürültülerini simüle edebilir veya gerçek bir telefon kaydı yükleyerek
              filtre öncesi ve sonrası akustik berraklığı test edebilirsiniz.
            </p>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <div
              style={{
                background: "#0c121e",
                padding: "14px",
                borderRadius: "10px",
                border: "1px dashed #334155",
              }}
            >
              <div style={{ fontSize: "13px", fontWeight: 600, marginBottom: "6px" }}>
                1. Seçenek: Simülasyon — Sentetik Seyir Halinde Araç Sesi
              </div>
              <p className="muted" style={{ fontSize: "12px", margin: "0 0 10px" }}>
                60 Hz/90 Hz motor devri titreşimi + asfalt yol tıslaması ve araya giren kısık sürücü konuşması oluşturur.
              </p>
              <button
                type="button"
                className="secondary"
                onClick={handleGenerateSynthAndTest}
                disabled={processingPreview}
                style={{ fontSize: "12px" }}
              >
                {processingPreview ? "İşleniyor..." : "🏎️ Simülasyon: Sentetik Araç Uğultusu Üret ve Temizle ➔"}
              </button>
            </div>

            <div
              style={{
                background: "#0c121e",
                padding: "14px",
                borderRadius: "10px",
                border: "1px dashed #334155",
              }}
            >
              <div style={{ fontSize: "13px", fontWeight: 600, marginBottom: "6px" }}>
                2. Seçenek: Gerçek Ses Dosyası Yükleme
              </div>
              <input
                type="file"
                accept="audio/*,.wav,.mp3"
                onChange={handleFileUpload}
                style={{ fontSize: "12px" }}
              />
            </div>

            {/* Önizleme ve Sonuç Kartı */}
            {previewResult && previewResult.stats && (
              <div
                style={{
                  background: "#111827",
                  border: "1px solid #1f2937",
                  borderRadius: "10px",
                  padding: "16px",
                  marginTop: "8px",
                }}
              >
                <h4 style={{ margin: "0 0 10px", fontSize: "14px", color: "#86efac" }}>
                  ✅ Temizlenmiş Ses & Akustik Rapor
                </h4>

                {previewResult.audio_base64 && (
                  <audio
                    controls
                    src={`data:audio/wav;base64,${previewResult.audio_base64}`}
                    style={{ width: "100%", height: "36px", marginBottom: "12px" }}
                  />
                )}

                <div className="grid-2" style={{ gap: "8px", fontSize: "12px" }}>
                  <div style={{ background: "#1f2937", padding: "8px", borderRadius: "6px" }}>
                    <span style={{ color: "#94a3b8" }}>Giriş Global RMS:</span>
                    <strong style={{ display: "block", color: "#fca5a5" }}>
                      {dash(previewResult.stats.input_global_rms_dbfs, " dBFS")}
                    </strong>
                  </div>
                  <div style={{ background: "#1f2937", padding: "8px", borderRadius: "6px" }}>
                    <span style={{ color: "#94a3b8" }}>Çıkış Seviyesi (AGC):</span>
                    <strong style={{ display: "block", color: "#86efac" }}>
                      {dash(previewResult.stats.output_global_rms_dbfs, " dBFS")}
                    </strong>
                  </div>
                  <div style={{ background: "#1f2937", padding: "8px", borderRadius: "6px" }}>
                    <span style={{ color: "#94a3b8" }}>Ort. Gürültü Bastırma:</span>
                    <strong style={{ display: "block", color: "#38bdf8" }}>
                      {dash(previewResult.stats.avg_noise_suppression_db, " dB")}
                    </strong>
                  </div>
                  <div style={{ background: "#1f2937", padding: "8px", borderRadius: "6px" }}>
                    <span style={{ color: "#94a3b8" }}>SNR İyileşmesi:</span>
                    <strong style={{ display: "block", color: "#c084fc" }}>
                      {dash(previewResult.stats.snr_improvement_db, " dB")}
                    </strong>
                  </div>
                </div>

                <div
                  style={{
                    marginTop: "10px",
                    padding: "8px",
                    background: "#14532d",
                    borderRadius: "6px",
                    fontSize: "11px",
                    color: "#bbf7d0",
                  }}
                >
                  🛡️ <b>Sahte Barge-in Koruması:</b> Sub-bass motor uğultusu {previewResult.stats.hpf_cutoff_hz ?? config.hpf_cutoff} Hz HPF ile kesildi;
                  bu önizleme tek bir ses dosyası içindir, canlı görüşmede ölçülmüş bir sonuç değildir.
                </div>
              </div>
            )}
          </div>
        </section>
      </div>
    </>
  );
}

