"""Fail-closed M11 acceptance tests; no model or external service required."""
import json
import tempfile
import unittest
import wave
from pathlib import Path
from automotive_voice.m11.acceptance import (
    Gate,Status,evidence_ref,save_gate,load_gate,summary,wav_info,
    error_rates,validate_pbx_trace,validate_voice_reviews,hash_file,now)


class M11EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)

    def evidence(self):
        p=self.base/'evidence.json';p.write_text('{"observed":"test"}',encoding='utf-8')
        return p

    def gate(self, name='freya_leyla',status=Status.HOLD,physical=False):
        return Gate(name,status,('test',),{},(evidence_ref(self.evidence()),),now(),physical)

    def test_missing_all_hold(self):
        self.assertEqual(summary(self.base)['overall'],'HOLD')
        self.assertEqual(len(summary(self.base)['gates']),8)

    def test_strict_gate_names(self):
        with self.assertRaises(ValueError):Gate('fake_pbx',Status.HOLD,(),{},(),now())

    def test_physical_pass_not_accepted_from_mock(self):
        with self.assertRaises(ValueError):self.gate(status=Status.PASS,physical=False)

    def test_real_pass_requires_evidence(self):
        with self.assertRaises(ValueError):Gate('codec',Status.PASS,(),{},(),now(),True)

    def test_regression_can_pass_without_physical(self):
        g=self.gate(name='legacy_regression',status=Status.PASS)
        save_gate(self.base,g)
        self.assertEqual(load_gate(self.base,'legacy_regression').status,Status.PASS)

    def test_evidence_tampering_rejects_pass(self):
        g=self.gate(status=Status.PASS,physical=True)
        save_gate(self.base,g)
        self.evidence().write_text('tampered',encoding='utf-8')
        with self.assertRaises(ValueError):load_gate(self.base,'freya_leyla')
        self.assertEqual(summary(self.base)['overall'],'FAIL')

    def test_renamed_gate_rejected(self):
        g=self.gate()
        save_gate(self.base,g)
        original=self.base/'freya_leyla.json'
        data=json.loads(original.read_text());data['name']='codec'
        original.write_text(json.dumps(data))
        with self.assertRaises(ValueError):load_gate(self.base,'freya_leyla')

    def test_invalid_pass_without_physical_on_disk_fails(self):
        g=self.gate()
        save_gate(self.base,g)
        path=self.base/'freya_leyla.json';obj=json.loads(path.read_text());obj['status']='PASS'
        path.write_text(json.dumps(obj))
        self.assertEqual(summary(self.base)['overall'],'FAIL')

    def test_pbx_fake_cannot_pass(self):
        with self.assertRaises(ValueError):validate_pbx_trace([
           {'event':'MEDIA_START','channel_id':'a','mono_ns':1,'provenance':'fake','mock':True}])

    @staticmethod
    def trace():
        types=('MEDIA_START','REPORT_QUEUE_DRAINED','FLUSH_MEDIA',
               'MEASURED_INTERRUPTION','QUEUE_DRAINED','HANGUP')
        out=[{'event':e,'channel_id':'lab-session','mono_ns':i+1,
              'provenance':'asterisk_live','mock':False} for i,e in enumerate(types)]
        out[0].update(codec='ulaw',ptime_ms=20)
        out[3]['heard_old_audio_ms_after_speech_start']=325
        return out

    def test_pbx_ordered_real_trace_fields(self):
        r=validate_pbx_trace(self.trace())
        self.assertTrue(r['latency_target_met'])

    def test_pbx_order_error(self):
        trace=self.trace();trace[2]['event'],trace[1]['event']=trace[1]['event'],trace[2]['event']
        with self.assertRaises(ValueError):validate_pbx_trace(trace)

    def test_pbx_mismatched_channel(self):
        trace=self.trace();trace[-1]['channel_id']='other'
        with self.assertRaises(ValueError):validate_pbx_trace(trace)

    def test_pbx_duplicate_mono(self):
        trace=self.trace();trace[-1]['mono_ns']=trace[-2]['mono_ns']
        with self.assertRaises(ValueError):validate_pbx_trace(trace)

    def test_pbx_stale_flush_ack_not_sufficient(self):
        trace=self.trace();trace[4]['event']='MEDIA_FLUSHED'
        with self.assertRaises(ValueError):validate_pbx_trace(trace)

    def test_pbx_slow_acoustic_stop_fails_latency(self):
        trace=self.trace();trace[3]['heard_old_audio_ms_after_speech_start']=500
        self.assertFalse(validate_pbx_trace(trace)['latency_target_met'])

    def test_empty_stt_reference_rejected(self):
        with self.assertRaises(ValueError):error_rates([('','')])

    def test_wer_cer_exact(self):
        self.assertEqual(error_rates([('Merhaba dünya','Merhaba dünya')])['wer'],0)
        self.assertEqual(error_rates([('Merhaba dünya','Merhaba dünya')])['cer'],0)

    def test_wer_one_substitution(self):
        result=error_rates([('merhaba dünya','merhaba kedi')])
        self.assertEqual(result['wer'],0.5)
        self.assertGreater(result['cer'],0)

    def test_unicode_casefold(self):
        self.assertEqual(error_rates([('İSTANBUL','istanbul')])['wer'],0)

    def test_wav_metadata(self):
        p=self.base/'test.wav'
        with wave.open(str(p),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\x00\x00'*320)
        self.assertEqual(wav_info(p)['duration_seconds'],0.02)

    def test_stereo_wav_rejected(self):
        p=self.base/'stereo.wav'
        with wave.open(str(p),'wb') as f:
            f.setnchannels(2);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\x00\x00'*4)
        with self.assertRaises(ValueError):wav_info(p)

    def test_voice_review_rejects_partial_corpus(self):
        with self.assertRaises(ValueError):
            validate_voice_reviews({'mode':'smoke','rows':[]},[],expected_cases=1)

    def test_voice_review_rejects_missing_human_review(self):
        with self.assertRaises(ValueError):
            validate_voice_reviews({'mode':'full','blocked':[],'failed':[],'rows':[]},[],expected_cases=1)

    def test_voice_review_rejects_bad_wav_hash(self):
        file=self.base/'wav.wav'
        with wave.open(str(file),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(48000);f.writeframes(b'\x00\x00'*480)
        rows=[{'id':'T01','variant':x,'wav':str(file),'sha256':'0'*64} for x in ('raw','prepared')]
        with self.assertRaises(ValueError):
            validate_voice_reviews({'mode':'full','blocked':[],'failed':[],'rows':rows},[{}],expected_cases=1)

    def test_hash_file(self):
        p=self.evidence();self.assertEqual(len(hash_file(p)),64)


if __name__=='__main__': unittest.main()
