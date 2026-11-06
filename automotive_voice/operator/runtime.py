"""M08 read-model and operator actions wired into genuine M01-M07 mock contracts.

Only fake adapters, opaque references, and synthetic control. No microphone, model,
phone, audio payload, SIP, external network or real customer data.
"""
from __future__ import annotations
import asyncio
import csv
import json
from collections import deque
from pathlib import Path
from uuid import uuid4
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.core.session import State
from automotive_voice.conversation.reducer import ConversationReducer, Decision
from automotive_voice.conversation.signals import ConversationSignal, SignalKind
from automotive_voice.audio.queue import MediaBuffer
from automotive_voice.audio.coordinator import MediaCoordinator
from automotive_voice.telephony.transport import FakeTransport
from automotive_voice.adapters.lifecycle.clock import MockClock
from automotive_voice.adapters.lifecycle.supervisor import AdapterSupervisor
from .review_store import PronunciationReviewStore, ReviewError
from automotive_voice.readiness.contracts import AdapterConfig,AdapterType,OfflineReadiness
from automotive_voice.e2e import ScenarioRunner, SCENARIOS

ACTIONS={
    'open': SignalKind.SESSION_OPENED,
    'vad': SignalKind.VAD_SPEECH_STARTED,
    'transcript': SignalKind.TRANSCRIPT_FINAL,
    'llm': SignalKind.LLM_RESPONSE_READY,
    'playout': SignalKind.PLAYOUT_FINISHED,
    'hangup': SignalKind.HANGUP,
    'handoff': SignalKind.HANDOFF_REQUESTED,
}

