#!/usr/bin/env python3
"""Holder-concentration evidence for the positioning radar: data/positioning-evidence.json.

For every Binance USDT perpetual whose base asset maps to a single token contract:
  CoinGecko   -> contract address (highest-market-cap coin with that symbol) and circulating/total supply
  GoPlus      -> top-10 holders with balance, lock flag and DEX pairs (one free call per token)
  address book (scripts/build_exchange_labels.py) -> which holders are exchange wallets
The radar builder (apply_evidence) turns this into the adjusted top-10 concentration.
Native L1 coins (BTC, ETH, SOL, ...) have no single contract and are skipped, not guessed.
"""
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = {'User-Agent': 'FlowHunt-evidence/1.0 (+https://btc.flowhunt.net)'}
CG = 'https://api.coingecko.com/api/v3'
GOPLUS_EVM = 'https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={address}'
GOPLUS_SOL = 'https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={address}'
# CoinGecko platform -> (network label, GoPlus chain id or 'solana', explorer token URL, explorer address URL)
CHAINS = {
    'ethereum': ('ETH', '1', 'https://etherscan.io/token/{}#balances', 'https://etherscan.io/address/{}'),
    'solana': ('SOL', 'solana', 'https://solscan.io/token/{}#holders', 'https://solscan.io/account/{}'),
    'binance-smart-chain': ('BSC', '56', 'https://bscscan.com/token/{}#balances', 'https://bscscan.com/address/{}'),
    'base': ('Base', '8453', 'https://basescan.org/token/{}#balances', 'https://basescan.org/address/{}'),
    'arbitrum-one': ('Arbitrum', '42161', 'https://arbiscan.io/token/{}#balances', 'https://arbiscan.io/address/{}'),
    'optimistic-ethereum': ('OP', '10', 'https://optimistic.etherscan.io/token/{}#balances', 'https://optimistic.etherscan.io/address/{}'),
    'polygon-pos': ('Polygon', '137', 'https://polygonscan.com/token/{}#balances', 'https://polygonscan.com/address/{}'),
    'avalanche': ('Avalanche', '43114', 'https://snowtrace.io/token/{}', 'https://snowtrace.io/address/{}'),
}
PACE_SECONDS = 3.0          # GoPlus free tier answers 4029 above roughly 20 calls per minute
TIME_BUDGET_SECONDS = 38 * 60  # leave room inside the 45-minute job; the rest keeps yesterday's evidence
BURN = {'0x0000000000000000000000000000000000000000', '0x000000000000000000000000000000000000dead',
        '0xdead000000000000000042069420694206942069', '1nc1nerator11111111111111111111111111111111'}
TAG_KINDS = (('burn', ('burn', 'dead', 'null address', 'black hole')),
             ('bridge', ('bridge', 'wormhole', 'portal', 'layerzero', 'axelar', 'stargate', 'multichain', 'gateway')),
             ('dex', ('swap', 'pool', 'dex', 'pancake', 'uniswap', 'raydium', 'orca', 'meteora', 'pump.fun', 'aerodrome', 'curve', 'balancer')),
             ('exchange', ('binance', 'okx', 'bybit', 'coinbase', 'kraken', 'bitget', 'kucoin', 'gate', 'htx', 'huobi', 'mexc',
                           'bitfinex', 'crypto.com', 'upbit', 'bithumb', 'exchange', 'hot wallet', 'cold wallet')))
PREFIX = re.compile(r'^(1000000|100000|10000|1000|1M)(?=[A-Z])')
# Layer-1 coins whose supply lives on their own chain; an ERC-20/BEP-20 copy of them says nothing about holders.
NATIVE = set('''BTC ETH SOL BNB XRP ADA DOGE TRX TON AVAX DOT LTC BCH XLM HBAR ATOM NEAR APT SUI ETC FIL ICP ALGO XTZ
EGLD KAS SEI INJ TIA HYPE TAO ZEC XMR DASH NEO ONT IOTA VET THETA KSM FLOW MINA ROSE CELO ONE ZIL QTUM IOST ICX WAVES
KAVA STX BERA S CORE IP MOVE XDC KAIA RUNE OSMO AR AXL SONIC CFX CKB GLMR ASTR SCRT BAND XEM ZEN RVN DCR
DYDX STRK ZK MON'''.split())


