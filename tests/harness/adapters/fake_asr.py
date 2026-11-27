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

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, EventEnvelope, GenerationRef
from backend.core.contracts.recognition import (
    ASROutcome,
    ASRResult,
    ASRStatus,
    CatalogStatus,
    ConfidenceEstimate,
    ConfirmationStatus,
    EntityCandidate,
)
from backend.core.runtime.cancellation import CancellationScope, StaleScopeError
from backend.observability.evidence import EvidenceKind


@dataclass(frozen=True, slots=True)
class MalformedASRResultError(ValueError):
    reason_code: str


class FakeASRAdapter:
    """Mock ASR producing controlled revisions, unknown confidences, and delayed/malformed variants."""

    source_class: EvidenceKind = EvidenceKind.MOCK_RUNTIME

    def __init__(self) -> None:
        self.invocation_count = 0
        self.call_refs: list[dict[str, object]] = []

    def make_result(
        self,
        *,
        session_id: str,
        utterance_id: str,
        revision: int,
        status: ASRStatus,
        raw_transcript: str,
        normalized_transcript: str | None = None,
        canonical_transcript: str | None = None,
        outcome: ASROutcome = ASROutcome.OK,
        confidence: ConfidenceEstimate | None = None,
        entities: tuple[EntityCandidate, ...] = (),
        turn_id: int | None = 1,
        generation_id: int | None = 1,
        monotonic_ns: int = 1_000,
        clock_domain: str = "harness.fake.clock",
        trace_id: str | None = None,
    ) -> ASRResult:
        self.invocation_count += 1
        env = EventEnvelope(
            schema_version=CONTRACT_SCHEMA_VERSION,
            event_type=f"asr.{status.value.lower()}",
            session_id=session_id,
            trace_id=trace_id,
            turn_id=turn_id,
            generation_id=generation_id,
            sequence=revision,
            monotonic_ns=monotonic_ns,
            clock_domain=clock_domain,
            producer="tests.harness.fake_asr",
            metadata={"source_class": self.source_class.value},
        )
        res = ASRResult(
            envelope=env,
            utterance_id=utterance_id,
            revision=revision,
            status=status,
            raw_transcript=raw_transcript,
            outcome=outcome,
            language="tr",
            normalized_transcript=normalized_transcript,
            canonical_transcript=canonical_transcript,
            entities=entities,
            confidence=confidence,
        )
        self.call_refs.append({
            "session_id": session_id,
            "utterance_id": utterance_id,
            "revision": revision,
            "status": status.value,
            "source_class": self.source_class.value,
        })
        return res

    def make_conflicting_candidates(self) -> tuple[EntityCandidate, EntityCandidate]:
        return (
            EntityCandidate(
                entity_id="cand-1",
                entity_type="vehicle_model",
                raw_value="pasat",
                canonical_value="Volkswagen Passat",
                score=0.51,
                catalog_status=CatalogStatus.UNVERIFIED,
                confirmation_status=ConfirmationStatus.CANDIDATE,
            ),
            EntityCandidate(
                entity_id="cand-2",
                entity_type="vehicle_model",
                raw_value="pasat",
                canonical_value="Volkswagen Polo",
                score=0.49,
                catalog_status=CatalogStatus.UNVERIFIED,
                confirmation_status=ConfirmationStatus.CANDIDATE,
            ),
        )

    def deliver_with_fence(
        self,
        result: ASRResult,
        scope: CancellationScope,
        *,
        expected_generation: GenerationRef | None = None,
    ) -> tuple[bool, str]:
        """Deliver ASRResult through an M02 CancellationScope fence; stale scopes reject."""
        try:
            scope.check_active()
        except StaleScopeError:
            return False, "REJECTED_STALE_SCOPE"
        if expected_generation is not None and result.envelope.generation_id != expected_generation.generation_id:
            return False, "REJECTED_STALE_GENERATION"
        return True, "ADMITTED"

    @staticmethod
    def validate_raw_payload(payload: object) -> ASRResult:
        if not isinstance(payload, ASRResult):
            raise MalformedASRResultError("MALFORMED_ASR_PAYLOAD")
        return payload
