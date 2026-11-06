"""M03 acceptance: no real speech, phone, model or network I/O."""
import asyncio
import unittest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from automotive_voice.dialogue import (
    Intent, AccessContext, AppointmentSlot, DialogueInput, Availability,
    BookingStatus, Commitment, VehicleRecord, PriceQuote, BookingReceipt,
    FakeCRM, FakeBookingService, ReferenceStore, MissingReferenceError,
    DialoguePolicy, DialogueCoordinator)
from automotive_voice.conversation import (ConversationReducer, ConversationSignal,
                                         SignalKind, Decision, EffectKind)
from automotive_voice.core.session import State

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
SLOT = AppointmentSlot('2026-11-03T14:30:00+03:00','TRABZON')
BAD_SLOT = AppointmentSlot('2026-10-01T14:30:00+03:00','TRABZON')
FULL_ACCESS = AccessContext(authenticated=True, crm_processing_allowed=True)

class M03Policy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = ReferenceStore()
        self.crm = FakeCRM({'veh-1': VehicleRecord('veh-1','Nissan','Qashqai',2024)},
                           {'veh-1': PriceQuote('veh-1',1250000,'CRM-VALUE-1',NOW+timedelta(days=1))})
        self.booking = FakeBookingService({FakeBookingService.key('veh-1',SLOT): Availability.AVAILABLE})
        self.policy = DialoguePolicy(self.crm,self.booking,self.store,now=lambda: NOW)
        self.sid = 'session-1'

    async def go(self, intent, *, vehicle='veh-1', slot=None, access=FULL_ACCESS, sid=None):
        return await self.policy.handle(sid or self.sid,DialogueInput(intent,vehicle,slot),access)

    def text(self, decision, sid=None):
        return self.store.get_response(sid or self.sid,decision.response_ref).text

    async def offered(self):
        a = await self.go(Intent.REQUEST_INSPECTION,slot=SLOT)
        self.assertEqual(a.booking_status,BookingStatus.AWAITING_CONFIRMATION)
        return a

    async def test_hello_without_authentication(self):
        r = await self.go(Intent.GREETING,access=AccessContext())
        self.assertIn('Merhaba',self.text(r))

    async def test_identity_gate_prevents_crm_and_booking(self):
        r = await self.go(Intent.VEHICLE_LOOKUP,access=AccessContext())
        self.assertEqual(r.action,'identity_required')
        r2 = await self.go(Intent.REQUEST_INSPECTION,slot=SLOT,access=AccessContext())
        self.assertEqual(r2.action,'identity_required')
        self.assertEqual(self.crm.vehicle_reads,0)
        self.assertEqual(self.booking.creations,0)

    async def test_consent_gate_prevents_crm_and_booking(self):
        no = AccessContext(authenticated=True,crm_processing_allowed=False)
        r = await self.go(Intent.PRICE_LOOKUP,access=no)
        self.assertEqual(r.action,'data_permission_required')
        self.assertEqual(self.crm.price_reads,0)
        await self.go(Intent.REQUEST_INSPECTION,slot=SLOT,access=no)
        self.assertEqual(self.booking.creations,0)

    async def test_marketing_optin_does_not_grant_crm_access(self):
        r = await self.go(Intent.PRICE_LOOKUP,access=AccessContext(authenticated=True,marketing_opt_in=True))
        self.assertEqual(r.action,'data_permission_required')

    async def test_verified_vehicle(self):
        r = await self.go(Intent.VEHICLE_LOOKUP)
        self.assertEqual(r.action,'vehicle_verified')
        self.assertIn('Qashqai',self.text(r))

    async def test_missing_vehicle_or_unverified(self):
        r=await self.go(Intent.VEHICLE_LOOKUP,vehicle=None)
        self.assertEqual(r.action,'need_vehicle')
        r=await self.go(Intent.VEHICLE_LOOKUP,vehicle='missing')
        self.assertEqual(r.action,'vehicle_unverified')
        self.assertNotIn('2024',self.text(r))

    async def test_verified_price_not_a_sale_commitment(self):
        r = await self.go(Intent.PRICE_LOOKUP)
        self.assertEqual(r.action,'price_verified')
        self.assertIn('1.250.000',self.text(r))
        self.assertIn('kesin satış teklifi değildir',self.text(r))

    async def test_missing_or_expired_or_mismatched_quote_no_price(self):
        for quote in (None, PriceQuote('veh-1',9,'x',NOW),
                      PriceQuote('veh-2',9000000,'x',NOW+timedelta(days=1)),
                      PriceQuote('veh-1',9000000,'x',NOW+timedelta(days=1),verified=False)):
            self.crm.quotes = {} if quote is None else {'veh-1':quote}
            r = await self.go(Intent.PRICE_LOOKUP)
            self.assertEqual(r.action,'price_unavailable')
            self.assertNotIn('9.000.000',self.text(r))

    async def test_future_slot_and_timezone_required(self):
        with self.assertRaises(ValueError):
            AppointmentSlot('2026-11-03T14:00:00','TRABZON')
        with self.assertRaises(ValueError):
            AppointmentSlot('not-date','TRABZON')
        r=await self.go(Intent.REQUEST_INSPECTION,slot=BAD_SLOT)
        self.assertEqual(r.action,'slot_past')
        self.assertEqual(self.booking.creations,0)

    async def test_offer_is_not_confirmation(self):
        r=await self.offered()
        self.assertIn('Henüz oluşturulmadı',self.text(r))
        self.assertEqual(self.booking.creations,0)

    async def test_confirmation_after_explicit_yes_and_receipt(self):
        await self.offered()
        r=await self.go(Intent.CONFIRM)
        self.assertEqual(r.booking_status,BookingStatus.CONFIRMED)
        self.assertIn('Onay referansı:',self.text(r))
        self.assertEqual(self.booking.creations,1)

    async def test_duplicate_confirm_no_duplicate_booking(self):
        await self.offered()
        a=await self.go(Intent.CONFIRM)
        b=await self.go(Intent.CONFIRM)
        self.assertEqual(a.booking_status,BookingStatus.CONFIRMED)
        self.assertEqual(b.action,'already_confirmed')
        self.assertEqual(self.booking.creations,1)

    async def test_idempotency_of_fake_server(self):
        await self.offered()
        key=self.policy._session(self.sid).idempotency_key
        a=await self.booking.commit('veh-1',SLOT,key)
        b=await self.booking.commit('veh-1',SLOT,key)
        self.assertEqual(a,b)
        self.assertEqual(self.booking.creations,1)

    async def test_confirm_without_offer_never_books(self):
        r=await self.go(Intent.CONFIRM)
        self.assertEqual(r.action,'no_offer')
        self.assertEqual(self.booking.creations,0)

    async def test_decline_ends_pending_offer(self):
        await self.offered()
        r=await self.go(Intent.DECLINE)
        self.assertEqual(r.booking_status,BookingStatus.DECLINED)
        r=await self.go(Intent.CONFIRM)
        self.assertEqual(r.action,'no_offer')
        self.assertEqual(self.booking.creations,0)

    async def test_availability_unavailable_unknown_never_books(self):
        for availability,status in [(Availability.UNAVAILABLE,BookingStatus.UNAVAILABLE),
                                    (Availability.UNKNOWN,BookingStatus.UNKNOWN)]:
            self.booking.availability[FakeBookingService.key('veh-1',SLOT)]=availability
            r=await self.go(Intent.REQUEST_INSPECTION,slot=SLOT)
            self.assertEqual(r.booking_status,status)
            r2=await self.go(Intent.CONFIRM)
            self.assertEqual(r2.action,'no_offer')
        self.assertEqual(self.booking.creations,0)

    async def test_availability_changed_at_commit(self):
        await self.offered()
        self.booking.availability[FakeBookingService.key('veh-1',SLOT)]=Availability.UNAVAILABLE
        r=await self.go(Intent.CONFIRM)
        self.assertEqual(r.booking_status,BookingStatus.UNAVAILABLE)
        self.assertNotIn('Onay referansı',self.text(r))
        self.assertEqual(self.booking.creations,0)

    async def test_unknown_availability_at_commit(self):
        await self.offered()
        self.booking.availability[FakeBookingService.key('veh-1',SLOT)]=Availability.UNKNOWN
        r=await self.go(Intent.CONFIRM)
        self.assertEqual(r.booking_status,BookingStatus.UNKNOWN)
        self.assertEqual(self.booking.creations,0)

    async def test_commit_exception_no_success(self):
        class BrokenBooking(FakeBookingService):
            async def commit(self,*args):
                raise ConnectionError('fake')
        await self.offered()
        broken=BrokenBooking({FakeBookingService.key('veh-1',SLOT): Availability.AVAILABLE})
        self.policy.booking=broken
        r=await self.go(Intent.CONFIRM)
        self.assertEqual(r.action,'booking_service_error')
        self.assertEqual(r.booking_status,BookingStatus.UNKNOWN)

    async def test_stale_precommit_does_not_create_booking(self):
        await self.offered()
        r=await self.policy.handle(self.sid,DialogueInput(Intent.CONFIRM),FULL_ACCESS,
                                   is_current=lambda: asyncio.sleep(0,result=False))
        self.assertEqual(r.action,'stale_generation')
        self.assertEqual(self.booking.creations,0)

    async def test_unverified_vehicle_no_offer(self):
        r=await self.go(Intent.REQUEST_INSPECTION,vehicle='wrong',slot=SLOT)
        self.assertEqual(r.action,'vehicle_unverified')
        self.assertEqual(self.booking.creations,0)

    async def test_unknown_twice_handoff(self):
        a=await self.go(Intent.UNKNOWN)
        b=await self.go(Intent.UNKNOWN)
        self.assertEqual(a.action,'clarify')
        self.assertTrue(b.handoff_requested)
        self.assertIsNone(b.response_ref)
        self.assertEqual(b.booking_status,BookingStatus.HANDOFF)

    async def test_direct_handoff(self):
        a=await self.go(Intent.HANDOFF,access=AccessContext())
        self.assertTrue(a.handoff_requested)
        self.assertIsNone(a.response_ref)

    async def test_per_session_isolation(self):
        await self.offered()
        r=await self.go(Intent.CONFIRM,sid='other')
        self.assertEqual(r.action,'no_offer')
        self.assertEqual(self.booking.creations,0)

    async def test_store_does_not_cross_sessions(self):
        inp_ref=self.store.put_input('one',DialogueInput(Intent.GREETING))
        with self.assertRaises(MissingReferenceError):
            self.store.get_input('two',inp_ref)
        reply=self.store.put_response('one','Gizli metin','test')
        with self.assertRaises(MissingReferenceError):
            self.store.get_response('two',reply)
        self.store.erase_session('one')
        with self.assertRaises(MissingReferenceError):
            self.store.get_response('one',reply)

    async def test_invalid_price_object_rejected(self):
        with self.assertRaises(ValueError):
            PriceQuote('veh-1',-1,'crm',NOW+timedelta(days=1))
        with self.assertRaises(ValueError):
            BookingReceipt(Commitment.CONFIRMED)
        with self.assertRaises(ValueError):
            BookingReceipt(Commitment.UNKNOWN,'fake-confirmation')

    async def test_booking_result_recheck_after_expiry(self):
        await self.offered()
        self.policy.now=lambda: NOW+timedelta(days=8)
        r=await self.go(Intent.CONFIRM)
        self.assertEqual(r.action,'slot_expired')
        self.assertEqual(self.booking.creations,0)

    async def test_confirmation_key_reused_on_retry_with_same_mock_port(self):
        await self.offered()
        key=self.policy._session(self.sid).idempotency_key
        r=await self.booking.commit('veh-1',SLOT,key)
        self.assertEqual(r.status,Commitment.CONFIRMED)
        a=await self.go(Intent.CONFIRM)
        self.assertEqual(a.action,'booking_confirmed')
        self.assertEqual(self.booking.creations,1)

    async def test_lookup_prices_for_another_session_no_leak(self):
        x=await self.go(Intent.VEHICLE_LOOKUP,sid='one')
        with self.assertRaises(MissingReferenceError):
            self.store.get_response('two',x.response_ref)


