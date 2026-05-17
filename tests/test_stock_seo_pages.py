import json
import pathlib
import unittest
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
MVP_TICKERS = ("nvda", "tsla", "pltr", "amd", "smci")
STOCK_HOST = "https://stock.flowhunt.net"
BANNED_DIRECT_RECOMMENDATIONS = (
    "建议买入",
    "建议卖出",
    "可以买",
    "应该买",
    "应该卖",
    "清仓",
    "满仓",
)


def read_text(path):
    return path.read_text(encoding="utf-8")


def sitemap_locs(path):
    root = ET.fromstring(read_text(path))
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [loc.text for loc in root.findall("sm:url/sm:loc", namespace)]


class StockSeoPageTests(unittest.TestCase):
    def test_mvp_stock_pages_exist_and_have_static_core_content(self):
        for ticker in MVP_TICKERS:
            with self.subTest(ticker=ticker):
                path = ROOT / f"stock-{ticker}-risk.html"
                self.assertTrue(path.exists(), f"{path.name} should exist")

                html = read_text(path)
                self.assertRegex(html, r"<h1\b[^>]*>.*?</h1>")
                self.assertIn("三条关键证据", html)
                self.assertIn("下一步该查什么", html)
                self.assertIn("不构成投资建议", html)
                self.assertIn(
                    f'<link rel="canonical" href="{STOCK_HOST}/stock/{ticker}-risk">',
                    html,
                )

    def test_mvp_stock_pages_have_repeated_evidence_metadata(self):
        expected_labels = ("来源 / 更新时间", "局限", "下一步检查")
        for ticker in MVP_TICKERS:
            with self.subTest(ticker=ticker):
                html = read_text(ROOT / f"stock-{ticker}-risk.html")
                for label in expected_labels:
                    self.assertGreaterEqual(
                        html.count(label),
                        3,
                        f"{ticker} should include at least 3 occurrences of {label}",
                    )

    def test_mvp_stock_pages_do_not_include_direct_recommendations(self):
        for ticker in MVP_TICKERS:
            with self.subTest(ticker=ticker):
                html = read_text(ROOT / f"stock-{ticker}-risk.html")
                for phrase in BANNED_DIRECT_RECOMMENDATIONS:
                    self.assertNotIn(phrase, html)

    def test_mvp_stock_pages_include_engagement_event_hooks(self):
        expected_hooks = (
            "stock_seo_evidence_view",
            "stock_seo_link_click",
            "stock-seo-engagement",
        )
        for ticker in MVP_TICKERS:
            with self.subTest(ticker=ticker):
                html = read_text(ROOT / f"stock-{ticker}-risk.html")
                for hook in expected_hooks:
                    self.assertIn(hook, html)

    def test_vercel_rewrites_include_all_mvp_clean_stock_routes(self):
        config = json.loads(read_text(ROOT / "vercel.json"))
        rewrites = {
            rewrite.get("source"): rewrite.get("destination")
            for rewrite in config.get("rewrites", [])
        }

        for ticker in MVP_TICKERS:
            with self.subTest(ticker=ticker):
                self.assertEqual(
                    rewrites.get(f"/stock/{ticker}-risk"),
                    f"/stock-{ticker}-risk.html",
                )

    def test_stock_sitemap_includes_stock_index_and_all_mvp_stock_urls(self):
        locs = sitemap_locs(ROOT / "sitemap-stock.xml")
        self.assertIn(f"{STOCK_HOST}/stock", locs)

        for ticker in MVP_TICKERS:
            with self.subTest(ticker=ticker):
                self.assertIn(f"{STOCK_HOST}/stock/{ticker}-risk", locs)

    def test_main_sitemap_does_not_include_stock_host_urls(self):
        locs = sitemap_locs(ROOT / "sitemap.xml")
        self.assertFalse(
            any(loc and "stock.flowhunt.net" in loc for loc in locs),
            "sitemap.xml should not include stock.flowhunt.net URLs",
        )

    def test_stock_index_canonical_points_to_stock_host(self):
        html = read_text(ROOT / "stock.html")
        self.assertIn(
            f'<link rel="canonical" href="{STOCK_HOST}/stock">',
            html,
        )

    def test_no_extra_stock_risk_pages_exist_beyond_mvp_tickers(self):
        expected = {f"stock-{ticker}-risk.html" for ticker in MVP_TICKERS}
        actual = {path.name for path in ROOT.glob("stock-*-risk.html")}
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
