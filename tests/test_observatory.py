"""Calculation tests for the observatory pipeline: series maths, rules, gaps, scores, backtests,
the 25-delta risk reversal and the rate-limited on-chain store. No network."""
import json
import pathlib
import sys
import unittest
import urllib.error
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import onchain_store  # noqa: E402
import options_rr  # noqa: E402
import signals as S  # noqa: E402


def days(start, values):
    d0 = date.fromisoformat(start)
    return [((d0 + timedelta(days=i)).isoformat(), v) for i, v in enumerate(values)]


class SeriesTests(unittest.TestCase):
    def test_asof_respects_age_and_skips_non_finite(self):
        series = {'2026-10-28': 1.0, '2026-10-30': float('nan'), '2026-10-31': None}
        self.assertEqual(S.asof(series, '2026-10-31', 3), ('2026-10-28', 1.0))
        self.assertIsNone(S.asof(series, '2026-11-01', 3))
        self.assertIsNone(S.asof({'2026-10-31': True}, '2026-10-31', 0), 'booleans are not numbers')

    def test_rolling_mean_resets_on_missing_day(self):
        closes = days('2026-01-01', [1, 2, 3]) + days('2026-01-05', [10, 20, 30])
        means = S.rolling_mean(closes, 3)
        self.assertEqual(means, {'2026-01-03': 2, '2026-01-07': 20})

    def test_weekly_closes_need_all_seven_days(self):
        closes = days('2026-10-05', range(14))  # Monday 5 Oct .. Sunday 18 Oct
        weeks = S.weekly_closes(closes)
        self.assertEqual([w[0] for w in weeks], ['2026-10-11', '2026-10-18'])
        broken = [c for c in closes if c[0] != '2026-10-14']
        self.assertEqual([w[0] for w in S.weekly_closes(broken)], ['2026-10-11'])

    def test_wilder_rsi_flat_and_monotonic(self):
        flat = [(str(i), 5.0) for i in range(20)]
        up = [(str(i), float(i)) for i in range(20)]
        self.assertEqual(list(S.wilder_rsi(flat).values())[-1], 50.0)
        self.assertEqual(list(S.wilder_rsi(up).values())[-1], 100.0)
        self.assertEqual(S.wilder_rsi(up[:14]), {})

    def test_weekly_values_only_apply_after_the_week_closes(self):
        weekly = {'2026-10-18': 40.0}
        carried = S.carry_weekly(weekly, ['2026-10-18', '2026-10-19', '2026-10-26', '2026-10-27'])
        self.assertNotIn('2026-10-18', carried, 'a week cannot be used on its own closing day')
        self.assertEqual(carried['2026-10-19'], 40.0)
        self.assertIn('2026-10-26', carried)
        self.assertNotIn('2026-10-27', carried, 'older than 8 days without a newer week')

    def test_price_features_drawdown_and_mayer(self):
        closes = days('2025-01-01', [100.0] * 199 + [200.0] + [150.0])
        f = S.price_features(closes)
        self.assertAlmostEqual(f['drawdown90']['2025-07-20'], 25.0)
        self.assertAlmostEqual(f['mayer']['2025-07-19'], 200 / (100.5))

    def test_hash_ribbon_flags_capitulation(self):
        rising = {(date(2026, 1, 1) + timedelta(days=i)).isoformat(): 100.0 + i for i in range(80)}
        falling = {(date(2026, 1, 1) + timedelta(days=i)).isoformat(): 200.0 - i for i in range(80)}
        self.assertEqual(S.hash_ribbon(rising)['2026-03-21'], 0.0)
        self.assertEqual(S.hash_ribbon(falling)['2026-03-21'], 1.0)

    def test_change_over_needs_both_observations(self):
        series = {'2026-10-01': 10.0, '2026-10-31': 25.0, '2026-11-01': 30.0}
        self.assertEqual(S.change_over(series, 30), {'2026-10-31': 15.0})


