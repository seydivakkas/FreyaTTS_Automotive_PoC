"""M07 contract schemas and round-trip validation (no network)."""
import unittest, pathlib,json
from dataclasses import asdict
from automotive_voice.adapters.lifecycle import (
    Deadline, RetryPolicy, AdapterKind, AdapterState, SyntheticCommand,
    SyntheticResult, ResultCode, CircuitState, HealthSnapshot, StreamReceipt)
from automotive_voice.core.identifiers import SessionId,TurnId,GenerationId
try:
    from jsonschema import Draft202012Validator,ValidationError
except ImportError:
    Draft202012Validator=None

ROOT=pathlib.Path(__file__).resolve().parents[2]
class M07Schemas(unittest.TestCase):
    def setUp(self):
        if Draft202012Validator is None:self.skipTest('install optional validation extra: pip install -e .[validation]')
    def schema(self,name):
        s=json.loads((ROOT/'contracts'/f'm07_{name}.schema.json').read_text('utf-8'))
        Draft202012Validator.check_schema(s)
        return Draft202012Validator(s)
    def command(self):
        return SyntheticCommand('abc:1',AdapterKind.TTS,SessionId('m07'),TurnId(1),GenerationId(1),0,'ref:hash',Deadline(500))
    def test_all_five_schemas(self):
        self.assertEqual(len(list((ROOT/'contracts').glob('m07_*.schema.json'))),5)
        for name in ('synthetic_command','synthetic_result','health_snapshot','retry_policy','stream_receipt'):
            self.schema(name)
    def test_command(self):
        v=self.schema('synthetic_command');v.validate(self.command().safe_metadata())
    def test_command_reject_raw_text(self):
        v=self.schema('synthetic_command');value=self.command().safe_metadata();value['payload_ref']='Türkçe gizli metin'
        with self.assertRaises(ValidationError):v.validate(value)
    def test_result(self):
        v=self.schema('synthetic_result')
        r=SyntheticResult('abc:1',AdapterKind.TTS,SessionId('m07'),TurnId(1),GenerationId(1),ResultCode.OK,1,'mock-tts:abc:1')
        v.validate(r.safe_metadata())
    def test_health(self):
        v=self.schema('health_snapshot')
        h=HealthSnapshot(AdapterKind.TTS,AdapterState.READY,CircuitState.CLOSED,1,0,0,None,0)
        v.validate(h.safe_metadata())
    def test_retry(self):
        self.schema('retry_policy').validate(RetryPolicy().safe_metadata())
    def test_stream(self):
        self.schema('stream_receipt').validate(asdict(StreamReceipt(True,'mock_metadata_queued','clause:1')))
    def test_schema_reject_unexpected(self):
        v=self.schema('synthetic_command');c=self.command().safe_metadata();c['raw_audio']='secret'
        with self.assertRaises(ValidationError):v.validate(c)
