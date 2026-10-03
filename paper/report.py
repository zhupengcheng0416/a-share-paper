"""Deterministic technical research report and fixed-recipient SMTP delivery."""
import argparse,base64,hashlib,html,json,os,smtplib,ssl,urllib.request,urllib.error
import math
from decimal import Decimal,ROUND_CEILING,ROUND_FLOOR
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime,timezone
from .service import load_config

def technical_judgment(stock):
    closes=[b['close'] for b in stock['bars']]
    ma20=sum(closes[-20:])/20;ma60=sum(closes[-60:])/60
    if closes[-1]>ma20>ma60:trend='中短期趋势偏强'
    elif closes[-1]<ma20<ma60:trend='中短期趋势偏弱'
    else:trend='均线结构分歧，暂宜观察'
    return {'trend':trend,'ma20':ma20,'ma60':ma60,'momentum60':closes[-1]/closes[-61]-1}

def reference_levels(stock,result):
    """Conditional long research plan; no order, probability or execution promise."""
    def wait(reason):return {'status':'OBSERVE','reason':reason}
    sr=result.get('integration',{}).get('support_resistance',{})
    price=result.get('last_price');atr=sr.get('context',{}).get('atr')
    if not all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in (price,atr)):
        return wait('行情或ATR缺失，无法计算价位')
    zones=sr.get('zones',[])
    valid=[z for z in zones if all(isinstance(z.get(k),(int,float)) and math.isfinite(z[k]) for k in ('low','high')) and 0<z['low']<=z['high']]
    supports=[z for z in valid if z.get('zone_type')=='support' and z['high']<price]
    if not supports:return wait('未识别收盘价下方的完整支撑带')
    judgment=technical_judgment(stock)
    if judgment['ma20']<judgment['ma60'] or price<judgment['ma60']:
        return wait('趋势偏弱，等待均线与价格结构改善')
    support=max(supports,key=lambda z:z['high'])
    tick=Decimal('0.01')
    def cents(v,rounding):return float(Decimal(str(v)).quantize(tick,rounding=rounding))
    # Upper edge is the worst assumed entry. Stops round downward, targets upward.
    buy_low=cents(support['high']+.01,ROUND_CEILING)
    buy_high=cents(buy_low+.25*atr,ROUND_CEILING)
    stop=cents(support['low']-.5*atr,ROUND_FLOOR)
    if stop<=0 or stop>=buy_low:return wait('止损结构无效')
    risk=buy_high-stop
    target1=cents(buy_high+risk,ROUND_CEILING)
    target2=cents(buy_high+2*risk,ROUND_CEILING)
    resistances=[z for z in valid if z.get('zone_type')=='resistance' and z['high']>support['high']]
    if not resistances:return wait('上方阻力缺失，无法验证止盈空间')
    ceiling=cents(min(z['low'] for z in resistances),ROUND_FLOOR)
    if ceiling<target2:return wait('最近阻力前不足2R空间，暂不设买点')
    return {'status':'CONDITIONAL','buy_low':buy_low,'buy_high':buy_high,'stop':stop,
            'take_profit_1':target1,'take_profit_2':target2,'resistance_ceiling':ceiling,
            'risk_per_share':round(risk,2),'support_low':support['low'],'support_high':support['high']}

