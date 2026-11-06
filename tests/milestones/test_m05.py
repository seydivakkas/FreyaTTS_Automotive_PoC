import asyncio
from dataclasses import replace
import hashlib
from pathlib import Path
import unittest
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.nlp.lexicon import AutomotiveLexicon, LexiconRule
from automotive_voice.nlp.normalizer import TurkishAutomotiveNormalizer, NormalizationResult
from automotive_voice.prosody import (ProsodyClausePlanner, PlannerLimits, PlanStatus,
    SpanKind, BreakKind, MockTTS, ClausePlan)

ROOT = Path(__file__).resolve().parents[2]
VOCAB = ROOT/'data/a01yt/freya_char_vocab.json'

class M05PlannerTests(unittest.TestCase):
    def setUp(self):
        self.lex = AutomotiveLexicon()
        self.normalizer = TurkishAutomotiveNormalizer(vocab_path=VOCAB)
        self.planner = ProsodyClausePlanner(limits=PlannerLimits(max_words=12, max_chars=105))
        self.ids = dict(session_id=SessionId('test-m05'), turn_id=TurnId(1), generation_id=GenerationId(1))

    def plan(self, text, planner=None, normalizer=None):
        norm = (normalizer or self.normalizer).normalize(text)
        return (planner or self.planner).plan(norm, **self.ids)

    def test_money_protected(self):
        p = self.plan('Aracınızın tahmini değeri 1.250.000 TL, ekspertiz saati 14:30.')
        self.assertEqual(p.status, PlanStatus.READY)
        self.assertTrue(any(s.kind == SpanKind.MONEY and p.spoken_text[s.start:s.end] == 'bir milyon iki yüz elli bin Türk lirası' for s in p.protected_spans))
        self.assertEqual(len(p.tts_inputs()), len(p.clauses))
        self.assertEqual(len(p.clauses), 2)

    def test_decimal_money_cents_kept(self):
        p=self.plan('Fiyat 1.250,50 TL, pazarlık yok.')
        self.assertTrue(any(p.spoken_text[s.start:s.end].endswith('elli kuruş') for s in p.protected_spans))
        self.assertTrue(p.tts_inputs())

    def test_date_time_protected(self):
        p=self.plan("Ekspertiziniz 03.11.2026 saat 14:30'da yapılacak. Teşekkürler.")
        kinds = {s.kind for s in p.protected_spans}
        self.assertTrue({SpanKind.DATE, SpanKind.TIME}.issubset(kinds))
        self.assertEqual(p.status, PlanStatus.READY)
        self.assertEqual(len(p.clauses), 2)

    def test_engine_protected_acronyms(self):
        p=self.plan('Bugün 1.5 TSI motoru inceleyelim, ardından konuşuruz.')
        self.assertTrue(any(s.kind == SpanKind.ENGINE for s in p.protected_spans))

    def test_unapproved_qashqai_blocks_tts(self):
        p=self.plan("Nissan Qashqai'nin fiyatı 1.250.000 TL.")
        self.assertTrue(p.review_required)
        self.assertEqual(p.tts_inputs(), ())
        self.assertTrue(any(s.kind == SpanKind.MODEL for s in p.protected_spans))
        self.assertNotIn('spoken_text', p.safe_metadata())

    def test_skoda_blocks_unverified_reading(self):
        self.assertTrue(self.plan('Škoda Kamiq için randevu.').review_required)

    def test_digits_unexpanded_review(self):
        p=self.plan('Peugeot 3008 fiyatı nedir?')
        self.assertTrue(p.review_required)
        self.assertFalse(p.tts_inputs())

    def test_approved_example_without_real_claim(self):
        evidence=({'annotation_id':'test1','clip_id':'dummy1','source_url':'https://example.invalid'},)
        rule=LexiconRule('TESTMARKA', 'deneme marka', True, 'https://example.invalid','mock reviewer',evidence)
        lex=AutomotiveLexicon((rule,))
        normalizer=TurkishAutomotiveNormalizer(lexicon=lex, vocab_path=VOCAB)
        p=self.plan('TESTMARKA için görüşelim.',planner=ProsodyClausePlanner(lexicon=lex),normalizer=normalizer)
        self.assertEqual(p.status,PlanStatus.READY)
        self.assertTrue(any(s.kind==SpanKind.APPROVED_LEXICON for s in p.protected_spans))

    def test_parentheses_protected(self):
        p=self.plan('Bugün (gerekirse, sadece danışma), yarın karar verelim.')
        self.assertTrue(any('(gerekirse, sadece danışma)' in c.text for c in p.clauses))

    def test_question_hint(self):
        p=self.plan('Randevuyu onaylıyor musunuz?')
        self.assertEqual(p.clauses[-1].delivery_hint,'question')
        self.assertEqual(p.clauses[-1].pause_after_ms,0)

    def test_determinism(self):
        a=self.plan('Merhaba, araç değerini değerlendirelim. Randevu ister misiniz?')
        b=self.plan('Merhaba, araç değerini değerlendirelim. Randevu ister misiniz?')
        self.assertEqual(a,b)

    def test_no_lost_text(self):
        p=self.plan('Selam.   Güzel; sıra geldi, teklif için konuşalım!')
        self.assertEqual(''.join(p.spoken_text.split()), ''.join(''.join(c.text.split()) for c in p.clauses))

    def test_long_money_not_split_even_with_tight_limit(self):
        p=self.plan('Fiyat 1.250.000 TL.',planner=ProsodyClausePlanner(limits=PlannerLimits(max_words=3,max_chars=12)))
        self.assertTrue(p.review_required)
        self.assertIn('overlong_atomic_span',p.warning_codes)
        self.assertEqual(p.tts_inputs(),())
        self.assertTrue(any('bir milyon iki yüz elli bin Türk lirası' in c.text for c in p.clauses))

    def test_unsupported_control_blocks(self):
        self.assertTrue(self.plan('Merhaba\u202e kötü metin.').review_required)

    def test_markup_not_synthesized(self):
        self.assertTrue(self.plan('<speak>Hoş geldiniz.</speak>').review_required)

    def test_manual_ready_with_warnings_rejected(self):
        p=self.plan('Merhaba.')
        with self.assertRaises(ValueError):
            replace(p,warning_codes=('unsafe',))

    def test_invalid_ids_rejected(self):
        with self.assertRaises(TypeError):
            self.planner.plan(self.normalizer.normalize('Merhaba.'),session_id='test-m05',turn_id=TurnId(1),generation_id=GenerationId(1))

    def test_tts_integrity_hash(self):
        p=self.plan('Merhaba.')
        item=p.tts_inputs()[0]
        self.assertEqual(item.text_sha256,hashlib.sha256(item.text.encode()).hexdigest())
        self.assertNotIn('text',item.safe_metadata())
        with self.assertRaises(ValueError):
            replace(item,text='başka metin')

    def test_empty_limits_rejected(self):
        with self.assertRaises(ValueError): PlannerLimits(0,10,20)

    def test_clause_limit_guard(self):
        with self.assertRaises(ValueError):
            self.plan('A. B. C.',planner=ProsodyClausePlanner(limits=PlannerLimits(max_clauses=2)))

    def test_m04_review_cannot_bypass(self):
        n=self.normalizer.normalize('Merhaba.')
        n=replace(n, review_required=True, warnings=('manual_review',))
        p=self.planner.plan(n,**self.ids)
        self.assertTrue(p.review_required)
        self.assertFalse(p.tts_inputs())

