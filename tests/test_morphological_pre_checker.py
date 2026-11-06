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

import time
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.morphology.text_utils import tr_lower, tr_upper, normalize_apostrophes
from backend.morphology.syllabifier import TurkishSyllabifier
from backend.morphology.contracts import (
    NormalizedUtterance,
    ExtendedProsodyPlan,
    WordPhoneticHint,
    generate_hint_for_failed_word,
)
from backend.morphology.lexicon import load_freya_vocab, get_domain_lexicon, get_stress_exceptions
from backend.morphology.inflected_matcher import InflectedLexiconMatcher
from backend.morphology.stress_engine import MorphologicalStressEngine
from backend.morphology.clitics import CliticLookaheadAnalyzer
from backend.morphological_pre_checker import MorphologicalPreChecker, morphological_pre_checker


client = TestClient(app)


# ============================================================================
# F1: Unicode Güvenli tr_lower, tr_upper, normalize_apostrophes
# ============================================================================
def test_f1_unicode_text_utils():
    # 'İ' -> 'i' dönüşümü ve combining dot above (\u0307) kalıntısı olmaması
    res_ist = tr_lower("İSTANBUL")
    assert res_ist == "istanbul"
    assert "\u0307" not in res_ist
    assert len(res_ist) == 8

    # 'I' -> 'ı'
    assert tr_lower("IŞIK") == "ışık"
    assert tr_lower("İĞNE") == "iğne"

    # tr_upper
    assert tr_upper("istanbul") == "İSTANBUL"
    assert tr_upper("ışık") == "IŞIK"

    # normalize_apostrophes
    assert normalize_apostrophes("EcoBoost’un") == "EcoBoost'un"
    assert normalize_apostrophes("SUV`un") == "SUV'un"
    assert normalize_apostrophes("DSG‘ye") == "DSG'ye"


# ============================================================================
# F2: TurkishSyllabifier
# ============================================================================
def test_f2_turkish_syllabifier():
    assert TurkishSyllabifier.syllabify("müşteri") == ["müş", "te", "ri"]
    assert TurkishSyllabifier.syllabify("kardeş") == ["kar", "deş"]
    assert TurkishSyllabifier.syllabify("Türkçe") == ["türk", "çe"]
    assert TurkishSyllabifier.syllabify("araba") == ["a", "ra", "ba"]
    assert TurkishSyllabifier.syllabify("spor") == ["spor"]
    assert TurkishSyllabifier.syllabify("saat") == ["sa", "at"]
    assert TurkishSyllabifier.syllabify("kontrol") == ["kont", "rol"]
    assert TurkishSyllabifier.syllabify("ev") == ["ev"]

    # Ünlüsüz tokenlar ve rakamlar hata vermeden tek parça dönmeli
    assert TurkishSyllabifier.syllabify("km") == ["km"]
    assert TurkishSyllabifier.syllabify("1500") == ["1500"]

    # Ofset doğrulaması
    offsets = TurkishSyllabifier.syllabify_with_offsets("araba")
    assert offsets == [("a", 0, 1), ("ra", 1, 3), ("ba", 3, 5)]


# ============================================================================
# F3 & F4: InflectedLexiconMatcher ve Ünsüz Köprülemesi (Liaison)
# ============================================================================
def test_f3_f4_inflected_matcher_and_liaison():
    lexicon = get_domain_lexicon()
    matcher = InflectedLexiconMatcher(lexicon)

    # 1. Kesmeli + ünsüzle biten kök + ünlüyle başlayan ek -> Liaison (bust+un -> bus-tun)
    hint_ecoboost_un = matcher.match("EcoBoost'un")
    assert hint_ecoboost_un is not None
    assert hint_ecoboost_un.liaison_syllables == ["e", "ko", "bus", "tun"]
    assert hint_ecoboost_un.primary_stress_syllable_idx == 2  # 'bus' hecesinde sabit
    assert "ˈ" in hint_ecoboost_un.phonetic_guide

    # 2. Kesmeli + ünsüzle başlayan ek -> Liaison yok
    hint_ecoboost_ta = matcher.match("EcoBoost'ta")
    assert hint_ecoboost_ta is not None
    assert hint_ecoboost_ta.liaison_syllables is None
    assert hint_ecoboost_ta.morpheme_breakdown == "e-ko-bust-ta"
    assert hint_ecoboost_ta.primary_stress_syllable_idx == 2  # 'bust' hecesinde sabit

    # 3. Kesmesiz en uzun önek eşleşmesi (Bluetoothlu)
    hint_bt = matcher.match("Bluetoothlu")
    assert hint_bt is not None
    assert hint_bt.morpheme_breakdown == "blu-tut-lu"
    assert hint_bt.primary_stress_syllable_idx == 0  # 'blu' hecesinde sabit

    # 4. SUV'lerin
    hint_suv = matcher.match("SUV'lerin")
    assert hint_suv is not None
    assert hint_suv.primary_stress_syllable_idx == 0

    # 5. Normalizer genişletmesi testi
    assert matcher.expand_spoken_token("EcoBoost'un") == "ekobustun"
    assert matcher.expand_spoken_token("Bluetooth'lu") == "blututlu"


