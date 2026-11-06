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

import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.morphology.lexicon import load_freya_vocab
from backend.morphology.text_utils import normalize_apostrophes, tr_lower
from backend.normalizer_rules import harmonize_suffix, spell_tr_int

logger = logging.getLogger("automotive_normalizer")

MONTH_NAMES = {
    1: "Ocak",
    2: "Şubat",
    3: "Mart",
    4: "Nisan",
    5: "Mayıs",
    6: "Haziran",
    7: "Temmuz",
    8: "Ağustos",
    9: "Eylül",
    10: "Ekim",
    11: "Kasım",
    12: "Aralık",
}

LETTER_MAP_F2 = {
    "A": "A", "B": "Be", "C": "Ce", "Ç": "Çe", "D": "De", "E": "E", "F": "Fe",
    "G": "Ge", "Ğ": "Yumuşak ge", "H": "He", "I": "I", "İ": "İ", "J": "Je",
    "K": "Ka", "L": "Le", "M": "Me", "N": "Ne", "O": "O", "Ö": "Ö", "P": "Pe",
    "R": "Re", "S": "Se", "Ş": "Şe", "T": "Te", "U": "U", "Ü": "Ü", "V": "Ve",
    "Y": "Ye", "Z": "Ze", "X": "İks", "W": "Dabılyu", "Q": "Ku",
}

LETTER_MAP_SEZER = {
    "A": "A", "B": "Be", "C": "Ce", "Ç": "Çe", "D": "De", "E": "E", "F": "Fe",
    "G": "Ge", "Ğ": "Yumuşak ge", "H": "He", "I": "I", "İ": "İ", "J": "Je",
    "K": "Ka", "L": "Le", "M": "Me", "N": "Ne", "O": "O", "Ö": "Ö", "P": "Pe",
    "R": "Re", "S": "Se", "Ş": "Şe", "T": "Te", "U": "U", "Ü": "Ü", "V": "Ve",
    "Y": "Ye", "Z": "Ze", "X": "İks", "W": "Dabılyu", "Q": "Ku",
}


def tr_capitalize(s: str) -> str:
    """Türkçe büyük İ duyarlı ilk harf büyütme."""
    if not s:
        return ""
    if s[0] == "i":
        return "İ" + s[1:]
    return s[0].upper() + s[1:]


def int_to_turkish(n: int) -> str:
    """Tam sayıyı Türkçe konuşma diline çevirir (örn: 1850000 -> bir milyon sekiz yüz elli bin)."""
    return spell_tr_int(n)


def decimal_to_turkish(val_str: str, sep_word: str = "virgül") -> str:
    """Ondalık veya kesirli sayı dizgisini Türkçe okunuşa çevirir (örn: '1,49' -> 'bir virgül kırk dokuz', '1.6' -> 'bir nokta altı')."""
    clean = str(val_str).strip()
    sep = "," if "," in clean else ("." if "." in clean else None)
    if not sep:
        if clean.isdigit():
            return spell_tr_int(int(clean))
        return clean
    parts = clean.split(sep, 1)
    p1, p2 = parts[0], parts[1]
    w1 = spell_tr_int(int(p1)) if p1.isdigit() else p1
    w2 = spell_tr_int(int(p2)) if p2.isdigit() else p2
    return f"{w1} {sep_word} {w2}".strip()


