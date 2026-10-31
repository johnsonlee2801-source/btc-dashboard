"""Independent contracts: data errors must not create trading observations."""
import copy
import importlib.util
import pathlib
import unittest
import tempfile
import json
from unittest.mock import patch

PATH = pathlib.Path(__file__).resolve().parents[1] / 'scripts/build_positioning_radar.py'
radar = None
if PATH.exists():
    spec = importlib.util.spec_from_file_location('radar', PATH)
    radar = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(radar)

NOW = 1793448000000
T = NOW - 3600000
INFO = {'symbol': 'BTCUSDT', 'baseAsset': 'BTC'}


def sources():
    return {
        'top': [{'symbol':'BTCUSDT','timestamp':T-86400000,'longAccount':'0.60','shortAccount':'0.40'},
                {'symbol':'BTCUSDT','timestamp':T,'longAccount':'0.65','shortAccount':'0.35'}],
        'accounts': [{'symbol':'BTCUSDT','timestamp':T-86400000,'longAccount':'0.40','shortAccount':'0.60'},
                     {'symbol':'BTCUSDT','timestamp':T,'longAccount':'0.30','shortAccount':'0.70'}],
        'oi': [{'symbol':'BTCUSDT','timestamp':T-86400000,'sumOpenInterestValue':'10000000','sumOpenInterest':'100'},
               {'symbol':'BTCUSDT','timestamp':T,'sumOpenInterestValue':'12000000','sumOpenInterest':'120'}],
        'ticker': {'symbol':'BTCUSDT','closeTime':T,'priceChangePercent':'0','quoteVolume':'15000000'},
        'funding': [{'symbol':'BTCUSDT','fundingTime':T-14400000,'fundingRate':'0.0001'},
                    {'symbol':'BTCUSDT','fundingTime':T,'fundingRate':'0'}],
    }


