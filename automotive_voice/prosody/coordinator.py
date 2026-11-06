"""Bridge M02 START_TTS refs -> M03 response store -> M04 -> M05 mock queue.

No LLM, no Freya runtime, no audio. Fail closed on missing, stale or
review-required text; store is session scoped, events carry only opaque refs.
"""
from __future__ import annotations
from dataclasses import dataclass
from automotive_voice.conversation.effects import Effect, EffectKind
from automotive_voice.dialogue.storage import ReferenceStore, MissingReferenceError
from automotive_voice.nlp.normalizer import TurkishAutomotiveNormalizer
from .planner import ProsodyClausePlanner
from .mock_tts import MockTTS

@dataclass(frozen=True, slots=True)
class PlanningResult:
    status: str
    reason: str
    queued_clauses: int
    warning_codes: tuple[str, ...] = ()

class ProsodyCoordinator:
    def __init__(self, store: ReferenceStore, normalizer: TurkishAutomotiveNormalizer,
                 planner: ProsodyClausePlanner, mock_tts: MockTTS, *, presentation=None):
        self.store = store
        self.normalizer = normalizer
        self.planner = planner
        self.mock_tts = mock_tts
        self.presentation = presentation

    async def process(self, effect: Effect) -> PlanningResult:
        if not isinstance(effect, Effect) or effect.kind is not EffectKind.START_TTS:
            raise ValueError('M02 START_TTS effect required')
        sid = str(effect.session_id)
        if not await self.mock_tts._active(sid, effect.turn_id, effect.generation_id):
            return PlanningResult('rejected', 'stale_generation_or_wrong_state', 0)
        try:
            response = self.store.get_response(sid, effect.reference or '')
        except MissingReferenceError:
            return PlanningResult('rejected', 'missing_response_reference', 0)
        try:
            spoken_text = response.text
            if self.presentation is not None:
                candidate = self.presentation.render(response)
                if candidate.warnings:
                    return PlanningResult('review_required','presentation_gate',0,candidate.warnings)
                spoken_text = candidate.speech_text
            normalized = self.normalizer.normalize(spoken_text)
            plan = self.planner.plan(normalized, session_id=effect.session_id,
                                     turn_id=effect.turn_id, generation_id=effect.generation_id)
        except (TypeError, ValueError):
            return PlanningResult('rejected', 'invalid_tts_text', 0)
        if plan.review_required:
            # No content or forbidden character in logs/audit.
            return PlanningResult('review_required', 'unresolved_text', 0, plan.warning_codes)
        receipt = await self.mock_tts.enqueue(plan)
        return PlanningResult('queued' if receipt.accepted else 'rejected', receipt.reason,
                              receipt.count)
