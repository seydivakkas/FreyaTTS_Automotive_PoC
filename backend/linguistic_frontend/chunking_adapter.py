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
import re

from backend.linguistic_frontend.protected_atoms import ProtectedAtom
from backend.linguistic_frontend.text_mapping import TextMapping


_PAUSE_MS_MAP = {
    "?": 320,
    ".": 280,
    "!": 280,
    ";": 200,
    ":": 200,
    ",": 140,
}
_DEFAULT_PAUSE_MS = 80
_SHORT_CLAUSE_MAX_CHARS = 15

_TR_CAP_MAP = {"i": "İ", "ı": "I", "ü": "Ü", "ş": "Ş", "ö": "Ö", "ç": "Ç", "ğ": "ğ"}


@dataclass(frozen=True, slots=True)
class ChunkCandidate:
    """Single non-empty chunk candidate with exact source span and protected entity refs."""

    chunk_index: int
    model_text: str
    norm_span: tuple[int, int]
    source_span: tuple[int, int]
    protected_entity_refs: tuple[str, ...]
    post_pause_ms: int | None
    requested_speed: float | None = None
    requested_emphasis: tuple[str, ...] = ()
    requested_controls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    ok: bool
    chunks: tuple[ChunkCandidate, ...] = ()
    reason_code: str = "OK"
    safe_message: str = ""


def _turkish_capitalize(text: str) -> str:
    s = text.strip()
    if not s:
        return s
    first = _TR_CAP_MAP.get(s[0], s[0].upper())
    return first + s[1:]


def _prepare_clause_text(text: str) -> str:
    s = text.strip()
    if not s:
        return s
    cap = _turkish_capitalize(s)
    if cap[-1] not in ".?!,:;":
        cap += "."
    return cap


def _atoms_in_span(atoms: tuple[ProtectedAtom, ...], start: int, end: int) -> tuple[ProtectedAtom, ...]:
    res: list[ProtectedAtom] = []
    for a in atoms:
        if a.parent_atom_id is not None or a.normalized_span is None:
            continue
        ns0, ns1 = a.normalized_span
        if ns0 < end and start < ns1:
            res.append(a)
    return tuple(res)


def _split_segment_preserving_atoms(
    norm_text: str,
    seg_start: int,
    seg_end: int,
    atoms: tuple[ProtectedAtom, ...],
    *,
    max_chunk_chars: int,
    max_chunk_words: int,
) -> tuple[list[tuple[int, int]], str | None]:
    """
    Split [seg_start, seg_end) into sub-spans without ever splitting inside a
    ProtectedAtom's normalized_span.
    """
    seg_str = norm_text[seg_start:seg_end].strip()
    if not seg_str:
        return [], None

    # Check if any single protected atom alone exceeds max_chunk_chars (even accounting for '.' suffix)
    for atom in _atoms_in_span(atoms, seg_start, seg_end):
        assert atom.normalized_span is not None
        atom_len = atom.normalized_span[1] - atom.normalized_span[0]
        if atom_len + 1 > max_chunk_chars:
            return [], "PROTECTED_ATOM_EXCEEDS_LIMIT"

    if len(seg_str.split()) <= max_chunk_words and len(seg_str) + 1 <= max_chunk_chars:
        return [(seg_start, seg_end)], None

    # Tokenize [seg_start, seg_end) into atomic units (either full ProtectedAtom or single word)
    units: list[tuple[int, int]] = []
    top_atoms = sorted(
        _atoms_in_span(atoms, seg_start, seg_end),
        key=lambda a: a.normalized_span[0],  # type: ignore[index]
    )
    pos = seg_start
    for atom in top_atoms:
        assert atom.normalized_span is not None
        a0 = max(seg_start, atom.normalized_span[0])
        a1 = min(seg_end, atom.normalized_span[1])
        if a0 > pos:
            for wm in re.finditer(r"\S+", norm_text[pos:a0]):
                units.append((pos + wm.start(), pos + wm.end()))
        if a1 > a0:
            units.append((a0, a1))
        pos = max(pos, a1)
    if pos < seg_end:
        for wm in re.finditer(r"\S+", norm_text[pos:seg_end]):
            units.append((pos + wm.start(), pos + wm.end()))

    if not units:
        return [], None

    groups: list[tuple[int, int]] = []
    cur_start: int | None = None
    cur_end: int = 0
    cur_words = 0

    for u0, u1 in units:
        unit_text = norm_text[u0:u1]
        unit_words = max(1, len(unit_text.split()))
        if cur_start is None:
            cur_start = u0
            cur_end = u1
            cur_words = unit_words
            continue

        candidate_len = (u1 - cur_start) + 1
        candidate_words = cur_words + unit_words
        if candidate_len > max_chunk_chars or candidate_words > max_chunk_words:
            groups.append((cur_start, cur_end))
            cur_start = u0
            cur_end = u1
            cur_words = unit_words
        else:
            cur_end = u1
            cur_words = candidate_words

    if cur_start is not None:
        groups.append((cur_start, cur_end))

    return groups, None


