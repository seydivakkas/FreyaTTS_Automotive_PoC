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

from pathlib import Path

def patch_sft_early_check():
    path = Path("vendor/FreyaTTS/training/sft.py")
    content = path.read_text(encoding="utf-8")

    # Remove second duplicate check if present
    content = content.replace(
        '    if not args.init or not os.path.exists(args.init):\n        raise RuntimeError("Base checkpoint missing or mismatched")\n\n    try:',
        '    try:'
    )

    # Ensure pre-flight check happens right at the start of main()
    old_main_start = "def main():\n    args = parse_args()"
    new_main_start = (
        "def main():\n"
        "    args = parse_args()\n"
        "    if not args.init or not os.path.exists(args.init):\n"
        "        raise RuntimeError(\"Base checkpoint missing or mismatched\")\n"
        "    if not os.path.exists(args.vocab_json):\n"
        "        if os.path.exists(\"config/freya_vocab.json\"):\n"
        "            args.vocab_json = \"config/freya_vocab.json\"\n"
        "        elif os.path.exists(\"vendor/FreyaTTS/freyatts/char_vocab.json\"):\n"
        "            args.vocab_json = \"vendor/FreyaTTS/freyatts/char_vocab.json\""
    )
    if "if not args.init or not os.path.exists(args.init):" not in content[:content.find("torch.manual_seed")]:
        content = content.replace(old_main_start, new_main_start)
    path.write_text(content, encoding="utf-8")
    print("Updated sft.py early pre-flight check")

if __name__ == "__main__":
    patch_sft_early_check()
