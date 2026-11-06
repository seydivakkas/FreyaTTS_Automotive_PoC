"""Hibrit DTMF Tuşlama ve 8 kHz / 16 kHz Goertzel Dedektörü (DTMF Hybrid Router & DSP)

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

import math
from typing import Any
import numpy as np


# ============================================================================
# 1. DTMF FREKANS MATRİSİ VE GOERTZEL DSP SABİTLERİ
# ============================================================================

LOW_FREQS = [697, 770, 852, 941]
HIGH_FREQS = [1209, 1336, 1477, 1633]
ALL_DTMF_FREQS = LOW_FREQS + HIGH_FREQS

DTMF_MATRIX: dict[tuple[int, int], str] = {
    (697, 1209): "1", (697, 1336): "2", (697, 1477): "3", (697, 1633): "A",
    (770, 1209): "4", (770, 1336): "5", (770, 1477): "6", (770, 1633): "B",
    (852, 1209): "7", (852, 1336): "8", (852, 1477): "9", (852, 1633): "C",
    (941, 1209): "*", (941, 1336): "0", (941, 1477): "#", (941, 1633): "D",
}

DIGIT_TO_FREQS: dict[str, tuple[int, int]] = {
    v: k for k, v in DTMF_MATRIX.items()
}

# Sahte tuş randevu onaylayabildiği için eşikler sıkıdır. Oran 0,35 iken 640 konuşma
# kaydının 56'sında sahte tuş oluşuyordu; bu değerlerle sahte tuş 0, gerçek ton 384/384.
MIN_ENERGY_RATIO = 0.60
MIN_DOMINANCE = 4.0


def _calc_goertzel(samples: np.ndarray, coeff: float) -> float:
    """Tek bir hedef frekans için optimize edilmiş Goertzel büyüklük hesabı."""
    s1 = 0.0
    s2 = 0.0
    for x in samples:
        s0 = float(x) + coeff * s1 - s2
        s2 = s1
        s1 = s0
    return s1 * s1 + s2 * s2 - coeff * s1 * s2


def generate_dtmf_tone(
    digit: str,
    duration_sec: float = 0.08,
    sample_rate: int = 8000,
    amplitude: float = 0.5,
) -> np.ndarray:
    """Sentetik standart çift-tonlu DTMF dalga formu üretir (test ve simülasyon)."""
    d = digit.strip().upper()
    if d not in DIGIT_TO_FREQS:
        raise ValueError(f"Geçersiz DTMF tuşu: {digit}")
    f1, f2 = DIGIT_TO_FREQS[d]
    num_samples = int(sample_rate * duration_sec)
    t = np.arange(num_samples) / float(sample_rate)
    tone = amplitude * (np.sin(2.0 * np.pi * f1 * t) + np.sin(2.0 * np.pi * f2 * t))
    return tone.astype(np.float32)


# ============================================================================
# 2. GOERTZEL DSP DEDEKTÖRÜ VE SES ÇENTİĞİ (AUDIO NOTCH / MUTE)
# ============================================================================

class GoertzelDetector:
    """Ses akışındaki (In-Band) DTMF çift-tonlarını Goertzel algoritmasıyla gerçek zamanlı yakalar.
    
    Yakaladığı tuş seslerini konuşma tanıma (STT/Whisper) tamponundan sessizleştirerek (mute)
    halüsinasyon oluşmasını önler.
    """

    def __init__(self, sample_rate: int = 16000, frame_ms: int = 20):
        self.sample_rate = sample_rate
        self.frame_size = int(sample_rate * (frame_ms / 1000.0))  # 160 samples @ 8kHz, 320 samples @ 16kHz
        self.coeffs = {
            f: 2.0 * math.cos(2.0 * math.pi * f / float(sample_rate))
            for f in ALL_DTMF_FREQS
        }
        self.last_candidate: str | None = None
        self.consecutive_frames: int = 0
        self.last_emitted_digit: str | None = None
        self.silence_frames: int = 0

    def _detect_frame(self, frame: np.ndarray) -> str | None:
        """20 ms'lik tek bir çerçevede DTMF frekans enerjisini analiz eder."""
        tot_energy = float(np.sum(frame ** 2))
        if tot_energy < 0.005:  # Sessizlik eşiği
            return None

        low_powers = [(f, _calc_goertzel(frame, self.coeffs[f])) for f in LOW_FREQS]
        high_powers = [(f, _calc_goertzel(frame, self.coeffs[f])) for f in HIGH_FREQS]

        best_low_f, best_low_p = max(low_powers, key=lambda x: x[1])
        best_high_f, best_high_p = max(high_powers, key=lambda x: x[1])

        # Baskınlık testi: gerçek tonda her grupta tek frekans öne çıkar, konuşmada çıkmaz.
        second_low_p = max(p for f, p in low_powers if f != best_low_f)
        second_high_p = max(p for f, p in high_powers if f != best_high_f)
        if best_low_p < MIN_DOMINANCE * second_low_p or best_high_p < MIN_DOMINANCE * second_high_p:
            return None

        # Enerji konsantrasyon testi
        detected_energy = (best_low_p + best_high_p) / (self.frame_size / 2.0)
        ratio = detected_energy / (tot_energy + 1e-9)

        # Twist testi (Alçak ve yüksek grup genlik oranı <= 8 dB)
        if best_low_p <= 0 or best_high_p <= 0:
            return None
        twist_db = 10.0 * abs(math.log10(best_high_p / best_low_p))

        if ratio >= MIN_ENERGY_RATIO and twist_db <= 8.5:
            return DTMF_MATRIX.get((best_low_f, best_high_f))
        return None

    def process_samples(self, samples: np.ndarray) -> tuple[list[str], np.ndarray]:
        """Gelen ses bloğunu analiz eder.
        
        Döndürür:
          - detected_digits: Debounce edilmiş yeni tespit edilen tuşlar
          - cleaned_samples: Tuş bip sesleri sessizleştirilmiş (STT'ye güvenli) ses
        """
        if len(samples) < self.frame_size:
            return [], samples

        detected_digits: list[str] = []
        cleaned = samples.copy()
        num_frames = len(samples) // self.frame_size

        for i in range(num_frames):
            start = i * self.frame_size
            end = start + self.frame_size
            frame = samples[start:end]

            cand = self._detect_frame(frame)

            if cand is not None:
                # Tuş algılandı: STT'nin 'bip' seslerini kelime sanmasını önlemek için sustur
                cleaned[start:end] = np.zeros(self.frame_size, dtype=np.float32)
                self.silence_frames = 0

                if cand == self.last_candidate:
                    self.consecutive_frames += 1
                else:
                    self.last_candidate = cand
                    self.consecutive_frames = 1

                # En az 2 ardışık çerçeve (>= 40 ms) ve yeni tuş ise tetikle (Debounce)
                if self.consecutive_frames == 2 and cand != self.last_emitted_digit:
                    self.last_emitted_digit = cand
                    detected_digits.append(cand)
            else:
                self.silence_frames += 1
                if self.silence_frames >= 2:
                    self.last_candidate = None
                    self.consecutive_frames = 0
                    self.last_emitted_digit = None

        return detected_digits, cleaned


