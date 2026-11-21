# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Otomotiv LLM Veriseti Üretici CLI Komut Dosyası."""

import argparse
import sys
from pathlib import Path

# Proje kök dizinini sys.path'e ekle
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.dataset_generator import export_dataset_file


def main():
    parser = argparse.ArgumentParser(description="FreyaTTS Otomotiv LLM Fine-Tuning Veriseti Üreticisi")
    parser.add_argument("--count", type=int, default=50, help="Üretilecek kayıt sayısı (varsayılan: 50)")
    parser.add_argument("--format", type=str, default="alpaca", choices=["alpaca", "sharegpt"], help="Format (alpaca | sharegpt)")
    parser.add_argument("--output", type=str, required=True, help="Hedef JSONL dosya yolu")
    parser.add_argument("--seed", type=int, default=42, help="Rastgelelik tohumu (varsayılan: 42)")

    args = parser.parse_args()

    try:
        out_path = export_dataset_file(
            format=args.format,
            output_path=Path(args.output),
            count=args.count,
            seed=args.seed,
        )
        print(f"Başarıyla üretildi: {out_path} ({args.count} kayıt, format: {args.format})")
        sys.exit(0)
    except Exception as e:
        print(f"Hata: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
