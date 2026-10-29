#!/usr/bin/env python3
"""Build a public-data BTC/ETH snapshot. No keys, paid parser or git side effects.

Daily observations and realtime quotes have separate timestamps. Failed sources
retain their original dates; missing/expired values never light a signal.
"""
import argparse
import concurrent.futures
import json
import math
import statistics
import urllib.request
from html.parser import HTMLParser
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'Binance': 'https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints',
    'BGeometrics': 'https://api.bitcoin-data.com/swagger-ui/index.html',
    'Alternative.me': 'https://alternative.me/crypto/fear-and-greed-index/',
    'Binance Futures': 'https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api',
    'Coin Metrics': 'https://docs.coinmetrics.io/',
    'DefiLlama': 'https://defillama.com/',
    'validatorqueue': 'https://www.validatorqueue.com/',
    'Blockscout': 'https://eth.blockscout.com/',
    'Ethereum RPC': 'https://ethereum.org/en/developers/docs/apis/json-rpc/',
    'Farside': 'https://farside.co.uk/bitcoin-etf/',
    'Deribit': 'https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data',
    'CoinMarketCap': 'https://coinmarketcap.com/charts/fear-and-greed-index/',
}


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def parsed_date(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    except (ValueError, TypeError):
        return None


def metric(value, as_of, source, now=None, max_hours=72, note=''):
    now = now or datetime.now(timezone.utc)
    value, stamp = number(value), parsed_date(as_of)
    hours = (now - stamp).total_seconds() / 3600 if stamp else None
    status = 'missing' if value is None else 'fresh' if hours is not None and 0 <= hours <= max_hours else 'stale'
    return {'value': value, 'asOf': as_of, 'source': source,
            'sourceUrl': SOURCES.get(source), 'status': status, 'maxAgeHours': max_hours, 'note': note}


def trigger(m, op, target):
    if m.get('status') != 'fresh' or m.get('value') is None:
        return None
    x = m['value']
    return {'<': lambda: x < target, '<=': lambda: x <= target,
            '>': lambda: x > target, '>=': lambda: x >= target}[op]()


def combine(values):
    return False if False in values else None if None in values else True


def bull_line(ma200w, sth_cost):
    return max(ma200w, sth_cost) if ma200w and sth_cost else None


def score_bounds(groups):
    low = high = available = total = 0
    for group in groups:
        items = group['items']
        weight = group['weight'] / len(items)
        for item in items:
            state = item['triggered']
            total += 1
            available += state is not None
            low += weight if state is True else 0
            high += weight if state is not False else 0
    return {'lower': round(low, 1), 'upper': round(high, 1), 'available': available, 'total': total}


def closed_candles(rows, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now.timestamp() * 1000
    points = {}
    for row in rows:
        try:
            close = number(row[4])
            opened,ended=number(row[0]),number(row[6])
            if close is None or close <= 0 or opened is None or ended is None or not 0 <= opened <= ended < cutoff:
                continue
            day = datetime.fromtimestamp(opened/1000, timezone.utc).date().isoformat()
            points[day] = {'date': day, 'close': close}
        except (ValueError, TypeError, IndexError, OverflowError):
            continue
    return sorted(points.values(), key=lambda p:p['date'])


def rsi(values, period=14):
    if len(values) <= period:
        return None
    changes = [b-a for a,b in zip(values, values[1:])]
    gain = sum(max(x, 0) for x in changes[:period]) / period
    loss = sum(max(-x, 0) for x in changes[:period]) / period
    for x in changes[period:]:
        gain = (gain*(period-1) + max(x, 0)) / period
        loss = (loss*(period-1) + max(-x, 0)) / period
    return 50 if gain == loss == 0 else 100 if loss == 0 else round(100 - 100/(1+gain/loss), 2)


def weekly_closes(points, now):
    # Only completed UTC weeks; Binance weeks start Monday.
    start = now.date() - timedelta(days=now.weekday())
    weeks = {}
    for p in points:
        day = datetime.fromisoformat(p['date']).date()
        if day < start:
            weeks[day.isocalendar()[:2]] = p
    return list(weeks.values())


BTC_RULES = [
    ('大底必要信号', '五项条件，亮起至少四项才进入深度观察', 40, [
        ('supply_profit','全网盈利占比','<',60,'%'), ('weekly_rsi','周线 RSI','<',35,''),
        ('miner_cost','矿工收入 / 成本','<',1,''), ('sopr','SOPR','<',1,''), ('mayer','Mayer 倍数','<',.8,'')]),
    ('大底确认信号', '链上估值与长期均线的交叉确认', 40, [
        ('mvrv_z','MVRV Z-Score','<',-1,''), ('supply_profit','全网盈利占比','<',50,'%'),
        ('price_ma200w','价格 / 200周均线','<',1,''), ('mvrv','MVRV','<',1,''),
        ('nupl','NUPL','<',0,''), ('puell','Puell Multiple','<',.5,''),
        ('weekly_rsi','周线 RSI','<',30,''), ('pi_cycle','Pi Cycle 底部','<',1,'')]),
    ('相对底部信号', '短期持有者、情绪与回撤的共同观察', 20, [
        ('sth_mvrv','STH-MVRV','<',1,''), ('sth_profit','STH 盈利占比','<',30,'%'),
        ('fear','恐慌指数','<=',20,''), ('hash_ribbon','哈希带投降','>',0,''),
        ('lth_net30','LTH 30天净变化','>',0,' BTC'), ('whale_net30','巨鲸 30天净变化','>',0,' BTC'),
        ('puell','Puell Multiple','<',.7,''), ('drawdown90','90天高点回撤','>=',20,'%')]),
]
ETH_RULES = [
    ('价格与周期', 'ETH 独立技术观察，不套用 BTC 链上模型', 0, [
        ('weekly_rsi','周线 RSI','<',35,''), ('mayer','Mayer 倍数','<',.8,''),
        ('price_ma200w','价格 / 200周均线','<',1,''), ('drawdown90','90天高点回撤','>=',20,'%')]),
    ('供给与质押', '原生 ETH 供给结构；展示事实，不计入 BTC 分数', 0, [
        ('staked_pct','质押占比',None,None,'%'), ('total_staked','总质押量',None,None,' ETH'),
        ('burn_rate_daily','每日销毁',None,None,' ETH'), ('burn_issuance_pct','销毁 / 估算增发',None,None,'%'),
        ('stake_conc_top5','质押前五集中度',None,None,'%'), ('whale_top100_pct','前百地址持仓',None,None,'%')]),
    ('网络与流动性', '地址口径不等于实体口径，缺少 cohort 数据时不推断', 0, [
        ('holder_count','非零持币地址',None,None,''), ('active_addr_7d','7日均活跃地址',None,None,''),
        ('stablecoin_mcap_b','链上稳定币规模',None,None,' B USD'),
        ('stablecoin_change_30d','稳定币 30天变化',None,None,'%')]),
]


def build_asset(symbol, points, chain, extras, legacy, now=None):
    now = now or datetime.now(timezone.utc)
    metrics = {}
    day = points[-1]['date'] if points else None
    prices = [p['close'] for p in points]
    price = prices[-1] if prices else None
    weeks = weekly_closes(points, now)
    ma200 = statistics.mean(prices[-200:]) if len(prices) >= 200 else None
    ma200w = statistics.mean([p['close'] for p in weeks[-200:]]) if len(weeks) >= 200 else None
    high90 = max(prices[-90:]) if len(prices) >= 90 else None
    values = {'price': price, 'ma200d': ma200, 'ma200w': ma200w, 'high90': high90,
              'mayer': price/ma200 if price and ma200 else None,
              'price_ma200w': price/ma200w if price and ma200w else None,
              'weekly_rsi': rsi([p['close'] for p in weeks]),
              'drawdown90': max(0,(1-price/high90)*100) if price and high90 else None}
    for key,value in values.items():
        metrics[key] = metric(value, weeks[-1]['date'] if key in ('weekly_rsi','ma200w') and weeks else day,
                              'Binance', now, max_hours=216 if key in ('weekly_rsi','ma200w') else 72)
    if symbol == 'BTC':
        mapping = {'mvrv': 'mvrv', 'mvrv_z':'mvrvZscore','sopr':'sopr','puell':'puellMultiple', 'realized_price':'realizedPrice'}
        for key,field in mapping.items():
            metrics[key] = metric(chain.get(field), chain.get('date'), 'BGeometrics', now)
        mvrv = metrics['mvrv']
        metrics['nupl'] = metric(1-1/mvrv['value'] if mvrv['value'] and mvrv['value']>0 else None,
                                 mvrv['asOf'], 'BGeometrics', now, note='由同日 MVRV 计算：1 − 1/MVRV')
        for key in ('sth_cost','sth_mvrv','sth_profit','supply_profit','true_mean','lth_cost'):
            row = extras.get(key) or {}
            metrics[key] = metric(row.get('value'), row.get('date'), 'BGeometrics', now,
                                   note='公共接口可能延迟；严格按数据实际日期判断新鲜度')
        fear = extras.get('fear') or {}
        metrics['fear'] = metric(fear.get('value'), fear.get('date'), 'Alternative.me', now, max_hours=48,
                                 note='Bitcoin 情绪指数，非 ETH 专属情绪')
        metrics['cmc_fear'] = metric(None,None,'CoinMarketCap',now,note='CMC 独立口径暂未接通；不使用 Alternative.me 数值替代。')
        for key in ('miner_cost','pi_cycle','hash_ribbon','lth_net30','whale_net30'):
            metrics[key] = metric(None,None,'',now,note='暂无已核验、口径一致的公开数据；不参与确认')
    else:
        source_fields = {
            'staked_pct':'validatorqueue','total_staked':'validatorqueue','burn_rate_daily':'Ethereum RPC',
            'burn_issuance_pct':'Ethereum RPC','stake_conc_top5':'DefiLlama','whale_top100_pct':'Blockscout',
            'holder_count':'Coin Metrics','active_addr_7d':'Coin Metrics',
            'stablecoin_mcap_b':'DefiLlama','stablecoin_change_30d':'DefiLlama'}
        dates = legacy.get('as_of') or {}
        for key,source in source_fields.items():
            # Do not label missing field dates with the new collector timestamp.
            observed = dates.get(key)
            if key == 'burn_issuance_pct':
                dependencies = [dates.get('burn_rate_daily'), dates.get('total_staked')]
                observed = min(dependencies) if all(parsed_date(d) for d in dependencies) else None
            metrics[key] = metric(legacy.get(key), observed, source, now)
        metrics['burn_rate_daily']['note'] = '近7200区块基础费销毁估算，不含 blob 费用；区块 gasLimit 采用最新值。'
        metrics['burn_issuance_pct']['note'] = '销毁量除以由质押量估算的共识增发；依赖源日期取最早值，非实际完整增发统计。'
    for key,entry in extras.get('derivatives',{}).items():
        metrics[key] = metric(entry.get('value'), entry.get('date'), entry.get('source','Binance Futures'), now, max_hours=12,
                              note='DVOL 30日期权隐含波动率指数，采用最近完整小时观测值。' if key=='dvol' else
                                   'Binance 最近5分钟的账户数多空比，不等于资金或持仓金额比。' if key=='long_short' else
                                   '该交易所返回的最新资金费率；未假设固定8小时结算，也未换算年化。')
    for key in ('funding','long_short'):
        metrics.setdefault(key, metric(None,None,'Binance Futures',now,max_hours=12))
    metrics.setdefault('dvol',metric(None,None,'Deribit',now,max_hours=12))
    metrics['risk_reversal25']=metric(None,None,'Deribit',now,note='25Δ 风险逆转需要明确到期期限与看涨/看跌符号口径；参考图未提供完整定义，暂不推断。')
    rules = BTC_RULES if symbol == 'BTC' else ETH_RULES
    groups = []
    for title,description,weight,items in rules:
        group = {'title':title,'description':description,'weight':weight,'items':[]}
        for key,label,op,threshold,unit in items:
            group['items'].append({'key':key,'label':label,'op':op,'threshold':threshold,'unit':unit,
                                   'triggered':trigger(metrics[key],op,threshold) if op else None})
        groups.append(group)
    history = []
    for idx,p in enumerate(points):
        if idx < len(points)-365:
            continue
        window = points[max(0,idx-199):idx+1]
        history.append({**p,'ma200':round(statistics.mean(q['close'] for q in window),2) if len(window)==200 else None})
    return {'symbol':symbol,'metrics':metrics,'groups':groups,'history':history,
            'score':score_bounds(groups) if symbol=='BTC' else None,
            'historySource':'Binance','historyAsOf':day,
            'methodVersion':'flowhunt-observation-v1',
            'definition':'公开数据观察框架，非参考作者模型复刻；未回测历史命中率'}


def get_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'FlowHunt-observatory/1.0 (+https://btc.flowhunt.net)'})
    with urllib.request.urlopen(req,timeout=25) as response:
        return json.load(response)


