import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DistributionRadarLabelsTests(unittest.TestCase):
    def test_fiat_spot_premium_is_not_labeled_as_us_session_when_fallback_sources_exist(self):
        html = (ROOT / "distribution-radar.html").read_text(encoding="utf-8")
        api = (ROOT / "api" / "distribution-radar.js").read_text(encoding="utf-8")
        combined = html + "\n" + api
        self.assertIn("美元现货溢价", combined)
        self.assertNotIn("美盘现货溢价", combined)
        self.assertNotIn("美盘/法币现货溢价", combined)
        self.assertNotIn("美盘溢价", combined)


if __name__ == "__main__":
    unittest.main()
