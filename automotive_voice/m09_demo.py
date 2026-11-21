"""M09 offline synthetic acceptance: python -m automotive_voice.m09_demo."""
import asyncio
import json
from automotive_voice.e2e.runner import run_catalog

def main():
    report=asyncio.run(run_catalog())
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))
    if report['failed']:raise SystemExit(1)
if __name__=='__main__':main()
