"""No-audio demonstration of M04 -> M05 -> fake TTS -> interruption."""
import asyncio
import json
from pathlib import Path
from .core.event_bus import EventBus
from .core.session_manager import SessionManager
from .nlp import TurkishAutomotiveNormalizer, A01YTReadOnlyAdapter
from .prosody import ProsodyClausePlanner, MockTTS

ROOT=Path(__file__).resolve().parents[1]
async def main():
    sid='m05-text-demo'
    mgr=SessionManager(EventBus())
    await mgr.create(sid)
    await mgr.start(sid)
    await mgr.begin_turn(sid)
    snap=await mgr.begin_response(sid)
    lex=A01YTReadOnlyAdapter(ROOT/'data/a01yt/a01yt_v05_readonly.sqlite3').load()
    normalizer=TurkishAutomotiveNormalizer(lexicon=lex, vocab_path=ROOT/'data/a01yt/freya_char_vocab.json')
    planner=ProsodyClausePlanner(lexicon=lex)
    p=planner.plan(normalizer.normalize('Randevu üç kasım iki bin yirmi altı saat on dört otuzda. Bunu onaylıyor musunuz?'),
                   session_id=snap.session_id,turn_id=snap.turn_id,generation_id=snap.generation_id)
    tts=MockTTS(mgr)
    receipt=await tts.enqueue(p)
    delivered=await tts.pop_next()
    await mgr.interrupt(sid)
    late=await tts.pop_next()
    out={'plan':p.safe_metadata(),'mock_enqueue':receipt.__dict__ if hasattr(receipt,'__dict__') else
         {'accepted':receipt.accepted,'reason':receipt.reason,'count':receipt.count},
         'first_clause_dispatched':delivered is not None,
         'old_generation_clause_after_barge_in':late is not None,
         'audio_generated':False}
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':
    asyncio.run(main())
