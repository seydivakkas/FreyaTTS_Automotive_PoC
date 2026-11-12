import { useEffect, useState } from "react";
import type { ActionFn, Conversation, ConversationDetail } from "../api";
import { analysisSource, analysisState } from "../AnalysisQueuePanel";
import { errorMessage, formatDate, formatMetrics } from "../ui";
import type { ApiFn } from "../ui";

type Props = {
  api: ApiFn;
  action: ActionFn;
  refresh: () => Promise<void>;
  calls: Conversation[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onOpenQuality: (id: string) => void;
};

export function HistoryTab({ api, action, refresh, calls, selectedId, onSelect, onOpenQuality }: Props) {
  const [response, setResponse] = useState<{ id: string; detail?: ConversationDetail; error?: string } | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!selectedId) return;
    let current = true;
    setResponse(null);
    api(`supervisor/conversations/${selectedId}/detail`).then(
      (detail: ConversationDetail) => { if (current) setResponse({ id: selectedId, detail }); },
      (err: unknown) => { if (current) setResponse({ id: selectedId, error: errorMessage(err) }); },
    );
    return () => { current = false; };
  }, [api, selectedId, revision]);

  const selected = response?.id === selectedId ? response : null;
  const detail = selected?.detail;

  return (
    <div className="two conversation-history">
      <section>
        <h2>Görüşmeler</h2>
        {calls.map((c) => (
          <div className="row" key={c.id}>
            <button
              className="secondary"
              aria-label={`Görüşme ${formatDate(c.created_at)}`}
              aria-current={selectedId === c.id ? "true" : undefined}
              onClick={() => onSelect(c.id)}
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
                  if (selectedId === c.id) onSelect(null);
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
      <section className="card conversation-detail" aria-labelledby="conversation-detail-title">
        <div className="row">
          <h2 id="conversation-detail-title">Görüşme detayı</h2>
          {selectedId && <button className="secondary" disabled={!selected} onClick={() => setRevision((n) => n + 1)}>
            Detayı yenile
          </button>}
        </div>
        {!selectedId && <p className="muted">Detayı görmek için bir görüşme seçin.</p>}
        {selectedId && !selected && <p role="status">Görüşme yükleniyor…</p>}
        {selected?.error && <p role="alert">{selected.error}</p>}
        {detail && <>
          <p>{formatDate(detail.conversation.created_at)} · {detail.conversation.channel} · <strong>{detail.conversation.status}</strong></p>
          <p className="muted"><small>{detail.conversation.id}</small></p>
          {detail.conversation.status === "purged" ? <p>Bu görüşmenin ayrıntıları saklama politikasına göre silinmiş.</p> : <>
            <div className="conversation-linked">
              <section aria-labelledby="linked-appointment">
                <h3 id="linked-appointment">Bağlı randevu</h3>
                {detail.appointment ? <>
                  <p><strong>{detail.appointment.status}</strong>{detail.appointment.starts_at && ` · ${formatDate(detail.appointment.starts_at)}`}</p>
                  <small>{detail.appointment.id}</small>
                </> : <p className="muted">Bu görüşmeyle eşleşen randevu kaydı yok.</p>}
              </section>
              <section aria-labelledby="linked-transfers">
                <h3 id="linked-transfers">Operatör aktarımı</h3>
                {detail.transfers.length ? <ul>{detail.transfers.map((transfer) =>
                  <li key={transfer.id}>{transfer.status} · {formatDate(transfer.completed_at ?? transfer.created_at)}</li>,
                )}</ul> : <p className="muted">Bağlı aktarım kaydı yok.</p>}
              </section>
              <section aria-labelledby="linked-analysis">
                <h3 id="linked-analysis">FQICI analiz işleri</h3>
                {detail.fqici.store === "UNAVAILABLE" ? <p>Kuyruk deposu hazır değil.</p> :
                  detail.fqici.scope ? <>
                    <p>{analysisSource(detail.fqici.scope)}</p>
                    {detail.fqici.scope.ready_at_ms !== null && <p>Yeni analiz için bekleyen kanıt var.</p>}
                    {!detail.fqici.scope.terminal_seen && <p>Kapanış kaydı bekleniyor.</p>}
                    {!!detail.fqici.runs.length && <ul>{detail.fqici.runs.map((run) =>
                      <li key={run.id}>{analysisState(run)} · {run.rule_version} · {run.attempts} deneme</li>,
                    )}</ul>}
                  </> : <p className="muted">Bu görüşme için FQICI kaydı yok.</p>}
              </section>
              <section aria-labelledby="linked-traces">
                <h3 id="linked-traces">Supervisor kararları</h3>
                {detail.traces.length ? <>
                  <ul>{detail.traces.map((trace) => (
                    <li key={trace.id}>
                      <strong>{trace.intents.join(", ") || trace.route_state}</strong>
                      <small> · {trace.outcome}{trace.reason_codes.length > 0 && ` · ${trace.reason_codes.join(", ")}`}</small>
                    </li>
                  ))}</ul>
                  <button className="secondary" onClick={() => onOpenQuality(detail.conversation.id)}>Supervisor kararlarını aç</button>
                </> : <p className="muted">Bu görüşme için karar izi yok.</p>}
              </section>
            </div>
            <h3>Transkript ve ölçümler</h3>
            {!detail.turns.length && <p className="muted">Bu görüşmede konuşma kaydı yok.</p>}
            {detail.turns.map((t) => (
              <p className="bubble" key={t.id}>
                <b>{t.role === "metric" ? "ölçüm" : t.role}</b>
                {t.text || formatMetrics(t.metrics) || "—"}
              </p>
            ))}
          </>}
        </>}
      </section>
    </div>
  );
}
