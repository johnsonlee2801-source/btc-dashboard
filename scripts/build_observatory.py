#!/usr/bin/env python3
"""Build the BTC/ETH observatory snapshot (schema v2). No keys, no git side effects.

Every number carries its own observation date and source. Each signal comes
with its distance to trigger, a trigger price where the metric moves with
price, and a backtest computed from the same public history. Missing or
expired inputs never light a signal and are never filled with substitutes.
"""
import argparse
import json
import math
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import binance_futures  # noqa: E402
import onchain_store  # noqa: E402
import options_rr  # noqa: E402
import signals as S  # noqa: E402

SOURCES = {
    'Binance': 'https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints',
    'Binance Futures': 'https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api',
    'BGeometrics': onchain_store.DOC,
    'Alternative.me': 'https://alternative.me/crypto/fear-and-greed-index/',
    'CoinMarketCap': 'https://coinmarketcap.com/charts/fear-and-greed-index/',
    'Deribit': 'https://docs.deribit.com/',
    'Farside': 'https://farside.co.uk/',
    'Coin Metrics': 'https://docs.coinmetrics.io/',
    'DefiLlama': 'https://defillama.com/',
    'validatorqueue': 'https://www.validatorqueue.com/',
    'Blockscout': 'https://eth.blockscout.com/',
    'Ethereum RPC': 'https://ethereum.org/en/developers/docs/apis/json-rpc/',
    'FlowHunt 计算': 'https://btc.flowhunt.net/#method',
}
METHOD_VERSION = 'flowhunt-observation-v2'
UA = 'FlowHunt-observatory/2.0 (+https://btc.flowhunt.net)'

# Which source and freshness window each signal key reports.
KEY_SOURCE = {
    'price': 'Binance', 'ma200d': 'Binance', 'ma200w': 'Binance', 'high90': 'Binance', 'mayer': 'Binance',
    'price_ma200w': 'Binance', 'weekly_rsi': 'Binance', 'drawdown90': 'Binance', 'pi_bottom': 'Binance',
    'supply_profit': 'BGeometrics', 'sopr': 'BGeometrics', 'mvrv_z': 'BGeometrics', 'mvrv': 'BGeometrics',
    'puell': 'BGeometrics', 'sth_cost': 'BGeometrics', 'sth_profit': 'BGeometrics', 'lth_cost': 'BGeometrics',
    'realized_price': 'BGeometrics', 'true_mean': 'BGeometrics', 'lth_net30': 'BGeometrics',
    'hash_ribbon': 'BGeometrics', 'whale_net30': 'BGeometrics', 'sth_mvrv': 'FlowHunt 计算',
    'lth_ratio': 'FlowHunt 计算', 'fear': 'Alternative.me',
}
NOTES = {
    'hash_ribbon': '哈希率 30 日均线跌破 60 日均线视为矿工投降（1=投降中）。由 BGeometrics 全网哈希率计算。',
    'pi_bottom': 'Pi Cycle 底部：150 日 EMA ÷ (0.745 × 471 日均线)，低于 1 为历史底部区。由 Binance 日收盘计算。',
    'sth_mvrv': '价格 ÷ 短期持有者实现价格（STH 成本）。与 BGeometrics 发布值误差 <0.3%，自算可避免其接口约 5 天的发布延迟。',
    'lth_ratio': '价格 ÷ 长期持有者实现价格（LTH 成本）。',
    'whale_net30': '持有 1,000–10,000 BTC 的地址余额合计 30 天变化。地址口径，含部分交易所/托管地址，不等于实体买卖。',
    'lth_net30': '长期持有者（持币 >155 天）供给 30 天净变化。正值通常意味着筹码在沉淀。',
    'mvrv_z': 'BGeometrics 口径的 MVRV Z-Score。不同数据商的 Z 值标准差口径不同，数值不可跨站比较；本站阈值按本口径设定并回测。',
    'weekly_rsi': '完整 UTC 周收盘，Wilder 14 周平滑。',
    'mayer': '日收盘 ÷ 200 日均线。',
    'price_ma200w': '日收盘 ÷ 200 周均线（完整 UTC 周收盘均值）。',
    'fear': 'Alternative.me 恐慌与贪婪指数（BTC 市场情绪）。',
    'drawdown90': '距近 90 个完整日收盘高点的回撤，未使用日内最高价。',
    'eth_mvrv': 'ETH 市值 ÷ 实现市值（BGeometrics）。该序列发布约晚 5–7 天，有效期按 8 天计。',
}


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def safe_get(url, errors, timeout=30):
    try:
        return get_json(url, timeout)
    except Exception as exc:
        errors.append({'url': url, 'error': type(exc).__name__})
        return None