def chunk_normalized_text(
    normalized_text: str,
    *,
    atoms: tuple[ProtectedAtom, ...],
    text_mapping: TextMapping,
    max_chunk_chars: int = 270,
    max_chunk_words: int = 15,
    max_total_chunks: int = 64,
    clitic_pause_ms: int = 0,
    emphasis_targets: tuple[str, ...] = (),
) -> ChunkingResult:
    """
    Adapt baseline punctuation clause splitting over already-normalized text.

    Never invokes normalization, never splits inside protected atoms, never truncates
    oversized protected atoms, and emits no whitespace-only chunks.
    """
    if not normalized_text or not normalized_text.strip():
        return ChunkingResult(ok=False, reason_code="EMPTY_NORMALIZED_TEXT", safe_message="Cannot chunk empty text")

    # Find punctuation boundary splits that do NOT fall inside any ProtectedAtom
    top_atoms = [a for a in atoms if a.parent_atom_id is None and a.normalized_span is not None]

    def _inside_atom(idx: int) -> bool:
        for a in top_atoms:
            assert a.normalized_span is not None
            if a.normalized_span[0] < idx < a.normalized_span[1]:
                return True
        return False

    raw_segments: list[tuple[int, int]] = []
    seg_start = 0
    for m in re.finditer(r"(?<=[,.;?!:])\s+", normalized_text):
        split_at = m.start()
        if _inside_atom(split_at):
            continue
        if split_at > seg_start:
            raw_segments.append((seg_start, split_at))
        seg_start = m.end()
    if seg_start < len(normalized_text):
        raw_segments.append((seg_start, len(normalized_text)))

    # Merge short trailing-comma segments (<= 15 chars) matching backend/text.py clauses()
    merged_segments: list[tuple[int, int]] = []
    pending_start: int | None = None
    for s0, s1 in raw_segments:
        piece = normalized_text[s0:s1].strip()
        if not piece:
            continue
        start_eff = pending_start if pending_start is not None else s0
        pending_start = None
        if piece.endswith(",") and len(piece) <= _SHORT_CLAUSE_MAX_CHARS:
            pending_start = start_eff
            continue
        merged_segments.append((start_eff, s1))
    if pending_start is not None:
        merged_segments.append((pending_start, len(normalized_text)))

    chunk_spans: list[tuple[int, int, int]] = []
    for s0, s1 in merged_segments:
        trimmed = normalized_text[s0:s1].strip()
        if not trimmed:
            continue
        # Trim whitespace offsets accurately
        while s0 < s1 and normalized_text[s0].isspace():
            s0 += 1
        while s1 > s0 and normalized_text[s1 - 1].isspace():
            s1 -= 1
        if s0 >= s1:
            continue

        last_ch = normalized_text[s1 - 1]
        base_pause_ms = _PAUSE_MS_MAP.get(last_ch, _DEFAULT_PAUSE_MS)

        sub_spans, err = _split_segment_preserving_atoms(
            normalized_text,
            s0,
            s1,
            atoms,
            max_chunk_chars=max_chunk_chars,
            max_chunk_words=max_chunk_words,
        )
        if err is not None:
            return ChunkingResult(
                ok=False,
                reason_code=err,
                safe_message="Protected atom exceeds max_chunk_chars without truncation",
            )
        for idx, (u0, u1) in enumerate(sub_spans):
            while u0 < u1 and normalized_text[u0].isspace():
                u0 += 1
            while u1 > u0 and normalized_text[u1 - 1].isspace():
                u1 -= 1
            if u0 >= u1 or not normalized_text[u0:u1].strip():
                continue
            pause_ms = base_pause_ms if idx == len(sub_spans) - 1 else _DEFAULT_PAUSE_MS
            chunk_spans.append((u0, u1, pause_ms))

    if not chunk_spans:
        return ChunkingResult(ok=False, reason_code="NO_NONEMPTY_CHUNKS", safe_message="No non-empty speech chunks produced")

    if len(chunk_spans) > max_total_chunks:
        return ChunkingResult(
            ok=False,
            reason_code="LIMIT_EXCEEDED",
            safe_message="Chunk count exceeds max_total_chunks",
        )

    candidates: list[ChunkCandidate] = []
    for idx, (c0, c1, pause_ms) in enumerate(chunk_spans):
        raw_chunk = normalized_text[c0:c1]
        model_text = _prepare_clause_text(raw_chunk)
        if not model_text or not any(ch.isalnum() for ch in model_text):
            continue
        if len(model_text) > max_chunk_chars:
            return ChunkingResult(
                ok=False,
                reason_code="LIMIT_EXCEEDED",
                safe_message="Prepared chunk exceeds max_chunk_chars",
            )
        src_span = text_mapping.source_span_for_normalized(c0, c1)
        atom_refs = text_mapping.atom_ids_in_normalized_span(c0, c1)
        final_pause = pause_ms + clitic_pause_ms if (idx == len(chunk_spans) - 1 and clitic_pause_ms > 0) else pause_ms
        chunk_emph = tuple(e for e in emphasis_targets if e.lower() in raw_chunk.lower())
        candidates.append(
            ChunkCandidate(
                chunk_index=len(candidates),
                model_text=model_text,
                norm_span=(c0, c1),
                source_span=src_span,
                protected_entity_refs=atom_refs,
                post_pause_ms=final_pause,
                requested_speed=None,
                requested_emphasis=chunk_emph,
                requested_controls=(),
            )
        )

    if not candidates:
        return ChunkingResult(ok=False, reason_code="NO_NONEMPTY_CHUNKS", safe_message="Only whitespace/punctuation chunks remained")

    return ChunkingResult(ok=True, chunks=tuple(candidates), reason_code="OK")
