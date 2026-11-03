"""Holder-concentration evidence and spot flow by trade size. No network."""
import io
import pathlib
import sys
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_exchange_labels as labels  # noqa: E402
import build_positioning_evidence as ev  # noqa: E402
import build_positioning_radar as radar  # noqa: E402
import build_spot_flow as flow  # noqa: E402


def holder(balance, kind='unknown', locked=False, address=None):
    return {'address': address or f'0x{balance:040x}'[-42:], 'balance': balance, 'kind': kind, 'locked': locked,
            'label': '', 'evidenceUrl': 'https://etherscan.io/address/x'}


class ConcentrationTests(unittest.TestCase):
    def test_exchange_burn_dex_bridge_and_locked_leave_numerator_and_denominator(self):
        holders = [holder(400, 'exchange'), holder(100, 'burn'), holder(50, 'dex'), holder(50, 'bridge'),
                   holder(100, locked=True), holder(200), holder(50, 'contract')]
        r = radar.top10_concentration(holders, 1000)
        # remaining 250 of (1000 - 700) eligible supply
        self.assertAlmostEqual(r['value'], 250 / 300 * 100)
        self.assertAlmostEqual(r['raw'], 95.0)
        self.assertEqual(r['known'], 2)
        self.assertAlmostEqual(r['unknownShare'], 250 / 950 * 100)
        self.assertAlmostEqual(r['lockedShare'], 100 / 950 * 100)

    def test_invalid_inputs_give_no_value(self):
        self.assertIsNone(radar.top10_concentration([], 1000))
        self.assertIsNone(radar.top10_concentration([holder(10)], 0))
        self.assertIsNone(radar.top10_concentration([holder(2000)], 1000), 'holders above total supply')
        self.assertIsNone(radar.top10_concentration([holder(1000, 'exchange')], 1000), 'nothing left to measure')

    def test_apply_evidence_publishes_dated_metrics_and_audit(self):
        row = {'symbol': 'FFUSDT', 'baseAsset': 'FF', 'network': None, 'address': None, 'multiplier': None, 'makers': [],
               'metrics': {k: radar.metric(note='暂无可核验数据') for k in radar.FIELDS}}
        now = 1_800_000_000_000
        evidence = {'symbol': 'FFUSDT', 'baseAsset': 'FF', 'asOf': now - 1000, 'url': 'https://etherscan.io/token/x',
                    'network': 'ETH', 'address': '0xabc', 'method': 'goplus-top10', 'total': 1000,
                    'circulating': 234, 'supplyTotal': 1000,
                    'holders': [holder(600), holder(300, 'exchange'), holder(50)]}
        radar.apply_evidence(row, evidence, now)
        m = row['metrics']
        self.assertAlmostEqual(m['concentration']['value'], 650 / 700 * 100)
        self.assertEqual(m['concentration']['maxAgeHours'], 72)
        self.assertAlmostEqual(m['circulation']['value'], 23.4)
        self.assertEqual(row['concentrationAudit']['method'], 'goplus-top10')
        self.assertEqual(len(row['concentrationAudit']['excluded']), 1)

    def test_a_contract_with_few_holders_is_not_scored(self):
        row = {'symbol': 'ATUSDT', 'baseAsset': 'AT', 'network': None, 'address': None, 'multiplier': None, 'makers': [],
               'metrics': {k: radar.metric() for k in radar.FIELDS}}
        evidence = {'symbol': 'ATUSDT', 'baseAsset': 'AT', 'asOf': 5, 'url': 'https://x', 'network': 'ETH', 'address': '0x1',
                    'method': 'goplus-top10', 'total': 100, 'holderCount': 19, 'holders': [holder(100)]}
        radar.apply_evidence(row, evidence, 10)
        self.assertIsNone(row['metrics']['concentration']['value'])

    def test_native_coins_never_take_token_evidence(self):
        row = {'symbol': 'BNBUSDT', 'baseAsset': 'BNB', 'metrics': {k: radar.metric() for k in radar.FIELDS}}
        radar.apply_evidence(row, {'symbol': 'BNBUSDT', 'baseAsset': 'BNB', 'asOf': 1, 'url': 'https://x', 'network': 'ETH',
                                   'address': '0x1', 'method': 'goplus-top10', 'total': 10, 'holders': [holder(5)]}, 10)
        self.assertIsNone(row['metrics']['concentration']['value'])


