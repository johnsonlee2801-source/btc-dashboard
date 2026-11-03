"""Pure calculations for the BTC/ETH observatory: series, rules, gaps, scores and backtests.

Everything here works on plain {date: value} series (ISO dates, UTC days) so the
same code produces today's reading, the 365-day index history and the backtest.
No network access and no clock: callers pass the dates they want evaluated.
"""
import math
import statistics
from datetime import date, timedelta

# ---------------------------------------------------------------- series helpers


def d(s):
    return date.fromisoformat(s[:10])


def iso(day):
    return day.isoformat()


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def sorted_dates(series):
    return sorted(series)


def asof(series, day, max_age_days, lag=0):
    """Latest (date, value) observed no more than max_age_days before `day`, else None.

    `lag` is the publication delay: an observation is only visible `lag` days after its
    date, while its freshness still counts from the observation date itself.
    """
    probe = d(day)
    for back in range(lag, max_age_days + 1):
        key = iso(probe - timedelta(days=back))
        value = series.get(key)
        if finite(value):
            return key, value
    return None


def rolling_mean(closes, window):
    """closes: [(date, value)] contiguous days. Returns {date: mean of last `window`}."""
    out, total, queue = {}, 0.0, []
    prev = None
    for day, value in closes:
        if prev is not None and (d(day) - d(prev)).days != 1:
            total, queue = 0.0, []
        queue.append(value)
        total += value
        if len(queue) > window:
            total -= queue.pop(0)
        if len(queue) == window:
            out[day] = total / window
        prev = day
    return out


def ema(closes, span):
    out, value, prev = {}, None, None
    alpha = 2 / (span + 1)
    count = 0
    for day, close in closes:
        if prev is not None and (d(day) - d(prev)).days != 1:
            value, count = None, 0
        value = close if value is None else alpha * close + (1 - alpha) * value
        count += 1
        if count >= span:
            out[day] = value
        prev = day
    return out


def rolling_max(closes, window):
    out, prev, queue = {}, None, []
    for day, value in closes:
        if prev is not None and (d(day) - d(prev)).days != 1:
            queue = []
        queue.append(value)
        if len(queue) > window:
            queue.pop(0)
        if len(queue) == window:
            out[day] = max(queue)
        prev = day
    return out


def weekly_closes(closes):
    """Complete UTC weeks (Mon-Sun all present) -> [(sunday, close)]."""
    by_day = dict(closes)
    weeks = []
    if not closes:
        return weeks
    first, last = d(closes[0][0]), d(closes[-1][0])
    monday = first - timedelta(days=first.weekday())
    while monday + timedelta(days=6) <= last:
        days = [iso(monday + timedelta(days=i)) for i in range(7)]
        if all(x in by_day for x in days):
            weeks.append((days[-1], by_day[days[-1]]))
        monday += timedelta(days=7)
    return weeks


def wilder_rsi(values, period=14):
    """values: [(key, close)] -> {key: rsi} starting once `period` changes exist."""
    out = {}
    if len(values) <= period:
        return out
    changes = [(values[i][0], values[i][1] - values[i - 1][1]) for i in range(1, len(values))]
    gain = sum(max(c, 0) for _, c in changes[:period]) / period
    loss = sum(max(-c, 0) for _, c in changes[:period]) / period

    def value(g, l):
        return 50.0 if g == l == 0 else 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    out[changes[period - 1][0]] = value(gain, loss)
    for key, c in changes[period:]:
        gain = (gain * (period - 1) + max(c, 0)) / period
        loss = (loss * (period - 1) + max(-c, 0)) / period
        out[key] = value(gain, loss)
    return out


def carry_weekly(weekly, days):
    """Map each day to the latest complete week's value.

    A week is usable from its own closing day on: callers only pass closed daily candles,
    so the Sunday candle that completes the week is final. Values are carried at most
    8 days, i.e. until the next week has had a day to arrive.
    """
    keys = sorted(weekly)
    out, i, current = {}, 0, None
    for day in days:
        while i < len(keys) and keys[i] <= day:
            current = keys[i]
            i += 1
        if current is not None and (d(day) - d(current)).days <= 8:
            out[day] = weekly[current]
    return out


