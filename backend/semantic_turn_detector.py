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
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
import numpy as np

try:
    import soxr
except ImportError:
    soxr = None


# 1. Türkçe Düşünme, Tereddüt ve Bağlaç Belirteçleri (Unfinished Discourse Markers)
DISCOURSE_MARKERS_UNFINISHED_SINGLE: set[str] = {
    "ve",
    "veya",
    "aslında",
    "fakat",
    "ama",
    "çünkü",
    "yani",
    "ise",
    "ile",
    "için",
    "de",
    "da",
    "ki",
    "belki",
    "sanırım",
    "galiba",
    "şey",
    "ııı",
    "eee",
    "hım",
    "hmm",
    "mesela",
    "örneğin",
    "dolayısıyla",
    "oysa",
    "oysaki",
    "halbuki",
    "hatta",
    "zira",
    "lakin",
    "falan",
    "filan",
    "şöyle",
    "böyle",
}

DISCOURSE_MARKERS_UNFINISHED_MULTI: list[str] = [
    "ya da",
    "dediğim gibi",
    "daha doğrusu",
    "nasıl desem",
    "bir de",
    "aynı zamanda",
    "ondan sonra",
    "diyecektim ki",
    "şöyle ki",
    "düşündüm de",
    "bakayım da",
    "aslına bakarsanız",
    "açıkçası",
    "ne var ki",
    "buna rağmen",
    "bunun yanında",
    "hem de",
]

# 2. Tamamlanmamış Cümle Edatları (Postpositions requiring an ensuing head)
POSTPOSITIONS_INCOMPLETE: set[str] = {
    "kadar",
    "göre",
    "doğru",
    "karşı",
    "rağmen",
    "dolayı",
    "ötürü",
    "itibaren",
    "beri",
    "adına",
    "uğruna",
}

# 3. Türkçe Çekimli Yüklem Sonekleri (Finite Verb Inflection Patterns)
# Türkçe SOV dil yapısında cümlenin bittiğini gösteren ana fiil çekimleri
VERB_PATTERNS: list[re.Pattern] = [
    # Şimdiki zaman: -iyor, -iyoruz, -iyorsunuz...
    re.compile(r"[ıiuü]yor(?:um|sun||uz|sunuz|lar)?$", re.IGNORECASE),
    # Gelecek zaman: -ecek, -eceğim, -acak, -acağız...
    re.compile(r"(?:[e|a]ce[kğ](?:im|sin||iz|siniz|ler)?|[a|e]ca[kğ](?:ım|sın||ız|sınız|lar)?)$", re.IGNORECASE),
    # Görülen geçmiş zaman: -di, -dim, -tik, -tılar...
    re.compile(r"(?:[dt][ıiuü](?:m|n||k|niz|ler)?)$", re.IGNORECASE),
    # Duyulan geçmiş zaman: -miş, -mişim, -miştir...
    re.compile(r"(?:m[ıiuü]ş(?:ım|sın||ız|sınız|lar|tır|tir|tur|tür)?)$", re.IGNORECASE),
    # Geniş zaman: -ir, -irim, -iriz, -er, -eriz, -mez, -mem...
    re.compile(r"(?:[ıiuüae]r(?:im|sin||iz|siniz|ler)?|m[ae]z(?:sin||iz|siniz|ler)?|m[ae]m)$", re.IGNORECASE),
    # Gereklilik kipi: -meli, -meliyim, -malıyız...
    re.compile(r"(?:m[ae]l[ıi](?:yım|yim|sin||yız|yiz|siniz|ler)?)$", re.IGNORECASE),
    # Yeterlilik kipi: -ebilir, -ebilirim, -ebildim, -emem...
    re.compile(r"(?:[ae]bil(?:ir|irim|iriz|irsiniz|irler|di|dim|dik|miş)?)$", re.IGNORECASE),
]

