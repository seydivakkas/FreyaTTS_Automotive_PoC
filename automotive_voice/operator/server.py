"""Loopback-only HTTP API for an explicitly synthetic operator console.

Server is not an authentication boundary for untrusted users; Windows-first local
single-operator development only. Does not expose raw transcripts or recordings.
"""
from __future__ import annotations
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import secrets
import threading
from urllib.parse import urlsplit
from .runtime import ConsoleRuntime
from .review_store import ReviewError

STATIC={'/':'index.html','/index.html':'index.html','/app.css':'app.css','/app.js':'app.js'}
MIME={'index.html':'text/html; charset=utf-8','app.css':'text/css; charset=utf-8',
      'app.js':'application/javascript; charset=utf-8'}

class ConsoleHTTP:
    def __init__(self,runtime:ConsoleRuntime,host:str='127.0.0.1',port:int=8765):
        if host!='127.0.0.1':raise ValueError('M08 must listen on 127.0.0.1 only')
        self.runtime=runtime
        self.csrf=secrets.token_urlsafe(32)
        self.loop=asyncio.new_event_loop()
        self.thread=threading.Thread(target=self.loop.run_forever,daemon=True)
        self.thread.start()
        self.call(self.runtime.initialize())
        self.http=ThreadingHTTPServer((host,port),self._handler())
        self.http.daemon_threads=True
        self.host=host
        self.port=self.http.server_address[1]

    def call(self,coro):
        try:return asyncio.run_coroutine_threadsafe(coro,self.loop).result(timeout=10)
        except FutureTimeout as exc:raise RuntimeError('operator_action_timeout') from exc

    def _handler(self):
        outer=self
        class Handler(BaseHTTPRequestHandler):
            server_version='Freya-M08-Local/0.8'
            sys_version=''
            def log_message(self,fmt,*args):
                # Suppress potential sensitive request payloads and URL parameters.
                return
            def _security_headers(self):
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('X-Frame-Options','DENY')
                self.send_header('Referrer-Policy','no-referrer')
                self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            def _respond(self,status,body,content_type='application/json; charset=utf-8'):
                blob=(json.dumps(body,ensure_ascii=False,sort_keys=True).encode('utf-8')
                      if not isinstance(body,bytes) else body)
                self.send_response(status)
                self._security_headers()
                self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(len(blob)))
                self.end_headers()
                try:self.wfile.write(blob)
                except (ConnectionAbortedError,BrokenPipeError):pass
            def _same_host(self):
                host=self.headers.get('Host','')
                return host in (f'127.0.0.1:{outer.port}',f'localhost:{outer.port}')
            def _route(self):return urlsplit(self.path).path
            def _drain(self):
                try:
                    ln=int(self.headers.get('Content-Length','0'))
                    if 0<ln<=65536:self.rfile.read(ln)
                except Exception:pass
            def do_GET(self):
                if not self._same_host():return self._respond(403,{'error':'invalid_host'})
                path=self._route()
                if path=='/api/bootstrap':
                    return self._respond(200,{'csrf':outer.csrf,'version':'M09-v1','mock_only':True})
                if path=='/api/snapshot':
                    try:return self._respond(200,outer.call(outer.runtime.snapshot()))
                    except Exception:return self._respond(500,{'error':'snapshot_unavailable'})
                name=STATIC.get(path)
                if name is None:return self._respond(404,{'error':'not_found'})
                src=files('automotive_voice.operator').joinpath('static',name)
                return self._respond(200,src.read_bytes(),MIME[name])
            def do_POST(self):
                if not self._same_host():
                    self._drain()
                    return self._respond(403,{'error':'invalid_host'})
                origin=self.headers.get('Origin')
                if origin is not None and origin!=f'http://{self.headers.get("Host")}' :
                    self._drain()
                    return self._respond(403,{'error':'invalid_origin'})
                if self.headers.get('X-Console-CSRF')!=outer.csrf:
                    self._drain()
                    return self._respond(403,{'error':'csrf_required'})
                if self._route()!='/api/action':
                    self._drain()
                    return self._respond(404,{'error':'not_found'})
                if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
                    self._drain()
                    return self._respond(415,{'error':'json_required'})
                try:
                    length=int(self.headers.get('Content-Length','-1'))
                except ValueError:length=-1
                if length<2 or length>4096:return self._respond(413,{'error':'invalid_body_size'})
                try:
                    payload=json.loads(self.rfile.read(length))
                    if not isinstance(payload,dict):raise ValueError('object_required')
                    if any(key not in ('action','session_id','delta_ms','annotation_id','decision','reviewer','reason_code','scenario') for key in payload):
                        raise ValueError('unknown_argument')
                    action=payload.pop('action')
                    if not isinstance(action,str):raise ValueError('invalid_action')
                    result=outer.call(outer.runtime.act(action,payload.pop('session_id',None),**payload))
                    return self._respond(200,{'ok':True,'result':result})
                except (ValueError,ReviewError,TypeError) as exc:
                    return self._respond(422,{'ok':False,'error':str(exc)[:100]})
                except Exception:
                    return self._respond(500,{'ok':False,'error':'action_failed'})
            def do_OPTIONS(self):return self._respond(405,{'error':'not_supported'})
        return Handler

    def serve_forever(self):
        try:self.http.serve_forever(poll_interval=0.15)
        finally:self.shutdown()

    def shutdown(self):
        # call from another thread if serve_forever is running.
        self.http.server_close()
        self.loop.call_soon_threadsafe(self.loop.stop)
        if threading.current_thread()!=self.thread:self.thread.join(timeout=2)
