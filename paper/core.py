import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_config(config):
    if config['environment'] != 'SIMULATE':
        raise ValueError('REAL trading is prohibited')
    for field in ('max_position_fraction','risk_per_trade','daily_loss_limit','drawdown_limit','max_atr_fraction','max_spread_fraction'):
        if not finite(config[field]) or not 0 < config[field] < 1:
            raise ValueError(f'invalid {field}')
    if config['auto_submit'] and not config['parameters_approved']:
        raise ValueError('strategy parameters are not approved')


def evaluate(stock, config):
    """Input contains complete completed-session, consistently adjusted OHLCV bars.
    Missing/invalid fundamentals and membership block entries, never count as passes.
    """
    check_config(config)
    required = ('code','name','industry','market_cap_cny','is_st','suspended','listing_days','roe','fundamental_asof','session','source','bars')
    if any(k not in stock for k in required):
        return {'signal':'BLOCKED','reason':'missing_data'}
    if not re.fullmatch(r'(SH|SZ)\.\d{6}',stock['code']):
        return {'signal':'BLOCKED','reason':'unsupported_code'}
    bars = stock['bars']
    if len(bars) < 61:
        return {'signal':'BLOCKED','reason':'insufficient_history'}
    dates = [b.get('date','') for b in bars]
    if dates != sorted(set(dates)) or dates[-1] != stock['session'] or stock['fundamental_asof'] > stock['session'] or not stock['source']:
        return {'signal':'BLOCKED','reason':'invalid_dates_or_provenance'}
    for b in bars:
        if any(not finite(b.get(k)) for k in ('open','high','low','close','volume','turnover_cny')):
            return {'signal':'BLOCKED','reason':'invalid_bar'}
        if not 0 < b['low'] <= min(b['open'],b['close']) <= max(b['open'],b['close']) <= b['high'] or b['volume'] <= 0 or b['turnover_cny'] <= 0:
            return {'signal':'BLOCKED','reason':'invalid_bar'}
    if any(not finite(stock[k]) for k in ('market_cap_cny','listing_days','roe')) or stock['market_cap_cny'] <= 0 or stock['is_st'] is not False or stock['suspended'] is not False:
        return {'signal':'BLOCKED','reason':'invalid_metadata_or_restricted'}
    pools = []
    if stock['industry'] in config['tech_industries']:
        pools.append('technology')
    if stock['market_cap_cny'] <= config['market_cap_max_cny']:
        pools.append('microcap_le_7bn')
    if not pools or stock['listing_days'] < config['min_listing_days']:
        return {'signal':'EXCLUDED','reason':'outside_universe_or_new_listing'}
    close = [b['close'] for b in bars]
    tr = [max(bars[i]['high']-bars[i]['low'],abs(bars[i]['high']-close[i-1]),abs(bars[i]['low']-close[i-1])) for i in range(1,len(bars))]
    atr = sum(tr[:14])/14
    for v in tr[14:]:
        atr = (13*atr+v)/14
    factors = {'ma20':sum(close[-20:])/20,'ma60':sum(close[-60:])/60,'momentum60':close[-1]/close[-61]-1,'high20_prior':max(b['high'] for b in bars[-21:-1]),'volume_ratio':bars[-1]['volume']/(sum(b['volume'] for b in bars[-21:-1])/20),'avg_turnover_cny':sum(b['turnover_cny'] for b in bars[-20:])/20,'atr14':atr,'atr_fraction':atr/close[-1],'roe':stock['roe']}
    checks = {'liquidity':factors['avg_turnover_cny']>=config['min_avg_turnover_cny'],'trend':close[-1]>factors['ma20']>factors['ma60'],'momentum':factors['momentum60']>0,'breakout':close[-1]>factors['high20_prior'],'volume':factors['volume_ratio']>=config['volume_ratio_entry'],'quality':stock['roe']>=config['min_roe'],'volatility':factors['atr_fraction']<=config['max_atr_fraction']}
    return {'signal':'ENTRY' if all(checks.values()) else 'WATCH','pools':pools,'factors':factors,'checks':checks,'rule_pass_count':sum(checks.values()),'rule_count':len(checks),'version':config['version'],'session':stock['session'],'code':stock['code'],'source':stock['source'],'fundamental_asof':stock['fundamental_asof']}


