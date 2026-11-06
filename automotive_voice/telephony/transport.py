"""M06 transport ports: fake-only behavior; Asterisk JSON is a dry-run encoder.

Sending FLUSH_MEDIA is not evidence of PBX-side completion. No real sockets.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from collections import deque
from automotive_voice.audio.contracts import AudioChunkMetadata, FlushRequest, FlushAck

class TransportPort(Protocol):
    async def send_metadata(self, chunk: AudioChunkMetadata) -> bool: ...
    async def request_flush(self, request: FlushRequest) -> None: ...

@dataclass(frozen=True, slots=True)
class FakeTransportStats:
    sent: int
    queued_at_transport: int
    paused: bool

class FakeTransport:
    """Explicit synthetic playback queue; confirm_flush() models a fake ACK."""
    def __init__(self, *, max_items: int = 128, adapter_id: str = 'fake-asterisk'):
        if type(max_items) is not int or max_items < 1: raise ValueError('max_items must be positive')
        self.max_items=max_items;self.adapter_id=adapter_id
        self._media: dict[str,deque[AudioChunkMetadata]]={}
        self._pending: dict[str,FlushRequest]={}
        self._xoff: set[str]=set()
        self._closed: set[str]=set()
        self._confirmed: dict[str,FlushAck]={}
        self._sent=0

    async def send_metadata(self,chunk:AudioChunkMetadata)->bool:
        sid=str(chunk.session_id)
        if not isinstance(chunk,AudioChunkMetadata):raise TypeError('AudioChunkMetadata required')
        if sid in self._xoff or sid in self._closed or sid in self._pending: return False
        q=self._media.setdefault(sid,deque())
        if len(q)>=self.max_items:return False
        q.append(chunk);self._sent+=1
        return True

    async def request_flush(self,request:FlushRequest)->None:
        sid=str(request.session_id)
        if sid in self._pending:
            if self._pending[sid]!=request: raise ValueError('concurrent or conflicting flush')
            return
        self._pending[sid]=request

    async def confirm_flush(self,sid:str,request_id:str)->FlushAck | None:
        """Explicit test-only proof; does NOT represent PBX confirmation."""
        request=self._pending.get(sid)
        if request is None or request.flush_request_id != request_id:return None
        self._media.setdefault(sid,deque()).clear()
        self._pending.pop(sid)
        ack=FlushAck(request.flush_request_id,request.session_id,request.turn_id,
                     request.generation_id,self.adapter_id,True,'fake')
        self._confirmed[request.flush_request_id]=ack
        return ack

    def has_confirmed(self,ack:FlushAck)->bool:
        return self._confirmed.get(ack.flush_request_id)==ack
    def consume_confirmation(self,ack:FlushAck)->None:
        if not self.has_confirmed(ack):raise ValueError('ACK not issued by this fake transport')
        self._confirmed.pop(ack.flush_request_id,None)
    def xoff(self,sid:str):self._xoff.add(sid)
    def xon(self,sid:str):
        if sid not in self._pending and sid not in self._closed:self._xoff.discard(sid)
    def can_send(self,sid:str)->bool:
        return sid not in self._xoff and sid not in self._closed and sid not in self._pending and len(self._media.get(sid,())) < self.max_items
    def stats(self,sid:str)->FakeTransportStats:
        return FakeTransportStats(self._sent,len(self._media.get(sid,())),sid in self._xoff or sid in self._closed or sid in self._pending)
    async def terminate(self,sid:str):
        self._media.setdefault(sid,deque()).clear()
        self._pending.pop(sid,None);self._xoff.add(sid);self._closed.add(sid)
        for key,ack in list(self._confirmed.items()):
            if str(ack.session_id)==sid:self._confirmed.pop(key,None)

class AsteriskCommandEncoder:
    """Validate/format commands only. Does not open a connection or acknowledge anything.

    Requires chan_websocket with JSON support (not all Asterisk builds).
    FLUSH_MEDIA may not emit a generic explicit ACK on every version. A later
    real adapter must verify version-specific correlation/queue-drain semantics.
    """
    @staticmethod
    def flush_json(request:FlushRequest)->dict:
        if not isinstance(request,FlushRequest):raise TypeError('FlushRequest required')
        return {'command':'FLUSH_MEDIA','correlation_id':request.flush_request_id}

    @staticmethod
    def hangup_json()->dict:
        return {'command':'HANGUP'}
