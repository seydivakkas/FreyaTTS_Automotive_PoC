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

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from backend.core.contracts.recognition import CatalogStatus, EntityCandidate
from backend.core.contracts.validation import freeze_value, require_finite, require_safe_id, require_strict_int
from backend.shared_lexicon.contracts import LookupResult, make_safe_id
from backend.shared_lexicon.registry import LexiconRegistry


@dataclass(frozen=True, slots=True)
class CatalogItemRef:
    """Read-only opaque reference to a catalog vehicle or service item."""

    catalog_ref_id: str
    brand: str | None = None
    model: str | None = None
    display_label: str = ""
    canonical_entity_ids: tuple[str, ...] = ()
    opaque_payload: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        require_safe_id(self.catalog_ref_id, "catalog_ref_id")
        if not isinstance(self.display_label, str):
            raise TypeError("display_label must be str")
        object.__setattr__(
            self,
            "canonical_entity_ids",
            freeze_value(tuple(dict.fromkeys(str(eid) for eid in self.canonical_entity_ids if str(eid).strip()))),
        )
        object.__setattr__(self, "opaque_payload", freeze_value(dict(self.opaque_payload)))


@dataclass(frozen=True, slots=True)
class CatalogMatchRef:
    """Read-only match reference linking a catalog item to matched lexicon entity IDs."""

    item_ref: CatalogItemRef
    matched_entity_ids: tuple[str, ...]
    score: float
    lexicon_revision: str
    catalog_status: CatalogStatus = CatalogStatus.UNVERIFIED

    def __post_init__(self) -> None:
        if not isinstance(self.item_ref, CatalogItemRef):
            raise TypeError("item_ref must be CatalogItemRef")
        require_finite(self.score, "score", minimum=0.0, maximum=1.0)
        if not isinstance(self.catalog_status, CatalogStatus):
            raise ValueError("catalog_status must be CatalogStatus")
        object.__setattr__(
            self,
            "matched_entity_ids",
            freeze_value(tuple(dict.fromkeys(str(e) for e in self.matched_entity_ids))),
        )


@dataclass(frozen=True, slots=True)
class CatalogResolution:
    """Bounded read-only catalog resolution result without silent winner on ambiguity."""

    candidates: tuple[CatalogMatchRef, ...]
    selected_ref: CatalogItemRef | None
    ambiguous: bool
    bounded_limit: int
    lexicon_revision: str

    def __post_init__(self) -> None:
        require_strict_int(self.bounded_limit, "bounded_limit", minimum=1, maximum=100)
        cands = tuple(self.candidates)
        if len(cands) > self.bounded_limit:
            raise ValueError("CatalogResolution candidates exceed bounded_limit")
        if self.ambiguous and self.selected_ref is not None:
            raise ValueError("Ambiguous CatalogResolution must not set selected_ref")
        object.__setattr__(self, "candidates", freeze_value(cands))


@runtime_checkable
class CatalogReader(Protocol):
    """Read-only opaque seam protocol between M05 lexicon and external catalog stores."""

    def list_refs(self) -> tuple[CatalogItemRef, ...]: ...

    def find_by_entity_id(self, entity_id: str) -> tuple[CatalogItemRef, ...]: ...


def _collect_item_entity_ids(
    *,
    registry: LexiconRegistry,
    brand: str | None,
    model: str | None,
    desc: str,
) -> tuple[str, ...]:
    ids: list[str] = []
    for text in (desc, brand or "", model or ""):
        if text.strip():
            for cand in registry.lookup_text(text, max_candidates=5).candidates:
                if cand.entity_id not in ids:
                    ids.append(cand.entity_id)
    return tuple(ids)


def _coerce_catalog_ref(item: Any, registry: LexiconRegistry) -> CatalogItemRef:
    if isinstance(item, CatalogItemRef):
        if item.canonical_entity_ids or not (item.display_label or item.brand or item.model):
            return item
        eids = _collect_item_entity_ids(
            registry=registry,
            brand=item.brand,
            model=item.model,
            desc=item.display_label,
        )
        return CatalogItemRef(
            catalog_ref_id=item.catalog_ref_id,
            brand=item.brand,
            model=item.model,
            display_label=item.display_label,
            canonical_entity_ids=eids,
            opaque_payload=item.opaque_payload,
        )

    if isinstance(item, Mapping):
        raw_id = item.get("catalog_ref_id") or item.get("id") or item.get("ref_id") or ""
        brand = item.get("brand")
        model = item.get("model")
        desc = str(item.get("display_label") or item.get("description") or f"{brand or ''} {model or ''}".strip())
        ref_id = make_safe_id("cat", str(raw_id) if str(raw_id).strip() else desc)
        explicit_eids = tuple(item.get("canonical_entity_ids") or ())
        if not explicit_eids:
            explicit_eids = _collect_item_entity_ids(
                registry=registry,
                brand=str(brand) if brand else None,
                model=str(model) if model else None,
                desc=desc,
            )
        opaque = {k: v for k, v in item.items() if k not in {"catalog_ref_id", "id", "ref_id", "brand", "model", "display_label", "description", "canonical_entity_ids"}}
        return CatalogItemRef(
            catalog_ref_id=ref_id,
            brand=str(brand) if brand else None,
            model=str(model) if model else None,
            display_label=desc,
            canonical_entity_ids=explicit_eids,
            opaque_payload=opaque,
        )

    raw_id = getattr(item, "catalog_ref_id", None) or getattr(item, "id", None) or ""
    brand = getattr(item, "brand", None)
    model = getattr(item, "model", None)
    desc = str(getattr(item, "display_label", None) or getattr(item, "description", None) or f"{brand or ''} {model or ''}".strip())
    ref_id = make_safe_id("cat", str(raw_id) if str(raw_id).strip() else desc)
    eids = _collect_item_entity_ids(
        registry=registry,
        brand=str(brand) if brand else None,
        model=str(model) if model else None,
        desc=desc,
    )
    return CatalogItemRef(
        catalog_ref_id=ref_id,
        brand=str(brand) if brand else None,
        model=str(model) if model else None,
        display_label=desc,
        canonical_entity_ids=eids,
    )


