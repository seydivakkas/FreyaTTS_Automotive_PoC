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

