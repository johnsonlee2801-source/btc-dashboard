"""Browser regression contracts; fixtures are confined to local test contexts."""
import copy
import json
import pathlib
import re
import sys
import unittest
from datetime import datetime,timedelta,timezone
from playwright.sync_api import sync_playwright

sys.path.insert(0,str(pathlib.Path(__file__).parent))
from test_btc_halving_page import serve_with_rewrites

ROOT=pathlib.Path(__file__).resolve().parents[1]
NOW=datetime(2026,10,30,12,tzinfo=timezone.utc)


class BrowserPlanContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=serve_with_rewrites();cls.base=cls.server.__enter__()
        cls.p=sync_playwright().start();cls.browser=cls.p.chromium.launch(headless=True,channel='chrome')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.p.stop();cls.server.__exit__(None,None,None)

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1440,'height':1000})
        self.fixture=json.loads((ROOT/'data/observatory.json').read_text())
        self.fixture['generatedAt']=NOW.isoformat()
        for asset in self.fixture['assets'].values():
            for m in asset['metrics'].values():
                if m['value'] is not None:m['asOf']=NOW.isoformat();m['status']='fresh'
        self.quote={'symbol':'BTC','price':80000,'source':'Binance','change24h':1,'asOf':NOW.isoformat()}
        self.context.route('**/api/ticker?*',lambda r:r.fulfill(json=self.quote))

    def tearDown(self):self.context.close()

    def start(self,fixture=None):
        data=copy.deepcopy(fixture or self.fixture)
        self.context.route('**/data/observatory.json',lambda r:r.fulfill(json=data))
        page=self.context.new_page();page.clock.install(time=NOW)
        page.goto(self.base+'/',wait_until='networkidle')
        page.locator('.metric-card').first.wait_for()
        return page

    def resume(self,page,hours=2):
        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
        page.clock.fast_forward(hours*3600000)
        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'))")

    def test_returning_to_a_background_tab_does_not_label_an_expired_quote_realtime(self):
        page=self.start();self.assertEqual(page.locator('#priceType').inner_text(),'实时参考价')
        self.resume(page)
        self.assertNotEqual(page.locator('#priceType').inner_text(),'实时参考价')

    def test_quote_for_another_asset_is_rejected(self):
        self.quote={**self.quote,'symbol':'ETH','price':2345}
        page=self.start()
        self.assertEqual(page.locator('#priceType').inner_text(),'最近完整日收盘')

    def test_etf_and_exchange_freshness_is_rechecked_after_a_background_interval(self):
        data=copy.deepcopy(self.fixture)
        stamp=(NOW-timedelta(days=6,hours=23)).isoformat()
        data['assets']['BTC']['etf']={'asOf':stamp,'source':'Farside','sourceUrl':'https://farside.co.uk/bitcoin-etf/',
                                    'rows':[{'date':'2026-10-23','value':1.0}]}
        cex=json.loads((ROOT/'data/cex-reserves.json').read_text())
        cex['anchor']=(NOW-timedelta(hours=59)).isoformat()
        for a in cex['assets'].values():
            for row in a['exchanges']:row['asOf']=cex['anchor'];row['stale']=False
        self.context.route('**/data/cex-reserves.json',lambda r:r.fulfill(json=cex))
        page=self.start(data)
        self.assertIn('有效',page.locator('#flowSubtitle').inner_text())
        self.assertEqual(page.locator('.reserve-row').first.locator('small').inner_text(),'储备变化')
        self.resume(page)
        self.assertIn('已过期',page.locator('#flowSubtitle').inner_text())
        self.assertEqual(page.locator('.reserve-row').first.locator('small').inner_text(),'历史记录')

    def test_display_rounding_cannot_contradict_an_active_threshold(self):
        for key,value,threshold in [('supply_profit',59.96,60),('sopr',.99996,1),('mayer',.7999,.8),('weekly_rsi',34.6,35)]:
            with self.subTest(metric=key):
                data=copy.deepcopy(self.fixture);data['assets']['BTC']['metrics'][key]['value']=value
                page=self.start(data)
                card=page.locator(f'[data-group="0"][data-metric="{key}"]')
                self.assertIn('is-triggered',card.get_attribute('class'))
                text=card.locator('.metric-value').inner_text().replace('%','').replace(',','').strip()
                self.assertLess(float(text),threshold,'Rounded visible value must remain on the triggered side')
                card.click()
                detail=page.locator('.detail-value').inner_text().replace('%','').replace(',','').strip()
                self.assertLess(float(detail),threshold)
                page.close()

    def test_expired_dependency_keeps_the_derived_tile_unknown(self):
        data=copy.deepcopy(self.fixture)
        m=data['assets']['BTC']['metrics']['price_ma200w']
        m.update(value=.6,dependencies={'price':{'asOf':NOW.isoformat(),'maxAgeHours':72},
                                      'ma200w':{'asOf':'2026-09-27','maxAgeHours':216}})
        page=self.start(data)
        card=page.locator('[data-metric="price_ma200w"]')
        self.assertIn('is-unavailable',card.get_attribute('class'))
        self.assertNotIn('is-triggered',card.get_attribute('class'))

    def test_chart_does_not_compress_or_interpolate_missing_calendar_days(self):
        data=copy.deepcopy(self.fixture)
        data['assets']['BTC']['history']=[{'date':day,'close':price,'ma200':None} for day,price in
                                        [('2026-01-01',100),('2026-01-02',110),('2026-04-01',120)]]
        page=self.start(data)
        path=page.locator('#priceChart svg path[stroke="#ffb547"]').get_attribute('d')
        coordinates=re.findall(r'[ML]([\d.]+)\s+([\d.]+)',path)
        xs=[float(x) for x,y in coordinates]
        self.assertLess((xs[1]-xs[0])/(xs[2]-xs[0]),.05,'Jan 2 should be near Jan 1, not halfway to Apr 1')
        self.assertEqual(path.count('M'),2,'No synthetic price segment across the missing dates')


if __name__=='__main__':unittest.main(verbosity=2)
