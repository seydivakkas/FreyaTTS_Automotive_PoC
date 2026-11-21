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

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# TÜRKİYE İL KODLARI VE SAYI SÖZLÜĞÜ (01 - 81)
# ---------------------------------------------------------------------------
_PROVINCE_WORDS = {
    "sıfır bir": "01", "bir": "01",
    "sıfır iki": "02", "iki": "02",
    "sıfır üç": "03", "üç": "03",
    "sıfır dört": "04", "dört": "04",
    "sıfır beş": "05", "beş": "05",
    "sıfır altı": "06", "altı": "06",
    "sıfır yedi": "07", "yedi": "07",
    "sıfır sekiz": "08", "sekiz": "08",
    "sıfır dokuz": "09", "dokuz": "09",
    "on": "10", "on bir": "11", "on iki": "12", "on üç": "13", "on dört": "14",
    "on beş": "15", "on altı": "16", "on yedi": "17", "on sekiz": "18", "on dokuz": "19",
    "yirmi": "20", "yirmi bir": "21", "yirmi iki": "22", "yirmi üç": "23", "yirmi dört": "24",
    "yirmi beş": "25", "yirmi altı": "26", "yirmi yedi": "27", "yirmi sekiz": "28", "yirmi dokuz": "29",
    "otuz": "30", "otuz bir": "31", "otuz iki": "32", "otuz üç": "33", "otuz dört": "34",
    "otuz beş": "35", "otuz altı": "36", "otuz yedi": "37", "otuz sekiz": "38", "otuz dokuz": "39",
    "kırk": "40", "kırk bir": "41", "kırk iki": "42", "kırk üç": "43", "kırk dört": "44",
    "kırk beş": "45", "kırk altı": "46", "kırk yedi": "47", "kırk sekiz": "48", "kırk dokuz": "49",
    "elli": "50", "elli bir": "51", "elli iki": "52", "elli üç": "53", "elli dört": "54",
    "elli beş": "55", "elli altı": "56", "elli yedi": "57", "elli sekiz": "58", "elli dokuz": "59",
    "altmış": "60", "altmış bir": "61", "altmış iki": "62", "altmış üç": "63", "altmış dört": "64",
    "altmış beş": "65", "altmış altı": "66", "altmış yedi": "67", "altmış sekiz": "68", "altmış dokuz": "69",
    "yetmiş": "70", "yetmiş bir": "71", "yetmiş iki": "72", "yetmiş üç": "73", "yetmiş dört": "74",
    "yetmiş beş": "75", "yetmiş altı": "76", "yetmiş yedi": "77", "yetmiş sekiz": "78", "yetmiş dokuz": "79",
    "seksen": "80", "seksen bir": "81",
}

