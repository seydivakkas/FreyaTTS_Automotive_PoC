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
import hashlib
import threading
import unicodedata

from backend.core.contracts.dialogue import DialogueOutcome, DialogueResponse
from backend.core.contracts.validation import require_safe_id


DEFAULT_MAX_INPUT_CHARS = 4000
_ALLOWED_CONTROL_CHARS = frozenset({"\t", "\n", "\r"})
_UNTRUSTED_PRODUCER_TOKENS = frozenset({"untrusted", "raw_caller", "public_raw", "llm_raw"})


class PlanningOutcome(StrEnum):
    """Local linguistic planning outcome mapped cleanly onto M01/M02 semantics."""

    ADMITTED = "ADMITTED"
    NO_SYNTHESIS = "NO_SYNTHESIS"
    REJECTED = "REJECTED"
    STALE = "STALE"
    CONFLICT = "CONFLICT"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class AdmittedResponse:
    """Validated immutable input envelope and source speech text admitted for F4-A planning."""

    response: DialogueResponse
    session_id: str
    turn_id: int
    response_id: str
    state_revision: int
    speech_text: str
    speech_act: str
    outcome: DialogueOutcome
    content_digest: str
    incarnation_id: str = "default"


@dataclass(frozen=True, slots=True)
class InputValidationResult:
    """Result of validating an incoming response prior to normalization."""

    outcome: PlanningOutcome
    admitted: AdmittedResponse | None = None
    reason_code: str = "OK"
    safe_message: str = ""
    duplicate_of_plan_id: str | None = None


@dataclass(frozen=True, slots=True)
class _DedupEntry:
    content_digest: str
    plan_id: str
    plan_revision: int


class ResponseDedupLedger:
    """Thread-safe deduplication ledger scoped by (session_id, incarnation_id, turn_id, response_id)."""

    def __init__(self, *, max_entries: int = 2048) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str, int, str], _DedupEntry] = {}

    def check(
        self,
        *,
        session_id: str,
        incarnation_id: str,
        turn_id: int,
        response_id: str,
        content_digest: str,
    ) -> tuple[str, _DedupEntry | None]:
        key = (session_id, incarnation_id, turn_id, response_id)
        with self._lock:
            existing = self._entries.get(key)
            if existing is None:
                return "NEW", None
            if existing.content_digest == content_digest:
                return "DUPLICATE_IDENTICAL", existing
            return "CONFLICT", existing

    def record(
        self,
        *,
        session_id: str,
        incarnation_id: str,
        turn_id: int,
        response_id: str,
        content_digest: str,
        plan_id: str,
        plan_revision: int,
    ) -> None:
        key = (session_id, incarnation_id, turn_id, response_id)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None and existing.content_digest != content_digest:
                raise ValueError("Cannot overwrite response identity with conflicting content")
            if len(self._entries) >= self._max_entries and key not in self._entries:
                oldest_key = next(iter(self._entries))
                self._entries.pop(oldest_key, None)
            self._entries[key] = _DedupEntry(
                content_digest=content_digest,
                plan_id=plan_id,
                plan_revision=plan_revision,
            )

    def clear_session(self, session_id: str) -> int:
        with self._lock:
            to_del = [k for k in self._entries if k[0] == session_id]
            for k in to_del:
                del self._entries[k]
            return len(to_del)


def compute_response_content_digest(response: DialogueResponse) -> str:
    """Compute a deterministic digest of spoken content and verified fact references."""
    facts = "|".join(
        f"{f.provenance}:{f.reference_id}:{f.status}:{f.revision}"
        for f in response.verified_fact_refs
    )
    payload = "\x1f".join(
        (
            response.outcome.value,
            response.speech_act,
            response.speech_text,
            str(response.state_revision),
            facts,
        )
    )
    return hashlib.sha256(payload.encode("utf-8", errors="strict")).hexdigest()


def _validate_unicode_text(text: str) -> tuple[bool, str]:
    """Verify text has valid Unicode codepoints without surrogates or forbidden controls."""
    for ch in text:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            return False, "INVALID_UNICODE_SURROGATE"
        if ch == "\x00":
            return False, "INVALID_CONTROL_CHAR"
        cat = unicodedata.category(ch)
        if cat == "Cc" and ch not in _ALLOWED_CONTROL_CHARS:
            return False, "INVALID_CONTROL_CHAR"
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False, "INVALID_UNICODE_ENCODING"
    return True, "OK"


