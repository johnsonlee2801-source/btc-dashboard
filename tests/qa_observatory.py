"""Manual browser smoke test for all five pages: python3 tests/qa_observatory.py [output_dir]

Desktop and mobile viewports; fails on page errors or horizontal overflow and saves full-page
screenshots for a visual pass. External APIs are left unmocked, so live-only panels may be empty.
"""
import pathlib
import sys
import tempfile
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_btc_halving_page import serve_with_rewrites  # noqa: E402

PAGES = ('/', '/eth', '/halving', '/distribution-radar', '/positioning-radar')
VIEWPORTS = {'desktop': (1440, 900), 'mobile': (390, 844)}


def main():
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(tempfile.mkdtemp(prefix='flowhunt-qa-'))
    out.mkdir(parents=True, exist_ok=True)
    failures = []
    with serve_with_rewrites() as base, sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel='chrome', args=['--disable-gpu'])
        for name, (w, h) in VIEWPORTS.items():
            ctx = browser.new_context(viewport={'width': w, 'height': h})
            for path in PAGES:
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e, errors=errors: errors.append(str(e)))
                page.goto(base + path, wait_until='load')
                page.wait_for_timeout(2500)
                overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
                shot = out / f"{name}-{path.strip('/') or 'btc'}.png"
                page.screenshot(path=str(shot), full_page=True)
                status = 'ok' if not errors and overflow <= 0 else 'FAIL'
                if status == 'FAIL':
                    failures.append((name, path, errors[:2], overflow))
                print(f'{status:4} {name:7} {path:20} overflow={overflow} errors={errors[:2]}')
                page.close()
            ctx.close()
        browser.close()
    print('screenshots:', out)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
