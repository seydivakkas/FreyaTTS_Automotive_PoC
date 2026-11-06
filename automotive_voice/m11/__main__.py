"""M11 local acceptance CLI. Optional real actions require --enable-physical.

Never installs packages, downloads media or opens a phone call automatically.
"""
from __future__ import annotations
import argparse, json, os, platform, shutil, subprocess, sys, time, wave, csv
from hashlib import sha256
from pathlib import Path
from .acceptance import (Gate,Status,now,evidence_ref,hash_file,save_gate,
                         summary,write_summary,wav_info,error_rates,validate_pbx_trace,validate_voice_reviews)

PROJECT=Path(__file__).resolve().parents[2]
DEFAULT_FOLDER=PROJECT/'data'/'m11'/'results'

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def gate(folder,name,status,checks,metrics=None,evidence=(),physical=False):
    val=Gate(name,Status(status),tuple(checks),metrics or {},tuple(evidence),now(),physical)
    path=save_gate(folder,val)
    print(f'{name}: {status} | '+', '.join(checks)+f' | {path}')
    return status

def preflight(args):
    checks=[];details={'system':platform.platform(), 'python':platform.python_version(),
                       'windows':sys.platform=='win32','ffmpeg_available':bool(shutil.which('ffmpeg'))}
    try:
        import torch
        details['torch_version']=torch.__version__
        details['cuda_available']=bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            details['gpu']=torch.cuda.get_device_name(0)
            details['gpu_vram_bytes']=torch.cuda.get_device_properties(0).total_memory
    except ImportError:details['cuda_available']=False
    model=Path(args.model_dir) if args.model_dir else None
    details['model_files_present']=bool(model and all((model/f).is_file() for f in ('config.json','model.safetensors')))
    if details['model_files_present']:
        details['model_sha256']=hash_file(model/'model.safetensors')
        details['model_config_sha256']=hash_file(model/'config.json')
    checkout=Path(args.freya_checkout) if args.freya_checkout else None
    details['freya_checkout_present']=bool(checkout and (checkout/'freyatts'/'pipeline.py').is_file())
    details['official_model_id']='freyavoice/freya-tts'
    checks.extend(k for k,ok in [('windows_11',sys.platform=='win32'),
               ('python_3_11',sys.version_info[:2]==(3,11)),
               ('ffmpeg',details['ffmpeg_available']),
               ('cuda_gpu',details['cuda_available']),
               ('local_freya_model',details['model_files_present']),
               ('local_freya_checkout',details['freya_checkout_present'])] if not ok)
    out=args.folder/'preflight_details.json';dump(out,details)
    # Edge/driver real testing is a separate manual gate. Preflight never establishes it.
    return gate(args.folder,'windows_edge','HOLD',checks or ['edge_and_audio_device_manual_checks_required'],
                details,(evidence_ref(out),))

def _sample_cases(args):
    cases=json.loads((PROJECT/'data'/'fixtures'/'legacy_320_cases.json').read_text(encoding='utf-8'))
    assert len(cases)==320, 'golden corpus unexpectedly changed'
    if args.mode=='smoke':
        # Capture all smoke data but cap to 12 for GPU warm-up.
        return [c for c in cases if c['tier']=='smoke'][:12]
    return cases

