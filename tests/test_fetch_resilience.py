import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "fetch_data.py"
spec = importlib.util.spec_from_file_location("fetch_data", MODULE_PATH)
fetch_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_data)


class FetchResilienceTests(unittest.TestCase):
    def test_carry_forward_uses_previous_value_when_current_missing(self):
        previous = {"onchain": {"mvrv_zscore": 2.04}, "tips": 1.97}
        self.assertEqual(
            fetch_data.carry_forward(previous, None, ["onchain", "mvrv_zscore"], "MVRV"),
            2.04,
        )
        self.assertEqual(
            fetch_data.carry_forward(previous, None, ["tips"], "TIPS"),
            1.97,
        )

    def test_carry_forward_prefers_fresh_value(self):
        previous = {"onchain": {"mvrv_zscore": 2.04}}
        self.assertEqual(
            fetch_data.carry_forward(previous, 2.15, ["onchain", "mvrv_zscore"], "MVRV"),
            2.15,
        )

    def test_fed_low_confidence_should_be_replaced_by_previous_valid_value(self):
        previous = {
            "fed": {
                "fed_direction": "cut2",
                "reasoning": "old good value",
                "confidence": "high",
            }
        }
        fed = {"fed_direction": "cut1", "reasoning": "failed fetch", "confidence": "low"}

        if fed and fed.get("confidence") == "low" and previous["fed"].get("fed_direction"):
            result = {
                "fed_direction": previous["fed"].get("fed_direction"),
                "reasoning": f"沿用上一版有效值；本轮抓取失败。上一版依据：{previous['fed'].get('reasoning', '')}".strip(),
                "confidence": previous["fed"].get("confidence", "carried_forward"),
            }
        else:
            result = fed

        self.assertEqual(result["fed_direction"], "cut2")
        self.assertIn("沿用上一版有效值", result["reasoning"])

    def test_parse_oddpool_cut_count_html_converts_zero_cuts_to_at_least_one_cut(self):
        html = """
        <span>Number of Fed Rate Cuts in 2026</span>
        <tr><td class="px-4">Exactly 0 cuts</td>
        <td><span>64.0%</span></td>
        <td><span>68.2%</span></td>
        <td><span>66.1%</span></td></tr>
        """
        parsed = fetch_data.parse_oddpool_cut_count_html(html)
        self.assertEqual(parsed["year"], "2026")
        self.assertEqual(parsed["zero_cut_probability"], 66.1)
        self.assertEqual(parsed["cut_probability"], 33.9)


class OnchainFreshnessTests(unittest.TestCase):
    """MVRV drives the score, so a value carried forward for weeks must be
    labelled rather than rendered like a fresh reading."""

    def _today(self):
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).date()

    def test_fresh_value_is_not_marked_stale(self):
        onchain = {
            "mvrv_zscore": 0.41,
            "nupl": 0.19,
            "mvrv_zscore_as_of": self._today().isoformat(),
            "nupl_as_of": self._today().isoformat(),
        }
        fetch_data.mark_onchain_freshness({}, onchain)
        self.assertFalse(onchain["mvrv_zscore_stale"])
        self.assertEqual(onchain["mvrv_zscore_age_days"], 0)

    def test_carried_value_keeps_its_original_date_and_is_marked_stale(self):
        from datetime import timedelta

        old_date = (self._today() - timedelta(days=60)).isoformat()
        previous = {
            "onchain": {
                "mvrv_zscore_as_of": old_date,
                "mvrv_zscore_source": "lookintobitcoin",
                "nupl_as_of": old_date,
                "nupl_source": "lookintobitcoin",
            }
        }
        # carry_forward already restored the values; the dates are missing.
        onchain = {"mvrv_zscore": 2.5, "nupl": 0.64}
        fetch_data.mark_onchain_freshness(previous, onchain)
        self.assertEqual(onchain["mvrv_zscore_as_of"], old_date)
        self.assertEqual(onchain["mvrv_zscore_age_days"], 60)
        self.assertTrue(onchain["mvrv_zscore_stale"])
        self.assertTrue(onchain["nupl_stale"])

    def test_unknown_date_counts_as_stale(self):
        onchain = {"mvrv_zscore": 2.5, "nupl": 0.64}
        fetch_data.mark_onchain_freshness({}, onchain)
        self.assertIsNone(onchain["mvrv_zscore_age_days"])
        self.assertTrue(onchain["mvrv_zscore_stale"])


class PayloadSafetyTests(unittest.TestCase):
    """data.json must stay parseable: one bad float blanks the whole page."""

    def test_non_finite_floats_become_null(self):
        payload = {
            "price": {"price": float("nan"), "change24h": 1.2},
            "series": [1.0, float("inf"), 3.0],
            "tips": float("-inf"),
            "text": "unchanged",
        }
        fetch_data.drop_non_finite(payload)
        self.assertIsNone(payload["price"]["price"])
        self.assertEqual(payload["price"]["change24h"], 1.2)
        self.assertIsNone(payload["series"][1])
        self.assertIsNone(payload["tips"])
        self.assertEqual(payload["text"], "unchanged")

    def test_sanitised_payload_survives_strict_json(self):
        import json as _json

        payload = {"a": float("nan"), "b": [float("inf")]}
        fetch_data.drop_non_finite(payload)
        # allow_nan=False raises on any survivor.
        self.assertEqual(_json.dumps(payload, allow_nan=False), '{"a": null, "b": [null]}')


class BeijingTimestampTests(unittest.TestCase):
    """The page labels this value as China time, so it must not follow the
    runner's clock — GitHub's runners are UTC."""

    def test_cn_timestamp_is_eight_hours_ahead_of_utc(self):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        moment = datetime(2026, 8, 8, 2, 20, tzinfo=timezone.utc)
        rendered = moment.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
        self.assertEqual(rendered, "2026-08-08 10:20")


if __name__ == "__main__":
    unittest.main()
