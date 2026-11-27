import React, { useState, useEffect } from "react";
import { errorMessage } from "./ui";

import type { ApiProps as Props } from "./api";

type LiftItem = {
  id: string;
  name: string;
  lift_number: number;
  status: "idle" | "busy" | "maintenance";
  current_appointment_id?: string | null;
  current_vehicle_plate?: string;
  package_type: string;
  started_at?: string | null;
  estimated_duration_min: number;
  notes?: string;
};

type QueueItem = {
  id: string;
  queue_number: number;
  appointment_id?: string | null;
  vehicle_id?: string | null;
  plate: string;
  customer: string;
  package_type: string;
  duration_minutes: number;
  status: "waiting" | "in_progress" | "completed" | "cancelled";
  lift_id?: string | null;
  check_in_at: string;
  started_at?: string | null;
  completed_at?: string | null;
};

type CapacityStatus = {
  total_lifts: number;
  active_lifts: number;
  busy_lifts: number;
  idle_lifts: number;
  maintenance_lifts: number;
  queue_waiting_count: number;
  // null = hesaplanamadı (lift yok veya kalan süre bilinmiyor)
  estimated_wait_minutes: number | null;
  all_lifts_busy: boolean;
  earliest_available_time: string | null;
  spoken_message: string;
};

type PackageItem = {
  key: string;
  name: string;
  duration_minutes: number;
  description: string;
  base_price_kurus: number;
};

