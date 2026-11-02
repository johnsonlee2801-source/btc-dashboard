"""BGeometrics on-chain history kept in data/onchain-history.json.

The free API allows 10 requests per hour and 15 per day per IP, and each series
endpoint returns roughly the last four years of daily values. So instead of
asking for `/last` values every run, each run refreshes at most MAX_CALLS whole
series, oldest first, and merges them into the stored history. Missing series
(first runs) come first, then core series older than 20h, then slower ones.
Merged history keeps every date ever seen, so a failed run loses nothing.
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = 'https://api.bitcoin-data.com/v1/'
DOC = 'https://api.bitcoin-data.com/swagger-ui/index.html'
MAX_CALLS = 8

# key -> (endpoint, refresh hours). Core inputs of today's signals refresh daily.
SERIES = {
    'sth_cost': ('realized-price-sth', 20),
    'sth_profit': ('percent-sth-in-profit', 20),
    'supply_profit': ('supply-in-profit-pct', 20),
    'lth_net30': ('lth-net-position-change-30d-btc', 20),
    'whale_1k_10k': ('coins-addr-10K-1K-BTC', 20),
    'lth_cost': ('realized-price-lth', 44),
    'true_mean': ('true-market-mean', 68),
    'whale_10k_plus': ('coins-addr-10K-BTC', 68),
    'retail_lt1': ('coins-addr-1-BTC', 68),
    'eth_mvrv': ('eth-mvrv', 44),
    # The snapshot adds yesterday's value daily; whole series only back-fill history,
    # and these endpoints publish ~5 days later than the snapshot anyway.
    'mvrv': ('mvrv', 168),
    'mvrv_z': ('mvrv-zscore', 168),
    'sopr': ('sopr', 168),
    'puell': ('puell-multiple', 168),
    'realized_price': ('realized-price', 168),
    'hashrate': ('hashrate', 168),
}
# The snapshot endpoint returns yesterday's value for several series in one call.
SNAPSHOT_FIELDS = {'mvrv': 'mvrv', 'mvrv_z': 'mvrvZscore', 'sopr': 'sopr', 'puell': 'puellMultiple',
                   'realized_price': 'realizedPrice', 'hashrate': 'hashrate'}


def number(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and n not in (float('inf'), float('-inf')) else None


def parse_series(raw):
    """[{'d': '2026-10-31', 'unixTs': .., '<field>': value}] -> {date: value}.

    Endpoints name their value field differently; each row carries exactly one
    numeric field besides the timestamp, so take that one.
    """
    out = {}
    if not isinstance(raw, list):
        return out
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get('d'), str):
            continue
        values = [number(v) for k, v in row.items() if k not in ('d', 'unixTs', 'date') and number(v) is not None]
        if len(values) == 1:
            out[row['d'][:10]] = values[0]
    return out


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'FlowHunt-observatory/2.0 (+https://btc.flowhunt.net)'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def load(path):
    try:
        store = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        store = {}
    store.setdefault('series', {})
    store.setdefault('fetched', {})
    return store


def due(store, now):
    """Series keys to refresh this run, most urgent first."""
    def age_hours(key):
        stamp = store['fetched'].get(key)
        try:
            return (now - datetime.fromisoformat(stamp)).total_seconds() / 3600
        except (TypeError, ValueError):
            return None
    missing = [k for k in SERIES if not store['series'].get(k)]
    stale = [k for k in SERIES if k not in missing and (age_hours(k) is None or age_hours(k) >= SERIES[k][1])]
    stale.sort(key=lambda k: (SERIES[k][1], -(age_hours(k) or 1e9)))
    return missing + stale


def refresh(store, now=None, fetch=get_json, max_calls=MAX_CALLS):
    """Mutates and returns (store, errors). One call is reserved for the snapshot when due."""
    now = now or datetime.now(timezone.utc)
    errors, calls = [], 0
    snap_stamp = store['fetched'].get('_snapshot')
    try:
        snap_due = (now - datetime.fromisoformat(snap_stamp)).total_seconds() >= 20 * 3600
    except (TypeError, ValueError):
        snap_due = True
    if snap_due and max_calls > 0:
        calls += 1
        try:
            snap = fetch(BASE + 'snapshot')
            day = str(snap.get('date', ''))[:10] if isinstance(snap, dict) else ''
            if day:
                for key, field in SNAPSHOT_FIELDS.items():
                    value = number(snap.get(field))
                    if value is not None:
                        store['series'].setdefault(key, {})[day] = value
                store['fetched']['_snapshot'] = now.isoformat()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors.append({'url': BASE + 'snapshot', 'error': type(exc).__name__})
    for key in due(store, now):
        if calls >= max_calls:
            break
        endpoint = SERIES[key][0]
        calls += 1
        try:
            parsed = parse_series(fetch(BASE + endpoint))
            if not parsed:
                raise ValueError('empty series')
            store['series'].setdefault(key, {}).update(parsed)
            store['fetched'][key] = now.isoformat()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors.append({'url': BASE + endpoint, 'error': type(exc).__name__})
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                break
    return store, errors


def save(store, path):
    store['series'] = {k: dict(sorted(v.items())) for k, v in sorted(store['series'].items())}
    path.write_text(json.dumps(store, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
