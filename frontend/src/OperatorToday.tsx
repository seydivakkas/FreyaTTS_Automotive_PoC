import { useEffect, useState } from "react";
import { errorMessage, formatDate } from "./ui";
import type { ApiFn } from "./ui";

type Kind = "transfer" | "callback" | "booking_pending" | "booking_unknown" | "follow_up";
type Category = "all" | "transfer" | "callback" | "booking" | "follow_up";
type Period = "all" | "today" | "carryover";
type Item = {
  id: string;
  conversation_id: string | null;
  kind: Kind;
  since: string;
  since_source: "transfer" | "follow_up" | "conversation";
  period: "today" | "carryover" | "unknown";
  age_seconds: number | null;
};
type Today = { local_date: string; counts: Partial<Record<Kind, number>>; total: number; items: Item[] };

const itemLabels: Record<Kind, [string, string]> = {
  transfer: ["Bekleyen aktarım", "Aktarım detayını aç"],
  callback: ["Geri arama talebi", "Geri arama talebini incele"],
  booking_pending: ["Yarım kalan randevu", "Randevu adımını kontrol et"],
  booking_unknown: ["Randevu sonucu belirsiz", "Randevu sonucunu doğrula"],
  follow_up: ["Görüşme takibi", "Takip nedenini incele"],
};

function age(seconds: number | null) {
  if (seconds === null) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds / 3600) % 24;
  const minutes = Math.floor(seconds / 60) % 60;
  if (days) return `${days} gün ${hours} sa`;
  if (hours) return `${hours} sa ${minutes} dk`;
  return minutes ? `${minutes} dk` : `${seconds} sn`;
}

export function OperatorToday({ api, autoRefresh, revision, onOpenConversation, onOpenTransfer }: {
  api: ApiFn;
  autoRefresh: boolean;
  revision: number;
  onOpenConversation: (id: string) => void;
  onOpenTransfer: (id: string) => void;
}) {
  const [data, setData] = useState<Today | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [category, setCategory] = useState<Category>("all");
  const [period, setPeriod] = useState<Period>("all");
  const [page, setPage] = useState(0);
  const pageSize = 25;

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    setData(null);
    setLoading(true);
    const params = new URLSearchParams({ category, period, limit: String(pageSize), offset: String(page * pageSize) });
    async function load() {
      try {
        const result: Today = await api(`operator/today?${params}`);
        if (!cancelled) {
          setData(result);
          setError("");
          if (page > 0 && page * pageSize >= result.total) setPage(0);
        }
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
          if (autoRefresh) timer = window.setTimeout(() => void load(), 3000);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [api, category, period, page, revision, autoRefresh]);

  return (
    <section className="card operator-today" aria-labelledby="operator-today-title" aria-busy={loading}>
      <h2 id="operator-today-title">Bugün</h2>
      <p>Açık operatör işleri ve önceki günlerden devreden kayıtlar.</p>
      {data && <dl className="analysis-facts">
        <div><dt>Bekleyen aktarım</dt><dd>{data.counts.transfer ?? 0}</dd></div>
        <div><dt>Geri arama</dt><dd>{data.counts.callback ?? 0}</dd></div>
        <div><dt>Randevu takibi</dt><dd>{(data.counts.booking_pending ?? 0) + (data.counts.booking_unknown ?? 0)}</dd></div>
        <div><dt>Diğer takipler</dt><dd>{data.counts.follow_up ?? 0}</dd></div>
      </dl>}
      <div className="row">
        <label>Dönem{" "}<select value={period} onChange={(e) => { setPage(0); setPeriod(e.target.value as Period); }}>
          <option value="all">Tümü</option>
          <option value="today">Bugünün işleri</option>
          <option value="carryover">Devredenler</option>
        </select></label>
        <label>İş türü{" "}<select value={category} onChange={(e) => { setPage(0); setCategory(e.target.value as Category); }}>
          <option value="all">Tümü</option>
          <option value="transfer">Bekleyen aktarım</option>
          <option value="callback">Geri arama</option>
          <option value="booking">Randevu takibi</option>
          <option value="follow_up">Diğer takipler</option>
        </select></label>
      </div>
      {loading && <p role="status">Operatör işleri yükleniyor…</p>}
      {error && <p role="alert">İş listesi yenilenemedi. {error}</p>}
      {data && <>
        <p className="muted">{data.total} iş · İstanbul {data.local_date.split("-").reverse().join(".")}</p>
        {!data.items.length && <p>Bu filtreye uyan açık iş yok.</p>}
        <ul className="operator-work-list">
          {data.items.map((item) => {
            const conversationId = item.conversation_id;
            return <li className="row" key={`${item.kind}-${item.id}`}>
              <div>
                <strong>{itemLabels[item.kind][0]}</strong>
                <small>{item.period === "carryover" ? "Devreden · " : ""}
                  {item.since_source === "conversation" ? "Görüşme yaşı" : "Bekleme"} {age(item.age_seconds)}
                  {item.age_seconds !== null && ` · ${formatDate(item.since)}`}
                </small>
                <small>Sıradaki adım · {itemLabels[item.kind][1]}</small>
              </div>
              <div className="operator-work-actions">
                {conversationId && <button className="secondary" onClick={() => onOpenConversation(conversationId)}>Görüşmeyi aç</button>}
                {item.kind === "transfer" && <button className="secondary" onClick={() => onOpenTransfer(item.id)}>Aktarımı aç</button>}
              </div>
            </li>;
          })}
        </ul>
        {data.total > pageSize && <div className="row">
          <button className="secondary" disabled={page === 0} onClick={() => setPage((n) => n - 1)}>Önceki</button>
          <small>{page + 1} / {Math.ceil(data.total / pageSize)}</small>
          <button className="secondary" disabled={(page + 1) * pageSize >= data.total} onClick={() => setPage((n) => n + 1)}>Sonraki</button>
        </div>}
      </>}
    </section>
  );
}