class RuleTests(unittest.TestCase):
    def test_every_signal_appears_once_and_weights_sum_to_100(self):
        keys = [i[0] for g in S.BTC_GROUPS for i in g['items']]
        self.assertEqual(len(keys), 16)
        self.assertEqual(len(keys), len(set(keys)), 'an indicator must not score twice')
        self.assertEqual(sum(g['weight'] for g in S.BTC_GROUPS), 100)
        self.assertEqual(len(S.ETH_GROUPS[0]['items']), 6)

    def test_boundaries_keep_strict_and_inclusive_operators(self):
        self.assertFalse(S.evaluate('<', 1, 1))
        self.assertTrue(S.evaluate('<=', 20, 20))
        self.assertTrue(S.evaluate('>=', 20, 20))
        self.assertIsNone(S.evaluate('<', 1, None))

    def test_gap_gives_trigger_price_only_for_price_linked_metrics(self):
        mayer = ('mayer', 'Mayer', '<', 0.8, '', True, 3)
        g = S.gap(mayer, 1.0, 50000.0)
        self.assertAlmostEqual(g['triggerPrice'], 40000.0)
        self.assertAlmostEqual(g['movePct'], -20.0)
        rsi = ('weekly_rsi', 'RSI', '<', 35, '', False, 9)
        self.assertEqual(S.gap(rsi, 50, 50000.0), {'met': False, 'delta': -15})
        self.assertEqual(S.gap(mayer, 0.7, 50000.0), {'met': True})
        self.assertIsNone(S.gap(mayer, None, 50000.0))

    def test_missing_inputs_are_unknown_not_zero(self):
        table = {'mayer': {'2026-11-01': 0.7}}
        score = S.score_on(S.BTC_GROUPS, table, '2026-11-01')
        self.assertEqual(score['lit'], 1)
        self.assertEqual(score['known'], 1)
        self.assertEqual(score['lower'], 8.0)
        self.assertEqual(score['upper'], 100.0, 'unknown items keep their possible weight')

    def test_stale_input_does_not_light_a_signal(self):
        table = {'mayer': {'2026-10-20': 0.7}}
        self.assertEqual(S.score_on(S.BTC_GROUPS, table, '2026-11-01')['lit'], 0)

    def test_combo_needs_both_conditions(self):
        table = {'price': {'2026-11-01': 60000.0}, 'sth_cost': {'2026-10-31': 70000.0}, 'drawdown90': {'2026-11-01': 25.0}}
        self.assertTrue(S.combo_on(table, '2026-11-01'))
        table['drawdown90']['2026-11-01'] = 10.0
        self.assertFalse(S.combo_on(table, '2026-11-01'))
        del table['sth_cost']
        self.assertIsNone(S.combo_on(table, '2026-11-01'))

    def test_verdict_bands(self):
        self.assertEqual(S.verdict(0)[0], 'none')
        self.assertEqual(S.verdict(20)[0], 'watch')
        self.assertEqual(S.verdict(55)[0], 'building')
        self.assertEqual(S.verdict(60)[0], 'strong')


class BacktestTests(unittest.TestCase):
    def setUp(self):
        # V-shaped market: falls for 200 days to a low, then recovers for 200 days.
        values = [1000 - 4 * i for i in range(200)] + [200 + 4 * i for i in range(200)]
        self.price = dict(days('2024-01-01', values))
        self.low_day = '2024-07-19'  # index 200, value 200

    def test_local_low_is_found_once(self):
        self.assertEqual(S.local_lows(self.price), [self.low_day])

    def test_signal_lit_at_low_covers_it_and_rises_afterwards(self):
        lit = {k for k, v in self.price.items() if v < 260}
        bt = S.backtest(lit, self.price, '2024-01-01', '2025-02-03')
        self.assertEqual(bt['episodes'], 1)
        self.assertEqual(bt['lowsCovered'], 1)
        self.assertEqual(bt['forwardUpPct'], 100)
        self.assertGreater(bt['forwardMedianPct'], 0)

    def test_never_lit_signal_reports_zero(self):
        bt = S.backtest(set(), self.price, '2024-01-01', '2025-02-03')
        self.assertEqual((bt['litDays'], bt['lowsCovered'], bt['forwardMedianPct']), (0, 0, None))

    def test_too_short_sample_is_rejected(self):
        self.assertIsNone(S.backtest(set(), self.price, '2024-01-01', '2024-03-01'))


