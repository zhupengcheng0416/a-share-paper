"""Frozen published-plan forward studies. No trading or hindsight reconstruction."""
import argparse,base64,hashlib,html,inspect,json,math,os,urllib.request,urllib.error
from collections import Counter
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from .market import MarketClient,normalized_bars
from .report import reference_levels,send,DeliveryLedger

ROOT=Path('.research')
RULE='published-plan-forward-v1'
FEE=.001  # Assumed all-in cost per side, not the user's broker fee schedule.
SLIP=.001
MAX_SYMBOLS=120

def archive(report,mail,prepare=False):
    """Prepare durably before SMTP; activate only a successfully delivered revision."""
    if not prepare and mail.get('mail_status')!='smtp_accepted':return {'archive_status':'not_newly_sent'}
    published=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    stocks={s['code']:s for s in report['input_stocks']}
    rows=[{'code':r['code'],'name':r['name'],'plan':reference_levels(stocks[r['code']],r),
           'seed':stocks[r['code']]['bars'][-61:]} for r in report['results']]
    delivery_key=hashlib.sha256(('market-v1|'+report['session']).encode()).hexdigest()[:24]
    content={'rule':RULE,'session':report['session'],'published_at':published,'state':'PREPARED' if prepare else 'SENT',
             'delivery_key':delivery_key,
             'price_rule_sha256':hashlib.sha256(inspect.getsource(reference_levels).encode()).hexdigest(),
             'message_id':mail.get('message_id',f'<{delivery_key}@a-share-analysis.local>'),'source':report['source'],'adjustment':report['adjustment'],
             'plans':rows,'coverage':report['coverage']}
    # Same report/session is immutable, including on an archive retry.
    path=ROOT/published[:7]/(report['session']+'.json')
    repo=os.environ['GITHUB_REPOSITORY']
    if repo!='zhupengcheng0416/a-share-paper':raise ValueError('unexpected archive repository')
    url=f'https://api.github.com/repos/{repo}/contents/{path.as_posix()}'
    headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'User-Agent':'a-share-analysis','Content-Type':'application/json'}
    sha=None;existing=None
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=20) as response:remote=json.load(response)
        sha=remote['sha'];existing=json.loads(base64.b64decode(remote['content']))
    except urllib.error.HTTPError as e:
        if e.code!=404:raise
    if existing:
        if existing['plans']!=content['plans'] or existing['price_rule_sha256']!=content['price_rule_sha256']:
            raise ValueError('frozen archive revision mismatch')
        if prepare or existing['state']=='SENT':
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(existing,ensure_ascii=False),encoding='utf-8')
            return {'archive_status':'existing_'+existing['state']}
        content['prepared_at']=existing['published_at']
    raw=json.dumps(content,ensure_ascii=False,allow_nan=False).encode()
    payload={'message':'Archive frozen research plans [skip ci]','branch':'main','content':base64.b64encode(raw).decode()}
    if sha:payload['sha']=sha
    request=urllib.request.Request(url,method='PUT',data=json.dumps(payload).encode(),headers=headers)
    with urllib.request.urlopen(request,timeout=20) as response:json.load(response)
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return {'archive_status':content['state'],'published_at':published,'plans':len(rows)}

