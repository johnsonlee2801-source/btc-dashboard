"""Behaviour of the relay client, halving cycles, spot-flow merge, exchange labels and token mapping. No network."""
import hashlib
import io
import json
import math
import pathlib
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import binance_futures as bf  # noqa: E402
import build_exchange_labels as labels  # noqa: E402
import build_halving as halving  # noqa: E402
import build_positioning_evidence as ev  # noqa: E402
import build_spot_flow as flow  # noqa: E402


class RelayClientTests(unittest.TestCase):
    def test_proxy_mode_batches_and_keeps_order(self):
        sent = []

        def post(url, payload, timeout=60):
            sent.append(len(payload['requests']))
            return {'results': [{'status': 200, 'body': r['params']['i']} for r in payload['requests']]}
        reqs = [('/fapi/v1/premiumIndex', {'i': i}) for i in range(250)]
        with patch.object(bf, 'PROXY', 'https://relay'), patch.object(bf, '_post', post):
            out = bf.fetch_many(reqs)
        self.assertEqual(sent, [100, 100, 50])
        self.assertEqual([r['body'] for r in out], list(range(250)))

    def test_proxy_transport_failure_marks_each_request_without_raising(self):
        def post(*a, **k):
            raise urllib.error.URLError('down')
        with patch.object(bf, 'PROXY', 'https://relay'), patch.object(bf, '_post', post):
            out = bf.fetch_many([('/a', {}), ('/b', {})])
        self.assertEqual([r['status'] for r in out], [502, 502])
        self.assertTrue(out[0]['error'].startswith('relay'))

    def test_malformed_proxy_reply_is_an_error_not_silent_data(self):
        with patch.object(bf, 'PROXY', 'https://relay'), patch.object(bf, '_post', lambda *a, **k: {'results': []}):
            with self.assertRaises(bf.SourceError):
                bf.fetch_many([('/a', {})])

    def test_malformed_entries_become_explicit_errors(self):
        reply = {'results': [None, {'status': 200}, {'status': 200, 'body': [1]}]}
        with patch.object(bf, 'PROXY', 'https://relay'), patch.object(bf, '_post', lambda *a, **k: reply):
            out = bf.fetch_many([('/a', {}), ('/b', {}), ('/c', {})])
        self.assertEqual([r['status'] for r in out], [502, 502, 200])

    def test_throttling_stops_later_batches_and_keeps_order(self):
        calls = []

        def post(url, payload, timeout=60):
            calls.append(1)
            return {'results': [{'status': 429, 'error': 'HTTP 429', 'retryAfter': 60}] + [{'status': 200, 'body': 1}] * (len(payload['requests']) - 1)}
        with patch.object(bf, 'PROXY', 'https://relay'), patch.object(bf, '_post', post):
            out = bf.fetch_many([('/a', {'i': i}) for i in range(250)])
        self.assertEqual(len(calls), 1, 'no further batches after a 429')
        self.assertEqual(len(out), 250)
        self.assertTrue(all(r['status'] == 429 for r in out[100:]))
        self.assertEqual(out[-1]['retryAfter'], 60)

    def test_relay_http_error_keeps_its_status(self):
        def post(url, payload, timeout=60):
            raise urllib.error.HTTPError(url, 401, 'Unauthorized', {}, None)
        with patch.object(bf, 'PROXY', 'https://relay'), patch.object(bf, '_post', post):
            out = bf.fetch_many([('/a', {})])
        self.assertEqual(out[0]['status'], 401)

    def test_real_direct_routes_por_to_binance_com_and_reports_throttling(self):
        seen = []

        def urlopen(req, timeout=12):
            seen.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 429, 'Too Many', {'Retry-After': '30'}, None)
        with patch.object(bf, 'PROXY', ''), patch.object(bf.urllib.request, 'urlopen', urlopen):
            out = bf.fetch_many([('/bapi/apex/v1/public/apex/market/por/address', None), ('/fapi/v1/premiumIndex', {'symbol': 'BTCUSDT'})])
        self.assertEqual(seen, ['https://www.binance.com/bapi/apex/v1/public/apex/market/por/address'])
        self.assertEqual([r['status'] for r in out], [429, 429])
        self.assertEqual(out[0]['retryAfter'], 30.0)
        self.assertEqual(out[1]['error'], 'skipped after upstream throttling')


