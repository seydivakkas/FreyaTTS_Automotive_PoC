import type { ActionFn, Appointment, Slot } from "../api";
import { formatDate } from "../ui";
import type { ApiFn } from "../ui";

type Props = {
  api: ApiFn;
  action: ActionFn;
  refresh: () => Promise<void>;
  busy: boolean;
  slots: Slot[];
  appointments: Appointment[];
};

export function AppointmentsTab({ api, action, refresh, busy, slots, appointments }: Props) {
  return (
    <>
      <section>
        <h2>Müsait saat ekle</h2>
        <form
          className="inline"
          onSubmit={(e) => {
            e.preventDefault();
            const d = new FormData(e.currentTarget);
            action(async () => {
              await api("slots", "POST", {
                starts_at: String(d.get("time")) + ":00+03:00",
              });
              await refresh();
            });
          }}
        >
          <label>
            İstanbul tarihi ve saati
            <input type="datetime-local" name="time" required />
          </label>
          <button disabled={busy}>Saat ekle</button>
        </form>
      </section>
      <section>
        <h2>Randevu takvimi</h2>
        {slots.map((s) => {
          const a = appointments.find((x) => x.slot_id === s.id && x.status === "confirmed");
          return (
            <div className="row" key={s.id}>
              <div>
                <b>{formatDate(s.starts_at)}</b>
                <small>{a ? a.customer : "Müsait"}</small>
              </div>
              {a ? (
                <button
                  className="secondary"
                  onClick={() =>
                    action(async () => {
                      await api(`appointments/${a.id}/cancel`, "POST");
                      await refresh();
                    })
                  }
                >
                  İptal et
                </button>
              ) : (
                <span className="pill">Müsait</span>
              )}
            </div>
          );
        })}
        {!slots.length && (
          <p className="muted">
            Asistanın sunabilmesi için önce müsait saat ekleyin.
          </p>
        )}
      </section>
    </>
  );
}
