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

from backend.morphology.text_utils import tr_lower, normalize_apostrophes
from backend.normalizer import normalize_text_for_tts

logger = logging.getLogger("asr_mapper")


class ASRMapper:
    """
    Gelen ASR (Konuşma Tanıma) transkriptlerindeki hatalı marka/model yazımlarını,
    fonetik varyantları ve gayriresmî kısaltmaları kanonik otomotiv araç adına çeviren modül.
    Kaynak: 04_TTS_ALIAS (1.664 alias kuralı), 02_MARKALAR ve 03_MODELLER.
    """

    def __init__(self, compiled_lexicon_path: Optional[Path | str] = None):
        self.path = Path(
            compiled_lexicon_path
            or "config/freyatts_automotive_lexicon.json"
        )
        if not self.path.exists():
            self.path = Path("config/automotive_compiled_lexicon.json")

        self._compiled_patterns: List[Tuple[re.Pattern, str, str]] = []
        self._canonical_brands: Dict[str, str] = {}
        self._canonical_vehicles: Dict[str, str] = {}
        self._load_mappings()

    def _load_mappings(self) -> None:
        """Derlenmiş leksikon JSON dosyasını okur ve regex eşleme kalıplarını derler."""
        if not self.path.exists():
            logger.warning(f"Derlenmiş leksikon bulunamadı: {self.path}")
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Leksikon okunurken hata: {e}")
            return

        # 1. Marka Kanonik Eşlemeleri (02_MARKALAR ve takma adlar)
        for b_item in data.get("brands", []):
            canon_brand = b_item.get("source") or b_item.get("canonical", "")
            if canon_brand:
                self._canonical_brands[tr_lower(canon_brand)] = canon_brand
                for alias in b_item.get("asr_variants", b_item.get("aliases", [])):
                    self._canonical_brands[tr_lower(alias)] = canon_brand

        # 2. ASR Alias Tablosu (04_TTS_ALIAS)
        raw_aliases = list(data.get("asr_mappings", []))

        # 3. Fonetik Araç İfadeleri (Tersine ASR Eşlemesi: "Tog Te on iks" -> "Togg T10X")
        full_list = data.get("full_models", data.get("full_expressions", []))
        for f_item in full_list:
            canon_expr = f_item.get("canonical", f_item.get("source", ""))
            spoken_expr = f_item.get("tts_2026", f_item.get("spoken", ""))
            if canon_expr and spoken_expr and canon_expr.lower() != spoken_expr.lower():
                raw_aliases.append({
                    "variant": spoken_expr,
                    "canonical": canon_expr,
                    "alias_type": "Fonetik Tam Araç",
                })

        # 4. Fonetik Markalar (Örn: "Reno" -> "Renault", "Porşe" -> "Porsche")
        for b_item in data.get("brands", []):
            canon_b = b_item.get("canonical", b_item.get("source", ""))
            spk_b = b_item.get("tts_2026", b_item.get("spoken", ""))
            if canon_b and spk_b and canon_b.lower() != spk_b.lower():
                raw_aliases.append({
                    "variant": spk_b,
                    "canonical": canon_b,
                    "alias_type": "Fonetik Marka",
                })

        # Uzun eşleşme önce kuralı (Longest match first)
        sorted_aliases = sorted(raw_aliases, key=lambda x: len(x.get("variant", "")), reverse=True)

        for item in sorted_aliases:
            variant = item.get("variant", "").strip()
            canonical = item.get("canonical", "").strip()
            alias_type = item.get("alias_type", "ASR varyant")
            if not variant or not canonical or tr_lower(variant) in self._canonical_vehicles:
                continue

            self._canonical_vehicles[tr_lower(variant)] = canonical

            var_esc = re.escape(variant)
            var_pattern = var_esc.replace("'", "['’`]")
            try:
                pattern = re.compile(rf"(?<![\w-]){var_pattern}(?![\w-])", re.IGNORECASE)
                self._compiled_patterns.append((pattern, canonical, alias_type))
            except Exception as pe:
                logger.debug(f"Regex derlenemedi: {variant} ({pe})")

        logger.info(
            f"ASRMapper hazır: {len(self._compiled_patterns)} eşleme kuralı, "
            f"{len(self._canonical_brands)} marka dizini yüklendi."
        )

    def map_asr_to_canonical(self, text: str) -> Dict[str, Any]:
        """
        Metin içindeki ASR hatalarını ve alternatif telaffuzları kanonik marka/model adlarına dönüştürür.
        """
        if not text:
            return {
                "source_text": "",
                "canonical_text": "",
                "detected_brand": None,
                "detected_model": None,
                "canonical_vehicle": None,
                "applied_mappings": [],
            }

        t = normalize_apostrophes(text)
        applied: List[Dict[str, str]] = []
        detected_brand: Optional[str] = None
        detected_model: Optional[str] = None
        canonical_vehicle: Optional[str] = None

        for pattern, canonical, alias_type in self._compiled_patterns:
            if pattern.search(t):
                m = pattern.search(t)
                matched_str = m.group(0) if m else ""
                t = pattern.sub(canonical, t)
                applied.append({
                    "matched": matched_str,
                    "canonical": canonical,
                    "type": alias_type,
                })
                if not canonical_vehicle and " " in canonical:
                    canonical_vehicle = canonical

        # Tespit edilen kanonik metin üzerinden marka/model ayıklama
        lowered_mapped = tr_lower(t)
        for b_low, b_canon in self._canonical_brands.items():
            pattern_b = rf"(?<![\w-]){re.escape(b_low)}(?![\w-])"
            if re.search(pattern_b, lowered_mapped):
                detected_brand = b_canon
                break

        if canonical_vehicle:
            parts = canonical_vehicle.split(maxsplit=1)
            if len(parts) == 2:
                detected_brand = detected_brand or parts[0]
                detected_model = parts[1]

        return {
            "source_text": text,
            "canonical_text": t,
            "detected_brand": detected_brand,
            "detected_model": detected_model,
            "canonical_vehicle": canonical_vehicle,
            "applied_mappings": applied,
        }

    def canonicalize_asr_text(self, asr_input: str) -> Dict[str, Any]:
        """
        ASR transkript metnini kanonikleştiren ve TTS seslendirme ön-izlemesini üreten fonksiyon.
        Dönen sözlük yapısı:
        {
          "source_text": asr_input,
          "canonical_text": ...,
          "detected_brand": ...,
          "detected_model": ...,
          "canonical_vehicle": ...,
          "tts_preview": ...
        }
        """
        res = self.map_asr_to_canonical(asr_input)
        res["tts_preview"] = normalize_text_for_tts(res["canonical_text"])
        return res

    def get_canonical_vehicle(self, raw_name: str) -> Optional[str]:
        """Tekil araç adını veya varyantını kanonik tam araç adına çevirir."""
        if not raw_name:
            return None
        k = tr_lower(normalize_apostrophes(raw_name.strip()))
        return self._canonical_vehicles.get(k)

    def get_canonical_brand(self, raw_brand: str) -> Optional[str]:
        """Tekil marka adını kanonik markaya çevirir."""
        if not raw_brand:
            return None
        k = tr_lower(normalize_apostrophes(raw_brand.strip()))
        return self._canonical_brands.get(k)


# Singleton örneği
asr_mapper = ASRMapper()


def canonicalize_asr_text(asr_input: str) -> Dict[str, Any]:
    """ASR girdisini kanonikleştiren ve tts_preview üreten yardımcı fonksiyon."""
    return asr_mapper.canonicalize_asr_text(asr_input)
