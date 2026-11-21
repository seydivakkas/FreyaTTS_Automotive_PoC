"""M07 deterministic fake adapter runtime: retry, fault scripts, cancellation, bounded work.

No actual STT/TTS/LLM/telephony call; all outputs are opaque synthetic refs.
"""
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.core.session import State
from .clock import MockClock
from .breaker import CircuitBreaker
from .contracts import (AdapterKind,AdapterState,AdapterReceipt,SyntheticCommand,SyntheticResult,
                        HealthSnapshot,RetryPolicy,ResultCode)

@dataclass(slots=True)
class _Work:
    command: SyntheticCommand
    attempts: int=0
    ready_at_ns: int=0
    complete_at_ns: int | None=None
    outcome: str='ok'

class SyntheticAdapter:
    """Reusable fake STT/TTS/LLM/telephony adapter. Single reactor lock, no real I/O.

    `tick` must be explicitly called after advancing the MockClock. Faults are
    preloaded in attempt order. Completion always revalidates the M01 token.
    """
    def __init__(self,kind:AdapterKind,manager:SessionManager,clock:MockClock,*,
                 retry:RetryPolicy|None=None,max_pending:int=32,max_inflight:int=2,
                 latency_ns:int=20_000_000,replay_limit:int=256,
                 breaker_threshold:int=3,breaker_cooldown_ns:int=250_000_000):
        if not isinstance(kind,AdapterKind):raise TypeError('kind required')
        for value in (max_pending,max_inflight,replay_limit):
            if type(value) is not int or value<1:raise ValueError('positive capacities required')
        if type(latency_ns) is not int or latency_ns<0:raise ValueError('nonnegative latency required')
        self.kind=kind;self.manager=manager;self.clock=clock
        self.retry=retry or RetryPolicy();self.max_pending=max_pending
        self.max_inflight=max_inflight;self.latency_ns=latency_ns;self.replay_limit=replay_limit
        self.breaker=CircuitBreaker(breaker_threshold,breaker_cooldown_ns)
        self.state=AdapterState.CREATED;self.last_error_code=None
        self._jobs:dict[str,_Work]={};self._inflight:set[str]=set();self._terminal:dict[str,tuple[SyntheticCommand,SyntheticResult]]={}
        self._terminal_order:deque[str]=deque();self._last_seq:dict[str,int]={}
        self._faults:dict[str,tuple[str,...]]={};self._lock=asyncio.Lock()
        self._disconnected=False
    def inject_faults(self,command_id:str,attempts:list[str]|tuple[str,...]):
        if not isinstance(command_id,str) or not isinstance(attempts,(list,tuple)) or any(x not in ('ok','transient','permanent','disconnect','timeout') for x in attempts):
            raise ValueError('supported scripted faults: ok/transient/permanent/disconnect/timeout')
        self._faults[command_id]=tuple(attempts)
    def health(self)->HealthSnapshot:
        return HealthSnapshot(self.kind,self.state,self.breaker.state,
             len(self._jobs)-len(self._inflight),len(self._inflight),len(self._terminal),self.last_error_code,self.clock.now_ns())
    async def start(self):
        async with self._lock:
            if self.state is AdapterState.READY:return
            if self.state not in (AdapterState.CREATED,AdapterState.STOPPED,AdapterState.FAILED,AdapterState.DEGRADED):
                raise RuntimeError('invalid adapter start transition')
            self.state=AdapterState.STARTING
            # Explicit virtual start, no real side effect.
            self._disconnected=False
            self.breaker.success()
            self.last_error_code=None;self.state=AdapterState.READY
    async def reconnect(self):
        async with self._lock:
            if self.state is not AdapterState.DEGRADED:raise RuntimeError('reconnect requires degraded state')
            self._disconnected=False;self.state=AdapterState.READY
            self.breaker.success();self.last_error_code=None
    async def stop(self):
        async with self._lock:
            if self.state is AdapterState.STOPPED:return
            self.state=AdapterState.STOPPING
            for job in tuple(self._jobs.values()):self._finish(job,ResultCode.CANCELLED)
            self._inflight.clear();self._disconnected=False;self.state=AdapterState.STOPPED
    async def _active(self,cmd:SyntheticCommand)->bool:
        try:
            snap=await self.manager.snapshot(str(cmd.session_id))
            tok=await self.manager.current_token(str(cmd.session_id))
            return (snap.turn_id==cmd.turn_id and snap.generation_id==cmd.generation_id
                    and snap.state not in (State.IDLE,State.ENDED,State.FAILED,State.HANDOFF)
                    and not tok.cancelled and tok.generation_id==cmd.generation_id)
        except (LookupError,ValueError):return False
    async def expected_sequence(self,sid:str)->int:
        """Authoritative sequence allocator for this adapter/session."""
        async with self._lock:
            return self._last_seq.get(sid,-1)+1

    async def submit(self,cmd:SyntheticCommand)->AdapterReceipt:
        if not isinstance(cmd,SyntheticCommand) or cmd.kind is not self.kind:raise TypeError('matching synthetic command required')
        async with self._lock:
            old=self._jobs.get(cmd.command_id)
            if old is not None:
                return AdapterReceipt(old.command==cmd,'duplicate_ignored' if old.command==cmd else 'conflicting_replay',cmd.command_id)
            terminal=self._terminal.get(cmd.command_id)
            if terminal is not None:
                return AdapterReceipt(terminal[0]==cmd,'duplicate_ignored' if terminal[0]==cmd else 'conflicting_replay',cmd.command_id)
            if self.state is not AdapterState.READY:return AdapterReceipt(False,'adapter_not_ready',cmd.command_id)
            if cmd.deadline.expired(self.clock.now_ns()):return AdapterReceipt(False,'deadline_expired',cmd.command_id)
            if not await self._active(cmd):return AdapterReceipt(False,'stale_generation',cmd.command_id)
            sid=str(cmd.session_id)
            expect=self._last_seq.get(sid,-1)+1
            if cmd.sequence != expect:
                return AdapterReceipt(False,'sequence_gap' if cmd.sequence>expect else 'stale_sequence',cmd.command_id)
            if len(self._jobs)>=self.max_pending:return AdapterReceipt(False,'backpressure',cmd.command_id)
            self._last_seq[sid]=cmd.sequence
            self._jobs[cmd.command_id]=_Work(cmd,ready_at_ns=self.clock.now_ns())
            return AdapterReceipt(True,'accepted_mock',cmd.command_id)
    def _finish(self,job:_Work,code:ResultCode)->SyntheticResult:
        cmd=job.command
        output=f'mock-{cmd.kind.value}:{cmd.command_id}' if code is ResultCode.OK else None
        result=SyntheticResult(cmd.command_id,cmd.kind,cmd.session_id,cmd.turn_id,cmd.generation_id,code,job.attempts,output)
        self._jobs.pop(cmd.command_id,None)
        if cmd.command_id in self._inflight:self.breaker.abandon_probe()
        self._inflight.discard(cmd.command_id)
        self._terminal[cmd.command_id]=(cmd,result);self._terminal_order.append(cmd.command_id)
        while len(self._terminal_order)>self.replay_limit:
            self._terminal.pop(self._terminal_order.popleft(),None)
        return result
    async def cancel_session(self,sid:str)->tuple[SyntheticResult,...]:
        async with self._lock:
            return tuple(self._finish(job,ResultCode.CANCELLED) for job in list(self._jobs.values()) if str(job.command.session_id)==sid)
    async def tick(self)->tuple[SyntheticResult,...]:
        async with self._lock:
            now=self.clock.now_ns();result=[]
            # Drop expired/stale work first, including in-flight responses.
            for job in list(self._jobs.values()):
                if not await self._active(job.command):result.append(self._finish(job,ResultCode.STALE))
                elif job.command.deadline.expired(now):result.append(self._finish(job,ResultCode.TIMED_OUT))
            # Consume all ready in-flight completions. The scripted fault resolves
            # only here, so stale callbacks can never leak an old generation.
            for cid in tuple(self._jobs):
                if cid not in self._inflight:continue
                job=self._jobs.get(cid)
                if job is None or job.complete_at_ns is None or now<job.complete_at_ns:continue
                self._inflight.discard(cid);job.complete_at_ns=None
                if not await self._active(job.command):result.append(self._finish(job,ResultCode.STALE));self.breaker.abandon_probe();continue
                outcome=job.outcome
                if outcome=='ok':
                    self.breaker.success();result.append(self._finish(job,ResultCode.OK));continue
                self.last_error_code=outcome
                if outcome=='disconnect':
                    self._disconnected=True;self.state=AdapterState.DEGRADED
                    self.breaker.failure(now)
                elif outcome=='permanent':
                    self.breaker.failure(now)
                    result.append(self._finish(job,ResultCode.PERMANENT_FAILURE));continue
                elif outcome=='timeout':
                    self.breaker.failure(now)
                    result.append(self._finish(job,ResultCode.TIMED_OUT));continue
                else:self.breaker.failure(now)
                if not job.command.idempotent or job.attempts>=self.retry.max_attempts:
                    result.append(self._finish(job,ResultCode.DISCONNECTED if outcome=='disconnect' else ResultCode.RETRY_EXHAUSTED));continue
                job.ready_at_ns=now+self.retry.delay_after(job.attempts)
                if job.ready_at_ns>=job.command.deadline.mono_ns:
                    result.append(self._finish(job,ResultCode.TIMED_OUT))
            if self.state is not AdapterState.READY or self._disconnected:return tuple(result)
            slots=self.max_inflight-len(self._inflight)
            for job in list(self._jobs.values()):
                if slots<=0:break
                if job.complete_at_ns is not None or job.ready_at_ns>now:continue
                if not self.breaker.allow(now):break
                job.attempts+=1
                outcomes=self._faults.get(job.command.command_id,())
                job.outcome=outcomes[job.attempts-1] if job.attempts<=len(outcomes) else 'ok'
                job.complete_at_ns=now+self.latency_ns
                self._inflight.add(job.command.command_id);slots-=1
            # A zero-latency attempt is completed on the next explicit tick. This
            # preserves deterministic event-loop boundaries and cancellation gates.
            return tuple(result)
    def read_result(self,command_id:str)->SyntheticResult|None:
        pair=self._terminal.get(command_id)
        return pair[1] if pair else None
