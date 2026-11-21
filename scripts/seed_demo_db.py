"""
Demo veritabanına test koşusu için dondurulmuş fixture yazar.

Çalıştır:
    .venv\Scripts\python.exe scripts/seed_demo_db.py

Yazar:
  - Toyota Corolla aracını (plaka boş, diyalog doldurur)
  - 2.500 TL (250.000 kuruş) standart ekspertiz paketi
  - Yarın: 09:00 DOLU, 10:00 AÇIK, 11:00 AÇIK
  - 09:00 slotuna yer tutucu randevu (başka müşteri)

Alembic migration uygulanmış ve tablolar mevcut olmalı.
"""
import sqlite3
import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")
DB_PATH = "data/demo/assistant.db"


def uid():
    return str(uuid.uuid4())


def now_utc():
    return datetime.now(ZoneInfo("UTC")).isoformat()


def seed():
    if not os.path.exists(DB_PATH):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        print(f"[!] Demo DB bulunamadı: {DB_PATH}")
        print("    Önce: BASLAT.bat --demo  (ya da alembic upgrade head ile tabloları oluştur)")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # PRAGMA
    cur.execute("PRAGMA foreign_keys=ON")

    tomorrow = (datetime.now(TZ) + timedelta(days=1))
    t_09 = tomorrow.replace(hour=9,  minute=0, second=0, microsecond=0)
    t_10 = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    t_11 = tomorrow.replace(hour=11, minute=0, second=0, microsecond=0)
    date_str = tomorrow.strftime("%Y-%m-%d")

    # Mevcut test slotlarını temizle (sadece yarın)
    cur.execute(
        "DELETE FROM appointments WHERE slot_id IN "
        "(SELECT id FROM slots WHERE starts_at LIKE ? AND id NOT IN "
        "(SELECT slot_id FROM appointments WHERE idempotency_key NOT LIKE 'seed-%'))",
        (f"{date_str}%",)
    )
    cur.execute("DELETE FROM slots WHERE starts_at LIKE ? AND id NOT IN "
                "(SELECT slot_id FROM appointments WHERE slot_id IS NOT NULL)",
                (f"{date_str}%",))

    # Corolla var mı?
    cur.execute("SELECT id FROM vehicles WHERE description LIKE '%orolla%' LIMIT 1")
    row = cur.fetchone()
    if row:
        vehicle_id = row[0]
        print(f"[OK] Mevcut Corolla kullanılıyor: {vehicle_id[:8]}...")
    else:
        vehicle_id = uid()
        cur.execute(
            "INSERT INTO vehicles (id, description, plate, vin) VALUES (?, ?, ?, ?)",
            (vehicle_id, "Toyota Corolla", "", "")
        )
        print(f"[+] Corolla eklendi: {vehicle_id[:8]}...")

    # Mevcut quote var mı?
    cur.execute("SELECT id FROM quotes WHERE vehicle_id=? LIMIT 1", (vehicle_id,))
    if not cur.fetchone():
        quote_id = uid()
        cur.execute(
            "INSERT INTO quotes (id, vehicle_id, amount_kurus) VALUES (?, ?, ?)",
            (quote_id, vehicle_id, 250000)
        )
        print(f"[+] Quote eklendi: 2.500 TL")

    # Slotlar
    slots = {}
    for label, dt in [("09", t_09), ("10", t_10), ("11", t_11)]:
        iso = dt.isoformat()
        cur.execute("SELECT id FROM slots WHERE starts_at=?", (iso,))
        row = cur.fetchone()
        if row:
            slots[label] = row[0]
            print(f"[OK] Slot {label}:00 mevcut: {slots[label][:8]}...")
        else:
            slot_id = uid()
            cur.execute("INSERT INTO slots (id, starts_at) VALUES (?, ?)", (slot_id, iso))
            slots[label] = slot_id
            print(f"[+] Slot {label}:00 eklendi")

    # 09:00'ı doldur (yer tutucu)
    cur.execute("SELECT id FROM appointments WHERE slot_id=? AND idempotency_key='seed-occupied-09'", (slots["09"],))
    if not cur.fetchone():
        occ_id = uid()
        cur.execute(
            "INSERT INTO appointments (id, slot_id, vehicle_id, customer, idempotency_key, confirmed, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (occ_id, slots["09"], vehicle_id, "Mevcut Müşteri", "seed-occupied-09", 1, "confirmed", now_utc())
        )
        print(f"[+] 09:00 randevusu dolduruldu (seed-occupied-09)")
    else:
        print(f"[OK] 09:00 zaten dolu")

    # 10:00 ve 11:00 açık olmalı
    for label in ["10", "11"]:
        cur.execute(
            "SELECT id FROM appointments WHERE slot_id=? AND idempotency_key != 'seed-occupied-09'",
            (slots[label],)
        )
        rows = cur.fetchall()
        if rows:
            print(f"[!] {label}:00 slotunda {len(rows)} beklenmedik randevu var — siliniyor")
            for r in rows:
                cur.execute("DELETE FROM appointments WHERE id=?", (r[0],))

    conn.commit()
    conn.close()

    print(f"\n✓ Demo DB hazır: {DB_PATH}")
    print(f"  Corolla: {vehicle_id[:8]}...")
    print(f"  Tarih  : {date_str}")
    print(f"  09:00  : DOLU (seed-occupied-09)")
    print(f"  10:00  : AÇIK")
    print(f"  11:00  : AÇIK")
    print(f"  Fiyat  : 2.500 TL (250.000 kuruş)")


if __name__ == "__main__":
    seed()
