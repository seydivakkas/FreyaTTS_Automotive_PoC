"""M03 fully synthetic two-phase vehicle booking; no network, voice or real CRM."""
import asyncio
from datetime import datetime, timezone, timedelta
from automotive_voice.conversation import ConversationReducer, ConversationSignal, SignalKind
from automotive_voice.dialogue import (ReferenceStore, DialogueInput, DialoguePolicy,
    DialogueCoordinator, FakeCRM, FakeBookingService, VehicleRecord, PriceQuote, AccessContext,
    AppointmentSlot, Availability, Intent)

async def main():
    sid = 'm03-automotive-local-demo'
    store = ReferenceStore()
    reducer = ConversationReducer()
    when = datetime.now(timezone.utc)
    slot = AppointmentSlot((when + timedelta(days=3)).astimezone(timezone(timedelta(hours=3))).replace(hour=14,minute=30,second=0,microsecond=0).isoformat(), 'TRABZON')
    crm = FakeCRM({'demo-car':VehicleRecord('demo-car','Nissan','Qashqai',2024)},
                  {'demo-car':PriceQuote('demo-car',1250000,'synthetic-quote',when+timedelta(days=3))})
    booking = FakeBookingService({FakeBookingService.key('demo-car',slot):Availability.AVAILABLE})
    policy = DialoguePolicy(crm,booking,store)
    coord = DialogueCoordinator(reducer,policy,store)
    access = AccessContext(authenticated=True, crm_processing_allowed=True)

    async def emit(kind,ref=None):
        snap = await reducer.try_snapshot(sid)
        signal = ConversationSignal.create(kind,sid,int(snap.turn_id) if snap else 0,
                 int(snap.generation_id) if snap else 0,
                 await reducer.expected_sequence(sid),reference=ref)
        return await reducer.handle(signal)

    await emit(SignalKind.SESSION_OPENED)
    for input_item in [DialogueInput(Intent.PRICE_LOOKUP,'demo-car'),
                       DialogueInput(Intent.REQUEST_INSPECTION,'demo-car',slot),
                       DialogueInput(Intent.CONFIRM)]:
        ref=store.put_input(sid,input_item)
        out=await emit(SignalKind.TRANSCRIPT_FINAL,ref)
        response=await coord.process(out.effects[0],access)
        assert response.status == 'applied',response
        print(input_item.intent.value, ':',store.get_response(sid,response.response_ref).text)
        await emit(SignalKind.PLAYOUT_FINISHED)
    assert booking.creations == 1
    await emit(SignalKind.HANGUP)
    print('PASS: 3 turns; 1 confirmed synthetic booking; real audio/phone not used')

if __name__ == '__main__':
    asyncio.run(main())
