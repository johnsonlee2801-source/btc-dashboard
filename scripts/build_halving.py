#!/usr/bin/env python3
"""Halving-cycle data for /halving from Coin Metrics community daily closes (USD).

Writes data/halving-cycles.json: per cycle, the close on halving day, the cycle
peak and the lowest close after it (all closing prices, with day numbers), plus a
5-day sampled curve of price / halving-day price for the comparison chart.

Nothing is written unless every cycle is complete: finite positive closes, no missing
day inside any analysed window, all four halvings present and data no older than
MAX_STALE_DAYS. A failed run leaves the previous file untouched.
"""
import json
import math
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = ('https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=PriceUSD'
       '&frequency=1d&start_time=2012-11-01&page_size=10000')
HALVINGS = [date(2012, 11, 28), date(2016, 7, 9), date(2020, 5, 11), date(2024, 4, 20)]
NEXT_HALVING_ESTIMATE = date(2028, 4, 17)
PEAK_WITHIN, LOW_WITHIN = 730, 1200
MAX_STALE_DAYS = 3


class IncompleteData(ValueError):
    pass


def fetch_closes():
    closes, url = {}, URL
    while url:
        req = urllib.request.Request(url, headers={'User-Agent': 'FlowHunt-halving/1.0 (+https://btc.flowhunt.net)'})
        with urllib.request.urlopen(req, timeout=60) as response:
            page = json.load(response)
        for row in page.get('data', []):
            try:
                value = float(row['PriceUSD'])
                day = date.fromisoformat(row['time'][:10])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(value) and value > 0:
                closes[day] = value
        url = page.get('next_page_url')
    return closes


def cycle_stats(closes, start, end=None):
    """Stats for one cycle; `end` is the next observed halving (None for the running cycle)."""
    days = sorted(d for d in closes if start <= d and (end is None or d < end))
    if not days or days[0] != start:
        return None
    if len(days) != (days[-1] - start).days + 1:
        # A missing day can hide the real peak or low; refuse rather than publish wrong extremes.
        raise IncompleteData(f'cycle {start}: {(days[-1] - start).days + 1 - len(days)} missing days')
    base = closes[start]
    # The bull-market top comes within two years of each halving; the bear-market low follows it
    # before the run-up to the next halving (which would otherwise win the max/min).
    peak = max((d for d in days if (d - start).days <= PEAK_WITHIN), key=lambda d: closes[d])
    after = [d for d in days if peak < d and (d - start).days <= LOW_WITHIN]
    low = min(after, key=lambda d: closes[d]) if after else None
    curve = [[(d - start).days, round(closes[d] / base, 4)] for d in days if (d - start).days % 5 == 0 and (d - start).days <= 1460]
    return {
        'halving': start.isoformat(), 'halvingClose': base,
        'peak': {'date': peak.isoformat(), 'day': (peak - start).days, 'close': closes[peak], 'multiple': closes[peak] / base},
        'lowAfterPeak': None if low is None else {'date': low.isoformat(), 'day': (low - start).days, 'close': closes[low],
                                                  'drawdownPct': (closes[low] / closes[peak] - 1) * 100},
        'lastDate': days[-1].isoformat(), 'lastDay': (days[-1] - start).days, 'lastClose': closes[days[-1]],
        'curve': curve,
    }


def main():
    closes = fetch_closes()
    today = datetime.now(timezone.utc).date()
    if not closes or (today - max(closes)).days > MAX_STALE_DAYS:
        print(f'::error::Coin Metrics data ends {max(closes) if closes else None}; keeping the previous file')
        return 1
    # Closed cycles end at the next actual halving; the running one ends at the newest close.
    bounds = HALVINGS[1:] + [None]
    try:
        cycles = [cycle_stats(closes, s, e) for s, e in zip(HALVINGS, bounds)]
    except IncompleteData as exc:
        print(f'::error::{exc}; keeping the previous file')
        return 1
    if not all(cycles) or any(c['lowAfterPeak'] is None for c in cycles[:3]):
        print('::error::a halving cycle is missing; keeping the previous file')
        return 1
    payload = {'generatedAt': datetime.now(timezone.utc).isoformat(), 'source': 'Coin Metrics Community API (PriceUSD, daily close)',
               'sourceUrl': 'https://docs.coinmetrics.io/', 'nextHalvingEstimate': NEXT_HALVING_ESTIMATE.isoformat(),
               'cycles': cycles}
    # Closed cycles define the historical windows the page compares against.
    closed = [c for c in payload['cycles'][:-1] if c['lowAfterPeak']]
    payload['windows'] = {
        'peakDays': [min(c['peak']['day'] for c in closed[1:]), max(c['peak']['day'] for c in closed[1:])],
        'peakMultiple': [min(c['peak']['multiple'] for c in closed[1:]), max(c['peak']['multiple'] for c in closed[1:])],
        'lowDays': [min(c['lowAfterPeak']['day'] for c in closed), max(c['lowAfterPeak']['day'] for c in closed)],
        'drawdownPct': [max(c['lowAfterPeak']['drawdownPct'] for c in closed), min(c['lowAfterPeak']['drawdownPct'] for c in closed)],
        'note': '高点窗口取第 2、3 周期（第 1 周期样本过早）；低点窗口与回撤取前 3 个完整周期，均为日收盘口径。',
    }
    out = ROOT / 'data/halving-cycles.json'
    tmp = out.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8')
    tmp.replace(out)
    for c in payload['cycles']:
        p, l = c['peak'], c['lowAfterPeak']
        print(c['halving'], f"base {c['halvingClose']:.0f} peak {p['close']:.0f} D{p['day']} x{p['multiple']:.2f}",
              f"low {l['close']:.0f} D{l['day']} {l['drawdownPct']:.1f}%" if l else '', 'last D', c['lastDay'])
    print('windows', payload['windows'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
