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
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence

from backend.security.contracts import AccessContext, PrincipalKind

TURKISH_I = str.maketrans({"I": "ı", "İ": "i"})
_TOKEN_RE = re.compile(r"[a-zçğıöşü0-9]+(?:[.\-][a-zçğıöşü0-9]+)*", re.IGNORECASE)

DEFAULT_BM25_K1 = 1.2
DEFAULT_BM25_B = 0.75
DEFAULT_RRF_K = 60
DEFAULT_TOP_K_BRANCH = 20
DEFAULT_FINAL_K = 5
MAX_CANDIDATE_UNION = 40
MAX_CHUNK_TOKENS = 512


def tokenize_turkish(text: str) -> tuple[str, ...]:
    """
    Turkish-aware deterministic tokenizer preserving dotted/dotless I,
    hyphenated/dotted technical codes (P0300, ID.4, 1.6), and numeric units.
    """
    nfkc = unicodedata.normalize("NFKC", text).translate(TURKISH_I).lower()
    return tuple(_TOKEN_RE.findall(nfkc))


class AccessClass(StrEnum):
    """Corpus document access partition."""

    PUBLIC = "PUBLIC"
    WORKSHOP_INTERNAL = "WORKSHOP_INTERNAL"
    LICENSED_OEM = "LICENSED_OEM"


class ApplicabilityKind(StrEnum):
    """Document applicability scope."""

    GENERAL = "GENERAL"
    SPECIFIC = "SPECIFIC"


class SupportStatus(StrEnum):
    """Grounded claim support verdict."""

    SUPPORTED = "SUPPORTED"
    CONFLICT = "CONFLICT"
    INSUFFICIENT = "INSUFFICIENT"
    UNKNOWN = "UNKNOWN"


class AuthorityClass(IntEnum):
    """Approved source authority rank (higher = more authoritative)."""

    SUPPLEMENTAL_NOTE = 1
    WORKSHOP_POLICY = 2
    OEM_MANUAL = 3


@dataclass(frozen=True, slots=True)
class ApplicabilityScope:
    """Explicit applicability metadata; unknown fields never act as universal wildcards."""

    kind: ApplicabilityKind = ApplicabilityKind.GENERAL
    make: str | None = None
    model: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    engine: str | None = None
    language: str = "tr"

    def matches(self, *, make: str | None = None, model: str | None = None, year: int | None = None) -> bool:
        if self.kind == ApplicabilityKind.GENERAL:
            return True
        # SPECIFIC document requires explicit matching model (unknown vehicle cannot unlock specific docs).
        if self.model is not None:
            if not model or self.model.lower() != model.lower():
                return False
        if self.make is not None:
            if not make or self.make.lower() != make.lower():
                return False
        if self.year_min is not None or self.year_max is not None:
            if year is None:
                return False
            if self.year_min is not None and year < self.year_min:
                return False
            if self.year_max is not None and year > self.year_max:
                return False
        return True


@dataclass(frozen=True, slots=True)
class DocumentManifest:
    """Immutable provenance & trust manifest for an approved local document."""

    doc_id: str
    revision: str
    content_sha256: str
    byte_size: int
    media_type: str
    language: str
    publisher: str
    authority_class: AuthorityClass
    effective_date: str
    applicability: ApplicabilityScope
    access_class: AccessClass
    allowed_principal_kinds: frozenset[PrincipalKind] = frozenset({
        PrincipalKind.ANONYMOUS,
        PrincipalKind.CUSTOMER,
        PrincipalKind.OPERATOR,
        PrincipalKind.SYSTEM,
    })
    review_status: str = "APPROVED"
    supersedes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceAnchor:
    """Traceable non-PII source anchor (never exposes host file paths)."""

    doc_id: str
    revision: str
    content_sha256: str
    section: str
    page_index: int | None = None
    printed_page_label: str | None = None
    span_start: int = 0
    span_end: int = 0


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """Immutable bounded corpus chunk with pre-indexed ACL & applicability."""

    chunk_id: str
    doc_id: str
    revision: str
    text: str
    anchor: SourceAnchor
    applicability: ApplicabilityScope
    access_class: AccessClass
    allowed_principal_kinds: frozenset[PrincipalKind]
    authority_class: AuthorityClass
    effective_date: str
    supersedes: tuple[str, ...] = ()
    qualifiers: tuple[str, ...] = ()
    claim_key: str | None = None
    claim_value: str | None = None
    tokens: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        toks = self.tokens if self.tokens else tokenize_turkish(self.text)
        if len(toks) > MAX_CHUNK_TOKENS:
            raise ValueError(f"Chunk {self.chunk_id} exceeds max {MAX_CHUNK_TOKENS} tokens")
        object.__setattr__(self, "tokens", toks)