def weekly_runs(weeks):
    """Split complete weeks into runs 7 days apart, so indicators never bridge a missing week."""
    runs, run = [], []
    for key, value in weeks:
        if run and (d(key) - d(run[-1][0])).days != 7:
            runs.append(run)
            run = []
        run.append((key, value))
    if run:
        runs.append(run)
    return runs


def change_over(series, days):
    """{date: value[t] - value[t-days]} where both observations exist."""
    out = {}
    for key, value in series.items():
        old = series.get(iso(d(key) - timedelta(days=days)))
        if finite(value) and finite(old):
            out[key] = value - old
    return out


def price_features(closes):
    """closes: sorted [(date, close)] of closed candles. Returns {feature: {date: value}}.

    Non-finite or non-positive closes are dropped; the resulting gap resets every rolling window.
    """
    closes = [(day, close) for day, close in closes if finite(close) and close > 0]
    ma200 = rolling_mean(closes, 200)
    high90 = rolling_max(closes, 90)
    ma200w_week, rsi_week = {}, {}
    for run in weekly_runs(weekly_closes(closes)):
        rsi_week.update(wilder_rsi(run))
        window = []
        for key, value in run:
            window.append(value)
            if len(window) > 200:
                window.pop(0)
            if len(window) == 200:
                ma200w_week[key] = sum(window) / 200
    days = [day for day, _ in closes]
    ma200w = carry_weekly(ma200w_week, days)
    weekly_rsi = carry_weekly(rsi_week, days)
    ema150 = ema(closes, 150)
    sma471 = rolling_mean(closes, 471)
    price = dict(closes)
    feats = {'price': price, 'ma200d': ma200, 'high90': high90, 'ma200w': ma200w, 'weekly_rsi': weekly_rsi,
             'mayer': {}, 'price_ma200w': {}, 'drawdown90': {}, 'pi_bottom': {}}
    for day, close in closes:
        if day in ma200:
            feats['mayer'][day] = close / ma200[day]
        if day in ma200w:
            feats['price_ma200w'][day] = close / ma200w[day]
        if day in high90:
            feats['drawdown90'][day] = max(0.0, (high90[day] - close) / high90[day] * 100)
        if day in ema150 and day in sma471:
            # Pi Cycle Bottom: 150-day EMA versus 0.745 x 471-day SMA; below 1 marks the bottom zone.
            feats['pi_bottom'][day] = ema150[day] / (0.745 * sma471[day])
    return feats


def hash_ribbon(hashrate):
    """1 while the 30-day hashrate SMA is below the 60-day SMA (miner capitulation), else 0."""
    points = sorted((k, v) for k, v in hashrate.items() if finite(v) and v > 0)
    # Hashrate series can skip days; rebuild a contiguous run with carry-forward of at most 2 days.
    if not points:
        return {}
    filled, cursor = [], d(points[0][0])
    lookup = dict(points)
    last_value, last_seen = None, None
    end = d(points[-1][0])
    while cursor <= end:
        key = iso(cursor)
        if key in lookup:
            last_value, last_seen = lookup[key], cursor
        if last_value is not None and (cursor - last_seen).days <= 2:
            filled.append((key, last_value))
        cursor += timedelta(days=1)
    sma30, sma60 = rolling_mean(filled, 30), rolling_mean(filled, 60)
    return {k: 1.0 if sma30[k] < sma60[k] else 0.0 for k in sma60 if k in sma30}


# ---------------------------------------------------------------- rules

OPS = {'<': lambda x, t: x < t, '<=': lambda x, t: x <= t, '>': lambda x, t: x > t, '>=': lambda x, t: x >= t}

