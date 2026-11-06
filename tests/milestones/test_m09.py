"""M09 scenario integration / UI security / regression contract tests; no real audio."""
from __future__ import annotations
import asyncio
from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from automotive_voice.e2e import ScenarioRunner,SCENARIOS
from automotive_voice.e2e.runner import run_catalog
from automotive_voice.operator.runtime import ConsoleRuntime
from automotive_voice.operator.server import ConsoleHTTP
from automotive_voice.nlp.nlu import DeterministicNLU, ParseContext
from automotive_voice.dialogue.models import Intent
from automotive_voice.conversation.signals import SignalKind
from automotive_voice.conversation.reducer import Decision
from automotive_voice.core.session import State
ROOT=Path(__file__).resolve().parents[2]

class M09Scenarios(unittest.IsolatedAsyncioTestCase):
    async def test_whole_catalog(self):
        data=await run_catalog()
        self.assertEqual(len(SCENARIOS),data['passed'])
        self.assertEqual(0,data['failed'])
        self.assertEqual(0,data['audio_bytes_generated'])
        self.assertFalse(data['production_ready'])
        self.assertFalse(data['real_pbx_connected'])
    async def test_scenario_names_restricted(self):
        for bad in ('__import__','../passwd','','unknown',None,42):
            with self.assertRaises(ValueError):await ScenarioRunner().run(bad)
    async def test_e2e_not_physical_audio(self):
        for name in ('price_verified','booking_confirmed','barge_in_ack'):
            r=(await ScenarioRunner().run(name)).to_dict()
            self.assertEqual(0,r['audio_bytes_generated'])
            self.assertFalse(r['real_model_called'])
            self.assertFalse(r['real_crm_connected'])
            self.assertFalse(r['real_pbx_connected'])
    async def test_price_m04_review_must_not_fake_audio(self):
        r=(await ScenarioRunner().run('price_verified')).to_dict()
        self.assertTrue(r['passed'])
        self.assertEqual(0,r['sessions'][0]['fake_transport_sent'])
        self.assertTrue(any(t['step']=='prosody' and t['outcome']=='review_required' for t in r['trace']))
    async def test_valid_safe_response_generates_fake_metadata(self):
        r=(await ScenarioRunner().run('price_expired')).to_dict()
        self.assertTrue(r['passed'])
        self.assertGreater(r['sessions'][0]['fake_transport_sent'],0)
        self.assertEqual(0,r['audio_bytes_generated'])
    async def test_no_automatic_flush_ack(self):
        x=ScenarioRunner();sid='ack-barrier'
        await x.open(sid)
        await x.user(sid,'merhaba',auto_playout=False)
        await x.interrupt(sid)
        self.assertEqual(State.INTERRUPTING,(await x.reducer.try_snapshot(sid)).state)
        self.assertFalse(x.transport._confirmed)
        self.assertIsNotNone(await x.reducer.pending_flush_id(sid))
        r=await x.fake_ack(sid)
        self.assertEqual(Decision.APPLIED,r.decision)
        self.assertEqual(State.LISTENING,r.state)
        with self.assertRaises(ValueError):await x.fake_ack(sid)
    async def test_same_response_idempotency_across_resubmission(self):
        r=(await ScenarioRunner().run('duplicate_confirmation')).to_dict()
        self.assertTrue(r['checks']['repeat_not_second_booking'])
    async def test_wrong_answer_cannot_be_resolved_to_booking(self):
        runner=ScenarioRunner();sid='no-implicit-consent'
        await runner.open(sid)
        r=await runner.user(sid,'evet')
        self.assertIn(r['action'],('clarify','no_offer'))
        self.assertEqual(0,runner.booking.creations)
    async def test_text_not_in_safe_e2e_trace(self):
        runner=ScenarioRunner();r=(await runner.run('booking_confirmed')).to_dict()
        raw=json.dumps(r,ensure_ascii=False)
        self.assertNotIn('Qashqai için Trabzon 03.11.2026',raw)
        self.assertNotIn('1.250.000',raw)
        self.assertNotIn('onay referansı:',raw.lower())
    async def test_cross_session_no_booking_leak(self):
        r=(await ScenarioRunner().run('multi_session')).to_dict()
        self.assertEqual(2,len(r['sessions']))
        self.assertEqual(0,sum(s['pending_flush'] for s in r['sessions']))
        self.assertTrue(r['checks']['separate_policy'])
    async def test_generation_monotonic_on_interrupt(self):
        runner=ScenarioRunner();sid='gen-monotonic'
        await runner.open(sid)
        await runner.user(sid,'merhaba',auto_playout=False,stream=False)
        before=await runner.reducer.try_snapshot(sid)
        await runner.interrupt(sid)
        after=await runner.reducer.try_snapshot(sid)
        self.assertGreater(int(after.generation_id),int(before.generation_id))
        self.assertFalse(await runner.manager.accepts_chunk(sid,int(before.generation_id)))
    async def test_hangup_does_not_resume(self):
        r=(await ScenarioRunner().run('hangup_cancels')).to_dict()
        self.assertTrue(r['passed'])
        self.assertEqual('ENDED',r['sessions'][0]['state'])
    async def test_handoff_turkish_suffix(self):
        p=DeterministicNLU().parse('Lütfen beni temsilciye aktarın',ParseContext())
        self.assertEqual(Intent.HANDOFF,p.dialogue_input.intent)
    async def test_m09_does_not_mutate_golden(self):
        older=ROOT/'data/fixtures/legacy_320_cases.json'
        local=ROOT/'data/fixtures/legacy_320_cases.json'
        self.assertEqual('7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e',sha256(local.read_bytes()).hexdigest())
    async def test_no_pending_flush_when_normal_price(self):
        r=(await ScenarioRunner().run('price_expired')).to_dict()
        self.assertFalse(r['sessions'][0]['pending_flush'])
    async def test_adapter_disconnect_recover_isolated(self):
        r=(await ScenarioRunner().run('adapter_disconnect')).to_dict()
        self.assertTrue(r['checks']['isolated_degradation'])
        self.assertTrue(r['checks']['recovered'])
    async def test_call_timeout_terminal(self):
        r=(await ScenarioRunner().run('barge_in_timeout')).to_dict()
        self.assertTrue(r['passed'])
        self.assertEqual('FAILED',r['sessions'][0]['state'])
    async def test_no_speech_file_artifacts_created_by_catalog(self):
        with tempfile.TemporaryDirectory() as d:
            await run_catalog()
            self.assertEqual([],list(Path(d).iterdir()))

