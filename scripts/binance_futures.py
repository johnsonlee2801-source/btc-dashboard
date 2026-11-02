"""Binance USDT-M futures public market data, direct or through the site proxy.

fapi.binance.com answers HTTP 451 to US addresses, which includes every GitHub
Actions runner. When BINANCE_PROXY_URL is set (the workflows point it at
/api/binance-futures, pinned to Singapore) requests are sent there in batches;
otherwise they go direct, which works from most non-US networks.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = 'https://fapi.binance.com'
PROXY = os.environ.get('BINANCE_PROXY_URL', '').strip()
BATCH = 100
USER_AGENT = 'FlowHunt-public-research/1.0'


class SourceError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _post(url, payload, timeout=60):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method='POST',
                                 headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _direct(path, params, timeout=12):
    url = HOST + path + ('?' + urllib.parse.urlencode(params) if params else '')
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': USER_AGENT}),
                                    timeout=timeout) as response:
            return {'status': 200, 'body': json.load(response)}
    except urllib.error.HTTPError as exc:
        return {'status': exc.code, 'error': f'HTTP {exc.code}'}
    except Exception as exc:
        return {'status': 502, 'error': type(exc).__name__}


def fetch_many(requests, pause=0.0):
    """requests: [(path, params)] -> [{'status':int,'body'?:..,'error'?:str}] in order.

    `pause` is the minimum seconds between upstream batches (direct mode: between
    single requests) so a full universe scan stays inside Binance IP weight limits.
    """
    results = []
    if PROXY:
        for start in range(0, len(requests), BATCH):
            chunk = requests[start:start + BATCH]
            began = time.monotonic()
            try:
                reply = _post(PROXY, {'requests': [{'path': p, 'params': q or {}} for p, q in chunk]})
                got = reply.get('results') if isinstance(reply, dict) else None
                if not isinstance(got, list) or len(got) != len(chunk):
                    raise SourceError('proxy returned malformed results')
                results.extend(got)
            except SourceError:
                raise
            except Exception as exc:
                results.extend({'status': 502, 'error': 'proxy ' + type(exc).__name__} for _ in chunk)
            wait = pause - (time.monotonic() - began)
            if wait > 0 and start + BATCH < len(requests):
                time.sleep(wait)
        return results
    for path, params in requests:
        began = time.monotonic()
        results.append(_direct(path, params))
        wait = pause / BATCH - (time.monotonic() - began)
        if wait > 0:
            time.sleep(wait)
    return results


def fetch_one(path, params=None):
    result = fetch_many([(path, params)])[0]
    if result.get('status') != 200:
        raise SourceError(result.get('error') or 'HTTP error', result.get('status'))
    return result['body']
