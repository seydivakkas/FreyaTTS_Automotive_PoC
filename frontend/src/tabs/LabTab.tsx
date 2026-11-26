/**
 * FreyaTTS Automotive Cockpit — Ses Laboratuvarı & FreyaTTS Stüdyosu (LabTab.tsx)
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
  request_ms: number;
  duration_sec: number | null;
  rtf: number | null;
  sample_rate_hz: number | null;
  size_kb: number;
}

// H01.13: ses süresi tahmin edilmez; WAV başlığındaki gerçek örnekleme hızı ve veri
// boyutundan hesaplanır. Başlık okunamazsa null ("—") döner.
function parseWavInfo(buf: ArrayBuffer): { sampleRate: number; durationSec: number } | null {
  const v = new DataView(buf);
  if (buf.byteLength < 44) return null;
  const tag = (o: number) => String.fromCharCode(v.getUint8(o), v.getUint8(o + 1), v.getUint8(o + 2), v.getUint8(o + 3));
  if (tag(0) !== "RIFF" || tag(8) !== "WAVE") return null;
  let off = 12;
  let sampleRate = 0;
  let blockAlign = 0;
  while (off + 8 <= buf.byteLength) {
    const id = tag(off);
    const size = v.getUint32(off + 4, true);
    if (id === "fmt ") {
      sampleRate = v.getUint32(off + 12, true);
      blockAlign = v.getUint16(off + 20, true);
    } else if (id === "data") {
      if (!sampleRate || !blockAlign) return null;
      const dataBytes = Math.min(size, buf.byteLength - off - 8);
      return { sampleRate, durationSec: dataBytes / blockAlign / sampleRate };
    }
    off += 8 + size + (size % 2);
  }
  return null;
}

// H01.13: arka uç /api/synthesize bu parametreleri uygulamıyor (FreyaTTS, Leyla seed 9).
const INERT_CONTROL_NOTE = "Devre dışı: FreyaTTS arka ucu bu parametreyi uygulamıyor (Leyla, seed 9).";

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
    text: "Mevcut randevunuz 18 Kasım Çarşamba günü saat 14:00 olarak güncellenmiştir.",
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
  // H01.13: ölçüm yokken sabit sayı gösterilmez.
  const [telemetry, setTelemetry] = useState<TtsTelemetry | null>(null);

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
        const r = await rawApi("synthesize", "POST", { text });
        const blob = await r.blob();
        const elapsedMs = Math.round(performance.now() - start);
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        const url = URL.createObjectURL(blob);
        setAudioUrl(url);

        const info = parseWavInfo(await blob.arrayBuffer());
        const sizeKb = Math.round(blob.size / 1024);
        setTelemetry({
          request_ms: elapsedMs,
          duration_sec: info ? info.durationSec : null,
          rtf: info && info.durationSec > 0 ? elapsedMs / 1000 / info.durationSec : null,
          sample_rate_hz: info ? info.sampleRate : null,
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
    <div className="lab-tab" style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0, padding: "2px 0", overflow: "hidden" }}>
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
            Ses Laboratuvarı & FreyaTTS Stüdyosu
          </h2>
          <span className="stage-badge brand">
            <Volume2 size={12} /> F5 FreyaTTS
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
          Model: FreyaTTS · Leyla (seed 9)
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
                  disabled
                  title={INERT_CONTROL_NOTE}
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
                <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 6 }}>{INERT_CONTROL_NOTE}</div>
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
                  disabled
                  title={INERT_CONTROL_NOTE}
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
                  disabled
                  title={INERT_CONTROL_NOTE}
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
                  disabled
                  title={INERT_CONTROL_NOTE}
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
              aria-label="Sentez metni"
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
                  <span data-testid="lab-normalized-text" style={{ color: "#34d399", fontWeight: 600, wordBreak: "break-word" }}>
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
                    <span className="metric-tile-label">İstek süresi</span>
                    <span className="metric-tile-value tabular-data" style={{ color: "#34d399" }}>
                      {telemetry.request_ms} ms
                    </span>
                    <span className="metric-tile-sub">Tek istek; p95 değildir</span>
                  </div>

                  <div className="metric-tile">
                    <span className="metric-tile-label">Hız Faktörü (RTF)</span>
                    <span className="metric-tile-value tabular-data" style={{ color: "#38bdf8" }}>
                      {telemetry.rtf === null ? "—" : `${telemetry.rtf.toFixed(2)}x`}
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
                      {telemetry.duration_sec === null ? "—" : `${telemetry.duration_sec.toFixed(2)} sn`}
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "#94a3b8" }}>Örnekleme Hızı:</span>
                    <span className="tabular-data" style={{ color: "#f8fafc", fontWeight: 600 }}>
                      {telemetry.sample_rate_hz === null ? "—" : `${telemetry.sample_rate_hz} Hz`}
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
                    <span style={{ color: "#94a3b8", fontWeight: 600 }}>—</span>
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
                  <span>Tek istek ölçümüdür; gecikme kararlılığı için p50/p95 ölçümü gerekir (Ölçüm bekleniyor).</span>
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
