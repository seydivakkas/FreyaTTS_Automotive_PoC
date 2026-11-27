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

from typing import Sequence

from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    ErrorCategory,
    ErrorInfo,
    EventEnvelope,
    MetricSample,
    Retryability,
)
from backend.core.contracts.recognition import (
    ASROutcome,
    ASRResult,
    ASRStatus,
    ConfidenceEstimate,
    EntityCandidate,
)
from backend.core.runtime.deadlines import Clock
from backend.speech_recognition.errors import ASRInputError, build_safe_error_info


def build_final_asr_result(
    *,
    session_id: str,
    utterance_id: str,
    turn_id: int | None,
    sequence: int,
    clock: Clock,
    outcome: ASROutcome,
    raw_transcript: str = "",
    language: str | None = None,
    entities: Sequence[EntityCandidate] = (),
    confidence: ConfidenceEstimate | None = None,
    error: ErrorInfo | None = None,
    metrics: Sequence[MetricSample] = (),
    trace_id: str | None = None,
    status: ASRStatus = ASRStatus.FINAL,
    revision: int = 0,
    model_revision: str | None = None,
    config_revision: str | None = None,
    lexicon_revision: str | None = None,
    producer: str = "backend.speech_recognition",
) -> ASRResult:
    """
    Assemble an immutable M01 final ASRResult.

    - Rejects any non-FINAL status (PARTIAL / STABLE_PREFIX are not valid F2-A output).
    - Keeps `normalized_transcript`, `canonical_transcript`, and `stable_prefix` as None.
    - Guarantees empty/whitespace-only `raw_transcript` cannot receive `ASROutcome.OK`.
    """
    if status != ASRStatus.FINAL:
        raise ASRInputError(
            "ASR_PARTIAL_NOT_ALLOWED_IN_F2A",
            f"F2-A only produces FINAL ASRResult; rejected status={status.value}",
            field_name="status",
        )

    effective_outcome = outcome
    effective_error = error
    if effective_outcome == ASROutcome.OK and not raw_transcript.strip():
        effective_outcome = ASROutcome.NO_SPEECH
        if effective_error is None:
            effective_error = build_safe_error_info(
                code="ASR_EMPTY_TRANSCRIPT",
                category=ErrorCategory.VALIDATION,
                retryable=Retryability.NO,
                safe_message="Empty or whitespace-only transcript classified as NO_SPEECH",
            )

    safe_meta: dict[str, object] = {
        "utterance_id": utterance_id,
        "outcome": effective_outcome.value,
        "status": ASRStatus.FINAL.value,
    }
    if model_revision:
        safe_meta["model_revision"] = model_revision
    if config_revision:
        safe_meta["config_revision"] = config_revision
    if lexicon_revision:
        safe_meta["lexicon_revision"] = lexicon_revision

    envelope = EventEnvelope(
        schema_version=CONTRACT_SCHEMA_VERSION,
        event_type="asr.final",
        session_id=session_id,
        trace_id=trace_id,
        turn_id=turn_id,
        generation_id=None,
        sequence=sequence,
        monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
        producer=producer,
        metadata=safe_meta,
    )

    requires_confirmation = True if effective_outcome == ASROutcome.OK else None

    return ASRResult(
        envelope=envelope,
        utterance_id=utterance_id,
        revision=revision,
        status=ASRStatus.FINAL,
        raw_transcript=raw_transcript,
        outcome=effective_outcome,
        language=language,
        normalized_transcript=None,
        canonical_transcript=None,
        stable_prefix=None,
        entities=tuple(entities),
        confidence=confidence,
        requires_confirmation=requires_confirmation,
        error=effective_error,
        metrics=tuple(metrics),
    )