async def _case(name):
    r=await ScenarioRunner().run(name)
    assert r.passed, f'{name} failed: {r.checks}, {r.notes}'

for _scenario in SCENARIOS:
    async def _test(self,name=_scenario):
        r=await ScenarioRunner().run(name)
        self.assertTrue(r.passed,(name,r.checks,r.notes))
        self.assertEqual(0,r.to_dict()['audio_bytes_generated'])
    setattr(M09Scenarios,'test_case_'+_scenario,_test)

class M09OperatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self.tmp.cleanup)
        self.app=ConsoleRuntime(ROOT/'data',Path(self.tmp.name)/'review.sqlite3')
        await self.app.initialize()
    async def _cleanup(self):self.tmp.cleanup()
    async def test_20_scenarios_visible_in_read_model(self):
        snap=await self.app.snapshot()
        self.assertEqual(20,len(snap['scenario_catalog']))
        self.assertEqual([],snap['scenario_reports'])
    async def test_scenario_action_restricts_names(self):
        for name in ('../oops','__class__','',None,15):
            with self.assertRaises(ValueError):await self.app.act('run_scenario',scenario=name)
    async def test_scenario_exposed_to_m08_ui(self):
        outcome=await self.app.act('run_scenario',scenario='booking_confirmed')
        self.assertTrue(outcome['passed'])
        snap=await self.app.snapshot()
        self.assertEqual(1,len(snap['scenario_reports']))
        self.assertEqual('booking_confirmed',snap['scenario_reports'][0]['scenario'])
        self.assertEqual(0,snap['scenario_reports'][0]['audio_bytes_generated'])
        self.assertEqual(0,len(snap['sessions']))
    async def test_reports_bounded(self):
        for _ in range(14):
            await self.app.act('run_scenario',scenario='price_expired')
        self.assertEqual(12,len((await self.app.snapshot())['scenario_reports']))
    async def test_trace_privacy(self):
        await self.app.act('run_scenario',scenario='booking_confirmed')
        snap=await self.app.snapshot()
        txt=json.dumps(snap['scenario_reports'],ensure_ascii=False)
        self.assertNotIn('Qashqai için Trabzon 03.11.2026',txt)
    async def test_old_console_actions_still_work(self):
        sid=(await self.app.act('open'))['session_id']
        await self.app.act('run_scenario',scenario='price_verified')
        self.assertEqual('LISTENING',(await self.app.snapshot())['sessions'][0]['state'])
        self.assertEqual('THINKING',(await self.app.act('transcript',sid))['state'])

class M09HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.runtime=ConsoleRuntime(ROOT/'data',Path(cls.tmp.name)/'review.sqlite3')
        cls.server=ConsoleHTTP(cls.runtime,port=0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.http.shutdown();cls.thread.join(timeout=4)
        cls.tmp.cleanup()
    def req(self,method,path,body=None,headers=None,host=None):
        conn=HTTPConnection('127.0.0.1',self.server.port,timeout=4)
        data=json.dumps(body).encode() if body is not None else None
        h={'Host':host or f'127.0.0.1:{self.server.port}',**(headers or {})}
        conn.request(method,path,data,h)
        r=conn.getresponse();buf=r.read();status=r.status;conn.close()
        return status,buf
    def token(self):return json.loads(self.req('GET','/api/bootstrap')[1])['csrf']
    def test_ui_has_scenario_tab(self):
        code,body=self.req('GET','/')
        self.assertEqual(200,code)
        self.assertIn(b'data-view="scenarios"',body)
        js=self.req('GET','/app.js')[1]
        self.assertIn(b'run_scenario',js)
    def test_csrf_required_for_scenario(self):
        code,_=self.req('POST','/api/action',{'action':'run_scenario','scenario':'price_verified'},headers={'Content-Type':'application/json'})
        self.assertEqual(403,code)
    def test_scenario_valid_post(self):
        code,body=self.req('POST','/api/action',{'action':'run_scenario','scenario':'booking_declined'},headers={'Content-Type':'application/json','X-Console-CSRF':self.token()})
        self.assertEqual(200,code)
        self.assertTrue(json.loads(body)['result']['passed'])
        self.assertGreaterEqual(len(json.loads(self.req('GET','/api/snapshot')[1])['scenario_reports']),1)
    def test_scenario_bad_post(self):
        code,_=self.req('POST','/api/action',{'action':'run_scenario','scenario':'../../../passwd'},headers={'Content-Type':'application/json','X-Console-CSRF':self.token()})
        self.assertEqual(422,code)
    def test_invalid_host_rejected(self):
        code,_=self.req('GET','/api/snapshot',host='evil.example')
        self.assertEqual(403,code)
