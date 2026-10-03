"""Deterministic technical research report and fixed-recipient SMTP delivery."""
import argparse,base64,hashlib,html,json,os,smtplib,ssl,urllib.request,urllib.error
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

def render(report):
    esc=lambda v:html.escape(str(v));coverage=report['coverage'];rows=[]
    benchmarks='；'.join(esc(b['name'])+'：'+(esc(b['trend'])+f"（收盘{b['last_close']:.2f}，60日{b['momentum60']:.1%}）" if 'trend' in b else '本次数据缺失') for b in report.get('benchmarks',[]))
    stocks={s['code']:s for s in report['input_stocks']}
    for result in report['results']:
        if 'integration' not in result:continue
        judgment=technical_judgment(stocks[result['code']]);price=result['last_price']
        sr=result['integration']['support_resistance'];zones=sr['zones']
        supports=[z for z in zones if z['zone_type']=='support'];resistances=[z for z in zones if z['zone_type']=='resistance']
        support=max(supports,key=lambda z:z['center']) if supports else None
        resistance=min(resistances,key=lambda z:z['center']) if resistances else None
        label=lambda z:'未识别' if z is None else f"{z['low']:.2f}–{z['high']:.2f}"
        atr=sr['context']['atr_pct'];risk='波动较大' if atr>5 else '仍需留意跌破支撑'
        if resistance and (resistance['low']/price-1)<.03:risk+='；接近阻力，不宜仅凭趋势判断追涨'
        rows.append(f"<tr><td>{esc(result['name'])}<br>{esc(result['code'])}</td><td>{price:.2f}</td><td>{esc(judgment['trend'])}<br>60日涨幅{judgment['momentum60']:.1%}</td><td>{label(support)}</td><td>{label(resistance)}</td><td>ATR占价格{atr:.2f}%<br>{esc(risk)}</td></tr>")
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><body style="font:15px system-ui;line-height:1.7;color:#18324e;max-width:1100px;margin:auto;padding:24px">
<h1>A股市场技术分析 · {esc(report['session'])}</h1><p>生成时间：{esc(report['generated_at'])}；币种：人民币。数据来自富途只读REST，使用最近已收盘交易日，未调用大模型或交易接口。</p>
<p>股票列表{coverage['universe_count']}只；沪深A股选股取值{coverage['snapshot_count']}只，取值缺失{len(coverage['snapshot_missing'])}只；按用户要求排除北交所{coverage.get('excluded_bj_count',0)}只。70亿元以内候选{coverage['smallcap_snapshot_candidates']}只。
详细分析选取市值最接近70亿元上限的前{coverage['detail_limit']}只候选：成功{coverage['detail_success']}只，失败{len(coverage['detail_failures'])}只。该部分是子集，不是全市场逐股技术扫描。</p>
<p>市场指数判断：{benchmarks}</p>
<h2>技术判断</h2><p>均线判断使用MA20/MA60；支撑阻力来自V3Fusion；AlphaMaster计算65个特征，PA_Agent提供价格行为客观依据。没有经过验证的冻结挖掘模型，因子分数不用于选股建议。</p>
<table cellpadding="10" style="border-collapse:collapse;width:100%;border:1px solid #ccd"><thead><tr><th>股票</th><th>收盘价</th><th>趋势</th><th>邻近支撑</th><th>邻近阻力</th><th>风险观察</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>数据边界</h2><p>行情快照需要额外实时行情权限，本版本使用免费可访问的选股取值和历史日线。选股取值未提供单股时间戳，详细分析以交易日历与最后一根日线及价格交叉检查；不把市值取值用于历史时点回测。行业覆盖、停牌标记与ROE公布日期尚未核实，科技股池及财务质量筛选暂缺；不将缺失值当作达标。前复权不含股息，取本次最新快照，不能用于历史时点回测。支撑阻力可能失效，不输出未经验证的胜率。</p>
<p>失败记录：{esc(coverage['detail_failures'])}。快照缺失：{esc(coverage['snapshot_missing'])}。</p>
<p>来源：<a href="https://webapi.futunn.com/zh-cn/api/quote/screening/stock-screen">富途选股取值</a>；<a href="https://webapi.futunn.com/zh-cn/api/quote/basic-data/history-kline">历史日线</a>。</p>
</body></html>'''

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

def send(report,body):
    recipient=load_config()['recipient'];sender=os.environ.get('MAIL_SMTP_USER','')
    if recipient!='zhupengcheng0416@163.com' or sender!=recipient:raise ValueError('fixed mailbox mismatch')
    password=os.environ.get('MAIL_SMTP_PASSWORD','')
    if not password:raise ValueError('SMTP authorization not configured')
    key=hashlib.sha256(('market-v1|'+report['session']).encode()).hexdigest()[:24];ledger=DeliveryLedger(key)
    previous=ledger.current()
    if previous and previous['state'] in ('PENDING','SENT','UNCERTAIN'):
        return {'mail_status':'deduplicated_'+previous['state'],'session':report['session']}
    status={'session':report['session'],'state':'PENDING','message_id':f'<{key}@a-share-analysis.local>','updated_at':datetime.now(timezone.utc).isoformat()}
    ledger.save(status)
    msg=EmailMessage();msg['From']=sender;msg['To']=recipient;msg['Subject']='A股市场技术分析 '+report['session'];msg['Message-ID']=status['message_id']
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
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--html',default='state/market-report.html');p.add_argument('--send',action='store_true');args=p.parse_args()
    report=json.loads(Path(args.input).read_text(encoding='utf-8'));body=render(report);Path(args.html).parent.mkdir(parents=True,exist_ok=True);Path(args.html).write_text(body,encoding='utf-8')
    result=send(report,body) if args.send else {'mail_status':'rendered_not_sent'}
    Path('state/mail-status.json').write_text(json.dumps(result),encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main()
