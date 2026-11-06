import { useEffect, useState } from "react";
type Props = {
  api: (path: string, method?: string, body?: unknown) => Promise<any>;
};
export function MilestonePanel({ api }: Props) {
  const [overview, setOverview] = useState<any>(null),
    [items, setItems] = useState<any[]>([]),
    [error, setError] = useState(""),
    [text, setText] = useState("1.250.000 TL için yarın saat 14:30 uygun mu?"),
    [result, setResult] = useState<any>(null),
    [reviewer, setReviewer] = useState(""),
    [calls, setCalls] = useState<any[]>([]),
    [events, setEvents] = useState<any[]>([]);
  async function refresh() {
    const [o, i, c] = await Promise.all([
      api("milestones/overview"),
      api("milestones/pronunciation"),
      api("conversations"),
    ]);
    setOverview(o);
    setItems(i);
    setCalls(c);
  }
  async function act(fn: () => Promise<void>) {
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    act(refresh);
  }, []);
  return (
    <>
      <section>
        <h2>M01–M11 entegrasyonu</h2>
        <p className="muted">
          Güncel M11 kaynakları ve önceki sürümlerin sözleşmeleri mevcut yerel
          uygulamaya dahil edildi. Sentetik servisler canlı görüşmede
          kullanılmaz.
        </p>
        {overview && (
          <>
            <div className="row">
              <b>Fiziksel kabul</b>
              <span className="pill">{overview.physical_acceptance}</span>
            </div>
            <small>
              {overview.imported_files} dosya · {overview.archive}
            </small>
            <p>{overview.live_components.join(" · ")}</p>
          </>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
      </section>
      <section>
        <h2>Metin ve yan cümle sözleşmesi</h2>
        <label>
          İncelenecek metin
          <textarea
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        <button
          onClick={() =>
            act(async () =>
              setResult(await api("milestones/inspect", "POST", { text })),
            )
          }
        >
          Sözleşmeyi incele
        </button>
        {result && (
          <>
            <p className="bubble">{result.normalization.spoken_text}</p>
            <span className="pill">{result.plan.status}</span>
            <p className="muted">
              Bu inceleme ses üretmez. İnceleme gerektiren marka okunuşları
              otomatik onaylanmaz.
            </p>
            {result.plan.clauses.map((c: any) => (
              <div className="row" key={c.index}>
                <span>{c.text}</span>
                <small>{c.pause_after_ms} ms</small>
              </div>
            ))}
          </>
        )}
      </section>
      <section>
        <h2>Telaffuz incelemeleri</h2>
        <p className="muted">
          Kaynak veritabanı salt okunur. Onay, doğrulanmış ses ve insan
          transkripti gerektirir; kararlar ayrı inceleme günlüğüne yazılır.
        </p>
        <label>
          İnceleyen
          <input
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            placeholder="operator_01"
          />
        </label>
        {!items.length && (
          <p className="muted">
            Kaynakta incelenecek gözlem bulunmuyor; okunuş uydurulmadı.
          </p>
        )}
        {items.map((i) => (
          <div className="row" key={i.id}>
            <div>
              <b>{i.canonical}</b>
              <small>
                {i.spoken_tr} · {i.review?.decision || "İnceleme bekliyor"}
              </small>
            </div>
            <button
              disabled={
                !reviewer ||
                !i.transcript_checked ||
                !i.has_clip_reference ||
                !i.audio_use_authorized
              }
              onClick={() =>
                act(async () => {
                  await api("milestones/pronunciation", "POST", {
                    annotation_id: i.id,
                    decision: "approved",
                    reviewer,
                    reason_code: "verified_evidence",
                  });
                  await refresh();
                })
              }
            >
              Kanıtı onayla
            </button>
            <button
              className="secondary"
              disabled={!reviewer}
              onClick={() =>
                act(async () => {
                  await api("milestones/pronunciation", "POST", {
                    annotation_id: i.id,
                    decision: "rejected",
                    reviewer,
                    reason_code: "insufficient_evidence",
                  });
                  await refresh();
                })
              }
            >
              Yetersiz kanıt
            </button>
          </div>
        ))}
      </section>
      <section>
        <h2>Kalıcı oturum olayları</h2>
        <label>
          Görüşme
          <select
            defaultValue=""
            onChange={(e) =>
              act(async () =>
                setEvents(
                  e.target.value
                    ? await api("milestones/timeline/" + e.target.value)
                    : [],
                ),
              )
            }
          >
            <option value="">Görüşme seçin</option>
            {calls.map((c) => (
              <option key={c.id} value={c.id}>
                {new Date(c.created_at).toLocaleString("tr-TR")} · {c.channel}
              </option>
            ))}
          </select>
        </label>
        {events.map((e) => (
          <div key={e.event_id} className="row">
            <span>
              {e.sequence} · {e.event_type}
            </span>
            <small>
              Tur {e.turn_id} · Üretim {e.generation_id}
            </small>
          </div>
        ))}
        <p className="muted">
          Günlük teslimi, telefon tarafında oynatma veya tampon temizleme onayı
          anlamına gelmez.
        </p>
      </section>
    </>
  );
}
