import copy,unittest
from paper.ross import audit

class RossTests(unittest.TestCase):
    def fixture(self):
        asof='2026-10-02T09:15:00-04:00'
        facts=['price_usd','relative_volume','gain_today','float_shares','news_catalyst','minute_feed','level2','tape','chart_review']
        row=dict(as_of=asof,price_usd=5,relative_volume=5,gain_today=.1,float_shares=9999999,
                 relative_volume_basis='cumulative_today_over_prior_30_complete_daily_volumes',
                 float_basis='public_float_not_total_shares',positive_news_catalyst=True,timeframes_minutes=[1,5],
                 minute_feed_complete=True,realtime_feed_verified=True,retracement_fraction=.4,
                 last_pullback_candle_high=4.98,pullback_low=4.9,reviewed_entry_reference=5,
                 evidence={key:dict(source='synthetic_test_only',available_at=asof,verified=True) for key in facts})
        for key in ('front_side_momentum','first_pullback','flagpole_high_volume','pullback_lower_volume',
                    'vwap_holds','ema9_holds','level2_no_heavy_seller','tape_buying_supports_breakout','daily_resistance_allows_2r'):
            row[key]=True
        return row
    def test_qualified_reference_geometry_and_partial_profit(self):
        r=audit(self.fixture());self.assertEqual(r['status'],'CONDITIONAL_REFERENCE')
        self.assertAlmostEqual(r['first_take_profit'],5.2);self.assertEqual(r['first_take_profit_fraction'],.5)
        self.assertIsNone(r['second_fixed_profit_target']);self.assertFalse(r['trading_enabled'])
    def test_missing_critical_evidence_produces_no_price_plan(self):
        row=self.fixture();row['evidence'].pop('level2');r=audit(row)
        self.assertEqual(r['status'],'BLOCKED');self.assertNotIn('buy_trigger_above',r)
    def test_float_boundary_and_proxy_not_accepted(self):
        row=self.fixture();row['float_shares']=10000000;self.assertEqual(audit(row)['status'],'BLOCKED')
        row=self.fixture();row['float_basis']='issued_shares';self.assertEqual(audit(row)['status'],'BLOCKED')
    def test_future_news_and_unverified_story_not_accepted(self):
        row=self.fixture();row['evidence']['news_catalyst']['available_at']='2026-10-02T09:16:00-04:00'
        self.assertEqual(audit(row)['status'],'BLOCKED')
        row=self.fixture();row['positive_news_catalyst']=False;self.assertEqual(audit(row)['status'],'BLOCKED')
    def test_old_volume_ratio_not_ross_rvol(self):
        row=self.fixture();row['relative_volume_basis']='broker_volume_ratio';self.assertEqual(audit(row)['status'],'BLOCKED')
    def test_daily_chart_cannot_replace_intraday(self):
        row=self.fixture();row['timeframes_minutes']=[1440];self.assertEqual(audit(row)['status'],'BLOCKED')
    def test_discretionary_checks_cannot_be_silently_skipped(self):
        row=self.fixture();row.pop('level2_no_heavy_seller');self.assertEqual(audit(row)['status'],'BLOCKED')
        row=self.fixture();row['retracement_fraction']=.51;self.assertEqual(audit(row)['status'],'BLOCKED')
    def test_nan_bool_and_naive_time_rejected(self):
        for key,value in [('float_shares',float('nan')),('relative_volume',True),('as_of','2026-10-02T09:15:00')]:
            row=self.fixture();row[key]=value;self.assertEqual(audit(row)['status'],'BLOCKED')

if __name__=='__main__':unittest.main()
