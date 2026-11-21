"""
Gerçek mikrofon kabul testi — sonuç gözlemci

Her koşudan ÖNCE çalıştır:
    .venv\Scripts\python.exe scripts\acceptance_snapshot.py --before KOSU_ADI

Her koşudan SONRA çalıştır:
    .venv\Scripts\python.exe scripts\acceptance_snapshot.py --after KOSU_ADI

Çıktı: data/acceptance/<KOSU_ADI>_before.json ve _after.json
Fark:   data/acceptance/<KOSU_ADI>_diff.json
"""
import argparse
import json
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")
DB_PATH = "data/demo/assistant.db"
OUT_DIR = "data/acceptance"


def snapshot(label: str) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Tüm slotları ve randevuları çek
    cur.execute("""
        SELECT s.id, s.starts_at,
               a.id AS app_id, a.customer, a.status, a.confirmed,
               a.idempotency_key, a.created_at,
               v.description, v.plate
        FROM slots s
        LEFT JOIN appointments a ON a.slot_id = s.id
        LEFT JOIN vehicles v ON a.vehicle_id = v.id
        ORDER BY s.starts_at
    """)
    slots = [dict(r) for r in cur.fetchall()]

    # Turns şeması: id, conversation_id, role, text, metrics, created_at
    # plate_candidate / intent / turn_id yok — metrics JSON içinde olabilir
    cur.execute("""
        SELECT c.id AS conv_id, c.created_at AS conv_at,
               t.id AS turn_id, t.role, t.text, t.metrics, t.created_at AS turn_at
        FROM conversations c
        JOIN turns t ON t.conversation_id = c.id
        ORDER BY c.created_at DESC, t.created_at ASC
        LIMIT 50
    """)
    turns = [dict(r) for r in cur.fetchall()]

    conn.close()

    return {
        "label": label,
        "timestamp": datetime.now(TZ).isoformat(),
        "slots": slots,
        "recent_turns": turns,
    }


def diff_snapshots(before: dict, after: dict) -> dict:
    before_apps = {s["app_id"] for s in before["slots"] if s["app_id"]}
    after_apps  = {s["app_id"] for s in after["slots"]  if s["app_id"]}

    new_app_ids = after_apps - before_apps

    new_apps = []
    for s in after["slots"]:
        if s["app_id"] in new_app_ids:
            new_apps.append({
                "slot":    s["starts_at"],
                "app_id":  s["app_id"],
                "customer": s["customer"],
                "plate":   s["plate"],
                "status":  s["status"],
                "confirmed": s["confirmed"],
                "idem_key": s["idempotency_key"],
            })

    before_turn_ids = {t["turn_id"] for t in before["recent_turns"] if t.get("turn_id")}
    new_turns = [t for t in after["recent_turns"]
                 if t.get("turn_id") and t["turn_id"] not in before_turn_ids]
    # Fallback: turns id ile de karşılaştır
    if not new_turns:
        before_ids = {t.get("turn_id") or t.get("id") for t in before["recent_turns"]}
        new_turns = [t for t in after["recent_turns"]
                     if (t.get("turn_id") or t.get("id")) not in before_ids]

    return {
        "new_appointments_count": len(new_apps),
        "new_appointments": new_apps,
        "new_turns_count": len(new_turns),
        "new_turns": new_turns,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", metavar="NAME", help="Koşu öncesi snapshot")
    parser.add_argument("--after",  metavar="NAME", help="Koşu sonrası snapshot + diff")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    if args.before:
        name = args.before
        data = snapshot(f"before_{name}")
        path = os.path.join(OUT_DIR, f"{name}_before.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[✓] Snapshot kaydedildi: {path}")
        print(f"    Toplam slot: {len(data['slots'])}")
        total_apps = sum(1 for s in data["slots"] if s["app_id"])
        print(f"    Toplam randevu: {total_apps}")

    elif args.after:
        name = args.after
        after_data = snapshot(f"after_{name}")
        after_path = os.path.join(OUT_DIR, f"{name}_after.json")
        with open(after_path, "w", encoding="utf-8") as f:
            json.dump(after_data, f, ensure_ascii=False, indent=2)
        print(f"[✓] After snapshot: {after_path}")

        before_path = os.path.join(OUT_DIR, f"{name}_before.json")
        if os.path.exists(before_path):
            with open(before_path, encoding="utf-8") as f:
                before_data = json.load(f)
            d = diff_snapshots(before_data, after_data)
            diff_path = os.path.join(OUT_DIR, f"{name}_diff.json")
            with open(diff_path, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)

            print(f"\n--- FARK ({name}) ---")
            print(f"Yeni randevu sayısı : {d['new_appointments_count']}")
            for a in d["new_appointments"]:
                print(f"  Slot   : {a['slot']}")
                print(f"  Plaka  : {a['plate']!r}")
                print(f"  Müşteri: {a['customer']!r}")
                print(f"  Durum  : {a['status']} / confirmed={a['confirmed']}")
                print(f"  Idem   : {a['idem_key']}")
            print(f"Yeni diyalog tur sayısı: {d['new_turns_count']}")
            for t in d["new_turns"][:10]:
                print(f"  [{t.get('role','?'):>10}] {str(t.get('text',''))[:80]}")
                # metrics JSON içinden plate bilgisi çıkarmaya çalış
                try:
                    import json as _j
                    m = _j.loads(t.get("metrics") or "{}")
                    if m.get("plate"):
                        print(f"             → plaka: {m['plate']}")
                except Exception:
                    pass
            print(f"Diff kaydedildi: {diff_path}")
        else:
            print(f"[!] Before snapshot bulunamadı: {before_path}")
            print("    Önce --before ile snapshot alın.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