class M05MockTTSTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager=SessionManager(EventBus())
        self.sid='m05-mock'
        await self.manager.create(self.sid)
        await self.manager.start(self.sid)
        await self.manager.begin_turn(self.sid)
        await self.manager.begin_response(self.sid)
        self.snap=await self.manager.snapshot(self.sid)
        self.tts=MockTTS(self.manager,max_pending=8)
        self.planner=ProsodyClausePlanner()
        self.norm=TurkishAutomotiveNormalizer(vocab_path=VOCAB)

    def plan(self,text='Merhaba. Nasıl yardımcı olabilirim?'):
        return self.planner.plan(self.norm.normalize(text),session_id=self.snap.session_id,turn_id=self.snap.turn_id,generation_id=self.snap.generation_id)

    async def test_enqueue_pop_mock(self):
        p=self.plan()
        r=await self.tts.enqueue(p)
        self.assertTrue(r.accepted)
        self.assertEqual(r.count,2)
        self.assertEqual((await self.tts.pop_next()).clause_index,0)
        self.assertEqual((await self.tts.pop_next()).clause_index,1)
        self.assertIsNone(await self.tts.pop_next())

    async def test_barge_in_invalidates_pending_text(self):
        p=self.plan()
        self.assertTrue((await self.tts.enqueue(p)).accepted)
        await self.manager.interrupt(self.sid)
        self.assertIsNone(await self.tts.pop_next())
        self.assertEqual(self.tts.pending_count,0)

    async def test_reject_review(self):
        p=self.plan("Qashqai'nin fiyatı.")
        r=await self.tts.enqueue(p)
        self.assertEqual(r.reason,'review_required')
        self.assertFalse(r.accepted)

    async def test_wrong_generation_rejected(self):
        p=self.plan()
        p=replace(p,generation_id=GenerationId(int(p.generation_id)+1))
        self.assertEqual((await self.tts.enqueue(p)).reason,'stale_generation_or_wrong_state')

    async def test_terminal_invalidates(self):
        p=self.plan()
        await self.tts.enqueue(p)
        await self.manager.end(self.sid)
        self.assertEqual(await self.tts.discard_stale(),2)

    async def test_wrong_state_rejected(self):
        await self.manager.finish_playout(self.sid)
        self.assertFalse((await self.tts.enqueue(self.plan())).accepted)

    async def test_backpressure_atomic(self):
        short=MockTTS(self.manager,max_pending=1)
        r=await short.enqueue(self.plan())
        self.assertEqual((r.reason,short.pending_count),('backpressure',0))

    async def test_new_generation_old_plan_rejected(self):
        old=self.plan()
        await self.manager.finish_playout(self.sid)
        await self.manager.begin_turn(self.sid)
        await self.manager.begin_response(self.sid)
        self.assertFalse((await self.tts.enqueue(old)).accepted)

    async def test_discard_preserves_fresh(self):
        old=self.plan()
        await self.tts.enqueue(old)
        await self.manager.interrupt(self.sid)
        self.assertEqual(await self.tts.discard_stale(),2)

    async def test_queue_receipt_no_text(self):
        r=await self.tts.enqueue(self.plan())
        self.assertNotIn('Merhaba',str(r))

