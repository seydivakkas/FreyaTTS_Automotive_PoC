// =====================================================================
// ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
// Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
// =====================================================================
import React, { useEffect, useMemo, useState } from "react";
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

const TR_MONTHS = [
  "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
  "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
];

const TR_WEEKDAYS_SHORT = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];

const TIMELINE_HOURS = Array.from({ length: 12 }, (_, i) =>
  String(i + 8).padStart(2, "0")
); // 08..19

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

function toIsoDate(year: number, monthZero: number, day: number): string {
  return `${year}-${pad2(monthZero + 1)}-${pad2(day)}`;
}

function formatTurkishLongDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  const dt = new Date(Date.UTC(y, m - 1, d, 12, 0, 0));
  return dt.toLocaleDateString("tr-TR", {
    timeZone: "Europe/Istanbul",
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

function extractSlotHourMinute(startsAt: string): string {
  const tIdx = startsAt.indexOf("T");
  if (tIdx >= 0 && startsAt.length >= tIdx + 6) {
    return startsAt.slice(tIdx + 1, tIdx + 6);
  }
  return startsAt.slice(11, 16) || "09:00";
}

export function AppointmentsTab({ api, action, refresh, busy, slots, appointments }: Props) {
  const todayIso = useMemo(
    () => new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Istanbul" }),
    []
  );

  const availableDates = useMemo(() => {
    const dates = new Set<string>();
    slots.forEach((s) => {
      const d = s.starts_at.substring(0, 10);
      if (d) dates.add(d);
    });
    return Array.from(dates).sort();
  }, [slots]);

  const [viewMode, setViewMode] = useState<"calendar" | "list">("calendar");
  const [selectedDate, setSelectedDate] = useState<string>(() => todayIso);
  const [showAllDays, setShowAllDays] = useState<boolean>(false);
  const [calMonth, setCalMonth] = useState<{ year: number; month: number }>(() => {
    const [y, m] = todayIso.split("-").map(Number);
    return { year: y || 2026, month: (m || 1) - 1 };
  });

  // If user has slots on dates and selectedDate has none, jump to first slot date once on initial load
  const [didAutoFocus, setDidAutoFocus] = useState(false);
  useEffect(() => {
    if (!didAutoFocus && availableDates.length > 0) {
      if (!availableDates.includes(selectedDate)) {
        const target = availableDates.find((d) => d >= todayIso) ?? availableDates[0];
        setSelectedDate(target);
        const [y, m] = target.split("-").map(Number);
        if (y && m) setCalMonth({ year: y, month: m - 1 });
      }
      setDidAutoFocus(true);
    }
  }, [availableDates, didAutoFocus, selectedDate, todayIso]);

  const [draggedApptId, setDraggedApptId] = useState<string | null>(null);
  const [dragOverSlotId, setDragOverSlotId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);
  const [move, setMove] = useState<{ appointment: Appointment; target: string } | null>(null);

  const [hour, setHour] = useState("09:00");

  // Index confirmed appointments by slot_id
  const apptBySlotId = useMemo(() => {
    const map = new Map<string, Appointment>();
    for (const a of appointments) {
      if (a.status === "confirmed" && a.slot_id) {
        map.set(a.slot_id, a);
      }
    }
    return map;
  }, [appointments]);

  // Day stats for monthly calendar badges
  const dayStats = useMemo(() => {
    const stats = new Map<string, { total: number; booked: number; free: number }>();
    for (const s of slots) {
      const d = s.starts_at.substring(0, 10);
      if (!d) continue;
      const cur = stats.get(d) ?? { total: 0, booked: 0, free: 0 };
      cur.total += 1;
      if (apptBySlotId.has(s.id)) cur.booked += 1;
      else cur.free += 1;
      stats.set(d, cur);
    }
    return stats;
  }, [slots, apptBySlotId]);

  const selectedDaySlots = useMemo(() => {
    const list = showAllDays
      ? [...slots]
      : slots.filter((s) => s.starts_at.startsWith(selectedDate));
    return list.sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  }, [slots, selectedDate, showAllDays]);

  const selectedDayCounts = useMemo(() => {
    let booked = 0;
    let free = 0;
    for (const s of selectedDaySlots) {
      if (apptBySlotId.has(s.id)) booked += 1;
      else free += 1;
    }
    return { booked, free, total: selectedDaySlots.length };
  }, [selectedDaySlots, apptBySlotId]);

  // Build 42-cell Monday-first calendar grid for calMonth
  const calendarCells = useMemo(() => {
    const { year, month } = calMonth;
    const firstWeekday = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7; // 0=Mon..6=Sun
    const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    const prevMonthDays = new Date(Date.UTC(year, month, 0)).getUTCDate();

    const cells: Array<{ iso: string; dayNum: number; inMonth: boolean }> = [];
    for (let i = firstWeekday - 1; i >= 0; i--) {
      const d = prevMonthDays - i;
      const pm = month === 0 ? 11 : month - 1;
      const py = month === 0 ? year - 1 : year;
      cells.push({ iso: toIsoDate(py, pm, d), dayNum: d, inMonth: false });
    }
    for (let d = 1; d <= daysInMonth; d++) {
      cells.push({ iso: toIsoDate(year, month, d), dayNum: d, inMonth: true });
    }
    let nextDay = 1;
    while (cells.length % 7 !== 0 || cells.length < 35) {
      const nm = month === 11 ? 0 : month + 1;
      const ny = month === 11 ? year + 1 : year;
      cells.push({ iso: toIsoDate(ny, nm, nextDay), dayNum: nextDay, inMonth: false });
      nextDay += 1;
    }
    return cells;
  }, [calMonth]);

  const selectDay = (iso: string) => {
    setSelectedDate(iso);
    setShowAllDays(false);
    const [y, m] = iso.split("-").map(Number);
    if (y && m) setCalMonth({ year: y, month: m - 1 });
  };

  const shiftMonth = (delta: number) => {
    setCalMonth((prev) => {
      const total = prev.year * 12 + prev.month + delta;
      return { year: Math.floor(total / 12), month: ((total % 12) + 12) % 12 };
    });
  };

  const addSlotAt = (targetDay: string, targetHour: string) => {
    action(async () => {
      await api("slots", "POST", {
        starts_at: `${targetDay}T${targetHour}:00+03:00`,
      });
      await refresh();
      setMessage({ text: `${formatTurkishLongDate(targetDay)} ${targetHour} (TSİ) eklendi.`, type: "success" });
    });
  };

  // Drag & drop handlers
  const handleDragStart = (e: React.DragEvent, apptId: string) => {
    e.dataTransfer.setData("text/plain", apptId);
    e.dataTransfer.effectAllowed = "move";
    setDraggedApptId(apptId);
  };

  const handleDragEnd = () => {
    setDraggedApptId(null);
    setDragOverSlotId(null);
  };

  const handleDragOver = (e: React.DragEvent, slotId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (dragOverSlotId !== slotId) setDragOverSlotId(slotId);
  };

  const handleDragLeave = (slotId: string) => {
    if (dragOverSlotId === slotId) setDragOverSlotId(null);
  };

  const handleDrop = (e: React.DragEvent, targetSlot: Slot) => {
    e.preventDefault();
    const apptId = e.dataTransfer.getData("text/plain") || draggedApptId;
    setDragOverSlotId(null);
    setDraggedApptId(null);
    if (!apptId) return;
    const existing = appointments.find((a) => a.id === apptId);
    if (existing && existing.slot_id !== targetSlot.id) {
      setMove({ appointment: existing, target: targetSlot.id });
    }
  };

  const getPackageAccent = (pkg?: string) => {
    switch (pkg) {
      case "vip_ekspertiz":
        return { border: "#818cf8", badgeBg: "rgba(129,140,248,0.18)", badgeText: "#c7d2fe" };
      case "full_ekspertiz":
        return { border: "#38bdf8", badgeBg: "rgba(56,189,248,0.18)", badgeText: "#bae6fd" };
      case "motor_mekanik":
        return { border: "#f59e0b", badgeBg: "rgba(245,158,11,0.18)", badgeText: "#fde68a" };
      default:
        return { border: "#10b981", badgeBg: "rgba(16,185,129,0.20)", badgeText: "#a7f3ce" };
    }
  };

  // Group selectedDaySlots by HH for the classic hourly timeline
  const slotsByHour = useMemo(() => {
    const map = new Map<string, Slot[]>();
    for (const s of selectedDaySlots) {
      const hh = extractSlotHourMinute(s.starts_at).slice(0, 2);
      const arr = map.get(hh) ?? [];
      arr.push(s);
      map.set(hh, arr);
    }
    return map;
  }, [selectedDaySlots]);

  const extraHours = useMemo(() => {
    const base = new Set(TIMELINE_HOURS);
    return Array.from(slotsByHour.keys())
      .filter((hh) => !base.has(hh))
      .sort();
  }, [slotsByHour]);

  const allTimelineHours = useMemo(
    () => [...TIMELINE_HOURS, ...extraHours].sort(),
    [extraHours]
  );

  const renderSlotCard = (s: Slot) => {
    const appt = apptBySlotId.get(s.id);
    const isOccupied = !!appt;
    const isDragOver = dragOverSlotId === s.id;
    const accent = getPackageAccent(appt?.package_type);
    const hm = extractSlotHourMinute(s.starts_at);

    return (
      <div
        key={s.id}
        onDragOver={(e) => !isOccupied && handleDragOver(e, s.id)}
        onDragLeave={() => !isOccupied && handleDragLeave(s.id)}
        onDrop={(e) => !isOccupied && handleDrop(e, s)}
        style={{
          borderRadius: "8px",
          border: isDragOver
            ? "1.5px dashed var(--info)"
            : isOccupied
            ? "1px solid var(--border-strong)"
            : "1px dashed var(--ok-border)",
          borderLeft: isOccupied ? `4px solid ${accent.border}` : isDragOver ? "4px solid var(--info)" : "4px solid #10b981",
          background: isDragOver
            ? "rgba(56, 189, 248, 0.12)"
            : isOccupied
            ? "var(--surface-3)"
            : "rgba(16, 185, 129, 0.08)",
          padding: "8px 12px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "10px",
          flexWrap: "wrap",
          transition: "all 0.15s ease",
        }}
      >
        {isOccupied && appt ? (
          <>
            <div
              draggable={!busy}
              onDragStart={(e) => handleDragStart(e, appt.id)}
              onDragEnd={handleDragEnd}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "10px",
                flex: "1 1 220px",
                cursor: "grab",
                userSelect: "none",
              }}
              title="Bu randevuyu sürükleyip boş bir saate bırakabilirsiniz"
            >
              <span style={{ color: "var(--muted)", fontSize: "14px" }} aria-hidden="true">⠿</span>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                  <strong style={{ color: "var(--text-strong)", fontSize: "0.92rem" }}>{appt.customer}</strong>
                  <span
                    style={{
                      fontSize: "0.7rem",
                      padding: "2px 7px",
                      borderRadius: "999px",
                      background: accent.badgeBg,
                      color: accent.badgeText,
                      fontWeight: 600,
                      letterSpacing: "0.02em",
                    }}
                  >
                    {appt.package_type?.replace(/_/g, " ").toUpperCase() || "STANDART"}
                  </span>
                </div>
                <div style={{ fontSize: "0.78rem", color: "var(--muted)", marginTop: "2px" }}>
                  🕒 {showAllDays ? formatDate(s.starts_at) : `${hm} TSİ`}
                  {appt.customer_phone ? `  •  📞 ${appt.customer_phone}` : ""}
                </div>
              </div>
            </div>
            <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                style={{ fontSize: "0.76rem", padding: "4px 10px" }}
                onClick={() => setMove({ appointment: appt, target: "" })}
              >
                Taşı
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                style={{
                  fontSize: "0.76rem",
                  padding: "4px 10px",
                  background: "var(--danger-bg)",
                  borderColor: "var(--danger-border)",
                  color: "var(--danger-text)",
                }}
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
          </>
        ) : (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span
                style={{
                  fontSize: "0.7rem",
                  padding: "2px 8px",
                  borderRadius: "999px",
                  background: "rgba(16, 185, 129, 0.22)",
                  color: "var(--accent)",
                  fontWeight: 700,
                }}
              >
                MÜSAİT
              </span>
              <span style={{ color: "var(--text)", fontSize: "0.85rem", fontWeight: 500 }}>
                {showAllDays ? formatDate(s.starts_at) : `${hm} TSİ`}
              </span>
            </div>
            <span style={{ color: isDragOver ? "var(--info)" : "var(--muted)", fontSize: "0.78rem" }}>
              {isDragOver ? "⬇️ Randevuyu Buraya Bırakın" : "Boş Slot — Randevu Sürükleyin"}
            </span>
          </>
        )}
      </div>
    );
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0, overflowY: "auto", padding: "4px 6px", gap: "10px" }}>
      {/* Üst Başlık & Görünüm Seçici */}
      <section
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "10px",
          padding: "10px 14px",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
              <h2 style={{ margin: 0, fontSize: "16px", color: "var(--text-strong)" }}>Randevu Takvimi & Planlama</h2>
              <span
                style={{
                  fontSize: "0.72rem",
                  padding: "2px 8px",
                  borderRadius: "999px",
                  background: "var(--surface-3)",
                  border: "1px solid var(--border-strong)",
                  color: "var(--info)",
                  fontWeight: 600,
                }}
              >
                İstanbul TS (UTC+03:00)
              </span>
            </div>
            <p style={{ margin: "3px 0 0 0", color: "var(--muted)", fontSize: "0.78rem" }}>
              Soldan gün seçin, saat çizelgesinden randevuları yönetin veya müsait slotlara sürükleyip bırakın.
            </p>
          </div>
          <div style={{ display: "flex", gap: "6px" }}>
            <button
              type="button"
              className={viewMode === "calendar" ? "primary" : "secondary"}
              onClick={() => setViewMode("calendar")}
              style={{ display: "flex", alignItems: "center", gap: "5px" }}
            >
              📅 Takvim Görünümü
            </button>
            <button
              type="button"
              className={viewMode === "list" ? "primary" : "secondary"}
              onClick={() => setViewMode("list")}
              style={{ display: "flex", alignItems: "center", gap: "5px" }}
            >
              📋 Liste Görünümü
            </button>
          </div>
        </div>

        {message && (
          <div
            style={{
              marginTop: "10px",
              padding: "8px 12px",
              borderRadius: "6px",
              background: message.type === "success" ? "rgba(16,185,129,0.14)" : "var(--danger-bg)",
              color: message.type === "success" ? "var(--accent)" : "var(--danger-text)",
              border: `1px solid ${message.type === "success" ? "var(--ok-border)" : "var(--danger-border)"}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              fontSize: "0.84rem",
            }}
          >
            <span>{message.text}</span>
            <button
              type="button"
              style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", fontWeight: "bold" }}
              onClick={() => setMessage(null)}
            >
              ✕
            </button>
          </div>
        )}
      </section>

      {/* Hızlı Müsait Saat Tanımlama Barı */}
      <section
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "10px",
          padding: "10px 14px",
        }}
      >
        <form
          className="inline"
          style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}
          onSubmit={(e) => {
            e.preventDefault();
            addSlotAt(selectedDate, hour);
          }}
        >
          <span style={{ fontSize: "0.84rem", fontWeight: 600, color: "var(--text-strong)" }}>
            ➕ Müsait Saat Tanımla:
          </span>
          <input
            type="date"
            aria-label="Tarih ve Saat (İstanbul TS)"
            required
            value={selectedDate}
            onChange={(e) => selectDay(e.target.value)}
            style={{
              background: "var(--input-bg)",
              color: "var(--text-strong)",
              border: "1px solid var(--border-strong)",
              borderRadius: "6px",
              padding: "5px 8px",
              fontSize: "0.82rem",
            }}
          />
          <div aria-label="Randevu saati" style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
            {Array.from({ length: 9 }, (_, i) => String(i + 9).padStart(2, "0") + ":00").map((h) => (
              <button
                type="button"
                key={h}
                aria-pressed={hour === h}
                className={hour === h ? "primary" : "secondary"}
                style={{ padding: "4px 8px", fontSize: "0.76rem", fontVariantNumeric: "tabular-nums" }}
                onClick={() => setHour(h)}
              >
                {h}
              </button>
            ))}
          </div>
          <button type="submit" className="primary" disabled={busy} style={{ padding: "5px 12px", fontSize: "0.8rem" }}>
            Saat Ekle
          </button>
        </form>
      </section>

      {/* GÖRÜNÜM 1: KLASİK AYLIK TAKVİM + SAATLİK GÜNLÜK ÇİZELGE */}
      {viewMode === "calendar" ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(270px, 310px) minmax(0, 1fr)",
            gap: "12px",
            alignItems: "start",
          }}
        >
          {/* SOL PANEL: Klasik Aylık Takvim */}
          <aside
            style={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: "10px",
              padding: "12px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
              <button type="button" className="secondary" style={{ padding: "4px 9px" }} onClick={() => shiftMonth(-1)} aria-label="Önceki Ay">
                ‹
              </button>
              <strong style={{ color: "var(--text-strong)", fontSize: "0.95rem" }}>
                {TR_MONTHS[calMonth.month]} {calMonth.year}
              </strong>
              <button type="button" className="secondary" style={{ padding: "4px 9px" }} onClick={() => shiftMonth(1)} aria-label="Sonraki Ay">
                ›
              </button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: "4px", marginBottom: "6px" }}>
              {TR_WEEKDAYS_SHORT.map((wd) => (
                <div
                  key={wd}
                  style={{
                    textAlign: "center",
                    fontSize: "0.72rem",
                    fontWeight: 600,
                    color: "var(--muted)",
                    padding: "3px 0",
                  }}
                >
                  {wd}
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: "4px" }}>
              {calendarCells.map((cell) => {
                const st = dayStats.get(cell.iso);
                const isSelected = !showAllDays && selectedDate === cell.iso;
                const isToday = cell.iso === todayIso;

                return (
                  <button
                    key={cell.iso}
                    type="button"
                    onClick={() => selectDay(cell.iso)}
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      justifyContent: "space-between",
                      minHeight: "42px",
                      padding: "5px 2px",
                      borderRadius: "7px",
                      border: isSelected
                        ? "1.5px solid var(--accent)"
                        : isToday
                        ? "1px solid var(--info)"
                        : "1px solid transparent",
                      background: isSelected
                        ? "rgba(167, 243, 206, 0.14)"
                        : st
                        ? "var(--surface-3)"
                        : "var(--surface-2)",
                      color: !cell.inMonth ? "var(--muted)" : isSelected ? "var(--accent)" : "var(--text-strong)",
                      opacity: cell.inMonth ? 1 : 0.45,
                      cursor: "pointer",
                      fontSize: "0.82rem",
                      fontWeight: isSelected || isToday ? 700 : 500,
                      fontVariantNumeric: "tabular-nums",
                    }}
                    title={st ? `${cell.iso}: ${st.booked} dolu, ${st.free} müsait` : cell.iso}
                  >
                    <span>{cell.dayNum}</span>
                    {st ? (
                      <span style={{ display: "flex", gap: "3px", marginTop: "2px" }}>
                        {st.booked > 0 && (
                          <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--info)" }} />
                        )}
                        {st.free > 0 && (
                          <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#10b981" }} />
                        )}
                      </span>
                    ) : (
                      <span style={{ height: "6px" }} />
                    )}
                  </button>
                );
              })}
            </div>

            {/* Takvim Alt Kısayolları & Renk Açıklaması */}
            <div style={{ marginTop: "10px", paddingTop: "10px", borderTop: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: "8px" }}>
              <div style={{ display: "flex", gap: "10px", fontSize: "0.73rem", color: "var(--muted)" }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                  <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: "var(--info)" }} /> Dolu Randevu
                </span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                  <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: "#10b981" }} /> Müsait Slot
                </span>
              </div>

              <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                <button
                  type="button"
                  className={!showAllDays && selectedDate === todayIso ? "primary" : "secondary"}
                  style={{ fontSize: "0.75rem", padding: "3px 8px" }}
                  onClick={() => selectDay(todayIso)}
                >
                  Bugün
                </button>
                <button
                  type="button"
                  className={showAllDays ? "primary" : "secondary"}
                  style={{ fontSize: "0.75rem", padding: "3px 8px" }}
                  onClick={() => setShowAllDays((v) => !v)}
                >
                  Tüm Günler ({slots.length})
                </button>
              </div>

              {availableDates.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  <span style={{ fontSize: "0.72rem", color: "var(--muted)", fontWeight: 600 }}>Kayıtlı Günler:</span>
                  <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                    {availableDates.map((d) => {
                      const st = dayStats.get(d);
                      const active = !showAllDays && selectedDate === d;
                      return (
                        <button
                          key={d}
                          type="button"
                          className={active ? "primary" : "secondary"}
                          style={{ fontSize: "0.73rem", padding: "2px 7px", fontVariantNumeric: "tabular-nums" }}
                          onClick={() => selectDay(d)}
                        >
                          {d} ({st?.total ?? 0})
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </aside>

          {/* SAĞ PANEL: Klasik Saatlik Gün Programı */}
          <section
            style={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: "10px",
              padding: "12px 14px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "8px", paddingBottom: "10px", borderBottom: "1px solid var(--border)", marginBottom: "10px" }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "1rem", color: "var(--text-strong)" }}>
                  {showAllDays ? "Tüm Günler — Kronolojik Program" : formatTurkishLongDate(selectedDate)}
                </h3>
                <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  İstanbul Saati (TSİ / UTC+03:00)
                </span>
              </div>
              <div style={{ display: "flex", gap: "6px", fontSize: "0.76rem" }}>
                <span style={{ padding: "3px 9px", borderRadius: "999px", background: "rgba(56,189,248,0.16)", color: "var(--info)", fontWeight: 600 }}>
                  Dolu: {selectedDayCounts.booked}
                </span>
                <span style={{ padding: "3px 9px", borderRadius: "999px", background: "rgba(16,185,129,0.18)", color: "var(--accent)", fontWeight: 600 }}>
                  Müsait: {selectedDayCounts.free}
                </span>
              </div>
            </div>

            {showAllDays ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {selectedDaySlots.length > 0 ? (
                  selectedDaySlots.map(renderSlotCard)
                ) : (
                  <p style={{ textAlign: "center", color: "var(--muted)", padding: "24px 12px", margin: 0 }}>
                    Henüz tanımlanmış randevu saati bulunmuyor.
                  </p>
                )}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column" }}>
                {allTimelineHours.map((hh) => {
                  const rowSlots = slotsByHour.get(hh) ?? [];
                  const hourLabel = `${hh}:00`;
                  return (
                    <div
                      key={hh}
                      style={{
                        display: "grid",
                        gridTemplateColumns: "64px minmax(0, 1fr)",
                        gap: "10px",
                        alignItems: "stretch",
                        borderBottom: "1px solid var(--border)",
                        padding: "7px 0",
                      }}
                    >
                      <div
                        style={{
                          fontSize: "0.8rem",
                          fontWeight: 600,
                          color: rowSlots.length > 0 ? "var(--text-strong)" : "var(--muted)",
                          fontVariantNumeric: "tabular-nums",
                          paddingTop: "6px",
                        }}
                      >
                        {hourLabel}
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                        {rowSlots.length > 0 ? (
                          rowSlots.map(renderSlotCard)
                        ) : (
                          <div
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              padding: "5px 10px",
                              borderRadius: "6px",
                              background: "var(--surface-2)",
                              border: "1px solid transparent",
                              color: "var(--muted)",
                              fontSize: "0.78rem",
                            }}
                          >
                            <span>Planlanmış slot yok</span>
                            <button
                              type="button"
                              className="secondary"
                              disabled={busy}
                              style={{ fontSize: "0.72rem", padding: "2px 8px" }}
                              onClick={() => addSlotAt(selectedDate, hourLabel)}
                            >
                              + {hourLabel} Aç
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      ) : (
        /* GÖRÜNÜM 2: KLASİK LİSTE GÖRÜNÜMÜ */
        <section
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "10px",
            padding: "12px 14px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
            <h3 style={{ margin: 0, color: "var(--text-strong)" }}>Randevu Listesi</h3>
            <button
              type="button"
              className={showAllDays ? "primary" : "secondary"}
              style={{ fontSize: "0.76rem", padding: "3px 9px" }}
              onClick={() => setShowAllDays((v) => !v)}
            >
              {showAllDays ? "Seçili Güne Dön" : `Tüm Günleri Göster (${slots.length})`}
            </button>
          </div>
          {selectedDaySlots.map((s) => {
            const a = apptBySlotId.get(s.id);
            return (
              <div
                className="row"
                key={s.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "10px 6px",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                <div>
                  <b style={{ color: "var(--text-strong)" }}>{formatDate(s.starts_at)}</b>
                  <div style={{ fontSize: "0.84rem", color: "var(--muted)", marginTop: "2px" }}>
                    {a ? `${a.customer} (${a.customer_phone || "Tel yok"}) — ${a.package_type || "standart"}` : "Müsait"}
                  </div>
                </div>
                {a ? (
                  <div className="appointment-row-actions" style={{ display: "flex", gap: "6px" }}>
                    <button type="button" className="secondary" disabled={busy} onClick={() => setMove({ appointment: a, target: "" })}>
                      Taşı
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy}
                      style={{
                        background: "var(--danger-bg)",
                        borderColor: "var(--danger-border)",
                        color: "var(--danger-text)",
                      }}
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
                  </div>
                ) : (
                  <span
                    className="pill"
                    style={{
                      background: "rgba(16,185,129,0.20)",
                      color: "var(--accent)",
                      border: "1px solid var(--ok-border)",
                    }}
                  >
                    Müsait
                  </span>
                )}
              </div>
            );
          })}
          {!selectedDaySlots.length && (
            <p style={{ textAlign: "center", color: "var(--muted)", padding: "20px 0", margin: 0 }}>
              Bu görünüm için kayıtlı slot bulunamadı.
            </p>
          )}
        </section>
      )}

      {move && (
        <AppointmentMoveDialog
          api={api}
          appointment={move.appointment}
          slots={slots}
          appointments={appointments}
          initialTarget={move.target}
          onClose={() => setMove(null)}
          refresh={() => action(refresh)}
          onMoved={(startsAt) => {
            setMove(null);
            setMessage({ text: `Randevu ${formatDate(startsAt)} saatine taşındı.`, type: "success" });
            void action(refresh);
          }}
        />
      )}
    </div>
  );
}
