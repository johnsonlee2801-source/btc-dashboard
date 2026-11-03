"""Binance USDT-M futures public market data, direct or through the site relay.

fapi.binance.com answers HTTP 451 to US addresses, which includes every GitHub
Actions runner. When BINANCE_PROXY_URL is set (the workflows point it at
/api/binance-futures, pinned to Singapore) requests are sent there in batches,
authenticated with BINANCE_PROXY_TOKEN; otherwise they go direct, which works
from most non-US networks.

Throttling (HTTP 429/418) stops the remaining requests: they come back as
explicit "skipped" results in order, so callers never mistake them for data.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = 'https://fapi.binance.com'
PROXY = os.environ.get('BINANCE_PROXY_URL', '').strip()
PROXY_TOKEN = os.environ.get('BINANCE_PROXY_TOKEN', '').strip()
BATCH = 100
# The relay answers within its own 20s batch deadline; leave headroom for transport.
PROXY_TIMEOUT = 45
THROTTLED = (418, 429)
USER_AGENT = 'FlowHunt-public-research/1.0'
OTHER_HOSTS = {'/bapi/apex/v1/public/apex/market/por/address': 'https://www.binance.com'}


class SourceError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _post(url, payload, timeout=PROXY_TIMEOUT):
    body = json.dumps(payload).encode()
    headers = {'Content-Type': 'application/json', 'User-Agent': USER_AGENT}
    if PROXY_TOKEN:
        headers['X-Relay-Token'] = PROXY_TOKEN
    req = urllib.request.Request(url, data=body, method='POST', headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _retry_after(headers):
    try:
        return float(headers.get('Retry-After')) if headers and headers.get('Retry-After') else None
    except (TypeError, ValueError):
        return None


def _direct(path, params, timeout=12):
    url = OTHER_HOSTS.get(path, HOST) + path + ('?' + urllib.parse.urlencode(params) if params else '')
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': USER_AGENT}),
                                    timeout=timeout) as response:
            return {'status': 200, 'body': json.load(response)}
    except urllib.error.HTTPError as exc:
        out = {'status': exc.code, 'error': f'HTTP {exc.code}'}
        retry = _retry_after(exc.headers)
        if retry is not None:
            out['retryAfter'] = retry
        return out
    except Exception as exc:
        return {'status': 502, 'error': type(exc).__name__}


def _normalise(result):
    """One relay result -> a well-formed record; malformed entries become explicit errors."""
    if not isinstance(result, dict) or not isinstance(result.get('status'), int):
        return {'status': 502, 'error': 'malformed relay result'}
    if result['status'] == 200 and 'body' not in result:
        return {'status': 502, 'error': 'relay result without body'}
    if result['status'] != 200 and not isinstance(result.get('error'), str):
        return {**result, 'error': f"HTTP {result['status']}"}
    return result


def _skipped(stop, count):
    note = {'status': stop['status'], 'error': 'skipped after upstream throttling'}
    if stop.get('retryAfter') is not None:
        note['retryAfter'] = stop['retryAfter']
    return [dict(note) for _ in range(count)]


def fetch_many(requests, pause=0.0):
    """requests: [(path, params)] -> [{'status':int,'body'?:..,'error'?:str}] in order.

    `pause` is a pacing budget per batch of BATCH requests: in relay mode the minimum
    seconds between relay calls, in direct mode spread evenly (pause / BATCH seconds
    between single requests). A full radar scan uses pause=32 to stay under Binance's
    1,000 data requests per 5 minutes per IP.
    """
    results = []
    if PROXY:
        for start in range(0, len(requests), BATCH):
            chunk = requests[start:start + BATCH]
            began = time.monotonic()
            try:
                reply = _post(PROXY, {'requests': [{'path': p, 'params': q or {}} for p, q in chunk]})
            except urllib.error.HTTPError as exc:
                # Keep the relay's real status (401 token, 429 throttled, 503 not configured).
                failed = {'status': exc.code, 'error': f'relay HTTP {exc.code}'}
                retry = _retry_after(exc.headers)
                if retry is not None:
                    failed['retryAfter'] = retry
                results.extend(dict(failed) for _ in chunk)
                if exc.code in THROTTLED:
                    results.extend(_skipped(failed, len(requests) - len(results)))
                    return results
                continue
            except Exception as exc:
                results.extend({'status': 502, 'error': 'relay ' + type(exc).__name__} for _ in chunk)
                continue
            got = reply.get('results') if isinstance(reply, dict) else None
            if not isinstance(got, list) or len(got) != len(chunk):
                raise SourceError('relay returned malformed results')
            got = [_normalise(r) for r in got]
            results.extend(got)
            stop = next((r for r in got if r['status'] in THROTTLED), None)
            if stop:
                results.extend(_skipped(stop, len(requests) - len(results)))
                return results
            wait = pause - (time.monotonic() - began)
            if wait > 0 and start + BATCH < len(requests):
                time.sleep(wait)
        return results
    for index, (path, params) in enumerate(requests):
        began = time.monotonic()
        result = _direct(path, params)
        results.append(result)
        if result['status'] in THROTTLED:
            results.extend(_skipped(result, len(requests) - index - 1))
            return results
        wait = pause / BATCH - (time.monotonic() - began)
        if wait > 0:
            time.sleep(wait)
    return results


def fetch_one(path, params=None):
    result = fetch_many([(path, params)])[0]
    if result.get('status') != 200:
        raise SourceError(result.get('error') or 'HTTP error', result.get('status'))
    return result['body']
