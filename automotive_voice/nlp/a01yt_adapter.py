"""Read-only A01-YT SQLite snapshot adapter; never licenses or synthesizes audio.

Only observation rows with review provenance, media-import metadata and a
source-specific permission basis are candidates. Empty v0.5 observations =>
empty lexicon. Approval is still an application review decision.
"""
from __future__ import annotations
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from .lexicon import AutomotiveLexicon, LexiconRule, LexiconError, tr_key

class A01YTReadOnlyAdapter:
    def __init__(self, sqlite_path: str | Path):
        self.path = Path(sqlite_path)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)

    def load(self) -> AutomotiveLexicon:
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as cx:
            cx.row_factory = sqlite3.Row
            cx.execute('PRAGMA query_only = ON')
            rows = cx.execute('''
                SELECT a.id AS annotation_id, a.canonical, a.spoken_tr, a.context,
                       a.reviewer, a.reviewed_at, s.id AS clip_id, s.clip_sha256, s.audio_status,
                       s.transcript_final, s.transcript_reviewer,
                       so.url, so.rights_basis, so.rights_evidence,
                       so.platform_authorized, so.audio_use_authorized,
                       so.media_origin, so.permission_claim_status,
                       so.permitted_scope, so.verified_by, so.attribution
                FROM annotations a
                JOIN segments s ON s.id = a.segment_id
                JOIN sources so ON so.id = s.source_id
                WHERE a.status = 'approved'
                ORDER BY a.id
            ''').fetchall()
        by_term: dict[str, list[sqlite3.Row]] = {}
        for r in rows:
            valid = (not r['context'] and bool(r['reviewer']) and bool(r['reviewed_at'])
              and bool(r['transcript_reviewer']) and bool(r['transcript_final'])
              and r['audio_status'] == 'imported' and bool(r['clip_id']) and bool(re.fullmatch(r'[0-9a-fA-F]{64}', r['clip_sha256'] or ''))
              and bool(r['audio_use_authorized']) and bool(r['verified_by'])
              and bool(r['rights_evidence']) and bool(r['attribution'])
              and r['rights_basis'] in ('cc_by', 'written_permission', 'verbal_permission', 'owned')
              and r['permission_claim_status'] in ('user_attested', 'documented', 'verified')
              and r['permitted_scope'] in ('pronunciation_reference','tts_lexicon_reference','reference_and_training')
              and (r['media_origin'] == 'direct_from_rights_holder' or bool(r['platform_authorized'])))
            if valid:
                by_term.setdefault(tr_key(r['canonical']), []).append(r)
        rules = []
        for term, observations in sorted(by_term.items()):
            if len({tr_key(r['spoken_tr']) for r in observations}) != 1:
                # Conflicting observations must not be auto-resolved.
                continue
            first = observations[0]
            evidence = tuple({'annotation_id':r['annotation_id'], 'clip_id':r['clip_id'],
                              'source_url':r['url'], 'clip_sha256':r['clip_sha256']}
                             for r in observations)
            try:
                rules.append(LexiconRule(first['canonical'], first['spoken_tr'], True,
                    first['url'], first['reviewer'], evidence))
            except LexiconError:
                continue
        return AutomotiveLexicon(tuple(rules))