def reference_intervals(result):
    """Structural price ranges for inspection, without creating a buy signal."""
    sr=result.get('integration',{}).get('support_resistance',{})
    atr=sr.get('context',{}).get('atr');price=result.get('last_price')
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>0 for v in (atr,price)):
        return {'status':'UNAVAILABLE','reason':'价格或ATR缺失'}
    supports=[z for z in sr.get('zones',[]) if z.get('zone_type')=='support' and
              all(isinstance(z.get(k),(int,float)) and math.isfinite(z[k]) for k in ('low','high')) and 0<z['low']<=z['high']<price]
    if not supports:return {'status':'UNAVAILABLE','reason':'收盘价下方完整支撑带缺失'}
    support=max(supports,key=lambda z:z['high'])
    def cents(v,rounding):return float(Decimal(str(v)).quantize(Decimal('.01'),rounding=rounding))
    entry_low=cents(support['high']+.01,ROUND_CEILING)
    entry_high=cents(entry_low+.25*atr,ROUND_CEILING)
    stop_low=cents(support['low']-.5*atr,ROUND_FLOOR)
    stop_high=cents(support['low']-.25*atr,ROUND_FLOOR)
    if not 0<stop_low<=stop_high<entry_low:return {'status':'UNAVAILABLE','reason':'止损区间结构无效'}
    el,eh,sl,sh=map(lambda v:Decimal(str(v)),(entry_low,entry_high,stop_low,stop_high))
    return {'status':'REFERENCE_ONLY','assumed_entry_range':[entry_low,entry_high],
            'stop_range':[stop_low,stop_high],
            'take_profit_1_range':[cents(2*el-sh,ROUND_CEILING),cents(2*eh-sl,ROUND_CEILING)],
            'take_profit_2_range':[cents(3*el-2*sh,ROUND_CEILING),cents(3*eh-2*sl,ROUND_CEILING)]}

def levels_html(plan,intervals=None):
    extra=''
    if intervals:
        if intervals['status']=='REFERENCE_ONLY':
            band=lambda key:'–'.join(f'{v:.2f}' for v in intervals[key])
            extra=f"<br>结构参考止损区间 {band('stop_range')}<br>止盈一区间 {band('take_profit_1_range')}（1R）<br>止盈二区间 {band('take_profit_2_range')}（2R）"
            if plan['status']!='CONDITIONAL':extra+=f"<br>以上基于假设入场 {band('assumed_entry_range')}，仅观察，尚无有效买点。"
        else:extra='<br>区间无法计算：'+html.escape(intervals['reason'])
    if plan['status']!='CONDITIONAL':return '观察，不设买点<br>'+html.escape(plan['reason'])+extra
    return (f"条件买点 {plan['buy_low']:.2f}–{plan['buy_high']:.2f}<br>"
            f"止损参考 {plan['stop']:.2f}<br>止盈一 {plan['take_profit_1']:.2f}（1R）<br>"
            f"止盈二 {plan['take_profit_2']:.2f}（2R）<br>"
            f"触发：后续日线回踩支撑后收于买点区间；未触发则等待，超过上限不追买。"+extra)

