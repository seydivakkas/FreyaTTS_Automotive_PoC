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
from typing import Callable, Sequence

from backend.core.contracts.recognition import CatalogStatus, ConfirmationStatus, EntityCandidate
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.observability.projection import contains_sentinel
from backend.shared_lexicon.asr_adapter import extract_asr_candidates
from backend.shared_lexicon.contracts import LookupResult
from backend.shared_lexicon.registry import LexiconRegistry
from backend.speech_recognition.config_adapter import LEGACY_HOTWORDS_CAP, LEGACY_HOTWORDS_TTL_SEC
from backend.speech_recognition.errors import ASRConfigError


@dataclass(frozen=True, slots=True)
class PinnedLexiconSnapshot:
    """Immutable M05 LexiconRegistry handle captured at utterance admission."""

    registry: LexiconRegistry | None
    lexicon_revision: str | None
    available: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class HotwordSelection:
    """Bounded, PII-scrubbed legacy-compatible hotword list pinned at admission."""

    terms: tuple[str, ...]
    hotwords_text: str | None
    from_cache: bool
    filtered_pii_count: int


@dataclass(frozen=True, slots=True)
class LexiconCandidateBundle:
    """Conservative M05 exact/approved-alias EntityCandidates attached to ASRResult."""

    candidates: tuple[EntityCandidate, ...]
    lookup_result: LookupResult | None
    lexicon_revision: str | None
    snapshot_available: bool
    unavailable_reason: str | None = None


class LegacyHotwordCache:
    """Preserves legacy 50-item / 60s TTL catalog hotword caching without PII leakage."""

    def __init__(
        self,
        *,
        ttl_sec: float = LEGACY_HOTWORDS_TTL_SEC,
        cap: int = LEGACY_HOTWORDS_CAP,
        clock: Clock | None = None,
    ) -> None:
        self._ttl_sec = ttl_sec
        self._cap = cap
        self._clock: Clock = clock or SystemMonotonicClock()
        self._cached: tuple[int, tuple[str, ...]] | None = None

    def invalidate(self) -> None:
        self._cached = None

    def select(
        self,
        *,
        catalog_enabled: bool,
        catalog_provider: Callable[[int], Sequence[str]] | None = None,
        custom_hotwords: Sequence[str] = (),
    ) -> HotwordSelection:
        return build_legacy_hotwords(
            catalog_enabled=catalog_enabled,
            catalog_provider=catalog_provider,
            custom_hotwords=custom_hotwords,
            cap=self._cap,
            ttl_sec=self._ttl_sec,
            cache=self,
        )


def _is_safe_hotword(term: str) -> bool:
    if not isinstance(term, str):
        return False
    cleaned = term.strip()
    if not cleaned:
        return False
    if contains_sentinel(cleaned):
        return False
    return True


def build_legacy_hotwords(
    *,
    catalog_enabled: bool,
    catalog_provider: Callable[[int], Sequence[str]] | None = None,
    custom_hotwords: Sequence[str] = (),
    cap: int = LEGACY_HOTWORDS_CAP,
    ttl_sec: float = LEGACY_HOTWORDS_TTL_SEC,
    cache: LegacyHotwordCache | None = None,
) -> HotwordSelection:
    """
    Preserve `backend/models.py` hotword list ordering, deduplication, 50-item cap,
    and 60s TTL cache semantics while strictly blocking PII sentinels from global hotwords.
    """
    catalog_terms: tuple[str, ...] = ()
    from_cache = False
    filtered_pii = 0

    if catalog_enabled:
        now_ns = cache._clock.monotonic_ns() if cache is not None else 0
        ttl_ns = int(ttl_sec * 1_000_000_000)
        if cache is not None and cache._cached is not None and (now_ns - cache._cached[0]) < ttl_ns:
            catalog_terms = cache._cached[1]
            from_cache = True
        elif catalog_provider is not None:
            raw_items = list(catalog_provider(cap))[:cap]
            safe_cat: list[str] = []
            for item in raw_items:
                if _is_safe_hotword(item):
                    safe_cat.append(item.strip())
                else:
                    filtered_pii += 1
            catalog_terms = tuple(dict.fromkeys(safe_cat))[:cap]
            if cache is not None:
                cache._cached = (now_ns, catalog_terms)

    safe_custom: list[str] = []
    for item in custom_hotwords:
        if _is_safe_hotword(item):
            safe_custom.append(item.strip())
        else:
            filtered_pii += 1

    combined = tuple(dict.fromkeys([*catalog_terms, *safe_custom]))
    hotwords_text = ", ".join(combined) if combined else None
    return HotwordSelection(
        terms=combined,
        hotwords_text=hotwords_text,
        from_cache=from_cache,
        filtered_pii_count=filtered_pii,
    )


