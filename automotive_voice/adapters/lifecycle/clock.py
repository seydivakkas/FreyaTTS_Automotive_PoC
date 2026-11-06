"""Explicit virtual monotonic clock; no wall clock, await sleep or background scheduling."""
from __future__ import annotations
class MockClock:
    def __init__(self, start_ns:int=0):
        if type(start_ns) is not int or start_ns < 0: raise ValueError('nonnegative start_ns required')
        self._now=start_ns
    def now_ns(self)->int:return self._now
    def advance(self, delta_ns:int)->int:
        if type(delta_ns) is not int or delta_ns < 0:raise ValueError('nonnegative delta_ns required')
        if self._now+delta_ns > 2**63-1:raise OverflowError('monotonic clock overflow')
        self._now+=delta_ns
        return self._now
