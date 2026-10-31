"""Browser contracts for the new radar. Synthetic market values stay in tests."""
import copy
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime,timezone
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(pathlib.Path(__file__).parent))
from test_btc_halving_page import serve_with_rewrites

NOW=datetime(2026,10,31,12,tzinfo=timezone.utc)
STAMP=int(NOW.timestamp()*1000)-3600000
OUT=pathlib.Path(tempfile.mkdtemp(prefix='positioning-radar-qa-'))


def fixture():
    def m(v):return {'value':v,'asOf':STAMP,'source':'Test-only evidence','url':'https://example.com/evidence','note':''}
    rows=[]
    for i in range(12):
        symbol=['BTCUSDT','ETHUSDT'][i] if i<2 else f'COIN{i}USDT'
        rows.append({'symbol':symbol,'baseAsset':symbol[:-4],'network':None,'makers':[],
                     'metrics':{'topLong':m(.7),'accountLong':m(.3),'oiUsd':m(12000000),'oiUnits':m(120),
                                'priceChange':m(-1.2),'volumeUsd':m(20000000),'fundingRate':m(.01),'fundingHours':m(4),
                                'concentration':m(95 if i==0 else 94 if i==1 else None)}})
    return {'schemaVersion':1,'generatedAt':STAMP,'universeAsOf':STAMP,'universeTotal':12,'sampled':12,'rows':rows,'history':[],'errors':[]}


class RadarBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=serve_with_rewrites();cls.base=cls.server.__enter__()
        cls.p=sync_playwright().start();cls.browser=cls.p.chromium.launch(headless=True,channel='chrome')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.p.stop();cls.server.__exit__(None,None,None)
        print('Radar screenshots:',OUT)

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1440,'height':1000})
        self.data=fixture();self.status=200;self.errors=[]
        self.context.route('**/data/positioning-radar.json*',lambda r:r.fulfill(status=self.status,json=self.data))
        self.context.route('**/api/ticker?*',lambda r:r.fulfill(status=503,json={}))
        self.page=self.context.new_page();self.page.clock.install(time=NOW)
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))

    def tearDown(self):
        self.assertEqual(self.errors,[]);self.context.close()

    def start(self,path='/positioning-radar'):
        response=self.page.goto(self.base+path,wait_until='networkidle')
        self.assertEqual(response.status,200,'new radar route should serve the page')

    def test_all_reference_sections_and_mobile_layout(self):
        self.start()
        for name in ['大户与全体账户分歧','全体账户拥挤 · 多头','全体账户拥挤 · 空头','高集中度 ≥95%','90–95% 观察','高集中度币的多空','今日变化']:
            self.assertEqual(self.page.get_by_role('heading',name=name,exact=True).count(),1)
        for width in (1440,768,390,320):
            self.page.set_viewport_size({'width':width,'height':1000})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            if width in (1440,390):self.page.screenshot(path=str(OUT/f'radar-{width}.png'),full_page=True)

    def test_search_expand_and_evidence_dialog(self):
        self.start()
        self.assertEqual(self.page.locator('#radar-divergence tbody tr').count(),8)
        self.page.locator('#radar-divergence').get_by_role('button',name='展开全部').click()
        self.assertEqual(self.page.locator('#radar-divergence tbody tr').count(),12)
        self.page.get_by_label('搜索币种').fill('BTC')
        self.assertEqual(self.page.locator('#radar-market tbody tr').count(),1)
        self.page.locator('#radar-market tbody button').first.click()
        self.assertTrue(self.page.locator('#radarDialog').is_visible())
        self.assertIn('Test-only evidence',self.page.locator('#radarDetail').inner_text())
        self.page.keyboard.press('Escape');self.assertFalse(self.page.locator('#radarDialog').is_visible())

    def test_homepage_summary_agrees_with_full_page(self):
        for path in ('/','/eth'):
            self.start(path)
            self.assertEqual(self.page.locator('[data-radar-stat="divergence"]').inner_text(),'12')
            self.assertEqual(self.page.locator('[data-radar-stat="high"]').inner_text(),'1')
            self.assertEqual(self.page.locator('[data-radar-summary] a[href="/positioning-radar"]').count(),1)

    def test_stale_data_excluded_when_tab_returns(self):
        self.start();self.page.clock.fast_forward(4*3600000)
        self.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        self.assertEqual(self.page.locator('[data-radar-stat="divergence"]').inner_text(),'待核验')
        self.assertIn('过期',self.page.locator('#radarNotice').inner_text())

    def test_untrusted_text_and_links_remain_inert(self):
        self.data['rows'][0]['baseAsset']='<img src=x onerror=window.pwned=1>'
        self.data['rows'][0]['metrics']['topLong']['url']='javascript:alert(1)'
        self.start()
        self.page.locator('#radar-divergence tbody button').first.click()
        self.assertTrue(self.page.evaluate('window.pwned===undefined'))
        self.assertEqual(self.page.locator('#radarDetail a[href^="javascript:"]').count(),0)

    def test_offline_and_retry_do_not_show_zero_opportunities(self):
        self.status=503;self.start()
        self.assertIn('无法读取',self.page.locator('#radarNotice').inner_text())
        self.assertEqual(self.page.locator('[data-radar-stat="divergence"]').inner_text(),'待核验')
        self.status=200;self.page.get_by_role('button',name='刷新雷达').click()
        self.page.wait_for_function("document.querySelector('[data-radar-stat=divergence]').textContent==='12'")

    def test_near_neutral_proportions_do_not_display_as_fifty_percent(self):
        self.data['rows']=self.data['rows'][:1]
        self.data['rows'][0]['metrics']['topLong']['value']=.50001
        self.data['rows'][0]['metrics']['accountLong']['value']=.49999
        self.start()
        cells=self.page.locator('#radar-divergence tbody tr').first.locator('td')
        self.assertIn('50.001%',cells.nth(1).inner_text())
        self.assertIn('50.001%',cells.nth(2).inner_text())

    def test_keyboard_focus_and_horizontal_scroll_survive_render(self):
        self.start();self.page.set_viewport_size({'width':390,'height':844})
        button=self.page.locator('#radar-divergence').get_by_role('button',name='展开全部')
        button.focus();self.page.keyboard.press('Enter')
        self.assertEqual(self.page.evaluate("document.activeElement?.tagName==='BUTTON'?document.activeElement.textContent:''"),'收起')
        scroll=self.page.locator('#radar-divergence .radar-scroll')
        scroll.evaluate('(e)=>e.scrollLeft=150')
        self.page.clock.fast_forward(60000)
        self.assertEqual(self.page.evaluate("document.activeElement?.tagName==='BUTTON'?document.activeElement.textContent:''"),'收起')
        self.assertGreaterEqual(scroll.evaluate('(e)=>e.scrollLeft'),149)

    def test_concentration_detail_shows_excluded_amounts_and_denominator(self):
        self.data['rows'][0]['concentrationAudit']={'totalSupply':120,'excludedSupply':10,'remainingSupply':110,'adjustedTop10Balance':100,'excluded':[{'address':'0xsource','amount':10,'kind':'exchange','url':'https://example.com/address'}],'adjustedTop10':[],'omittedExcluded':0,'url':'https://example.com/ledger'}
        self.start();self.page.locator('#radar-high tbody button').first.click()
        text=self.page.locator('#radarDetail').inner_text()
        self.assertIn('剔除余额',text);self.assertIn('剩余供应',text);self.assertIn('0xsource',text)


if __name__=='__main__':unittest.main()