class ClassificationTests(unittest.TestCase):
    def test_holder_kinds(self):
        book = {'0xf977814e90da44bfa03b6295a0616a897441acec': 'Binance', '9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM': 'Binance'}
        pairs = {'0xpair'}
        cases = [({'address': '0xF977814e90dA44bFA03b6295A0616a897441aceC'}, 'exchange'),
                 ({'address': '9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM'}, 'exchange'),
                 ({'address': '0x000000000000000000000000000000000000dEaD'}, 'burn'),
                 ({'address': '0xPAIR'}, 'dex'),
                 ({'address': '0x1', 'tag': 'Wormhole Token Bridge'}, 'bridge'),
                 ({'address': '0x2', 'tag': 'Raydium Authority V4'}, 'dex'),
                 ({'address': '0x3', 'isContract': True}, 'contract'),
                 ({'address': '0x4'}, 'unknown')]
        for h, kind in cases:
            with self.subTest(h=h):
                self.assertEqual(ev.classify(h, book, pairs)[0], kind)

    def test_bridged_copy_loses_to_the_chain_with_more_holders(self):
        counts = {'ethereum': 40, 'binance-smart-chain': 25000}
        calls = []

        def fake(platform, address):
            calls.append(platform)
            return 1000.0, [], set(), counts[platform]
        original = ev.PACE_SECONDS
        ev.PACE_SECONDS = 0
        try:
            platform, got = ev.pick_chain({'ethereum': '0x1', 'binance-smart-chain': '0x2'}, fake)
        finally:
            ev.PACE_SECONDS = original
        self.assertEqual(platform, 'binance-smart-chain')
        self.assertEqual(got[3], 25000)
        self.assertEqual(calls, ['ethereum', 'binance-smart-chain'])

    def test_base_symbol_prefixes(self):
        self.assertEqual(ev.base_symbol('1000PEPE'), ('PEPE', 1000))
        self.assertEqual(ev.base_symbol('1MBABYDOGE'), ('BABYDOGE', 1_000_000))
        self.assertEqual(ev.base_symbol('1INCH'), ('1INCH', 1), 'a leading digit that is part of the name stays')
        self.assertIn('BNB', ev.NATIVE)

    def test_adapter_parsing_keeps_chains_apart(self):
        source = '''const config = { ethereum: { owners: ["0xAbC0000000000000000000000000000000000001"] },
          solana: { owners: ['5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9'] },
          bitcoin: { owners: ['1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'] } }'''
        found = labels.parse_adapter(source)
        self.assertEqual(found['evm'], {'0xabc0000000000000000000000000000000000001'})
        self.assertEqual(found['solana'], {'5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9'})


class SpotFlowTests(unittest.TestCase):
    def test_buckets_and_taker_side(self):
        rows = [(100.0, 50, False), (100.0, 50, True), (100.0, 500, False), (100_000.0, 20, True)]
        out = flow.summarise(rows)
        self.assertEqual(out['lt10k'], {'buy': 5000.0, 'sell': 5000.0, 'trades': 2, 'net': 0.0})
        self.assertEqual(out['10k_100k']['net'], 50_000.0)
        self.assertEqual(out['gt1m']['net'], -2_000_000.0, 'buyer-maker trades are taker sells')

    def test_zip_parsing_skips_header(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('x.csv', 'agg_trade_id,price,quantity,first,last,time,is_buyer_maker,best\n'
                                '1,100.5,2,1,1,1700000000000,true,true\n2,100,1,2,2,1700000000001,False,True\n')
        self.assertEqual(list(flow.parse_zip(buf.getvalue())), [(100.5, 2.0, True), (100.0, 1.0, False)])


if __name__ == '__main__':
    unittest.main()
