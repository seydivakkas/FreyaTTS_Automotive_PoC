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

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Priority ordering (higher index = higher priority)
# ---------------------------------------------------------------------------
PRIORITY_ORDER: dict[str, int] = {
    "Düşük": 0,
    "Orta": 1,
    "Yüksek": 2,
    "Kritik": 3,
}


@dataclass(frozen=True, slots=True)
class IntentProsodySpec:
    """Immutable prosody specification for a single intent."""

    intent: str
    style_token: str       # capability-gated style token (e.g. <nav>)
    style_label: str       # human-readable style label
    f0_factor: float       # pitch multiplier
    rate_factor: float     # speaking-rate multiplier
    energy_factor: float   # energy/loudness multiplier
    pause_factor: float    # inter-phrase pause multiplier
    priority: str          # one of: Düşük | Orta | Yüksek | Kritik

    @property
    def priority_rank(self) -> int:
        return PRIORITY_ORDER.get(self.priority, 0)


# ---------------------------------------------------------------------------
# Full 31-intent mapping table (verbatim from specification)
# ---------------------------------------------------------------------------
INTENT_PROSODY_TABLE: dict[str, IntentProsodySpec] = {
    "navigasyon_devam": IntentProsodySpec(
        intent="navigasyon_devam", style_token="<nav>", style_label="nötr",
        f0_factor=1.00, rate_factor=1.05, energy_factor=1.00, pause_factor=1.00, priority="Orta",
    ),
    "navigasyon_yaklasiyor": IntentProsodySpec(
        intent="navigasyon_yaklasiyor", style_token="<nav_alert>", style_label="dikkat çekici",
        f0_factor=1.10, rate_factor=0.98, energy_factor=1.10, pause_factor=1.10, priority="Yüksek",
    ),
    "navigasyon_kacirildi": IntentProsodySpec(
        intent="navigasyon_kacirildi", style_token="<reroute>", style_label="ciddi",
        f0_factor=1.15, rate_factor=0.95, energy_factor=1.15, pause_factor=1.15, priority="Yüksek",
    ),
    "fiyat_sorgu": IntentProsodySpec(
        intent="fiyat_sorgu", style_token="<info>", style_label="bilgilendirici",
        f0_factor=0.98, rate_factor=1.00, energy_factor=1.00, pause_factor=1.00, priority="Orta",
    ),
    "servis_randevu": IntentProsodySpec(
        intent="servis_randevu", style_token="<assistant>", style_label="profesyonel",
        f0_factor=1.00, rate_factor=1.00, energy_factor=1.00, pause_factor=1.00, priority="Orta",
    ),
    "servis_sonucu": IntentProsodySpec(
        intent="servis_sonucu", style_token="<report>", style_label="resmi",
        f0_factor=0.96, rate_factor=0.95, energy_factor=1.00, pause_factor=1.10, priority="Orta",
    ),
    "kampanya_bilgisi": IntentProsodySpec(
        intent="kampanya_bilgisi", style_token="<friendly>", style_label="pozitif",
        f0_factor=1.08, rate_factor=1.05, energy_factor=1.05, pause_factor=0.95, priority="Düşük",
    ),
    "arac_durumu": IntentProsodySpec(
        intent="arac_durumu", style_token="<status>", style_label="nötr",
        f0_factor=1.00, rate_factor=1.00, energy_factor=1.00, pause_factor=1.00, priority="Orta",
    ),
    "yakit_bilgisi": IntentProsodySpec(
        intent="yakit_bilgisi", style_token="<status>", style_label="nötr",
        f0_factor=1.00, rate_factor=1.00, energy_factor=1.00, pause_factor=1.00, priority="Orta",
    ),
    "batarya_bilgisi": IntentProsodySpec(
        intent="batarya_bilgisi", style_token="<status>", style_label="nötr",
        f0_factor=1.00, rate_factor=0.98, energy_factor=1.05, pause_factor=1.00, priority="Orta",
    ),
    "uyari": IntentProsodySpec(
        intent="uyari", style_token="<warning>", style_label="ciddi",
        f0_factor=1.12, rate_factor=0.95, energy_factor=1.12, pause_factor=1.15, priority="Yüksek",
    ),
    "kritik_ariza": IntentProsodySpec(
        intent="kritik_ariza", style_token="<critical>", style_label="ciddi",
        f0_factor=1.20, rate_factor=0.90, energy_factor=1.20, pause_factor=1.20, priority="Kritik",
    ),
    "emniyet_uyarisi": IntentProsodySpec(
        intent="emniyet_uyarisi", style_token="<safety>", style_label="çok ciddi",
        f0_factor=1.25, rate_factor=0.88, energy_factor=1.25, pause_factor=1.20, priority="Kritik",
    ),
    "kaza_algilandi": IntentProsodySpec(
        intent="kaza_algilandi", style_token="<emergency>", style_label="acil",
        f0_factor=1.30, rate_factor=0.85, energy_factor=1.30, pause_factor=1.30, priority="Kritik",
    ),
    "abs_ariza": IntentProsodySpec(
        intent="abs_ariza", style_token="<critical>", style_label="ciddi",
        f0_factor=1.22, rate_factor=0.90, energy_factor=1.20, pause_factor=1.20, priority="Kritik",
    ),
    "esp_ariza": IntentProsodySpec(
        intent="esp_ariza", style_token="<critical>", style_label="ciddi",
        f0_factor=1.22, rate_factor=0.90, energy_factor=1.20, pause_factor=1.20, priority="Kritik",
    ),
    "obd_hata": IntentProsodySpec(
        intent="obd_hata", style_token="<diagnostic>", style_label="teknik",
        f0_factor=1.05, rate_factor=0.95, energy_factor=1.05, pause_factor=1.10, priority="Yüksek",
    ),
    "motor_ariza": IntentProsodySpec(
        intent="motor_ariza", style_token="<critical>", style_label="ciddi",
        f0_factor=1.25, rate_factor=0.92, energy_factor=1.20, pause_factor=1.25, priority="Kritik",
    ),
    "lastik_basinci": IntentProsodySpec(
        intent="lastik_basinci", style_token="<warning>", style_label="dikkat çekici",
        f0_factor=1.15, rate_factor=0.95, energy_factor=1.15, pause_factor=1.15, priority="Yüksek",
    ),
    "fren_sistemi": IntentProsodySpec(
        intent="fren_sistemi", style_token="<critical>", style_label="ciddi",
        f0_factor=1.25, rate_factor=0.88, energy_factor=1.25, pause_factor=1.25, priority="Kritik",
    ),
    "hava_yastigi": IntentProsodySpec(
        intent="hava_yastigi", style_token="<critical>", style_label="ciddi",
        f0_factor=1.25, rate_factor=0.88, energy_factor=1.25, pause_factor=1.20, priority="Kritik",
    ),
    "sesli_komut_onay": IntentProsodySpec(
        intent="sesli_komut_onay", style_token="<confirm>", style_label="pozitif",
        f0_factor=1.05, rate_factor=1.02, energy_factor=1.05, pause_factor=0.95, priority="Düşük",
    ),
    "sesli_komut_hata": IntentProsodySpec(
        intent="sesli_komut_hata", style_token="<retry>", style_label="yardımcı",
        f0_factor=1.08, rate_factor=0.98, energy_factor=1.05, pause_factor=1.05, priority="Orta",
    ),
    "kullanici_karsilama": IntentProsodySpec(
        intent="kullanici_karsilama", style_token="<welcome>", style_label="sıcak",
        f0_factor=1.10, rate_factor=1.00, energy_factor=1.10, pause_factor=0.95, priority="Düşük",
    ),
    "kullanici_veda": IntentProsodySpec(
        intent="kullanici_veda", style_token="<goodbye>", style_label="sıcak",
        f0_factor=1.05, rate_factor=0.95, energy_factor=1.00, pause_factor=1.00, priority="Düşük",
    ),
    "hava_durumu": IntentProsodySpec(
        intent="hava_durumu", style_token="<info>", style_label="nötr",
        f0_factor=1.00, rate_factor=1.00, energy_factor=1.00, pause_factor=1.00, priority="Düşük",
    ),
    "trafik_bilgisi": IntentProsodySpec(
        intent="trafik_bilgisi", style_token="<traffic>", style_label="ciddi",
        f0_factor=1.08, rate_factor=0.98, energy_factor=1.05, pause_factor=1.10, priority="Orta",
    ),
    "park_yardimi": IntentProsodySpec(
        intent="park_yardimi", style_token="<parking>", style_label="sakin",
        f0_factor=0.95, rate_factor=0.88, energy_factor=0.95, pause_factor=1.10, priority="Yüksek",
    ),
    "geri_manevra": IntentProsodySpec(
        intent="geri_manevra", style_token="<parking_alert>", style_label="dikkat çekici",
        f0_factor=1.15, rate_factor=0.85, energy_factor=1.20, pause_factor=1.15, priority="Kritik",
    ),
    "telefon_aramasi": IntentProsodySpec(
        intent="telefon_aramasi", style_token="<phone>", style_label="doğal",
        f0_factor=1.00, rate_factor=1.00, energy_factor=1.00, pause_factor=1.00, priority="Düşük",
    ),
    "mesaj_okuma": IntentProsodySpec(
        intent="mesaj_okuma", style_token="<reader>", style_label="nötr",
        f0_factor=0.95, rate_factor=0.92, energy_factor=1.00, pause_factor=1.10, priority="Düşük",
    ),
}

# Make table itself immutable (values are already frozen dataclasses)
INTENT_PROSODY_TABLE = dict(INTENT_PROSODY_TABLE)  # keep as plain dict for O(1) lookup

# Fallback spec returned for unknown intents
_FALLBACK_SPEC = IntentProsodySpec(
    intent="unknown", style_token="<info>", style_label="nötr",
    f0_factor=1.00, rate_factor=1.00, energy_factor=1.00, pause_factor=1.00, priority="Orta",
)


def resolve_intent_prosody(intent: str) -> IntentProsodySpec:
    """
    Return the IntentProsodySpec for the given intent key.

    Returns the fallback neutral spec for unknown intents.
    Never raises; always advisory-only — does NOT mutate model_text.
    """
    return INTENT_PROSODY_TABLE.get(intent, _FALLBACK_SPEC)
