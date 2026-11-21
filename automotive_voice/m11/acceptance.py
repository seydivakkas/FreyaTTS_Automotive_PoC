"""M11 auditable, fail-closed acceptance verdicts. No fake measurements become PASS.

All gate records are inspectable JSON with SHA256 evidence references. The ledger
only establishes file integrity/field validation; human provenance and live
hardware authenticity must also be checked by the independent reviewer.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256
from enum import Enum
from typing import Iterable
import json
import unicodedata
import re
import wave

GATES = ('windows_edge', 'freya_leyla', 'stt_vad', 'codec', 'asterisk_pbx',
         'a01yt_references', 'safety_privacy', 'legacy_regression')

class Status(str, Enum):
    PASS = 'PASS'
    FAIL = 'FAIL'
    HOLD = 'HOLD'

@dataclass(frozen=True)
class Gate:
    name: str
    status: Status
    checks: tuple[str,...]
    metrics: dict
    evidence: tuple[dict,...]
    run_at_utc: str
    physical: bool = False

    def __post_init__(self):
        if self.name not in GATES: raise ValueError('unknown gate')
        if not isinstance(self.status, Status): raise TypeError('invalid status')
        if self.status is Status.PASS and not self.evidence:
            raise ValueError('PASS requires inspectable evidence')
        if self.name != 'legacy_regression' and self.status is Status.PASS and not self.physical:
            raise ValueError('physical PASS requires real-world evidence')

    def to_dict(self):
        d = asdict(self)
        d['status'] = self.status.value
        return d


def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')

def hash_file(path: Path) -> str:
    digest = sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def evidence_ref(path: Path, *, label: str = 'local_file') -> dict:
    if not path.is_file(): raise FileNotFoundError(str(path))
    return {'path': str(path.resolve()), 'sha256':hash_file(path), 'bytes':path.stat().st_size,'label':label}

def save_gate(folder: Path, gate: Gate) -> Path:
    folder.mkdir(parents=True,exist_ok=True)
    path = folder / f'{gate.name}.json'
    path.write_text(json.dumps(gate.to_dict(),ensure_ascii=False,indent=2,sort_keys=True)+'\n', encoding='utf-8')
    return path

def load_gate(folder: Path, name: str) -> Gate:
    path = folder / f'{name}.json'
    if not path.is_file():
        return Gate(name,Status.HOLD,('no_evidence_submitted',),{},(),now())
    raw = json.loads(path.read_text(encoding='utf-8'))
    if raw.get('name')!=name: raise ValueError('gate identity mismatch')
    gate=Gate(name,Status(raw['status']),tuple(raw['checks']),raw['metrics'],
              tuple(raw['evidence']),raw['run_at_utc'],raw.get('physical',False))
    if gate.status is Status.PASS:
        for item in gate.evidence:
            p=Path(item['path'])
            if not p.is_file() or p.stat().st_size!=item['bytes'] or hash_file(p)!=item['sha256']:
                raise ValueError('evidence damaged: '+name)
    return gate

def summary(folder:Path)->dict:
    gates=[]
    for name in GATES:
        try:gate=load_gate(folder,name)
        except (OSError,ValueError,KeyError,TypeError) as e:
            gate=Gate(name,Status.FAIL,('evidence_invalid',str(e)[:120]),{},(),now())
        gates.append(gate.to_dict())
    status= ('FAIL' if any(g['status']=='FAIL' for g in gates)
             else 'PASS' if all(g['status']=='PASS' for g in gates) else 'HOLD')
    return {'schema_version':'m11-acceptance-1','overall':status,
            'production_ready':False,  # physical acceptance != production security certification
            'gates':gates,'created_utc':now()}


def write_summary(folder:Path, output:Path):
    result=summary(folder)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


def wav_info(path:Path)->dict:
    with wave.open(str(path),'rb') as wav:
        if wav.getnchannels()!=1 or wav.getsampwidth()!=2:raise ValueError('16-bit mono PCM WAV required')
        frames=wav.getnframes(); rate=wav.getframerate()
        if frames<1 or rate not in (8000,16000,48000):raise ValueError('invalid WAV length/rate')
        return {'rate':rate,'frames':frames,'duration_seconds':frames/rate}


def norm_words(s: str)->list[str]:
    return re.findall(r'[\w]+',unicodedata.normalize('NFC',s).replace('I','ı').replace('İ','i').lower(),flags=re.UNICODE)

def distance(a:list,b:list)->int:
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        cur=[i]
        for j,y in enumerate(b,1):
            cur.append(min(prev[j]+1,cur[-1]+1,prev[j-1]+(x!=y)))
        prev=cur
    return prev[-1]

def error_rates(pairs:Iterable[tuple[str,str]])->dict:
    wd=wn=cd=cn=0
    for expected,actual in pairs:
        gold=norm_words(expected);hyp=norm_words(actual)
        wd+=distance(gold,hyp);wn+=len(gold)
        g=''.join(gold);h=''.join(hyp)
        cd+=distance(list(g),list(h));cn+=len(g)
    if not wn or not cn:raise ValueError('nonempty reference required')
    return {'wer':round(wd/wn,6),'cer':round(cd/cn,6),
            'word_errors':wd,'reference_words':wn,
            'char_errors':cd,'reference_chars':cn}


def validate_pbx_trace(trace:list[dict])->dict:
    """Asterisk real-trace gate. QUEUE_DRAINED is not proof of acoustic stop.

    Requires an independently captured MEDIA_START and physical interruption
    measurement, aligned to the same channel and ordered flush commands.
    """
    if not trace or any(not isinstance(x,dict) for x in trace):
        raise ValueError('nonempty structured trace required')
    if any(x.get('provenance')!='asterisk_live' or x.get('mock') is not False for x in trace):
        raise ValueError('fake or unproven trace')
    chan={x.get('channel_id') for x in trace}
    if len(chan)!=1 or not next(iter(chan)):raise ValueError('mixed/invalid channels')
    times=[x.get('mono_ns') for x in trace]
    if any(type(v)!=int or v<0 for v in times) or times!=sorted(times) or len(set(times))!=len(times):
        raise ValueError('trace must be strictly ordered')
    events=[x.get('event') for x in trace]
    required=('MEDIA_START','REPORT_QUEUE_DRAINED','FLUSH_MEDIA','QUEUE_DRAINED','HANGUP')
    if any(events.count(e)!=1 for e in required):raise ValueError('missing or duplicate PBX event')
    indices=[events.index(e) for e in required]
    if indices!=sorted(indices):raise ValueError('invalid flush event order')
    media=trace[events.index('MEDIA_START')]
    if media.get('codec') not in ('ulaw','alaw','slin8','slin16','g722'):
        raise ValueError('invalid live codec')
    if media.get('ptime_ms')!=20:raise ValueError('20 ms packetization not evidenced')
    interruption=next((x for x in trace if x.get('event')=='MEASURED_INTERRUPTION'),None)
    if not interruption:raise ValueError('physical interruption measurement absent')
    measured=interruption.get('heard_old_audio_ms_after_speech_start')
    if type(measured) not in (int,float) or measured<0 or measured>30000:
        raise ValueError('invalid measured interruption')
    return {'channel_id':next(iter(chan)),'codec':media['codec'],
            'heard_old_audio_ms_after_speech_start':measured,
            'queue_drained_observed':True,'pass_target_ms':400,
            'latency_target_met':measured<=400}


def validate_voice_reviews(measurements:dict,reviews:list[dict],*,expected_cases:int=320)->dict:
    """Review a fully generated A/B corpus; no AI guess or mock audio allowed."""
    if measurements.get('mode')!='full' or measurements.get('blocked') or measurements.get('failed'):
        raise ValueError('not a fully available 320-pair physical corpus')
    rows=measurements.get('rows') or []
    cases={}
    for row in rows:
        identifier=row['id']
        if row.get('variant') not in ('raw','prepared') or row['variant'] in cases.setdefault(identifier,{}):
            raise ValueError('invalid or duplicate TTS variant')
        if hash_file(Path(row['wav']))!=row['sha256'] or wav_info(Path(row['wav']))['rate']!=48000:
            raise ValueError('audio fingerprint/rate mismatch')
        cases[identifier][row['variant']]=row
    if len(cases)!=expected_cases or any(len(v)!=2 for v in cases.values()) or len(reviews)!=expected_cases:
        raise ValueError('exactly expected complete A/B comparisons required')
    seen=set(); identity_failures=[];pronunciation_failures=[]
    for r in reviews:
        cid=r.get('case_id')
        if cid not in cases or cid in seen:raise ValueError('unknown or duplicate case in review')
        seen.add(cid)
        if (r.get('raw_sha256')!=cases[cid]['raw']['sha256'] or
                r.get('prepared_sha256')!=cases[cid]['prepared']['sha256'] or
                not r.get('reviewer') or not r.get('reviewed_at_utc') or
                len(r.get('notes') or '')<10):
            raise ValueError('unattributed or mismatched human review')
        if type(r.get('leyla_identity_pass')) is not bool or type(r.get('prepared_pronunciation_pass')) is not bool:
            raise ValueError('explicit human bool decisions required')
        if not r['leyla_identity_pass']:identity_failures.append(cid)
        if not r['prepared_pronunciation_pass']:pronunciation_failures.append(cid)
    return {'reviewed_cases':expected_cases,'identity_failures':identity_failures,
            'pronunciation_failures':pronunciation_failures,
            'all_pass':not identity_failures and not pronunciation_failures}
