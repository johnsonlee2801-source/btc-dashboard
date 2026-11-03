#!/usr/bin/env python3
"""Holder-concentration evidence for the positioning radar: data/positioning-evidence.json.

For every Binance USDT perpetual whose base asset maps to a single token contract:
  CoinGecko   -> candidate coins with that symbol; the one whose price matches the Binance
                 contract (open-interest value / units, divided by the 1000x-style multiplier)
                 is accepted, so a same-symbol token cannot be published under the contract
  GoPlus      -> top-10 holders with balance, lock flag and DEX pairs, on every supported chain
                 the token is deployed on; the deployment with the most holders is used
  address book (scripts/build_exchange_labels.py) -> which holders are exchange wallets
The radar builder (apply_evidence) turns this into the adjusted top-10 concentration.
Native L1 coins (BTC, ETH, SOL, ...) have no single contract and are skipped, not guessed.
Any token that fails (rate limit, malformed response, unresolved identity) keeps its
previous dated evidence; the page judges its age.
"""
import json
import math
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
PACE_SECONDS = 3.0           # GoPlus free tier answers 4029 above roughly 20 calls per minute
DEADLINE_SECONDS = 36 * 60   # whole run, CoinGecko included; the job allows 45 minutes
MIN_MARKETS = 1500           # a shorter market list is a partial response, not a market
PRICE_TOLERANCE = 0.25       # CoinGecko vs. Binance contract price, relative
BURN = {'0x0000000000000000000000000000000000000000', '0x000000000000000000000000000000000000dead',
        '0xdead000000000000000042069420694206942069', '1nc1nerator11111111111111111111111111111111'}
# Whole-word tag patterns only: "Delegated treasury" must not read as Gate, "Deadfellaz" as a burn.
TAG_KINDS = (
    ('burn', re.compile(r'\b(burn|burned|dead address|null address|black ?hole)\b')),
    ('bridge', re.compile(r'\b(bridge|wormhole|layerzero|axelar|stargate|multichain|portal bridge)\b')),
    ('dex', re.compile(r'\b(uniswap|pancakeswap|raydium|orca|meteora|pump\.fun|aerodrome|curve|balancer|sushiswap|liquidity pool|amm)\b')),
    ('exchange', re.compile(r'\b(binance|okx|bybit|coinbase|kraken|bitget|kucoin|gate\.io|htx|huobi|mexc|bitfinex|crypto\.com|upbit|bithumb)\b')),
)
PREFIX = re.compile(r'^(1000000|100000|10000|1000|1M)(?=[A-Z])')
# Layer-1 coins whose supply lives on their own chain; an ERC-20/BEP-20 copy of them says nothing about holders.
NATIVE = set('''BTC ETH SOL BNB XRP ADA DOGE TRX TON AVAX DOT LTC BCH XLM HBAR ATOM NEAR APT SUI ETC FIL ICP ALGO XTZ
EGLD KAS SEI INJ TIA HYPE TAO ZEC XMR DASH NEO ONT IOTA VET THETA KSM FLOW MINA ROSE CELO ONE ZIL QTUM IOST ICX WAVES
KAVA STX BERA S CORE IP MOVE XDC KAIA RUNE OSMO AR AXL SONIC CFX CKB GLMR ASTR SCRT BAND XEM ZEN RVN DCR
DYDX STRK ZK MON'''.split())


class DeadlineReached(RuntimeError):
    pass


