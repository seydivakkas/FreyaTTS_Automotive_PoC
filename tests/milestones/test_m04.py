import json
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from automotive_voice.nlp import (TurkishAutomotiveNormalizer, AutomotiveLexicon,
    LexiconRule, LexiconError, DeterministicNLU, ParseContext)
from automotive_voice.nlp.normalizer import int_to_tr
from automotive_voice.dialogue.models import Intent, CaseKind

ROOT = Path(__file__).resolve().parents[2]
VOCAB = ROOT / 'data/a01yt/freya_char_vocab.json'
A01 = ROOT / 'data/a01yt/approved_lexicon_v05_snapshot.json'


def rule(canonical='Peugeot', spoken_tr='pöjo', **kwargs):
    return LexiconRule(canonical, spoken_tr, True, 'https://example.com/reference',
        'reviewer_1', ({'annotation_id':'ann1','clip_id':'clip1','source_url':'https://example.com/clip'},), **kwargs)

class M04Numbers(unittest.TestCase):
    def setUp(self):
        self.norm = TurkishAutomotiveNormalizer(vocab_path=VOCAB)

    def test_int_to_tr_zero(self): self.assertEqual(int_to_tr(0),'sıfır')
    def test_int_to_tr_1000(self): self.assertEqual(int_to_tr(1000),'bin')
    def test_int_to_tr_million(self): self.assertEqual(int_to_tr(1250000),'bir milyon iki yüz elli bin')
    def test_int_to_tr_large(self): self.assertIn('trilyon', int_to_tr(1000000000000))
    def test_int_to_tr_out_of_range(self):
        with self.assertRaises(ValueError): int_to_tr(10**15)
    def test_int_to_tr_negative(self):
        with self.assertRaises(ValueError): int_to_tr(-1)
    def test_int_to_tr_float(self):
        with self.assertRaises(ValueError): int_to_tr(2.5)
    def test_money_thousands(self):
        o=self.norm.normalize('Fiyat 1.250.000 TL.')
        self.assertIn('bir milyon iki yüz elli bin Türk lirası',o.spoken_text)
        self.assertFalse(o.review_required)
    def test_money_decimal(self):
        o=self.norm.normalize('Bedel 1.250,50 TL.')
        self.assertIn('bin iki yüz elli Türk lirası ve elli kuruş',o.spoken_text)
    def test_money_one_cent(self):
        o=self.norm.normalize('Bedel 9,05 ₺.')
        self.assertIn('dokuz Türk lirası ve beş kuruş',o.spoken_text)
    def test_iso_date(self):
        self.assertIn('üç kasım iki bin yirmi altı',self.norm.normalize('2026-11-03').spoken_text)
    def test_tr_date(self):
        self.assertIn('üç kasım iki bin yirmi altı',self.norm.normalize('03.11.2026').spoken_text)
    def test_invalid_date(self):
        o=self.norm.normalize('31.02.2026')
        self.assertIn('invalid_date',o.warnings)
        self.assertIn('31.02.2026',o.spoken_text)
    def test_ambiguous_date(self):
        o=self.norm.normalize('03/11/2026')
        self.assertIn('ambiguous_date_separator',o.warnings)
    def test_time(self):
        self.assertIn('on dört otuz',self.norm.normalize('Saat 14:30').spoken_text)
    def test_time_suffix(self):
        self.assertIn('otuzda',self.norm.normalize("Saat 14:30'da").spoken_text)
    def test_time_0900_suffix(self):
        self.assertIn('dokuzda',self.norm.normalize("09:00'da").spoken_text)
    def test_invalid_time(self):
        o=self.norm.normalize('25:90')
        self.assertIn('invalid_time',o.warnings)
    def test_kilometres(self):
        self.assertIn('yüz kırk beş bin kilometre',self.norm.normalize('145.000 km').spoken_text)
    def test_engine(self):
        self.assertIn('bir nokta beş TSI',self.norm.normalize('1.5 TSI').spoken_text)
    def test_model_year(self):
        self.assertIn('iki bin yirmi üç model',self.norm.normalize('2023 model').spoken_text)
    def test_identity_brand_preserved(self):
        o=self.norm.normalize('Qashqai Škoda Peugeot Citroën')
        self.assertEqual(o.spoken_text,'Qashqai Škoda Peugeot Citroën')
        self.assertIn('unsupported_freya_characters',o.warnings)
    def test_strict_brand_reject(self):
        with self.assertRaises(ValueError): self.norm.normalize('Škoda',strict=True)
    def test_no_guessed_form(self):
        self.assertEqual(self.norm.normalize("Qashqai'nin").spoken_text,"Qashqai'nin")
    def test_display_unchanged(self):
        o=self.norm.normalize(' 1.250.000 TL! ')
        self.assertEqual(o.display_text,' 1.250.000 TL! ')
    def test_bidi_fails_closed(self):
        o=self.norm.normalize('Araç \u202e fiyatı')
        self.assertIn('unsafe_control_characters',o.warnings)
    def test_empty_rejected(self):
        with self.assertRaises(ValueError): self.norm.normalize('   ')
    def test_long_rejected(self):
        with self.assertRaises(ValueError): self.norm.normalize('a'*5001)
    def test_unknown_number_flag(self):
        o=self.norm.normalize('Aracın kodu 123456')
        self.assertIn('unexpanded_numeric_token',o.warnings)
        self.assertIn('123456',o.spoken_text)
    def test_no_phone_rewrite(self):
        o=self.norm.normalize('Telefon +90 555 123 45 67')
        self.assertIn('+90 555',o.spoken_text)

