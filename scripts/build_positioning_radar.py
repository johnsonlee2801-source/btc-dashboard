#!/usr/bin/env python3
"""Public Binance positioning snapshot. No keys, orders or paid endpoints."""
import argparse
import concurrent.futures
import copy
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = 'https://fapi.binance.com'
DOC = 'https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data'
FIELDS = ('topLong','accountLong','topDelta','accountDelta','oiUsd','oiUnits','oiDelta',
          'priceChange','volumeUsd','fundingRate','fundingHours','concentration','concentrationDelta',
          'circulation','unlockPct','unknownShare','lockedShare')


def number(value):
    if value is None or isinstance(value, bool) or value == '':return None
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):return None


def metric(value=None, as_of=None, note='', url=DOC, source='Binance Futures'):
    return {'value':value,'asOf':as_of,'source':source,'url':url,'note':note}


def latest(series, symbol, now, time_key='timestamp'):
    valid=[r for r in (series or []) if isinstance(r,dict) and r.get('symbol')==symbol
           and number(r.get(time_key)) is not None and 0<number(r[time_key])<=now]
    return max(valid,key=lambda r:float(r[time_key]),default=None)


def proportion(record):
    if not record:return None
    a,b=number(record.get('longAccount')),number(record.get('shortAccount'))
    return a if a is not None and b is not None and 0<=a<=1 and 0<=b<=1 and abs(a+b-1)<=.002 else None


def build_row(info, sources, previous, now):
    symbol=info['symbol']
    # Endpoints publish asynchronously. Prefer their newest common fresh window,
    # while retaining the full returned series for exact-24h comparisons.
    common=None
    for key in ('top','accounts','oi'):
        stamps=set()
        for record in sources.get(key) or []:
            if not isinstance(record,dict) or record.get('symbol')!=symbol:continue
            stamp=number(record.get('timestamp'))
            valid=proportion(record) is not None if key!='oi' else number(record.get('sumOpenInterestValue')) is not None and number(record.get('sumOpenInterestValue'))>=0
            if valid and stamp is not None and 0<=now-stamp<=10800000:stamps.add(stamp)
        common=stamps if common is None else common&stamps
    window=max(common) if common else now
    row={'symbol':symbol,'baseAsset':info['baseAsset'],'network':None,'address':None,
         'multiplier':None,'makers':[], 'metrics':{k:metric(note='暂无可核验数据') for k in FIELDS}}
    m=row['metrics']
    for source,key,delta in [('top','topLong','topDelta'),('accounts','accountLong','accountDelta')]:
        record=latest(sources.get(source),symbol,window)
        value=proportion(record)
        if value is not None:
            stamp=record['timestamp'];m[key]=metric(value,stamp)
            old=next((r for r in sources[source] if r.get('symbol')==symbol and r.get('timestamp')==stamp-86400000),None)
            old_value=proportion(old)
            if old_value is not None:
                m[delta]=metric(round((value-old_value)*100,8),stamp,'与恰好24h前的同窗口比较；单位为百分点')
                m[delta]['fromAsOf']=stamp-86400000
    record=latest(sources.get('oi'),symbol,window)
    if record:
        stamp=record['timestamp']
        for key,raw in [('oiUsd','sumOpenInterestValue'),('oiUnits','sumOpenInterest')]:
            value=number(record.get(raw))
            if value is not None and value>=0:m[key]=metric(value,stamp)
        old=next((r for r in sources['oi'] if r.get('symbol')==symbol and r.get('timestamp')==stamp-86400000),None)
        denominator=number(old.get('sumOpenInterestValue')) if old else None
        if denominator is not None and denominator>0 and m['oiUsd']['value'] is not None:
            m['oiDelta']=metric((m['oiUsd']['value']/denominator-1)*100,stamp,'名义金额变化受价格影响，不等于净流入')
            m['oiDelta']['fromAsOf']=stamp-86400000
    ticker=sources.get('ticker') or {}
    stamp=number(ticker.get('closeTime'))
    if ticker.get('symbol')==symbol and stamp is not None and 0<stamp<=now:
        for key,raw in [('priceChange','priceChangePercent'),('volumeUsd','quoteVolume')]:
            v=number(ticker.get(raw))
            if v is not None and (key!='volumeUsd' or v>=0):m[key]=metric(v,stamp,'滚动24小时')
    funding=latest(sources.get('funding'),symbol,now,'fundingTime')
    if funding and number(funding.get('fundingRate')) is not None:
        stamp=funding['fundingTime'];m['fundingRate']=metric(number(funding['fundingRate'])*100,stamp,'最近已结算费率；不是预测费率')
        before=latest(sources.get('funding'),symbol,stamp-1,'fundingTime')
        if before:
            hours=(stamp-before['fundingTime'])/3600000
            if 0<hours<=24:
                m['fundingHours']=metric(hours,stamp,'最近两次实际结算的间隔')
                # A settled rate remains the last settled rate for its interval.
                m['fundingRate']['maxAgeHours']=hours+3
                m['fundingHours']['maxAgeHours']=hours+3
    # Preserve failed fields, never give retained values a new observation date.
    if previous:
        for key in FIELDS:
            prior=previous.get('metrics',{}).get(key,{})
            if m[key]['value'] is None and number(prior.get('value')) is not None and number(prior.get('asOf')) is not None and 0<prior['asOf']<=now:
                parent={'topDelta':'topLong','accountDelta':'accountLong','oiDelta':'oiUsd'}.get(key)
                if parent and m[parent]['value'] is not None and m[parent]['asOf']!=prior['asOf']:continue
                if parent and sources.get({'topDelta':'top','accountDelta':'accounts','oiDelta':'oi'}[key]) is not None:continue
                m[key]=copy.deepcopy(prior);m[key]['note']='源不可用，保留原观测；'+prior.get('note','').replace('源不可用，保留原观测；','')
    return row


