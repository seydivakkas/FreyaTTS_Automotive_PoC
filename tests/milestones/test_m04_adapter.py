import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from automotive_voice.nlp import A01YTReadOnlyAdapter

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT/'data/a01yt/a01yt_v05_readonly.sqlite3'

class AdapterTest(unittest.TestCase):
    def test_real_snapshot_empty_rules(self):
        lex = A01YTReadOnlyAdapter(SNAP).load()
        self.assertEqual(len(lex.rules),0)
    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError): A01YTReadOnlyAdapter('/tmp/m04_absent_database_123.sqlite3')
    def test_synthetic_review_requires_media_and_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'copy.sqlite3'
            shutil.copyfile(SNAP,path)
            cx=sqlite3.connect(path)
            source='YT-QASHQAI-001'
            # This is synthetic metadata only. A real import must verify actual clip hash.
            cx.execute('''INSERT INTO segments(id,source_id,start_sec,end_sec,clip_sha256,audio_status,
                       transcript_final,transcript_reviewer,created_at) VALUES (?,?,?,?,?,?,?,?,?)''',
                      ('synthetic_clip',source,1,4,'a'*64,'imported','Qashqai','tester','2026-10-31'))
            cx.execute('''INSERT INTO annotations(id,segment_id,canonical,spoken_tr,status,reviewer,reviewed_at)
                       VALUES (?,?,?,?,?,?,?)''',
                      ('synthetic_ann','synthetic_clip','Qashqai','kaşkay','approved','tester','2026-10-31'))
            cx.commit()
            self.assertEqual(len(A01YTReadOnlyAdapter(path).load().rules),0) # only link, no platform authorization
            cx.execute("UPDATE sources SET media_origin='direct_from_rights_holder' WHERE id=?",(source,))
            cx.commit()
            lex=A01YTReadOnlyAdapter(path).load()
            self.assertEqual(len(lex.rules),1)
            self.assertEqual(lex.apply('Qashqai').text,'kaşkay')
            cx.execute("UPDATE annotations SET reviewer='' WHERE id='synthetic_ann'")
            cx.commit()
            self.assertEqual(len(A01YTReadOnlyAdapter(path).load().rules),0)
            cx.close()

    def test_legacy_320_hash_kept(self):
        p=ROOT/'data/fixtures/legacy_320_cases.json'
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),
                         '7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e')
