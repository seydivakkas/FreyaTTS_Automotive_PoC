"""M05 immutable text-only TTS contracts. No audio buffers or transport objects."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import hashlib
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId

class BreakKind(str, Enum):
    SENTENCE = 'sentence'
    PAUSE = 'pause'
    LIMIT = 'limit'
    FINAL = 'final'

class PlanStatus(str, Enum):
    READY = 'ready'
    REVIEW_REQUIRED = 'review_required'

class SpanKind(str, Enum):
    MONEY = 'money'
    DATE = 'date'
    TIME = 'time'
    ENGINE = 'engine'
    MODEL = 'model'
    DISTANCE = 'distance'
    MODEL_YEAR = 'model_year'
    APPROVED_LEXICON = 'approved_lexicon'

@dataclass(frozen=True, slots=True)
class PhraseBoundary:
    start: int
    end: int
    kind: SpanKind
    evidence: str = ''  # non-sensitive rule tag, NEVER source transcript

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.end) is not int or self.start < 0 or self.end <= self.start:
            raise ValueError('invalid protected span offsets')
        if not isinstance(self.kind, SpanKind):
            raise TypeError('SpanKind required')

@dataclass(frozen=True, slots=True)
class Clause:
    index: int
    start: int
    end: int
    text: str
    break_kind: BreakKind
    pause_after_ms: int
    delivery_hint: str

    def __post_init__(self) -> None:
        if (type(self.index) is not int or self.index < 0 or self.start < 0 or
            self.end <= self.start or not self.text or
            self.text != self.text.strip() or self.pause_after_ms < 0 or
            self.delivery_hint not in {'statement', 'question', 'continuation'}):
            raise ValueError('invalid clause')
        if not isinstance(self.break_kind, BreakKind):
            raise TypeError('BreakKind required')

@dataclass(frozen=True, slots=True)
class TTSInput:
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    clause_index: int
    clause_count: int
    text: str  # kept in local processing memory, not events/telemetry
    text_sha256: str
    break_kind: BreakKind
    pause_after_ms: int
    delivery_hint: str

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, SessionId) or not isinstance(self.turn_id, TurnId) or not isinstance(self.generation_id, GenerationId):
            raise TypeError('strong session, turn, generation identifiers required')
        if (type(self.clause_index) is not int or type(self.clause_count) is not int or
            not (0 <= self.clause_index < self.clause_count) or not self.text or
            hashlib.sha256(self.text.encode('utf-8')).hexdigest() != self.text_sha256):
            raise ValueError('invalid or corrupted text-only TTS input')

    def safe_metadata(self) -> dict:
        return {'session_id': str(self.session_id), 'turn_id': int(self.turn_id),
                'generation_id': int(self.generation_id), 'clause_index': self.clause_index,
                'clause_count': self.clause_count, 'text_sha256': self.text_sha256,
                'break_kind': self.break_kind.value, 'delivery_hint': self.delivery_hint}

@dataclass(frozen=True, slots=True)
class ClausePlan:
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    spoken_text: str  # private; never serialized into event payloads or logs
    status: PlanStatus
    clauses: tuple[Clause, ...]
    protected_spans: tuple[PhraseBoundary, ...]
    warning_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, SessionId) or not isinstance(self.turn_id, TurnId) or not isinstance(self.generation_id, GenerationId):
            raise TypeError('M01 identity types required')
        if not self.spoken_text or not isinstance(self.status, PlanStatus):
            raise ValueError('invalid clause plan')
        if self.warning_codes and self.status is PlanStatus.READY:
            raise ValueError('warning-bearing plan cannot be ready')
        for i, c in enumerate(self.clauses):
            if i != c.index or self.spoken_text[c.start:c.end] != c.text:
                raise ValueError('clause offsets/text mismatch')
        if ''.join(self.spoken_text.split()) != ''.join(''.join(c.text.split()) for c in self.clauses):
            raise ValueError('clauses must preserve all non-whitespace characters')
        for span in self.protected_spans:
            if span.end > len(self.spoken_text):
                raise ValueError('protected span outside text')
            if not any(c.start <= span.start and span.end <= c.end for c in self.clauses):
                raise ValueError('protected span split across clauses')

    @property
    def review_required(self) -> bool:
        return self.status is PlanStatus.REVIEW_REQUIRED

    def tts_inputs(self) -> tuple[TTSInput, ...]:
        """No TTS inputs if text has any unresolved pronunciation/formatting warning."""
        if self.review_required:
            return ()
        return tuple(TTSInput(self.session_id, self.turn_id, self.generation_id,
                              c.index, len(self.clauses), c.text,
                              hashlib.sha256(c.text.encode('utf-8')).hexdigest(),
                              c.break_kind, c.pause_after_ms, c.delivery_hint)
                     for c in self.clauses)

    def safe_metadata(self) -> dict:
        return {'session_id': str(self.session_id), 'turn_id': int(self.turn_id),
                'generation_id': int(self.generation_id), 'status': self.status.value,
                'clause_count': len(self.clauses), 'protected_span_count': len(self.protected_spans),
                'warning_codes': list(self.warning_codes)}