def load_file(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def metric(value, as_of, source, max_hours=72, note=''):
    return {'value': number(value), 'asOf': as_of, 'source': source, 'sourceUrl': SOURCES.get(source),
            'maxAgeHours': max_hours, 'note': note}


# ---------------------------------------------------------------- sources

def candle_closes(rows, cutoff_ms):
    """{date: close} from closed, well-formed kline rows; anything else is skipped."""
    closes = {}
    for row in rows:
        try:
            opened, ended, close = float(row[0]), float(row[6]), float(row[4])
            if not (math.isfinite(close) and close > 0 and 0 <= opened <= ended < cutoff_ms):
                continue
            closes[datetime.fromtimestamp(opened / 1000, timezone.utc).date().isoformat()] = close
        except (TypeError, ValueError, IndexError, KeyError, OverflowError, OSError):
            continue
    return closes


def fetch_candles(symbol, errors, now, pages=4):
    """Closed UTC daily candles, oldest first, up to pages*1000 days.

    A host whose pagination fails part-way is not trusted with a truncated history:
    the other host is tried, and the longer complete (or, failing that, longest) result wins.
    """
    best, best_complete = {}, False
    for host in ('data-api.binance.vision', 'api.binance.com'):
        rows, end, complete = [], None, False
        for _ in range(pages):
            url = f'https://{host}/api/v3/klines?symbol={symbol}USDT&interval=1d&limit=1000' + (f'&endTime={end}' if end else '')
            page = safe_get(url, errors)
            if not isinstance(page, list) or not page or not isinstance(page[0], list):
                break
            rows = page + rows
            try:
                end = int(page[0][0]) - 1
            except (TypeError, ValueError, IndexError):
                break
            if len(page) < 1000:
                complete = True
                break
        else:
            complete = True  # reached the page budget without a failure
        closes = candle_closes(rows, now.timestamp() * 1000)
        if (complete, len(closes)) > (best_complete, len(best)):
            best, best_complete = closes, complete
        if complete and closes:
            break
    return sorted(best.items())


def fetch_fear_alt(errors):
    raw = safe_get('https://api.alternative.me/fng/?limit=0&format=json', errors)
    rows = raw.get('data') if isinstance(raw, dict) else None
    return dated_values(rows if isinstance(rows, list) else [], 'timestamp', 'value')


def dated_values(rows, time_key, value_key):
    """{date: value} from rows with a unix-seconds timestamp; malformed rows are skipped."""
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp, value = number(row.get(time_key)), number(row.get(value_key))
        if stamp is None or value is None:
            continue
        try:
            out[datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()] = value
        except (OverflowError, OSError, ValueError):
            continue
    return out


def fetch_fear_cmc(errors, now):
    start = int((now - timedelta(days=400)).timestamp())
    raw = safe_get(f'https://api.coinmarketcap.com/data-api/v3/fear-greed/chart?start={start}&end={int(now.timestamp())}', errors)
    data = raw.get('data') if isinstance(raw, dict) else None
    rows = data.get('dataList') if isinstance(data, dict) else None
    return dated_values(rows if isinstance(rows, list) else [], 'timestamp', 'score')


def ratio_rows(body, field='longShortRatio'):
    out = []
    for row in body if isinstance(body, list) else []:
        stamp, value = number(row.get('timestamp')), number(row.get(field))
        long_part = number(row.get('longAccount'))
        if stamp is not None and value is not None:
            out.append({'t': int(stamp), 'ratio': value, 'long': long_part})
    return sorted(out, key=lambda r: r['t'])


def fetch_derivatives(symbol, errors, now):
    """Funding, positioning ratios (via Singapore proxy when configured), DVOL and RR25."""
    pair = symbol + 'USDT'
    requests = [('/fapi/v1/premiumIndex', {'symbol': pair}),
                ('/futures/data/globalLongShortAccountRatio', {'symbol': pair, 'period': '1d', 'limit': 31}),
                ('/futures/data/topLongShortPositionRatio', {'symbol': pair, 'period': '1d', 'limit': 31}),
                ('/futures/data/globalLongShortAccountRatio', {'symbol': pair, 'period': '1h', 'limit': 1}),
                ('/futures/data/topLongShortPositionRatio', {'symbol': pair, 'period': '1h', 'limit': 1})]
    try:
        results = binance_futures.fetch_many(requests)
    except Exception as exc:
        results = [{'status': 0, 'error': type(exc).__name__}] * len(requests)
    for (path, _), result in zip(requests, results):
        if result.get('status') != 200:
            errors.append({'url': binance_futures.HOST + path + '?symbol=' + pair, 'error': str(result.get('error'))})
    body = [r.get('body') if r.get('status') == 200 else None for r in results]
    out = {}
    prem = body[0] if isinstance(body[0], dict) else {}
    rate, stamp = number(prem.get('lastFundingRate')), number(prem.get('time'))
    if rate is not None and stamp:
        out['funding'] = metric(rate * 100, datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat(),
                                'Binance Futures', 12, '最新资金费率（每期，%）。年化按每 8 小时结算估算。')
    for key, idx, label in (('long_short', 1, '全体账户多空人数比'), ('top_position', 2, '大户持仓多空比')):
        rows = ratio_rows(body[idx])
        # Daily rows are stamped at the period start; the newest reading comes from the hourly series.
        hourly = ratio_rows(body[3 if key == 'long_short' else 4])
        if hourly:
            rows = rows + hourly
        if rows:
            last = rows[-1]
            month = next((r for r in rows if abs(last['t'] - r['t'] - 30 * 86400000) <= 43200000), None)
            out[key] = {**metric(last['ratio'], datetime.fromtimestamp(last['t'] / 1000, timezone.utc).isoformat(),
                                 'Binance Futures', 12,
                                 f'{label}。全体账户按人数计；大户为保证金前 20% 账户，按持仓计。'),
                        'longPct': round(last['long'] * 100, 1) if last['long'] is not None else None,
                        'ago30': month['ratio'] if month else None}
    end = int(now.timestamp() * 1000)
    raw = safe_get(f'https://www.deribit.com/api/v2/public/get_volatility_index_data?currency={symbol}'
                   f'&start_timestamp={end - 33 * 86400000}&end_timestamp={end}&resolution=3600', errors)
    rows = [(number(r[0]), number(r[4])) for r in ((raw or {}).get('result') or {}).get('data') or []
            if isinstance(r, list) and len(r) >= 5]
    rows = sorted((t, v) for t, v in rows if t is not None and v and t + 3600000 <= end)
    if rows:
        t, v = rows[-1]
        month = next((x for x in rows if abs(t - x[0] - 30 * 86400000) <= 3600000), None)
        out['dvol'] = {**metric(v, datetime.fromtimestamp((t + 3600000) / 1000, timezone.utc).isoformat(), 'Deribit', 12,
                                'DVOL：Deribit 30 日期权隐含波动率指数，最近完整小时。'),
                       'ago30': month[1] if month else None}
    book = safe_get(f'https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={symbol}&kind=option', errors)
    # Judge the book's age at the moment it arrived, not at the start of the build.
    rr = options_rr.rr25_30d((book or {}).get('result'), datetime.now(timezone.utc))
    if rr:
        out['rr25'] = metric(rr['value'], rr['asOf'], 'Deribit', 12,
                             f"25Δ 风险逆转 = 25Δ 看涨 IV − 25Δ 看跌 IV（{rr['tenor']}），负值表示看跌期权更贵。"
                             '由 Deribit 期权标记 IV 按 Black-Scholes 远期 delta 计算。')
    return out


class ETFTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], [], None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th'):
            self.cell = ''

    def handle_data(self, text):
        if self.cell is not None:
            self.cell += text

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell = None
        if tag == 'tr' and self.row:
            self.rows.append(self.row)


