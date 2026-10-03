import base64,copy,io,json,tempfile,unittest,urllib.error
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch,MagicMock
from paper.feedback import archive,build_feedback,evaluate,periods,summarize,render_feedback

class FeedbackTests(unittest.TestCase):
    def setup_case(self):
        start=date(2026,6,1)
        seed=[dict(date=str(start+timedelta(days=i)),open=10.02,high=10.1,low=10,close=10.02,volume=1000) for i in range(61)]
        row={'code':'SH.600000','name':'测试','seed':seed,'plan':{'status':'CONDITIONAL','support_low':9.8,'support_high':10,
            'buy_low':10.01,'buy_high':10.1,'stop':9.7,'take_profit_1':10.5,'take_profit_2':10.9}}
        def bar(day,**kw):return dict(date=day,open=10.05,high=10.2,low=9.9,close=10.05,volume=1000,**kw)
        future=[bar('2026-08-03'),bar('2026-08-04'),bar('2026-08-05')]
        return row,seed+future
    def evaluate(self,row,bars,end='2026-08-31'):
        return evaluate(row,'2026-08-01T16:35:00+08:00',bars,end)
    def test_calendar_periods_year_and_quarter_boundary(self):
        p=periods(date(2027,1,1))
        self.assertEqual(p[0][1:],('2026-12',date(2026,12,1),date(2026,12,31)))
        self.assertEqual(p[1][1:],('2026-Q4',date(2026,10,1),date(2026,12,31)))
    def test_entry_after_confirmation_not_same_close(self):
        row,bars=self.setup_case();r=self.evaluate(row,bars[:62])
        self.assertEqual(r['status'],'CONFIRMED_PENDING_ENTRY')
        r=self.evaluate(row,bars[:63]);self.assertEqual(r['status'],'OPEN');self.assertEqual(r['entry_date'],'2026-08-04')
    def test_no_lookahead_and_no_backdated_publication(self):
        row,bars=self.setup_case();self.assertEqual(self.evaluate(row,bars,'2026-08-03')['status'],'CONFIRMED_PENDING_ENTRY')
        r=evaluate(row,'2026-09-01T16:35:00+08:00',bars,'2026-08-31')
        self.assertEqual(r['status'],'PENDING')
    def test_same_bar_stop_and_profit_uses_stop_first(self):
        row,bars=self.setup_case();bars[-1].update(low=9.6,high=11)
        r=self.evaluate(row,bars);self.assertEqual(r['exit_reason'],'STOP_FIRST_AMBIGUOUS');self.assertLess(r['net_return'],0)
    def test_t1_defers_entry_day_stop_to_next_open(self):
        row,bars=self.setup_case();bars[-2].update(low=9.6);bars[-1].update(open=9,low=8.8,high=10.4,close=9.2)
        r=self.evaluate(row,bars);self.assertEqual(r['exit_reason'],'T1_DEFERRED_STOP_NEXT_OPEN');self.assertAlmostEqual(r['exit_price'],8.991)
    def test_adverse_gap_stop_fills_below_stop(self):
        row,bars=self.setup_case();bars[-1].update(open=9,low=8.8,high=9.3,close=9.2)
        r=self.evaluate(row,bars);self.assertLess(r['exit_price'],row['plan']['stop'])
    def test_adjustment_revision_excluded(self):
        row,bars=self.setup_case();bars=copy.deepcopy(bars);bars[0]['close']+=.01
        self.assertEqual(self.evaluate(row,bars)['status'],'DATA_UNAVAILABLE')
    def test_limit_like_single_price_is_not_fake_fill(self):
        row,bars=self.setup_case();bars[-2].update(open=10.05,high=10.05,low=10.05,close=10.05)
        self.assertEqual(self.evaluate(row,bars)['status'],'EXECUTION_UNCERTAIN')
    def test_future_open_outside_band_cancels(self):
        row,bars=self.setup_case();bars[-2].update(open=10.15)
        self.assertEqual(self.evaluate(row,bars)['status'],'ENTRY_CANCELLED')
    def test_cost_sensitivity_and_closed_only_denominator(self):
        row,bars=self.setup_case();bars[-1].update(high=11)
        r=self.evaluate(row,bars);self.assertEqual(r['status'],'CLOSED')
        self.assertGreater(r['sensitivity']['0.0005'],r['sensitivity']['0.002'])
        s=summarize([r,{'status':'OPEN','entry_date':'2026-08-04'},{'status':'DATA_UNAVAILABLE'},{'status':'OBSERVE'}])
        self.assertEqual(s['closed_cases'],1);self.assertEqual(s['win_rate'],1);self.assertIsNone(s['portfolio_return'])
    def test_empty_period_does_not_request_market_or_invent_returns(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=build_feedback(None,'monthly_backtest','2026-09',date(2026,9,1),date(2026,9,30),Path(tmp))
        self.assertIsNone(r['summary']['win_rate']);self.assertIn('样本不足',render_feedback(r))
    def test_duplicate_daily_mail_does_not_archive_new_price_revision(self):
        with patch('urllib.request.urlopen') as request:
            self.assertEqual(archive({}, {'mail_status':'deduplicated_SENT'})['archive_status'],'not_newly_sent')
        request.assert_not_called()
    def test_archive_is_prepared_before_delivery_then_activated_without_changing_plans(self):
        row,_=self.setup_case();written=[]
        report={'session':'2026-07-31','source':'Futu REST','adjustment':'qfq','coverage':{},
            'input_stocks':[{'code':row['code'],'bars':row['seed']}],
            'results':[{'code':row['code'],'name':row['name'],'last_price':10.02,
                'integration':{'support_resistance':{'context':{'atr':.05},'zones':[
                    {'zone_type':'support','low':9.8,'high':10},{'zone_type':'resistance','low':12,'high':12.5}]}}}]}
        def request(req,**kwargs):
            if req.get_method()=='GET':
                if not written:raise urllib.error.HTTPError(req.full_url,404,'missing',{},None)
                data={'sha':'existing-sha','content':base64.b64encode(json.dumps(written[-1]).encode()).decode()}
            else:
                self.assertEqual(req.get_method(),'PUT');data=json.loads(req.data)
                written.append(json.loads(base64.b64decode(data['content'])))
                data={'content':{'sha':'new-sha'}}
            response=MagicMock();response.__enter__.return_value=io.StringIO(json.dumps(data));return response
        with tempfile.TemporaryDirectory() as tmp,patch('paper.feedback.ROOT',Path(tmp)/'.research'),patch.dict('os.environ',{'GITHUB_REPOSITORY':'zhupengcheng0416/a-share-paper','GITHUB_TOKEN':'test'}),patch('urllib.request.urlopen',side_effect=request):
            archive(report,{},prepare=True)
            self.assertEqual(written[0]['state'],'PREPARED')
            archive(report,{'mail_status':'smtp_accepted','message_id':'test-id'})
            self.assertEqual(written[1]['state'],'SENT');self.assertEqual(written[0]['plans'],written[1]['plans'])

if __name__=='__main__':unittest.main()