def tts(args):
    if not args.enable_physical:
        return gate(args.folder,'freya_leyla','HOLD',['physical_inference_requires_explicit_enable_flag'])
    model=Path(args.model_dir)
    checkout=Path(args.freya_checkout)
    for f in ('config.json','model.safetensors'):
        if not (model/f).is_file():raise ValueError('local model missing '+f)
    if not (checkout/'freyatts'/'pipeline.py').is_file():raise ValueError('Freya source checkout missing')
    if not args.allow_cpu:
        import torch
        if not torch.cuda.is_available():
            return gate(args.folder,'freya_leyla','HOLD',['cuda_not_available'])
    # Explicit local checkout avoids accidentally importing another model's code.
    sys.path.insert(0,str(checkout.resolve()))
    import numpy as np
    from freyatts import FreyaTTS
    from automotive_voice.nlp.normalizer import TurkishAutomotiveNormalizer
    from automotive_voice.nlp.a01yt_adapter import A01YTReadOnlyAdapter
    lex=A01YTReadOnlyAdapter(PROJECT/'data'/'a01yt'/'a01yt_v05_readonly.sqlite3').load()
    normalizer=TurkishAutomotiveNormalizer(lex,PROJECT/'data'/'a01yt'/'freya_char_vocab.json')
    runtime=FreyaTTS.from_pretrained(str(model.resolve()), device='cpu' if args.allow_cpu else 'cuda')
    cases=_sample_cases(args)
    rows=[];blocked=[];failed=[]
    model_sha=hash_file(model/'model.safetensors')
    outdir=args.output_dir
    outdir.mkdir(parents=True,exist_ok=True)
    for case in cases:
        normalized=normalizer.normalize(case['text'])
        if normalized.review_required:
            blocked.append({'id':case['id'],'warnings':normalized.warnings,
                            'unsupported_chars':normalized.unsupported_chars})
            continue
        for version,spoken in (('raw',case['text']),('prepared',normalized.spoken_text)):
            t0=time.perf_counter()
            try:
                wav=runtime.synthesize(spoken,steps=args.steps,seed=args.seed)
            except (ValueError,RuntimeError,KeyError) as exc:
                failed.append({'id':case['id'],'variant':version,'error_type':type(exc).__name__})
                continue
            elapsed=time.perf_counter()-t0
            arr=np.asarray(wav,dtype=np.float32)
            if arr.ndim!=1 or arr.size==0 or not np.isfinite(arr).all():raise ValueError('bad generated audio')
            arr=np.clip(arr,-1,1)
            out=outdir/(case['id']+'_'+version+'.wav')
            pcm=(arr*32767).astype('<i2').tobytes()
            with wave.open(str(out),'wb') as h:
                h.setnchannels(1);h.setsampwidth(2);h.setframerate(48000);h.writeframes(pcm)
            info=wav_info(out)
            rows.append({'id':case['id'],'variant':version,'wav':str(out.resolve()),
                         'sha256':hash_file(out),'duration_s':round(info['duration_seconds'],4),
                         'inference_s':round(elapsed,4),
                         'rtf':round(elapsed/info['duration_seconds'],4),'seed':args.seed,
                         'steps':args.steps, 'model_sha256':model_sha})
    path=args.folder/'freya_leyla_measurements.json';dump(path,{'mode':args.mode,
         'model_dir':str(model.resolve()),'model_sha256':model_sha,
         'seed':args.seed,'steps':args.steps,'generated':len(rows),'blocked':blocked,'failed':failed,'rows':rows})
    # A/B waveform presence alone cannot demonstrate human-scored voice identity.
    checks=[f'generated_{len(rows)}_waves',f'blocked_{len(blocked)}_cases',f'failed_{len(failed)}_variants',
            'voice_identity_and_pronunciation_human_review_pending']
    return gate(args.folder,'freya_leyla','HOLD',checks,
                {'generated':len(rows),'target_wavs':640,'blocked':len(blocked),'failed':len(failed),'seed':args.seed},
                [evidence_ref(path)],physical=True)

def voice_review(args):
    source=args.folder/'freya_leyla_measurements.json'
    if not source.is_file() or not args.manifest.is_file():
        return gate(args.folder,'freya_leyla','HOLD',['full_corpus_or_human_review_manifest_missing'])
    measurements=json.loads(source.read_text(encoding='utf-8'))
    reviews=[json.loads(x) for x in args.manifest.read_text(encoding='utf-8').splitlines() if x.strip()]
    try:
        verdict=validate_voice_reviews(measurements,reviews)
    except (ValueError,KeyError,OSError) as exc:
        return gate(args.folder,'freya_leyla','FAIL',['voice_review_validation_failed',str(exc)[:100]],
                evidence=(evidence_ref(source),evidence_ref(args.manifest)),physical=True)
    status='PASS' if verdict['all_pass'] else 'FAIL'
    return gate(args.folder,'freya_leyla',status,
                ['all_320_ab_pairs_human_reviewed','wav_hashes_verified',
                 'leyla_voice_and_pronunciation_reviewed'],verdict,
                (evidence_ref(source),evidence_ref(args.manifest)),physical=True)