def get_json(url, timeout=60, attempts=4):
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < attempts - 1:
                time.sleep(30 * (attempt + 1))
                continue
            raise


def base_symbol(asset):
    m = PREFIX.match(asset)
    if not m:
        return asset, 1
    return asset[m.end():], 1_000_000 if m.group(1) == '1M' else int(m.group(1))


def classify(holder, book, dex_pairs):
    address = holder['address']
    key = address.lower() if address.startswith('0x') else address
    tag = (holder.get('tag') or '').lower()
    if key in BURN:
        return 'burn', 'burn address'
    if key in book:
        return 'exchange', book[key]
    if key in dex_pairs:
        return 'dex', 'DEX pool'
    for kind, words in TAG_KINDS:
        if tag and any(w in tag for w in words):
            return kind, holder.get('tag')
    return ('contract' if holder.get('isContract') else 'unknown'), holder.get('tag') or ''


def goplus(platform, address):
    _, chain, _, _ = CHAINS[platform]
    url = GOPLUS_SOL.format(address=address) if chain == 'solana' else GOPLUS_EVM.format(chain=chain, address=address.lower())
    for attempt in range(3):
        raw = get_json(url)
        if str(raw.get('code')) != '4029':
            break
        time.sleep(60)  # per-minute rate limit: wait it out instead of losing the token
    if raw.get('code') not in (1, '1'):
        raise RuntimeError(f"GoPlus code {raw.get('code')}: {raw.get('message')}")
    result = next(iter((raw.get('result') or {}).values()), None)
    if not result:
        raise RuntimeError('GoPlus returned no token')
    holders = []
    for h in result.get('holders') or []:
        holders.append({'address': h.get('account') or h.get('address'), 'balance': float(h.get('balance') or 0),
                        'percent': float(h.get('percent') or 0) * 100, 'locked': bool(int(h.get('is_locked') or 0)),
                        'isContract': bool(int(h.get('is_contract') or 0)), 'tag': h.get('tag') or ''})
    pairs = {str(d.get('pair') or d.get('id') or '').lower() for d in result.get('dex') or [] if isinstance(d, dict)}
    pairs |= {str(d.get('address') or '').lower() for d in result.get('lp_holders') or [] if isinstance(d, dict) and d.get('is_contract') in (1, '1')}
    count = int(float(result.get('holder_count') or 0))
    return float(result.get('total_supply') or 0), holders, pairs, count


def pick_chain(platforms, fetch=None):
    """Query the token's chains in CHAINS order and keep the one with the most holders.

    A bridged copy (e.g. an ERC-20 wrapper of a BSC token) is held almost entirely by the
    bridge, which would read as ~100% concentration. Stop early once a chain has 1,000+ holders.
    Returns (platform, (total, holders, pairs, count)) or raises the last error.
    """
    fetch = fetch or goplus
    best, last_error = None, None
    for platform in [p for p in CHAINS if p in platforms][:3]:
        try:
            got = fetch(platform, platforms[platform])
            time.sleep(PACE_SECONDS)
        except Exception as exc:
            last_error = exc
            continue
        if best is None or got[3] > best[1][3]:
            best = (platform, got)
        if got[3] >= 1000:
            break
    if best is None:
        raise last_error or RuntimeError('no supported chain')
    return best


