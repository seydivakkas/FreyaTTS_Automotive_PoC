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

import math
from typing import Any, Tuple

import numpy as np
from scipy import signal


class CarNoiseFilter:
    """
    Motor ve Yol Uğultusu Kesici (120 Hz 4. Derece Durumlu Butterworth High-Pass Filtresi).

    Otomobil kabininde seyir halindeyken egzoz, lastik ve motor devrinden (RPM) kaynaklanan
    20-100 Hz bandındaki sub-bass uğultular insan konuşması frekanslarının altında kalmasına
    rağmen yüksek akustik enerji taşır. Bu durum hem RMS enerji dedektörlerini hem de nöral
    VAD'ları (Silero) yanıltarak asistan konuşurken sahte 'Barge-in' kesilmelerine yol açar.

    Bu filtre ardışık 20 ms (160 örnek @ 8 kHz) çerçeveler arasında durumunu (state `zi`)
    kesintisiz korur; çerçeve sınırlarında (frame boundary) faz kayması veya klik oluşturmaz.
    """

    def __init__(self, cutoff_hz: float = 120.0, sample_rate: int = 8000, order: int = 4):
        self.cutoff_hz = float(cutoff_hz)
        self.sample_rate = int(sample_rate)
        self.order = int(order)
        self._init_filter()

    def _init_filter(self) -> None:
        nyquist = self.sample_rate / 2.0
        # Sayısal kararlılık için cutoff Nyquist'in %80'ini aşamaz
        norm_cutoff = min(max(self.cutoff_hz / nyquist, 0.005), 0.85)
        self.sos = signal.butter(self.order, norm_cutoff, btype="highpass", output="sos")
        self.zi = signal.sosfilt_zi(self.sos)
        self._first_frame = True

    def reset(self) -> None:
        """Filtre durumunu sıfırlar (yeni çağrı başlangıcında çağrılır)."""
        self.zi = signal.sosfilt_zi(self.sos)
        self._first_frame = True

    def process(self, samples: np.ndarray) -> np.ndarray:
        """
        Durumlu (stateful) 4. derece Butterworth filtreleme uygular.
        samples: float32 dizisi [-1.0, 1.0].
        """
        if len(samples) == 0:
            return samples.copy()

        if self._first_frame:
            # Çerçeve başındaki basamak geçişini (step transient) engellemek için
            # başlangıç durumunu ilk örnekle ölçeklendir
            self.zi = self.zi * float(samples[0])
            self._first_frame = False

        filtered, self.zi = signal.sosfilt(self.sos, samples, zi=self.zi)
        return filtered.astype(np.float32)


