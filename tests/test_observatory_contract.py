"""Plan-level oracles and source-failure regressions; no live requests/writes."""
import copy
import importlib.util
import io
import json
import pathlib
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('observatory_contract_subject',ROOT/'scripts/build_observatory.py')
obs=importlib.util.module_from_spec(spec)
spec.loader.exec_module(obs)


class PlanContractTests(unittest.TestCase):
    def test_btc_all_21_thresholds_match_the_written_observation_model(self):
        expected=[
            [('supply_profit','<',60),('weekly_rsi','<',35),('miner_cost','<',1),('sopr','<',1),('mayer','<',.8)],
            [('mvrv_z','<',-1),('supply_profit','<',50),('price_ma200w','<',1),('mvrv','<',1),('nupl','<',0),('puell','<',.5),('weekly_rsi','<',30),('pi_cycle','<',1)],
            [('sth_mvrv','<',1),('sth_profit','<',30),('fear','<=',20),('hash_ribbon','>',0),('lth_net30','>',0),('whale_net30','>',0),('puell','<',.7),('drawdown90','>=',20)],
        ]
        self.assertEqual([g[2] for g in obs.BTC_RULES],[40,40,20])
        self.assertEqual([[(r[0],r[2],r[3]) for r in g[3]] for g in obs.BTC_RULES],expected)

    def test_every_threshold_keeps_its_strict_or_inclusive_boundary(self):
        now=datetime(2026,10,30,12,tzinfo=timezone.utc)
        for group in obs.BTC_RULES:
            for key,label,op,threshold,unit in group[3]:
                with self.subTest(group=group[0],key=key):
                    m=obs.metric(threshold,'2026-10-30', 'test',now)
                    self.assertEqual(obs.trigger(m,op,threshold),op in ('<=','>='))
                    m['value']=threshold-.001
                    self.assertEqual(obs.trigger(m,op,threshold),op in ('<','<='))
                    m['value']=threshold+.001
                    self.assertEqual(obs.trigger(m,op,threshold),op in ('>','>='))

    def test_all_unknowns_produce_a_range_not_a_zero_score(self):
        groups=[{'weight':w,'items':[{'triggered':None} for _ in range(n)]} for w,n in [(40,5),(40,8),(20,8)]]
        self.assertEqual(obs.score_bounds(groups),{'lower':0,'upper':100,'available':0,'total':21})

    def test_partial_utc_week_is_not_a_completed_week(self):
        now=datetime(2026,10,30,12,tzinfo=timezone.utc)
        points=[{'date':(datetime(2026,10,20)+timedelta(days=i)).date().isoformat(),'close':100+i} for i in range(6)]
        self.assertEqual(obs.weekly_closes(points,now),[],'Tuesday–Sunday is not a complete seven-day week')

    def test_current_week_is_excluded_and_previous_full_week_is_used(self):
        points=[{'date':(datetime(2026,10,19)+timedelta(days=i)).date().isoformat(),'close':100+i} for i in range(12)]
        self.assertEqual(obs.weekly_closes(points,datetime(2026,10,31,tzinfo=timezone.utc)),[{'date':'2026-10-25','close':106}])

    def test_gapped_daily_data_does_not_become_a_200_day_or_90_day_window(self):
        start=datetime(2026,3,1)
        points=[{'date':(start+timedelta(days=i)).date().isoformat(),'close':100+i} for i in range(202) if i!=150]
        a=obs.build_asset('BTC',points,{}, {},{},datetime(2026,10,30,tzinfo=timezone.utc))
        for key in ('ma200d','high90','mayer','drawdown90'):
            self.assertIsNone(a['metrics'][key]['value'],key+' requires consecutive calendar days')
        self.assertIsNone(a['history'][-1]['ma200'])

    def test_contiguous_daily_average_matches_independent_arithmetic(self):
        start=datetime(2026,1,1)
        points=[{'date':(start+timedelta(days=i)).date().isoformat(),'close':i+1} for i in range(300)]
        a=obs.build_asset('ETH',points,{}, {},{},datetime(2026,10,30,tzinfo=timezone.utc))
        self.assertAlmostEqual(a['metrics']['ma200d']['value'],200.5)

    def test_wilder_rsi_uses_mixed_gains_losses_and_recursive_smoothing(self):
        prices=[1]
        for delta in [2,-1]*7:prices.append(prices[-1]+delta)
        self.assertEqual(obs.rsi(prices),66.67)  # gain 1, loss .5
        self.assertEqual(obs.rsi(prices+[prices[-1]+4]),72.34)  # next gain 17/14, loss 6.5/14

    def test_exact_twenty_percent_drawdown_satisfies_the_inclusive_condition(self):
        now=datetime(2026,10,30,12,tzinfo=timezone.utc)
        for high,last in [(100,80),(100.5,80.4)]:
            with self.subTest(high=high,last=last):
                points=[{'date':(datetime(2026,8,1)+timedelta(days=i)).date().isoformat(),'close':high} for i in range(90)]
                points[-1]['close']=last
                a=obs.build_asset('BTC',points,{}, {},{},now)
                m=a['metrics']['drawdown90']
                self.assertEqual(m['value'],20.0)
                self.assertTrue(obs.trigger(m,'>=',20))

    def test_current_price_cannot_freshen_an_expired_weekly_denominator(self):
        end=datetime(2026,9,27)
        points=[{'date':(end-timedelta(days=1399-i)).date().isoformat(),'close':100000} for i in range(1400)]
        points.append({'date':'2026-10-29','close':60000})
        a=obs.build_asset('BTC',points,{}, {},{},datetime(2026,10,30,12,tzinfo=timezone.utc))
        self.assertEqual(a['metrics']['ma200w']['status'],'stale')
        ratio=a['metrics']['price_ma200w']
        self.assertEqual(ratio['status'],'stale')
        self.assertIsNone(obs.trigger(ratio,'<',1))
        self.assertIn('2026-09-27',ratio['note'],'Explain which underlying observation expired')

    def test_eth_protocol_metrics_are_facts_not_btc_score_inputs(self):
        a=obs.build_asset('ETH',[],{}, {},{},datetime(2026,10,30,tzinfo=timezone.utc))
        self.assertIsNone(a['score'])
        self.assertEqual([g['weight'] for g in a['groups']],[0,0,0])
        for group in a['groups'][1:]:
            self.assertTrue(all(item['op'] is None for item in group['items']))


