import json
import pathlib
import subprocess
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "api" / "stock-radar.js"


def run_aggregate(metrics):
    source = MODULE_PATH.read_text(encoding="utf-8")
    start = source.index("const METRIC_WEIGHTS")
    end = source.index("export default async function handler")
    scoring_source = source[start:end]
    script = textwrap.dedent(
        f"""
        {scoring_source}
        const metrics = {json.dumps(metrics, ensure_ascii=False)};
        console.log(JSON.stringify(aggregate(metrics)));
        """
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def run_history_fixture():
    source = MODULE_PATH.read_text(encoding="utf-8")
    start = source.index("function computeDistributionDays")
    end = source.index("export default async function handler")
    history_source = source[start:end]
    script = textwrap.dedent(
        f"""
        {history_source}
        function bars(base, drift) {{
          const out = [];
          for (let i = 0; i < 95; i++) {{
            const close = base + i * drift;
            out.push({{
              t: 1700000000 + i * 86400,
              open: close - 0.2,
              high: close + 1,
              low: close - 1,
              close,
              volume: i % 6 === 0 ? 1300000 : 1000000,
            }});
          }}
          return out;
        }}
        const spyBars = bars(100, 0.2);
        const qqqBars = bars(100, 0.15);
        const sectorBars = Object.fromEntries(['xlk','xlf','xle','xlv','xly','xlp','xli','xlb','xlu','xlre','xlc'].map((key, idx) => [
          key,
          bars(60 + idx, ['xlu','xlp','xlv'].includes(key) ? 0.42 : 0.03),
        ]));
        const result = buildMarketTemperatureHistory({{
          spyBars,
          qqqBars,
          iwmBars: bars(80, -0.08),
          rspBars: bars(90, -0.04),
          hygBars: bars(70, -0.03),
          sectorBars,
        }});
        console.log(JSON.stringify(result));
        """
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


class StockRadarScoringTests(unittest.TestCase):
    def test_score_is_weighted_evidence_balance_not_raw_signal_count(self):
        metrics = [
            {"id": "finra_margin_debt", "name": "Margin", "status": "distribution", "dataStatus": "Cached", "value": "cached"},
            {"id": "sec_form4_insider_activity", "name": "Form 4", "status": "distribution", "dataStatus": "Cached", "value": "cached"},
            {"id": "nyse_ad_line", "name": "A/D", "status": "distribution", "dataStatus": "Cached", "value": "cached"},
            {"id": "sp500_breadth_snapshot", "name": "S&P breadth", "status": "distribution", "dataStatus": "Cached", "value": "cached"},
            {"id": "nyse_nh_nl", "name": "NH/NL", "status": "distribution", "dataStatus": "Cached", "value": "cached"},
            {"id": "bofa_fms_cash", "name": "BofA", "status": "distribution", "dataStatus": "Manual", "value": "manual"},
            {"id": "equal_weight_rs_rsp_spy", "name": "RSP/SPY", "status": "distribution", "dataStatus": "Live", "value": "live"},
            {"id": "credit_risk_hyg_spy", "name": "HYG/SPY", "status": "distribution", "dataStatus": "Live", "value": "live"},
            {"id": "distribution_days", "name": "Distribution Days", "status": "distribution", "dataStatus": "Live", "value": "live"},
            {"id": "cboe_equity_pc", "name": "Put/Call", "status": "neutral", "dataStatus": "Live", "value": "live neutral"},
            {"id": "ai_core_breadth_ma", "name": "AI breadth", "status": "accumulation", "dataStatus": "Live", "value": "live"},
        ]

        result = run_aggregate(metrics)

        self.assertEqual(result["overall"], "distribution")
        margin_driver = next(d for d in result["scoreDrivers"] if d["id"] == "finra_margin_debt")
        live_driver = next(d for d in result["scoreDrivers"] if d["id"] == "equal_weight_rs_rsp_spy")
        self.assertLess(margin_driver["delta"], margin_driver["weight"])
        self.assertEqual(live_driver["delta"], live_driver["weight"])
        self.assertEqual(result["dataQuality"]["netDelta"], 42.6)
        self.assertEqual(result["dataQuality"]["evidenceCapacity"], 60.6)
        self.assertEqual(result["score"], 85)

    def test_all_one_sided_live_evidence_can_still_reach_100(self):
        metrics = [
            {"id": "equal_weight_rs_rsp_spy", "name": "RSP/SPY", "status": "distribution", "dataStatus": "Live", "value": "live"},
            {"id": "credit_risk_hyg_spy", "name": "HYG/SPY", "status": "distribution", "dataStatus": "Live", "value": "live"},
            {"id": "distribution_days", "name": "Distribution Days", "status": "distribution", "dataStatus": "Live", "value": "live"},
        ]

        result = run_aggregate(metrics)

        self.assertEqual(result["score"], 100)

    def test_market_temperature_history_is_chronological_and_bounded(self):
        result = run_history_fixture()
        points = result["points"]

        self.assertGreater(len(points), 20)
        self.assertEqual(points, sorted(points, key=lambda x: x["date"]))
        self.assertTrue(all(0 <= p["score"] <= 100 for p in points))
        self.assertTrue(all(len(p["drivers"]) <= 3 for p in points))
        self.assertIn("Form 4", result["note"])


if __name__ == "__main__":
    unittest.main()