def finite_number(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


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


def address_key(address):
    """EVM addresses are case-insensitive; Solana base58 addresses are not."""
    return address.lower() if address.startswith('0x') else address


def classify(holder, book, dex_pairs):
    key = address_key(holder['address'])
    tag = (holder.get('tag') or '').lower()
    if key in BURN:
        return 'burn', 'burn address'
    if key in book:
        return 'exchange', book[key]
    if key in dex_pairs:
        return 'dex', 'DEX pool'
    for kind, pattern in TAG_KINDS:
        if tag and pattern.search(tag):
            return kind, holder.get('tag')
    return ('contract' if holder.get('isContract') else 'unknown'), holder.get('tag') or ''


def is_native(coin):
    """No contract platform at all, or a platform named after the coin itself (sui -> {'sui': ...})."""
    platforms = {k: v for k, v in (coin.get('platforms') or {}).items() if v}
    return not platforms or coin['id'] in platforms


def contract_price(row):
    """Binance unit price of the base token implied by open interest, or None."""
    metrics = row.get('metrics') or {}
    usd = finite_number((metrics.get('oiUsd') or {}).get('value'))
    units = finite_number((metrics.get('oiUnits') or {}).get('value'))
    return usd / units if usd and units and usd > 0 and units > 0 else None


def resolve_coin(candidates, rank, prices, binance_price, multiplier):
    """Pick the CoinGecko coin behind a Binance contract, or None when identity is unproven.

    With a Binance price, the candidate must trade within PRICE_TOLERANCE of it (multiplier
    applied). Without one, only an unambiguous single candidate is accepted.
    """
    listed = sorted((c for c in candidates if c['id'] in rank), key=lambda c: rank[c['id']])
    if binance_price:
        unit = binance_price / multiplier
        for coin in listed:
            p = prices.get(coin['id'])
            if p and abs(p / unit - 1) <= PRICE_TOLERANCE:
                return coin
        return None
    return listed[0] if len(listed) == 1 else None


def goplus(platform, address):
    _, chain, _, _ = CHAINS[platform]
    url = GOPLUS_SOL.format(address=address) if chain == 'solana' else GOPLUS_EVM.format(chain=chain, address=address.lower())
    for _ in range(3):
        raw = get_json(url)
        if str(raw.get('code')) != '4029':
            break
        time.sleep(60)  # per-minute rate limit: wait it out instead of losing the token
    if raw.get('code') not in (1, '1'):
        raise RuntimeError(f"GoPlus code {raw.get('code')}: {raw.get('message')}")
    result = next(iter((raw.get('result') or {}).values()), None)
    if not result:
        raise RuntimeError('GoPlus returned no token')
    total = finite_number(result.get('total_supply'))
    if total is None or total <= 0:
        raise RuntimeError('GoPlus total supply missing')
    holders = []
    for h in result.get('holders') or []:
        address = h.get('account') or h.get('address')
        balance, percent = finite_number(h.get('balance')), finite_number(h.get('percent'))
        if not isinstance(address, str) or not address or balance is None or balance < 0:
            raise RuntimeError('GoPlus holder without address or finite balance')
        holders.append({'address': address, 'balance': balance, 'percent': (percent or 0) * 100,
                        'locked': str(h.get('is_locked')) == '1', 'isContract': str(h.get('is_contract')) == '1',
                        'tag': h.get('tag') or ''})
    if not holders:
        raise RuntimeError('GoPlus returned no holders')
    pairs = set()
    for d in result.get('dex') or []:
        pair = isinstance(d, dict) and (d.get('pair') or d.get('id'))
        if isinstance(pair, str) and pair:
            pairs.add(address_key(pair))
    for d in result.get('lp_holders') or []:
        if isinstance(d, dict) and str(d.get('is_contract')) == '1' and isinstance(d.get('address'), str) and d['address']:
            pairs.add(address_key(d['address']))
    count = int(finite_number(result.get('holder_count')) or 0)
    return total, holders, pairs, count


def pick_chain(platforms, fetch=None, deadline=None):
    """Query every supported deployment (up to three) and keep the one with the most holders.

    A bridged copy (e.g. an ERC-20 wrapper of a BSC token) is held almost entirely by the
    bridge, which would read as ~100% concentration. Paced on success and failure alike.
    Returns (platform, (total, holders, pairs, count)) or raises the last error.
    """
    fetch = fetch or goplus
    best, last_error = None, None
    for platform in [p for p in CHAINS if p in platforms][:3]:
        if deadline is not None and time.monotonic() > deadline:
            raise DeadlineReached('run deadline')
        try:
            got = fetch(platform, platforms[platform])
        except Exception as exc:
            last_error = exc
            continue
        finally:
            time.sleep(PACE_SECONDS)
        if best is None or got[3] > best[1][3]:
            best = (platform, got)
    if best is None:
        raise last_error or RuntimeError('no supported chain')
    return best


def main():
    started = time.monotonic()
    deadline = started + DEADLINE_SECONDS
    now = datetime.now(timezone.utc)
    stamp = int(now.timestamp() * 1000)
    radar = json.loads((ROOT / 'data/positioning-radar.json').read_text())
    book_file = json.loads((ROOT / 'data/exchange-addresses.json').read_text())
    book = book_file['addresses']
    coins = get_json(CG + '/coins/list?include_platform=true', timeout=120)
    markets = []
    for page in range(1, 9):
        markets += get_json(CG + f'/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}')
        time.sleep(6)
    if len(markets) < MIN_MARKETS:
        # Publishing from a partial market list would silently drop or mis-map tokens.
        print(f'::error::CoinGecko returned {len(markets)} markets; keeping the previous evidence file')
        return 1
    rank = {m['id']: i for i, m in enumerate(markets)}
    supply = {m['id']: m for m in markets}
    prices = {m['id']: finite_number(m.get('current_price')) for m in markets}
    by_symbol = {}
    for coin in coins:
        by_symbol.setdefault(coin['symbol'].upper(), []).append(coin)
    previous = {}
    try:
        previous = json.loads((ROOT / 'data/positioning-evidence.json').read_text()).get('assets', {})
    except (OSError, ValueError):
        pass
    assets, skipped, errors, deferred = {}, {'native': [], 'unmapped': [], 'unverified': []}, [], []

    def keep_previous(symbol):
        if symbol in previous:
            assets[symbol] = previous[symbol]

    # Oldest (or missing) evidence first, so a run cut short by rate limits still rotates through everything.
    rows = sorted(radar.get('rows', []), key=lambda r: (previous.get(r['symbol']) or {}).get('asOf') or 0)
    for row in rows:
        symbol, asset = row['symbol'], row['baseAsset']
        token_symbol, multiplier = base_symbol(asset)
        candidates = by_symbol.get(token_symbol, [])
        leader = min((c for c in candidates if c['id'] in rank), key=lambda c: rank[c['id']], default=None)
        if token_symbol in NATIVE or (leader and is_native(leader)):
            skipped['native'].append(symbol)
            continue
        coin = resolve_coin(candidates, rank, prices, contract_price(row), multiplier)
        if not coin:
            (skipped['unverified'] if candidates else skipped['unmapped']).append(symbol)
            keep_previous(symbol)
            continue
        platforms = {k: v for k, v in (coin.get('platforms') or {}).items() if v and k in CHAINS}
        if not platforms:
            skipped['unmapped'].append(symbol)
            keep_previous(symbol)
            continue
        if time.monotonic() > deadline:
            deferred.append(symbol)
            keep_previous(symbol)
            continue
        try:
            platform, (total, holders, pairs, holder_count) = pick_chain(platforms, deadline=deadline)
            address = platforms[platform]
            network, _, token_url, address_url = CHAINS[platform]
            for h in holders:
                h['kind'], h['label'] = classify(h, book, pairs)
                h['evidenceUrl'] = address_url.format(h['address'])
        except DeadlineReached:
            deferred.append(symbol)
            keep_previous(symbol)
            continue
        except Exception as exc:
            errors.append({'symbol': symbol, 'error': str(exc)[:120]})
            keep_previous(symbol)
            continue
        market = supply.get(coin['id']) or {}
        assets[symbol] = {
            'symbol': symbol, 'baseAsset': asset, 'coingeckoId': coin['id'], 'name': coin['name'],
            'network': network, 'address': address, 'multiplier': multiplier,
            'asOf': stamp, 'url': token_url.format(address),
            'source': 'GoPlus 前10持仓 · CoinGecko 供应 · DefiLlama/交易所 PoR 地址簿',
            'method': 'goplus-top10', 'total': total, 'holders': holders, 'holderCount': holder_count,
            'chains': list(platforms),
            'circulating': finite_number(market.get('circulating_supply')),
            'supplyTotal': finite_number(market.get('total_supply')),
        }
    payload = {'generatedAt': stamp, 'assets': assets, 'skipped': skipped, 'errors': errors, 'deferred': deferred,
               'addressBookAsOf': book_file.get('generatedAt')}
    (ROOT / 'data/positioning-evidence.json').write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n', encoding='utf-8')
    fresh = sum(1 for a in assets.values() if a.get('asOf') == stamp)
    print(json.dumps({'assets': len(assets), 'refreshed': fresh, 'deferred': len(deferred), 'native': len(skipped['native']),
                      'unmapped': len(skipped['unmapped']), 'unverified': len(skipped['unverified']),
                      'errors': len(errors)}, ensure_ascii=False))
    return 0 if assets else 1


if __name__ == '__main__':
    raise SystemExit(main())