# key, label, op, threshold, unit, price_linked, max_age_days
# price_linked: the metric moves proportionally with price today, so a trigger price exists.
BTC_GROUPS = [
    {'id': 'necessary', 'title': '大底必要信号', 'weight': 40,
     'description': '周期性大底通常同时出现的五个条件',
     'items': [
         ('supply_profit', '全网盈利占比', '<', 60, '%', False, 4),
         ('weekly_rsi', '周线 RSI', '<', 35, '', False, 2),
         ('hash_ribbon', '哈希带投降', '>', 0, '', False, 4),
         ('sopr', 'SOPR', '<', 1, '', False, 4),
         ('mayer', 'Mayer 倍数', '<', 0.8, '', True, 3),
     ]},
    {'id': 'confirm', 'title': '大底确认信号', 'weight': 40,
     'description': '链上估值与长期均线跌到历史低估区',
     'items': [
         ('mvrv_z', 'MVRV Z-Score', '<', 0, '', False, 4),
         ('price_ma200w', '价格 / 200周均线', '<', 1, '', True, 2),
         ('mvrv', 'MVRV', '<', 1, '', True, 4),
         ('lth_ratio', '价格 / LTH 成本', '<', 1, '', True, 4),
         ('puell', 'Puell Multiple', '<', 0.5, '', False, 4),
         ('pi_bottom', 'Pi Cycle 底部', '<', 1, '', False, 3),
     ]},
    {'id': 'relative', 'title': '相对底部信号', 'weight': 20,
     'description': '短期持有者亏损、情绪恐慌与长线/大户承接',
     'items': [
         ('sth_mvrv', 'STH-MVRV', '<', 1, '', True, 4),
         ('sth_profit', 'STH 盈利占比', '<', 30, '%', False, 4),
         ('fear', '恐慌指数', '<=', 20, '', False, 2),
         ('lth_net30', 'LTH 30天净变化', '>', 0, ' BTC', False, 4),
         ('whale_net30', '巨鲸 30天净变化', '>', 0, ' BTC', False, 4),
     ]},
]

ETH_GROUPS = [
    {'id': 'technical', 'title': 'ETH 低位条件', 'weight': 0,
     'description': '价格周期与链上估值；每项可回测，阈值与 BTC 同口径',
     'items': [
         ('weekly_rsi', '周线 RSI', '<', 35, '', False, 2),
         ('mayer', 'Mayer 倍数', '<', 0.8, '', True, 3),
         ('price_ma200w', '价格 / 200周均线', '<', 1, '', True, 2),
         ('drawdown90', '距90天高点回撤', '>=', 20, '%', False, 3),
         ('pi_bottom', 'Pi Cycle 底部', '<', 1, '', False, 3),
         # BGeometrics publishes ETH MVRV about 5-7 days late; a tighter window would never be fresh.
         ('mvrv', 'ETH MVRV', '<', 1, '', True, 8),
     ]},
]

VERDICT_BANDS = [(60, 'strong', '历史低位信号集中'), (50, 'building', '低位信号增强'),
                 (20, 'watch', '进入关注区'), (0, 'none', '无底部信号')]


def verdict(score):
    for floor, code, label in VERDICT_BANDS:
        if score >= floor:
            return code, label
    return 'none', '无底部信号'


def evaluate(op, threshold, value):
    return OPS[op](value, threshold) if finite(value) else None


def gap(item, value, price):
    """Distance to the trigger. Price-linked metrics also give the trigger price."""
    key, _, op, threshold, unit, linked, _ = item
    if not finite(value):
        return None
    if evaluate(op, threshold, value):
        return {'met': True}
    out = {'met': False, 'delta': threshold - value}
    if linked and finite(price) and value > 0:
        target = price * threshold / value
        out['triggerPrice'] = target
        out['movePct'] = (target / price - 1) * 100
    return out


def series_value(series, item, day):
    found = asof(series, day, item[6])
    return found