def risk_plan(decision, market, account, config, now=None):
    check_config(config)
    now = now or datetime.now(timezone.utc)
    if decision['signal'] != 'ENTRY':
        raise ValueError('not an entry signal')
    if market.get('tradable') is not True or market.get('session_open') is not True:
        raise ValueError('market closed or code not tradable')
    stamp = datetime.fromisoformat(market['quote_time'])
    if stamp.tzinfo is None or not 0 <= (now-stamp).total_seconds() <= config['quote_max_age_seconds']:
        raise ValueError('stale quote')
    numeric = ('equity','cash','high_water','day_start_equity','open_positions','daily_orders','pending_buy_value')
    if any(not finite(account.get(k)) or account[k] < 0 for k in numeric) or min(account['equity'],account['high_water'],account['day_start_equity']) <= 0:
        raise ValueError('invalid account state')
    if account.get('connected') is not True or account.get('reconciled') is not True or account.get('unknown_orders') is not False:
        raise ValueError('account disconnected or unreconciled')
    if account['equity']/account['high_water']-1 <= -config['drawdown_limit'] or account['equity']/account['day_start_equity']-1 <= -config['daily_loss_limit']:
        raise ValueError('circuit breaker')
    if account['open_positions'] >= config['max_positions'] or account['daily_orders'] >= config['max_orders_per_day'] or account.get('held_or_pending') is not False:
        raise ValueError('position/order limit')
    price, bid, ask = market['price'],market['bid'],market['ask']
    lot=market['lot_size']
    if any(not finite(x) or x <= 0 for x in (price,bid,ask,lot)) or ask < bid or int(lot)!=lot:
        raise ValueError('invalid quote or lot')
    if not bid <= price <= ask or (ask-bid)/price>config['max_spread_fraction']:
        raise ValueError('spread or price invalid')
    if not market['limit_down'] < price < market['limit_up']:
        raise ValueError('price limit')
    stop_distance = config['atr_stop_multiple']*decision['factors']['atr14']
    if not finite(stop_distance) or not 0 < stop_distance < price:
        raise ValueError('invalid ATR stop')
    budget = min(account['equity']*config['max_position_fraction'],account['cash']-account['pending_buy_value'])
    qty = int(min(budget/price,account['equity']*config['risk_per_trade']/stop_distance)//lot)*int(lot)
    if qty <= 0:
        raise ValueError('insufficient risk budget')
    key=hashlib.sha256(f"{decision['version']}|{decision['session']}|{decision['code']}|BUY".encode()).hexdigest()[:32]
    return {'key':key,'code':decision['code'],'side':'BUY','qty':qty,'price':price,'stop':round(price-stop_distance,4),'environment':'SIMULATE','decision':decision,'market':market,'account':account}


class Ledger:
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=20)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, created TEXT, snapshot TEXT); CREATE TABLE IF NOT EXISTS orders(key TEXT PRIMARY KEY, created TEXT, state TEXT, order_id TEXT, snapshot TEXT); CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, created TEXT, kind TEXT, payload TEXT);')
    def decision(self,data):
        with self.db:
            self.db.execute('INSERT INTO decisions(created,snapshot) VALUES(?,?)',(datetime.now(timezone.utc).isoformat(),json.dumps(data,ensure_ascii=False,allow_nan=False)))
    def reserve(self,plan):
        # Durable before network call. Duplicate and uncertain requests never auto-retry.
        with self.db:
            self.db.execute('INSERT INTO orders VALUES(?,?,?,?,?)',(plan['key'],datetime.now(timezone.utc).isoformat(),'PENDING',None,json.dumps(plan,ensure_ascii=False,allow_nan=False)))
    def update(self,key,state,order_id=None):
        with self.db:
            self.db.execute('UPDATE orders SET state=?,order_id=? WHERE key=?',(state,order_id,key))
    def event(self,kind,data):
        with self.db:
            self.db.execute('INSERT INTO events(created,kind,payload) VALUES(?,?,?)',(datetime.now(timezone.utc).isoformat(),kind,json.dumps(data,ensure_ascii=False,allow_nan=False)))
