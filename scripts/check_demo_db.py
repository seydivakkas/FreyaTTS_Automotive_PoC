"""Demo veritabanı durumunu inceler ve eksik fixture'ları ekler."""
import sqlite3
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")
DB_PATH = "data/demo/assistant.db"

def inspect_db():
    if not os.path.exists(DB_PATH):
        print(f"[HATA] Demo DB bulunamadı: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"Tablolar: {tables}")

    for t in ["vehicles", "quotes", "slots", "appointments"]:
        if t in tables:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"  {t}: {cur.fetchone()[0]} kayit")
        else:
            print(f"  {t}: TABLO YOK")

    # Corolla var mı?
    if "vehicles" in tables:
        cur.execute("SELECT id, description, plate FROM vehicles WHERE description LIKE '%orolla%'")
        rows = cur.fetchall()
        if rows:
            print(f"\nCorolla araçları:")
            for r in rows:
                print(f"  id={r[0][:8]}... desc={r[1]} plate={r[2]!r}")
        else:
            print("\n[!] Corolla bulunamadı")

    # Yarın sabahın slotları var mı?
    if "slots" in tables:
        tomorrow = (datetime.now(TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
        cur.execute("SELECT id, starts_at FROM slots WHERE starts_at LIKE ? ORDER BY starts_at", (f"{tomorrow}%",))
        slots = cur.fetchall()
        if slots:
            print(f"\nYarın ({tomorrow}) slotları:")
            for s in slots:
                # Bu slotta randevu var mı?
                cur.execute("SELECT id, status, confirmed FROM appointments WHERE slot_id=?", (s[0],))
                apps = cur.fetchall()
                status = f"DOLU ({apps[0][1]})" if apps else "AÇIK"
                print(f"  {s[1]} → {status}")
        else:
            print(f"\n[!] Yarın ({tomorrow}) için slot bulunamadı")

    conn.close()

if __name__ == "__main__":
    inspect_db()
