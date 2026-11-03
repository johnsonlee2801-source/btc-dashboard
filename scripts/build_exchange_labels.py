#!/usr/bin/env python3
"""Exchange wallet address book for labelling token holders in the positioning radar.

Sources: Binance's published proof-of-reserves wallet list (via the site's Singapore relay
when BINANCE_PROXY_URL is set) and the `owners` lists in DefiLlama's CEX adapters, which
also back the exchange-reserve panel. Writes data/exchange-addresses.json.
An address missing from this book is reported as unlabelled, never assumed to be retail.
"""
import json
import re
import sys
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
    'mexc-cex': 'MEXC', 'phemex': 'Phemex', 'blofin-cex': 'BloFin', 'weex-cex': 'WEEX', 'crypto-com': 'Crypto.com', 'kraken': 'Kraken', 'robinhood': 'Robinhood', 'deribit': 'Deribit',
    'bitmex': 'BitMEX', 'bingx': 'BingX', 'upbit': 'Upbit', 'lbank': 'LBank', 'poloniex': 'Poloniex', 'woo-cex': 'WOO X',
}
EVM_CHAINS = {'ethereum', 'bsc', 'base', 'arbitrum', 'polygon', 'optimism', 'avax', 'era', 'linea', 'scroll', 'mantle', 'blast', 'sonic', 'op_bnb'}
BLOCK_RE = re.compile(r'(\w+)\s*:\s*\{[^{}]*?owners\s*:\s*\[([^\]]*)\]', re.S)
EVM_RE = re.compile(r'0x[0-9a-fA-F]{40}')
B58_RE = re.compile(r'[1-9A-HJ-NP-Za-km-z]{32,44}')
UA = {'User-Agent': 'FlowHunt-labels/1.0 (+https://btc.flowhunt.net)'}


def parse_adapter(source):
    """{'evm': set, 'solana': set} from an adapter's `chain: { owners: [...] }` blocks."""
    out = {'evm': set(), 'solana': set()}
    for chain, body in BLOCK_RE.findall(source):
        if chain == 'solana':
            out['solana'].update(B58_RE.findall(body))
        elif chain in EVM_CHAINS:
            out['evm'].update(a.lower() for a in EVM_RE.findall(body))
    return out


def binance_por():
    rows = binance_futures.fetch_one('/bapi/apex/v1/public/apex/market/por/address').get('data') or []
    out = {'evm': set(), 'solana': set()}
    for row in rows:
        address, network = str(row.get('address') or ''), str(row.get('network') or '').upper()
        if EVM_RE.fullmatch(address):
            out['evm'].add(address.lower())
        elif network == 'SOL' and B58_RE.fullmatch(address):
            out['solana'].add(address)
    return out


def bybit_por(now):
    """Bybit's monthly proof-of-reserves CSV: Coin,Height,Amount,<space-separated addresses>."""
    out = {'evm': set(), 'solana': set()}
    for back in range(3):
        y, m = now.year, now.month - back
        while m <= 0:
            y, m = y - 1, m + 12
        try:
            req = urllib.request.Request(BYBIT_POR.format(f'{y}{m:02d}'), headers=UA)
            with urllib.request.urlopen(req, timeout=150) as response:
                text = response.read().decode('utf-8', 'replace')
        except urllib.error.URLError:
            continue
        if not text.startswith('Coin,'):
            continue
        for line in text.splitlines()[1:]:
            parts = line.split(',')
            if len(parts) < 4 or '(ALL)' in parts[0]:
                continue
            chain = parts[0].split('-')[-1]
            for address in ','.join(parts[3:]).split():
                if EVM_RE.fullmatch(address):
                    out['evm'].add(address.lower())
                elif chain == 'Solana' and B58_RE.fullmatch(address):
                    out['solana'].add(address)
        return out
    raise RuntimeError('no Bybit PoR CSV in the last 3 months')


def main():
    book, sources, errors = {}, [], []

    def add(name, found, url):
        for kind in ('evm', 'solana'):
            for address in found[kind]:
                book.setdefault(address, name)
        sources.append({'name': name, 'url': url, 'evm': len(found['evm']), 'solana': len(found['solana'])})
    try:
        add('Binance', binance_por(), 'https://www.binance.com/en/proof-of-reserves')
    except Exception as exc:
        errors.append({'source': 'Binance PoR', 'error': str(exc)[:120]})
    try:
        add('Bybit', bybit_por(datetime.now(timezone.utc)), 'https://www.bybit.com/app/user/proof-of-reserve')
    except Exception as exc:
        errors.append({'source': 'Bybit PoR', 'error': str(exc)[:120]})
    for slug, name in ADAPTERS.items():
        for pattern in RAW:
            url = pattern.format(slug)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as response:
                    found = parse_adapter(response.read().decode('utf-8', 'replace'))
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    errors.append({'source': name, 'error': f'HTTP {exc.code}'})
                continue
            except Exception as exc:
                errors.append({'source': name, 'error': type(exc).__name__})
                continue
            if found['evm'] or found['solana']:
                add(name, found, url)
            break
    out = ROOT / 'data/exchange-addresses.json'
    if len(book) < 200:
        # Keep the previous book rather than publishing a thin one that would mislabel exchanges as holders.
        print(f'::warning::only {len(book)} addresses collected; keeping {out.name}', errors)
        return 1
    payload = {'generatedAt': datetime.now(timezone.utc).isoformat(), 'sources': sources, 'errors': errors,
               'addresses': dict(sorted(book.items()))}
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(json.dumps({'addresses': len(book), 'sources': [(s['name'], s['evm'], s['solana']) for s in sources], 'errors': errors}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