# 4. Tamamlanmış Statik Yüklemler / Kısa Cevaplar (Predicate keywords)
COMPLETING_PREDICATE_WORDS: set[str] = {
    "tamam",
    "olur",
    "olmaz",
    "uygun",
    "uygundur",
    "var",
    "yok",
    "evet",
    "hayır",
    "gelirim",
    "gelemem",
    "isterim",
    "istemiyorum",
    "istiyorum",
    "ederim",
    "ediyorum",
    "gerek",
    "lazım",
    "mümkün",
    "değil",
    "peki",
    "anladım",
    "teşekkürler",
    "sağolun",
    "merhaba",
    "günaydın",
    "iyi günler",
    "iyi akşamlar",
    "lütfen",
}

# 5. Soru Belirteçleri (Question particles & words)
QUESTION_PARTICLES: set[str] = {
    "mi",
    "mı",
    "mu",
    "mü",
    "midir",
    "mıdır",
    "mudur",
    "müdür",
    "misiniz",
    "mısınız",
    "musunuz",
    "müsünüz",
    "miyiz",
    "mıyız",
}


@dataclass
class SemanticAnalysisResult:
    text: str
    is_syntactically_complete: bool
    completeness_score: float  # 0.0 (kesin eksik) - 1.0 (kesin tamamlanmış)
    has_finite_verb: bool
    is_question: bool
    detected_incomplete_markers: List[str] = field(default_factory=list)
    last_word: str = ""
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TurnDecision:
    action: str  # "WAIT" | "COMMIT" | "FORCE_COMMIT"
    is_complete: bool
    confidence: float
    silence_duration_ms: float
    recommended_silence_timeout_ms: float
    reasons: List[str] = field(default_factory=list)
    semantic_analysis: Optional[SemanticAnalysisResult] = None
    acoustic_pitch_slope: Optional[float] = None
    trailing_energy_ratio: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.semantic_analysis:
            d["semantic_analysis"] = self.semantic_analysis.to_dict()
        return d


def normalize_turkish_text(text: str) -> str:
    """Türkçe karakterleri ve noktalama işaretlerini normalize eder."""
    t = text.strip()
    t = re.sub(r"\s+", " ", t)
    return t


