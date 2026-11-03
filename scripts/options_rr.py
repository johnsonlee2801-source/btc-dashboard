"""30-day 25-delta risk reversal from Deribit public option marks.

RR25 = IV(25-delta call) - IV(25-delta put), in volatility points. Negative means
puts are priced richer than calls (downside protection in demand).

Method: per expiry, Black-Scholes forward delta from each option's mark IV
(Deribit options settle on the expiry's forward, rates ~0), interpolate the IV
at |delta| = 0.25 separately for calls and puts, then interpolate the two
expiries bracketing 30 days linearly in time. Without a bracket there is no
30-day value: a far expiry is not passed off as 30 days.

Only rows whose own `creation_timestamp` is recent are used, and the result
carries the newest of those timestamps as its observation time.
"""
import math
from datetime import datetime, timezone

MONTHS = {m: i + 1 for i, m in enumerate(('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'))}
MAX_AGE_SECONDS = 2 * 3600
TARGET_DAYS = 30.0


def positive(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def parse_instrument(name):
    """BTC-13NOV26-83000-P -> (expiry datetime 08:00 UTC, strike, 'C'|'P'), else None."""
    if not isinstance(name, str):
        return None
    try:
        _, code, strike, kind = name.split('-')
        day, month, year = int(code[:-5]), MONTHS[code[-5:-2]], 2000 + int(code[-2:])
        strike = float(strike)
        if kind not in ('C', 'P') or not math.isfinite(strike) or strike <= 0:
            return None
        return datetime(year, month, day, 8, tzinfo=timezone.utc), strike, kind
    except (ValueError, KeyError):
        return None


def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def forward_delta(forward, strike, iv_pct, years, kind):
    sigma = iv_pct / 100
    if forward <= 0 or strike <= 0 or sigma <= 0 or years <= 0:
        return None
    d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * years) / (sigma * math.sqrt(years))
    return norm_cdf(d1) if kind == 'C' else norm_cdf(d1) - 1


def iv_at_delta(points, target):
    """points: [(abs_delta, iv)]; exact match or linear interpolation at abs delta `target`."""
    points = sorted(points)
    for d, v in points:
        if d == target:
            return v
    for (d0, v0), (d1, v1) in zip(points, points[1:]):
        if d0 < target < d1:
            return v0 + (v1 - v0) * (target - d0) / (d1 - d0)
    return None


def rr25_by_expiry(summaries, now):
    """{expiry: rr} from fresh, well-formed rows; also returns the newest row time used."""
    by_expiry, newest = {}, None
    for row in summaries if isinstance(summaries, list) else []:
        if not isinstance(row, dict):
            continue
        parsed = parse_instrument(row.get('instrument_name'))
        iv, forward, created = positive(row.get('mark_iv')), positive(row.get('underlying_price')), positive(row.get('creation_timestamp'))
        if not parsed or not iv or not forward or not created:
            continue
        stamp = datetime.fromtimestamp(created / 1000, timezone.utc)
        age = (now - stamp).total_seconds()
        if not 0 <= age <= MAX_AGE_SECONDS:
            continue
        expiry, strike, kind = parsed
        years = (expiry - now).total_seconds() / (365 * 86400)
        if years <= 2 / 365:
            continue
        delta = forward_delta(forward, strike, iv, years, kind)
        if delta is None or not math.isfinite(delta):
            continue
        by_expiry.setdefault(expiry, {'C': [], 'P': []})[kind].append((abs(delta), iv))
        newest = stamp if newest is None or stamp > newest else newest
    out = {}
    for expiry, sides in by_expiry.items():
        call, put = iv_at_delta(sides['C'], 0.25), iv_at_delta(sides['P'], 0.25)
        if call is not None and put is not None:
            out[expiry] = call - put
    return out, newest


def rr25_30d(summaries, now=None):
    """{'value', 'tenor', 'asOf'} for the 30-day RR25, or None without fresh bracketing expiries."""
    now = now or datetime.now(timezone.utc)
    per, newest = rr25_by_expiry(summaries, now)
    days = sorted(((e - now).total_seconds() / 86400, v) for e, v in per.items())
    below = [x for x in days if x[0] <= TARGET_DAYS]
    above = [x for x in days if x[0] >= TARGET_DAYS]
    if not below or not above:
        return None
    (t0, v0), (t1, v1) = below[-1], above[0]
    value = v0 if t1 == t0 else v0 + (v1 - v0) * (TARGET_DAYS - t0) / (t1 - t0)
    return {'value': round(value, 2), 'tenor': f'{t0:.0f}d/{t1:.0f}d 插值至 30d', 'asOf': newest.isoformat()}
