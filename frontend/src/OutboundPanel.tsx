import { useEffect, useState, useMemo } from "react";

export type OutboundCallItem = {
  id: string;
  appointment_id: string;
  phone: string;
  customer: string;
  call_type: "reminder" | "confirmation";
  status: "queued" | "originating" | "in-progress" | "completed" | "failed" | "cancelled";
  outcome: "pending" | "confirmed" | "cancelled" | "unreachable";
  action_id: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  completed_at: string | null;
};

type Props = {
  api: (path: string, method?: string, body?: unknown) => Promise<any>;
};

export function OutboundPanel({ api }: Props) {
  const [calls, setCalls] = useState<OutboundCallItem[]>([]);
  const [appointments, setAppointments] = useState<any[]>([]);
  const [slots, setSlots] = useState<any[]>([]);
  const [amiStatus, setAmiStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Form State
  const [selectedAppointment, setSelectedAppointment] = useState("");
  const [phone, setPhone] = useState("");
  const [callType, setCallType] = useState("reminder");

  // Filters
  const [statusFilter, setStatusFilter] = useState("all");
  const [outcomeFilter, setOutcomeFilter] = useState("all");

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
    const [cList, aList, sList, ami] = await Promise.all([
      api("outbound/calls"),
      api("appointments"),
      api("slots"),
      api("outbound/ami-status"),
    ]);
    setCalls(cList);
    setAppointments(aList);
    setSlots(sList);
    setAmiStatus(ami);
  }

  useEffect(() => {
    act(refresh);
  }, []);

  async function handleOriginateCall(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedAppointment) {
      setError("Lütfen aranacak bir randevu seçin.");
      return;
    }
    await act(async () => {
      const res = await api("outbound/call", "POST", {
        appointment_id: selectedAppointment,
        phone: phone.trim() || undefined,
        call_type: callType,
      });
      setSuccess(
        `'${res.customer}' (${res.phone}) için Asterisk AMI üzerinden giden arama başlatıldı (ActionID: ${res.action_id}).`
      );
      setSelectedAppointment("");
      setPhone("");
      await refresh();
    });
  }

  async function handleCompleteOutcome(
    callId: string,
    outcome: "confirmed" | "cancelled" | "unreachable"
  ) {
    await act(async () => {
      const res = await api(`outbound/calls/${callId}/complete`, "POST", {
        outcome,
        notes: `Panel operatörü tarafından '${outcome}' olarak sonuçlandırıldı.`,
      });
      setSuccess(
        `Arama kaydı güncellendi. Sonuç: ${res.outcome.toUpperCase()}${
          res.outcome === "cancelled" ? " (Randevu iptal edildi)" : ""
        }.`
      );
      await refresh();
    });
  }

  async function handleCancelCall(callId: string) {
    await act(async () => {
      await api(`outbound/calls/${callId}/cancel`, "POST");
      setSuccess("Arama süreci iptal edildi.");
      await refresh();
    });
  }

  // Active confirmed appointments that can be called
  const confirmedAppointments = useMemo(() => {
    return appointments.filter((a) => a.status === "confirmed" && a.slot_id);
  }, [appointments]);

  // Statistics
  const totalCalls = calls.length;
  const inProgressCalls = calls.filter((c) => c.status === "in-progress" || c.status === "originating").length;
  const confirmedCalls = calls.filter((c) => c.outcome === "confirmed").length;
  const cancelledCalls = calls.filter((c) => c.outcome === "cancelled").length;

  const filteredCalls = useMemo(() => {
    return calls.filter((c) => {
      if (statusFilter !== "all" && c.status !== statusFilter) return false;
      if (outcomeFilter !== "all" && c.outcome !== outcomeFilter) return false;
      return true;
    });
  }, [calls, statusFilter, outcomeFilter]);

  function getSlotTime(slotId: string) {
    const s = slots.find((x) => x.id === slotId);
    if (!s) return "";
    try {
      return new Date(s.starts_at).toLocaleString("tr-TR", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return s.starts_at;
    }
  }

  return (
    <>
      <div className="stats">
        <article>
          <small>Toplam Giden Arama</small>
          <strong>{totalCalls}</strong>
        </article>
        <article>
          <small>Teyit Edilen (Confirmed)</small>
          <strong style={{ color: "#a7f3ce" }}>{confirmedCalls}</strong>
        </article>
        <article>
          <small>İptal Edilen / Aktif</small>
          <strong style={{ color: inProgressCalls > 0 ? "#93c5fd" : "#fca5a5" }}>
            {inProgressCalls} devam eden · {cancelledCalls} iptal
          </strong>
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

      {/* Asterisk AMI Durum Bilgisi */}
      {amiStatus && (
        <div
          className="row"
          style={{
            marginTop: "18px",
            background: "#151c2b",
            padding: "14px 20px",
            borderRadius: "10px",
            border: "1px solid #2a3344",
          }}
        >
          <div>
            <b>ASTERISK MANAGER INTERFACE (AMI)</b>
            <small>
              Sunucu: {amiStatus.ami_host}:{amiStatus.ami_port} · Bağlantı:{" "}
              {amiStatus.connected ? "Hazır (Connected)" : "Çevrimdışı (Offline)"}
            </small>
          </div>
          <span className={"pill " + (amiStatus.connected ? "ok" : "")}>
            {amiStatus.connected ? "● AMI AKTİF" : "○ BAĞLANTI YOK"}
          </span>
        </div>
      )}

      {/* Yeni Giden Arama Başlatma */}
      <section>
        <h2>Yeni Teyit / Hatırlatma Araması Başlat (Originate)</h2>
        <p className="muted">
          Seçilen randevu için Asterisk PBX üzerinden müşteriye otomatik dış arama
          başlatılır. Müşteri telefonu açtığında sesli asistan randevu detaylarını
          hatırlatır, teyit veya iptal yanıtını işleyerek randevu durumunu anında günceller.
        </p>

        <form onSubmit={handleOriginateCall} className="inline" style={{ marginTop: "16px" }}>
          <label style={{ flex: "2 1 240px" }}>
            Teyit Bekleyen Randevu Seç
            <select
              value={selectedAppointment}
              onChange={(e) => {
                const appId = e.target.value;
                setSelectedAppointment(appId);
                const app = appointments.find((a) => a.id === appId);
                if (app && app.customer) {
                  // If customer has phone digits, prefill phone
                  const digits = app.customer.replace(/[^0-9+]/g, "");
                  if (digits.length >= 7) setPhone(digits);
                }
              }}
              required
            >
              <option value="">Randevu Seçin...</option>
              {confirmedAppointments.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.customer} ({getSlotTime(a.slot_id)}) — Ref: {a.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>

          <label style={{ flex: "1 1 180px" }}>
            Telefon Numarası
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="0532 123 45 67"
            />
          </label>

          <label style={{ flex: "1 1 150px" }}>
            Çağrı Türü
            <select value={callType} onChange={(e) => setCallType(e.target.value)}>
              <option value="reminder">Randevu Hatırlatma (reminder)</option>
              <option value="confirmation">Randevu Teyidi (confirmation)</option>
            </select>
          </label>

          <button
            type="submit"
            disabled={loading || !selectedAppointment}
            style={{ padding: "12px 20px" }}
          >
            {loading ? "Aranıyor..." : "Aramayı Başlat 📞"}
          </button>
        </form>
      </section>

      {/* Giden Aramalar Tablosu */}
      <section>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "14px",
            marginBottom: "16px",
          }}
        >
          <h2>Giden Çağrı Kayıtları ({filteredCalls.length})</h2>
          <button
            type="button"
            className="secondary"
            onClick={() => act(refresh)}
            disabled={loading}
            style={{ fontSize: "12px", padding: "8px 14px" }}
          >
            Yenile ↻
          </button>
        </div>

        {/* Filtre Barı */}
        <div
          className="inline"
          style={{
            background: "#0e1522",
            padding: "14px",
            borderRadius: "10px",
            border: "1px solid #2a3344",
            marginBottom: "20px",
          }}
        >
          <label style={{ flex: "1 1 140px" }}>
            Çağrı Durumu
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">Tüm Durumlar ({calls.length})</option>
              <option value="in-progress">Devam Eden (in-progress)</option>
              <option value="completed">Tamamlanan (completed)</option>
              <option value="failed">Başarısız (failed)</option>
              <option value="cancelled">İptal Edilen (cancelled)</option>
            </select>
          </label>

          <label style={{ flex: "1 1 140px" }}>
            Çağrı Sonucu (Outcome)
            <select
              value={outcomeFilter}
              onChange={(e) => setOutcomeFilter(e.target.value)}
            >
              <option value="all">Tüm Sonuçlar</option>
              <option value="confirmed">Teyit Edildi (confirmed)</option>
              <option value="cancelled">Randevu İptal (cancelled)</option>
              <option value="unreachable">Ulaşılamadı (unreachable)</option>
              <option value="pending">Bekliyor (pending)</option>
            </select>
          </label>
        </div>

        {/* Tablo */}
        <div style={{ overflowX: "auto" }}>
          <div className="table-wrap"><table className="lexicon-table">
            <thead>
              <tr>
                <th>Müşteri</th>
                <th>Telefon</th>
                <th>Tür</th>
                <th>Durum</th>
                <th>Sonuç</th>
                <th>Tarih</th>
                <th style={{ textAlign: "right" }}>İşlemler</th>
              </tr>
            </thead>
            <tbody>
              {filteredCalls.map((item) => (
                <tr key={item.id}>
                  <td style={{ fontWeight: 600 }}>{item.customer}</td>
                  <td>{item.phone}</td>
                  <td>
                    <span className="badge-cat">{item.call_type}</span>
                  </td>
                  <td>
                    <span
                      style={{
                        padding: "3px 8px",
                        borderRadius: "10px",
                        fontSize: "11px",
                        background:
                          item.status === "completed"
                            ? "#14532d"
                            : item.status === "failed"
                              ? "#451a03"
                              : "#1e3a8a",
                        color:
                          item.status === "completed"
                            ? "#86efac"
                            : item.status === "failed"
                              ? "#fdba74"
                              : "#bfdbfe",
                      }}
                    >
                      {item.status}
                    </span>
                  </td>
                  <td>
                    <span
                      className={
                        item.outcome === "confirmed"
                          ? "badge-custom"
                          : item.outcome === "cancelled"
                            ? "danger"
                            : "badge-override"
                      }
                      style={{ padding: "3px 8px", borderRadius: "10px" }}
                    >
                      {item.outcome === "confirmed"
                        ? "Teyit Edildi"
                        : item.outcome === "cancelled"
                          ? "İptal Edildi"
                          : item.outcome === "unreachable"
                            ? "Ulaşılamadı"
                            : "Bekliyor"}
                    </span>
                  </td>
                  <td style={{ fontSize: "12px", whiteSpace: "nowrap" }}>
                    {new Date(item.created_at).toLocaleString("tr-TR", {
                      day: "2-digit",
                      month: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {item.status === "in-progress" && (
                      <>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => handleCompleteOutcome(item.id, "confirmed")}
                          style={{
                            padding: "6px 10px",
                            fontSize: "11px",
                            marginRight: "6px",
                          }}
                        >
                          Teyit
                        </button>
                        <button
                          type="button"
                          className="danger"
                          onClick={() => handleCompleteOutcome(item.id, "cancelled")}
                          style={{
                            padding: "6px 10px",
                            fontSize: "11px",
                            marginRight: "6px",
                          }}
                        >
                          İptal
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => handleCancelCall(item.id)}
                          style={{ padding: "6px 10px", fontSize: "11px" }}
                        >
                          Durdur
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {!filteredCalls.length && (
                <tr>
                  <td
                    colSpan={7}
                    style={{
                      textAlign: "center",
                      padding: "30px",
                      color: "#93a0b5",
                    }}
                  >
                    Henüz giden arama kaydı bulunamadı.
                  </td>
                </tr>
              )}
            </tbody>
          </table></div>
        </div>
      </section>
    </>
  );
}

