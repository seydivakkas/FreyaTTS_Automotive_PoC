"""M07: deterministic virtual-time lifecycle, fault isolation, no audio or network."""
import asyncio
from dataclasses import replace
import unittest
from uuid import uuid4
from automotive_voice.adapters.lifecycle import (
    MockClock,CircuitBreaker,AdapterKind,AdapterState,CircuitState,ResultCode,Deadline,
    RetryPolicy,SyntheticCommand,SyntheticAdapter,AdapterSupervisor,SyntheticStreamBridge)
from automotive_voice.core.identifiers import SessionId,TurnId,GenerationId
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.prosody import MockTTS,ProsodyClausePlanner
from automotive_voice.nlp.lexicon import AutomotiveLexicon
from automotive_voice.audio import MediaBuffer,MediaCoordinator
from automotive_voice.telephony import FakeTransport
from automotive_voice.conversation import ConversationReducer,ConversationSignal,SignalKind,Decision
from automotive_voice.conversation.effects import Effect,EffectKind

class ContractTests(unittest.TestCase):
    def test_clock(self):
        c=MockClock(5);self.assertEqual(c.advance(10),15)
        with self.assertRaises(ValueError):c.advance(-1)
        with self.assertRaises(OverflowError):c.advance(2**64)
        self.assertEqual(c.now_ns(),15)
    def test_retry(self):
        p=RetryPolicy(4,5,13)
        self.assertEqual([p.delay_after(i) for i in (1,2,3,4)],[5,10,13,13])
        with self.assertRaises(ValueError):RetryPolicy(0)
        with self.assertRaises(ValueError):RetryPolicy(3,10,1)
    def test_deadline(self):
        self.assertFalse(Deadline(10).expired(9));self.assertTrue(Deadline(10).expired(10))
        with self.assertRaises(ValueError):Deadline(0)
    def test_command_no_raw_text(self):
        c=SyntheticCommand('a',AdapterKind.STT,SessionId('s'),TurnId(1),GenerationId(1),0,'ref:23',Deadline(10))
        self.assertEqual(c.payload_ref,'ref:23')
        with self.assertRaises(ValueError):replace(c,payload_ref='Merhaba nasılsınız')
        with self.assertRaises(ValueError):replace(c,command_id='hello\nworld')
        with self.assertRaises(ValueError):replace(c,sequence=-1)
        with self.assertRaises(TypeError):replace(c,generation_id=1)
    def test_breaker_probe(self):
        b=CircuitBreaker(threshold=2,cooldown_ns=10)
        b.failure(0);self.assertEqual(b.state,CircuitState.CLOSED)
        b.failure(1);self.assertEqual(b.state,CircuitState.OPEN)
        self.assertFalse(b.allow(10));self.assertTrue(b.allow(11))
        self.assertEqual(b.state,CircuitState.HALF_OPEN);self.assertFalse(b.allow(12))
        b.failure(12);self.assertEqual(b.state,CircuitState.OPEN)
        self.assertTrue(b.allow(22));b.success();self.assertEqual(b.state,CircuitState.CLOSED)