class RiskReversalTests(unittest.TestCase):
    def test_instrument_parsing(self):
        exp, strike, kind = options_rr.parse_instrument('BTC-13NOV26-83000-P')
        self.assertEqual((exp.date(), strike, kind), (date(2026, 11, 13), 83000.0, 'P'))
        self.assertIsNone(options_rr.parse_instrument('BTC-PERPETUAL'))

    def test_skewed_smile_gives_negative_rr(self):
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        rows = []
        for code, fwd in (('27NOV26', 78000), ('25DEC26', 78500)):
            for strike in range(50000, 110001, 2000):
                for kind in 'CP':
                    iv = 45 + (78000 - strike) / 2000 * 0.6  # puts (low strikes) richer
                    rows.append({'instrument_name': f'BTC-{code}-{strike}-{kind}', 'mark_iv': iv, 'underlying_price': fwd})
        rr = options_rr.rr25_30d(rows, now)
        self.assertLess(rr['value'], 0)
        self.assertIn('30d', rr['tenor'])
        self.assertIsNone(options_rr.rr25_30d([], now))


class OnchainStoreTests(unittest.TestCase):
    def test_parse_series_takes_the_single_value_field(self):
        raw = [{'d': '2026-10-30', 'unixTs': 1, 'sthMvrv': '1.02'}, {'d': '2026-10-31', 'unixTs': 2, 'x': None},
               {'d': '2026-11-01', 'unixTs': 3, 'a': 1, 'b': 2}]
        self.assertEqual(onchain_store.parse_series(raw), {'2026-10-30': 1.02})

    def test_refresh_respects_call_budget_and_merges_history(self):
        now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
        store = {'series': {'sth_cost': {'2022-11-02': 1.0}}, 'fetched': {}}
        calls = []

        def fetch(url):
            calls.append(url)
            if url.endswith('snapshot'):
                return {'date': '2026-11-01', 'mvrv': 1.4, 'sopr': 1.0}
            return [{'d': '2026-11-01', 'unixTs': 0, 'v': 2.0}]
        store, errors = onchain_store.refresh(store, now, fetch, max_calls=4)
        self.assertEqual(len(calls), 4)
        self.assertEqual(errors, [])
        self.assertEqual(store['series']['mvrv']['2026-11-01'], 1.4)
        self.assertIn('2022-11-02', store['series']['sth_cost'], 'older history is kept')

    def test_missing_series_come_before_refreshes(self):
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        store = {'series': {k: {'2026-11-01': 1.0} for k in onchain_store.SERIES if k != 'eth_mvrv'},
                 'fetched': {k: (now - timedelta(hours=30)).isoformat() for k in onchain_store.SERIES}}
        self.assertEqual(onchain_store.due(store, now)[0], 'eth_mvrv')

    def test_rate_limit_stops_the_run_and_keeps_old_data(self):
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        store = {'series': {'sth_cost': {'2026-10-01': 5.0}}, 'fetched': {'_snapshot': now.isoformat()}}
        calls = []

        def fetch(url):
            calls.append(url)
            raise urllib.error.HTTPError(url, 429, 'Too Many Requests', None, None)
        store, errors = onchain_store.refresh(store, now, fetch)
        self.assertEqual(len(calls), 1, 'stop after the first 429')
        self.assertEqual(store['series']['sth_cost'], {'2026-10-01': 5.0})
        self.assertEqual(errors[0]['error'], 'HTTPError')


if __name__ == '__main__':
    unittest.main()
