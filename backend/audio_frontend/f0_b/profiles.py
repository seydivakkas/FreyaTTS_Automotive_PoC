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
from enum import StrEnum


class EnvironmentProfileId(StrEnum):
    """Supported F0-B acoustic environment DSP profile classes (opt-in, not sensor truth)."""

    QUIET_OFFICE = "QUIET_OFFICE"
    PARKED_CAR = "PARKED_CAR"
    MOVING_CAR = "MOVING_CAR"
    WORKSHOP = "WORKSHOP"
    WIND_EXPOSED = "WIND_EXPOSED"
    TELEPHONE_NARROWBAND = "TELEPHONE_NARROWBAND"


@dataclass(frozen=True, slots=True)
class EnhancementProfile:
    """
    Pinned immutable F0-B DSP & AEC profile parameters per stream/epoch.

    Profiles describe signal-processing bounds, never factual vehicle or sensor identity.
    """

    profile_id: EnvironmentProfileId
    profile_revision: str = "f0b-profile-v1"
    hpf_cutoff_hz: float = 120.0
    suppression_db: float = 18.0
    over_subtraction: float = 1.5
    noise_tau_s: float = 0.35
    gain_floor: float = 0.12589254  # 10^(-18/20)
    target_dbfs: float = -16.0
    noise_gate_dbfs: float = -42.0
    max_boost_db: float = 12.0
    max_cut_db: float = 6.0
    gate_attenuation_db: float = 30.0
    limiter_ceiling_dbfs: float = -1.0  # ~0.89125 peak
    aec_max_lag_ms: float = 240.0
    aec_corr_window_ms: float = 80.0
    aec_filter_len_ms: float = 64.0
    aec_mu: float = 0.25
    aec_leakage: float = 1e-4
    browser_aec_preserved: bool = True
    narrowband_ceiling_hz: float | None = None

    def __post_init__(self) -> None:
        if not self.profile_revision:
            raise ValueError("profile_revision required")
        if self.hpf_cutoff_hz <= 0.0:
            raise ValueError("hpf_cutoff_hz must be positive")
        if self.suppression_db < 0.0 or self.suppression_db > 40.0:
            raise ValueError("suppression_db must be in [0, 40]")
        if not (0.0 < self.gain_floor <= 1.0):
            raise ValueError("gain_floor must be in (0, 1]")
        if self.noise_tau_s <= 0.0:
            raise ValueError("noise_tau_s must be positive")
        if not (0.0 < self.aec_mu < 2.0):
            raise ValueError("aec_mu must be in (0, 2)")
        if self.aec_max_lag_ms < 0.0 or self.aec_filter_len_ms <= 0.0:
            raise ValueError("Invalid AEC lag/filter bounds")


ENVIRONMENT_PROFILES: dict[EnvironmentProfileId, EnhancementProfile] = {
    EnvironmentProfileId.QUIET_OFFICE: EnhancementProfile(
        profile_id=EnvironmentProfileId.QUIET_OFFICE,
        hpf_cutoff_hz=80.0,
        suppression_db=12.0,
        over_subtraction=1.1,
        noise_tau_s=0.50,
        gain_floor=10.0 ** (-12.0 / 20.0),
        target_dbfs=-16.0,
        noise_gate_dbfs=-48.0,
        max_boost_db=10.0,
        aec_max_lag_ms=200.0,
        aec_filter_len_ms=64.0,
        aec_mu=0.25,
    ),
    EnvironmentProfileId.PARKED_CAR: EnhancementProfile(
        profile_id=EnvironmentProfileId.PARKED_CAR,
        hpf_cutoff_hz=120.0,
        suppression_db=16.0,
        over_subtraction=1.35,
        noise_tau_s=0.35,
        gain_floor=10.0 ** (-16.0 / 20.0),
        target_dbfs=-16.0,
        noise_gate_dbfs=-44.0,
        max_boost_db=12.0,
        aec_max_lag_ms=160.0,
        aec_filter_len_ms=64.0,
        aec_mu=0.25,
    ),
    EnvironmentProfileId.MOVING_CAR: EnhancementProfile(
        profile_id=EnvironmentProfileId.MOVING_CAR,
        hpf_cutoff_hz=140.0,
        suppression_db=20.0,
        over_subtraction=1.55,
        noise_tau_s=0.25,
        gain_floor=10.0 ** (-20.0 / 20.0),
        target_dbfs=-15.0,
        noise_gate_dbfs=-38.0,
        max_boost_db=12.0,
        aec_max_lag_ms=160.0,
        aec_filter_len_ms=64.0,
        aec_mu=0.20,
    ),
    EnvironmentProfileId.WORKSHOP: EnhancementProfile(
        profile_id=EnvironmentProfileId.WORKSHOP,
        hpf_cutoff_hz=130.0,
        suppression_db=22.0,
        over_subtraction=1.65,
        noise_tau_s=0.20,
        gain_floor=10.0 ** (-22.0 / 20.0),
        target_dbfs=-15.0,
        noise_gate_dbfs=-36.0,
        max_boost_db=10.0,
        aec_max_lag_ms=200.0,
        aec_filter_len_ms=64.0,
        aec_mu=0.20,
    ),
    EnvironmentProfileId.WIND_EXPOSED: EnhancementProfile(
        profile_id=EnvironmentProfileId.WIND_EXPOSED,
        hpf_cutoff_hz=180.0,
        suppression_db=22.0,
        over_subtraction=1.60,
        noise_tau_s=0.18,
        gain_floor=10.0 ** (-22.0 / 20.0),
        target_dbfs=-16.0,
        noise_gate_dbfs=-36.0,
        max_boost_db=9.0,
        aec_max_lag_ms=160.0,
        aec_filter_len_ms=48.0,
        aec_mu=0.18,
    ),
    EnvironmentProfileId.TELEPHONE_NARROWBAND: EnhancementProfile(
        profile_id=EnvironmentProfileId.TELEPHONE_NARROWBAND,
        hpf_cutoff_hz=180.0,
        suppression_db=18.0,
        over_subtraction=1.45,
        noise_tau_s=0.30,
        gain_floor=10.0 ** (-18.0 / 20.0),
        target_dbfs=-16.0,
        noise_gate_dbfs=-40.0,
        max_boost_db=12.0,
        aec_max_lag_ms=240.0,
        aec_filter_len_ms=64.0,
        aec_mu=0.22,
        narrowband_ceiling_hz=3400.0,
    ),
}


def resolve_enhancement_profile(
    profile_id: EnvironmentProfileId | str | None,
) -> EnhancementProfile:
    """Resolve an EnhancementProfile by ID; defaults to PARKED_CAR when None."""
    if profile_id is None:
        return ENVIRONMENT_PROFILES[EnvironmentProfileId.PARKED_CAR]
    pid = (
        profile_id
        if isinstance(profile_id, EnvironmentProfileId)
        else EnvironmentProfileId(str(profile_id))
    )
    return ENVIRONMENT_PROFILES[pid]
