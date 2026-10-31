"""Local browser acceptance. Production assets never contain mocked quotes."""
import copy
import json
import pathlib
import sys
import tempfile
from datetime import datetime,timezone
from playwright.sync_api import sync_playwright

sys.path.insert(0,str(pathlib.Path(__file__).parent))
from test_btc_halving_page import serve_with_rewrites

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=pathlib.Path(tempfile.mkdtemp(prefix='btc-eth-observatory-qa-'))
OUT.mkdir(parents=True,exist_ok=True)
snapshot=json.loads((ROOT/'data/observatory.json').read_text())
checks=[]


def check(name,condition):
    assert condition,name
    checks.append(name)


with serve_with_rewrites() as base,sync_playwright() as p:
    browser=p.chromium.launch(headless=True,channel="chrome")
    context=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1)
    context.route('**/api/ticker?*',lambda r:r.fulfill(status=503,json={'error':'local preview has no edge runtime'}))
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    for symbol,path in [('BTC','/'),('ETH','/eth')]:
        for width in (1440,768,390,320):
            page.set_viewport_size({'width':width,'height':1000 if width>600 else 844})
            page.goto(base+path,wait_until='networkidle')
            page.locator('.metric-card').first.wait_for()
            check(f'{symbol} {width}px no page overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            check(f'{symbol} {width}px correct heading',page.locator('h1').inner_text()==symbol+' 低位观察台')
            check(f'{symbol} {width}px no image author impersonation','笑苍生' not in page.locator('body').inner_text())
            check(f'{symbol} {width}px chart rendered',page.locator('#priceChart svg').count()==1)
            check(f'{symbol} {width}px no false realtime quote',page.locator('#priceType').inner_text()=='最近完整日收盘')
            if width in (1440,390):
                page.screenshot(path=str(OUT/f'{symbol.lower()}-{width}.png'),full_page=True)
        page.locator('[data-range="90"]').click()
        check(f'{symbol} range switch',page.locator('#chartPeriod').inner_text()=='近 90 天')
        check(f'{symbol} range data actual', '90 个观测值' in page.locator('#chartSource').inner_text())
        page.locator('[data-filter="missing"]').click()
        check(f'{symbol} missing filter accurate',page.locator('.metric-card:not(.is-unavailable)').count()==0)
        page.locator('[data-filter="all"]').click()
        page.locator('.metric-card').first.click()
        check(f'{symbol} detail dialog',page.locator('dialog[open]').count()==1 and '数据来源' in page.locator('#dialogContent').inner_text())
        page.keyboard.press('Escape')
        check(f'{symbol} escape closes dialog',page.locator('dialog[open]').count()==0)
        page.locator('[data-method]').first.click()
        check(f'{symbol} method explains missing data','缺失项不会' in page.locator('#dialogContent').inner_text())
        page.locator('#closeDialog').click()
        page.locator('[data-reserve-window="30d"]').click()
        check(f'{symbol} reserve range',page.locator('[data-reserve-window="30d"]').get_attribute('aria-pressed')=='true')
        check(f'{symbol} reserve rows',page.locator('.reserve-row').count()>0)
        if symbol=='ETH':
            check('ETH no BTC mining cards',page.locator('[data-metric="miner_cost"]').count()==0)
            check('ETH no Bitcoin sentiment attribution',page.locator('#sentimentGrid').get_by_text('Alternative.me',exact=False).count()==0)
    # Verify realtime quote separately, using controlled test-only input.
    page.route('**/api/ticker?*',lambda r:r.fulfill(json={'symbol':'ETH','price':2345.67,'change24h':1.25,'source':'Coinbase','asOf':datetime.now(timezone.utc).isoformat()}))
    page.locator('#refresh').click()
    page.wait_for_function("document.querySelector('#priceType').textContent==='实时参考价'")
    check('realtime source displayed',page.locator('#quoteSource').inner_text()=='Coinbase')
    check('USD versus USDT pair distinguished',page.locator('#quotePair').inner_text()=='ETH/USD')
    # Every source becomes stale, but a loaded price history remains historical.
    stale=copy.deepcopy(snapshot)
    for a in stale['assets'].values():
        for m in a['metrics'].values():
            if m['value'] is not None:
                m['asOf']='2020-01-01';m['status']='fresh'
    page.route('**/data/observatory.json',lambda r:r.fulfill(json=stale))
    page.goto(base+'/',wait_until='networkidle')
    check('stale snapshot never lights signals',page.locator('.is-triggered').count()==0)
    check('stale score remains uncertainty interval','0' in page.locator('#gaugeValue').inner_text() and '100' in page.locator('#gaugeValue').inner_text())
    # XSS in an upstream label must remain text, not markup.
    hostile=copy.deepcopy(snapshot)
    hostile['assets']['BTC']['groups'][0]['items'][0]['label']='<img src=x onerror=window.__injected=1>'
    page.route('**/data/observatory.json',lambda r:r.fulfill(json=hostile))
    page.goto(base+'/',wait_until='networkidle')
    check('untrusted labels escaped',page.evaluate('window.__injected===undefined') and page.locator('.metric-label img').count()==0)
    # Failed fetch has an explicit empty state and permits retry.
    page.route('**/data/observatory.json',lambda r:r.fulfill(status=503,json={'error':'test unavailable'}))
    page.goto(base+'/',wait_until='networkidle')
    check('offline notice', '暂时无法读取数据' in page.locator('#dataNotice').inner_text())
    check('offline no recommendation',page.locator('#heroTitle').inner_text()=='等待有效数据')
    check('offline refresh usable',page.locator('#refresh').is_enabled())
    check('no uncaught JavaScript errors',not errors)
    context.close();browser.close()

(OUT/'verification.json').write_text(json.dumps({'checks':len(checks),'passed':checks,'javascript_errors':errors},ensure_ascii=False,indent=2))
print(json.dumps({'checks':len(checks),'screenshots':str(OUT),'javascript_errors':errors},ensure_ascii=False))