if __name__=='__main__': unittest.main()

from uuid import uuid4
from automotive_voice.dialogue.storage import ReferenceStore
from automotive_voice.conversation.effects import Effect, EffectKind
from automotive_voice.prosody import ProsodyCoordinator

class M05CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sid='coord-m05'
        self.manager=SessionManager(EventBus())
        await self.manager.create(self.sid)
        await self.manager.start(self.sid)
        await self.manager.begin_turn(self.sid)
        await self.manager.begin_response(self.sid)
        self.snap=await self.manager.snapshot(self.sid)
        self.store=ReferenceStore()
        self.queue=MockTTS(self.manager)
        self.coordinator=ProsodyCoordinator(self.store,
            TurkishAutomotiveNormalizer(vocab_path=VOCAB), ProsodyClausePlanner(), self.queue)

    def effect(self,ref,kind=EffectKind.START_TTS,sid=None):
        return Effect(str(uuid4()),kind,SessionId(sid or self.sid),
                      self.snap.turn_id,self.snap.generation_id,str(uuid4()),ref)

    async def test_cross_session_reference_not_accessible(self):
        ref=self.store.put_response('another', 'Merhaba.', 'greeting')
        result=await self.coordinator.process(self.effect(ref))
        self.assertEqual(result.reason, 'missing_response_reference')
        self.assertEqual(self.queue.pending_count,0)

    async def test_response_ready_as_ref(self):
        ref=self.store.put_response(self.sid,'Randevunuz onaylandı.','confirmed')
        result=await self.coordinator.process(self.effect(ref))
        self.assertEqual(result.status,'queued')
        self.assertEqual(result.queued_clauses,1)
        self.assertEqual((await self.queue.pop_next()).text, 'Randevunuz onaylandı.')

    async def test_unsupported_freya_text_blocked(self):
        ref=self.store.put_response(self.sid, 'Škoda için randevu alabiliriz.', 'unverified')
        result=await self.coordinator.process(self.effect(ref))
        self.assertEqual(result.status,'review_required')
        self.assertEqual(self.queue.pending_count,0)

    async def test_stale_response_rejected_without_store_lookup(self):
        ref=self.store.put_response(self.sid,'Merhaba.', 'greeting')
        await self.manager.interrupt(self.sid)
        result=await self.coordinator.process(self.effect(ref))
        self.assertEqual(result.reason,'stale_generation_or_wrong_state')

    async def test_wrong_effect_rejected(self):
        ref=self.store.put_response(self.sid,'Merhaba.', 'greeting')
        with self.assertRaises(ValueError):
            await self.coordinator.process(self.effect(ref,EffectKind.REQUEST_LLM))

