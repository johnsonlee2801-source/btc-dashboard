#!/usr/bin/env python3
"""Exchange wallet address book for labelling token holders in the positioning radar.

Sources, each validated on its own:
  - Binance proof-of-reserves wallet list (via the site's Singapore relay when BINANCE_PROXY_URL is set)
  - Bybit's monthly proof-of-reserves CSV (current month, falling back up to two months)
  - the `owners` lists in DefiLlama's CEX adapters (projects/<slug>/index.js or cex/<slug>.js),
    which also back the exchange-reserve panel
Writes data/exchange-addresses.json. A source that fails this run keeps the addresses it had
in the previous book, so one outage never erases an exchange's labels. An address missing
from the book is reported as unlabelled, never assumed to be retail.
"""
import csv
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import binance_futures  # noqa: E402

RAW = ('https://raw.githubusercontent.com/DefiLlama/DefiLlama-Adapters/main/projects/{}/index.js',
       'https://raw.githubusercontent.com/DefiLlama/DefiLlama-Adapters/main/cex/{}.js')
BYBIT_POR = 'https://api2.bybit.com/common-static/por/bybit_por_{}.csv'
ADAPTERS = {
    'okex': 'OKX', 'bitget': 'Bitget', 'kucoin': 'KuCoin', 'gate-io': 'Gate', 'huobi': 'HTX',
    'bitfinex': 'Bitfinex', 'gemini': 'Gemini', 'bitstamp': 'Bitstamp', 'coinex': 'CoinEx', 'bitrue-cex': 'Bitrue',
    'mexc-cex': 'MEXC', 'phemex': 'Phemex', 'blofin-cex': 'BloFin', 'weex-cex': 'WEEX',
    'crypto-com': 'Crypto.com', 'kraken': 'Kraken', 'robinhood': 'Robinhood', 'deribit': 'Deribit',
    'bitmex': 'BitMEX', 'bingx': 'BingX', 'upbit': 'Upbit', 'lbank': 'LBank', 'poloniex': 'Poloniex', 'woo-cex': 'WOO X',
}
EVM_CHAINS = {'ethereum', 'bsc', 'base', 'arbitrum', 'polygon', 'optimism', 'avax', 'era', 'linea', 'scroll', 'mantle', 'blast', 'sonic', 'op_bnb'}
COMMENTS = re.compile(r'/\*.*?\*/|//[^\n]*', re.S)
BLOCK_RE = re.compile(r'''['"]?(\w+)['"]?\s*:\s*\{[^{}]*?owners\s*:\s*\[([^\]]*)\]''', re.S)
STRING_RE = re.compile(r'''(['"])([^'"\n]+)\1''')
EVM_RE = re.compile(r'0x[0-9a-fA-F]{40}')
B58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
DEADLINE_SECONDS = 8 * 60  # leaves the evidence collector its own budget inside the 45-minute job
UA = {'User-Agent': 'FlowHunt-labels/1.0 (+https://btc.flowhunt.net)'}


def is_solana(address):
    """Base58 that decodes to exactly 32 bytes (an ed25519 public key)."""
    if not 32 <= len(address) <= 44 or any(c not in B58_ALPHABET for c in address):
        return False
    n = 0
    for c in address:
        n = n * 58 + B58_ALPHABET.index(c)
    leading = len(address) - len(address.lstrip('1'))
    return leading + (n.bit_length() + 7) // 8 == 32


def parse_adapter(source):
    """{'evm': set, 'solana': set} from active `chain: { owners: [...] }` blocks (comments ignored)."""
    out = {'evm': set(), 'solana': set()}
    for chain, body in BLOCK_RE.findall(COMMENTS.sub('', source)):
        for _, literal in STRING_RE.findall(body):
            literal = literal.strip()
            if chain == 'solana' and is_solana(literal):
                out['solana'].add(literal)
            elif chain in EVM_CHAINS and EVM_RE.fullmatch(literal):
                out['evm'].add(literal.lower())
    return out