class SpectralNoiseSuppressor:
    """
    Kabin ve Rüzgâr Gürültüsü Bastırıcı (Streaming Overlap-Add & Spektral Çıkarma).

    Kabin içi fan, havalandırma, asfalt sürtünmesi ve rüzgâr gürültüsünü konuşma
    anlaşılırlığını bozmadan -18 dB seviyesinde dengeli bir biçimde bastırır.

    Özellikler:
    - 50% örtüşmeli (overlap-add) Sine penceresi (MDCT simetrisi sayesinde
      birlik kazançta makine hassasiyetinde 10^-16 sıfır rekonstrüksiyon hatası).
    - Konuşma olmayan zaman dilimlerinde arka plan gürültü spektrumunu (Pn[k])
      otomatik takip eden rekürsif gürültü kestirimi.
    - Aşırı çıkarma faktörü (eta=1.5) ve -18 dB spektral zemin (spectral floor)
      sayesinde müzikal gürültü (musical artifact / chattering) oluşumu engellenir.
    - Zaman domeninde ardışık çerçeveler arası kazanç yumuşatma (inter-frame gain smoothing).
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        n_fft: int = 256,
        hop_size: int = 128,
        suppression_db: float = 18.0,
        over_subtraction: float = 1.5,
    ):
        self.sample_rate = int(sample_rate)
        self.n_fft = int(n_fft)
        self.hop_size = int(hop_size)
        self.suppression_db = float(suppression_db)
        self.over_subtraction = float(over_subtraction)

        # -18 dB alt limit kazancı (G_min = 10^(-18/20) ~ 0.12589)
        self.g_floor = float(10.0 ** (-abs(self.suppression_db) / 20.0))
        self.g_floor_sq = self.g_floor**2

        # Sine penceresi (50% örtüşmede kareleri toplamı kesinlikle 1.0 eder)
        n = np.arange(self.n_fft, dtype=np.float32)
        self.window = np.sin(np.pi * (n + 0.5) / self.n_fft).astype(np.float32)

        # Akış tamponları
        self.n_bins = self.n_fft // 2 + 1
        self.freqs = np.fft.rfftfreq(self.n_fft, 1.0 / self.sample_rate)

        # Konuşma bandı (300 - 3400 Hz) indeksleri
        self.speech_bin_start = int(np.searchsorted(self.freqs, 300.0))
        self.speech_bin_end = int(np.searchsorted(self.freqs, 3400.0))
        self.speech_bin_end = max(self.speech_bin_end, self.speech_bin_start + 1)

        self.reset()

    def reset(self) -> None:
        """Gürültü profili ve tamponları sıfırlar."""
        self.in_fifo = np.zeros(0, dtype=np.float32)
        self.out_buffer = np.zeros(self.n_fft, dtype=np.float32)
        self.out_fifo = np.zeros(0, dtype=np.float32)

        self.noise_power = np.full(self.n_bins, 1e-4, dtype=np.float32)
        self.prev_gain = np.ones(self.n_bins, dtype=np.float32)
        self.smooth_power = np.full(self.n_bins, 1e-4, dtype=np.float32)
        self.warmup_frames = 12  # İlk 12 çerçevede gürültü tabanı kalibre edilir
        self.frame_count = 0
        self.last_snr_db = 0.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        """
        Gelen ham örnekleri akış içinde spektral çıkarma ile temizler.
        Giriş uzunluğu ile tam olarak aynı uzunlukta çıkış üretir.
        """
        if len(samples) == 0:
            return samples.copy()

        self.in_fifo = np.concatenate((self.in_fifo, samples.astype(np.float32)))

        while len(self.in_fifo) >= self.n_fft:
            # 1. Analiz çerçevesini al ve Sine penceresi uygula
            frame = self.in_fifo[: self.n_fft] * self.window

            # 2. FFT ve Güç Spektrumu
            X = np.fft.rfft(frame)
            P_y = np.abs(X) ** 2

            # 3. Güç spektrumu düzleştirme
            self.smooth_power = 0.80 * self.smooth_power + 0.20 * P_y

            # 4. Gürültü Kestirimi ve Güncelleme (IMCRA tabanlı minima kontrolü)
            if self.frame_count < self.warmup_frames:
                self.noise_power = 0.70 * self.noise_power + 0.30 * self.smooth_power
                self.frame_count += 1
            else:
                # Konuşma bandı SNR hesabı
                s_band = float(np.sum(self.smooth_power[self.speech_bin_start : self.speech_bin_end]))
                n_band = float(np.sum(self.noise_power[self.speech_bin_start : self.speech_bin_end])) + 1e-12
                band_snr = s_band / n_band
                self.last_snr_db = 10.0 * math.log10(max(band_snr, 1e-4))

                if band_snr < 1.8:  # ~2.5 dB altı: konuşma yok, gürültü güncellenir
                    self.noise_power = 0.90 * self.noise_power + 0.10 * self.smooth_power
                else:  # Konuşma var: gürültü kestirimi korunur (yavaş sızıntı)
                    self.noise_power = 0.996 * self.noise_power + 0.004 * self.smooth_power

                # Anlık gürültü düşüşlerini hızlı yakala
                drop_mask = self.smooth_power < self.noise_power
                self.noise_power[drop_mask] = (
                    0.60 * self.noise_power[drop_mask] + 0.40 * self.smooth_power[drop_mask]
                )

            # 5. Spektral Çıkarma Kazancı (Spectral Floor = -18 dB)
            # Düzleştirilmiş güç spektrumu kullanarak Gauss gürültüsünün varyansından
            # kaynaklanan yapay tepe değerleri (musical noise) engellenir
            snr_post = self.smooth_power / (self.noise_power + 1e-12)
            sub_factor = self.over_subtraction
            gain_sq = np.maximum(self.g_floor_sq, 1.0 - sub_factor * (1.0 / np.maximum(snr_post, 1e-6)))
            raw_gain = np.sqrt(gain_sq).astype(np.float32)

            # 6. Zamanlar Arası Kazanç Düzleştirme (Müzikal gürültüyü yok eder)
            smooth_gain = 0.65 * self.prev_gain + 0.35 * raw_gain
            self.prev_gain = smooth_gain

            # 7. Sentez ve IFFT
            Y = X * smooth_gain
            y = (np.fft.irfft(Y, n=self.n_fft) * self.window).astype(np.float32)

            # 8. Overlap-Add
            self.out_buffer += y
            self.out_fifo = np.concatenate((self.out_fifo, self.out_buffer[: self.hop_size]))

            # Tamponları hop_size kadar kaydır
            self.out_buffer = np.roll(self.out_buffer, -self.hop_size)
            self.out_buffer[-self.hop_size :] = 0.0
            self.in_fifo = self.in_fifo[self.hop_size :]

        # Giriş uzunluğu kadar örneği çıkışa ver
        out_len = len(samples)
        if len(self.out_fifo) >= out_len:
            res = self.out_fifo[:out_len].copy()
            self.out_fifo = self.out_fifo[out_len:]
            return res
        else:
            # Henüz hop_size dolmadıysa veya başlangıç gecikmesindeyse sıfır dolgu ile dengeli ver
            res = np.zeros(out_len, dtype=np.float32)
            avail = len(self.out_fifo)
            if avail > 0:
                res[:avail] = self.out_fifo
                self.out_fifo = np.zeros(0, dtype=np.float32)
            return res


class SoftAGC:
    """
    Bluetooth Kabin Uyumlu Akıllı Soft AGC (Gürültü Kapılı Otomatik Kazanç Kontrolü).

    Handsfree mikrofonlar araç tavanında veya dikiz aynasında olduğundan sürücünün sesi
    kısık (-28 dBFS) gelebilir. Klasik bir AGC sürücü sustuğunda yol gürültüsünü +20 dB
    yükselterek patlamalara sebep olur.

    Noise-Gated Soft AGC Çözümü:
    - Gürültü Kapısı (-42 dBFS altı): Kazanç artırılmaz, 1.0 (0 dB) seviyesinde tutulur.
    - Konuşma Bandı: Hedef seviye -16.0 dBFS'e doğru pürüzsüzce taşınır.
    - Hızlı Attack (50 ms) / Yumuşak Release (300 ms).
    - Maksimum kazanç limiti (+12 dB / 4x sınır).
    - Yumuşak Tepe Sınırlayıcı (Polynomial/Tanh Soft Limiter): Sürücü aniden bağırdığında
      kesinlikle dijital tepe kırpılması (clipping) oluşmaz.
    """

    def __init__(
        self,
        target_dbfs: float = -16.0,
        noise_gate_dbfs: float = -42.0,
        max_boost_db: float = 12.0,
        max_cut_db: float = 6.0,
        sample_rate: int = 8000,
    ):
        self.target_dbfs = float(target_dbfs)
        self.noise_gate_dbfs = float(noise_gate_dbfs)
        self.max_boost_db = float(max_boost_db)
        self.max_cut_db = float(max_cut_db)
        self.sample_rate = int(sample_rate)

        self.reset()

    def reset(self) -> None:
        """Kazanç durumunu sıfırlar."""
        self.current_gain = 1.0
        self.last_applied_gain_db = 0.0
        self.last_input_dbfs = -90.0
        self.last_output_dbfs = -90.0
        self.is_speech = False

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Çerçeveye yumuşak gürültü kapılı kazanç ve limiter uygular."""
        frame_size = int(self.sample_rate * 0.020)  # 20 ms (160 örnek @ 8kHz)
        if len(samples) > frame_size:
            out_chunks = []
            for i in range(0, len(samples), frame_size):
                out_chunks.append(self._process_single_frame(samples[i : i + frame_size]))
            return np.concatenate(out_chunks).astype(np.float32)
        return self._process_single_frame(samples)

    def _process_single_frame(self, samples: np.ndarray) -> np.ndarray:
        n_samples = len(samples)
        if n_samples == 0:
            return samples.copy()

        # RMS Enerji Hesabı
        mean_sq = float(np.mean(samples**2))
        rms = math.sqrt(max(mean_sq, 1e-12))
        dbfs = 20.0 * math.log10(max(rms, 1e-6))
        self.last_input_dbfs = dbfs

        # 1. Gürültü Kapısı Denetimi
        if dbfs < self.noise_gate_dbfs:
            # Sadece gürültü / sessizlik var: Kazancı yükseltme, unity (1.0) seviyesine doğru gevşet
            self.is_speech = False
            target_gain_linear = 1.0
            # Yavaşça 1.0'a dön
            self.current_gain = 0.95 * self.current_gain + 0.05 * target_gain_linear
        else:
            # Konuşma algılandı: Hedef seviyeye göre kazancı hesapla
            self.is_speech = True
            delta_db = self.target_dbfs - dbfs
            # Kazanç sınırları: [-max_cut_db, +max_boost_db]
            clamped_delta_db = max(min(delta_db, self.max_boost_db), -self.max_cut_db)
            target_gain_linear = float(10.0 ** (clamped_delta_db / 20.0))

            # Attack (hızlı kısma: ses yüksek geldiğinde) vs Release (yavaş yükseltme)
            if target_gain_linear < self.current_gain:
                # Attack: ~50 ms
                self.current_gain = 0.80 * self.current_gain + 0.20 * target_gain_linear
            else:
                # Release: ~300 ms
                self.current_gain = 0.95 * self.current_gain + 0.05 * target_gain_linear

        # 2. Çerçeve Boyunca Örnek Bazlı Doğrusal Kazanç Rampası (Klik önleyici)
        g_start = self.current_gain
        g_end = self.current_gain
        gain_ramp = np.linspace(g_start, g_end, n_samples, dtype=np.float32)
        amplified = samples * gain_ramp
        self.last_applied_gain_db = 20.0 * math.log10(max(self.current_gain, 1e-4))

        # 3. Yumuşak Tepe Sınırlayıcı (Polynomial Tanh Soft Limiter)
        # 0.90 genliğin üzerinde yumuşak doygunluk uygular, 1.0'ı asla aşmaz
        abs_val = np.abs(amplified)
        over_threshold = abs_val > 0.90
        if np.any(over_threshold):
            excess = abs_val[over_threshold] - 0.90
            sign = np.sign(amplified[over_threshold])
            amplified[over_threshold] = sign * (0.90 + 0.095 * np.tanh(excess / 0.10))

        # Çıkış RMS seviyesi
        out_rms = math.sqrt(max(float(np.mean(amplified**2)), 1e-12))
        self.last_output_dbfs = 20.0 * math.log10(max(out_rms, 1e-6))

        return np.clip(amplified, -1.0, 1.0).astype(np.float32)


