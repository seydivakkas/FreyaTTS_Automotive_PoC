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
from typing import Any, Callable

from backend.core.configuration.contracts import SupervisorMode
from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.core.contracts.dialogue import (
    DialogueOutcome,
    DialogueResponse,
    ProviderMode,
    ToolReceipt,
    ToolReceiptStatus,
)
from backend.supervisor.dialogue_facade import DialogueFacade, DialogueTurnOutcome
from backend.supervisor.response_composer import receipt_to_semantic_text


@dataclass(frozen=True, slots=True)
class LegacyReplyProjection:
    """Preserves legacy public return shape while keeping internal verified receipt truth."""

    public_ok: bool
    reply_text: str | None
    internal_receipt: ToolReceipt
    mode: SupervisorMode


def legacy_bool_to_receipt(
    *,
    operation_id: str,
    tool_id: str,
    legacy_ok: bool,
    verified_evidence_ref: str | None = None,
    provider_mode: ProviderMode = ProviderMode.UNKNOWN,
) -> ToolReceipt:
    """
    Convert a legacy public bool return into an honest M01 ToolReceipt.

    A bare legacy True WITHOUT verified REAL evidence is downgraded internally
    to UNKNOWN (verified_result=False) — never upgraded to verified commit.
    """
    if not legacy_ok:
        return ToolReceipt(
            operation_id=operation_id,
            tool_id=tool_id,
            status=ToolReceiptStatus.FAILED,
            provider_mode=provider_mode,
            verified_result=False,
            error=ErrorInfo(
                code="legacy.boolean_false",
                category=ErrorCategory.PROVIDER,
                retryable=Retryability.UNKNOWN,
                safe_message="Legacy workflow returned false",
            ),
        )
    if verified_evidence_ref and provider_mode == ProviderMode.REAL:
        return ToolReceipt(
            operation_id=operation_id,
            tool_id=tool_id,
            status=ToolReceiptStatus.COMMITTED,
            provider_mode=ProviderMode.REAL,
            evidence_ref=verified_evidence_ref,
            verified_result=True,
        )
    return ToolReceipt(
        operation_id=operation_id,
        tool_id=tool_id,
        status=ToolReceiptStatus.UNKNOWN,
        provider_mode=provider_mode,
        evidence_ref=verified_evidence_ref,
        verified_result=False,
        error=ErrorInfo(
            code="legacy.unverified_boolean_true",
            category=ErrorCategory.PROVIDER,
            retryable=Retryability.UNKNOWN,
            safe_message="Legacy True lacks verified transaction receipt",
        ),
    )


class LegacyDialogueAdapter:
    """
    Backward-compatible adapter for backend.dialogue.Dialogue and WebSupervisor shapes.

    Preserves external return types (str | None, bool) without modifying existing
    protected files or weakening M07 enforcement in GUARDED mode.
    """

    def __init__(self, facade: DialogueFacade) -> None:
        self._facade = facade

    def project_outcome(self, outcome: DialogueTurnOutcome) -> LegacyReplyProjection:
        resp: DialogueResponse | None = outcome.response
        receipt = outcome.receipt or ToolReceipt(
            operation_id="legacy-noop",
            tool_id="dialogue.reply",
            status=ToolReceiptStatus.COMMITTED if resp is not None else ToolReceiptStatus.FAILED,
            provider_mode=ProviderMode.MOCK,
            verified_result=False,
        )
        if outcome.receipt is not None and not outcome.receipt.is_committed_real:
            text, _, _ = receipt_to_semantic_text(outcome.receipt)
        else:
            text = resp.speech_text if resp is not None else None

        public_ok = resp is not None and resp.outcome not in {DialogueOutcome.BLOCKED, DialogueOutcome.ERROR}
        return LegacyReplyProjection(
            public_ok=public_ok,
            reply_text=text,
            internal_receipt=receipt,
            mode=outcome.mode,
        )

    @staticmethod
    def wrap_legacy_dtmf_result(
        *,
        digit: str,
        raw_reply: str,
        accepted: bool,
        operation_id: str,
    ) -> LegacyReplyProjection:
        receipt = legacy_bool_to_receipt(
            operation_id=operation_id,
            tool_id="dtmf.handle",
            legacy_ok=accepted,
            verified_evidence_ref=f"dtmf:{digit}" if accepted else None,
            provider_mode=ProviderMode.MOCK,
        )
        return LegacyReplyProjection(
            public_ok=accepted,
            reply_text=raw_reply,
            internal_receipt=receipt,
            mode=SupervisorMode.OFF,
        )