class EmbeddingProvider(Protocol):
    """Offline bounded embedding provider protocol (CPU-first or deterministic test fake)."""

    @property
    def revision(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_query(self, query: str) -> tuple[float, ...]: ...

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...


@dataclass(frozen=True, slots=True)
class IndexSnapshot:
    """Immutable pinned knowledge index snapshot."""

    snapshot_id: str
    corpus_digest: str
    chunks: tuple[KnowledgeChunk, ...]
    bm25_k1: float = DEFAULT_BM25_K1
    bm25_b: float = DEFAULT_BM25_B
    embedding_revision: str | None = None
    embedding_dimension: int = 0
    vectors: Mapping[str, tuple[float, ...]] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "vectors", MappingProxyType(dict(self.vectors)))


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """Single-branch candidate hit (rank/score only; never authorization or proof)."""

    chunk_id: str
    rank: int
    score: float
    branch: str


@dataclass(frozen=True, slots=True)
class FusedHit:
    """RRF-fused candidate hit with branch provenance."""

    chunk: KnowledgeChunk
    lexical_rank: int | None
    dense_rank: int | None
    rrf_score: float


@dataclass(frozen=True, slots=True)
class ClaimSupport:
    """Deterministic claim support & conflict verdict."""

    status: SupportStatus
    supported_anchors: tuple[SourceAnchor, ...]
    conflict_anchors: tuple[SourceAnchor, ...] = ()
    reason_code: str = ""


@dataclass(frozen=True, slots=True)
class KnowledgeAnswer:
    """Scoped grounded knowledge response (never holds tool execution authority)."""

    snapshot_id: str
    branch_mode: str  # "HYBRID_RRF" or "LEXICAL_ONLY"
    hits: tuple[FusedHit, ...]
    support: ClaimSupport
    answer_text: str
    abstained: bool
    has_authority: bool = False

    def __post_init__(self) -> None:
        if self.has_authority:
            raise ValueError("KnowledgeAnswer can never hold tool authority")


