"""M05 320-golden text-only planning report. Never produces audio."""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
import csv
import json
from pathlib import Path
from .nlp import TurkishAutomotiveNormalizer, A01YTReadOnlyAdapter
from .core.identifiers import SessionId, TurnId, GenerationId
from .prosody import ProsodyClausePlanner

ROOT = Path(__file__).resolve().parents[1]
LEGACY_SHA256 = '7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e'

def build_report(output: Path | None = None) -> dict:
    fixture = ROOT/'data/fixtures/legacy_320_cases.json'
    digest = sha256(fixture.read_bytes()).hexdigest()
    if digest != LEGACY_SHA256:
        raise ValueError('legacy 320 SHA-256 mismatch')
    rows_in = json.loads(fixture.read_text(encoding='utf-8'))
    if len(rows_in) != 320 or len({e['id'] for e in rows_in}) != 320:
        raise ValueError('legacy 320 fixture altered')
    lex = A01YTReadOnlyAdapter(ROOT/'data/a01yt/a01yt_v05_readonly.sqlite3').load()
    n = TurkishAutomotiveNormalizer(lexicon=lex, vocab_path=ROOT/'data/a01yt/freya_char_vocab.json')
    p = ProsodyClausePlanner(lexicon=lex)
    rows=[]
    for entry in rows_in:
        normalization=n.normalize(entry['text'])
        plan=p.plan(normalization,session_id=SessionId('m05-report'), turn_id=TurnId(1),generation_id=GenerationId(1))
        rows.append({'case_id':entry['id'],'category':entry['category'],
                     'status':plan.status.value,'clauses':len(plan.clauses),
                     'protected_spans':len(plan.protected_spans),
                     'tts_input_count':len(plan.tts_inputs()),
                     'warning_codes':';'.join(plan.warning_codes),
                     'breaks':';'.join(c.break_kind.value for c in plan.clauses)})
    statuses=Counter(r['status'] for r in rows)
    summary={'fixture_count':320,'fixture_sha256':digest,
             'ready_plans':statuses['ready'], 'review_required_plans':statuses['review_required'],
             'total_text_clauses':sum(r['clauses'] for r in rows),
             'eligible_mock_tts_inputs':sum(r['tts_input_count'] for r in rows),
             'total_protected_spans':sum(r['protected_spans'] for r in rows),
             'active_approved_lexicon_rules':len(lex.rules),
             'real_tts_calls':0,'audio_files_generated':0,
             'claims_about_audio_quality':'none; text-only deterministic simulation'}
    if output is not None:
        output.mkdir(parents=True,exist_ok=True)
        (output/'m05_320_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        with (output/'m05_320_clause_report.csv').open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return summary

def main():
    print(json.dumps(build_report(ROOT/'data/reports'),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
