"""Launch M08 offline operator UI: python -m automotive_voice.operator."""
from __future__ import annotations
import argparse
from pathlib import Path
from .runtime import ConsoleRuntime
from .server import ConsoleHTTP

def main():
    parser=argparse.ArgumentParser(description='Freya M08 offline MOCK operator console')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--instance',default=None,help='Writable local review/audit overlay directory')
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[2]
    data=project/'data'
    instance=Path(args.instance).resolve() if args.instance else project/'var'
    app=ConsoleHTTP(ConsoleRuntime(data,instance/'m08_reviews.sqlite3'),port=args.port)
    print(f'Freya M08 MOCK-ONLY local console: http://127.0.0.1:{app.port}',flush=True)
    print('No audio, SIP, external network, model or real booking services.',flush=True)
    try:app.serve_forever()
    except KeyboardInterrupt:app.shutdown()

if __name__=='__main__':main()
