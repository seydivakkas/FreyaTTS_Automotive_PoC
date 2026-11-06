import type { ActionFn } from "./api";
import type { ApiFn } from "./ui";

type Props = {
  password: string;
  setPassword: (v: string) => void;
  busy: boolean;
  error: string;
  action: ActionFn;
  api: ApiFn;
  onLogged: () => void;
};

export function LoginGate({ password, setPassword, busy, error, action, api, onLogged }: Props) {
  return (
    <main className="login">
      <div className="brand">
        f<span>reya</span>
        <small>OTOMOTİV ASİSTANI</small>
      </div>
      <h1>Yerel ses, doğal iletişim.</h1>
      <p>Yönetim paneline güvenli giriş yapın.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          action(async () => {
            await api("readiness");
            onLogged();
          });
        }}
      >
        <label>
          Yönetici parolası
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button disabled={busy}>Panele giriş →</button>
      </form>
      {error && (
        <div role="alert" className="error">
          {error}
        </div>
      )}
    </main>
  );
}