def stt(args):
    if not args.enable_physical:
        return gate(args.folder,'stt_vad','HOLD',['physical_stt_requires_explicit_enable_flag'])
    if not args.manifest.is_file():return gate(args.folder,'stt_vad','HOLD',['missing_labeled_audio_manifest'])
    try:from faster_whisper import WhisperModel
    except ImportError:return gate(args.folder,'stt_vad','HOLD',['faster_whisper_not_installed'])
    if not args.model_dir.is_dir():return gate(args.folder,'stt_vad','HOLD',['local_stt_model_missing'])
    model=WhisperModel(str(args.model_dir.resolve()),device=args.device,compute_type=args.compute_type,local_files_only=True)
    pairs=[];rows=[]
    for line in args.manifest.read_text(encoding='utf-8').splitlines():
        if not line.strip():continue
        rec=json.loads(line)
        audio=Path(rec['audio_path'])
        info=wav_info(audio)
        if not rec['reference'].strip():raise ValueError('missing human reference')
        segments,meta=model.transcribe(str(audio),language='tr',vad_filter=True,beam_size=5)
        actual=' '.join(x.text.strip() for x in segments)
        pairs.append((rec['reference'],actual))
        rows.append({'audio_sha256':hash_file(audio),'audio_seconds':info['duration_seconds'],
                     'reference':rec['reference'],'transcription':actual})
    metrics=error_rates(pairs)
    path=args.folder/'stt_vad_measurements.json';dump(path,{'metrics':metrics,'samples':rows,
          'vad_acoustic_barge_in_measured':False})
    return gate(args.folder,'stt_vad','HOLD',['stt_wer_cer_measured','real_vad_barge_in_unmeasured'],
                {**metrics,'recordings':len(rows)},[evidence_ref(path)],physical=True)

def codec(args):
    if not args.enable_physical:
        return gate(args.folder,'codec','HOLD',['physical_codec_requires_explicit_enable_flag'])
    if not args.input_wav or not args.input_wav.is_file():
        return gate(args.folder,'codec','HOLD',['real_input_wav_missing'])
    if not shutil.which('ffmpeg'):return gate(args.folder,'codec','HOLD',['ffmpeg_missing'])
    inp=wav_info(args.input_wav)
    out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    cases=[]
    for name,fmt,rate,bps in [('slin16','s16le',16000,2),('slin8','s16le',8000,2),
                               ('ulaw','mulaw',8000,1),('alaw','alaw',8000,1)]:
        path=out/(name+'.raw')
        proc=subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y',
                     '-i',str(args.input_wav),'-ac','1','-ar',str(rate),'-f',fmt,str(path)],
                     capture_output=True,text=True,timeout=90)
        if proc.returncode: raise RuntimeError('ffmpeg: '+proc.stderr[:300])
        frame=rate*20//1000*bps
        nbytes=path.stat().st_size
        if nbytes<=0: raise ValueError('empty codec output')
        frames=nbytes//frame;leftover=nbytes%frame
        cases.append({'codec':name,'rate':rate,'frame_ms':20,'payload_bytes_per_frame':frame,
              'full_frames':frames,'tail_bytes':leftover,'hash':hash_file(path),
              'duration_seconds':round(nbytes/(rate*bps),4)})
    report=args.folder/'codec_measurements.json';dump(report,{'source':evidence_ref(args.input_wav),
              'cases':cases,'input_duration_s':inp['duration_seconds']})
    # Encoding a file is NOT a live 20ms pacing / roundtrip phone validation.
    return gate(args.folder,'codec','HOLD',['ffmpeg_encoding_measured',
            'real_transport_playout_and_pacing_pending'],{'codecs':len(cases)},[evidence_ref(report)],physical=True)

def youtube(args):
    if not args.manifest.is_file():return gate(args.folder,'a01yt_references','HOLD',['real_reference_manifest_missing'])
    sources={row['id'] for row in csv.DictReader((PROJECT/'data'/'a01yt'/'sources_verbal_permission_v05.csv').open(encoding='utf-8-sig',newline=''))}
    rows=[];errors=[];unique=set()
    for i,line in enumerate(args.manifest.read_text(encoding='utf-8').splitlines(),1):
        if not line.strip():continue
        try:
            r=json.loads(line)
            if r['source_id'] not in sources:raise ValueError('unrecognized source')
            if r.get('review_status')!='approved' or not r.get('reviewer') or not r.get('reviewed_at_utc'):
                raise ValueError('human approval missing')
            if r.get('origin')!='direct_from_rights_holder':raise ValueError('origin is not direct')
            if not (isinstance(r.get('start_ms'),int) and isinstance(r.get('end_ms'),int)
                    and 0<=r['start_ms']<r['end_ms']):raise ValueError('timecode invalid')
            if not r.get('transcript') or not r.get('spoken_tr') or not r.get('canonical'):
                raise ValueError('annotation incomplete')
            path=Path(r['audio_path'])
            info=wav_info(path)
            if r['clip_sha256'].lower()!=hash_file(path):raise ValueError('clip checksum mismatch')
            if r['end_ms']-r['start_ms']>info['duration_seconds']*1000+250:
                raise ValueError('time range exceeds clip')
            rows.append({'source_id':r['source_id'],'canonical':r['canonical'],
                   'clip_sha256':r['clip_sha256'],'reviewer':r['reviewer']})
            unique.add(r['canonical'].casefold())
        except (KeyError,OSError,ValueError,TypeError) as exc:
            errors.append(f'line_{i}_{str(exc)[:65]}')
    path=args.folder/'a01yt_reference_audit.json';dump(path,{'audited_count':len(rows),
                     'unique_targets':len(unique),'errors':errors,'rows':rows})
    status='FAIL' if errors else 'PASS' if len(unique)>=50 else 'HOLD'
    checks=['real_clips_approved_'+str(len(rows)),'unique_targets_'+str(len(unique))]
    if errors:checks+=errors[:5]
    if len(unique)<50:checks+=['initial_50_not_complete']
    return gate(args.folder,'a01yt_references',status,checks,{'approved_clips':len(rows),
             'unique_targets':len(unique)},[evidence_ref(path),evidence_ref(args.manifest)],physical=True)

