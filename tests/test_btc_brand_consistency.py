import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BRAND = "FlowHunt｜流程猎人 · 算盘"
PAGES = (
    "index.html",
    "eth.html",
    "distribution-radar.html",
    "halving.html",
)


class BtcBrandConsistencyTests(unittest.TestCase):
    def test_core_btc_pages_use_same_visible_brand_text(self):
        for page in PAGES:
            with self.subTest(page=page):
                html = (ROOT / page).read_text(encoding="utf-8")
                self.assertIn(BRAND, html)

    def test_core_btc_pages_keep_page_specific_professional_subtitle(self):
        expected = {
            "index.html": "BTC 评分仪表盘 · 链上数据 / 风险温度 / 周期观察",
            "eth.html": "ETH 链上观察 · 筹码集中度 / 交易所净流量 / 质押结构",
            "distribution-radar.html": "BTC 派发雷达 · 上涨质量 / 承接强弱 / 合约推动风险",
            "halving.html": "BTC 减半周期观察 · 历史节奏 / 周期位置 / 风险温度",
        }
        for page, subtitle in expected.items():
            with self.subTest(page=page):
                html = (ROOT / page).read_text(encoding="utf-8")
                self.assertIn(subtitle, html)


if __name__ == "__main__":
    unittest.main()
