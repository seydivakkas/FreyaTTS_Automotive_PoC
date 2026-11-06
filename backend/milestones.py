"""Live bridges to the supplied M01–M11 contracts; synthetic adapters stay opt-in."""

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid4
from dataclasses import asdict
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session import State
from automotive_voice.resilience.durable import DurableJournal, DurableSessionManager
from automotive_voice.nlp.normalizer import TurkishAutomotiveNormalizer
from automotive_voice.prosody.planner import ProsodyClausePlanner
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.operator.review_store import PronunciationReviewStore
from backend.db import engine


def runtime_root():
    return Path(engine.url.database).with_suffix("") / "sessions"


class LiveControl:
    """M01 state authority with M10 durable outbox for local application events.

    Dispatch ACK means local event-bus delivery, never PBX playout/flush ACK.
    No synthetic M06 transport or fake business service is used here.
    """

    def __init__(self, sid):
        self.sid = str(UUID(sid))
        self.lock = asyncio.Lock()
        self.manager = None
        self.journal = None

    async def _ensure(self):
        if self.manager is not None:
            return
        self.journal = DurableJournal(runtime_root() / (self.sid + ".sqlite3"))
        self.manager = DurableSessionManager(EventBus(), self.journal)
        await self.manager.restore_fail_closed()
        await self.manager.create(self.sid)
        await self.manager.start(self.sid)
        await self.manager.dispatch_pending(self.sid)

    async def move(self, target):
        async with self.lock:
            await self._ensure()
            manager = self.manager
            state = (await manager.snapshot(self.sid)).state
            if target == "thinking":
                if state == State.SPEAKING:
                    await manager.interrupt(self.sid)
                    # Local output queue has been invalidated by VoiceSession.
                    # AudioSocket offers no remote flush acknowledgment.
                    await manager.complete_interrupt(self.sid)
                elif state == State.THINKING:
                    await manager.abort_thinking(self.sid)
                if (await manager.snapshot(self.sid)).state == State.LISTENING:
                    await manager.begin_turn(self.sid)
            elif target == "speaking":
                if state == State.LISTENING:
                    await manager.begin_turn(self.sid)
                if (await manager.snapshot(self.sid)).state == State.THINKING:
                    await manager.begin_response(self.sid)
            elif target == "listening":
                if state == State.SPEAKING:
                    await manager.finish_playout(self.sid)
                elif state == State.THINKING:
                    await manager.abort_thinking(self.sid)
            elif target == "ended":
                await manager.end(self.sid)
            else:
                raise ValueError("Unknown control target")
            await manager.dispatch_pending(self.sid)
            return await manager.snapshot(self.sid)

    async def accepts(self, generation):
        return bool(
            self.manager and await self.manager.accepts_chunk(self.sid, generation)
        )

    async def close(self):
        if self.manager:
            try:
                await self.move("ended")
            finally:
                self.journal.close()
                self.manager = None


async def recover_abandoned():
    count = 0
    for path in runtime_root().glob("*.sqlite3"):
        journal = DurableJournal(path)
        try:
            manager = DurableSessionManager(EventBus(), journal)
            count += await manager.restore_fail_closed()
        finally:
            journal.close()
    return count


def timeline(sid):
    path = runtime_root() / (str(UUID(sid)) + ".sqlite3")
    if not path.exists():
        return []
    with closing(
        sqlite3.connect("file:" + path.resolve().as_posix() + "?mode=ro", uri=True)
    ) as db:
        return [
            json.loads(r[0])
            for r in db.execute("SELECT envelope FROM outbox ORDER BY sequence")
        ]


def reviews():
    return PronunciationReviewStore(
        "data/a01yt/a01yt_v05_readonly.sqlite3",
        runtime_root().parent / "pronunciation-review.sqlite3",
    )


def inspect_text(text):
    normalized = TurkishAutomotiveNormalizer(
        vocab_path="config/freya_vocab.json"
    ).normalize(text)
    plan = ProsodyClausePlanner().plan(
        normalized,
        session_id=SessionId(str(uuid4())),
        turn_id=TurnId(1),
        generation_id=GenerationId(1),
    )
    return {
        "mode": "TEXT_CONTRACT_REVIEW",
        "normalization": normalized.as_dict(),
        "plan": {**plan.safe_metadata(), "clauses": [asdict(c) for c in plan.clauses]},
        "audio_generated": False,
    }
