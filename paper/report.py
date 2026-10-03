"""Deterministic technical research report and fixed-recipient SMTP delivery."""
import argparse,base64,hashlib,html,json,os,smtplib,ssl,urllib.request,urllib.error
from email.message import EmailMessage
from pathlib import Path
from datetime import datetime,timezone
from .service import load_config

def technical_judgment(stock):
    closes=[b['close'] for b in stock['bars']]
    ma20=sum(closes[-20:])/20;ma60=sum(closes[-60:])/60
    if closes[-1]>ma20>ma60:trend='�ж�������ƫǿ'
    elif closes[-1]<ma20<ma60:trend='�ж�������ƫ��'
    else:trend='���߽ṹ���磬���˹۲�'
    return {'trend':trend,'ma20':ma20,'ma60':ma60,'momentum60':closes[-1]/closes[-61]-1}

def render(report):
    esc=lambda v:html.escape(str(v));coverage=report['coverage'];rows=[]
    benchmarks='��'.join(esc(b['name'])+'��'+(esc(b['trend'])+f"������{b['last_close']:.2f}��60��{b['momentum60']:.1%}��" if 'trend' in b else '��������ȱʧ') for b in report.get('benchmarks',[]))
    stocks={s['code']:s for s in report['input_stocks']}
    for result in report['results']:
        if 'integration' not in result:continue
        judgment=technical_judgment(stocks[result['code']]);price=result['last_price']
        sr=result['integration']['support_resistance'];zones=sr['zones']
        supports=[z for z in zones if z['zone_type']=='support'];resistances=[z for z in zones if z['zone_type']=='resistance']
        support=max(supports,key=lambda z:z['center']) if supports else None
        resistance=min(resistances,key=lambda z:z['center']) if resistances else None
        label=lambda z:'δʶ��' if z is None else f"{z['low']:.2f}�C{z['high']:.2f}"
        atr=sr['context']['atr_pct'];risk='�����ϴ�' if atr>5 else '�����������֧��'
        if resistance and (resistance['low']/price-1)<.03:risk+='���ӽ����������˽�ƾ�����ж�׷��'
        rows.append(f"<tr><td>{esc(result['name'])}<br>{esc(result['code'])}</td><td>{price:.2f}</td><td>{esc(judgment['trend'])}<br>60���Ƿ�{judgment['momentum60']:.1%}</td><td>{label(support)}</td><td>{label(resistance)}</td><td>ATRռ�۸�{atr:.2f}%<br>{esc(risk)}</td></tr>")
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><body style="font:15px system-ui;line-height:1.7;color:#18324e;max-width:1100px;margin:auto;padding:24px">
<h1>A���г��������� �� {esc(report['session'])}</h1><p>����ʱ�䣺{esc(report['generated_at'])}�����֣�����ҡ��������Ը�;ֻ��REST��ʹ����������̽����գ�δ���ô�ģ�ͻ��׽ӿڡ�</p>
<p>��Ʊ�б�{coverage['universe_count']}ֻ������A��ѡ��ȡֵ{coverage['snapshot_count']}ֻ��ȡֵȱʧ{len(coverage['snapshot_missing'])}ֻ�����û�Ҫ���ų�������{coverage.get('excluded_bj_count',0)}ֻ��70��Ԫ���ں�ѡ{coverage['smallcap_snapshot_candidates']}ֻ��
��ϸ����ѡȡ��ֵ��ӽ�70��Ԫ���޵�ǰ{coverage['detail_limit']}ֻ��ѡ���ɹ�{coverage['detail_success']}ֻ��ʧ��{len(coverage['detail_failures'])}ֻ���ò������Ӽ�������ȫ�г���ɼ���ɨ�衣</p>
<p>�г�ָ���жϣ�{benchmarks}</p>
<h2>�����ж�</h2><p>�����ж�ʹ��MA20/MA60��֧����������V3Fusion��AlphaMaster����65��������PA_Agent�ṩ�۸���Ϊ�͹����ݡ�û�о�����֤�Ķ����ھ�ģ�ͣ����ӷ���������ѡ�ɽ��顣</p>
<table cellpadding="10" style="border-collapse:collapse;width:100%;border:1px solid #ccd"><thead><tr><th>��Ʊ</th><th>���̼�</th><th>����</th><th>�ڽ�֧��</th><th>�ڽ�����</th><th>���չ۲�</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>���ݱ߽�</h2><p>���������Ҫ����ʵʱ����Ȩ�ޣ����汾ʹ����ѿɷ��ʵ�ѡ��ȡֵ����ʷ���ߡ�ѡ��ȡֵδ�ṩ����ʱ�������ϸ�����Խ������������һ�����߼��۸񽻲��飻������ֵȡֵ������ʷʱ��ز⡣��ҵ���ǡ�ͣ�Ʊ����ROE����������δ��ʵ���Ƽ��ɳؼ���������ɸѡ��ȱ������ȱʧֵ������ꡣǰ��Ȩ������Ϣ��ȡ�������¿��գ�����������ʷʱ��ز⡣֧����������ʧЧ�������δ����֤��ʤ�ʡ�</p>
<p>ʧ�ܼ�¼��{esc(coverage['detail_failures'])}������ȱʧ��{esc(coverage['snapshot_missing'])}��</p>
<p>��Դ��<a href="https://webapi.futunn.com/zh-cn/api/quote/screening/stock-screen">��;ѡ��ȡֵ</a>��<a href="https://webapi.futunn.com/zh-cn/api/quote/basic-data/history-kline">��ʷ����</a>��</p>
</body></html>'''

class DeliveryLedger:
    """Tiny delivery status in GitHub; durable PENDING before SMTP, never blind retry."""
    def __init__(self,key):
        repo=os.environ['GITHUB_REPOSITORY']
        if repo!='zhupengcheng0416/a-share-paper':raise ValueError('unexpected delivery repository')
        self.url=f'https://api.github.com/repos/{repo}/contents/.delivery/{key}.json';self.sha=None
    def request(self,data=None):
        req=urllib.request.Request(self.url,data=json.dumps(data).encode() if data else None,
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
    msg=EmailMessage();msg['From']=sender;msg['To']=recipient;msg['Subject']='A���г��������� '+report['session'];msg['Message-ID']=status['message_id']
    msg.set_content('���ʼ�����HTML��ʽ���г������������档');msg.add_alternative(body,subtype='html')
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
