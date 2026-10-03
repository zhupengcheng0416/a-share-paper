import copy,unittest
from paper.market import normalized_bars,universe
from paper.report import technical_judgment,render
from test_integrations import fixture

class FakeClient:
    def __init__(self,pages):self.pages=iter(pages)
    def get(self,*args,**kwargs):return next(self.pages)

class MarketTests(unittest.TestCase):
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

if __name__=='__main__':unittest.main()