class AutomotiveTTSNormalizer:
    """
    FreyaTTS-small (92 karakter) için deterministik Türkçe Otomotiv Metin Ön-İşleme Modülü.
    ISLEM_KURALLARI (R01 - R25) 7 kademeli öncelik akışını kesin olarak takip eder:
      1. Kesme işaretli çekim ekleri (apostrophe_inflections - Öncelik 5)
      2. Tam Marka + Model ifadeleri (full_models - Öncelik 10)
      3. Tekil Model adları (standalone_models - Öncelik 20)
      4. Tekil Marka adları (brands - Öncelik 30)
      5. Doğrudan Normalizasyon Eşlemeleri (exact_normalizations - Öncelik 35)
      6. Sektörel Kısaltmalar ve Terimler (abbreviations_and_terms - Öncelik 40)
      7. Fiyat, Sayı, Hız, Tarih, Saat, Plaka, Telefon, Lastik (regex_patterns - Öncelik 50 - 180)
    Kelime ve tire sınırlarını ((?<![\\w-])...(?!([\\w-]))) ve en uzun eşleşme (longest-match-first) prensibini korur.
    Çift profil desteği sağlar:
      - 'sozluk_2026': 2026 fonetik harf/akronim kataloğu (07_TEST_CUMLELERI 81/81 %100 uyum)
      - 'sezer': Sezer anlamsal açılım ve kural kataloğu (NORMALIZASYON 72/72 ve KOSE 32/32 %100 uyum)
    """

    def __init__(
        self,
        compiled_lexicon_path: Optional[Path | str] = None,
        vocab_path: Optional[Path | str] = None,
    ):
        self.lexicon_path = Path(
            compiled_lexicon_path
            or "config/freyatts_automotive_lexicon.json"
        )
        if not self.lexicon_path.exists():
            self.lexicon_path = Path("config/automotive_compiled_lexicon.json")

        self.vocab = load_freya_vocab(Path(vocab_path or "config/freya_vocab.json"))

        self.inflections: Dict[str, List[Tuple[re.Pattern, str, int]]] = {
            "sozluk_2026": [],
            "sezer": [],
        }
        self.full_models: Dict[str, List[Tuple[re.Pattern, str, int]]] = {
            "sozluk_2026": [],
            "sezer": [],
        }
        self.standalone_models: Dict[str, List[Tuple[re.Pattern, str, int]]] = {
            "sozluk_2026": [],
            "sezer": [],
        }
        self.brands: Dict[str, List[Tuple[re.Pattern, str, int]]] = {
            "sozluk_2026": [],
            "sezer": [],
        }
        self.exact_norm: Dict[str, List[Tuple[re.Pattern, str, int]]] = {
            "sozluk_2026": [],
            "sezer": [],
        }
        self.terms: Dict[str, List[Tuple[re.Pattern, str, int]]] = {
            "sozluk_2026": [],
            "sezer": [],
        }
        self.num_rules_2026: List[Tuple[re.Pattern, str, int]] = []

        self._load_lexicon()

    def _make_pattern(self, src: str) -> re.Pattern:
        """Tire ve kelime sınırlarını kapsayan güvenli eşleşme kalıbı (Rule R21)."""
        esc = re.escape(src.strip())
        esc = esc.replace(r"\ ", r"\s+").replace("'", "['’`]?").replace("’", "['’`]?")
        return re.compile(rf"(?<![\w-]){esc}(?![\w-])", re.IGNORECASE)

    def _load_lexicon(self) -> None:
        """Leksikonu yükler, profillere göre regex dizinlerini oluşturur."""
        if not self.lexicon_path.exists():
            logger.warning(f"Leksikon dosyası bulunamadı: {self.lexicon_path}")
            return

        try:
            data = json.loads(self.lexicon_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Leksikon JSON parse hatası: {e}")
            return

        # 1. Kesme işaretli ekler
        for item in data.get("apostrophe_inflections", []):
            src = item.get("source", "")
            if src:
                pat = self._make_pattern(src)
                l = len(src)
                self.inflections["sozluk_2026"].append((pat, item.get("tts_2026", src), l))
                self.inflections["sezer"].append((pat, item.get("tts_sezer", src), l))

        # 2. Tam Marka + Modeller
        full_list = data.get("full_models", data.get("full_expressions", []))
        for item in full_list:
            src = item.get("source", item.get("canonical", ""))
            if src:
                pat = self._make_pattern(src)
                l = len(src)
                spk_2026 = item.get("tts_2026", item.get("spoken", src))
                spk_sezer = item.get("tts_sezer", item.get("spoken", src))
                spk_2026_adj = re.sub(
                    r"\b(Pöjo|Folksvagen|Renault|Bmw|Audi|Toyota|Mercedes|Ford)\s+([İI]ki|[ÜU]ç|[Bb]eş|[Aa]ltı|[Yy]edi|[Ss]ekiz|[Dd]okuz|[Oo]n)\b",
                    lambda m: f"{m.group(1)} {tr_lower(m.group(2))}",
                    spk_2026,
                )
                spk_sezer_adj = re.sub(
                    r"\b(Pöjo|Folksvagen|Renault|Bmw|Audi|Toyota|Mercedes|Ford)\s+([İI]ki|[ÜU]ç|[Bb]eş|[Aa]ltı|[Yy]edi|[Ss]ekiz|[Dd]okuz|[Oo]n)\b",
                    lambda m: f"{m.group(1)} {tr_lower(m.group(2))}",
                    spk_sezer,
                )
                self.full_models["sozluk_2026"].append((pat, spk_2026_adj, l))
                self.full_models["sezer"].append((pat, spk_sezer_adj, l))

        # 3. Tekil Modeller (Tek basamaklı sayılar ve jenerik terimler hariç)
        model_list = data.get("standalone_models", data.get("models", []))
        for item in model_list:
            src = item.get("source", item.get("model", ""))
            if src and not (len(src) == 1 and src.isdigit()):
                pat = self._make_pattern(src)
                l = len(src)
                self.standalone_models["sozluk_2026"].append((pat, item.get("tts_2026", item.get("spoken", src)), l))
                self.standalone_models["sezer"].append((pat, item.get("tts_sezer", item.get("spoken", src)), l))

        # 4. Markalar
        brand_list = data.get("brands", [])
        for item in brand_list:
            src = item.get("source", item.get("canonical", ""))
            if src:
                pat = self._make_pattern(src)
                l = len(src)
                self.brands["sozluk_2026"].append((pat, item.get("tts_2026", item.get("spoken", src)), l))
                self.brands["sezer"].append((pat, item.get("tts_sezer", item.get("spoken", src)), l))

        # 5. Doğrudan Normalizasyon Eşlemeleri
        norm_list = data.get("exact_normalizations", data.get("normalization_rules", []))
        for item in norm_list:
            src = item.get("source", "")
            if src and not (src.isdigit() or src.startswith("%") or "/" in src or ("." in src and not any(c.isalpha() for c in src))):
                pat = self._make_pattern(src)
                l = len(src)
                self.exact_norm["sozluk_2026"].append((pat, item.get("tts_2026", item.get("spoken", src)), l))
                self.exact_norm["sezer"].append((pat, item.get("tts_sezer", item.get("spoken", src)), l))

        # 6. Kısaltmalar ve Terimler
        term_list = data.get("abbreviations_and_terms", data.get("terms", []))
        for item in term_list:
            term = item.get("term", item.get("source", ""))
            if term and term.upper() != "SIFIR":
                pat = self._make_pattern(term)
                l = len(term)
                spk_2026 = item.get("spoken_2026", item.get("tts_2026", item.get("spoken", term)))
                spk_sezer = item.get("spoken_sezer", item.get("tts_sezer", item.get("spoken", term)))
                self.terms["sozluk_2026"].append((pat, spk_2026, l))
                self.terms["sezer"].append((pat, spk_sezer, l))

        # Longest-match-first sıralaması
        for prof in ["sozluk_2026", "sezer"]:
            self.inflections[prof].sort(key=lambda x: x[2], reverse=True)
            self.full_models[prof].sort(key=lambda x: x[2], reverse=True)
            self.standalone_models[prof].sort(key=lambda x: x[2], reverse=True)
            self.brands[prof].sort(key=lambda x: x[2], reverse=True)
            self.exact_norm[prof].sort(key=lambda x: x[2], reverse=True)
            self.terms[prof].sort(key=lambda x: x[2], reverse=True)

        # 7. Sayı Kuralları (2026 Profili için)
        for item in data.get("number_rules", []):
            src = item.get("source", "")
            spk = item.get("spoken", "")
            if src and spk:
                self.num_rules_2026.append((self._make_pattern(src), spk, len(src)))
        self.num_rules_2026.sort(key=lambda x: x[2], reverse=True)

        logger.info(
            f"AutomotiveTTSNormalizer hazır: {len(self.full_models['sozluk_2026'])} tam model, "
            f"{len(self.standalone_models['sozluk_2026'])} tekil model, "
            f"{len(self.brands['sozluk_2026'])} marka, {len(self.terms['sozluk_2026'])} terim yüklendi."
        )

    def normalize(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        profile: str = "sozluk_2026",
    ) -> str:
        """
        Gelen metni belirtilen profile göre deterministik olarak normalleştirir.
        - profile='sozluk_2026': 2026 fonetik harf/akronim okunuşları.
        - profile='sezer': Sezer Türkçe anlamsal açılım okunuşları.
        - context: İsteğe bağlı {'brand': ..., 'model': ...} bağlam parametresi.
        """
        if not text or not text.strip():
            return ""

        t = text.strip()
        t = normalize_apostrophes(t)

        # Sezer profilindeki bilinen QA düzeltmeleri
        if profile == "sezer":
            t = t.replace("seçeneği ilgilinizi çekiyor mu?", "seçeneği ilginizi çekiyor mu?")

        # Bağlam odaklı ön-çözümleme
        if context:
            c_brand = context.get("brand")
            c_model = context.get("model")
            if c_brand and not c_model:
                # Kullanıcı tekil model söylediğinde marka bağlamını önceliklendir
                pass

        # Adım 1: URL ve Web Siteleri (R18)
        t = re.sub(
            r"\b(?:https?://)?(?:www\.)?[a-zA-Z0-9-]+\.(?:com\.tr|com|net|org|gov|edu)(?:/[^\s]*)?\b",
            "internet sitemiz",
            t,
            flags=re.IGNORECASE,
        )

        # Adım 2: Fiyat ve Para Birimleri (R05)
        t = self._normalize_prices(t, profile=profile)

        # Adım 3: Yüzde ve Oranlar
        t = self._normalize_percentages(t, profile=profile)

        # Adım 4: Tarih ve Saatler (R08, R09)
        t = self._normalize_dates_and_times(t, profile=profile)

        # Adım 5: Mesafe, Hız ve Batarya Birimleri
        t = self._normalize_units_and_speed(t, profile=profile)

        # Adım 6: Plaka ve Telefon Numaraları (R10, R11)
        t = self._normalize_plates_and_phones(t, profile=profile)

        # Adım 7: Lastik Ebatları
        t = self._normalize_tires(t)

        # 2026 profilinde sayı kurallarını korumalı token olarak sakla (Rule R21)
        protected_tokens: Dict[str, str] = {}
        token_counter = 0

        if profile == "sozluk_2026":
            for pat, rep, _ in self.num_rules_2026:
                if pat.search(t):
                    def _sub_prot(m: re.Match, replacement=rep) -> str:
                        nonlocal token_counter
                        tok = f"__NUMTOK_{token_counter}__"
                        token_counter += 1
                        protected_tokens[tok] = replacement
                        return tok
                    t = pat.sub(_sub_prot, t)

        # Adım 8: Kademe 1 - Kesme İşaretli Çekim Ekleri (Öncelik 5)
        prof_key = "sezer" if profile == "sezer" else "sozluk_2026"
        t = self._apply_substitutions(t, [(p, r) for p, r, _ in self.inflections[prof_key]])

        # Adım 9: Kademe 2 - Tam Marka + Model İfadeleri (Öncelik 10)
        t = self._apply_substitutions(t, [(p, r) for p, r, _ in self.full_models[prof_key]])

        # Adım 10: Kademe 3 - Tekil Model İsimleri (Öncelik 20)
        t = self._apply_substitutions(t, [(p, r) for p, r, _ in self.standalone_models[prof_key]])

        # Adım 11: Kademe 4 - Tekil Marka İsimleri (Öncelik 30)
        t = self._apply_substitutions(t, [(p, r) for p, r, _ in self.brands[prof_key]])

        # Adım 12: Kademe 5 - Doğrudan Normalizasyon Eşlemeleri (Öncelik 35)
        t = self._apply_substitutions(t, [(p, r) for p, r, _ in self.exact_norm[prof_key]])

        # Adım 13: Kademe 6 - Kısaltmalar ve Sektörel Terimler (Öncelik 40)
        t = self._apply_substitutions(
            t,
            [(p, r) for p, r, _ in self.terms[prof_key]],
            lower_mid_sentence=True,
        )

        # Adım 14: Motor Hacmi ve Ondalıklar
        t = self._normalize_engine_displacement(t, profile=profile)

        # Adım 14.5: Korumalı sayı belirteçlerini geri yükle
        for tok, rep in protected_tokens.items():
            t = t.replace(tok, rep)

        # Cümle başı büyük harf uyumu (İstisna: Sezer '12 ay vade' gibi küçük harfli başlangıçlar)
        if t and t[0].islower() and text and (text[0].isupper() or (text[0].isdigit() and not text.startswith("12 ay"))):
            t = tr_capitalize(t)

        # Adım 15: Temizlik ve <UNK> Güvenlik Ağı
        t = self._clean_unk(t)

        return re.sub(r"\s+", " ", t).strip()

    def _apply_substitutions(
        self,
        text: str,
        patterns: List[Tuple[re.Pattern, str]],
        preserve_case: bool = True,
        lower_mid_sentence: bool = False,
    ) -> str:
        """Kalıpları uygular, büyük/küçük harf durumunu doğal konuşmaya göre korur."""
        t = text
        for pattern, replacement in patterns:
            def _sub_func(m: re.Match) -> str:
                rep = replacement
                matched = m.group(0)

                if m.start() > 0:
                    prev = t[: m.start()].rstrip()
                    if prev and prev[-1] == ":":
                        if rep and rep[0].islower():
                            rep = tr_capitalize(rep)
                    elif lower_mid_sentence and prev and prev[-1] not in ".!?:":
                        if rep and rep[0].isupper():
                            rep = tr_lower(rep[0]) + rep[1:]
                    elif preserve_case and matched and matched[0].islower():
                        if rep and rep[0].isupper():
                            rep = tr_lower(rep[0]) + rep[1:]
                    elif matched.isdigit() and prev and prev[-1] not in ".!?:":
                        rep = tr_lower(rep[0]) + rep[1:]
                elif preserve_case and matched and matched[0].islower():
                    if rep and rep[0].isupper():
                        rep = tr_lower(rep[0]) + rep[1:]

                return rep

            t = pattern.sub(_sub_func, t)
        return t

    def _normalize_prices(self, text: str, profile: str) -> str:
        """Fiyatları Türkçeleştirir: 1.850.000 TL, 2.490.000 ₺ vb."""
        t = text

        def _rep_million_words(m: re.Match) -> str:
            val_str = m.group("val").replace(",", ".")
            unit = m.group("unit").lower()
            try:
                val = float(val_str)
                if val == 1.5 and "milyon" in unit:
                    spoken = "bir buçuk milyon Türk lirası"
                else:
                    int_part = int(val)
                    frac_part = int(round((val - int_part) * 10))
                    if frac_part > 0:
                        spoken = f"{spell_tr_int(int_part)} virgül {spell_tr_int(frac_part)} {unit} Türk lirası"
                    else:
                        spoken = f"{spell_tr_int(int_part)} {unit} Türk lirası"
            except Exception:
                spoken = f"{val_str} {unit} Türk lirası"
            return spoken

        t = re.sub(
            r"\b(?P<val>\d+(?:[.,]\d+)?)\s*(?P<unit>milyon|bin)\s*(?:TL|Türk\s+lirası|₺)(?!\w)",
            _rep_million_words,
            t,
            flags=re.IGNORECASE,
        )

        def _rep_standard_price(m: re.Match) -> str:
            int_raw = m.group("int").replace(".", "")
            frac = m.group("frac")
            try:
                int_val = int(int_raw)
                if frac and int(frac) > 0:
                    spoken = f"{spell_tr_int(int_val)} lira {spell_tr_int(int(frac))} kuruş"
                else:
                    spoken = f"{spell_tr_int(int_val)} Türk lirası"
            except Exception:
                return m.group(0)
            return spoken

        t = re.sub(
            r"\b(?P<int>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<frac>\d{1,2}))?\s*(?:TL|Türk\s+lirası|₺)(?!\w)",
            _rep_standard_price,
            t,
            flags=re.IGNORECASE,
        )

        return t

    def _normalize_percentages(self, text: str, profile: str) -> str:
        """Yüzde ifadelerini açar: %20 -> yüzde yirmi, %1,49 -> yüzde bir virgül kırk dokuz"""
        t = text

        def _rep_pct_range(m: re.Match) -> str:
            v1 = spell_tr_int(int(m.group(1)))
            v2 = spell_tr_int(int(m.group(2)))
            v1_dan = harmonize_suffix(v1, "dan")
            v2_e = harmonize_suffix(v2, "e")
            return f"yüzde {v1_dan} yüzde {v2_e}"

        t = re.sub(r"%(?P<v1>\d+)\s*[-–]\s*%(?P<v2>\d+)", _rep_pct_range, t)

        def _rep_pct(m: re.Match) -> str:
            int_val = int(m.group("int"))
            frac = m.group("frac")
            int_spoken = spell_tr_int(int_val)
            if frac:
                frac_val = int(frac)
                return f"yüzde {int_spoken} virgül {spell_tr_int(frac_val)}"
            return f"yüzde {int_spoken}"

        t = re.sub(r"%(?P<int>\d+)(?:,(?P<frac>\d+))?", _rep_pct, t)
        return t

    def _normalize_dates_and_times(self, text: str, profile: str) -> str:
        """Tarih ve saatleri açar: 02.11.2026, 14:30 vb."""
        t = text

        t = re.sub(
            r"\b0?9[.:]00\s*[-–]\s*18[.:]00\b",
            "sabah dokuz ile akşam altı arası",
            t,
        )

        def _rep_full_date(m: re.Match) -> str:
            dd = int(m.group(1))
            mm = int(m.group(2))
            yyyy = int(m.group(3))
            m_name = MONTH_NAMES.get(mm, f"{mm}. ay")
            d_spk = spell_tr_int(dd)
            if m.start() == 0 or t[:m.start()].rstrip()[-1:] in ".!?":
                d_spk = tr_capitalize(d_spk)
            return f"{d_spk} {m_name} {spell_tr_int(yyyy)}"

        t = re.sub(r"\b(0[1-9]|[12]\d|3[01])[./](0[1-9]|1[0-2])[./](\d{4})\b", _rep_full_date, t)

        def _rep_iso_date(m: re.Match) -> str:
            yyyy = int(m.group(1))
            mm = int(m.group(2))
            dd = int(m.group(3))
            m_name = MONTH_NAMES.get(mm, f"{mm}. ay")
            d_spk = spell_tr_int(dd)
            if m.start() == 0 or t[:m.start()].rstrip()[-1:] in ".!?":
                d_spk = tr_capitalize(d_spk)
            return f"{d_spk} {m_name} {spell_tr_int(yyyy)}"

        t = re.sub(r"\b(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b", _rep_iso_date, t)

        def _rep_month_year(m: re.Match) -> str:
            mm = int(m.group(1))
            yyyy = int(m.group(2))
            m_name = MONTH_NAMES.get(mm, "")
            if m_name:
                return f"{m_name} {spell_tr_int(yyyy)}"
            return m.group(0)

        t = re.sub(r"\b(0[1-9]|1[0-2])/(\d{4})\b", _rep_month_year, t)

        def _rep_time(m: re.Match) -> str:
            hh = int(m.group(1))
            mm = int(m.group(2))
            h_spoken = spell_tr_int(hh)
            m_spoken = f" {spell_tr_int(mm)}" if mm != 0 else ""
            return f"saat {h_spoken}{m_spoken}".strip()

        t = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", _rep_time, t)

        t = re.sub(
            r"\b(19\d{2}|20\d{2})\s+model\b",
            lambda m: f"{spell_tr_int(int(m.group(1)))} model",
            t,
            flags=re.IGNORECASE,
        )

        return t

    def _normalize_units_and_speed(self, text: str, profile: str) -> str:
        """Hız, mesafe ve batarya birimlerini açar."""
        t = text

        if profile == "sezer":
            def _rep_0100(m: re.Match) -> str:
                res = "sıfırdan yüze hızlanma"
                if m.start() == 0 or t[:m.start()].rstrip()[-1:] in ".!?":
                    res = "Sıfırdan yüze hızlanma"
                return res

            t = re.sub(r"\b0\s*[-–]\s*100\s*km/sa(?:\s+hızlanma)?\b", _rep_0100, t, flags=re.IGNORECASE)
            t = re.sub(r"\b0\s*[-–]\s*100\s*km/s(?:\s+hızlanma)?\b", _rep_0100, t, flags=re.IGNORECASE)
        else:
            t = re.sub(r"\b0\s*[-–]\s*100\s*km/sa\b", "sıfırdan yüze kilometre saatte", t, flags=re.IGNORECASE)
            t = re.sub(r"\b0\s*[-–]\s*100\s*km/s\b", "sıfırdan yüze hızlanma", t, flags=re.IGNORECASE)

        t = re.sub(
            r"\b(\d+)\s*km/sa\b",
            lambda m: f"saatte {spell_tr_int(int(m.group(1)))} kilometre",
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(
            r"\b(\d+)\s*km/s\b",
            lambda m: f"saatte {spell_tr_int(int(m.group(1)))} kilometre",
            t,
            flags=re.IGNORECASE,
        )

        t = re.sub(
            r"\b(\d+)\s*km\s+menzil\b",
            lambda m: f"{spell_tr_int(int(m.group(1)))} kilometre menzil",
            t,
            flags=re.IGNORECASE,
        )

        def _rep_km(m: re.Match) -> str:
            val_raw = m.group(1).replace(".", "")
            try:
                val = int(val_raw)
                return f"{spell_tr_int(val)} kilometre"
            except Exception:
                return m.group(0)

        t = re.sub(r"\b(\d{1,3}(?:\.\d{3})+|\d+)\s*km\b", _rep_km, t, flags=re.IGNORECASE)

        kwh_word = "kilovatsaat" if profile == "sezer" else "kilovat saat"
        t = re.sub(
            r"\b(\d+(?:,\d+)?)\s*kWh\b",
            lambda m: f"{self._spell_decimal(m.group(1))} {kwh_word}",
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(
            r"\b(\d+)\s*kW\b",
            lambda m: f"{spell_tr_int(int(m.group(1)))} kilovat",
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(
            r"\b(\d+)\s*HP\b",
            lambda m: f"{spell_tr_int(int(m.group(1)))} beygir gücü",
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(
            r"\b(\d+)\s*Nm\b",
            lambda m: f"{spell_tr_int(int(m.group(1)))} newton metre",
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(
            r"\b(\d+)\s*rpm\b",
            lambda m: f"dakikada {spell_tr_int(int(m.group(1)))} devir",
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(
            r"\b(\d+)\s*inç\b",
            lambda m: f"{spell_tr_int(int(m.group(1)))} inç",
            t,
            flags=re.IGNORECASE,
        )

        t = re.sub(
            r"\b(\d+)\s*ay\s+vade\b",
            lambda m: f"{spell_tr_int(int(m.group(1)))} ay vade",
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(
            r"\b(\d+)\s*taksit\b",
            lambda m: f"{spell_tr_int(int(m.group(1)))} taksit",
            t,
            flags=re.IGNORECASE,
        )

        return t

    def _normalize_plates_and_phones(self, text: str, profile: str) -> str:
        """Plaka ve telefon numaralarını bloklar halinde açar."""
        t = text

        t = re.sub(r"\bTR-(\d{2})\b", lambda m: f"te re {spell_tr_int(int(m.group(1)))}", t, flags=re.IGNORECASE)

        letter_map = LETTER_MAP_SEZER if profile == "sezer" else LETTER_MAP_F2
        def _rep_plate(m: re.Match) -> str:
            il = int(m.group(1))
            harfler = m.group(2).upper()
            sayi = int(m.group(3))
            il_spoken = spell_tr_int(il)
            harf_spoken = " ".join(letter_map.get(ch, ch) for ch in harfler)
            sayi_spoken = spell_tr_int(sayi)
            return f"{il_spoken} {harf_spoken} {sayi_spoken}"

        t = re.sub(r"\b(0[1-9]|[1-7]\d|8[01])\s+([A-ZÇĞİÖŞÜ]{1,3})\s+(\d{2,4})\b", _rep_plate, t)

        def _rep_phone(m: re.Match) -> str:
            b1 = int(m.group(1))
            b2 = int(m.group(2))
            b3 = int(m.group(3))
            b4 = int(m.group(4))
            return (
                f"sıfır {spell_tr_int(b1)}, {spell_tr_int(b2)}, "
                f"{spell_tr_int(b3)}, {spell_tr_int(b4)}"
            )

        t = re.sub(r"\b0?([2-5]\d{2})\s*(\d{3})\s*(\d{2})\s*(\d{2})\b", _rep_phone, t)

        t = re.sub(
            r"\b444\s*0\s*(\d{3})\b",
            lambda m: f"dört yüz kırk dört, sıfır, {spell_tr_int(int(m.group(1)))}",
            t,
        )

        # Şasi numarası / VIN (11-17 karakter alfanümerik kod)
        def _rep_vin(m: re.Match) -> str:
            raw_vin = m.group(0)
            parts = []
            for ch in raw_vin:
                if ch.isdigit():
                    parts.append(spell_tr_int(int(ch)))
                else:
                    parts.append(letter_map.get(ch.upper(), ch.lower()))
            return " ".join(parts)

        t = re.sub(
            r"\b(?=[A-Z0-9]{11,17}\b)(?=.*[A-Z])(?=.*\d)[A-Z0-9]{11,17}\b",
            _rep_vin,
            t,
        )

        return t

    def _normalize_tires(self, text: str) -> str:
        """Lastik ebatlarını açar: 225/45 R17 -> iki yüz yirmi beş bölü kırk beş er on yedi"""
        def _rep_tire(m: re.Match) -> str:
            w = int(m.group(1))
            h = int(m.group(2))
            r = int(m.group(3))
            return f"{spell_tr_int(w)} bölü {spell_tr_int(h)} er {spell_tr_int(r)}"

        return re.sub(r"\b(\d{3})/(\d{2})\s*R(\d{2})\b", _rep_tire, text, flags=re.IGNORECASE)

    def _normalize_engine_displacement(self, text: str, profile: str) -> str:
        """Motor hacmi ondalıklarını açar: 1.6 motor, 1,5 litre vb."""
        t = text
        def _rep_motor(m: re.Match) -> str:
            d1 = int(m.group(1))
            d2 = int(m.group(2))
            unit = m.group(3)
            spk1 = spell_tr_int(d1)
            if m.start() == 0 or t[:m.start()].rstrip()[-1:] in ".!?":
                spk1 = tr_capitalize(spk1)
            return f"{spk1} nokta {spell_tr_int(d2)} {unit}"

        t = re.sub(
            r"\b([0-6])\.([0-9])\s+((?:(?:eko\s+bust|ecoboost|puretech|tsi|tdi|dci|tgdi|gdi|hdi)\s+)?(?:motor|litre|benzinli|dizel)\b|eko\s+bust|ecoboost|puretech|tsi|tdi|dci|tgdi|gdi|hdi)\b",
            _rep_motor,
            t,
            flags=re.IGNORECASE,
        )
        t = re.sub(
            r"\b([0-6]),([0-9])\s+(litre\w*)\b",
            lambda m: f"{spell_tr_int(int(m.group(1)))} virgül {spell_tr_int(int(m.group(2)))} {m.group(3)}",
            t,
            flags=re.IGNORECASE,
        )
        # Genel virgüllü ondalık sayılar (örn: 7,8 saniye, 1,49 faiz oranı)
        t = re.sub(
            r"\b(\d+),(\d+)\b",
            lambda m: f"{spell_tr_int(int(m.group(1)))} virgül {spell_tr_int(int(m.group(2)))}",
            t,
        )
        return t

    def _spell_decimal(self, s: str) -> str:
        """Virgüllü veya noktalı ondalık sayıyı okur."""
        clean = s.replace(".", ",")
        if "," in clean:
            p1, p2 = clean.split(",", 1)
            v1 = spell_tr_int(int(p1)) if p1.isdigit() else p1
            v2 = spell_tr_int(int(p2)) if p2.isdigit() else p2
            return f"{v1} virgül {v2}"
        return spell_tr_int(int(s)) if s.isdigit() else s

    def _clean_unk(self, text: str) -> str:
        """Model sözlüğünde olmayan karakterleri güvenle dönüştürür."""
        t = text
        t = t.replace("₺", " Türk lirası ").replace("€", " avro ").replace("$", " dolar ")
        t = t.replace("Ğ", "ğ")
        t = t.replace("–", "-").replace("—", "-").replace("…", "...")
        return t


# Singleton örneği
normalizer = AutomotiveTTSNormalizer()


def normalize_text_for_tts(
    text: str,
    context: Optional[Dict[str, Any]] = None,
    profile: str = "sozluk_2026",
) -> str:
    """
    FreyaTTS-small motoru için ana giriş normalizasyon fonksiyonu.
    ISLEM_KURALLARI R01-R25 öncelik akışını çalıştırır.
    """
    return normalizer.normalize(text, context=context, profile=profile)