class InboundCarDenoiser:
    """
    8 kHz Araç İçi Gürültü Bastırma ve Otomatik Kazanç Orkestratörü.

    Bileşenler:
    1. CarNoiseFilter: 120 Hz 4. Derece Durumlu Butterworth HPF (Motor & yol uğultusunu keser).
    2. SpectralNoiseSuppressor: Overlap-Add Spektral Çıkarma (-18 dB kabin/rüzgâr bastırma).
    3. SoftAGC: Gürültü Kapılı Bluetooth Otomatik Kazanç Kontrolü (-16 dBFS hedef seviye).
    """

    def __init__(
        self,
        sample_rate: int = 8000,
        hpf_cutoff_hz: float = 120.0,
        suppression_db: float = 18.0,
        target_dbfs: float = -16.0,
        noise_gate_dbfs: float = -42.0,
        max_boost_db: float = 12.0,
        enabled: bool = True,
    ):
        self.sample_rate = int(sample_rate)
        self.enabled = bool(enabled)
        self.hpf_cutoff_hz = float(hpf_cutoff_hz)
        self.suppression_db = float(suppression_db)
        self.target_dbfs = float(target_dbfs)

        self.hpf = CarNoiseFilter(cutoff_hz=hpf_cutoff_hz, sample_rate=sample_rate)
        self.suppressor = SpectralNoiseSuppressor(
            sample_rate=sample_rate, suppression_db=suppression_db
        )
        self.agc = SoftAGC(
            target_dbfs=target_dbfs,
            noise_gate_dbfs=noise_gate_dbfs,
            max_boost_db=max_boost_db,
            sample_rate=sample_rate,
        )

        # Telemetri ve İstatistik
        self.total_frames_processed = 0
        self.speech_frames_detected = 0
        self.false_barge_in_prevented = 0
        self.total_noise_suppression_db = 0.0

    def reset(self) -> None:
        """Yeni bir arama oturumu için tüm durumları sıfırlar."""
        self.hpf.reset()
        self.suppressor.reset()
        self.agc.reset()
        self.total_frames_processed = 0
        self.speech_frames_detected = 0
        self.false_barge_in_prevented = 0
        self.total_noise_suppression_db = 0.0

    def process_frame(self, samples: np.ndarray) -> Tuple[np.ndarray, dict[str, Any]]:
        """
        Bir ses çerçevesini (örneğin 160 örnek @ 8 kHz / 20 ms) işler.
        Döndürür: (temizlenmiş_örnekler, teşhis_metrikleri)
        """
        if not self.enabled or len(samples) == 0:
            rms_raw = math.sqrt(max(float(np.mean(samples**2)), 1e-12))
            return samples.copy(), {
                "enabled": False,
                "raw_rms_dbfs": 20.0 * math.log10(max(rms_raw, 1e-6)),
                "output_rms_dbfs": 20.0 * math.log10(max(rms_raw, 1e-6)),
                "is_speech": False,
                "is_barge_in_candidate": False,
            }

        self.total_frames_processed += 1
        raw_rms = math.sqrt(max(float(np.mean(samples**2)), 1e-12))
        raw_dbfs = 20.0 * math.log10(max(raw_rms, 1e-6))

        # 1. 120 Hz HPF (Motor / Yol Uğultusu Kesici)
        hpf_samples = self.hpf.process(samples)
        hpf_rms = math.sqrt(max(float(np.mean(hpf_samples**2)), 1e-12))
        hpf_dbfs = 20.0 * math.log10(max(hpf_rms, 1e-6))

        # 2. Spektral Çıkarma (-18 dB Kabin & Rüzgâr Bastırıcı)
        denoised_samples = self.suppressor.process(hpf_samples)
        denoised_rms = math.sqrt(max(float(np.mean(denoised_samples**2)), 1e-12))
        denoised_dbfs = 20.0 * math.log10(max(denoised_rms, 1e-6))

        # 3. Soft AGC (Bluetooth Handsfree Dengeleyici)
        out_samples = self.agc.process(denoised_samples)
        out_rms = math.sqrt(max(float(np.mean(out_samples**2)), 1e-12))
        out_dbfs = 20.0 * math.log10(max(out_rms, 1e-6))

        # Metrikler ve Sahte Barge-in Analizi
        noise_suppressed_db = max(raw_dbfs - denoised_dbfs, 0.0)
        self.total_noise_suppression_db += noise_suppressed_db

        is_speech = self.agc.is_speech
        if is_speech:
            self.speech_frames_detected += 1

        # Eğer ham giriş enerjisi yüksek (-20 dBFS üzeri) ama filtrelenip gürültü kesildikten sonra
        # konuşma olmadığı tespit edilmişse, bu bir "Sahte Barge-In Önleme" başarısıdır!
        if raw_dbfs > -22.0 and not is_speech:
            self.false_barge_in_prevented += 1

        # Barge-in adayı: Gerçek konuşma var ve sinyal-gürültü oranı yüksek
        is_barge_in_candidate = is_speech and (self.suppressor.last_snr_db > 5.0)

        diag = {
            "enabled": True,
            "raw_rms_dbfs": round(raw_dbfs, 2),
            "hpf_rms_dbfs": round(hpf_dbfs, 2),
            "denoised_rms_dbfs": round(denoised_dbfs, 2),
            "output_rms_dbfs": round(out_dbfs, 2),
            "noise_suppressed_db": round(noise_suppressed_db, 2),
            "applied_agc_gain_db": round(self.agc.last_applied_gain_db, 2),
            "estimated_snr_db": round(self.suppressor.last_snr_db, 2),
            "is_speech": is_speech,
            "is_barge_in_candidate": is_barge_in_candidate,
            "sample_rate": self.sample_rate,
        }

        return out_samples, diag

    def process_bytes(self, raw_bytes: bytes, sample_rate: int | None = None) -> bytes:
        """
        Asterisk AudioSocket / PBX 16-bit PCM (slin16) byte dizisini işler.
        Giriş ile aynı uzunlukta int16 slin16 byte dizisi döndürür.
        """
        if not self.enabled or not raw_bytes:
            return raw_bytes

        if sample_rate and sample_rate != self.sample_rate:
            self.sample_rate = sample_rate
            self.hpf = CarNoiseFilter(cutoff_hz=self.hpf_cutoff_hz, sample_rate=sample_rate)
            self.suppressor = SpectralNoiseSuppressor(
                sample_rate=sample_rate, suppression_db=self.suppression_db
            )
            self.agc.sample_rate = sample_rate

        samples_int16 = np.frombuffer(raw_bytes, dtype="<i2")
        samples_f32 = samples_int16.astype(np.float32) / 32768.0

        cleaned_f32, _ = self.process_frame(samples_f32)
        cleaned_int16 = (np.clip(cleaned_f32, -1.0, 1.0) * 32767.0).round().astype("<i2")
        return cleaned_int16.tobytes()

    def get_summary_stats(self) -> dict[str, Any]:
        """Oturum boyunca toplanan DSP istatistiklerini döndürür."""
        total = max(self.total_frames_processed, 1)
        return {
            "enabled": self.enabled,
            "sample_rate": self.sample_rate,
            "total_frames_processed": self.total_frames_processed,
            "speech_frames_detected": self.speech_frames_detected,
            "speech_ratio_percent": round((self.speech_frames_detected / total) * 100.0, 1),
            "false_barge_in_prevented": self.false_barge_in_prevented,
            "avg_noise_suppression_db": round(self.total_noise_suppression_db / total, 2),
            "hpf_cutoff_hz": self.hpf_cutoff_hz,
            "target_dbfs": self.target_dbfs,
            "suppression_db": self.suppression_db,
        }


