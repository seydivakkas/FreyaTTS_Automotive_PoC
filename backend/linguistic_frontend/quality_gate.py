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
import math

from backend.core.contracts.synthesis import PlanValidationStatus, SynthesisPlan
from backend.linguistic_frontend.config_adapter import PinnedFrontendSnapshot
from backend.linguistic_frontend.freya_adapter import FreyaVocabularyValidator, VocabularyCheck, VocabularyStatus
from backend.linguistic_frontend.protected_atoms import ProtectedAtom


@dataclass(frozen=True, slots=True)
class QualityGateResult:
    """Outcome of F4-A semantic preservation, vocabulary, and contract quality gate."""

    ok: bool
    reason_code: str = "OK"
    safe_message: str = ""
    vocab_checks: tuple[VocabularyCheck, ...] = ()
    vocab_rejections: int = 0


def validate_plan_quality(
    plan: SynthesisPlan,
    *,
    expected_source_text: str,
    atoms: tuple[ProtectedAtom, ...],
    pinned: PinnedFrontendSnapshot,
    vocab_validator: FreyaVocabularyValidator,
    require_real_vocab: bool = True,
) -> QualityGateResult:
    """Verify semantic preservation, single-pass invariant, M01/M03 alignment, and Freya vocab."""
    if not isinstance(plan, SynthesisPlan):
        return QualityGateResult(ok=False, reason_code="INVALID_PLAN_TYPE", safe_message="SynthesisPlan required")

    if plan.source_text != expected_source_text:
        return QualityGateResult(ok=False, reason_code="SOURCE_TEXT_MUTATED", safe_message="source_text must remain verbatim")

    if plan.normalization_passes != 1:
        return QualityGateResult(ok=False, reason_code="INVALID_PASS_COUNT", safe_message="normalization_passes must equal 1")

    if plan.validation_status != PlanValidationStatus.VALID:
        return QualityGateResult(ok=False, reason_code="PLAN_NOT_VALID", safe_message="Plan validation_status must be VALID")

    if plan.seed != pinned.seed or plan.voice_profile != pinned.voice_profile_id:
        return QualityGateResult(ok=False, reason_code="PROFILE_MISMATCH", safe_message="Plan voice profile or seed mismatch")

    if (
        plan.model_revision != pinned.model_revision
        or plan.lexicon_revision != pinned.lexicon_revision
        or plan.capability_revision != pinned.capability_revision
    ):
        return QualityGateResult(ok=False, reason_code="REVISION_MISMATCH", safe_message="Plan revision mismatch")

    if not plan.chunks:
        return QualityGateResult(ok=False, reason_code="NO_CHUNKS", safe_message="SynthesisPlan has no chunks")

    # Verify every critical top-level ProtectedAtom is mapped across chunks without loss or duplication
    seen_atom_counts: dict[str, int] = {}
    for chk in plan.chunks:
        if not chk.model_text or not chk.model_text.strip():
            return QualityGateResult(ok=False, reason_code="EMPTY_CHUNK", safe_message="Chunk model_text cannot be empty")
        if chk.source_span is not None:
            s0, s1 = chk.source_span
            if s0 < 0 or s1 < s0 or s1 > len(plan.source_text):
                return QualityGateResult(ok=False, reason_code="INVALID_MAPPING", safe_message="Chunk source_span out of bounds")
        if chk.post_pause_ms is not None and chk.post_pause_ms < 0:
            return QualityGateResult(ok=False, reason_code="INVALID_PAUSE", safe_message="Negative post_pause_ms rejected")
        if chk.requested_speed is not None and (
            isinstance(chk.requested_speed, bool)
            or not math.isfinite(chk.requested_speed)
            or chk.requested_speed <= 0.0
        ):
            return QualityGateResult(ok=False, reason_code="INVALID_SPEED", safe_message="Non-finite or non-positive speed rejected")
        for ref_id in chk.protected_entity_refs:
            seen_atom_counts[ref_id] = seen_atom_counts.get(ref_id, 0) + 1

    for atom in atoms:
        if atom.parent_atom_id is not None or not atom.critical:
            continue
        count = seen_atom_counts.get(atom.atom_id, 0)
        if count == 0:
            return QualityGateResult(
                ok=False,
                reason_code="MISSING_PROTECTED_ATOM",
                safe_message=f"Critical protected atom {atom.atom_id} missing from chunks",
            )
        if count > 1:
            return QualityGateResult(
                ok=False,
                reason_code="SPLIT_OR_DUPLICATED_ATOM",
                safe_message=f"Critical protected atom {atom.atom_id} split or duplicated across chunks",
            )

    checks: list[VocabularyCheck] = []
    rejections = 0
    for chk in plan.chunks:
        vc = vocab_validator.check_chunk(
            chk.model_text,
            expected_capability_revision=pinned.capability_revision,
            requested_controls=chk.requested_controls,
            require_real_vocab=require_real_vocab,
        )
        checks.append(vc)
        if vc.status != VocabularyStatus.PASS:
            rejections += 1

    if rejections > 0:
        first_fail = next(c for c in checks if c.status != VocabularyStatus.PASS)
        return QualityGateResult(
            ok=False,
            reason_code=first_fail.reason_code,
            safe_message="Chunk failed Freya vocabulary or capability validation",
            vocab_checks=tuple(checks),
            vocab_rejections=rejections,
        )

    return QualityGateResult(
        ok=True,
        reason_code="OK",
        vocab_checks=tuple(checks),
        vocab_rejections=0,
    )
