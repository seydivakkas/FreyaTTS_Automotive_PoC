import { useEffect, useRef, useState } from "react";
import type { Appointment, Slot } from "./api";
import { errorMessage, formatDate } from "./ui";
import type { ApiFn } from "./ui";

type Preview = {
  source: Slot | null;
  target: Slot;
  status: string;
  lift_status: "available" | "unknown" | "conflict" | "unchecked";
  message: string;
  preview_version: string;
  alternatives: Slot[];
};

const liftLabels: Record<Preview["lift_status"], string> = {
  available: "Tanımlı kapasite uygun",
  unknown: "Kapasite tanımlı değil",
  conflict: "Kapasite veya atama çakışması",
  unchecked: "Saat kontrolü sonuçlanmadı",
};

export function AppointmentMoveDialog({ api, appointment, slots, appointments, initialTarget,
  onClose, onMoved, refresh }: {
  api: ApiFn; appointment: Appointment; slots: Slot[]; appointments: Appointment[];
  initialTarget: string; onClose: () => void; onMoved: (startsAt: string) => void; refresh: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [target, setTarget] = useState(initialTarget);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [commitError, setCommitError] = useState("");
  const [loading, setLoading] = useState(Boolean(initialTarget));
  const [saving, setSaving] = useState(false);
  const [revision, setRevision] = useState(0);
  const requestInProgress = useRef(false);

  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);

  useEffect(() => {
    if (!target) return;
    let current = true;
    api(`appointments/${appointment.id}/reschedule-preview?target_slot_id=${encodeURIComponent(target)}`).then(
      (data: Preview) => { if (current) setPreview(data); },
      (error: unknown) => { if (current) setPreviewError(errorMessage(error)); },
    ).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [api, appointment.id, target, revision]);

  function resetPreview(next: string) {
    setPreview(null);
    setPreviewError("");
    setLoading(Boolean(next));
  }

  function chooseSlot(next: string) {
    if (next === target) return;
    setCommitError("");
    resetPreview(next);
    setTarget(next);
  }

  async function confirm() {
    if (preview?.status !== "available" || loading || requestInProgress.current) return;
    requestInProgress.current = true;
    setSaving(true);
    setCommitError("");
    try {
      const result = await api(`appointments/${appointment.id}/reschedule`, "POST", {
        target_slot_id: preview.target.id, preview_version: preview.preview_version,
      });
      onMoved(result.starts_at);
    } catch (err) {
      setCommitError(errorMessage(err));
      resetPreview(target);
      setRevision((n) => n + 1);
      void refresh();
    } finally {
      requestInProgress.current = false;
      setSaving(false);
    }
  }

  const source = preview ? preview.source : slots.find((slot) => slot.id === appointment.slot_id);
  const reserved = new Set(appointments.map((item) => item.slot_id));
  const choices = slots.filter((slot) => slot.id !== appointment.slot_id &&
    (slot.id === target || (!reserved.has(slot.id) && Date.parse(slot.starts_at) > Date.now())));
  const unknownTarget = Boolean(target) && !choices.some((slot) => slot.id === target);

  return (
    <dialog ref={dialog} className="appointment-move-dialog card" aria-labelledby="appointment-move-title"
      onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}>
      <h2 id="appointment-move-title">Randevuyu taşı</h2>
      <p>{appointment.customer}</p>
      <dl className="analysis-facts">
        <div><dt>Eski saat</dt><dd>{source ? formatDate(source.starts_at) : "—"}</dd></div>
        <div><dt>Yeni saat</dt><dd>{preview ? formatDate(preview.target.starts_at) : "—"}</dd></div>
      </dl>
      <label>Hedef saat{" "}
        <select value={target} disabled={saving} onChange={(event) => chooseSlot(event.target.value)}>
          <option value="">Saat seçin</option>
          {unknownTarget && <option value={target}>Seçilen saat</option>}
          {choices.map((slot) => <option key={slot.id} value={slot.id}>{formatDate(slot.starts_at)}</option>)}
        </select>
      </label>
      {!choices.length && !target && <p className="muted">Takvimde seçilebilecek boş saat görünmüyor.</p>}
      {loading && <p role="status">Müsaitlik ve kapasite kontrol ediliyor…</p>}
      {commitError && <p role="alert">{commitError}</p>}
      {previewError && <p role="alert">{previewError}</p>}
      {preview && <>
        <p><strong>Saat durumu</strong> · {preview.message}</p>
        <p><strong>Lift ve istasyon</strong> · {liftLabels[preview.lift_status]}</p>
        {preview.alternatives.length > 0 && <>
          <h3>Güncel alternatif saatler</h3>
          <ul>{preview.alternatives.map((slot) => <li key={slot.id}>
            <button className="secondary" disabled={saving} onClick={() => chooseSlot(slot.id)}>
              {formatDate(slot.starts_at)}
            </button>
          </li>)}</ul>
        </>}
      </>}
      <div className="row">
        <button className="secondary" disabled={saving} onClick={onClose}>Vazgeç</button>
        <button disabled={saving || loading || preview?.status !== "available"} onClick={() => void confirm()}>
          {saving ? "Taşınıyor…" : "Taşımayı onayla"}
        </button>
      </div>
    </dialog>
  );
}
