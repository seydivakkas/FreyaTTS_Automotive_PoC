from dataclasses import dataclass, field
from enum import Enum

class State(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    INTERRUPTING = "INTERRUPTING"
    HANDOFF = "HANDOFF"
    FAILED = "FAILED"
    ENDED = "ENDED"

ALLOWED = {
    State.IDLE: {State.LISTENING, State.ENDED},
    State.LISTENING: {State.THINKING, State.HANDOFF, State.ENDED, State.FAILED},
    State.THINKING: {State.SPEAKING, State.HANDOFF, State.LISTENING, State.FAILED, State.ENDED},
    State.SPEAKING: {State.LISTENING, State.INTERRUPTING, State.ENDED, State.FAILED},
    State.INTERRUPTING: {State.LISTENING, State.ENDED, State.FAILED},
    State.HANDOFF: {State.ENDED, State.FAILED},
    State.FAILED: {State.ENDED},
    State.ENDED: set(),
}

@dataclass
class Session:
    session_id: str
    state: State = State.IDLE
    turn_id: int = 0
    generation_id: int = 0
    history: list[State] = field(default_factory=list)

    def move(self, target: State) -> None:
        if target == self.state and target == State.ENDED:
            return  # idempotent teardown
        if target not in ALLOWED[self.state]:
            raise ValueError(f"Invalid state transition: {self.state} -> {target}")
        self.state = target
        self.history.append(target)

    def new_turn(self) -> int:
        if self.state != State.LISTENING:
            raise ValueError("New turn only from listening")
        self.turn_id += 1
        self.generation_id += 1
        self.move(State.THINKING)
        return self.generation_id

    def interrupt(self) -> int:
        if self.state != State.SPEAKING:
            raise ValueError("Barge-in only while speaking")
        self.move(State.INTERRUPTING)
        self.generation_id += 1
        return self.generation_id

    def accepts_chunk(self, generation_id: int) -> bool:
        return self.state == State.SPEAKING and generation_id == self.generation_id
