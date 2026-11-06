import dataclasses
import json
from pathlib import Path
import unittest
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.nlp.normalizer import TurkishAutomotiveNormalizer
from automotive_voice.prosody import ProsodyClausePlanner
ROOT=Path(__file__).resolve().parents[2]

class M05SchemaTests(unittest.TestCase):
    def test_new_draft_2020_schemas(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest('Optional validation extra not installed')
        for name in ('phrase_boundary','tts_input','clause_plan_diagnostics'):
            schema=json.loads((ROOT/'contracts'/f'{name}.schema.json').read_text(encoding='utf-8'))
            jsonschema.Draft202012Validator.check_schema(schema)
        n=TurkishAutomotiveNormalizer(vocab_path=ROOT/'data/a01yt/freya_char_vocab.json')
        p=ProsodyClausePlanner().plan(n.normalize('Fiyat 1.250.000 TL, tamam mı?'),
            session_id=SessionId('schema'),turn_id=TurnId(1),generation_id=GenerationId(1))
        self.assertFalse(p.review_required)
        from enum import Enum
        def serialize(v):
            return {k:(w.value if isinstance(w,Enum) else w) for k,w in dataclasses.asdict(v).items()}
        jsonschema.validate(p.safe_metadata(), json.loads((ROOT/'contracts/clause_plan_diagnostics.schema.json').read_text(encoding='utf-8')))
        for span in p.protected_spans:
            jsonschema.validate(serialize(span), json.loads((ROOT/'contracts/phrase_boundary.schema.json').read_text(encoding='utf-8')))
        for inp in p.tts_inputs():
            data=serialize(inp)
            jsonschema.validate(data,json.loads((ROOT/'contracts/tts_input.schema.json').read_text(encoding='utf-8')))
            self.assertNotIn('text',inp.safe_metadata())
    def test_exact_legacy_320_hash(self):
        import hashlib
        p=ROOT/'data/fixtures/legacy_320_cases.json'
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),
                         '7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e')
