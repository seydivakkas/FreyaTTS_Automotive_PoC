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

# ADR-X-03: Canonical AI disclosure texts (governed by M03 configuration)
AI_DISCLOSURE_GREETING = "Merhaba, Freya yapay zekâ destekli müşteri temsilcisine ulaştınız."
AI_DISCLOSURE_INTERRUPTED_FOLLOWUP = "Ben Freya, yapay zekâ destekli asistanım."
AI_DISCLOSURE_HUMAN_QUESTION_REPLY = (
    "Ben Freya, yapay zekâ destekli asistanım. İsterseniz sizi canlı müşteri temsilcisine aktarabilirim."
)

# ADR-F3-02: CPU-only embedding policy
EMBEDDING_MODEL_ID = "bge-m3"
EMBEDDING_DEVICE = "cpu"


@dataclass(frozen=True, slots=True)
class EmbeddingPolicy:
    model_id: str = EMBEDDING_MODEL_ID
    device: str = EMBEDDING_DEVICE
    allow_gpu: bool = False


DEFAULT_EMBEDDING_POLICY = EmbeddingPolicy()


class AIDisclosureTracker:
    """Tracks per-call AI disclosure completion across barge-in per ADR-X-03."""

    def __init__(
        self,
        *,
        greeting_text: str = AI_DISCLOSURE_GREETING,
        followup_text: str = AI_DISCLOSURE_INTERRUPTED_FOLLOWUP,
    ) -> None:
        self._greeting_text = greeting_text
        self._followup_text = followup_text
        self._greeting_delivered = False
        self._followup_delivered = False

    @property
    def is_disclosed(self) -> bool:
        return self._greeting_delivered or self._followup_delivered

    def build_greeting_text(self, body: str = "") -> str:
        if not body.strip():
            return self._greeting_text
        return f"{self._greeting_text} {body.strip()}"

    def mark_greeting_completed(self) -> None:
        self._greeting_delivered = True

    def mark_greeting_interrupted(self) -> None:
        """Record barge-in before disclosure completed; next turn must repeat short form."""
        self._greeting_delivered = False

    def wrap_next_reply(self, reply_text: str) -> str:
        """Ensure disclosure is completed even if initial greeting was interrupted."""
        if self.is_disclosed:
            return reply_text
        self._followup_delivered = True
        if not reply_text.strip():
            return self._followup_text
        return f"{self._followup_text} {reply_text.strip()}"

    @staticmethod
    def answer_human_inquiry() -> str:
        return AI_DISCLOSURE_HUMAN_QUESTION_REPLY


__all__ = [
    "AI_DISCLOSURE_GREETING",
    "AI_DISCLOSURE_HUMAN_QUESTION_REPLY",
    "AI_DISCLOSURE_INTERRUPTED_FOLLOWUP",
    "AIDisclosureTracker",
    "DEFAULT_EMBEDDING_POLICY",
    "EMBEDDING_DEVICE",
    "EMBEDDING_MODEL_ID",
    "EmbeddingPolicy",
]
