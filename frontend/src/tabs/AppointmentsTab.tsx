// =====================================================================
// ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
// Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
// =====================================================================
import React, { useState, useMemo } from "react";
import type { ActionFn, Appointment, Slot } from "../api";
import { formatDate } from "../ui";
import type { ApiFn } from "../ui";
import { AppointmentMoveDialog } from "../AppointmentMoveDialog";

type Props = {
  api: ApiFn;
  action: ActionFn;
  refresh: () => Promise<void>;
  busy: boolean;
  slots: Slot[];
  appointments: Appointment[];
};

export function AppointmentsTab({ api, action, refresh, busy, slots, appointments }: Props) {
  const [viewMode, setViewMode] = useState<"calendar" | "list">("calendar");
  const [selectedDate, setSelectedDate] = useState<string>("all");
  const [draggedApptId, setDraggedApptId] = useState<string | null>(null);
  const [dragOverSlotId, setDragOverSlotId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);
  const [move, setMove] = useState<{ appointment: Appointment; target: string } | null>(null);

  // Group unique dates from slots
  const availableDates = useMemo(() => {
    const dates = new Set<string>();
    slots.forEach((s) => {
      const d = s.starts_at.substring(0, 10);
      if (d) dates.add(d);
    });
    return Array.from(dates).sort();
  }, [slots]);

  // Filter slots by selected date
  const filteredSlots = useMemo(() => {
    if (selectedDate === "all") return slots;
    return slots.filter((s) => s.starts_at.startsWith(selectedDate));
  }, [slots, selectedDate]);

  // Handle Drag Start
  const handleDragStart = (e: React.DragEvent, apptId: string) => {
    e.dataTransfer.setData("text/plain", apptId);
    e.dataTransfer.effectAllowed = "move";
    setDraggedApptId(apptId);
  };

  const handleDragEnd = () => {
    setDraggedApptId(null);
    setDragOverSlotId(null);
  };

  // Handle Drag Over
  const handleDragOver = (e: React.DragEvent, slotId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (dragOverSlotId !== slotId) {
      setDragOverSlotId(slotId);
    }
  };

  const handleDragLeave = (e: React.DragEvent, slotId: string) => {
    if (dragOverSlotId === slotId) {
      setDragOverSlotId(null);
    }
  };

  // Handle Drop onto Empty Slot
  const handleDrop = (e: React.DragEvent, targetSlot: Slot) => {
    e.preventDefault();
    const apptId = e.dataTransfer.getData("text/plain") || draggedApptId;
    setDragOverSlotId(null);
    setDraggedApptId(null);

    if (!apptId) return;

    // Check if appointment is already in this slot
    const existing = appointments.find((a) => a.id === apptId);
    if (existing && existing.slot_id !== targetSlot.id) {
      setMove({ appointment: existing, target: targetSlot.id });
    }
  };

  const getPackageBadgeColor = (pkg?: string) => {
    switch (pkg) {
      case "vip_ekspertiz":
        return { bg: "#818CF8", color: "#FFFFFF" };
      case "full_ekspertiz":
        return { bg: "#3B82F6", color: "#FFFFFF" };
      case "motor_mekanik":
        return { bg: "#F59E0B", color: "#FFFFFF" };
      default:
        return { bg: "#10B981", color: "#FFFFFF" };
    }
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0, overflowY: "auto", padding: "2px 4px" }}>
      {/* Üst Yönetim ve Saat Ekleme */}
      <section style={{ marginBottom: "8px", padding: "8px 12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem" }}>
          <div>
            <h2 style={{ margin: "0 0 0.15rem 0", fontSize: "16px" }}>Randevu Takvimi & Planlama</h2>
            <p style={{ margin: 0, color: "var(--muted, #64748B)", fontSize: "0.8rem" }}>
              Randevuları takvim üzerinde sürükleyip boş slotlara bırakarak yeniden saatlendirebilirsiniz.
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button
              type="button"
              className={viewMode === "calendar" ? "primary" : "secondary"}
              onClick={() => setViewMode("calendar")}
              style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}
            >
              📅 Takvim Görünümü
            </button>
            <button
              type="button"
              className={viewMode === "list" ? "primary" : "secondary"}
              onClick={() => setViewMode("list")}
              style={{ display: "flex", alignItems: "center", gap: "0.35rem" }}
            >
              📋 Liste Görünümü
            </button>
          </div>
        </div>

        {message && (
          <div
            style={{
              marginTop: "1rem",
              padding: "0.75rem 1rem",
              borderRadius: "6px",
              backgroundColor: message.type === "success" ? "#ECFDF5" : "#FEF2F2",
              color: message.type === "success" ? "#065F46" : "#991B1B",
              border: `1px solid ${message.type === "success" ? "#A7F3D0" : "#FECACA"}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>{message.text}</span>
            <button
              type="button"
              style={{ background: "none", border: "none", cursor: "pointer", fontWeight: "bold" }}
              onClick={() => setMessage(null)}
            >
              ✕
            </button>
          </div>
        )}
      </section>

      {/* Müsait Saat Ekleme Kartı */}
      <section style={{ marginBottom: "8px", background: "var(--bg-card, #F8FAFC)", padding: "8px 12px", borderRadius: "8px", border: "1px solid var(--border, #E2E8F0)" }}>
        <h3 style={{ margin: "0 0 0.4rem 0", fontSize: "0.9rem" }}>➕ Yeni Müsait Saat Tanımla</h3>
        <form
          className="inline"
          style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end", flexWrap: "wrap" }}
          onSubmit={(e) => {
            e.preventDefault();
            const d = new FormData(e.currentTarget);
            action(async () => {
              await api("slots", "POST", {
                starts_at: String(d.get("time")) + ":00+03:00",
              });
              await refresh();
              setMessage({ text: "Yeni randevu saati başarıyla eklendi.", type: "success" });
            });
          }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: "0.2rem", fontSize: "0.8rem" }}>
            Tarih ve Saat (İstanbul TS)
            <input type="datetime-local" name="time" required disabled={busy} style={{ padding: "0.3rem 0.5rem", fontSize: "0.8rem" }} />
          </label>
          <button type="submit" disabled={busy} style={{ padding: "5px 12px", fontSize: "0.8rem" }}>
            Saat Ekle
          </button>
        </form>
      </section>

      {/* Tarih Filtresi */}
      {availableDates.length > 0 && (
        <div style={{ display: "flex", gap: "0.4rem", alignItems: "center", marginBottom: "6px", overflowX: "auto", paddingBottom: "0.25rem" }}>
          <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--muted, #64748B)" }}>Tarih:</span>
          <button
            type="button"
            className={selectedDate === "all" ? "primary" : "secondary"}
            style={{ fontSize: "0.8rem", padding: "0.25rem 0.6rem" }}
            onClick={() => setSelectedDate("all")}
          >
            Tüm Günler ({slots.length})
          </button>
          {availableDates.map((d) => (
            <button
              key={d}
              type="button"
              className={selectedDate === d ? "primary" : "secondary"}
              style={{ fontSize: "0.8rem", padding: "0.25rem 0.6rem" }}
              onClick={() => setSelectedDate(d)}
            >
              {d}
            </button>
          ))}
        </div>
      )}

      {/* GÖRÜNÜM 1: SÜRÜKLE-BIRAK TAKVİM GRID */}
      {viewMode === "calendar" ? (
        <section>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: "1rem",
            }}
          >
            {filteredSlots.map((s) => {
              const appt = appointments.find((x) => x.slot_id === s.id && x.status === "confirmed");
              const isOccupied = !!appt;
              const isDragOver = dragOverSlotId === s.id;
              const badgeStyle = getPackageBadgeColor(appt?.package_type);

              return (
                <div
                  key={s.id}
                  onDragOver={(e) => !isOccupied && handleDragOver(e, s.id)}
                  onDragLeave={(e) => !isOccupied && handleDragLeave(e, s.id)}
                  onDrop={(e) => !isOccupied && handleDrop(e, s)}
                  style={{
                    borderRadius: "8px",
                    border: isDragOver
                      ? "2px dashed #2563EB"
                      : isOccupied
                      ? "1px solid #CBD5E1"
                      : "1px dashed #10B981",
                    backgroundColor: isDragOver
                      ? "#EFF6FF"
                      : isOccupied
                      ? "#FFFFFF"
                      : "#F0FDF4",
                    padding: "1rem",
                    transition: "all 0.15s ease",
                    boxShadow: isOccupied ? "0 1px 3px rgba(0,0,0,0.06)" : "none",
                    minHeight: "130px",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "space-between",
                  }}
                >
                  {/* Slot Zaman Başlığı */}
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                      <span style={{ fontSize: "1.1rem" }}>🕒</span>
                      <strong style={{ fontSize: "0.95rem" }}>{formatDate(s.starts_at)}</strong>
                    </div>
                    {isOccupied ? (
                      <span style={{ fontSize: "0.75rem", padding: "0.15rem 0.45rem", borderRadius: "12px", background: badgeStyle.bg, color: badgeStyle.color, fontWeight: 600 }}>
                        {appt.package_type?.replace(/_/g, " ").toUpperCase() || "DOLU"}
                      </span>
                    ) : (
                      <span style={{ fontSize: "0.75rem", padding: "0.15rem 0.45rem", borderRadius: "12px", background: "#D1FAE5", color: "#065F46", fontWeight: 600 }}>
                        MÜSAİT
                      </span>
                    )}
                  </div>

                  {/* Slot İçeriği / Draggable Kart */}
                  {isOccupied && appt ? (
                    <div
                      draggable={!busy}
                      onDragStart={(e) => handleDragStart(e, appt.id)}
                      onDragEnd={handleDragEnd}
                      style={{
                        padding: "0.6rem",
                        background: "#F8FAFC",
                        borderRadius: "6px",
                        border: "1px solid #E2E8F0",
                        cursor: "grab",
                        userSelect: "none",
                      }}
                      title="Bu randevuyu sürükleyip boş bir saate bırakabilirsiniz"
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.25rem" }}>
                        <span style={{ fontWeight: 600, fontSize: "0.9rem" }}>{appt.customer}</span>
                        <span style={{ fontSize: "0.85rem", color: "#94A3B8" }}>⠿ Sürükle</span>
                      </div>
                      {appt.customer_phone && (
                        <div style={{ fontSize: "0.8rem", color: "var(--muted, #64748B)" }}>
                          📞 {appt.customer_phone}
                        </div>
                      )}
                      <div style={{ marginTop: "0.6rem", display: "flex", justifyContent: "flex-end", gap: "0.4rem" }}>
                        <button type="button" className="secondary" disabled={busy}
                          onClick={() => setMove({ appointment: appt, target: "" })}>Taşı</button>
                        <button
                          type="button"
                          className="secondary"
                          style={{ fontSize: "0.75rem", padding: "0.2rem 0.5rem" }}
                          disabled={busy}
                          onClick={() =>
                            action(async () => {
                              await api(`appointments/${appt.id}/cancel`, "POST");
                              setMessage({ text: `${appt.customer} randevusu iptal edildi.`, type: "success" });
                              await refresh();
                            })
                          }
                        >
                          İptal Et
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div
                      style={{
                        textAlign: "center",
                        padding: "1rem 0.5rem",
                        color: isDragOver ? "#2563EB" : "#059669",
                        fontSize: "0.85rem",
                      }}
                    >
                      {isDragOver ? "⬇️ Randevuyu Buraya Bırakın" : "➕ Boş Slot — Randevu Sürükleyin"}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {!filteredSlots.length && (
            <p className="muted" style={{ textAlign: "center", padding: "2rem" }}>
              Bu tarih için tanımlanmış randevu saati bulunmuyor. Yukarıdan yeni saat ekleyebilirsiniz.
            </p>
          )}
        </section>
      ) : (
        /* GÖRÜNÜM 2: KLASİK LİSTE GÖRÜNÜMÜ */
        <section>
          <h2>Randevu Listesi</h2>
          {filteredSlots.map((s) => {
            const a = appointments.find((x) => x.slot_id === s.id && x.status === "confirmed");
            return (
              <div className="row" key={s.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.75rem", borderBottom: "1px solid #E2E8F0" }}>
                <div>
                  <b>{formatDate(s.starts_at)}</b>
                  <div style={{ fontSize: "0.85rem", color: "#64748B" }}>
                    {a ? `${a.customer} (${a.customer_phone || "Tel yok"}) — ${a.package_type || "standart"}` : "Müsait"}
                  </div>
                </div>
                {a ? (<div className="appointment-row-actions">
                  <button type="button" className="secondary" disabled={busy}
                    onClick={() => setMove({ appointment: a, target: "" })}>Taşı</button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      action(async () => {
                        await api(`appointments/${a.id}/cancel`, "POST");
                        setMessage({ text: "Randevu iptal edildi.", type: "success" });
                        await refresh();
                      })
                    }
                  >
                    İptal et
                  </button>
                </div>) : (
                  <span className="pill" style={{ background: "#D1FAE5", color: "#065F46" }}>Müsait</span>
                )}
              </div>
            );
          })}
        </section>
      )}
      {move && <AppointmentMoveDialog
        api={api} appointment={move.appointment} slots={slots} appointments={appointments}
        initialTarget={move.target} onClose={() => setMove(null)} refresh={() => action(refresh)}
        onMoved={(startsAt) => {
          setMove(null);
          setMessage({ text: `Randevu ${formatDate(startsAt)} saatine taşındı.`, type: "success" });
          void action(refresh);
        }}
      />}
    </div>
  );
}