def parse_etf(html, now=None):
    now = now or datetime.now(timezone.utc)
    parser = ETFTableParser()
    parser.feed(html)
    out, total_idx = {}, None
    for row in parser.rows:
        if 'Total' in row and ('Date' in row or row[0] == ''):
            total_idx = row.index('Total')
            continue
        if total_idx is None or len(row) <= total_idx:
            continue
        try:
            day = datetime.strptime(row[0], '%d %b %Y').date()
        except ValueError:
            continue
        # US-listed ETFs report after the US close; a row for the current UTC day is still partial.
        if day > now.date() or (day == now.date() and now.hour < 23):
            continue
        text = row[total_idx].replace(',', '').replace('−', '-')
        value = number('-' + text[1:-1] if text.startswith('(') and text.endswith(')') else text)
        if value is not None:
            # Farside fills late-reporting funds as they arrive (often 0.0 until then), so the
            # newest session and any row with an unreported '-' cell are marked provisional.
            close = datetime(day.year, day.month, day.day, 21, tzinfo=timezone.utc)
            pending = any(c.strip() in ('-', '') for c in row[1:total_idx]) or (now - close).total_seconds() < 36 * 3600
            out[day.isoformat()] = {'date': day.isoformat(), 'value': value, **({'provisional': True} if pending else {})}
    return sorted(out.values(), key=lambda r: r['date'])[-10:]