def score_on(groups, table, day, lags=None):
    """Score on one day. table: {key: series}; lags: {key: publication delay in days}.

    Missing inputs count as unknown. With lags, only what was published by `day` is used.
    """
    lags = lags or {}
    lower = upper = 0.0
    lit = known = total = 0
    per_group = []
    for group in groups:
        weight = group['weight'] / len(group['items']) if group['weight'] else 0
        g_lit = g_known = 0
        for item in group['items']:
            total += 1
            found = asof(table.get(item[0], {}), day, item[6], lags.get(item[0], 0))
            state = evaluate(item[2], item[3], found[1]) if found else None
            if state is not None:
                known += 1
                g_known += 1
            if state:
                lit += 1
                g_lit += 1
                lower += weight
            if state is not False:
                upper += weight
        per_group.append({'id': group['id'], 'lit': g_lit, 'known': g_known, 'total': len(group['items'])})
    return {'lower': round(lower, 1), 'upper': round(upper, 1), 'lit': lit, 'known': known, 'total': total,
            'groups': per_group}


def combo_on(table, day, lags=None):
    """BTC combination: price below STH cost AND >=20% below the 90-day closing high."""
    lags = lags or {}
    price, sth, dd = (asof(table.get(k, {}), day, a, lags.get(k, 0)) for k, a in (('price', 0), ('sth_cost', 4), ('drawdown90', 0)))
    if not price or not sth or not dd:
        return None
    return price[1] < sth[1] and dd[1] >= 20


# ---------------------------------------------------------------- backtest

def local_lows(price, radius=45):
    """Dates whose close is the minimum within +-radius days and that have a full window."""
    days = sorted(price)
    lows = []
    for i in range(radius, len(days) - radius):
        window = [price[days[j]] for j in range(i - radius, i + radius + 1)]
        if price[days[i]] == min(window) and (d(days[i + radius]) - d(days[i - radius])).days == 2 * radius:
            lows.append(days[i])
    return lows


def backtest(lit_days, price, start, end, horizon=90, near=7):
    """Evidence for one signal over [start, end].

    lit_days: set of dates the signal was on. Reports how often it was on, what
    price did `horizon` days later, and how many 3-month lows it was on around.
    """
    days = [x for x in sorted(price) if start <= x <= end]
    if len(days) < horizon * 2:
        return None
    lit = [x for x in days if x in lit_days]
    forward = []
    for x in lit:
        later = price.get(iso(d(x) + timedelta(days=horizon)))
        if finite(later):
            forward.append(later / price[x] - 1)
    episodes, prev = 0, None
    for x in lit:
        if prev is None or (d(x) - d(prev)).days > near:
            episodes += 1
        prev = x
    lows = [x for x in local_lows({k: price[k] for k in days})]
    covered = sum(1 for low in lows if any(iso(d(low) + timedelta(days=k)) in lit_days for k in range(-near, near + 1)))
    lit_near_low = sum(1 for x in lit if any(abs((d(x) - d(low)).days) <= 30 for low in lows))
    return {
        'start': days[0], 'end': days[-1], 'sampleDays': len(days), 'litDays': len(lit), 'episodes': episodes,
        'forwardDays': horizon, 'forwardN': len(forward),
        'forwardMedianPct': round(statistics.median(forward) * 100, 1) if forward else None,
        'forwardUpPct': round(sum(1 for r in forward if r > 0) / len(forward) * 100) if forward else None,
        'lows': len(lows), 'lowsCovered': covered,
        'nearLowPct': round(lit_near_low / len(lit) * 100) if lit else None,
    }


def lit_set(series, op, threshold):
    return {k for k, v in series.items() if evaluate(op, threshold, v)}


def lit_days(series, item, days, lag=0):
    """Days a signal was on as a live reader would have seen it.

    An observation counts only from its publication day (observation date + `lag` days)
    and only while it is within the item's freshness window counted from the observation
    date, exactly like today's evaluation.
    """
    out = set()
    for day in days:
        found = asof(series, day, item[6], lag)
        if found and evaluate(item[2], item[3], found[1]):
            out.add(day)
    return out
