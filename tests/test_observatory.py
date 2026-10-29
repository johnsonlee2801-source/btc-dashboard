import importlib.util
import pathlib
import unittest
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH = ROOT / 'scripts/build_observatory.py'
spec = importlib.util.spec_from_file_location('observatory', PATH) if PATH.exists() else None
obs = importlib.util.module_from_spec(spec) if spec else None
if spec:
    spec.loader.exec_module(obs)


class ObservatoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(obs, 'The public-data observatory collector must exist')

    def test_unknown_metrics_are_not_negative_signals(self):
        metric = obs.metric(None, '2026-10-28', 'test', now=datetime(2026, 10, 29, tzinfo=timezone.utc))
        self.assertIsNone(obs.trigger(metric, '<', 1))

    def test_future_and_expired_metrics_are_unknown(self):
        now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        for day in ('2026-11-01', '2026-10-01', None, 'invalid'):
            m = obs.metric(.4, day, 'test', now=now)
            self.assertIsNone(obs.trigger(m, '<', 1))

    def test_boolean_and_non_finite_values_are_not_numbers(self):
        for value in (True, False, float('nan'), float('inf'), 'not-a-number'):
            self.assertIsNone(obs.number(value))

    def test_closed_candles_reject_current_and_invalid_prices(self):
        now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        stamp = int(now.timestamp() * 1000)
        rows = [[stamp-172800000, '1','2','1','100','3',stamp-86400001],
                [stamp-86400000, '1','2','1','200','3',stamp+1],
                [stamp-86400000, '1','2','1','0','3',stamp-1]]
        points = obs.closed_candles(rows, now)
        self.assertEqual([p['close'] for p in points], [100.0])

    def test_candles_with_non_finite_or_reversed_times_are_rejected(self):
        now=datetime(2026,10,29,tzinfo=timezone.utc)
        stamp=int(now.timestamp()*1000)
        for start,end in [(stamp-86400000,'NaN'),('NaN',stamp-1),(-1,stamp-1),(stamp-1,stamp-86400000)]:
            with self.subTest(start=start,end=end):
                self.assertEqual(obs.closed_candles([[start,'1','2','1','100','3',end]],now),[])

    def test_rsi_wilder_flat_and_monotonic(self):
        self.assertEqual(obs.rsi([3] * 20), 50)
        self.assertEqual(obs.rsi(list(range(1, 22))), 100)
        self.assertEqual(obs.rsi(list(range(22, 1, -1))), 0)
        self.assertIsNone(obs.rsi([1, 2, 3]))

    def test_score_is_interval_with_missing_metrics(self):
        groups = [{'weight':40, 'items':[{'triggered':True}, {'triggered':None}]},
                  {'weight':60, 'items':[{'triggered':False}]}]
        self.assertEqual(obs.score_bounds(groups), {'lower':20.0,'upper':40.0,'available':2,'total':3})

    def test_combination_requires_both_metrics(self):
        self.assertIsNone(obs.combine([True, None]))
        self.assertFalse(obs.combine([False, None]))
        self.assertTrue(obs.combine([True, True]))

    def test_missing_sth_cost_does_not_invent_bull_line(self):
        self.assertIsNone(obs.bull_line(70000, None))
        self.assertEqual(obs.bull_line(70000, 75000), 75000)

    def test_eth_does_not_inherit_btc_chain_signals(self):
        now = datetime(2026,10,29,tzinfo=timezone.utc)
        asset = obs.build_asset('ETH', [], {}, {}, {}, now)
        self.assertIsNone(asset['score'])
        ids = [i['key'] for g in asset['groups'] for i in g['items']]
        for key in ('puell', 'sth_mvrv', 'miner_cost', 'hash_ribbon', 'fear'):
            self.assertNotIn(key, ids)

    def test_stale_legacy_eth_fields_keep_their_observation_date(self):
        now = datetime(2026,10,29,tzinfo=timezone.utc)
        asset = obs.build_asset('ETH', [], {}, {}, {'staked_pct':28,'timestamp':'2026-10-01T00:00:00Z','as_of':{'staked_pct':'2026-09-30'}}, now)
        m=asset['metrics']['staked_pct']
        self.assertEqual(m['asOf'], '2026-09-30')
        self.assertEqual(m['status'], 'stale')

    def test_no_snapshot_values_are_copied_from_reference_images(self):
        asset=obs.build_asset('BTC', [], {}, {}, {}, datetime(2026,10,29,tzinfo=timezone.utc))
        self.assertIsNone(asset['metrics']['price']['value'])
        self.assertIsNone(asset['metrics']['sth_cost']['value'])
        self.assertEqual(asset['history'], [])

    def test_etf_parser_preserves_dates_sign_and_missing_rows(self):
        html='<table><tr><th>Date</th><th>Fund</th><th>Total</th></tr><tr><td>27 Oct 2026</td><td>2</td><td>(123.4)</td></tr><tr><td>28 Oct 2026</td><td>-</td><td>-</td></tr><tr><td>29 Oct 2026</td><td>0</td><td>0.0</td></tr><tr><td>Total</td><td>2</td><td>9000</td></tr></table>'
        self.assertTrue(hasattr(obs,'parse_etf'),'Dated ETF parser must exist')
        self.assertEqual(obs.parse_etf(html),[{'date':'2026-10-27','value':-123.4},{'date':'2026-10-29','value':0.0}])

    def test_etf_future_observations_are_excluded(self):
        self.assertTrue(hasattr(obs,'parse_etf'),'Dated ETF parser must exist')
        html='<table><tr><th>Date</th><th>Total</th></tr><tr><td>01 Nov 2026</td><td>2</td></tr></table>'
        self.assertEqual(obs.parse_etf(html,datetime(2026,10,29,tzinfo=timezone.utc)),[])

    def test_eth_etf_header_has_an_empty_date_cell(self):
        html='<table><tr><th></th><th>ETHA</th><th>Total</th></tr><tr><td>28 Oct 2026</td><td>(2.5)</td><td>(2.5)</td></tr></table>'
        self.assertEqual(obs.parse_etf(html),[{'date':'2026-10-28','value':-2.5}])

    def test_successful_snapshot_does_not_discard_previous_optional_source(self):
        old={'extras':{'sth_mvrv':{'value':1.1,'date':'2026-10-20'}}}
        self.assertTrue(hasattr(obs,'updated_chain_cache'),'Per-source cache merger must exist')
        new=obs.updated_chain_cache(old,{'date':'2026-10-28'},'2026-10-29')
        self.assertEqual(new['extras']['sth_mvrv'],old['extras']['sth_mvrv'])
        new['extras']['sth_mvrv']={'value':.9,'date':'2026-10-28'}
        self.assertEqual(old['extras']['sth_mvrv']['date'],'2026-10-20')

    def test_dvol_uses_last_completed_hour_and_rejects_invalid_bars(self):
        self.assertTrue(hasattr(obs,'dvol_observation'),'Public DVOL parser must exist')
        now=datetime(2026,10,29,12,tzinfo=timezone.utc)
        end=int(now.timestamp()*1000)
        raw={'result':{'data':[[end-7200000,1,2,1,38.2],[end,1,2,1,40],[end-3600000,1,2,1,'NaN']]}}
        self.assertEqual(obs.dvol_observation(raw,now),{'value':38.2,'date':'2026-10-29T11:00:00+00:00'})

    def test_history_has_an_official_market_only_domain_and_fallback(self):
        from unittest.mock import patch
        now=datetime(2026,10,29,tzinfo=timezone.utc)
        end=int(now.timestamp()*1000)
        candle=[end-86400000,'1','2','1','100','3',end-1]
        calls=[]
        def public_source(url,errors):
            calls.append(url)
            if 'data-api.binance.vision' in url:return None
            return [] if 'endTime=' in url else [candle]
        with patch.object(obs,'safe_get',public_source):
            points=obs.fetch_candles('BTC',[],now)
        self.assertIn('data-api.binance.vision',calls[0])
        self.assertTrue(any('api.binance.com' in url for url in calls))
        self.assertEqual(points,[{'date':'2026-10-28','close':100.0}])


if __name__ == '__main__':
    unittest.main()
