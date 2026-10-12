import importlib.util
import json
import pathlib
import unittest
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fetch_eth_data", ROOT / "scripts" / "fetch_eth_data.py")
eth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eth)


def account_row(rank, name, pct):
    return (f"<tr><td>{rank}</td><td><a>0xabc</a></td><td>{name}</td>"
            f"<td>1 ETH</td><td>{pct}%</td><td>10</td></tr>")


class WhaleConcentrationTests(unittest.TestCase):
    def test_non_holder_contracts_are_excluded(self):
        rows = [account_row(1, "Beacon Deposit Contract", "75.0"),
                account_row(2, "Wrapped Ether", "1.8"),
                account_row(3, "Binance 7", "1.6"),
                account_row(4, "Arbitrum: Bridge", "0.6"),
                account_row(5, "", "0.5")]
        accounts = eth.parse_top_accounts("".join(rows))
        self.assertEqual(len(accounts), 5)
        kept = [pct for name, pct in accounts if not eth.NON_HOLDER_PATTERNS.search(name)]
        self.assertAlmostEqual(sum(kept), 2.1)


class StakingTests(unittest.TestCase):
    def test_latest_staking_record_is_picked(self):
        html = ('<script>var d=[{"date": "2026-10-10", "validators": 1, "staked_amount": 43679166, "staked_percent": 35.77, "apr": 2.6},'
                '{"date": "2026-10-11", "validators": 1, "staked_amount": 43669573, "staked_percent": 35.77, "apr": 2.6}]</script>')
        records = eth.parse_staking_records(html)
        self.assertEqual(records[-1], ("2026-10-11", 43669573.0, 35.77))

    def test_page_without_records_yields_nothing(self):
        self.assertEqual(eth.parse_staking_records("<html>Just a moment...</html>"), [])


class ScoringInputTests(unittest.TestCase):
    def test_issuance_matches_known_scale(self):
        # 43.7M ETH 质押时，共识层年发行约 110 万 ETH，即每天 3,000 上下
        self.assertAlmostEqual(eth.daily_issuance(43_669_573), 3011, delta=15)

    def test_stablecoin_change_uses_value_thirty_days_back(self):
        pts = [(date(2026, 9, 10), 100.0), (date(2026, 9, 12), 102.0), (date(2026, 10, 12), 104.04)]
        self.assertEqual(eth.stablecoin_change(pts), (104.04, 2.0, "2026-10-12"))

    def test_stablecoin_change_without_history(self):
        self.assertEqual(eth.stablecoin_change([(date(2026, 10, 12), 100.0)]), (100.0, None, "2026-10-12"))


class CarryForwardTests(unittest.TestCase):
    def test_recent_value_is_reused_with_its_date(self):
        prev = {"burn_rate_daily": 15.0, "as_of": {"burn_rate_daily": "2026-10-10"}}
        self.assertEqual(eth.carry_forward(prev, "burn_rate_daily", date(2026, 10, 11)), (15.0, "2026-10-10"))

    def test_old_or_undated_values_are_dropped(self):
        old = {"burn_rate_daily": 15.0, "as_of": {"burn_rate_daily": "2026-09-01"}}
        undated = {"burn_rate_daily": 1200.0}
        self.assertEqual(eth.carry_forward(old, "burn_rate_daily", date(2026, 10, 11)), (None, None))
        self.assertEqual(eth.carry_forward(undated, "burn_rate_daily", date(2026, 10, 11)), (None, None))


class NoInventedNumbersTests(unittest.TestCase):
    # 这些是以前抓取失败时写死的「估计值」，每天原样发布还参与评分
    INVENTED = ("1_780_000_000", "38.5", "27.8", "approx_top5 = 58.0", "lth_pct = 62.0",
                "'reserve': '3,200K'", "450000", "return 1200.0")

    def test_fetch_script_has_no_hardcoded_fallbacks(self):
        src = (ROOT / "scripts" / "fetch_eth_data.py").read_text(encoding="utf-8")
        for token in self.INVENTED:
            with self.subTest(token=token):
                self.assertNotIn(token, src)

    def test_unavailable_metrics_are_published_as_null(self):
        data = json.loads((ROOT / "eth-data.json").read_text(encoding="utf-8"))
        for field in ("stake_conc_top5", "lth_pct", "distribution"):
            with self.subTest(field=field):
                self.assertIsNone(data.get(field))
        self.assertNotIn("exchanges", data)

    def test_eth_page_reads_exchange_data_from_shared_reserves_file(self):
        html = (ROOT / "eth.html").read_text(encoding="utf-8")
        self.assertIn("/data/cex-reserves.json", html)
        self.assertNotIn("YourApiKeyToken", html)


class HalvingPageTests(unittest.TestCase):
    def test_200wma_is_read_from_data_not_hardcoded(self):
        html = (ROOT / "halving.html").read_text(encoding="utf-8")
        self.assertNotIn("$48,000–$55,000", html)
        self.assertIn("ma200w", html)


if __name__ == "__main__":
    unittest.main()
