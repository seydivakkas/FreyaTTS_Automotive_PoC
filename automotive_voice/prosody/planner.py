"""Deterministic Turkish clause planner over M04 normalized text.

Protects typed multi-token spans and never converts an unapproved pronunciation.
Punctuation/whitespace splitting is advisory text planning, not acoustic control.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.nlp.normalizer import (NormalizationResult, TurkishAutomotiveNormalizer,
                                            CLOCK, YEAR_MODEL, KM)
from automotive_voice.nlp.lexicon import AutomotiveLexicon, tr_key
from .contracts import (Clause, ClausePlan, PhraseBoundary, SpanKind,
                        BreakKind, PlanStatus)

WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*|[^\s]", re.UNICODE)
NUMBER = frozenset(('sıfır bir iki üç dört beş altı yedi sekiz dokuz on yirmi otuz kırk elli '
                    'altmış yetmiş seksen doksan yüz bin milyon milyar trilyon').split())
MONTHS = frozenset(('ocak şubat mart nisan mayıs haziran temmuz ağustos eylül ekim kasım aralık').split())
ENGINES = frozenset(('tsi tdi tfsi tce dci cdi hdi').split())
MODELS = ('Nissan Qashqai', 'Qashqai', 'Peugeot', 'Citroën', 'Škoda', 'Volkswagen',
          'Passat', 'Kamiq', 'Tiguan', 'Mercedes-Benz')
SUFFIXES = ('da', 'de', 'ta', 'te', 'ya', 'ye')

@dataclass(frozen=True, slots=True)
class PlannerLimits:
    max_words: int = 16
    max_chars: int = 160
    max_clauses: int = 80

    def __post_init__(self):
        for value in (self.max_words, self.max_chars, self.max_clauses):
            if type(value) is not int or value < 1:
                raise ValueError('planner limits must be positive integers')


def _number(value: str, allow_suffix: bool = False) -> bool:
    v = tr_key(value)
    if v in NUMBER:
        return True
    return allow_suffix and any(v == n + s for n in NUMBER for s in SUFFIXES)


def _protected(text: str, lexicon: AutomotiveLexicon, display: str) -> tuple[PhraseBoundary, ...]:
    tokens = list(WORD.finditer(text))
    norm = [tr_key(t.group()) for t in tokens]
    spans: list[PhraseBoundary] = []
    def put(i: int, j: int, kind: SpanKind):
        if 0 <= i < j <= len(tokens):
            spans.append(PhraseBoundary(tokens[i].start(), tokens[j-1].end(), kind, kind.value))

    for i, token in enumerate(norm):
        # Number words + Türk lirası (+ ve ... kuruş), one indivisible currency amount.
        if token == 'türk' and i + 1 < len(norm) and norm[i+1] == 'lirası':
            start = i
            while start > 0 and _number(norm[start-1]):
                start -= 1
            if start != i:
                stop = i + 2
                if stop + 2 < len(norm) and norm[stop] == 've':
                    cursor = stop + 1
                    while cursor < len(norm) and _number(norm[cursor]):
                        cursor += 1
                    if cursor > stop + 1 and cursor < len(norm) and norm[cursor] == 'kuruş':
                        stop = cursor + 1
                put(start, stop, SpanKind.MONEY)
        if token in MONTHS:
            before = i
            while before > 0 and i - before < 3 and _number(norm[before-1]):
                before -= 1
            after = i + 1
            while after < len(norm) and after - i <= 6 and _number(norm[after]):
                after += 1
            if before < i:
                put(before, after, SpanKind.DATE)
        if token == 'saat' and i + 1 < len(norm) and _number(norm[i+1]):
            after = i + 1
            while after < len(norm) and after - i <= 5 and _number(norm[after], allow_suffix=True):
                after += 1
            if after > i + 1:
                put(i, after, SpanKind.TIME)
        if token == 'nokta' and i and i + 2 < len(norm) and _number(norm[i-1]) and _number(norm[i+1]) and tokens[i+2].group().lower() in ENGINES:
            put(i-1, i+3, SpanKind.ENGINE)

    # Known names are protected as spellings only, NEVER rewritten or approved here.
    # Multiword approved lexicon readings are also protected, with no guessed variants.
    names = [(name, SpanKind.MODEL) for name in MODELS]
    names += [(rule.spoken_tr, SpanKind.APPROVED_LEXICON)
              for rule in lexicon.rules if rule.approved and not rule.context]
    for name, kind in names:
        parts = [tr_key(t.group()) for t in WORD.finditer(name)]
        if not parts:
            continue
        for i in range(len(norm) - len(parts) + 1):
            segment = norm[i:i+len(parts)]
            if (segment == parts or (segment[:-1] == parts[:-1] and
                (segment[-1].startswith(parts[-1] + "'") or segment[-1].startswith(parts[-1] + '’')))):
                put(i, i+len(parts), kind)

    # M04 can expand a bare 14:30 into "on dört otuz" without the cue "saat".
    # Recover only syntactically typed, already-normalized source expressions.
    # Never guess an isolated number phrase is a time, distance, or model year.
    renderer = TurkishAutomotiveNormalizer(lexicon=lexicon)
    for pattern, kind in ((CLOCK, SpanKind.TIME), (YEAR_MODEL, SpanKind.MODEL_YEAR),
                          (KM, SpanKind.DISTANCE)):
        for raw in pattern.finditer(display):
            rendered = renderer.normalize(raw.group()).spoken_text
            if rendered != raw.group() and rendered:
                for hit in re.finditer(r'(?<!\w)' + re.escape(rendered) + r'(?!\w)', text, re.I):
                    spans.append(PhraseBoundary(hit.start(), hit.end(), kind, kind.value))

    # Merge overlaps for atomicity; canonical kind prioritizes first discovered.
    spans.sort(key=lambda s: (s.start, -s.end, s.kind.value))
    merged: list[PhraseBoundary] = []
    for s in spans:
        if merged and s.start < merged[-1].end:
            p = merged[-1]
            merged[-1] = PhraseBoundary(p.start, max(p.end, s.end), p.kind, 'overlap_union')
        else:
            merged.append(s)
    return tuple(merged)


class ProsodyClausePlanner:
    def __init__(self, *, lexicon: AutomotiveLexicon | None = None,
                 limits: PlannerLimits | None = None):
        self.lexicon = lexicon or AutomotiveLexicon()
        self.limits = limits or PlannerLimits()

    def plan(self, normalized: NormalizationResult, *, session_id: SessionId,
             turn_id: TurnId, generation_id: GenerationId) -> ClausePlan:
        if not isinstance(normalized, NormalizationResult):
            raise TypeError('M04 NormalizationResult required')
        if not isinstance(session_id, SessionId) or not isinstance(turn_id, TurnId) or not isinstance(generation_id, GenerationId):
            raise TypeError('M01 typed identifiers required')
        text = normalized.spoken_text
        if not text or len(text) > 5000:
            raise ValueError('invalid spoken text length')
        spans = _protected(text, self.lexicon, normalized.display_text)
        tokens = list(WORD.finditer(text))
        # Boundaries must never bisect protected spans or parentheses/quotes.
        protected_inside = lambda pos: any(s.start < pos < s.end for s in spans)
        depth = 0
        candidates: dict[int, BreakKind] = {}
        for m in tokens:
            v = m.group()
            if v in '([{':
                depth += 1
            if v in ')]}':
                depth = max(0, depth - 1)
            if depth == 0 and not protected_inside(m.end()):
                if v in ('.', '?', '!'):
                    candidates[m.end()] = BreakKind.SENTENCE
                elif v in (',', ';', ':'):
                    candidates[m.end()] = BreakKind.PAUSE
        # A chunk is assembled token by token and cut at preferred punctuation,
        # or the last non-protected word boundary within limits.
        clauses: list[Clause] = []
        warnings = list(normalized.warnings)
        i = 0
        while i < len(tokens):
            begin = tokens[i].start()
            j = i
            last_valid: tuple[int, BreakKind] | None = None
            preferred: tuple[int, BreakKind] | None = None
            while j < len(tokens):
                end = tokens[j].end()
                span = text[begin:end]
                words = len(re.findall(r"[^\W_]+(?:['’][^\W_]+)*", span))
                too_long = (len(span) > self.limits.max_chars or words > self.limits.max_words)
                if too_long and last_valid is not None:
                    break
                if not protected_inside(end):
                    kind = candidates.get(end, BreakKind.LIMIT)
                    last_valid = (j, kind)
                    if kind in (BreakKind.SENTENCE, BreakKind.PAUSE):
                        preferred = (j, kind)
                        break
                j += 1
                if too_long and last_valid is None:
                    # One indivisible span can be larger than the limit; keep it
                    # intact but block all TTS until manually reviewed.
                    while j < len(tokens) and protected_inside(tokens[j-1].end()):
                        j += 1
            if preferred is not None:
                cut, kind = preferred
            elif j >= len(tokens):
                cut, kind = len(tokens)-1, BreakKind.FINAL
            elif last_valid is not None:
                cut, kind = last_valid
            else:
                cut, kind = j-1, BreakKind.LIMIT
            if cut < i:
                cut = i
            end = tokens[cut].end()
            content = text[begin:end].strip()
            if len(content) > self.limits.max_chars or len(content.split()) > self.limits.max_words:
                warnings.append('overlong_atomic_span')
            if len(clauses) + 1 > self.limits.max_clauses:
                raise ValueError('too_many_clauses')
            if kind is BreakKind.FINAL:
                pause_ms = 0
            elif kind is BreakKind.SENTENCE:
                pause_ms = 260 if content.endswith('?') else 240
            elif kind is BreakKind.PAUSE:
                pause_ms = 110
            else:
                pause_ms = 80
            hint = ('question' if content.endswith('?') else
                    'continuation' if kind in (BreakKind.PAUSE, BreakKind.LIMIT) else 'statement')
            clauses.append(Clause(len(clauses), begin, end, content, kind, pause_ms, hint))
            i = cut + 1
        if clauses and clauses[-1].break_kind != BreakKind.FINAL:
            last = clauses[-1]
            clauses[-1] = Clause(last.index, last.start, last.end, last.text,
                                 BreakKind.FINAL, 0, 'question' if last.text.endswith('?') else 'statement')
        warnings = tuple(dict.fromkeys(warnings))
        return ClausePlan(session_id, turn_id, generation_id, text,
                          PlanStatus.REVIEW_REQUIRED if normalized.review_required or warnings else PlanStatus.READY,
                          tuple(clauses), spans, warnings)