# ============================================================================
# F5 & F6: MorphologicalStressEngine & Kalıplaşmış İstisnalar
# ============================================================================
def test_f5_f6_morphological_stress_engine():
    exceptions = get_stress_exceptions()
    engine = MorphologicalStressEngine(exceptions)

    # 1. Kalıplaşmış istisnalar (1. hece)
    hint_halbuki = engine.analyze_word("halbuki")
    assert hint_halbuki is not None
    assert hint_halbuki.primary_stress_syllable_idx == 0
    assert hint_halbuki.stress_reason == "lexicalized_exception"

    hint_cunku = engine.analyze_word("çünkü")
    assert hint_cunku is not None
    assert hint_cunku.primary_stress_syllable_idx == 0

    hint_simdi = engine.analyze_word("şimdi")
    assert hint_simdi is not None
    assert hint_simdi.primary_stress_syllable_idx == 0

    # 2. Olumsuzluk eki (-mA, -mIyor): Vurgu ekin hemen önceki hecesinde
    # gel-me-di -> heceler: ['gel', 'me', 'di'], vurgu 0 ('gel')
    hint_gelmedi = engine.analyze_word("gelmedi")
    assert hint_gelmedi is not None
    assert hint_gelmedi.primary_stress_syllable_idx == 0

    # gö-rüş-tü-rü-le-me-di -> heceler: ['gö', 'rüş', 'tü', 'rü', 'le', 'me', 'di'], vurgu 4 ('le')
    hint_gor = engine.analyze_word("görüştürülemedi")
    assert hint_gor is not None
    assert hint_gor.primary_stress_syllable_idx == 4
    assert "ˈle" in hint_gor.phonetic_guide

    # 3. Zarf-fiil (-ken): gi-der-ken -> heceler: ['gi', 'der', 'ken'], vurgu 1 ('der')
    hint_ken = engine.analyze_word("giderken")
    assert hint_ken is not None
    assert hint_ken.primary_stress_syllable_idx == 1
    assert "ˈder" in hint_ken.phonetic_guide

    # 4. Sıfatlaştıran -deki: ba-yi-de-ki -> heceler: ['ba', 'yi', 'de', 'ki'], vurgu 1 ('yi')
    hint_bayi = engine.analyze_word("bayideki")
    assert hint_bayi is not None
    assert hint_bayi.primary_stress_syllable_idx == 1
    assert "ˈyi" in hint_bayi.phonetic_guide

    # 5. Bildirme eki (-dIr): öğ-ren-ci-dir -> heceler: ['öğ', 'ren', 'ci', 'dir'], vurgu 2 ('ci')
    hint_ogrenci = engine.analyze_word("öğrencidir")
    assert hint_ogrenci is not None
    assert hint_ogrenci.primary_stress_syllable_idx == 2
    assert "ˈci" in hint_ogrenci.phonetic_guide

    # 6. Vasıta/Birliktelik (-lA): müş-te-ri-ler-le -> heceler: ['müş', 'te', 'ri', 'ler', 'le'], vurgu 3 ('ler')
    hint_musteri = engine.analyze_word("müşterilerle")
    assert hint_musteri is not None
    assert hint_musteri.primary_stress_syllable_idx == 3
    assert "ˈler" in hint_musteri.phonetic_guide

    # 7. Eşitlik (-cA): hız-lı-ca -> heceler: ['hız', 'lı', 'ca'], vurgu 1 ('lı')
    hint_hizlica = engine.analyze_word("hızlıca")
    assert hint_hizlica is not None
    assert hint_hizlica.primary_stress_syllable_idx == 1
    assert "ˈlı" in hint_hizlica.phonetic_guide

    # 8. Korunan isim kökü (elma) -> istisnai olumsuzluk sayılmaz
    hint_elma = engine.analyze_word("elma")
    assert hint_elma is None  # Düzenli son hece vurgusu olduğundan istisna dönmez


# ============================================================================
# F7: Clitic Lookahead ve Mikro Duraksama Enjeksiyonu
# ============================================================================
def test_f7_clitics_and_pause_injection():
    analyzer = CliticLookaheadAnalyzer(default_pause_ms=35)
    tokens = "müşterilerle görüştürülemedi de mi".split()
    emphasis, pauses, clitic_idx = analyzer.analyze_tokens(tokens)

    # 'de' ve 'mi' clitic indeksleridir
    assert 2 in clitic_idx
    assert 3 in clitic_idx

    # 'de' öncesindeki 'görüştürülemedi' ve 'mi' öncesindeki 'de' emphasis listesine girmeli
    assert "görüştürülemedi" in emphasis

    # 'de' arkasında noktalama yoksa 35ms pause enjekte edilir
    assert pauses.get(2) == 35

    # Çift duraksama önleme: 'mi?' arkasında soru işareti varsa enjeksiyon yapılmaz
    punct_tokens = "görüştürülemedi de mi?".split()
    _, punct_pauses, _ = analyzer.analyze_tokens(punct_tokens)
    assert 1 in punct_pauses  # 'de' sonrası 35 ms (index 1)
    assert 2 not in punct_pauses  # 'mi?' sonrası noktalama olduğu için atlanır (index 2)


