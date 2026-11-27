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

import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from backend.core.contracts.common import GenerationRef, TurnRef
from backend.core.contracts.validation import freeze_value
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.deadlines import Clock, DeadlineBudget, SystemMonotonicClock
from backend.observability.projection import redact_sentinels
from backend.runtime_resources.contracts import (
    AdmissionOutcome,
    ExecutionLeaseState,
    PriorityClass,
    ProviderKind,
    ResourceRequest,
)
from backend.runtime_resources.scheduler import ExecutionOutcome, UnifiedGpuScheduler
from backend.security.contracts import redact_sensitive_text
from backend.supervisor.contracts import Intent

MAX_LLM_PROMPT_CHARS = 1200
MAX_LLM_OUTPUT_BYTES = 4096

# Strict allowlist of tools an untrusted LLM proposal may name (never grants permission).
ALLOWLISTED_LLM_TOOLS: frozenset[str] = frozenset({
    "vehicle.read_specs",
    "availability.read",
    "booking.read_status",
    "customer.read_record",
    "booking.create",
    "booking.reschedule",
    "booking.cancel",
    "complaint.create",
    "operator.transfer_request",
})

_DANGEROUS_PATTERN = re.compile(
    r"(?i)(?:\b(?:select|insert|update|delete|drop|alter|union|exec|eval|__import__|subprocess|os\.system)\b"
    r"|;\s*--|\bhttps?://|\bfile://)",
)


@dataclass(frozen=True, slots=True)
class UntrustedToolProposal:
    """Validated-shape LLM proposal; strictly untrusted (has_authority is always False)."""

    valid: bool
    intent: Intent | None
    proposed_tool: str | None
    arguments: Mapping[str, Any]
    speech_text: str
    claimed_role: str | None = None
    error_code: str | None = None
    has_authority: bool = False

    def __post_init__(self) -> None:
        if self.has_authority:
            raise ValueError("UntrustedToolProposal can never hold authority")
        object.__setattr__(self, "arguments", freeze_value(dict(self.arguments)))


@dataclass(frozen=True, slots=True)
class LLMBridgeResult:
    """Result of executing an LLM fallback request strictly via M06 UnifiedGpuScheduler."""

    executed: bool
    admission: AdmissionOutcome
    lease_id: str | None
    lease_state: ExecutionLeaseState | None
    quarantined: bool
    fenced: bool
    proposal: UntrustedToolProposal | None
    latency_ms: float | None
    error_code: str | None = None


