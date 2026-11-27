"""Waveform finishing and telephone-band conversion."""

import math
import numpy as np
from scipy import signal


def apply_fade_and_comfort_noise(
    wav_48k: np.ndarray, sr: int = 48000, fade_ms: float = 10.0
) -> np.ndarray:
    """Yan cumle başı/sonundaki tıklama (click) seslerini kosinüs penceresiyle yumusatır."""
    n_fade = int(sr * (fade_ms / 1000.0))
    if len(wav_48k) > 2 * n_fade:
        fade_in = 0.5 * (
            1.0 - np.cos(np.linspace(0, math.pi, n_fade, dtype=np.float32))
        )
        fade_out = 0.5 * (
            1.0 + np.cos(np.linspace(0, math.pi, n_fade, dtype=np.float32))
        )
        wav_48k = wav_48k.copy()
        wav_48k[:n_fade] *= fade_in
        wav_48k[-n_fade:] *= fade_out
    return wav_48k


def apply_telephony_eq_and_downsample_8k(
    wav_48k: np.ndarray, hp_cutoff: float = 120.0
) -> np.ndarray:
    """
    48 kHz FreyaTTS ciktisina Antalia-2 Mini tarzi ses berraklastirma EQ'su uygular
    ve anti-aliasing filtre ile Asterisk icin 8 kHz 16-bit PCM (slin16) dizisine indirger.

    1. 120 Hz Yuksek Geciren Filtre (Sub-bass ugultu ve motor kabin rezonansi kesici)
    2. 3.2 kHz Presence Boost (+2.8 dB telefon anlasilirlik artisi)
    3. 48 kHz -> 8 kHz Polifaz (Anti-Aliasing) Asagi Ornekleme (oran 1 / 6)
    4. Yumusak Tepe Sinirlayici (Soft Peak Limiter) ve int16 slin16 donusumu
    """
    sr_in = 48000
    # 1. Yuksek Geciren Filtre (Sub-bass ve motor ugultusu kesici)
    sos_hp = signal.butter(2, hp_cutoff / (sr_in / 2), btype="highpass", output="sos")
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
