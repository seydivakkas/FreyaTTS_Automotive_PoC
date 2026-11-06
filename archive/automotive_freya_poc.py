"""
FreyaTTS Tabanli Otomotiv Sesli Asistani PoC Uygulamasi

Kapsam:
1. Otomotiv Telaffuz Sozlugu (Pronunciation Lexicon) ve Ek Uyumlama (Suffix Re-harmony)
2. Motor hacmi (1.5 TSI), noktasiz fiyat (1250000 TL), saat (14:30'da) ve <UNK> (q, TL, !) duzeltici
3. Noktalama duyarli dinamik duraksama (Prosody) + Konfor gurultusu + 8 kHz Telefon Bandi EQ
4. Asterisk AudioSocket 20 ms Frame Pacer (Re-clamping) ve Barge-in Kesme Sunucusu
"""

import asyncio
import math
import re
import struct
import time
from typing import Dict, List, Tuple

import numpy as np
import soundfile as sf
from scipy import signal

# FreyaTTS ana model ve sabitlerinin ice aktarilmasi (opsiyonel)
try:
    from freyatts import FreyaTTS
    from freyatts.model import LEYLA_SEED
    FREYA_AVAILABLE = True
except Exception:
    FreyaTTS = None
    LEYLA_SEED = 9
    FREYA_AVAILABLE = False

# ==============================================================================
# 1. OTOMOTIV TELAFFUZ SOZLUGU (PRONUNCIATION LEXICON) VE METIN NORMALIZASYONU
# ==============================================================================

AUTOMOTIVE_LEXICON: Dict[str, str] = {
    # Otomobil Markalari
    "volkswagen": "Folksvagen",
    "peugeot": "Pejo",
    "renault": "Reno",
    "citroën": "Sitroen",
    "citroen": "Sitroen",
    "qashqai": "Kaşkai",
    "nissan": "Nisan",
    "hyundai": "Hunday",
    "škoda": "Şkoda",
    "skoda": "Şkoda",
    "dacia": "Daçya",
    "chevrolet": "Şevrole",
    "porsche": "Porşe",
    "mercedes-benz": "Mersedes Benz",
    "mercedes": "Mersedes",
    "audi": "Audi",
    "bmw": "Be Me Ve",
    "chery": "Çeri",
    "togg": "Tog",
    # Model ve Paket Isimleri
    "passat": "Passat",
    "tiguan": "Tiguan",
    "t-roc": "Ti Rok",
    "tucson": "Tukson",
    "megane": "Megan",
    "captur": "Kaptur",
    "kamiq": "Kamik",
    "octavia": "Oktavya",
    "superb": "Süperb",
    "corolla": "Korolla",
    "q2": "ku iki",
    "q3": "ku üç",
    "q5": "ku beş",
    "q7": "ku yedi",
    "q8": "ku sekiz",
    "e-power": "i pavır",
    "e-tech": "i tek",
    "hybrid": "hibrit",
    "lounge": "launc",
    "touch": "taç",
    "prestige": "prestij",
    "comfortline": "komfortlayn",
    "highline": "haylayn",
    "trendline": "trendlayn",
    # Motor, Sanziman ve Guvenlik Kisaltmalari
    "tsi": "te se i",
    "tdi": "te de i",
    "tfsi": "te fe se i",
    "dci": "de ce i",
    "bluehdi": "blu haş de i",
    "hdi": "haş de i",
    "tce": "te ce e",
    "multijet": "multijet",
    "puretech": "pürtek",
    "ecotsi": "eko te se i",
    "dsg": "de se ge",
    "edc": "e de ce",
    "eat8": "e a te sekiz",
    "cvt": "ce ve te",
    "suv": "suv",
    "abs": "a be se",
    "esp": "e se pe",
    "kdv": "ka de ve",
    "ötv": "ö te ve",
    "mtv": "me te ve",
    "tramer": "tramer",
}