def validate_untrusted_proposal(raw_output: str | bytes | Mapping[str, Any]) -> UntrustedToolProposal:
    """
    Strictly parse and allowlist-validate an untrusted LLM JSON proposal.

    Rejects oversized payloads, malformed JSON, unknown intents/tools, SQL/shell/URL
    injections, and ignores any claimed admin/bypass privilege fields.
    """
    if isinstance(raw_output, bytes):
        if len(raw_output) > MAX_LLM_OUTPUT_BYTES:
            return UntrustedToolProposal(
                valid=False,
                intent=None,
                proposed_tool=None,
                arguments={},
                speech_text="",
                error_code="llm.oversized_output",
            )
        try:
            raw_text = raw_output.decode("utf-8")
        except UnicodeDecodeError:
            return UntrustedToolProposal(
                valid=False,
                intent=None,
                proposed_tool=None,
                arguments={},
                speech_text="",
                error_code="llm.invalid_utf8",
            )
    elif isinstance(raw_output, str):
        if len(raw_output.encode("utf-8")) > MAX_LLM_OUTPUT_BYTES:
            return UntrustedToolProposal(
                valid=False,
                intent=None,
                proposed_tool=None,
                arguments={},
                speech_text="",
                error_code="llm.oversized_output",
            )
        raw_text = raw_output
    elif isinstance(raw_output, Mapping):
        encoded = json.dumps(dict(raw_output), ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_LLM_OUTPUT_BYTES:
            return UntrustedToolProposal(
                valid=False,
                intent=None,
                proposed_tool=None,
                arguments={},
                speech_text="",
                error_code="llm.oversized_output",
            )
        data = dict(raw_output)
        raw_text = ""
    else:
        return UntrustedToolProposal(
            valid=False,
            intent=None,
            proposed_tool=None,
            arguments={},
            speech_text="",
            error_code="llm.unsupported_output_type",
        )

    if not isinstance(raw_output, Mapping):
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            return UntrustedToolProposal(
                valid=False,
                intent=None,
                proposed_tool=None,
                arguments={},
                speech_text="",
                error_code="llm.invalid_json",
            )
        if not isinstance(parsed, dict):
            return UntrustedToolProposal(
                valid=False,
                intent=None,
                proposed_tool=None,
                arguments={},
                speech_text="",
                error_code="llm.json_not_object",
            )
        data = parsed

    # Strip/note privilege escalation claims without ever granting authority.
    claimed_role: str | None = None
    for priv_key in ("role", "claimed_role", "admin", "bypass_policy", "verified", "is_admin"):
        if priv_key in data and data[priv_key] is not None:
            claimed_role = str(data[priv_key])[:64]

    raw_intent = data.get("intent")
    if not isinstance(raw_intent, str) or not raw_intent.strip():
        return UntrustedToolProposal(
            valid=False,
            intent=None,
            proposed_tool=None,
            arguments={},
            speech_text="",
            claimed_role=claimed_role,
            error_code="llm.missing_intent",
        )
    try:
        intent = Intent(raw_intent.strip())
    except ValueError:
        return UntrustedToolProposal(
            valid=False,
            intent=None,
            proposed_tool=None,
            arguments={},
            speech_text="",
            claimed_role=claimed_role,
            error_code="llm.unknown_intent",
        )

    proposed_tool = data.get("proposed_tool")
    if proposed_tool is not None:
        if not isinstance(proposed_tool, str) or proposed_tool not in ALLOWLISTED_LLM_TOOLS:
            return UntrustedToolProposal(
                valid=False,
                intent=intent,
                proposed_tool=None,
                arguments={},
                speech_text="",
                claimed_role=claimed_role,
                error_code="llm.unknown_or_forbidden_tool",
            )

    raw_args = data.get("arguments") or {}
    if not isinstance(raw_args, Mapping):
        return UntrustedToolProposal(
            valid=False,
            intent=intent,
            proposed_tool=None,
            arguments={},
            speech_text="",
            claimed_role=claimed_role,
            error_code="llm.invalid_arguments",
        )

    clean_args: dict[str, Any] = {}
    for k, v in raw_args.items():
        ks = str(k)
        if ks in {"sql", "query", "command", "shell", "eval", "exec", "admin", "bypass", "verified"}:
            return UntrustedToolProposal(
                valid=False,
                intent=intent,
                proposed_tool=None,
                arguments={},
                speech_text="",
                claimed_role=claimed_role,
                error_code="llm.forbidden_argument_key",
            )
        if isinstance(v, str) and _DANGEROUS_PATTERN.search(v):
            return UntrustedToolProposal(
                valid=False,
                intent=intent,
                proposed_tool=None,
                arguments={},
                speech_text="",
                claimed_role=claimed_role,
                error_code="llm.injection_rejected",
            )
        clean_args[ks] = v

    speech = str(data.get("speech_text", ""))
    if _DANGEROUS_PATTERN.search(speech):
        return UntrustedToolProposal(
            valid=False,
            intent=intent,
            proposed_tool=None,
            arguments={},
            speech_text="",
            claimed_role=claimed_role,
            error_code="llm.dangerous_speech_payload",
        )

    return UntrustedToolProposal(
        valid=True,
        intent=intent,
        proposed_tool=proposed_tool,
        arguments=MappingProxyType(clean_args),
        speech_text=speech,
        claimed_role=claimed_role,
        error_code=None,
        has_authority=False,
    )


class LLMAdapter:
    """
    Bounded M06 PriorityClass.P3 bridge for Qwen/Ollama proposals.

    Never bypasses M06 UnifiedGpuScheduler when admission is rejected or expired,
    and retains/fences quarantined leases when native completion status is unknown.
    """

    def __init__(
        self,
        scheduler: UnifiedGpuScheduler,
        *,
        model_id: str = "qwen2.5-3b-instruct",
        estimated_vram_bytes: int = 0,
        clock: Clock | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._model_id = model_id
        self._estimated_vram_bytes = estimated_vram_bytes
        self._clock: Clock = clock or scheduler.clock or SystemMonotonicClock()

    def build_sanitized_prompt(
        self,
        utterance: str,
        *,
        intent_hint: str | None = None,
        safe_slots: Mapping[str, Any] | None = None,
    ) -> str:
        """Build a bounded, PII-redacted prompt payload without raw DB records or secrets."""
        redacted_utt, _ = redact_sentinels(redact_sensitive_text(utterance[:MAX_LLM_PROMPT_CHARS]))
        payload = {
            "task": "classify_automotive_intent",
            "text": redacted_utt[:MAX_LLM_PROMPT_CHARS],
            "intent_hint": intent_hint,
            "slots": {str(k): str(v)[:120] for k, v in (safe_slots or {}).items()},
        }
        return json.dumps(payload, ensure_ascii=False)[:MAX_LLM_PROMPT_CHARS]

    async def propose(
        self,
        *,
        utterance: str,
        session_id: str,
        turn_ref: TurnRef | None,
        generation_ref: GenerationRef | None,
        cancellation_scope: CancellationScope,
        deadline: DeadlineBudget | None = None,
        model_id: str | None = None,
        safe_slots: Mapping[str, Any] | None = None,
        drain_grace_ms: int = 50,
    ) -> LLMBridgeResult:
        """Submit a P3 OLLAMA ResourceRequest through M06 and validate any delivered proposal."""
        if cancellation_scope.is_cancel_requested:
            return LLMBridgeResult(
                executed=False,
                admission=AdmissionOutcome.REJECTED_CANCELLED,
                lease_id=None,
                lease_state=None,
                quarantined=False,
                fenced=True,
                proposal=None,
                latency_ms=None,
                error_code="llm.scope_cancelled_before_submit",
            )

        prompt_payload = self.build_sanitized_prompt(utterance, safe_slots=safe_slots)
        req = ResourceRequest(
            request_id=f"llm-x{uuid4().hex[:12]}",
            priority=PriorityClass.P3,
            provider=ProviderKind.OLLAMA,
            model_id=model_id or self._model_id,
            estimated_vram_bytes=self._estimated_vram_bytes,
            cancellation_scope=cancellation_scope,
            session_id=session_id,
            turn_ref=turn_ref,
            generation_ref=generation_ref,
            deadline=deadline,
            drain_grace_ms=drain_grace_ms,
            payload=prompt_payload,
        )

        t0_ns = self._clock.monotonic_ns()
        outcome: ExecutionOutcome = await self._scheduler.run_request(req)
        t1_ns = self._clock.monotonic_ns()
        latency_ms = max(0.0, (t1_ns - t0_ns) / 1_000_000.0)

        if outcome.admission != AdmissionOutcome.ADMITTED:
            return LLMBridgeResult(
                executed=False,
                admission=outcome.admission,
                lease_id=outcome.lease_id,
                lease_state=outcome.lease_state,
                quarantined=outcome.quarantined,
                fenced=False,
                proposal=None,
                latency_ms=None,
                error_code=outcome.error or f"llm.{outcome.admission.value.lower()}",
            )

        # If cancelled / quarantined / fenced, NEVER deliver stale LLM output.
        if outcome.quarantined or cancellation_scope.is_cancel_requested or outcome.fenced_outputs > 0:
            return LLMBridgeResult(
                executed=True,
                admission=outcome.admission,
                lease_id=outcome.lease_id,
                lease_state=outcome.lease_state,
                quarantined=outcome.quarantined,
                fenced=True,
                proposal=None,
                latency_ms=latency_ms,
                error_code="llm.output_fenced_or_quarantined",
            )

        if not outcome.delivered:
            return LLMBridgeResult(
                executed=True,
                admission=outcome.admission,
                lease_id=outcome.lease_id,
                lease_state=outcome.lease_state,
                quarantined=False,
                fenced=False,
                proposal=None,
                latency_ms=latency_ms,
                error_code="llm.empty_delivery",
            )

        if len(outcome.delivered) > 1 and all(isinstance(x, str) for x in outcome.delivered):
            raw_item: Any = "".join(outcome.delivered)
        else:
            raw_item = outcome.delivered[-1]
        proposal = validate_untrusted_proposal(raw_item)
        return LLMBridgeResult(
            executed=True,
            admission=outcome.admission,
            lease_id=outcome.lease_id,
            lease_state=outcome.lease_state,
            quarantined=False,
            fenced=False,
            proposal=proposal,
            latency_ms=latency_ms,
            error_code=proposal.error_code,
        )
