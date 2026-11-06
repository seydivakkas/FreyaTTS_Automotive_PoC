"""M01 stdlib-only unit/contract/mock concurrency tests; no real audio."""
import asyncio
import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from datetime import datetime
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.core.events import EventEnvelope, EventType
from automotive_voice.core.event_bus import EventBus, EventBusFull, EventBusClosed, EventOrderingError
from automotive_voice.core.cancellation import CancellationController, StaleGenerationError
from automotive_voice.core.session_manager import SessionManager, UnknownSessionError, SessionAlreadyExistsError, SessionOutboxFullError
from automotive_voice.core.session import State
from automotive_voice.core.audio import AudioFormat, AudioFrame

ROOT = Path(__file__).resolve().parents[2]

def event(sid="test-1", seq=0, et=EventType.SESSION_STARTED):
    return EventEnvelope.create(et, SessionId(sid), TurnId(0), GenerationId(0), seq,
                                {"nested": {"x": [1, 2]}})

class IdAndEnvelopeTests(unittest.TestCase):
    def test_session_id_validity(self):
        for value in ("", " ", "../token", "foo/bar", "ğç", "x"*129):
            with self.subTest(value=value), self.assertRaises(ValueError): SessionId(value)
        self.assertEqual(SessionId("S-001"), "S-001")
        self.assertTrue(SessionId.new())

    def test_monotonic_identifiers_guard_bool_negative_float(self):
        for typ in (TurnId, GenerationId):
            for value in (-1, True, False, 1.2, "1", 2**63):
                with self.subTest(typ=typ, value=value), self.assertRaises(ValueError): typ(value)
            self.assertEqual(typ(3), 3)

    def test_round_trip_schema_and_utc(self):
        original = event()
        self.assertEqual(EventEnvelope.from_dict(json.loads(json.dumps(original.to_dict()))).to_dict(), original.to_dict())
        self.assertIsNotNone(datetime.fromisoformat(original.occurred_at_utc.replace("Z", "+00:00")).utcoffset())
        schema = json.loads((ROOT/"contracts/event.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), set(original.to_dict()))
        self.assertEqual(set(schema["properties"]["event_type"]["enum"]), {e.value for e in EventType})
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0")

    def test_strict_wire_validation(self):
        body = event().to_dict()
        for key, value in (("turn_id", True), ("generation_id", -2), ("sequence", -1), ("event_type", "garbage"), ("occurred_at_utc", "2026-01-01T12:00:00"), ("event_id", "123")):
            invalid = dict(body); invalid[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): EventEnvelope.from_dict(invalid)
        with self.assertRaises(ValueError): EventEnvelope.from_dict({**body, "unknown": 5})
        with self.assertRaises(ValueError): EventEnvelope.create(EventType.ERROR, SessionId("x"), TurnId(0), GenerationId(0), 0, {"bad": float('nan')})

    def test_payload_immutable_and_consumer_isolated(self):
        source={"nested":{"x":[1]}}
        item=EventEnvelope.create(EventType.ERROR, SessionId("x"), TurnId(0), GenerationId(0), 0, source)
        source['nested']['x'].append(99)
        self.assertEqual(item.to_dict()['payload']['nested']['x'],[1])
        with self.assertRaises(TypeError):item.payload['nested']['x'] = (3,)
        with self.assertRaises(TypeError):item.payload['nested']['x'][0] = 1
        new=item.to_dict();new['payload']['nested']['x'].append(10)
        self.assertEqual(item.to_dict()['payload']['nested']['x'],[1])

class AudioContractsTests(unittest.TestCase):
    def test_20ms_8khz_pcm16(self):
        fmt=AudioFormat(8000,1,16,"pcm_s16le")
        frame=AudioFrame(SessionId("s"), "egress", GenerationId(7),0,160,1234,fmt,b"\x00"*320)
        self.assertEqual(len(frame.payload),320)
        with self.assertRaises(ValueError):
            AudioFrame(SessionId("s"), "egress", GenerationId(7),0,161,1234,fmt,b"\x00"*320)

    def test_g711_frame_size_and_rate(self):
        fmt=AudioFormat(8000,1,8,"mulaw")
        f=AudioFrame(SessionId("s"),"line",GenerationId(0),0,160,88,fmt,b"\x00"*160)
        self.assertEqual(len(f.payload),160)
        with self.assertRaises(ValueError):AudioFormat(16000,1,8,"alaw")

    def test_explicit_format_conversion_required(self):
        a=AudioFormat(8000,1,16,"pcm_s16le")
        b=AudioFormat(16000,1,16,"pcm_s16le")
        with self.assertRaises(ValueError):a.assert_compatible(b)
        with self.assertRaises(ValueError):AudioFormat(48000,2,16,"pcm_s16le")
        with self.assertRaises(ValueError):AudioFormat(8000,1,8,"pcm_s16le")
        with self.assertRaises(ValueError):AudioFormat(16000,1,8,"mulaw")
        with self.assertRaises(TypeError): AudioFrame(SessionId('s'),'mic',GenerationId(0),0,1,1,a,bytearray(2))

class AsyncContractsTests(unittest.IsolatedAsyncioTestCase):
    async def test_bus_atomic_backpressure_and_retry(self):
        b=EventBus(default_capacity=1)
        fast=await b.subscribe('fast'); slow=await b.subscribe('slow')
        x0=event(seq=0);x1=event(seq=1)
        await b.publish(x0)
        self.assertEqual(fast.get_nowait().event_id,x0.event_id)
        with self.assertRaises(EventBusFull):await b.publish(x1)
        self.assertEqual(fast.pending,0)
        self.assertEqual(slow.get_nowait().event_id,x0.event_id)
        await b.publish(x1)
        self.assertEqual(fast.get_nowait().event_id,x1.event_id)
        self.assertEqual(slow.get_nowait().event_id,x1.event_id)

    async def test_bus_rejects_duplicates_order_errors_and_closed(self):
        b=EventBus()
        s=await b.subscribe('a')
        with self.assertRaises(EventOrderingError):await b.publish(event(seq=2))
        await b.publish(event(seq=0))
        with self.assertRaises(EventOrderingError):await b.publish(event(seq=0))
        await b.close()
        with self.assertRaises(EventBusClosed):await b.publish(event(seq=1))
        with self.assertRaises(EventBusClosed):await b.subscribe('new')
        self.assertEqual(s.pending,1)

    async def test_session_lifecycle_and_event_order(self):
        b=EventBus();sub=await b.subscribe('observer');m=SessionManager(b)
        await m.create('sess1');await m.start('sess1');first=await m.begin_turn('sess1')
        self.assertEqual(first.turn_id,1);self.assertEqual(first.generation_id,1)
        await m.begin_response('sess1')
        self.assertTrue(await m.accepts_chunk('sess1',1))
        old_token=await m.current_token('sess1')
        current=await m.interrupt('sess1')
        self.assertEqual(current.generation_id,2)
        self.assertTrue(old_token.cancelled)
        self.assertFalse(await m.accepts_chunk('sess1',1))
        await m.complete_interrupt('sess1')
        await m.begin_turn('sess1');await m.begin_response('sess1')
        self.assertTrue(await m.accepts_chunk('sess1',3))
        await m.end('sess1');before=await m.snapshot('sess1')
        self.assertEqual(before.state,State.ENDED)
        self.assertEqual(await m.end('sess1'),before)
        self.assertEqual(await m.dispatch_pending('sess1'),8)
        events=[sub.get_nowait() for _ in range(8)]
        self.assertEqual([e.sequence for e in events],list(range(8)))
        self.assertEqual(events[-1].event_type,EventType.SESSION_ENDED)
        self.assertEqual((await m.snapshot('sess1')).pending_events,0)

    async def test_prevent_invalid_transition_without_mutation(self):
        m=SessionManager(EventBus())
        await m.create('s1')
        before=await m.snapshot('s1')
        with self.assertRaises(ValueError):await m.begin_response('s1')
        self.assertEqual(await m.snapshot('s1'),before)
        with self.assertRaises(SessionAlreadyExistsError):await m.create('s1')
        with self.assertRaises(UnknownSessionError):await m.snapshot('unknown')

    async def test_outbox_full_rollback_then_recover(self):
        b=EventBus(default_capacity=1);sub=await b.subscribe('client')
        m=SessionManager(b,max_pending_events=2)
        await m.create('s')
        await m.start('s');await m.begin_turn('s')
        snapshot=await m.snapshot('s')
        with self.assertRaises(SessionOutboxFullError):await m.begin_response('s')
        self.assertEqual((await m.snapshot('s')),snapshot)
        with self.assertRaises(EventBusFull):await m.dispatch_pending('s')
        self.assertEqual((await m.snapshot('s')).pending_events,1)
        self.assertEqual(sub.get_nowait().sequence,0)
        self.assertEqual(await m.dispatch_pending('s'),1)
        self.assertEqual(sub.get_nowait().sequence,1)
        await m.begin_response('s')
        self.assertEqual((await m.snapshot('s')).state,State.SPEAKING)

    async def test_parallel_sessions_no_crosstalk(self):
        b=EventBus();sub=await b.subscribe('audit');m=SessionManager(b)
        async def run(name):
            await m.create(name);await m.start(name);await m.begin_turn(name)
            await m.begin_response(name);await m.finish_playout(name);await m.end(name)
            await m.dispatch_pending(name)
        await asyncio.gather(*(run(f's{i}') for i in range(12)))
        result={}
        while sub.pending:
            e=sub.get_nowait()
            result.setdefault(e.session_id,[]).append(e.sequence)
        self.assertEqual(len(result),12)
        self.assertTrue(all(v==list(range(5)) for v in result.values()))

    async def test_cancellation_of_registered_task(self):
        b=EventBus();m=SessionManager(b)
        await m.create('s');await m.start('s');await m.begin_turn('s');await m.begin_response('s')
        observed=asyncio.Event()
        async def pending():
            try:await asyncio.Event().wait()
            except asyncio.CancelledError:
                observed.set();raise
        task=asyncio.create_task(pending());await asyncio.sleep(0)
        await m.register_task('s',1,task)
        await m.interrupt('s')
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(observed.is_set())
        with self.assertRaises(StaleGenerationError):await m.register_task('s',1,asyncio.create_task(asyncio.sleep(0)))

    async def test_cancellation_token_wait(self):
        c=CancellationController()
        token=c.current
        task=asyncio.create_task(token.wait_cancelled())
        c.advance(GenerationId(1))
        await asyncio.wait_for(task,0.5)
        self.assertTrue(token.cancelled)
        self.assertFalse(c.is_current(0))
        self.assertTrue(c.is_current(1))
        with self.assertRaises(ValueError):c.advance(GenerationId(1))

    async def test_handoff_and_terminal_behavior(self):
        m=SessionManager(EventBus())
        await m.create('handoff');await m.start('handoff')
        await m.request_handoff('handoff')
        self.assertEqual((await m.snapshot('handoff')).state,State.HANDOFF)
        await m.end('handoff')
        with self.assertRaises(ValueError):await m.begin_turn('handoff')
        with self.assertRaises(ValueError):await m.current_token('handoff')

    async def test_failure_is_terminal_and_cancels(self):
        m=SessionManager(EventBus());await m.create('f');await m.start('f')
        token=await m.current_token('f')
        await m.fail('f','test_failure')
        self.assertTrue(token.cancelled)
        self.assertEqual((await m.snapshot('f')).state,State.FAILED)
        await m.end('f')
        self.assertEqual((await m.snapshot('f')).state,State.ENDED)

    async def test_stale_chunk_rejection_survives_next_turn(self):
        m=SessionManager(EventBus());await m.create('s');await m.start('s')
        await m.begin_turn('s');await m.begin_response('s')
        await m.interrupt('s');await m.complete_interrupt('s')
        await m.begin_turn('s');await m.begin_response('s')
        self.assertFalse(await m.accepts_chunk('s',1))
        self.assertFalse(await m.accepts_chunk('s',2))
        self.assertTrue(await m.accepts_chunk('s',3))

    async def test_unsubscribe_removes_fanout(self):
        b=EventBus(default_capacity=1)
        sub=await b.subscribe('short')
        await b.publish(event(seq=0))
        await b.unsubscribe('short')
        await b.publish(event(seq=1))
        self.assertEqual(sub.pending,1)
        self.assertEqual(sub.get_nowait().sequence,0)
        with self.assertRaises(EventBusClosed):await sub.get()

    async def test_many_concurrent_same_session_turns_only_one_wins(self):
        m=SessionManager(EventBus())
        await m.create('one');await m.start('one')
        outcomes=await asyncio.gather(*(m.begin_turn('one') for _ in range(20)),return_exceptions=True)
        self.assertEqual(sum(not isinstance(x,Exception) for x in outcomes),1)
        self.assertEqual((await m.snapshot('one')).turn_id,1)
        self.assertEqual((await m.snapshot('one')).last_sequence,1)