def apply_evidence(row, evidence, now):
    """Only explicitly matched, dated, source-linked evidence can populate chain fields.

    This is an ingestion contract, NOT a claim that public entity labels are complete.
    Concentration needs a full auditable balance ledger, not a supplied percentage.
    """
    if not isinstance(evidence,dict) or evidence.get('symbol')!=row['symbol'] or evidence.get('baseAsset')!=row['baseAsset']:return
    stamp=number(evidence.get('asOf'));url=evidence.get('url','')
    if stamp is None or not 0<stamp<=now or not url.startswith('https://') or not evidence.get('network') or not evidence.get('address'):return
    # Native coin identity cannot be inferred from a wrapped-token contract.
    if row['baseAsset'] in ('BTC','ETH','SOL','BNB'):return
    row.update(network=evidence['network'],address=evidence['address'],multiplier=number(evidence.get('multiplier')))
    m=row['metrics'];source=evidence.get('source','公开链上证据')
    def put(key,value,note):
        m[key]=metric(value,stamp,note,url,source);m[key]['maxAgeHours']=48
    total,circ=number(evidence.get('total')),number(evidence.get('circulating'))
    if total is not None and circ is not None and 0<circ<=total and evidence.get('supplyComparable') is True:
        put('circulation',circ/total*100,'同口径流通供应 / 总供应')
        unlock=number(evidence.get('unlock30d'))
        if unlock is not None and unlock>=0 and evidence.get('unlockComplete') is True:
            put('unlockPct',unlock/circ*100,'未来30天已核验解锁 / 当前流通供应')
    ledger=evidence.get('holders')
    if total and isinstance(ledger,list) and evidence.get('ledgerComplete') is True:
        balances=[];excluded=0;seen=set();valid=True;audited=[]
        for h in ledger:
            balance=number(h.get('balance'));locked=number(h.get('locked'))
            address=h.get('address');kind=h.get('kind')
            if not address or address in seen or balance is None or locked is None or not 0<=locked<=balance or not h.get('evidenceUrl','').startswith('https://'):
                valid=False;break
            seen.add(address)
            subtract=balance if kind in ('exchange','bridge','burn','dex') else locked
            excluded+=subtract;balances.append((balance, balance-subtract,kind,locked))
            audited.append({'address':address,'balance':balance,'amount':subtract,'eligibleBalance':balance-subtract,'kind':kind,'locked':locked,'url':h['evidenceUrl']})
        if valid and balances and abs(sum(b[0] for b in balances)-total)<=max(1e-9,total*1e-8) and total>excluded:
            remaining=sorted((b[1] for b in balances if b[1]>0),reverse=True)
            put('concentration',sum(remaining[:10])/(total-excluded)*100,'经完整地址账本核验；剔除托管/桥/销毁/DEX及锁定部分；地址不等于实体')
            removals=[h for h in audited if h['amount']>0]
            row['concentrationAudit']={'asOf':stamp,'url':url,'totalSupply':total,'excludedSupply':excluded,'remainingSupply':total-excluded,
                                       'adjustedTop10Balance':sum(remaining[:10]),'excluded':removals[:40],'omittedExcluded':max(0,len(removals)-40),
                                       'adjustedTop10':sorted(audited,key=lambda x:-x['eligibleBalance'])[:10]}
            top=sorted(balances,reverse=True)[:10];den=sum(b[0] for b in top)
            if den:
                put('unknownShare',sum(b[0] for b in top if b[2]=='unknown')/den*100,'原始前10地址中未归属余额比例')
                put('lockedShare',sum(b[3] for b in top)/den*100,'原始前10地址中已验证锁定部分')
    row['makers']=[{'name':x['name'],'url':x['url'],'asOf':x['asOf']} for x in evidence.get('makers',[])
                   if isinstance(x,dict) and isinstance(x.get('name'),str) and x.get('url','').startswith('https://') and number(x.get('asOf')) is not None and 0<x['asOf']<=now]