def safe_get(url, errors):
    try:
        return get_json(url)
    except Exception as exc:
        errors.append({'url':url,'error':type(exc).__name__})
        return None


def load_file(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        return {}


def fetch_candles(symbol, errors, now):
    base=f'https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=1d&limit=1000'
    newest=safe_get(base,errors)
    if not isinstance(newest,list) or not newest:
        return []
    older=safe_get(base+f'&endTime={int(newest[0][0])-1}',errors)
    return closed_candles((older if isinstance(older,list) else [])+newest, now)


def fetch_derivatives(symbol, errors):
    out={}
    funding=safe_get(f'https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}USDT',errors)
    if isinstance(funding,dict) and number(funding.get('time')):
        n=number(funding.get('lastFundingRate'))
        out['funding']={'value':n*100 if n is not None else None,
                        'date':datetime.fromtimestamp(float(funding['time'])/1000,timezone.utc).isoformat()}
    ls=safe_get(f'https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={symbol}USDT&period=5m&limit=1',errors)
    if isinstance(ls,list) and ls and number(ls[-1].get('timestamp')):
        row=ls[-1]
        out['long_short']={'value':number(row.get('longShortRatio')),
                           'date':datetime.fromtimestamp(float(row['timestamp'])/1000,timezone.utc).isoformat()}
    end=int(datetime.now(timezone.utc).timestamp()*1000)
    raw=safe_get(f'https://www.deribit.com/api/v2/public/get_volatility_index_data?currency={symbol}&start_timestamp={end-86400000}&end_timestamp={end}&resolution=3600',errors)
    dvol=dvol_observation(raw)
    if dvol:
        out['dvol']={**dvol,'source':'Deribit'}
    return out


def dvol_observation(raw,now=None):
    now=now or datetime.now(timezone.utc)
    rows=((raw or {}).get('result') or {}).get('data') or []
    valid=[]
    for row in rows:
        if not isinstance(row,list) or len(row)<5:
            continue
        stamp,value=number(row[0]),number(row[4])
        if stamp is not None and stamp>=0 and value is not None and value>0 and stamp+3600000<=now.timestamp()*1000:
            valid.append((stamp,value))
    if not valid:
        return {}
    stamp,value=max(valid)
    return {'value':value,'date':datetime.fromtimestamp((stamp+3600000)/1000,timezone.utc).isoformat()}


def latest_endpoint(raw, fields):
    row=raw[-1] if isinstance(raw,list) and raw else raw
    if not isinstance(row,dict):
        return {}
    value=next((number(row[f]) for f in fields if number(row.get(f)) is not None),None)
    return {'value':value,'date':row.get('d') or row.get('date') or row.get('day')}


class ETFTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows=[]
        self.row=[]
        self.cell=None

    def handle_starttag(self,tag,attrs):
        if tag=='tr': self.row=[]
        if tag in ('td','th'): self.cell=''

    def handle_data(self,text):
        if self.cell is not None: self.cell+=text

    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell=None
        if tag=='tr' and self.row:
            self.rows.append(self.row)


def parse_etf(html,now=None):
    now=now or datetime.now(timezone.utc)
    parser=ETFTableParser()
    parser.feed(html)
    out={}
    total_idx=None
    for row in parser.rows:
        if 'Total' in row and ('Date' in row or row[0]==''):
            total_idx=row.index('Total')
            continue
        if total_idx is None or len(row)<=total_idx:
            continue
        try:
            day=datetime.strptime(row[0],'%d %b %Y').date()
        except ValueError:
            continue
        if day>now.date():
            continue
        text=row[total_idx].replace(',','').replace('\u2212','-')
        value=number('-'+text[1:-1] if text.startswith('(') and text.endswith(')') else text)
        if value is not None:
            out[day.isoformat()]={'date':day.isoformat(),'value':value}
    return sorted(out.values(),key=lambda r:r['date'])[-10:]


def fetch_etf(symbol,errors):
    url='https://farside.co.uk/'+('bitcoin-etf/' if symbol=='BTC' else 'eth/')
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (FlowHunt public-data research)'})
        with urllib.request.urlopen(req,timeout=25) as response:
            rows=parse_etf(response.read().decode('utf-8'))
        if not rows:
            raise ValueError('no dated rows')
        return {'rows':rows,'source':'Farside','sourceUrl':url,'asOf':rows[-1]['date'],'unit':'USD million'}
    except Exception as exc:
        errors.append({'url':url,'error':type(exc).__name__})
        return None


def updated_chain_cache(previous, snapshot, fetched_at):
    return {'fetchedAt':fetched_at,'snapshot':snapshot,'extras':dict(previous.get('extras') or {})}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'data/observatory.json')
    args=parser.parse_args()
    now=datetime.now(timezone.utc)
    previous=load_file(args.output)
    errors=[]
    chain_cache=previous.get('chainCache') or {}
    stamp=parsed_date(chain_cache.get('fetchedAt'))
    if not stamp or not 0 <= (now-stamp).total_seconds() < 86400:
        snapshot=safe_get('https://api.bitcoin-data.com/v1/snapshot',errors)
        if isinstance(snapshot,dict) and snapshot.get('date'):
            chain_cache=updated_chain_cache(chain_cache,snapshot,now.isoformat())
            endpoints={
                'sth_cost':('realized-price-sth',('realizedPriceSth','realizedPriceSTH','realizedPrice','sthRealizedPrice')),
                'sth_mvrv':('sth-mvrv',('sthMvrv','sthMVRV','mvrv')),
                'sth_profit':('percent-sth-in-profit',('percentSthInProfit',)),
                'supply_profit':('supply-in-profit-pct',('supplyInProfitPct',)),
            }
            for key,(endpoint,fields) in endpoints.items():
                raw=safe_get(f'https://api.bitcoin-data.com/v1/{endpoint}/last',errors)
                parsed=latest_endpoint(raw,fields)
                if parsed.get('value') is not None and parsed_date(parsed.get('date')):
                    chain_cache['extras'][key]=parsed
    cost_attempt=parsed_date(chain_cache.get('costAttemptAt'))
    if not cost_attempt or not 0 <= (now-cost_attempt).total_seconds()<86400:
        for key,endpoint,fields in (
            ('true_mean','true-market-mean',('trueMarketMean','trueMarketMeanPrice')),
            ('lth_cost','realized-price-lth',('realizedPriceLth','realizedPriceLTH','lthRealizedPrice'))):
            raw=safe_get(f'https://api.bitcoin-data.com/v1/{endpoint}/last',errors)
            row=latest_endpoint(raw,fields)
            if row.get('value') is not None and parsed_date(row.get('date')):
                chain_cache.setdefault('extras',{})[key]=row
        chain_cache['costAttemptAt']=now.isoformat()
    fng=safe_get('https://api.alternative.me/fng/?limit=2',errors)
    fear=(previous.get('fear') or {})
    if isinstance(fng,dict) and fng.get('data'):
        row=fng['data'][0]
        stamp=number(row.get('timestamp'))
        if stamp:
            fear={'value':number(row.get('value')),'date':datetime.fromtimestamp(stamp,timezone.utc).isoformat()}
    assets={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures={symbol:pool.submit(fetch_candles,symbol,errors,now) for symbol in ('BTC','ETH')}
        for symbol,future in futures.items():
            points=future.result()
            if not points:
                # Price calculations need the full history; retain old computed values unchanged instead.
                old=(previous.get('assets') or {}).get(symbol)
                if old:
                    for key,m in old['metrics'].items():
                        m.update(metric(m.get('value'),m.get('asOf'),m.get('source'),now,
                                        m.get('maxAgeHours',72),m.get('note','')))
                    for group in old['groups']:
                        for item in group['items']:
                            item['triggered']=trigger(old['metrics'][item['key']],item['op'],item['threshold']) if item['op'] else None
                    old['score']=score_bounds(old['groups']) if symbol=='BTC' else None
                    assets[symbol]=old
                    continue
            extras={**(chain_cache.get('extras') or {}),'fear':fear,'derivatives':fetch_derivatives(symbol,errors)}
            legacy=load_file(ROOT/('data.json' if symbol=='BTC' else 'eth-data.json'))
            assets[symbol]=build_asset(symbol,points,chain_cache.get('snapshot') or {},extras,legacy,datetime.now(timezone.utc))
            assets[symbol]['etf']=fetch_etf(symbol,errors) or ((previous.get('assets') or {}).get(symbol) or {}).get('etf')
    payload={'schemaVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),'assets':assets,'fear':fear,
             'chainCache':chain_cache,'errors':errors,
             'sources':[{'name':k,'url':v} for k,v in SOURCES.items()]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n',encoding='utf-8')
    for symbol,asset in assets.items():
        fresh=sum(m['status']=='fresh' for m in asset['metrics'].values())
        print(f'{symbol}: {fresh}/{len(asset["metrics"])} fresh metrics, {len(asset["history"])} closed daily candles')
    print(f'Public source failures: {len(errors)}; retained dates are never refreshed on failure.')
    # Broken price acquisition must fail CI rather than publish a fully empty dashboard.
    return 0 if all(a['metrics']['price']['status']=='fresh' for a in assets.values()) else 1


if __name__=='__main__':
    raise SystemExit(main())
