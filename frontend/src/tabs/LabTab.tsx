import type { ActionFn } from "../api";
import type { ApiFn, RawApiFn } from "../ui";

type Props = {
  api: ApiFn;
  rawApi: RawApiFn;
  action: ActionFn;
  text: string;
  setText: (v: string) => void;
  normalized: string;
  setNormalized: (v: string) => void;
  audioUrl: string;
  setAudioUrl: (v: string) => void;
};

export function LabTab({ api, rawApi, action, text, setText, normalized, setNormalized, audioUrl, setAudioUrl }: Props) {
  return (
    <section>
      <h2>Türkçe telaffuz denemesi</h2>
      <label>
        Kaynak metin
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} />
      </label>
      <div className="inline">
        <button
          onClick={() =>
            action(async () =>
              setNormalized((await api("normalize", "POST", { text })).normalized),
            )
          }
        >
          Normalizasyonu incele
        </button>
        <button
          className="secondary"
          onClick={() =>
            action(async () => {
              const r = await rawApi("synthesize", "POST", { text });
              if (audioUrl) URL.revokeObjectURL(audioUrl);
              setAudioUrl(URL.createObjectURL(await r.blob()));
            })
          }
        >
          Sesi üret
        </button>
      </div>
      {normalized && <p className="bubble">{normalized}</p>}
      {audioUrl && <audio controls src={audioUrl} />}
    </section>
  );
}
