"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, EventEnvelope
from backend.core.contracts.recognition import ASROutcome, ASRResult, ASRStatus, ConfidenceEstimate
from backend.core.contracts.validation import ConversionResult


def asr_result_from_legacy_text(
    *,
    session_id: str,
    utterance_id: str,
    raw_text: str,
    sequence: int,
    monotonic_ns: int,
    clock_domain: str = "legacy.local",
    turn_id: int | None = None,
    is_final: bool = True,
    language: str | None = "tr",
    canonical_text: str | None = None,
    avg_logprob: float | None = None,
    no_speech_prob: float | None = None,
    source_ref: str = "backend.models.transcribe",
) -> ConversionResult[ASRResult]:
    missing: list[str] = []
    if turn_id is None:
        missing.append("turn_id")
    if avg_logprob is None:
        missing.append("confidence.avg_logprob")
    status = ASRStatus.FINAL if is_final else ASRStatus.PARTIAL
    outcome = ASROutcome.OK if raw_text.strip() else ASROutcome.NO_SPEECH
    conf = None
    if avg_logprob is not None or no_speech_prob is not None:
        conf = ConfidenceEstimate(avg_logprob=avg_logprob, no_speech_prob=no_speech_prob)
    env = EventEnvelope(
        schema_version=CONTRACT_SCHEMA_VERSION,
        event_type="asr.final" if is_final else "asr.partial",
        session_id=session_id,
        trace_id=None,
        turn_id=turn_id,
        generation_id=None,
        sequence=sequence,
        monotonic_ns=monotonic_ns,
        clock_domain=clock_domain,
        producer=source_ref,
    )
    res = ASRResult(
        envelope=env,
        utterance_id=utterance_id,
        revision=0,
        status=status,
        raw_transcript=raw_text,
        outcome=outcome,
        language=language,
        canonical_transcript=canonical_text,
        confidence=conf,
        requires_confirmation=True if outcome == ASROutcome.OK else None,
    )
    return ConversionResult(res, tuple(missing), lossy=bool(missing), source_ref=source_ref)


def asr_result_to_legacy_text(result: ASRResult) -> str:
    return result.raw_transcript
