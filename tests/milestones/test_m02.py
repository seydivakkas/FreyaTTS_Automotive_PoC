"""M02 acceptance: deterministic control signals with no audio/network I/O."""
import asyncio
import unittest
from uuid import uuid4
from automotive_voice.conversation import ConversationReducer, ConversationSignal, SignalKind, Decision, EffectKind
from automotive_voice.core.event_bus import EventBus, EventBusFull
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.core.session import State


class M02(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bus = EventBus()
        self.manager = SessionManager(self.bus)
        self.reducer = ConversationReducer(self.manager)
        self.sid = 'vehicle-demo'

    async def send(self, kind, *, sid=None, t=None, g=None, seq=None, ref=None,
                   flush_id=None, event_id=None, mono_ns=None, reducer=None):
        r = reducer or self.reducer
        sid = sid or self.sid
        snapshot = await r._state(sid)
        signal = ConversationSignal.create(kind, sid,
            int(snapshot.turn_id) if t is None and snapshot else (t if t is not None else 0),
            int(snapshot.generation_id) if g is None and snapshot else (g if g is not None else 0),
            await r.expected_sequence(sid) if seq is None else seq,
            reference=ref, flush_request_id=flush_id, event_id=event_id, mono_ns=mono_ns)
        return await r.handle(signal)

    async def started(self):
        v = await self.send(SignalKind.SESSION_OPENED)
        self.assertEqual(v.state,State.LISTENING)

    async def speaking(self):
        await self.started()
        self.assertEqual((await self.send(SignalKind.TRANSCRIPT_FINAL,ref='transcript:1')).state, State.THINKING)
        self.assertEqual((await self.send(SignalKind.LLM_RESPONSE_READY,ref='response:1')).state, State.SPEAKING)

    async def test_nominal_flow_effects(self):
        await self.started()
        await self.send(SignalKind.VAD_SPEECH_STARTED)
        a=await self.send(SignalKind.TRANSCRIPT_FINAL,ref='text:1')
        self.assertEqual(a.effects[0].kind,EffectKind.REQUEST_LLM)
        self.assertEqual(a.effects[0].generation_id,1)
        b=await self.send(SignalKind.LLM_RESPONSE_READY,ref='reply:1')
        self.assertEqual(b.effects[0].kind,EffectKind.START_TTS)
        c=await self.send(SignalKind.AUDIO_CHUNK_READY,ref='chunk:1')
        self.assertEqual(c.effects[0].kind,EffectKind.QUEUE_AUDIO)
        d=await self.send(SignalKind.PLAYOUT_FINISHED)
        self.assertEqual(d.state,State.LISTENING)
        self.assertEqual([e.kind for e in await self.reducer.drain_effects(self.sid)],
                         [EffectKind.REQUEST_LLM,EffectKind.START_TTS,EffectKind.QUEUE_AUDIO])

    async def test_barge_in_flush_ack_gate_and_stale_audio(self):
        await self.speaking()
        old=await self.manager.current_token(self.sid)
        a=await self.send(SignalKind.VAD_SPEECH_STARTED)
        self.assertEqual(a.state,State.INTERRUPTING)
        self.assertTrue(old.cancelled)
        self.assertEqual([e.kind for e in a.effects], [EffectKind.CANCEL_GENERATION,EffectKind.FLUSH_MEDIA])
        self.assertFalse(await self.manager.accepts_chunk(self.sid,1))
        flush_id=a.effects[-1].effect_id
        late=await self.send(SignalKind.AUDIO_CHUNK_READY,t=1,g=1,ref='old:chunk')
        self.assertEqual((late.decision,late.reason),(Decision.IGNORED,'stale_turn_or_generation'))
        wrong=await self.send(SignalKind.MEDIA_FLUSH_ACK,flush_id=str(uuid4()))
        self.assertEqual(wrong.decision,Decision.IGNORED)
        self.assertEqual((await self.manager.snapshot(self.sid)).state, State.INTERRUPTING)
        correct=await self.send(SignalKind.MEDIA_FLUSH_ACK,flush_id=flush_id)
        self.assertEqual(correct.state, State.LISTENING)
        self.assertIsNone(await self.reducer.pending_flush_id(self.sid))

    async def test_deferred_transcript_is_atomic_on_flush_ack(self):
        await self.speaking()
        flush=(await self.send(SignalKind.VAD_SPEECH_STARTED)).effects[-1].effect_id
        p=await self.send(SignalKind.TRANSCRIPT_FINAL,ref='new:text')
        self.assertEqual(p.reason,'defer_transcript')
        a=await self.send(SignalKind.MEDIA_FLUSH_ACK,flush_id=flush)
        self.assertEqual((a.state,a.effects[0].kind),(State.THINKING,EffectKind.REQUEST_LLM))
        self.assertEqual(a.effects[0].reference,'new:text')
        snap=await self.manager.snapshot(self.sid)
        self.assertEqual((snap.turn_id,snap.generation_id),(2,3))
        events_count=snap.last_sequence
        self.assertEqual(events_count,5) # open, turn, response, interrupt, ack, new turn

    async def test_handoff_during_speaking_flushes_before_transfer(self):
        await self.speaking()
        h=await self.send(SignalKind.HANDOFF_REQUESTED)
        self.assertEqual(h.state,State.INTERRUPTING)
        flush=h.effects[-1].effect_id
        self.assertEqual([e.kind for e in h.effects], [EffectKind.CANCEL_GENERATION,EffectKind.FLUSH_MEDIA])
        a=await self.send(SignalKind.MEDIA_FLUSH_ACK,flush_id=flush)
        self.assertEqual(a.state,State.HANDOFF)
        self.assertEqual(a.effects[0].kind,EffectKind.START_HANDOFF)
        self.assertEqual((await self.send(SignalKind.HANGUP)).state,State.ENDED)

    async def test_handoff_overrides_deferred_transcript(self):
        await self.speaking()
        flush=(await self.send(SignalKind.VAD_SPEECH_STARTED)).effects[-1].effect_id
        await self.send(SignalKind.TRANSCRIPT_FINAL,ref='new:text')
        await self.send(SignalKind.HANDOFF_REQUESTED)
        a=await self.send(SignalKind.MEDIA_FLUSH_ACK,flush_id=flush)
        self.assertEqual(a.state,State.HANDOFF)
        self.assertEqual(a.effects[0].kind,EffectKind.START_HANDOFF)

    async def test_timeout_never_allows_listening(self):
        await self.speaking()
        flush=(await self.send(SignalKind.VAD_SPEECH_STARTED)).effects[-1].effect_id
        a=await self.send(SignalKind.MEDIA_FLUSH_TIMEOUT,flush_id=flush)
        self.assertEqual(a.state,State.FAILED)
        self.assertEqual(a.effects[0].kind,EffectKind.TERMINATE_CALL)
        self.assertEqual((await self.send(SignalKind.MEDIA_FLUSH_ACK,flush_id=flush)).decision, Decision.IGNORED)

    async def test_vad_in_thinking_cancels_old_llm_generation(self):
        await self.started()
        await self.send(SignalKind.TRANSCRIPT_FINAL,ref='text:1')
        token=await self.manager.current_token(self.sid)
        a=await self.send(SignalKind.VAD_SPEECH_STARTED)
        self.assertEqual(a.state,State.LISTENING)
        self.assertTrue(token.cancelled)
        self.assertEqual(a.effects[0].kind,EffectKind.CANCEL_GENERATION)
        self.assertEqual((await self.send(SignalKind.LLM_RESPONSE_READY,t=1,g=1,ref='old:response')).reason,
                         'stale_turn_or_generation')
        b=await self.send(SignalKind.TRANSCRIPT_FINAL,ref='new:text')
        self.assertEqual((b.state,b.effects[0].generation_id),(State.THINKING,3))

    async def test_replay_gap_duplicate_event_id(self):
        await self.started()
        id1=str(uuid4())
        first=await self.send(SignalKind.VAD_SPEECH_STARTED,event_id=id1)
        self.assertEqual(first.decision,Decision.APPLIED)
        replay=await self.send(SignalKind.VAD_SPEECH_STARTED,seq=1,event_id=id1)
        self.assertEqual((replay.decision,replay.reason),(Decision.IGNORED,'replayed_sequence'))
        dup=await self.send(SignalKind.VAD_SPEECH_STARTED,event_id=id1)
        self.assertEqual((dup.decision,dup.reason),(Decision.IGNORED,'duplicate_event_id'))
        gap=await self.send(SignalKind.TRANSCRIPT_FINAL,seq=6,ref='txt')
        self.assertEqual((gap.decision,gap.reason),(Decision.REJECTED,'sequence_gap'))
        correct=await self.send(SignalKind.TRANSCRIPT_FINAL,ref='txt')
        self.assertEqual(correct.decision,Decision.APPLIED)

    async def test_old_generation_and_wrong_ack_not_applied(self):
        await self.speaking()
        flush=(await self.send(SignalKind.VAD_SPEECH_STARTED)).effects[-1].effect_id
        old=await self.send(SignalKind.LLM_RESPONSE_READY,t=1,g=1,ref='old')
        self.assertEqual(old.decision,Decision.IGNORED)
        wrong=await self.send(SignalKind.MEDIA_FLUSH_ACK,g=1,flush_id=flush)
        self.assertEqual(wrong.decision,Decision.IGNORED)
        self.assertEqual((await self.manager.snapshot(self.sid)).state,State.INTERRUPTING)

    async def test_idempotent_hangup(self):
        await self.speaking()
        a=await self.send(SignalKind.HANGUP)
        b=await self.send(SignalKind.HANGUP)
        self.assertEqual((a.decision,a.state),(Decision.APPLIED,State.ENDED))
        self.assertEqual((b.decision,b.reason),(Decision.IGNORED,'terminal_session'))
        self.assertEqual(len([x for x in await self.reducer.pending_effects(self.sid)
                              if x.kind == EffectKind.TERMINATE_CALL]),1)

    async def test_handoff_thinking_cancels_llm(self):
        await self.started(); await self.send(SignalKind.TRANSCRIPT_FINAL,ref='text')
        token=await self.manager.current_token(self.sid)
        result=await self.send(SignalKind.HANDOFF_REQUESTED)
        self.assertEqual(result.state,State.HANDOFF)
        self.assertTrue(token.cancelled)
        self.assertEqual([e.kind for e in result.effects], [EffectKind.CANCEL_GENERATION,EffectKind.START_HANDOFF])

    async def test_effect_backpressure_rejects_without_state_mutation(self):
        r=ConversationReducer(SessionManager(EventBus()),effect_capacity=2)
        await self.send(SignalKind.SESSION_OPENED,reducer=r)
        await self.send(SignalKind.TRANSCRIPT_FINAL,ref='text',reducer=r) # 1 effect
        await self.send(SignalKind.LLM_RESPONSE_READY,ref='reply',reducer=r) # 2 effects
        snap=await r.manager.snapshot(self.sid)
        a=await self.send(SignalKind.VAD_SPEECH_STARTED,reducer=r)
        self.assertEqual((a.decision,a.reason),(Decision.REJECTED,'effect_queue_full'))
        self.assertEqual(snap,await r.manager.snapshot(self.sid))
        self.assertEqual(await r.expected_sequence(self.sid),3)
        await r.drain_effects(self.sid)
        retried=await self.send(SignalKind.VAD_SPEECH_STARTED,reducer=r)
        self.assertEqual(retried.state,State.INTERRUPTING)

    async def test_outbox_backpressure_rollbacks_input(self):
        manager=SessionManager(EventBus(),max_pending_events=2)
        r=ConversationReducer(manager)
        await self.send(SignalKind.SESSION_OPENED,reducer=r)
        await self.send(SignalKind.TRANSCRIPT_FINAL,ref='text',reducer=r)
        snap=await manager.snapshot(self.sid)
        a=await self.send(SignalKind.LLM_RESPONSE_READY,ref='resp',reducer=r)
        self.assertEqual((a.decision,a.reason),(Decision.REJECTED,'state_or_outbox_rejected'))
        self.assertEqual(snap,await manager.snapshot(self.sid))
        await manager.dispatch_pending(self.sid)
        self.assertEqual((await self.send(SignalKind.LLM_RESPONSE_READY,ref='resp',reducer=r)).state,State.SPEAKING)

    async def test_ack_followup_is_transactional_when_outbox_short(self):
        manager=SessionManager(EventBus(),max_pending_events=5)
        r=ConversationReducer(manager)
        await self.send(SignalKind.SESSION_OPENED,reducer=r)
        await self.send(SignalKind.TRANSCRIPT_FINAL,ref='old:txt',reducer=r)
        await self.send(SignalKind.LLM_RESPONSE_READY,ref='old:resp',reducer=r)
        flush=(await self.send(SignalKind.VAD_SPEECH_STARTED,reducer=r)).effects[-1].effect_id
        await self.send(SignalKind.TRANSCRIPT_FINAL,ref='new:txt',reducer=r)
        snap=await manager.snapshot(self.sid)
        a=await self.send(SignalKind.MEDIA_FLUSH_ACK,flush_id=flush,reducer=r)
        self.assertEqual((a.decision,a.reason),(Decision.REJECTED,'state_or_outbox_rejected'))
        self.assertEqual(await manager.snapshot(self.sid),snap)
        self.assertEqual(await r.pending_flush_id(self.sid),flush)
        await manager.dispatch_pending(self.sid)
        b=await self.send(SignalKind.MEDIA_FLUSH_ACK,flush_id=flush,reducer=r)
        self.assertEqual(b.state,State.THINKING)

    async def test_unmatched_timeout_is_not_fatal(self):
        await self.speaking()
        await self.send(SignalKind.VAD_SPEECH_STARTED)
        a=await self.send(SignalKind.MEDIA_FLUSH_TIMEOUT,flush_id=str(uuid4()))
        self.assertEqual((a.decision,a.reason),(Decision.IGNORED,'unmatched_flush_request'))
        self.assertEqual((await self.manager.snapshot(self.sid)).state,State.INTERRUPTING)

    async def test_invalid_signals_and_clock_regression(self):
        with self.assertRaises(ValueError):
            ConversationSignal.create(SignalKind.TRANSCRIPT_FINAL,'s',0,0,0,reference='raw transcript with PII!')
        with self.assertRaises(ValueError):
            ConversationSignal.create(SignalKind.MEDIA_FLUSH_ACK,'s',0,0,0)
        with self.assertRaises(ValueError):
            ConversationSignal.create(SignalKind.PLAYOUT_FINISHED,'s',-1,0,0)
        await self.send(SignalKind.SESSION_OPENED,mono_ns=100)
        a=await self.send(SignalKind.VAD_SPEECH_STARTED,mono_ns=99)
        self.assertEqual((a.decision,a.reason),(Decision.REJECTED,'monotonic_clock_regression'))
        self.assertEqual((await self.send(SignalKind.VAD_SPEECH_STARTED,mono_ns=101)).decision,Decision.APPLIED)

    async def test_multi_session_isolation_and_effect_determinism(self):
        await asyncio.gather(*(self.send(SignalKind.SESSION_OPENED,sid=f's{i}') for i in range(16)))
        items=await asyncio.gather(*(self.send(SignalKind.TRANSCRIPT_FINAL,sid=f's{i}',ref=f'val:{i}') for i in range(16)))
        self.assertEqual(sum(x.decision == Decision.APPLIED for x in items),16)
        self.assertEqual(len({x.effects[0].effect_id for x in items}),16)
        self.assertTrue(all((awaitable.state == State.THINKING) for awaitable in items))
        self.assertEqual((await self.manager.snapshot('s1')).last_sequence,1)

    async def test_concurrent_repeated_signal_sequence_only_one_commits(self):
        await self.started()
        e1=ConversationSignal.create(SignalKind.TRANSCRIPT_FINAL,self.sid,0,0,1,reference='txt')
        e2=ConversationSignal.create(SignalKind.TRANSCRIPT_FINAL,self.sid,0,0,1,reference='txt')
        a,b=await asyncio.gather(self.reducer.handle(e1),self.reducer.handle(e2))
        self.assertEqual(sorted([a.decision,b.decision],key=lambda x:x.value), [Decision.APPLIED,Decision.IGNORED])
        self.assertEqual((await self.manager.snapshot(self.sid)).turn_id,1)

    async def test_audit_has_no_transcripts(self):
        await self.started()
        await self.send(SignalKind.TRANSCRIPT_FINAL,ref='transcript:opaque-key')
        audit=await self.reducer.audit_records(self.sid)
        self.assertEqual(len(audit),2)
        self.assertEqual(audit[-1].state,State.THINKING)
        self.assertEqual(audit[-1].reason,'turn')
        self.assertFalse(hasattr(audit[-1],'reference'))

    async def test_bus_reordering_avoided_by_m01_outbox(self):
        sub=await self.bus.subscribe('audit',capacity=1)
        await self.speaking()
        with self.assertRaises(EventBusFull):
            await self.manager.dispatch_pending(self.sid)
        self.assertEqual(sub.get_nowait().sequence,0)
        for expected in [1,2]:
            with self.assertRaises(EventBusFull) if expected == 1 else _NoException():
                await self.manager.dispatch_pending(self.sid)
            self.assertEqual(sub.get_nowait().sequence,expected)
        self.assertEqual((await self.manager.snapshot(self.sid)).pending_events,0)

class _NoException:
    def __enter__(self): return self
    def __exit__(self, typ, val, tb): return False


if __name__ == '__main__':
    unittest.main()

class WatchdogTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_timeout_after_deadline(self):
        manager=SessionManager(EventBus())
        r=ConversationReducer(manager,flush_timeout_ms=10)
        sid='watchdog'
        async def push(kind,ref=None,mono=None,flush=None):
            snap=await r._state(sid)
            x=ConversationSignal.create(kind,sid,0 if snap is None else snap.turn_id,
                    0 if snap is None else snap.generation_id,await r.expected_sequence(sid),
                    reference=ref,flush_request_id=flush,mono_ns=mono)
            return await r.handle(x)
        await push(SignalKind.SESSION_OPENED,mono=100)
        await push(SignalKind.TRANSCRIPT_FINAL,ref='txt',mono=200)
        await push(SignalKind.LLM_RESPONSE_READY,ref='answer',mono=300)
        a=await push(SignalKind.VAD_SPEECH_STARTED,mono=400)
        self.assertEqual(a.state,State.INTERRUPTING)
        self.assertEqual(await r.poll_flush_timeouts(10_000_399),{})
        outcomes=await r.poll_flush_timeouts(10_000_400)
        self.assertEqual(outcomes[sid].state,State.FAILED)
        self.assertEqual(await r.poll_flush_timeouts(999_999_999),{})

    async def test_timeout_does_not_trigger_after_ack(self):
        manager=SessionManager(EventBus())
        r=ConversationReducer(manager,flush_timeout_ms=5)
        sid='ack-watchdog'
        async def push(kind,ref=None,mono=None,flush=None):
            snap=await r._state(sid)
            return await r.handle(ConversationSignal.create(kind,sid,
                    0 if snap is None else snap.turn_id,
                    0 if snap is None else snap.generation_id,
                    await r.expected_sequence(sid),reference=ref,flush_request_id=flush,mono_ns=mono))
        await push(SignalKind.SESSION_OPENED,mono=100)
        await push(SignalKind.TRANSCRIPT_FINAL,ref='txt',mono=200)
        await push(SignalKind.LLM_RESPONSE_READY,ref='reply',mono=300)
        x=await push(SignalKind.VAD_SPEECH_STARTED,mono=400)
        await push(SignalKind.MEDIA_FLUSH_ACK,mono=500,flush=x.effects[-1].effect_id)
        self.assertEqual(await r.poll_flush_timeouts(20_000_000),{})
        self.assertEqual((await manager.snapshot(sid)).state,State.LISTENING)

class EmergencyCloseTests(unittest.IsolatedAsyncioTestCase):
    async def test_hangup_when_m01_outbox_full_is_fail_closed(self):
        mgr=SessionManager(EventBus(),max_pending_events=2)
        r=ConversationReducer(mgr,effect_capacity=1)
        sid='overloaded'
        async def send(k,ref=None):
            snap=await r._state(sid)
            return await r.handle(ConversationSignal.create(k,sid,
                snap.turn_id if snap else 0,snap.generation_id if snap else 0,
                await r.expected_sequence(sid),reference=ref))
        await send(SignalKind.SESSION_OPENED)
        await send(SignalKind.TRANSCRIPT_FINAL,ref='t:1') # outbox 2/2, effect 1/1
        a=await send(SignalKind.HANGUP)
        self.assertEqual((a.state,a.reason),(State.ENDED,'emergency_closed_no_m01_event'))
        self.assertEqual([x.kind for x in await r.pending_effects(sid)],[EffectKind.TERMINATE_CALL])
        self.assertEqual((await mgr.snapshot(sid)).last_sequence,1) # no false session_ended event

    async def test_timeout_full_outbox_safely_fails(self):
        mgr=SessionManager(EventBus(),max_pending_events=4)
        r=ConversationReducer(mgr)
        sid='overloaded-timeout'
        async def send(k,ref=None,flush=None):
            snap=await r._state(sid)
            return await r.handle(ConversationSignal.create(k,sid,
                snap.turn_id if snap else 0,snap.generation_id if snap else 0,
                await r.expected_sequence(sid),reference=ref,flush_request_id=flush))
        await send(SignalKind.SESSION_OPENED)
        await send(SignalKind.TRANSCRIPT_FINAL,ref='t:1')
        await send(SignalKind.LLM_RESPONSE_READY,ref='r:1')
        flush=(await send(SignalKind.VAD_SPEECH_STARTED)).effects[-1].effect_id
        a=await send(SignalKind.MEDIA_FLUSH_TIMEOUT,flush=flush)
        self.assertEqual((a.state,a.reason),(State.FAILED,'emergency_closed_no_m01_event'))
        self.assertEqual([x.kind for x in await r.pending_effects(sid)],[EffectKind.TERMINATE_CALL])
        self.assertIsNone(await r.pending_flush_id(sid))
