import json
import pathlib
import unittest
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
BTC_HOST = "https://btc.flowhunt.net"


def read_text(path):
    return path.read_text(encoding="utf-8")


def sitemap_locs(path):
    root = ET.fromstring(read_text(path))
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [loc.text for loc in root.findall("sm:url/sm:loc", namespace)]


class BtcHalvingPageTests(unittest.TestCase):
    def test_halving_page_exists_with_safe_positioning(self):
        html = read_text(ROOT / "halving.html")
        self.assertIn("BTC 减半周期观察器", html)
        self.assertIn("仅作研究参考，不构成投资建议", html)
        self.assertIn("const TODAY    = new Date();", html)
        self.assertNotIn("new Date('2026-04-21')", html)
        for risky_phrase in ("预测", "底部", "买入", "卖出"):
            self.assertNotIn(risky_phrase, html)

    def test_halving_route_and_dashboard_link_exist(self):
        config = json.loads(read_text(ROOT / "vercel.json"))
        rewrites = {
            rewrite.get("source"): rewrite.get("destination")
            for rewrite in config.get("rewrites", [])
        }
        self.assertEqual(rewrites.get("/halving"), "/halving.html")
        self.assertIn('href="/halving"', read_text(ROOT / "index.html"))

    def test_btc_sitemap_and_robots_point_to_btc_host(self):
        locs = sitemap_locs(ROOT / "sitemap.xml")
        self.assertIn(f"{BTC_HOST}/halving", locs)
        self.assertFalse(any(loc and "stock.flowhunt.net" in loc for loc in locs))
        self.assertIn(f"Sitemap: {BTC_HOST}/sitemap.xml", read_text(ROOT / "robots.txt"))


if __name__ == "__main__":
    unittest.main()
