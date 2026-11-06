import asyncio
import unittest
import json
from pathlib import Path
from automotive_voice.core.session import Session, State
from automotive_voice.domain.booking import BookingOutcome, can_announce_booking
from automotive_voice.ports.contracts import AudioFormat
from automotive_voice.adapters.fake import FakeTTS, FakeMediaOutput

class SessionTests(unittest.TestCase):
    def test_nominal_transition(self):
        s = Session("s1")
        s.move(State.LISTENING); g=s.new_turn(); s.move(State.SPEAKING)
        self.assertTrue(s.accepts_chunk(g))
        s.move(State.LISTENING);s.move(State.ENDED);s.move(State.ENDED)
    def test_bad_transition_rejected(self):
        s=Session("s1")
        with self.assertRaises(ValueError):s.move(State.SPEAKING)
    def test_interrupt_rejects_late_output(self):
        s=Session("s2");s.move(State.LISTENING);old=s.new_turn();s.move(State.SPEAKING)
        s.interrupt();self.assertFalse(s.accepts_chunk(old))
        self.assertEqual(s.generation_id,old+1)
    def test_booking_requires_confirmed_and_ref(self):
        self.assertFalse(can_announce_booking(BookingOutcome("available",None),True))
        self.assertFalse(can_announce_booking(BookingOutcome("confirmed","r123"),False))
        self.assertFalse(can_announce_booking(BookingOutcome("confirmed",None),True))
        self.assertTrue(can_announce_booking(BookingOutcome("confirmed","r123"),True))
    def test_format_mismatch_rejected(self):
        with self.assertRaises(ValueError): AudioFormat(44100,1,32,"float32")
        with self.assertRaises(ValueError): AudioFormat(8000,2,16,"pcm_s16le")
    def test_legacy_cases_preserved(self):
        p = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "legacy_320_cases.json"
        cases = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 320)
        self.assertEqual(len({x["id"] for x in cases}), 320)

    def test_fake_output_flush(self):
        async def check():
            out=FakeMediaOutput();tts=FakeTTS();s=Session("s");s.move(State.LISTENING);g=s.new_turn();s.move(State.SPEAKING)
            async for chunk in tts.synthesize("Merhaba size nasıl yardımcı olabilirim",g):
                await out.enqueue(chunk)
            self.assertEqual(len(out.items),5)
            s.interrupt();await out.flush();self.assertEqual(len(out.items),0)
            self.assertEqual(out.flush_count,1)
        asyncio.run(check())

if __name__ == '__main__':unittest.main()
