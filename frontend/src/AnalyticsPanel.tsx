import { useEffect, useState, useMemo } from "react";
import { formatMetrics, useEscape } from "./ui";

// Ölçüm yoksa API null döner; ekranda 0 yerine "—" gösterilir.
type Measured = number | null;

const fmt = (value: Measured | undefined, unit = "") =>
  value === null || value === undefined ? "—" : `${value}${unit}`;

type LatencyStats = {
  avg: Measured;
  min?: Measured;
  max?: Measured;
  p50: Measured;
  p95: Measured;
  sample_count: number;
};

type LLMStats = {
  avg_total: Measured;
  p50_total: Measured;
  p95_total: Measured;
  avg_first_token: Measured;
  p50_first_token: Measured;
  p95_first_token: Measured;
  sample_count: number;
};

type AnalyticsData = {
  summary: {
    total_conversations: number;
    completed_conversations: number;
    follow_up_conversations: number;
    resolved_conversations: number;
    active_conversations: number;
    total_appointments: number;
    confirmed_appointments: number;
    conversion_rate_pct: number;
    avg_turns_per_conversation: Measured;
    avg_duration_seconds: Measured;
    stt_clarity_rate_pct: Measured;
    stt_unclear_count: number;
    channels: Record<string, number>;
  };
  latency_kpis: {
    first_audio_ms: LatencyStats;
    llm_ms: LLMStats;
    stt_ms: LatencyStats;
    tts_ms: {
      avg: Measured;
      avg_rtf: Measured;
      sample_count: number;
    };
    barge_in_count: number;
  };
  daily_trend: Array<{
    date: string;
    appointments: number;
    conversations: number;
  }>;
  hourly_distribution: number[];
};

type FollowUpItem = {
  id: string;
  channel: string;
  status: "active" | "completed" | "follow_up" | "resolved";
  operator_notes: string;
  resolved_at: string | null;
  created_at: string;
  turn_count: number;
  duration_seconds: number;
  last_user_text: string;
  last_assistant_text: string;
};

type TurnItem = {
  id: string;
  conversation_id: string;
  role: string;
  text: string;
  metrics: string;
  created_at: string;
};

type Props = {
  api: (path: string, method?: string, body?: unknown) => Promise<any>;
};

