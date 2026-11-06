"""M10 offline resilience run: all M09 policies with durable M01 and safer TTS presentation.

No GPU, socket, STT, Freya model, PBX or audio bytes. Use --output for report.
"""
import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from automotive_voice.e2e import ScenarioRunner, SCENARIOS
from automotive_voice.resilience.durable import DurableJournal, DurableSessionManager
from automotive_voice.core.event_bus import EventBus

async def run():
    cases=[]
    for name in SCENARIOS:
        with tempfile.TemporaryDirectory(prefix='m10_sim_') as d:
            journal=DurableJournal(Path(d)/'events.sqlite3')
            try:
                result=await ScenarioRunner(m10_presentation=True,durable_journal=journal).run(name)
                blocked=sum(e.get('step')=='prosody' and e.get('outcome')=='review_required' for e in result.trace)
                cases.append({'scenario':name,'passed':bool(result.passed),
                              'speech_review_blocked':blocked,
                              'durable_outbox':journal.counts()['pending_outbox']})
            finally: journal.close()
    with tempfile.TemporaryDirectory(prefix='m10_recovery_') as d:
        path=Path(d)/'events.sqlite3';j=DurableJournal(path)
        try:
            m=DurableSessionManager(EventBus(),j)
            await m.restore_fail_closed();await m.create('m10-restart-check')
            await m.start('m10-restart-check')
        finally:j.close()
        j=DurableJournal(path)
        try:
            restored=DurableSessionManager(EventBus(),j)
            failclosed=await restored.restore_fail_closed()
            snap=await restored.snapshot('m10-restart-check')
            recovery={'forced_terminal_count':failclosed,'terminal_state':snap.state.value,
                      'manual_reconciliation_required':True}
        finally:j.close()
    return {'mode':'M10_DRY_RUN','passed':sum(c['passed'] for c in cases),
            'total':len(cases),'speech_review_blocked':sum(c['speech_review_blocked'] for c in cases),
            'real_network_connections':0,'audio_bytes':0,'production_ready':False,
            'recovery':recovery,'scenarios':cases}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default=None,help='Write UTF-8 JSON report to local file')
    a=parser.parse_args()
    report=asyncio.run(run())
    if a.output:
        out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report['passed']==report['total'] and
                     report['recovery']['terminal_state']=='FAILED' else 1)
if __name__=='__main__':main()
