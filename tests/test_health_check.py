import importlib.util, pathlib, sys, unittest
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("health_check", ROOT / "scripts" / "health_check.py")
hc = importlib.util.module_from_spec(spec); sys.modules["health_check"] = hc; spec.loader.exec_module(hc)


class HoursSinceTests(unittest.TestCase):
    def test_future_timestamp_is_not_healthy(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch
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


if __name__ == "__main__":
    unittest.main()
