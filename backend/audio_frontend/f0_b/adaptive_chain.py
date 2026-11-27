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

from collections import deque
from dataclasses import dataclass

import numpy as np

from backend.audio_frontend.f0_b.acoustic_evidence import (
    AcousticEvidence,
    SnrMethod,
    SnrTap,
    compute_erle_db,
)
from backend.audio_frontend.f0_b.adaptive_denoiser import AdaptiveDenoiserStage
from backend.audio_frontend.f0_b.aec_adapter import AecOutputStatus, BoundedNlmsAec
from backend.audio_frontend.f0_b.delay_estimator import DelayEstimate, DelayStatus, NccDelayEstimator
from backend.audio_frontend.f0_b.double_talk import (
    AdaptationDecision,
    DoubleTalkCategory,
    DoubleTalkClassifier,
    DoubleTalkEvidence,
)
from backend.audio_frontend.legacy_dsp_adapter import LegacyAgcGateStage, LegacyHpfStage
from backend.audio_frontend.f0_b.profiles import EnhancementProfile
from backend.audio_frontend.f0_b.reference_adapter import (
    ClockMappingStatus,
    DeliveryStatus,
    PlaybackReferenceSource,
    resolve_clock_mapping,
)
from backend.audio_frontend.f0_b.rnnoise_adapter import RnnoiseDenoiserAdapter, RnnoiseProvider
from backend.core.contracts.common import MetricStatus
from backend.core.contracts.playback import ObservationScope


@dataclass(frozen=True, slots=True)
class AdaptiveChainResult:
    """Result of one F0-B adaptive DSP block execution."""

    samples: np.ndarray
    route: str
    evidence: AcousticEvidence
    is_speech: bool
    last_applied_gain_db: float


