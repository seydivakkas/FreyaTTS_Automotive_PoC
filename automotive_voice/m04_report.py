"""Deterministic, text-only golden set impact report. No model/GPU/audio."""
from __future__ import annotations
import csv
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from .nlp import TurkishAutomotiveNormalizer, A01YTReadOnlyAdapter

ROOT = Path(__file__).resolve().parents[1]

def build_report(output: Path | None = None) -> dict:
    dataset = ROOT/'data/fixtures/legacy_320_cases.json'
    data = json.loads(dataset.read_text(encoding='utf-8'))
    if len(data) != 320 or len({r['id'] for r in data}) != 320:
        raise ValueError('golden 320 fixture has changed')
    a01_db = ROOT/'data/a01yt/a01yt_v05_readonly.sqlite3'
    lex = A01YTReadOnlyAdapter(a01_db).load()
    normalizer = TurkishAutomotiveNormalizer(lexicon=lex, vocab_path=ROOT/'data/a01yt/freya_char_vocab.json')
    rows=[]
    for entry in data:
        norm = normalizer.normalize(entry['text'])
        rows.append({'id':entry['id'], 'category':entry['category'],
                     'changed':int(norm.spoken_text != norm.display_text),
                     'review_required':int(norm.review_required),
                     'unsupported_chars':''.join(norm.unsupported_chars),
                     'warning_codes':';'.join(norm.warnings),
                     'applied_rules':';'.join(norm.rules_applied),
                     'original':norm.display_text,'prepared':norm.spoken_text})
    with sqlite3.connect(a01_db) as conn:
        source_count=conn.execute('SELECT count(*) FROM sources').fetchone()[0]
        segments=conn.execute('SELECT count(*) FROM segments').fetchone()[0]
        approved_annotations=conn.execute("SELECT count(*) FROM annotations WHERE status='approved'").fetchone()[0]
    metrics = {'input_count':len(rows), 'input_sha256':sha256(dataset.read_bytes()).hexdigest(),
               'changed_texts':sum(r['changed'] for r in rows),
               'review_required':sum(r['review_required'] for r in rows),
               'unsupported_char_cases':sum(bool(r['unsupported_chars']) for r in rows),
               'a01yt_sources':source_count,'a01yt_segments':segments,
               'a01yt_approved_annotations':approved_annotations,
               'active_lexicon_rules':len(lex.rules),
               'voice_quality_measured':False,'audio_generated':False,
               'interpretation':'Text transformations are NOT evidence of pronunciation or speech quality improvement.'}
    if output is not None:
        output.mkdir(parents=True,exist_ok=True)
        (output/'m04_320_summary.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        with (output/'m04_320_compare.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return metrics

def main():
    print(json.dumps(build_report(ROOT/'data/reports'),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