def _validate_unit_vector(vec: Sequence[float], expected_dim: int) -> tuple[float, ...]:
    if len(vec) != expected_dim or expected_dim <= 0:
        raise ValueError("Embedding dimension mismatch")
    vals = tuple(float(x) for x in vec)
    if any(not math.isfinite(x) for x in vals):
        raise ValueError("Embedding contains non-finite value")
    norm = math.sqrt(sum(x * x for x in vals))
    if norm <= 0.0:
        raise ValueError("Embedding vector has zero norm")
    return tuple(x / norm for x in vals)


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def build_index_snapshot(
    *,
    snapshot_id: str,
    manifests: Sequence[DocumentManifest],
    chunks: Sequence[KnowledgeChunk],
    embedding_provider: EmbeddingProvider | None = None,
) -> IndexSnapshot:
    """
    Validate document manifests + chunks and build an immutable IndexSnapshot.

    Rejects duplicate doc_id+revision with conflicting content hashes and
    enforces bounded chunk sizes.
    """
    manifest_map: dict[tuple[str, str], DocumentManifest] = {}
    for m in manifests:
        key = (m.doc_id, m.revision)
        existing = manifest_map.get(key)
        if existing is not None and existing.content_sha256 != m.content_sha256:
            raise ValueError(f"Conflicting content hash for {m.doc_id}@{m.revision}; quarantined")
        if m.review_status != "APPROVED":
            raise ValueError(f"Unapproved document {m.doc_id}@{m.revision} cannot be indexed")
        manifest_map[key] = m

    seen_chunks: set[str] = set()
    ordered_chunks: list[KnowledgeChunk] = []
    for c in chunks:
        if c.chunk_id in seen_chunks:
            raise ValueError(f"Duplicate chunk_id: {c.chunk_id}")
        key = (c.doc_id, c.revision)
        if key not in manifest_map:
            raise ValueError(f"Chunk {c.chunk_id} references unknown manifest {c.doc_id}@{c.revision}")
        if c.anchor.content_sha256 != manifest_map[key].content_sha256:
            raise ValueError(f"Chunk {c.chunk_id} anchor hash mismatch")
        seen_chunks.add(c.chunk_id)
        ordered_chunks.append(c)

    digest_hasher = hashlib.sha256()
    for c in sorted(ordered_chunks, key=lambda x: x.chunk_id):
        digest_hasher.update(f"{c.chunk_id}:{c.anchor.content_sha256}|".encode("utf-8"))

    vectors: dict[str, tuple[float, ...]] = {}
    emb_rev: str | None = None
    emb_dim = 0
    if embedding_provider is not None and ordered_chunks:
        emb_rev = embedding_provider.revision
        emb_dim = embedding_provider.dimension
        raw_vecs = embedding_provider.embed_documents([c.text for c in ordered_chunks])
        for c, v in zip(ordered_chunks, raw_vecs, strict=True):
            vectors[c.chunk_id] = _validate_unit_vector(v, emb_dim)

    return IndexSnapshot(
        snapshot_id=snapshot_id,
        corpus_digest=digest_hasher.hexdigest(),
        chunks=tuple(ordered_chunks),
        embedding_revision=emb_rev,
        embedding_dimension=emb_dim,
        vectors=vectors,
    )


def _is_chunk_eligible(
    chunk: KnowledgeChunk,
    *,
    access: AccessContext,
    vehicle_make: str | None,
    vehicle_model: str | None,
    vehicle_year: int | None,
) -> bool:
    if access.principal.kind not in chunk.allowed_principal_kinds:
        return False
    if chunk.access_class != AccessClass.PUBLIC and not access.principal.verified:
        return False
    return chunk.applicability.matches(make=vehicle_make, model=vehicle_model, year=vehicle_year)


def _bm25_rank(
    query_tokens: tuple[str, ...],
    eligible_chunks: Sequence[KnowledgeChunk],
    *,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
    top_k: int = DEFAULT_TOP_K_BRANCH,
) -> tuple[RetrievalHit, ...]:
    n_docs = len(eligible_chunks)
    if n_docs == 0 or not query_tokens:
        return ()

    doc_lens = [len(c.tokens) for c in eligible_chunks]
    avgdl = sum(doc_lens) / n_docs if n_docs > 0 else 0.0
    if avgdl <= 0.0:
        return ()

    q_terms = tuple(dict.fromkeys(query_tokens))
    df: dict[str, int] = {t: 0 for t in q_terms}
    tf_per_doc: list[Counter[str]] = []
    for c in eligible_chunks:
        counts = Counter(c.tokens)
        tf_per_doc.append(counts)
        for t in q_terms:
            if counts[t] > 0:
                df[t] += 1

    scored: list[tuple[float, str]] = []
    for c, dl, tf_map in zip(eligible_chunks, doc_lens, tf_per_doc, strict=True):
        if dl == 0:
            continue
        score = 0.0
        for t in q_terms:
            tf = tf_map[t]
            if tf <= 0:
                continue
            idf = math.log(1.0 + (n_docs - df[t] + 0.5) / (df[t] + 0.5))
            denom = tf + k1 * (1.0 - b + b * (dl / avgdl))
            if denom > 0.0:
                score += idf * (tf * (k1 + 1.0)) / denom
        if score > 0.0 and math.isfinite(score):
            scored.append((score, c.chunk_id))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(
        RetrievalHit(chunk_id=cid, rank=idx + 1, score=sc, branch="lexical")
        for idx, (sc, cid) in enumerate(scored[:top_k])
    )