def periods(today):
    # Only completed Monday-Sunday weeks, including ISO week-year boundaries.
    week_end=today-timedelta(days=today.weekday()+1)
    week_start=week_end-timedelta(days=6)
    iso=week_start.isocalendar()
    week=('weekly_backtest',f'{iso.year}-W{iso.week:02d}',week_start,week_end)
    previous=today.replace(day=1)-timedelta(days=1)
    month=('monthly_backtest',previous.strftime('%Y-%m'),previous.replace(day=1),previous)
    quarter_start=date(today.year,((today.month-1)//3)*3+1,1)
    end=quarter_start-timedelta(days=1);start=date(end.year,((end.month-1)//3)*3+1,1)
    return [week,month,('quarterly_backtest',f'{end.year}-Q{(end.month-1)//3+1}',start,end)]

def validate_history(bars):
    if not bars or [b['date'] for b in bars]!=sorted(set(b['date'] for b in bars)):
        raise ValueError('history_empty_duplicate_or_unsorted')
    for b in bars:
        for key in ('open','high','low','close','volume'):
            if not isinstance(b[key],(int,float)) or not math.isfinite(b[key]):raise ValueError('invalid_history_value')
        if not (0<b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high']) or b['volume']<0:
            raise ValueError('invalid_history_geometry')

def evaluate(row,published_at,bars,end,benchmark=None,calendar_days=None):
    plan=row['plan'];base={'code':row['code'],'name':row['name'],'published_at':published_at}
    def outcome(status,**values):return dict(base,status=status,**values)
    if plan['status']!='CONDITIONAL':return outcome('OBSERVE',reason=plan['reason'])
    validate_history(bars)
    # Reject revised/ex-rights snapshots rather than silently repricing old plans.
    lookup={b['date']:b for b in bars}
    for seed in row['seed']:
        current=lookup.get(seed['date'])
        if not current or any(abs(current[k]-seed[k])>1e-6 for k in ('open','high','low','close')):
            return outcome('DATA_UNAVAILABLE',reason='historical_price_revision_or_adjustment_changed')
    published_date=datetime.fromisoformat(published_at).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    future=[b for b in bars if published_date<b['date']<=end]
    expected=[d for d in (calendar_days or []) if published_date<d<=end]
    if expected and (not future or future[0]['date']!=expected[0]):
        return outcome('DATA_UNAVAILABLE',reason='missing_first_post_publication_session')
    if not future:return outcome('PENDING',reason='no_post_publication_session')
    confirmation=future[0]
    history=[b['close'] for b in bars if b['date']<=confirmation['date']]
    if len(history)<60:return outcome('DATA_UNAVAILABLE',reason='insufficient_ma_history')
    # One future session to confirm; newer daily plans supersede unconfirmed plans.
    qualifies=(plan['support_low']<=confirmation['low']<=plan['support_high']
               and confirmation['low']>plan['stop'] and plan['buy_low']<=confirmation['close']<=plan['buy_high']
               and sum(history[-20:])/20>=sum(history[-60:])/60 and confirmation['close']>=sum(history[-60:])/60)
    if not qualifies:return outcome('NOT_TRIGGERED')
    if len(future)<2:
        return outcome('DATA_UNAVAILABLE',reason='missing_entry_session') if len(expected)>1 else outcome('CONFIRMED_PENDING_ENTRY')
    entry_bar=future[1];entry=entry_bar['open']*(1+SLIP)
    if expected and (len(expected)<2 or entry_bar['date']!=expected[1]):
        return outcome('DATA_UNAVAILABLE',reason='missing_entry_session')
    if entry_bar['volume']<=0 or entry_bar['low']==entry_bar['high']:
        return outcome('EXECUTION_UNCERTAIN',reason='zero_volume_or_single_price_entry')
    if not plan['buy_low']<=entry<=plan['buy_high']:
        return outcome('ENTRY_CANCELLED',reason='next_open_after_slippage_outside_buy_band')
    base.update(entry_date=entry_bar['date'],entry_price=entry)
    peak=entry;drawdown=min(0,entry_bar['close']/peak-1);peak=max(peak,entry_bar['close']);tp1=False
    deferred_stop=entry_bar['low']<=plan['stop']
    # Entry-day exits are forbidden (T+1); follow the frozen study until exit.
    for holding,b in enumerate(future[2:],start=2):
        if expected and (holding>=len(expected) or b['date']!=expected[holding]):
            return outcome('DATA_UNAVAILABLE',reason='missing_holding_session')
        tp1=tp1 or b['high']>=plan['take_profit_1']
        stop_hit=b['low']<=plan['stop'];target_hit=b['high']>=plan['take_profit_2']
        if deferred_stop or stop_hit or target_hit or holding>=20:
            if b['volume']<=0 or b['low']==b['high']:
                return outcome('EXECUTION_UNCERTAIN',reason='zero_volume_or_single_price_exit')
            # OHLC cannot resolve order: stop first; adverse gap fills at open.
            exit_raw=b['open'] if deferred_stop else min(b['open'],plan['stop']) if stop_hit else plan['take_profit_2'] if target_hit else b['close']
            exit_price=exit_raw*(1-SLIP)
            peak=max(peak,exit_price);drawdown=min(drawdown,exit_price/peak-1)
            gross=exit_price/entry-1;net=exit_price*(1-FEE)/(entry*(1+FEE))-1
            reason='T1_DEFERRED_STOP_NEXT_OPEN' if deferred_stop else 'STOP_FIRST_AMBIGUOUS' if stop_hit and target_hit else 'STOP' if stop_hit else 'TARGET_2R' if target_hit else 'TIME_20_SESSIONS'
            matched=None
            if benchmark and entry_bar['date'] in benchmark and b['date'] in benchmark:
                matched=benchmark[b['date']]['close']/benchmark[entry_bar['date']]['open']-1
            return outcome('CLOSED',exit_date=b['date'],exit_price=exit_price,exit_reason=reason,
                           gross_return=gross,net_return=net,benchmark_return=matched,
                           excess_return=None if matched is None else net-matched,
                           max_close_drawdown=drawdown,take_profit_1_hit=tp1,
                           sensitivity={str(f):exit_price*(1-f)/(entry*(1+f))-1 for f in (.0005,.001,.002)})
        peak=max(peak,b['close']);drawdown=min(drawdown,b['close']/peak-1)
    last=future[-1]
    return outcome('OPEN',mark_date=last['date'],unrealized_return=last['close']/entry-1,max_close_drawdown=drawdown,take_profit_1_hit=tp1)

def summarize(cases):
    closed=[r for r in cases if r['status']=='CLOSED'];conditional=[r for r in cases if r['status']!='OBSERVE']
    entries=[r for r in cases if 'entry_date' in r]
    confirmable=[r for r in cases if r['status'] not in ('OBSERVE','PENDING','DATA_UNAVAILABLE')]
    confirmed=[r for r in confirmable if r['status']!='NOT_TRIGGERED']
    entry_evaluable=[r for r in cases if r['status'] in ('NOT_TRIGGERED','ENTRY_CANCELLED','OPEN','CLOSED') or (r['status']=='EXECUTION_UNCERTAIN' and 'entry_date' in r)]
    returns=[r['net_return'] for r in closed];excess=[r['excess_return'] for r in closed if r.get('excess_return') is not None]
    return {'published_stock_cases':len(cases),'conditional_cases':len(conditional),'status_counts':dict(Counter(r['status'] for r in cases)),
            'hypothetical_entries':len(entries),'closed_cases':len(closed),
            'confirmation_rate':len(confirmed)/len(confirmable) if confirmable else None,
            'entry_rate':sum('entry_date' in r for r in entry_evaluable)/len(entry_evaluable) if entry_evaluable else None,
            'win_rate':sum(r>0 for r in returns)/len(returns) if returns else None,
            'mean_net_return':sum(returns)/len(returns) if returns else None,
            'mean_excess_vs_sse':sum(excess)/len(excess) if excess else None,
            'worst_case_close_drawdown':min((r['max_close_drawdown'] for r in entries if 'max_close_drawdown' in r),default=None),
            'sufficient_sample':len(closed)>=30,'portfolio_return':None,
            'annualized_return':None,'sharpe':None}

def build_feedback(client,kind,label,start,end,root=ROOT):
    records=[]
    for path in sorted(root.glob('*/*.json')):
        record=json.loads(path.read_text(encoding='utf-8'))
        if record.get('state')!='SENT':
            # Recover SMTP success even if post-send archive activation failed.
            delivery=Path('.delivery')/(record['delivery_key']+'.json')
            if not delivery.exists():continue
            status=json.loads(delivery.read_text(encoding='utf-8'))
            if status.get('state')!='SENT':continue
            record['published_at']=datetime.fromisoformat(status['updated_at']).astimezone(ZoneInfo('Asia/Shanghai')).isoformat()
        published=datetime.fromisoformat(record['published_at']).astimezone(ZoneInfo('Asia/Shanghai')).date()
        if record.get('rule')!=RULE:raise ValueError('unknown archived rule version')
        if start<=published<=end:records.append(record)
    conditional=[(record,row) for record in records for row in record['plans'] if row['plan']['status']=='CONDITIONAL']
    codes=sorted(set(row['code'] for _,row in conditional));history={};errors={};benchmark={};days=[]
    if conditional:
        calendar=client.get('calendar',start=str(start),end=str(end))
        days=[d['time'] for d in calendar['data']['trading_days'] if d['time']<=str(end)]
        if not days:raise ValueError('period_calendar_unavailable')
        session=max(days)
        for code in codes[:MAX_SYMBOLS]:
            seed_start=min(row['seed'][0]['date'] for _,row in conditional if row['code']==code)
            try:history[code]=normalized_bars(client.get('history',code=code,start=seed_start,end=session),session)
            except (RuntimeError,ValueError,KeyError) as e:errors[code]=str(e)
        for code in codes[MAX_SYMBOLS:]:errors[code]='free_symbol_budget_exceeded'
        try:
            bars=normalized_bars(client.get('history',code='SH.000001',start=str(start-timedelta(days=120)),end=session),session)
            benchmark={b['date']:b for b in bars}
        except (RuntimeError,ValueError,KeyError) as e:errors['SH.000001']=str(e)
    cases=[]
    for record in records:
        for row in record['plans']:
            if row['plan']['status']=='CONDITIONAL' and row['code'] in errors:
                cases.append({'code':row['code'],'name':row['name'],'published_at':record['published_at'],'status':'DATA_UNAVAILABLE','reason':errors[row['code']]});continue
            try:cases.append(evaluate(row,record['published_at'],history.get(row['code'],[]),str(end),benchmark,days))
            except (ValueError,KeyError,IndexError) as e:cases.append({'code':row['code'],'name':row['name'],'status':'DATA_UNAVAILABLE','reason':str(e)})
    return {'session':label,'kind':kind,'start':str(start),'end':str(end),'rule':RULE,
            'generated_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'source':'Futu REST + immutable published-plan archive',
            'archive_days':len(records),'first_published_at':min((r['published_at'] for r in records),default=None),
            'errors':errors,'summary':summarize(cases),'cases':cases,'fee_per_side':FEE,'slippage_per_side':SLIP,'trading_enabled':False}

def render_feedback(report):
    esc=lambda v:html.escape(str(v));s=report['summary']
    pct=lambda v:'样本不足／暂无' if v is None else f'{v:.2%}'
    rows=[]
    names={'OBSERVE':'观察','NOT_TRIGGERED':'未触发','PENDING':'待后续行情','CONFIRMED_PENDING_ENTRY':'确认后待下一日开盘',
           'ENTRY_CANCELLED':'开盘不符取消','EXECUTION_UNCERTAIN':'成交条件无法核实','DATA_UNAVAILABLE':'数据缺失或复权变化','OPEN':'未结束','CLOSED':'已结束'}
    for c in report['cases']:
        rows.append(f"<tr><td>{esc(c['name'])}<br>{esc(c['code'])}</td><td>{esc(c.get('published_at',''))}</td><td>{esc(names[c['status']])}<br>{esc(c.get('reason',c.get('exit_reason','')))}</td><td>{esc(c.get('entry_date','—'))} → {esc(c.get('exit_date','—'))}</td><td>{pct(c.get('net_return'))}</td><td>{pct(c.get('max_close_drawdown'))}</td></tr>")
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><body style="font:15px system-ui;line-height:1.7;padding:24px;color:#18324e">
<h1>A股{ {'weekly_backtest':'周度','monthly_backtest':'月度','quarterly_backtest':'季度'}[report['kind']] }回测反馈 · {esc(report['session'])}</h1>
<p>期间：{report['start']}至{report['end']}；生成：{esc(report['generated_at'])}。范围：已发送报告的沪深A股详细分析子集，排除北交所。</p>
<p>留档{report['archive_days']}天，股票方案案例{s['published_stock_cases']}个，条件方案{s['conditional_cases']}个，假设入场{s['hypothetical_entries']}个，已结束{s['closed_cases']}个。确认触发率{pct(s['confirmation_rate'])}；入场率{pct(s['entry_rate'])}；已结束案例胜率{pct(s['win_rate'])}；平均净收益{pct(s['mean_net_return'])}；对应持有区间相对上证指数价格收益（指数不计费用）的平均差值{pct(s['mean_excess_vs_sse'])}；最大单案例收盘及退出价回撤{pct(s['worst_case_close_drawdown'])}。</p>
<p>{'已结束案例达到30个，但同股和日期相关性仍影响统计。' if s['sufficient_sample'] else '样本不足：已结束案例少于30个；暂无可验证的策略盈利结论。'} 确认率排除无发布后行情或数据不可得案例；入场率仅统计可判定入场的案例。未触发、未结束、复权变化及数据缺失单独列示，不当作零收益交易。不同日报可能重复覆盖同一股票，案例相互重叠；这是发布后前向方案回测，平均案例收益与回撤不是可投资组合收益或组合最大回撤。不输出年化收益或夏普比率。</p>
<table cellpadding="8" border="1" style="border-collapse:collapse"><tr><th>股票</th><th>发布时间</th><th>状态／原因</th><th>假设入场→退出</th><th>净收益</th><th>单案例收盘及退出价回撤</th></tr>{''.join(rows)}</table>
<h2>冻结方法与执行假设</h2><p>仅使用成功发信后的不可变方案；按实际发布时间归属自然周（周一至周日）/月份/季度，评估截至该周期结束日，不把休市期间发出的旧收盘报告归到过去。周期结束仍未退出的案例单列未结束，不计入胜率或已结束平均收益。第一根发布后日线验证回踩、收于买点带、未触及止损及MA20/MA60条件；未确认即过期。确认后下一交易日开盘计入0.1%不利滑点，仍在买点带内才假设入场，禁止用确认日收盘成交。确认后独立跟踪冻结方案，日报更新不修改该研究案例；最多20个交易日。全仓止盈采用2R，1R只记录触及情况，不假设分批卖出；买入当天不允许退出（T+1）；当日触及止损则在下一交易日开盘假设退出。同日止损与2R都触及，保守按止损优先；向下跳空按更低开盘价；单一价格或零成交量时不假装可成交。</p>
<p>佣金、税费等合并假设每边0.1%，另每边0.1%滑点；不是你的实际券商费率。回撤仅使用持仓期间收盘价及退出成交参考价，不使用退出后的当日收盘价。净收益计入这些假设，机器留档另列每边0.05%、0.1%、0.2%费用情景。未核实历史涨跌停/ST标记及完整订单簿，剩余成交假设不能代表券商实盘。历史OHLC与发布时61根种子逐根比对，复权或修订变化则剔除并披露；未验证分红现金流。停牌、退市或权限导致数据不可得时不填充价格。当前不做今日股票池的追溯历史选股，不宣称无幸存者偏差。</p>
<p>数据缺口：{esc(report['errors'])}；状态分布：{esc(s['status_counts'])}。源码规则版本：{RULE}；无订单、无付费服务。</p>
<p>来源：<a href="https://webapi.futunn.com/zh-cn/api/quote/basic-data/history-kline">富途历史日线</a>；<a href="https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml">上交所交易规则</a>。</p></body></html>'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--archive-report');p.add_argument('--mail-status',default='state/mail-status.json');p.add_argument('--send',action='store_true');args=p.parse_args()
    Path('state').mkdir(exist_ok=True)
    if args.archive_report:
        from .report import prioritize
        report=prioritize(json.loads(Path(args.archive_report).read_text(encoding='utf-8')))
        print(json.dumps(archive(report,json.loads(Path(args.mail_status).read_text(encoding='utf-8')))));return
    outputs=[]
    for kind,label,start,end in periods(datetime.now(ZoneInfo('Asia/Shanghai')).date()):
        # Avoid data collection and repeated SMTP calls for already processed periods.
        if args.send:
            key=hashlib.sha256((kind+'-v1|'+label).encode()).hexdigest()[:24];old=DeliveryLedger(key).current()
            if old and old['state'] in ('SENT','PENDING','UNCERTAIN'):
                outputs.append({'kind':kind,'session':label,'mail_status':'deduplicated_'+old['state']});continue
        report=build_feedback(MarketClient(),kind,label,start,end);body=render_feedback(report)
        stem=Path('state')/(kind+'-'+label)
        stem.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');stem.with_suffix('.html').write_text(body,encoding='utf-8')
        result=send(report,body,kind) if args.send else {'mail_status':'rendered_not_sent'}
        outputs.append(dict(result,kind=kind,summary=report['summary']))
    Path('state/feedback-status.json').write_text(json.dumps(outputs,ensure_ascii=False),encoding='utf-8');print(json.dumps(outputs,ensure_ascii=False))

if __name__=='__main__':main()