def render_detailed(report):
    esc=lambda v:html.escape(str(v));coverage=report['coverage'];rows=[]
    benchmarks='；'.join(esc(b['name'])+'：'+(esc(b['trend'])+f"（收盘{b['last_close']:.2f}，60日{b['momentum60']:.1%}）" if 'trend' in b else '本次数据缺失') for b in report.get('benchmarks',[]))
    stocks={s['code']:s for s in report['input_stocks']}
    for result in report['results']:
        if 'integration' not in result:
            rows.append(f"<tr><td>{esc(result.get('name',''))}<br>{esc(result['code'])}</td><td colspan='6'>数据不足，买点及止盈止损暂缺</td></tr>")
            continue
        judgment=technical_judgment(stocks[result['code']]);price=result['last_price']
        sr=result['integration']['support_resistance'];zones=sr['zones']
        supports=[z for z in zones if z['zone_type']=='support'];resistances=[z for z in zones if z['zone_type']=='resistance']
        support=max(supports,key=lambda z:z['center']) if supports else None
        resistance=min(resistances,key=lambda z:z['center']) if resistances else None
        label=lambda z:'未识别' if z is None else f"{z['low']:.2f}–{z['high']:.2f}"
        atr=sr['context']['atr_pct'];risk='波动较大' if atr>5 else '仍需留意跌破支撑'
        if resistance and (resistance['low']/price-1)<.03:risk+='；接近阻力，不宜仅凭趋势判断追涨'
        plan=reference_levels(stocks[result['code']],result)
        rows.append(f"<tr><td>{esc(result['name'])}<br>{esc(result['code'])}</td><td>{price:.2f}</td><td>{esc(judgment['trend'])}<br>60日涨幅{judgment['momentum60']:.1%}</td><td>{label(support)}</td><td>{label(resistance)}</td><td>{levels_html(plan,reference_intervals(result))}</td><td>ATR占价格{atr:.2f}%<br>{esc(risk)}</td></tr>")
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><body style="font:15px system-ui;line-height:1.7;color:#18324e;max-width:1100px;margin:auto;padding:24px">
<h1>A股市场技术分析 · {esc(report['session'])}</h1><p>生成时间：{esc(report['generated_at'])}；币种：人民币。数据来自富途只读REST，使用最近已收盘交易日，未调用大模型或交易接口。</p>
<p>股票列表{coverage['universe_count']}只；沪深A股选股取值{coverage['snapshot_count']}只，取值缺失{len(coverage['snapshot_missing'])}只；按用户要求排除北交所{coverage.get('excluded_bj_count',0)}只。70亿元以内候选{coverage['smallcap_snapshot_candidates']}只。
详细分析选取市值最接近70亿元上限的前{coverage['detail_limit']}只候选：成功{coverage['detail_success']}只，失败{len(coverage['detail_failures'])}只。该部分是子集，不是全市场逐股技术扫描。</p>
<p>市场指数判断：{benchmarks}</p>
<h2>技术判断</h2><p>均线判断使用MA20/MA60；支撑阻力来自V3Fusion；AlphaMaster计算65个特征，PA_Agent提供价格行为客观依据。没有经过验证的冻结挖掘模型，因子分数不用于选股建议。</p>
<p>区间计算：止损区间为支撑下沿减0.5ATR至减0.25ATR；止盈一区间按假设入场区间与止损区间组合的1R上下界，止盈二区间按2R上下界。不同端点对应不同入场和止损假设，不能任意混用。区间仅展示结构敏感性，不代表成交保证；趋势或阻力条件不达标时仍仅观察。现有回测保留冻结的单点规则，未将新展示区间当成已验证的执行策略；这些ATR系数是工程参数，并非Ross规则。</p>
<table cellpadding="10" style="border-collapse:collapse;width:100%;border:1px solid #ccd"><thead><tr><th>股票</th><th>收盘价</th><th>趋势</th><th>邻近支撑</th><th>邻近阻力</th><th>条件买点／止盈止损（元）</th><th>风险观察</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>价位规则与触发条件</h2><p>仅为条件研究方案，不是已经触发的买入信号。要求MA20≥MA60且收盘价≥MA60。选择收盘价下方最近完整支撑带；买点下沿为支撑上沿+0.01元，上沿再加0.25×ATR；止损为支撑下沿−0.5×ATR。按买点上沿计算R=买点上沿−止损，止盈一为买点上沿+1R，止盈二为买点上沿+2R，且最近阻力下沿须不低于止盈二。价格按0.01元取整；止损和阻力下沿向下取整，买点和止盈向上取整。0.25、0.5与2R是工程研究参数，未经收益回测，不代表最优参数或胜率。</p>
<p>触发须等待发布后的首个完整交易日最低价进入支撑带、未触及止损且收盘价位于买点区间，同时重新核对均线与阻力空间；止损条件为触及止损参考价，触及任一止盈价后重新评估。买入当日受A股T+1限制，跳空或跌停也可能使止损无法按参考价成交。R与目标不含交易费用和滑点；复权变化或价格跌破止损时旧方案失效；首个后续交易日未确认的方案过期。确认后的案例在周期反馈中独立跟踪，最长20个交易日，日报更新不修改其研究价位。没有你的持仓成本，此处并非持仓专属卖出价。</p>
<h2>数据边界</h2><p>行情快照需要额外实时行情权限，本版本使用免费可访问的选股取值和历史日线。选股取值未提供单股时间戳，详细分析以交易日历与最后一根日线及价格交叉检查；不把市值取值用于历史时点回测。行业覆盖、停牌标记与ROE公布日期尚未核实，科技股池及财务质量筛选暂缺；不将缺失值当作达标。前复权不含股息，取本次最新快照，不能用于历史时点回测。支撑阻力可能失效，不输出未经验证的胜率。</p>
<p>失败记录：{esc(coverage['detail_failures'])}。快照缺失：{esc(coverage['snapshot_missing'])}。</p>
<p>来源：<a href="https://webapi.futunn.com/zh-cn/api/quote/screening/stock-screen">富途选股取值</a>；<a href="https://webapi.futunn.com/zh-cn/api/quote/basic-data/history-kline">历史日线</a>。</p>
</body></html>'''

def prioritize(report):
    """Rank valid technical setups, not unverifiable purchase suitability."""
    stocks={s['code']:s for s in report['input_stocks']};eligible=[]
    for r in report['results']:
        p=reference_levels(stocks[r['code']],r)
        if p['status']=='CONDITIONAL':
            eligible.append((p['risk_per_share']/p['buy_high'],abs(r['last_price']/p['buy_high']-1),r['code'],r))
    selected=[item[-1] for item in sorted(eligible,key=lambda x:x[:3])[:10]]
    return dict(report,results=selected,input_stocks=[stocks[r['code']] for r in selected],
                selection={'eligible_count':len(eligible),'selected_count':len(selected),'analyzed_count':len(report['results'])})

def render(report):
    report=prioritize(report) if 'selection' not in report else report
    stocks={s['code']:s for s in report['input_stocks']};rows=[]
    band=lambda values:'–'.join(f'{v:.2f}' for v in values)
    for rank,r in enumerate(report['results'],1):
        p=reference_levels(stocks[r['code']],r);b=reference_intervals(r)
        rows.append(f"<tr><td>{rank}</td><td>{html.escape(r['name'])}<br>{html.escape(r['code'])}</td><td>{p['buy_low']:.2f}–{p['buy_high']:.2f}</td><td>{band(b['take_profit_1_range'])}</td><td>{band(b['take_profit_2_range'])}</td><td>{band(b['stop_range'])}</td></tr>")
    selection=report['selection']
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><body style="font:16px system-ui;line-height:1.7;padding:20px">
<h1>A股优先技术候选 · {html.escape(report['session'])}</h1>
<p>详细筛选{selection['analyzed_count']}只，符合条件{selection['eligible_count']}只，本次选出{selection['selected_count']}只。价格单位：人民币元。</p>
<table border="1" cellpadding="10" style="border-collapse:collapse"><tr><th>顺序</th><th>股票</th><th>条件买入区间</th><th>止盈一区间</th><th>止盈二区间</th><th>止损区间</th></tr>{''.join(rows)}</table>
<p>{'暂无符合条件的股票。' if not rows else '等待后续日线回踩确认，未确认不买，超过买入上限不追涨。'}按止损距离占比、接近买入区间程度排序；这是沪深A股候选子集的技术筛选，尚缺财务及行业核验，不代表全市场最优。数据源：富途最近已收盘日线。</p>
<p>止损区间在支撑下沿以下0.25–0.5ATR；止盈区间按入场及止损假设的1R/2R计算，端点不能任意混用。A股T+1、跳空或跌停可能影响退出。仅研究，不下单。</p></body></html>'''