class SourceFailureTests(unittest.TestCase):
    def collect(self,new_derivatives):
        now=datetime.now(timezone.utc)
        old_time=(now-timedelta(hours=1)).isoformat()
        expired_time=(now-timedelta(hours=30)).isoformat()
        previous={'chainCache':{'fetchedAt':now.isoformat(),'costAttemptAt':now.isoformat(),'snapshot':{},'extras':{}},'assets':{}}
        for symbol in ('BTC','ETH'):
            previous['assets'][symbol]={'metrics':{
                'funding':obs.metric(0,old_time,'Binance Futures',now,max_hours=12),
                'long_short':obs.metric(1.8,expired_time,'Binance Futures',now,max_hours=12),
                'dvol':obs.metric(40,old_time,'Deribit',now,max_hours=12)}}
        target=pathlib.Path('/private/tmp/observatory-tdd-no-write.json')
        points=[{'date':(now-timedelta(days=1)).date().isoformat(),'close':80000}]
        written=[]
        def write(path,text,**kwargs):written.append(json.loads(text));return len(text)
        with patch('sys.argv',['test','--output',str(target)]),\
             patch.object(obs,'load_file',side_effect=lambda p:copy.deepcopy(previous) if p==target else {}),\
             patch.object(obs,'safe_get',return_value=None),\
             patch.object(obs,'fetch_candles',return_value=points),\
             patch.object(obs,'fetch_derivatives',return_value=new_derivatives),\
             patch.object(obs,'fetch_etf',return_value=None),\
             patch.object(pathlib.Path,'mkdir'),\
             patch.object(pathlib.Path,'write_text',new=write),redirect_stdout(io.StringIO()):
            self.assertEqual(obs.main(),0)
        return written[-1],old_time,expired_time

    def test_failed_derivatives_keep_zero_value_and_original_time(self):
        payload,stamp,expired=self.collect({})
        for a in payload['assets'].values():
            self.assertEqual(a['metrics']['funding']['value'],0)
            self.assertEqual(a['metrics']['funding']['asOf'],stamp)
            self.assertEqual(a['metrics']['long_short']['value'],1.8)
            self.assertEqual(a['metrics']['long_short']['asOf'],expired)
            self.assertEqual(a['metrics']['long_short']['status'],'stale')
            self.assertEqual(a['metrics']['dvol']['source'],'Deribit')

    def test_invalid_new_value_does_not_erase_previous_derivative(self):
        payload,stamp,_=self.collect({'funding':{'value':None,'date':datetime.now(timezone.utc).isoformat()}})
        self.assertEqual(payload['assets']['BTC']['metrics']['funding']['value'],0)
        self.assertEqual(payload['assets']['BTC']['metrics']['funding']['asOf'],stamp)

    def test_successful_field_replaces_old_value_while_other_fields_are_retained(self):
        stamp=datetime.now(timezone.utc).isoformat()
        payload,_,expired=self.collect({'funding':{'value':.0123,'date':stamp}})
        self.assertEqual(payload['assets']['BTC']['metrics']['funding']['value'],.0123)
        self.assertEqual(payload['assets']['BTC']['metrics']['funding']['asOf'],stamp)
        self.assertEqual(payload['assets']['BTC']['metrics']['long_short']['asOf'],expired)


if __name__=='__main__':unittest.main()
