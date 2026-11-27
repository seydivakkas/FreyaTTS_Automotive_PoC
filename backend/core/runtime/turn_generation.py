"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from backend.core.contracts.common import GenerationRef, TurnRef
from backend.core.runtime.cancellation import CancellationScope


class PauseState(StrEnum):
    RUNNING = "RUNNING"
    SOFT_PAUSED = "SOFT_PAUSED"


@dataclass(frozen=True, slots=True)
class PauseRef:
    generation_ref: GenerationRef
    pause_epoch: int


class PauseController:
    """Output gate scoped to a single active generation without incrementing turn_id."""

    def __init__(self) -> None:
        self._state: PauseState = PauseState.RUNNING
        self._epoch: int = 0
        self._active_gen: GenerationRef | None = None

    @property
    def state(self) -> PauseState:
        return self._state

    @property
    def epoch(self) -> int:
        return self._epoch

    def soft_pause(self, gen_ref: GenerationRef) -> PauseRef:
        self._epoch += 1
        self._state = PauseState.SOFT_PAUSED
        self._active_gen = gen_ref
        return PauseRef(gen_ref, self._epoch)

    def resume(self, pause_ref: PauseRef, current_gen: GenerationRef, gen_scope: CancellationScope) -> bool:
        if gen_scope.is_cancel_requested:
            return False
        if self._state != PauseState.SOFT_PAUSED:
            return False
        if pause_ref.generation_ref != current_gen or self._active_gen != current_gen:
            return False
        if pause_ref.pause_epoch != self._epoch:
            return False
        self._state = PauseState.RUNNING
        return True

    def commit_interrupt(self, gen_ref: GenerationRef, gen_scope: CancellationScope, reason: str = "barge_in_commit") -> bool:
        changed = gen_scope.request_cancel(reason)
        if self._active_gen == gen_ref or self._state == PauseState.SOFT_PAUSED:
            self._state = PauseState.RUNNING
            self._epoch += 1
            self._active_gen = None
        return changed

    def reset_for_generation(self, gen_ref: GenerationRef) -> None:
        self._state = PauseState.RUNNING
        self._active_gen = gen_ref
        self._epoch += 1


class TurnGenerationManager:
    """Monotonic per-session turn and generation allocator."""

    def __init__(self, session_id: str, session_scope: CancellationScope) -> None:
        self.session_id = session_id
        self._session_scope = session_scope
        self._turn_counter: int = 0
        self._generation_counter: int = 0
        self._active_turn: TurnRef | None = None
        self._turn_scope: CancellationScope | None = None
        self._active_generation: GenerationRef | None = None
        self._generation_scope: CancellationScope | None = None

    @property
    def active_turn(self) -> TurnRef | None:
        return self._active_turn

    @property
    def active_generation(self) -> GenerationRef | None:
        return self._active_generation

    @property
    def turn_scope(self) -> CancellationScope | None:
        return self._turn_scope

    @property
    def generation_scope(self) -> CancellationScope | None:
        return self._generation_scope

    def begin_turn(self, supersede_reason: str = "turn_superseded") -> tuple[TurnRef, CancellationScope]:
        self._session_scope.check_active()
        if self._generation_scope is not None:
            self._generation_scope.request_cancel(supersede_reason)
        if self._turn_scope is not None:
            self._turn_scope.request_cancel(supersede_reason)
        self._turn_counter += 1
        tref = TurnRef(self.session_id, self._turn_counter)
        tscope = self._session_scope.child_scope(f"turn:{tref.turn_id}")
        self._active_turn = tref
        self._turn_scope = tscope
        self._active_generation = None
        self._generation_scope = None
        return tref, tscope

    def begin_generation(self, turn_ref: TurnRef | None = None, supersede_reason: str = "generation_superseded") -> tuple[GenerationRef, CancellationScope]:
        self._session_scope.check_active()
        if self._active_turn is None or self._turn_scope is None:
            raise ValueError("Cannot begin generation without active turn")
        if turn_ref is not None and turn_ref != self._active_turn:
            raise ValueError("turn_ref is stale or wrong session")
        self._turn_scope.check_active()
        if self._generation_scope is not None:
            self._generation_scope.request_cancel(supersede_reason)
        self._generation_counter += 1
        gref = GenerationRef(self.session_id, self._active_turn.turn_id, self._generation_counter)
        gscope = self._turn_scope.child_scope(f"gen:{gref.generation_id}")
        self._active_generation = gref
        self._generation_scope = gscope
        return gref, gscope