def main():
    now = datetime.now(timezone.utc)
    radar = json.loads((ROOT / 'data/positioning-radar.json').read_text())
    book = json.loads((ROOT / 'data/exchange-addresses.json').read_text())['addresses']
    coins = get_json(CG + '/coins/list?include_platform=true', timeout=120)
    markets = []
    for page in range(1, 9):
        markets += get_json(CG + f'/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}')
        time.sleep(6)
    rank = {m['id']: i for i, m in enumerate(markets)}
    supply = {m['id']: m for m in markets}
    by_symbol = {}
    for coin in coins:
        by_symbol.setdefault(coin['symbol'].upper(), []).append(coin)
    previous = {}
    try:
        previous = json.loads((ROOT / 'data/positioning-evidence.json').read_text()).get('assets', {})
    except (OSError, ValueError):
        pass
    assets, skipped, errors, deferred = {}, {'native': [], 'unmapped': []}, [], []
    started = time.monotonic()
    # Oldest (or missing) evidence first, so a run cut short by rate limits still rotates through everything.
    rows = sorted(radar.get('rows', []), key=lambda r: (previous.get(r['symbol']) or {}).get('asOf') or 0)
    for row in rows:
        symbol, asset = row['symbol'], row['baseAsset']
        token_symbol, multiplier = base_symbol(asset)
        candidates = [c for c in by_symbol.get(token_symbol, []) if c['id'] in rank]
        if not candidates:
            skipped['unmapped'].append(symbol)
            continue
        coin = min(candidates, key=lambda c: rank[c['id']])
        platforms = {k: v for k, v in (coin.get('platforms') or {}).items() if v}
        own_chain = coin['id'] in platforms  # e.g. sui -> {'sui': ...}: the coin is its chain's own asset
        if token_symbol in NATIVE or not platforms or own_chain:
            skipped['native'].append(symbol)
            continue
        platform = next((p for p in CHAINS if p in platforms), None)
        if not platform:
            skipped['unmapped'].append(symbol)
            continue
        if time.monotonic() - started > TIME_BUDGET_SECONDS:
            deferred.append(symbol)
            if symbol in previous:
                assets[symbol] = previous[symbol]
            continue
        try:
            platform, (total, holders, pairs, holder_count) = pick_chain(platforms)
        except Exception as exc:
            errors.append({'symbol': symbol, 'error': str(exc)[:120]})
            if symbol in previous:
                assets[symbol] = previous[symbol]  # keep the older dated evidence; the page judges its age
            continue
        address = platforms[platform]
        network, _, token_url, address_url = CHAINS[platform]
        for h in holders:
            h['kind'], h['label'] = classify(h, book, pairs)
            h['evidenceUrl'] = address_url.format(h['address'])
        market = supply.get(coin['id']) or {}
        assets[symbol] = {
            'symbol': symbol, 'baseAsset': asset, 'coingeckoId': coin['id'], 'name': coin['name'],
            'network': network, 'address': address, 'multiplier': multiplier,
            'asOf': int(now.timestamp() * 1000), 'url': token_url.format(address),
            'source': 'GoPlus 前10持仓 · CoinGecko 供应 · DefiLlama/交易所 PoR 地址簿',
            'method': 'goplus-top10', 'total': total, 'holders': holders, 'holderCount': holder_count,
            'chains': [p for p in CHAINS if p in platforms],
            'circulating': market.get('circulating_supply'), 'supplyTotal': market.get('total_supply'),
        }
    payload = {'generatedAt': int(now.timestamp() * 1000), 'assets': assets, 'skipped': skipped, 'errors': errors,
               'deferred': deferred,
               'addressBookAsOf': json.loads((ROOT / 'data/exchange-addresses.json').read_text()).get('generatedAt')}
    (ROOT / 'data/positioning-evidence.json').write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    fresh = sum(1 for a in assets.values() if a.get('asOf') == int(now.timestamp() * 1000))
    print(json.dumps({'assets': len(assets), 'refreshed': fresh, 'deferred': len(deferred), 'native': len(skipped['native']),
                      'unmapped': len(skipped['unmapped']), 'errors': len(errors)}, ensure_ascii=False))
    return 0 if assets else 1


if __name__ == '__main__':
    raise SystemExit(main())
