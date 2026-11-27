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
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from backend.core.contracts.dialogue import VerifiedFactRef
from backend.core.contracts.validation import freeze_value, require_safe_id, require_strict_int
from backend.supervisor.slot_manager import SlotDelta, SlotManager, SlotMutationOutcome, SlotValue

MAX_HISTORY_TURNS = 12
MAX_TURN_CHARS = 4096
MAX_TOTAL_TEXT_BYTES = 32 * 1024  # 32 KiB
MAX_SLOTS = 32


class ContextCapacityError(RuntimeError):
    """Raised when required dialogue state cannot fit within configured bounds."""


class ContextClosedError(RuntimeError):
    """Raised when attempting to mutate a closed session context."""


@dataclass(frozen=True, slots=True)
class HistoryTurn:
    """Bounded immutable history entry; repr hides text content."""

    turn_id: int
    role: str
    bounded_text: str
    byte_len: int
    text_digest: str
    monotonic_ns: int
    truncated: bool = False

    def __repr__(self) -> str:
        return (
            f"HistoryTurn(turn_id={self.turn_id}, role={self.role!r}, "
            f"bytes={self.byte_len}, truncated={self.truncated})"
        )


@dataclass(frozen=True, slots=True)
class ProtectedRefs:
    """Protected approval/operation references never silently dropped on history truncation."""

    pending_challenge_id: str | None = None
    pending_operation_id: str | None = None
    pending_idempotency_key: str | None = None
    active_booking_ref: str | None = None
    availability_valid: bool = False


@dataclass(frozen=True, slots=True)
class DialogueContextSnapshot:
    """Deeply immutable snapshot of a session's ephemeral dialogue context."""

    session_id: str
    incarnation_id: str
    state_revision: int
    active_workflow: str | None
    workflow_stage: str
    principal_ref: str
    subject_ref: str | None
    slots: Mapping[str, SlotValue]
    protected_refs: ProtectedRefs
    verified_fact_refs: tuple[VerifiedFactRef, ...]
    tool_receipt_refs: tuple[str, ...]
    config_revision: str | None
    model_revision: str | None
    lexicon_revision: str | None
    history: tuple[HistoryTurn, ...]
    history_truncated: bool
    total_text_bytes: int
    closed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "slots", MappingProxyType(dict(self.slots)))
        object.__setattr__(self, "verified_fact_refs", freeze_value(tuple(self.verified_fact_refs)))
        object.__setattr__(self, "tool_receipt_refs", freeze_value(tuple(self.tool_receipt_refs)))
        object.__setattr__(self, "history", tuple(self.history))

    def __repr__(self) -> str:
        return (
            f"DialogueContextSnapshot(session={self.session_id!r}, inc={self.incarnation_id!r}, "
            f"rev={self.state_revision}, stage={self.workflow_stage!r}, "
            f"slots={len(self.slots)}, turns={len(self.history)}, closed={self.closed})"
        )


@dataclass(slots=True)
class _SessionState:
    session_id: str
    incarnation_id: str
    state_revision: int = 0
    active_workflow: str | None = None
    workflow_stage: str = "WAITING_INPUT"
    principal_ref: str = "anonymous"
    subject_ref: str | None = None
    slots: dict[str, SlotValue] = field(default_factory=dict)
    protected_refs: ProtectedRefs = field(default_factory=ProtectedRefs)
    verified_fact_refs: list[VerifiedFactRef] = field(default_factory=list)
    tool_receipt_refs: list[str] = field(default_factory=list)
    config_revision: str | None = None
    model_revision: str | None = None
    lexicon_revision: str | None = None
    history: list[HistoryTurn] = field(default_factory=list)
    history_truncated: bool = False
    total_text_bytes: int = 0
    last_reply: str = ""
    closed: bool = False


@dataclass(frozen=True, slots=True)
class CleanupReport:
    """Idempotent context teardown result."""

    already_closed: bool
    revoked_challenge_id: str | None
    preserved_operation_id: str | None
    cleared_turns: int
    cleared_slots: int


