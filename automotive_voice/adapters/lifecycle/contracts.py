"""M07: typed control-plane contracts. No network, audio payload, PII or real wall clocks."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Protocol
import re
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId

SAFE = re.compile(r'^[a-zA-Z0-9_.:/-]{1,128}$')
class AdapterKind(str, Enum):
    STT = 'stt'
    TTS = 'tts'
    LLM = 'llm'
    TELEPHONY = 'telephony'
class AdapterState(str, Enum):
    CREATED = 'created'
    STARTING = 'starting'
    READY = 'ready'
    DEGRADED = 'degraded'
    STOPPING = 'stopping'
    STOPPED = 'stopped'
    FAILED = 'failed'
class CircuitState(str, Enum):
    CLOSED = 'closed'
    OPEN = 'open'
    HALF_OPEN = 'half_open'
class ResultCode(str, Enum):
    OK = 'ok'
    TRANSIENT_FAILURE = 'transient_failure'
    PERMANENT_FAILURE = 'permanent_failure'
    TIMED_OUT = 'timed_out'
    STALE = 'stale_generation'
    CANCELLED = 'cancelled'
    DISCONNECTED = 'disconnected'
    RETRY_EXHAUSTED = 'retry_exhausted'

@dataclass(frozen=True, slots=True)
class Deadline:
    mono_ns: int
    def __post_init__(self):
        if type(self.mono_ns) is not int or not 0 < self.mono_ns <= 2**63-1:
            raise ValueError('positive monotonic_ns required')
    def expired(self, now_ns: int) -> bool:
        return now_ns >= self.mono_ns
    def safe_metadata(self) -> dict:
        return {"deadline_mono_ns":self.mono_ns}

@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_ns: int = 100_000_000
    max_delay_ns: int = 2_000_000_000
    def __post_init__(self):
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 16:
            raise ValueError('max_attempts must be 1..16')
        if any(type(x) is not int or x <= 0 for x in (self.base_delay_ns,self.max_delay_ns)) or self.max_delay_ns < self.base_delay_ns:
            raise ValueError('invalid retry bounds')
    def delay_after(self, failed_attempt:int) -> int:
        if type(failed_attempt) is not int or failed_attempt < 1: raise ValueError('invalid failed attempt')
        return min(self.max_delay_ns, self.base_delay_ns * (2**min(failed_attempt-1, 30)))
    def safe_metadata(self)->dict:
        return {"max_attempts":self.max_attempts,"base_delay_ns":self.base_delay_ns,"max_delay_ns":self.max_delay_ns}

@dataclass(frozen=True, slots=True)
class SyntheticCommand:
    """Reference-only request, with per-adapter/session monotonically increasing sequence."""
    command_id: str
    kind: AdapterKind
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    sequence: int
    payload_ref: str
    deadline: Deadline
    idempotent: bool = True
    def __post_init__(self):
        if not isinstance(self.kind,AdapterKind) or not isinstance(self.session_id,SessionId) or not isinstance(self.turn_id,TurnId) or not isinstance(self.generation_id,GenerationId):
            raise TypeError('adapter kind and strong IDs required')
        if not SAFE.fullmatch(self.command_id) or not SAFE.fullmatch(self.payload_ref):
            raise ValueError('command_id/payload_ref must be opaque ASCII tokens (no raw text)')
        if type(self.sequence) is not int or not 0 <= self.sequence <= 2**63-1:
            raise ValueError('sequence must be a nonnegative integer')
        if not isinstance(self.deadline,Deadline) or type(self.idempotent) is not bool:
            raise TypeError('deadline / idempotent invalid')
    def safe_metadata(self)->dict:
        return {"command_id":self.command_id,"kind":self.kind.value,"session_id":str(self.session_id),
                "turn_id":int(self.turn_id),"generation_id":int(self.generation_id),
                "sequence":self.sequence,"payload_ref":self.payload_ref,
                "deadline_mono_ns":self.deadline.mono_ns,"idempotent":self.idempotent}

@dataclass(frozen=True, slots=True)
class AdapterReceipt:
    accepted: bool
    reason: str
    command_id: str

@dataclass(frozen=True, slots=True)
class SyntheticResult:
    command_id: str
    kind: AdapterKind
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    code: ResultCode
    attempts: int
    output_ref: str | None = None
    def __post_init__(self):
        if self.output_ref is not None and not SAFE.fullmatch(self.output_ref):
            raise ValueError('unsafe opaque output reference')
    def safe_metadata(self)->dict:
        return {"command_id":self.command_id,"kind":self.kind.value,"session_id":str(self.session_id),
                "turn_id":int(self.turn_id),"generation_id":int(self.generation_id),
                "code":self.code.value,"attempts":self.attempts,"output_ref":self.output_ref}

@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    kind: AdapterKind
    state: AdapterState
    circuit: CircuitState
    queued: int
    in_flight: int
    completed: int
    last_error_code: str | None
    observed_mono_ns: int
    mock_only: bool = True
    def safe_metadata(self)->dict:
        return {"kind":self.kind.value,"state":self.state.value,"circuit":self.circuit.value,
                "queued":self.queued,"in_flight":self.in_flight,"completed":self.completed,
                "last_error_code":self.last_error_code,"observed_mono_ns":self.observed_mono_ns,
                "mock_only":self.mock_only}

class LifecyclePort(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def health(self) -> HealthSnapshot: ...
    async def submit(self, command:SyntheticCommand) -> AdapterReceipt: ...
    async def tick(self) -> tuple[SyntheticResult,...]: ...
