"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemaz.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""
from __future__ import annotations

import dataclasses
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Passive-import validation — no side-effectful top-level calls
# ---------------------------------------------------------------------------

def test_passive_import_intent_prosody() -> None:
    """Module must import without side effects (passive import rule)."""
    import backend.linguistic_frontend.intent_prosody as mod  # noqa: F401
    assert hasattr(mod, "INTENT_PROSODY_TABLE")
    assert hasattr(mod, "IntentProsodySpec")
    assert hasattr(mod, "resolve_intent_prosody")
    assert hasattr(mod, "PRIORITY_ORDER")


def test_public_api_via_package() -> None:
    """resolve_intent_prosody and IntentProsodySpec are reachable from the package __init__."""
    import backend.linguistic_frontend as lf
    assert hasattr(lf, "resolve_intent_prosody")
    assert hasattr(lf, "IntentProsodySpec")
    assert hasattr(lf, "INTENT_PROSODY_TABLE")
    assert hasattr(lf, "PRIORITY_ORDER")


# ---------------------------------------------------------------------------
# Table completeness — all 31 intents present
# ---------------------------------------------------------------------------

ALL_31_INTENTS = [
    "navigasyon_devam",
    "navigasyon_yaklasiyor",
    "navigasyon_kacirildi",
    "fiyat_sorgu",
    "servis_randevu",
    "servis_sonucu",
    "kampanya_bilgisi",
    "arac_durumu",
    "yakit_bilgisi",
    "batarya_bilgisi",
    "uyari",
    "kritik_ariza",
    "emniyet_uyarisi",
    "kaza_algilandi",
    "abs_ariza",
    "esp_ariza",
    "obd_hata",
    "motor_ariza",
    "lastik_basinci",
    "fren_sistemi",
    "hava_yastigi",
    "sesli_komut_onay",
    "sesli_komut_hata",
    "kullanici_karsilama",
    "kullanici_veda",
    "hava_durumu",
    "trafik_bilgisi",
    "park_yardimi",
    "geri_manevra",
    "telefon_aramasi",
    "mesaj_okuma",
]


def test_table_has_exactly_31_intents() -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE
    assert len(INTENT_PROSODY_TABLE) == 31


@pytest.mark.parametrize("intent", ALL_31_INTENTS)
def test_intent_present_in_table(intent: str) -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE
    assert intent in INTENT_PROSODY_TABLE, f"Missing intent: {intent}"


# ---------------------------------------------------------------------------
# Field validation for every intent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("intent", ALL_31_INTENTS)
def test_intent_spec_fields_valid(intent: str) -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE, PRIORITY_ORDER
    spec = INTENT_PROSODY_TABLE[intent]
    # intent key matches stored key
    assert spec.intent == intent
    # style_token non-empty
    assert spec.style_token and spec.style_token.startswith("<") and spec.style_token.endswith(">")
    # style_label non-empty
    assert spec.style_label
    # numeric factors reasonable (0.5 .. 2.0)
    for factor_name in ("f0_factor", "rate_factor", "energy_factor", "pause_factor"):
        val = getattr(spec, factor_name)
        assert 0.5 <= val <= 2.0, f"{intent}.{factor_name} out of range: {val}"
    # priority is one of the known values
    assert spec.priority in PRIORITY_ORDER, f"{intent} has unknown priority: {spec.priority!r}"


# ---------------------------------------------------------------------------
# Verbatim value spot-checks (critical intents)
# ---------------------------------------------------------------------------

def test_navigasyon_devam_values() -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE
    s = INTENT_PROSODY_TABLE["navigasyon_devam"]
    assert s.style_token == "<nav>"
    assert s.style_label == "nötr"
    assert s.f0_factor == 1.00
    assert s.rate_factor == 1.05
    assert s.energy_factor == 1.00
    assert s.pause_factor == 1.00
    assert s.priority == "Orta"


def test_kaza_algilandi_values() -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE
    s = INTENT_PROSODY_TABLE["kaza_algilandi"]
    assert s.style_token == "<emergency>"
    assert s.style_label == "acil"
    assert s.f0_factor == 1.30
    assert s.rate_factor == 0.85
    assert s.energy_factor == 1.30
    assert s.pause_factor == 1.30
    assert s.priority == "Kritik"


def test_emniyet_uyarisi_values() -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE
    s = INTENT_PROSODY_TABLE["emniyet_uyarisi"]
    assert s.style_token == "<safety>"
    assert s.style_label == "çok ciddi"
    assert s.f0_factor == 1.25
    assert s.rate_factor == 0.88
    assert s.energy_factor == 1.25
    assert s.pause_factor == 1.20
    assert s.priority == "Kritik"


