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

from enum import StrEnum

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.observability.projection import redact_sentinels


class ASRDispatchStatus(StrEnum):
    """Distinct scheduling/execution status separate from M01 ASROutcome."""

    QUEUED = "QUEUED"
    ADMITTED = "ADMITTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELED = "CANCELED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class ASRDeliveryStatus(StrEnum):
    """Downstream M02 result admission status separate from native completion."""

    DELIVERED = "DELIVERED"
    FENCED_STALE = "FENCED_STALE"
    REJECTED_BACKPRESSURE = "REJECTED_BACKPRESSURE"
    REJECTED_CLOSED = "REJECTED_CLOSED"
    NOT_DELIVERED = "NOT_DELIVERED"


class F2ABaseError(Exception):
    """Base typed exception carrying a safe M01 error code and category."""

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        category: ErrorCategory = ErrorCategory.VALIDATION,
        retryable: Retryability = Retryability.NO,
        field_name: str | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.category = category
        self.retryable = retryable
        self.safe_message = safe_message
        self.field_name = field_name

    def to_error_info(self) -> ErrorInfo:
        return build_safe_error_info(
            code=self.code,
            category=self.category,
            retryable=self.retryable,
            safe_message=self.safe_message,
            field_name=self.field_name,
        )


class ASRInputError(F2ABaseError):
    """Raised when incoming M01 Utterance or audio payload fails boundary validation."""

    def __init__(self, code: str, safe_message: str, *, field_name: str | None = None) -> None:
        super().__init__(
            code=code,
            safe_message=safe_message,
            category=ErrorCategory.VALIDATION,
            retryable=Retryability.NO,
            field_name=field_name,
        )


class ASRAdmissionError(F2ABaseError):
    """Raised when M02 utterance claim, scope fence, or queue admission fails."""

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        category: ErrorCategory = ErrorCategory.STALE_SCOPE,
        retryable: Retryability = Retryability.NO,
    ) -> None:
        super().__init__(
            code=code,
            safe_message=safe_message,
            category=category,
            retryable=retryable,
        )


class ASRConfigError(F2ABaseError):
    """Raised when M03 config or model capability cannot satisfy strict F2-A execution."""

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        category: ErrorCategory = ErrorCategory.VALIDATION,
        field_name: str | None = None,
    ) -> None:
        super().__init__(
            code=code,
            safe_message=safe_message,
            category=category,
            retryable=Retryability.NO,
            field_name=field_name,
        )


class ASRProviderError(F2ABaseError):
    """Raised when CTranslate2/Whisper execution or segment collection fails."""

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        retryable: Retryability = Retryability.UNKNOWN,
        uncertain_completion: bool = False,
    ) -> None:
        super().__init__(
            code=code,
            safe_message=safe_message,
            category=ErrorCategory.PROVIDER,
            retryable=retryable,
        )
        self.uncertain_completion = uncertain_completion


class ASRDeliveryError(F2ABaseError):
    """Raised when atomic downstream delivery fails due to backpressure or closed consumer."""

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        category: ErrorCategory = ErrorCategory.CAPACITY,
        retryable: Retryability = Retryability.NO,
    ) -> None:
        super().__init__(
            code=code,
            safe_message=safe_message,
            category=category,
            retryable=retryable,
        )


def build_safe_error_info(
    *,
    code: str,
    category: ErrorCategory,
    retryable: Retryability = Retryability.UNKNOWN,
    safe_message: str = "",
    field_name: str | None = None,
) -> ErrorInfo:
    """Construct an M01 ErrorInfo after scrubbing PII, transcript, and token sentinels."""
    sanitized, _ = redact_sentinels(str(safe_message or "")[:240])
    return ErrorInfo(
        code=code,
        category=category,
        retryable=retryable,
        safe_message=sanitized,
        field_name=field_name,
    )
