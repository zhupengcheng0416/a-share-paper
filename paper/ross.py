"""Source-pinned Ross checklist; missing/discretionary evidence fails closed."""
import json,math
from datetime import datetime
from pathlib import Path

CONFIG=Path(__file__).resolve().parents[1]/'ross-config.json'

def audit(observation):
    """Reference prices only after evidence checks, never an order instruction."""
    config=json.loads(CONFIG.read_text(encoding='utf-8'));fail=[];missing=[]
    def number(key):
        value=observation.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            missing.append(key);return None
        return value
    try:
        asof=datetime.fromisoformat(observation['as_of'])
        if asof.tzinfo is None:raise ValueError('as_of has no timezone')
    except (KeyError,TypeError,ValueError):
        return {'status':'BLOCKED','missing':['valid_as_of_with_timezone'],'failed':[], 'trading_enabled':False}
    price=number('price_usd');rvol=number('relative_volume');gain=number('gain_today');float_shares=number('float_shares')
    if price is not None and not config['price_usd']['min']<=price<=config['price_usd']['max']:fail.append('price_outside_1_to_20_usd')
    if rvol is not None and rvol<config['relative_volume_min']:fail.append('relative_volume_below_5')
    if gain is not None and gain<config['gain_today_min']:fail.append('gain_below_10_percent')
    if float_shares is not None and not 0<float_shares<config['float_shares_exclusive_max']:fail.append('float_not_below_10m')
    # Every supplied fact must be sourced, available by the decision time, and semantically verified.
    for key in ('price_usd','relative_volume','gain_today','float_shares','news_catalyst','minute_feed','level2','tape','chart_review'):
        evidence=observation.get('evidence',{}).get(key,{})
        try:
            available=datetime.fromisoformat(evidence['available_at'])
            if available.tzinfo is None or available>asof:raise ValueError('future or naive evidence')
            if not evidence.get('source') or evidence.get('verified') is not True:raise ValueError('unverified source')
        except (KeyError,TypeError,ValueError):missing.append('verified_point_in_time_'+key)
    if observation.get('relative_volume_basis')!=config['relative_volume_basis']:missing.append('matching_rvol_definition')
    if observation.get('float_basis')!='public_float_not_total_shares':missing.append('true_float_definition')
    if observation.get('positive_news_catalyst') is not True:missing.append('positive_catalyst_review')
    if observation.get('timeframes_minutes')!=config['require_intraday_timeframes_minutes']:missing.append('both_1m_and_5m')
    if observation.get('minute_feed_complete') is not True or observation.get('realtime_feed_verified') is not True:
        missing.append('complete_realtime_minute_feed')
    # Human/qualified source review remains explicit; no made-up Level2 or flagpole thresholds.
    for key in ('front_side_momentum','first_pullback','flagpole_high_volume','pullback_lower_volume',
                'vwap_holds','ema9_holds','level2_no_heavy_seller','tape_buying_supports_breakout','daily_resistance_allows_2r'):
        if observation.get(key) is not True:missing.append(key)
    retracement=number('retracement_fraction')
    if retracement is not None and not 0<=retracement<=config['bull_flag_max_retracement']:fail.append('pullback_retracement_above_half_or_invalid')
    trigger=number('last_pullback_candle_high');stop=number('pullback_low');entry=number('reviewed_entry_reference')
    if None not in (trigger,stop,entry) and not 0<stop<trigger<=entry:
        fail.append('invalid_entry_stop_structure')
    if fail or missing:return {'status':'BLOCKED','missing':sorted(set(missing)),'failed':fail,'trading_enabled':False}
    risk=entry-stop
    return {'status':'CONDITIONAL_REFERENCE','strategy_version':config['version'],'as_of':observation['as_of'],
            'buy_trigger_above':trigger,'reviewed_entry_reference':entry,'stop_reference':stop,
            'first_take_profit':entry+config['first_profit_r_multiple']*risk,'first_take_profit_fraction':config['first_profit_fraction'],
            'remaining_stop_after_first_profit':entry,'second_fixed_profit_target':None,
            'exit_review':'breakout failure, heavy sellers, weakening tape; no fixed substitute rule',
            'trading_enabled':False,'execution_assumed':False,'discretionary_review_replicated':False}
