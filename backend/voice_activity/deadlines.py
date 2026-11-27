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

from backend.core.contracts.common import MetricSample, MetricStatus
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock


@dataclass(frozen=True, slots=True)
class WatchdogStatus:
    ingress_stalled: bool
    idle_timed_out: bool
    ingress_elapsed_ms: float
    idle_elapsed_ms: float


def compute_same_domain_duration_ms(
    *,
    start_ns: int | None,
    start_clock_domain: str | None,
    end_ns: int | None,
    end_clock_domain: str | None,
    metric_name: str,
    observation_scope: str = "SERVER",
) -> MetricSample:
    """
    Compute elapsed duration strictly within a single monotonic clock domain.
    Never subtracts timestamps from missing or mismatched clock domains.
    """
    if start_ns is None or end_ns is None:
        return MetricSample(
            name=metric_name,
            value=None,
            unit="ms",
            observation_scope=observation_scope,
            status=MetricStatus.UNAVAILABLE,
            reason="missing_timestamp",
        )
    if not start_clock_domain or not end_clock_domain or start_clock_domain != end_clock_domain:
        return MetricSample(
            name=metric_name,
            value=None,
            unit="ms",
            observation_scope=observation_scope,
            status=MetricStatus.UNAVAILABLE,
            reason="cross_clock_domain_prohibited",
        )
    if end_ns < start_ns:
        return MetricSample(
            name=metric_name,
            value=None,
            unit="ms",
            observation_scope=observation_scope,
            status=MetricStatus.UNAVAILABLE,
            reason="negative_elapsed_rejected",
        )
    return MetricSample(
        name=metric_name,
        value=(end_ns - start_ns) / 1_000_000.0,
        unit="ms",
        observation_scope=observation_scope,
        status=MetricStatus.MEASURED,
    )


class F1DeadlineMonitor:
    """
    M02-backed monotonic clock & watchdog monitor separating ingress stall
    from acoustic silence and idle no-speech timeout.
    Never advances sample cursor or fabricates silent frames on stall.
    """

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        idle_watchdog_ms: int = 15000,
        input_stall_watchdog_ms: int = 5000,
    ) -> None:
        self.clock: Clock = clock or SystemMonotonicClock()
        self.idle_watchdog_ns = idle_watchdog_ms * 1_000_000
        self.input_stall_watchdog_ns = input_stall_watchdog_ms * 1_000_000
        now_ns = self.clock.monotonic_ns()
        self.last_ingress_ns: int = now_ns
        self.last_voice_ns: int = now_ns

    def record_ingress(self) -> int:
        self.last_ingress_ns = self.clock.monotonic_ns()
        return self.last_ingress_ns

    def record_voice_activity(self) -> int:
        self.last_voice_ns = self.clock.monotonic_ns()
        return self.last_voice_ns

    def evaluate(self, *, speech_active: bool) -> WatchdogStatus:
        now_ns = self.clock.monotonic_ns()
        ingress_elapsed_ns = max(0, now_ns - self.last_ingress_ns)
        idle_elapsed_ns = max(0, now_ns - self.last_voice_ns)
        return WatchdogStatus(
            ingress_stalled=(ingress_elapsed_ns >= self.input_stall_watchdog_ns),
            idle_timed_out=(not speech_active and idle_elapsed_ns >= self.idle_watchdog_ns),
            ingress_elapsed_ms=ingress_elapsed_ns / 1_000_000.0,
            idle_elapsed_ms=idle_elapsed_ns / 1_000_000.0,
        )
