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

import hashlib
import threading
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.core.contracts.recognition import ASROutcome, ASRResult, ASRStatus
from backend.core.contracts.validation import freeze_value, require_safe_id, require_strict_int
from backend.core.runtime.cancellation import CancellationScope
from backend.security.contracts import canonical_json_bytes

_UNTRUSTED_PRODUCERS: frozenset[str] = frozenset({
    "",
    "untrusted",
    "client_untrusted",
    "raw_json",
    "llm",
    "synthetic_untrusted",
})

_VALID_DTMF_DIGITS: frozenset[str] = frozenset({
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "#", "A", "B", "C", "D",
})


class DialogueChannel(StrEnum):
    """Supported ingress channels; non-ASR channels never fabricate ASRResult."""

    VOICE_ASR = "VOICE_ASR"
    DTMF = "DTMF"
    UI_AUTHENTICATED = "UI_AUTHENTICATED"
    OUTBOUND_COMMAND = "OUTBOUND_COMMAND"
    OPERATOR_COMMAND = "OPERATOR_COMMAND"


class AdmissionDisposition(StrEnum):
    """Deterministic admission outcome for dialogue ingress."""

    ADMITTED = "ADMITTED"
    REJECTED_NON_FINAL = "REJECTED_NON_FINAL"
    REJECTED_NON_OK = "REJECTED_NON_OK"
    REJECTED_UNTRUSTED_CLAIM = "REJECTED_UNTRUSTED_CLAIM"
    REJECTED_STALE_SESSION = "REJECTED_STALE_SESSION"
    REJECTED_STALE_TURN = "REJECTED_STALE_TURN"
    REJECTED_CANCELED = "REJECTED_CANCELED"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_CONFLICT = "REJECTED_CONFLICT"
    REJECTED_INVALID = "REJECTED_INVALID"


@dataclass(frozen=True, slots=True)
class DialogueInputRef:
    """Immutable reference to an admitted dialogue input; repr hides raw payload."""

    claim_id: str
    channel: DialogueChannel
    session_id: str
    incarnation_id: str
    turn_id: int
    trace_id: str | None
    utterance_id: str | None
    source_revision: int
    content_digest: str
    dtmf_digit: str | None = None
    ui_action: str | None = None
    trusted_channel_proof: bool = False

    def __post_init__(self) -> None:
        require_safe_id(self.claim_id, "claim_id")
        if not isinstance(self.channel, DialogueChannel):
            raise ValueError("channel must be DialogueChannel")
        require_safe_id(self.session_id, "session_id")
        require_safe_id(self.incarnation_id, "incarnation_id")
        require_strict_int(self.turn_id, "turn_id", minimum=0)
        if self.trace_id is not None:
            require_safe_id(self.trace_id, "trace_id")
        if self.utterance_id is not None:
            require_safe_id(self.utterance_id, "utterance_id")
        require_strict_int(self.source_revision, "source_revision", minimum=0)
        if not isinstance(self.content_digest, str) or len(self.content_digest) != 64:
            raise ValueError("content_digest must be 64-char SHA-256 hex")

    def __repr__(self) -> str:
        return (
            f"DialogueInputRef(claim_id={self.claim_id!r}, channel={self.channel.value}, "
            f"session_id={self.session_id!r}, turn_id={self.turn_id}, rev={self.source_revision})"
        )


@dataclass(frozen=True, slots=True)
class InputAdmissionResult:
    """Result of admitting an ASRResult or trusted non-ASR channel event."""

    admitted: bool
    disposition: AdmissionDisposition
    reason_code: str
    input_ref: DialogueInputRef | None = None
    asr_result: ASRResult | None = None
    channel_payload: Mapping[str, Any] | None = None
    error: ErrorInfo | None = None


def _reject(
    disposition: AdmissionDisposition,
    reason_code: str,
    safe_message: str,
    *,
    category: ErrorCategory = ErrorCategory.VALIDATION,
    retryable: Retryability = Retryability.NO,
    asr_result: ASRResult | None = None,
) -> InputAdmissionResult:
    return InputAdmissionResult(
        admitted=False,
        disposition=disposition,
        reason_code=reason_code,
        asr_result=asr_result,
        error=ErrorInfo(
            code=reason_code,
            category=category,
            retryable=retryable,
            safe_message=safe_message,
        ),
    )