def pbx(args):
    if not args.trace.is_file():return gate(args.folder,'asterisk_pbx','HOLD',['no_real_asterisk_trace'])
    if not args.enable_physical:
        return gate(args.folder,'asterisk_pbx','HOLD',['physical_pbx_requires_explicit_enable_flag'])
    if not args.capture_file or not args.capture_file.is_file() or not args.observer_record or not args.observer_record.is_file():
        return gate(args.folder,'asterisk_pbx','HOLD',['independent_live_capture_and_observer_record_required'])
    try:
        trace=[json.loads(x) for x in args.trace.read_text(encoding='utf-8').splitlines() if x.strip()]
        details=validate_pbx_trace(trace)
        # Independent raw capture and observer record are required in addition to an exported event list.
        capture=args.capture_file.read_text(encoding='utf-8',errors='replace')
        if not all(token in capture for token in ('MEDIA_START','FLUSH_MEDIA','QUEUE_DRAINED',details['channel_id'])):
            raise ValueError('raw PBX capture does not corroborate trace')
        observer=json.loads(args.observer_record.read_text(encoding='utf-8'))
        if (observer.get('channel_id')!=details['channel_id'] or not observer.get('observer')
              or observer.get('mock') is not False
              or type(observer.get('heard_old_audio_ms_after_speech_start')) not in (int,float)
              or abs(observer['heard_old_audio_ms_after_speech_start']-details['heard_old_audio_ms_after_speech_start'])>20):
            raise ValueError('missing or conflicting independent listener evidence')
        import math
        samples=observer.get('measurements_ms')
        if (not isinstance(samples,list) or len(samples)<30 or
            any(type(v) not in (int,float) or v<0 or v>30000 for v in samples)):
            return gate(args.folder,'asterisk_pbx','HOLD',['at_least_30_independent_real_interruptions_required'],
                        {'observed':len(samples) if isinstance(samples,list) else 0},
                        [evidence_ref(args.trace),evidence_ref(args.capture_file),evidence_ref(args.observer_record)],physical=True)
        p95=sorted(samples)[math.ceil(0.95*len(samples))-1]
        details['interruptions']=len(samples)
        details['p95_old_audio_ms']=p95
        status='PASS' if p95<=400 and details['latency_target_met'] else 'FAIL'
        checks=['same_channel_and_ordered_queue_drain_verified',
                'raw_capture_and_independent_observer_correlated']
    except (ValueError,KeyError,TypeError) as exc:
        status='FAIL';details={};checks=['trace_invalid',str(exc)[:120]]
    return gate(args.folder,'asterisk_pbx',status,checks,details,
                [evidence_ref(args.trace),evidence_ref(args.capture_file),evidence_ref(args.observer_record)],physical=True)

def manual(args):
    # Reviewer-attested physical gates. Other gates require automated data contracts.
    allowed={'windows_edge','safety_privacy'}
    if args.gate not in allowed:raise ValueError('manual override forbidden for this gate')
    if not args.enable_physical:raise ValueError('explicit real-world reviewer opt-in required')
    if not args.reviewer.strip() or len(args.reviewer)<3 or len(args.statement.strip())<20:
        raise ValueError('reviewer and substantive observation required')
    if not args.evidence.is_file() or args.evidence.stat().st_size==0:
        raise ValueError('real evidence file required')
    check={'reviewer':args.reviewer.strip(),'observation':args.statement.strip(),
           'observed_at_utc':now(),'evidence_sha256':hash_file(args.evidence)}
    out=args.folder/(args.gate+'_attestation.json')
    dump(out,check)
    return gate(args.folder,args.gate,args.status,
                ('human_reviewed_physical_evidence',),check,
                (evidence_ref(out),evidence_ref(args.evidence)),physical=True)