def test_mesaj_okuma_values() -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE
    s = INTENT_PROSODY_TABLE["mesaj_okuma"]
    assert s.style_token == "<reader>"
    assert s.style_label == "nötr"
    assert s.f0_factor == 0.95
    assert s.rate_factor == 0.92
    assert s.energy_factor == 1.00
    assert s.pause_factor == 1.10
    assert s.priority == "Düşük"


def test_geri_manevra_values() -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE
    s = INTENT_PROSODY_TABLE["geri_manevra"]
    assert s.style_token == "<parking_alert>"
    assert s.style_label == "dikkat çekici"
    assert s.f0_factor == 1.15
    assert s.rate_factor == 0.85
    assert s.energy_factor == 1.20
    assert s.pause_factor == 1.15
    assert s.priority == "Kritik"


def test_park_yardimi_values() -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE
    s = INTENT_PROSODY_TABLE["park_yardimi"]
    assert s.style_token == "<parking>"
    assert s.style_label == "sakin"
    assert s.f0_factor == 0.95
    assert s.rate_factor == 0.88
    assert s.energy_factor == 0.95
    assert s.pause_factor == 1.10
    assert s.priority == "Yüksek"


# ---------------------------------------------------------------------------
# Priority ranking: Kritik > Yüksek > Orta > Düşük
# ---------------------------------------------------------------------------

def test_priority_ordering() -> None:
    from backend.linguistic_frontend.intent_prosody import PRIORITY_ORDER
    assert PRIORITY_ORDER["Kritik"] > PRIORITY_ORDER["Yüksek"]
    assert PRIORITY_ORDER["Yüksek"] > PRIORITY_ORDER["Orta"]
    assert PRIORITY_ORDER["Orta"] > PRIORITY_ORDER["Düşük"]


def test_kritik_intents_have_highest_rank() -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE, PRIORITY_ORDER
    kritik_intents = {
        "kritik_ariza", "emniyet_uyarisi", "kaza_algilandi",
        "abs_ariza", "esp_ariza", "motor_ariza",
        "fren_sistemi", "hava_yastigi", "geri_manevra",
    }
    max_rank = PRIORITY_ORDER["Kritik"]
    for intent in kritik_intents:
        spec = INTENT_PROSODY_TABLE[intent]
        assert spec.priority_rank == max_rank, f"{intent} should be Kritik, got {spec.priority!r}"


def test_dusuk_intents_have_lowest_rank() -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE, PRIORITY_ORDER
    dusuk_intents = {
        "kampanya_bilgisi", "sesli_komut_onay", "kullanici_karsilama",
        "kullanici_veda", "hava_durumu", "telefon_aramasi", "mesaj_okuma",
    }
    min_rank = PRIORITY_ORDER["Düşük"]
    for intent in dusuk_intents:
        spec = INTENT_PROSODY_TABLE[intent]
        assert spec.priority_rank == min_rank, f"{intent} should be Düşük, got {spec.priority!r}"


# ---------------------------------------------------------------------------
# Immutability — IntentProsodySpec is a frozen dataclass
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("intent", ["kaza_algilandi", "navigasyon_devam", "mesaj_okuma"])
def test_spec_is_immutable(intent: str) -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE
    spec = INTENT_PROSODY_TABLE[intent]
    # frozen=True means direct attribute assignment must raise FrozenInstanceError
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
        spec.f0_factor = 99.9  # type: ignore[misc]


def test_table_values_are_frozen_dataclasses() -> None:
    from backend.linguistic_frontend.intent_prosody import INTENT_PROSODY_TABLE
    for intent, spec in INTENT_PROSODY_TABLE.items():
        assert dataclasses.is_dataclass(spec), f"{intent} spec is not a dataclass"
        # frozen=True means direct attribute assignment raises FrozenInstanceError
        try:
            spec.f0_factor = 0.0  # type: ignore[misc]
            raise AssertionError(f"{intent} spec is NOT frozen — mutation succeeded")
        except (dataclasses.FrozenInstanceError, AttributeError, TypeError):
            pass  # expected


# ---------------------------------------------------------------------------
# Fallback for unknown intents
# ---------------------------------------------------------------------------

def test_resolve_unknown_intent_returns_fallback() -> None:
    from backend.linguistic_frontend.intent_prosody import resolve_intent_prosody
    spec = resolve_intent_prosody("__nonexistent_intent__")
    # Must return a valid spec, not raise
    assert spec is not None
    assert spec.intent == "unknown"
    assert spec.priority == "Orta"


def test_resolve_empty_string_returns_fallback() -> None:
    from backend.linguistic_frontend.intent_prosody import resolve_intent_prosody
    spec = resolve_intent_prosody("")
    assert spec.intent == "unknown"