def pin_lexicon_snapshot(
    registry: LexiconRegistry | None,
    *,
    strict_required: bool = False,
) -> PinnedLexiconSnapshot:
    """Capture an immutable M05 LexiconRegistry snapshot at utterance admission."""
    if registry is None:
        if strict_required:
            raise ASRConfigError(
                "ASR_LEXICON_UNAVAILABLE",
                "M05 LexiconRegistry snapshot required by strict policy is unavailable",
                field_name="lexicon_registry",
            )
        return PinnedLexiconSnapshot(
            registry=None,
            lexicon_revision=None,
            available=False,
            unavailable_reason="lexicon_snapshot_unavailable",
        )
    if not isinstance(registry, LexiconRegistry):
        raise ASRConfigError(
            "ASR_INVALID_LEXICON_REGISTRY",
            "registry must be M05 LexiconRegistry",
            field_name="lexicon_registry",
        )
    return PinnedLexiconSnapshot(
        registry=registry,
        lexicon_revision=registry.lexicon_revision,
        available=True,
        unavailable_reason=None,
    )


def extract_conservative_candidates(
    pinned: PinnedLexiconSnapshot,
    raw_transcript: str,
    *,
    max_candidates: int = 5,
    strict_required: bool = False,
) -> LexiconCandidateBundle:
    """
    Extract exact/approved-alias M05 EntityCandidates against the pinned lexicon snapshot.

    - Never enables fuzzy/phonetic rewriting (`allow_fuzzy=False`).
    - Strictly enforces `CatalogStatus.UNVERIFIED` and `ConfirmationStatus.CANDIDATE`.
    - Fails closed if `strict_required=True` and snapshot is unavailable.
    """
    if not pinned.available or pinned.registry is None:
        if strict_required:
            raise ASRConfigError(
                "ASR_LEXICON_UNAVAILABLE",
                pinned.unavailable_reason or "M05 LexiconRegistry snapshot unavailable",
                field_name="lexicon_registry",
            )
        return LexiconCandidateBundle(
            candidates=(),
            lookup_result=None,
            lexicon_revision=None,
            snapshot_available=False,
            unavailable_reason=pinned.unavailable_reason or "lexicon_snapshot_unavailable",
        )

    if not raw_transcript.strip():
        return LexiconCandidateBundle(
            candidates=(),
            lookup_result=None,
            lexicon_revision=pinned.lexicon_revision,
            snapshot_available=True,
        )

    extraction = extract_asr_candidates(
        pinned.registry,
        raw_transcript,
        max_candidates=max_candidates,
        allow_fuzzy=False,
    )

    verified_candidates: list[EntityCandidate] = []
    for cand in extraction.candidates:
        if cand.catalog_status != CatalogStatus.UNVERIFIED or cand.confirmation_status != ConfirmationStatus.CANDIDATE:
            raise AssertionError("M05 adapter violated conservative candidate status invariant")
        verified_candidates.append(cand)

    return LexiconCandidateBundle(
        candidates=tuple(verified_candidates),
        lookup_result=extraction.lookup_result,
        lexicon_revision=extraction.lexicon_revision,
        snapshot_available=True,
    )
