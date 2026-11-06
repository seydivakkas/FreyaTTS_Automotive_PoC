import { useEffect, useState, useMemo } from "react";

export type LexiconEntry = {
  term: string;
  spoken: string;
  category: string;
  is_base: boolean;
  is_override: boolean;
};

type Props = {
  api: (path: string, method?: string, body?: unknown) => Promise<any>;
};

export function LexiconPanel({ api }: Props) {
  const [entries, setEntries] = useState<LexiconEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Form State
  const [term, setTerm] = useState("");
  const [spoken, setSpoken] = useState("");
  const [category, setCategory] = useState("brand");
  const [editingTerm, setEditingTerm] = useState<string | null>(null);

  // Filter State
  const [search, setSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [onlyCustom, setOnlyCustom] = useState(false);

  // Live Normalizer Test State
  const [testText, setTestText] = useState(
    "Volkswagen Passat 1.5 TSI aracınız için ekspertiz fiyatı 1.250 TL."
  );
  const [normalizedResult, setNormalizedResult] = useState("");
  const [testing, setTesting] = useState(false);

  async function act(fn: () => Promise<void>) {
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      await fn();
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    const list = await api("lexicon");
    setEntries(list);
  }

  useEffect(() => {
    act(refresh);
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!term.trim() || !spoken.trim()) {
      setError("Terim ve telaffuz boş olamaz.");
      return;
    }
    await act(async () => {
      const res = await api("lexicon", "POST", {
        term: term.trim(),
        spoken: spoken.trim(),
        category,
      });
      setSuccess(
        `'${res.term}' telaffuzu kaydedildi (${res.spoken}). Normalizer güncellendi.`
      );
      setTerm("");
      setSpoken("");
      setEditingTerm(null);
      await refresh();
    });
  }

  function handleEdit(item: LexiconEntry) {
    setTerm(item.term);
    setSpoken(item.spoken);
    setCategory(item.category || "custom");
    setEditingTerm(item.term);
    setError("");
    setSuccess(`'${item.term}' düzenleniyor...`);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function handleCancelEdit() {
    setTerm("");
    setSpoken("");
    setEditingTerm(null);
    setSuccess("");
    setError("");
  }

  async function handleDelete(item: LexiconEntry) {
    const actionDesc = item.is_base
      ? `'${item.term}' için yapılan özelleştirme kaldırılıp varsayılan telaffuza dönülsün mü?`
      : `'${item.term}' terimi sözlükten silinsin mi?`;
    if (!window.confirm(actionDesc)) return;

    await act(async () => {
      const res = await api("lexicon/" + encodeURIComponent(item.term), "DELETE");
      setSuccess(
        res.reverted_to_base
          ? `'${item.term}' varsayılan telaffuzuna döndürüldü.`
          : `'${item.term}' silindi.`
      );
      if (editingTerm === item.term) {
        handleCancelEdit();
      }
      await refresh();
    });
  }

  async function handleReset() {
    if (
      !window.confirm(
        "Tüm özelleştirilmiş ve yeni eklenen sözlük terimleri silinip varsayılan otomotiv sözlüğüne sıfırlansın mı?"
      )
    ) {
      return;
    }
    await act(async () => {
      const res = await api("lexicon/reset", "POST");
      setSuccess(`Sözlük varsayılan ayarlara sıfırlandı (${res.count} terim).`);
      handleCancelEdit();
      await refresh();
    });
  }

  async function handleTest() {
    if (!testText.trim()) return;
    setError("");
    setTesting(true);
    try {
      const res = await api("normalize", "POST", { text: testText.trim() });
      setNormalizedResult(res.normalized);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setTesting(false);
    }
  }

  // Statistics
  const totalCount = entries.length;
  const customCount = entries.filter((e) => !e.is_base).length;
  const overrideCount = entries.filter((e) => e.is_override).length;
  const baseCount = entries.filter((e) => e.is_base && !e.is_override).length;

  // Filtered List
  const filteredEntries = useMemo(() => {
    return entries.filter((item) => {
      if (onlyCustom && item.is_base && !item.is_override) {
        return false;
      }
      if (selectedCategory !== "all" && item.category !== selectedCategory) {
        return false;
      }
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        const termMatch = item.term.toLowerCase().includes(q);
        const spokenMatch = item.spoken.toLowerCase().includes(q);
        const catMatch = item.category.toLowerCase().includes(q);
        return termMatch || spokenMatch || catMatch;
      }
      return true;
    });
  }, [entries, search, selectedCategory, onlyCustom]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    entries.forEach((e) => {
      if (e.category) set.add(e.category);
    });
    return Array.from(set).sort();
  }, [entries]);

  return (
    <>
      <div className="stats">
        <article>
          <small>Toplam Terim</small>
          <strong>{totalCount}</strong>
        </article>
        <article>
          <small>Özelleştirilmiş / Eklenen</small>
          <strong>{customCount + overrideCount}</strong>
        </article>
        <article>
          <small>Varsayılan Otomotiv</small>
          <strong>{baseCount}</strong>
        </article>
      </div>

      {error && (
        <div role="alert" className="error" style={{ marginTop: "18px" }}>
          {error}
        </div>
      )}
      {success && (
        <div
          role="status"
          className="bubble"
          style={{
            marginTop: "18px",
            background: "#1c382f",
            borderColor: "#347458",
            border: "1px solid",
          }}
        >
          <b>Başarılı</b>
          {success}
        </div>
      )}

      {/* Terim Ekleme / Güncelleme Formu */}
      <section>
        <h2>{editingTerm ? `Terimi Güncelle: ${editingTerm}` : "Yeni Telaffuz / Terim Ekle"}</h2>
        <p className="muted">
          Marka, model, motor kodu veya teknik terimlerin Türkçe ses motoru
          (FreyaTTS) tarafından nasıl telaffuz edileceğini tanımlayın. Otomotiv
          normalizer kuralları canlı görüşmelerde bu sözlüğü otomatik kullanır.
        </p>

        <form onSubmit={handleSave} className="inline" style={{ marginTop: "16px" }}>
          <label style={{ flex: "1 1 200px" }}>
            Terim (Yazılış)
            <input
              required
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder="Örn: BMW 320i, Chery Tiggo, TDI, vb."
            />
          </label>

          <label style={{ flex: "1 1 200px" }}>
            Okunuş / Telaffuz
            <input
              required
              value={spoken}
              onChange={(e) => setSpoken(e.target.value)}
              placeholder="Örn: be me ve üç yüz yirmi i, çeri tigo"
            />
          </label>

          <label style={{ flex: "1 1 140px" }}>
            Kategori
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="brand">Marka (brand)</option>
              <option value="model">Model (model)</option>
              <option value="package">Donanım / Paket (package)</option>
              <option value="technical">Teknik / Kısaltma (technical)</option>
              <option value="custom">Özel Terim (custom)</option>
            </select>
          </label>

          <div style={{ display: "flex", gap: "10px", alignItems: "flex-end" }}>
            <button type="submit" disabled={loading}>
              {editingTerm ? "Güncellemeyi Kaydet" : "Sözlüğe Ekle"}
            </button>
            {editingTerm && (
              <button
                type="button"
                className="secondary"
                onClick={handleCancelEdit}
                disabled={loading}
              >
                Vazgeç
              </button>
            )}
          </div>
        </form>
      </section>

      {/* Canlı Normalizer Test Alanı */}
      <section>
        <h2>Canlı Ses / Telaffuz Testi</h2>
        <p className="muted">
          Yazacağınız cümlenin sözlükteki telaffuz ve Türkçe ek kurallarıyla
          nasıl seslendirileceğini anında simüle edin.
        </p>
        <label>
          Test Metni
          <textarea
            rows={2}
            value={testText}
            onChange={(e) => setTestText(e.target.value)}
            placeholder="Test edilecek metni yazın..."
          />
        </label>
        <div className="inline">
          <button type="button" onClick={handleTest} disabled={testing || !testText.trim()}>
            {testing ? "Dönüştürülüyor..." : "Normalizasyonu Test Et"}
          </button>
        </div>
        {normalizedResult && (
          <div style={{ marginTop: "16px" }}>
            <small style={{ marginBottom: "6px" }}>SES MOTORUNUN OKUYACAĞI METİN:</small>
            <p className="bubble">{normalizedResult}</p>
          </div>
        )}
      </section>

      {/* Terimler Tablosu ve Filtreler */}
      <section>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "14px",
            marginBottom: "16px",
          }}
        >
          <h2>Kayıtlı Sözlük Terimleri ({filteredEntries.length})</h2>
          <button
            type="button"
            className="danger"
            onClick={handleReset}
            disabled={loading}
            style={{ fontSize: "12px", padding: "8px 14px" }}
          >
            Varsayılan Sözlüğe Sıfırla ↺
          </button>
        </div>

        {/* Filtre Barı */}
        <div
          className="inline"
          style={{
            background: "#0e1522",
            padding: "14px",
            borderRadius: "10px",
            border: "1px solid #2a3344",
            marginBottom: "20px",
          }}
        >
          <label style={{ flex: "2 1 200px" }}>
            Arama
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Terim veya telaffuz ara..."
            />
          </label>

          <label style={{ flex: "1 1 140px" }}>
            Kategori Filtresi
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
            >
              <option value="all">Tüm Kategoriler ({entries.length})</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c} ({entries.filter((e) => e.category === c).length})
                </option>
              ))}
            </select>
          </label>

          <label
            style={{
              flex: "1 1 200px",
              display: "flex",
              alignItems: "center",
              gap: "8px",
              cursor: "pointer",
              fontSize: "13px",
              paddingTop: "24px",
            }}
          >
            <input
              type="checkbox"
              checked={onlyCustom}
              onChange={(e) => setOnlyCustom(e.target.checked)}
              style={{ width: "18px", height: "18px", accentColor: "#a7f3ce" }}
            />
            Sadece Özelleştirilen / Eklenenleri Göster ({customCount + overrideCount})
          </label>
        </div>

        {/* Tablo */}
        <div style={{ overflowX: "auto" }}>
          <div className="table-wrap"><table className="lexicon-table">
            <thead>
              <tr>
                <th>Terim</th>
                <th>Okunuş / Telaffuz</th>
                <th>Kategori</th>
                <th>Durum</th>
                <th style={{ textAlign: "right" }}>İşlemler</th>
              </tr>
            </thead>
            <tbody>
              {filteredEntries.map((item) => (
                <tr key={item.term.toLowerCase()}>
                  <td style={{ fontWeight: 600 }}>{item.term}</td>
                  <td style={{ color: "#a7f3ce" }}>{item.spoken}</td>
                  <td>
                    <span className="badge-cat">{item.category}</span>
                  </td>
                  <td>
                    {item.is_override ? (
                      <span className="badge-override">Özelleştirildi</span>
                    ) : item.is_base ? (
                      <span className="badge-base">Varsayılan</span>
                    ) : (
                      <span className="badge-custom">Yeni Özel</span>
                    )}
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => handleEdit(item)}
                      style={{ padding: "6px 12px", fontSize: "12px", marginRight: "6px" }}
                    >
                      Düzenle
                    </button>
                    {(item.is_override || !item.is_base) && (
                      <button
                        type="button"
                        className="danger"
                        onClick={() => handleDelete(item)}
                        style={{ padding: "6px 12px", fontSize: "12px" }}
                      >
                        {item.is_override ? "Geri Al" : "Sil"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {!filteredEntries.length && (
                <tr>
                  <td colSpan={5} style={{ textAlign: "center", padding: "30px", color: "#93a0b5" }}>
                    Aranan kriterlere uygun sözlük terimi bulunamadı.
                  </td>
                </tr>
              )}
            </tbody>
          </table></div>
        </div>
      </section>
    </>
  );
}

