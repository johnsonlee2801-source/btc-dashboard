"""BGeometrics on-chain history kept in data/onchain-history.json.

The free API allows 10 requests per hour and 15 per day per IP, and each series
endpoint returns roughly the last four years of daily values. So instead of
asking for `/last` values every run, each run refreshes whole series, oldest
first, and merges them into the stored history. Missing series (first runs)
come first, then core series older than 20h, then slower ones.

Every request attempt is logged in the store and the hourly/daily allowance is
enforced across runs (scheduled and manual alike). A 429 stops the run at once.
Merged history keeps every date ever seen, so a failed run loses nothing; a
corrupt history file stops the run instead of being silently replaced.
"""
import http.client
import json
import math
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

BASE = 'https://api.bitcoin-data.com/v1/'
DOC = 'https://api.bitcoin-data.com/swagger-ui/index.html'
MAX_CALLS = 8
HOURLY_LIMIT, DAILY_LIMIT = 9, 14   # one below the published 10/h and 15/day
FETCH_ERRORS = (urllib.error.URLError, OSError, ValueError, http.client.HTTPException)

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
MIN_SNAPSHOT_FIELDS = 4


class CorruptStore(RuntimeError):
    pass


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if math.isfinite(n) else None


def observation_day(value, today):
    """Canonical YYYY-MM-DD not after today, else None."""
    if not isinstance(value, str):
        return None
    try:
        day = date.fromisoformat(value[:10])
    except ValueError:
        return None
    return day.isoformat() if day <= today else None


def parse_series(raw, today=None):
    """[{'d': '2026-10-31', 'unixTs': .., '<field>': value}] -> {date: value}.

    Endpoints name their value field differently; each row carries exactly one
    numeric field besides the timestamp, so take that one.
    """
    today = today or datetime.now(timezone.utc).date()
    out = {}
    if not isinstance(raw, list):
        return out
    for row in raw:
        if not isinstance(row, dict):
            continue
        day = observation_day(row.get('d'), today)
        values = [number(v) for k, v in row.items() if k not in ('d', 'unixTs', 'date') and number(v) is not None]
        if day and len(values) == 1:
            out[day] = values[0]
    return out


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'FlowHunt-observatory/2.0 (+https://btc.flowhunt.net)'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def load(path):
    """Missing file -> empty store. An existing file that is unreadable or malformed raises."""
    if not path.exists():
        return {'series': {}, 'fetched': {}, 'calls': []}
    try:
        store = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise CorruptStore(f'{path.name}: {exc}') from None
    if not isinstance(store, dict):
        raise CorruptStore(f'{path.name}: root is not an object')
    store.setdefault('series', {})
    store.setdefault('fetched', {})
    store.setdefault('calls', [])
    if not isinstance(store['series'], dict) or not isinstance(store['fetched'], dict) or not isinstance(store['calls'], list) \
            or not all(isinstance(v, dict) for v in store['series'].values()):
        raise CorruptStore(f'{path.name}: unexpected structure')
    return store


def _stamp(value):
    try:
        t = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def allowance(store, now):
    """Requests still allowed now under the hourly and daily limits, counting earlier runs."""
    calls = [t for t in (_stamp(c) for c in store['calls']) if t and now - t < timedelta(days=1)]
    store['calls'] = [t.isoformat() for t in calls]
    hour = sum(1 for t in calls if now - t < timedelta(hours=1))
    return max(0, min(HOURLY_LIMIT - hour, DAILY_LIMIT - len(calls)))


def due(store, now):
    """Series keys to refresh this run, most urgent first."""
    def age_hours(key):
        stamp = _stamp(store['fetched'].get(key))
        return (now - stamp).total_seconds() / 3600 if stamp else None
    missing = [k for k in SERIES if not store['series'].get(k)]
    stale = [k for k in SERIES if k not in missing and (age_hours(k) is None or age_hours(k) >= SERIES[k][1])]
    stale.sort(key=lambda k: (SERIES[k][1], -(age_hours(k) or 1e9)))
    return missing + stale


def refresh(store, now=None, fetch=get_json, max_calls=MAX_CALLS):
    """Mutates and returns (store, errors). One call is reserved for the snapshot when due."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    errors = []
    for key, empty in (('series', {}), ('fetched', {}), ('calls', [])):
        store.setdefault(key, empty)
    budget = min(max_calls, allowance(store, now))

    def call(url):
        store['calls'].append(now.isoformat())
        return fetch(url)

    snap_stamp = _stamp(store['fetched'].get('_snapshot'))
    snap_due = not snap_stamp or (now - snap_stamp).total_seconds() >= 20 * 3600
    if snap_due and budget > 0:
        budget -= 1
        try:
            snap = call(BASE + 'snapshot')
            day = observation_day(snap.get('date'), today) if isinstance(snap, dict) else None
            values = {key: number(snap.get(field)) for key, field in SNAPSHOT_FIELDS.items()} if day else {}
            usable = {k: v for k, v in values.items() if v is not None}
            if not day or len(usable) < MIN_SNAPSHOT_FIELDS:
                raise ValueError(f'incomplete snapshot ({len(usable)} usable fields)')
            for key, value in usable.items():
                store['series'].setdefault(key, {})[day] = value
            store['fetched']['_snapshot'] = now.isoformat()
        except FETCH_ERRORS as exc:
            errors.append({'url': BASE + 'snapshot', 'error': type(exc).__name__})
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                return store, errors
    for key in due(store, now):
        if budget <= 0:
            break
        endpoint = SERIES[key][0]
        budget -= 1
        try:
            parsed = parse_series(call(BASE + endpoint), today)
            if not parsed:
                raise ValueError('empty series')
            store['series'].setdefault(key, {}).update(parsed)
            store['fetched'][key] = now.isoformat()
        except FETCH_ERRORS as exc:
            errors.append({'url': BASE + endpoint, 'error': type(exc).__name__})
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                break
    return store, errors


def save(store, path):
    store['series'] = {k: dict(sorted(v.items())) for k, v in sorted(store['series'].items())}
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(store, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8')
    tmp.replace(path)