class M05IdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager=SessionManager(EventBus())
        self.sid='idem-m05'
        await self.manager.create(self.sid)
        await self.manager.start(self.sid)
        await self.manager.begin_turn(self.sid)
        await self.manager.begin_response(self.sid)
        s=await self.manager.snapshot(self.sid)
        n=TurkishAutomotiveNormalizer(vocab_path=VOCAB)
        self.plan=ProsodyClausePlanner().plan(n.normalize('Merhaba. Nasılsınız?'),session_id=s.session_id,turn_id=s.turn_id,generation_id=s.generation_id)
        self.queue=MockTTS(self.manager)

    async def test_replayed_plan_only_queued_once(self):
        self.assertEqual((await self.queue.enqueue(self.plan)).count,2)
        result=await self.queue.enqueue(self.plan)
        self.assertEqual((result.reason,result.count,self.queue.pending_count),('duplicate_ignored',0,2))

    async def test_conflicting_plan_same_identity_rejected(self):
        self.assertTrue((await self.queue.enqueue(self.plan)).accepted)
        n=TurkishAutomotiveNormalizer(vocab_path=VOCAB)
        other=ProsodyClausePlanner().plan(n.normalize('Selam. Nasılsınız?'),
             session_id=self.plan.session_id,turn_id=self.plan.turn_id,generation_id=self.plan.generation_id)
        self.assertEqual((await self.queue.enqueue(other)).reason,'conflicting_replay')

    async def test_replay_after_pop_still_ignored(self):
        await self.queue.enqueue(self.plan)
        await self.queue.pop_next()
        await self.queue.pop_next()
        self.assertEqual((await self.queue.enqueue(self.plan)).reason,'duplicate_ignored')

class M05TypedSourceTests(unittest.TestCase):
    def setUp(self):
        self.n=TurkishAutomotiveNormalizer(vocab_path=VOCAB)
        self.p=ProsodyClausePlanner(limits=PlannerLimits(max_words=6, max_chars=80))
        self.ids=dict(session_id=SessionId('typed'),turn_id=TurnId(1),generation_id=GenerationId(1))
    def check(self, original, kind):
        result=self.p.plan(self.n.normalize(original),**self.ids)
        self.assertTrue(any(s.kind==kind for s in result.protected_spans))
        return result
    def test_bare_clock(self):
        p=self.check('Randevu 14:30. Sonraki adım bekleniyor.',SpanKind.TIME)
        self.assertTrue(p.tts_inputs())
    def test_distance(self):
        self.check('Aracınız 145.000 km, kayıtlıdır.',SpanKind.DISTANCE)
    def test_model_year(self):
        self.check('2024 model aracınız için görüşelim.',SpanKind.MODEL_YEAR)