def fetch_etf(symbol, errors):
    url = 'https://farside.co.uk/' + ('bitcoin-etf/' if symbol == 'BTC' else 'eth/')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (FlowHunt public-data research)'})
        with urllib.request.urlopen(req, timeout=25) as response:
            rows = parse_etf(response.read().decode('utf-8'))
        if not rows:
            raise ValueError('no dated rows')
        return {'rows': rows, 'source': 'Farside', 'sourceUrl': url, 'asOf': rows[-1]['date'], 'unit': 'USD million'}
    except Exception as exc:
        errors.append({'url': url, 'error': type(exc).__name__})
        return None


# ---------------------------------------------------------------- assembly

def build_table(symbol, closes, store, fear_alt):
    feats = S.price_features(closes)
    table = dict(feats)
    series = store.get('series', {})
    price = feats['price']
    if symbol == 'BTC':
        for key in ('supply_profit', 'sopr', 'mvrv_z', 'mvrv', 'puell', 'sth_cost', 'sth_profit', 'lth_cost',
                    'realized_price', 'true_mean', 'lth_net30'):
            table[key] = dict(series.get(key, {}))
        table['hash_ribbon'] = S.hash_ribbon(series.get('hashrate', {}))
        table['whale_net30'] = S.change_over(series.get('whale_1k_10k', {}), 30)
        table['fear'] = fear_alt
        # Each close is divided by the latest cost still valid on that day (costs publish a day late),
        # so the ratio never pairs today's cost with an older price or vice versa.
        for key, base in (('sth_mvrv', 'sth_cost'), ('lth_ratio', 'lth_cost')):
            table[key] = {}
            for day, p in price.items():
                cost = S.asof(table[base], day, 4)
                if cost and cost[1] > 0:
                    table[key][day] = p / cost[1]
    else:
        table['mvrv'] = dict(series.get('eth_mvrv', {}))
        # ETH realized price follows from MVRV on the same day.
        table['realized_price'] = {day: price[day] / v for day, v in table['mvrv'].items() if price.get(day) and v}
    return table