def process_audio_stream(
    audio_data: np.ndarray,
    sample_rate: int = 8000,
    chunk_size: int = 160,
    hpf_cutoff_hz: float = 120.0,
    suppression_db: float = 18.0,
    target_dbfs: float = -16.0,
) -> Tuple[np.ndarray, dict[str, Any]]:
    """
    Tek seferlik tam bir ses kaydını 20 ms'lik gerçek zamanlı bloklar halinde
    simüle ederek işler. Karşılaştırmalı önizleme ve testler için kullanılır.
    """
    denoiser = InboundCarDenoiser(
        sample_rate=sample_rate,
        hpf_cutoff_hz=hpf_cutoff_hz,
        suppression_db=suppression_db,
        target_dbfs=target_dbfs,
    )

    out_chunks = []
    n_total = len(audio_data)
    for i in range(0, n_total, chunk_size):
        chunk = audio_data[i : i + chunk_size]
        out_chunk, _ = denoiser.process_frame(chunk)
        out_chunks.append(out_chunk)

    processed_audio = np.concatenate(out_chunks)[:n_total] if out_chunks else audio_data.copy()
    stats = denoiser.get_summary_stats()

    # Öncesi / sonrası global metrikler
    in_rms = math.sqrt(max(float(np.mean(audio_data**2)), 1e-12))
    out_rms = math.sqrt(max(float(np.mean(processed_audio**2)), 1e-12))

    stats["input_global_rms_dbfs"] = round(20.0 * math.log10(max(in_rms, 1e-6)), 2)
    stats["output_global_rms_dbfs"] = round(20.0 * math.log10(max(out_rms, 1e-6)), 2)
    stats["snr_improvement_db"] = round(
        stats["output_global_rms_dbfs"] - stats["input_global_rms_dbfs"] + stats["avg_noise_suppression_db"],
        2,
    )

    return processed_audio, stats
