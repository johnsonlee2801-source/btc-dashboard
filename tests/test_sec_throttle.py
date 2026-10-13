import importlib.util
import pathlib
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("snapshot_sec", ROOT / "scripts" / "build_stock_breadth_snapshot.py")
snap = importlib.util.module_from_spec(spec)
sys.modules["snapshot_sec"] = snap
spec.loader.exec_module(snap)


class SecThrottleTests(unittest.TestCase):
    def test_only_sec_hosts_are_throttled(self):
        self.assertTrue(snap._is_sec("https://www.sec.gov/Archives/x.txt"))
        self.assertTrue(snap._is_sec("https://data.sec.gov/submissions/CIK1.json"))
        self.assertFalse(snap._is_sec("https://query1.finance.yahoo.com/v8/finance/chart/SPY"))
        self.assertFalse(snap._is_sec("https://notsec.gov.example.com/"))

    def test_requests_are_spaced_under_sec_limit(self):
        # SEC 上限每秒 10 个；连续 9 次请求至少要隔开 8 个间隔
        snap._sec_next_at = 0.0
        start = time.monotonic()
        for _ in range(9):
            snap._sec_throttle()
        self.assertGreaterEqual(time.monotonic() - start, 8 * snap.SEC_MIN_INTERVAL - 0.01)


if __name__ == "__main__":
    unittest.main()
