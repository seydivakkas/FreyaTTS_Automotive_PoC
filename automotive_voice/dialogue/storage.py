"""Bounded ephemeral mock secure store. Not encryption, persistence or production KMS."""
from __future__ import annotations
import threading
from collections import OrderedDict
from dataclasses import dataclass
from uuid import uuid4
from .models import DialogueInput

@dataclass(frozen=True, repr=False)
class StoredTranscript:
    text: str
    parsed: DialogueInput

@dataclass(frozen=True, repr=False)
class StoredResponse:
    text: str
    category: str

class MissingReferenceError(LookupError):
    pass

class ReferenceStore:
    def __init__(self, *, capacity: int = 2048):
        if type(capacity) is not int or capacity < 1:
            raise ValueError('capacity must be positive')
        self._cap = capacity
        self._lock = threading.RLock()
        self._values: OrderedDict[tuple[str, str], object] = OrderedDict()

    def _put(self, sid: str, prefix: str, value: object) -> str:
        reference = f'{prefix}:{uuid4().hex}'
        with self._lock:
            self._values[(sid, reference)] = value
            while len(self._values) > self._cap:
                self._values.popitem(last=False)
        return reference

    def put_input(self, session_id: str, value: DialogueInput) -> str:
        if not isinstance(value, DialogueInput):
            raise TypeError('DialogueInput required')
        return self._put(session_id, 'transcript', value)

    def put_transcript(self, session_id: str, raw_text: str, parsed: DialogueInput) -> str:
        if not isinstance(raw_text, str) or not 1 <= len(raw_text) <= 4096:
            raise ValueError('raw transcript length 1..4096 required')
        if not isinstance(parsed, DialogueInput):
            raise TypeError('parsed DialogueInput required')
        return self._put(session_id, 'transcript', StoredTranscript(raw_text, parsed))

    def get_transcript(self, session_id: str, ref: str) -> str:
        with self._lock:
            v = self._values.get((session_id, ref))
        if not isinstance(v, StoredTranscript):
            raise MissingReferenceError('raw transcript missing for session')
        return v.text

    def get_input(self, session_id: str, ref: str) -> DialogueInput:
        with self._lock:
            v = self._values.get((session_id, ref))
        if isinstance(v, StoredTranscript):
            return v.parsed
        if not isinstance(v, DialogueInput):
            raise MissingReferenceError('input reference missing for this session')
        return v

    def put_response(self, session_id: str, text: str, category: str) -> str:
        if not text or not category:
            raise ValueError('response requires text and category')
        return self._put(session_id, 'response', StoredResponse(text, category))

    def get_response(self, session_id: str, ref: str) -> StoredResponse:
        with self._lock:
            v = self._values.get((session_id, ref))
        if not isinstance(v, StoredResponse):
            raise MissingReferenceError('response reference missing for this session')
        return v

    def erase_session(self, sid: str) -> None:
        with self._lock:
            for k in tuple(self._values):
                if k[0] == sid:
                    del self._values[k]
