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

import re
from dataclasses import dataclass, replace
from typing import Iterable

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.core.contracts.dialogue import (
    DialogueOutcome,
    DialogueResponse,
    ProviderMode,
    ToolReceipt,
    ToolReceiptStatus,
)
from backend.observability.projection import contains_sentinel

_PRICE_CLAIM_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(?:tl|lira|kuruş|eur|usd)\b", re.IGNORECASE)
_BOOKING_REF_RE = re.compile(r"\bFRY-[A-Z0-9]{4,16}\b")
_DATE_CLAIM_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|\d{2}\.\d{2}\.20\d{2})\b")
_COMMIT_CLAIM_RE = re.compile(
    r"\b(?:randevunuz\s+onaylandı|randevunuz\s+oluşturuldu|işleminiz\s+tamamlandı|gerçek\s+randevu\s+oluşturuldu)\b",
    re.IGNORECASE,
)
_F4_MARKUP_RE = re.compile(r"<\s*/?\s*(?:speak|phoneme|prosody|break|say-as)\b|/[a-zA-Zɑɛɪɔʊʃʒθðŋ]{2,}/")


@dataclass(frozen=True, slots=True)
class ResponseValidationResult:
    """Result of validating an outgoing M01 DialogueResponse against grounded facts."""

    valid: bool
    response: DialogueResponse
    violations: tuple[str, ...] = ()
    replaced: bool = False


class ResponseValidator:
    """
    Validates critical fact consistency, no-F4-normalization invariant, and
    non-empty semantic text before atomic M02 response admission.
    """

    SAFE_FALLBACK_TEXT = "Bilgileri doğrulayamadığım için şu anda kesin yanıt veremiyorum."

    def validate(
        self,
        response: DialogueResponse,
        *,
        receipts: Iterable[ToolReceipt] = (),
        authorized_numbers: Iterable[str] = (),
        authorized_dates: Iterable[str] = (),
        authorized_booking_refs: Iterable[str] = (),
    ) -> ResponseValidationResult:
        if not isinstance(response, DialogueResponse):
            raise TypeError("response must be M01 DialogueResponse")

        violations: list[str] = []
        receipt_list = tuple(receipts)

        if response.outcome != DialogueOutcome.NO_RESPONSE and not response.speech_text.strip():
            violations.append("response.empty_speech_text")

        if _F4_MARKUP_RE.search(response.speech_text):
            violations.append("response.f4_normalization_markup_prohibited")

        # Commit claims require an actual COMMITTED REAL receipt (never MOCK/UNKNOWN/no receipt).
        if _COMMIT_CLAIM_RE.search(response.speech_text) and "[TEST/SİMÜLASYON]" not in response.speech_text:
            has_real_commit = any(
                r.status == ToolReceiptStatus.COMMITTED and r.provider_mode == ProviderMode.REAL and r.verified_result
                for r in receipt_list
            )
            if not has_real_commit:
                violations.append("response.ungrounded_commit_claim")

        # Critical price/number grounding.
        auth_nums = {str(x).replace(",", ".").strip() for x in authorized_numbers}
        for m in _PRICE_CLAIM_RE.finditer(response.speech_text):
            raw_num = m.group(1).replace(".", "").replace(",", ".")
            raw_exact = m.group(1).replace(",", ".")
            if raw_num not in auth_nums and raw_exact not in auth_nums:
                violations.append("response.ungrounded_price_claim")
                break

        # Critical booking reference grounding.
        auth_refs = {str(x).strip() for x in authorized_booking_refs}
        for r in receipt_list:
            if r.evidence_ref:
                auth_refs.add(r.evidence_ref)
        for m in _BOOKING_REF_RE.finditer(response.speech_text):
            if m.group(0) not in auth_refs:
                violations.append("response.ungrounded_booking_ref")
                break

        # Critical date grounding.
        auth_dates = {str(x).strip() for x in authorized_dates}
        for m in _DATE_CLAIM_RE.finditer(response.speech_text):
            if m.group(1) not in auth_dates:
                violations.append("response.ungrounded_date_claim")
                break

        # Display text must never leak PII/secret sentinels when telemetry/display restricted.
        if response.display_text and contains_sentinel(response.display_text):
            violations.append("response.display_pii_sentinel")

        if not violations:
            return ResponseValidationResult(valid=True, response=response, violations=(), replaced=False)

        safe_err = ErrorInfo(
            code="response.validation_blocked",
            category=ErrorCategory.VALIDATION,
            retryable=Retryability.NO,
            safe_message="Response blocked or replaced due to ungrounded critical fact",
        )
        safe_response = replace(
            response,
            speech_text=self.SAFE_FALLBACK_TEXT,
            display_text=None,
            speech_act="SAFE_FALLBACK",
            outcome=DialogueOutcome.CLARIFICATION_REQUIRED
            if response.outcome == DialogueOutcome.OK
            else response.outcome,
            error=safe_err,
        )
        return ResponseValidationResult(
            valid=False,
            response=safe_response,
            violations=tuple(violations),
            replaced=True,
        )