class ContextManager:
    """
    Single authoritative owner of per-(session_id, incarnation_id) ephemeral dialogue state.

    All mutations are serialized under a fast non-blocking per-session lock (no await,
    DB, LLM, or network calls inside the lock) and guarded by expected state_revision CAS.
    """

    def __init__(
        self,
        *,
        max_history_turns: int = MAX_HISTORY_TURNS,
        max_turn_chars: int = MAX_TURN_CHARS,
        max_total_text_bytes: int = MAX_TOTAL_TEXT_BYTES,
        max_slots: int = MAX_SLOTS,
        slot_manager: SlotManager | None = None,
    ) -> None:
        require_strict_int(max_history_turns, "max_history_turns", minimum=1)
        require_strict_int(max_turn_chars, "max_turn_chars", minimum=64)
        require_strict_int(max_total_text_bytes, "max_total_text_bytes", minimum=256)
        require_strict_int(max_slots, "max_slots", minimum=1)
        self.max_history_turns = max_history_turns
        self.max_turn_chars = max_turn_chars
        self.max_total_text_bytes = max_total_text_bytes
        self.max_slots = max_slots
        self._slot_manager = slot_manager or SlotManager()
        self._registry_lock = threading.RLock()
        self._sessions: dict[tuple[str, str], _SessionState] = {}
        self._session_locks: dict[tuple[str, str], threading.RLock] = {}

    def _get_or_create_lock(self, key: tuple[str, str]) -> threading.RLock:
        with self._registry_lock:
            lock = self._session_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._session_locks[key] = lock
            return lock

    def open_session(
        self,
        *,
        session_id: str,
        incarnation_id: str,
        principal_ref: str = "anonymous",
        subject_ref: str | None = None,
        config_revision: str | None = None,
        model_revision: str | None = None,
        lexicon_revision: str | None = None,
    ) -> DialogueContextSnapshot:
        """Initialize an isolated context scoped strictly to (session_id, incarnation_id)."""
        require_safe_id(session_id, "session_id")
        require_safe_id(incarnation_id, "incarnation_id")
        require_safe_id(principal_ref, "principal_ref")
        if subject_ref is not None:
            require_safe_id(subject_ref, "subject_ref")
        key = (session_id, incarnation_id)
        lock = self._get_or_create_lock(key)
        with lock:
            if key not in self._sessions:
                self._sessions[key] = _SessionState(
                    session_id=session_id,
                    incarnation_id=incarnation_id,
                    principal_ref=principal_ref,
                    subject_ref=subject_ref,
                    config_revision=config_revision,
                    model_revision=model_revision,
                    lexicon_revision=lexicon_revision,
                )
            return self._build_snapshot(self._sessions[key])

    def get_snapshot(self, session_id: str, incarnation_id: str) -> DialogueContextSnapshot | None:
        key = (session_id, incarnation_id)
        lock = self._get_or_create_lock(key)
        with lock:
            st = self._sessions.get(key)
            if st is None:
                return None
            return self._build_snapshot(st)

    @staticmethod
    def _build_snapshot(st: _SessionState) -> DialogueContextSnapshot:
        return DialogueContextSnapshot(
            session_id=st.session_id,
            incarnation_id=st.incarnation_id,
            state_revision=st.state_revision,
            active_workflow=st.active_workflow,
            workflow_stage=st.workflow_stage,
            principal_ref=st.principal_ref,
            subject_ref=st.subject_ref,
            slots=st.slots,
            protected_refs=st.protected_refs,
            verified_fact_refs=tuple(st.verified_fact_refs),
            tool_receipt_refs=tuple(st.tool_receipt_refs),
            config_revision=st.config_revision,
            model_revision=st.model_revision,
            lexicon_revision=st.lexicon_revision,
            history=tuple(st.history),
            history_truncated=st.history_truncated,
            total_text_bytes=st.total_text_bytes,
            closed=st.closed,
        )

    def _require_open_state(self, session_id: str, incarnation_id: str) -> tuple[threading.RLock, _SessionState]:
        key = (session_id, incarnation_id)
        lock = self._get_or_create_lock(key)
        with lock:
            st = self._sessions.get(key)
            if st is None:
                raise KeyError(f"Unknown dialogue session context: {key}")
            if st.closed:
                raise ContextClosedError(f"Dialogue session context already closed: {key}")
            return lock, st

    def append_turn(
        self,
        *,
        session_id: str,
        incarnation_id: str,
        turn_id: int,
        role: str,
        text: str,
        monotonic_ns: int,
        expected_state_revision: int | None = None,
    ) -> DialogueContextSnapshot:
        """Append a conversational turn enforcing per-turn char cap and 32 KiB total byte cap."""
        require_strict_int(turn_id, "turn_id", minimum=0)
        require_strict_int(monotonic_ns, "monotonic_ns", minimum=0)
        key = (session_id, incarnation_id)
        lock = self._get_or_create_lock(key)
        with lock:
            st = self._sessions.get(key)
            if st is None:
                raise KeyError(f"Unknown dialogue session context: {key}")
            if st.closed:
                raise ContextClosedError(f"Dialogue session context already closed: {key}")
            if expected_state_revision is not None and st.state_revision != expected_state_revision:
                raise ValueError("CAS revision mismatch on append_turn")

            truncated = False
            bounded = text
            if len(bounded) > self.max_turn_chars:
                bounded = bounded[: self.max_turn_chars]
                truncated = True
                st.history_truncated = True

            byte_len = len(bounded.encode("utf-8"))
            if byte_len > self.max_total_text_bytes:
                # Trim UTF-8 safely without splitting multi-byte chars and mark truncation.
                raw_bytes = bounded.encode("utf-8")[: self.max_total_text_bytes]
                bounded = raw_bytes.decode("utf-8", errors="ignore")
                byte_len = len(bounded.encode("utf-8"))
                truncated = True
                st.history_truncated = True

            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            entry = HistoryTurn(
                turn_id=turn_id,
                role=role,
                bounded_text=bounded,
                byte_len=byte_len,
                text_digest=digest,
                monotonic_ns=monotonic_ns,
                truncated=truncated,
            )
            st.history.append(entry)
            st.total_text_bytes += byte_len

            while len(st.history) > self.max_history_turns or st.total_text_bytes > self.max_total_text_bytes:
                if len(st.history) <= 1 and st.total_text_bytes > self.max_total_text_bytes:
                    raise ContextCapacityError("Single turn exceeds total textual context budget")
                dropped = st.history.pop(0)
                st.total_text_bytes = max(0, st.total_text_bytes - dropped.byte_len)
                st.history_truncated = True

            if role == "assistant":
                st.last_reply = bounded
            return self._build_snapshot(st)

    def apply_slot_delta(
        self,
        *,
        session_id: str,
        incarnation_id: str,
        delta: SlotDelta,
    ) -> tuple[SlotMutationOutcome, DialogueContextSnapshot]:
        """Apply CAS SlotDelta and invalidate dependent protected refs / verified facts."""
        key = (session_id, incarnation_id)
        lock = self._get_or_create_lock(key)
        with lock:
            st = self._sessions.get(key)
            if st is None:
                raise KeyError(f"Unknown dialogue session context: {key}")
            if st.closed:
                raise ContextClosedError(f"Dialogue session context already closed: {key}")

            outcome = self._slot_manager.validate_and_apply(
                st.slots,
                st.state_revision,
                delta,
                max_slots=self.max_slots,
            )
            if outcome.applied and not outcome.no_op:
                st.state_revision = outcome.new_revision
                if outcome.customer_switched:
                    st.verified_fact_refs.clear()
                    st.protected_refs = ProtectedRefs(
                        pending_challenge_id=None,
                        pending_operation_id=st.protected_refs.pending_operation_id,
                        pending_idempotency_key=st.protected_refs.pending_idempotency_key,
                        active_booking_ref=None,
                        availability_valid=False,
                    )
                else:
                    st.protected_refs = ProtectedRefs(
                        pending_challenge_id=(
                            None if outcome.invalidate_confirmation else st.protected_refs.pending_challenge_id
                        ),
                        pending_operation_id=st.protected_refs.pending_operation_id,
                        pending_idempotency_key=st.protected_refs.pending_idempotency_key,
                        active_booking_ref=st.protected_refs.active_booking_ref,
                        availability_valid=(
                            False if outcome.invalidate_availability else st.protected_refs.availability_valid
                        ),
                    )
            return outcome, self._build_snapshot(st)

    def update_runtime_state(
        self,
        *,
        session_id: str,
        incarnation_id: str,
        expected_state_revision: int,
        active_workflow: str | None = None,
        workflow_stage: str | None = None,
        principal_ref: str | None = None,
        subject_ref: str | None = None,
        protected_refs: ProtectedRefs | None = None,
        add_verified_facts: tuple[VerifiedFactRef, ...] = (),
        add_tool_receipt_refs: tuple[str, ...] = (),
        bump_revision: bool = True,
    ) -> tuple[bool, DialogueContextSnapshot]:
        """CAS update of workflow metadata, principal/subject, and verified/receipt refs."""
        key = (session_id, incarnation_id)
        lock = self._get_or_create_lock(key)
        with lock:
            st = self._sessions.get(key)
            if st is None:
                raise KeyError(f"Unknown dialogue session context: {key}")
            if st.closed:
                raise ContextClosedError(f"Dialogue session context already closed: {key}")
            if st.state_revision != expected_state_revision:
                return False, self._build_snapshot(st)

            if active_workflow is not None:
                st.active_workflow = active_workflow
            if workflow_stage is not None:
                st.workflow_stage = workflow_stage
            if principal_ref is not None:
                require_safe_id(principal_ref, "principal_ref")
                st.principal_ref = principal_ref
            if subject_ref is not None:
                require_safe_id(subject_ref, "subject_ref")
                st.subject_ref = subject_ref
            if protected_refs is not None:
                st.protected_refs = protected_refs
            for fact in add_verified_facts:
                if fact not in st.verified_fact_refs:
                    st.verified_fact_refs.append(fact)
            for ref in add_tool_receipt_refs:
                if ref not in st.tool_receipt_refs:
                    st.tool_receipt_refs.append(ref)
            if bump_revision:
                st.state_revision += 1
            return True, self._build_snapshot(st)

    def get_last_reply(self, session_id: str, incarnation_id: str) -> str:
        key = (session_id, incarnation_id)
        lock = self._get_or_create_lock(key)
        with lock:
            st = self._sessions.get(key)
            return st.last_reply if st is not None else ""

    def close_session(self, session_id: str, incarnation_id: str) -> CleanupReport:
        """Idempotently release transient context while reporting pending challenge/operation refs."""
        key = (session_id, incarnation_id)
        lock = self._get_or_create_lock(key)
        with lock:
            st = self._sessions.get(key)
            if st is None:
                return CleanupReport(
                    already_closed=True,
                    revoked_challenge_id=None,
                    preserved_operation_id=None,
                    cleared_turns=0,
                    cleared_slots=0,
                )
            if st.closed:
                return CleanupReport(
                    already_closed=True,
                    revoked_challenge_id=None,
                    preserved_operation_id=st.protected_refs.pending_operation_id,
                    cleared_turns=0,
                    cleared_slots=0,
                )
            revoked_challenge = st.protected_refs.pending_challenge_id
            preserved_op = st.protected_refs.pending_operation_id
            cleared_turns = len(st.history)
            cleared_slots = len(st.slots)
            st.history.clear()
            st.total_text_bytes = 0
            st.slots.clear()
            st.verified_fact_refs.clear()
            st.last_reply = ""
            st.protected_refs = ProtectedRefs(
                pending_challenge_id=None,
                pending_operation_id=preserved_op,
                pending_idempotency_key=st.protected_refs.pending_idempotency_key,
                active_booking_ref=st.protected_refs.active_booking_ref,
                availability_valid=False,
            )
            st.closed = True
            return CleanupReport(
                already_closed=False,
                revoked_challenge_id=revoked_challenge,
                preserved_operation_id=preserved_op,
                cleared_turns=cleared_turns,
                cleared_slots=cleared_slots,
            )
