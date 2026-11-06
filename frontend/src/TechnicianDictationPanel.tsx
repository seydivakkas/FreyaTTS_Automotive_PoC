import React, { useState, useEffect, useRef } from "react";

import { ApiFn } from "./ui";

type Props = {
  api: ApiFn;
};

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
    } catch (e: any) {
      setError("Veriler yüklenirken hata oluştu: " + e.message);
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
    } catch (e: any) {
      setError("Ayrıştırma hatası: " + e.message);
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
    } catch (e: any) {
      setError("Rapora aktarım hatası: " + e.message);
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
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
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
                    } catch (e: any) {
                      setError("PDF bağlantısı alınamadı: " + (e?.message || String(e)));
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