class M04Lexicon(unittest.TestCase):
    def test_a01_empty(self):
        lex=AutomotiveLexicon.from_a01yt_export(A01)
        self.assertEqual(len(lex.rules),0)
    def test_unapproved_not_applied(self):
        r=LexiconRule('Qashqai','kaşkay',False,'','')
        o=AutomotiveLexicon((r,)).apply('Qashqai')
        self.assertEqual(o.text,'Qashqai')
        self.assertTrue(o.review_required)
    def test_missing_proof_rejected(self):
        with self.assertRaises(LexiconError): LexiconRule('Peugeot','pöjo',True,'','')
    def test_approved_rewrite(self):
        o=AutomotiveLexicon((rule(),)).apply('Peugeot için Peugeot.')
        self.assertEqual(o.text,'pöjo için pöjo.')
        self.assertEqual(len(o.hits),2)
    def test_suffix_fails_closed(self):
        o=AutomotiveLexicon((rule(),)).apply("Peugeot'nun fiyatı")
        self.assertIn("Peugeot'nun",o.text)
        self.assertTrue(o.review_required)
    def test_approved_suffix(self):
        o=AutomotiveLexicon((rule(suffix_map={"'nun":'nun'}),)).apply("Peugeot'nun fiyatı")
        self.assertIn('pöjonun',o.text)
    def test_do_not_partially_replace(self):
        o=AutomotiveLexicon((rule(),)).apply('Peugeotler Peugeota')
        self.assertEqual(o.text,'Peugeotler Peugeota')
    def test_single_pass(self):
        first=rule('Qashqai','Peugeot')
        second=rule()
        o=AutomotiveLexicon((first,second)).apply('Qashqai')
        self.assertEqual(o.text,'Peugeot')
    def test_conflicting_alias(self):
        with self.assertRaises(LexiconError):
            AutomotiveLexicon((rule(aliases=('araba',)),rule('Qashqai','kaşkay',aliases=('araba',))))
    def test_conflicts_export_rejected(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'lex.json'
            p.write_text(json.dumps({'schema_version':1,'approved_rules':[], 'conflicts':[{'name':'x'}]}))
            with self.assertRaises(LexiconError): AutomotiveLexicon.from_a01yt_export(p)
    def test_unsupported_proposed_reading(self):
        with self.assertRaises(LexiconError): rule(spoken_tr='pöjo!')

class M04NLU(unittest.TestCase):
    def setUp(self):
        self.parser=DeterministicNLU()
        self.ctx=ParseContext(vehicle_aliases={'Qashqai':'VEH1'},location_aliases={'Ankara servis':'LOC1'},
                              as_of=datetime(2026,10,31,22,0,tzinfo=timezone(timedelta(hours=3))))
    def test_greeting(self):
        self.assertEqual(self.parser.parse('Merhaba',self.ctx).dialogue_input.intent,Intent.GREETING)
    def test_handoff(self):
        self.assertEqual(self.parser.parse('Temsilci ile görüşmek istiyorum',self.ctx).dialogue_input.intent,Intent.HANDOFF)
    def test_handoff_priority(self):
        self.assertEqual(self.parser.parse('Fiyat için temsilci istiyorum',self.ctx).dialogue_input.intent,Intent.HANDOFF)
    def test_price_no_guess(self):
        res=self.parser.parse('Peugeot için fiyat',self.ctx)
        self.assertEqual(res.dialogue_input.intent,Intent.PRICE_LOOKUP)
        self.assertIsNone(res.dialogue_input.vehicle_id)
        self.assertTrue(res.requires_clarification)
    def test_resolved_vehicle(self):
        res=self.parser.parse('Qashqai fiyatı',self.ctx)
        self.assertEqual(res.dialogue_input.vehicle_id,'VEH1')
    def test_two_intents(self):
        res=self.parser.parse('Qashqai fiyat ve ekspertiz',self.ctx)
        self.assertEqual(res.dialogue_input.intent,Intent.UNKNOWN)
    def test_confirmation_needs_offer(self):
        self.assertEqual(self.parser.parse('evet',self.ctx).dialogue_input.intent,Intent.UNKNOWN)
    def test_confirmation_with_offer(self):
        ctx=ParseContext(awaiting_confirmation=True)
        self.assertEqual(self.parser.parse('Evet',ctx).dialogue_input.intent,Intent.CONFIRM)
    def test_decline_with_offer(self):
        ctx=ParseContext(awaiting_confirmation=True)
        self.assertEqual(self.parser.parse('Hayır',ctx).dialogue_input.intent,Intent.DECLINE)
    def test_booking_complete(self):
        res=self.parser.parse('Qashqai için Ankara servis ekspertiz 03.11.2026 saat 14:30',self.ctx)
        self.assertEqual(res.dialogue_input.intent,Intent.REQUEST_INSPECTION)
        self.assertEqual(res.dialogue_input.vehicle_id,'VEH1')
        self.assertEqual(res.dialogue_input.slot.start_at,'2026-11-03T14:30:00+03:00')
        self.assertFalse(res.requires_clarification)
    def test_relative_tomorrow(self):
        res=self.parser.parse('Qashqai Ankara servis ekspertiz yarın saat 14:30',self.ctx)
        self.assertEqual(res.dialogue_input.slot.start_at,'2026-11-01T14:30:00+03:00')
    def test_relative_without_clock(self):
        ctx=ParseContext(vehicle_aliases={'Qashqai':'VEH1'},location_aliases={'Ankara servis':'LOC1'})
        res=self.parser.parse('Qashqai Ankara servis ekspertiz yarın saat 14:30',ctx)
        self.assertIsNone(res.dialogue_input.slot)
        self.assertIn('relative_date_without_anchor',res.warnings)
    def test_absolute_without_timezone(self):
        ctx=ParseContext(vehicle_aliases={'Qashqai':'VEH1'},location_aliases={'Ankara servis':'LOC1'})
        res=self.parser.parse('Qashqai Ankara servis ekspertiz 03.11.2026 14:30',ctx)
        self.assertIsNone(res.dialogue_input.slot)
        self.assertIn('timezone_not_resolved',res.warnings)
    def test_absolute_with_explicit_offset(self):
        ctx=ParseContext(vehicle_aliases={'Qashqai':'VEH1'},location_aliases={'Ankara servis':'LOC1'},timezone_offset_minutes=180)
        res=self.parser.parse('Qashqai Ankara servis ekspertiz 03.11.2026 14:30',ctx)
        self.assertIsNotNone(res.dialogue_input.slot)
    def test_missing_location(self):
        res=self.parser.parse('Qashqai ekspertiz 03.11.2026 14:30',self.ctx)
        self.assertIsNone(res.dialogue_input.slot)
    def test_invalid_calendar(self):
        res=self.parser.parse('Qashqai Ankara servis ekspertiz 31.02.2026 14:30',self.ctx)
        self.assertIsNone(res.dialogue_input.slot)
        self.assertIn('invalid_date',res.warnings)
    def test_invalid_time(self):
        res=self.parser.parse('Qashqai Ankara servis ekspertiz 03.11.2026 27:90',self.ctx)
        self.assertIsNone(res.dialogue_input.slot)
    def test_case_callback(self):
        res=self.parser.parse('Qashqai için geri arayın, talep kaydı',self.ctx)
        self.assertEqual(res.dialogue_input.intent,Intent.CREATE_CRM_CASE)
        self.assertEqual(res.dialogue_input.case_kind,CaseKind.CALLBACK)
    def test_diagnostics_no_transcript(self):
        res=self.parser.parse('Qashqai fiyat 05551234567',self.ctx)
        self.assertNotIn('05551234567',str(res.safe_diagnostics()))
    def test_invalid_anchor(self):
        with self.assertRaises(ValueError): ParseContext(as_of=datetime(2026,1,1))
    def test_invalid_utc_offset(self):
        with self.assertRaises(ValueError): ParseContext(timezone_offset_minutes=1000)
    def test_empty_text(self):
        with self.assertRaises(ValueError): self.parser.parse('',self.ctx)

if __name__=='__main__': unittest.main()

class M04BridgeAndAmbiguity(unittest.TestCase):
    def setUp(self):
        from automotive_voice.nlp import DeterministicNLU, ParseContext
        self.parser=DeterministicNLU()
        self.ctx=ParseContext(vehicle_aliases={'Qashqai':'VEH1'},
            location_aliases={'Ankara servis':'LOC1'}, timezone_offset_minutes=180)
    def test_multiple_dates_rejected(self):
        r=self.parser.parse('Qashqai Ankara servis ekspertiz 03.11.2026 veya 04.11.2026 saat 14:30',self.ctx)
        self.assertIsNone(r.dialogue_input.slot)
        self.assertIn('ambiguous_date',r.warnings)
    def test_multiple_times_rejected(self):
        r=self.parser.parse('Qashqai Ankara servis ekspertiz 03.11.2026 saat 14:30 veya 15:00',self.ctx)
        self.assertIsNone(r.dialogue_input.slot)
        self.assertIn('ambiguous_time',r.warnings)
    def test_relative_and_absolute_conflict(self):
        r=self.parser.parse('Qashqai Ankara servis ekspertiz yarın 03.11.2026 saat 14:30',self.ctx)
        self.assertIsNone(r.dialogue_input.slot)
        self.assertIn('ambiguous_date',r.warnings)
    def test_conflicting_offset_rejected(self):
        with self.assertRaises(ValueError):
            ParseContext(as_of=datetime(2026,10,31,tzinfo=timezone.utc),timezone_offset_minutes=180)
    def test_bridge_is_reference_only(self):
        from automotive_voice.nlp import NLUReferenceBridge
        from automotive_voice.dialogue.storage import ReferenceStore
        store=ReferenceStore()
        bridge=NLUReferenceBridge(self.parser,store)
        x=bridge.resolve('sidA','Qashqai fiyat 555-44-33',self.ctx)
        self.assertTrue(x.ref.startswith('transcript:'))
        self.assertEqual(store.get_input('sidA',x.ref).vehicle_id,'VEH1')
        with self.assertRaises(Exception):store.get_transcript('sidA',x.ref)
        with self.assertRaises(Exception):store.get_input('sidB',x.ref)
    def test_bridge_reject_empty_session(self):
        from automotive_voice.nlp import NLUReferenceBridge
        from automotive_voice.dialogue.storage import ReferenceStore
        with self.assertRaises(ValueError):
            NLUReferenceBridge(self.parser,ReferenceStore()).resolve('', 'merhaba',self.ctx)