def _dense_rank(
    query_text: str,
    eligible_chunks: Sequence[KnowledgeChunk],
    snapshot: IndexSnapshot,
    embedding_provider: EmbeddingProvider,
    *,
    top_k: int = DEFAULT_TOP_K_BRANCH,
) -> tuple[RetrievalHit, ...]:
    if not eligible_chunks or snapshot.embedding_revision != embedding_provider.revision:
        return ()
    q_vec = _validate_unit_vector(embedding_provider.embed_query(query_text), snapshot.embedding_dimension)
    scored: list[tuple[float, str]] = []
    for c in eligible_chunks:
        d_vec = snapshot.vectors.get(c.chunk_id)
        if d_vec is None:
            continue
        sim = _cosine_similarity(q_vec, d_vec)
        if math.isfinite(sim) and sim > 0.0:
            scored.append((sim, c.chunk_id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(
        RetrievalHit(chunk_id=cid, rank=idx + 1, score=sc, branch="dense")
        for idx, (sc, cid) in enumerate(scored[:top_k])
    )


def _resolve_support_and_conflicts(fused_hits: Sequence[FusedHit]) -> ClaimSupport:
    if not fused_hits:
        return ClaimSupport(
            status=SupportStatus.INSUFFICIENT,
            supported_anchors=(),
            reason_code="rag.zero_eligible_hits",
        )

    # Filter out superseded chunks when superseding doc is present in eligible hits.
    superseded_docs: set[str] = set()
    for h in fused_hits:
        superseded_docs.update(h.chunk.supersedes)

    active_hits = [h for h in fused_hits if h.chunk.doc_id not in superseded_docs]
    if not active_hits:
        active_hits = list(fused_hits)

    # Check material claim conflicts among active hits sharing a claim_key.
    by_claim: dict[str, list[FusedHit]] = {}
    for h in active_hits:
        if h.chunk.claim_key and h.chunk.claim_value is not None:
            by_claim.setdefault(h.chunk.claim_key, []).append(h)

    for claim_key, group in by_claim.items():
        distinct_vals = {h.chunk.claim_value for h in group}
        if len(distinct_vals) > 1:
            # Resolve by highest AuthorityClass first; if tied, abstain with CONFLICT.
            max_auth = max(int(h.chunk.authority_class) for h in group)
            top_auth_vals = {h.chunk.claim_value for h in group if int(h.chunk.authority_class) == max_auth}
            if len(top_auth_vals) > 1:
                return ClaimSupport(
                    status=SupportStatus.CONFLICT,
                    supported_anchors=(),
                    conflict_anchors=tuple(h.chunk.anchor for h in group),
                    reason_code=f"rag.material_conflict:{claim_key}",
                )

    return ClaimSupport(
        status=SupportStatus.SUPPORTED,
        supported_anchors=tuple(h.chunk.anchor for h in active_hits),
        reason_code="rag.supported",
    )


class OfflineRagRetriever:
    """
    Offline F3-C knowledge retriever with pre-ranking ACL + applicability filtering,
    deterministic BM25 + optional dense cosine RRF fusion, and conflict/abstention gate.
    """

    def __init__(
        self,
        *,
        snapshot: IndexSnapshot,
        embedding_provider: EmbeddingProvider | None = None,
        rrf_k: int = DEFAULT_RRF_K,
        top_k_branch: int = DEFAULT_TOP_K_BRANCH,
        final_k: int = DEFAULT_FINAL_K,
    ) -> None:
        self._snapshot = snapshot
        self._embedding_provider = embedding_provider
        self._rrf_k = rrf_k
        self._top_k_branch = top_k_branch
        self._final_k = final_k

    def retrieve(
        self,
        *,
        query_text: str,
        access: AccessContext,
        vehicle_make: str | None = None,
        vehicle_model: str | None = None,
        vehicle_year: int | None = None,
    ) -> KnowledgeAnswer:
        # 1. Pre-ranking ACL & applicability filter (never post-filter only!).
        eligible = [
            c
            for c in self._snapshot.chunks
            if _is_chunk_eligible(
                c,
                access=access,
                vehicle_make=vehicle_make,
                vehicle_model=vehicle_model,
                vehicle_year=vehicle_year,
            )
        ]

        if not eligible:
            return KnowledgeAnswer(
                snapshot_id=self._snapshot.snapshot_id,
                branch_mode="LEXICAL_ONLY" if self._embedding_provider is None else "HYBRID_RRF",
                hits=(),
                support=ClaimSupport(
                    status=SupportStatus.INSUFFICIENT,
                    supported_anchors=(),
                    reason_code="rag.no_eligible_documents",
                ),
                answer_text="Bu konuda aracınız ve yetki kapsamınız için doğrulanmış bir teknik kaynak bulunamadı.",
                abstained=True,
            )

        q_tokens = tokenize_turkish(query_text)
        lex_hits = _bm25_rank(
            q_tokens,
            eligible,
            k1=self._snapshot.bm25_k1,
            b=self._snapshot.bm25_b,
            top_k=self._top_k_branch,
        )

        dense_hits: tuple[RetrievalHit, ...] = ()
        branch_mode = "LEXICAL_ONLY"
        if self._embedding_provider is not None and self._snapshot.vectors:
            try:
                dense_hits = _dense_rank(
                    query_text,
                    eligible,
                    self._snapshot,
                    self._embedding_provider,
                    top_k=self._top_k_branch,
                )
                if dense_hits:
                    branch_mode = "HYBRID_RRF"
            except Exception:
                dense_hits = ()
                branch_mode = "LEXICAL_ONLY"

        # 2. Deterministic RRF fusion over unique eligible chunk IDs.
        chunk_by_id = {c.chunk_id: c for c in eligible}
        lex_rank_map = {h.chunk_id: h.rank for h in lex_hits}
        dense_rank_map = {h.chunk_id: h.rank for h in dense_hits}
        candidate_ids = sorted(set(lex_rank_map) | set(dense_rank_map))[:MAX_CANDIDATE_UNION]

        fused: list[FusedHit] = []
        for cid in candidate_ids:
            lr = lex_rank_map.get(cid)
            dr = dense_rank_map.get(cid)
            score = (1.0 / (self._rrf_k + lr) if lr is not None else 0.0) + (
                1.0 / (self._rrf_k + dr) if dr is not None else 0.0
            )
            fused.append(
                FusedHit(
                    chunk=chunk_by_id[cid],
                    lexical_rank=lr,
                    dense_rank=dr,
                    rrf_score=score,
                )
            )
        fused.sort(key=lambda f: (-f.rrf_score, -int(f.chunk.authority_class), f.chunk.chunk_id))
        top_fused = tuple(fused[: self._final_k])

        # 3. Conflict / abstention gate.
        support = _resolve_support_and_conflicts(top_fused)
        if support.status != SupportStatus.SUPPORTED:
            msg = (
                "Farklı kaynaklarda çelişkili teknik bilgi bulunduğu için kesin talimat veremiyorum; yetkili servis teknisyenine danışmanız önerilir."
                if support.status == SupportStatus.CONFLICT
                else "Bu soruya yanıt verebilecek doğrulanmış bir teknik kaynak bulunamadı."
            )
            return KnowledgeAnswer(
                snapshot_id=self._snapshot.snapshot_id,
                branch_mode=branch_mode,
                hits=top_fused,
                support=support,
                answer_text=msg,
                abstained=True,
            )

        lead = top_fused[0].chunk
        anchor = lead.anchor
        answer_text = f"{lead.text} (Kaynak: {anchor.doc_id} rev.{anchor.revision}, Bölüm {anchor.section})"
        return KnowledgeAnswer(
            snapshot_id=self._snapshot.snapshot_id,
            branch_mode=branch_mode,
            hits=top_fused,
            support=support,
            answer_text=answer_text,
            abstained=False,
        )
