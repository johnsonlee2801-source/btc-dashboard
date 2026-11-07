"""Daily series from checkonchain's public charts, merged into the on-chain store.

checkonchain publishes each chart as a static Plotly page on its CDN. The traces
carry the full daily history (dates as ISO strings, values as plain lists or
base64 typed arrays), so one request per chart refreshes every series on it.
Entity-adjusted cohorts, MVRV Z-Score, NUPL and miner revenue vs production cost
come from here; they are what most public BTC bottom dashboards quote.

The current UTC day is still being built on the charts and is never stored.
Failures keep the history already in the store.
"""
import base64
import json
import math
import struct
import urllib.error
import urllib.request
import http.client
from datetime import datetime, timezone

CDN = 'https://charts-cdn.checkonchain.com/btconchain/'
DOC = 'https://charts.checkonchain.com/'
UA = 'Mozilla/5.0 (FlowHunt-observatory/2.0; +https://btc.flowhunt.net)'
REFRESH_HOURS = 12
HISTORY_START = '2017-01-01'
FETCH_ERRORS = (urllib.error.URLError, OSError, ValueError, http.client.HTTPException, KeyError, struct.error)

# chart path -> {store key: (combine, trace names)}
CHARTS = {
    'mining/revenuevscost/revenuevscost': {
        'cc_miner_rev_cost': ('ratio', ('Miner Revenue [USD]', 'Estimated Cost [USD]')),
    },
    'unrealised/mvrv_all_zscore/mvrv_all_zscore': {
        'cc_mvrv_z': ('first', ('MVRV Z-Score',)),
        'cc_mvrv_z_m1_price': ('first', ('Price -1.0sd',)),
    },
    'unrealised/nupl/nupl': {
        # Each NUPL zone is its own trace with NaN outside the zone.
        'cc_nupl': ('any', ('Euphoria-Greed', 'Belief-Denial', 'Optimism', 'Hope-Fear', 'Capitulation')),
    },
    'supply/lthnetposchange_0/lthnetposchange_0': {
        # Split into a positive and a negative trace, each 0 on the other side's days.
        'cc_lth_net30': ('sum', ('Positive 30d Change', 'Negative 30d Change')),
    },
    'supply/distribution_netposchange_30/distribution_netposchange_30': {
        'cc_net30_lt1': ('first', ('Shrimp < 1BTC',)),
        'cc_net30_1_10': ('first', ('Crabs 1 to 10 1BTC',)),
        'cc_net30_10_100': ('first', ('Fish 10 to 100BTC',)),
        'cc_net30_100_1k': ('first', ('Sharks 100 to 1kBTC',)),
        'cc_net30_1k_10k': ('first', ('Whales 1kBTC to 10k BTC',)),
        'cc_net30_10k_plus': ('first', ('MegaWhales and Exchanges > 10k BTC',)),
    },
    'pricing/pricing_costbasisoriginals/pricing_costbasisoriginals': {
        'cc_true_mean': ('first', ('True Mean Price',)),
        'cc_sth_cost': ('first', ('STH Cost Basis',)),
        'cc_lth_cost': ('first', ('LTH Cost Basis',)),
    },
}

DTYPES = {'f8': 'd', 'f4': 'f', 'i4': 'i', 'i2': 'h', 'i1': 'b', 'u1': 'B', 'u2': 'H', 'u4': 'I'}


def chart_url(path):
    return CDN + path + '_light.html'


def get_text(url, timeout=45):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode('utf-8')


def values(v):
    """Plotly array: a plain list or {'dtype', 'bdata'} little-endian typed array."""
    if isinstance(v, list):
        return v
    if isinstance(v, dict) and 'bdata' in v:
        fmt = DTYPES[v['dtype']]
        raw = base64.b64decode(v['bdata'])
        n = len(raw) // struct.calcsize(fmt)
        return list(struct.unpack('<%d%s' % (n, fmt), raw[:n * struct.calcsize(fmt)]))
    raise ValueError('unsupported array encoding')


def traces(html):
    """{trace name: {date: value}} from the first Plotly.newPlot call on the page."""
    start = html.index('Plotly.newPlot(')
    body = html[start:]
    data, _ = json.JSONDecoder().raw_decode(body[body.index('['):])
    out = {}
    for trace in data:
        name = trace.get('name')
        if not name or name in out:
            continue
        xs, ys = trace.get('x'), trace.get('y')
        if xs is None or ys is None:
            continue
        xs, ys = values(xs), values(ys)
        series = {}
        for x, y in zip(xs, ys):
            if not isinstance(x, str) or len(x) < 10 or isinstance(y, bool) or not isinstance(y, (int, float)):
                continue
            if math.isfinite(y):
                series[x[:10]] = float(y)
        out[name] = series
    return out


def combine(kind, parts):
    if kind == 'first':
        return dict(parts[0])
    if kind == 'any':
        out = {}
        for part in parts:
            for day, v in part.items():
                out.setdefault(day, v)
        return out
    if kind == 'sum':
        days = set(parts[0]).intersection(*parts[1:])
        return {day: sum(part[day] for part in parts) for day in days}
    if kind == 'ratio':
        num, den = parts
        return {day: num[day] / den[day] for day in num if den.get(day)}
    raise ValueError(kind)


def parse_chart(html, spec, today):
    """{store key: {date: value}} for one chart; drops the current, still-forming UTC day."""
    found = traces(html)
    out = {}
    for key, (kind, names) in spec.items():
        parts = [found[n] for n in names]  # KeyError when checkonchain renames a trace
        series = {d: v for d, v in combine(kind, parts).items() if HISTORY_START <= d < today}
        if not series:
            raise ValueError(f'{key}: empty')
        out[key] = series
    return out


def _age_hours(store, path, now):
    try:
        stamp = datetime.fromisoformat(store['fetched'].get('cc:' + path, ''))
    except (TypeError, ValueError):
        return None
    stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    return (now - stamp).total_seconds() / 3600


def refresh(store, now=None, fetch=get_text):
    """Mutates and returns (store, errors). Charts fetched within REFRESH_HOURS are skipped."""
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    errors = []
    store.setdefault('series', {})
    store.setdefault('fetched', {})
    for path, spec in CHARTS.items():
        age = _age_hours(store, path, now)
        if age is not None and 0 <= age < REFRESH_HOURS:
            continue
        url = chart_url(path)
        try:
            parsed = parse_chart(fetch(url), spec, today)
        except FETCH_ERRORS as exc:
            errors.append({'url': url, 'error': type(exc).__name__})
            continue
        for key, series in parsed.items():
            store['series'].setdefault(key, {}).update(series)
            store['fetched'][key] = now.isoformat()
        store['fetched']['cc:' + path] = now.isoformat()
    return store, errors