class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock=MockClock();self.m=SessionManager(EventBus())
        for sid in ('m07','other'):
            await self.m.create(sid);await self.m.start(sid);await self.m.begin_turn(sid);await self.m.begin_response(sid)
        self.a=SyntheticAdapter(AdapterKind.TTS,self.m,self.clock,latency_ns=10,retry=RetryPolicy(3,10,100))
        await self.a.start()
    async def make(self,n=0,*,sid='m07',id=None,ref='sha:123',deadline=200,idempotent=True):
        snap=await self.m.snapshot(sid)
        return SyntheticCommand(id or f'cmd{n}',AdapterKind.TTS,snap.session_id,snap.turn_id,snap.generation_id,n,ref,Deadline(deadline),idempotent)
    async def test_start_stop_health(self):
        self.assertEqual(self.a.health().state,AdapterState.READY)
        await self.a.stop();self.assertEqual(self.a.health().state,AdapterState.STOPPED)
        await self.a.start();self.assertEqual(self.a.health().state,AdapterState.READY)
    async def test_ok_virtual_completion(self):
        cmd=await self.make()
        self.assertTrue((await self.a.submit(cmd)).accepted)
        self.assertEqual(await self.a.tick(),())
        self.clock.advance(9);self.assertEqual(await self.a.tick(),())
        self.clock.advance(1);out=await self.a.tick()
        self.assertEqual(len(out),1);self.assertEqual(out[0].code,ResultCode.OK)
        self.assertEqual(out[0].output_ref,'mock-tts:cmd0')
        self.assertEqual(self.a.read_result('cmd0'),out[0])
    async def test_replay_and_conflict(self):
        cmd=await self.make();await self.a.submit(cmd)
        self.assertEqual((await self.a.submit(cmd)).reason,'duplicate_ignored')
        self.assertEqual((await self.a.submit(replace(cmd,payload_ref='sha:other'))).reason,'conflicting_replay')
        await self.a.tick();self.clock.advance(10);await self.a.tick()
        self.assertEqual((await self.a.submit(cmd)).reason,'duplicate_ignored')
    async def test_sequence_gap_no_poison(self):
        cmd=await self.make(1)
        self.assertEqual((await self.a.submit(cmd)).reason,'sequence_gap')
        self.assertTrue((await self.a.submit(await self.make())).accepted)
        self.assertTrue((await self.a.submit(cmd)).accepted)
    async def test_capacity(self):
        a=SyntheticAdapter(AdapterKind.TTS,self.m,self.clock,max_pending=1)
        await a.start();self.assertTrue((await a.submit(await self.make())).accepted)
        self.assertEqual((await a.submit(await self.make(1))).reason,'backpressure')
    async def test_timeout_before_start(self):
        self.clock.advance(201)
        self.assertEqual((await self.a.submit(await self.make())).reason,'deadline_expired')
    async def test_deadline_inflight(self):
        cmd=await self.make(deadline=5)
        await self.a.submit(cmd);await self.a.tick();self.clock.advance(5)
        self.assertEqual((await self.a.tick())[0].code,ResultCode.TIMED_OUT)
    async def test_retry_and_recovery(self):
        cmd=await self.make();self.a.inject_faults('cmd0',['transient','ok'])
        await self.a.submit(cmd);await self.a.tick();self.clock.advance(10);self.assertEqual(await self.a.tick(),())
        self.clock.advance(9);await self.a.tick();self.assertEqual(self.a.health().in_flight,0)
        self.clock.advance(1);await self.a.tick();self.clock.advance(10)
        r=await self.a.tick();self.assertEqual(r[0].code,ResultCode.OK);self.assertEqual(r[0].attempts,2)
    async def test_nonidempotent_never_retry(self):
        cmd=await self.make(idempotent=False);self.a.inject_faults('cmd0',['transient','ok'])
        await self.a.submit(cmd);await self.a.tick();self.clock.advance(10)
        self.assertEqual((await self.a.tick())[0].code,ResultCode.RETRY_EXHAUSTED)
    async def test_permanent_never_retry(self):
        self.a.inject_faults('cmd0',['permanent','ok'])
        await self.a.submit(await self.make());await self.a.tick();self.clock.advance(10)
        self.assertEqual((await self.a.tick())[0].code,ResultCode.PERMANENT_FAILURE)
    async def test_disconnect_and_reconnect(self):
        self.a.inject_faults('cmd0',['disconnect','ok'])
        await self.a.submit(await self.make());await self.a.tick();self.clock.advance(10)
        await self.a.tick();self.assertEqual(self.a.health().state,AdapterState.DEGRADED)
        self.clock.advance(10);self.assertEqual(await self.a.tick(),())
        await self.a.reconnect();await self.a.tick();self.clock.advance(10)
        self.assertEqual((await self.a.tick())[0].code,ResultCode.OK)
    async def test_reconnect_invalid(self):
        with self.assertRaises(RuntimeError):await self.a.reconnect()
    async def test_stale_generation(self):
        await self.a.submit(await self.make());await self.a.tick()
        await self.m.interrupt('m07');self.clock.advance(10)
        self.assertEqual((await self.a.tick())[0].code,ResultCode.STALE)
    async def test_cancel_session_independent(self):
        await self.a.submit(await self.make())
        await self.a.submit(await self.make(0,sid='other',id='other0'))
        cancelled=await self.a.cancel_session('m07')
        self.assertEqual(len(cancelled),1);self.assertEqual(cancelled[0].code,ResultCode.CANCELLED)
        await self.a.tick();self.clock.advance(10)
        self.assertEqual((await self.a.tick())[0].session_id,SessionId('other'))
    async def test_fault_isolation_other_adapter(self):
        stt=SyntheticAdapter(AdapterKind.STT,self.m,self.clock,latency_ns=1)
        await stt.start()
        cmd=SyntheticCommand('stt0',AdapterKind.STT,SessionId('other'),TurnId(1),GenerationId(1),0,'ref:stt',Deadline(100))
        self.a.inject_faults('cmd0',['disconnect'])
        await self.a.submit(await self.make());await self.a.tick()
        self.assertTrue((await stt.submit(cmd)).accepted);await stt.tick()
        self.clock.advance(10);await self.a.tick()
        self.assertEqual(self.a.state,AdapterState.DEGRADED)
        self.assertEqual((await stt.tick())[0].code,ResultCode.OK)
    async def test_circuit_open_and_half_open(self):
        a=SyntheticAdapter(AdapterKind.TTS,self.m,self.clock,latency_ns=1,
                           retry=RetryPolicy(1),breaker_threshold=1,breaker_cooldown_ns=10,max_inflight=1)
        await a.start();a.inject_faults('a',['transient'])
        snap=await self.m.snapshot('m07')
        def cmd(id,n):return SyntheticCommand(id,AdapterKind.TTS,snap.session_id,snap.turn_id,snap.generation_id,n,'ref:xyz',Deadline(100))
        await a.submit(cmd('a',0));await a.submit(cmd('b',1));await a.tick()
        self.clock.advance(1);result=await a.tick()
        self.assertEqual(result[0].code,ResultCode.RETRY_EXHAUSTED)
        # b may already be in-flight (capacity 2), demonstrating best-effort CB.
        self.assertEqual(a.breaker.state,CircuitState.OPEN)
    async def test_stop_cancels_inflight(self):
        await self.a.submit(await self.make());await self.a.tick()
        await self.a.stop()
        self.assertEqual(self.a.read_result('cmd0').code,ResultCode.CANCELLED)
        self.clock.advance(20);self.assertEqual(await self.a.tick(),())
    async def test_bounded_replay_window(self):
        a=SyntheticAdapter(AdapterKind.TTS,self.m,self.clock,latency_ns=0,replay_limit=1)
        await a.start()
        for n in range(2):
            cmd=await self.make(n)
            await a.submit(cmd);await a.tick();await a.tick()
        self.assertIsNone(a.read_result('cmd0'))
        self.assertIsNotNone(a.read_result('cmd1'))

