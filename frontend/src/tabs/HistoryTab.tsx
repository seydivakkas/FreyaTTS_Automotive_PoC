import type { ActionFn, Conversation, Turn } from "../api";
import { formatDate, formatMetrics } from "../ui";
import type { ApiFn } from "../ui";

type Props = {
  api: ApiFn;
  action: ActionFn;
  refresh: () => Promise<void>;
  calls: Conversation[];
  turns: Turn[];
  setTurns: (t: Turn[]) => void;
};

export function HistoryTab({ api, action, refresh, calls, turns, setTurns }: Props) {
  return (
    <div className="two">
      <section>
        <h2>Görüşmeler</h2>
        {calls.map((c) => (
          <div className="row" key={c.id}>
            <button
              className="secondary"
              onClick={() => action(async () => setTurns(await api("conversations/" + c.id)))}
            >
              {formatDate(c.created_at)}
              <small>
                {c.channel} · {c.status}
              </small>
            </button>
            <button
              className="danger"
              onClick={() =>
                action(async () => {
                  await api("conversations/" + c.id, "DELETE");
                  setTurns([]);
                  await refresh();
                })
              }
            >
              Sil
            </button>
          </div>
        ))}
        {!calls.length && <p className="muted">Henüz görüşme yok.</p>}
      </section>
      <section>
        <h2>Transkript ve ölçümler</h2>
        {turns.map((t) => (
          <p className="bubble" key={t.id}>
            <b>{t.role === "metric" ? "ölçüm" : t.role}</b>
            {t.text || formatMetrics(t.metrics) || "—"}
          </p>
        ))}
      </section>
    </div>
  );
}
