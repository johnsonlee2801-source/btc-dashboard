"""30-day 25-delta risk reversal from Deribit public option marks.

RR25 = IV(25-delta call) - IV(25-delta put), in volatility points. Negative means
puts are priced richer than calls (downside protection in demand).

Method: per expiry, Black-Scholes forward delta from each option's mark IV
(Deribit options settle on the expiry's forward, rates ~0), interpolate the IV
at |delta| = 0.25 separately for calls and puts, then interpolate the two
expiries bracketing 30 days linearly in time.
"""
import math
from datetime import datetime, timezone

MONTHS = {m: i + 1 for i, m in enumerate(('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'))}


def parse_instrument(name):
    """BTC-13NOV26-83000-P -> (expiry datetime 08:00 UTC, strike, 'C'|'P')."""
    try:
        _, code, strike, kind = name.split('-')
        day, month, year = int(code[:-5]), MONTHS[code[-5:-2]], 2000 + int(code[-2:])
        return datetime(year, month, day, 8, tzinfo=timezone.utc), float(strike), kind
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
    """points: [(abs_delta, iv)]; linear interpolation at abs delta `target`."""
    points = sorted(points)
    for (d0, v0), (d1, v1) in zip(points, points[1:]):
        if d0 <= target <= d1 and d1 > d0:
            return v0 + (v1 - v0) * (target - d0) / (d1 - d0)
    return None


def rr25_by_expiry(summaries, now):
    by_expiry = {}
    for row in summaries or []:
        parsed = parse_instrument(row.get('instrument_name', ''))
        iv, forward = row.get('mark_iv'), row.get('underlying_price')
        if not parsed or not isinstance(iv, (int, float)) or not isinstance(forward, (int, float)) or iv <= 0:
            continue
        expiry, strike, kind = parsed
        years = (expiry - now).total_seconds() / (365 * 86400)
        if years <= 2 / 365:
            continue
        delta = forward_delta(forward, strike, iv, years, kind)
        if delta is None:
            continue
        by_expiry.setdefault(expiry, {'C': [], 'P': []})[kind].append((abs(delta), iv))
    out = {}
    for expiry, sides in by_expiry.items():
        call, put = iv_at_delta(sides['C'], 0.25), iv_at_delta(sides['P'], 0.25)
        if call is not None and put is not None:
            out[expiry] = call - put
    return out


def rr25_30d(summaries, now=None):
    now = now or datetime.now(timezone.utc)
    per = rr25_by_expiry(summaries, now)
    if not per:
        return None
    target = 30.0
    days = sorted(((e - now).total_seconds() / 86400, v) for e, v in per.items())
    below = [x for x in days if x[0] <= target]
    above = [x for x in days if x[0] >= target]
    if below and above:
        (t0, v0), (t1, v1) = below[-1], above[0]
        value = v0 if t1 == t0 else v0 + (v1 - v0) * (target - t0) / (t1 - t0)
        tenor = f'{t0:.0f}d/{t1:.0f}d 插值至 30d'
    else:
        t0, value = min(days, key=lambda x: abs(x[0] - target))
        tenor = f'最近到期 {t0:.0f}d'
    return {'value': round(value, 2), 'tenor': tenor}
