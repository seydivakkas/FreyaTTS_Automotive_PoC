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

from typing import Any, Mapping

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, EventEnvelope, GenerationRef, MetricSample, MetricStatus
from backend.core.contracts.playback import PlaybackEvent, PlaybackProfile
from backend.core.runtime.deadlines import Clock
from backend.core.runtime.result_admission import AdmissionStatus
from backend.observability.event_bus import BoundedEventBus
from backend.observability.evidence import EvidenceKind, EvidenceRecorder
from backend.observability.metrics import MetricsRegistry
from backend.observability.projection import Projection

_SAFE_RENDER_EXTRA_KEYS = frozenset({
    "profile",
    "channel",
    "sequence",
    "sample_count",
    "valid_sample_count",
    "terminal",
    "outcome",
    "completion_stage",
    "bytes_written",
    "reanchored",
    "underrun",
    "discarded_samples",
    "padding_samples",
    "observation_scope",
    "queue_depth",
    "sample_progress",
    "reason",
    "status",
    "stage",
})


class RenderTelemetry:
    """
    M04 observability adapter for F6-A audio rendering and transport.

    - Strictly non-blocking: bus overflows or projection drops are counted as diagnostics
      and NEVER block or fail audio rendering, cancellation, or transport.
    - Never admits raw waveforms, PCM bytes, transcripts, phones, plates, VINs, secrets,
      or file paths into events or metrics.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        bus: BoundedEventBus | None = None,
        metrics: MetricsRegistry | None = None,
        projector: Projection | None = None,
        evidence_recorder: EvidenceRecorder | None = None,
    ) -> None:
        self._clock = clock
        self.projector = projector or Projection()
        self.bus = bus or BoundedEventBus()
        self.metrics = metrics or MetricsRegistry()
        self.evidence = evidence_recorder or EvidenceRecorder(projector=self.projector)
        self._seq = -1
        self.telemetry_drop_count = 0
        self.telemetry_overflow_count = 0

    def _safe_publish(
        self,
        *,
        event_type: str,
        generation_ref: GenerationRef,
        trace_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            self._seq += 1
            projected_meta: dict[str, Any] = {}
            if metadata:
                proj = self.projector.project(
                    dict(metadata),
                    event_type=event_type,
                    extra_allowlist=_SAFE_RENDER_EXTRA_KEYS,
                )
                if proj is None:
                    self.telemetry_drop_count += 1
                    return
                projected_meta = proj

            env = EventEnvelope(
                schema_version=CONTRACT_SCHEMA_VERSION,
                event_type=event_type,
                session_id=generation_ref.session_id,
                trace_id=trace_id,
                turn_id=generation_ref.turn_id,
                generation_id=generation_ref.generation_id,
                sequence=self._seq,
                monotonic_ns=self._clock.monotonic_ns(),
                clock_domain=self._clock.clock_domain,
                producer="backend.audio_rendering",
                metadata=projected_meta,
            )
            status = self.bus.try_publish(env)
            if status == AdmissionStatus.BACKPRESSURE:
                self.telemetry_overflow_count += 1
                self.telemetry_drop_count += 1
            elif status != AdmissionStatus.ACCEPTED:
                self.telemetry_drop_count += 1
        except Exception:
            self.telemetry_drop_count += 1

    def publish_playback_event(self, event: PlaybackEvent) -> None:
        try:
            status = self.bus.try_publish(event.envelope)
            if status == AdmissionStatus.BACKPRESSURE:
                self.telemetry_overflow_count += 1
                self.telemetry_drop_count += 1
            elif status != AdmissionStatus.ACCEPTED:
                self.telemetry_drop_count += 1
        except Exception:
            self.telemetry_drop_count += 1

    def record_render_chunk(
        self,
        *,
        generation_ref: GenerationRef,
        profile: PlaybackProfile,
        wall_ns: int,
        rms_dbfs: float | None,
        rejected_stale: bool = False,
    ) -> None:
        labels = {"profile": profile.value}
        try:
            self.metrics.observe(
                "f6.render.wall_ns",
                float(wall_ns),
                unit="ns",
                observation_scope="SERVER",
                labels=labels,
            )
            if rms_dbfs is None:
                self.metrics.set_gauge(
                    "f6.render.audio_rms_dbfs",
                    None,
                    unit="dBFS",
                    observation_scope="SERVER",
                    labels=labels,
                    status=MetricStatus.UNAVAILABLE,
                    reason="EXACT_SILENCE_NO_FINITE_DBFS",
                )
            else:
                self.metrics.set_gauge(
                    "f6.render.audio_rms_dbfs",
                    rms_dbfs,
                    unit="dBFS",
                    observation_scope="SERVER",
                    labels=labels,
                    status=MetricStatus.MEASURED,
                )
            if rejected_stale:
                self.metrics.inc(
                    "f6.render.rejected_stale",
                    1.0,
                    unit="count",
                    observation_scope="SERVER",
                    labels=labels,
                )
        except Exception:
            self.telemetry_drop_count += 1

        self._safe_publish(
            event_type="pipeline.stage.f6",
            generation_ref=generation_ref,
            metadata={
                "stage": "F6",
                "status": "rejected_stale" if rejected_stale else "rendered",
                "profile": profile.value,
            },
        )

    def record_frame_submitted(
        self,
        *,
        generation_ref: GenerationRef,
        profile: PlaybackProfile,
        sequence: int,
        outcome: str,
        observation_scope: str,
        signed_error_ns: int,
        abs_error_ns: int,
        inter_submit_gap_ns: int | None,
        reanchored: bool,
        underrun: bool,
    ) -> None:
        labels = {"profile": profile.value, "outcome": outcome}
        try:
            self.metrics.inc(
                "f6.transport.frames_submitted",
                1.0,
                unit="frames",
                observation_scope=observation_scope,
                labels=labels,
            )
            self.metrics.observe(
                "f6.pacing.abs_error_ns",
                float(abs_error_ns),
                unit="ns",
                observation_scope=observation_scope,
                labels={"profile": profile.value},
            )
            self.metrics.set_gauge(
                "f6.pacing.last_signed_error_ns",
                float(signed_error_ns),
                unit="ns",
                observation_scope=observation_scope,
                labels={"profile": profile.value},
            )
            if inter_submit_gap_ns is not None:
                self.metrics.observe(
                    "f6.pacing.inter_submit_gap_ns",
                    float(inter_submit_gap_ns),
                    unit="ns",
                    observation_scope=observation_scope,
                    labels={"profile": profile.value},
                )
            if reanchored:
                self.metrics.inc(
                    "f6.pacing.reanchors",
                    1.0,
                    unit="count",
                    observation_scope=observation_scope,
                    labels={"profile": profile.value},
                )
            if underrun:
                self.metrics.inc(
                    "f6.pacing.underruns",
                    1.0,
                    unit="count",
                    observation_scope=observation_scope,
                    labels={"profile": profile.value},
                )
        except Exception:
            self.telemetry_drop_count += 1

        self._safe_publish(
            event_type="media.frame.submitted",
            generation_ref=generation_ref,
            metadata={
                "profile": profile.value,
                "sequence": sequence,
                "outcome": outcome,
                "observation_scope": observation_scope,
                "reanchored": reanchored,
                "underrun": underrun,
            },
        )

    def record_unsafe_metadata_probe(self, *, generation_ref: GenerationRef, metadata: Mapping[str, Any]) -> None:
        """Explicit safe projection path used to verify PII/waveform sentinels are dropped/redacted."""
        self._safe_publish(
            event_type="pipeline.stage.f6",
            generation_ref=generation_ref,
            metadata=metadata,
        )

    def record_evidence(
        self,
        *,
        kind: EvidenceKind,
        claim: str,
        subject: str,
        observation_scope: str = "SERVER",
        metrics: tuple[MetricSample, ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            self.evidence.record(
                kind=kind,
                claim=claim,
                subject=subject,
                recorded_monotonic_ns=self._clock.monotonic_ns(),
                clock_domain=self._clock.clock_domain,
                observation_scope=observation_scope,
                metrics=metrics,
                details=details,
            )
        except Exception:
            self.telemetry_drop_count += 1
