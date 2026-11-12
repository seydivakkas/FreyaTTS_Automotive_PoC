import { useEffect, useState } from "react";
import type { Props } from "./api";
import { errorMessage } from "./ui";
import { AnalysisQueuePanel } from "./AnalysisQueuePanel";

type Definition = { intent_id: string; domain: string; description: string; agent: string };
type Candidate = { intent_id: string; score: number | null; evidence: string };
type Step = { step_id: string; agent: string; action: string; depends_on: string[] };
type Trace = {
  trace_id: string;
  conversation_id: string;
  created_at: string;
  review_status: string;
  review_labels: string[] | null;
  outcome: string;
  qa_flags: string[];
  decision: { route_state: string; source: string; candidates: Candidate[]; reason_codes: string[] };
  plan: {
    steps: Step[];
    priority: string;
    requires_confirmation: boolean;
    model_version: string;
    policy_version: string;
  };
};
type Report = {
  model_version: string;
  dataset_sources: string[];
  test: Record<string, number | null>;
};
type Quality = {
  catalogue_version: string;
  mode: string;
  trace_store: string;
  catalogue: Definition[];
  traces: Trace[];
  registry: { approval_configured: boolean; fallback_enabled: boolean };
  evaluation: { baseline: Report | null; xgboost: Report | null; comparable: boolean };
  software_regression: { status: string; tests?: number; failures?: number; errors?: number; skipped?: number };
  physical_regression: string;
};
type Verdict = "ACCEPT" | "EDIT" | "REJECT" | "NEEDS_MORE_EVIDENCE";

const metrics = [
  ["macro_f1", "Makro F1"],
  ["micro_f1", "Mikro F1"],
  ["multi_intent_exact_match", "Çoklu niyet tam eşleşme"],
  ["emergency_recall", "Acil durum yakalama"],
  ["ood_false_accept", "Kapsam dışı yanlış kabul"],
  ["latency_ms_p95", "Gecikme p95 (ms)"],
];
const traceTime = new Intl.DateTimeFormat("tr-TR", {
  dateStyle: "short", timeStyle: "medium", timeZone: "Europe/Istanbul",
});

