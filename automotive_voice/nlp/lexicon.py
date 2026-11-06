"""Evidence-gated, single-pass automotive pronunciation overlay.

A01-YT approval is required. A user permission claim is NOT a pronunciation
observation. Never synthesize foreign-name readings from spelling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import unicodedata


class LexiconError(ValueError):
    pass


def tr_key(value: str) -> str:
    return unicodedata.normalize('NFC', value).translate(str.maketrans({'I': 'ı', 'İ': 'i'})).lower()


def _safe_reading(value: str) -> bool:
    return (bool(value.strip()) and len(value) <= 160
            and all(c.isalpha() or c in ' -' for c in value))


@dataclass(frozen=True, slots=True)
class LexiconRule:
    canonical: str
    spoken_tr: str
    approved: bool
    source_ref: str
    reviewer: str
    evidence: tuple[dict, ...] = ()
    aliases: tuple[str, ...] = ()
    suffix_map: dict[str, str] = field(default_factory=dict)
    context: str = ''

    def __post_init__(self):
        if not self.canonical.strip() or not _safe_reading(self.spoken_tr):
            raise LexiconError('invalid canonical or Turkish reading')
        if self.approved:
            if not (self.source_ref.strip() and self.reviewer.strip() and self.evidence):
                raise LexiconError('approved pronunciation must have reviewer, source and evidence')
            for evidence in self.evidence:
                if not isinstance(evidence, dict) or not all(evidence.get(k) for k in ('annotation_id', 'clip_id', 'source_url')):
                    raise LexiconError('evidence must identify source, clip and annotation')
        for suffix, replacement in self.suffix_map.items():
            if not re.fullmatch(r"['’][A-Za-zÇĞİÖŞÜçğıöşü]{1,8}", suffix):
                raise LexiconError('invalid explicit suffix key')
            if not re.fullmatch(r"[A-Za-zÇĞİÖŞÜçğıöşü]{1,10}", replacement):
                raise LexiconError('invalid explicit spoken suffix')

    def as_dict(self) -> dict:
        return {'canonical': self.canonical, 'spoken_tr': self.spoken_tr,
                'approved': self.approved, 'source_ref': self.source_ref,
                'reviewer': self.reviewer, 'evidence': list(self.evidence),
                'aliases': list(self.aliases), 'suffix_map': dict(self.suffix_map),
                'context': self.context}


@dataclass(frozen=True, slots=True)
class LexiconApplication:
    text: str
    hits: tuple[str, ...]
    review_required: tuple[str, ...]


class AutomotiveLexicon:
    def __init__(self, rules: tuple[LexiconRule, ...] = ()):
        self.rules = rules
        index: dict[str, LexiconRule] = {}
        for rule in rules:
            for alias in (rule.canonical, *rule.aliases):
                key = tr_key(alias)
                if not alias.strip() or (key in index and index[key] != rule):
                    raise LexiconError('duplicate or conflicting lexicon form')
                index[key] = rule
        self._by_name = index
        # One regex: no cascading replacement and no partial match inside model names.
        names = sorted({name for r in rules for name in (r.canonical, *r.aliases)}, key=len, reverse=True)
        self._pattern = (re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(n) for n in names) +
                                    r")(?:['’](?:[A-Za-zÇĞİÖŞÜçğıöşü]+))?(?!\w)", re.I)
                         if names else None)

    @classmethod
    def from_a01yt_export(cls, path: str | Path) -> 'AutomotiveLexicon':
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('schema_version') != 1 or not isinstance(data.get('approved_rules'), list):
            raise LexiconError('unsupported A01-YT export')
        if data.get('conflicts'):
            # Do not quietly accept a snapshot containing conflicting readings.
            raise LexiconError('source export has pronunciation conflicts')
        rules = []
        for entry in data['approved_rules']:
            if entry.get('context'):
                continue   # context-sensitive readings require a later contract
            evidences = tuple(entry.get('evidence', ()))
            source_ref = entry.get('source_ref') or (evidences[0].get('source_url') if evidences else '')
            reviewer = entry.get('reviewer') or entry.get('reviewed_by') or ''
            # v0.5's exports do not carry reviewer. Do not fabricate approval.
            if not reviewer:
                raise LexiconError('approved export is missing reviewer provenance')
            rules.append(LexiconRule(canonical=entry['canonical'], spoken_tr=entry['spoken_tr'],
                                     approved=True, source_ref=source_ref, reviewer=reviewer,
                                     evidence=evidences, aliases=tuple(entry.get('aliases', ())),
                                     suffix_map=dict(entry.get('suffix_map', {}))))
        return cls(tuple(rules))

    def apply(self, text: str) -> LexiconApplication:
        if self._pattern is None:
            return LexiconApplication(text, (), ())
        hits: list[str] = []
        reviews: list[str] = []
        def replace(match: re.Match) -> str:
            literal = match.group()
            base = re.split("['’]", literal, maxsplit=1)[0]
            rule = self._by_name.get(tr_key(base))
            if rule is None:  # re.I may match Turkish I in a non-Turkish way
                return literal
            if not rule.approved or rule.context:
                reviews.append('unapproved:' + rule.canonical)
                return literal
            suffix = literal[len(base):]
            if suffix:
                mapping = rule.suffix_map.get(suffix) or rule.suffix_map.get(suffix.replace('’', "'"))
                if mapping is None:
                    reviews.append('suffix_requires_review:' + literal)
                    return literal
                replacement = rule.spoken_tr + mapping
            else:
                replacement = rule.spoken_tr
            hits.append(rule.canonical)
            return replacement
        result = self._pattern.sub(replace, text)
        return LexiconApplication(result, tuple(hits), tuple(dict.fromkeys(reviews)))

    def approved_export(self) -> dict:
        return {'schema_version': 1, 'rules': [r.as_dict() for r in self.rules if r.approved]}