def analyze_semantic_completeness(text: str) -> SemanticAnalysisResult:
    """
    Türkçe konuşma transkriptinin dilbilgisel ve anlamsal olarak tamamlanıp tamamlanmadığını
    n-gram bağlaç dedektörü, eksik yüklem denetimi ve soru eki kurallarıyla analiz eder.
    """
    norm = normalize_turkish_text(text)
    if not norm:
        return SemanticAnalysisResult(
            text="",
            is_syntactically_complete=False,
            completeness_score=0.0,
            has_finite_verb=False,
            is_question=False,
            detected_incomplete_markers=["boş_metin"],
            explanation="Metin boş veya algılanamadı.",
        )

    # Noktalamadan arındırılmış kelime listesi
    words = [re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]", "", w).lower() for w in norm.split() if w]
    words = [w for w in words if w]

    if not words:
        return SemanticAnalysisResult(
            text=norm,
            is_syntactically_complete=False,
            completeness_score=0.0,
            has_finite_verb=False,
            is_question=False,
            detected_incomplete_markers=["sadece_noktalama"],
            explanation="Metin yalnızca noktalama içeriyor.",
        )

    last_word = words[-1]
    last_two_words = " ".join(words[-2:]) if len(words) >= 2 else ""
    detected_markers: List[str] = []

    # 1. Soru tespiti (Örn: "?", "mı", "mi", "musunuz", "ne kadar")
    is_question = bool(
        "?" in norm
        or last_word in QUESTION_PARTICLES
        or any(w in QUESTION_PARTICLES for w in words[-2:])
        or last_two_words in {"ne kadar", "kaç para"}
        or last_word in {"kaçta", "nerede", "nasıl", "neden", "niçin"}
    )

    # 2. Çok kelimeli tamamlanmamış bağlaç kontrolü (Örn: "ya da", "dediğim gibi")
    for multi in DISCOURSE_MARKERS_UNFINISHED_MULTI:
        if norm.lower().endswith(multi) or last_two_words == multi:
            detected_markers.append(multi)

    # 3. Tek kelimeli bağlaç veya düşünme belirteci (Örn: "ve", "aslında", "ama", "çünkü")
    if last_word in DISCOURSE_MARKERS_UNFINISHED_SINGLE:
        detected_markers.append(last_word)

    # 4. Cümle sonunda tek başına kalan edat (Örn: "kadar", "göre", "rağmen")
    if last_word in POSTPOSITIONS_INCOMPLETE:
        # "ne kadar" kalıbı veya soru cümleleri edat eksikliği sayılmaz
        if not (last_word == "kadar" and last_two_words == "ne kadar") and not is_question:
            detected_markers.append(f"edat:{last_word}")

    # 5. Çekimli yüklem veya bitirici kelime denetimi
    has_finite_verb = False
    if is_question:
        has_finite_verb = True
    elif last_word in COMPLETING_PREDICATE_WORDS:
        has_finite_verb = True
    else:
        for pat in VERB_PATTERNS:
            if pat.search(last_word):
                has_finite_verb = True
                break

    # 6. Askıda kalma / Duraksama işaretleri (Locative/Ablative suspension without verb)
    # Örn: "saat ikide...", "çarşambaya..."
    is_suspended_locative = bool(
        re.search(r"(?:[d|t][e|a]|[d|t][e|a]n|[y]?[e|a])$", last_word)
        and not has_finite_verb
        and len(words) >= 2
    )
    if is_suspended_locative:
        detected_markers.append("askıda_duraksama")

    # 7. Nihai skor ve karar
    # Eğer bitirici belirteçler tespit edildiyse cümle tamamlanmamıştır
    if detected_markers:
        is_complete = False
        score = 0.15 if "askıda_duraksama" in detected_markers else 0.05
        explanation = f"Tamamlanmamış düşünme belirteci tespit edildi: {', '.join(detected_markers)}"
    elif not has_finite_verb and len(words) > 1:
        # Fiil yoksa eksik cümle
        is_complete = False
        score = 0.35
        explanation = "Cümle sonunda çekimli fiil veya yüklem bulunamadı."
    elif has_finite_verb or is_question:
        # Fiil var veya soru cümlesi
        is_complete = True
        score = 0.95 if is_question else 0.90
        explanation = "Cümle dilbilgisel olarak yüklem veya soru ekiyle tamamlandı."
    else:
        # Tek kelimelik olası onay ("passat", "34abc", "ikide")
        is_complete = True
        score = 0.70
        explanation = "Kısa ifade veya tek kelimelik yanıt."

    return SemanticAnalysisResult(
        text=norm,
        is_syntactically_complete=is_complete,
        completeness_score=score,
        has_finite_verb=has_finite_verb,
        is_question=is_question,
        detected_incomplete_markers=detected_markers,
        last_word=last_word,
        explanation=explanation,
    )


def resample_to_16k(audio: np.ndarray, orig_sr: int) -> np.ndarray:
    """Gelen ses dizisini (örn. 8 kHz telefon) 16 kHz Whisper/VAD standardına dönüştürür."""
    if orig_sr == 16000 or len(audio) == 0:
        return audio.astype(np.float32)

    if soxr is not None:
        try:
            return soxr.resample(audio.astype(np.float32), orig_sr, 16000, quality="HQ")
        except Exception:
            pass

    # Fallback linear interpolation
    duration = len(audio) / orig_sr
    num_target_samples = int(duration * 16000)
    indices = np.linspace(0, len(audio) - 1, num_target_samples)
    return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)