class InputAdmissionGate:
    """
    Single atomic admission fence for F2-A ASRResult and trusted non-ASR channels.

    Enforces final-only ASR admission, active session/incarnation/turn/cancellation
    scope, provenance verification, and at-most-once claim/conflict detection.
    """

    def __init__(self, *, max_claim_history: int = 2048) -> None:
        require_strict_int(max_claim_history, "max_claim_history", minimum=16)
        self._max_claim_history = max_claim_history
        self._lock = threading.RLock()
        self._claims: dict[tuple[str, str, int, str, str], tuple[int, str]] = {}
        self._claim_order: list[tuple[str, str, int, str, str]] = []
        self._seq = 0

    def _next_claim_id(self) -> str:
        self._seq += 1
        return f"inclaim-{self._seq:08d}"

    def _record_claim(
        self,
        key: tuple[str, str, int, str, str],
        revision: int,
        digest: str,
    ) -> tuple[bool, AdmissionDisposition, str]:
        with self._lock:
            existing = self._claims.get(key)
            if existing is not None:
                prev_rev, prev_digest = existing
                if prev_rev == revision and prev_digest == digest:
                    return False, AdmissionDisposition.REJECTED_DUPLICATE, "input.duplicate"
                return False, AdmissionDisposition.REJECTED_CONFLICT, "input.conflict_altered_content"
            if len(self._claim_order) >= self._max_claim_history:
                evicted = self._claim_order.pop(0)
                self._claims.pop(evicted, None)
            self._claims[key] = (revision, digest)
            self._claim_order.append(key)
            return True, AdmissionDisposition.ADMITTED, "input.admitted"

    @staticmethod
    def _validate_scope(
        *,
        payload_session_id: str,
        payload_turn_id: int | None,
        expected_session_id: str,
        expected_turn_id: int,
        cancellation_scope: CancellationScope | None,
    ) -> InputAdmissionResult | None:
        if payload_session_id != expected_session_id:
            return _reject(
                AdmissionDisposition.REJECTED_STALE_SESSION,
                "input.wrong_session",
                "Input belongs to a different session",
                category=ErrorCategory.STALE_SCOPE,
            )
        if cancellation_scope is not None and cancellation_scope.is_cancel_requested:
            return _reject(
                AdmissionDisposition.REJECTED_CANCELED,
                "input.scope_canceled",
                "Input arrived after scope cancellation",
                category=ErrorCategory.STALE_SCOPE,
            )
        if payload_turn_id is None or payload_turn_id != expected_turn_id:
            return _reject(
                AdmissionDisposition.REJECTED_STALE_TURN,
                "input.stale_turn",
                "Input turn does not match active turn",
                category=ErrorCategory.STALE_SCOPE,
            )
        return None

    def admit_asr(
        self,
        payload: object,
        *,
        expected_session_id: str,
        incarnation_id: str,
        expected_turn_id: int,
        cancellation_scope: CancellationScope | None = None,
        allowed_producers: frozenset[str] | None = None,
    ) -> InputAdmissionResult:
        """Validate and atomically claim an M01 FINAL/OK ASRResult."""
        if not isinstance(payload, ASRResult):
            # Raw dicts / JSON claiming admitted=True or confirmed=True are untrusted.
            if isinstance(payload, Mapping):
                return _reject(
                    AdmissionDisposition.REJECTED_UNTRUSTED_CLAIM,
                    "input.untrusted_json_claim",
                    "Untrusted raw JSON input rejected without M01 ASRResult provenance",
                    category=ErrorCategory.SECURITY,
                )
            return _reject(
                AdmissionDisposition.REJECTED_INVALID,
                "input.invalid_asr_type",
                "Payload must be M01 ASRResult",
            )

        producer = (payload.envelope.producer or "").strip()
        if producer.lower() in _UNTRUSTED_PRODUCERS:
            return _reject(
                AdmissionDisposition.REJECTED_UNTRUSTED_CLAIM,
                "input.untrusted_producer",
                "ASRResult producer lacks trusted provenance",
                category=ErrorCategory.SECURITY,
            )
        if allowed_producers is not None and producer not in allowed_producers:
            return _reject(
                AdmissionDisposition.REJECTED_UNTRUSTED_CLAIM,
                "input.producer_not_allowlisted",
                "ASRResult producer is not in active allowlist",
                category=ErrorCategory.SECURITY,
            )

        if bool(payload.envelope.metadata.get("untrusted_claim")):
            return _reject(
                AdmissionDisposition.REJECTED_UNTRUSTED_CLAIM,
                "input.untrusted_metadata_claim",
                "ASRResult carries untrusted metadata claim",
                category=ErrorCategory.SECURITY,
            )

        scope_err = self._validate_scope(
            payload_session_id=payload.envelope.session_id,
            payload_turn_id=payload.envelope.turn_id,
            expected_session_id=expected_session_id,
            expected_turn_id=expected_turn_id,
            cancellation_scope=cancellation_scope,
        )
        if scope_err is not None:
            return scope_err

        if payload.status != ASRStatus.FINAL:
            return _reject(
                AdmissionDisposition.REJECTED_NON_FINAL,
                f"asr.non_final.{payload.status.value.lower()}",
                "Non-final ASR transcript cannot dispatch dialogue effects",
                asr_result=payload,
            )

        if payload.outcome != ASROutcome.OK:
            return _reject(
                AdmissionDisposition.REJECTED_NON_OK,
                f"asr.non_ok.{payload.outcome.value.lower()}",
                f"ASR outcome {payload.outcome.value} routed to safe non-OK lifecycle path",
                asr_result=payload,
            )

        if not payload.raw_transcript.strip():
            return _reject(
                AdmissionDisposition.REJECTED_NON_OK,
                "asr.empty_transcript",
                "Blank FINAL ASR transcript cannot drive dialogue effects",
                asr_result=payload,
            )

        digest = hashlib.sha256(
            canonical_json_bytes({
                "raw_transcript": payload.raw_transcript,
                "status": payload.status.value,
                "outcome": payload.outcome.value,
                "revision": payload.revision,
            })
        ).hexdigest()

        claim_key = (
            expected_session_id,
            incarnation_id,
            expected_turn_id,
            DialogueChannel.VOICE_ASR.value,
            payload.utterance_id,
        )
        ok, disp, reason = self._record_claim(claim_key, payload.revision, digest)
        if not ok:
            cat = ErrorCategory.STALE_SCOPE if disp == AdmissionDisposition.REJECTED_DUPLICATE else ErrorCategory.VALIDATION
            return _reject(
                disp,
                reason,
                "Duplicate or conflicting FINAL ASRResult for same utterance identity",
                category=cat,
                asr_result=payload,
            )

        claim_id = self._next_claim_id()
        ref = DialogueInputRef(
            claim_id=claim_id,
            channel=DialogueChannel.VOICE_ASR,
            session_id=expected_session_id,
            incarnation_id=incarnation_id,
            turn_id=expected_turn_id,
            trace_id=payload.envelope.trace_id,
            utterance_id=payload.utterance_id,
            source_revision=payload.revision,
            content_digest=digest,
            trusted_channel_proof=False,
        )
        return InputAdmissionResult(
            admitted=True,
            disposition=AdmissionDisposition.ADMITTED,
            reason_code="asr.final_admitted",
            input_ref=ref,
            asr_result=payload,
        )

    def admit_dtmf(
        self,
        *,
        digit: str,
        event_id: str,
        session_id: str,
        incarnation_id: str,
        turn_id: int,
        trace_id: str | None = None,
        sequence: int = 0,
        cancellation_scope: CancellationScope | None = None,
    ) -> InputAdmissionResult:
        """Admit a trusted DTMF event on its own channel contract (never fabricates ASRResult)."""
        require_safe_id(event_id, "event_id")
        require_safe_id(session_id, "session_id")
        require_safe_id(incarnation_id, "incarnation_id")
        require_strict_int(turn_id, "turn_id", minimum=0)
        require_strict_int(sequence, "sequence", minimum=0)

        if cancellation_scope is not None and cancellation_scope.is_cancel_requested:
            return _reject(
                AdmissionDisposition.REJECTED_CANCELED,
                "dtmf.scope_canceled",
                "DTMF arrived after scope cancellation",
                category=ErrorCategory.STALE_SCOPE,
            )

        clean_digit = (digit or "").strip().upper()
        if clean_digit not in _VALID_DTMF_DIGITS:
            return _reject(
                AdmissionDisposition.REJECTED_INVALID,
                "dtmf.invalid_digit",
                "Invalid DTMF digit",
            )

        digest = hashlib.sha256(
            canonical_json_bytes({"digit": clean_digit, "event_id": event_id, "sequence": sequence})
        ).hexdigest()
        claim_key = (session_id, incarnation_id, turn_id, DialogueChannel.DTMF.value, event_id)
        ok, disp, reason = self._record_claim(claim_key, sequence, digest)
        if not ok:
            return _reject(
                disp,
                reason,
                "Duplicate or conflicting DTMF event",
                category=ErrorCategory.STALE_SCOPE,
            )

        ref = DialogueInputRef(
            claim_id=self._next_claim_id(),
            channel=DialogueChannel.DTMF,
            session_id=session_id,
            incarnation_id=incarnation_id,
            turn_id=turn_id,
            trace_id=trace_id,
            utterance_id=None,
            source_revision=sequence,
            content_digest=digest,
            dtmf_digit=clean_digit,
            trusted_channel_proof=True,
        )
        return InputAdmissionResult(
            admitted=True,
            disposition=AdmissionDisposition.ADMITTED,
            reason_code="dtmf.admitted",
            input_ref=ref,
            channel_payload=MappingProxyType({"digit": clean_digit, "event_id": event_id}),
        )

    def admit_ui_action(
        self,
        *,
        action: str,
        event_id: str,
        session_id: str,
        incarnation_id: str,
        turn_id: int,
        payload: Mapping[str, Any] | None = None,
        trusted_channel_proof: bool = False,
        trace_id: str | None = None,
        sequence: int = 0,
        cancellation_scope: CancellationScope | None = None,
    ) -> InputAdmissionResult:
        """Admit an authenticated UI/operator command on its own channel contract."""
        require_safe_id(event_id, "event_id")
        require_safe_id(session_id, "session_id")
        require_safe_id(incarnation_id, "incarnation_id")
        require_strict_int(turn_id, "turn_id", minimum=0)
        require_strict_int(sequence, "sequence", minimum=0)

        if not trusted_channel_proof:
            return _reject(
                AdmissionDisposition.REJECTED_UNTRUSTED_CLAIM,
                "ui.untrusted_channel",
                "UI action requires authenticated channel proof",
                category=ErrorCategory.SECURITY,
            )
        if cancellation_scope is not None and cancellation_scope.is_cancel_requested:
            return _reject(
                AdmissionDisposition.REJECTED_CANCELED,
                "ui.scope_canceled",
                "UI action arrived after scope cancellation",
                category=ErrorCategory.STALE_SCOPE,
            )
        clean_action = (action or "").strip()
        if not clean_action:
            return _reject(
                AdmissionDisposition.REJECTED_INVALID,
                "ui.empty_action",
                "UI action cannot be empty",
            )

        body = dict(payload or {})
        digest = hashlib.sha256(
            canonical_json_bytes({"action": clean_action, "event_id": event_id, "payload": body})
        ).hexdigest()
        claim_key = (session_id, incarnation_id, turn_id, DialogueChannel.UI_AUTHENTICATED.value, event_id)
        ok, disp, reason = self._record_claim(claim_key, sequence, digest)
        if not ok:
            return _reject(
                disp,
                reason,
                "Duplicate or conflicting UI event",
                category=ErrorCategory.STALE_SCOPE,
            )

        ref = DialogueInputRef(
            claim_id=self._next_claim_id(),
            channel=DialogueChannel.UI_AUTHENTICATED,
            session_id=session_id,
            incarnation_id=incarnation_id,
            turn_id=turn_id,
            trace_id=trace_id,
            utterance_id=None,
            source_revision=sequence,
            content_digest=digest,
            ui_action=clean_action,
            trusted_channel_proof=True,
        )
        return InputAdmissionResult(
            admitted=True,
            disposition=AdmissionDisposition.ADMITTED,
            reason_code="ui.admitted",
            input_ref=ref,
            channel_payload=freeze_value({"action": clean_action, "event_id": event_id, **body}),
        )
