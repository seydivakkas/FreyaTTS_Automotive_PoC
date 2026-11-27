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
import threading
from dataclasses import dataclass
from enum import StrEnum

from backend.core.configuration.contracts import ConfigSnapshot
from backend.core.configuration.feature_flags import FeatureFlagRegistry
from backend.core.contracts.validation import require_finite, require_strict_int


class F1RouteMode(StrEnum):
    """Execution mode for F1 acoustic segmentation."""

    OFF = "off"
    STRICT = "strict"
    SHADOW = "shadow"


@dataclass(frozen=True, slots=True)
class F1ProfileConfig:
    """Validated, immutable acoustic VAD & endpointing profile pinned per stream."""

    profile_name: str = "strict_experimental"
    route_mode: F1RouteMode = F1RouteMode.STRICT
    sample_rate_hz: int = 16000
    channels: int = 1
    window_samples: int = 512
    start_threshold: float = 0.60
    end_threshold: float = 0.35
    onset_confirmation_windows: int = 2
    pre_roll_samples: int = 5120
    post_roll_samples: int = 2560
    endpoint_silence_samples: int = 5120
    max_utterance_samples: int = 320000
    history_capacity_samples: int = 6656
    max_pending_input_samples: int = 16000
    max_pending_bytes: int = 64000
    idle_watchdog_ms: int = 15000
    input_stall_watchdog_ms: int = 5000
    allow_eos_model_padding: bool = True
    overlap_consecutive_utterances: bool = False
    model_revision: str = "silero_vad_6.2.3"

    def __post_init__(self) -> None:
        if not isinstance(self.profile_name, str) or not self.profile_name.strip():
            raise ValueError("profile_name must be non-empty str")
        if not isinstance(self.route_mode, F1RouteMode):
            raise ValueError("route_mode must be F1RouteMode")
        require_strict_int(self.sample_rate_hz, "sample_rate_hz", minimum=16000, maximum=16000)
        require_strict_int(self.channels, "channels", minimum=1, maximum=1)
        require_strict_int(self.window_samples, "window_samples", minimum=512, maximum=512)
        start = require_finite(self.start_threshold, "start_threshold", minimum=0.0, maximum=1.0)
        end = require_finite(self.end_threshold, "end_threshold", minimum=0.0, maximum=1.0)
        assert start is not None and end is not None
        if not (0.0 <= end < start <= 1.0):
            raise ValueError(
                f"Thresholds must satisfy 0 <= end_threshold < start_threshold <= 1; got end={end}, start={start}"
            )
        require_strict_int(self.onset_confirmation_windows, "onset_confirmation_windows", minimum=1, maximum=100)
        require_strict_int(self.pre_roll_samples, "pre_roll_samples", minimum=0, maximum=160000)
        require_strict_int(self.post_roll_samples, "post_roll_samples", minimum=0, maximum=160000)
        require_strict_int(self.endpoint_silence_samples, "endpoint_silence_samples", minimum=self.window_samples, maximum=320000)
        if self.post_roll_samples > self.endpoint_silence_samples:
            raise ValueError(
                f"post_roll_samples ({self.post_roll_samples}) must be <= endpoint_silence_samples ({self.endpoint_silence_samples})"
            )
        require_strict_int(self.max_utterance_samples, "max_utterance_samples", minimum=self.window_samples, maximum=16000 * 120)
        min_history = self.pre_roll_samples + (self.onset_confirmation_windows * self.window_samples) + self.window_samples
        require_strict_int(self.history_capacity_samples, "history_capacity_samples", minimum=min_history, maximum=16000 * 120)
        require_strict_int(self.max_pending_input_samples, "max_pending_input_samples", minimum=self.window_samples, maximum=16000 * 60)
        require_strict_int(self.max_pending_bytes, "max_pending_bytes", minimum=self.window_samples * 4, maximum=16000 * 60 * 4)
        require_strict_int(self.idle_watchdog_ms, "idle_watchdog_ms", minimum=100, maximum=600000)
        require_strict_int(self.input_stall_watchdog_ms, "input_stall_watchdog_ms", minimum=100, maximum=600000)
        if type(self.allow_eos_model_padding) is not bool:
            raise ValueError("allow_eos_model_padding must be bool")
        if type(self.overlap_consecutive_utterances) is not bool:
            raise ValueError("overlap_consecutive_utterances must be bool")
        if not isinstance(self.model_revision, str) or not self.model_revision.strip():
            raise ValueError("model_revision must be non-empty str")

    @property
    def required_endpoint_low_windows(self) -> int:
        return math.ceil(self.endpoint_silence_samples / float(self.window_samples))

    @classmethod
    def strict_experimental(cls, *, route_mode: F1RouteMode = F1RouteMode.STRICT) -> "F1ProfileConfig":
        """Proposed strict experimental profile (320ms pre-roll, 64ms onset, 160ms post-roll, 320ms silence, 20s cap)."""
        return cls(
            profile_name="strict_experimental",
            route_mode=route_mode,
            start_threshold=0.60,
            end_threshold=0.35,
            onset_confirmation_windows=2,
            pre_roll_samples=5120,
            post_roll_samples=2560,
            endpoint_silence_samples=5120,
            max_utterance_samples=320000,
            history_capacity_samples=6656,
            overlap_consecutive_utterances=False,
        )

    @classmethod
    def legacy_compatible(cls, *, route_mode: F1RouteMode = F1RouteMode.OFF) -> "F1ProfileConfig":
        """Profile reflecting baseline legacy Endpoint parameters without breaking strict validation."""
        return cls(
            profile_name="legacy_compatible",
            route_mode=route_mode,
            start_threshold=0.55,
            end_threshold=0.5499,
            onset_confirmation_windows=1,
            pre_roll_samples=5120,
            post_roll_samples=4800,
            endpoint_silence_samples=4800,
            max_utterance_samples=625 * 512,
            history_capacity_samples=6656,
            overlap_consecutive_utterances=True,
        )


