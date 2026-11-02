"""Snapshot contract: what build_observatory produces is what assets/observatory.js reads. No network."""
import json
import math
import pathlib
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import binance_futures  # noqa: E402
import build_observatory as B  # noqa: E402
import signals as S  # noqa: E402

NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def synthetic_closes(n=1600, end=date(2026, 11, 1)):
    start = end - timedelta(days=n - 1)
    return [((start + timedelta(days=i)).isoformat(), 50000 + 20000 * math.sin(i / 120)) for i in range(n)]


def synthetic_store(closes):
    series = {}
    for day, close in closes[-1460:]:
        series.setdefault('sth_cost', {})[day] = close * 0.95
        series.setdefault('lth_cost', {})[day] = 30000.0
        series.setdefault('realized_price', {})[day] = 40000.0
        series.setdefault('mvrv', {})[day] = close / 40000.0
        series.setdefault('supply_profit', {})[day] = 70.0
        series.setdefault('sth_profit', {})[day] = 50.0
        series.setdefault('sopr', {})[day] = 1.01
        series.setdefault('mvrv_z', {})[day] = 1.0
        series.setdefault('puell', {})[day] = 1.0
        series.setdefault('hashrate', {})[day] = 5e8
        series.setdefault('lth_net30', {})[day] = -1000.0
        series.setdefault('whale_1k_10k', {})[day] = 4.2e6
    return {'series': series, 'fetched': {}}


class BuildContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        closes = synthetic_closes()
        store = synthetic_store(closes)
        fear = {d: 40.0 for d, _ in closes}
        cls.btc = B.build_asset('BTC', closes, store, fear, NOW)
        cls.eth = B.build_asset('ETH', closes, {'series': {'eth_mvrv': store['series']['mvrv']}}, fear, NOW)

    def test_btc_payload_has_every_section_the_page_reads(self):
        for key in ('groups', 'metrics', 'score', 'verdict', 'scoreHistory', 'combo', 'scoreBacktest', 'band',
                    'cohorts', 'ladder', 'history'):
            self.assertIn(key, self.btc)
        self.assertEqual(len(self.btc['combo']['conditions']), 2)
        self.assertEqual(len(self.btc['scoreHistory'][0]), 3, '[date, score, close]')
        self.assertIn(self.btc['band']['zone'], (0, 1, 2, 3))

    def test_items_carry_dates_sources_and_backtests(self):
        items = [i for g in self.btc['groups'] for i in g['items']]
        self.assertEqual(len(items), 16)
        for i in items:
            with self.subTest(key=i['key']):
                for field in ('key', 'label', 'op', 'threshold', 'unit', 'linked', 'maxAgeDays', 'source', 'value', 'asOf', 'triggered'):
                    self.assertIn(field, i)
                if i['value'] is not None and i['key'] in ('mayer', 'price_ma200w', 'mvrv'):
                    self.assertIsNotNone(i['backtest'])

    def test_price_linked_gap_has_a_trigger_price_below_price(self):
        mayer = next(i for g in self.btc['groups'] for i in g['items'] if i['key'] == 'mayer')
        if not mayer['triggered']:
            self.assertLess(mayer['gap']['triggerPrice'], self.btc['metrics']['price']['value'])

    def test_combo_trigger_is_the_lower_of_the_two_lines(self):
        sth, dd = (c['triggerPrice'] for c in self.btc['combo']['conditions'])
        self.assertAlmostEqual(dd, self.btc['combo']['conditions'][1]['high90'] * 0.8)
        self.assertTrue(sth > 0 and dd > 0)

    def test_ladder_is_sorted_from_high_to_low(self):
        values = [r['value'] for r in self.btc['ladder']]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_eth_never_gets_a_btc_score(self):
        self.assertNotIn('verdict', self.eth)
        self.assertEqual(set(self.eth['score']), {'lit', 'total', 'known'})
        self.assertEqual(self.eth['score']['total'], 6)

    def test_snapshot_is_json_serialisable_without_nan(self):
        json.dumps(self.btc, allow_nan=False)
        json.dumps(self.eth, allow_nan=False)


class SourceEdgeTests(unittest.TestCase):
    def test_etf_row_for_the_current_us_session_is_dropped(self):
        html = ('<table><tr><th>Date</th><th>IBIT</th><th>Total</th></tr>'
                '<tr><td>30 Oct 2026</td><td>1</td><td>(643.2)</td></tr>'
                '<tr><td>02 Nov 2026</td><td>0</td><td>0.0</td></tr></table>')
        rows = B.parse_etf(html, datetime(2026, 11, 2, 15, tzinfo=timezone.utc))
        self.assertEqual(rows, [{'date': '2026-10-30', 'value': -643.2}])
        rows = B.parse_etf(html, datetime(2026, 11, 2, 23, 30, tzinfo=timezone.utc))
        self.assertEqual(rows[-1]['date'], '2026-11-02')

    def test_binance_451_is_reported_not_invented(self):
        blocked = [{'status': 451, 'error': 'HTTP 451'}] * 5
        errors = []
        with patch.object(binance_futures, 'fetch_many', return_value=blocked), \
             patch.object(B, 'safe_get', return_value=None):
            out = B.fetch_derivatives('BTC', errors, NOW)
        self.assertEqual(out, {})
        self.assertTrue(any('premiumIndex' in e['url'] and '451' in e['error'] for e in errors))

    def test_positioning_ratio_uses_the_hourly_reading(self):
        day0 = int(datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp() * 1000)
        daily = [{'timestamp': day0 - 30 * 86400000, 'longShortRatio': '1.2', 'longAccount': '0.55'},
                 {'timestamp': day0, 'longShortRatio': '1.5', 'longAccount': '0.6'}]
        hourly = [{'timestamp': day0 + 11 * 3600000, 'longShortRatio': '2.0', 'longAccount': '0.667'}]
        results = [{'status': 200, 'body': {'lastFundingRate': '0.0001', 'time': day0}},
                   {'status': 200, 'body': daily}, {'status': 200, 'body': daily},
                   {'status': 200, 'body': hourly}, {'status': 200, 'body': hourly}]
        with patch.object(binance_futures, 'fetch_many', return_value=results), \
             patch.object(B, 'safe_get', return_value=None):
            out = B.fetch_derivatives('BTC', [], NOW)
        self.assertEqual(out['top_position']['value'], 2.0)
        self.assertEqual(out['long_short']['ago30'], 1.2)
        self.assertAlmostEqual(out['funding']['value'], 0.01)


class PageContractTests(unittest.TestCase):
    def test_pages_load_the_v2_assets_and_share_the_shell(self):
        for page in ('index.html', 'eth.html'):
            html = (ROOT / page).read_text(encoding='utf-8')
            for needle in ('/assets/site.css', '/assets/observatory.css', '/assets/observatory-model.js', 'class="site-header"',
                           'id="verdict"', 'id="combo"', 'id="trend"', 'id="groups"', 'id="ladder"', 'id="sentiment"'):
                with self.subTest(page=page, needle=needle):
                    self.assertIn(needle, html)
            self.assertNotIn('positioning-radar.json', html, 'the home pages must not download the 2.7 MB radar file')

    def test_eth_page_has_its_own_icon_and_no_btc_band(self):
        html = (ROOT / 'eth.html').read_text(encoding='utf-8')
        self.assertIn('favicon-eth.svg', html)
        self.assertNotIn('id="band"', html)


if __name__ == '__main__':
    unittest.main()
