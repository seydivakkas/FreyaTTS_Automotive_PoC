import type { ActionFn, Quote, Vehicle } from "../api";
import type { ApiFn } from "../ui";

type Props = {
  api: ApiFn;
  action: ActionFn;
  refresh: () => Promise<void>;
  busy: boolean;
  vehicles: Vehicle[];
  quotes: Quote[];
};

export function VehiclesTab({ api, action, refresh, busy, vehicles, quotes }: Props) {
  return (
    <>
      <section>
        <h2>Araç ekle</h2>
        <form
          className="inline"
          onSubmit={(e) => {
            e.preventDefault();
            const f = e.currentTarget,
              d = new FormData(f);
            action(async () => {
              await api("vehicles", "POST", {
                description: d.get("description"),
                plate: d.get("plate"),
              });
              f.reset();
              await refresh();
            });
          }}
        >
          <label>
            Marka ve model
            <input name="description" required placeholder="Volkswagen Passat" />
          </label>
          <label>
            Plaka
            <input name="plate" placeholder="34 ABC 123" />
          </label>
          <button disabled={busy}>Kaydet</button>
        </form>
      </section>
      <section>
        <h2>Kayıtlı araçlar ve ekspertiz fiyatı</h2>
        {vehicles.length ? (
          vehicles.map((v) => (
            <form
              className="inline row"
              key={v.id}
              onSubmit={(e) => {
                e.preventDefault();
                const d = new FormData(e.currentTarget);
                action(async () => {
                  await api("quotes", "POST", {
                    vehicle_id: v.id,
                    amount_kurus: Math.round(Number(d.get("price")) * 100),
                  });
                  await refresh();
                });
              }}
            >
              <div>
                <b>{v.description}</b>
                <small>{v.plate || "Plaka girilmedi"}</small>
              </div>
              <label>
                Fiyat (TL)
                <input
                  name="price"
                  defaultValue={
                    (quotes.find((q) => q.vehicle_id === v.id)?.amount_kurus ?? NaN) / 100 ||
                    undefined
                  }
                  type="number"
                  min="0.01"
                  step="0.01"
                  required
                />
              </label>
              <button className="secondary">Fiyatı kaydet</button>
            </form>
          ))
        ) : (
          <p className="muted">Henüz araç kaydı yok.</p>
        )}
      </section>
    </>
  );
}
