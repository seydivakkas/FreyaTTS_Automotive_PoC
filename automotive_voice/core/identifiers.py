"""Strongly checked, serializable identifiers. No model/network dependency."""
from __future__ import annotations
import re
from uuid import uuid4

_VALID_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

class SessionId(str):
    def __new__(cls, value: str) -> "SessionId":
        if not isinstance(value, str) or _VALID_SESSION.fullmatch(value) is None:
            raise ValueError("SessionId must be 1..128 safe ASCII characters")
        return str.__new__(cls, value)

    @classmethod
    def new(cls) -> "SessionId":
        return cls(str(uuid4()))

class _SequenceId(int):
    def __new__(cls, value: int):
        if (not isinstance(value, int) or isinstance(value, bool)) or value < 0 or value > 2**63 - 1:
            raise ValueError(f"{cls.__name__} must be a non-negative signed 64-bit integer")
        return int.__new__(cls, value)

class TurnId(_SequenceId):
    """Session-local conversational turn, starting at zero."""

class GenerationId(_SequenceId):
    """Session-local cancelable response generation, starting at zero."""
