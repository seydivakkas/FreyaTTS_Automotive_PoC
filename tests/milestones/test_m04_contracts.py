import json
import unittest
from pathlib import Path
from automotive_voice.nlp import TurkishAutomotiveNormalizer, DeterministicNLU, ParseContext, AutomotiveLexicon, LexiconRule

ROOT=Path(__file__).resolve().parents[2]
class M04Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            raise unittest.SkipTest('jsonschema optional not installed')
        cls.Validator=Draft202012Validator
    def load(self,name):
        s=json.loads((ROOT/'contracts'/f'{name}.schema.json').read_text())
        self.Validator.check_schema(s)
        return self.Validator(s)
    def test_normalization_schema(self):
        self.load('normalization_result').validate(TurkishAutomotiveNormalizer().normalize('1.250.000 TL').as_dict())
    def test_nlu_schema(self):
        x=DeterministicNLU().parse('merhaba',ParseContext())
        self.load('nlu_diagnostics').validate(x.safe_diagnostics())
    def test_approved_schema(self):
        r=LexiconRule('Peugeot','pöjo',True,'source','reviewer',({'annotation_id':'ann','clip_id':'clip','source_url':'url'},))
        self.load('approved_lexicon_rule').validate(r.as_dict())
