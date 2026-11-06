/*
 * ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
 * Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlıdır.
 */

import { useEffect, useState, useMemo } from "react";
import { RawApiFn, errorMessage } from "./ui";

export type NotificationItem = {
  id: string;
  appointment_id: string;
  recipient_type: "customer" | "corporate";
  recipient: string;
  channel: "sms" | "whatsapp";
  message: string;
  status: "pending" | "sent" | "simulated" | "failed";
  idempotency_key: string;
  attempts: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
};

export type WhatsAppInboundItem = {
  id: string;
  from_phone: string;
  customer_name: string;
  message_type: "text" | "voice";
  raw_content: string;
  transcription: string;
  extracted_intent: string;
  extracted_time: string | null;
  appointment_id: string | null;
  reply_text: string;
  outbound_calls_cancelled: number;
  processed: boolean;
  created_at: string;
};

import type { Props } from "./api";

export function NotificationPanel({ api, rawApi }: Props) {
  const [activeTab, setActiveTab] = useState<"inbound" | "outbox">("inbound");
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [inboundMessages, setInboundMessages] = useState<WhatsAppInboundItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Inbound Simulator Form
  const [simPhone, setSimPhone] = useState("");
  const [simText, setSimText] = useState("");
  const [simVoiceFile, setSimVoiceFile] = useState<File | null>(null);
  const [simulating, setSimulating] = useState(false);

  // Outbox Filters
  const [statusFilter, setStatusFilter] = useState("all");
  const [channelFilter, setChannelFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");

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
    try {
      const [outboxList, inboundList] = await Promise.all([
        api("notifications"),
        api("whatsapp/messages"),
      ]);
      setNotifications(Array.isArray(outboxList) ? outboxList : []);
      setInboundMessages(Array.isArray(inboundList) ? inboundList : []);
    } catch (err: any) {
      setError("Bildirim verisi yüklenemedi: " + (err?.message || String(err)));
    }
  }

  useEffect(() => {
    act(refresh);
  }, []);

  async function handleDispatch() {
    await act(async () => {
      const res = await api("notifications/dispatch", "POST");
      setSuccess(
        `${res.dispatched_count} adet bekleyen bildirim başarıyla iletildi.`
      );
      await refresh();
    });
  }

  async function handleRetry(item: NotificationItem) {
    await act(async () => {
      const res = await api(`notifications/${item.id}/retry`, "POST");
      setSuccess(
        `'${item.recipient}' alıcısına bildirim yeniden gönderildi (Durum: ${res.status}).`
      );
      await refresh();
    });
  }

  async function handleSimulateText() {
    if (!simPhone.trim() || !simText.trim()) return;
    setSimulating(true);
    setError("");
    setSuccess("");
    try {
      const res = await api("whatsapp/inbound", "POST", {
        phone: simPhone,
        text: simText,
      });
      const cancelInfo =
        res.cancelled_outbound_calls_count > 0
          ? ` (${res.cancelled_outbound_calls_count} otomatik arama iptal edildi)`
          : "";
      setSuccess(
        `WhatsApp mesajı işlendi: Niyet='${res.intent}'${
          res.extracted_time ? `, Saat='${res.extracted_time}'` : ""
        }${cancelInfo}. Otomatik yanıt outbox'a eklendi.`
      );
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSimulating(false);
    }
  }

  async function handleSimulateVoice() {
    if (!simVoiceFile || !simPhone.trim()) return;
    setSimulating(true);
    setError("");
    setSuccess("");
    try {
      const formData = new FormData();
      formData.append("phone", simPhone);
      formData.append("audio_file", simVoiceFile);

      const resp = await rawApi("whatsapp/inbound-voice", "POST", formData);
      const res = await resp.json();
      setSuccess(
        `Ses Faster-Whisper ile çözümlendi: "${res.transcript}" ➔ Niyet='${res.intent}'.`
      );
      setSimVoiceFile(null);
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSimulating(false);
    }
  }

  // Statistics
  const totalOutbox = notifications.length;
  const sentCount = notifications.filter((n) => n.status === "sent").length;
  const pendingCount = notifications.filter((n) => n.status === "pending").length;
  const failedCount = notifications.filter((n) => n.status === "failed").length;

  const totalInbound = inboundMessages.length;
  const timeChangeCount = inboundMessages.filter(
    (m) => m.extracted_intent === "time_change"
  ).length;
  const cancelCount = inboundMessages.filter(
    (m) => m.extracted_intent === "cancel" || m.extracted_intent === "cancellation"
  ).length;

  const filteredOutbox = useMemo(() => {
    return notifications.filter((n) => {
      if (statusFilter !== "all" && n.status !== statusFilter) return false;
      if (channelFilter !== "all" && n.channel !== channelFilter) return false;
      if (typeFilter !== "all" && n.recipient_type !== typeFilter) return false;
      return true;
    });
  }, [notifications, statusFilter, channelFilter, typeFilter]);

  function formatDate(iso: string | null) {
    if (!iso) return "-";
    try {
      return new Date(iso).toLocaleString("tr-TR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return iso;
    }
  }

  function getIntentBadge(intent: string) {
    switch (intent) {
      case "time_change":
        return { label: "Saat Değişimi", bg: "#1e3a8a", color: "#bfdbfe" };
      case "cancellation":
        return { label: "İptal Talebi", bg: "#7f1d1d", color: "#fecaca" };
      case "confirmation":
        return { label: "Onay / Geliyorum", bg: "#14532d", color: "#bbf7d0" };
      case "location_inquiry":
        return { label: "Konum / Adres", bg: "#78350f", color: "#fde68a" };
      default:
        return { label: "Genel Soru", bg: "#374151", color: "#e5e7eb" };
    }
  }

  return (
    <>
      {/* İstatistik Kartları */}
      <div className="stats">
        <article>
          <small>Gelen WhatsApp Mesajları</small>
          <strong>{totalInbound}</strong>
          <span style={{ fontSize: "11px", color: "#93a0b5", marginTop: "2px" }}>
            {timeChangeCount} saat güncelleme · {cancelCount} iptal
          </span>
        </article>
        <article>
          <small>Outbox Toplam Bildirim</small>
          <strong>{totalOutbox}</strong>
          <span style={{ fontSize: "11px", color: "#a7f3ce", marginTop: "2px" }}>
            {sentCount} iletildi
          </span>
        </article>
        <article>
          <small>Outbox Bekleyen / Hatalı</small>
          <strong style={{ color: failedCount > 0 ? "#fca5a5" : "#fef08a" }}>
            {pendingCount} bekleyen · {failedCount} hatalı
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

      {/* Üst Sekmeler */}
      <div
        style={{
          display: "flex",
          gap: "10px",
          marginTop: "24px",
          marginBottom: "16px",
          borderBottom: "1px solid #2a3344",
          paddingBottom: "8px",
        }}
      >
        <button
          type="button"
          onClick={() => setActiveTab("inbound")}
          style={{
            background: activeTab === "inbound" ? "#2563eb" : "#1f2937",
            color: "#fff",
            padding: "8px 16px",
            fontSize: "13px",
            fontWeight: activeTab === "inbound" ? 600 : 400,
          }}
        >
          📥 Çift Yönlü WhatsApp Gelen & Simülatör ({totalInbound})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("outbox")}
          style={{
            background: activeTab === "outbox" ? "#2563eb" : "#1f2937",
            color: "#fff",
            padding: "8px 16px",
            fontSize: "13px",
            fontWeight: activeTab === "outbox" ? 600 : 400,
          }}
        >
          📤 Outbox Bildirim Kuyruğu (M10 & GPS Pini) ({totalOutbox})
        </button>
      </div>

      {activeTab === "inbound" ? (
        <section>
          {/* WhatsApp Simülatör Kartı */}
          <div
            style={{
              background: "#0c121e",
              border: "1px solid #1e293b",
              borderRadius: "12px",
              padding: "20px",
              marginBottom: "24px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "16px", color: "#38bdf8" }}>
                  📱 Çift Yönlü WhatsApp & Sesli Not Simülatörü
                </h3>
                <p className="muted" style={{ margin: "4px 0 0", fontSize: "12px" }}>
                  Müşteri WhatsApp'tan yazdığında ("Saati 16:00 yapalım") veya sesli mesaj attığında
                  randevu anında güncellenir ve bekleyen giden arama tekrarları (Auto-Retry) otomatik iptal edilir.
                </p>
              </div>
              <span
                style={{
                  background: "#14532d",
                  color: "#86efac",
                  padding: "4px 10px",
                  borderRadius: "12px",
                  fontSize: "11px",
                  fontWeight: 600,
                }}
              >
                Simülasyon
              </span>
            </div>

            <div className="grid-1-2" style={{ gap: "16px" }}>
              <div>
                <label style={{ fontSize: "12px", color: "#cbd5e1" }}>
                  Müşteri Telefon Numarası
                  <input
                    type="text"
                    value={simPhone}
                    onChange={(e) => setSimPhone(e.target.value)}
                    placeholder="+905551234567"
                    style={{ marginTop: "6px" }}
                  />
                </label>
                <button
                  type="button"
                  className="secondary"
                  style={{ fontSize: "11px", padding: "6px 10px", marginTop: "8px" }}
                  onClick={() => {
                    setSimPhone("+905551234567");
                    setSimText("Saati 16:00 yapalım lütfen");
                  }}
                >
                  Örnek doldur
                </button>

                {/* Hızlı Senaryo Butonları */}
                <div style={{ marginTop: "12px" }}>
                  <small style={{ color: "#94a3b8", display: "block", marginBottom: "6px" }}>
                    Hızlı Test Cümleleri:
                  </small>
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    <button
                      type="button"
                      className="secondary"
                      style={{ fontSize: "11px", padding: "6px 10px", textAlign: "left" }}
                      onClick={() => setSimText("Saati 16:00 yapalım lütfen, işim uzadı.")}
                    >
                      🕒 "Saati 16:00 yapalım"
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      style={{ fontSize: "11px", padding: "6px 10px", textAlign: "left" }}
                      onClick={() => setSimText("Bugünkü ekspertiz randevumu iptal etmek istiyorum.")}
                    >
                      ❌ "Randevumu iptal edin"
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      style={{ fontSize: "11px", padding: "6px 10px", textAlign: "left" }}
                      onClick={() => setSimText("Evet onaylıyorum, saatinde orada olacağım.")}
                    >
                      ✅ "Onaylıyorum, geliyorum"
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      style={{ fontSize: "11px", padding: "6px 10px", textAlign: "left" }}
                      onClick={() => setSimText("Şubenizin açık adresi nedir, konum atar mısınız?")}
                    >
                      📍 "Konum atar mısınız?"
                    </button>
                  </div>
                </div>
              </div>

              <div>
                <label style={{ fontSize: "12px", color: "#cbd5e1" }}>
                  WhatsApp Yazılı Mesajı
                  <textarea
                    rows={3}
                    value={simText}
                    onChange={(e) => setSimText(e.target.value)}
                    placeholder="Müşterinin yazacağı mesaj..."
                    style={{ marginTop: "6px", width: "100%", fontSize: "13px" }}
                  />
                </label>

                <div style={{ display: "flex", gap: "10px", marginTop: "10px" }}>
                  <button
                    type="button"
                    onClick={handleSimulateText}
                    disabled={simulating || !simText.trim()}
                    style={{ fontSize: "12px", padding: "8px 16px" }}
                  >
                    {simulating ? "İşleniyor..." : "Yazılı Mesajı Simüle Et ➔"}
                  </button>
                </div>

                <hr style={{ borderColor: "#1e293b", margin: "16px 0" }} />

                {/* Sesli Not Bölümü */}
                <div>
                  <label style={{ fontSize: "12px", color: "#cbd5e1", display: "block" }}>
                    🎙️ WhatsApp Sesli Not Simülatörü (Faster-Whisper STT)
                    <input
                      type="file"
                      accept="audio/*,.wav,.mp3,.ogg,.m4a"
                      onChange={(e) => setSimVoiceFile(e.target.files?.[0] || null)}
                      style={{ marginTop: "6px", display: "block", fontSize: "12px" }}
                    />
                  </label>
                  {simVoiceFile && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={handleSimulateVoice}
                      disabled={simulating}
                      style={{ marginTop: "8px", fontSize: "12px", padding: "6px 14px" }}
                    >
                      {simulating ? "STT Çözümleniyor..." : `"${simVoiceFile.name}" Sesini Çözümle & İşle ➔`}
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Gelen Mesajlar Tablosu */}
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <h3 style={{ margin: 0 }}>Gelen WhatsApp Mesajları ({inboundMessages.length})</h3>
              <button
                type="button"
                className="secondary"
                onClick={() => act(refresh)}
                style={{ fontSize: "12px", padding: "6px 12px" }}
              >
                Yenile ↻
              </button>
            </div>

            <div style={{ overflowX: "auto" }}>
              <div className="table-wrap"><table className="lexicon-table">
                <thead>
                  <tr>
                    <th>Gönderen</th>
                    <th>Tip</th>
                    <th>Mesaj / Çözümlenen Ses</th>
                    <th>Niyet (Intent)</th>
                    <th>Çıkarılan Saat</th>
                    <th>Oto-Arama İptal</th>
                    <th>Durum</th>
                    <th>Tarih</th>
                  </tr>
                </thead>
                <tbody>
                  {inboundMessages.map((msg) => {
                    const badge = getIntentBadge(msg.extracted_intent);
                    const displayText =
                      msg.message_type === "voice"
                        ? msg.transcription || msg.raw_content
                        : msg.raw_content;
                    return (
                      <tr key={msg.id}>
                        <td style={{ fontWeight: 600, whiteSpace: "nowrap" }}>
                          {msg.from_phone}
                        </td>
                        <td>
                          <span
                            style={{
                              padding: "2px 6px",
                              borderRadius: "6px",
                              fontSize: "10px",
                              fontWeight: 600,
                              background: msg.message_type === "voice" ? "#581c87" : "#1e293b",
                              color: msg.message_type === "voice" ? "#d8b4fe" : "#94a3b8",
                            }}
                          >
                            {msg.message_type === "voice" ? "🎙️ Sesli Not" : "💬 Metin"}
                          </span>
                        </td>
                        <td style={{ maxWidth: "340px", fontSize: "12px" }}>
                          {displayText}
                          {msg.reply_text && (
                            <div style={{ color: "#38bdf8", fontSize: "11px", marginTop: "3px" }}>
                              ↳ Yanıt: {msg.reply_text.slice(0, 80)}...
                            </div>
                          )}
                        </td>
                        <td>
                          <span
                            style={{
                              padding: "3px 8px",
                              borderRadius: "8px",
                              fontSize: "11px",
                              fontWeight: 600,
                              background: badge.bg,
                              color: badge.color,
                            }}
                          >
                            {badge.label}
                          </span>
                        </td>
                        <td style={{ fontWeight: 600, color: "#38bdf8" }}>
                          {msg.extracted_time || "-"}
                        </td>
                        <td>
                          {msg.outbound_calls_cancelled > 0 ? (
                            <span
                              style={{
                                padding: "2px 6px",
                                borderRadius: "6px",
                                fontSize: "11px",
                                background: "#450a0a",
                                color: "#fca5a5",
                                fontWeight: 600,
                              }}
                            >
                              {msg.outbound_calls_cancelled} Arama İptal
                            </span>
                          ) : (
                            <span style={{ color: "#64748b", fontSize: "11px" }}>Yok</span>
                          )}
                        </td>
                        <td>
                          <span
                            className={msg.processed ? "badge-custom" : "danger"}
                            style={{ padding: "3px 8px", borderRadius: "10px", fontSize: "11px" }}
                          >
                            {msg.processed ? "İşlendi" : "Hata"}
                          </span>
                        </td>
                        <td style={{ fontSize: "11px", whiteSpace: "nowrap" }}>
                          {formatDate(msg.created_at)}
                        </td>
                      </tr>
                    );
                  })}
                  {!inboundMessages.length && (
                    <tr>
                      <td colSpan={8} style={{ textAlign: "center", padding: "24px", color: "#93a0b5" }}>
                        Henüz gelen WhatsApp mesajı veya sesli not bulunmuyor. Yukarıdaki simülatörle test edebilirsiniz.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table></div>
            </div>
          </div>
        </section>
      ) : (
        <section>
          {/* M10 Outbox Bölümü */}
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
            <div>
              <h2 style={{ margin: 0, fontSize: "18px" }}>
                M10 Outbox Bildirim Kuyruğu (SMS / WhatsApp & Şube GPS Pini)
              </h2>
              <p className="muted" style={{ margin: "4px 0 0", fontSize: "13px" }}>
                Randevu tamamlandığında veya saat güncellendiğinde SMS ve WhatsApp mesajları GPS konum pini
                (Google Maps linki) ile birlikte güvenli (at-least-once) şekilde kuyruklanır.
              </p>
            </div>
            <button
              type="button"
              onClick={handleDispatch}
              disabled={loading || pendingCount === 0}
              style={{ fontSize: "13px", padding: "10px 18px" }}
            >
              {loading ? "Sevk ediliyor..." : "Bekleyenleri Gönder ➔"}
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
              Kanal Filtresi
              <select
                value={channelFilter}
                onChange={(e) => setChannelFilter(e.target.value)}
              >
                <option value="all">Tüm Kanallar ({notifications.length})</option>
                <option value="sms">SMS</option>
                <option value="whatsapp">WhatsApp</option>
              </select>
            </label>

            <label style={{ flex: "1 1 140px" }}>
              Alıcı Tipi
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
              >
                <option value="all">Tüm Alıcılar</option>
                <option value="customer">Müşteri (Bireysel)</option>
                <option value="corporate">Galeri (Kurumsal Cari)</option>
              </select>
            </label>

            <label style={{ flex: "1 1 140px" }}>
              Durum
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="all">Tüm Durumlar</option>
                <option value="pending">Bekleyen (pending)</option>
                <option value="sent">İletildi (sent)</option>
                <option value="failed">Hatalı (failed)</option>
              </select>
            </label>
          </div>

          {/* Outbox Tablosu */}
          <div style={{ overflowX: "auto" }}>
            <div className="table-wrap"><table className="lexicon-table">
              <thead>
                <tr>
                  <th>Kanal</th>
                  <th>Alıcı Tipi</th>
                  <th>Alıcı</th>
                  <th>Onay & Konum Metni</th>
                  <th>Durum</th>
                  <th>Tarih</th>
                  <th style={{ textAlign: "right" }}>İşlem</th>
                </tr>
              </thead>
              <tbody>
                {filteredOutbox.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <span
                        style={{
                          padding: "3px 8px",
                          borderRadius: "10px",
                          fontSize: "11px",
                          fontWeight: 600,
                          background:
                            item.channel === "whatsapp" ? "#14532d" : "#1e3a8a",
                          color:
                            item.channel === "whatsapp" ? "#86efac" : "#bfdbfe",
                        }}
                      >
                        {item.channel === "whatsapp" ? "WhatsApp" : "SMS"}
                      </span>
                    </td>
                    <td>
                      <span
                        style={{
                          padding: "3px 8px",
                          borderRadius: "10px",
                          fontSize: "11px",
                          background:
                            item.recipient_type === "corporate"
                              ? "#3b0764"
                              : "#1f2937",
                          color:
                            item.recipient_type === "corporate"
                              ? "#e9d5ff"
                              : "#d1d5db",
                        }}
                      >
                        {item.recipient_type === "corporate"
                          ? "Galeri"
                          : "Müşteri"}
                      </span>
                    </td>
                    <td style={{ fontWeight: 600, whiteSpace: "nowrap" }}>
                      {item.recipient}
                    </td>
                    <td style={{ maxWidth: "420px", fontSize: "12px" }}>
                      {item.message}
                      {item.last_error && (
                        <div
                          style={{
                            color: "#fca5a5",
                            fontSize: "11px",
                            marginTop: "4px",
                          }}
                        >
                          Hata: {item.last_error}
                        </div>
                      )}
                    </td>
                    <td>
                      <span
                        className={
                          item.status === "sent"
                            ? "badge-custom"
                            : item.status === "failed"
                              ? "danger"
                              : "badge-override"
                        }
                        style={{ padding: "3px 8px", borderRadius: "10px" }}
                      >
                        {item.status === "sent"
                          ? "İletildi"
                          : item.status === "simulated"
                            ? "gönderilmedi (sağlayıcı yok)"
                            : item.status === "failed"
                              ? "Başarısız"
                              : "Bekliyor"}
                      </span>
                      {item.attempts > 1 && (
                        <small style={{ marginTop: "2px" }}>
                          {item.attempts} deneme
                        </small>
                      )}
                    </td>
                    <td style={{ fontSize: "12px", whiteSpace: "nowrap" }}>
                      <div>Oluşturma: {formatDate(item.created_at)}</div>
                      {item.sent_at && (
                        <small style={{ color: "#a7f3ce" }}>
                          İletim: {formatDate(item.sent_at)}
                        </small>
                      )}
                    </td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      {item.status !== "sent" && (
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => handleRetry(item)}
                          style={{ padding: "6px 12px", fontSize: "12px" }}
                        >
                          Tekrar Gönder
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {!filteredOutbox.length && (
                  <tr>
                    <td
                      colSpan={7}
                      style={{
                        textAlign: "center",
                        padding: "30px",
                        color: "#93a0b5",
                      }}
                    >
                      Henüz outbox bildirim kaydı bulunamadı.
                    </td>
                  </tr>
                )}
              </tbody>
            </table></div>
          </div>
        </section>
      )}
    </>
  );
}
