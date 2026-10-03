"""Read-only real-market ingestion through the Cloudflare quote relay."""
import argparse,json,os,time,urllib.request,urllib.error
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .integrations import analyze,clean
from .service import load_config

BASE='https://a-share-paper-control.zhupengcheng0416.workers.dev'
class MarketClient:
    def __init__(self,token=None):self.token=token;self.oidc=None;self.until=0;self.calls=0
    def auth(self):
        if self.token:return self.token
        if not self.oidc or time.time()>self.until:
            url=os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']+'&audience=a-share-market-data'
            req=urllib.request.Request(url,headers={'Authorization':'Bearer '+os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
            with urllib.request.urlopen(req,timeout=20) as r:self.oidc=json.load(r)['value']
            self.until=time.time()+180
        return self.oidc
    def get(self,operation,**fields):
        for attempt in range(3):
            self.calls+=1
            req=urllib.request.Request(BASE+'/api/market-data',data=json.dumps({'operation':operation,**fields}).encode(),
                headers={'Authorization':'Bearer '+self.auth(),'Content-Type':'application/json','User-Agent':'Mozilla/5.0'})
            try:
                with urllib.request.urlopen(req,timeout=25) as r:return json.load(r)
            except urllib.error.HTTPError as e:
                detail=''
                try:detail=json.loads(e.read()).get('detail','')
                except Exception:pass
                if e.code not in (429,502,503) or attempt==2:raise RuntimeError('quote_relay_http_'+str(e.code)+':'+detail) from None
                time.sleep(2**attempt)
        raise RuntimeError('quote_relay_failed')

def universe(client):
    items=[];cursor='';seen=set();total=None
    for page in range(40):
        response=client.get('universe',**({'cursor':cursor} if cursor else {}))
        data=response['data']['items'];pagination=response['pagination']
        total=pagination['total'] if total is None else total
        if total!=pagination['total']:raise ValueError('universe changed during pagination')
        for item in data:
            code=item['code']
            if code in seen:raise ValueError('duplicate universe symbol')
            if not code.startswith(('SH.','SZ.','BJ.')):raise ValueError('unexpected universe market')
            items.append(item);seen.add(code)
        if not pagination['has_more']:
            if len(items)!=total:raise ValueError('incomplete universe pagination')
            return items
        next_cursor=pagination['next_key']
        if not data or next_cursor==cursor:raise ValueError('pagination stalled')
        cursor=next_cursor
    raise ValueError('universe exceeds free request budget')

def normalized_bars(response,session):
    precision=response['data'].get('volume_precision',0)
    if not isinstance(precision,int) or not 0<=precision<=8:raise ValueError('invalid volume precision')
    output=[]
    for b in response['data']['kline_list']:
        stamp=datetime.strptime(str(b['date']),'%Y%m%d').date().isoformat()
        if stamp>session:raise ValueError('future/forming history returned')
        output.append({'date':stamp,**{k:b[k] for k in ('open','high','low','close')},'volume':b['volume']/10**precision,
            'turnover_cny':b['turnover'],'closed':True})
    output.sort(key=lambda b:b['date'])
    if not output or len(set(b['date'] for b in output))!=len(output) or output[-1]['date']!=session:raise ValueError('history incomplete/duplicate/stale')
    return output

def screen_values(item):
    values={}
    for wrapper in item.get('results') or []:
        row=wrapper.get('simple_property_result',{})
        name=row.get('property',{}).get('name');raw=row.get('res',{}).get('ival')
        if name in (2201,2301) and raw is not None:values[name]=int(raw)/1000
    return values

def build_report(client,details=20):
    if not 1<=details<=60:raise ValueError('free detail budget is 1..60 symbols')
    now=datetime.now(ZoneInfo('Asia/Shanghai'));today=now.date()
    calendar=client.get('calendar',start=str(today-timedelta(days=30)),end=str(today))
    # Calendar format is provider-specific; completed session anchored below by
    # data_date and separately verified against actual trading-day records.
    items=universe(client);unsupported=[i['code'] for i in items if i['code'].startswith('BJ.')]
    completed=[d['time'] for d in calendar['data']['trading_days'] if d['time']<str(today) or now.hour>=16]
    if not completed:raise ValueError('no completed trading session')
    session=max(completed);snapshots=[];missing=[];excluded=Counter()
    import re
    for item in items:
        code=item['code']
        if code.startswith('BJ.'):continue
        if not re.fullmatch(r'(SH\.6\d{5}|SZ\.(?:00|30)\d{4})',code):excluded['non_a_share']+=1;continue
        values=screen_values(item)
        if 2201 not in values or 2301 not in values:missing.append(code);continue
        snapshots.append({'code':code,'sc_name':item.get('sc_name') or item.get('name'),
            'last_price':values[2201],'total_market_val':values[2301]})
    if session>str(today) or (session==str(today) and now.hour<16):raise ValueError('latest daily session not completed')
    if (today-datetime.strptime(session,'%Y-%m-%d').date()).days>14:raise ValueError('market snapshot too stale')
    config=load_config();eligible=[]
    for s in snapshots:
        name=s.get('sc_name') or s.get('name','')
        if 'ST' in name.upper():excluded['restricted_name']+=1;continue
        cap=s.get('total_market_val')
        if cap<=0 or s['last_price']<=0:excluded['missing_cap_or_price']+=1;continue
        if cap<=config['market_cap_max_cny']:eligible.append(s)
    selected=sorted(eligible,key=lambda s:(-s['total_market_val'],s['code']))[:details]
    results=[];input_stocks=[];failures=[]
    for s in selected:
        code=s['code']
        try:
            history=client.get('history',code=code,start=str(today-timedelta(days=730)),end=session)
            bars=normalized_bars(history,session)
            if abs(bars[-1]['close']-s['last_price'])>max(.03,s['last_price']*.001):raise ValueError('adjusted final close differs from snapshot')
            # Fundamentals stay absent: never substitute a report-period date for publication date.
            stock={'code':code,'name':s.get('sc_name') or s.get('name'),'market_cap_cny':s['total_market_val'],
                'session':session,'source':'Futu REST','bars':bars,'adjust_mode':'qfq_latest_snapshot',
                'adjustment_provenance':{'autype':1,'dividends_included':False,'retrieved_at':history['retrieved_at'],'historical_point_in_time':False}}
            result=analyze(stock,config)
            result.update(code=code,name=stock['name'],last_price=s['last_price'],market_cap_cny=s['total_market_val'],history_bars=len(bars),
                screening_eligible=False,missing_fields=['industry','roe','fundamental_publication_date','suspension_flag'],analysis_scope='technical_only')
            input_stocks.append(stock);results.append(result)
        except (RuntimeError,ValueError,KeyError) as e:failures.append({'code':code,'reason':str(e)})
    if not results:raise ValueError('no real history analysis succeeded')
    benchmarks=[]
    for code,name in [('SH.000001','上证指数'),('SZ.399001','深证成指'),('SZ.399006','创业板指')]:
        try:
            bars=normalized_bars(client.get('history',code=code,start=str(today-timedelta(days=730)),end=session),session)
            from .report import technical_judgment
            benchmarks.append({'code':code,'name':name,'last_close':bars[-1]['close'],**technical_judgment({'bars':bars})})
        except (RuntimeError,ValueError,KeyError,IndexError) as e:benchmarks.append({'code':code,'name':name,'missing':str(e)})
    return clean({'mode':'ANALYSIS_ONLY','generated_at':now.isoformat(),'session':session,'currency':'CNY','source':'Futu REST',
        'source_urls':['https://webapi.futunn.com/zh-cn/api/quote/screening/stock-screen','https://webapi.futunn.com/zh-cn/api/quote/basic-data/history-kline'],
        'quote_mode':'latest_completed_session; not a live tick feed','adjustment':'front-adjusted excluding dividends; latest retrieval, not PIT backtest',
        'coverage':{'universe_count':len(items),'snapshot_scope':'Shanghai/Shenzhen A shares via screener (no realtime entitlement)','excluded_bj_count':len(unsupported),'unsupported_market_count':0,'unsupported_markets':[],
            'snapshot_count':len(snapshots),'snapshot_missing':missing,'screen_values_timestamp':'not provided; retrieval timestamp recorded',
            'screen_scaling':'2201 price /1000; 2301 market cap /1000; cross-checked against 3 local authorized snapshots',
            'smallcap_snapshot_candidates':len(eligible),'detail_limit':details,'detail_success':len(results),'detail_failures':failures,
            'detail_selection':'largest market caps within <=7bn pool; not ranked by turnover','technology_pool_status':'industry coverage pending; not included','excluded_counts':dict(excluded)},
        'budget_cny':0,'trading_enabled':False,'llm_calls':0,'results':results,'input_stocks':input_stocks,'calendar_response':calendar,
        'benchmarks':benchmarks,'limitations':['Full-universe screener, limited detailed technical subset','Screen market cap has no provider timestamp; only latest research, not PIT backtest','ROE and publication dates not validated; no fundamental entry judgment','No frozen mined model activated']})

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='state/real-market-report.json');p.add_argument('--details',type=int,default=20);args=p.parse_args()
    report=build_report(MarketClient(os.environ.get('MARKET_CONTROL_TOKEN')),args.details)
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['mode','session','coverage','budget_cny']},ensure_ascii=False))
if __name__=='__main__':main()