class AdaptiveDspChain:
    """
    Per-stream/epoch F0-B Adaptive DSP, AEC, Double-Talk, and Denoising chain.

    Stage order (single owner, no duplicate HPF or cascaded suppressors):
      1. Optional F6-B reference read + clock mapping + NCC delay estimation
      2. Bounded NLMS AEC (if enabled, eligible reference, confident lag, and browser AEC not duplicated)
      3. Double-talk classification & causal adaptation guard
      4. Legacy 4th-order Butterworth HPF (cutoff from pinned EnhancementProfile)
      5. Adaptive noise PSD estimation + Wiener-style suppressor (or optional RNNoise provider)
      6. Legacy soft AGC/gate + bounded -1 dBFS limiter ceiling
    """

    def __init__(
        self,
        *,
        session_id: str,
        input_stream_id: str,
        input_format_epoch: int,
        sample_rate_hz: int,
        profile: EnhancementProfile,
        aec_enabled: bool = False,
        rnnoise_enabled: bool = False,
        rnnoise_provider: RnnoiseProvider | None = None,
        reference_source: PlaybackReferenceSource | None = None,
        browser_native_aec_active: bool = False,
        bypass: bool = False,
        already_processed: bool = False,
    ) -> None:
        self.session_id = session_id
        self.input_stream_id = input_stream_id
        self.input_format_epoch = int(input_format_epoch)
        self.sample_rate_hz = int(sample_rate_hz)
        self.profile = profile
        self.aec_enabled = bool(aec_enabled)
        self.rnnoise_enabled = bool(rnnoise_enabled)
        self.reference_source = reference_source
        self.browser_native_aec_active = bool(browser_native_aec_active)
        self.bypass = bool(bypass)
        self.already_processed = bool(already_processed)

        self._limiter_ceiling = float(10.0 ** (profile.limiter_ceiling_dbfs / 20.0))

        self.hpf = LegacyHpfStage(
            sample_rate_hz=self.sample_rate_hz,
            cutoff_hz=profile.hpf_cutoff_hz,
            order=4,
        )
        self.delay_estimator = NccDelayEstimator(
            sample_rate_hz=self.sample_rate_hz,
            max_lag_ms=profile.aec_max_lag_ms,
            corr_window_ms=profile.aec_corr_window_ms,
        )
        self.aec = BoundedNlmsAec(
            sample_rate_hz=self.sample_rate_hz,
            filter_len_ms=profile.aec_filter_len_ms,
            mu=profile.aec_mu,
            leakage=profile.aec_leakage,
        )
        self.double_talk = DoubleTalkClassifier()
        self.denoiser = AdaptiveDenoiserStage(
            sample_rate_hz=self.sample_rate_hz,
            profile=profile,
        )
        self.rnnoise: RnnoiseDenoiserAdapter | None = (
            RnnoiseDenoiserAdapter(sample_rate_hz=self.sample_rate_hz, provider=rnnoise_provider)
            if rnnoise_enabled and rnnoise_provider is not None
            else None
        )
        self.agc_gate = LegacyAgcGateStage(
            sample_rate_hz=self.sample_rate_hz,
            target_dbfs=profile.target_dbfs,
            noise_gate_dbfs=profile.noise_gate_dbfs,
            max_boost_db=profile.max_boost_db,
            max_cut_db=profile.max_cut_db,
            gate_attenuation_db=profile.gate_attenuation_db,
        )

        max_mic_hist = max(
            self.delay_estimator.corr_window_samples + self.sample_rate_hz,
            int(0.25 * self.sample_rate_hz),
        )
        self._mic_hist: deque[float] = deque(maxlen=max_mic_hist)

    def reset(self) -> None:
        """Reset all stateful F0-B filters, estimators, and history buffers."""
        self.hpf.reset()
        self.delay_estimator.reset()
        self.aec.reset()
        self.denoiser.reset()
        if self.rnnoise is not None:
            self.rnnoise.reset()
        self.agc_gate.reset()
        self._mic_hist.clear()

    def close(self) -> None:
        self.reset()
        if self.rnnoise is not None:
            self.rnnoise.close()

    def process(
        self,
        samples: np.ndarray,
        *,
        output_start_sample: int = 0,
        output_sample_rate_hz: int = 16000,
        capture_clock_domain: str | None = None,
        dtmf_active: bool = False,
        discontinuity: bool = False,
    ) -> AdaptiveChainResult:
        arr = np.ascontiguousarray(samples, dtype=np.float32)
        n = len(arr)
        out_end = output_start_sample + max(0, int(round(n * output_sample_rate_hz / self.sample_rate_hz)))

        if self.already_processed or self.bypass or n == 0:
            route = "already_processed" if self.already_processed else "bypass"
            ev = AcousticEvidence(
                session_id=self.session_id,
                input_stream_id=self.input_stream_id,
                input_format_epoch=self.input_format_epoch,
                output_start_sample=output_start_sample,
                output_end_exclusive=out_end,
                output_sample_rate_hz=output_sample_rate_hz,
                reference_stream_id=None,
                reference_generation_id=None,
                observation_scope=ObservationScope.UNKNOWN,
                delivery_status=DeliveryStatus.UNAVAILABLE,
                reference_coverage_fraction=None,
                clock_mapping_status=ClockMappingStatus.UNKNOWN,
                delay=None,
                double_talk=None,
                aec_status=AecOutputStatus.BYPASS,
                erle_db=None,
                snr_db=None,
                snr_status=MetricStatus.UNAVAILABLE,
                snr_method=SnrMethod.ESTIMATED,
                snr_tap=SnrTap.PRE_NS,
                snr_reason="dsp_bypass_or_already_processed",
                noise_floor_dbfs=None,
                noise_calibrated=False,
                clipping_fraction=0.0,
                wind_turbulence_detected=False,
                profile_id=self.profile.profile_id.value,
                profile_revision=self.profile.profile_revision,
                discontinuity=discontinuity,
            )
            return AdaptiveChainResult(
                samples=arr.copy(),
                route=route,
                evidence=ev,
                is_speech=False,
                last_applied_gain_db=0.0,
            )

        self._mic_hist.extend(arr.tolist())

        # 1. Optional reference acquisition, delay estimation, double-talk & AEC
        delay_est: DelayEstimate | None = None
        dt_ev: DoubleTalkEvidence | None = None
        aec_status = AecOutputStatus.BYPASS
        erle_db: float | None = None
        ref_stream_id: str | None = None
        ref_gen_id: int | None = None
        obs_scope = ObservationScope.UNKNOWN
        deliv_status = DeliveryStatus.UNAVAILABLE
        ref_cov: float | None = None
        clock_status = ClockMappingStatus.UNKNOWN

        current = arr
        aec_eligible = (
            self.aec_enabled
            and self.reference_source is not None
            and not (self.profile.browser_aec_preserved and self.browser_native_aec_active)
        )

        if aec_eligible and self.reference_source is not None:
            needed = n + self.delay_estimator.max_lag_samples + self.delay_estimator.corr_window_samples
            ref_read = self.reference_source.read_recent(max_samples=needed)
            deliv_status = ref_read.delivery_status
            obs_scope = ref_read.observation_scope
            ref_gen_id = ref_read.latest_generation_id
            cmap = resolve_clock_mapping(capture_clock_domain, ref_read.clock_domain)
            clock_status = cmap.status

            if ref_read.ok and len(ref_read.samples) >= n:
                ref_cov = min(1.0, len(ref_read.samples) / float(max(1, needed)))
                mic_win = np.asarray(list(self._mic_hist), dtype=np.float32)
                delay_est = self.delay_estimator.estimate(mic_win, ref_read.samples)

                aligned_ref: np.ndarray | None = None
                delay_confident = delay_est.status == DelayStatus.CONFIDENT and delay_est.lag_samples is not None
                if delay_confident and delay_est.lag_samples is not None:
                    d = delay_est.lag_samples
                    end_idx = len(ref_read.samples) - d
                    start_idx = end_idx - n
                    if start_idx >= 0 and end_idx <= len(ref_read.samples):
                        aligned_ref = ref_read.samples[start_idx:end_idx]

                # Pre-update double-talk observation using aligned reference
                dt_ev = self.double_talk.classify(
                    mic_samples=arr,
                    aligned_ref_samples=aligned_ref,
                    residual_samples=None,
                    delay_confident=delay_confident,
                    interval_start=output_start_sample,
                    interval_end_exclusive=out_end,
                )

                aec_res = self.aec.process_block(
                    arr,
                    aligned_ref,
                    adaptation=dt_ev.adaptation_decision,
                    bypass=not delay_confident,
                )
                current = aec_res.samples
                aec_status = aec_res.output_status

                # Re-evaluate residual double-talk evidence after AEC
                if aligned_ref is not None and delay_confident:
                    dt_ev = self.double_talk.classify(
                        mic_samples=arr,
                        aligned_ref_samples=aligned_ref,
                        residual_samples=current,
                        delay_confident=True,
                        interval_start=output_start_sample,
                        interval_end_exclusive=out_end,
                    )
                    if (
                        dt_ev.category == DoubleTalkCategory.FAR_END_ONLY_LIKELY
                        and aec_status in {AecOutputStatus.ACTIVE, AecOutputStatus.FROZEN_FILTER}
                    ):
                        erle_db = compute_erle_db(arr, current)

        # 2. HPF (preserving existing 4th-order Butterworth, cutoff from profile)
        current = self.hpf.process(current)

        # 3. Noise suppression: either RNNoise alternative (if verified provider) OR adaptive spectral
        freeze_noise = dtmf_active or (
            dt_ev is not None
            and dt_ev.category in {DoubleTalkCategory.NEAR_END_ONLY_LIKELY, DoubleTalkCategory.DOUBLE_TALK_LIKELY}
        )
        denoise_res = self.denoiser.process(
            current,
            freeze_noise_update=freeze_noise,
            dtmf_active=dtmf_active,
        )
        if self.rnnoise is not None:
            current = self.rnnoise.process(current)
            route = f"f0b_rnnoise:{self.profile.profile_id.value}"
        else:
            current = denoise_res.samples
            route = f"f0b_adaptive:{self.profile.profile_id.value}"

        # 4. Soft AGC + gate + bounded -1 dBFS limiter
        current = self.agc_gate.process(current)
        if self._limiter_ceiling < 1.0:
            current = np.clip(current, -self._limiter_ceiling, self._limiter_ceiling).astype(np.float32)

        snr_val = denoise_res.estimated_snr_db
        snr_status = MetricStatus.MEASURED if snr_val is not None else MetricStatus.UNAVAILABLE
        snr_reason = None if snr_val is not None else "uncalibrated_or_below_floor"
        clip_frac = float(denoise_res.clipped_input_samples) / float(max(1, n))

        ev = AcousticEvidence(
            session_id=self.session_id,
            input_stream_id=self.input_stream_id,
            input_format_epoch=self.input_format_epoch,
            output_start_sample=output_start_sample,
            output_end_exclusive=out_end,
            output_sample_rate_hz=output_sample_rate_hz,
            reference_stream_id=ref_stream_id,
            reference_generation_id=ref_gen_id,
            observation_scope=obs_scope,
            delivery_status=deliv_status,
            reference_coverage_fraction=ref_cov,
            clock_mapping_status=clock_status,
            delay=delay_est,
            double_talk=dt_ev,
            aec_status=aec_status,
            erle_db=erle_db,
            snr_db=snr_val,
            snr_status=snr_status,
            snr_method=SnrMethod.ESTIMATED,
            snr_tap=SnrTap.POST_AEC,
            snr_reason=snr_reason,
            noise_floor_dbfs=denoise_res.noise_floor_dbfs,
            noise_calibrated=denoise_res.noise_calibrated,
            clipping_fraction=clip_frac,
            wind_turbulence_detected=denoise_res.wind_turbulence_detected,
            profile_id=self.profile.profile_id.value,
            profile_revision=self.profile.profile_revision,
            discontinuity=discontinuity,
        )
        return AdaptiveChainResult(
            samples=np.ascontiguousarray(current, dtype=np.float32),
            route=route,
            evidence=ev,
            is_speech=self.agc_gate.is_speech,
            last_applied_gain_db=self.agc_gate.last_applied_gain_db,
        )
