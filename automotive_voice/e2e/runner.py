"""M09 integration of the ACTUAL M01–M08 contracts. No WAV, sockets, models, SIP or wall delays.

Each run constructs one M01 authority with M02–M07 adapters. Transcripts are
in memory in the test fixture and never copied into a trace or telemetry.
Completion of M03 business policy is distinct from readiness of a TTS clause.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.resilience.durable import DurableJournal, DurableSessionManager
from automotive_voice.core.session import State
from automotive_voice.conversation.reducer import ConversationReducer, Decision
from automotive_voice.conversation.signals import ConversationSignal, SignalKind
from automotive_voice.conversation.effects import EffectKind
from automotive_voice.dialogue import (ReferenceStore, DialoguePolicy, DialogueCoordinator, FakeCRM,
    FakeBookingService, VehicleRecord, PriceQuote, AccessContext, Availability, AppointmentSlot)
from automotive_voice.dialogue.models import BookingReceipt, Commitment
from automotive_voice.nlp.nlu import DeterministicNLU, ParseContext
from automotive_voice.nlp.bridge import NLUReferenceBridge
from automotive_voice.nlp.normalizer import TurkishAutomotiveNormalizer
from automotive_voice.prosody import ProsodyClausePlanner, MockTTS, ProsodyCoordinator
from automotive_voice.readiness.presentation import PolicySpeechPresenter
from automotive_voice.audio.queue import MediaBuffer
from automotive_voice.audio.coordinator import MediaCoordinator
from automotive_voice.telephony.transport import FakeTransport
from automotive_voice.adapters.lifecycle.clock import MockClock
from automotive_voice.adapters.lifecycle.supervisor import AdapterSupervisor
from automotive_voice.adapters.lifecycle.streaming import SyntheticStreamBridge
from automotive_voice.adapters.lifecycle.contracts import AdapterKind, ResultCode

FIXED_NOW = datetime(2026, 10, 31, 18, 0, tzinfo=timezone.utc)
TR_TZ = timezone(timedelta(hours=3))
SLOT = AppointmentSlot('2026-11-03T14:30:00+03:00', 'TRABZON')
ACCESS = AccessContext(authenticated=True, crm_processing_allowed=True)
NO_ACCESS = AccessContext(authenticated=False, crm_processing_allowed=False)

SCENARIOS = (
    'price_verified', 'price_expired', 'booking_confirmed', 'booking_declined',
    'booking_unknown', 'duplicate_confirmation', 'crm_case', 'handoff',
    'barge_in_ack', 'barge_in_timeout', 'xoff_backpressure', 'late_generation',
    'adapter_disconnect', 'llm_retry', 'booking_commit_unknown', 'wrong_fake_ack',
    'hangup_cancels', 'multi_session', 'unauthorized', 'ambiguous_time',
)

@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    checks: dict[str,bool]
    sessions: tuple[dict[str,Any],...]
    trace: tuple[dict[str,Any],...]
    notes: tuple[str,...]
    def to_dict(self)->dict:
        return {'scenario':self.name,'passed':self.passed,'checks':dict(self.checks),
                'sessions':list(self.sessions),'trace':list(self.trace),'notes':list(self.notes),
                'audio_bytes_generated':0,'real_pbx_connected':False,'real_crm_connected':False,
                'real_model_called':False,'production_ready':False}

class ScenarioRunner:
    """Fresh deterministic world for each run; no external dependencies.

    Methods are serial in a run. Multi-session runs share ONE manager/reducer,
    but retain independent booking sessions and generation counters.
    """
    def __init__(self, *, m10_presentation: bool = False, durable_journal: DurableJournal | None = None):
        self.clock=MockClock()
        self.manager=(DurableSessionManager(EventBus(),durable_journal) if durable_journal is not None
                      else SessionManager(EventBus()))
        self.reducer=ConversationReducer(self.manager,flush_timeout_ms=1500)
        self.store=ReferenceStore()
        self.crm=FakeCRM({'veh1':VehicleRecord('veh1','Nissan','Qashqai',2024)},
                {'veh1':PriceQuote('veh1',1250000,'fixture-price',FIXED_NOW+timedelta(days=20))})
        self.booking=FakeBookingService({FakeBookingService.key('veh1',SLOT):Availability.AVAILABLE})
        self.policy=DialoguePolicy(self.crm,self.booking,self.store,now=lambda:FIXED_NOW)
        self.dialogue=DialogueCoordinator(self.reducer,self.policy,self.store,clock_ns=self.clock.now_ns)
        self.nlu=NLUReferenceBridge(DeterministicNLU(),self.store)
        self.normalizer=TurkishAutomotiveNormalizer()
        self.mock_tts=MockTTS(self.manager)
        self.prosody=ProsodyCoordinator(self.store,self.normalizer,ProsodyClausePlanner(),self.mock_tts,
            presentation=PolicySpeechPresenter() if m10_presentation else None)
        self.buffer=MediaBuffer(self.manager)
        self.transport=FakeTransport(adapter_id='m09-fake-only')
        self.media=MediaCoordinator(self.reducer,self.buffer,self.transport)
        self.supervisor=AdapterSupervisor(self.manager,self.clock,media=self.media)
        self.stream=SyntheticStreamBridge(self.manager,self.clock,
            self.supervisor.adapters[AdapterKind.TTS],self.mock_tts,self.buffer)
        self.trace:list[dict[str,Any]]=[]
        self.notes:list[str]=[]
        self._opened=False
    def log(self,sid:str,step:str,outcome:str,**meta):
        # Whitelist only booleans, counters, state names, and diagnostic codes.
        self.trace.append({'ms':self.clock.now_ns()//1_000_000,'session':sid,
                'step':step,'outcome':outcome,**meta})
    def context(self,sid:str)->ParseContext:
        return ParseContext(vehicle_aliases={'qashqai':'veh1','nissan':'veh1'},
                location_aliases={'trabzon':'TRABZON'},
                as_of=FIXED_NOW.astimezone(TR_TZ),
                awaiting_confirmation=self.policy.snapshot(sid)['booking_status']=='awaiting_confirmation')
    async def init(self):
        if isinstance(self.manager, DurableSessionManager) and not self.manager._restored:
            await self.manager.restore_fail_closed()
        if not self._opened:
            await self.supervisor.start_all();self._opened=True
    async def emit(self,sid:str,kind:SignalKind,ref:str|None=None,*,flush_id:str|None=None):
        snap=await self.reducer.try_snapshot(sid)
        self.clock.advance(1_000_000)
        event=ConversationSignal.create(kind,sid,int(snap.turn_id) if snap else 0,
               int(snap.generation_id) if snap else 0,await self.reducer.expected_sequence(sid),
               reference=ref,flush_request_id=flush_id,mono_ns=self.clock.now_ns())
        out=await self.reducer.handle(event)
        self.log(sid,kind.value,out.decision.value,state=out.state.value if out.state else None)
        return out
    async def open(self,sid:str):
        await self.init()
        out=await self.emit(sid,SignalKind.SESSION_OPENED)
        assert out.decision is Decision.APPLIED
    async def _finish_adapter(self,kind:AdapterKind)->tuple:
        # No real time advances. Start job then advance virtual time and complete.
        await self.supervisor.tick_all()
        self.clock.advance(25_000_000)
        result=await self.supervisor.tick_all()
        return result[kind]
    async def user(self,sid:str,transcript:str,*,access:AccessContext=ACCESS,
                   auto_playout:bool=True,stream:bool=True)->dict:
        """Process a synthetic STT event through M04 -> M02 -> M07 -> M03 -> M05 -> M06.

        When a policy response is review-blocked, no audio is sent; optional
        playout is a *control-plane fixture transition*, explicitly recorded.
        """
        incoming=self.nlu.resolve(sid,transcript,self.context(sid))
        in_effect=await self.emit(sid,SignalKind.TRANSCRIPT_FINAL,incoming.ref)
        if in_effect.decision is not Decision.APPLIED:
            return {'status':'signal_rejected','reason':in_effect.reason}
        request=next(e for e in in_effect.effects if e.kind is EffectKind.REQUEST_LLM)
        rec=await self.supervisor.dispatch_effect(request)
        if not rec.accepted:return {'status':'adapter_rejected','reason':rec.reason}
        llm_results=await self._finish_adapter(AdapterKind.LLM)
        if not any(r.command_id==request.effect_id and r.code is ResultCode.OK for r in llm_results):
            return {'status':'adapter_not_complete'}
        result=await self.dialogue.process(request,access)
        self.log(sid,'policy',result.action,has_response=bool(result.response_ref),
             requires_clarification=incoming.parse.requires_clarification)
        tts_state='not_requested';sent=0
        if result.status=='applied' and result.response_ref:
            pending=await self.reducer.pending_effects(sid)
            start=next(e for e in pending if e.kind is EffectKind.START_TTS)
            planning=await self.prosody.process(start)
            tts_state=planning.status
            self.log(sid,'prosody',tts_state,clauses=planning.queued_clauses,
                     warning_codes=list(planning.warning_codes))
            if planning.status=='queued' and stream:
                sent=await self.pump(sid)
        await self.reducer.drain_effects(sid)
        if auto_playout and result.response_ref:
            # If text requires review, this advances the mock *state machine* only.
            # It does not pretend that a customer heard an actual prompt.
            played=await self.emit(sid,SignalKind.PLAYOUT_FINISHED)
            if played.decision is not Decision.APPLIED:
                raise AssertionError('invalid_playout:'+played.reason)
            if tts_state=='review_required':
                self.log(sid,'control_only_playout','no_audio_verified')
        return {'status':result.status,'action':result.action,
                'tts':tts_state,'sent_metadata':sent,'intent':incoming.parse.dialogue_input.intent.value,
                'requires_clarification':incoming.parse.requires_clarification}
    async def pump(self,sid:str,*,max_clauses:int=80)->int:
        delivered=0
        for _ in range(max_clauses):
            submission=await self.stream.submit_next_clause()
            if not submission.accepted:
                if submission.reason!='no_active_clause':self.log(sid,'stream_rejected',submission.reason)
                break
            outcomes=await self._finish_adapter(AdapterKind.TTS)
            for outcome in outcomes:
                if outcome.command_id!=submission.command_id:continue
                receipt=await self.stream.materialize_metadata(outcome)
                self.log(sid,'fake_tts',receipt.reason)
                if receipt.accepted:
                    send=await self.media.send_next(sid)
                    self.log(sid,'fake_transport',send.reason)
                    delivered+=int(send.accepted)
        return delivered
    async def interrupt(self,sid:str):
        out=await self.emit(sid,SignalKind.VAD_SPEECH_STARTED)
        if out.decision is not Decision.APPLIED:return out
        for effect in out.effects:
            r=await self.supervisor.dispatch_effect(effect)
            assert r.accepted, r.reason
        await self.reducer.drain_effects(sid)
        self.stream.abandon_generation(sid)
        await self.mock_tts.discard_stale()
        return out
    async def fake_ack(self,sid:str):
        pending=await self.reducer.pending_flush_id(sid)
        if not pending:raise ValueError('no_pending_flush')
        ack=await self.transport.confirm_flush(sid,pending)
        if ack is None:raise ValueError('not_confirmed_by_fake_transport')
        self.clock.advance(1_000_000)
        result=await self.media.accept_fake_ack(ack,sequence=await self.reducer.expected_sequence(sid),mono_ns=self.clock.now_ns())
        self.log(sid,'FAKE_ACK',result.decision.value,real_pbx_proven=False)
        return result
    async def expire_flush(self,sid:str):
        self.clock.advance(1_600_000_000)
        outcomes=await self.reducer.poll_flush_timeouts(self.clock.now_ns())
        for session,out in outcomes.items():
            for effect in out.effects:
                await self.supervisor.dispatch_effect(effect)
            self.log(session,'flush_timeout',out.decision.value,state=out.state.value)
        return outcomes.get(sid)
    async def hangup(self,sid:str):
        out=await self.emit(sid,SignalKind.HANGUP)
        for eff in out.effects:await self.supervisor.dispatch_effect(eff)
        await self.reducer.drain_effects(sid)
        return out
    async def session_summary(self,sid:str)->dict:
        snap=await self.reducer.try_snapshot(sid)
        audits=await self.reducer.audit_records(sid)
        return {'id':sid,'state':snap.state.value,'turn':int(snap.turn_id),
                'generation':int(snap.generation_id),'audit_events':len(audits),
                'booking_status':self.policy.snapshot(sid)['booking_status'],
                'pending_flush':bool(await self.reducer.pending_flush_id(sid)),
                'fake_transport_sent':self.transport.stats(sid).sent,
                'transport_paused':self.transport.stats(sid).paused}
    async def run(self,name:str)->ScenarioResult:
        if name not in SCENARIOS:raise ValueError('unknown_scenario')
        checks:dict[str,bool]={}
        self.notes=[]
        sid='m09-'+name.replace('_','-')
        await self.open(sid)
        try:
            if name in ('price_verified','price_expired','unauthorized'):
                if name=='price_expired':
                    self.crm.quotes['veh1']=PriceQuote('veh1',1250000,'stale-quote',FIXED_NOW-timedelta(days=1))
                outcome=await self.user(sid,'Nissan Qashqai aracımın fiyatı nedir?',
                         access=NO_ACCESS if name=='unauthorized' else ACCESS)
                checks['right_policy']=outcome['action']==('identity_required' if name=='unauthorized' else 'price_unavailable' if name=='price_expired' else 'price_verified')
                checks['no_booking']=self.booking.creations==0
            elif name in ('booking_confirmed','booking_declined','duplicate_confirmation','booking_unknown'):
                if name=='booking_unknown':
                    self.booking.availability.clear()
                first=await self.user(sid,'Qashqai için Trabzon 03.11.2026 saat 14:30 ekspertiz randevusu istiyorum.')
                checks['offer_gate']=first['action']==('slot_unknown' if name=='booking_unknown' else 'offer_confirmation')
                checks['no_early_booking']=self.booking.creations==0
                if name=='booking_unknown':
                    checks['unknown_not_confirmed']=self.policy.snapshot(sid)['booking_status']=='unknown'
                else:
                    next_text='hayır' if name=='booking_declined' else 'evet'
                    last=await self.user(sid,next_text)
                    checks['confirmation_step']=last['action']==('declined' if name=='booking_declined' else 'booking_confirmed')
                    if name=='duplicate_confirmation':
                        replay=await self.user(sid,'evet')
                        checks['repeat_not_second_booking']=self.booking.creations==1 and replay['action']!='booking_confirmed'
                    checks['booking_count']=self.booking.creations==(0 if name=='booking_declined' else 1)
            elif name=='crm_case':
                r=await self.user(sid,'Nissan Qashqai için geri ara talep kaydı oluştur')
                checks['crm_created']=r['action']=='crm_case_created' and self.crm.case_creations==1
            elif name=='handoff':
                r=await self.user(sid,'Beni bir temsilciye aktar')
                checks['handoff_policy']=r['action']=='handoff'
                checks['handoff_terminal']=(await self.reducer.try_snapshot(sid)).state is State.HANDOFF
            elif name=='barge_in_ack':
                await self.user(sid,'merhaba',auto_playout=False)
                out=await self.interrupt(sid)
                checks['barge_in_applied']=out.decision is Decision.APPLIED
                checks['ack_barrier']=(await self.reducer.try_snapshot(sid)).state is State.INTERRUPTING
                ack=await self.fake_ack(sid)
                checks['fake_ack_only']=ack.decision is Decision.APPLIED and (await self.reducer.try_snapshot(sid)).state is State.LISTENING
            elif name=='barge_in_timeout':
                await self.user(sid,'merhaba',auto_playout=False)
                await self.interrupt(sid)
                out=await self.expire_flush(sid)
                checks['watchdog_fails_closed']=bool(out and out.state is State.FAILED)
            elif name=='xoff_backpressure':
                await self.user(sid,'merhaba',auto_playout=False,stream=False)
                self.transport.xoff(sid)
                sent=await self.pump(sid)
                checks['no_send_under_xoff']=sent==0 and self.transport.stats(sid).paused
                self.transport.xon(sid)
                sent2=await self.media.send_next(sid)
                checks['resume_without_loss']=sent2.accepted
                await self.emit(sid,SignalKind.PLAYOUT_FINISHED)
            elif name=='late_generation':
                await self.user(sid,'merhaba',auto_playout=False,stream=False)
                r=await self.stream.submit_next_clause()
                await self.supervisor.tick_all()
                await self.interrupt(sid)
                self.clock.advance(25_000_000)
                late=await self.supervisor.tick_all()
                has_ok=any(x.code is ResultCode.OK and x.command_id==r.command_id for x in late[AdapterKind.TTS])
                checks['old_generation_not_delivered']=not has_ok
                checks['stale_chunk_rejected']=not await self.manager.accepts_chunk(sid,1)
            elif name=='llm_retry':
                incoming=self.nlu.resolve(sid,'merhaba',self.context(sid))
                out=await self.emit(sid,SignalKind.TRANSCRIPT_FINAL,incoming.ref)
                eff=next(x for x in out.effects if x.kind is EffectKind.REQUEST_LLM)
                llm=self.supervisor.adapters[AdapterKind.LLM]
                llm.inject_faults(eff.effect_id,['transient','ok'])
                receipt=await self.supervisor.dispatch_effect(eff)
                await self.supervisor.tick_all()
                self.clock.advance(25_000_000)
                await self.supervisor.tick_all()
                self.clock.advance(100_000_000)
                await self.supervisor.tick_all()
                self.clock.advance(25_000_000)
                res=await self.supervisor.tick_all()
                results=[x for x in res[AdapterKind.LLM] if x.command_id==eff.effect_id]
                checks['retry_one_recover']=receipt.accepted and len(results)==1 and results[0].code is ResultCode.OK and results[0].attempts==2
                policy=await self.dialogue.process(eff,ACCESS)
                checks['business_after_retry']=policy.status=='applied' and policy.action=='greeting'
                self.log(sid,'LLM retry','completed',attempts=results[0].attempts if results else 0)
            elif name=='booking_commit_unknown':
                first=await self.user(sid,'Qashqai için Trabzon 03.11.2026 saat 14:30 ekspertiz istiyorum')
                async def uncertain(vehicle_id,slot,idempotency_key):
                    self.booking.commit_calls+=1
                    return BookingReceipt(Commitment.UNKNOWN)
                self.booking.commit=uncertain
                second=await self.user(sid,'evet')
                third=await self.user(sid,'randevu durumu')
                checks['offer_and_unknown']=first['action']=='offer_confirmation' and second['action']=='booking_unknown'
                checks['recheck_no_duplicate']=third['action']=='recheck_unknown' and self.booking.commit_calls==1 and self.booking.creations==0
            elif name=='wrong_fake_ack':
                await self.user(sid,'merhaba',auto_playout=False)
                await self.interrupt(sid)
                wrong=await self.transport.confirm_flush(sid,'00000000-0000-0000-0000-000000000001')
                checks['wrong_ack_rejected']=wrong is None and (await self.reducer.try_snapshot(sid)).state is State.INTERRUPTING
                valid=await self.fake_ack(sid)
                checks['explicit_fake_ack_only']=valid.decision is Decision.APPLIED
            elif name=='hangup_cancels':
                await self.user(sid,'merhaba',auto_playout=False,stream=False)
                submitted=await self.stream.submit_next_clause()
                await self.supervisor.tick_all()
                await self.hangup(sid)
                self.clock.advance(25_000_000)
                res=await self.supervisor.tick_all()
                checks['hangup_terminal']=(await self.reducer.try_snapshot(sid)).state is State.ENDED
                checks['no_late_tts']=not any(x.command_id==submitted.command_id and x.code is ResultCode.OK for x in res[AdapterKind.TTS])
            elif name=='adapter_disconnect':
                adapter=self.supervisor.adapters[AdapterKind.TTS]
                await adapter.stop()
                checks['isolated_degradation']=self.supervisor.adapters[AdapterKind.LLM].state.value=='ready'
                await adapter.start()
                checks['recovered']=adapter.state.value=='ready'
            elif name=='multi_session':
                other='m09-secondary'
                await self.open(other)
                a=await self.user(sid,'Qashqai fiyatı nedir?')
                b=await self.user(other,'Qashqai için Trabzon 03.11.2026 saat 14:30 ekspertiz istiyorum')
                checks['separate_policy']=a['action']=='price_verified' and b['action']=='offer_confirmation'
                checks['independent_turns']=(await self.reducer.try_snapshot(sid)).turn_id==(await self.reducer.try_snapshot(other)).turn_id
                checks['no_cross_booking']=self.booking.creations==0
            elif name=='ambiguous_time':
                r=await self.user(sid,'Qashqai için Trabzon 03.11.2026 saat 14:30 veya 15:30 ekspertiz istiyorum')
                checks['ambiguity_flagged']=r['requires_clarification']
                checks['no_booking']=self.booking.creations==0
            else:raise AssertionError(name)
        except Exception as exc:
            # Type only: no raw transcript/PII in result.
            self.notes.append('harness_exception:'+type(exc).__name__)
            checks['no_exception']=False
        summaries=[]
        for session in (sid,'m09-secondary') if name=='multi_session' else (sid,):
            summaries.append(await self.session_summary(session))
        self.notes.append('All audio/media is metadata only; M08 read-model is a report projection.')
        self.notes.append('Volatile events do not survive process restarts; persistence HOLD.')
        return ScenarioResult(name,bool(checks) and all(checks.values()),checks,tuple(summaries),tuple(self.trace[-100:]),tuple(self.notes))

async def run_catalog()->dict:
    results=[]
    for name in SCENARIOS:
        results.append((await ScenarioRunner().run(name)).to_dict())
    return {'suite':'M09 deterministic synthetic E2E','scenario_count':len(results),
            'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),
            'results':results,'audio_bytes_generated':0,'real_pbx_connected':False,
            'production_ready':False}