class ConsoleRuntime:
    def __init__(self, data_root: str | Path, overlay_path: str | Path):
        root=Path(data_root)
        self.review=PronunciationReviewStore(root/'a01yt'/'a01yt_v05_readonly.sqlite3',overlay_path)
        self.golden_summary=json.loads((root/'reports'/'m04_320_summary.json').read_text(encoding='utf-8'))
        with (root/'reports'/'m04_320_compare.csv').open(encoding='utf-8-sig',newline='') as stream:
            self.golden_cases=list(csv.DictReader(stream))
        self.clock=MockClock()
        self.manager=SessionManager(EventBus())
        self.reducer=ConversationReducer(self.manager)
        self.buffer=MediaBuffer(self.manager)
        self.transport=FakeTransport(adapter_id='m08-test-only-fake-pbx')
        self.media=MediaCoordinator(self.reducer,self.buffer,self.transport)
        self.supervisor=AdapterSupervisor(self.manager,self.clock,media=self.media)
        self.sessions:list[str]=[]
        self.activities=deque(maxlen=160)
        self._lock=asyncio.Lock()
        self._ready=False
        self._reference_index=0
        self.scenario_reports=deque(maxlen=12)

    async def initialize(self):
        async with self._lock:
            if not self._ready:
                await self.supervisor.start_all()
                self._ready=True

    def _activity(self,category,session,decision,reason):
        self.activities.appendleft({'clock_ms':self.clock.now_ns()//1_000_000,
                 'kind':category,'session':session,'decision':decision,'reason':reason})

    async def _signal(self,kind:SignalKind,sid:str):
        snap=await self.reducer.try_snapshot(sid)
        if kind is SignalKind.SESSION_OPENED:
            turn=generation=seq=0
        else:
            if snap is None:raise ValueError('unknown_session')
            turn=int(snap.turn_id);generation=int(snap.generation_id)
            seq=await self.reducer.expected_sequence(sid)
        reference=None
        if kind in (SignalKind.TRANSCRIPT_FINAL,SignalKind.LLM_RESPONSE_READY):
            self._reference_index+=1
            reference=f'm08_synthetic_ref_{self._reference_index:05d}'
        self.clock.advance(1_000_000)
        signal=ConversationSignal.create(kind,sid,turn,generation,seq,
                    reference=reference,mono_ns=self.clock.now_ns())
        outcome=await self.reducer.handle(signal)
        self._activity(kind.value,sid,outcome.decision.value,outcome.reason)
        accepted_all=True
        for eff in outcome.effects:
            receipt=await self.supervisor.dispatch_effect(eff)
            accepted_all=accepted_all and receipt.accepted
            self._activity('effect:'+eff.kind.value,sid,
                      'accepted' if receipt.accepted else 'rejected',receipt.reason)
        # Effects are handed to the supervisor, but not durably committed. Drain the
        # volatile M02 hand-off queue only after successful mock dispatch, per effect.
        if outcome.effects and accepted_all:
            # Explicitly avoid counting a delivery to a real transport.
            await self.reducer.drain_effects(sid,len(outcome.effects))
        return {'decision':outcome.decision.value,'reason':outcome.reason,
                'state':outcome.state.value if outcome.state else None}

    async def act(self,action:str,sid:str|None=None,**kwargs):
        async with self._lock:
            if action=='open':
                sid='sim-'+uuid4().hex[:12]
                result=await self._signal(SignalKind.SESSION_OPENED,sid)
                if result['decision']==Decision.APPLIED.value:self.sessions.insert(0,sid)
                return {'session_id':sid,**result}
            if action=='tick':
                delta=kwargs.get('delta_ms',20)
                if type(delta) is not int or delta not in (20,100,1600):
                    raise ValueError('invalid_tick_delta')
                self.clock.advance(delta*1_000_000)
                ticks=await self.supervisor.tick_all()
                count=sum(len(v) for v in ticks.values())
                expired=await self.reducer.poll_flush_timeouts(self.clock.now_ns())
                for item_sid,out in expired.items():
                    self._activity('flush_timeout',item_sid,out.decision.value,out.reason)
                    for eff in out.effects:
                        receipt=await self.supervisor.dispatch_effect(eff)
                        self._activity('effect:'+eff.kind.value,item_sid,'accepted' if receipt.accepted else 'rejected',receipt.reason)
                self._activity('clock_advance','-', 'ok',f'{delta}ms; {count} mock results')
                return {'advanced_ms':delta,'results':count,'flush_timeouts':len(expired)}
            if action=='run_scenario':
                name=kwargs.get('scenario')
                if type(name) is not str or name not in SCENARIOS:
                    raise ValueError('unknown_scenario')
                report=(await ScenarioRunner().run(name)).to_dict()
                self.scenario_reports.appendleft(report)
                self._activity('M09 scenario','-', 'passed' if report['passed'] else 'failed',name)
                return {'scenario':name,'passed':report['passed'],'checks':report['checks']}
            if action=='review':
                result=self.review.decide(kwargs.get('annotation_id',''),
                    kwargs.get('decision',''),reviewer=kwargs.get('reviewer',''),
                    reason_code=kwargs.get('reason_code',''))
                self._activity('review','-',result['decision'],result['annotation_id'])
                return {'annotation_id':result['annotation_id'],'decision':result['decision']}
            if sid not in self.sessions:raise ValueError('unknown_console_session')
            if action=='fake_ack':
                pending=await self.reducer.pending_flush_id(sid)
                if not pending:raise ValueError('no_pending_flush')
                # Explicit confirmation by M06 fake transport is the only valid path.
                ack=await self.transport.confirm_flush(sid,pending)
                if ack is None:raise ValueError('fake_adapter_did_not_confirm')
                self.clock.advance(1_000_000)
                outcome=await self.media.accept_fake_ack(ack,sequence=await self.reducer.expected_sequence(sid),mono_ns=self.clock.now_ns())
                self._activity('FAKE_ACK_only',sid,outcome.decision.value,outcome.reason)
                for eff in outcome.effects:
                    receipt=await self.supervisor.dispatch_effect(eff)
                    self._activity('effect:'+eff.kind.value,sid,'accepted' if receipt.accepted else 'rejected',receipt.reason)
                if outcome.effects: await self.reducer.drain_effects(sid,len(outcome.effects))
                return {'decision':outcome.decision.value,'reason':outcome.reason,
                        'real_pbx_proven':False,'state':outcome.state.value}
            if action in ('xoff','xon'):
                (self.transport.xoff if action=='xoff' else self.transport.xon)(sid)
                self._activity('transport_'+action,sid,'applied','fake_transport_only')
                return {'decision':'applied','reason':'fake_transport_only'}
            kind=ACTIONS.get(action)
            if kind is None or kind is SignalKind.SESSION_OPENED:raise ValueError('unsupported_action')
            return await self._signal(kind,sid)

    async def snapshot(self):
        async with self._lock:
            sessions=[]
            for sid in self.sessions[:50]:
                snap=await self.reducer.try_snapshot(sid)
                if snap is None:continue
                audit=await self.reducer.audit_records(sid)
                m=await self.buffer.metrics(sid)
                t=self.transport.stats(sid)
                sessions.append({'session_id':sid,'state':snap.state.value,
                      'turn_id':int(snap.turn_id),'generation_id':int(snap.generation_id),
                      'last_sequence':snap.last_sequence,'pending_events':snap.pending_events,
                      'pending_flush_id':await self.reducer.pending_flush_id(sid),
                      'queued_chunks':m.pending_chunks,'queued_ms':m.pending_ms,
                      'transport_queued':t.queued_at_transport,'transport_paused':t.paused,
                      'audit_count':len(audit)})
            counts={'sessions':len(self.sessions),'active':sum(s['state'] not in ('ENDED','FAILED') for s in sessions),
                'waiting_flush':sum(bool(s['pending_flush_id']) for s in sessions),
                'mock_tts_results':sum(h.completed for h in self.supervisor.health().values())}
            return {'mode':'OFFLINE MOCK ONLY','simulation_time_ms':self.clock.now_ns()//1_000_000,
                 'counts':counts,'sessions':sessions,
                 'scenario_catalog':list(SCENARIOS),'scenario_reports':list(self.scenario_reports),
                 'adapters':[x.safe_metadata() for x in self.supervisor.health().values()],
                 'timeline':list(self.activities),'golden_summary':self.golden_summary,
                 'golden_cases':self.golden_cases,'sources':self.review.sources(),
                 'annotations':self.review.items(),
                 'audio_bytes_generated':0,'real_pbx_connected':False,
                 'production_ready':False,
                 'm10_readiness':OfflineReadiness.evaluate([
                     AdapterConfig(AdapterType.FREYA,'freyatts-local',model_path=str(Path.cwd()/'models'/'freya')),
                     AdapterConfig(AdapterType.STT,'whisper-local',model_path=str(Path.cwd()/'models'/'whisper')),
                     AdapterConfig(AdapterType.LLM,'ollama-local',endpoint='http://127.0.0.1:11434'),
                     AdapterConfig(AdapterType.PBX,'asterisk-websocket',endpoint='ws://127.0.0.1:8088',codec='slin16',sample_rate_hz=16000)]),
                 'durable_outbox_in_console':False}