def validate_dialogue_response(
    response: object,
    *,
    expected_session_id: str | None = None,
    expected_turn_id: int | None = None,
    min_state_revision: int | None = None,
    expected_asr_revision: int | None = None,
    incarnation_id: str = "default",
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
    dedup_ledger: ResponseDedupLedger | None = None,
    allow_safe_reprompt_outcomes: bool = True,
) -> InputValidationResult:
    """
    Validate an incoming M01 DialogueResponse before F4-A linguistic processing.

    Untrusted raw dicts/strings are always rejected. NO_RESPONSE never produces speech.
    """
    if not isinstance(response, DialogueResponse):
        return InputValidationResult(
            outcome=PlanningOutcome.REJECTED,
            reason_code="UNTRUSTED_RESPONSE_TYPE",
            safe_message="DialogueResponse contract required",
        )

    env = response.envelope
    producer_low = env.producer.strip().lower()
    if any(tok in producer_low for tok in _UNTRUSTED_PRODUCER_TOKENS):
        return InputValidationResult(
            outcome=PlanningOutcome.REJECTED,
            reason_code="UNTRUSTED_PRODUCER",
            safe_message="Untrusted response producer",
        )

    if env.turn_id is None:
        return InputValidationResult(
            outcome=PlanningOutcome.REJECTED,
            reason_code="MISSING_TURN_ID",
            safe_message="DialogueResponse envelope must carry turn_id",
        )

    if expected_session_id is not None and env.session_id != expected_session_id:
        return InputValidationResult(
            outcome=PlanningOutcome.STALE,
            reason_code="WRONG_SESSION",
            safe_message="Response belongs to a different session",
        )

    if expected_turn_id is not None and env.turn_id != expected_turn_id:
        return InputValidationResult(
            outcome=PlanningOutcome.STALE,
            reason_code="STALE_TURN",
            safe_message="Response turn_id does not match active turn",
        )

    if min_state_revision is not None and response.state_revision < min_state_revision:
        return InputValidationResult(
            outcome=PlanningOutcome.STALE,
            reason_code="STALE_STATE_REVISION",
            safe_message="Response state_revision is stale",
        )

    if (
        expected_asr_revision is not None
        and response.source_asr_revision is not None
        and response.source_asr_revision != expected_asr_revision
    ):
        return InputValidationResult(
            outcome=PlanningOutcome.STALE,
            reason_code="STALE_ASR_REVISION",
            safe_message="Response source_asr_revision is stale",
        )

    require_safe_id(incarnation_id, "incarnation_id")

    if response.outcome == DialogueOutcome.NO_RESPONSE:
        return InputValidationResult(
            outcome=PlanningOutcome.NO_SYNTHESIS,
            reason_code="NO_RESPONSE",
            safe_message="DialogueOutcome.NO_RESPONSE produces no speech",
        )

    if response.outcome in {DialogueOutcome.ERROR, DialogueOutcome.BLOCKED}:
        if not allow_safe_reprompt_outcomes or not response.speech_text.strip():
            return InputValidationResult(
                outcome=PlanningOutcome.NO_SYNTHESIS,
                reason_code=f"NON_SPEAKABLE_{response.outcome.value}",
                safe_message="Non-OK outcome without safe spoken message",
            )

    if response.outcome in {
        DialogueOutcome.CLARIFICATION_REQUIRED,
        DialogueOutcome.IDENTITY_REQUIRED,
    } and not response.speech_text.strip():
        return InputValidationResult(
            outcome=PlanningOutcome.NO_SYNTHESIS,
            reason_code=f"EMPTY_{response.outcome.value}",
            safe_message="Reprompt outcome has empty speech_text",
        )

    if not response.speech_text or not response.speech_text.strip():
        return InputValidationResult(
            outcome=PlanningOutcome.REJECTED,
            reason_code="EMPTY_SPEECH_TEXT",
            safe_message="speech_text must be non-empty for synthesis",
        )

    if len(response.speech_text) > max_input_chars:
        return InputValidationResult(
            outcome=PlanningOutcome.REJECTED,
            reason_code="LIMIT_EXCEEDED",
            safe_message="speech_text exceeds max_input_chars",
        )

    unicode_ok, unicode_err = _validate_unicode_text(response.speech_text)
    if not unicode_ok:
        return InputValidationResult(
            outcome=PlanningOutcome.REJECTED,
            reason_code=unicode_err,
            safe_message="speech_text failed strict Unicode validation",
        )

    digest = compute_response_content_digest(response)

    if dedup_ledger is not None:
        status, existing = dedup_ledger.check(
            session_id=env.session_id,
            incarnation_id=incarnation_id,
            turn_id=env.turn_id,
            response_id=response.response_id,
            content_digest=digest,
        )
        if status == "DUPLICATE_IDENTICAL" and existing is not None:
            return InputValidationResult(
                outcome=PlanningOutcome.NO_SYNTHESIS,
                reason_code="DUPLICATE_RESPONSE",
                safe_message="Duplicate response identity with identical content",
                duplicate_of_plan_id=existing.plan_id,
            )
        if status == "CONFLICT":
            return InputValidationResult(
                outcome=PlanningOutcome.CONFLICT,
                reason_code="DUPLICATE_RESPONSE_CONFLICT",
                safe_message="Duplicate response identity with changed contents",
            )

    admitted = AdmittedResponse(
        response=response,
        session_id=env.session_id,
        turn_id=env.turn_id,
        response_id=response.response_id,
        state_revision=response.state_revision,
        speech_text=response.speech_text,
        speech_act=response.speech_act,
        outcome=response.outcome,
        content_digest=digest,
        incarnation_id=incarnation_id,
    )
    return InputValidationResult(
        outcome=PlanningOutcome.ADMITTED,
        admitted=admitted,
        reason_code="ADMITTED",
    )
