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
from typing import Any

from backend.core.contracts.synthesis import PlanValidationStatus, SynthesisPlan


class ProvenanceClass(StrEnum):
    """Explicit classification distinguishing F4-A strict plans from legacy strings."""

    STRICT_F4_PLAN = "STRICT_F4_PLAN"
    LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class LegacyPreparedPayload:
    """Explicitly classified legacy prepared text (never claims normalization_passes=1)."""

    text: str
    provenance: ProvenanceClass = ProvenanceClass.LEGACY_UNVERIFIED
    normalization_passes: int | None = None
    strict_coverage: bool = False


@dataclass(frozen=True, slots=True)
class PreparedPlanHandoff:
    """
    Trusted handoff seam for F5-A neural synthesis.

    Accepts ONLY a validated immutable M01 SynthesisPlan with normalization_passes == 1.
    Raw strings or dicts claiming 'already_normalized=True' are rejected.
    """

    plan: SynthesisPlan
    provenance: ProvenanceClass = ProvenanceClass.STRICT_F4_PLAN


def accept_prepared_plan(
    candidate: object,
    *,
    expected_model_revision: str | None = None,
    expected_capability_revision: str | None = None,
) -> PreparedPlanHandoff:
    """Validate and wrap an immutable F4-A SynthesisPlan for F5-A consumption."""
    if not isinstance(candidate, SynthesisPlan):
        raise TypeError("Strict F5 handoff requires an immutable M01 SynthesisPlan")
    if candidate.validation_status != PlanValidationStatus.VALID:
        raise ValueError("SynthesisPlan must have validation_status=VALID")
    if candidate.normalization_passes != 1:
        raise ValueError("SynthesisPlan must carry normalization_passes=1")
    if not candidate.chunks:
        raise ValueError("SynthesisPlan must contain at least one ChunkPlan")
    if expected_model_revision is not None and candidate.model_revision != expected_model_revision:
        raise ValueError("SynthesisPlan model_revision mismatch")
    if expected_capability_revision is not None and candidate.capability_revision != expected_capability_revision:
        raise ValueError("SynthesisPlan capability_revision mismatch")
    return PreparedPlanHandoff(plan=candidate, provenance=ProvenanceClass.STRICT_F4_PLAN)


def wrap_legacy_string(text: str) -> LegacyPreparedPayload:
    """Classify a legacy prepared string honestly without fabricating strict provenance."""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    return LegacyPreparedPayload(
        text=text,
        provenance=ProvenanceClass.LEGACY_UNVERIFIED,
        normalization_passes=None,
        strict_coverage=False,
    )


def legacy_normalize(text: str) -> dict[str, Any]:
    """Delegate to baseline backend.text.normalize preserving public API behavior."""
    from backend.text import normalize
    return normalize(text)


def legacy_clauses(text: str) -> list[tuple[str, float]]:
    """Delegate to baseline backend.text.clauses preserving public API behavior."""
    from backend.text import clauses
    return list(clauses(text))


def legacy_prepare_tts_clause(text: str) -> str:
    """Delegate to baseline backend.text.prepare_tts_clause preserving public API behavior."""
    from backend.text import prepare_tts_clause
    return prepare_tts_clause(text)