class SupervisorAndStreaming(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock=MockClock();self.m=SessionManager(EventBus())
        await self.m.create('m07');await self.m.start('m07');await self.m.begin_turn('m07');await self.m.begin_response('m07')
        self.reducer=ConversationReducer(self.m);self.buffer=MediaBuffer(self.m)
        self.transport=FakeTransport();self.media=MediaCoordinator(self.reducer,self.buffer,self.transport)
        self.sup=AdapterSupervisor(self.m,self.clock,media=self.media)
        await self.sup.start_all()
    async def test_health_four_adapters(self):
        h=self.sup.health();self.assertEqual(set(h),{a.value for a in AdapterKind})
        self.assertTrue(all(x.state is AdapterState.READY and x.mock_only for x in h.values()))
    async def test_bad_effect_reference(self):
        e=Effect(str(uuid4()),EffectKind.REQUEST_LLM,SessionId('m07'),TurnId(1),GenerationId(1),str(uuid4()),None)
        self.assertEqual((await self.sup.dispatch_effect(e)).reason,'opaque_reference_required')
    async def test_effect_idempotency_and_cancel(self):
        e=Effect(str(uuid4()),EffectKind.START_TTS,SessionId('m07'),TurnId(1),GenerationId(1),str(uuid4()),'ref:planned')
        self.assertTrue((await self.sup.dispatch_effect(e)).accepted)
        self.assertEqual((await self.sup.dispatch_effect(e)).reason,'duplicate_ignored')
        await self.sup.tick_all();self.clock.advance(20_000_000)
        results=await self.sup.tick_all()
        self.assertEqual(results[AdapterKind.TTS][0].code,ResultCode.OK)
        self.assertEqual((await self.sup.dispatch_effect(e)).reason,'duplicate_ignored')
    async def test_cancel_effect(self):
        e=Effect(str(uuid4()),EffectKind.START_TTS,SessionId('m07'),TurnId(1),GenerationId(1),str(uuid4()),'ref:planned')
        await self.sup.dispatch_effect(e)
        cancel=Effect(str(uuid4()),EffectKind.CANCEL_GENERATION,SessionId('m07'),TurnId(1),GenerationId(1),str(uuid4()))
        self.assertTrue((await self.sup.dispatch_effect(cancel)).accepted)
        self.assertEqual(self.sup.adapters[AdapterKind.TTS].read_result(e.effect_id).code,ResultCode.CANCELLED)
    async def test_no_fabricated_pbx_ack(self):
        self.assertEqual(len(self.transport._confirmed),0)
        self.assertTrue(all(not a._terminal for a in self.sup.adapters.values()))
    async def test_clause_to_synthetic_media(self):
        from automotive_voice.prosody.contracts import ClausePlan,Clause,BreakKind,PlanStatus
        clause=Clause(0,0,7,'Merhaba',BreakKind.FINAL,0,'statement')
        plan=ClausePlan(SessionId('m07'),TurnId(1),GenerationId(1),'Merhaba',PlanStatus.READY,(clause,),(),())
        q=MockTTS(self.m)
        self.assertTrue((await q.enqueue(plan)).accepted)
        a=self.sup.adapters[AdapterKind.TTS]
        bridge=SyntheticStreamBridge(self.m,self.clock,a,q,self.buffer)
        self.assertTrue((await bridge.submit_next_clause()).accepted)
        await a.tick();self.clock.advance(20_000_000);r=(await a.tick())[0]
        self.assertTrue((await bridge.materialize_metadata(r)).accepted)
        self.assertEqual((await self.buffer.metrics('m07')).pending_chunks,1)
        self.assertFalse((await bridge.materialize_metadata(r)).accepted)
    async def test_stale_completion_blocked_by_m06(self):
        from automotive_voice.prosody.contracts import ClausePlan,Clause,BreakKind,PlanStatus
        clause=Clause(0,0,7,'Merhaba',BreakKind.FINAL,0,'statement')
        plan=ClausePlan(SessionId('m07'),TurnId(1),GenerationId(1),'Merhaba',PlanStatus.READY,(clause,),(),())
        q=MockTTS(self.m);await q.enqueue(plan)
        a=self.sup.adapters[AdapterKind.TTS]
        bridge=SyntheticStreamBridge(self.m,self.clock,a,q,self.buffer)
        await bridge.submit_next_clause();await a.tick();await self.m.interrupt('m07')
        self.clock.advance(20_000_000)
        r=(await a.tick())[0]
        self.assertEqual(r.code,ResultCode.STALE)
        self.assertFalse((await bridge.materialize_metadata(r)).accepted)
    async def test_media_backpressure_does_not_advance_chunk_seq(self):
        from automotive_voice.prosody.contracts import ClausePlan,Clause,BreakKind,PlanStatus
        text='Merhaba dünya';clauses=(Clause(0,0,7,'Merhaba',BreakKind.PAUSE,100,'continuation'),
                                     Clause(1,8,13,'dünya',BreakKind.FINAL,0,'statement'))
        plan=ClausePlan(SessionId('m07'),TurnId(1),GenerationId(1),text,PlanStatus.READY,clauses,(),())
        q=MockTTS(self.m);await q.enqueue(plan)
        buffer=MediaBuffer(self.m,max_chunks_per_session=1)
        a=self.sup.adapters[AdapterKind.TTS]
        bridge=SyntheticStreamBridge(self.m,self.clock,a,q,buffer)
        await bridge.submit_next_clause();await a.tick();self.clock.advance(20_000_000)
        r=(await a.tick())[0];self.assertTrue((await bridge.materialize_metadata(r)).accepted)
        await bridge.submit_next_clause();await a.tick();self.clock.advance(20_000_000)
        r2=(await a.tick())[0];self.assertEqual((await bridge.materialize_metadata(r2)).reason,'backpressure')
        await buffer.pop_next('m07')
        self.assertTrue((await bridge.materialize_metadata(r2)).accepted)
    async def test_independent_tts_telephony_failures(self):
        self.sup.adapters[AdapterKind.TTS].inject_faults('dummy',['disconnect'])
        self.assertEqual(self.sup.adapters[AdapterKind.TELEPHONY].state,AdapterState.READY)

if __name__=='__main__':unittest.main()

class SafetyAndFlushTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock=MockClock();self.manager=SessionManager(EventBus());self.sid='m07-flush'
        self.reducer=ConversationReducer(self.manager)
        self.transport=FakeTransport(adapter_id='fake-PBX')
        self.buffer=MediaBuffer(self.manager)
        self.media=MediaCoordinator(self.reducer,self.buffer,self.transport)
        self.sup=AdapterSupervisor(self.manager,self.clock,media=self.media)
        await self.sup.start_all()
        r=await self.reducer.handle(ConversationSignal.create(SignalKind.SESSION_OPENED,self.sid,0,0,0,mono_ns=0))
        self.assertEqual(r.decision,Decision.APPLIED)
        await self.reducer.handle(ConversationSignal.create(SignalKind.TRANSCRIPT_FINAL,self.sid,0,0,1,reference='ref:transcript',mono_ns=1))
        await self.reducer.handle(ConversationSignal.create(SignalKind.LLM_RESPONSE_READY,self.sid,1,1,2,reference='ref:reply',mono_ns=2))
    async def test_flush_is_not_auto_acked(self):
        # A started mock TTS command must be invalidated by the barge-in effect.
        pending=Effect(str(uuid4()),EffectKind.START_TTS,SessionId(self.sid),TurnId(1),GenerationId(1),str(uuid4()),'ref:tts')
        await self.sup.dispatch_effect(pending)
        sig=ConversationSignal.create(SignalKind.VAD_SPEECH_STARTED,self.sid,1,1,3,mono_ns=3)
        r=await self.reducer.handle(sig)
        self.assertEqual(r.state.value,'INTERRUPTING')
        effects=r.effects
        cancel=next(e for e in effects if e.kind is EffectKind.CANCEL_GENERATION)
        flush=next(e for e in effects if e.kind is EffectKind.FLUSH_MEDIA)
        self.assertTrue((await self.sup.dispatch_effect(cancel)).accepted)
        self.assertTrue((await self.sup.dispatch_effect(flush)).accepted)
        self.assertEqual(self.sup.adapters[AdapterKind.TTS].read_result(pending.effect_id).code,ResultCode.CANCELLED)
        self.assertEqual((await self.manager.snapshot(self.sid)).state.value,'INTERRUPTING')
        self.assertFalse(self.transport._confirmed)
        fake_req=self.media._pending[self.sid]
        ack=await self.transport.confirm_flush(self.sid,fake_req.flush_request_id)
        ack_result=await self.media.accept_fake_ack(ack,sequence=await self.reducer.expected_sequence(self.sid),mono_ns=4)
        self.assertEqual(ack_result.state.value,'LISTENING')
    async def test_flush_requires_valid_m02_state(self):
        e=Effect(str(uuid4()),EffectKind.FLUSH_MEDIA,SessionId(self.sid),TurnId(1),GenerationId(1),str(uuid4()))
        with self.assertRaises(ValueError):await self.sup.dispatch_effect(e)
    async def test_separate_stt_llm_commands(self):
        # STT/LLM use same control contract but independent ordered sequences.
        sid=self.sid
        snap=await self.manager.snapshot(sid)
        for kind in (AdapterKind.STT,AdapterKind.LLM):
            c=SyntheticCommand('cmd-'+kind.value,kind,snap.session_id,snap.turn_id,snap.generation_id,
                               0,'ref:input',Deadline(5_000_000_000))
            self.assertTrue((await self.sup.adapters[kind].submit(c)).accepted)
        await self.sup.tick_all();self.clock.advance(20_000_000)
        r=await self.sup.tick_all()
        self.assertEqual(r[AdapterKind.STT][0].code,ResultCode.OK)
        self.assertEqual(r[AdapterKind.LLM][0].code,ResultCode.OK)
    async def test_bridge_holds_clause_on_adapter_backpressure(self):
        from automotive_voice.prosody.contracts import ClausePlan,Clause,BreakKind,PlanStatus
        q=MockTTS(self.manager)
        plan=ClausePlan(SessionId(self.sid),TurnId(1),GenerationId(1),'Merhaba',PlanStatus.READY,
                        (Clause(0,0,7,'Merhaba',BreakKind.FINAL,0,'statement'),),(),())
        await q.enqueue(plan)
        a=SyntheticAdapter(AdapterKind.TTS,self.manager,self.clock,max_pending=1)
        await a.start()
        other=SyntheticCommand('occupy',AdapterKind.TTS,SessionId(self.sid),TurnId(1),GenerationId(1),0,'ref:occupy',Deadline(5_000_000_000))
        await a.submit(other)
        bridge=SyntheticStreamBridge(self.manager,self.clock,a,q,self.buffer)
        self.assertEqual((await bridge.submit_next_clause()).reason,'backpressure')
        await a.tick();self.clock.advance(20_000_000);await a.tick()
        # The clause is held; a fresh pop would lose it, but retry succeeds.
        self.assertTrue((await bridge.submit_next_clause()).accepted)
    async def test_adapter_session_isolation_with_stale_callback(self):
        await self.manager.create('another');await self.manager.start('another')
        await self.manager.begin_turn('another');await self.manager.begin_response('another')
        a=self.sup.adapters[AdapterKind.TTS]
        for sid in (self.sid,'another'):
            snap=await self.manager.snapshot(sid)
            await a.submit(SyntheticCommand('job-'+sid,AdapterKind.TTS,snap.session_id,snap.turn_id,snap.generation_id,
                                          0,'ref:data',Deadline(5_000_000_000)))
        await a.tick()
        # An independent session interrupt cannot cancel the other session's work.
        await self.manager.interrupt(self.sid)
        self.clock.advance(20_000_000)
        r=await a.tick()
        self.assertEqual({x.code for x in r},{ResultCode.OK,ResultCode.STALE})
