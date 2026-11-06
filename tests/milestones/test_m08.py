"""M08 acceptance: mock control-plane, evidence gate, local HTTP and security."""
from __future__ import annotations
from contextlib import closing
import asyncio
from contextlib import closing
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import io
import wave
import threading
import unittest
from automotive_voice.operator.runtime import ConsoleRuntime
from automotive_voice.operator.review_store import PronunciationReviewStore,ReviewError
from automotive_voice.operator.server import ConsoleHTTP

ROOT=Path(__file__).resolve().parents[2]

class M08CoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        self.app=ConsoleRuntime(ROOT/'data',Path(self.tmp.name)/'review.sqlite3')
        await self.app.initialize()
    async def _cleanup(self):self.tmp.cleanup()
    async def test_initial_dashboard(self):
        s=await self.app.snapshot()
        self.assertEqual(4,len(s['adapters']))
        self.assertTrue(all(a['mock_only'] for a in s['adapters']))
        self.assertFalse(s['real_pbx_connected'])
        self.assertFalse(s['production_ready'])
        self.assertEqual(0,s['audio_bytes_generated'])
        self.assertEqual(3,len(s['sources']))
    async def test_open_and_turn(self):
        sid=(await self.app.act('open'))['session_id']
        self.assertEqual('LISTENING',(await self.app.snapshot())['sessions'][0]['state'])
        self.assertEqual('THINKING',(await self.app.act('transcript',sid))['state'])
        self.assertEqual('SPEAKING',(await self.app.act('llm',sid))['state'])
        self.assertEqual('LISTENING',(await self.app.act('playout',sid))['state'])
    async def test_signal_guards_invalid_order(self):
        sid=(await self.app.act('open'))['session_id']
        r=await self.app.act('llm',sid)
        self.assertEqual('ignored',r['decision'])
        self.assertEqual('LISTENING',(await self.app.snapshot())['sessions'][0]['state'])
    async def test_barge_in_requires_fake_ack(self):
        sid=(await self.app.act('open'))['session_id']
        await self.app.act('transcript',sid)
        await self.app.act('llm',sid)
        await self.app.act('vad',sid)
        s=(await self.app.snapshot())['sessions'][0]
        self.assertEqual('INTERRUPTING',s['state'])
        self.assertTrue(s['pending_flush_id'])
        self.assertFalse((await self.app.snapshot())['real_pbx_connected'])
        ack=await self.app.act('fake_ack',sid)
        self.assertFalse(ack['real_pbx_proven'])
        self.assertEqual('LISTENING',ack['state'])
    async def test_no_ack_when_not_pending(self):
        sid=(await self.app.act('open'))['session_id']
        with self.assertRaisesRegex(ValueError,'no_pending_flush'):
            await self.app.act('fake_ack',sid)
    async def test_flush_timeout_safe_failure(self):
        sid=(await self.app.act('open'))['session_id']
        await self.app.act('transcript',sid)
        await self.app.act('llm',sid)
        await self.app.act('vad',sid)
        r=await self.app.act('tick',delta_ms=1600)
        self.assertEqual(1,r['flush_timeouts'])
        self.assertEqual('FAILED',(await self.app.snapshot())['sessions'][0]['state'])
    async def test_xoff_xon(self):
        sid=(await self.app.act('open'))['session_id']
        await self.app.act('xoff',sid)
        self.assertTrue((await self.app.snapshot())['sessions'][0]['transport_paused'])
        await self.app.act('xon',sid)
        self.assertFalse((await self.app.snapshot())['sessions'][0]['transport_paused'])
    async def test_multiple_sessions_separate(self):
        a=(await self.app.act('open'))['session_id']
        b=(await self.app.act('open'))['session_id']
        await self.app.act('transcript',a)
        s={r['session_id']:r for r in (await self.app.snapshot())['sessions']}
        self.assertEqual('THINKING',s[a]['state'])
        self.assertEqual('LISTENING',s[b]['state'])
    async def test_hangup_prevents_operations(self):
        sid=(await self.app.act('open'))['session_id']
        self.assertEqual('ENDED',(await self.app.act('hangup',sid))['state'])
        res=await self.app.act('transcript',sid)
        self.assertEqual('ignored',res['decision'])
    async def test_unknown_session_rejected(self):
        with self.assertRaisesRegex(ValueError,'unknown_console_session'):
            await self.app.act('transcript','bad-session')
    async def test_bad_clock_delta(self):
        for value in (0,-1,3,20.0,True):
            with self.assertRaises(ValueError):await self.app.act('tick',delta_ms=value)
    async def test_review_empty_and_cannot_invent(self):
        s=await self.app.snapshot()
        self.assertEqual([],s['annotations'])
        with self.assertRaises(ReviewError):
            await self.app.act('review',annotation_id='fake',decision='approved',reviewer='operator_01',reason_code='verified_evidence')
    async def test_timeline_no_raw_transcript(self):
        sid=(await self.app.act('open'))['session_id']
        await self.app.act('transcript',sid)
        history=json.dumps((await self.app.snapshot())['timeline'])
        self.assertNotIn('müşteri',history)
        self.assertIn('transcript_final',history)