class HalvingTests(unittest.TestCase):
    def closes(self, start, values):
        d0 = date.fromisoformat(start)
        return {d0 + timedelta(days=i): v for i, v in enumerate(values)}

    def test_peak_within_two_years_and_low_after_it(self):
        # rises to 10x at day 500, falls to 3x at day 900, then rallies above the peak late in the cycle
        values = [1 + 9 * i / 500 for i in range(501)] + [10 - 7 * i / 400 for i in range(1, 401)] + [3 + 0.01 * i for i in range(1, 700)]
        closes = self.closes('2020-01-01', values)
        s = halving.cycle_stats(closes, date(2020, 1, 1), date(2024, 1, 1))
        self.assertEqual(s['peak']['day'], 500)
        self.assertEqual(s['lowAfterPeak']['day'], 900)
        self.assertAlmostEqual(s['lowAfterPeak']['drawdownPct'], -70.0)
        self.assertTrue(all(x % 5 == 0 for x, _ in s['curve']))

    def test_a_missing_day_inside_a_cycle_is_refused(self):
        closes = self.closes('2020-01-01', [1.0] * 100)
        del closes[date(2020, 2, 1)]
        with self.assertRaises(halving.IncompleteData):
            halving.cycle_stats(closes, date(2020, 1, 1))

    def full_history(self, end):
        start = halving.HALVINGS[0]
        n = (end - start).days + 1
        # gentle rise and fall per cycle so every closed cycle has a peak and a later low
        return {date.fromordinal(start.toordinal() + i): 100 + 50 * math.sin(i / 300) + i * 0.01 for i in range(n)}

    def test_main_writes_only_complete_current_data(self):
        today = datetime.now(timezone.utc).date()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            out = root / 'data/halving-cycles.json'
            out.write_text('{"old": true}')
            stale = self.full_history(today - timedelta(days=10))
            with patch.object(halving, 'ROOT', root), patch.object(halving, 'fetch_closes', return_value=stale):
                self.assertEqual(halving.main(), 1)
            self.assertEqual(json.loads(out.read_text()), {'old': True}, 'a failed run keeps the previous file')
            fresh = self.full_history(today - timedelta(days=1))
            with patch.object(halving, 'ROOT', root), patch.object(halving, 'fetch_closes', return_value=fresh):
                self.assertEqual(halving.main(), 0)
            data = json.loads(out.read_text())
        self.assertEqual(len(data['cycles']), 4)
        self.assertEqual(data['cycles'][-1]['lastDate'], (today - timedelta(days=1)).isoformat(), 'running cycle is not cut at an estimate')

    def test_fetch_keeps_only_finite_positive_closes(self):
        page = {'data': [{'time': '2026-01-01T00:00:00Z', 'PriceUSD': 'NaN'}, {'time': '2026-01-02T00:00:00Z', 'PriceUSD': '-1'},
                         {'time': '2026-01-03T00:00:00Z', 'PriceUSD': '0'}, {'time': 'bad', 'PriceUSD': '5'},
                         {'time': '2026-01-04T00:00:00Z', 'PriceUSD': '90000.5'}]}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        with patch.object(halving.urllib.request, 'urlopen', return_value=Resp(json.dumps(page).encode())):
            self.assertEqual(halving.fetch_closes(), {date(2026, 1, 4): 90000.5})

    def test_missing_halving_day_gives_no_cycle(self):
        closes = self.closes('2020-01-02', [1.0] * 10)
        self.assertIsNone(halving.cycle_stats(closes, date(2020, 1, 1), date(2021, 1, 1)))


