import { useEffect, useState, useMemo } from "react";
import { ApiFn, useEscape } from "./ui";

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

type Props = {
  api: ApiFn;
};

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
    } catch (e: any) {
      setError("PDF bağlantısı alınamadı: " + (e?.message || String(e)));
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
    } catch (e: any) {
      setError(e?.message || String(e));
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

