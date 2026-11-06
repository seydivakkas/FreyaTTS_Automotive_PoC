"""Bounded deterministic circuit breaker; exactly one HALF_OPEN probe at a time."""
from __future__ import annotations
from automotive_voice.adapters.lifecycle.contracts import CircuitState
class CircuitBreaker:
    def __init__(self, threshold:int=2, cooldown_ns:int=1_000_000_000):
        if type(threshold) is not int or threshold<1 or type(cooldown_ns) is not int or cooldown_ns<1:
            raise ValueError('positive circuit threshold and cooldown required')
        self.threshold=threshold;self.cooldown_ns=cooldown_ns
        self.state=CircuitState.CLOSED;self.failures=0;self.opened_at_ns=None;self.probe_in_progress=False
    def allow(self,now_ns:int)->bool:
        if self.state is CircuitState.OPEN:
            if now_ns-self.opened_at_ns < self.cooldown_ns:return False
            self.state=CircuitState.HALF_OPEN;self.probe_in_progress=False
        if self.state is CircuitState.HALF_OPEN:
            if self.probe_in_progress:return False
            self.probe_in_progress=True
        return True
    def success(self):
        self.state=CircuitState.CLOSED;self.failures=0;self.opened_at_ns=None;self.probe_in_progress=False
    def failure(self,now_ns:int):
        self.failures+=1
        if self.state is CircuitState.HALF_OPEN or self.failures>=self.threshold:
            self.state=CircuitState.OPEN;self.opened_at_ns=now_ns
        self.probe_in_progress=False
    def abandon_probe(self):
        if self.state is CircuitState.HALF_OPEN:self.probe_in_progress=False
