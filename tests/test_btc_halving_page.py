import contextlib
import http.server
import json
import pathlib
import threading
import unittest
import urllib.request
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
BTC_HOST = "https://btc.flowhunt.net"


def read_text(path):
    return path.read_text(encoding="utf-8")


NAMESPACE = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def sitemap_locs(path):
    root = ET.fromstring(read_text(path))
    return [loc.text for loc in root.findall("sm:url/sm:loc", NAMESPACE)]


def sitemap_priority(path, loc):
    root = ET.fromstring(read_text(path))
    for url in root.findall("sm:url", NAMESPACE):
        if url.findtext("sm:loc", namespaces=NAMESPACE) == loc:
            return url.findtext("sm:priority", namespaces=NAMESPACE)
    return None


@contextlib.contextmanager
def serve_with_rewrites():
    """Serve the repo root the way Vercel does, applying vercel.json rewrites.

    A plain static server 404s on /halving because the extensionless route only
    exists as a rewrite. Applying the rewrites here lets the local check assert
    what actually ships instead of standing in for it.
    """
    config = json.loads(read_text(ROOT / "vercel.json"))
    rewrites = {
        rewrite.get("source"): rewrite.get("destination")
        for rewrite in config.get("rewrites", [])
    }

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def do_GET(self):
            self.path = rewrites.get(self.path, self.path)
            super().do_GET()

        def log_message(self, *args):
            pass

    class LocalServer(http.server.ThreadingHTTPServer):
        # A browser opens parallel connections for HTML/preloads/scripts/styles.
        # The default backlog of five sporadically resets a script connection.
        request_queue_size = 128

    server = LocalServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


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

    def test_halving_sitemap_entry_carries_expected_priority(self):
        priority = sitemap_priority(ROOT / "sitemap.xml", f"{BTC_HOST}/halving")
        self.assertEqual(priority, "0.8")

    def test_dashboard_nav_links_to_halving(self):
        html = read_text(ROOT / "index.html")
        start = html.find('href="/halving"')
        self.assertNotEqual(start, -1, 'no href="/halving" in index.html')
        self.assertIn("减半周期", html[start:html.find("</a>", start)])

    def test_halving_page_reads_generated_cycle_data(self):
        html = read_text(ROOT / "halving.html")
        self.assertIn("/data/halving-cycles.json", html)
        self.assertNotIn("$200,000", html, "no forward price ranges for the next cycle")
        data = json.loads(read_text(ROOT / "data" / "halving-cycles.json"))
        self.assertEqual(len(data["cycles"]), 4)
        self.assertEqual([c["halving"] for c in data["cycles"]], ["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20"])

    def test_halving_route_returns_200_locally(self):
        with serve_with_rewrites() as base_url:
            with urllib.request.urlopen(f"{base_url}/halving", timeout=5) as response:
                self.assertEqual(response.status, 200)
                body = response.read().decode("utf-8")
        self.assertIn("BTC 减半周期观察器", body)

    def test_halving_page_links_back_to_sibling_products(self):
        html = read_text(ROOT / "halving.html")
        for target in ('href="/"', 'href="/distribution-radar"', 'href="/eth"'):
            self.assertIn(target, html)

    def test_halving_page_preserves_core_modules(self):
        html = read_text(ROOT / "halving.html")
        for module in (
            "当前周期",
            "历史减半",
            "周期对比",
            "周期位置测算",
            "观察框架",
            "链上指标",
        ):
            self.assertIn(module, html)


if __name__ == "__main__":
    unittest.main()