PRICE_KEYS = {'price', 'ma200d', 'high90', 'ma200w', 'weekly_rsi', 'mayer', 'price_ma200w', 'drawdown90', 'pi_bottom', 'fear'}


def publication_lag(symbol, key):
    """Days between an observation's date and the day a live reader could have had it."""
    if key in PRICE_KEYS:
        return 0  # closed daily candles and the fear index are out the same day
    if symbol == 'ETH' and key in ('mvrv', 'realized_price'):
        return 6  # BGeometrics publishes ETH MVRV about a week late
    return 1      # BGeometrics series, and anything derived from them, land the next day


def item_payload(item, table, today, price_series, backtest_end, lags=None, days=None):
    key, label, op, threshold, unit, linked, max_age = item
    series = table.get(key, {})
    found = S.asof(series, today, max_age)
    payload = {'key': key, 'label': label, 'op': op, 'threshold': threshold, 'unit': unit, 'linked': linked,
               'maxAgeDays': max_age, 'source': KEY_SOURCE.get(key, ''), 'sourceUrl': SOURCES.get(KEY_SOURCE.get(key, '')),
               'note': NOTES.get('eth_mvrv' if label == 'ETH MVRV' else key, ''), 'value': None, 'asOf': None, 'triggered': None, 'gap': None}
    latest = max(series) if series else None
    if found:
        day, value = found
        payload.update(value=value, asOf=day, triggered=S.evaluate(op, threshold, value),
                       gap=S.gap(item, value, price_series.get(day)))
    elif latest:
        payload.update(value=series[latest], asOf=latest, stale=True)
    if series:
        start = max(min(series), min(price_series))
        lit = S.lit_days(series, item, days or sorted(price_series), (lags or {}).get(key, 0))
        payload['backtest'] = S.backtest(lit, price_series, start, backtest_end)
    if key in ('lth_net30', 'whale_net30'):
        payload['spark'] = [[k, round(series[k], 1)] for k in sorted(series)[-90:]]
    return payload


