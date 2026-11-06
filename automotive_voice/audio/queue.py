"""Bounded per-session metadata queue; capacity/sequence/generation gates.

No payloads or sockets. Stale buffered metadata is revalidated at dequeue;
there is no atomic guarantee with external PBX writes (final phase HOLD).
"""
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.core.session import State
from .contracts import AudioChunkMetadata

@dataclass(frozen=True, slots=True)
class MediaReceipt:
    accepted: bool
    reason: str
    pending_chunks: int
    pending_ms: int

class MediaBuffer:
    def __init__(self, manager: SessionManager, *, max_chunks_per_session: int = 64,
                 max_ms_per_session: int = 2000, max_seen_per_session: int = 256):
        for value in (max_chunks_per_session, max_ms_per_session, max_seen_per_session):
            if type(value) is not int or value < 1: raise ValueError('positive bounds required')
        self.manager=manager
        self.max_chunks_per_session=max_chunks_per_session
        self.max_ms_per_session=max_ms_per_session
        self.max_seen_per_session=max_seen_per_session
        self._queues: dict[str, deque[AudioChunkMetadata]]={}
        self._locks: dict[str,asyncio.Lock]={}
        self._expected: dict[tuple[str,int,int,str],int]={}
        self._seen: dict[tuple[str,int,int,str,int],AudioChunkMetadata]={}
        self._seen_fifo: dict[str,deque[tuple[str,int,int,str,int]]]={}
        self._blocked: set[str]=set()
        self._registry_lock=asyncio.Lock()

    async def _lock(self,sid: str) -> asyncio.Lock:
        async with self._registry_lock:
            return self._locks.setdefault(sid,asyncio.Lock())

    async def _active(self,item: AudioChunkMetadata) -> bool:
        try:
            snap=await self.manager.snapshot(str(item.session_id))
            token=await self.manager.current_token(str(item.session_id))
            return snap.state==State.SPEAKING and snap.turn_id==item.turn_id and snap.generation_id==item.generation_id and not token.cancelled and token.generation_id==item.generation_id
        except (LookupError, ValueError): return False

    def _receipt(self,sid: str,ok: bool,reason:str) -> MediaReceipt:
        q=self._queues.get(sid,())
        return MediaReceipt(ok,reason,len(q),sum(x.duration_ms for x in q))

    async def enqueue(self,item: AudioChunkMetadata) -> MediaReceipt:
        if not isinstance(item,AudioChunkMetadata): raise TypeError('AudioChunkMetadata required')
        sid=str(item.session_id)
        lock=await self._lock(sid)
        async with lock:
            if sid in self._blocked: return self._receipt(sid,False,'flush_pending')
            if not await self._active(item): return self._receipt(sid,False,'stale_generation_or_state')
            key=(sid,int(item.turn_id),int(item.generation_id),item.stream_id)
            replay_key=(*key,item.seq)
            old=self._seen.get(replay_key)
            if old is not None:
                return self._receipt(sid,old==item,'duplicate_ignored' if old==item else 'conflicting_replay')
            expected=self._expected.get(key,0)
            if item.seq!=expected:
                return self._receipt(sid,False,'sequence_gap' if item.seq>expected else 'stale_sequence')
            q=self._queues.setdefault(sid,deque())
            if len(q)>=self.max_chunks_per_session or sum(x.duration_ms for x in q)+item.duration_ms>self.max_ms_per_session:
                return self._receipt(sid,False,'backpressure')
            q.append(item);self._expected[key]=expected+1;self._seen[replay_key]=item
            fifo=self._seen_fifo.setdefault(sid,deque());fifo.append(replay_key)
            while len(fifo)>self.max_seen_per_session:
                self._seen.pop(fifo.popleft(),None)
            return self._receipt(sid,True,'queued')

    async def pop_next(self,sid:str) -> AudioChunkMetadata | None:
        lock=await self._lock(sid)
        async with lock:
            if sid in self._blocked: return None
            q=self._queues.setdefault(sid,deque())
            while q:
                item=q.popleft()
                if await self._active(item): return item
            return None


    async def return_front(self,item: AudioChunkMetadata)->bool:
        """Restore a popped chunk if a mock transport rejects before delivery.

        Caller must retry; no sequence counter changes. Never revive stale media.
        """
        sid=str(item.session_id)
        lock=await self._lock(sid)
        async with lock:
            if sid in self._blocked or not await self._active(item):return False
            q=self._queues.setdefault(sid,deque())
            if len(q)>=self.max_chunks_per_session or sum(x.duration_ms for x in q)+item.duration_ms>self.max_ms_per_session:return False
            if q and q[0].seq <= item.seq and q[0].stream_id==item.stream_id and q[0].generation_id==item.generation_id:return False
            q.appendleft(item)
            return True

    async def discard_stale(self,sid: str) -> int:
        lock=await self._lock(sid)
        async with lock:
            q=self._queues.setdefault(sid,deque())
            kept=deque()
            for item in q:
                if await self._active(item): kept.append(item)
            count=len(q)-len(kept);self._queues[sid]=kept
            return count

    async def begin_flush(self,sid:str) -> int:
        """Local queue invalidation, deliberately NOT a PBX ACK."""
        lock=await self._lock(sid)
        async with lock:
            self._blocked.add(sid)
            q=self._queues.setdefault(sid,deque())
            n=len(q);q.clear();return n

    async def end_flush(self,sid:str):
        lock=await self._lock(sid)
        async with lock: self._blocked.discard(sid)

    async def close(self,sid:str):
        lock=await self._lock(sid)
        async with lock:
            self._blocked.add(sid)
            self._queues.setdefault(sid,deque()).clear()

    async def metrics(self,sid:str) -> MediaReceipt:
        lock=await self._lock(sid)
        async with lock:return self._receipt(sid,True,'snapshot')
