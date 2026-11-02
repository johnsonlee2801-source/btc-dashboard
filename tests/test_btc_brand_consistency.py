import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BRAND = "FlowHunt｜流程猎人"
PAGES = (
    "index.html",
    "eth.html",
    "distribution-radar.html",
    "halving.html",
    "positioning-radar.html",
)


class BtcBrandConsistencyTests(unittest.TestCase):
    def test_core_btc_pages_use_same_visible_brand_text(self):
        for page in PAGES:
            with self.subTest(page=page):
                html = (ROOT / page).read_text(encoding="utf-8")
                self.assertIn(BRAND, html)

    def test_core_btc_pages_keep_page_specific_professional_subtitle(self):
        # Each page names itself in its own <h1>; the shared header carries the brand.
        expected = {
            "index.html": "<h1>BTC 低位观察台</h1>",
            "eth.html": "<h1>ETH 低位观察台</h1>",
            "distribution-radar.html": "BTC 派发雷达</h1>",
            "halving.html": "BTC 减半周期观察器</h1>",
        }
        for page, subtitle in expected.items():
            with self.subTest(page=page):
                html = (ROOT / page).read_text(encoding="utf-8")
                self.assertIn(subtitle, html)


class SharedShellTests(unittest.TestCase):
    def test_every_page_uses_the_shared_header_and_links_all_sections(self):
        for page in PAGES:
            with self.subTest(page=page):
                html = (ROOT / page).read_text(encoding="utf-8")
                self.assertIn('/assets/site.css', html)
                self.assertIn('class="site-header"', html)
                for href in ('href="/"', 'href="/eth"', 'href="/positioning-radar"', 'href="/distribution-radar"', 'href="/halving"'):
                    self.assertIn(href, html)
                self.assertEqual(html.count('aria-current="page"'), 1)


if __name__ == "__main__":
    unittest.main()
