#!/usr/bin/env python3
"""Spot taker flow by trade size for BTC and ETH: data/spot-flow.json.

Source: Binance public daily aggTrades dumps (data.binance.vision), verified against the
published SHA-256. Each aggregated trade is one taker order's fills at one price, so its
notional approximates order size; a large order that sweeps several prices is split and
therefore counted smaller (big-order totals are conservative).

Net flow per bucket = taker buy notional - taker sell notional (USDT). Only days not yet
in the file are fetched; the last 30 complete UTC days are kept.
"""
import csv
import hashlib
import io
import json
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
UA = {'User-Agent': 'FlowHunt-spot-flow/1.0 (+https://btc.flowhunt.net)'}


def fetch(url, timeout=120):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as response:
        return response.read()


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


def parse_zip(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        with z.open(z.namelist()[0]) as f:
            for rec in csv.reader(io.TextIOWrapper(f, 'utf-8')):
                if not rec or not rec[0].isdigit():
                    continue  # newer dumps carry a header row
                yield float(rec[1]), float(rec[2]), rec[6].strip().lower() in ('true', '1')


def day_flow(symbol, day):
    url = URL.format(s=symbol, d=day)
    blob = fetch(url)
    expected = fetch(url + '.CHECKSUM').decode().split()[0]
    if hashlib.sha256(blob).hexdigest() != expected:
        raise ValueError('checksum mismatch')
    return summarise(parse_zip(blob)), url


def main():
    out_file = ROOT / 'data/spot-flow.json'
    try:
        data = json.loads(out_file.read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault('assets', {})
    today = datetime.now(timezone.utc).date()
    wanted = [(today - timedelta(days=i)).isoformat() for i in range(KEEP_DAYS, 0, -1)]
    errors = []
    for symbol in ('BTC', 'ETH'):
        days = {d['date']: d for d in data['assets'].get(symbol, {}).get('days', [])}
        for day in wanted:
            if day in days:
                continue
            try:
                buckets, url = day_flow(symbol, day)
            except urllib.error.HTTPError as exc:
                if exc.code != 404:  # 404 = not published yet (usually a few hours after UTC midnight)
                    errors.append({'symbol': symbol, 'date': day, 'error': f'HTTP {exc.code}'})
                continue
            except Exception as exc:
                errors.append({'symbol': symbol, 'date': day, 'error': type(exc).__name__})
                continue
            days[day] = {'date': day, 'buckets': buckets, 'url': url,
                         'net': round(sum(b['net'] for b in buckets.values()), 2)}
        kept = sorted((d for k, d in days.items() if k in wanted), key=lambda d: d['date'])
        data['assets'][symbol] = {'days': kept}
    data.update(generatedAt=datetime.now(timezone.utc).isoformat(), errors=errors,
                buckets=[{'key': k, 'label': label} for k, _, _, label in BUCKETS], unit='USDT',
                source='Binance 现货 aggTrades 公开日数据', sourceUrl='https://data.binance.vision/?prefix=data/spot/daily/aggTrades/',
                note='按单笔聚合成交金额分档；跨价位的大单会被拆分，大单金额偏保守。净额 = 主动买入 − 主动卖出。')
    out_file.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    for symbol, a in data['assets'].items():
        last = a['days'][-1] if a['days'] else None
        print(symbol, len(a['days']), 'days; latest', last and last['date'],
              last and {k: round(v['net'] / 1e6, 1) for k, v in last['buckets'].items()})
    print('errors', errors[:5])
    return 0 if all(a['days'] for a in data['assets'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
