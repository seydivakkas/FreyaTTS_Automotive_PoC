import { useEffect, useState } from "react";
import type { AnalysisQueue, AnalysisRun, AnalysisSource } from "./api";
import { errorMessage, formatDate } from "./ui";
import type { ApiFn } from "./ui";

const runLabels: Record<string, string> = {
  QUEUED: "Kuyrukta",
  RUNNING: "İşleniyor",
  SUCCEEDED: "Tamamlandı",
  FAILED_RETRYABLE: "Yeniden denenecek",
  FAILED_TERMINAL: "Başarısız",
  SUPERSEDED: "Yeni analizle değiştirildi",
};

export function analysisState(run: AnalysisRun) {
  return run.lease_expired ? "İşçi kirası doldu" : runLabels[run.state] ?? run.state;
}

export function analysisSource(source: AnalysisSource) {
  const transports: Record<string, string> = { WEB: "Web", AUDIOSOCKET: "AudioSocket", SIP: "SIP" };
  const origins: Record<string, string> = {
    SYNTHETIC: "Sentetik", DEMO: "Demo", REAL: "Gerçek", UNKNOWN: "Köken belirsiz",
  };
  return `${transports[source.transport] ?? source.transport} · ${origins[source.origin] ?? source.origin}`;
}

function age(ms: number | null) {
  if (ms === null) return "—";
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes} dk ${seconds % 60} sn` : `${seconds} sn`;
}

export function AnalysisQueuePanel({ api, onOpenConversation }: {
  api: ApiFn; onOpenConversation?: (id: string) => void;
}) {
  const [data, setData] = useState<AnalysisQueue | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    api("supervisor/fqici-queue").then(
      (value: AnalysisQueue) => { if (current) setData(value); },
      (err: unknown) => { if (current) { setData(null); setError(errorMessage(err)); } },
    ).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [api, revision]);

  function conversationLink(id: string) {
    return onOpenConversation
      ? <button type="button" className="secondary" onClick={() => onOpenConversation(id)} aria-label={`Görüşmeyi aç ${id}`}>Görüşmeyi aç</button>
      : <small>{id}</small>;
  }

  return (
    <section className="analysis-queue" aria-labelledby="analysis-queue-title" aria-busy={loading}>
      <div className="row">
        <h3 id="analysis-queue-title">Analiz Kuyruğu</h3>
        <button className="secondary" disabled={loading} onClick={() => setRevision((n) => n + 1)}>Kuyruğu yenile</button>
      </div>
      {loading && <p role="status">Kuyruk yükleniyor…</p>}
      {error && <p role="alert">{error}</p>}
      {data && <>
        <p>Olay alımı <strong>{data.intake_enabled ? "açık" : "kapalı"}</strong> · Analiz işçisi{" "}
          <strong>{data.worker_status === "NOT_CONNECTED" ? "bağlı değil" : data.worker_status}</strong> ·
          Fiziksel SIP kabulü <strong>{data.physical_sip_status}</strong></p>
        {data.store === "UNAVAILABLE" ? <p>Kuyruk deposu hazır değil. FQICI migrasyonunu kontrol edin.</p> : <>
          <dl className="analysis-facts">
            <div><dt>Kuyrukta</dt><dd>{data.counts.QUEUED ?? 0}</dd></div>
            <div><dt>Kiralı işler</dt><dd>{data.counts.RUNNING ?? 0}</dd></div>
            <div><dt>Yeniden denenecek</dt><dd>{data.counts.FAILED_RETRYABLE ?? 0}</dd></div>
            <div><dt>Ertelenen görüşme</dt><dd>{data.deferred_count ?? "—"}</dd></div>
            <div><dt>En eski bekleme</dt><dd>{age(data.oldest_wait_ms)}</dd></div>
          </dl>
          {data.runs.length === 0 && data.deferred.length === 0 ? <p>Gösterilecek analiz işi yok.</p> : <details>
          <summary>Analiz işlerini göster ({data.runs.length + data.deferred.length})</summary>
          {data.runs.map((run) => (
            <div key={run.id} className="row">
              <div><strong>{analysisState(run)}</strong><br />
                <small>{analysisSource(run)} · {run.attempts} deneme · {formatDate(new Date(run.created_at_ms).toISOString())}</small></div>
              {conversationLink(run.conversation_id)}
            </div>
          ))}
          {data.deferred.map((scope) => (
            <div key={scope.conversation_id} className="row">
              <div><strong>Ertelendi</strong><br />
                <small>{analysisSource(scope)} · Uygunluk {formatDate(new Date(scope.ready_at_ms).toISOString())}</small></div>
              {conversationLink(scope.conversation_id)}
            </div>
          ))}
          </details>}
        </>}
      </>}
    </section>
  );
}
