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


class StockRadarScoringTests(unittest.TestCase):
    def test_cached_and_manual_risk_signals_do_not_force_hard_100_score(self):
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
            {"id": "ai_core_breadth_ma", "name": "AI breadth", "status": "accumulation", "dataStatus": "Live", "value": "live"},
        ]

        result = run_aggregate(metrics)

        self.assertEqual(result["overall"], "distribution")
        self.assertLess(result["score"], 95)
        margin_driver = next(d for d in result["scoreDrivers"] if d["id"] == "finra_margin_debt")
        live_driver = next(d for d in result["scoreDrivers"] if d["id"] == "equal_weight_rs_rsp_spy")
        self.assertLess(margin_driver["delta"], margin_driver["weight"])
        self.assertEqual(live_driver["delta"], live_driver["weight"])


if __name__ == "__main__":
    unittest.main()
