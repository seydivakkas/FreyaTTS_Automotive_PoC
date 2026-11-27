"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""

"""Adım 6: Canlı Mikrofon Kabul Koşuları & Otomotiv Terim Doğrulama CLI aracı.

Kullanım örnekleri:
    .venv\\Scripts\\python.exe -m scripts.voice_acceptance_protocol prepare
    .venv\\Scripts\\python.exe -m scripts.voice_acceptance_protocol start --scenario run_1_plate_correction --speaker seydi
    .venv\\Scripts\\python.exe -m scripts.voice_acceptance_protocol verify <RUN_ID> --masked
    .venv\\Scripts\\python.exe -m scripts.voice_acceptance_protocol terminology-audit
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.acceptance_protocol import (  # noqa: E402
    ACCEPTANCE_SCENARIOS,
    finish_and_verify_run,
    get_prerequisites_status,
    mask_acceptance_report,
    prepare_poc_acceptance_fixtures,
    start_acceptance_run,
)
from backend.automotive_terminology import run_terminology_verification_suite  # noqa: E402
from backend.db import Session  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Canlı Mikrofon Kabul ve Terim Doğrulama Protokolü")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prepare", help="Bölüm 10 PoC kabul fikstürünü hazırla")
    p_prep.add_argument("--reset", action="store_true", help="Önceki PoC doluluk kaydını sıfırla")

    sub.add_parser("prereqs", help="Ön koşulları ve model/DB durumunu yazdır")

    p_start = sub.add_parser("start", help="Canlı mikrofon kabul koşusu başlat (Before Snapshot)")
    p_start.add_argument("--scenario", choices=list(ACCEPTANCE_SCENARIOS.keys()), required=True)
    p_start.add_argument("--speaker", default="", help="Konuşmacı etiketi")
    p_start.add_argument("--env", default="quiet_room", choices=["quiet_room", "in_car_noise", "telephony_pbx", "virtual_mic"])
    p_start.add_argument("--notes", default="")

    p_verify = sub.add_parser("verify", help="Koşuyu değerlendir ve katman kanıtı üret (After Diff)")
    p_verify.add_argument("run_id", help="start komutuyla üretilen run_id")
    p_verify.add_argument("--masked", action="store_true", help="KVKK uyumlu maskeli çıktı yazdır")

    sub.add_parser("terminology-audit", help="Otomotiv Terim Doğrulama Protokolünü çalıştır")

    args = parser.parse_args()

    with Session() as db:
        if args.cmd == "prereqs":
            print(json.dumps(get_prerequisites_status(db), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "prepare":
            print(json.dumps(prepare_poc_acceptance_fixtures(db, reset_existing=args.reset), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "start":
            res = start_acceptance_run(
                db,
                scenario_id=args.scenario,
                speaker_label=args.speaker,
                environment=args.env,
                notes=args.notes,
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "verify":
            res = finish_and_verify_run(db, args.run_id)
            out = mask_acceptance_report(res) if args.masked else res
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0 if res.get("status") == "PASS" else 1
        if args.cmd == "terminology-audit":
            res = run_terminology_verification_suite(db=db)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0 if res.get("failed", 1) == 0 else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
