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

from uuid import uuid4

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, ErrorInfo, EventEnvelope
from backend.core.contracts.dialogue import (
    DialogueOutcome,
    DialogueResponse,
    ProviderMode,
    ToolReceipt,
    ToolReceiptStatus,
    VerifiedFactRef,
)
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock


def receipt_to_semantic_text(
    receipt: ToolReceipt,
    *,
    details: dict[str, object] | None = None,
) -> tuple[str, str, DialogueOutcome]:
    """
    Deterministic receipt-grounded Turkish semantic text & speech_act.

    Strictly separates COMMITTED+REAL, COMMITTED+MOCK, PENDING, UNKNOWN, FAILED,
    BLOCKED, transfer-submitted, and notification-queued outcomes.
    """
    info = details or {}

    if receipt.tool_id == "operator.transfer_request" and receipt.status == ToolReceiptStatus.PENDING:
        return (
            "Operatör aktarım talebiniz iletildi; henüz canlı bağlantı kurulmadı.",
            "OPERATOR_TRANSFER_SUBMITTED",
            DialogueOutcome.OK,
        )

    if receipt.tool_id == "notification.enqueue" and receipt.status == ToolReceiptStatus.PENDING:
        return (
            "Bildirim kuyruğa alındı; henüz teslim edilmedi.",
            "NOTIFICATION_QUEUED",
            DialogueOutcome.OK,
        )

    if receipt.status == ToolReceiptStatus.COMMITTED:
        if receipt.provider_mode == ProviderMode.REAL and receipt.verified_result:
            ref = str(info.get("reference_code") or receipt.evidence_ref or "").strip()
            ref_part = f" Referans kodunuz: {ref}." if ref else ""
            return (
                f"İşleminiz onaylandı ve tamamlandı.{ref_part}",
                "CONFIRMATION_COMMITTED",
                DialogueOutcome.OK,
            )
        if receipt.provider_mode == ProviderMode.MOCK:
            ref = str(info.get("reference_code") or receipt.evidence_ref or "").strip()
            ref_part = f" Test referansı: {ref}." if ref else ""
            return (
                f"[TEST/SİMÜLASYON] İşlem simülasyon modunda kaydedildi; gerçek bir kayıt oluşturulmadı.{ref_part}",
                "MOCK_COMMITTED",
                DialogueOutcome.OK,
            )
        # COMMITTED without verified REAL evidence or unknown provider mode -> cannot claim verified real commit.
        return (
            "İşlemin sonucunu henüz doğrulayamadım.",
            "RECEIPT_UNVERIFIED",
            DialogueOutcome.OK,
        )

    if receipt.status == ToolReceiptStatus.PENDING:
        return (
            "İşlem henüz tamamlanmadı.",
            "OPERATION_PENDING",
            DialogueOutcome.OK,
        )

    if receipt.status == ToolReceiptStatus.UNKNOWN:
        return (
            "İşlemin sonucunu henüz doğrulayamadım.",
            "OPERATION_UNKNOWN",
            DialogueOutcome.OK,
        )

    if receipt.status == ToolReceiptStatus.BLOCKED:
        return (
            "Güvenlik veya doğrulama gereksinimi nedeniyle bu işlemi gerçekleştiremiyorum.",
            "SECURITY_BLOCKED",
            DialogueOutcome.BLOCKED,
        )

    # FAILED
    return (
        "İşlem tamamlanamadı. Lütfen daha sonra tekrar deneyin veya operatörümüzden destek alın.",
        "OPERATION_FAILED",
        DialogueOutcome.ERROR,
    )


class ResponseComposer:
    """
    Produces immutable semantic Turkish M01 DialogueResponse objects.

    Does NOT perform F4 TTS pronunciation/number normalization, IPA, SSML, or SynthesisPlan.
    """

    def __init__(self, *, clock: Clock | None = None, producer: str = "f3.dialogue") -> None:
        self._clock: Clock = clock or SystemMonotonicClock()
        self._producer = producer
        self._seq = 0

    def compose(
        self,
        *,
        session_id: str,
        trace_id: str | None,
        turn_id: int | None,
        generation_id: int | None = None,
        speech_text: str,
        speech_act: str,
        state_revision: int,
        outcome: DialogueOutcome = DialogueOutcome.OK,
        display_text: str | None = None,
        source_asr_revision: int | None = None,
        focus_entity_refs: tuple[str, ...] = (),
        verified_fact_refs: tuple[VerifiedFactRef, ...] = (),
        tool_receipt_refs: tuple[str, ...] = (),
        error: ErrorInfo | None = None,
        response_id: str | None = None,
    ) -> DialogueResponse:
        self._seq += 1
        env = EventEnvelope(
            schema_version=CONTRACT_SCHEMA_VERSION,
            event_type="dialogue.response",
            session_id=session_id,
            trace_id=trace_id,
            turn_id=turn_id,
            generation_id=generation_id,
            sequence=self._seq,
            monotonic_ns=self._clock.monotonic_ns(),
            clock_domain=self._clock.clock_domain,
            producer=self._producer,
        )
        return DialogueResponse(
            envelope=env,
            response_id=response_id or f"resp-x{uuid4().hex[:12]}",
            speech_text=speech_text,
            speech_act=speech_act,
            state_revision=state_revision,
            outcome=outcome,
            display_text=display_text,
            source_asr_revision=source_asr_revision,
            focus_entity_refs=focus_entity_refs,
            verified_fact_refs=verified_fact_refs,
            tool_receipt_refs=tool_receipt_refs,
            error=error,
        )

    def compose_from_receipt(
        self,
        *,
        session_id: str,
        trace_id: str | None,
        turn_id: int | None,
        receipt: ToolReceipt,
        state_revision: int,
        source_asr_revision: int | None = None,
        verified_fact_refs: tuple[VerifiedFactRef, ...] = (),
        focus_entity_refs: tuple[str, ...] = (),
        details: dict[str, object] | None = None,
        display_text: str | None = None,
    ) -> DialogueResponse:
        speech_text, speech_act, outcome = receipt_to_semantic_text(receipt, details=details)
        return self.compose(
            session_id=session_id,
            trace_id=trace_id,
            turn_id=turn_id,
            speech_text=speech_text,
            speech_act=speech_act,
            state_revision=state_revision,
            outcome=outcome,
            display_text=display_text,
            source_asr_revision=source_asr_revision,
            focus_entity_refs=focus_entity_refs,
            verified_fact_refs=verified_fact_refs,
            tool_receipt_refs=(receipt.operation_id,),
            error=receipt.error if outcome in {DialogueOutcome.BLOCKED, DialogueOutcome.ERROR} else None,
        )
