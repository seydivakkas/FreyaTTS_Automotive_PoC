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

import hashlib
import math
from typing import Iterable

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, GenerationRef
from backend.core.contracts.synthesis import ChunkPlan, PlanValidationStatus, SynthesisPlan
from backend.linguistic_frontend.chunking_adapter import ChunkCandidate
from backend.linguistic_frontend.config_adapter import PinnedFrontendSnapshot


def make_plan_id(
    *,
    session_id: str,
    turn_id: int,
    generation_id: int,
    response_id: str,
    plan_revision: int,
) -> str:
    """Create a deterministic M01-safe plan_id distinct from generation_id."""
    digest = hashlib.sha256(
        f"{session_id}:{turn_id}:{generation_id}:{response_id}:{plan_revision}".encode("utf-8")
    ).hexdigest()[:12]
    return f"plan-{turn_id}-{generation_id}-{plan_revision}-{digest}"


def build_synthesis_plan(
    *,
    generation_ref: GenerationRef,
    response_id: str,
    plan_revision: int,
    source_text: str,
    normalized_text: str,
    speech_act: str,
    pinned: PinnedFrontendSnapshot,
    chunk_candidates: Iterable[ChunkCandidate],
    warnings: tuple[str, ...] = (),
    plan_id: str | None = None,
    validation_status: PlanValidationStatus = PlanValidationStatus.VALID,
) -> SynthesisPlan:
    """Build an immutable M01 SynthesisPlan with deeply frozen ChunkPlan tuples."""
    pid = plan_id or make_plan_id(
        session_id=generation_ref.session_id,
        turn_id=generation_ref.turn_id,
        generation_id=generation_ref.generation_id,
        response_id=response_id,
        plan_revision=plan_revision,
    )
    chunk_plans: list[ChunkPlan] = []
    for cand in chunk_candidates:
        if cand.post_pause_ms is not None and cand.post_pause_ms < 0:
            raise ValueError("post_pause_ms cannot be negative")
        if cand.requested_speed is not None and (
            isinstance(cand.requested_speed, bool)
            or not math.isfinite(cand.requested_speed)
            or cand.requested_speed <= 0.0
        ):
            raise ValueError("requested_speed must be finite positive")
        chunk_plans.append(
            ChunkPlan(
                chunk_id=f"{pid}:chk-{cand.chunk_index}",
                chunk_index=cand.chunk_index,
                model_text=cand.model_text,
                source_span=cand.source_span,
                protected_entity_refs=cand.protected_entity_refs,
                requested_speed=cand.requested_speed,
                requested_emphasis=cand.requested_emphasis,
                post_pause_ms=cand.post_pause_ms,
                requested_controls=cand.requested_controls,
            )
        )

    return SynthesisPlan(
        schema_version=CONTRACT_SCHEMA_VERSION,
        generation_ref=generation_ref,
        plan_id=pid,
        plan_revision=plan_revision,
        response_id=response_id,
        source_text=source_text,
        normalized_text=normalized_text,
        language=pinned.language,
        voice_profile=pinned.voice_profile_id,
        seed=pinned.seed,
        chunks=tuple(chunk_plans),
        model_revision=pinned.model_revision,
        lexicon_revision=pinned.lexicon_revision,
        capability_revision=pinned.capability_revision,
        normalization_passes=1,
        speech_act=speech_act,
        validation_status=validation_status,
        warnings=warnings,
    )
