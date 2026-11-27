"""Kısa ifadelerde süre şişmesi ve virgülde bölünme regresyonları."""

from backend.batched_ode import clause_frame_count
from backend.text import clauses, normalize


def _parts(text):
    return [part for part, _ in clauses(text)]


def test_short_comma_prefix_merges_with_next_clause():
    assert _parts("Evet, onaylıyorum.") == ["Evet, onaylıyorum."]
    assert _parts("Hayır, başka bir saat olsun.") == ["Hayır, başka bir saat olsun."]


def test_short_comma_prefixes_chain():
    assert _parts("Evet, tamam, olur.") == ["Evet, tamam, olur."]


def test_long_comma_clause_still_splits():
    text = "Bilginizi doğruladıktan sonra değeri açıklayabilirim, ancak kesin fiyat değildir."
    assert _parts(text) == [
        "Bilginizi doğruladıktan sonra değeri açıklayabilirim,",
        "ancak kesin fiyat değildir.",
    ]


def test_sentence_boundary_is_not_merged():
    assert _parts("Evet. Onaylıyorum.") == ["Evet.", "Onaylıyorum."]


def test_spoken_option_ordinals_stay_with_their_clause():
    result = normalize("1. seçenek 25 Kasım saat 10:00. 24. seçenek saat 14:30.")
    assert _parts(result["normalized"]) == [
        "birinci seçenek yirmi beş Kasım saat on.",
        "yirmi dördüncü seçenek saat on dört otuz.",
    ]


def test_trailing_short_comma_clause_is_not_lost():
    assert _parts("Evet,") == ["Evet,"]


def test_merged_clause_pause_comes_from_final_punctuation():
    assert list(clauses("Evet, onaylıyor musunuz?")) == [("Evet, onaylıyor musunuz?", 0.32)]


def test_short_clause_frames_are_capped():
    assert clause_frame_count(5, 22) == 11  # "Evet."
    assert clause_frame_count(6, 26) == 13  # "Uygun."
    assert clause_frame_count(15, 40) == 29


def test_short_clause_keeps_lower_prediction():
    assert clause_frame_count(5, 9) == 9


def test_short_clause_keeps_minimum_frames():
    assert clause_frame_count(1, 2) == 8


def test_longer_clause_prediction_is_untouched():
    assert clause_frame_count(16, 40) == 40
    assert clause_frame_count(60, 95) == 95
    assert clause_frame_count(200, 900) == 300