# ---------------------------------------------------------------------------
# TÜRKÇE ŞEHİR FONETİK ALFABESİ & HARF İSİMLERİ (A-Z)
# ---------------------------------------------------------------------------
_PHONETIC_CITY_MAP = {
    # A
    "adana": "A", "ankara": "A", "aydın": "A", "a": "A", "ahmet": "A",
    # B
    "bursa": "B", "bolu": "B", "balıkesir": "B", "b": "B", "be": "B",
    # C
    "ceyhan": "C", "c": "C", "ce": "C",
    # Ç
    "çanakkale": "Ç", "çankırı": "Ç", "çorum": "Ç", "ç": "Ç", "çe": "Ç",
    # D
    "denizli": "D", "diyarbakır": "D", "düzce": "D", "d": "D", "de": "D",
    # E
    "edirne": "E", "elazığ": "E", "erzincan": "E", "erzurum": "E", "eskişehir": "E", "e": "E",
    # F
    "fatsa": "F", "fethiye": "F", "f": "F", "fe": "F",
    # G
    "giresun": "G", "gaziantep": "G", "gümüşhane": "G", "g": "G", "ge": "G",
    # Ğ
    "yumuşak g": "Ğ", "yumuşak ge": "Ğ", "ğ": "Ğ",
    # H
    "hatay": "H", "hakkari": "H", "h": "H", "he": "H", "ha": "H",
    # I
    "ısparta": "I", "ığdır": "I", "ı": "I",
    # İ
    "izmir": "İ", "istanbul": "İ", "i": "İ",
    # J
    "jandarma": "J", "j": "J", "je": "J",
    # K
    "kars": "K", "konya": "K", "kastamonu": "K", "kayseri": "K", "kocaeli": "K", "kütahya": "K", "kırıkkale": "K", "k": "K", "ke": "K", "ka": "K",
    # L
    "lüleburgaz": "L", "lapseki": "L", "l": "L", "le": "L",
    # M
    "malatya": "M", "manisa": "M", "mardin": "M", "mersin": "M", "muğla": "M", "muş": "M", "m": "M", "me": "M",
    # N
    "niğde": "N", "nazilli": "N", "nevşehir": "N", "n": "N", "ne": "N",
    # O
    "ordu": "O", "osmaniye": "O", "o": "O",
    # Ö
    "ödemiş": "Ö", "ö": "Ö",
    # P
    "polatlı": "P", "pazar": "P", "p": "P", "pe": "P",
    # R
    "rize": "R", "r": "R", "re": "R",
    # S
    "samsun": "S", "sinop": "S", "sivas": "S", "sakarya": "S", "siirt": "S", "s": "S", "se": "S",
    # Ş
    "şırnak": "Ş", "şanlıurfa": "Ş", "ş": "Ş", "şe": "Ş",
    # T
    "trabzon": "T", "tokat": "T", "tekirdağ": "T", "t": "T", "te": "T",
    # U
    "uşak": "U", "urfa": "U", "u": "U",
    # Ü
    "ünye": "Ü", "ü": "Ü",
    # V
    "van": "V", "yalova": "V", "v": "V", "ve": "V",
    # Y
    "yozgat": "Y", "y": "Y", "ye": "Y",
    # Z
    "zonguldak": "Z", "z": "Z", "ze": "Z",
}

# ---------------------------------------------------------------------------
# SAYI ÇÖZÜCÜ (0 - 9999)
# ---------------------------------------------------------------------------
_DIGIT_WORDS = {
    "sıfır": 0, "bir": 1, "iki": 2, "üç": 3, "dört": 4,
    "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9,
}
_TENS_WORDS = {
    "on": 10, "yirmi": 20, "otuz": 30, "kırk": 40,
    "elli": 50, "altmış": 60, "yetmiş": 70, "seksen": 80, "doksan": 90,
}


def _tr_clean(text: str) -> str:
    """Türkçe büyük/küçük harf ve noktalama normalizasyonu."""
    t = text.replace("İ", "i").replace("I", "ı").lower()
    # Kesme işaretleri ve apostrofları temizle ("Ceyhan'ın" -> "ceyhan in", "Denizli'nin" -> "denizli nin")
    t = re.sub(r"['’´`]", " ", t)
    # Noktalama işaretlerini boşluğa çevir
    t = re.sub(r"[.,!?;:\-–—\(\)\[\]/]", " ", t)
    # Fazla boşlukları temizle
    return " ".join(t.split())


def _words_to_number(phrase: str) -> Optional[int]:
    """Türkçe söylenmiş sayı öbeğini tamsayıya çevirir (örn. 'yüz yirmi üç' -> 123)."""
    words = phrase.strip().split()
    if not words:
        return None

    # Eğer kelimelerin hepsi doğrudan rakam ise ("123", "99")
    if len(words) == 1 and words[0].isdigit():
        return int(words[0])

    total = 0
    current = 0
    i = 0
    recognized_any = False

    while i < len(words):
        w = words[i]
        if w.isdigit():
            recognized_any = True
            current += int(w)
        elif w in _DIGIT_WORDS:
            recognized_any = True
            current += _DIGIT_WORDS[w]
        elif w in _TENS_WORDS:
            recognized_any = True
            current += _TENS_WORDS[w]
        elif w == "yüz":
            recognized_any = True
            if current == 0:
                current = 100
            else:
                current *= 100
        elif w == "bin":
            recognized_any = True
            if current == 0:
                total += 1000
            else:
                total += current * 1000
            current = 0
        else:
            # Sayı sözlüğü dışı bir kelime geldiyse
            return None
        i += 1

    if recognized_any:
        return total + current
    return None


@dataclass
class PlateParseResult:
    raw_text: str
    plate: Optional[str] = None
    province: Optional[str] = None
    letters: Optional[str] = None
    digits: Optional[str] = None
    is_correction: bool = False
    correction_target: Optional[str] = None
    confidence: float = 1.0


