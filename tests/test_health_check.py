import copy, importlib.util, io, pathlib, sys, tempfile, unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("health_check", ROOT / "scripts" / "health_check.py")
hc = importlib.util.module_from_spec(spec); sys.modules["health_check"] = hc; spec.loader.exec_module(hc)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)


def iso(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def day(days_ago):
    return (NOW.date() - timedelta(days=days_ago)).isoformat()


class HoursSinceTests(unittest.TestCase):
    def test_future_timestamp_is_not_healthy(self):
        future=(datetime.now(timezone.utc)+timedelta(hours=5)).isoformat()
        with patch.object(hc,'results',[]),redirect_stdout(io.StringIO()):
            self.assertFalse(hc.check_age('future source',future,48))

    def test_iso_timestamp_with_offset(self):
        ts = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        self.assertAlmostEqual(hc.hours_since(ts), 5, delta=0.05)

    def test_plain_date_is_treated_as_midnight_utc(self):
        today = datetime.now(timezone.utc).date().isoformat()
        self.assertLess(hc.hours_since(today), 24)

    def test_garbage_returns_none(self):
        self.assertIsNone(hc.hours_since("not a date"))
        self.assertIsNone(hc.hours_since(None))
        self.assertIsNone(hc.hours_since(True))
        self.assertIsNone(hc.hours_since(float("inf")))

    def test_age_zero_is_fresh_and_future_is_not(self):
        with patch.object(hc, "now_utc", lambda: NOW):
            self.assertTrue(hc.within(NOW.isoformat(), 12))
            self.assertTrue(hc.within(MS, 12))
            self.assertFalse(hc.within(iso(-1), 12))

    def test_real_rejects_infinity_nan_and_bool(self):
        for v in (float("inf"), float("nan"), True, "1", None):
            self.assertFalse(hc.real(v))
        self.assertTrue(hc.real(0))


# ---- a healthy production, in miniature ----
def item(days_ago=1, value=1.0, max_age=3):
    return {"value": value, "asOf": day(days_ago), "maxAgeDays": max_age, "triggered": False}


def asset(n):
    deriv = {k: {"value": 1.0, "asOf": iso(1), "maxAgeHours": 12} for k in ("funding", "long_short", "top_position", "dvol", "rr25")}
    return {"metrics": {"price": {"value": 78000.0, "asOf": day(1)}},
            "groups": [{"items": [item() for _ in range(n)]}], "derivatives": deriv}


def bucket(buy, sell, trades):
    return {"buy": buy, "sell": sell, "trades": trades, "net": buy - sell}


def flow_day(days_ago=1):
    b = {k: bucket(100.0, 60.0, 10) for k in hc.FLOW_BUCKETS}
    return {"date": day(days_ago), "buckets": b, "net": 160.0}


def cycle(halving, last):
    return {"halving": halving, "halvingClose": 1.0, "peak": {"close": 2.0, "day": 530, "multiple": 2.0, "date": "2025-10-06"},
            "lowAfterPeak": {"close": 1.2, "day": 800, "drawdownPct": -40.0, "date": "2026-06-30"},
            "lastDate": last, "lastClose": 1.5, "curve": [[0, 1.0], [5, 1.1]]}


def major():
    return {"topLong": 0.6, "accountLong": 0.7, "oiUsd": 1e9, "asOf": MS - 3600000}


def evidence():
    return {"asOf": MS - 3600000, "total": 1e9, "holderCount": 5000, "holders": [{"address": "0xabc", "balance": 1.0}]}


def healthy():
    return {
        "/api/ticker?symbol=BTC": {"price": 78000.0, "source": "test"},
        "/api/distribution-radar": {"score": 40, "coverage": 100, "raw": {"sourcesFailed": []}},
        "/data/observatory.json": {"schemaVersion": 2, "generatedAt": iso(2),
                                   "assets": {"BTC": asset(14), "ETH": asset(6)}},
        "/data/onchain-history.json": {"series": {k: {day(2): 1.0} for k in
                                                  ("sth_cost", "supply_profit", "sth_profit", "lth_net30", "whale_1k_10k")}},
        "/data/positioning-summary.json": {"generatedAt": MS - 3600000, "dataStatus": "available", "universeTotal": 500,
                                           "sampled": 500, "valid": 480, "validByAsOf": {str(MS - 3600000): 480}, "majors": {"BTCUSDT": major(), "ETHUSDT": major()}},
        "/data/halving-cycles.json": {"generatedAt": iso(10), "nextHalvingEstimate": "2028-04-17",
                                      "windows": {"peakDays": [525, 546], "lowDays": [777, 912], "drawdownPct": [-76.7, -84.5]},
                                      "cycles": [cycle(h, "2016-07-08") for h in hc.HALVINGS[:-1]]
                                      + [cycle(hc.HALVINGS[-1], day(2))]},
        "/data/spot-flow.json": {"assets": {s: {"days": [flow_day()]} for s in ("BTC", "ETH")}},
        "/data/positioning-evidence.json": {"generatedAt": MS, "errors": [],
                                            "assets": {f"T{i}": evidence() for i in range(160)}},
        "/eth-data.json": {"timestamp": iso(5), **{f: 1.0 for f in ("holder_count", "active_addr_7d", "burn_rate_daily",
                           "staked_pct", "stake_conc_top5", "whale_top100_pct", "stablecoin_mcap_b",
                           "stablecoin_change_30d", "burn_issuance_pct")},
                           "as_of": {f: day(1) for f in ("holder_count", "active_addr_7d", "burn_rate_daily", "staked_pct",
                                                         "stake_conc_top5", "whale_top100_pct", "stablecoin_mcap_b",
                                                         "stablecoin_change_30d", "total_staked")}},
        "/data/cex-reserves.json": {"anchor": day(1), "assets": {
            s: {"exchanges": [{"name": f"X{i}", "latest": 1.0, "asOf": day(1)} for i in range(12)]} for s in ("BTC", "ETH")}},
    }


class MainTests(unittest.TestCase):
    def run_main(self, mutate=lambda d: None):
        data = healthy(); mutate(data)

        def get_json(url):
            path = url.replace(hc.BTC, "")
            if path not in data:
                raise AssertionError(f"unexpected url {url}")
            return 200, copy.deepcopy(data[path])
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(hc, "now_utc", lambda: NOW), \
                patch.object(hc, "get", lambda url, timeout=45: (200, b"x" * 600)), \
                patch.object(hc, "get_json", get_json), redirect_stdout(io.StringIO()):
            report = pathlib.Path(tmp) / "report.md"
            code = hc.main(str(report))
            text = report.read_text(encoding="utf-8")
        return code, text, {name: ok for ok, name, _ in hc.results}

    def assertFails(self, mutate, check):
        code, text, checks = self.run_main(mutate)
        self.assertEqual(code, 1)
        self.assertFalse(checks[check], check)
        self.assertIn("❌ " + check, text)

    def test_healthy_production_passes_and_writes_report(self):
        code, text, checks = self.run_main()
        self.assertEqual(code, 0, [n for n, ok in checks.items() if not ok])
        self.assertIn("通过", text)

    def test_radar_without_failure_metadata_fails_closed(self):
        self.assertFails(lambda d: d["/api/distribution-radar"]["raw"].pop("sourcesFailed"), "/api/distribution-radar")

    def test_radar_unavailable_state_fails(self):
        self.assertFails(lambda d: d["/api/distribution-radar"].update(score=None, coverage=40), "/api/distribution-radar")

    def test_infinite_price_fails(self):
        self.assertFails(lambda d: d["/data/observatory.json"]["assets"]["BTC"]["metrics"]["price"].update(value=float("inf")),
                         "研究快照: BTC 日收盘有效")

    def test_expired_signals_do_not_count_even_if_triggered_is_set(self):
        def m(d):
            for i in d["/data/observatory.json"]["assets"]["ETH"]["groups"][0]["items"]:
                i["asOf"] = day(10)
        self.assertFails(m, "研究快照: ETH 有效信号 ≥4")

    def test_future_or_null_derivatives_are_not_fresh(self):
        def m(d):
            dv = d["/data/observatory.json"]["assets"]["BTC"]["derivatives"]
            dv["funding"]["asOf"] = iso(-3); dv["dvol"]["value"] = None
        self.assertFails(m, "研究快照: BTC 合约/期权数据（经新加坡中转）")

    def test_onchain_future_day_fails(self):
        self.assertFails(lambda d: d["/data/onchain-history.json"]["series"]["sth_cost"].update({day(-2): 1.0}),
                         "链上历史库: 核心序列 6 天内有更新")

    def test_radar_coverage_counts_valid_rows_and_majors(self):
        self.assertFails(lambda d: d["/data/positioning-summary.json"].update(validByAsOf={str(MS - 3600000): 1}), "资金雷达: 有效覆盖")
        self.assertFails(lambda d: d["/data/positioning-summary.json"].pop("validByAsOf"), "资金雷达: 有效覆盖")
        # 302 rows valid at generation, only 2 still within three hours now.
        self.assertFails(lambda d: d["/data/positioning-summary.json"].update(
            validByAsOf={str(MS - 4 * 3600000): 300, str(MS - 3600000): 2}), "资金雷达: 有效覆盖")
        self.assertFails(lambda d: d["/data/positioning-summary.json"]["majors"].pop("ETHUSDT"), "资金雷达: 有效覆盖")
        self.assertFails(lambda d: d["/data/positioning-summary.json"]["majors"].update(BTCUSDT={}), "资金雷达: 有效覆盖")
        self.assertFails(lambda d: d["/data/positioning-summary.json"]["majors"]["BTCUSDT"].update(asOf=MS - 4 * 3600000),
                         "资金雷达: 有效覆盖")
        self.assertFails(lambda d: d["/data/positioning-summary.json"].update(generatedAt=MS - 4 * 3600000), "资金雷达: 有效覆盖")

    def test_halving_needs_all_cycles_and_a_moving_current_cycle(self):
        self.assertFails(lambda d: d["/data/halving-cycles.json"]["cycles"].pop(0), "减半周期数据: 四个周期完整、当前周期在更新")
        self.assertFails(lambda d: d["/data/halving-cycles.json"]["cycles"][-1].update(lastDate=day(9)),
                         "减半周期数据: 四个周期完整、当前周期在更新")

    def test_halving_fields_the_page_renders_are_required(self):
        name = "减半周期数据: 四个周期完整、当前周期在更新"
        self.assertFails(lambda d: d["/data/halving-cycles.json"].pop("windows"), name)
        self.assertFails(lambda d: d["/data/halving-cycles.json"]["windows"].update(lowDays=[1e308, 1e308]), name)
        self.assertFails(lambda d: d["/data/halving-cycles.json"]["cycles"][1]["peak"].pop("multiple"), name)
        self.assertFails(lambda d: d["/data/halving-cycles.json"]["cycles"][2]["lowAfterPeak"].pop("drawdownPct"), name)
        self.assertFails(lambda d: d["/data/halving-cycles.json"]["cycles"][0].update(curve=[None]), name)
        self.assertFails(lambda d: d["/data/halving-cycles.json"]["cycles"][0]["peak"].update(date="2025-02-30"), name)
        self.assertFails(lambda d: d["/data/halving-cycles.json"]["cycles"][1].pop("lowAfterPeak"), name)
        self.assertFails(lambda d: d["/data/halving-cycles.json"]["cycles"][2].update(lastClose=0), name)

    def test_running_cycle_may_not_have_a_low_yet(self):
        code, _, checks = self.run_main(lambda d: d["/data/halving-cycles.json"]["cycles"][-1].pop("lowAfterPeak"))
        self.assertTrue(checks["减半周期数据: 四个周期完整、当前周期在更新"])

    def test_spot_flow_day_needs_real_buckets(self):
        self.assertFails(lambda d: d["/data/spot-flow.json"]["assets"]["ETH"]["days"][-1].update(buckets={}, net=None),
                         "现货分档资金流: 最近交易日完整")
        self.assertFails(lambda d: d["/data/spot-flow.json"]["assets"]["BTC"]["days"][-1]["buckets"]["gt1m"].update(net=999.0),
                         "现货分档资金流: 最近交易日完整")

    def test_retained_old_evidence_does_not_count(self):
        def m(d):
            for a in d["/data/positioning-evidence.json"]["assets"].values():
                a["asOf"] = MS - 72 * 3600000
        self.assertFails(m, "控盘证据: 48 小时内观测 ≥150 个代币")

    def test_eth_field_dates_are_checked_including_dependencies(self):
        name = "eth-data.json: 关键字段有值且未沿用旧值"
        self.assertFails(lambda d: d["/eth-data.json"]["as_of"].update(burn_rate_daily=day(5)), name)
        self.assertFails(lambda d: d["/eth-data.json"]["as_of"].update(total_staked=day(5)), name)
        self.assertFails(lambda d: d["/eth-data.json"]["as_of"].update(whale_top100_pct=day(2)), name)
        self.assertFails(lambda d: d["/eth-data.json"]["as_of"].update(holder_count=day(-1)), name)

    def test_staking_may_lag_two_days_behind_the_run(self):
        # validatorqueue.com publishes day D during D+1, after the ~06:30 UTC ETH run.
        name = "eth-data.json: 关键字段有值且未沿用旧值"
        code, _, checks = self.run_main(lambda d: d["/eth-data.json"]["as_of"].update(staked_pct=day(2), total_staked=day(2)))
        self.assertTrue(checks[name])
        self.assertFails(lambda d: d["/eth-data.json"]["as_of"].update(staked_pct=day(3)), name)

    def test_evidence_needs_holder_data_the_page_accepts(self):
        name = "控盘证据: 48 小时内观测 ≥150 个代币"

        def strip(field, value):
            def m(d):
                for a in d["/data/positioning-evidence.json"]["assets"].values():
                    a[field] = value
            return m
        self.assertFails(strip("holders", []), name)
        self.assertFails(strip("holderCount", 150), name)
        self.assertFails(strip("holders", [{"address": "0xabc", "balance": 2e9}]), name)
        # The consumer rejects these too: top holders over 100% of supply, or everything excluded.
        self.assertFails(strip("holders", [{"address": "0xabc", "balance": 1.0005e9}]), name)
        self.assertFails(strip("holders", [{"address": "0xabc", "balance": 1e9, "kind": "exchange"}]), name)

    def test_reserves_judged_per_exchange_and_per_asset(self):
        self.assertFails(lambda d: d["/data/cex-reserves.json"]["assets"]["ETH"].update(exchanges=[]),
                         "cex-reserves.json: ETH 交易所各自新鲜")

        def m(d):
            for x in d["/data/cex-reserves.json"]["assets"]["BTC"]["exchanges"][:4]:
                x["asOf"] = day(9)
        self.assertFails(m, "cex-reserves.json: BTC 交易所各自新鲜")


if __name__ == "__main__":
    unittest.main()