def parse_f1_route_mode(raw: object) -> F1RouteMode:
    if isinstance(raw, F1RouteMode):
        return raw
    if isinstance(raw, str):
        norm = raw.strip().lower()
        for mode in F1RouteMode:
            if mode.value == norm:
                return mode
    raise ValueError(f"Invalid F1 route mode: {raw!r}; expected off/strict/shadow")


class F1ConfigAdapter:
    """Bridges M03 ConfigSnapshot/FeatureFlagRegistry to immutable per-stream F1 profiles."""

    def __init__(
        self,
        snapshot: ConfigSnapshot | None = None,
        *,
        default_profile: F1ProfileConfig | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._snapshot = snapshot
        self._published_profile = default_profile or F1ProfileConfig.legacy_compatible(route_mode=F1RouteMode.OFF)

    @property
    def current_revision(self) -> str:
        with self._lock:
            return self._snapshot.config_revision if self._snapshot is not None else "default-local"

    @property
    def current_profile(self) -> F1ProfileConfig:
        with self._lock:
            return self._published_profile

    def resolve_from_snapshot(
        self,
        snapshot: ConfigSnapshot,
        *,
        profile_override: F1ProfileConfig | None = None,
    ) -> F1ProfileConfig:
        """Resolve an F1ProfileConfig from an M03 ConfigSnapshot without changing legacy defaults unexpectedly."""
        flags = FeatureFlagRegistry.from_snapshot(snapshot)
        raw_mode = snapshot.feature_flags.get("f1_vad_route_mode", snapshot.values.get("f1_vad_route_mode", "off"))
        mode = parse_f1_route_mode(raw_mode)
        if profile_override is not None:
            resolved = profile_override
        elif mode == F1RouteMode.OFF and not flags.is_enabled("experimental_barge_in_v2"):
            resolved = F1ProfileConfig.legacy_compatible(route_mode=F1RouteMode.OFF)
        else:
            resolved = F1ProfileConfig.strict_experimental(route_mode=mode)
        return resolved

    def publish_revision(
        self,
        snapshot: ConfigSnapshot,
        *,
        profile_override: F1ProfileConfig | None = None,
    ) -> F1ProfileConfig:
        """Publish a new validated configuration revision for future streams only."""
        resolved = self.resolve_from_snapshot(snapshot, profile_override=profile_override)
        with self._lock:
            self._snapshot = snapshot
            self._published_profile = resolved
            return resolved

    def pin_for_stream(self) -> tuple[F1ProfileConfig, str]:
        """Atomically capture the active profile and config revision for a newly opened stream."""
        with self._lock:
            rev = self._snapshot.config_revision if self._snapshot is not None else "default-local"
            return self._published_profile, rev
