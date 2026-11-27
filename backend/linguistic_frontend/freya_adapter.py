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
import json
from pathlib import Path
import re
import unicodedata
from typing import Mapping


_SSML_OR_XML_RE = re.compile(r"<\s*/?\s*(?:speak|prosody|break|say-as|phoneme|emphasis|voice|audio|sub|mark)\b[^>]*>", re.IGNORECASE)
_IPA_GLYPHS = frozenset({"ˈ", "ˌ", "ə", "ʃ", "ʒ", "θ", "ð", "ŋ", "ɾ", "ɫ", "ɲ", "ɣ", "ʔ", "ː"})
_SENTINEL_LEAK_RE = re.compile(r"(?:__ATOM_\d+__|\[REDACTED(?:_[A-Z]+)?\])")


class VocabularyStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class VocabularyCheck:
    """CPU-only vocabulary & capability compatibility check without weight loading."""

    model_revision: str
    capability_revision: str
    tokenizer_profile: str
    status: VocabularyStatus
    real_vocab_available: bool
    vocab_sha256: str | None = None
    vocab_size: int = 0
    unsupported_classes: tuple[str, ...] = ()
    unsupported_count: int = 0
    reason_code: str = "OK"


class FreyaVocabularyValidator:
    """
    Validates model_text chunks against FreyaTTS character vocabulary CPU-only
    without importing torch, CUDA, or loading model checkpoint weights.
    """

    def __init__(
        self,
        *,
        vocab_chars: frozenset[str],
        model_revision: str,
        capability_revision: str,
        real_vocab_available: bool,
        vocab_sha256: str | None = None,
        tokenizer_profile: str = "freya-char-vocab",
        max_sequence_chars: int = 270,
    ) -> None:
        self.vocab_chars = vocab_chars
        self.model_revision = model_revision
        self.capability_revision = capability_revision
        self.real_vocab_available = real_vocab_available
        self.vocab_sha256 = vocab_sha256
        self.tokenizer_profile = tokenizer_profile
        self.max_sequence_chars = max_sequence_chars

    @classmethod
    def from_vocab_file(
        cls,
        vocab_path: Path | str | None,
        *,
        model_revision: str,
        capability_revision: str,
        max_sequence_chars: int = 270,
    ) -> "FreyaVocabularyValidator":
        if vocab_path is not None:
            p = Path(vocab_path)
            if p.exists() and p.is_file():
                raw_bytes = p.read_bytes()
                data = json.loads(raw_bytes.decode("utf-8"))
                if isinstance(data, Mapping) and data:
                    chars = frozenset(str(k) for k in data.keys() if k not in {"<FILL>", "<UNK>"})
                    return cls(
                        vocab_chars=chars,
                        model_revision=model_revision,
                        capability_revision=capability_revision,
                        real_vocab_available=True,
                        vocab_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                        tokenizer_profile=f"freya-char-vocab:{p.name}",
                        max_sequence_chars=max_sequence_chars,
                    )
        return cls(
            vocab_chars=frozenset(),
            model_revision=model_revision,
            capability_revision=capability_revision,
            real_vocab_available=False,
            vocab_sha256=None,
            tokenizer_profile="missing-vocab",
            max_sequence_chars=max_sequence_chars,
        )

    @classmethod
    def from_fake_vocab(
        cls,
        vocab_chars: frozenset[str],
        *,
        model_revision: str,
        capability_revision: str,
        max_sequence_chars: int = 270,
    ) -> "FreyaVocabularyValidator":
        """Interface-only fake vocab (real_vocab_available=False so real compatibility remains UNKNOWN)."""
        return cls(
            vocab_chars=frozenset(ch for ch in vocab_chars if ch not in {"<FILL>", "<UNK>"}),
            model_revision=model_revision,
            capability_revision=capability_revision,
            real_vocab_available=False,
            vocab_sha256=None,
            tokenizer_profile="fake-vocab-interface-only",
            max_sequence_chars=max_sequence_chars,
        )

    def check_chunk(
        self,
        model_text: str,
        *,
        expected_capability_revision: str | None = None,
        requested_controls: tuple[str, ...] = (),
        require_real_vocab: bool = True,
    ) -> VocabularyCheck:
        if expected_capability_revision is not None and expected_capability_revision != self.capability_revision:
            return VocabularyCheck(
                model_revision=self.model_revision,
                capability_revision=self.capability_revision,
                tokenizer_profile=self.tokenizer_profile,
                status=VocabularyStatus.FAIL,
                real_vocab_available=self.real_vocab_available,
                vocab_sha256=self.vocab_sha256,
                vocab_size=len(self.vocab_chars),
                unsupported_classes=("CAPABILITY_REVISION_MISMATCH",),
                unsupported_count=1,
                reason_code="CAPABILITY_MISMATCH",
            )

        if not self.vocab_chars or (require_real_vocab and not self.real_vocab_available):
            return VocabularyCheck(
                model_revision=self.model_revision,
                capability_revision=self.capability_revision,
                tokenizer_profile=self.tokenizer_profile,
                status=VocabularyStatus.UNKNOWN,
                real_vocab_available=self.real_vocab_available,
                vocab_sha256=self.vocab_sha256,
                vocab_size=len(self.vocab_chars),
                unsupported_classes=("REAL_VOCAB_UNAVAILABLE",),
                unsupported_count=1,
                reason_code="REAL_VOCAB_UNAVAILABLE",
            )

        if requested_controls:
            return VocabularyCheck(
                model_revision=self.model_revision,
                capability_revision=self.capability_revision,
                tokenizer_profile=self.tokenizer_profile,
                status=VocabularyStatus.FAIL,
                real_vocab_available=self.real_vocab_available,
                vocab_sha256=self.vocab_sha256,
                vocab_size=len(self.vocab_chars),
                unsupported_classes=("UNSUPPORTED_CONTROLS",),
                unsupported_count=len(requested_controls),
                reason_code="UNSUPPORTED_CONTROLS",
            )

        if len(model_text) > self.max_sequence_chars:
            return VocabularyCheck(
                model_revision=self.model_revision,
                capability_revision=self.capability_revision,
                tokenizer_profile=self.tokenizer_profile,
                status=VocabularyStatus.FAIL,
                real_vocab_available=self.real_vocab_available,
                vocab_sha256=self.vocab_sha256,
                vocab_size=len(self.vocab_chars),
                unsupported_classes=("MAX_SEQUENCE_EXCEEDED",),
                unsupported_count=1,
                reason_code="LIMIT_EXCEEDED",
            )

        classes: list[str] = []
        bad_count = 0

        if _SSML_OR_XML_RE.search(model_text):
            classes.append("SSML_OR_MARKUP")
            bad_count += 1
        if _SENTINEL_LEAK_RE.search(model_text):
            classes.append("SENTINEL_LEAK")
            bad_count += 1

        for ch in model_text:
            code = ord(ch)
            if 0xD800 <= code <= 0xDFFF or unicodedata.category(ch) == "Cc":
                if "CONTROL_CHAR" not in classes:
                    classes.append("CONTROL_CHAR")
                bad_count += 1
                continue
            if ch in _IPA_GLYPHS:
                if "IPA_GLYPH" not in classes:
                    classes.append("IPA_GLYPH")
                bad_count += 1
                continue
            if ch not in self.vocab_chars:
                cls_name = f"UNSUPPORTED_CAT_{unicodedata.category(ch)}"
                if cls_name not in classes:
                    classes.append(cls_name)
                bad_count += 1

        if bad_count > 0:
            return VocabularyCheck(
                model_revision=self.model_revision,
                capability_revision=self.capability_revision,
                tokenizer_profile=self.tokenizer_profile,
                status=VocabularyStatus.FAIL,
                real_vocab_available=self.real_vocab_available,
                vocab_sha256=self.vocab_sha256,
                vocab_size=len(self.vocab_chars),
                unsupported_classes=tuple(classes),
                unsupported_count=bad_count,
                reason_code="UNSUPPORTED_VOCAB",
            )

        return VocabularyCheck(
            model_revision=self.model_revision,
            capability_revision=self.capability_revision,
            tokenizer_profile=self.tokenizer_profile,
            status=VocabularyStatus.PASS,
            real_vocab_available=self.real_vocab_available,
            vocab_sha256=self.vocab_sha256,
            vocab_size=len(self.vocab_chars),
            reason_code="OK",
        )