def legacy(args):
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-q'],
                          cwd=PROJECT,env={**os.environ,'PYTHONPATH':str(PROJECT/'src')},
                          capture_output=True,text=True,timeout=90)
    path=args.folder/'regression_output.txt';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    fixture=PROJECT/'data'/'fixtures'/'legacy_320_cases.json'
    count=len(json.loads(fixture.read_text(encoding='utf-8')))
    status='PASS' if result.returncode==0 and count==320 else 'FAIL'
    return gate(args.folder,'legacy_regression',status,
                ['unittest_exit_'+str(result.returncode),'golden_count_'+str(count)],
                {'golden_count':count,'legacy_suite_exit':result.returncode},
                [evidence_ref(path),evidence_ref(fixture)])

def report(args):
    result=write_summary(args.folder,args.output)
    from .html_report import create_html
    create_html(result,args.output.with_suffix('.html'))
    print('M11 PHYSICAL ACCEPTANCE:',result['overall'], 'production_ready:',result['production_ready'])
    for g in result['gates']:
        print(' ',g['name'],g['status'],','.join(g['checks']))
    print('Report:',args.output,'HTML:',args.output.with_suffix('.html'))
    return result['overall']

def main():
    parser=argparse.ArgumentParser(description='M11 physical acceptance. NO real service action without explicit opt-in.')
    parser.add_argument('--folder',type=Path,default=DEFAULT_FOLDER)
    commands=parser.add_subparsers(dest='cmd',required=True)
    p=commands.add_parser('preflight');p.add_argument('--model-dir');p.add_argument('--freya-checkout')
    p=commands.add_parser('tts');p.add_argument('--enable-physical',action='store_true')
    p.add_argument('--allow-cpu',action='store_true');p.add_argument('--model-dir',type=Path,required=True)
    p.add_argument('--freya-checkout',type=Path,required=True);p.add_argument('--output-dir',type=Path,default=PROJECT/'data'/'m11'/'audio')
    p.add_argument('--mode',choices=['smoke','full'],default='smoke')
    p.add_argument('--steps',type=int,choices=[16,32,64],default=32);p.add_argument('--seed',type=int,default=9)
    p=commands.add_parser('voice-review');p.add_argument('--manifest',type=Path,required=True)
    p=commands.add_parser('stt');p.add_argument('--enable-physical',action='store_true')
    p.add_argument('--model-dir',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--device',choices=['cuda','cpu'],default='cuda');p.add_argument('--compute-type',default='float16')
    p=commands.add_parser('codec');p.add_argument('--enable-physical',action='store_true')
    p.add_argument('--input-wav',type=Path);p.add_argument('--output-dir',type=Path,default=PROJECT/'data'/'m11'/'codec')
    p=commands.add_parser('a01yt');p.add_argument('--manifest',type=Path,required=True)
    p=commands.add_parser('pbx');p.add_argument('--trace',type=Path,required=True);p.add_argument('--enable-physical',action='store_true')
    p.add_argument('--capture-file',type=Path);p.add_argument('--observer-record',type=Path)
    p=commands.add_parser('manual');p.add_argument('--gate',choices=['windows_edge','safety_privacy'],required=True)
    p.add_argument('--status',choices=['PASS','FAIL','HOLD'],required=True)
    p.add_argument('--enable-physical',action='store_true');p.add_argument('--reviewer',required=True)
    p.add_argument('--statement',required=True);p.add_argument('--evidence',type=Path,required=True)
    commands.add_parser('legacy')
    p=commands.add_parser('report');p.add_argument('--output',type=Path,default=PROJECT/'data'/'m11'/'M11_ACCEPTANCE.json')
    a=parser.parse_args()
    if a.cmd=='preflight':preflight(a)
    elif a.cmd=='tts':tts(a)
    elif a.cmd=='voice-review':voice_review(a)
    elif a.cmd=='stt':stt(a)
    elif a.cmd=='codec':codec(a)
    elif a.cmd=='a01yt':youtube(a)
    elif a.cmd=='pbx':pbx(a)
    elif a.cmd=='manual':manual(a)
    elif a.cmd=='legacy':legacy(a)
    elif a.cmd=='report':report(a)

if __name__=='__main__':main()