class DeliveryLedger:
    """Tiny delivery status in GitHub; durable PENDING before SMTP, never blind retry."""
    def __init__(self,key):
        repo=os.environ['GITHUB_REPOSITORY']
        if repo!='zhupengcheng0416/a-share-paper':raise ValueError('unexpected delivery repository')
        self.url=f'https://api.github.com/repos/{repo}/contents/.delivery/{key}.json';self.sha=None
    def request(self,data=None):
        req=urllib.request.Request(self.url,data=json.dumps(data).encode() if data is not None else None,method='PUT' if data is not None else 'GET',
            headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json','User-Agent':'a-share-analysis','Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
    def current(self):
        try:r=self.request()
        except urllib.error.HTTPError as e:
            if e.code==404:return None
            raise
        self.sha=r['sha'];return json.loads(base64.b64decode(r['content']))
    def save(self,status):
        data={'message':f'Record research email delivery {status["state"]} [skip ci]',
            'content':base64.b64encode(json.dumps(status).encode()).decode(),'branch':'main'}
        if self.sha:data['sha']=self.sha
        r=self.request(data);self.sha=r['content']['sha']

def send(report,body,kind='market',test_id=None):
    subjects={'market':'A股优先技术候选与价格区间','selection_test':'【测试】A股优先候选与买入止盈止损区间','weekly_backtest':'A股周度回测反馈','monthly_backtest':'A股月度回测反馈','quarterly_backtest':'A股季度回测反馈'}
    if kind not in subjects:raise ValueError('unsupported report kind')
    if kind=='selection_test' and (not isinstance(test_id,str) or not test_id.isdigit()):raise ValueError('explicit test run id required')
    recipient=load_config()['recipient'];sender=os.environ.get('MAIL_SMTP_USER','')
    if recipient!='zhupengcheng0416@163.com' or sender!=recipient:raise ValueError('fixed mailbox mismatch')
    password=os.environ.get('MAIL_SMTP_PASSWORD','')
    if not password:raise ValueError('SMTP authorization not configured')
    identity=kind+'-v1|'+report['session']+('|' + test_id if kind=='selection_test' else '')
    key=hashlib.sha256(identity.encode()).hexdigest()[:24];ledger=DeliveryLedger(key)
    previous=ledger.current()
    if previous and previous['state'] in ('PENDING','SENT','UNCERTAIN'):
        return {'mail_status':'deduplicated_'+previous['state'],'session':report['session']}
    if kind=='market':
        from .feedback import archive
        archive(report,{},prepare=True)
    status={'session':report['session'],'state':'PENDING','message_id':f'<{key}@a-share-analysis.local>','updated_at':datetime.now(timezone.utc).isoformat()}
    ledger.save(status)
    msg=EmailMessage();msg['From']=sender;msg['To']=recipient;msg['Subject']=subjects[kind]+' '+report['session'];msg['Message-ID']=status['message_id']
    msg.set_content('本邮件包含HTML格式的市场技术分析报告。');msg.add_alternative(body,subtype='html')
    try:
        with smtplib.SMTP_SSL('smtp.163.com',465,timeout=30,context=ssl.create_default_context()) as smtp:
            smtp.login(sender,password);refused=smtp.send_message(msg)
            if refused:raise smtplib.SMTPRecipientsRefused(refused)
        status['state']='SENT'
    except (smtplib.SMTPAuthenticationError,smtplib.SMTPRecipientsRefused) as e:
        status.update(state='FAILED_BEFORE_DELIVERY',error_type=type(e).__name__);ledger.save(status);raise RuntimeError(status['error_type']) from None
    except Exception as e:
        status.update(state='UNCERTAIN',error_type=type(e).__name__);ledger.save(status);raise RuntimeError('mail_delivery_uncertain_no_automatic_retry') from None
    status['updated_at']=datetime.now(timezone.utc).isoformat();ledger.save(status)
    return {'mail_status':'smtp_accepted','session':report['session'],'message_id':status['message_id'],'inbox_delivery':'not_independently_verified'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--html',default='state/market-report.html');p.add_argument('--send',action='store_true');p.add_argument('--test-id');args=p.parse_args()
    report=prioritize(json.loads(Path(args.input).read_text(encoding='utf-8')));body=render(report);Path(args.html).parent.mkdir(parents=True,exist_ok=True);Path(args.html).write_text(body,encoding='utf-8')
    if args.test_id:
        stocks={s['code']:s for s in report['input_stocks']}
        plans=[dict(code=r['code'],name=r['name'],**reference_levels(stocks[r['code']],r)) for r in report['results']]
        valid=[p for p in plans if p['status']=='CONDITIONAL']
        intervals=[dict(code=r['code'],name=r['name'],**reference_intervals(r)) for r in report['results']]
        banner=f'<p><strong>用户主动请求的测试邮件</strong>：行情日期{html.escape(report["session"])}；条件方案{len(valid)}只。未满足技术条件的股票仅列观察，不强设价位。仅用于检查选股报告和邮件通道，不下单。</p>'
        body=body.replace('<h1>',banner+'<h1>',1)
        Path(args.html).write_text(body,encoding='utf-8')
        print(json.dumps({'test_plan_count':len(valid),'conditional_plans':valid,'interval_count':sum(p['status']=='REFERENCE_ONLY' for p in intervals),'intervals':intervals},ensure_ascii=False))
    result=send(report,body,'selection_test',args.test_id) if args.send and args.test_id else send(report,body) if args.send else {'mail_status':'rendered_not_sent'}
    Path('state').mkdir(parents=True,exist_ok=True)
    Path('state/selection-test-status.json' if args.test_id else 'state/mail-status.json').write_text(json.dumps(result),encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main()