# ============================================================================
# 3. SIFIR GECİKMELİ DİYALOG EŞLEME VE STT FALLBACK MESAJLARI
# ============================================================================

def format_stt_fallback_message(dialogue: Any) -> str:
    """Gürültü veya ardışık STT tanıma hatalarında devreye giren otomatik tuşlama anonsu."""
    if getattr(dialogue, "awaiting", False):
        return (
            "Ortamınız gürültülü olabilir veya sesinizi net alamadım. "
            "Randevunuzu onaylamak için 1'i, saat seçeneklerini tekrar dinlemek için 2'yi, "
            "müşteri temsilcimize bağlanmak için 0'ı tuşlayabilirsiniz."
        )
    if getattr(dialogue, "options", None) and len(dialogue.options) > 0:
        opts_summary = ", ".join(f"{i + 1}" for i in range(len(dialogue.options)))
        return (
            f"Sizi duyamadım. Müsait saatlerimizden birini seçmek için {opts_summary}'i, "
            "seçenekleri tekrar dinlemek için yıldızı, danışmanımıza bağlanmak için 0'ı tuşlayabilirsiniz."
        )
    if getattr(dialogue, "mode", "inbound") == "outbound_reminder":
        return (
            "Sesiniz net gelmiyor. Randevunuza gelebilecekseniz onaylamak için 1'i, "
            "iptal etmek için 2'yi, danışmanımıza bağlanmak için 0'ı tuşlayabilirsiniz."
        )
    return (
        "Ortamınız gürültülü olabilir. Randevu oluşturmak için aracınızın marka modelini söyleyebilir "
        "veya doğrudan müşteri temsilcimize bağlanmak için 0'ı tuşlayabilirsiniz."
    )

