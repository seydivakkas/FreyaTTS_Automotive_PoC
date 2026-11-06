"""M05 clause -> fake TTS -> M06 20ms PCM metadata, without any sound bytes.

Fake TTS success is NOT proof of TTS synthesis; only an explicit virtual-clock
completion yields synthetic metadata. This stage does not emit fake PBX ACKs.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.core.session import State
from automotive_voice.prosody.mock_tts import MockTTS
from automotive_voice.prosody.contracts import TTSInput
from automotive_voice.audio.queue import MediaBuffer
from automotive_voice.audio.contracts import MediaFormat,Codec,AudioChunkMetadata
from .clock import MockClock
from .runtime import SyntheticAdapter
from .contracts import AdapterKind,Deadline,ResultCode,SyntheticCommand,SyntheticResult

@dataclass(frozen=True,slots=True)
class StreamReceipt:
    accepted:bool
    reason:str
    command_id:str|None=None

class SyntheticStreamBridge:
    def __init__(self,manager:SessionManager,clock:MockClock,tts_adapter:SyntheticAdapter,
                 mock_tts:MockTTS,buffer:MediaBuffer,*,deadline_budget_ns:int=3_000_000_000,
                 seen_limit:int=2048,max_pending:int=64):
        if tts_adapter.kind is not AdapterKind.TTS:raise ValueError('TTS adapter required')
        if type(seen_limit) is not int or seen_limit<1 or type(max_pending) is not int or max_pending<1 or type(deadline_budget_ns) is not int or deadline_budget_ns<1:
            raise ValueError('invalid bounds')
        self.manager=manager;self.clock=clock;self.adapter=tts_adapter;self.mock_tts=mock_tts;self.buffer=buffer
        self.deadline_budget_ns=deadline_budget_ns;self.seen_limit=seen_limit;self.max_pending=max_pending
        self._held:TTSInput|None=None
        self._pending:dict[str,TTSInput]={}
        self._consumed:set[str]=set();self._consumed_order:deque[str]=deque()
        self._chunk_seq:dict[tuple[str,int,int],int]={}
    def _command_id(self,item:TTSInput)->str:
        return f'clause:{item.session_id}:{int(item.turn_id)}:{int(item.generation_id)}:{item.clause_index}'
    async def submit_next_clause(self)->StreamReceipt:
        if len(self._pending)>=self.max_pending:return StreamReceipt(False,'bridge_backpressure')
        item=self._held
        if item is None:item=await self.mock_tts.pop_next()
        if item is None:return StreamReceipt(False,'no_active_clause')
        sid=str(item.session_id);key=self._command_id(item)
        if key in self._consumed or key in self._pending:
            self._held=None
            return StreamReceipt(False,'duplicate_clause',key)
        seq=await self.adapter.expected_sequence(sid)
        cmd=SyntheticCommand(key,AdapterKind.TTS,item.session_id,item.turn_id,item.generation_id,
                             seq,f'clause_sha:{item.text_sha256[:32]}',
                             Deadline(self.clock.now_ns()+self.deadline_budget_ns))
        receipt=await self.adapter.submit(cmd)
        if receipt.accepted and receipt.reason=='accepted_mock':
            self._pending[key]=item;self._held=None
        elif receipt.reason in ('backpressure','adapter_not_ready','stale_sequence','sequence_gap'):
            self._held=item
        else:
            self._held=None  # stale/deadline/sequence failures are fail-closed
        return StreamReceipt(receipt.accepted,receipt.reason,key)
    async def materialize_metadata(self,result:SyntheticResult)->StreamReceipt:
        """A successful fake TTS callback maps to one 20ms metadata frame, never WAV."""
        if not isinstance(result,SyntheticResult) or result.kind is not AdapterKind.TTS:
            return StreamReceipt(False,'wrong_adapter_result')
        item=self._pending.get(result.command_id)
        if item is None:return StreamReceipt(False,'unknown_or_replayed_completion',result.command_id)
        if self.adapter.read_result(result.command_id)!=result:
            return StreamReceipt(False,'unverified_fake_completion',result.command_id)
        if result.code is not ResultCode.OK:
            self._pending.pop(result.command_id,None)
            return StreamReceipt(False,f'fake_tts_{result.code.value}',result.command_id)
        sid=str(item.session_id)
        snap=await self.manager.snapshot(sid)
        if (snap.state is not State.SPEAKING or snap.turn_id!=item.turn_id or
                snap.generation_id!=item.generation_id or
                not await self.manager.accepts_chunk(sid,int(item.generation_id))):
            self._pending.pop(result.command_id,None)
            return StreamReceipt(False,'stale_completion',result.command_id)
        key=(sid,int(item.turn_id),int(item.generation_id));seq=self._chunk_seq.get(key,0)
        chunk=AudioChunkMetadata(item.session_id,item.turn_id,item.generation_id,
             f'mock-tts:{int(item.turn_id)}:{int(item.generation_id)}',seq,320,20,
             self.clock.now_ns(),MediaFormat(Codec.PCM_S16LE,16000),item.clause_index)
        receipt=await self.buffer.enqueue(chunk)
        if not receipt.accepted:return StreamReceipt(False,receipt.reason,result.command_id)
        self._chunk_seq[key]=seq+1
        self._pending.pop(result.command_id,None)
        self._consumed.add(result.command_id);self._consumed_order.append(result.command_id)
        while len(self._consumed_order)>self.seen_limit:
            self._consumed.discard(self._consumed_order.popleft())
        return StreamReceipt(True,'mock_metadata_queued',result.command_id)
    def pending_count(self)->int:return len(self._pending)
    def abandon_generation(self,sid:str):
        if self._held is not None and str(self._held.session_id)==sid:self._held=None
        for key,item in list(self._pending.items()):
            if str(item.session_id)==sid:self._pending.pop(key,None)
