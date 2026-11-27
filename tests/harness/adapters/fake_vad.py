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
from typing import Iterable

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, EventEnvelope, GenerationRef, StreamDirection, StreamRef
from backend.core.contracts.speech import SpeechEvent, SpeechEventKind
from backend.observability.evidence import EvidenceKind


@dataclass(frozen=True, slots=True)
class ScriptedVADStep:
    kind: SpeechEventKind
    sample_offset: int
    reason: str
    vad_score: float | None = None


class FakeVADAdapter:
    """Mock VAD returning scripted SpeechEvents with exact sample offsets (no acoustic VAD)."""

    source_class: EvidenceKind = EvidenceKind.MOCK_RUNTIME
    measures_acoustic_vad: bool = False

    def __init__(self, steps: Iterable[ScriptedVADStep] = ()) -> None:
        self._steps = list(steps)
        self.invocation_count = 0
        self.call_refs: list[dict[str, object]] = []

    def emit_all(
        self,
        *,
        session_id: str,
        stream_id: str = "in-audio",
        trace_id: str | None = None,
        clock_domain: str = "harness.fake.clock",
        base_monotonic_ns: int = 1_000,
        target_generation: GenerationRef | None = None,
    ) -> list[SpeechEvent]:
        self.invocation_count += 1
        stream_ref = StreamRef(session_id=session_id, stream_id=stream_id, direction=StreamDirection.INPUT, format_epoch=0)
        events: list[SpeechEvent] = []
        for idx, step in enumerate(self._steps):
            env = EventEnvelope(
                schema_version=CONTRACT_SCHEMA_VERSION,
                event_type=f"vad.{step.kind.value.lower()}",
                session_id=session_id,
                trace_id=trace_id,
                turn_id=target_generation.turn_id if target_generation else None,
                generation_id=target_generation.generation_id if target_generation else None,
                sequence=idx,
                monotonic_ns=base_monotonic_ns + idx * 1000,
                clock_domain=clock_domain,
                producer="tests.harness.fake_vad",
                metadata={"source_class": self.source_class.value},
            )
            events.append(
                SpeechEvent(
                    envelope=env,
                    kind=step.kind,
                    stream_ref=stream_ref,
                    sample_offset=step.sample_offset,
                    reason=step.reason,
                    vad_score=step.vad_score,
                    target_generation=target_generation,
                )
            )
        self.call_refs.append({"session_id": session_id, "step_count": len(events), "source_class": self.source_class.value})
        return events
