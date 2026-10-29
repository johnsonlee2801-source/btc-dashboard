import importlib.util
import json
import pathlib
import unittest
from datetime import date, datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "fetch_cex_reserves.py"
spec = importlib.util.spec_from_file_location("fetch_cex_reserves", MODULE_PATH)
cex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cex)


def ts(y, m, d, hour=0):
    return int(datetime(y, m, d, hour, tzinfo=timezone.utc).timestamp())


def row(t, **tokens):
    return {"date": t, "tokens": tokens}


class ExtractDailyTests(unittest.TestCase):
    def test_same_day_rows_on_one_chain_are_not_added_together(self):
        # DefiLlama 当天会有日线和实时快照两行，相加会让最新值翻倍
        protocol = {"chainTvls": {"Bitcoin": {"tokens": [
            row(ts(2026, 10, 10), BTC=100),
            row(ts(2026, 10, 11), BTC=110),
            row(ts(2026, 10, 11, 9), BTC=112),
        ]}}}
        daily = cex.extract_daily(protocol, "BTC")
        self.assertEqual(daily[date(2026, 10, 11)], 112)

    def test_eth_sums_mainnet_weth_and_l2_eth_but_skips_bsc_pegs(self):
        protocol = {"chainTvls": {
            "Ethereum": {"tokens": [row(ts(2026, 10, 11), WETH=1000, ETH=5)]},
            "Arbitrum": {"tokens": [row(ts(2026, 10, 11), ETH=20, WETH=999)]},
            "Binance": {"tokens": [row(ts(2026, 10, 11), ETH=500)]},
        }}
        self.assertEqual(cex.extract_daily(protocol, "ETH")[date(2026, 10, 11)], 1025)

    def test_btc_ignores_wrapped_btc(self):
        protocol = {"chainTvls": {
            "Bitcoin": {"tokens": [row(ts(2026, 10, 11), BTC=50)]},
            "Ethereum": {"tokens": [row(ts(2026, 10, 11), WBTC=10, BTC=3)]},
        }}
        self.assertEqual(cex.extract_daily(protocol, "BTC")[date(2026, 10, 11)], 50)


class StepTests(unittest.TestCase):
    def setUp(self):
        self.series = [
            (date(2026, 1, 1), 100.0),
            (date(2026, 1, 2), 105.0),   # +5%：正常流动
            (date(2026, 1, 3), 205.0),   # +95%：地址补录
            (date(2026, 1, 4), 200.0),
        ]

    def test_normal_daily_flows_are_not_flagged(self):
        self.assertEqual(cex.detect_steps(self.series), [(date(2026, 1, 3), 100.0)])

    def test_adjusted_series_removes_step_but_keeps_real_flows(self):
        adjusted = dict(cex.adjusted_series(self.series, cex.detect_steps(self.series)))
        self.assertEqual(adjusted[date(2026, 1, 2)], 105.0)
        self.assertEqual(adjusted[date(2026, 1, 3)], 105.0)
        self.assertEqual(adjusted[date(2026, 1, 4)], 100.0)

    def test_changes_exclude_steps(self):
        adjusted = cex.adjusted_series(self.series, cex.detect_steps(self.series))
        change = cex.changes(adjusted, date(2026, 1, 4))
        # 窗口超出数据起点时没有可比值
        self.assertIsNone(change["7d"])
        series = [(date(2025, 12, 1), 100.0)] + self.series
        adjusted = cex.adjusted_series(series, cex.detect_steps(series))
        self.assertEqual(cex.changes(adjusted, date(2026, 1, 4))["30d"], 0)


class WeeklyTests(unittest.TestCase):
    def test_weekly_points_align_to_anchor_and_use_last_value_on_or_before(self):
        series = [(date(2026, 9, 26), 1.0), (date(2026, 10, 3), 2.0), (date(2026, 10, 9), 3.0)]
        pts = cex.weekly_points(series, date(2026, 10, 11), weeks=2)
        self.assertEqual(pts, [["2026-09-27", 1], ["2026-10-04", 2], ["2026-10-11", 3]])

    def test_weeks_before_first_data_are_skipped(self):
        series = [(date(2026, 10, 1), 7.0)]
        pts = cex.weekly_points(series, date(2026, 10, 11), weeks=4)
        self.assertEqual(pts, [["2026-10-04", 7], ["2026-10-11", 7]])


class PageWiringTests(unittest.TestCase):
    def test_dashboard_reads_real_reserve_data_instead_of_preview(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "assets" / "observatory.js").read_text(encoding="utf-8")
        self.assertIn("/data/cex-reserves.json", app)
        self.assertIn('id="reserveList"', html)
        self.assertNotIn("reservePreview", html)
        self.assertNotIn("预览数据", html)
        self.assertIn('href="/eth"', html)

    def test_committed_snapshot_has_two_years_of_weekly_points(self):
        data = json.loads((ROOT / "data" / "cex-reserves.json").read_text(encoding="utf-8"))
        for asset in ("BTC", "ETH"):
            binance = next(e for e in data["assets"][asset]["exchanges"] if e["slug"] == "binance-cex")
            self.assertEqual(len(binance["weekly"]), cex.WEEKS + 1)
            self.assertEqual(binance["weekly"][-1][0], data["anchor"])


if __name__ == "__main__":
    unittest.main()
