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
import unicodedata

from backend.voice_activity.semantic_contracts import (
    ContinuationCue,
    ExpectedSlotCategory,
    ExpectedSlotProjection,
)

MAX_INSPECTED_CHARS = 512
MAX_INSPECTED_TOKENS = 64

_EXPLICIT_INTERRUPT_PHRASES: tuple[str, ...] = (
    "bir dakika",
    "dur",
    "durun",
    "operatöre bağla",
    "müşteri temsilcisi",
    "bekle",
)

_NEGATION_CORRECTION_TOKENS: frozenset[str] = frozenset({
    "değil",
    "hayır",
    "yok",
    "daha doğrusu",
    "yanlış",
})

_CONTINUATION_TRAILING_TOKENS: frozenset[str] = frozenset({
    "ve",
    "ama",
    "fakat",
    "lakin",
    "çünkü",
    "eğer",
    "yani",
    "bir de",
    "ayrıca",
    "sonra",
})

_BACKCHANNEL_TOKENS: frozenset[str] = frozenset({
    "hı hı",
    "hıhı",
    "anlıyorum",
    "anladım",
    "tamam",
    "olur",
    "evet",
    "peki",
})

_DANGLING_TIME_RE = re.compile(r"(?:saat\s+(?:on\s+dört|on\s+beş|\d{1,2}))$")
_PARTIAL_DIGITS_RE = re.compile(r"(?:\b0?5\d{2,6}|\b\d{2}\s*[a-zçğıöşü]{1,3})$")


def turkish_casefold(text: str) -> str:
    """Turkish-aware casefolding (İ->i, I->ı) without mutating caller's transcript."""
    normalized = unicodedata.normalize("NFC", text)
    mapped = normalized.replace("İ", "i").replace("I", "ı")
    return mapped.lower()


def classify_turkish_cues(
    provisional_text: str | None,
    *,
    context: ExpectedSlotProjection | None = None,
) -> ContinuationCue:
    """
    Deterministic, bounded CPU classifier for Turkish continuation/backchannel cues.
    Never treats provisional text as business approval or customer fact.
    """
    if not provisional_text or not isinstance(provisional_text, str):
        return ContinuationCue.UNKNOWN

    bounded = provisional_text[:MAX_INSPECTED_CHARS]
    folded = turkish_casefold(bounded).strip()
    if not folded:
        return ContinuationCue.UNKNOWN

    # Strip trailing punctuation only for cue matching; never mutate raw transcript.
    cleaned = re.sub(r"[^\w\sçğıöşü]", " ", folded)
    tokens = [t for t in cleaned.split() if t][:MAX_INSPECTED_TOKENS]
    if not tokens:
        return ContinuationCue.UNKNOWN

    joined = " ".join(tokens)

    # 1. Explicit interrupt phrases take priority over backchannel tokens.
    for phrase in _EXPLICIT_INTERRUPT_PHRASES:
        if phrase in joined:
            return ContinuationCue.EXPLICIT_INTERRUPT_CUE

    # Repeated or contrastive backchannel forms are NOT simple backchannels.
    if joined in {"tamam tamam", "evet ama", "hı hı hayır", "evet değil"}:
        return ContinuationCue.CORRECTION_OR_NEGATION

    last_tok = tokens[-1]
    last_two = " ".join(tokens[-2:]) if len(tokens) >= 2 else ""

    # 2. Negation / correction tokens.
    if last_tok in _NEGATION_CORRECTION_TOKENS or last_two in _NEGATION_CORRECTION_TOKENS or "ama" in tokens[:-1]:
        return ContinuationCue.CORRECTION_OR_NEGATION

    # 3. Trailing continuation conjunctions.
    if last_tok in _CONTINUATION_TRAILING_TOKENS or last_two in _CONTINUATION_TRAILING_TOKENS:
        return ContinuationCue.POSSIBLE_CONTINUATION

    # 4. Incomplete expected slot patterns (time, phone, plate).
    expected = context.expected_slot if context is not None else ExpectedSlotCategory.NONE
    if expected in (ExpectedSlotCategory.DATE_TIME, ExpectedSlotCategory.PHONE_PLATE):
        if _DANGLING_TIME_RE.search(joined) or _PARTIAL_DIGITS_RE.search(joined):
            return ContinuationCue.INCOMPLETE_EXPECTED_SLOT

    # 5. Backchannel vs meaningful short confirmation.
    if joined in _BACKCHANNEL_TOKENS or (len(tokens) == 1 and last_tok in _BACKCHANNEL_TOKENS):
        if context is not None and (
            context.confirmation_pending or context.expected_slot == ExpectedSlotCategory.SHORT_CONFIRMATION
        ):
            return ContinuationCue.POSSIBLE_COMPLETION
        return ContinuationCue.BACKCHANNEL_CANDIDATE

    return ContinuationCue.UNKNOWN