class TurkishPlateParser:
    """Türkçe araç plakalarını yazılı ve sözlü doğal dilden çıkaran ve düzeltmeleri işleyen sınıf."""

    @staticmethod
    def parse_written(text: str) -> Optional[str]:
        """Standart yazılı plakaları yakalar (örn: '34 ABC 123', '06 ANK 99', '34AB1234')."""
        m = re.search(
            r"\b(0[1-9]|[1-7][0-9]|8[01])\s*([a-zA-ZçğıöşüÇĞİÖŞÜ]{1,3})\s*(\d{2,4})\b",
            text,
            re.IGNORECASE,
        )
        if m:
            prov = m.group(1).zfill(2)
            letters = m.group(2).upper().replace("I", "I").replace("İ", "İ")
            digits = m.group(3)
            return f"{prov} {letters} {digits}"
        return None

    @classmethod
    def parse_spoken(cls, text: str) -> Optional[PlateParseResult]:
        """Sözlü doğal Türkçe plaka ifadesini çözümler.

        Örnekler:
          - "Otuz dört Adana Bursa Ceyhan yüz yirmi üç" -> "34 ABC 123"
          - "Sıfır altı Ankara Niğde Kırıkkale doksan dokuz" -> "06 ANK 99"
          - "34 A B C 123" -> "34 ABC 123"
          - "Plakam 61 Trabzon Samsun sıfır altmış bir" -> "61 TS 061"
        """
        # 1. Önce standart yazılı kalıbı dene
        written = cls.parse_written(text)
        if written:
            parts = written.split()
            return PlateParseResult(
                raw_text=text,
                plate=written,
                province=parts[0],
                letters=parts[1],
                digits=parts[2],
                confidence=1.0,
            )

        clean = _tr_clean(text)
        words = clean.split()
        if len(words) < 3:
            return None

        # İl kodunu bul (1 veya 2 kelimelik sayı örüntüsü veya doğrudan 01-81 rakamı)
        prov_code: Optional[str] = None
        prov_end_idx = 0

        # İki kelimelik il ifadesi ("otuz dört", "sıfır altı", "on altı")
        for i in range(len(words)):
            if i + 1 < len(words):
                two_words = f"{words[i]} {words[i+1]}"
                if two_words in _PROVINCE_WORDS:
                    prov_code = _PROVINCE_WORDS[two_words]
                    prov_end_idx = i + 2
                    break
            # Tek kelimelik il ifadesi ("34", "06", "on", "yirmi")
            one_word = words[i]
            if one_word.isdigit() and 1 <= int(one_word) <= 81:
                prov_code = str(int(one_word)).zfill(2)
                prov_end_idx = i + 1
                break
            if one_word in _PROVINCE_WORDS:
                prov_code = _PROVINCE_WORDS[one_word]
                prov_end_idx = i + 1
                break

        if not prov_code:
            return None

        # Harf grubu ve Seri numarasını ayıkla
        remaining = words[prov_end_idx:]
        letters_list = []
        num_start_idx = len(remaining)

        j = 0
        while j < len(remaining):
            w = remaining[j]

            # Eğer "çift b", "iki tane a" gibi kalıp varsa
            if w in ("çift", "iki") and j + 1 < len(remaining):
                next_w = remaining[j + 1]
                # "iki tane a" kalıbı
                if next_w == "tane" and j + 2 < len(remaining):
                    target_w = remaining[j + 2]
                    if target_w in _PHONETIC_CITY_MAP:
                        char = _PHONETIC_CITY_MAP[target_w]
                        letters_list.extend([char, char])
                        j += 3
                        continue
                elif next_w in _PHONETIC_CITY_MAP:
                    char = _PHONETIC_CITY_MAP[next_w]
                    letters_list.extend([char, char])
                    j += 2
                    continue

            # Şehir veya harf eşleşmesi
            if w in _PHONETIC_CITY_MAP:
                letters_list.append(_PHONETIC_CITY_MAP[w])
                j += 1
                if len(letters_list) == 3:
                    # Türkiye plakalarında harf grubu en fazla 3 karakterdir
                    num_start_idx = j
                    break
            elif w.isalpha() and len(w) == 1:
                letters_list.append(w.upper())
                j += 1
                if len(letters_list) == 3:
                    num_start_idx = j
                    break
            else:
                # Harf olmayan bir kelimeye geldiysek sayı kısmına geçtik demektir
                num_start_idx = j
                break

        if not (1 <= len(letters_list) <= 3):
            return None

        # Kalan kelimeler sayı grubu olmalı
        num_words = remaining[num_start_idx:]
        if not num_words:
            return None

        # Sayıyı çözümle
        num_phrase = " ".join(num_words)
        # Örnek: "sıfır altmış bir" -> 061 özel durumu için baştaki sıfırları koru
        leading_zeros = 0
        for nw in num_words:
            if nw == "sıfır" or nw == "0":
                leading_zeros += 1
            else:
                break

        resolved_num = _words_to_number(num_phrase)
        if resolved_num is None:
            # Belki ardışık tekil rakamlar söylenmiştir: "bir iki üç" -> 123
            digit_seq = ""
            for nw in num_words:
                if nw.isdigit():
                    digit_seq += nw
                elif nw in _DIGIT_WORDS:
                    digit_seq += str(_DIGIT_WORDS[nw])
                else:
                    break
            if 2 <= len(digit_seq) <= 4:
                final_digits = digit_seq
            else:
                return None
        else:
            if leading_zeros > 0:
                final_digits = ("0" * leading_zeros) + str(resolved_num)
            else:
                final_digits = str(resolved_num)

        # Türkiye plaka kuralları: 2-4 rakam olmalı
        if not (2 <= len(final_digits) <= 4):
            return None

        letters_str = "".join(letters_list)
        formatted_plate = f"{prov_code} {letters_str} {final_digits}"

        return PlateParseResult(
            raw_text=text,
            plate=formatted_plate,
            province=prov_code,
            letters=letters_str,
            digits=final_digits,
            confidence=0.95,
        )

    @classmethod
    def correct_plate(cls, current_plate: str, correction_text: str) -> Optional[PlateParseResult]:
        """Kullanıcının yaptığı hedefli plaka düzeltmesini yorumlar ve güncel plakayı üretir.

        Örnekler:
          - current_plate="34 ABC 123", correction_text="C değil, Denizli’nin D’si" -> "34 ABD 123"
          - current_plate="34 AB 123",  correction_text="Hayır, 34 ABC 123. Ceyhan’ın C’si de var." -> "34 ABC 123"
          - current_plate="34 ABC 123", correction_text="Sonu 124 olacak" -> "34 ABC 124"
          - current_plate="34 ABC 123", correction_text="34 değil 35" -> "35 ABC 123"
        """
        # 1. Önce kullanıcının tamamen yeni veya tam bir plaka söyleyip söylemediğine bak
        fresh_parsed = cls.parse_spoken(correction_text)
        if fresh_parsed and fresh_parsed.plate and fresh_parsed.plate != current_plate:
            fresh_parsed.is_correction = True
            fresh_parsed.correction_target = "full"
            return fresh_parsed

        if not current_plate:
            return None

        parts = current_plate.strip().split()
        if len(parts) != 3:
            return None

        prov, letters, digits = parts[0], parts[1], parts[2]
        clean = _tr_clean(correction_text)

        # 2. Harf Değiştirme / Düzeltme Örüntüsü ("X değil, Y'nin Z'si" / "X değil Y")
        # Örn: "c değil denizli nin d si", "c değil d", "bursa değil bolu"
        replace_match = re.search(
            r"([a-zçğıöşü]+)\s+değil\s+(?:,\s*)?([a-zçğıöşü]+(?:\s+(?:nin|nın|in|ın)\s+[a-zçğıöşü]+)?)",
            clean,
        )
        if replace_match:
            old_token = replace_match.group(1).strip()
            new_token_phrase = replace_match.group(2).strip()

            # Eski harfi bul
            old_char = None
            if old_token in _PHONETIC_CITY_MAP:
                old_char = _PHONETIC_CITY_MAP[old_token]
            elif len(old_token) == 1:
                old_char = old_token.upper()

            # Yeni harfi bul
            new_char = None
            for w in reversed(new_token_phrase.split()):
                if w in _PHONETIC_CITY_MAP:
                    new_char = _PHONETIC_CITY_MAP[w]
                    break
                elif len(w) == 1 and w.isalpha():
                    new_char = w.upper()
                    break

            if old_char and new_char and old_char in letters:
                # Yalnızca ilgili harfi değiştir!
                updated_letters = letters.replace(old_char, new_char, 1)
                new_plate = f"{prov} {updated_letters} {digits}"
                return PlateParseResult(
                    raw_text=correction_text,
                    plate=new_plate,
                    province=prov,
                    letters=updated_letters,
                    digits=digits,
                    is_correction=True,
                    correction_target=f"letter:{old_char}->{new_char}",
                    confidence=0.98,
                )

        # 3. Harf Ekleme Örüntüsü ("Ceyhan'ın C'si de var", "arada C var", "C de var")
        add_match = re.search(
            r"(?:([a-zçğıöşü]+)\s+(?:nin|nın|in|ın)\s+)?([a-zçğıöşü]+)(?:\s+(?:si|sı|i|ı))?\s+(?:de|da)?\s*var",
            clean,
        )
        if add_match:
            cand_ph = add_match.group(1)
            cand_let = add_match.group(2)
            add_char = None
            if cand_let in _PHONETIC_CITY_MAP:
                add_char = _PHONETIC_CITY_MAP[cand_let]
            elif cand_ph and cand_ph in _PHONETIC_CITY_MAP:
                add_char = _PHONETIC_CITY_MAP[cand_ph]
            elif cand_let and len(cand_let) == 1:
                add_char = cand_let.upper()

            if add_char and len(letters) < 3 and add_char not in letters:
                updated_letters = letters + add_char
                new_plate = f"{prov} {updated_letters} {digits}"
                return PlateParseResult(
                    raw_text=correction_text,
                    plate=new_plate,
                    province=prov,
                    letters=updated_letters,
                    digits=digits,
                    is_correction=True,
                    correction_target=f"add_letter:{add_char}",
                    confidence=0.95,
                )

        # 4. İl Kodu Düzeltme ("34 değil 35", "otuz dört değil otuz beş", "kocaeli olacak 41")
        prov_match = re.search(r"(?:değil|olacak)\s+([a-zçğıöşü\s0-9]+)", clean)
        if prov_match:
            cand_prov = prov_match.group(1).strip()
            if cand_prov in _PROVINCE_WORDS:
                new_prov = _PROVINCE_WORDS[cand_prov]
                new_plate = f"{new_prov} {letters} {digits}"
                return PlateParseResult(
                    raw_text=correction_text,
                    plate=new_plate,
                    province=new_prov,
                    letters=letters,
                    digits=digits,
                    is_correction=True,
                    correction_target=f"province:{prov}->{new_prov}",
                    confidence=0.95,
                )
            if cand_prov.isdigit() and 1 <= int(cand_prov) <= 81:
                new_prov = str(int(cand_prov)).zfill(2)
                new_plate = f"{new_prov} {letters} {digits}"
                return PlateParseResult(
                    raw_text=correction_text,
                    plate=new_plate,
                    province=new_prov,
                    letters=letters,
                    digits=digits,
                    is_correction=True,
                    correction_target=f"province:{prov}->{new_prov}",
                    confidence=0.95,
                )

        # 5. Sayı / Sonu Düzeltme ("sonu 124", "sonu yüz yirmi dört", "rakamı 99")
        digit_match = re.search(r"(?:sonu|rakam[ıi]|say[ıi]s[ıi]|rakamlar[ıi])\s+([a-zçğıöşü\s0-9]+)", clean)
        if digit_match:
            digit_phrase = digit_match.group(1).strip()
            new_num = _words_to_number(digit_phrase)
            if new_num is not None and 2 <= len(str(new_num)) <= 4:
                new_digits = str(new_num)
                new_plate = f"{prov} {letters} {new_digits}"
                return PlateParseResult(
                    raw_text=correction_text,
                    plate=new_plate,
                    province=prov,
                    letters=letters,
                    digits=new_digits,
                    is_correction=True,
                    correction_target=f"digits:{digits}->{new_digits}",
                    confidence=0.95,
                )

        return None


def extract_plate(text: str) -> Optional[str]:
    """Geriye dönük uyumluluk köprüsü: metin içindeki yazılı veya sözlü Türk plakasını döner."""
    res = TurkishPlateParser.parse_spoken(text)
    if res and res.plate:
        return res.plate
    return TurkishPlateParser.parse_written(text)
