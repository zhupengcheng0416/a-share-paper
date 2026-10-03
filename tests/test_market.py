import copy,unittest
from paper.market import normalized_bars,universe
from paper.report import technical_judgment,render,prioritize,reference_levels,reference_intervals,levels_html
from test_integrations import fixture

class FakeClient:
    def __init__(self,pages):self.pages=iter(pages)
    def get(self,*args,**kwargs):return next(self.pages)

class MarketTests(unittest.TestCase):
    def test_extended_target_capped_by_resistance_without_widening_stop(self):
        stock,result=self.plan_fixture()
        before=reference_intervals(result)
        self.assertEqual(before['extended_profit_range'],[11.13,12.04])
        result['integration']['support_resistance']['zones'][1]['low']=11.5
        after=reference_intervals(result)
        self.assertEqual(after['extended_profit_range'],[11.13,11.5])
        self.assertEqual(after['stop_range'],before['stop_range'])
        self.assertFalse(after['execution_rule_changed'])
        self.assertFalse(after['breakout_confirmed'])
        self.assertGreater(after['breakout_profit_range'][0],after['breakout_resistance'])
        self.assertEqual(after['breakout_profit_range'][1],12.7)
        result['integration']['support_resistance']['zones'][1]['low']=10.5
        self.assertIsNone(reference_intervals(result)['extended_profit_range'])
    def test_priority_mail_caps_ten_and_never_fills_with_invalid_setups(self):
        stocks=[];results=[]
        for i in range(12):
            s,r=self.plan_fixture();code=f'SH.{600000+i}'
            s.update(code=code);r.update(code=code,name=f'股票{i}')
            stocks.append(s);results.append(r)
        report={'session':'2026-09-30','input_stocks':stocks,'results':results}
        selected=prioritize(report)
        self.assertEqual(len(selected['results']),10)
        self.assertEqual(selected['selection']['eligible_count'],12)
        self.assertEqual(len(selected['input_stocks']),10)
        for r in results[1:]:r['integration']['support_resistance']['zones']=[]
        selected=prioritize(report)
        self.assertEqual(len(selected['results']),1)
        body=render(selected)
        self.assertIn('止盈一区间',body);self.assertIn('止损区间',body)
        self.assertNotIn('股票11',body);self.assertNotIn('AlphaMaster',body)
    def test_structural_intervals_do_not_promote_weak_stock_to_signal(self):
        stock,result=self.plan_fixture()
        stock['bars']=[{'close':14-i/30} for i in range(61)]
        p=reference_levels(stock,result);bands=reference_intervals(result)
        self.assertEqual(p['status'],'OBSERVE')
        self.assertEqual(bands['stop_range'],[9.4,9.45])
        self.assertEqual(bands['take_profit_1_range'],[10.57,10.72])
        self.assertEqual(bands['take_profit_2_range'],[11.13,11.38])
        self.assertIn('尚无有效买点',levels_html(p,bands))
        result['integration']['support_resistance']['context']['atr']=float('nan')
        self.assertEqual(reference_intervals(result)['status'],'UNAVAILABLE')
    def plan_fixture(self):
        stock={'bars':[{'close':12} for _ in range(61)]}
        result={'last_price':12,'integration':{'support_resistance':{'context':{'atr':.2},'zones':[
            {'zone_type':'support','low':9.5,'high':10},
            {'zone_type':'resistance','low':12.5,'high':13}]}}}
        return stock,result
    def test_conditional_levels_have_valid_geometry_and_two_r_room(self):
        stock,result=self.plan_fixture();p=reference_levels(stock,result)
        self.assertEqual(p['status'],'CONDITIONAL')
        self.assertLess(p['stop'],p['buy_low']);self.assertLessEqual(p['buy_low'],p['buy_high'])
        self.assertLess(p['buy_high'],p['take_profit_1']);self.assertLess(p['take_profit_1'],p['take_profit_2'])
        self.assertLessEqual(p['take_profit_2'],p['resistance_ceiling'])
        self.assertGreaterEqual((p['take_profit_2']-p['buy_high'])/(p['buy_high']-p['stop']),2-1e-9)
        self.assertIn('止盈二',levels_html(p))
    def test_no_buy_when_downtrend(self):
        stock,result=self.plan_fixture();stock['bars']=[{'close':14-i/30} for i in range(61)]
        self.assertEqual(reference_levels(stock,result)['status'],'OBSERVE')
    def test_no_buy_when_resistance_is_too_close_or_overlaps(self):
        stock,result=self.plan_fixture();zone=result['integration']['support_resistance']['zones'][1]
        for low,high in [(10.5,11),(9.9,10.2)]:
            zone.update(low=low,high=high)
            self.assertEqual(reference_levels(stock,result)['status'],'OBSERVE')
    def test_no_invented_levels_when_support_or_atr_missing(self):
        stock,result=self.plan_fixture();sr=result['integration']['support_resistance']
        sr['context']['atr']=float('nan')
        self.assertEqual(reference_levels(stock,result)['status'],'OBSERVE')
        sr['context']['atr']=.2;sr['zones']=[]
        self.assertEqual(reference_levels(stock,result)['status'],'OBSERVE')
    def test_price_rounding_is_conservative(self):
        stock,result=self.plan_fixture();sr=result['integration']['support_resistance']
        sr['context']['atr']=.123;sr['zones'][0].update(low=9.503,high=10.001)
        p=reference_levels(stock,result)
        self.assertEqual(p['buy_low'],10.02);self.assertEqual(p['buy_high'],10.06);self.assertEqual(p['stop'],9.44)
    def test_delivery_ledger_uses_get_and_put(self):
        from paper.report import DeliveryLedger
        from unittest.mock import patch,MagicMock
        import io
        def response(request,**kwargs):
            methods.append(request.get_method())
            context=MagicMock();context.__enter__.return_value=io.StringIO('{}')
            return context
        methods=[]
        with patch.dict('os.environ',{'GITHUB_REPOSITORY':'zhupengcheng0416/a-share-paper','GITHUB_TOKEN':'test'}),patch('urllib.request.urlopen',side_effect=response):
            ledger=DeliveryLedger('test');ledger.request();ledger.request({'content':'test'})
        self.assertEqual(methods,['GET','PUT'])
    def test_volume_precision_and_no_future(self):
        row={'date':20260930,'open':10,'high':11,'low':9,'close':10,'volume':12300,'turnover':1230}
        response={'data':{'kline_list':[row],'volume_precision':2}}
        self.assertEqual(normalized_bars(response,'2026-09-30')[0]['volume'],123)
        with self.assertRaises(ValueError):normalized_bars(response,'2026-09-29')
        with self.assertRaises(ValueError):normalized_bars(response,'2026-10-01')
        response['data']['kline_list'].append(copy.deepcopy(row))
        with self.assertRaises(ValueError):normalized_bars(response,'2026-09-30')
    def test_universe_coverage_and_duplicate_detection(self):
        a={'data':{'items':[{'code':'SH.600000'}]},'pagination':{'total':2,'has_more':True,'next_key':'1'}}
        b={'data':{'items':[{'code':'SZ.000001'}]},'pagination':{'total':2,'has_more':False,'next_key':'-1'}}
        self.assertEqual(len(universe(FakeClient([a,b]))),2)
        b['data']['items'][0]['code']='SH.600000'
        with self.assertRaises(ValueError):universe(FakeClient([a,b]))
    def test_latest_adjustment_research_with_missing_fundamentals(self):
        from paper.integrations import analyze
        from paper.service import load_config
        s=fixture();s.pop('roe');s.pop('fundamental_asof');s['adjust_mode']='qfq_latest_snapshot'
        result=analyze(s,load_config())
        self.assertEqual(result['signal'],'BLOCKED')
        self.assertIn('integration',result)
        self.assertIn('trend',technical_judgment(s))
    def test_no_fixed_recipient_override(self):
        from paper.report import send
        from unittest.mock import patch
        with patch.dict('os.environ',{'MAIL_SMTP_USER':'other@example.com'}):
            with self.assertRaises(ValueError):send({},'irrelevant')
    def test_explicit_selection_test_is_separate_and_retry_deduplicated(self):
        from paper.report import send
        from unittest.mock import patch,MagicMock
        report={'session':'2026-09-30'}
        with self.assertRaises(ValueError):send(report,'test','selection_test')
        with patch.dict('os.environ',{'MAIL_SMTP_USER':'zhupengcheng0416@163.com','MAIL_SMTP_PASSWORD':'test'}),patch('paper.report.DeliveryLedger') as ledger,patch('paper.report.smtplib.SMTP_SSL') as smtp:
            ledger.return_value.current.return_value=None
            smtp.return_value.__enter__.return_value.send_message.return_value={}
            result=send(report,'<p>test</p>','selection_test','123')
            self.assertEqual(result['mail_status'],'smtp_accepted')
            msg=smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertIn('【测试】',msg['Subject'])
            self.assertEqual(msg['To'],'zhupengcheng0416@163.com')
            ledger.return_value.current.return_value={'state':'SENT'}
            self.assertEqual(send(report,'test','selection_test','123')['mail_status'],'deduplicated_SENT')
            self.assertEqual(smtp.call_count,1)

if __name__=='__main__':unittest.main()