# ============================================================================
# F8: Değişmez Kurallar (Immutable chunk_text & Freya Vocab Güvenliği)
# ============================================================================
def test_immutable_chunk_text_and_vocab_safety():
    checker = MorphologicalPreChecker()
    vocab = load_freya_vocab()

    original_text = "Halbuki yeni EcoBoost'un Bluetoothlu paketi bayideki müşterilerle görüştürülemedi de mi?"
    utt = NormalizedUtterance(
        utterance_id="utt_test_immut",
        chunk_id="chunk_test_immut",
        chunk_text=original_text,
    )

    # 1. Byte-level immutability testi
    plan = checker.analyze(utt)
    assert utt.chunk_text == original_text
    assert utt.chunk_text.encode("utf-8") == original_text.encode("utf-8")

    # 2. Frozen Pydantic modeli mutasyon hatası vermelidir
    with pytest.raises(Exception):
        utt.chunk_text = "değiştirilmiş metin"

    # 3. Model metninde veya hintlerde model sözlüğü dışı karakter olmamalı (Örn: 'ˈ' metne sızmamalı)
    assert "ˈ" not in utt.chunk_text
    # Üretilen her hecede vocab doğrulaması
    for hint in plan.pronunciation_hints:
        if hint.morpheme_breakdown:
            for ch in hint.morpheme_breakdown.replace("-", ""):
                assert ch in vocab or ch.lower() in vocab

    # 4. Failed word hint üreticisi testi
    failed_hint = generate_hint_for_failed_word("ekspertiz")
    assert failed_hint.target_word == "ekspertiz"
    assert failed_hint.morpheme_breakdown == "eks-per-tiz"


# ============================================================================
# Performans Kriteri: Chunk Başına Ortalama < 1.0 ms (1000 Tekrar)
# ============================================================================
def test_performance_micro_benchmark():
    checker = MorphologicalPreChecker()
    test_text = "Halbuki yeni EcoBoost'un Bluetoothlu paketi bayideki müşterilerle görüştürülemedi de mi?"
    utt = NormalizedUtterance(
        utterance_id="utt_bench",
        chunk_id="chk_bench",
        chunk_text=test_text,
    )

    # Isınma turu
    for _ in range(50):
        checker.analyze(utt)

    # 1000 iterasyon ölçümü
    iterations = 1000
    t0 = time.perf_counter()
    for _ in range(iterations):
        checker.analyze(utt)
    t1 = time.perf_counter()

    elapsed_ms = (t1 - t0) * 1000.0
    avg_per_chunk_ms = elapsed_ms / iterations

    # Kriter: Chunk başına ortalama < 1.0 ms olmalıdır (genellikle < 0.15 ms)
    assert avg_per_chunk_ms < 1.0, f"Ortalama analiz süresi 1.0 ms'yi aştı: {avg_per_chunk_ms:.3f} ms"


# ============================================================================
# Feature Flag Testi: MORPH_PRECHECK_ENABLED = False
# ============================================================================
def test_feature_flag_disabled():
    disabled_checker = MorphologicalPreChecker(enabled=False)
    utt = NormalizedUtterance(
        utterance_id="utt_off",
        chunk_id="chk_off",
        chunk_text="EcoBoost'un motoru bayideki müşterilerle görüştürülemedi",
    )
    plan = disabled_checker.analyze(utt)
    assert len(plan.pronunciation_hints) == 0
    assert len(plan.emphasis_targets) == 0
    assert len(plan.pause_injections_ms) == 0


# ============================================================================
# REST API Endpoint Testi: POST /api/frontend/morphological-check
# ============================================================================
def test_api_morphological_check():
    from backend.config import settings
    settings.admin_password = "test-pass"
    client.auth = ("admin", "test-pass")

    payload = {
        "text": "Halbuki yeni EcoBoost'un Bluetoothlu paketi bayideki müşterilerle görüştürülemedi de mi?",
        "include_hints": True,
        "chunk_id": "test_chunk_42",
    }
    resp = client.post("/api/frontend/morphological-check", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["chunk_id"] == "test_chunk_42"
    assert "emphasis_targets" in data
    assert "pause_injections_ms" in data
    assert len(data["pronunciation_hints"]) > 0

    # include_hints = False kontrolü
    payload_no_hints = dict(payload, include_hints=False)
    resp2 = client.post("/api/frontend/morphological-check", json=payload_no_hints)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["pronunciation_hints"]) == 0
