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

from backend.vin_ruhsat_decoder import (
    TURKISH_PHONETIC_ALPHABET,
    decode_phonetic_spelling,
    decode_ruhsat_text,
    extract_text_from_ruhsat_image,
    parse_spoken_number,
    process_inbound_ruhsat_image,
)

__all__ = [
    "TURKISH_PHONETIC_ALPHABET",
    "decode_phonetic_spelling",
    "decode_ruhsat_text",
    "extract_text_from_ruhsat_image",
    "parse_spoken_number",
    "process_inbound_ruhsat_image",
]