export function QueueLiftPanel({ api }: Props) {
  const [lifts, setLifts] = useState<LiftItem[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [packages, setPackages] = useState<PackageItem[]>([]);
  const [capacity, setCapacity] = useState<CapacityStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  // Check-in Form States
  const [newPlate, setNewPlate] = useState("");
  const [newCustomer, setNewCustomer] = useState("");
  const [newPackage, setNewPackage] = useState("standart_ekspertiz");

  // New Lift Form States
  const [showAddLift, setShowAddLift] = useState(false);
  const [newLiftName, setNewLiftName] = useState("");
  const [newLiftNumber, setNewLiftNumber] = useState<number | "">("");
  const [newLiftNotes, setNewLiftNotes] = useState("");

  // Manual Assign Modal / State
  const [assigningLiftId, setAssigningLiftId] = useState<string | null>(null);
  const [assignPlate, setAssignPlate] = useState("");
  const [assignPackage, setAssignPackage] = useState("standart_ekspertiz");

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000); // 10s auto refresh
    return () => clearInterval(interval);
  }, []);

  async function loadData() {
    try {
      const [lList, qList, cap, pkgs] = await Promise.all([
        api("lifts"),
        api("queue"),
        api("lifts/capacity"),
        api("packages"),
      ]);
      setLifts(lList || []);
      setQueue(qList || []);
      setCapacity(cap);
      setPackages(pkgs || []);
      setLoadError("");
    } catch (e) {
      setLoadError("Lift ve sıra verileri alınamadı: " + errorMessage(e));
    }
  }

  async function handleAddQueue(e: React.FormEvent) {
    e.preventDefault();
    if (!newPlate.trim() || !newCustomer.trim()) {
      setError("Lütfen araç plakası ve müşteri adını girin.");
      return;
    }
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      const created = await api("queue", "POST", {
        plate: newPlate.trim().toUpperCase(),
        customer: newCustomer.trim(),
        package_type: newPackage,
      });
      setNewPlate("");
      setNewCustomer("");
      await loadData();
      setSuccessMsg(
        `Araç sıraya eklendi! Sıra No: #${created.queue_number} (${created.plate})`
      );
    } catch (e) {
      setError("Sıraya alma hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleAddLift(e: React.FormEvent) {
    e.preventDefault();
    if (!newLiftName.trim()) {
      setError("Lütfen lift adını girin.");
      return;
    }
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      await api("lifts", "POST", {
        name: newLiftName.trim(),
        lift_number: newLiftNumber === "" ? undefined : Number(newLiftNumber),
        notes: newLiftNotes.trim(),
      });
      setNewLiftName("");
      setNewLiftNumber("");
      setNewLiftNotes("");
      setShowAddLift(false);
      await loadData();
      setSuccessMsg("Yeni muayene lifti başarıyla oluşturuldu.");
    } catch (e) {
      setError("Lift oluşturma hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleCallNext(liftId: string) {
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      const res = await api(`lifts/${liftId}/call-next`, "POST");
      await loadData();
      if (res.assigned) {
        setSuccessMsg(
          `Sıradaki araç #${res.queue_item.queue_number} (${res.queue_item.plate}) lifte alındı ve muayene başladı!`
        );
      } else {
        setSuccessMsg("Sırada bekleyen araç bulunmuyor.");
      }
    } catch (e) {
      setError("Lifte alma hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleRelease(liftId: string) {
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      await api(`lifts/${liftId}/release`, "POST");
      await loadData();
      setSuccessMsg("Araç liftten çıkarıldı ve lift boş (müsait) duruma getirildi.");
    } catch (e) {
      setError("Lift boşaltma hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleToggleMaintenance(lift: LiftItem) {
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      const nextStatus = lift.status === "maintenance" ? "idle" : "maintenance";
      await api(`lifts/${lift.id}/status`, "POST", {
        status: nextStatus,
        notes: nextStatus === "maintenance" ? "Periyodik teknik bakımda" : "Bakım tamamlandı, aktif.",
      });
      await loadData();
      setSuccessMsg(
        nextStatus === "maintenance"
          ? `${lift.name} bakıma alındı.`
          : `${lift.name} bakımdan çıkarıldı ve hizmete hazır.`
      );
    } catch (e) {
      setError("Durum güncelleme hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleManualAssign(e: React.FormEvent) {
    e.preventDefault();
    if (!assigningLiftId || !assignPlate.trim()) {
      setError("Lütfen geçerli plaka girin.");
      return;
    }
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      await api(`lifts/${assigningLiftId}/assign`, "POST", {
        plate: assignPlate.trim().toUpperCase(),
        package_type: assignPackage,
      });
      setAssigningLiftId(null);
      setAssignPlate("");
      await loadData();
      setSuccessMsg("Araç başarıyla lifte atandı ve işlem başlatıldı.");
    } catch (e) {
      setError("Lifte atama hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleCancelQueue(qId: string) {
    setLoading(true);
    setError("");
    setSuccessMsg("");
    try {
      await api(`queue/${qId}/cancel`, "POST");
      await loadData();
      setSuccessMsg("Sıra kaydı iptal edildi.");
    } catch (e) {
      setError("İptal hatası: " + errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: "8px", minHeight: 0, overflowY: "auto", padding: "2px 4px" }}>
      {/* Üst Başlık & Kapasite Özeti */}
      <section
        style={{
          background: "linear-gradient(135deg, #1E293B 0%, #0F172A 100%)",
          color: "white",
          padding: "20px",
          borderRadius: "10px",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
          <div>
            <h2 style={{ margin: "0 0 6px 0", color: "#38BDF8", display: "flex", alignItems: "center", gap: "10px" }}>
              <span>🏗️</span> Sıra / Kuyruk Yönetimi ve Canlı Lift Durumu
            </h2>
            <p style={{ margin: 0, fontSize: "14px", color: "#94A3B8", maxWidth: "750px" }}>
              Ekspertiz merkezindeki lift kapasitesi, araç bekleme süreleri ve muayene paketlerine göre operasyonel akış takibi.
            </p>
          </div>
          <div style={{ display: "flex", gap: "10px" }}>
            <button
              type="button"
              className="secondary"
              onClick={() => setShowAddLift(!showAddLift)}
              style={{ padding: "8px 14px", fontSize: "13px" }}
            >
              ➕ Yeni Lift Tanımla
            </button>
            <button
              type="button"
              onClick={loadData}
              disabled={loading}
              style={{
                backgroundColor: "#2563EB",
                color: "white",
                padding: "8px 14px",
                borderRadius: "6px",
                border: "none",
                cursor: "pointer",
              }}
            >
              🔄 Yenile
            </button>
          </div>
        </div>

        {/* Canlı Kapasite Sayaçları */}
        {capacity && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "10px", marginTop: "16px" }}>
            <div style={{ backgroundColor: "#334155", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#94A3B8" }}>TOPLAM LİFT</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#F8FAFC" }}>{capacity.total_lifts}</div>
            </div>
            <div style={{ backgroundColor: "#065F46", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#A7F3D0" }}>BOŞ / MÜSAİT</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#FFFFFF" }}>{capacity.idle_lifts}</div>
            </div>
            <div style={{ backgroundColor: "#831843", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#FBCFE8" }}>DOLU (İŞLEMDE)</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#FFFFFF" }}>{capacity.busy_lifts}</div>
            </div>
            <div style={{ backgroundColor: "#713F12", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#FDE68A" }}>BAKIMDA</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#FFFFFF" }}>{capacity.maintenance_lifts}</div>
            </div>
            <div style={{ backgroundColor: "#1E3A8A", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#BFDBFE" }}>SIRADA BEKLEYEN</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#FFFFFF" }}>{capacity.queue_waiting_count} Araç</div>
            </div>
            <div style={{ backgroundColor: "#4C1D95", padding: "10px", borderRadius: "8px", textAlign: "center" }}>
              <div style={{ fontSize: "11px", color: "#DDD6FE" }}>TAHMİNİ BEKLEME</div>
              <div style={{ fontSize: "20px", fontWeight: "bold", color: "#FFFFFF" }}>
                {capacity.estimated_wait_minutes == null
                  ? (capacity.total_lifts - capacity.maintenance_lifts <= 0 ? "Lift yok" : "Hesaplanamadı")
                  : capacity.estimated_wait_minutes > 0
                    ? `~${capacity.estimated_wait_minutes} dk`
                    : "0 dk"}
              </div>
            </div>
          </div>
        )}

        {/* Sesli Asistan Canlı Anons Bandı */}
        {capacity && (
          <div
            style={{
              backgroundColor: "rgba(56, 189, 248, 0.12)",
              border: "1px solid #0284C7",
              borderRadius: "6px",
              padding: "10px 14px",
              marginTop: "14px",
              display: "flex",
              alignItems: "center",
              gap: "10px",
            }}
          >
            <span style={{ fontSize: "20px" }}>🎙️</span>
            <div>
              <div style={{ fontSize: "11px", fontWeight: "bold", color: "#38BDF8", textTransform: "uppercase" }}>
                Sesli Asistan Durum Bilgilendirmesi:
              </div>
              <div style={{ fontSize: "13.5px", color: "#F0F9FF", fontWeight: 500 }}>
                "{capacity.spoken_message}"
              </div>
            </div>
          </div>
        )}
      </section>

      {loadError && (
        <div role="alert" className="error" style={{ padding: "12px 16px", borderRadius: "8px" }}>
          ⚠️ {loadError}
        </div>
      )}

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

      {/* Yeni Lift Ekleme Formu (Açılır Kapanır) */}
      {showAddLift && (
        <section style={{ backgroundColor: "#F8FAFC", padding: "16px", borderRadius: "8px", border: "1px solid #CBD5E1" }}>
          <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", color: "#1E293B" }}>
            ➕ Yeni Muayene Lifti Tanımla
          </h3>
          <form onSubmit={handleAddLift} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "12px", alignItems: "flex-end" }}>
            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>Lift Adı:</label>
              <input
                type="text"
                required
                placeholder="Örn: Lift-3 (Süspansiyon & Yanal Kayma)"
                value={newLiftName}
                onChange={(e) => setNewLiftName(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>
            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>Lift Numarası (Sıra):</label>
              <input
                type="number"
                placeholder="Örn: 3"
                value={newLiftNumber}
                onChange={(e) => setNewLiftNumber(e.target.value ? Number(e.target.value) : "")}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>
            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>İstasyon Notu / Ekipman:</label>
              <input
                type="text"
                placeholder="Örn: 4 ton hidrolik lift, Dyno donanımlı"
                value={newLiftNotes}
                onChange={(e) => setNewLiftNotes(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button type="submit" disabled={loading} style={{ backgroundColor: "#2563EB", color: "white", padding: "9px 16px", borderRadius: "6px", border: "none", cursor: "pointer", fontWeight: "bold" }}>
                Kaydet
              </button>
              <button type="button" className="secondary" onClick={() => setShowAddLift(false)}>
                Vazgeç
              </button>
            </div>
          </form>
        </section>
      )}

      {/* Manuel Lifte Atama Modalı / Paneli */}
      {assigningLiftId && (
        <section style={{ backgroundColor: "#FEF3C7", padding: "16px", borderRadius: "8px", border: "1px solid #F59E0B" }}>
          <h3 style={{ margin: "0 0 10px 0", fontSize: "15px", color: "#92400E" }}>
            🚗 Lifte Doğrudan Araç Ata (Muayene Başlat)
          </h3>
          <form onSubmit={handleManualAssign} style={{ display: "flex", flexWrap: "wrap", gap: "10px", alignItems: "flex-end" }}>
            <div style={{ minWidth: "180px" }}>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>Araç Plakası:</label>
              <input
                type="text"
                required
                placeholder="34 ABC 123"
                value={assignPlate}
                onChange={(e) => setAssignPlate(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>
            <div style={{ minWidth: "200px" }}>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>Ekspertiz Paketi:</label>
              <select
                value={assignPackage}
                onChange={(e) => setAssignPackage(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              >
                {packages.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.name} ({p.duration_minutes} dk)
                  </option>
                ))}
              </select>
            </div>
            <button type="submit" disabled={loading} style={{ backgroundColor: "#D97706", color: "white", padding: "9px 16px", borderRadius: "6px", border: "none", fontWeight: "bold", cursor: "pointer" }}>
              Lifte Al ve Başlat
            </button>
            <button type="button" className="secondary" onClick={() => setAssigningLiftId(null)}>
              İptal
            </button>
          </form>
        </section>
      )}

      {/* 1. CANLI LİFT KARTLARI (İstasyon Takibi) */}
      <section>
        <h3 style={{ margin: "0 0 12px 0", fontSize: "16px", color: "#1E293B" }}>
          📍 İstasyon Liftleri ve Anlık Durum
        </h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "14px" }}>
          {lifts.map((lift) => {
            const isIdle = lift.status === "idle";
            const isBusy = lift.status === "busy";
            const isMaint = lift.status === "maintenance";

            const borderColor = isIdle ? "#10B981" : isBusy ? "#DC2626" : "#F59E0B";
            const badgeBg = isIdle ? "#ECFDF5" : isBusy ? "#FEF2F2" : "#FFFBEB";
            const badgeText = isIdle ? "#065F46" : isBusy ? "#991B1B" : "#92400E";
            const statusLabel = isIdle ? "BOŞ (MÜSAİT)" : isBusy ? "İŞLEMDE (DOLU)" : "BAKIMDA";

            return (
              <div
                key={lift.id}
                style={{
                  backgroundColor: "#FFFFFF",
                  border: `2px solid ${borderColor}`,
                  borderRadius: "8px",
                  padding: "16px",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  boxShadow: "0 2px 4px rgba(0,0,0,0.04)",
                }}
              >
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "8px" }}>
                    <div>
                      <div style={{ fontSize: "11px", fontWeight: "bold", color: "#64748B" }}>
                        LİFT #{lift.lift_number}
                      </div>
                      <div style={{ fontSize: "15px", fontWeight: "bold", color: "#0F172A" }}>
                        {lift.name}
                      </div>
                    </div>
                    <span
                      style={{
                        backgroundColor: badgeBg,
                        color: badgeText,
                        fontSize: "11px",
                        fontWeight: "bold",
                        padding: "3px 8px",
                        borderRadius: "4px",
                        border: `1px solid ${borderColor}`,
                      }}
                    >
                      {statusLabel}
                    </span>
                  </div>

                  {lift.notes && (
                    <div style={{ fontSize: "12px", color: "#64748B", marginBottom: "10px" }}>
                      ℹ️ {lift.notes}
                    </div>
                  )}

                  {isBusy && (
                    <div
                      style={{
                        backgroundColor: "#F8FAFC",
                        padding: "10px",
                        borderRadius: "6px",
                        border: "1px solid #E2E8F0",
                        marginBottom: "12px",
                      }}
                    >
                      <div style={{ fontSize: "14px", fontWeight: "bold", color: "#1E293B" }}>
                        🚙 Plaka: {lift.current_vehicle_plate || "Kayıtlı Araç"}
                      </div>
                      <div style={{ fontSize: "12px", color: "#475569", marginTop: "3px" }}>
                        📦 Paket: {lift.package_type} (~{lift.estimated_duration_min} dk)
                      </div>
                      {lift.started_at && (
                        <div style={{ fontSize: "11px", color: "#64748B", marginTop: "2px" }}>
                          ⏱️ Başlama: {lift.started_at.slice(11, 16)}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Buton Kontrolleri */}
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "12px" }}>
                  {isIdle && (
                    <>
                      <button
                        type="button"
                        onClick={() => handleCallNext(lift.id)}
                        disabled={loading}
                        style={{
                          backgroundColor: "#059669",
                          color: "white",
                          padding: "6px 12px",
                          borderRadius: "4px",
                          border: "none",
                          fontSize: "12.5px",
                          fontWeight: "bold",
                          cursor: "pointer",
                        }}
                      >
                        ⚡ Sıradakini Al
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => {
                          setAssigningLiftId(lift.id);
                          setAssignPlate("");
                        }}
                        style={{ padding: "6px 10px", fontSize: "12px" }}
                      >
                        Plaka Ata
                      </button>
                    </>
                  )}

                  {isBusy && (
                    <button
                      type="button"
                      onClick={() => handleRelease(lift.id)}
                      disabled={loading}
                      style={{
                        backgroundColor: "#DC2626",
                        color: "white",
                        padding: "6px 12px",
                        borderRadius: "4px",
                        border: "none",
                        fontSize: "12.5px",
                        fontWeight: "bold",
                        cursor: "pointer",
                      }}
                    >
                      ✅ Muayeneyi Tamamla
                    </button>
                  )}

                  <button
                    type="button"
                    className="secondary"
                    onClick={() => handleToggleMaintenance(lift)}
                    disabled={loading}
                    style={{ padding: "6px 10px", fontSize: "12px" }}
                  >
                    {isMaint ? "Bakımdan Çıkar" : "Bakıma Al"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* 2. CANLI SIRA KUYRUĞU (Queue Check-in & List) */}
      <div className="grid-1-2" style={{ gap: "18px", alignItems: "flex-start" }}>
        {/* Sol Kolon: Sıraya Yeni Araç Alma (Check-in) */}
        <section style={{ backgroundColor: "#FFFFFF", padding: "16px", borderRadius: "8px", border: "1px solid #E2E8F0" }}>
          <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", color: "#1E293B" }}>
            🎫 Sahaya Gelen Aracı Sıraya Al (Check-in)
          </h3>
          <form onSubmit={handleAddQueue} style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>
                Araç Plakası:
              </label>
              <input
                type="text"
                required
                placeholder="Örn: 34 EKP 2026"
                value={newPlate}
                onChange={(e) => setNewPlate(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>

            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>
                Müşteri / Kurumsal Ad:
              </label>
              <input
                type="text"
                required
                placeholder="Örn: Ahmet Yılmaz / Galeri A.Ş."
                value={newCustomer}
                onChange={(e) => setNewCustomer(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              />
            </div>

            <div>
              <label style={{ fontSize: "12px", fontWeight: "bold", display: "block", marginBottom: "4px" }}>
                Ekspertiz Paketi:
              </label>
              <select
                value={newPackage}
                onChange={(e) => setNewPackage(e.target.value)}
                style={{ width: "100%", padding: "8px", borderRadius: "6px", border: "1px solid #CBD5E1" }}
              >
                {packages.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.name} ({p.duration_minutes} dk) — {p.base_price_kurus / 100} TL
                  </option>
                ))}
              </select>
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{
                backgroundColor: "#2563EB",
                color: "white",
                padding: "10px",
                borderRadius: "6px",
                border: "none",
                fontWeight: "bold",
                cursor: "pointer",
                marginTop: "6px",
              }}
            >
              🎟️ Sıra Fişi Ver & Kuyruğa Ekle
            </button>
          </form>
        </section>

        {/* Sağ Kolon: Aktif Sıra Kuyruğu Tablosu */}
        <section style={{ backgroundColor: "#FFFFFF", padding: "16px", borderRadius: "8px", border: "1px solid #E2E8F0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <h3 style={{ margin: 0, fontSize: "15px", color: "#1E293B" }}>
              📋 Canlı Bekleme Kuyruğu ({queue.filter((q) => q.status === "waiting").length} Bekleyen)
            </h3>
            <span style={{ fontSize: "12px", color: "#64748B" }}>
              Toplam Kayıt: {queue.length}
            </span>
          </div>

          <div className="table-wrap">
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
              <thead>
                <tr style={{ backgroundColor: "#F8FAFC", borderBottom: "2px solid #E2E8F0", textAlign: "left" }}>
                  <th style={{ padding: "8px" }}>Sıra No</th>
                  <th style={{ padding: "8px" }}>Plaka</th>
                  <th style={{ padding: "8px" }}>Müşteri</th>
                  <th style={{ padding: "8px" }}>Paket / Süre</th>
                  <th style={{ padding: "8px" }}>Durum</th>
                  <th style={{ padding: "8px" }}>İşlem</th>
                </tr>
              </thead>
              <tbody>
                {queue.length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ padding: "16px", textAlign: "center", color: "#94A3B8" }}>
                      Henüz sırada araç bulunmuyor.
                    </td>
                  </tr>
                ) : (
                  queue.map((item) => {
                    let statusColor = "#64748B";
                    let statusLabel: string = item.status;
                    if (item.status === "waiting") {
                      statusColor = "#D97706";
                      statusLabel = "Bekliyor ⏳";
                    } else if (item.status === "in_progress") {
                      statusColor = "#2563EB";
                      statusLabel = "İşlemde ⚙️";
                    } else if (item.status === "completed") {
                      statusColor = "#059669";
                      statusLabel = "Tamamlandı ✅";
                    } else if (item.status === "cancelled") {
                      statusColor = "#DC2626";
                      statusLabel = "İptal ❌";
                    }

                    return (
                      <tr key={item.id} style={{ borderBottom: "1px solid #F1F5F9" }}>
                        <td style={{ padding: "8px", fontWeight: "bold" }}>#{item.queue_number}</td>
                        <td style={{ padding: "8px", fontWeight: "bold", color: "#0F172A" }}>{item.plate}</td>
                        <td style={{ padding: "8px" }}>{item.customer}</td>
                        <td style={{ padding: "8px" }}>
                          {item.package_type} <small style={{ color: "#64748B" }}>({item.duration_minutes} dk)</small>
                        </td>
                        <td style={{ padding: "8px", color: statusColor, fontWeight: "bold" }}>{statusLabel}</td>
                        <td style={{ padding: "8px" }}>
                          {item.status === "waiting" && (
                            <button
                              type="button"
                              className="danger"
                              onClick={() => handleCancelQueue(item.id)}
                              style={{ padding: "2px 8px", fontSize: "11px" }}
                            >
                              İptal
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* 3. STANDART EKSPERTİZ PAKETLERİ VE SÜRELERİ REFERANSI */}
      <section style={{ backgroundColor: "#F8FAFC", padding: "16px", borderRadius: "8px", border: "1px solid #E2E8F0" }}>
        <h3 style={{ margin: "0 0 10px 0", fontSize: "14px", color: "#334155" }}>
          ⏱️ Ekspertiz Paketleri ve Standart İşlem Süreleri
        </h3>
        {[...packages, {key:"", name:"", description:"", duration_minutes:30, base_price_kurus:0}].map(pkg =>
          <form key={pkg.key || "new"} onSubmit={async e => {
            e.preventDefault();
            const form = e.currentTarget;
            const d = new FormData(form);
            try {
              await api("packages/" + (pkg.key || crypto.randomUUID()), "PUT", {
                name: String(d.get("name")).trim(), description: String(d.get("description")),
                duration_minutes: Number(d.get("duration")), base_price_kurus: Math.round(Number(d.get("price")) * 100)
              });
              if (!pkg.key) form.reset();
              await loadData();
            } catch (err) { setError(errorMessage(err)); }
          }}>
            <label>İş adı <input name="name" required defaultValue={pkg.name}/></label>
            <label>İçerik <input name="description" defaultValue={pkg.description}/></label>
            <label>Dakika <input name="duration" type="number" min="1" max="1440" required defaultValue={pkg.duration_minutes}/></label>
            <label>Fiyat (TL) <input name="price" type="number" min="0" step="0.01" required defaultValue={pkg.base_price_kurus/100}/></label>
            <button>{pkg.key ? "Güncelle" : "Ek iş ekle"}</button>
            {pkg.key && pkg.key !== "standart_ekspertiz" && <button type="button" onClick={async () => {
              if (!window.confirm(pkg.name + " silinsin mi?")) return;
              try { await api("packages/" + pkg.key, "DELETE"); await loadData(); } catch (err) {setError(errorMessage(err));}
            }}>Sil</button>}
          </form>)}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "10px" }}>
          {packages.map((pkg) => (
            <div key={pkg.key} style={{ backgroundColor: "#FFFFFF", padding: "12px", borderRadius: "6px", border: "1px solid #E2E8F0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontWeight: "bold", fontSize: "13px", color: "#1E293B" }}>{pkg.name}</span>
                <span style={{ backgroundColor: "#EFF6FF", color: "#1D4ED8", padding: "2px 6px", borderRadius: "4px", fontSize: "11px", fontWeight: "bold" }}>
                  {pkg.duration_minutes} dk
                </span>
              </div>
              <p style={{ margin: "0 0 6px 0", fontSize: "12px", color: "#64748B", lineHeight: "1.4" }}>
                {pkg.description}
              </p>
              <div style={{ fontSize: "12px", fontWeight: "bold", color: "#059669" }}>
                Taban Fiyat: {pkg.base_price_kurus / 100} TL
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