def estimate_f0_pitch_slope(samples_16k: np.ndarray) -> Optional[float]:
    """
    Sesin son 300 ms'lik kısmındaki temel frekans (F0) eğimini (pitch slope) hesaplar.
    - Yükselen veya düz seyreden pitch (slope >= 0.0): Kullanıcının düşünmeye devam ettiğini (floor holding) gösterir.
    - Düşen pitch (slope < -0.05): Cümle bitişi (terminal falling intonation) gösterir.
    """
    if len(samples_16k) < 1600:  # En az 100 ms
        return None

    # Son 300 ms (4800 örnek)
    tail = samples_16k[-4800:] if len(samples_16k) > 4800 else samples_16k
    frame_len = 400   # 25 ms
    hop_len = 160     # 10 ms
    min_lag = int(16000 / 350)  # ~350 Hz tavan
    max_lag = int(16000 / 75)   # ~75 Hz taban

    f0_values: List[float] = []

    for i in range(0, len(tail) - frame_len, hop_len):
        frame = tail[i : i + frame_len]
        energy = np.sum(frame ** 2)
        if energy < 1e-4:
            continue

        # Normalleştirilmiş otokorelasyon
        corr = np.correlate(frame, frame, mode="full")[frame_len - 1 :]
        if len(corr) <= max_lag:
            continue

        search_range = corr[min_lag:max_lag]
        if len(search_range) == 0:
            continue

        peak_idx = np.argmax(search_range) + min_lag
        if corr[0] > 0 and (corr[peak_idx] / corr[0]) > 0.35:
            f0 = 16000.0 / peak_idx
            f0_values.append(f0)

    if len(f0_values) < 3:
        return None

    # Doğrusal regresyon eğimi (linear slope)
    x = np.arange(len(f0_values))
    slope, _ = np.polyfit(x, f0_values, 1)
    # Bağıl eğim (slope / mean_f0)
    mean_f0 = np.mean(f0_values)
    norm_slope = float(slope / mean_f0) if mean_f0 > 0 else float(slope)
    return round(norm_slope, 4)


class SemanticTurnDetector:
    """
    Akustik ve Anlamsal Çift Kademeli Konuşma Sırası (Smart Turn) Dedektörü.
    """

    def __init__(
        self,
        *,
        min_silence_ms: float = 250.0,
        extended_silence_ms: float = 800.0,
        max_hold_ms: float = 2500.0,
        enable_acoustic_pitch: bool = True,
    ):
        self.min_silence_ms = min_silence_ms
        self.extended_silence_ms = extended_silence_ms
        self.max_hold_ms = max_hold_ms
        self.enable_acoustic_pitch = enable_acoustic_pitch

    def analyze_text(self, text: str) -> SemanticAnalysisResult:
        """Metin parçasını anlamsal tamlık açısından analiz eder."""
        return analyze_semantic_completeness(text)

    def decide_turn(
        self,
        *,
        text: str,
        silence_duration_ms: float,
        audio_samples: Optional[np.ndarray] = None,
        sample_rate: int = 16000,
    ) -> TurnDecision:
        """
        Transkript ve ses parametrelerini harmanlayarak konuşma sırası kararı verir:
        - "WAIT": Kullanıcı cümlesini henüz tamamlamadı, sessizlik süresi esnetilmeli, asistan araya girmemeli.
        - "COMMIT": Cümle tamamlandı veya tolerans süresi doldu, LLM yanıtı başlatılabilir.
        - "FORCE_COMMIT": Tavan sınır (max_hold_ms) aşıldı, gecikmeyi önlemek için zorunlu başlatma.
        """
        sem = self.analyze_text(text)
        reasons: List[str] = [sem.explanation]

        pitch_slope: Optional[float] = None
        trailing_ratio: Optional[float] = None

        if audio_samples is not None and len(audio_samples) > 0 and self.enable_acoustic_pitch:
            samples_16k = (
                resample_to_16k(audio_samples, sample_rate)
                if sample_rate != 16000
                else audio_samples
            )
            pitch_slope = estimate_f0_pitch_slope(samples_16k)
            if pitch_slope is not None:
                reasons.append(f"Akustik F0 Eğim: {pitch_slope:+.3f}")

        # Dinamik Sessizlik Eşiği Belirleme
        if not sem.is_syntactically_complete:
            # Cümle eksikse (örn: "Yarın saat ikide... aslında") bekleme süresini 800 ms'ye esnet
            recommended_timeout = self.extended_silence_ms
        elif pitch_slope is not None and pitch_slope >= 0.02:
            # Akustik olarak ses perdesi yükseliyorsa kullanıcı devam edecektir
            recommended_timeout = self.extended_silence_ms
            reasons.append("Akustik yükselen tonlama nedeniyle süre esnetildi.")
        elif sem.is_question:
            # Soru cümlelerinde asistan hızlı yanıt vermelidir
            recommended_timeout = self.min_silence_ms
        else:
            # Normal tamamlanmış cümle
            recommended_timeout = self.min_silence_ms

        # Aksiyon Kararı
        if silence_duration_ms >= self.max_hold_ms:
            action = "FORCE_COMMIT"
            reasons.append(f"Tavan bekleme süresi aşıldı ({self.max_hold_ms} ms).")
        elif silence_duration_ms >= recommended_timeout:
            action = "COMMIT"
            reasons.append(f"Önerilen sessizlik süresi doldu ({recommended_timeout} ms).")
        else:
            action = "WAIT"
            reasons.append(
                f"Kullanıcı henüz tamamlamadı ({silence_duration_ms:.0f} ms < {recommended_timeout} ms). Bekleniyor."
            )

        confidence = sem.completeness_score
        if pitch_slope is not None:
            if pitch_slope < -0.05 and sem.is_syntactically_complete:
                confidence = min(1.0, confidence + 0.05)
            elif pitch_slope >= 0.0:
                confidence = max(0.1, confidence - 0.15)

        return TurnDecision(
            action=action,
            is_complete=sem.is_syntactically_complete,
            confidence=round(confidence, 2),
            silence_duration_ms=round(silence_duration_ms, 1),
            recommended_silence_timeout_ms=round(recommended_timeout, 1),
            reasons=reasons,
            semantic_analysis=sem,
            acoustic_pitch_slope=pitch_slope,
            trailing_energy_ratio=trailing_ratio,
        )


