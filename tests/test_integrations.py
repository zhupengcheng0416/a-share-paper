import copy,json,math,tempfile,unittest
from datetime import date,timedelta
from pathlib import Path
from paper.integrations import ROOT,analyze,setup_upstream,alpha_features,validate_history,factor_score

def fixture(n=320):
    bars=[]
    for i in range(n):
        c=20+0.012*i+math.sin(i*.22)*1.2
        bars.append({'date':str(date(2023,1,1)+timedelta(days=i)),'open':c-.08,'close':c,'high':c+.4,'low':c-.4,
            'volume':1000000+(i%13)*10000,'turnover_cny':35000000,'closed':True})
    return {'code':'SH.600000','name':'SYNTHETIC TEST ONLY','industry':'软件开发','market_cap_cny':4000000000,
        'is_st':False,'suspended':False,'listing_days':1000,'roe':.12,'fundamental_asof':'2022-12-31',
        'session':bars[-1]['date'],'source':'synthetic-test-not-market-data','adjust_mode':'hfq_point_in_time','bars':bars}

class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=json.loads((ROOT/'config.json').read_text(encoding='utf-8'));setup_upstream()
    def test_actual_three_engines(self):
        result=analyze(fixture(),self.config)
        self.assertEqual(result['signal'],'WATCH')
        self.assertEqual(len(result['integration']['commits']),3)
        self.assertEqual(result['integration']['alpha']['feature_count'],65)
        self.assertEqual(result['integration']['price_action']['llm_calls'],0)
        self.assertFalse(result['integration']['support_resistance']['context']['calibrated'])
        json.dumps(result,allow_nan=False)
    def test_alpha_prefix_is_causal(self):
        from model_core.vocab import FORMULA_VOCAB
        stock=fixture();df=validate_history(stock);features=alpha_features(df)
        changed=df.copy();changed.iloc[-1,changed.columns.get_loc('close')]*=2
        changed.iloc[-1,changed.columns.get_loc('volume')]*=5
        other=alpha_features(changed)
        import torch
        self.assertTrue(torch.allclose(features[:,:,:-1],other[:,:,:-1],atol=1e-5))
        with self.assertRaises(Exception):factor_score(features,{'formula_names':['RET'],'vocab_version':'wrong'})
    def test_forming_adjustment_and_future_metadata_blocked(self):
        s=fixture();s['bars'][-1]['closed']=False
        with self.assertRaises(ValueError):analyze(s,self.config)
        s=fixture();s.pop('adjust_mode')
        with self.assertRaises(ValueError):analyze(s,self.config)
        s=fixture();s['fundamental_asof']='2099-01-01'
        self.assertEqual(analyze(s,self.config)['signal'],'BLOCKED')
    def test_factor_freeze_gate(self):
        s=fixture();artifact={'training_end':s['session']}
        with self.assertRaises(ValueError):analyze(s,self.config,artifact)

    def test_bounded_mining_has_separate_holdout(self):
        from paper.mining import mine
        artifact=mine(fixture(800),limit=8)
        self.assertFalse(artifact['test_used_for_selection'])
        self.assertFalse(artifact['execution_eligible'])
        self.assertLess(artifact['selection_train_end'],artifact['validation_end'])
        self.assertLess(artifact['validation_end'],artifact['test_start'])
        self.assertEqual(artifact['candidate_count'],8)

if __name__=='__main__':unittest.main()
