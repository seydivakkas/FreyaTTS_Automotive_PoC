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
from typing import Any, Mapping

from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability
from backend.core.contracts.synthesis import ChunkPlan

MAX_ENCODER_TOKENS = 512


class EncoderValidationError(ValueError):
    """Raised when prepared model_text fails vocabulary or transformation guards."""

    def __init__(self, error_info: ErrorInfo) -> None:
        super().__init__(error_info.safe_message)
        self.error_info = error_info


@dataclass(frozen=True, slots=True)
class EncodedCondition:
    """Encoded text representation produced strictly from ChunkPlan.model_text without normalization."""

    chunk_id: str
    chunk_index: int
    token_ids: tuple[int, ...]
    token_count: int
    char_count: int
    vocab_revision: str
    context: Any
    char_mask: Any
    normalization_executed: bool = False


class EncoderAdapter:
    """
    Strict prepared-text encoder adapter.

    Guarantees:
    - Reads ONLY `ChunkPlan.model_text`.
    - Performs ZERO linguistic normalization, stripping, substitution, or <UNK> fallback.
    - Rejects any character missing from the approved model vocabulary.
    - Rejects any encoder wrapper that mutates/cleans `model_text`.
    """

    def __init__(self, *, max_tokens: int = MAX_ENCODER_TOKENS) -> None:
        if type(max_tokens) is not int or max_tokens < 1:
            raise ValueError("max_tokens must be positive int")
        self.max_tokens = max_tokens

    def validate_and_tokenize(
        self,
        chunk: ChunkPlan,
        char_to_id: Mapping[str, int],
    ) -> tuple[int, ...]:
        text = chunk.model_text
        if not isinstance(text, str) or not text.strip():
            raise EncoderValidationError(
                ErrorInfo(
                    code="BLANK_MODEL_TEXT",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message="Chunk model_text must be non-blank",
                    field_name="model_text",
                )
            )
        if len(text) > self.max_tokens:
            raise EncoderValidationError(
                ErrorInfo(
                    code="TOKEN_COUNT_EXCEEDED",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Token count {len(text)} exceeds max_tokens {self.max_tokens}",
                    field_name="model_text",
                )
            )

        missing = sorted({ch for ch in text if ch not in char_to_id})
        if missing:
            raise EncoderValidationError(
                ErrorInfo(
                    code="UNSUPPORTED_VOCABULARY",
                    category=ErrorCategory.VALIDATION,
                    retryable=Retryability.NO,
                    safe_message=f"Unsupported codepoints count={len(missing)} in prepared model_text",
                    field_name="model_text",
                )
            )

        return tuple(int(char_to_id[ch]) for ch in text)

    def encode(
        self,
        chunk: ChunkPlan,
        *,
        tts_model: Any,
        char_to_id: Mapping[str, int],
        vocab_revision: str,
        device: str = "cpu",
    ) -> EncodedCondition:
        exact_text = chunk.model_text
        token_ids = self.validate_and_tokenize(chunk, char_to_id)

        context: Any
        char_mask: Any = None
        if hasattr(tts_model, "encode_prepared_text"):
            out = tts_model.encode_prepared_text(exact_text, token_ids, device=device)
            if isinstance(out, dict):
                observed_text = out.get("observed_text")
                if observed_text is not None and observed_text != exact_text:
                    raise EncoderValidationError(
                        ErrorInfo(
                            code="UNTRUSTED_TEXT_TRANSFORMATION",
                            category=ErrorCategory.VALIDATION,
                            retryable=Retryability.NO,
                            safe_message="Encoder attempted hidden text transformation on prepared model_text",
                            field_name="model_text",
                        )
                    )
                if out.get("normalized_by_encoder"):
                    raise EncoderValidationError(
                        ErrorInfo(
                            code="UNTRUSTED_TEXT_TRANSFORMATION",
                            category=ErrorCategory.VALIDATION,
                            retryable=Retryability.NO,
                            safe_message="Encoder reported internal linguistic normalization",
                            field_name="model_text",
                        )
                    )
                context = out.get("context")
                char_mask = out.get("char_mask")
            else:
                context = out
        elif hasattr(tts_model, "text_encode"):
            import torch

            ids_tensor = torch.tensor([list(token_ids)], dtype=torch.long, device=device)
            char_mask = torch.ones_like(ids_tensor, dtype=torch.bool)
            with torch.inference_mode():
                context = tts_model.text_encode(ids_tensor)
        else:
            raise EncoderValidationError(
                ErrorInfo(
                    code="ENCODER_HANDLE_UNSUPPORTED",
                    category=ErrorCategory.PROVIDER,
                    retryable=Retryability.NO,
                    safe_message="TTS model handle exposes neither encode_prepared_text nor text_encode",
                )
            )

        return EncodedCondition(
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            token_ids=token_ids,
            token_count=len(token_ids),
            char_count=len(exact_text),
            vocab_revision=vocab_revision,
            context=context,
            char_mask=char_mask,
            normalization_executed=False,
        )


__all__ = [
    "EncodedCondition",
    "EncoderAdapter",
    "EncoderValidationError",
    "MAX_ENCODER_TOKENS",
]
