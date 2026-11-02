"""Browser contracts for the v2 observatory pages. Run manually: python3 tests/qa_observatory_contract.py

Uses the committed snapshot with a frozen clock; fixtures stay inside the test browser context.
"""
import copy
import json
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_btc_halving_page import serve_with_rewrites  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


class BrowserContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = serve_with_rewrites()
        cls.base = cls.server.__enter__()
        cls.p = sync_playwright().start()
        cls.browser = cls.p.chromium.launch(headless=True, channel='chrome', args=['--disable-gpu'])
        cls.snapshot = json.loads((ROOT / 'data/observatory.json').read_text())
        cls.now = datetime.fromisoformat(cls.snapshot['generatedAt'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()
        cls.server.__exit__(None, None, None)

    def open(self, path='/', snapshot=None, quote=None, now=None):
        ctx = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        data = copy.deepcopy(snapshot or self.snapshot)
        ctx.route('**/data/observatory.json', lambda r: r.fulfill(json=data))
        q = quote or {'symbol': 'BTC' if path == '/' else 'ETH', 'price': 70000 if path == '/' else 2000,
                      'source': 'Binance', 'change24h': -1.2, 'asOf': (now or self.now).isoformat()}
        ctx.route('**/api/ticker?*', lambda r: r.fulfill(json=q))
        page = ctx.new_page()
        page.clock.install(time=now or self.now)
        page.goto(self.base + path, wait_until='load')
        page.locator('.card').first.wait_for()
        self.addCleanup(ctx.close)
        return page

    def test_btc_page_renders_every_section(self):
        page = self.open('/')
        for sel in ('#verdict .verdict-title', '#combo .bar-row', '#band .zone', '#trend svg', '.group', '#ladder .rung', '#sentiment .senti'):
            self.assertGreater(page.locator(sel).count(), 0, sel)
        self.assertEqual(page.locator('.group .card').count(), 16)

    def test_trigger_distance_uses_the_live_quote(self):
        page = self.open('/')
        page.wait_for_function("document.getElementById('price').textContent.includes('70,000')")
        line = page.locator('.verdict-line').inner_text()
        self.assertIn('还需跌', line)

    def test_a_quote_for_another_asset_is_ignored(self):
        page = self.open('/', quote={'symbol': 'ETH', 'price': 2000, 'source': 'Binance', 'change24h': 0, 'asOf': self.now.isoformat()})
        page.wait_for_timeout(800)
        self.assertNotIn('2,000', page.locator('#price').inner_text())

    def test_an_old_snapshot_is_flagged_and_its_signals_expire(self):
        later = self.now + timedelta(days=12)
        page = self.open('/', now=later, quote={'symbol': 'BTC', 'price': 70000, 'source': 'Binance', 'change24h': 0, 'asOf': later.isoformat()})
        notice = page.locator('#dataNotice').inner_text()
        self.assertIn('未更新', notice)
        self.assertEqual(page.locator('.group .card.lit').count(), 0, 'expired inputs must not stay lit')

    def test_eth_page_has_no_btc_score(self):
        page = self.open('/eth')
        self.assertEqual(page.locator('.ring').count(), 1)
        self.assertEqual(page.locator('#band').count(), 0)
        self.assertEqual(page.locator('.group .card').count(), 6)

    def test_no_page_errors(self):
        for path in ('/', '/eth', '/halving'):
            errors = []
            ctx = self.browser.new_context()
            page = ctx.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(self.base + path, wait_until='load')
            page.wait_for_timeout(1500)
            ctx.close()
            self.assertEqual(errors, [], path)


if __name__ == '__main__':
    unittest.main()