_UNITS = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_SCALES = [(10 ** 9, "milyar"), (10 ** 6, "milyon"), (10 ** 3, "bin")]

VOWELS = "aeıioöuüAEIİOÖUÜ"
BACK_VOWELS = "aıouAIOU"
ROUND_VOWELS = "oöuüOÖUÜ"
HARD_CONSONANTS = "fstkçşhpFSTKÇŞHP"


def spell_tr_int(n: int) -> str:
    """Tam sayilari Turkce kurallarina gore yaziya cevirir (1000 -> 'bin', 'bir bin' degil)."""
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + spell_tr_int(-n)
    parts: List[str] = []
    for scale, name in _SCALES:
        if n >= scale:
            head = n // scale
            n = n % scale
            if not (scale == 1000 and head == 1):
                parts.append(spell_tr_int(head))
            parts.append(name)
    if n >= 100:
        if n // 100 > 1:
            parts.append(_UNITS[n // 100])
        parts.append("yüz")
        n = n % 100
    if n >= 10:
        parts.append(_TENS[n // 10])
        n = n % 10
    if n > 0:
        parts.append(_UNITS[n])
    return " ".join(parts)


def harmonize_suffix(stem_spoken: str, raw_suffix: str) -> str:
    """
    Sayi, saat, para birimi veya yabanci marka okunusuna gelen Turkce ekleri
    (orn. 14:30'da -> on dört otuzda, 15:00'de -> on beşte) son sese göre uyumlar.
    """
    stem = stem_spoken.strip()
    suf = raw_suffix.strip().lower()
    if not stem or not suf:
        return stem + suf

    last_vowel = "e"
    for ch in reversed(stem):
        if ch in VOWELS:
            last_vowel = ch.lower()
            break
    ends_with_vowel = stem[-1] in VOWELS
    ends_with_hard = stem[-1] in HARD_CONSONANTS

    is_back = last_vowel in "aıou"
    a_e = "a" if is_back else "e"
    if last_vowel in "aı":
        i_4 = "ı"
    elif last_vowel in "ei":
        i_4 = "i"
    elif last_vowel in "ou":
        i_4 = "u"
    else:
        i_4 = "ü"
    d_t = "t" if ends_with_hard else "d"

    if suf in ("da", "de", "ta", "te"):
        return f"{stem}{d_t}{a_e}"
    if suf in ("dan", "den", "tan", "ten"):
        return f"{stem}{d_t}{a_e}n"
    if suf in ("daki", "deki", "taki", "teki"):
        return f"{stem}{d_t}{a_e}ki"
    if suf in ("dakiler", "dekiler", "takiler", "tekiler"):
        return f"{stem}{d_t}{a_e}kiler"
    if suf in ("a", "e", "ya", "ye"):
        buf = "y" if ends_with_vowel else ""
        return f"{stem}{buf}{a_e}"
    if suf in ("ı", "i", "u", "ü", "yı", "yi", "yu", "yü"):
        buf = "y" if ends_with_vowel else ""
        return f"{stem}{buf}{i_4}"
    if suf in ("ın", "in", "un", "ün", "nın", "nin", "nun", "nün"):
        buf = "n" if ends_with_vowel else ""
        return f"{stem}{buf}{i_4}n"
    if suf in ("dır", "dir", "dur", "dür", "tır", "tir", "tur", "tür"):
        return f"{stem}{d_t}{i_4}r"
    if suf in ("lık", "lik", "luk", "lük"):
        return f"{stem}l{i_4}k"

    return f"{stem}{suf}"


def normalize_automotive_turkish(text: str) -> str:
    """
    FreyaTTS icin otomotiv alanina ozel kapsamli Turkce metin normalizasyonu.
    FreyaTTS'in dahili normalize() fonksiyonundaki 5 temel kisiti giderir.
    """
    t = text.strip()

    # 1. Saat ifadeleri ve ekleri (orn. "14:30'da", "09.00'da", "15:00'e")
    def _replace_time(m: re.Match) -> str:
        prefix = (m.group("prefix") or "")
        hh = int(m.group("h"))
        mm = int(m.group("m"))
        suf = m.group("suf")
        spoken_time = spell_tr_int(hh) if mm == 0 else f"{spell_tr_int(hh)} {spell_tr_int(mm)}"
        if suf:
            spoken_time = harmonize_suffix(spoken_time, suf)
        return f"{prefix}{spoken_time}"

    t = re.sub(
        r"(?P<prefix>(?:saat|yarın|bugün|sabah|akşam)\s+)?\b(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?\b",
        _replace_time,
        t,
        flags=re.IGNORECASE,
    )

    # 2. Motor hacmi sablonlari (orn. "1.5 TSI", "1.6 TDI", "2.0 BlueHDi", "1.3 TCe", "1.5 e-Power")
    def _replace_engine(m: re.Match) -> str:
        major = spell_tr_int(int(m.group("maj")))
        minor = spell_tr_int(int(m.group("min")))
        rest = m.group("rest")
        return f"{major} nokta {minor} {rest}"

    t = re.sub(
        r"\b(?P<maj>[0-6])\.(?P<min>[0-9])\s+(?P<rest>(?:TSI|TDI|TFSI|dCi|BlueHDi|HDi|TCe|MultiJet|PureTech|EcoTSI|e-Power|e-Tech|Hybrid|L|litre)\b)",
        _replace_engine,
        t,
        flags=re.IGNORECASE,
    )

    # 3. Para birimi ve arac fiyatlari (orn. "1.250.000 TL", "1250000 TL", "850.500,50 TL'ye")
    def _replace_currency(m: re.Match) -> str:
        int_part = int(m.group("int").replace(".", ""))
        frac_part = m.group("frac")
        suf = m.group("suf")
        if frac_part and int(frac_part) > 0:
            spoken = f"{spell_tr_int(int_part)} lira {spell_tr_int(int(frac_part))} kuruş"
        else:
            spoken = f"{spell_tr_int(int_part)} Türk lirası"
        if suf:
            spoken = harmonize_suffix(spoken, suf)
        return spoken

    t = re.sub(
        r"\b(?P<int>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<frac>\d{1,2}))?\s*(?:TL|₺|Türk\s+[Ll]irası)(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?",
        _replace_currency,
        t,
    )

    # 4. Kilometre ve diger birimler (orn. "145.000 km'de", "150 bg")
    def _replace_unit(m: re.Match) -> str:
        val = spell_tr_int(int(m.group("num").replace(".", "")))
        unit_map = {"km": "kilometre", "bg": "beygir", "hp": "beygir", "kw": "kilovat"}
        u_spoken = unit_map[m.group("u").lower()]
        suf = m.group("suf")
        if suf:
            u_spoken = harmonize_suffix(u_spoken, suf)
        return f"{val} {u_spoken}"

    t = re.sub(
        r"\b(?P<num>\d{1,3}(?:\.\d{3})+|\d+)\s*(?P<u>km|bg|hp|kw)(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?\b",
        _replace_unit,
        t,
        flags=re.IGNORECASE,
    )

    # 5. Otomotiv Telaffuz Sozlugu (Marka, Model, Kisaltma + Ek Uyumlama)
    for key in sorted(AUTOMOTIVE_LEXICON.keys(), key=len, reverse=True):
        spoken_val = AUTOMOTIVE_LEXICON[key]

        def _lex_sub(m: re.Match, sv: str = spoken_val) -> str:
            suf = m.group("suf")
            return harmonize_suffix(sv, suf) if suf else sv

        pattern = r"\b" + re.escape(key) + r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?\b"
        t = re.sub(pattern, _lex_sub, t, flags=re.IGNORECASE)

    # 6. Kalan standart sayilar, yuzdeler ve ekli sayilar (orn. "%20'si", "2023", "3008")
    def _replace_number(m: re.Match) -> str:
        pct = m.group("pct")
        num_str = m.group("num").replace(".", "")
        suf = m.group("suf")
        if len(num_str) >= 10 and num_str.startswith("0"):
            spoken = " ".join(spell_tr_int(int(ch)) for ch in num_str)
        else:
            spoken = spell_tr_int(int(num_str))
        if pct:
            spoken = f"yüzde {spoken}"
        if suf:
            spoken = harmonize_suffix(spoken, suf)
        return spoken

    t = re.sub(
        r"(?P<pct>%\s*)?\b(?P<num>\d{1,3}(?:\.\d{3})+|\d+)(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?\b",
        _replace_number,
        t,
    )

    # 7. FreyaTTS char_vocab.json <UNK> Guvenlik Agi (kucuk 'q', '!', 'TL', parantez temizligi)
    t = t.replace("!", ".").replace("₺", " Türk lirası ")
    t = t.replace("q", "k").replace("Q", "K").replace("w", "v").replace("W", "V")
    t = re.sub(r"[()\[\]{}\"#$\*\^_`|~<>]", " ", t)
    t = t.replace("...", ", ").replace("…", ", ").replace(" — ", ", ").replace(" - ", ", ")
    return re.sub(r"\s+", " ", t).strip()


# ==============================================================================
# 2. BAGLAC DUYARLI YAN CUMLE BOLUCU VE DINAMIK PROZODI / EQ MOTORU
# ==============================================================================

PAUSE_MAP_SECONDS: Dict[str, float] = {
    "?": 0.32,
    ".": 0.28,
    ";": 0.20,
    ":": 0.20,
    ",": 0.14,
    "conj": 0.08,
}


def split_prosodic_clauses(normalized_text: str, max_words: int = 11) -> List[Tuple[str, float]]:
    """Metni noktalama isaretlerinden ve Turkce baglaclardan bolerek her parçaya
    kendi noktalama turune uygun dinamik duraksama süresi (sn) atar."""
    raw_parts = re.split(r"(?<=[\.?!,;:])\s+", normalized_text)
    clauses_with_pauses: List[Tuple[str, float]] = []

    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        punct = part[-1] if part[-1] in PAUSE_MAP_SECONDS else "."
        pause_sec = PAUSE_MAP_SECONDS.get(punct, 0.20)
        words = part.split()

        if len(words) <= max_words + 2:
            clauses_with_pauses.append((part, pause_sec))
        else:
            chunk: List[str] = []
            for w in words:
                chunk.append(w)
                if len(chunk) >= 7 and w.lower() in ("için", "ve", "ile", "olarak", "ama", "ancak"):
                    clauses_with_pauses.append((" ".join(chunk), PAUSE_MAP_SECONDS["conj"]))
                    chunk = []
                elif len(chunk) >= 15:
                    clauses_with_pauses.append((" ".join(chunk), PAUSE_MAP_SECONDS["conj"]))
                    chunk = []
            if chunk:
                clauses_with_pauses.append((" ".join(chunk), pause_sec))

    return clauses_with_pauses


def apply_fade_and_comfort_noise(wav_48k: np.ndarray, sr: int = 48000, fade_ms: float = 10.0) -> np.ndarray:
    """Yan cumle başı/sonundaki tıklama (click) seslerini kosinüs penceresiyle yumusatır."""
    n_fade = int(sr * (fade_ms / 1000.0))
    if len(wav_48k) > 2 * n_fade:
        fade_in = 0.5 * (1.0 - np.cos(np.linspace(0, math.pi, n_fade, dtype=np.float32)))
        fade_out = 0.5 * (1.0 + np.cos(np.linspace(0, math.pi, n_fade, dtype=np.float32)))
        wav_48k = wav_48k.copy()
        wav_48k[:n_fade] *= fade_in
        wav_48k[-n_fade:] *= fade_out
    return wav_48k


def apply_telephony_eq_and_downsample_8k(wav_48k: np.ndarray) -> np.ndarray:
    """
    48 kHz FreyaTTS ciktisina Antalia-2 Mini tarzi ses berraklastirma EQ'su uygular
    ve anti-aliasing filtre ile Asterisk icin 8 kHz 16-bit PCM (slin16) dizisine indirger.
    """
    sr_in = 48000
    # 1. 80 Hz Yuksek Geciren Filtre (Sub-bass ugultu kesici)
    sos_hp = signal.butter(2, 80.0 / (sr_in / 2), btype="highpass", output="sos")
    y = signal.sosfilt(sos_hp, wav_48k).astype(np.float32)

    # 2. 3.2 kHz Presence Boost (+2.8 dB telefon anlasilirlik artisi)
    b_peak, a_peak = signal.iirpeak(3200.0 / (sr_in / 2), Q=1.5)
    y = (y + 0.35 * signal.lfilter(b_peak, a_peak, y)).astype(np.float32)

    # 3. 48 kHz -> 8 kHz Polifaz (Anti-Aliasing) Asagi Ornekleme (oran 1 / 6)
    y_8k = signal.resample_poly(y, up=1, down=6).astype(np.float32)

    # 4. Yumusak Tepe Sinirlayici (Soft Peak Limiter) ve int16 slin16 donusumu
    y_8k = np.tanh(y_8k * 1.15)
    pcm16 = (np.clip(y_8k, -1.0, 1.0) * 32767.0).round().astype("<i2")
    return pcm16


# ==============================================================================
# 3. FREYATTS OTOMOTIV SENTEZLEYICI VE ASTERISK 20 MS AUDIOSOCKET SUNUCUSU
# ==============================================================================

class AutomotiveFreyaAssistant:
    def __init__(self, model_id: str = "freyavoice/freya-tts", device: str = "cuda"):
        if not FREYA_AVAILABLE:
            raise RuntimeError("freyatts paketi bulunamadi. TTS sentezi devre disi.")
        self.tts = FreyaTTS.from_pretrained(model_id, device=device)
        self.sr_48k = 48000
        self.seed = LEYLA_SEED  # LEYLA_SEED = 9 ile Leyla ses karakterini sabitle

    def synthesize_utterance(self, raw_text: str, steps: int = 32) -> Tuple[np.ndarray, np.ndarray, str]:
        """Tam bir cumleyi normalize eder, dinamik duraksamalarla 48 kHz ve 8 kHz olarak sentezler.
        Donus: (wav_48k_float32, wav_8k_int16, normalized_text)"""
        norm_text = normalize_automotive_turkish(raw_text)
        clause_list = split_prosodic_clauses(norm_text, max_words=self.tts.max_words)

        segments_48k: List[np.ndarray] = []
        rng = np.random.default_rng(seed=42)

        for idx, (clause_str, pause_s) in enumerate(clause_list):
            w = self.tts._synth_one(clause_str, steps=steps, seed=self.seed)
            if not self.tts._voiced_ok(w):
                for offset in (1, 2, 3):
                    w_retry = self.tts._synth_one(clause_str, steps=steps, seed=self.seed + offset)
                    if self.tts._voiced_ok(w_retry):
                        w = w_retry
                        break

            w = apply_fade_and_comfort_noise(w.astype(np.float32), sr=self.sr_48k)
            segments_48k.append(w)

            if idx < len(clause_list) - 1:
                n_gap = int(pause_s * self.sr_48k)
                comfort_gap = rng.normal(0.0, 0.0012, size=n_gap).astype(np.float32)
                segments_48k.append(comfort_gap)

        full_wav_48k = np.concatenate(segments_48k) if segments_48k else np.zeros(0, dtype=np.float32)
        full_pcm_8k = apply_telephony_eq_and_downsample_8k(full_wav_48k)
        return full_wav_48k, full_pcm_8k, norm_text

    async def stream_to_asterisk_audiosocket(
        self,
        writer: asyncio.StreamWriter,
        raw_text: str,
        barge_in_event: asyncio.Event,
        steps: int = 32,
    ):
        """Asterisk app_audiosocket protokolune (0x10 frame type, 320 byte = 20 ms @ 8kHz slin16)
        tam uyumlu, deadline re-clamping yapan ve Barge-in aninda susan akis motoru."""
        norm_text = normalize_automotive_turkish(raw_text)
        clause_list = split_prosodic_clauses(norm_text, max_words=self.tts.max_words)

        FRAME_BYTES = 320  # 160 ornek * 2 byte (8 kHz 16-bit mono)
        FRAME_DURATION = 0.020  # 20 milisaniye
        next_deadline = time.monotonic()

        for clause_str, pause_s in clause_list:
            if barge_in_event.is_set():
                break

            w_48k = await asyncio.to_thread(self.tts._synth_one, clause_str, steps, self.seed)
            w_48k = apply_fade_and_comfort_noise(w_48k.astype(np.float32), sr=self.sr_48k)
            pcm_8k = apply_telephony_eq_and_downsample_8k(w_48k)
            pause_samples = np.zeros(int(pause_s * 8000), dtype="<i2")
            payload_bytes = np.concatenate([pcm_8k, pause_samples]).tobytes()

            for offset in range(0, len(payload_bytes) - FRAME_BYTES + 1, FRAME_BYTES):
                if barge_in_event.is_set():
                    return

                chunk = payload_bytes[offset: offset + FRAME_BYTES]
                header = struct.pack("!BH", 0x10, FRAME_BYTES)
                writer.write(header + chunk)
                await writer.drain()

                now = time.monotonic()
                next_deadline += FRAME_DURATION
                if next_deadline < now:
                    next_deadline = now + FRAME_DURATION
                await asyncio.sleep(max(0.0, next_deadline - now))


# ==============================================================================
# 4. PoC TEST SENARYOLARI CALISTIRICISI (PDF ORNEKLERI DOGRULAMASI)
# ==============================================================================

if __name__ == "__main__":
    test_sentences = [
        "Volkswagen Passat 1.5 TSI aracınız için sizi arıyorum.",
        "Aracınızın tahmini değeri 1.250.000 TL.",
        "Sizin için yarın saat 14:30'da ekspertiz randevusu oluşturabiliriz.",
        "2023 model Nissan Qashqai e-Power aracınızın 145.000 km'deki teklifi 1450000 ₺ olarak onaylandı!",
    ]

    print("=== OTOMOTIV METIN NORMALIZASYONU VE PROZODI DOGRULAMA TESTI ===")
    for idx, s in enumerate(test_sentences, 1):
        norm = normalize_automotive_turkish(s)
        clauses = split_prosodic_clauses(norm)
        print(f"\n[Test {idx}] Ham Girdi   : {s}")
        print(f"[Test {idx}] Normalize   : {norm}")
        print(f"[Test {idx}] Yan Cumleler: {clauses}")

    if FREYA_AVAILABLE:
        print("\n=== FREYATTS SENTEZI ===")
        assistant = AutomotiveFreyaAssistant(device="cuda")
        for idx, s in enumerate(test_sentences, 1):
            wav48, pcm8, _ = assistant.synthesize_utterance(s)
            sf.write(f"poc_test_{idx}_48khz.wav", wav48, 48000)
            sf.write(f"poc_test_{idx}_8khz_telephony.wav", pcm8, 8000, subtype="PCM_16")
            print(f"[Test {idx}] WAV yazildi: poc_test_{idx}_48khz.wav / poc_test_{idx}_8khz_telephony.wav")
    else:
        print("\n[NOT] freyatts paketi bulunamadi; TTS sentezi atlandi. Normalizasyon testi tamamlandi.")
