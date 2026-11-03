"""Behaviour of the relay client, halving cycles, spot-flow merge, exchange labels and token mapping. No network."""
import hashlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from datetime import date, timedelta
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
        self.assertTrue(out[0]['error'].startswith('proxy'))

    def test_malformed_proxy_reply_is_an_error_not_silent_data(self):
        with patch.object(bf, 'PROXY', 'https://relay'), patch.object(bf, '_post', lambda *a, **k: {'results': []}):
            with self.assertRaises(bf.SourceError):
                bf.fetch_many([('/a', {})])

    def test_direct_mode_routes_por_to_binance_com(self):
        urls = []

        def direct(path, params, timeout=12):
            urls.append(bf.OTHER_HOSTS.get(path, bf.HOST) + path)
            return {'status': 451, 'error': 'HTTP 451'}
        with patch.object(bf, 'PROXY', ''), patch.object(bf, '_direct', direct):
            with self.assertRaises(bf.SourceError) as ctx:
                bf.fetch_one('/bapi/apex/v1/public/apex/market/por/address')
        self.assertEqual(ctx.exception.status, 451)
        self.assertTrue(urls[0].startswith('https://www.binance.com/'))


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

    def test_missing_halving_day_gives_no_cycle(self):
        closes = self.closes('2020-01-02', [1.0] * 10)
        self.assertIsNone(halving.cycle_stats(closes, date(2020, 1, 1), date(2021, 1, 1)))


class SpotFlowMergeTests(unittest.TestCase):
    def zip_blob(self, rows):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('t.csv', '\n'.join(','.join(map(str, r)) for r in rows))
        return buf.getvalue()

    def test_checksum_mismatch_is_rejected(self):
        blob = self.zip_blob([[1, 100, 1, 1, 1, 0, 'false', 'true']])
        with patch.object(flow, 'fetch', side_effect=[blob, b'0' * 64 + b'  file.zip']):
            with self.assertRaises(ValueError):
                flow.day_flow('BTC', '2026-11-01')

    def test_main_adds_only_missing_days_and_keeps_thirty(self):
        blob = self.zip_blob([[1, 100, 1, 1, 1, 0, 'false', 'true']])
        digest = hashlib.sha256(blob).hexdigest().encode()

        def fetch(url, timeout=120):
            return digest + b'  x.zip' if url.endswith('.CHECKSUM') else blob
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            old = {'assets': {'BTC': {'days': [{'date': '2000-01-01', 'buckets': {}, 'net': 1}]}}}
            (root / 'data/spot-flow.json').write_text(json.dumps(old))
            with patch.object(flow, 'ROOT', root), patch.object(flow, 'fetch', side_effect=fetch):
                self.assertEqual(flow.main(), 0)
            data = json.loads((root / 'data/spot-flow.json').read_text())
        days = data['assets']['BTC']['days']
        self.assertEqual(len(days), flow.KEEP_DAYS, 'stale days beyond the window are dropped')
        self.assertEqual(days[-1]['buckets']['lt10k']['net'], 100.0)

    def test_unpublished_day_is_skipped_quietly(self):
        def fetch(url, timeout=120):
            raise urllib.error.HTTPError(url, 404, 'nf', None, None)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'data').mkdir()
            with patch.object(flow, 'ROOT', root), patch.object(flow, 'fetch', side_effect=fetch):
                self.assertEqual(flow.main(), 1, 'no days at all is a failure')
            data = json.loads((root / 'data/spot-flow.json').read_text())
        self.assertEqual(data['errors'], [])


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
            out = labels.bybit_por(date(2026, 11, 3))
        self.assertEqual(out['evm'], {'0xabc0000000000000000000000000000000000001', '0xabc0000000000000000000000000000000000002'})
        self.assertEqual(out['solana'], {'5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9'})

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
                 patch.object(ev, 'pick_chain', return_value=('ethereum', goplus_result)):
                ev.main()
            return json.loads((root / 'data/positioning-evidence.json').read_text())

    def test_native_unmapped_and_highest_market_cap_choice(self):
        coins = [{'id': 'bitcoin', 'symbol': 'btc', 'name': 'Bitcoin', 'platforms': {}},
                 {'id': 'falcon', 'symbol': 'ff', 'name': 'Falcon', 'platforms': {'ethereum': '0xf'}},
                 {'id': 'ff-scam', 'symbol': 'ff', 'name': 'FF copy', 'platforms': {'ethereum': '0xbad'}},
                 {'id': 'sui', 'symbol': 'sui', 'name': 'Sui', 'platforms': {'sui': '0x2::sui::SUI'}},
                 {'id': 'pepe', 'symbol': 'pepe', 'name': 'Pepe', 'platforms': {'ethereum': '0xp'}}]
        markets = [{'id': i} for i in ('bitcoin', 'falcon', 'sui', 'pepe', 'ff-scam')]
        rows = [{'symbol': 'BTCUSDT', 'baseAsset': 'BTC'}, {'symbol': 'FFUSDT', 'baseAsset': 'FF'},
                {'symbol': 'SUIUSDT', 'baseAsset': 'SUI'}, {'symbol': '1000PEPEUSDT', 'baseAsset': '1000PEPE'},
                {'symbol': 'NOPEUSDT', 'baseAsset': 'NOPE'}]
        out = self.run_main(coins, markets, rows)
        self.assertEqual(sorted(out['assets']), ['1000PEPEUSDT', 'FFUSDT'])
        self.assertEqual(out['assets']['FFUSDT']['address'], '0xf', 'highest market cap wins a symbol clash')
        self.assertEqual(out['assets']['1000PEPEUSDT']['multiplier'], 1000)
        self.assertEqual(sorted(out['skipped']['native']), ['BTCUSDT', 'SUIUSDT'])
        self.assertEqual(out['skipped']['unmapped'], ['NOPEUSDT'])

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
                 patch.object(ev, 'pick_chain', side_effect=RuntimeError('GoPlus code 4029')):
                ev.main()
            out = json.loads((root / 'data/positioning-evidence.json').read_text())
        self.assertTrue(out['assets']['FFUSDT']['old'])
        self.assertEqual(out['errors'][0]['symbol'], 'FFUSDT')


if __name__ == '__main__':
    unittest.main()
