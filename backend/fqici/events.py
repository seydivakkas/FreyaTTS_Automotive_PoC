import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID, NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Closure(Payload):
    kind: Literal["session.closed", "session.recovered"]
    reason: Literal["normal", "disconnect", "transport_error", "unclean_restart"]
    state: Literal["ENDED", "FAILED", "UNKNOWN"]


class ToolTimeout(Payload):
    kind: Literal["tool.timeout"]
    operation_id: UUID
    attempt_id: UUID
    elapsed_ms: Annotated[int, Field(strict=True, ge=0)]


class ToolCommit(Payload):
    kind: Literal["tool.commit_observed"]
    operation_id: UUID
    commit_state: Literal["COMMITTED", "NOT_COMMITTED"]


class EvidenceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["fqici.event.v1"] = "fqici.event.v1"
    policy_version: Literal["fqici.metadata.v1"] = "fqici.metadata.v1"
    producer: Literal["session_journal", "startup_recovery", "tool_gateway"]
    source_event_id: UUID
    session_id: UUID
    occurred_at: datetime
    clock_domain_id: UUID | None = None
    monotonic_offset_ms: Annotated[int, Field(strict=True, ge=0)] | None = None
    payload: Annotated[Closure | ToolTimeout | ToolCommit, Field(discriminator="kind")]

    @model_validator(mode="after")
    def verify_source(self):
        if self.occurred_at.utcoffset() is None:
            raise ValueError("event time requires an offset")
        if (self.clock_domain_id is None) != (self.monotonic_offset_ms is None):
            raise ValueError("monotonic time requires a clock domain")
        if isinstance(self.payload, Closure) != (self.producer in {"session_journal", "startup_recovery"}):
            raise ValueError("event kind is not allowed for this producer")
        if isinstance(self.payload, Closure) and (
            (self.payload.kind == "session.recovered") != (self.payload.reason == "unclean_restart")
        ):
            raise ValueError("recovery requires restart evidence")
        if self.producer == "startup_recovery" and (
            self.payload.kind != "session.recovered" or self.payload.state != "UNKNOWN"
        ):
            raise ValueError("missing journal cannot establish a terminal state")
        return self

    @property
    def id(self) -> str:
        return str(uuid5(NAMESPACE_URL, f"freya:fqici:{self.producer}:{self.source_event_id}"))

    def evidence(self) -> dict:
        value = self.model_dump(mode="json")
        value["occurred_at"] = self.occurred_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
        return value


def elapsed_ms(start: EvidenceEvent, end: EvidenceEvent) -> int | None:
    if (
        start.session_id != end.session_id
        or start.clock_domain_id is None
        or start.clock_domain_id != end.clock_domain_id
    ):
        return None
    delta = end.monotonic_offset_ms - start.monotonic_offset_ms
    return delta if delta >= 0 else None
