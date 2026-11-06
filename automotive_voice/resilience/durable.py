"""SQLite-authoritative session transitions and at-least-once event outbox.

No network, no production automatic recovery. New process fails open calls closed:
nonterminal sessions become FAILED or ENDED and are never resumed. M02 runtime,
booking confirmation, flush ACK and effect queues are NOT recoverable here.
"""
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from automotive_voice.core.session import Session, State
from automotive_voice.core.session_manager import (SessionManager, SessionSnapshot, _ManagedSession,
    SessionAlreadyExistsError, SessionOutboxFullError)
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.core.events import EventEnvelope, EventType

TERMINAL = (State.ENDED, State.FAILED, State.HANDOFF)

class DurableConflict(RuntimeError):
    pass

class DurableJournal:
    """Single-process connection, SQLite WAL, synchronous FULL, atomic snapshots+outbox."""
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(str(path), timeout=5, isolation_level=None)
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, state TEXT NOT NULL, turn_id INTEGER NOT NULL,
            generation_id INTEGER NOT NULL, last_sequence INTEGER NOT NULL,
            recovery_required INTEGER NOT NULL DEFAULT 0
          );
          CREATE TABLE IF NOT EXISTS outbox (
            session_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE,
            envelope TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','acked')),
            PRIMARY KEY (session_id, sequence),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
          );
          CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox (status,session_id,sequence);
        ''')

    def close(self):
        self.db.close()

    def insert_session(self, sid: SessionId):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('INSERT INTO sessions VALUES (?, ?, 0, 0, -1, 0)', (str(sid), State.IDLE.value))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def append(self, new: Session, previous: Session, expected_seq: int,
               events: list[EventEnvelope], *, recovery: bool=False):
        """CAS, monotonic counters, contiguous events; all or nothing."""
        if not events or any(e.session_id != new.session_id for e in events):
            raise DurableConflict('event scope missing')
        if any(e.sequence != expected_seq + i + 1 for i,e in enumerate(events)):
            raise DurableConflict('noncontiguous event sequence')
        # The journal must never retain raw customer text or audio. Even safe event
        # payloads should carry opaque refs and diagnostic codes only.
        prohibited={'transcript','raw_text','customer_name','phone_number','email',
                    'vin','audio_bytes','recording','customer_address'}
        def has_sensitive_key(value):
            if isinstance(value,dict):
                return any(str(k).lower() in prohibited or has_sensitive_key(v) for k,v in value.items())
            if isinstance(value,list):return any(has_sensitive_key(v) for v in value)
            return False
        if any(has_sensitive_key(e.to_dict()['payload']) for e in events):
            raise DurableConflict('sensitive_payload_key_rejected')
        if new.turn_id < previous.turn_id or new.generation_id < previous.generation_id:
            raise DurableConflict('turn or generation regression')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT state,turn_id,generation_id,last_sequence,recovery_required FROM sessions WHERE session_id=?', (new.session_id,)).fetchone()
            if row is None or row[:4] != (previous.state.value,previous.turn_id,previous.generation_id,expected_seq):
                raise DurableConflict('stale snapshot or changed sequence')
            if row[4] and not recovery:
                raise DurableConflict('session recovery hold')
            result=self.db.execute('UPDATE sessions SET state=?,turn_id=?,generation_id=?,last_sequence=?,recovery_required=? WHERE session_id=?',
                (new.state.value,new.turn_id,new.generation_id,events[-1].sequence,int(bool(row[4] or recovery)),new.session_id))
            if result.rowcount!=1:raise DurableConflict('lost update')
            for e in events:
                self.db.execute('INSERT INTO outbox VALUES (?,?,?,?,?)',
                    (str(e.session_id),e.sequence,e.event_id,json.dumps(e.to_dict(),sort_keys=True,ensure_ascii=False), 'pending'))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def read_all(self):
        rows=self.db.execute('SELECT session_id,state,turn_id,generation_id,last_sequence,recovery_required FROM sessions ORDER BY session_id').fetchall()
        for sid,st,turn,gen,seq,hold in rows:
            events=[EventEnvelope.from_dict(json.loads(r[0])) for r in
                self.db.execute("SELECT envelope FROM outbox WHERE session_id=? AND status='pending' ORDER BY sequence", (sid,)).fetchall()]
            acked=self.db.execute("SELECT MAX(sequence) FROM outbox WHERE session_id=? AND status='acked'",(sid,)).fetchone()[0]
            yield (sid, State(st),turn,gen,seq,bool(hold),events,acked if acked is not None else -1)

    def ack(self, sid: str, sequence: int):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT status FROM outbox WHERE session_id=? AND sequence=?',(sid,sequence)).fetchone()
            if row is None or row[0]!='pending':raise DurableConflict('event not pending')
            earlier=self.db.execute("SELECT 1 FROM outbox WHERE session_id=? AND sequence<? AND status='pending' LIMIT 1",
                                    (sid,sequence)).fetchone()
            if earlier:raise DurableConflict('earlier_event_unacknowledged')
            self.db.execute("UPDATE outbox SET status='acked' WHERE session_id=? AND sequence=?",(sid,sequence))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def counts(self) -> dict:
        sessions=self.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
        pending=self.db.execute("SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0]
        recovery=self.db.execute('SELECT COUNT(*) FROM sessions WHERE recovery_required=1').fetchone()[0]
        return {'sessions':sessions,'pending_outbox':pending,'recovery_holds':recovery}


class DurableSessionManager(SessionManager):
    """M01 public API with durable commit before memory mutation.

    Must call await restore_fail_closed() on a new manager BEFORE receiving events.
    This intentionally ends abandoned sessions; M02 and external tool effects are
    never automatically reissued across restart.
    """
    def __init__(self, bus, journal: DurableJournal, max_pending_events: int=256):
        super().__init__(bus,max_pending_events)
        self.journal=journal
        self._restored=False

    async def restore_fail_closed(self) -> int:
        async with self._directory_lock:
            if self._restored: return 0
            recovered=0
            for sid,st,turn,gen,seq,hold,events,acked in list(self.journal.read_all()):
                managed=_ManagedSession(Session(sid,state=st,turn_id=turn,generation_id=gen))
                managed.last_sequence=seq
                managed.outbox=deque(events)
                if st in TERMINAL:managed.cancellation.cancel_current()
                elif gen:managed.cancellation.advance(GenerationId(gen))
                self._sessions[SessionId(sid)]=managed
                # Fresh bus must start from last durably ACKed sequence, not -1.
                self.bus._last_sequence[sid]=acked
                if st not in (State.ENDED,State.FAILED):
                    old=replace(managed.value, history=list(managed.value.history))
                    new=replace(old, history=list(old.history))
                    target=State.ENDED if st==State.IDLE else State.FAILED
                    new.move(target)
                    e=EventEnvelope.create(EventType.SESSION_ENDED if target==State.ENDED else EventType.SESSION_FAILED,
                        SessionId(sid),TurnId(turn),GenerationId(gen),seq+1,{'code':'unclean_restart','requires_manual_reconcile':True})
                    self.journal.append(new,old,seq,[e],recovery=True)
                    managed.value=new
                    managed.last_sequence+=1
                    managed.outbox.append(e)
                    managed.cancellation.cancel_current()
                    recovered+=1
            self._restored=True
            return recovered

    async def create(self,session_id: str|None=None)->SessionSnapshot:
        if not self._restored:raise RuntimeError('restore_fail_closed first')
        sid=SessionId.new() if session_id is None else SessionId(session_id)
        async with self._directory_lock:
            if sid in self._sessions:raise SessionAlreadyExistsError(str(sid))
            self.journal.insert_session(sid)
            m=_ManagedSession(Session(sid))
            self._sessions[sid]=m
            return self._snapshot(m)

    async def _apply(self,session_id,event_type,mutation,payload=None,*,idempotent_ended=False):
        m=self._entry(session_id)
        async with m.lock:
            if idempotent_ended and m.value.state==State.ENDED:return self._snapshot(m)
            if len(m.outbox)>=self._pending_limit:raise SessionOutboxFullError('durable outbox full')
            old=m.value
            new=replace(old,history=list(old.history))
            old_gen=new.generation_id
            mutation(new)
            event=EventEnvelope.create(event_type,SessionId(new.session_id),TurnId(new.turn_id),
                GenerationId(new.generation_id),m.last_sequence+1,payload or {})
            self.journal.append(new,old,m.last_sequence,[event])
            m.value=new; m.last_sequence+=1;m.outbox.append(event)
            if new.state in TERMINAL:m.cancellation.cancel_current()
            elif new.generation_id>old_gen:m.cancellation.advance(GenerationId(new.generation_id))
            return self._snapshot(m)

    async def complete_interrupt_with_followup(self,session_id:str,followup:str|None=None):
        if followup not in (None,'turn','handoff'):raise ValueError('invalid followup')
        m=self._entry(session_id)
        async with m.lock:
            n=1+int(followup is not None)
            if len(m.outbox)+n>self._pending_limit:raise SessionOutboxFullError('outbox full')
            old=m.value;new=replace(old,history=list(old.history))
            if new.state!=State.INTERRUPTING:raise ValueError('not interrupting')
            new.move(State.LISTENING)
            first=EventEnvelope.create(EventType.INTERRUPTION_COMPLETED,SessionId(new.session_id),
                TurnId(new.turn_id),GenerationId(new.generation_id),m.last_sequence+1,
                {'to':'LISTENING','transport_ack':True})
            events=[first]
            if followup=='turn':
                new.new_turn()
                events.append(EventEnvelope.create(EventType.TURN_STARTED,SessionId(new.session_id),
                    TurnId(new.turn_id),GenerationId(new.generation_id),m.last_sequence+2,
                    {'to':'THINKING','source':'deferred_transcript'}))
            elif followup=='handoff':
                new.move(State.HANDOFF)
                events.append(EventEnvelope.create(EventType.HANDOFF_REQUESTED,SessionId(new.session_id),
                    TurnId(new.turn_id),GenerationId(new.generation_id),m.last_sequence+2,
                    {'to':'HANDOFF','source':'deferred_handoff'}))
            self.journal.append(new,old,m.last_sequence,events)
            m.value=new;m.last_sequence+=len(events);m.outbox.extend(events)
            if new.state in TERMINAL:m.cancellation.cancel_current()
            elif new.generation_id>old.generation_id:m.cancellation.advance(GenerationId(new.generation_id))
            return self._snapshot(m)

    async def emergency_close(self,session_id:str,*,fail:bool=False):
        m=self._entry(session_id)
        async with m.lock:
            if m.value.state in (State.ENDED,State.FAILED):return self._snapshot(m)
            old=m.value;new=replace(old,history=list(old.history))
            target=State.FAILED if fail and new.state!=State.IDLE else State.ENDED
            new.move(target)
            e=EventEnvelope.create(EventType.SESSION_FAILED if target==State.FAILED else EventType.SESSION_ENDED,
                SessionId(new.session_id),TurnId(new.turn_id),GenerationId(new.generation_id),
                m.last_sequence+1,{'code':'emergency_close','forced':True})
            self.journal.append(new,old,m.last_sequence,[e],recovery=True)
            m.value=new;m.last_sequence+=1;m.outbox.append(e);m.cancellation.cancel_current()
            return self._snapshot(m)

    async def dispatch_pending(self,session_id:str)->int:
        m=self._entry(session_id)
        count=0
        async with m.lock:
            while m.outbox:
                e=m.outbox[0]
                await self.bus.publish(e)
                # If process dies here, duplicate replay is possible. Consumers MUST dedup by event_id.
                self.journal.ack(session_id,e.sequence)
                m.outbox.popleft();count+=1
        return count