export function AnalyticsPanel({ api }: Props) {
  const [activeTab, setActiveTab] = useState<"dashboard" | "follow_ups">("dashboard");
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [followUps, setFollowUps] = useState<FollowUpItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Follow-up status filter
  const [statusFilter, setStatusFilter] = useState<string>("follow_up");

  // Resolve modal state
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolveNotes, setResolveNotes] = useState("");

  // Transcript view modal
  const [inspectConvId, setInspectConvId] = useState<string | null>(null);
  const [inspectTurns, setInspectTurns] = useState<TurnItem[]>([]);
  const [loadingTurns, setLoadingTurns] = useState(false);

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

  useEscape(() => setResolvingId(null), !!resolvingId);
  useEscape(() => setInspectConvId(null), !!inspectConvId);

  async function refresh() {
    const [overviewRes, followUpsRes] = await Promise.all([
      api("analytics/overview"),
      api(`analytics/follow-ups?status=${statusFilter}`),
    ]);
    setData(overviewRes);
    setFollowUps(followUpsRes);
  }

  useEffect(() => {
    act(refresh);
  }, [statusFilter]);

  async function handleResolve(e: React.FormEvent) {
    e.preventDefault();
    if (!resolvingId) return;

    await act(async () => {
      await api(`analytics/conversations/${resolvingId}/resolve`, "POST", {
        notes: resolveNotes,
      });
      setSuccess("Görüşme operatör tarafından 'Sonuçlandı' olarak güncellendi.");
      setResolvingId(null);
      setResolveNotes("");
      await refresh();
    });
  }

  async function handleReopen(id: string) {
    await act(async () => {
      await api(`analytics/conversations/${id}/reopen`, "POST");
      setSuccess("Görüşme yeniden takip durumuna (follow_up) alındı.");
      await refresh();
    });
  }

  async function handleOpenInspect(id: string) {
    setInspectConvId(id);
    setLoadingTurns(true);
    try {
      const turns = await api("conversations/" + id);
      setInspectTurns(Array.isArray(turns) ? turns : []);
    } catch (e: any) {
      setError("Tur detayları yüklenemedi: " + (e?.message || String(e)));
    } finally {
      setLoadingTurns(false);
    }
  }

  // Render SVG Trend Chart
  const trendMax = useMemo(() => {
    if (!data?.daily_trend) return 10;
    const maxVal = Math.max(
      ...data.daily_trend.map((d) => Math.max(d.appointments, d.conversations)),
      5
    );
    return Math.ceil(maxVal * 1.2);
  }, [data?.daily_trend]);

  return (
    <div className="section-container">
      {/* Alert Messages */}
      {error && <div className="alert-box error">{error}</div>}
      {success && <div className="alert-box success">{success}</div>}

      {/* Panel View Toggle */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1.2rem",
          borderBottom: "1px solid #334155",
          paddingBottom: "0.5rem",
        }}
      >
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            className={activeTab === "dashboard" ? "selected" : "secondary"}
            onClick={() => setActiveTab("dashboard")}
            style={{ padding: "0.5rem 1.2rem" }}
          >
            📊 KPI & Performans Göstergeleri
          </button>
          <button
            className={activeTab === "follow_ups" ? "selected" : "secondary"}
            onClick={() => setActiveTab("follow_ups")}
            style={{ padding: "0.5rem 1.2rem" }}
          >
            ⚠️ Takip Gerektiren Görüşmeler{" "}
            {data?.summary.follow_up_conversations ? (
              <span
                style={{
                  background: "#ca8a04",
                  color: "#fff",
                  padding: "2px 7px",
                  borderRadius: "10px",
                  fontSize: "11px",
                  marginLeft: "6px",
                }}
              >
                {data.summary.follow_up_conversations}
              </span>
            ) : null}
          </button>
        </div>

        <button
          onClick={() => act(refresh)}
          disabled={loading}
          style={{ padding: "0.45rem 1rem", fontSize: "0.85rem" }}
        >
          {loading ? "Yenileniyor..." : "🔄 Verileri Güncelle"}
        </button>
      </div>

      {/* TAB 1: EXECUTIVE KPI DASHBOARD */}
      {activeTab === "dashboard" && data && (
        <>
          {/* Executive Summary Cards */}
          <div
            className="stats kpi-grid-4"
            style={{ marginBottom: "1.5rem" }}
          >
            <div className="card" style={{ borderLeft: "4px solid #16a34a" }}>
              <small>🎯 DÖNÜŞÜM ORANI (CONVERSION)</small>
              <h2 style={{ color: "#4ade80", margin: "6px 0" }}>
                {data.summary.total_conversations ? `%${data.summary.conversion_rate_pct}` : "—"}
              </h2>
              <small>
                {data.summary.confirmed_appointments} Randevu /{" "}
                {data.summary.total_conversations} Görüşme
              </small>
            </div>

            <div className="card" style={{ borderLeft: "4px solid #0284c7" }}>
              <small>📞 TOPLAM GÖRÜŞME & KANAL</small>
              <h2 style={{ color: "#38bdf8", margin: "6px 0" }}>
                {data.summary.total_conversations}
              </h2>
              <small>
                Web: {data.summary.channels.web || 0} | Tel:{" "}
                {data.summary.channels.phone || 0} | Dış:{" "}
                {data.summary.channels.outbound || 0}
              </small>
            </div>

            <div className="card" style={{ borderLeft: "4px solid #ca8a04" }}>
              <small>⚠️ OPERATÖR TAKİBİ BEKLEYEN</small>
              <h2 style={{ color: "#facc15", margin: "6px 0" }}>
                {data.summary.follow_up_conversations}
              </h2>
              <small>
                Çözümlenen: {data.summary.resolved_conversations} | Tamamlanan:{" "}
                {data.summary.completed_conversations}
              </small>
            </div>

            <div className="card" style={{ borderLeft: "4px solid #a855f7" }}>
              <small>🎙️ STT DOĞRULUK & NETLİK</small>
              <h2 style={{ color: "#c084fc", margin: "6px 0" }}>
                {data.summary.stt_clarity_rate_pct === null
                  ? "—"
                  : `%${data.summary.stt_clarity_rate_pct}`}
              </h2>
              <small>
                Ort. Süre: {fmt(data.summary.avg_duration_seconds, "s")} | Ort. Tur:{" "}
                {fmt(data.summary.avg_turns_per_conversation)}
              </small>
            </div>
          </div>

          {/* LATENCY & MODEL PERFORMANCE KPIS */}
          <section style={{ marginBottom: "1.5rem" }}>
            <h2>⚡ Ses, STT & LLM Yanıt Süreleri (Latency KPIs)</h2>
            <div className="kpi-grid-3" style={{ gap: "1rem", marginTop: "1rem" }}>
              {/* First Audio MS */}
              <div
                style={{
                  background: "#1e293b",
                  padding: "1rem",
                  borderRadius: "8px",
                  border: "1px solid #334155",
                }}
              >
                <h4 style={{ margin: "0 0 0.5rem 0", color: "#38bdf8" }}>
                  🔊 İlk Ses Gecikmesi (First Audio)
                </h4>
                <div style={{ fontSize: "1.4rem", fontWeight: "bold", margin: "0.3rem 0" }}>
                  {fmt(data.latency_kpis.first_audio_ms.p50, " ms")}{" "}
                  <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>(p50 Medyan)</span>
                </div>
                <div className="grid-2" style={{ gap: "0.5rem", fontSize: "0.82rem", marginTop: "0.6rem" }}>
                  <div>Ortalama: <b>{fmt(data.latency_kpis.first_audio_ms.avg, " ms")}</b></div>
                  <div>95. Yüzdelik (p95): <b style={{ color: "#facc15" }}>{fmt(data.latency_kpis.first_audio_ms.p95, " ms")}</b></div>
                  <div>Min: <b>{fmt(data.latency_kpis.first_audio_ms.min, " ms")}</b></div>
                  <div>Örnek Sayısı: <b>{data.latency_kpis.first_audio_ms.sample_count}</b></div>
                </div>
              </div>

              {/* LLM Response Times */}
              <div
                style={{
                  background: "#1e293b",
                  padding: "1rem",
                  borderRadius: "8px",
                  border: "1px solid #334155",
                }}
              >
                <h4 style={{ margin: "0 0 0.5rem 0", color: "#4ade80" }}>
                  🧠 LLM Çıkarım Süreleri (Qwen2.5)
                </h4>
                <div style={{ fontSize: "1.4rem", fontWeight: "bold", margin: "0.3rem 0" }}>
                  {fmt(data.latency_kpis.llm_ms.p50_total, " ms")}{" "}
                  <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>(Toplam p50)</span>
                </div>
                <div className="grid-2" style={{ gap: "0.5rem", fontSize: "0.82rem", marginTop: "0.6rem" }}>
                  <div>İlk Token (TTFT p50): <b>{fmt(data.latency_kpis.llm_ms.p50_first_token, " ms")}</b></div>
                  <div>İlk Token p95: <b style={{ color: "#facc15" }}>{fmt(data.latency_kpis.llm_ms.p95_first_token, " ms")}</b></div>
                  <div>Toplam p95: <b style={{ color: "#f87171" }}>{fmt(data.latency_kpis.llm_ms.p95_total, " ms")}</b></div>
                  <div>Örnek Sayısı: <b>{data.latency_kpis.llm_ms.sample_count}</b></div>
                </div>
              </div>

              {/* STT & TTS & Barge-in */}
              <div
                style={{
                  background: "#1e293b",
                  padding: "1rem",
                  borderRadius: "8px",
                  border: "1px solid #334155",
                }}
              >
                <h4 style={{ margin: "0 0 0.5rem 0", color: "#c084fc" }}>
                  🎙️ STT, TTS & Araya Girme
                </h4>
                <div style={{ fontSize: "1.4rem", fontWeight: "bold", margin: "0.3rem 0" }}>
                  {fmt(data.latency_kpis.stt_ms.p50, " ms")}{" "}
                  <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>(STT p50)</span>
                </div>
                <div className="grid-2" style={{ gap: "0.5rem", fontSize: "0.82rem", marginTop: "0.6rem" }}>
                  <div>STT p95: <b>{fmt(data.latency_kpis.stt_ms.p95, " ms")}</b></div>
                  <div>TTS Ortalama: <b>{fmt(data.latency_kpis.tts_ms.avg, " ms")}</b></div>
                  <div>TTS RTF Faktörü: <b>{fmt(data.latency_kpis.tts_ms.avg_rtf, "x")}</b></div>
                  <div>Barge-in (Kesinti): <b style={{ color: "#38bdf8" }}>{data.latency_kpis.barge_in_count} kez</b></div>
                </div>
              </div>
            </div>
          </section>

          {/* VISUAL CHARTS (SVG) */}
          <div className="two" style={{ gap: "1.5rem" }}>
            {/* Chart 1: 14-Day Appointment & Conversation Trend */}
            <section>
              <h2>📈 14 Günlük Randevu & Görüşme Trendi</h2>
              <div style={{ height: "230px", marginTop: "1rem", position: "relative" }}>
                <svg width="100%" height="200" viewBox="0 0 500 200" preserveAspectRatio="none">
                  {/* Grid Lines */}
                  {[0, 50, 100, 150].map((y) => (
                    <line
                      key={y}
                      x1="30"
                      y1={y}
                      x2="490"
                      y2={y}
                      stroke="#334155"
                      strokeDasharray="3 3"
                    />
                  ))}

                  {/* Daily Bars */}
                  {data.daily_trend.map((d, i) => {
                    const x = 40 + i * 32;
                    const hConv = (d.conversations / trendMax) * 150;
                    const hApp = (d.appointments / trendMax) * 150;
                    return (
                      <g key={d.date}>
                        {/* Conversation Bar (Blue) */}
                        <rect
                          x={x}
                          y={160 - hConv}
                          width="12"
                          height={Math.max(2, hConv)}
                          fill="#0284c7"
                          rx="2"
                        >
                          <title>{`${d.date}: ${d.conversations} Görüşme`}</title>
                        </rect>
                        {/* Appointment Bar (Green) */}
                        <rect
                          x={x + 13}
                          y={160 - hApp}
                          width="12"
                          height={Math.max(2, hApp)}
                          fill="#16a34a"
                          rx="2"
                        >
                          <title>{`${d.date}: ${d.appointments} Randevu`}</title>
                        </rect>
                        {/* Day label */}
                        <text
                          x={x + 12}
                          y="180"
                          fontSize="9"
                          fill="#94a3b8"
                          textAnchor="middle"
                        >
                          {d.date.slice(8, 10)}.{d.date.slice(5, 7)}
                        </text>
                      </g>
                    );
                  })}
                </svg>
                {/* Legend */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "center",
                    gap: "1.5rem",
                    fontSize: "0.8rem",
                    marginTop: "0.3rem",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <span style={{ width: 10, height: 10, background: "#0284c7", borderRadius: 2 }} />
                    Görüşmeler
                  </span>
                  <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <span style={{ width: 10, height: 10, background: "#16a34a", borderRadius: 2 }} />
                    Oluşturulan Randevular
                  </span>
                </div>
              </div>
            </section>

            {/* Chart 2: 24-Hour Call Capacity Distribution */}
            <section>
              <h2>⏰ Saatlik Çağrı Yoğunluk Dağılımı (Kapasite)</h2>
              <div style={{ height: "230px", marginTop: "1rem" }}>
                <svg width="100%" height="200" viewBox="0 0 500 200" preserveAspectRatio="none">
                  {/* Grid Lines */}
                  {[0, 50, 100, 150].map((y) => (
                    <line
                      key={y}
                      x1="25"
                      y1={y}
                      x2="495"
                      y2={y}
                      stroke="#334155"
                      strokeDasharray="3 3"
                    />
                  ))}

                  {/* Hourly Bars */}
                  {data.hourly_distribution.map((count, hour) => {
                    const maxH = Math.max(...data.hourly_distribution, 5);
                    const barH = (count / maxH) * 150;
                    const x = 30 + hour * 19;
                    const isPeak = hour >= 9 && hour <= 18;
                    return (
                      <g key={hour}>
                        <rect
                          x={x}
                          y={160 - barH}
                          width="14"
                          height={Math.max(2, barH)}
                          fill={isPeak ? "#38bdf8" : "#475569"}
                          rx="2"
                        >
                          <title>{`Saat ${hour}:00 - ${count} Çağrı`}</title>
                        </rect>
                        {hour % 3 === 0 && (
                          <text
                            x={x + 7}
                            y="180"
                            fontSize="9"
                            fill="#94a3b8"
                            textAnchor="middle"
                          >
                            {hour}:00
                          </text>
                        )}
                      </g>
                    );
                  })}
                </svg>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "center",
                    gap: "1.5rem",
                    fontSize: "0.8rem",
                    marginTop: "0.3rem",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <span style={{ width: 10, height: 10, background: "#38bdf8", borderRadius: 2 }} />
                    Mesai Saatleri (09:00 - 18:00)
                  </span>
                  <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <span style={{ width: 10, height: 10, background: "#475569", borderRadius: 2 }} />
                    Mesai Dışı
                  </span>
                </div>
              </div>
            </section>
          </div>
        </>
      )}

      {activeTab === "dashboard" && !data && (
        <p className="muted">
          {loading ? "Veriler yükleniyor…" : "KPI verisi yok veya alınamadı. Yenilemeyi deneyin."}
        </p>
      )}

      {/* TAB 2: FOLLOW-UP CONVERSATION RESOLUTION WORKFLOW */}
      {activeTab === "follow_ups" && (
        <section>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "1rem",
            }}
          >
            <h2 style={{ margin: 0 }}>
              ⚠️ Takip Gerektiren Görüşmeler ve Çözümleme Akışı
            </h2>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                className={statusFilter === "follow_up" ? "selected" : "secondary"}
                onClick={() => setStatusFilter("follow_up")}
                style={{ padding: "0.35rem 0.8rem", fontSize: "0.8rem" }}
              >
                Bekleyen Takipler
              </button>
              <button
                className={statusFilter === "resolved" ? "selected" : "secondary"}
                onClick={() => setStatusFilter("resolved")}
                style={{ padding: "0.35rem 0.8rem", fontSize: "0.8rem" }}
              >
                Sonuçlandırılanlar
              </button>
              <button
                className={statusFilter === "all" ? "selected" : "secondary"}
                onClick={() => setStatusFilter("all")}
                style={{ padding: "0.35rem 0.8rem", fontSize: "0.8rem" }}
              >
                Tümü
              </button>
            </div>
          </div>

          <div className="table-wrap"><table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #475569" }}>
                <th style={{ padding: "0.6rem" }}>Kanal & ID</th>
                <th style={{ padding: "0.6rem" }}>Tarih / Süre</th>
                <th style={{ padding: "0.6rem" }}>Son Kullanıcı Girdisi</th>
                <th style={{ padding: "0.6rem" }}>Son Asistan Yanıtı</th>
                <th style={{ padding: "0.6rem" }}>Durum & Not</th>
                <th style={{ padding: "0.6rem" }}>İşlem</th>
              </tr>
            </thead>
            <tbody>
              {followUps.map((item) => (
                <tr
                  key={item.id}
                  style={{
                    borderBottom: "1px solid #334155",
                    background: item.status === "follow_up" ? "rgba(202, 138, 4, 0.05)" : "transparent",
                  }}
                >
                  <td style={{ padding: "0.6rem" }}>
                    <b>{item.channel.toUpperCase()}</b>
                    <br />
                    <small style={{ color: "#94a3b8" }}>{item.id.slice(0, 8)}</small>
                  </td>
                  <td style={{ padding: "0.6rem" }}>
                    {item.created_at?.slice(0, 16).replace("T", " ")}
                    <br />
                    <small style={{ color: "#94a3b8" }}>
                      {item.duration_seconds}s ({item.turn_count} tur)
                    </small>
                  </td>
                  <td style={{ padding: "0.6rem", maxWidth: "220px" }}>
                    <span style={{ fontSize: "0.85rem", color: "#e2e8f0" }}>
                      {item.last_user_text || "—"}
                    </span>
                  </td>
                  <td style={{ padding: "0.6rem", maxWidth: "250px" }}>
                    <span style={{ fontSize: "0.85rem", color: "#94a3b8" }}>
                      {item.last_assistant_text || "—"}
                    </span>
                  </td>
                  <td style={{ padding: "0.6rem" }}>
                    {item.status === "follow_up" ? (
                      <span className="pill yellow">⚠️ Takip Bekliyor</span>
                    ) : item.status === "resolved" ? (
                      <span className="pill green">✓ Çözümlendi</span>
                    ) : (
                      <span className="pill">{item.status}</span>
                    )}
                    {item.operator_notes && (
                      <div
                        style={{
                          fontSize: "0.75rem",
                          color: "#38bdf8",
                          marginTop: "4px",
                          fontStyle: "italic",
                        }}
                      >
                        Not: {item.operator_notes}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: "0.6rem" }}>
                    <div style={{ display: "flex", gap: "0.4rem" }}>
                      {item.status === "follow_up" ? (
                        <button
                          onClick={() => {
                            setResolvingId(item.id);
                            setResolveNotes(item.operator_notes || "");
                          }}
                          style={{
                            padding: "0.3rem 0.6rem",
                            fontSize: "0.78rem",
                            background: "#16a34a",
                            color: "white",
                            borderRadius: "4px",
                          }}
                        >
                          ✅ Sonuçlandır
                        </button>
                      ) : (
                        <button
                          onClick={() => handleReopen(item.id)}
                          style={{
                            padding: "0.3rem 0.6rem",
                            fontSize: "0.78rem",
                            background: "#252e40",
                            color: "#94a3b8",
                            borderRadius: "4px",
                          }}
                        >
                          ↩️ Geri Aç
                        </button>
                      )}
                      <button
                        onClick={() => handleOpenInspect(item.id)}
                        style={{
                          padding: "0.3rem 0.6rem",
                          fontSize: "0.78rem",
                          borderRadius: "4px",
                        }}
                      >
                        🔍 Diyalog
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {followUps.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ textAlign: "center", padding: "1.5rem" }}>
                    Bu filtreye uygun takip görüşmesi bulunamadı.
                  </td>
                </tr>
              )}
            </tbody>
          </table></div>
        </section>
      )}

      {/* RESOLUTION MODAL */}
      {resolvingId && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Görüşmeyi sonuçlandır"
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.75)",
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
              width: "500px",
              maxWidth: "92vw",
              border: "1px solid #475569",
            }}
          >
            <h3 style={{ margin: "0 0 0.8rem 0" }}>
              ✅ Görüşmeyi Sonuçlandır (Operatör İşlemi)
            </h3>
            <p style={{ fontSize: "0.85rem", color: "#94a3b8", margin: "0 0 1rem 0" }}>
              Görüşme ID: {resolvingId} — Müşteri ile yapılan harici arama, WhatsApp görüşmesi veya manuel randevu durumunu not edin.
            </p>
            <form onSubmit={handleResolve}>
              <textarea
                aria-label="Çözüm notu"
                placeholder="Örn: Müşteri arandı, yarın saat 14:00 maslak şubesine randevu oluşturuldu."
                value={resolveNotes}
                onChange={(e) => setResolveNotes(e.target.value)}
                rows={3}
                required
                style={{ width: "100%", padding: "0.6rem", borderRadius: "4px", marginBottom: "1rem" }}
              />
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.6rem" }}>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setResolvingId(null)}
                  style={{ padding: "0.4rem 0.9rem" }}
                >
                  İptal
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  style={{ padding: "0.4rem 1.1rem", background: "#16a34a", color: "white" }}
                >
                  {loading ? "Kaydediliyor..." : "✓ Sonuçlandırıldı Olarak Kaydet"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* DIALOGUE TRANSCRIPT INSPECT MODAL */}
      {inspectConvId && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Görüşme turları ve transkript"
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0,0,0,0.75)",
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
              width: "650px",
              maxWidth: "92vw",
              maxHeight: "80vh",
              overflowY: "auto",
              border: "1px solid #475569",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "0.8rem",
              }}
            >
              <h3 style={{ margin: 0 }}>🔍 Görüşme Turları & Transkript</h3>
              <button
                onClick={() => setInspectConvId(null)}
                aria-label="Kapat"
                style={{ background: "transparent", border: "none", fontSize: "1.2rem", cursor: "pointer" }}
              >
                ✕
              </button>
            </div>
            <p style={{ fontSize: "0.8rem", color: "#94a3b8", margin: "0 0 1rem 0" }}>
              Görüşme ID: {inspectConvId}
            </p>
            {loadingTurns ? (
              <p>Turlar yükleniyor...</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
                {inspectTurns.map((t) => (
                  <div
                    key={t.id}
                    style={{
                      background: t.role === "user" ? "#0f172a" : "#1e3a5f",
                      padding: "0.6rem 0.8rem",
                      borderRadius: "6px",
                      borderLeft: t.role === "user" ? "3px solid #38bdf8" : "3px solid #4ade80",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", color: "#94a3b8" }}>
                      <b>{t.role.toUpperCase()}</b>
                      <span>{t.created_at?.slice(11, 19)}</span>
                    </div>
                    <div style={{ marginTop: "4px", fontSize: "0.88rem" }}>{t.text}</div>
                    {formatMetrics(t.metrics) && (
                      <small style={{ color: "#64748b", marginTop: "4px" }}>
                        {formatMetrics(t.metrics)}
                      </small>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "1rem" }}>
              <button
                className="secondary"
                onClick={() => setInspectConvId(null)}
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

