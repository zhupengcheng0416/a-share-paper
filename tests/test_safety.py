import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from paper.core import Ledger, evaluate, risk_plan, check_config
from paper.futu_gateway import FutuGateway
from paper.service import scan

CONFIG=json.loads((Path(__file__).parents[1]/'config.json').read_text(encoding='utf-8'))


def sample():
    bars=[]
    for i in range(61):
        c=10+i*0.03
        if i==60:
            c+=0.5
        bars.append({'date':(datetime(2026,1,1)+timedelta(days=i)).date().isoformat(),'open':c,'close':c,'high':c+0.1,'low':c-0.1,'volume':2000000 if i==60 else 1000000,'turnover_cny':30000000})
    return {'code':'SZ.000001','name':'Synthetic fixture','industry':'软件开发','market_cap_cny':6000000000,'is_st':False,'suspended':False,'listing_days':300,'roe':0.10,'fundamental_asof':'2025-12-31','session':bars[-1]['date'],'source':'SYNTHETIC_TEST_ONLY','bars':bars}


class Safety(unittest.TestCase):
    def setUp(self):
        self.stock=sample()
        self.decision=evaluate(self.stock,CONFIG)
        self.now=datetime.now(timezone.utc)
        self.market={'tradable':True,'session_open':True,'quote_time':self.now.isoformat(),'price':12.3,'bid':12.29,'ask':12.31,'lot_size':100,'limit_down':11,'limit_up':13}
        self.account={'equity':1000000,'cash':1000000,'high_water':1000000,'day_start_equity':1000000,'open_positions':0,'daily_orders':0,'pending_buy_value':0,'held_or_pending':False,'connected':True,'reconciled':True,'unknown_orders':False}
    def plan(self):
        return risk_plan(self.decision,self.market,self.account,CONFIG,self.now)
    def test_entry_and_lot_budget(self):
        self.assertEqual(self.decision['signal'],'ENTRY')
        p=self.plan()
        self.assertEqual(p['qty']%100,0)
        self.assertLessEqual(p['qty']*p['price'],50000)
    def test_real_environment_rejected(self):
        cfg=dict(CONFIG,environment='REAL')
        with self.assertRaises(ValueError):
            check_config(cfg)
    def test_missing_fundamentals_blocked(self):
        del self.stock['roe']
        self.assertEqual(evaluate(self.stock,CONFIG)['signal'],'BLOCKED')
    def test_nan_blocked(self):
        self.stock['bars'][-1]['close']=float('nan')
        self.assertEqual(evaluate(self.stock,CONFIG)['signal'],'BLOCKED')
    def test_future_fundamentals_blocked(self):
        self.stock['fundamental_asof']='2099-01-01'
        self.assertEqual(evaluate(self.stock,CONFIG)['signal'],'BLOCKED')
    def test_stale_quote_and_closed_market(self):
        self.market['quote_time']=(self.now-timedelta(minutes=2)).isoformat()
        with self.assertRaises(ValueError):
            self.plan()
        self.market['quote_time']=self.now.isoformat()
        self.market['session_open']=False
        with self.assertRaises(ValueError):
            self.plan()
    def test_circuit_breaker_and_pending_reserve(self):
        self.account['equity']=970000
        with self.assertRaises(ValueError):
            self.plan()
        self.account['equity']=1000000
        self.account['pending_buy_value']=1000000
        with self.assertRaises(ValueError):
            self.plan()
    def test_uncertain_orders_block(self):
        self.account['unknown_orders']=True
        with self.assertRaises(ValueError):
            self.plan()
    def test_duplicate_durable_after_restart(self):
        p=self.plan()
        with tempfile.TemporaryDirectory() as d:
            file=str(Path(d)/'ledger.db')
            ledger=Ledger(file)
            ledger.reserve(p)
            ledger.update(p['key'],'UNKNOWN')
            ledger.db.close()
            ledger=Ledger(file)
            with self.assertRaises(sqlite3.IntegrityError):
                ledger.reserve(p)
            ledger.db.close()
    def test_broker_submit_disabled(self):
        gateway=FutuGateway.__new__(FutuGateway)
        with self.assertRaises(RuntimeError):
            gateway.submit(self.plan())
    def test_scan_snapshot_saved(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'input.json'
            file.write_text(json.dumps({'dataset_kind':'completed_session','source':self.stock['source'],'session':self.stock['session'],'coverage':'synthetic_one_symbol','stocks':[self.stock]}),encoding='utf-8')
            db=str(Path(d)/'ledger.db')
            result=scan(file,db)
            self.assertEqual(result['orders_submitted'],0)
            with closing(sqlite3.connect(db)) as conn:
                snapshot=json.loads(conn.execute('SELECT snapshot FROM decisions').fetchone()[0])
            self.assertEqual(snapshot['input']['source'],'SYNTHETIC_TEST_ONLY')
    def test_empty_scan_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'input.json'
            file.write_text(json.dumps({'dataset_kind':'completed_session','source':'TEST','session':'2026-01-01','stocks':[]}))
            with self.assertRaises(ValueError):
                scan(file,str(Path(d)/'ledger.db'))


if __name__=='__main__':
    unittest.main()
