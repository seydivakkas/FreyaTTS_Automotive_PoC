"""M10 dry-run: persistent atomicity, recovery hold, speech gating, no live adapters."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from automotive_voice.core.event_bus import EventBus, EventBusFull
from automotive_voice.core.session import State
from automotive_voice.core.identifiers import SessionId,TurnId,GenerationId
from automotive_voice.core.events import EventEnvelope,EventType
from automotive_voice.resilience.durable import DurableJournal,DurableSessionManager,DurableConflict
from automotive_voice.readiness.contracts import AdapterConfig,AdapterType,OfflineReadiness
from automotive_voice.readiness.presentation import PolicySpeechPresenter
from automotive_voice.dialogue.storage import StoredResponse
from automotive_voice.nlp.normalizer import TurkishAutomotiveNormalizer
from automotive_voice.prosody.planner import ProsodyClausePlanner
from automotive_voice.e2e import ScenarioRunner, SCENARIOS

class ReadinessTests(unittest.TestCase):
    def test_dryrun_has_no_activation(self):
        configs=[AdapterConfig(AdapterType.FREYA,'freyatts-local','',model_path='/not/a/model'),
                 AdapterConfig(AdapterType.STT,'whisper-local',model_path='/not/a/model'),
                 AdapterConfig(AdapterType.LLM,'ollama-local','http://127.0.0.1:11434'),
                 AdapterConfig(AdapterType.PBX,'asterisk-websocket','ws://127.0.0.1:8088',codec='slin16',sample_rate_hz=16000)]
        result=OfflineReadiness.evaluate(configs)
        self.assertFalse(result['production_ready']);self.assertEqual(0,result['external_connections'])
        self.assertEqual(4,len(result['adapters']))
        self.assertTrue(all(not x['ready_for_activation'] for x in result['adapters']))
    def test_remote_insecure_and_userinfo_rejected(self):
        c=AdapterConfig(AdapterType.LLM,'openai-compatible','http://example.com:80')
        self.assertIn('unencrypted_remote_transport',OfflineReadiness.check(c).findings)
        self.assertIn('external_endpoint_not_tested',OfflineReadiness.check(c).findings)
        c=replace(c,endpoint='https://user:secret@example.com/path')
        self.assertIn('unsafe_endpoint',OfflineReadiness.check(c).findings)
    def test_no_secrets_in_diagnostic(self):
        c=AdapterConfig(AdapterType.LLM,'ollama-local','http://127.0.0.1:1',secret_env='M10_MISSING_KEY',enabled=True)
        result=OfflineReadiness.check(c).as_dict()
        self.assertNotIn('secret',str(result).lower().replace('secret_missing_in_environment',''))
        self.assertIn('real_activation_explicitly_disabled_in_M10',result['findings'])
    def test_codec_contract(self):
        c=AdapterConfig(AdapterType.PBX,'asterisk-websocket','ws://localhost:8088',codec='ulaw',sample_rate_hz=16000)
        self.assertIn('codec_sample_rate_mismatch',OfflineReadiness.check(c).findings)
    def test_bad_config(self):
        with self.assertRaises(ValueError):OfflineReadiness.evaluate([])
        c=AdapterConfig(AdapterType.FREYA,'unknown',model_path='relative')
        self.assertIn('implementation_not_allowlisted',OfflineReadiness.check(c).findings)
        self.assertIn('absolute_model_path_required',OfflineReadiness.check(c).findings)

class PresentationTests(unittest.TestCase):
    def setUp(self):self.p=PolicySpeechPresenter();self.norm=TurkishAutomotiveNormalizer()
    def test_price_speech_distinct_from_display(self):
        o=self.p.render(StoredResponse('Tahmini araç değeri 1.250.000 Türk lirasıdır.','price_verified'))
        self.assertEqual('Tahmini araç değeri 1.250.000 Türk lirasıdır.',o.display_text)
        self.assertEqual('Tahmini araç değeri 1.250.000 TL.',o.speech_text)
        self.assertIn('bir milyon',self.norm.normalize(o.speech_text).spoken_text)
    def test_offer_iso_convert(self):
        t='2026-11-03T14:30:00+03:00 tarihinde, TRABZON lokasyonunda ekspertiz için müsaitlik var. Randevuyu onaylıyor musunuz?'
        o=self.p.render(StoredResponse(t,'offer_confirmation'))
        self.assertNotIn('2026-11-03T',o.speech_text)
        self.assertIn('saat 14:30',o.speech_text)
        self.assertFalse(self.norm.normalize(o.speech_text).review_required)
    def test_unknown_location_fails_closed(self):
        t='2026-11-03T14:30:00+03:00 tarihinde, UNKNOWN lokasyonunda ekspertiz için müsaitlik var.'
        o=self.p.render(StoredResponse(t,'offer_confirmation'))
        self.assertIn('slot_display_requires_review',o.warnings)
    def test_reference_masked_in_speech(self):
        o=self.p.render(StoredResponse('Ekspertiz randevunuz oluşturuldu. Onay referansı: id123XYZ.','booking_confirmed'))
        self.assertNotIn('id123XYZ',o.speech_text)
        self.assertIn('id123XYZ',o.display_text)
    def test_brand_not_transliterated(self):
        o=self.p.render(StoredResponse('Nissan Qashqai aracınız.','vehicle_verified'))
        self.assertEqual(o.display_text,o.speech_text)
    def test_unrecognized_reference_blocks(self):
        o=self.p.render(StoredResponse('Randevunuz onaylandı. Kod: 123-AA.','booking_confirmed'))
        self.assertIn('opaque_reference_requires_review',o.warnings)

class DurableTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'events.db'
        self.store=DurableJournal(self.path);self.bus=EventBus(default_capacity=10)
        self.manager=DurableSessionManager(self.bus,self.store,max_pending_events=4)
        await self.manager.restore_fail_closed()
    async def asyncTearDown(self):
        self.store.close();self.temp.cleanup()
    async def test_create_start_atomic_and_sequence(self):
        await self.manager.create('m10-a');await self.manager.start('m10-a');await self.manager.begin_turn('m10-a')
        snap=await self.manager.snapshot('m10-a');self.assertEqual(1,int(snap.generation_id))
        self.assertEqual(1,snap.last_sequence)
        self.assertEqual(2,self.store.counts()['pending_outbox'])
    async def test_crash_recovery_is_failclosed_and_does_not_replay_effects(self):
        await self.manager.create('m10-b');await self.manager.start('m10-b');await self.manager.begin_turn('m10-b')
        self.store.close();other=DurableJournal(self.path)
        mgr=DurableSessionManager(EventBus(),other)
        try:
            recovered=await mgr.restore_fail_closed()
            self.assertEqual(1,recovered)
            snap=await mgr.snapshot('m10-b')
            self.assertEqual(State.FAILED,snap.state)
            self.assertEqual(2,snap.last_sequence)
            self.assertFalse(await mgr.accepts_chunk('m10-b',1))
            self.assertEqual(3,other.counts()['pending_outbox'])
            await mgr.dispatch_pending('m10-b')
            self.assertEqual(0,other.counts()['pending_outbox'])
            with self.assertRaises((DurableConflict, ValueError)):
                await mgr.start('m10-b')
        finally:
            other.close()
            self.store=DurableJournal(self.path)
    async def test_restart_after_delivered_event_preserves_cursor(self):
        await self.manager.create('m10-c');await self.manager.start('m10-c')
        sub=await self.bus.subscribe('one')
        await self.manager.dispatch_pending('m10-c')
        self.assertEqual('session_started',sub.get_nowait().event_type.value)
        self.store.close();other=DurableJournal(self.path);mgr=DurableSessionManager(EventBus(),other)
        try:
            await mgr.restore_fail_closed()
            self.assertEqual(State.FAILED,(await mgr.snapshot('m10-c')).state)
            sub2=await mgr.bus.subscribe('one')
            self.assertEqual(1,await mgr.dispatch_pending('m10-c'))
            self.assertEqual(1,sub2.get_nowait().sequence)
        finally:
            other.close();self.store=DurableJournal(self.path)
    async def test_bus_backpressure_leaves_durable_pending(self):
        await self.manager.create('m10-d');await self.manager.start('m10-d')
        sub=await self.bus.subscribe('full',capacity=1)
        await self.bus.publish(EventEnvelope.create(EventType.SESSION_STARTED,SessionId('other'),TurnId(0),GenerationId(0),0))
        with self.assertRaises(EventBusFull): await self.manager.dispatch_pending('m10-d')
        self.assertEqual(1,self.store.counts()['pending_outbox'])
        sub.get_nowait()
        await self.manager.dispatch_pending('m10-d')
        self.assertEqual(0,self.store.counts()['pending_outbox'])
    async def test_failed_transaction_keeps_memory_unchanged(self):
        await self.manager.create('m10-e')
        fn=self.store.append
        def break_it(*a,**k):raise DurableConflict('injected_disk_failure')
        self.store.append=break_it
        try:
            with self.assertRaises(DurableConflict):await self.manager.start('m10-e')
            snap=await self.manager.snapshot('m10-e')
            self.assertEqual(State.IDLE,snap.state)
            self.assertEqual(-1,snap.last_sequence)
        finally:self.store.append=fn
    async def test_recovery_is_idempotent(self):
        await self.manager.create('m10-f')
        self.store.close();other=DurableJournal(self.path)
        mgr=DurableSessionManager(EventBus(),other)
        try:
            self.assertEqual(1,await mgr.restore_fail_closed())
            self.assertEqual(0,await mgr.restore_fail_closed())
            self.assertEqual(State.ENDED,(await mgr.snapshot('m10-f')).state)
        finally:other.close();self.store=DurableJournal(self.path)
    async def test_handoff_requires_reconciliation_after_restart(self):
        await self.manager.create('m10-handoff')
        await self.manager.start('m10-handoff')
        await self.manager.request_handoff('m10-handoff')
        self.store.close();other=DurableJournal(self.path)
        mgr=DurableSessionManager(EventBus(),other)
        try:
            self.assertEqual(1,await mgr.restore_fail_closed())
            self.assertEqual(State.FAILED,(await mgr.snapshot('m10-handoff')).state)
        finally:other.close();self.store=DurableJournal(self.path)

    async def test_terminal_not_recovered_as_new_call(self):
        await self.manager.create('m10-g');await self.manager.start('m10-g');await self.manager.end('m10-g')
        self.store.close();other=DurableJournal(self.path)
        mgr=DurableSessionManager(EventBus(),other)
        try:
            self.assertEqual(0,await mgr.restore_fail_closed())
            self.assertEqual(State.ENDED,(await mgr.snapshot('m10-g')).state)
        finally:other.close();self.store=DurableJournal(self.path)
    async def test_no_out_of_order_durable_ack(self):
        await self.manager.create('m10-order')
        await self.manager.start('m10-order')
        await self.manager.begin_turn('m10-order')
        with self.assertRaises(DurableConflict):self.store.ack('m10-order',1)
        self.assertEqual(2,self.store.counts()['pending_outbox'])

    async def test_pii_payload_refused(self):
        await self.manager.create('m10-pii')
        old=self.manager._entry('m10-pii').value
        e=EventEnvelope.create(EventType.ERROR,SessionId('m10-pii'),TurnId(0),GenerationId(0),0,
                               {'transcript':'Müşteri adı burada bulunmamalı'})
        with self.assertRaises(DurableConflict):self.store.append(old,old,-1,[e])
        self.assertEqual(-1,(await self.manager.snapshot('m10-pii')).last_sequence)

    async def test_duplicate_session_rejected(self):
        await self.manager.create('m10-h')
        with self.assertRaises(Exception):await self.manager.create('m10-h')

class M10ScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_business_scenarios_with_durable_persistence_and_speech_presentation(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as td:
                journal=DurableJournal(Path(td)/'events.db')
                try:
                    report=await ScenarioRunner(m10_presentation=True,durable_journal=journal).run(scenario)
                    self.assertTrue(report.passed,scenario)
                    self.assertGreater(journal.counts()['pending_outbox'],0)
                    self.assertFalse(report.to_dict()['production_ready'])
                finally:journal.close()

class M10ConsoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_readiness_dashboard_is_offline(self):
        from automotive_voice.operator.runtime import ConsoleRuntime
        root=Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as td:
            app=ConsoleRuntime(root/'data',Path(td)/'overlay.db')
            await app.initialize()
            snap=await app.snapshot()
            self.assertEqual('M10_DRY_RUN',snap['m10_readiness']['mode'])
            self.assertEqual(4,len(snap['m10_readiness']['adapters']))
            self.assertFalse(snap['durable_outbox_in_console'])
            self.assertEqual(0,snap['m10_readiness']['external_connections'])