def build_asset(symbol, closes, store, fear_alt, now):
    groups_def = S.BTC_GROUPS if symbol == 'BTC' else S.ETH_GROUPS
    table = build_table(symbol, closes, store, fear_alt)
    price = table['price']
    today = closes[-1][0]
    # Signals are judged as of the current UTC day; the last closed candle is normally yesterday.
    eval_day = now.date().isoformat()
    days = [day for day, _ in closes]
    backtest_end = today
    lags = {key: publication_lag(symbol, key) for key in table}
    # A candle history that ends days ago cannot describe "now": current sections are withheld.
    candles_fresh = (now.date() - S.d(today)).days <= 3
    groups = []
    for group in groups_def:
        groups.append({'id': group['id'], 'title': group['title'], 'weight': group['weight'],
                       'description': group['description'],
                       'items': [item_payload(i, table, eval_day, price, backtest_end, lags, days) for i in group['items']]})
    raw = {}
    for key in ('price', 'ma200d', 'ma200w', 'high90', 'drawdown90', 'sth_cost', 'lth_cost', 'realized_price', 'true_mean'):
        found = S.asof(table.get(key, {}), today, 9 if key == 'ma200w' else 4)
        if found:
            raw[key] = metric(found[1], found[0], KEY_SOURCE.get(key, 'Binance'), 216 if key == 'ma200w' else 72 if key in ('price', 'ma200d', 'high90', 'drawdown90') else 120,
                              NOTES.get(key, ''))
    # Score / count history, evaluated on every day the inputs allow.
    history_days = days[-365:]
    out = {'symbol': symbol, 'asOf': today, 'groups': groups, 'metrics': raw, 'methodVersion': METHOD_VERSION}
    if symbol == 'BTC':
        onchain_start = min(table['sth_cost']) if table['sth_cost'] else today
        score_days = [d for d in days if d >= onchain_start]
        # History is evaluated on what was published by each day; today's reading uses the latest data.
        scores = {d: S.score_on(groups_def, table, d, lags) for d in score_days}
        out['score'] = S.score_on(groups_def, table, eval_day)
        out['verdict'] = dict(zip(('code', 'label'), S.verdict(out['score']['lower'])))
        out['scoreHistory'] = [[d, scores[d]['lower'], price[d]] for d in score_days]
        combo_days = {d for d in days if S.combo_on(table, d, lags)}
        sth = S.asof(table['sth_cost'], today, 4)
        high90 = table['high90'].get(today)
        out['combo'] = {
            'met': S.combo_on(table, today) if candles_fresh else None,
            'conditions': [
                {'id': 'sth', 'label': '跌破短期持有者成本', 'triggerPrice': sth[1] if sth else None,
                 'asOf': sth[0] if sth else None, 'source': 'BGeometrics', 'note': 'STH 实现价格（持币 <155 天筹码的平均成本）'},
                {'id': 'drawdown', 'label': '距 90 天收盘高点跌 ≥20%', 'triggerPrice': high90 * 0.8 if high90 else None,
                 'asOf': today, 'source': 'Binance', 'high90': high90, 'note': '90 天收盘高点 × 0.8'},
            ],
            'backtest': S.backtest(combo_days, price, max(onchain_start, days[0]), backtest_end),
        }
        bands = {}
        for floor in (20, 50):
            lit = {d for d, s in scores.items() if s['lower'] >= floor}
            bands[str(floor)] = S.backtest(lit, price, onchain_start, backtest_end)
        out['scoreBacktest'] = bands
        # Position band: reference line = max(200-week MA, STH cost), with days spent above it.
        above, streak, prev = {}, 0, None
        for d in days:
            ma, sc = table['ma200w'].get(d), S.asof(table['sth_cost'], d, 4)
            if prev is not None and (S.d(d) - S.d(prev)).days != 1:
                streak = 0  # a missing candle breaks "consecutive days above"
            prev = d
            if ma is None or sc is None:
                streak = 0
                continue
            line = max(ma, sc[1])
            streak = streak + 1 if price[d] >= line else 0
            above[d] = (line, streak)
        ma200w, ref = table['ma200w'].get(today), above.get(today)
        if ma200w and ref and candles_fresh:
            line, streak = ref
            zone = 0 if price[today] < ma200w else 1 if price[today] < line else 2 if streak < 28 else 3
            out['band'] = {'ma200w': ma200w, 'line': line, 'sthCost': sth[1] if sth else None, 'zone': zone,
                           'daysAbove': streak, 'asOf': today}
        cohorts = {}
        for key, label, note in (('whale_1k_10k', '巨鲸 1k–10k BTC', '地址余额口径'),
                                 ('whale_10k_plus', '超大户 ≥10k BTC', '含交易所冷钱包'),
                                 ('retail_lt1', '散户 <1 BTC', '地址余额口径'),
                                 ('lth_net30', 'LTH 30天净变化', '长期持有者供给')):
            ser = store.get('series', {}).get(key, {})
            if not ser:
                continue
            last = max(ser)
            entry = {'label': label, 'note': note, 'asOf': last, 'value': ser[last],
                     'stale': (now.date() - S.d(last)).days > 6}
            if key != 'lth_net30':
                for n in (7, 30):
                    old = ser.get((datetime.fromisoformat(last) - timedelta(days=n)).date().isoformat())
                    entry[f'd{n}'] = ser[last] - old if old is not None else None
            entry['spark'] = [[k, round(ser[k], 1)] for k in sorted(ser)[-90:]]
            cohorts[key] = entry
        out['cohorts'] = cohorts
        combo_line = {d: min(S.asof(table['sth_cost'], d, 4)[1], table['high90'][d] * 0.8)
                      for d in history_days if S.asof(table['sth_cost'], d, 4) and d in table['high90']}
    else:
        lit_counts = {}
        for d in days:
            n = 0
            for item in groups_def[0]['items']:
                found = S.asof(table.get(item[0], {}), d, item[6], lags.get(item[0], 0))
                n += bool(found and S.evaluate(item[2], item[3], found[1]))
            lit_counts[d] = n
        out['scoreHistory'] = [[d, lit_counts[d], price[d]] for d in days[-1460:]]
        out['score'] = {'lit': sum(1 for i in groups[0]['items'] if i['triggered']), 'total': len(groups_def[0]['items']),
                        'known': sum(1 for i in groups[0]['items'] if i['triggered'] is not None)}
        combo_line = {}
    ladder = []
    p_today = price[today]

    def rung(label, value, as_of, meaning, source):
        if value:
            ladder.append({'label': label, 'value': value, 'asOf': as_of, 'meaning': meaning, 'source': source,
                           'pct': (value / p_today - 1) * 100})
    rung('最近日收盘', p_today, today, '', 'Binance')
    if table['ma200d'].get(today):
        rung('Mayer 0.8 价', table['ma200d'][today] * 0.8, today, 'Mayer 倍数 <0.8', 'Binance')
        rung('200 日均线', table['ma200d'][today], today, '日线趋势分界', 'Binance')
    if table['ma200w'].get(today):
        rung('200 周均线', table['ma200w'][today], today, '价格/200周均线 <1', 'Binance')
    if table['high90'].get(today):
        rung('90天高点 × 0.8', table['high90'][today] * 0.8, today, '回撤 ≥20%' + ('（组合②）' if symbol == 'BTC' else ''), 'Binance')
    cost_age = 8 if symbol == 'ETH' else 4  # same windows as the MVRV / cost signals
    for key, label, meaning in (('true_mean', 'True Mean 成本', '活跃投资者平均成本'),
                                ('sth_cost', 'STH 成本', '跌破即组合①；STH-MVRV <1'),
                                ('realized_price', '实现价格', 'MVRV <1'),
                                ('lth_cost', 'LTH 成本', '价格/LTH 成本 <1')):
        found = S.asof(table.get(key, {}), eval_day, cost_age)
        if found:
            rung(label, found[1], found[0], meaning, 'BGeometrics' if symbol == 'BTC' else 'BGeometrics（由 ETH MVRV 换算）')
    ladder.sort(key=lambda r: -r['value'])
    out['ladder'] = ladder
    out['history'] = [{'date': d, 'close': price[d], 'ma200': round(table['ma200d'][d], 2) if d in table['ma200d'] else None,
                       'trigger': round(combo_line[d], 2) if d in combo_line else None} for d in history_days]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/observatory.json')
    parser.add_argument('--store', type=Path, default=ROOT / 'data/onchain-history.json')
    parser.add_argument('--offline-onchain', action='store_true', help='Use the stored on-chain history without calling BGeometrics')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    previous = load_file(args.output)
    errors = []
    store = onchain_store.load(args.store)
    if not args.offline_onchain:
        store, chain_errors = onchain_store.refresh(store, now)
        errors.extend(chain_errors)
        onchain_store.save(store, args.store)
    fear_alt = fetch_fear_alt(errors)
    fear_cmc = fetch_fear_cmc(errors, now)
    assets = {}
    for symbol in ('BTC', 'ETH'):
        closes = fetch_candles(symbol, errors, now)
        old = (previous.get('assets') or {}).get(symbol)
        if not closes:
            if old:
                assets[symbol] = {**old, 'carried': True}  # last good snapshot, flagged; the run still fails
            continue
        asset = build_asset(symbol, closes, store, fear_alt, now)
        asset['derivatives'] = fetch_derivatives(symbol, errors, now)
        for key, entry in ((old or {}).get('derivatives') or {}).items():
            # A failed source keeps its last observation and original time; the page judges expiry.
            asset['derivatives'].setdefault(key, {**entry, 'carriedForward': True})
        asset['etf'] = fetch_etf(symbol, errors) or (old or {}).get('etf')
        sentiment = {}
        for key, ser, src in (('fear', fear_alt, 'Alternative.me'), ('cmc_fear', fear_cmc, 'CoinMarketCap')):
            if ser:
                last = max(ser)
                prev = ser.get((datetime.fromisoformat(last) - timedelta(days=1)).date().isoformat())
                sentiment[key] = {**metric(ser[last], last + 'T00:00:00+00:00', src, 48,
                                           'BTC 市场情绪，0=极度恐慌，100=极度贪婪。'),
                                  'prev': prev}
        asset['sentiment'] = sentiment
        if symbol == 'ETH':
            legacy = load_file(ROOT / 'eth-data.json')
            dates = legacy.get('as_of') or {}
            facts = []
            for key, label, unit, src in (
                    ('staked_pct', '质押占比', '%', 'validatorqueue'), ('total_staked', '总质押量', ' ETH', 'validatorqueue'),
                    ('burn_rate_daily', '每日销毁', ' ETH', 'Ethereum RPC'), ('burn_issuance_pct', '销毁 / 估算增发', '%', 'Ethereum RPC'),
                    ('stake_conc_top5', '流动性质押前五集中度', '%', 'DefiLlama'), ('whale_top100_pct', '前百地址持仓', '%', 'Blockscout'),
                    ('holder_count', '非零余额地址', '', 'Coin Metrics'), ('active_addr_7d', '7日均活跃地址', '', 'Coin Metrics'),
                    ('stablecoin_mcap_b', '链上稳定币规模', ' B USD', 'DefiLlama'), ('stablecoin_change_30d', '稳定币 30天变化', '%', 'DefiLlama')):
                observed = dates.get(key)
                if key == 'burn_issuance_pct':
                    deps = [dates.get('burn_rate_daily'), dates.get('total_staked')]
                    observed = min(deps) if all(deps) else None
                facts.append({'key': key, 'label': label, 'unit': unit,
                              **metric(legacy.get(key), observed, src, 72,
                                       '近 7200 个区块基础费销毁估算，不含 blob 费用。' if key == 'burn_rate_daily' else
                                       '销毁量 ÷ 由质押量估算的共识层增发，非完整增发统计。' if key == 'burn_issuance_pct' else
                                       '前 100 个地址含质押合约、交易所与跨链桥，不等于巨鲸实体。' if key == 'whale_top100_pct' else
                                       '只统计流动性质押协议（Lido 等）前五家占比，不含交易所直接质押与独立验证者。' if key == 'stake_conc_top5' else '')})
            asset['facts'] = facts
        assets[symbol] = asset
    payload = {'schemaVersion': 2, 'generatedAt': datetime.now(timezone.utc).isoformat(), 'assets': assets,
               'onchainFetched': store.get('fetched', {}), 'errors': errors,
               'sources': [{'name': k, 'url': v} for k, v in SOURCES.items() if k != 'FlowHunt 计算']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8')
    for symbol, asset in assets.items():
        items = [i for g in asset['groups'] for i in g['items']]
        known = sum(i['triggered'] is not None for i in items)
        print(f'{symbol}: {known}/{len(items)} signals with fresh inputs; as of {asset.get("asOf")}')
    print(f'Source failures: {len(errors)}')
    for e in errors[:12]:
        print('  ', e['error'], e['url'][:110])
    def current(asset):
        try:
            return not asset.get('carried') and (now.date() - S.d(asset['asOf'])).days <= 3
        except (KeyError, TypeError, ValueError):
            return False
    # A green run must mean both assets were rebuilt from candles no older than three days.
    return 0 if len(assets) == 2 and all(current(a) for a in assets.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
