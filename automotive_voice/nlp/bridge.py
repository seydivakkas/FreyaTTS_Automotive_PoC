"""M04 NLU -> unchanged M03 ReferenceStore with reference-only M02 event payloads."""
from __future__ import annotations
from dataclasses import dataclass
from automotive_voice.dialogue.storage import ReferenceStore
from .nlu import DeterministicNLU, ParseContext, ParseResult

@dataclass(frozen=True, slots=True)
class InputReference:
    ref: str
    parse: ParseResult

class NLUReferenceBridge:
    def __init__(self, parser: DeterministicNLU, store: ReferenceStore):
        self.parser, self.store = parser, store

    def resolve(self, session_id: str, transcript: str, context: ParseContext) -> InputReference:
        if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 100:
            raise ValueError('invalid session id')
        parsed = self.parser.parse(transcript, context)
        # No raw transcript is stored; to store raw text, an explicitly authorized
        # secure application port would have to be introduced separately.
        ref = self.store.put_input(session_id, parsed.dialogue_input)
        return InputReference(ref, parsed)
