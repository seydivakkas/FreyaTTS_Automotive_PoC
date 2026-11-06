"""M06 offline synthetic media/flush acceptance. No audio or PBX sockets."""
from __future__ import annotations
import asyncio
from dataclasses import replace
import unittest
from uuid import uuid4
from automotive_voice.core.identifiers import SessionId,TurnId,GenerationId
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.core.session import State
from automotive_voice.audio import (Codec,MediaFormat,AudioChunkMetadata,MediaBuffer,FlushRequest,FlushAck,MediaCoordinator)
from automotive_voice.telephony import FakeTransport,AsteriskCommandEncoder
from automotive_voice.conversation import ConversationReducer,ConversationSignal,SignalKind,Decision

class FormatTests(unittest.TestCase):
    def test_pcm8(self):
        f=MediaFormat(Codec.PCM_S16LE,8000)
        self.assertEqual(f.expected_bytes(160),320)
    def test_pcm16(self):
        self.assertEqual(MediaFormat(Codec.PCM_S16LE,16000).expected_bytes(320),640)
    def test_pcm48(self):
        self.assertEqual(MediaFormat(Codec.PCM_S16LE,48000).expected_bytes(960),1920)
    def test_alaw(self):
        self.assertEqual(MediaFormat(Codec.ALAW,8000).expected_bytes(160),160)
    def test_mulaw(self):
        self.assertEqual(MediaFormat(Codec.MULAW,8000).expected_bytes(160),160)
    def test_g711_rate_rejected(self):
        for codec in (Codec.ALAW,Codec.MULAW):
            with self.assertRaises(ValueError):MediaFormat(codec,16000)
    def test_g722_metadata_clock(self):
        f=MediaFormat(Codec.G722,16000,rtp_clock_hz=8000)
        self.assertIsNone(f.expected_bytes(320))
        self.assertFalse(f.payload_supported)
    def test_g722_clock_must_be_distinct(self):
        with self.assertRaises(ValueError):MediaFormat(Codec.G722,16000,rtp_clock_hz=16000)
    def test_reject_stereo_or_unknown_rate(self):
        with self.assertRaises(ValueError):MediaFormat(Codec.PCM_S16LE,22050)
        with self.assertRaises(ValueError):MediaFormat(Codec.PCM_S16LE,48000,2)
    def test_reject_bad_type(self):
        with self.assertRaises(ValueError):MediaFormat('pcm_s16le',48000)
        with self.assertRaises(ValueError):MediaFormat(Codec.PCM_S16LE,True)
    def test_chunk_duration_invariant(self):
        c=chunk()
        self.assertEqual(c.duration_ms,20)
        with self.assertRaises(ValueError):replace(c,sample_count=1)
        with self.assertRaises(ValueError):replace(c,duration_ms=0)
    def test_chunk_ids_and_private_metadata(self):
        c=chunk()
        self.assertNotIn('payload',c.safe_metadata())
        with self.assertRaises(TypeError):replace(c,session_id='s')
        with self.assertRaises(ValueError):replace(c,stream_id='unsafe label')
    def test_asterisk_json_dry_run(self):
        req=FlushRequest(str(uuid4()),SessionId('s'),TurnId(1),GenerationId(2))
        self.assertEqual(AsteriskCommandEncoder.flush_json(req),{'command':'FLUSH_MEDIA','correlation_id':req.flush_request_id})
        self.assertEqual(AsteriskCommandEncoder.hangup_json(),{'command':'HANGUP'})
    def test_ack_is_never_real_proof(self):
        ack=FlushAck(str(uuid4()),SessionId('s'),TurnId(1),GenerationId(2),'fake-adapter',True)
        self.assertFalse(ack.real_pbx_proven)
        with self.assertRaises(ValueError):replace(ack,flush_request_id='bad')