class M08ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.src=self.path/'source.sqlite3'
        shutil.copy(ROOT/'data'/'a01yt'/'a01yt_v05_readonly.sqlite3',self.src)
        self.overlay=self.path/'operator.sqlite3'
        self.store=PronunciationReviewStore(self.src,self.overlay)
        self.source_id=self.store.sources()[0]['id']
        with closing(sqlite3.connect(self.src)) as conn, conn:
            conn.execute("UPDATE sources SET audio_use_authorized=1, permitted_scope='automotive_pronunciation_reference' WHERE id=?",(self.source_id,))
            conn.execute("INSERT INTO segments(id,source_id,start_sec,end_sec,clip_path,clip_sha256,audio_status,transcript_final,transcript_reviewer,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               ('segment-test',self.source_id,1.0,2.0,'clip.wav','','imported','Qashqai','reviewer_01','2026-01-01'))
            conn.execute("INSERT INTO annotations(id,segment_id,canonical,spoken_tr,kind,status) VALUES(?,?,?,?,?,?)",
               ('annot-test','segment-test','Qashqai','kaşkay','model','draft'))
    def test_cannot_approve_without_real_evidence(self):
        with self.assertRaisesRegex(ReviewError,'audio_evidence_required'):
            self.store.decide('annot-test','approved',reviewer='operator_01',reason_code='verified_evidence')
    def test_rejection_audited_but_source_untouched(self):
        record=self.store.decide('annot-test','rejected',reviewer='operator_01',reason_code='insufficient_evidence')
        self.assertEqual('rejected',record['decision'])
        self.assertEqual('rejected',self.store.items()[0]['review']['decision'])
        with closing(sqlite3.connect(self.src)) as conn, conn:self.assertEqual('draft',conn.execute("SELECT status FROM annotations WHERE id='annot-test'").fetchone()[0])
    def test_approval_requires_valid_checksum_and_transcript(self):
        tmp=io.BytesIO()
        with wave.open(tmp,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000)
            w.writeframes(b'\x00\x00'*320)
        clip=tmp.getvalue()
        (self.path/'clip.wav').write_bytes(clip)
        sha=hashlib.sha256(clip).hexdigest()
        with closing(sqlite3.connect(self.src)) as c, c:c.execute('UPDATE segments SET clip_sha256=? WHERE id=?',(sha,'segment-test'))
        record=self.store.decide('annot-test','approved',reviewer='operator_01',reason_code='verified_evidence')
        self.assertEqual(sha,record['source_sha256'])
        with closing(sqlite3.connect(self.src)) as conn: self.assertEqual('draft',conn.execute("SELECT status FROM annotations WHERE id='annot-test'").fetchone()[0])
    def test_checksum_mismatch_rejected(self):
        (self.path/'clip.wav').write_bytes(b'modified-test-fixture')
        with closing(sqlite3.connect(self.src)) as c, c:c.execute("UPDATE segments SET clip_sha256='deadbeef' WHERE id='segment-test'")
        with self.assertRaisesRegex(ReviewError,'checksum_mismatch'):
            self.store.decide('annot-test','approved',reviewer='operator_01',reason_code='verified_evidence')
    def test_invalid_wav_bytes_refused_even_with_matching_checksum(self):
        blob=b'not audio bytes despite .wav suffix'
        (self.path/'clip.wav').write_bytes(blob)
        sha=hashlib.sha256(blob).hexdigest()
        with closing(sqlite3.connect(self.src)) as conn, conn:conn.execute("UPDATE segments SET clip_sha256=? WHERE id='segment-test'",(sha,))
        with self.assertRaisesRegex(ReviewError,'invalid_pcm_audio_evidence'):
            self.store.decide('annot-test','approved',reviewer='operator_01',reason_code='verified_evidence')
    def test_path_traversal_rejected(self):
        (self.path/'clip.wav').write_bytes(b'fixture')
        with closing(sqlite3.connect(self.src)) as c, c:c.execute("UPDATE segments SET clip_path='../clip.wav',clip_sha256='123' WHERE id='segment-test'")
        with self.assertRaises(ReviewError):
            self.store.decide('annot-test','approved',reviewer='operator_01',reason_code='verified_evidence')
    def test_invalid_reviewer_rejected(self):
        with self.assertRaisesRegex(ReviewError,'invalid_reviewer'):
            self.store.decide('annot-test','rejected',reviewer='../bob',reason_code='duplicate')
    def test_unknown_annotation_rejected(self):
        with self.assertRaisesRegex(ReviewError,'unknown_annotation'):
            self.store.decide('missing','rejected',reviewer='operator_01',reason_code='duplicate')

class M08HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.runtime=ConsoleRuntime(ROOT/'data',Path(cls.tmp.name)/'review.sqlite3')
        cls.server=ConsoleHTTP(cls.runtime,port=0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.http.shutdown()
        cls.thread.join(timeout=5)
        cls.tmp.cleanup()
    def req(self,method,path,body=None,headers=None,host=None):
        conn=HTTPConnection('127.0.0.1',self.server.port,timeout=3)
        data=json.dumps(body).encode() if body is not None else None
        h={'Host':host or f'127.0.0.1:{self.server.port}',**(headers or {})}
        conn.request(method,path,data,h)
        r=conn.getresponse();buf=r.read();meta=dict(r.getheaders());status=r.status;conn.close()
        return status,meta,buf
    def test_serves_actual_ui_assets(self):
        for route,mime in (('/','text/html'),('/app.js','javascript'),('/app.css','text/css')):
            status,h,b=self.req('GET',route)
            self.assertEqual(200,status)
            self.assertIn(mime,h['Content-Type'])
            self.assertTrue(b)
            self.assertEqual('DENY',h['X-Frame-Options'])
    def test_csp_no_external_scripts(self):
        _,h,_=self.req('GET','/')
        self.assertIn("default-src 'none'",h['Content-Security-Policy'])
        self.assertIn("connect-src 'self'",h['Content-Security-Policy'])
    def test_snapshot_no_audio_and_source_records(self):
        status,_,buf=self.req('GET','/api/snapshot')
        d=json.loads(buf)
        self.assertEqual(200,status)
        self.assertEqual(0,d['audio_bytes_generated'])
        self.assertEqual(3,len(d['sources']))
    def test_post_without_csrf_forbidden(self):
        status,_,_=self.req('POST','/api/action',{'action':'open'},headers={'Content-Type':'application/json'})
        self.assertEqual(403,status)
    def test_origin_rejected_even_with_csrf(self):
        token=json.loads(self.req('GET','/api/bootstrap')[2])['csrf']
        code,_,_=self.req('POST','/api/action',{'action':'open'},headers={'Content-Type':'application/json','X-Console-CSRF':token,'Origin':'https://evil.example'})
        self.assertEqual(403,code)
    def test_host_rejected(self):
        status,_,_=self.req('GET','/api/snapshot',host='attacker.example')
        self.assertEqual(403,status)
    def test_post_open_valid_token(self):
        token=json.loads(self.req('GET','/api/bootstrap')[2])['csrf']
        status,_,buf=self.req('POST','/api/action',{'action':'open'},headers={'Content-Type':'application/json','X-Console-CSRF':token})
        self.assertEqual(200,status)
        self.assertTrue(json.loads(buf)['result']['session_id'].startswith('sim-'))
    def test_invalid_payload_rejected(self):
        token=json.loads(self.req('GET','/api/bootstrap')[2])['csrf']
        status,_,_=self.req('POST','/api/action',{'action':'open','unexpected':True},headers={'Content-Type':'application/json','X-Console-CSRF':token})
        self.assertEqual(422,status)
    def test_reject_remote_bind(self):
        with self.assertRaisesRegex(ValueError,'127.0.0.1'):
            ConsoleHTTP(self.runtime,host='0.0.0.0',port=0)

if __name__=='__main__':unittest.main()