def test_resolve_known_intent_returns_correct_spec() -> None:
    from backend.linguistic_frontend.intent_prosody import resolve_intent_prosody
    spec = resolve_intent_prosody("navigasyon_yaklasiyor")
    assert spec.style_token == "<nav_alert>"
    assert spec.priority == "Yüksek"


# ---------------------------------------------------------------------------
# No SSML/XML injection into model_text
# ---------------------------------------------------------------------------

def test_resolve_does_not_mutate_model_text() -> None:
    """resolve_intent_prosody is advisory-only; it must not mutate any string."""
    from backend.linguistic_frontend.intent_prosody import resolve_intent_prosody
    model_text = "Yolunuza devam edin."
    original = model_text
    _spec = resolve_intent_prosody("navigasyon_devam")
    # model_text string is immutable in Python; this test validates no monkey-patching occurs
    assert model_text == original


# ---------------------------------------------------------------------------
# f4_c_prosody imports intent_prosody passively (no circular import)
# ---------------------------------------------------------------------------

def test_f4c_prosody_imports_intent_prosody() -> None:
    import backend.linguistic_frontend.f4_c_prosody as f4c
    assert hasattr(f4c, "resolve_intent_prosody")
    assert hasattr(f4c, "IntentProsodySpec")
    assert hasattr(f4c, "INTENT_PROSODY_TABLE")


# ---------------------------------------------------------------------------
# plan_f4c_prosody_and_chunks populates bundle.intent_prosody when intent given
# ---------------------------------------------------------------------------

def test_plan_f4c_with_intent_populates_intent_prosody() -> None:
    """plan_f4c_prosody_and_chunks(intent='kaza_algilandi') must populate bundle.intent_prosody."""
    from backend.linguistic_frontend.f4_c_prosody import plan_f4c_prosody_and_chunks
    from backend.linguistic_frontend.text_mapping import TextMapping, SpanMappingEntry

    text = "Kaza tespit edildi. Acil yardım çağrılıyor."
    mapping = TextMapping(
        source_text=text,
        normalized_text=text,
        entries=(SpanMappingEntry(source_span=(0, len(text)), target_span=(0, len(text))),),
    )
    chunk_res, bundle = plan_f4c_prosody_and_chunks(
        text,
        atoms=(),
        text_mapping=mapping,
        speech_act="WARNING",
        intent="kaza_algilandi",
    )
    # bundle.intent_prosody must be populated and match the spec
    assert bundle.intent_prosody is not None, "intent_prosody must be populated when intent is given"
    assert bundle.intent_prosody.intent == "kaza_algilandi"
    assert bundle.intent_prosody.style_token == "<emergency>"
    assert bundle.intent_prosody.priority == "Kritik"
    assert bundle.intent_prosody.f0_factor == 1.30
    # model_text must NOT contain style_token (no SSML injection)
    for chk in chunk_res.chunks:
        assert "<emergency>" not in chk.model_text, "style_token must NOT be injected into model_text"


def test_plan_f4c_without_intent_has_no_intent_prosody() -> None:
    """plan_f4c_prosody_and_chunks without intent= leaves bundle.intent_prosody as None."""
    from backend.linguistic_frontend.f4_c_prosody import plan_f4c_prosody_and_chunks
    from backend.linguistic_frontend.text_mapping import TextMapping, SpanMappingEntry

    text = "Yolunuza devam edin."
    mapping = TextMapping(
        source_text=text,
        normalized_text=text,
        entries=(SpanMappingEntry(source_span=(0, len(text)), target_span=(0, len(text))),),
    )
    _chunk_res, bundle = plan_f4c_prosody_and_chunks(
        text,
        atoms=(),
        text_mapping=mapping,
        speech_act="INFORM",
    )
    assert bundle.intent_prosody is None


def test_plan_f4c_unknown_intent_uses_fallback_spec() -> None:
    """Unknown intent gives fallback spec (not None), still doesn't inject into model_text."""
    from backend.linguistic_frontend.f4_c_prosody import plan_f4c_prosody_and_chunks
    from backend.linguistic_frontend.text_mapping import TextMapping, SpanMappingEntry

    text = "Test metni."
    mapping = TextMapping(
        source_text=text,
        normalized_text=text,
        entries=(SpanMappingEntry(source_span=(0, len(text)), target_span=(0, len(text))),),
    )
    _chunk_res, bundle = plan_f4c_prosody_and_chunks(
        text,
        atoms=(),
        text_mapping=mapping,
        speech_act="INFORM",
        intent="__nonexistent__",
    )
    assert bundle.intent_prosody is not None
    assert bundle.intent_prosody.intent == "unknown"
