"""A01-YT read-only source adapter + local operator audit overlay.

No modification of the A01-YT database. Approvals require physically accessible,
checksum-verified recorded audio plus finalized human transcription and license scope.
The overlay does not promote rules into Freya's approved production lexicon.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import sqlite3
from contextlib import contextmanager, closing
import wave
from datetime import datetime, timezone
from uuid import uuid4

class ReviewError(ValueError):
    pass

class PronunciationReviewStore:
    def __init__(self, source_db: str | Path, overlay_db: str | Path):
        self.source_db=Path(source_db).resolve(strict=True)
        self.overlay_db=Path(overlay_db).resolve()
        self.overlay_db.parent.mkdir(parents=True,exist_ok=True)
        with self._overlay() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS operator_review (
              id TEXT PRIMARY KEY, annotation_id TEXT NOT NULL, decision TEXT NOT NULL
              CHECK(decision IN ('approved','rejected')), reviewer TEXT NOT NULL,
              reason_code TEXT NOT NULL, source_sha256 TEXT, reviewed_at TEXT NOT NULL)''')
            conn.execute('CREATE INDEX IF NOT EXISTS operator_review_by_annotation ON operator_review(annotation_id,reviewed_at)')

    @contextmanager
    def _source(self):
        with closing(sqlite3.connect(f'file:{self.source_db.as_posix()}?mode=ro',uri=True)) as conn:
            conn.row_factory=sqlite3.Row
            yield conn

    @contextmanager
    def _overlay(self):
        with closing(sqlite3.connect(self.overlay_db)) as conn:
            conn.row_factory=sqlite3.Row
            with conn:
                yield conn

    def sources(self):
        with self._source() as conn:
            data=conn.execute('''SELECT id,title,creator,url,rights_basis,permission_claim_status,
              permitted_scope,audio_use_authorized FROM sources ORDER BY id''').fetchall()
        return [dict(x) for x in data]

    def items(self):
        with self._source() as conn:
            data=conn.execute('''SELECT a.id,a.canonical,a.spoken_tr,a.status,a.reviewer,a.kind,
                  s.id AS segment_id,s.source_id,s.start_sec,s.end_sec,s.audio_status,
                  s.clip_sha256,s.clip_path,s.transcript_final,s.transcript_reviewer,
                  p.permitted_scope,p.audio_use_authorized,p.title
                  FROM annotations a JOIN segments s ON s.id=a.segment_id
                  JOIN sources p ON p.id=s.source_id ORDER BY p.id,s.start_sec,a.id LIMIT 200''').fetchall()
        with self._overlay() as conn:
            reviews=conn.execute('''SELECT annotation_id,decision,reviewer,reason_code,reviewed_at
                  FROM operator_review ORDER BY reviewed_at,id''').fetchall()
        latest={x['annotation_id']:dict(x) for x in reviews}
        out=[]
        for item in data:
            entry=dict(item)
            # Clip paths never leave backend; do not leak transcript text or arbitrary file paths.
            entry.pop('clip_path')
            entry.pop('transcript_final')
            entry['transcript_checked']=bool(item['transcript_final'] and item['transcript_reviewer'])
            entry['has_clip_reference']=bool(item['clip_path'] and item['clip_sha256'])
            entry['review']=latest.get(item['id'])
            out.append(entry)
        return out

    def _evidence(self, annotation_id: str):
        with self._source() as conn:
            item=conn.execute('''SELECT a.id,a.canonical,a.spoken_tr,
                s.clip_path,s.clip_sha256,s.transcript_final,s.transcript_reviewer,
                p.audio_use_authorized,p.permitted_scope
                FROM annotations a JOIN segments s ON s.id=a.segment_id
                JOIN sources p ON p.id=s.source_id WHERE a.id=?''',(annotation_id,)).fetchone()
        if item is None: raise ReviewError('unknown_annotation')
        if not item['audio_use_authorized'] or 'pronunciation' not in (item['permitted_scope'] or '').lower():
            raise ReviewError('source_permission_scope_not_accepted')
        if not item['transcript_final'] or not item['transcript_reviewer']:
            raise ReviewError('human_transcript_required')
        if not item['canonical'] or not item['spoken_tr']:
            raise ReviewError('pronunciation_required')
        rel=item['clip_path']
        if not rel or not item['clip_sha256']:raise ReviewError('audio_evidence_required')
        p=Path(rel)
        # Refuse absolute paths, traversal and symlinks to files outside the approved source directory.
        if p.is_absolute(): raise ReviewError('source_path_outside_evidence_root')
        base=self.source_db.parent
        try:full=(base/p).resolve(strict=True)
        except (OSError,ValueError):raise ReviewError('audio_evidence_missing')
        if not full.is_relative_to(base):raise ReviewError('source_path_outside_evidence_root')
        if not full.is_file() or full.stat().st_size>50_000_000:raise ReviewError('audio_evidence_invalid')
        with full.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest.lower()!=item['clip_sha256'].lower():raise ReviewError('audio_evidence_checksum_mismatch')
        if full.suffix.lower()!='.wav':raise ReviewError('decoded_wav_required')
        try:
            with wave.open(str(full),'rb') as wav:
                if wav.getcomptype()!='NONE' or wav.getsampwidth()!=2 or wav.getnchannels()!=1 or wav.getframerate() not in (8000,16000,48000) or wav.getnframes()<160:
                    raise ReviewError('invalid_pcm_audio_evidence')
        except (wave.Error,EOFError, OSError) as exc:
            raise ReviewError('invalid_pcm_audio_evidence') from exc
        return digest

    def decide(self, annotation_id: str, decision: str, *, reviewer: str, reason_code: str) -> dict:
        if not isinstance(annotation_id,str) or len(annotation_id)>128 or not annotation_id.isascii():
            raise ReviewError('invalid_annotation_id')
        if decision not in ('approved','rejected'):raise ReviewError('invalid_decision')
        if not isinstance(reviewer,str) or not 1<=len(reviewer)<=48 or not reviewer.isascii() or not reviewer.replace('_','').replace('-','').isalnum():
            raise ReviewError('invalid_reviewer')
        if reason_code not in ('verified_evidence','incorrect_reading','insufficient_evidence','duplicate','other'):
            raise ReviewError('invalid_reason_code')
        if decision=='approved':
            if reason_code!='verified_evidence':raise ReviewError('approval_requires_verified_evidence')
            digest=self._evidence(annotation_id)
        else:
            with self._source() as conn:
                exists=conn.execute('SELECT 1 FROM annotations WHERE id=?',(annotation_id,)).fetchone()
            if not exists:raise ReviewError('unknown_annotation')
            digest=None
        record={'id':str(uuid4()),'annotation_id':annotation_id,'decision':decision,
                'reviewer':reviewer,'reason_code':reason_code,'source_sha256':digest,
                'reviewed_at':datetime.now(timezone.utc).isoformat()}
        with self._overlay() as conn:
            conn.execute('''INSERT INTO operator_review
                (id,annotation_id,decision,reviewer,reason_code,source_sha256,reviewed_at)
                VALUES (:id,:annotation_id,:decision,:reviewer,:reason_code,:source_sha256,:reviewed_at)''',record)
        return record
