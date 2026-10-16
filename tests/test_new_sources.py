import importlib.util, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m); return m
eth = _load("eth_src", "scripts/fetch_eth_data.py")
snap = _load("snap_src", "scripts/build_stock_breadth_snapshot.py")


class BlockscoutWhaleTests(unittest.TestCase):
    def test_contracts_excluded_multisig_kept(self):
        # Blockscout 富豪榜前 100：质押合约/WETH/桥排除，多签钱包与 EOA 保留
        import json
        BS = eth.fetch_blockscout_top_accounts  # smoke: function exists
        self.assertTrue(callable(BS))
        self.assertTrue(eth.WALLET_CONTRACT.search("GnosisSafeProxy"))
        self.assertIsNone(eth.WALLET_CONTRACT.search("DepositContract"))


class CboeSkewTests(unittest.TestCase):
    def test_latest_row_parsed_and_classified(self):
        csv = "DATE,SKEW\n10/14/2026,157.300000\n10/15/2026,160.450000\n"
        import unittest.mock as mock
        with mock.patch.object(snap, "fetch_text", return_value=csv):
            r = snap.parse_cboe_skew()
        self.assertEqual(r["value"], 160.45)
        self.assertEqual(r["updatedAt"], "2026-10-15")
        self.assertEqual(r["status"], "distribution")

    def test_rejects_garbage(self):
        import unittest.mock as mock
        with mock.patch.object(snap, "fetch_text", return_value="<html>blocked</html>"):
            self.assertIsNone(snap.parse_cboe_skew())


class EthDataShapeTests(unittest.TestCase):
    def test_staking_concentration_present_lth_distribution_null(self):
        import json
        d = json.loads((ROOT / "eth-data.json").read_text(encoding="utf-8"))
        self.assertIsInstance(d.get("stake_conc_top5"), (int, float))
        self.assertIsInstance(d.get("whale_top100_pct"), (int, float))
        self.assertIsNone(d.get("lth_pct"))
        self.assertIsNone(d.get("distribution"))


if __name__ == "__main__":
    unittest.main()
