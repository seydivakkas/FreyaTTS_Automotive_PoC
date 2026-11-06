import json
import unittest
from pathlib import Path
from dataclasses import asdict
from datetime import datetime,timezone
from automotive_voice.dialogue import (BookingReceipt, Commitment, PolicyDecision, BookingStatus,
                                         AccessContext, DialogueInput, Intent, AppointmentSlot)
ROOT=Path(__file__).resolve().parents[2]

class M03Contracts(unittest.TestCase):
    def test_json_contracts_load(self):
        for name in ('dialogue_input','policy_decision','booking_receipt','access_context'):
            d=json.loads((ROOT/'contracts'/f'{name}.schema.json').read_text(encoding='utf-8'))
            self.assertEqual(d['$schema'],'https://json-schema.org/draft/2020-12/schema')

    def test_schema_validator_examples(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema optional validation dependency not installed')
        for name in ('dialogue_input','policy_decision','booking_receipt','access_context'):
            schema=json.loads((ROOT/'contracts'/f'{name}.schema.json').read_text(encoding='utf-8'))
            Draft202012Validator.check_schema(schema)
        receipt=json.loads((ROOT/'contracts'/'booking_receipt.schema.json').read_text(encoding='utf-8'))
        Draft202012Validator(receipt).validate({'status':'confirmed','reference_id':'EX-1'})
        with self.assertRaises(Exception):
            Draft202012Validator(receipt).validate({'status':'confirmed','reference_id':None})
        with self.assertRaises(Exception):
            Draft202012Validator(receipt).validate({'status':'unknown','reference_id':'EX-1'})

    def test_input_schema_sample(self):
        from jsonschema import Draft202012Validator
        schema=json.loads((ROOT/'contracts'/'dialogue_input.schema.json').read_text(encoding='utf-8'))
        payload={'intent':'request_inspection','vehicle_id':'car-1','slot':{'start_at':'2026-11-03T14:30:00+03:00','location_id':'TRABZON'}}
        Draft202012Validator(schema).validate(payload)
        with self.assertRaises(Exception):
            Draft202012Validator(schema).validate({'intent':'make_up_price','vehicle_id':'car-1'})