def fetch_text(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as response:
        return response.read().decode('utf-8', 'replace')


def binance_por():
    reply = binance_futures.fetch_one('/bapi/apex/v1/public/apex/market/por/address')
    if not isinstance(reply, dict) or str(reply.get('code')) != '000000' or not isinstance(reply.get('data'), list):
        raise RuntimeError(f"unexpected Binance PoR envelope (code {reply.get('code') if isinstance(reply, dict) else None})")
    out = {'evm': set(), 'solana': set()}
    for row in reply['data']:
        if not isinstance(row, dict):
            continue
        address, network = str(row.get('address') or ''), str(row.get('network') or '').upper()
        if EVM_RE.fullmatch(address):
            out['evm'].add(address.lower())
        elif network == 'SOL' and is_solana(address):
            out['solana'].add(address)
    if len(out['evm']) + len(out['solana']) < 20:
        raise RuntimeError('Binance PoR list has too few usable addresses')
    return out, 'https://www.binance.com/en/proof-of-reserves', None


def parse_bybit_csv(text):
    out = {'evm': set(), 'solana': set()}
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or header[0] != 'Coin':
        return out
    for row in reader:
        if len(row) < 4 or '(ALL)' in row[0]:
            continue
        chain = row[0].split('-')[-1]
        for address in ' '.join(row[3:]).split():
            if EVM_RE.fullmatch(address):
                out['evm'].add(address.lower())
            elif chain == 'Solana' and is_solana(address):
                out['solana'].add(address)
    return out


def bybit_por(now, fetch=fetch_text):
    """Newest monthly PoR CSV with usable addresses -> (addresses, url, 'YYYY-MM')."""
    for back in range(3):
        y, m = now.year, now.month - back
        while m <= 0:
            y, m = y - 1, m + 12
        url = BYBIT_POR.format(f'{y}{m:02d}')
        try:
            found = parse_bybit_csv(fetch(url, timeout=150))
        except (urllib.error.URLError, OSError, TimeoutError):
            continue  # not published yet or slow: try the previous month
        if found['evm'] or found['solana']:
            return found, url, f'{y}-{m:02d}'
    raise RuntimeError('no usable Bybit PoR CSV in the last 3 months')


def adapter(slug, fetch=fetch_text):
    """First adapter location that yields owners -> (addresses, url, None)."""
    for pattern in RAW:
        url = pattern.format(slug)
        try:
            found = parse_adapter(fetch(url))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        if found['evm'] or found['solana']:
            return found, url, None
    raise RuntimeError('no adapter with owners')


def main():
    started = time.monotonic()
    out = ROOT / 'data/exchange-addresses.json'
    try:
        previous = json.loads(out.read_text())
    except (OSError, ValueError):
        previous = {}
    old_book = previous.get('addresses') or {}
    jobs = [('Binance', binance_por), ('Bybit', lambda: bybit_por(datetime.now(timezone.utc)))]
    jobs += [(name, (lambda s=slug: adapter(s))) for slug, name in ADAPTERS.items()]
    book, sources, errors = {}, [], []
    for name, job in jobs:
        if time.monotonic() - started > DEADLINE_SECONDS:
            errors.append({'source': name, 'error': 'run deadline'})
            continue
        try:
            found, url, period = job()
        except Exception as exc:
            errors.append({'source': name, 'error': str(exc)[:120]})
            continue
        for kind in ('evm', 'solana'):
            for address in found[kind]:
                book.setdefault(address, name)
        sources.append({'name': name, 'url': url, 'period': period, 'evm': len(found['evm']), 'solana': len(found['solana']),
                        'fetchedAt': datetime.now(timezone.utc).isoformat()})
    # Sources that failed this run keep their previous addresses (and previous source record).
    failed = {e['source'] for e in errors}
    for address, name in old_book.items():
        if name in failed:
            book.setdefault(address, name)
    sources += [s for s in previous.get('sources', []) if s.get('name') in failed]
    if len(book) < 200:
        # Keep the previous book rather than publishing a thin one that would mislabel exchanges as holders.
        print(f'::warning::only {len(book)} addresses collected; keeping {out.name}', errors)
        return 1
    payload = {'generatedAt': datetime.now(timezone.utc).isoformat(), 'sources': sources, 'errors': errors,
               'addresses': dict(sorted(book.items()))}
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(json.dumps({'addresses': len(book), 'sources': [(s.get('name'), s.get('evm'), s.get('solana')) for s in sources],
                      'errors': errors}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