class SpotFlowMergeTests(unittest.TestCase):
    def zip_blob(self, rows):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('t.csv', '\n'.join(','.join(map(str, r)) for r in rows))
        return buf.getvalue()

    @staticmethod
    def day_ms(day, micro=False):
        t = int(datetime.combine(date.fromisoformat(day), datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000) + 3600_000
        return t * 1000 if micro else t

    def dump_for(self, url):
        day = url.rsplit('aggTrades-', 1)[1][:10]
        return self.zip_blob([[1, 100, 1, 1, 1, self.day_ms(day), 'false', 'true']])

    def fetcher(self, missing=()):
        def fetch(url, timeout=120):
            if any(d in url for d in missing):
                raise urllib.error.HTTPError(url, 404, 'nf', None, None)
            blob = self.dump_for(url.replace('.CHECKSUM', ''))
            return hashlib.sha256(blob).hexdigest().encode() + b'  x.zip' if url.endswith('.CHECKSUM') else blob
        return fetch

    def test_checksum_mismatch_is_rejected(self):
        blob = self.zip_blob([[1, 100, 1, 1, 1, self.day_ms('2026-11-01'), 'false', 'true']])
        with patch.object(flow, 'fetch', side_effect=[blob, b'0' * 64 + b'  file.zip']):
            with self.assertRaises(ValueError):
                flow.day_flow('BTC', '2026-11-01')

    def test_invalid_records_are_rejected_not_skipped(self):
        day = '2026-11-01'
        ok = [1, 100, 1, 1, 1, self.day_ms(day), 'false', 'true']
        for bad in ([1, 'nan', 1, 1, 1, ok[5], 'false'], [1, 100, -1, 1, 1, ok[5], 'false'], [1, 100, 1, 1, 1, ok[5], 'unknown'],
                    [1, 100, 1, 1, 1, self.day_ms('2026-10-31'), 'false'], ['x', 100, 1, 1, 1, ok[5], 'false']):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                list(flow.parse_zip(self.zip_blob([ok, bad]), day))
        micro = [1, 100, 1, 1, 1, self.day_ms(day, micro=True), 'TRUE', 'true']
        self.assertEqual(list(flow.parse_zip(self.zip_blob([micro]), day)), [(100.0, 1.0, True)])

    def test_header_only_archive_is_not_cached_as_a_quiet_day(self):
        blob = self.zip_blob([['agg_trade_id', 'price', 'quantity', 'first', 'last', 'time', 'is_buyer_maker']])
        digest = hashlib.sha256(blob).hexdigest().encode()
        with patch.object(flow, 'fetch', side_effect=[blob, digest]):
            with self.assertRaises(ValueError):
                flow.day_flow('BTC', '2026-11-01')

    def test_main_adds_only_missing_days_and_keeps_thirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            old = {'assets': {'BTC': {'days': [{'date': '2000-01-01', 'buckets': {}, 'net': 1}]}}}
            (root / 'data/spot-flow.json').write_text(json.dumps(old))
            with patch.object(flow, 'ROOT', root), patch.object(flow, 'fetch', side_effect=self.fetcher()):
                self.assertEqual(flow.main(), 0)
            data = json.loads((root / 'data/spot-flow.json').read_text())
        days = data['assets']['BTC']['days']
        self.assertEqual(len(days), flow.KEEP_DAYS, 'stale days beyond the window are dropped')
        self.assertEqual(days[-1]['buckets']['lt10k']['net'], 100.0)

    def test_only_yesterday_may_be_missing_quietly(self):
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        older = (datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            with patch.object(flow, 'ROOT', root), patch.object(flow, 'fetch', side_effect=self.fetcher((yesterday, older))):
                self.assertEqual(flow.main(), 0)
            data = json.loads((root / 'data/spot-flow.json').read_text())
        self.assertEqual({e['date'] for e in data['errors']}, {older}, 'an old 404 is a real gap')

    def test_stale_data_fails_the_run(self):
        def fetch(url, timeout=120):
            raise urllib.error.HTTPError(url, 503, 'down', None, None)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            with patch.object(flow, 'ROOT', root), patch.object(flow, 'fetch', side_effect=fetch):
                self.assertEqual(flow.main(), 1)

    def test_throttling_stops_the_run(self):
        calls = []

        def fetch(url, timeout=120):
            calls.append(url)
            raise flow.Throttled('HTTP 429')
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            with patch.object(flow, 'ROOT', root), patch.object(flow, 'fetch', side_effect=fetch):
                flow.main()
        self.assertEqual(len(calls), 1)


class LabelBookTests(unittest.TestCase):
    def test_bybit_csv_rows_by_chain(self):
        csv = ('Coin,Height,Amount,Address\nUSDT(ALL),-,1,\n'
               'USDT-Ethereum,1,2,0xAbC0000000000000000000000000000000000001 0xabc0000000000000000000000000000000000002\n'
               'USDT-Solana,1,2,5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9\n'
               'BTC-Bitcoin,1,2,bc1qxyz\n')

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        with patch.object(labels.urllib.request, 'urlopen', return_value=Resp(csv.encode())):
            out, url, period = labels.bybit_por(date(2026, 11, 3))
        self.assertEqual(period, '2026-11')
        self.assertEqual(out['evm'], {'0xabc0000000000000000000000000000000000001', '0xabc0000000000000000000000000000000000002'})
        self.assertEqual(out['solana'], {'5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9'})

    def test_adapter_parsing_ignores_comments_and_truncation(self):
        good = '0x' + 'a' * 40
        source = f'''const config = {{
          // ethereum: {{ owners: ["0x{'b' * 40}"] }},
          "ethereum": {{ owners: ["{good}", "0x{'c' * 42}", /* "0x{'d' * 40}" */] }},
          solana: {{ owners: ["5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9", "1111"] }} }}'''
        found = labels.parse_adapter(source)
        self.assertEqual(found['evm'], {good})
        self.assertEqual(found['solana'], {'5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9'})

    def test_bybit_falls_back_a_month_on_timeout(self):
        csv_text = 'Coin,Height,Amount,Address\nUSDT-Ethereum,1,2,"0x' + 'e' * 40 + ' 0x' + 'f' * 40 + '"\n'
        urls = []

        def fetch(url, timeout=30):
            urls.append(url)
            if url.endswith('202611.csv'):
                raise TimeoutError('read timed out')
            return csv_text
        found, url, period = labels.bybit_por(date(2026, 11, 3), fetch)
        self.assertEqual(period, '2026-10')
        self.assertEqual(len(found['evm']), 2, 'quoted CSV field with two addresses')

    def test_a_failed_source_keeps_its_previous_addresses(self):
        old = {f'0x{i:040x}': 'OKX' for i in range(300)}
        old.update({'0x' + 'b' * 40: 'Bitget'})
        fresh = {'evm': {f'0x{i + 1000:040x}' for i in range(250)}, 'solana': set()}
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            (root / 'data/exchange-addresses.json').write_text(json.dumps({'addresses': old, 'sources': [{'name': 'OKX'}]}))

            def adapter(slug, fetch=None):
                if slug == 'okex':
                    raise RuntimeError('GitHub raw timed out')
                if slug == 'bitget':
                    return fresh, 'https://x', None
                raise RuntimeError('no adapter with owners')
            with patch.object(labels, 'ROOT', root), patch.object(labels, 'binance_por', side_effect=RuntimeError('451')), \
                 patch.object(labels, 'bybit_por', side_effect=RuntimeError('x')), patch.object(labels, 'adapter', adapter):
                self.assertEqual(labels.main(), 0)
            book = json.loads((root / 'data/exchange-addresses.json').read_text())['addresses']
        self.assertEqual(sum(1 for n in book.values() if n == 'OKX'), 300, 'OKX outage must not erase its labels')
        self.assertNotIn('0x' + 'b' * 40, book, 'a source that refreshed replaces its old list')

    def test_thin_book_keeps_the_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            (root / 'data/exchange-addresses.json').write_text('{"addresses":{"0x1":"OKX"}}')
            with patch.object(labels, 'ROOT', root), patch.object(labels, 'binance_por', side_effect=RuntimeError('451')), \
                 patch.object(labels, 'bybit_por', side_effect=RuntimeError('x')), \
                 patch.object(labels.urllib.request, 'urlopen', side_effect=urllib.error.HTTPError('u', 404, 'nf', None, None)):
                self.assertEqual(labels.main(), 1)
            self.assertEqual(json.loads((root / 'data/exchange-addresses.json').read_text())['addresses'], {'0x1': 'OKX'})


class TokenMappingTests(unittest.TestCase):
    def run_main(self, coins, markets, radar_rows, goplus_result=(1000.0, [], set(), 5000)):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            (root / 'data/positioning-radar.json').write_text(json.dumps({'rows': radar_rows}))
            (root / 'data/exchange-addresses.json').write_text('{"generatedAt":"x","addresses":{}}')

            def get_json(url, timeout=60, attempts=4):
                return coins if 'coins/list' in url else (markets if 'page=1' in url else [])
            with patch.object(ev, 'ROOT', root), patch.object(ev, 'get_json', get_json), patch.object(ev.time, 'sleep'), \
                 patch.object(ev, 'MIN_MARKETS', 1), patch.object(ev, 'pick_chain', return_value=('ethereum', goplus_result)):
                ev.main()
            return json.loads((root / 'data/positioning-evidence.json').read_text())

    @staticmethod
    def row(symbol, asset, price=None):
        metrics = {'oiUsd': {'value': price * 1000}, 'oiUnits': {'value': 1000}} if price else {}
        return {'symbol': symbol, 'baseAsset': asset, 'metrics': metrics}

    def test_identity_is_proven_by_price_not_market_cap(self):
        coins = [{'id': 'bitcoin', 'symbol': 'btc', 'name': 'Bitcoin', 'platforms': {}},
                 {'id': 'ff-big', 'symbol': 'ff', 'name': 'FF bigger namesake', 'platforms': {'ethereum': '0xbad'}},
                 {'id': 'falcon', 'symbol': 'ff', 'name': 'Falcon', 'platforms': {'ethereum': '0xf'}},
                 {'id': 'sui', 'symbol': 'sui', 'name': 'Sui', 'platforms': {'sui': '0x2::sui::SUI'}},
                 {'id': 'pepe', 'symbol': 'pepe', 'name': 'Pepe', 'platforms': {'ethereum': '0xp'}},
                 {'id': 'amb1', 'symbol': 'amb', 'name': 'A', 'platforms': {'ethereum': '0xa1'}},
                 {'id': 'amb2', 'symbol': 'amb', 'name': 'B', 'platforms': {'ethereum': '0xa2'}}]
        markets = [{'id': 'bitcoin', 'current_price': 78000}, {'id': 'ff-big', 'current_price': 5.0},
                   {'id': 'falcon', 'current_price': 0.12}, {'id': 'sui', 'current_price': 2},
                   {'id': 'pepe', 'current_price': 0.00001}, {'id': 'amb1', 'current_price': 1}, {'id': 'amb2', 'current_price': 2}]
        rows = [self.row('BTCUSDT', 'BTC', 78000), self.row('FFUSDT', 'FF', 0.121), self.row('SUIUSDT', 'SUI', 2),
                self.row('1000PEPEUSDT', '1000PEPE', 0.0101), self.row('AMBUSDT', 'AMB'), self.row('NOPEUSDT', 'NOPE', 1)]
        out = self.run_main(coins, markets, rows)
        self.assertEqual(sorted(out['assets']), ['1000PEPEUSDT', 'FFUSDT'])
        self.assertEqual(out['assets']['FFUSDT']['address'], '0xf', 'the price-matched coin wins, not the bigger namesake')
        self.assertEqual(out['assets']['1000PEPEUSDT']['multiplier'], 1000)
        self.assertEqual(sorted(out['skipped']['native']), ['BTCUSDT', 'SUIUSDT'])
        self.assertEqual(out['skipped']['unverified'], ['AMBUSDT'], 'two candidates and no price: identity unproven')
        self.assertEqual(out['skipped']['unmapped'], ['NOPEUSDT'])

    def test_partial_market_list_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            (root / 'data/positioning-radar.json').write_text('{"rows":[]}')
            (root / 'data/exchange-addresses.json').write_text('{"addresses":{}}')
            with patch.object(ev, 'ROOT', root), patch.object(ev, 'get_json', lambda *a, **k: []), patch.object(ev.time, 'sleep'):
                self.assertEqual(ev.main(), 1)
            self.assertFalse((root / 'data/positioning-evidence.json').exists())

    def test_goplus_rejects_holders_without_address_or_finite_balance(self):
        bad = [{'account': None, 'balance': '5'}, {'account': '0x1', 'balance': None}, {'account': '0x1', 'balance': 'NaN'}]
        for holder in bad:
            reply = {'code': 1, 'result': {'0xt': {'total_supply': '100', 'holders': [holder], 'holder_count': '10'}}}
            with self.subTest(holder=holder), patch.object(ev, 'get_json', return_value=reply):
                with self.assertRaises(RuntimeError):
                    ev.goplus('ethereum', '0xT')

    def test_solana_pool_keeps_case_and_blank_pairs_are_ignored(self):
        sol = '7YttLkHDoNj9wyDur5pM1ejNaAvT9X4eqaYcHQqtj2G5'
        reply = {'code': 1, 'result': {'m': {'total_supply': '100', 'holder_count': '9',
                                             'holders': [{'account': sol, 'balance': '50', 'percent': '0.5'}, {'account': 'Other', 'balance': '1'}],
                                             'dex': [{'pair': sol}, {'pair': ''}, {'id': None}]}}}
        with patch.object(ev, 'get_json', return_value=reply):
            total, holders, pairs, count = ev.goplus('solana', 'mint')
        self.assertEqual(pairs, {sol})
        self.assertEqual(ev.classify(holders[0], {}, pairs)[0], 'dex')

    def test_tags_match_whole_words_only(self):
        self.assertEqual(ev.classify({'address': '0x9', 'tag': 'Delegated staking treasury'}, {}, set())[0], 'unknown')
        self.assertEqual(ev.classify({'address': '0x9', 'tag': 'Deadfellaz treasury'}, {}, set())[0], 'unknown')
        self.assertEqual(ev.classify({'address': '0x9', 'tag': 'Gate.io 3'}, {}, set())[0], 'exchange')

    def test_failed_chain_requests_are_still_paced(self):
        sleeps = []

        def fail(platform, address):
            raise RuntimeError('down')
        with patch.object(ev.time, 'sleep', side_effect=sleeps.append):
            with self.assertRaises(RuntimeError):
                ev.pick_chain({'ethereum': '0x1', 'base': '0x2'}, fail)
        self.assertEqual(len(sleeps), 2)

    def test_rate_limited_token_keeps_previous_evidence(self):
        coins = [{'id': 'falcon', 'symbol': 'ff', 'name': 'Falcon', 'platforms': {'ethereum': '0xf'}}]
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            (root / 'data/positioning-radar.json').write_text(json.dumps({'rows': [{'symbol': 'FFUSDT', 'baseAsset': 'FF'}]}))
            (root / 'data/exchange-addresses.json').write_text('{"addresses":{}}')
            (root / 'data/positioning-evidence.json').write_text(json.dumps({'assets': {'FFUSDT': {'asOf': 1, 'old': True}}}))

            def get_json(url, timeout=60, attempts=4):
                return coins if 'coins/list' in url else ([{'id': 'falcon'}] if 'page=1' in url else [])
            with patch.object(ev, 'ROOT', root), patch.object(ev, 'get_json', get_json), patch.object(ev.time, 'sleep'), \
                 patch.object(ev, 'MIN_MARKETS', 1), patch.object(ev, 'pick_chain', side_effect=RuntimeError('GoPlus code 4029')):
                ev.main()
            out = json.loads((root / 'data/positioning-evidence.json').read_text())
        self.assertTrue(out['assets']['FFUSDT']['old'])
        self.assertEqual(out['errors'][0]['symbol'], 'FFUSDT')


if __name__ == '__main__':
    unittest.main()
