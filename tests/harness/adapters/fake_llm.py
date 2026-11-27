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
from dataclasses import dataclass
from typing import Any

from backend.observability.evidence import EvidenceKind


@dataclass(frozen=True, slots=True)
class UntrustedLLMProposal:
    valid: bool
    intent: str
    speech_text: str
    proposed_tool: str | None = None
    claimed_role: str | None = None
    error_code: str | None = None
    has_authority: bool = False
    source_class: EvidenceKind = EvidenceKind.MOCK_RUNTIME


class FakeLLMAdapter:
    """Mock LLM returning untrusted proposals; never grants permissions or executes tools."""

    source_class: EvidenceKind = EvidenceKind.MOCK_RUNTIME

    def __init__(self, *, supported_intents: frozenset[str] | None = None) -> None:
        self.supported_intents = supported_intents or frozenset({
            "greeting",
            "availability_check",
            "booking_create",
            "booking_cancel",
            "booking_reschedule",
            "clarify",
        })
        self.invocation_count = 0
        self.executed_side_effects: list[str] = []

    def parse_proposal(self, raw_json: str) -> UntrustedLLMProposal:
        self.invocation_count += 1
        try:
            data: Any = json.loads(raw_json)
        except json.JSONDecodeError:
            return UntrustedLLMProposal(
                valid=False,
                intent="invalid",
                speech_text="",
                error_code="MALFORMED_LLM_JSON",
                has_authority=False,
            )
        if not isinstance(data, dict) or "intent" not in data:
            return UntrustedLLMProposal(
                valid=False,
                intent="invalid",
                speech_text="",
                error_code="MISSING_INTENT",
                has_authority=False,
            )
        intent = str(data["intent"])
        if intent not in self.supported_intents:
            return UntrustedLLMProposal(
                valid=False,
                intent=intent,
                speech_text="",
                error_code="UNSUPPORTED_INTENT",
                has_authority=False,
            )
        # Untrusted text claims (administrator/tool injection) NEVER gain authority.
        return UntrustedLLMProposal(
            valid=True,
            intent=intent,
            speech_text=str(data.get("speech_text", "")),
            proposed_tool=str(data["proposed_tool"]) if data.get("proposed_tool") is not None else None,
            claimed_role=str(data["claimed_role"]) if data.get("claimed_role") is not None else None,
            has_authority=False,
        )