class CollectorContracts(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(radar, 'public radar collector not implemented')

    def row(self, data=None, previous=None):
        return radar.build_row(INFO, sources() if data is None else data, previous, NOW)

    def test_hand_calculated_deltas_and_units(self):
        m=self.row()['metrics']
        self.assertAlmostEqual(m['topDelta']['value'],5)
        self.assertAlmostEqual(m['accountDelta']['value'],-10)
        self.assertAlmostEqual(m['oiDelta']['value'],20)
        self.assertEqual(m['oiUsd']['value'],12000000)
        self.assertEqual(m['oiUnits']['value'],120)

    def test_zero_price_change_and_settled_funding_are_real(self):
        m=self.row()['metrics']
        self.assertEqual(m['priceChange']['value'],0)
        self.assertEqual(m['fundingRate']['value'],0)
        self.assertEqual(m['fundingHours']['value'],4)
        self.assertEqual(m['fundingRate']['asOf'],T)

    def test_missing_exact_24h_is_not_previous_point(self):
        data=sources();data['top'][0]['timestamp']+=3600000
        self.assertIsNone(self.row(data)['metrics']['topDelta']['value'])

    def test_wrong_asset_is_rejected(self):
        data=sources()
        for entry in data['top']:entry['symbol']='ETHUSDT'
        self.assertIsNone(self.row(data)['metrics']['topLong']['value'])

    def test_future_and_invalid_proportions_are_rejected(self):
        data=sources();data['top'][-1]['timestamp']=NOW+1
        self.assertNotEqual(self.row(data)['metrics']['topLong']['asOf'],NOW+1)
        data=sources();data['top'][-1]['longAccount']='1.4'
        self.assertIsNone(self.row(data)['metrics']['topLong']['value'])
        data=sources();data['top'][-1]['shortAccount']='0.5'
        self.assertIsNone(self.row(data)['metrics']['topLong']['value'])

    def test_failure_retains_value_and_source_date(self):
        old=self.row();data=sources();data['top']=None
        m=self.row(data,old)['metrics']
        self.assertEqual(m['topLong']['value'],.65)
        self.assertEqual(m['topLong']['asOf'],T)
        self.assertIn('保留',m['topLong']['note'])

    def test_current_ratio_does_not_retain_yesterdays_delta(self):
        old=self.row();data=sources();data['top']=data['top'][-1:]
        self.assertIsNone(self.row(data,old)['metrics']['topDelta']['value'])

    def test_source_dates_not_changed_to_collection_time(self):
        data=sources();data['accounts'][-1]['timestamp']-=3600000
        self.assertEqual(self.row(data)['metrics']['accountLong']['asOf'],T-3600000)

    def test_absent_identity_and_chain_are_unknown(self):
        row=self.row()
        self.assertIsNone(row['network'])
        self.assertIsNone(row['metrics']['concentration']['value'])
        self.assertEqual(row['makers'],[])

    def test_unknown_supply_cannot_become_circulation_or_control(self):
        row=self.row()
        radar.apply_evidence(row,{'circulating':100,'total':100,'concentration':99,'makers':['Fake']},NOW)
        self.assertIsNone(row['metrics']['concentration']['value'])
        self.assertIsNone(row['metrics']['circulation']['value'])
        self.assertEqual(row['makers'],[])

    def test_numeric_parser_rejects_booleans_empty_and_infinity(self):
        for v in (True,'',None,'NaN','Infinity'):
            self.assertIsNone(radar.number(v))

    def test_complete_evidence_ledger_derives_control_without_trusting_input_percentage(self):
        row=radar.build_row({'symbol':'TESTUSDT','baseAsset':'TEST'},{},None,NOW)
        holders=[{'address':str(i),'balance':10,'locked':0,'kind':'unknown','evidenceUrl':'https://example.com/ledger'} for i in range(12)]
        evidence={'symbol':'TESTUSDT','baseAsset':'TEST','asOf':T,'url':'https://example.com/supply','source':'fixture',
                  'network':'Testchain','address':'0xverified','total':120,'circulating':30,'supplyComparable':True,
                  'ledgerComplete':True,'holders':holders,'concentration':99,'unlockComplete':True,'unlock30d':3}
        radar.apply_evidence(row,evidence,NOW)
        self.assertAlmostEqual(row['metrics']['concentration']['value'],83.33333333333333)
        self.assertEqual(row['metrics']['circulation']['value'],25)
        self.assertEqual(row['metrics']['unlockPct']['value'],10)
        holders[0]['kind']='exchange'
        radar.apply_evidence(row,evidence,NOW)
        self.assertAlmostEqual(row['metrics']['concentration']['value'],90.9090909090909)
        self.assertIn('concentrationAudit',row,'calculation evidence was discarded')
        self.assertEqual(row['concentrationAudit']['excludedSupply'],10)
        self.assertEqual(row['concentrationAudit']['remainingSupply'],110)
        self.assertEqual(row['concentrationAudit']['adjustedTop10Balance'],100)
        self.assertEqual(row['concentrationAudit']['excluded'][0]['address'],'0')

    def test_latest_common_fresh_window_is_used_when_endpoints_lag(self):
        data=sources()
        for key in ('top','accounts','oi'):
            mid=copy.deepcopy(data[key][-1]);mid['timestamp']=T-3600000;data[key].insert(1,mid)
        data['accounts'].pop()
        row=self.row(data)
        self.assertEqual(row['metrics']['topLong']['asOf'],T-3600000)
        self.assertEqual(row['metrics']['oiUsd']['asOf'],T-3600000)
        self.assertIsNone(row['metrics']['topDelta']['value'])

    def test_public_source_failure_produces_publishable_degraded_state_without_redating(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);(root/'data').mkdir()
            previous={'schemaVersion':1,'generatedAt':T,'universeAsOf':T,'universeTotal':1,'rows':[self.row()],'history':[]}
            target=root/'data/positioning-radar.json';target.write_text(json.dumps(previous))
            error=None
            with patch.object(radar,'ROOT',root),patch.object(radar.PublicClient,'get',side_effect=RuntimeError('HTTP 451')),patch('sys.argv',['collector']),patch.object(radar.time,'time',return_value=NOW/1000):
                try:radar.main()
                except (Exception,SystemExit) as exc:error=exc
            self.assertIsNone(error,'a valid degraded snapshot must reach the state-publishing workflow')
            result=json.loads(target.read_text())
            self.assertEqual(result['dataStatus'],'unavailable')
            self.assertEqual(result['universeAsOf'],T)
            self.assertEqual(result['rows'][0]['metrics']['topLong']['asOf'],T)
            self.assertIn('451',result['errors'][0]['error'])

    def test_failed_evidence_validation_does_not_keep_an_unverified_numeric_claim(self):
        row=radar.build_row({'symbol':'TESTUSDT','baseAsset':'TEST'},{},None,NOW)
        evidence={'symbol':'TESTUSDT','baseAsset':'TEST','asOf':T,'url':'https://example.com/supply',
                  'network':'Testchain','address':'0xverified','total':100,'ledgerComplete':True,
                  'holders':[{'address':'a','balance':100,'locked':-1,'kind':'unknown','evidenceUrl':'https://example.com/a'}]}
        radar.apply_evidence(row,evidence,NOW)
        self.assertIsNone(row['metrics']['concentration']['value'])

    def test_fresh_snapshot_with_no_usable_positions_fails_health_gate(self):
        self.assertTrue(callable(getattr(radar,'snapshot_healthy',None)),'usable-position health gate missing')
        self.assertFalse(radar.snapshot_healthy({'rows':[self.row({'ticker':sources()['ticker']})]},NOW))
        self.assertTrue(radar.snapshot_healthy({'rows':[self.row()]},NOW))

    def test_historical_deltas_reject_invalid_old_ratio(self):
        data=sources();data['accounts'][0]['longAccount']='2'
        self.assertIsNone(self.row(data)['metrics']['accountDelta']['value'])

    def test_universe_excludes_inactive_delivery_and_noncrypto(self):
        base=dict(INFO,status='TRADING',contractType='PERPETUAL',quoteAsset='USDT',underlyingType='COIN')
        rows=[base,dict(base,symbol='OLD',status='SETTLING'),dict(base,symbol='QUARTER',contractType='CURRENT_QUARTER'),dict(base,symbol='INDEX',underlyingType='INDEX')]
        self.assertEqual([r['symbol'] for r in radar.universe({'symbols':rows})],['BTCUSDT'])

    def test_history_is_bounded_and_deduplicated(self):
        old=[{'asOf':NOW-31*86400000,'rows':[]},{'asOf':T,'rows':[]}]
        history=radar.history_append(old,{'asOf':T,'rows':[]},NOW)
        self.assertEqual(len(history),1)


if __name__=='__main__':unittest.main()
