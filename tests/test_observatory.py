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

    def test_weekly_values_apply_from_the_closing_sunday(self):
        weekly = {'2026-10-11': 30.0, '2026-10-18': 40.0}
        carried = S.carry_weekly(weekly, ['2026-10-17', '2026-10-18', '2026-10-19', '2026-10-26', '2026-10-27'])
        self.assertEqual(carried['2026-10-17'], 30.0)
        self.assertEqual(carried['2026-10-18'], 40.0, 'the closed Sunday candle completes the week')
        self.assertIn('2026-10-26', carried)
        self.assertNotIn('2026-10-27', carried, 'older than 8 days without a newer week')

    def test_monday_build_uses_the_week_that_just_closed(self):
        # Mondays: falling for 20 weeks, then one sharp up-week closing on Sunday 2026-11-01.
        start = date(2026, 6, 15)
        closes = []
        for i in range(140):
            day = start + timedelta(days=i)
            closes.append((day.isoformat(), 1000.0 - i * 5 if i < 133 else 2000.0))
        f = S.price_features(closes)
        last_sunday = closes[-1][0]
        self.assertEqual(last_sunday, '2026-11-01')
        found = S.asof(f['weekly_rsi'], '2026-11-02', 2)
        self.assertEqual(found[0], last_sunday)
        self.assertGreater(found[1], 40, 'the up-week is already in the published RSI')

    def test_weekly_indicators_restart_after_a_missing_week(self):
        closes = days('2020-01-06', [100.0] * 1500)
        broken = [c for c in closes if c[0] != '2023-06-14']
        f = S.price_features(broken)
        self.assertTrue(all(k < '2023-06-14' or k >= '2027' for k in f['ma200w']), '200 weeks cannot bridge the gap')

    def test_non_finite_closes_are_dropped_and_windows_reset(self):
        closes = days('2026-01-01', [100.0] * 5 + [float('inf')] + [100.0] * 5)
        f = S.price_features(closes)
        self.assertNotIn('2026-01-06', f['price'])

    def test_backtest_days_follow_publication_and_freshness(self):
        series = {'2026-01-10': 0.5}
        item = ('mvrv', 'ETH MVRV', '<', 1, '', True, 8)
        days_ = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(40)]
        lit = S.lit_days(series, item, days_, lag=6)
        self.assertEqual(min(lit), '2026-01-16', 'not before it was published')
        self.assertEqual(max(lit), '2026-01-18', 'freshness counts from the observation date, not publication')

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

    NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)

    def book(self, expiries=('27NOV26', '25DEC26'), call_iv=50.0, put_iv=55.0, age_s=60, extra=()):
        created = (self.NOW.timestamp() - age_s) * 1000
        rows = [{'instrument_name': f'BTC-{code}-{strike}-{kind}', 'mark_iv': call_iv if kind == 'C' else put_iv,
                 'underlying_price': 78000.0, 'creation_timestamp': created}
                for code in expiries for strike in range(40000, 130001, 1000) for kind in 'CP']
        return rows + list(extra)

    def test_forward_delta_matches_black_scholes(self):
        # F = K, sigma 50%, T = 1 year: d1 = 0.25, N(0.25) = 0.598706
        self.assertAlmostEqual(options_rr.forward_delta(100, 100, 50, 1, 'C'), 0.598706, places=5)
        self.assertAlmostEqual(options_rr.forward_delta(100, 100, 50, 1, 'P'), 0.598706 - 1, places=5)

    def test_flat_smiles_give_exactly_the_iv_difference(self):
        rr = options_rr.rr25_30d(self.book(), self.NOW)
        self.assertEqual(rr['value'], -5.0)
        self.assertIn('30d', rr['tenor'])
        self.assertEqual(rr['asOf'], datetime.fromtimestamp(self.NOW.timestamp() - 60, timezone.utc).isoformat())

    def test_expiry_interpolation_weights(self):
        # 25d -> rr -2, 53d -> rr -9: at 30d the value is -2 + (-7) * (30-25)/(53-25)
        rows = self.book(('27NOV26',), 50, 52) + self.book(('25DEC26',), 50, 59)
        per, _ = options_rr.rr25_by_expiry(rows, self.NOW)
        t = sorted((e - self.NOW).total_seconds() / 86400 for e in per)
        expected = -2 + (-7) * (30 - t[0]) / (t[1] - t[0])
        self.assertAlmostEqual(options_rr.rr25_30d(rows, self.NOW)['value'], round(expected, 2))

    def test_no_bracket_no_stale_no_value(self):
        self.assertIsNone(options_rr.rr25_30d(self.book(('29OCT27',)), self.NOW), 'a 361-day expiry is not 30 days')
        self.assertIsNone(options_rr.rr25_30d(self.book(age_s=3 * 3600), self.NOW), 'stale marks')
        self.assertIsNone(options_rr.rr25_30d(self.book(age_s=-600), self.NOW), 'future-dated marks')
        # Rows stamped by Deribit's clock a minute after the build started are current, not future.
        self.assertIsNotNone(options_rr.rr25_30d(self.book(age_s=-60), self.NOW), 'server stamp just after now')
        self.assertIsNone(options_rr.rr25_30d([], self.NOW))

    def test_malformed_rows_are_skipped_not_fatal(self):
        bad = [None, {'instrument_name': None}, {'instrument_name': 'BTC-27NOV26-80000-X', 'mark_iv': 50, 'underlying_price': 1},
               {'instrument_name': 'BTC-27NOV26-80000-C', 'mark_iv': True, 'underlying_price': 78000, 'creation_timestamp': 1},
               {'instrument_name': 'BTC-27NOV26-80000-C', 'mark_iv': 50, 'underlying_price': float('inf'), 'creation_timestamp': 1}]
        self.assertEqual(options_rr.rr25_30d(self.book(extra=bad), self.NOW)['value'], -5.0)

    def test_exact_delta_needs_no_neighbour(self):
        self.assertEqual(options_rr.iv_at_delta([(0.25, 50)], 0.25), 50)


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
                return {'date': '2026-11-01', 'mvrv': 1.4, 'sopr': 1.0, 'puellMultiple': 1, 'realizedPrice': 5e4}
            return [{'d': '2026-11-01', 'unixTs': 0, 'v': 2.0}]
        store, errors = onchain_store.refresh(store, now, fetch, max_calls=4)
        self.assertEqual(len(calls), 4)
        self.assertEqual(errors, [])
        self.assertEqual(store['series']['mvrv']['2026-11-01'], 1.4)
        self.assertIn('2022-11-02', store['series']['sth_cost'], 'older history is kept')
        self.assertEqual(len(store['calls']), 4, 'attempts are logged for the next run')

    def test_allowance_is_enforced_across_runs(self):
        now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
        earlier = [(now - timedelta(minutes=m)).isoformat() for m in range(5, 50, 5)]  # 9 in the last hour
        store = {'series': {}, 'fetched': {}, 'calls': earlier}
        calls = []
        onchain_store.refresh(store, now, lambda url: calls.append(url) or [], max_calls=8)
        self.assertEqual(calls, [], 'hourly allowance already used by earlier runs')
        day = [(now - timedelta(hours=h)).isoformat() for h in range(2, 16)]  # 14 in the last day
        store = {'series': {}, 'fetched': {}, 'calls': day}
        onchain_store.refresh(store, now, lambda url: calls.append(url) or [], max_calls=8)
        self.assertEqual(calls, [])

    def test_snapshot_429_stops_everything(self):
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        calls = []

        def fetch(url):
            calls.append(url)
            raise urllib.error.HTTPError(url, 429, 'Too Many', None, None)
        onchain_store.refresh({'series': {}, 'fetched': {}, 'calls': []}, now, fetch)
        self.assertEqual(len(calls), 1)

    def test_incomplete_snapshot_is_not_marked_fetched(self):
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        store = {'series': {k: {'2026-11-01': 1.0} for k in onchain_store.SERIES},
                 'fetched': {k: now.isoformat() for k in onchain_store.SERIES}, 'calls': []}
        store, errors = onchain_store.refresh(store, now, lambda url: {'date': '2026-11-01', 'mvrv': None})
        self.assertNotIn('_snapshot', store['fetched'])
        self.assertEqual(errors[0]['error'], 'ValueError')

    def test_invalid_values_and_dates_are_rejected(self):
        today = date(2026, 11, 2)
        raw = [{'d': '2026-02-30', 'v': 1}, {'d': '2026-12-01', 'v': 1}, {'d': None, 'v': 1},
               {'d': '2026-10-01', 'v': True}, {'d': '2026-10-02', 'v': 10 ** 400}, {'d': '2026-10-03', 'v': '4'}]
        self.assertEqual(onchain_store.parse_series(raw, today), {'2026-10-03': 4.0})

    def test_truncated_response_is_an_error_not_a_crash(self):
        import http.client
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)

        def fetch(url):
            raise http.client.IncompleteRead(b'[', 100)
        store, errors = onchain_store.refresh({'series': {}, 'fetched': {}, 'calls': []}, now, fetch, max_calls=2)
        self.assertEqual([e['error'] for e in errors], ['IncompleteRead', 'IncompleteRead'])

    def test_corrupt_history_stops_instead_of_resetting(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / 'h.json'
            self.assertEqual(onchain_store.load(path)['series'], {}, 'missing file starts empty')
            for bad in ('{not json', 'null', '[]', '{"series": null}'):
                path.write_text(bad)
                with self.subTest(bad=bad), self.assertRaises(onchain_store.CorruptStore):
                    onchain_store.load(path)
            path.write_text('{"series":{"a":{"2026-01-01":1}},"fetched":{}}')
            store = onchain_store.load(path)
            onchain_store.save(store, path)
            self.assertFalse(path.with_suffix('.tmp').exists())
            self.assertEqual(json.loads(path.read_text())['series'], {'a': {'2026-01-01': 1}})

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
