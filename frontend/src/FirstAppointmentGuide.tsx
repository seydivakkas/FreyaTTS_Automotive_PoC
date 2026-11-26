// =====================================================================
// ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
// Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
// =====================================================================

import React, { useState } from "react";
import type { ActionFn, Appointment, Conversation, Health, Slot, Vehicle } from "./api";
import { TabName } from "./nav";
import { ApiFn, formatDate } from "./ui";

interface Props {
  health: Health;
  vehicles: Vehicle[];
  slots: Slot[];
  appointments: Appointment[];
  calls: Conversation[];
  onNavigateToTab: (tab: TabName) => void;
  action: ActionFn;
  api: ApiFn;
  refresh: () => Promise<void>;
  busy: boolean;
  onStartVoice?: () => void;
}

export function FirstAppointmentGuide({
  health,
  vehicles,
  slots,
  appointments,
  calls,
  onNavigateToTab,
  action,
  api,
  refresh,
  busy,
  onStartVoice,
}: Props) {
  const modelsReady =
    health.stt?.status === "READY" &&
    health.ollama?.status === "READY" &&
    health.tts?.status === "READY";

  const vehiclesReady = vehicles.length > 0;
  const slotsReady = slots.length > 0;
  const confirmedAppointments = appointments.filter((a) => a.status === "confirmed");
  const appointmentReady = confirmedAppointments.length > 0;
  const conversationReady = calls.length > 0 || appointmentReady;

  const isAllComplete = modelsReady && vehiclesReady && slotsReady && appointmentReady;

  // Boş kurulumda açık, tüm adımlar bitince varsayılan olarak kapalı/özet
  const [isExpanded, setIsExpanded] = useState(!isAllComplete);

  const addQuickVehicle = () => {
    action(async () => {
      const v = await api("vehicles", "POST", {
        description: "Volkswagen Passat 1.5 TSI",
        plate: "34 ABC 123",
      });
      if (v?.id) {
        try {
          await api("quotes", "POST", {
            vehicle_id: v.id,
            amount_kurus: 350000,
          });
        } catch {
          // quotes opsiyonel
        }
      }
      await refresh();
    });
  };

  const addQuickSlot = () => {
    action(async () => {
      // Yarın sabah 10:00 İstanbul saati
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      const year = tomorrow.getFullYear();
      const month = String(tomorrow.getMonth() + 1).padStart(2, "0");
      const day = String(tomorrow.getDate()).padStart(2, "0");
      const isoTime = `${year}-${month}-${day}T10:00:00+03:00`;

      await api("slots", "POST", {
        starts_at: isoTime,
        duration_minutes: 30,
      });
      await refresh();
    });
  };

  const loadModels = () => {
    action(async () => {
      await api("models/load", "POST");
      await refresh();
    });
  };

  return (
    <div
      className="first-appointment-guide-container"
      style={{
        background: isAllComplete
          ? "linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(15, 23, 42, 0.6) 100%)"
          : "linear-gradient(135deg, rgba(37, 99, 235, 0.12) 0%, rgba(15, 23, 42, 0.8) 100%)",
        border: isAllComplete
          ? "1px solid rgba(16, 185, 129, 0.3)"
          : "1px solid rgba(59, 130, 246, 0.35)",
        borderRadius: "10px",
        margin: "0 0 10px 0",
        padding: "10px 14px",
        boxShadow: "0 4px 12px rgba(0, 0, 0, 0.2)",
      }}
    >
      {/* Başlık ve Durum Çubuğu */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          cursor: "pointer",
        }}
        onClick={() => setIsExpanded((prev) => !prev)}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "1.2rem" }}>{isAllComplete ? "✅" : "🚀"}</span>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <strong style={{ fontSize: "0.95rem", color: "#f8fafc" }}>
                {isAllComplete ? "İlk Randevu Akışı Tamamlandı" : "İlk Randevu Kurulum Rehberi"}
              </strong>
              <span
                style={{
                  fontSize: "10px",
                  fontWeight: 700,
                  padding: "1px 6px",
                  borderRadius: "4px",
                  background: isAllComplete ? "rgba(16, 185, 129, 0.2)" : "rgba(59, 130, 246, 0.2)",
                  color: isAllComplete ? "#34d399" : "#60a5fa",
                  border: isAllComplete
                    ? "1px solid rgba(16, 185, 129, 0.4)"
                    : "1px solid rgba(59, 130, 246, 0.4)",
                }}
              >
                {isAllComplete ? "TÜM ADIMLAR HAZIR" : "5 ADIMDA İLK RANDEVU"}
              </span>
            </div>
            {/* Playwright testi ve kullanıcı için semantik referans metni */}
            <p
              className="muted"
              style={{
                margin: "2px 0 0 0",
                fontSize: "12px",
                color: "#94a3b8",
              }}
            >
              Bir randevu ile başlayın. Paneli ilk kez açıyorsanız aşağıdaki yönlendirmeleri izleyerek ilk ekspertiz randevusunu oluşturun:
            </p>
          </div>
        </div>

        <button
          type="button"
          className="secondary"
          style={{
            fontSize: "11px",
            padding: "3px 8px",
            background: "rgba(255, 255, 255, 0.05)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            color: "#e2e8f0",
            cursor: "pointer",
            borderRadius: "5px",
          }}
          aria-label={isExpanded ? "Rehberi daralt" : "Rehberi genişlet"}
          onClick={(e) => {
            e.stopPropagation();
            setIsExpanded((prev) => !prev);
          }}
        >
          {isExpanded ? "▲ Gizle" : "▼ Adımları Göster"}
        </button>
      </div>

      {/* Adımlar Listesi (Genişletildiğinde) */}
      {isExpanded && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 210px), 1fr))",
            gap: "10px",
            marginTop: "12px",
            paddingTop: "10px",
            borderTop: "1px solid rgba(255, 255, 255, 0.08)",
          }}
        >
          {/* 1. ADIM: MODELLERİ HAZIRLA */}
          <div
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: modelsReady ? "rgba(16, 185, 129, 0.08)" : "rgba(30, 41, 59, 0.7)",
              border: modelsReady ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(148, 163, 184, 0.2)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, color: modelsReady ? "#34d399" : "#94a3b8" }}>
                  1. MODELLERİ HAZIRLA
                </span>
                <span>{modelsReady ? "✓ Hazır" : "⏳ Bekleniyor"}</span>
              </div>
              <p style={{ margin: "4px 0 8px 0", fontSize: "11.5px", color: "#cbd5e1" }}>
                {modelsReady
                  ? "Whisper STT, Qwen2.5 LLM ve Leyla TTS aktif."
                  : "Modeller henüz belleğe alınmadı."}
              </p>
            </div>
            {!modelsReady && (
              <button
                type="button"
                className="primary"
                disabled={busy}
                onClick={loadModels}
                style={{ fontSize: "11px", padding: "4px 8px", width: "100%" }}
              >
                {busy ? "Yükleniyor…" : "Modelleri Yükle"}
              </button>
            )}
          </div>

          {/* 2. ADIM: ARAÇ VE HİZMETİ TANIMLA */}
          <div
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: vehiclesReady ? "rgba(16, 185, 129, 0.08)" : "rgba(30, 41, 59, 0.7)",
              border: vehiclesReady ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(148, 163, 184, 0.2)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, color: vehiclesReady ? "#34d399" : "#94a3b8" }}>
                  2. ARAÇ & FİYAT TANIMLA
                </span>
                <span>{vehiclesReady ? `✓ (${vehicles.length})` : "⚠️ Boş"}</span>
              </div>
              <p style={{ margin: "4px 0 8px 0", fontSize: "11.5px", color: "#cbd5e1" }}>
                {vehiclesReady
                  ? `${vehicles[0]?.description} (${vehicles[0]?.plate || "Plakasız"}) kayıtlı.`
                  : "Müşterinin randevu alabilmesi için araç modeli gerekir."}
              </p>
            </div>
            <div style={{ display: "flex", gap: "4px" }}>
              {!vehiclesReady && (
                <button
                  type="button"
                  className="primary"
                  disabled={busy}
                  onClick={addQuickVehicle}
                  style={{ fontSize: "11px", padding: "4px 6px", flex: 1 }}
                  title="Örnek Volkswagen Passat ekler"
                >
                  + Örnek Ekle
                </button>
              )}
              <button
                type="button"
                className="secondary"
                onClick={() => onNavigateToTab("Araçlar ve fiyatlar")}
                style={{ fontSize: "11px", padding: "4px 6px", flex: 1 }}
              >
                Kataloğa Git →
              </button>
            </div>
          </div>

          {/* 3. ADIM: MÜSAİT SAAT EKLE */}
          <div
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: slotsReady ? "rgba(16, 185, 129, 0.08)" : "rgba(30, 41, 59, 0.7)",
              border: slotsReady ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(148, 163, 184, 0.2)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, color: slotsReady ? "#34d399" : "#94a3b8" }}>
                  3. MÜSAİT SAAT EKLE
                </span>
                <span>{slotsReady ? `✓ (${slots.length})` : "⚠️ Boş"}</span>
              </div>
              <p style={{ margin: "4px 0 8px 0", fontSize: "11.5px", color: "#cbd5e1" }}>
                {slotsReady
                  ? `${slots.length} randevu saati takvimde açık.`
                  : "Asistanın önerebilmesi için en az bir slot gerekir."}
              </p>
            </div>
            <div style={{ display: "flex", gap: "4px" }}>
              {!slotsReady && (
                <button
                  type="button"
                  className="primary"
                  disabled={busy}
                  onClick={addQuickSlot}
                  style={{ fontSize: "11px", padding: "4px 6px", flex: 1 }}
                  title="Yarın 10:00 için slot ekler"
                >
                  + Slot Ekle
                </button>
              )}
              <button
                type="button"
                className="secondary"
                onClick={() => onNavigateToTab("Randevular")}
                style={{ fontSize: "11px", padding: "4px 6px", flex: 1 }}
              >
                Takvime Git →
              </button>
            </div>
          </div>

          {/* 4. ADIM: GÖRÜŞMEYİ BAŞLAT */}
          <div
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: conversationReady ? "rgba(16, 185, 129, 0.08)" : "rgba(30, 41, 59, 0.7)",
              border: conversationReady ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(148, 163, 184, 0.2)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, color: conversationReady ? "#34d399" : "#94a3b8" }}>
                  4. GÖRÜŞMEYİ BAŞLAT
                </span>
                <span>{conversationReady ? "✓ Başlatıldı" : "🎙️ Bekliyor"}</span>
              </div>
              <p style={{ margin: "4px 0 8px 0", fontSize: "11.5px", color: "#cbd5e1" }}>
                Mikrofonu açın, adınızı ve araç modelini söyleyerek saati teyit edin.
              </p>
            </div>
            <button
              type="button"
              className="primary"
              onClick={() => {
                onNavigateToTab("Görüşme");
                if (onStartVoice) onStartVoice();
              }}
              style={{ fontSize: "11px", padding: "4px 8px", width: "100%" }}
            >
              🎙️ Görüşmeye Git
            </button>
          </div>

          {/* 5. ADIM: ONAYLANAN RANDEVUYU AÇ */}
          <div
            style={{
              padding: "10px",
              borderRadius: "8px",
              background: appointmentReady ? "rgba(16, 185, 129, 0.15)" : "rgba(30, 41, 59, 0.7)",
              border: appointmentReady ? "1px solid rgba(16, 185, 129, 0.5)" : "1px solid rgba(148, 163, 184, 0.2)",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
          >
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontSize: "11px", fontWeight: 700, color: appointmentReady ? "#34d399" : "#94a3b8" }}>
                  5. RANDEVUYU AÇ
                </span>
                <span>{appointmentReady ? `🎉 (${confirmedAppointments.length})` : "⏳ Bekliyor"}</span>
              </div>
              <p style={{ margin: "4px 0 8px 0", fontSize: "11.5px", color: "#cbd5e1" }}>
                {appointmentReady
                  ? `${confirmedAppointments[0].customer} randevusu takvime işlendi.`
                  : "Onaylanan randevu doğrudan takvimde görünecektir."}
              </p>
            </div>
            <button
              type="button"
              className={appointmentReady ? "primary" : "secondary"}
              onClick={() => onNavigateToTab("Randevular")}
              style={{ fontSize: "11px", padding: "4px 8px", width: "100%" }}
            >
              📅 Takvimde Gör
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