export function SupervisorPanel({ api, rawApi, initialConversationId, onOpenConversation }: Props & {
  initialConversationId?: string;
  onOpenConversation?: (id: string) => void;
}) {
  const [quality, setQuality] = useState<Quality | null>(null);
  const [queue, setQueue] = useState<"all" | "pending">(initialConversationId ? "all" : "pending");
  const [filter, setFilter] = useState(initialConversationId ?? "");
  const [selected, setSelected] = useState<Trace | null>(null);
  const [verdict, setVerdict] = useState<Verdict>("ACCEPT");
  const [labels, setLabels] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [group, setGroup] = useState("");
  const [split, setSplit] = useState("train");
  const [anonymity, setAnonymity] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const params = new URLSearchParams({ queue });
    if (filter.trim()) params.set("conversation_id", filter.trim());
    setQuality(await api(`supervisor/quality?${params}`));
  }

  async function action(work: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await work();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { void action(load); }, [queue]);

  function selectTrace(trace: Trace) {
    setSelected(trace);
    setVerdict("ACCEPT");
    setLabels(trace.review_labels ?? trace.decision.candidates.map((item) => item.intent_id));
    setText("");
    setGroup("");
    setAnonymity(false);
    setConsent(false);
  }

  async function saveReview() {
    if (!selected) return;
    const body: Record<string, unknown> = { verdict };
    if (verdict === "EDIT") body.labels = labels;
    if (text.trim() && (verdict === "ACCEPT" || verdict === "EDIT")) {
      Object.assign(body, {
        anonymous_text: text.trim(), group_id: group.trim(), split,
        anonymity_attested: anonymity, consent_attested: consent,
      });
    }
    await api(`supervisor/review/${selected.trace_id}`, "POST", body);
    setSelected(null);
    setText("");
    await load();
  }

  async function downloadDataset() {
    const response = await rawApi("supervisor/dataset");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "intent-reviewed.jsonl";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const baseline = quality?.evaluation.baseline;
  const challenger = quality?.evaluation.xgboost;
  const domains = [...new Set(quality?.catalogue.map((item) => item.domain))];

  return (
    <section className="card supervisor-panel" aria-labelledby="supervisor-title">
      <h2 id="supervisor-title">Supervisor Kalite</h2>
      <AnalysisQueuePanel api={api} onOpenConversation={onOpenConversation} />
      <div className="row">
        <label>Görünüm{" "}
          <select disabled={busy} value={queue} onChange={(event) => setQueue(event.target.value as typeof queue)}>
            <option value="pending">İnceleme kuyruğu</option>
            <option value="all">Tüm kararlar</option>
          </select>
        </label>
        <label>Görüşme kimliği{" "}
          <input value={filter} onChange={(event) => setFilter(event.target.value)} />
        </label>
        <button disabled={busy} onClick={() => void action(load)}>Yenile</button>
        <button disabled={busy || quality?.trace_store !== "READY"} onClick={() => void action(downloadDataset)}>
          Onaylı veri setini indir
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {quality && <>
        <p>Çalışma modu <strong>{quality.mode}</strong> · Katalog <strong>{quality.catalogue_version}</strong> ·
          Karar deposu <strong>{quality.trace_store}</strong> · Fiziksel çağrı <strong>{quality.physical_regression}</strong>
        </p>
        <p>Yazılım regresyonu <strong>{quality.software_regression.status}</strong>
          {quality.software_regression.tests !== undefined && ` · ${quality.software_regression.tests} test`}
        </p>
        <h3>Görüşme kararları</h3>
        <p>Görüşme metni ve slot değerleri bu panelde gösterilmez.</p>
        {!quality.traces.length && <p>Bu görünümde karar kaydı yok.</p>}
        {quality.traces.map((trace) => (
          <details key={trace.trace_id}>
            <summary>{traceTime.format(new Date(trace.created_at))} · {trace.decision.route_state} · {trace.plan.priority} · {trace.review_status}</summary>
            <p>Görüşme {trace.conversation_id} · Model {trace.plan.model_version} · Politika {trace.plan.policy_version}</p>
            <p>Kaynak {trace.decision.source} · Sonuç {trace.outcome} · QA {trace.qa_flags.join(", ") || "—"}</p>
            <p>Gerekçe {trace.decision.reason_codes.join(", ") || "—"}</p>
            <ul>{trace.decision.candidates.map((item) => (
              <li key={item.intent_id}>{item.intent_id} · {item.score?.toFixed(3) ?? "—"} · {item.evidence}</li>
            ))}</ul>
            <ol>{trace.plan.steps.map((step) => (
              <li key={step.step_id}>{step.agent} / {step.action}
                {step.depends_on.length > 0 && ` (${step.depends_on.join(", ")} sonrasında)`}
              </li>
            ))}</ol>
            <p>Açık onay gereği {trace.plan.requires_confirmation ? "var" : "yok"}</p>
            {trace.review_labels && <p>İncelenen etiketler {trace.review_labels.join(", ") || "—"}</p>}
            <button onClick={() => selectTrace(trace)}>İncele</button>
          </details>
        ))}
        {selected && <form onSubmit={(event) => { event.preventDefault(); void action(saveReview); }}>
          <h3>Karar incelemesi</h3>
          <p>{selected.trace_id}</p>
          <label>Karar{" "}<select value={verdict} onChange={(event) => setVerdict(event.target.value as Verdict)}>
            <option value="ACCEPT">Kabul</option><option value="EDIT">Etiketleri düzelt</option>
            <option value="REJECT">Reddet</option><option value="NEEDS_MORE_EVIDENCE">Ek kanıt gerekli</option>
          </select></label>
          {verdict === "EDIT" && <label>Düzeltilmiş niyetler{" "}
            <select multiple value={labels} onChange={(event) =>
              setLabels(Array.from(event.target.selectedOptions, (option) => option.value))}>
              {quality.catalogue.map((item) => <option key={item.intent_id}>{item.intent_id}</option>)}
            </select>
          </label>}
          {(verdict === "ACCEPT" || verdict === "EDIT") && <details>
            <summary>İzinli anonim örneği veri setine ekle</summary>
            <p>Aynı müşteri veya senaryo için aynı anonim grup kimliğini ve aynı bölümü kullanın.</p>
            <label>Anonim örnek <textarea value={text} maxLength={1200} onChange={(event) => setText(event.target.value)} /></label>
            <label>Anonim grup UUID <input value={group} onChange={(event) => setGroup(event.target.value)} /></label>
            <label>Bölüm <select value={split} onChange={(event) => setSplit(event.target.value)}>
              <option value="train">Eğitim</option><option value="validation">Doğrulama</option><option value="test">Test</option>
            </select></label>
            <label><input type="checkbox" checked={anonymity} onChange={(event) => setAnonymity(event.target.checked)} /> Örnek anonimleştirildi</label>
            <label><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /> Eğitim kullanımına izin var</label>
          </details>}
          <button disabled={busy}>Kaydet</button>{" "}
          <button type="button" onClick={() => setSelected(null)}>Kapat</button>
        </form>}
        <h3>Model kayıtları ve değerlendirme</h3>
        <p>Model onay ayarı {quality.registry.approval_configured ? "var" : "yok"} ·
          Yerel LLM ayarı {quality.registry.fallback_enabled ? "açık" : "kapalı"}</p>
        <p>{quality.evaluation.comparable ? "Aynı veri ve bölümler" : "Karşılaştırma bekliyor"}</p>
        <table>
          <thead><tr><th>Ölçüm</th><th>{baseline?.model_version ?? "Baseline · NOT RUN"}</th>
            <th>{challenger?.model_version ?? "XGBoost · NOT RUN"}</th></tr></thead>
          <tbody>
            <tr><th>Veri kaynağı</th><td>{baseline?.dataset_sources.join(", ") ?? "—"}</td>
              <td>{challenger?.dataset_sources.join(", ") ?? "—"}</td></tr>
            {metrics.map(([key, title]) => <tr key={key}><th>{title}</th>
              <td>{baseline?.test[key]?.toFixed(3) ?? "—"}</td>
              <td>{challenger?.test[key]?.toFixed(3) ?? "—"}</td></tr>)}
          </tbody>
        </table>
        <h3>Niyet kataloğu</h3>
        {domains.map((domain) => <details key={domain}>
          <summary>{domain}</summary>
          <ul>{quality.catalogue.filter((item) => item.domain === domain).map((item) => (
            <li key={item.intent_id}>{item.intent_id} · {item.description} · {item.agent}</li>
          ))}</ul>
        </details>)}
      </>}
    </section>
  );
}