def universe(raw):
    return [x for x in raw.get('symbols',[]) if x.get('status')=='TRADING' and x.get('contractType')=='PERPETUAL'
            and x.get('quoteAsset')=='USDT' and x.get('underlyingType')=='COIN']


def history_append(old, current, now):
    # Latest snapshot per UTC day, 31 slots, avoids unbounded hourly full snapshots.
    by_day={}
    for entry in old+[current]:
        stamp=number(entry.get('asOf'))
        if stamp is not None and now-30*86400000<=stamp<=now:
            day=int(stamp//86400000)
            if day not in by_day or stamp>=by_day[day]['asOf']:by_day[day]=entry
    return [by_day[k] for k in sorted(by_day)]


def snapshot_healthy(snapshot, now):
    for row in snapshot.get('rows',[]):
        values=[row.get('metrics',{}).get(k,{}) for k in ('topLong','accountLong','oiUsd')]
        if all(number(m.get('value')) is not None and number(m.get('asOf')) is not None and 0<=now-m['asOf']<=10800000 for m in values):
            if len({m['asOf'] for m in values})==1 and all(0<=m['value']<=1 for m in values[:2]) and values[2]['value']>=0:return True
    return False


class PublicClient:
    def __init__(self):
        self.lock=threading.Lock();self.next_request=0;self.blocked=None

    def get(self,path,params=None):
        with self.lock:
            if self.blocked:raise RuntimeError(self.blocked)
            delay=max(0,self.next_request-time.monotonic())
            self.next_request=max(time.monotonic(),self.next_request)+.4 # <=750 requests/5min
        if delay:time.sleep(delay)
        if self.blocked:raise RuntimeError(self.blocked)
        url=HOST+path+('?' + urllib.parse.urlencode(params) if params else '')
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'FlowHunt-public-research/1.0'}),timeout=12) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401,403,418,429,451):self.blocked='公开源访问受限 HTTP '+str(exc.code)
            raise RuntimeError('HTTP '+str(exc.code)) from None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=0,help='Explicit partial sample; 0 scans the full universe')
    args=parser.parse_args()
    client=PublicClient();output=ROOT/'data/positioning-radar.json'
    old=json.loads(output.read_text()) if output.exists() else {}
    try:
        infos=universe(client.get('/fapi/v1/exchangeInfo'))
        if not infos:raise RuntimeError('No active crypto USDT perpetual universe')
        tickers={x['symbol']:x for x in client.get('/fapi/v1/ticker/24hr')}
    except Exception as exc:
        # Publish the source state, not a fabricated fresh market observation.
        now=int(time.time()*1000)
        payload=copy.deepcopy(old) if old else {'schemaVersion':1,'rows':[],'history':[],'universeTotal':0,'universeAsOf':None}
        payload.update(generatedAt=now,dataStatus='unavailable',errors=[{'source':'universe/ticker','error':str(exc)[:120]}])
        output.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
        print('::warning::Source unavailable; retained original observations and published failure state',flush=True)
        return
    infos.sort(key=lambda x:-(number(tickers.get(x['symbol'],{}).get('quoteVolume')) or 0))
    selected=infos[:args.limit] if args.limit>0 else infos
    previous={x['symbol']:x for x in old.get('rows',[])}
    evidence_file=ROOT/'data/positioning-evidence.json'
    evidence=json.loads(evidence_file.read_text()).get('assets',{}) if evidence_file.exists() else {}
    rows=[];errors=[]
    def collect(info):
        symbol=info['symbol'];data={'ticker':tickers.get(symbol)};failures=[]
        for key,path in [('oi','/futures/data/openInterestHist'),('top','/futures/data/topLongShortPositionRatio'),('accounts','/futures/data/globalLongShortAccountRatio'),('funding','/fapi/v1/fundingRate')]:
            params={'symbol':symbol,'limit':2 if key=='funding' else 26}
            if key!='funding':params['period']='1h'
            try:data[key]=client.get(path,params)
            except Exception as exc:
                data[key]=None;failures.append({'symbol':symbol,'source':key,'error':str(exc)[:100]})
        now=int(time.time()*1000)
        row=build_row(info,data,previous.get(symbol),now)
        apply_evidence(row,evidence.get(symbol),now)
        return row,failures
    print('Public universe:',len(infos),'selected:',len(selected),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for row,failures in pool.map(collect,selected):
            rows.append(row);errors.extend(failures)
            if len(rows)%25==0:print('Collected',len(rows),'/',len(selected),'source errors',len(errors),flush=True)
    now=int(time.time()*1000)
    compact={'asOf':now,'rows':[{'symbol':r['symbol'],'metrics':{k:r['metrics'][k] for k in ('concentration','topLong','accountLong','oiUsd')}} for r in rows]}
    history=history_append(old.get('history',[]),compact,now)
    payload={'schemaVersion':1,'generatedAt':now,'universeAsOf':now,'universeTotal':len(infos),
             'sampled':len(rows),'partial':len(rows)!=len(infos),'venue':'Binance USDT perpetual',
             'rows':rows,'errors':errors,'history':history,
             'limitations':['集中度、流通率、解锁与做市关联暂无完整可核验公共管线；未核验字段不会进入高集中度榜。',
                            '大户为币安保证金前20%用户；全体账户含大户。持仓与OI变化不等于机构现货净买入。']}
    payload['dataStatus']='unavailable' if not snapshot_healthy(payload,now) else 'partial' if errors else 'available'
    output.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
    print(json.dumps({'rows':len(rows),'errors':len(errors),'output':str(output)},ensure_ascii=False),flush=True)
    if payload['dataStatus']!='available':print('::warning::Published valid degraded source state; data health='+payload['dataStatus'],flush=True)


if __name__=='__main__':main()