class M03Coordinator(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reducer=ConversationReducer()
        self.store=ReferenceStore()
        self.crm=FakeCRM({'v1':VehicleRecord('v1','Skoda','Octavia',2020)}, {})
        self.booking=FakeBookingService()
        self.policy=DialoguePolicy(self.crm,self.booking,self.store,now=lambda:NOW)
        self.coord=DialogueCoordinator(self.reducer,self.policy,self.store)
        self.sid='m03-session'
        await self.send(SignalKind.SESSION_OPENED)

    async def send(self,kind,ref=None):
        snap=await self.reducer.try_snapshot(self.sid)
        signal=ConversationSignal.create(kind,self.sid,int(snap.turn_id) if snap else 0,
            int(snap.generation_id) if snap else 0,await self.reducer.expected_sequence(self.sid),reference=ref)
        return await self.reducer.handle(signal)

    async def request(self, inp):
        ref=self.store.put_input(self.sid,inp)
        a=await self.send(SignalKind.TRANSCRIPT_FINAL,ref)
        self.assertEqual(a.state,State.THINKING)
        self.assertEqual(a.effects[0].kind,EffectKind.REQUEST_LLM)
        return a.effects[0]

    async def test_m02_integration_safe_ref_only(self):
        effect=await self.request(DialogueInput(Intent.GREETING))
        result=await self.coord.process(effect,FULL_ACCESS)
        self.assertEqual(result.status,'applied')
        self.assertEqual((await self.reducer.try_snapshot(self.sid)).state,State.SPEAKING)
        self.assertIn('Merhaba',self.store.get_response(self.sid,result.response_ref).text)
        audit=await self.reducer.audit_records(self.sid)
        self.assertNotIn('Merhaba',str(audit))

    async def test_handoff_runs_m02_transition(self):
        effect=await self.request(DialogueInput(Intent.HANDOFF))
        result=await self.coord.process(effect,FULL_ACCESS)
        self.assertEqual(result.action,'handoff')
        self.assertEqual((await self.reducer.try_snapshot(self.sid)).state,State.HANDOFF)

    async def test_missing_input_ref_does_not_make_response(self):
        a=await self.send(SignalKind.TRANSCRIPT_FINAL,'transcript:missing')
        outcome=await self.coord.process(a.effects[0],FULL_ACCESS)
        self.assertEqual(outcome.status,'missing_reference')
        self.assertEqual((await self.reducer.try_snapshot(self.sid)).state,State.THINKING)

    async def test_old_generation_response_blocked(self):
        a=await self.request(DialogueInput(Intent.GREETING))
        await self.send(SignalKind.VAD_SPEECH_STARTED)
        result=await self.coord.process(a,FULL_ACCESS)
        self.assertEqual(result.status,'stale')
        self.assertEqual((await self.reducer.try_snapshot(self.sid)).state,State.LISTENING)

    async def test_hangup_blocks_response(self):
        a=await self.request(DialogueInput(Intent.GREETING))
        await self.send(SignalKind.HANGUP)
        result=await self.coord.process(a,FULL_ACCESS)
        self.assertEqual(result.status,'stale')
        self.assertEqual((await self.reducer.try_snapshot(self.sid)).state,State.ENDED)

    async def test_input_ref_not_in_external_event_audit(self):
        ref=self.store.put_input(self.sid,DialogueInput(Intent.UNKNOWN))
        a=await self.send(SignalKind.TRANSCRIPT_FINAL,ref)
        result=await self.coord.process(a.effects[0],FULL_ACCESS)
        self.assertEqual(result.status,'applied')
        self.assertNotIn('İsteğinizi',str(await self.reducer.audit_records(self.sid)))

    async def test_no_unauthorized_booking_from_thinking(self):
        a=await self.request(DialogueInput(Intent.REQUEST_INSPECTION,'v1',SLOT))
        result=await self.coord.process(a,AccessContext())
        self.assertEqual(result.action,'identity_required')
        self.assertEqual(self.booking.creations,0)

    async def test_wrong_effect_rejected(self):
        from automotive_voice.conversation.effects import Effect
        signal=ConversationSignal.create(SignalKind.SESSION_OPENED,'s',0,0,0)
        fake=Effect.from_signal(signal,EffectKind.FLUSH_MEDIA,0,0)
        with self.assertRaises(ValueError):
            await self.coord.process(fake,FULL_ACCESS)

    async def test_duplicate_request_effect_becomes_stale(self):
        a=await self.request(DialogueInput(Intent.GREETING))
        first=await self.coord.process(a,FULL_ACCESS)
        second=await self.coord.process(a,FULL_ACCESS)
        self.assertEqual(first.status,'applied')
        self.assertEqual(second.status,'stale')

    async def test_reference_does_not_include_transcript_text(self):
        ref=self.store.put_input(self.sid,DialogueInput(Intent.PRICE_LOOKUP,vehicle_id='v1'))
        self.assertTrue(ref.startswith('transcript:'))
        self.assertNotIn('PRICE_LOOKUP',ref)
        self.assertLessEqual(len(ref),128)


if __name__=='__main__':
    unittest.main()

class M03Additional(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store=ReferenceStore(capacity=3)
        self.booking=FakeBookingService({FakeBookingService.key('v',SLOT): Availability.AVAILABLE})
        self.policy=DialoguePolicy(FakeCRM({'v':VehicleRecord('v','Peugeot','3008',2025)}),
                                   self.booking,self.store,now=lambda:NOW)
        self.sid='sid'

    async def test_raw_transcript_only_in_session_secure_store(self):
        text='Qashqai aracımı ekspertize götürmek istiyorum'
        ref=self.store.put_transcript(self.sid,text,DialogueInput(Intent.REQUEST_INSPECTION,'v',SLOT))
        self.assertNotIn('Qashqai',ref)
        self.assertEqual(self.store.get_transcript(self.sid,ref),text)
        self.assertEqual(self.store.get_input(self.sid,ref).intent,Intent.REQUEST_INSPECTION)
        with self.assertRaises(MissingReferenceError):
            self.store.get_transcript('other',ref)

    async def test_transcript_bound_size(self):
        with self.assertRaises(ValueError):
            self.store.put_transcript(self.sid,'',DialogueInput(Intent.GREETING))
        with self.assertRaises(ValueError):
            self.store.put_transcript(self.sid,'t'*4097,DialogueInput(Intent.GREETING))

    async def test_capacity_eviction(self):
        refs=[self.store.put_input(self.sid,DialogueInput(Intent.GREETING)) for _ in range(4)]
        with self.assertRaises(MissingReferenceError):
            self.store.get_input(self.sid,refs[0])
        self.assertIsNotNone(self.store.get_input(self.sid,refs[-1]))

    async def test_idempotency_key_reuse_for_other_slot_fails(self):
        key='abc'
        await self.booking.commit('v',SLOT,key)
        with self.assertRaises(ValueError):
            await self.booking.commit('v',AppointmentSlot('2026-11-04T10:00:00+03:00','TRABZON'),key)

    async def test_uncertain_commit_blocks_new_offer(self):
        s=await self.policy.handle(self.sid,DialogueInput(Intent.REQUEST_INSPECTION,'v',SLOT),FULL_ACCESS)
        self.assertEqual(s.booking_status,BookingStatus.AWAITING_CONFIRMATION)
        self.booking.availability[FakeBookingService.key('v',SLOT)]=Availability.UNKNOWN
        await self.policy.handle(self.sid,DialogueInput(Intent.CONFIRM),FULL_ACCESS)
        response=await self.policy.handle(self.sid,DialogueInput(Intent.REQUEST_INSPECTION,'v',SLOT),FULL_ACCESS)
        self.assertEqual(response.action,'reconcile_first')
        self.assertEqual(self.booking.creations,0)

    async def test_recheck_finds_confirmed_receipt_after_uncertainty(self):
        await self.policy.handle(self.sid,DialogueInput(Intent.REQUEST_INSPECTION,'v',SLOT),FULL_ACCESS)
        key=self.policy._session(self.sid).idempotency_key
        receipt=await self.booking.commit('v',SLOT,key)
        self.assertEqual(receipt.status,Commitment.CONFIRMED)
        self.policy._session(self.sid).booking_status=BookingStatus.UNKNOWN
        result=await self.policy.handle(self.sid,DialogueInput(Intent.RECHECK_BOOKING),FULL_ACCESS)
        self.assertEqual(result.booking_status,BookingStatus.CONFIRMED)
        self.assertEqual(self.booking.creations,1)
        self.assertIn('Referans:',self.store.get_response(self.sid,result.response_ref).text)

    async def test_recheck_without_key_fails_safe(self):
        result=await self.policy.handle(self.sid,DialogueInput(Intent.RECHECK_BOOKING),FULL_ACCESS)
        self.assertEqual(result.action,'nothing_to_recheck')

    async def test_prevent_second_booking_while_confirmed(self):
        await self.policy.handle(self.sid,DialogueInput(Intent.REQUEST_INSPECTION,'v',SLOT),FULL_ACCESS)
        await self.policy.handle(self.sid,DialogueInput(Intent.CONFIRM),FULL_ACCESS)
        second=AppointmentSlot('2026-11-04T11:00:00+03:00','TRABZON')
        a=await self.policy.handle(self.sid,DialogueInput(Intent.REQUEST_INSPECTION,'v',second),FULL_ACCESS)
        self.assertEqual(a.action,'booking_exists')
        self.assertEqual(self.booking.creations,1)

    async def test_cancel_offer_after_handoff_requires_new_review(self):
        await self.policy.handle(self.sid,DialogueInput(Intent.REQUEST_INSPECTION,'v',SLOT),FULL_ACCESS)
        result=await self.policy.handle(self.sid,DialogueInput(Intent.HANDOFF),FULL_ACCESS)
        self.assertTrue(result.handoff_requested)
        result=await self.policy.handle(self.sid,DialogueInput(Intent.CONFIRM),FULL_ACCESS)
        self.assertEqual(result.action,'no_offer')
        self.assertEqual(self.booking.creations,0)

    async def test_cancellation_before_postavailability_mutation(self):
        count=0
        async def current():
            nonlocal count
            count += 1
            return count <= 1
        result=await self.policy.handle(self.sid,DialogueInput(Intent.REQUEST_INSPECTION,'v',SLOT),FULL_ACCESS,is_current=current)
        self.assertEqual(result.action,'stale_generation')
        self.assertEqual(self.policy.snapshot(self.sid)['booking_status'],'idle')

    async def test_invalid_reference_key_rejected(self):
        with self.assertRaises(ValueError):
            DialogueInput(Intent.GREETING,vehicle_id='phone: 555 12 34')

class M03CRM(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from automotive_voice.dialogue import CaseKind
        self.kind = CaseKind
        self.crm=FakeCRM({'v':VehicleRecord('v','Citroen','C3',2022)}, {})
        self.booking=FakeBookingService()
        self.policy=DialoguePolicy(self.crm,self.booking,ReferenceStore(),now=lambda:NOW)
        self.sid='crm-demo'
    def inp(self,k=None,vid='v'):
        return DialogueInput(Intent.CREATE_CRM_CASE,vid,case_kind=k)
    async def test_explicit_crm_case_created_once(self):
        a=await self.policy.handle(self.sid,self.inp(self.kind.CALLBACK),FULL_ACCESS)
        b=await self.policy.handle(self.sid,self.inp(self.kind.CALLBACK),FULL_ACCESS)
        self.assertEqual(a.action,'crm_case_created')
        self.assertEqual(b.action,'crm_case_created')
        self.assertEqual(self.crm.case_creations,1)
    async def test_case_requires_authorization(self):
        a=await self.policy.handle(self.sid,self.inp(self.kind.PRICE_REQUEST),AccessContext())
        self.assertEqual(a.action,'identity_required')
        self.assertEqual(self.crm.case_creations,0)
    async def test_case_requires_consent(self):
        a=await self.policy.handle(self.sid,self.inp(self.kind.PRICE_REQUEST),AccessContext(authenticated=True))
        self.assertEqual(a.action,'data_permission_required')
        self.assertEqual(self.crm.case_creations,0)
    async def test_case_requires_known_vehicle(self):
        a=await self.policy.handle(self.sid,self.inp(self.kind.EXPERTISE_INFO,'absent'),FULL_ACCESS)
        self.assertEqual(a.action,'vehicle_unverified')
        self.assertEqual(self.crm.case_creations,0)
    async def test_case_kind_must_be_whitelisted(self):
        with self.assertRaises(ValueError):
            DialogueInput(Intent.CREATE_CRM_CASE,'v',case_kind='arbitrary customer data')
    async def test_case_exception_no_success(self):
        async def break_write(*_):
            raise OSError('fake service unavailable')
        self.crm.create_case=break_write
        a=await self.policy.handle(self.sid,self.inp(self.kind.CALLBACK),FULL_ACCESS)
        self.assertEqual(a.action,'crm_case_unknown')
        self.assertEqual(self.crm.case_creations,0)
class M03FaultInjection(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sid='faults'
        self.store=ReferenceStore()
        self.crm=FakeCRM({'v':VehicleRecord('v','Nissan','Qashqai',2024)},
                         {'v':PriceQuote('v',200000,'source',NOW+timedelta(days=2))})
        self.book=FakeBookingService({FakeBookingService.key('v',SLOT):Availability.AVAILABLE})
        self.policy=DialoguePolicy(self.crm,self.book,self.store,now=lambda:NOW)
    async def test_crm_price_unavailable_under_exception(self):
        async def fault(*_): raise OSError('down')
        self.crm.get_price_quote=fault
        r=await self.policy.handle(self.sid,DialogueInput(Intent.PRICE_LOOKUP,'v'),FULL_ACCESS)
        self.assertEqual(r.action,'price_unavailable')
    async def test_crm_vehicle_lookup_fails_closed(self):
        async def fault(*_): raise OSError('down')
        self.crm.get_vehicle=fault
        r=await self.policy.handle(self.sid,DialogueInput(Intent.PRICE_LOOKUP,'v'),FULL_ACCESS)
        self.assertEqual(r.action,'vehicle_unverified')
    async def test_booking_availability_exception_unknown(self):
        async def fault(*_): raise TimeoutError('down')
        self.book.check_availability=fault
        r=await self.policy.handle(self.sid,DialogueInput(Intent.REQUEST_INSPECTION,'v',SLOT),FULL_ACCESS)
        self.assertEqual(r.booking_status,BookingStatus.UNKNOWN)
        self.assertEqual(self.book.creations,0)
class M03BookingGraph(unittest.TestCase):
    def test_invalid_direct_confirmation(self):
        from automotive_voice.dialogue import BookingStateMachine, BookingStateError
        with self.assertRaises(BookingStateError):
            BookingStateMachine.transition(BookingStatus.IDLE,BookingStatus.CONFIRMED)
    def test_handoff_terminal(self):
        from automotive_voice.dialogue import BookingStateMachine, BookingStateError
        with self.assertRaises(BookingStateError):
            BookingStateMachine.transition(BookingStatus.HANDOFF,BookingStatus.AWAITING_CONFIRMATION)
    def test_valid_offer_to_confirm_path(self):
        from automotive_voice.dialogue import BookingStateMachine
        state=BookingStatus.IDLE
        for target in [BookingStatus.AWAITING_CONFIRMATION,BookingStatus.CONFIRMING,BookingStatus.CONFIRMED]:
            state=BookingStateMachine.transition(state,target)
        self.assertEqual(state,BookingStatus.CONFIRMED)
