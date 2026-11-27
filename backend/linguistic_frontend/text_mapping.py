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
from typing import Iterable


@dataclass(frozen=True, slots=True)
class SpanMappingEntry:
    """Explicit half-open Unicode codepoint mapping between two text representations."""

    source_span: tuple[int, int]
    target_span: tuple[int, int]
    atom_ids: tuple[str, ...] = ()
    transformation_kind: str = "IDENTITY"
    rule_revision: str = "f4a.v1"

    def __post_init__(self) -> None:
        s0, s1 = self.source_span
        t0, t1 = self.target_span
        if s0 < 0 or s1 < s0 or t0 < 0 or t1 < t0:
            raise ValueError("Invalid half-open span bounds in SpanMappingEntry")


@dataclass(frozen=True, slots=True)
class TextMapping:
    """Provenance map linking source_text, normalized_text, and model_text chunks."""

    source_text: str
    normalized_text: str
    entries: tuple[SpanMappingEntry, ...]
    ruleset_revision: str = "f4a.v1"

    def source_span_for_normalized(self, norm_start: int, norm_end: int) -> tuple[int, int]:
        """Project a half-open span in normalized_text back to source_text codepoint bounds."""
        if norm_start < 0 or norm_end < norm_start or norm_end > len(self.normalized_text):
            raise ValueError("Invalid normalized span bounds")
        if not self.entries:
            return (0, len(self.source_text))
        if norm_start == norm_end:
            for e in self.entries:
                t0, t1 = e.target_span
                if t0 <= norm_start <= t1:
                    return (e.source_span[0], e.source_span[0])
            pos = len(self.source_text)
            return (pos, pos)

        src_starts: list[int] = []
        src_ends: list[int] = []
        for e in self.entries:
            t0, t1 = e.target_span
            # Overlap in half-open [t0, t1) and [norm_start, norm_end)
            if t0 < norm_end and norm_start < t1:
                src_starts.append(e.source_span[0])
                src_ends.append(e.source_span[1])
        if not src_starts:
            return (0, len(self.source_text))
        return (min(src_starts), max(src_ends))

    def normalized_span_for_source(self, src_start: int, src_end: int) -> tuple[int, int] | None:
        """Project a half-open source_text span to normalized_text bounds."""
        if src_start < 0 or src_end < src_start or src_end > len(self.source_text):
            raise ValueError("Invalid source span bounds")
        tgt_starts: list[int] = []
        tgt_ends: list[int] = []
        for e in self.entries:
            s0, s1 = e.source_span
            if s0 < src_end and src_start < s1:
                tgt_starts.append(e.target_span[0])
                tgt_ends.append(e.target_span[1])
        if not tgt_starts:
            return None
        return (min(tgt_starts), max(tgt_ends))

    def atom_ids_in_normalized_span(self, norm_start: int, norm_end: int) -> tuple[str, ...]:
        seen: list[str] = []
        for e in self.entries:
            t0, t1 = e.target_span
            if t0 < norm_end and norm_start < t1:
                for aid in e.atom_ids:
                    if aid not in seen:
                        seen.append(aid)
        return tuple(seen)


@dataclass(frozen=True, slots=True)
class NormalizationTrace:
    """Safe normalization execution trace (zero raw PII/speech text persisted)."""

    response_id: str
    plan_id: str
    pass_count: int
    ruleset_revision: str
    stage_ids: tuple[str, ...]
    source_length: int
    normalized_length: int
    warning_codes: tuple[str, ...] = ()


def build_text_mapping(
    *,
    source_text: str,
    normalized_text: str,
    entries: Iterable[SpanMappingEntry],
    ruleset_revision: str = "f4a.v1",
) -> TextMapping:
    """Validate and freeze a TextMapping across source and normalized representations."""
    ordered = tuple(sorted(entries, key=lambda e: (e.target_span[0], e.target_span[1], e.source_span[0])))
    src_len = len(source_text)
    norm_len = len(normalized_text)
    for entry in ordered:
        if entry.source_span[1] > src_len:
            raise ValueError("SpanMappingEntry source_span exceeds source_text length")
        if entry.target_span[1] > norm_len:
            raise ValueError("SpanMappingEntry target_span exceeds normalized_text length")
    return TextMapping(
        source_text=source_text,
        normalized_text=normalized_text,
        entries=ordered,
        ruleset_revision=ruleset_revision,
    )