class SmartTurnAudioSocketAdapter:
    """
    Asterisk 8 kHz AudioSocket ve chan_websocket için Akıllı Konuşma Sırası Adaptörü.
    8 kHz gelen ses çerçevelerini SOXR ile 16 kHz'e yukarı örnekler, sessizlik sürelerini
    anlamsal analize göre dinamik esnetir.
    """

    def __init__(
        self,
        *,
        detector: Optional[SemanticTurnDetector] = None,
        sample_rate: int = 8000,
        target_sample_rate: int = 16000,
    ):
        self.detector = detector or SemanticTurnDetector()
        self.sample_rate = sample_rate
        self.target_sample_rate = target_sample_rate
        self.accumulated_pcm_16k = bytearray()
        self.current_silence_ms = 0.0
        self.is_speaking = False

    def reset(self):
        """Oturum tamponlarını sıfırlar."""
        self.accumulated_pcm_16k.clear()
        self.current_silence_ms = 0.0
        self.is_speaking = False

    def process_frame(
        self,
        raw_frame_8k: bytes,
        is_speech: bool,
        frame_duration_ms: float = 20.0,
        partial_transcript: str = "",
    ) -> TurnDecision:
        """
        20 ms'lik bir ses çerçevesini işler.
        Eğer kullanıcı konuşuyorsa sessizlik sayacını sıfırlar; sessizlikte ise
        anlamsal dedektörden aksiyon tavsiyesi alır.
        """
        # 8 kHz -> 16 kHz Dönüştürme
        audio_8k = np.frombuffer(raw_frame_8k, dtype=np.int16).astype(np.float32) / 32768.0
        audio_16k = resample_to_16k(audio_8k, self.sample_rate)

        if is_speech:
            self.is_speaking = True
            self.current_silence_ms = 0.0
            self.accumulated_pcm_16k.extend((audio_16k * 32767.0).astype(np.int16).tobytes())
            return TurnDecision(
                action="WAIT",
                is_complete=False,
                confidence=0.1,
                silence_duration_ms=0.0,
                recommended_silence_timeout_ms=self.detector.extended_silence_ms,
                reasons=["Kullanıcı aktif olarak konuşuyor."],
            )

        # Sessizlik bloğu
        self.current_silence_ms += frame_duration_ms
        recent_samples = (
            np.frombuffer(bytes(self.accumulated_pcm_16k[-9600:]), dtype=np.int16).astype(np.float32) / 32768.0
            if len(self.accumulated_pcm_16k) > 0
            else audio_16k
        )

        decision = self.detector.decide_turn(
            text=partial_transcript,
            silence_duration_ms=self.current_silence_ms,
            audio_samples=recent_samples,
            sample_rate=self.target_sample_rate,
        )

        if decision.action in {"COMMIT", "FORCE_COMMIT"}:
            self.reset()

        return decision