class InMemoryCatalogSeam:
    """Read-only opaque catalog adapter that never accesses DB or mutates source records."""

    def __init__(self, items: Iterable[Any], registry: LexiconRegistry) -> None:
        self._registry = registry
        refs = tuple(_coerce_catalog_ref(item, registry) for item in items)
        self._refs: tuple[CatalogItemRef, ...] = tuple(sorted(refs, key=lambda r: r.catalog_ref_id))
        by_eid: dict[str, list[CatalogItemRef]] = {}
        for ref in self._refs:
            for eid in ref.canonical_entity_ids:
                by_eid.setdefault(eid, []).append(ref)
        self._by_entity_id: dict[str, tuple[CatalogItemRef, ...]] = {
            eid: tuple(lst) for eid, lst in by_eid.items()
        }

    def list_refs(self) -> tuple[CatalogItemRef, ...]:
        return self._refs

    def find_by_entity_id(self, entity_id: str) -> tuple[CatalogItemRef, ...]:
        return self._by_entity_id.get(entity_id, ())

    def resolve_lookup_to_refs(
        self,
        lookup_result: LookupResult,
        *,
        max_results: int = 5,
    ) -> CatalogResolution:
        require_strict_int(max_results, "max_results", minimum=1, maximum=100)
        target_ids = tuple(dict.fromkeys(c.entity_id for c in lookup_result.candidates))
        return _resolve_entity_ids(
            seam=self,
            entity_ids=target_ids,
            lexicon_revision=self._registry.lexicon_revision,
            force_ambiguous=lookup_result.ambiguous,
            max_results=max_results,
        )

    def resolve_candidates_to_refs(
        self,
        candidates: Sequence[EntityCandidate],
        *,
        max_results: int = 5,
    ) -> CatalogResolution:
        require_strict_int(max_results, "max_results", minimum=1, maximum=100)
        target_ids = tuple(
            dict.fromkeys(
                c.entity_id
                for c in candidates
                if c.canonical_value is not None and not c.entity_id.startswith("ambig:")
            )
        )
        has_ambiguous = any(c.canonical_value is None or bool(c.alternatives) for c in candidates)
        return _resolve_entity_ids(
            seam=self,
            entity_ids=target_ids,
            lexicon_revision=self._registry.lexicon_revision,
            force_ambiguous=has_ambiguous,
            max_results=max_results,
        )


def _resolve_entity_ids(
    *,
    seam: CatalogReader,
    entity_ids: tuple[str, ...],
    lexicon_revision: str,
    force_ambiguous: bool,
    max_results: int,
) -> CatalogResolution:
    if not entity_ids:
        return CatalogResolution(
            candidates=(),
            selected_ref=None,
            ambiguous=force_ambiguous,
            bounded_limit=max_results,
            lexicon_revision=lexicon_revision,
        )

    target_set = set(entity_ids)
    scored: list[CatalogMatchRef] = []
    seen_refs: set[str] = set()
    for eid in entity_ids:
        for ref in seam.find_by_entity_id(eid):
            if ref.catalog_ref_id in seen_refs:
                continue
            seen_refs.add(ref.catalog_ref_id)
            overlap = tuple(e for e in ref.canonical_entity_ids if e in target_set)
            score = min(1.0, len(overlap) / max(1, len(target_set)))
            scored.append(
                CatalogMatchRef(
                    item_ref=ref,
                    matched_entity_ids=overlap,
                    score=score,
                    lexicon_revision=lexicon_revision,
                    catalog_status=CatalogStatus.UNVERIFIED,
                )
            )

    scored.sort(key=lambda m: (-m.score, m.item_ref.catalog_ref_id))
    bounded = tuple(scored[:max_results])
    top_score = bounded[0].score if bounded else 0.0
    top_count = sum(1 for m in bounded if m.score == top_score)
    is_ambiguous = force_ambiguous or top_count > 1
    selected = bounded[0].item_ref if (bounded and not is_ambiguous) else None
    return CatalogResolution(
        candidates=bounded,
        selected_ref=selected,
        ambiguous=is_ambiguous,
        bounded_limit=max_results,
        lexicon_revision=lexicon_revision,
    )
