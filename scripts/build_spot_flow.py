#!/usr/bin/env python3
"""Spot taker flow by trade size for BTC and ETH: data/spot-flow.json.

Source: Binance public daily aggTrades dumps (data.binance.vision), verified against the
published SHA-256. Each aggregated trade is one taker order's fills at one price, so its
notional approximates order size; a large order that sweeps several prices is split and
therefore counted smaller (big-order totals are conservative).

Net flow per bucket = taker buy notional - taker sell notional (USDT). Missing days are
fetched newest first under a deadline, and the file is saved after every day, so a slow
or throttled run keeps what it finished. The last 30 complete UTC days are kept.
"""
import csv
import hashlib
import io
import json
import math
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://data.binance.vision/data/spot/daily/aggTrades/{s}USDT/{s}USDT-aggTrades-{d}.zip'
BUCKETS = [('lt10k', 0, 1e4, '<1万'), ('10k_100k', 1e4, 1e5, '1–10万'),
           ('100k_1m', 1e5, 1e6, '10–100万'), ('gt1m', 1e6, float('inf'), '>100万')]
KEEP_DAYS = 30
MAX_STALE_DAYS = 3          # the newest day older than this is a failed pipeline, not a quiet one
DEADLINE_SECONDS = 6 * 60   # the observatory job also builds the snapshot within 12 minutes
UA = {'User-Agent': 'FlowHunt-spot-flow/1.0 (+https://btc.flowhunt.net)'}
FLAGS = {'true': True, 'false': False, '1': True, '0': False}


class Throttled(RuntimeError):
    pass


def fetch(url, timeout=120, attempts=3):
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code == 418:
                raise Throttled(f'HTTP {exc.code}') from None
            if exc.code >= 500 and attempt < attempts - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def bucket_of(notional):
    for key, low, high, _ in BUCKETS:
        if low <= notional < high:
            return key
    return BUCKETS[-1][0]


def summarise(rows):
    """rows: iterable of (price, qty, is_buyer_maker). Buyer-maker means the taker sold."""
    out = {key: {'buy': 0.0, 'sell': 0.0, 'trades': 0} for key, *_ in BUCKETS}
    for price, qty, buyer_maker in rows:
        notional = price * qty
        b = out[bucket_of(notional)]
        b['sell' if buyer_maker else 'buy'] += notional
        b['trades'] += 1
    for b in out.values():
        b['net'] = b['buy'] - b['sell']
        b['buy'], b['sell'], b['net'] = round(b['buy'], 2), round(b['sell'], 2), round(b['net'], 2)
    return out


def epoch_ms(value):
    """Dumps use milliseconds historically and microseconds since 2025."""
    t = int(value)
    return t // 1000 if t > 10**14 else t


def parse_zip(blob, day=None):
    """Validated (price, qty, buyer_maker) rows; malformed records raise instead of being skipped."""
    start = end = None
    if day:
        start = int(datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)
        end = start + 86_400_000
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        with z.open(z.namelist()[0]) as f:
            for index, rec in enumerate(csv.reader(io.TextIOWrapper(f, 'utf-8'))):
                if not rec:
                    continue
                if index == 0 and not rec[0].strip().isdigit():
                    continue  # header row of newer dumps
                if len(rec) < 7 or not rec[0].strip().isdigit():
                    raise ValueError(f'malformed record at line {index + 1}')
                price, qty = float(rec[1]), float(rec[2])
                flag = FLAGS.get(rec[6].strip().lower())
                if not (math.isfinite(price) and math.isfinite(qty)) or price <= 0 or qty <= 0 or flag is None:
                    raise ValueError(f'invalid record at line {index + 1}')
                if start is not None and not start <= epoch_ms(rec[5]) < end:
                    raise ValueError(f'trade outside {day} at line {index + 1}')
                yield price, qty, flag


def day_flow(symbol, day):
    url = URL.format(s=symbol, d=day)
    blob = fetch(url)
    expected = fetch(url + '.CHECKSUM').decode().split()[0]
    if hashlib.sha256(blob).hexdigest() != expected:
        raise ValueError('checksum mismatch')
    buckets = summarise(parse_zip(blob, day))
    if not sum(b['trades'] for b in buckets.values()):
        raise ValueError('archive has no trades')
    return buckets, url


def save(path, data):
    data['generatedAt'] = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8')
    tmp.replace(path)


def main():
    started = time.monotonic()
    out_file = ROOT / 'data/spot-flow.json'
    try:
        data = json.loads(out_file.read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault('assets', {})
    data.update(buckets=[{'key': k, 'label': label} for k, _, _, label in BUCKETS], unit='USDT',
                source='Binance 现货 aggTrades 公开日数据', sourceUrl='https://data.binance.vision/?prefix=data/spot/daily/aggTrades/',
                note='按单笔聚合成交金额分档；跨价位的大单会被拆分，大单金额偏保守。净额 = 主动买入 − 主动卖出。')
    today = datetime.now(timezone.utc).date()
    wanted = [(today - timedelta(days=i)).isoformat() for i in range(1, KEEP_DAYS + 1)]  # newest first
    errors, throttled = [], False
    days = {s: {d['date']: d for d in data['assets'].get(s, {}).get('days', []) if d.get('date') in wanted} for s in ('BTC', 'ETH')}
    for day in wanted:
        for symbol in ('BTC', 'ETH'):
            if day in days[symbol] or throttled or time.monotonic() - started > DEADLINE_SECONDS:
                continue
            try:
                buckets, url = day_flow(symbol, day)
            except Throttled as exc:
                errors.append({'symbol': symbol, 'date': day, 'error': str(exc)})
                throttled = True
                continue
            except urllib.error.HTTPError as exc:
                # Only yesterday may legitimately be unpublished; an older 404 is a real gap.
                if not (exc.code == 404 and day == wanted[0]):
                    errors.append({'symbol': symbol, 'date': day, 'error': f'HTTP {exc.code}'})
                continue
            except Exception as exc:
                errors.append({'symbol': symbol, 'date': day, 'error': type(exc).__name__ + ': ' + str(exc)[:80]})
                continue
            days[symbol][day] = {'date': day, 'buckets': buckets, 'url': url,
                                 'net': round(sum(b['net'] for b in buckets.values()), 2)}
            data['assets'][symbol] = {'days': sorted(days[symbol].values(), key=lambda d: d['date'])}
            data['errors'] = errors
            save(out_file, data)  # checkpoint: finished days survive a timeout later in the run
    for symbol in ('BTC', 'ETH'):
        data['assets'][symbol] = {'days': sorted(days[symbol].values(), key=lambda d: d['date'])}
    data['errors'] = errors
    save(out_file, data)
    status = 0
    for symbol, a in data['assets'].items():
        last = a['days'][-1]['date'] if a['days'] else None
        age = (today - date.fromisoformat(last)).days if last else None
        print(symbol, len(a['days']), 'days; latest', last)
        if age is None or age > MAX_STALE_DAYS:
            print(f'::error::{symbol} spot flow is {age} days old')
            status = 1
    print('errors', errors[:5])
    return status


if __name__ == '__main__':
    raise SystemExit(main())