def chunk(seq=0,sid='m06',turn=1,generation=1,stream='playout',codec=Codec.PCM_S16LE,rate=16000,ms=20):
    return AudioChunkMetadata(SessionId(sid),TurnId(turn),GenerationId(generation),stream,seq,rate*ms//1000,ms,seq*ms*1000000,MediaFormat(codec,rate),0)

class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.m=SessionManager(EventBus())
        for sid in ('m06','other'):
            await self.m.create(sid);await self.m.start(sid);await self.m.begin_turn(sid);await self.m.begin_response(sid)
        self.q=MediaBuffer(self.m,max_chunks_per_session=3,max_ms_per_session=60)

    async def test_enqueue_pop(self):
        self.assertEqual((await self.q.enqueue(chunk())).reason,'queued')
        self.assertEqual((await self.q.pop_next('m06')).seq,0)
        self.assertIsNone(await self.q.pop_next('m06'))
    async def test_duplicate_ignored(self):
        await self.q.enqueue(chunk())
        r=await self.q.enqueue(chunk())
        self.assertEqual((r.accepted,r.reason),(True,'duplicate_ignored'))
        self.assertEqual((await self.q.metrics('m06')).pending_chunks,1)
    async def test_conflicting_duplicate(self):
        await self.q.enqueue(chunk())
        self.assertEqual((await self.q.enqueue(replace(chunk(),clause_index=2))).reason,'conflicting_replay')
    async def test_gap_no_poison(self):
        self.assertEqual((await self.q.enqueue(chunk(1))).reason,'sequence_gap')
        self.assertTrue((await self.q.enqueue(chunk(0))).accepted)
        self.assertTrue((await self.q.enqueue(chunk(1))).accepted)
    async def test_capacity_transactional(self):
        for i in range(3):self.assertTrue((await self.q.enqueue(chunk(i))).accepted)
        self.assertEqual((await self.q.enqueue(chunk(3))).reason,'backpressure')
        await self.q.pop_next('m06')
        self.assertTrue((await self.q.enqueue(chunk(3))).accepted)
    async def test_duration_limit(self):
        small=MediaBuffer(self.m,max_ms_per_session=20)
        self.assertTrue((await small.enqueue(chunk())).accepted)
        self.assertEqual((await small.enqueue(chunk(1))).reason,'backpressure')
    async def test_independent_sessions(self):
        await self.q.enqueue(chunk())
        self.assertTrue((await self.q.enqueue(chunk(sid='other'))).accepted)
        self.assertEqual((await self.q.pop_next('other')).session_id,SessionId('other'))
    async def test_interruption_stales_old_generation(self):
        await self.q.enqueue(chunk())
        await self.m.interrupt('m06')
        self.assertEqual((await self.q.enqueue(chunk(1))).reason,'stale_generation_or_state')
        self.assertIsNone(await self.q.pop_next('m06'))
    async def test_interrupt_flush_discards_and_blocks(self):
        await self.q.enqueue(chunk())
        self.assertEqual(await self.q.begin_flush('m06'),1)
        self.assertEqual((await self.q.enqueue(chunk(1))).reason,'flush_pending')
        self.assertIsNone(await self.q.pop_next('m06'))
        await self.q.end_flush('m06')
        self.assertTrue((await self.q.enqueue(chunk(1))).accepted)
    async def test_discard_stale(self):
        await self.q.enqueue(chunk())
        await self.m.interrupt('m06')
        self.assertEqual(await self.q.discard_stale('m06'),1)
    async def test_terminal_rejects(self):
        await self.m.end('m06')
        self.assertFalse((await self.q.enqueue(chunk())).accepted)
    async def test_atomic_concurrent_sequence_race(self):
        items=await asyncio.gather(*[self.q.enqueue(chunk()) for _ in range(20)])
        self.assertEqual(sum(x.reason=='queued' for x in items),1)
        self.assertEqual((await self.q.metrics('m06')).pending_chunks,1)
    async def test_local_flush_no_pbx_proof(self):
        self.assertEqual(await self.q.begin_flush('m06'),0)
        self.assertEqual((await self.q.metrics('m06')).pending_ms,0)
    async def test_close_is_fail_closed(self):
        await self.q.enqueue(chunk());await self.q.close('m06')
        self.assertIsNone(await self.q.pop_next('m06'))
        self.assertEqual((await self.q.enqueue(chunk(1))).reason,'flush_pending')

class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.m=SessionManager(EventBus())
        self.r=ConversationReducer(self.m)
        self.sid='m06'
        self.q=MediaBuffer(self.m)
        self.t=FakeTransport(max_items=2,adapter_id='fake-PBX')
        self.c=MediaCoordinator(self.r,self.q,self.t)
        await self.signal(SignalKind.SESSION_OPENED)
        await self.signal(SignalKind.TRANSCRIPT_FINAL,ref='txt:1')
        await self.signal(SignalKind.LLM_RESPONSE_READY,ref='reply:1')
    async def signal(self,kind,ref=None,flush_id=None,seq=None,mono=10):
        snap=await self.r.try_snapshot(self.sid)
        return await self.r.handle(ConversationSignal.create(kind,self.sid,int(snap.turn_id) if snap else 0,int(snap.generation_id) if snap else 0,
                                 await self.r.expected_sequence(self.sid) if seq is None else seq,reference=ref,flush_request_id=flush_id,mono_ns=mono))
    async def barge(self):
        r=await self.signal(SignalKind.VAD_SPEECH_STARTED)
        self.assertEqual(r.state,State.INTERRUPTING)
        return r.effects[-1]
    async def test_send_nominal(self):
        self.assertTrue((await self.q.enqueue(chunk())).accepted)
        self.assertTrue((await self.c.send_next(self.sid)).accepted)
        self.assertEqual(self.t.stats(self.sid).queued_at_transport,1)
    async def test_xoff_backpressure_preserves_buffer(self):
        await self.q.enqueue(chunk())
        self.t.xoff(self.sid)
        self.assertEqual((await self.c.send_next(self.sid)).reason,'transport_backpressure')
        self.assertEqual((await self.q.metrics(self.sid)).pending_chunks,1)
        self.t.xon(self.sid)
        self.assertTrue((await self.c.send_next(self.sid)).accepted)
    async def test_transport_capacity_preserves_buffer(self):
        await self.q.enqueue(chunk())
        await self.q.enqueue(chunk(1))
        await self.q.enqueue(chunk(2))
        await self.c.send_next(self.sid);await self.c.send_next(self.sid)
        self.assertEqual((await self.c.send_next(self.sid)).reason,'transport_backpressure')
        self.assertEqual((await self.q.metrics(self.sid)).pending_chunks,1)
    async def test_flush_two_stage_with_explicit_fake_ack(self):
        await self.q.enqueue(chunk())
        await self.c.send_next(self.sid)
        f=await self.barge()
        req=await self.c.request_flush(f)
        self.assertEqual(req.flush_request_id,f.effect_id)
        self.assertEqual(self.t.stats(self.sid).queued_at_transport,1) # mock transport still pending until ACK
        self.assertEqual((await self.m.snapshot(self.sid)).state,State.INTERRUPTING)
        self.assertEqual((await self.q.metrics(self.sid)).pending_chunks,0)
        ack=await self.t.confirm_flush(self.sid,req.flush_request_id)
        self.assertTrue(ack.confirmed_by_adapter)
        result=await self.c.accept_fake_ack(ack,sequence=await self.r.expected_sequence(self.sid),mono_ns=11)
        self.assertEqual(result.state,State.LISTENING)
        self.assertEqual(self.t.stats(self.sid).queued_at_transport,0)
    async def test_forged_ack_without_transport_confirmation_rejected(self):
        f=await self.barge();req=await self.c.request_flush(f)
        fake_claim=FlushAck(req.flush_request_id,req.session_id,req.turn_id,req.generation_id,'fake-PBX',True)
        with self.assertRaises(ValueError):
            await self.c.accept_fake_ack(fake_claim,sequence=await self.r.expected_sequence(self.sid),mono_ns=12)
        self.assertEqual((await self.m.snapshot(self.sid)).state,State.INTERRUPTING)

    async def test_xoff_survives_flush_ack(self):
        self.t.xoff(self.sid)
        f=await self.barge();req=await self.c.request_flush(f)
        ack=await self.t.confirm_flush(self.sid,req.flush_request_id)
        await self.c.accept_fake_ack(ack,sequence=await self.r.expected_sequence(self.sid),mono_ns=13)
        self.assertFalse(self.t.can_send(self.sid))
        self.t.xon(self.sid)
        self.assertTrue(self.t.can_send(self.sid))

    async def test_transport_reject_after_pop_restores_chunk(self):
        await self.q.enqueue(chunk())
        original=self.t.send_metadata
        async def race(chunk):
            self.t.xoff(self.sid)
            return await original(chunk)
        self.t.send_metadata=race
        r=await self.c.send_next(self.sid)
        self.assertEqual(r.reason,'transport_backpressure_after_dequeue')
        self.assertEqual((await self.q.metrics(self.sid)).pending_chunks,1)

    async def test_wrong_ack_rejected(self):
        f=await self.barge();req=await self.c.request_flush(f)
        wrong=FlushAck(str(uuid4()),req.session_id,req.turn_id,req.generation_id,'fake-PBX',True)
        with self.assertRaises(ValueError):await self.c.accept_fake_ack(wrong,sequence=await self.r.expected_sequence(self.sid),mono_ns=12)
        self.assertEqual((await self.m.snapshot(self.sid)).state,State.INTERRUPTING)
    async def test_adapter_mismatch_rejected(self):
        f=await self.barge();req=await self.c.request_flush(f)
        wrong=FlushAck(req.flush_request_id,req.session_id,req.turn_id,req.generation_id,'other',True)
        with self.assertRaises(ValueError):await self.c.accept_fake_ack(wrong,sequence=await self.r.expected_sequence(self.sid),mono_ns=12)
    async def test_ack_replayed_rejected(self):
        f=await self.barge();req=await self.c.request_flush(f)
        ack=await self.t.confirm_flush(self.sid,req.flush_request_id)
        await self.c.accept_fake_ack(ack,sequence=await self.r.expected_sequence(self.sid),mono_ns=12)
        with self.assertRaises(ValueError):await self.c.accept_fake_ack(ack,sequence=await self.r.expected_sequence(self.sid),mono_ns=13)
    async def test_ack_requires_confirmed(self):
        f=await self.barge();req=await self.c.request_flush(f)
        fake_claim=FlushAck(req.flush_request_id,req.session_id,req.turn_id,req.generation_id,'fake-PBX',False)
        with self.assertRaises(ValueError):await self.c.accept_fake_ack(fake_claim,sequence=await self.r.expected_sequence(self.sid),mono_ns=12)
    async def test_flush_idempotent(self):
        f=await self.barge()
        self.assertEqual(await self.c.request_flush(f),await self.c.request_flush(f))
    async def test_no_flush_from_wrong_state(self):
        from automotive_voice.conversation.effects import Effect
        from uuid import uuid5,NAMESPACE_URL
        f=Effect(str(uuid4()),__import__('automotive_voice.conversation.effects',fromlist=['EffectKind']).EffectKind.FLUSH_MEDIA,SessionId(self.sid),TurnId(1),GenerationId(1),str(uuid4()))
        with self.assertRaises(ValueError):await self.c.request_flush(f)
    async def test_timeout_then_no_ack(self):
        f=await self.barge();req=await self.c.request_flush(f)
        await self.signal(SignalKind.MEDIA_FLUSH_TIMEOUT,flush_id=req.flush_request_id)
        ack=await self.t.confirm_flush(self.sid,req.flush_request_id)
        with self.assertRaises(ValueError):await self.c.accept_fake_ack(ack,sequence=await self.r.expected_sequence(self.sid),mono_ns=13)
        await self.c.terminate(self.sid)
        self.assertEqual(self.t.stats(self.sid).queued_at_transport,0)
    async def test_hangup_in_flight(self):
        f=await self.barge();await self.c.request_flush(f)
        await self.signal(SignalKind.HANGUP)
        await self.c.terminate(self.sid)
        self.assertFalse(self.t.can_send(self.sid))
    async def test_deferred_transcript_survives_ack(self):
        f=await self.barge();req=await self.c.request_flush(f)
        await self.signal(SignalKind.TRANSCRIPT_FINAL,ref='new:txt')
        ack=await self.t.confirm_flush(self.sid,req.flush_request_id)
        r=await self.c.accept_fake_ack(ack,sequence=await self.r.expected_sequence(self.sid),mono_ns=13)
        self.assertEqual(r.state,State.THINKING)
    async def test_invalid_sequence_ack_not_applied(self):
        f=await self.barge();req=await self.c.request_flush(f)
        ack=await self.t.confirm_flush(self.sid,req.flush_request_id)
        r=await self.c.accept_fake_ack(ack,sequence=99,mono_ns=13)
        self.assertEqual(r.decision,Decision.REJECTED)
        self.assertEqual((await self.m.snapshot(self.sid)).state,State.INTERRUPTING)
        r2=await self.c.accept_fake_ack(ack,sequence=await self.r.expected_sequence(self.sid),mono_ns=14)
        self.assertEqual(r2.decision,Decision.APPLIED)
