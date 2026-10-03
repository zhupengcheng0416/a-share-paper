"""Headless adapters over pinned upstream algorithms; no broker/LLM clients."""
import argparse
import dataclasses
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from .core import evaluate, Ledger

ROOT=Path(__file__).resolve().parents[1]

def setup_upstream():
    lock=json.loads((ROOT/'upstream-lock.json').read_text(encoding='utf-8'))
    for item in lock:
        root=ROOT/'vendor'/item['name']
        for name,digest in item['files'].items():
            if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:
                raise ValueError('upstream source integrity mismatch: '+name)
        if str(root) not in sys.path:sys.path.insert(0,str(root))
    return {item['name']:item['commit'] for item in lock}

def clean(value):
    if dataclasses.is_dataclass(value):value=dataclasses.asdict(value)
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,float) and not math.isfinite(value):return None
    return value

def validate_history(stock):
    import pandas as pd
    bars=stock['bars']
    if len(bars)<260:raise ValueError('integration requires at least 260 completed daily bars')
    if stock.get('adjust_mode') not in ('hfq_point_in_time','qfq_asof_session','qfq_latest_snapshot'):
        raise ValueError('adjustment provenance required')
    for bar in bars:
        datetime.strptime(bar['date'],'%Y-%m-%d')
        if bar.get('closed') is not True:raise ValueError('forming bar prohibited')
        if any(not isinstance(bar.get(k),(int,float)) or isinstance(bar[k],bool) or not math.isfinite(bar[k]) for k in ('open','high','low','close','volume','turnover_cny')):
            raise ValueError('invalid numeric history')
        if not 0<bar['low']<=min(bar['open'],bar['close'])<=max(bar['open'],bar['close'])<=bar['high'] or bar['volume']<=0 or bar['turnover_cny']<=0:
            raise ValueError('invalid price/volume history')
    dates=[b['date'] for b in bars]
    if dates!=sorted(set(dates)) or dates[-1]!=stock['session']:raise ValueError('session mismatch')
    frame=pd.DataFrame(bars)
    frame.index=pd.to_datetime(frame.pop('date'))
    return frame

def alpha_features(df):
    import torch
    from model_core.features import MT5FeatureEngineer
    torch.set_num_threads(2)
    raw={k:torch.tensor(df[k].values.copy(),dtype=torch.float32).unsqueeze(0) for k in ('open','high','low','close','volume')}
    features=MT5FeatureEngineer.compute_features(raw)
    if not torch.isfinite(features).all():raise ValueError('nonfinite feature tensor')
    return features

def factor_score(features,artifact):
    from model_core.vm import StackVM
    from model_core.vocab import FORMULA_VOCAB
    FORMULA_VOCAB.verify(artifact['vocab_version'])
    names=artifact['formula_names']
    if not names or len(names)>8:raise ValueError('formula length invalid')
    tokens=[FORMULA_VOCAB.token_names.index(n) for n in names]
    result=StackVM().execute(tokens,features)
    if result is None:raise ValueError('invalid formula')
    score=float(result[0,-1])
    if not math.isfinite(score):raise ValueError('nonfinite score')
    return score

def analyze(stock,config,artifact=None):
    decision=evaluate(stock,config)
    if decision['signal']=='EXCLUDED' or (decision['signal']=='BLOCKED' and decision.get('reason')!='missing_data'):return decision
    commits=setup_upstream()
    df=validate_history(stock)
    from src.sr_engine import SREngine
    from pa_agent.data.base import KlineBar
    from pa_agent.data.snapshot import take_snapshot_from_bars
    from pa_agent.ai.market_features import build_program_features_dict
    from pa_agent.ai.kline_features import compute_kline_geometry_features
    from model_core.vocab import FORMULA_VOCAB
    df.attrs.update(adjust_mode=stock['adjust_mode'],adjust_source=stock['source'],tick_base=0.01)
    zones,context=SREngine().detect(df,stock['code'])
    # Upstream calibration files are deliberately not bundled: no transplanted win rate.
    bars=[KlineBar(seq=i+1,ts_open=datetime.strptime(b['date'],'%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp()*1000,
        open=b['open'],high=b['high'],low=b['low'],close=b['close'],volume=b['volume'],amount=b['turnover_cny'],closed=True)
        for i,b in enumerate(reversed(stock['bars']))]
    frame=take_snapshot_from_bars(bars,60,stock['code'],'1d')
    features=alpha_features(df)
    alpha={'feature_count':features.shape[1],'vocab_version':FORMULA_VOCAB.version,'model_status':'no_frozen_factor','score':None}
    if artifact:
        if stock.get('adjust_mode')=='qfq_latest_snapshot':raise ValueError('latest-adjusted snapshot prohibited for frozen research backtest')
        if artifact.get('training_end','9999')>=stock['session']:raise ValueError('factor not frozen before decision session')
        if artifact.get('upstream_commit')!=commits['AlphaMaster']:raise ValueError('factor source version mismatch')
        alpha.update(score=factor_score(features,artifact),model_status=artifact.get('status','research_only'),formula_names=artifact['formula_names'])
    decision['base_signal']=decision['signal']
    decision['signal']='WATCH' if decision['base_signal']!='BLOCKED' else 'BLOCKED'
    decision['integration']={'commits':commits,'support_resistance':{'zones':zones,'context':context},'alpha':alpha,
        'price_action':{'program_features':build_program_features_dict(frame),'geometry':clean(compute_kline_geometry_features(frame,limit=10)),
        'mode':'deterministic_grounding','llm_calls':0},'execution':'DISABLED','validation_status':'research_only'}
    return clean(decision)

def run_batch(input_path,output_path,db_path,artifact_path=None):
    from .service import load_config
    batch=json.loads(Path(input_path).read_text(encoding='utf-8-sig'))
    if batch.get('dataset_kind')!='completed_session' or not batch.get('source') or not batch.get('stocks'):
        raise ValueError('validated completed-session dataset required')
    codes=[s['code'] for s in batch['stocks']]
    if len(codes)!=len(set(codes)):raise ValueError('duplicate symbols')
    artifact=json.loads(Path(artifact_path).read_text(encoding='utf-8')) if artifact_path else None
    results=[];config=load_config()
    for stock in batch['stocks']:
        if stock['session']!=batch['session'] or stock['source']!=batch['source']:raise ValueError('batch provenance mismatch')
        try:result=analyze(stock,config,artifact)
        except (ValueError,KeyError) as e:result={'code':stock.get('code'),'signal':'BLOCKED','reason':str(e)}
        results.append(result)
    report={'session':batch['session'],'source':batch['source'],'coverage':batch.get('coverage','supplied_subset'),
        'dataset_kind':batch['dataset_kind'],'budget_cny':0,'orders_submitted':0,'results':results}
    Path(db_path).parent.mkdir(parents=True,exist_ok=True)
    ledger=Ledger(db_path)
    try:
        for stock,result in zip(batch['stocks'],results):ledger.decision({'input':stock,'config':config,'result':result,'execution':'DISABLED'})
        ledger.event('integrated_scan_complete',{k:v for k,v in report.items() if k!='results'})
    finally:ledger.db.close()
    Path(output_path).parent.mkdir(parents=True,exist_ok=True)
    Path(output_path).write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    p.add_argument('--db',default=str(ROOT/'state/ledger.sqlite3'));p.add_argument('--factor');args=p.parse_args()
    report=run_batch(args.input,args.output,args.db,args.factor)
    print(json.dumps({'scanned':len(report['results']),'orders_submitted':0,'coverage':report['coverage']}))

if __name__=='__main__':main()
