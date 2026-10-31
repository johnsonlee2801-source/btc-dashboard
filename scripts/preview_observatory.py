#!/usr/bin/env python3
"""Loopback-only preview for the static site, including a public quote proxy.

No accounts, keys, paid endpoints or production changes. Hidden paths, Python
sources and arbitrary files outside the public site are not served.
"""
import argparse
import json
import http.server
import threading
import time
import urllib.parse
from datetime import datetime,timezone
from pathlib import Path
from build_observatory import get_json,number

ROOT=Path(__file__).resolve().parents[1]
REWRITES={'/positioning-radar':'/positioning-radar.html','/':'/index.html','/eth':'/eth.html','/halving':'/halving.html','/distribution-radar':'/distribution-radar.html'}
CACHE={}
LOCK=threading.Lock()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT),**kwargs)

    def do_GET(self):
        parsed=urllib.parse.urlsplit(self.path)
        if parsed.path=='/api/ticker':
            symbol=urllib.parse.parse_qs(parsed.query).get('symbol',['BTC'])[0].upper()
            if symbol not in ('BTC','ETH'):
                self.send_error(400);return
            try:
                with LOCK:
                    cached=CACHE.get(symbol)
                    if not cached or time.monotonic()-cached[0]>10:
                        raw=get_json(f'https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}USDT')
                        price=number(raw.get('lastPrice'))
                        if not price or price<=0:raise ValueError('invalid public quote')
                        data={'symbol':symbol,'price':price,'change24h':number(raw.get('priceChangePercent')),
                              'source':'Binance','asOf':datetime.now(timezone.utc).isoformat()}
                        CACHE[symbol]=(time.monotonic(),data)
                    else:data=cached[1]
                body=json.dumps(data,allow_nan=False).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
            except Exception:
                self.send_error(503,'Public quote unavailable; page retains its dated daily close')
            return
        decoded=urllib.parse.unquote(parsed.path)
        if any(part.startswith('.') for part in decoded.split('/') if part):
            self.send_error(403);return
        self.path=REWRITES.get(decoded,decoded)
        candidate=(ROOT/self.path.lstrip('/')).resolve()
        try:candidate.relative_to(ROOT)
        except ValueError:self.send_error(403);return
        if candidate.suffix.lower() not in ('.html','.css','.js','.json','.svg','.png','.jpg','.ico','.webp','.xml','.txt'):
            self.send_error(404);return
        super().do_GET()


class PreviewServer(http.server.ThreadingHTTPServer):
    request_queue_size=128


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    server=PreviewServer(('127.0.0.1',args.port),Handler)
    print(f'Local preview: http://127.0.0.1:{server.server_address[1]}/',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
