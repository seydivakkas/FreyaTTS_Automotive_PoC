"""M06 JSON boundary tests. JSON is public metadata; never raw audio."""
from pathlib import Path
import json
import unittest
from dataclasses import asdict
from automotive_voice.audio import Codec,MediaFormat,AudioChunkMetadata
from automotive_voice.core.identifiers import SessionId,TurnId,GenerationId
ROOT=Path(__file__).resolve().parents[2]

class SchemaTests(unittest.TestCase):
    def setUp(self):
        try:
            import jsonschema
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest('Install optional [validation] extra')
        self.jsonschema=jsonschema
        self.schemas={p.name:json.loads(p.read_text('utf-8')) for p in (ROOT/'contracts').glob('m06_*.schema.json')}
        self.registry=Registry().with_resources([(name,Resource.from_contents(schema)) for name,schema in self.schemas.items()])
    def check(self,name,data):
        self.jsonschema.Draft202012Validator(self.schemas[name+'.schema.json'],registry=self.registry).validate(data)
    def test_all_schemas_valid(self):
        for schema in self.schemas.values(): self.jsonschema.Draft202012Validator.check_schema(schema)
    def test_chunk_metadata_safe(self):
        c=AudioChunkMetadata(SessionId('schema'),TurnId(1),GenerationId(1),'out',0,320,20,100000,
                             MediaFormat(Codec.PCM_S16LE,16000),0)
        self.check('m06_audio_chunk_metadata',c.safe_metadata())
        self.assertNotIn('payload',c.safe_metadata())
    def test_bad_chunk_rejected_by_schema(self):
        c=AudioChunkMetadata(SessionId('schema'),TurnId(1),GenerationId(1),'out',0,320,20,100000,
                             MediaFormat(Codec.PCM_S16LE,16000),0)
        data=c.safe_metadata();data['payload']='private bytes'
        with self.assertRaises(self.jsonschema.ValidationError):self.check('m06_audio_chunk_metadata',data)
    def test_asterisk_control_schema(self):
        from automotive_voice.telephony import AsteriskCommandEncoder
        from automotive_voice.audio import FlushRequest
        from uuid import uuid4
        cmd=AsteriskCommandEncoder.flush_json(FlushRequest(str(uuid4()),SessionId('schema'),TurnId(1),GenerationId(2)))
        self.check('m06_transport_control',cmd)
        self.check('m06_transport_control',AsteriskCommandEncoder.hangup_json())
    def test_no_unverified_extra_ack_fields(self):
        ack={'session_id':'schema','turn_id':1,'generation_id':2,'flush_request_id':'00000000-0000-0000-0000-000000000000','adapter_id':'fake','confirmed_by_adapter':True,'adapter_kind':'fake'}
        self.check('m06_flush_ack',ack)
        ack['real_pbx_proven']=True
        with self.assertRaises(self.jsonschema.ValidationError):self.check('m06_flush_ack',ack)
