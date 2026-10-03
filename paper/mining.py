"""Bounded, free CPU research search over AlphaMaster features/operators.

Not the original RL trainer. Training selects candidates, validation selects one,
untouched test measures it once. Scores are predictive correlations, not returns.
"""
import argparse,json,math
from pathlib import Path
from .integrations import setup_upstream,validate_history,alpha_features,factor_score

def correlation(x,y):
    import numpy as np
    mask=np.isfinite(x)&np.isfinite(y)
    if mask.sum()<60 or np.std(x[mask])<1e-9 or np.std(y[mask])<1e-9:return None
    return float(np.corrcoef(x[mask],y[mask])[0,1])

def mine(stock,limit=192):
    import numpy as np
    from .core import evaluate
    from .service import load_config
    if evaluate(stock,load_config())['signal'] in ('BLOCKED','EXCLUDED'):raise ValueError('invalid research universe/data')
    commits=setup_upstream()
    from model_core.vocab import FORMULA_VOCAB
    from model_core.vm import StackVM
    df=validate_history(stock)
    if len(df)<700:raise ValueError('research requires 700+ daily bars with warmup and holdout')
    if not 1<=limit<=256:raise ValueError('candidate limit 1..256')
    features=alpha_features(df);vm=StackVM()
    # Signal at completed close t; target next open -> following open, not same close.
    opens=df['open'].to_numpy();target=np.full(len(df),np.nan)
    target[:-2]=opens[2:]/opens[1:-1]-1
    start=220;available=len(df)-start
    cut1=start+int(available*.6);cut2=start+int(available*.8);gap=5
    train=slice(start,cut1-gap);val=slice(cut1,cut2-gap);test=slice(cut2,len(df)-2)
    candidates=[[f] for f in FORMULA_VOCAB.feature_names]
    for op in ('NEG','TS_MEAN_5','DELTA','TS_ZSCORE_20'):
        if op in FORMULA_VOCAB.operator_names:candidates += [[f,op] for f in FORMULA_VOCAB.feature_names]
    ranked=[]
    for names in candidates[:limit]:
        values=vm.execute([FORMULA_VOCAB.token_names.index(n) for n in names],features)
        if values is None:continue
        a=values[0].detach().numpy();ic=correlation(a[train],target[train])
        if ic is not None:ranked.append((ic,names,a))
    top=sorted(ranked,key=lambda r:r[0],reverse=True)[:min(10,len(ranked))]
    validated=[(correlation(a[val],target[val]),ic,names,a) for ic,names,a in top]
    validated=[r for r in validated if r[0] is not None]
    if not validated:raise ValueError('no nondegenerate candidate')
    vic,tic,names,a=max(validated,key=lambda r:r[0])
    testic=correlation(a[test],target[test])
    return {'status':'research_only','execution_eligible':False,'search_method':'bounded_feature_operator_search',
        'vocab_version':FORMULA_VOCAB.version,'upstream_commit':commits['AlphaMaster'],'formula_names':names,
        'training_end':stock['session'],'selection_train_end':str(df.index[cut1-gap-1].date()),'validation_end':str(df.index[cut2-gap-1].date()),
        'test_start':str(df.index[cut2].date()),'target':'next_open_to_following_open','purge_bars':gap,
        'candidate_count':len(ranked),'train_pearson_ic':tic,'validation_pearson_ic':vic,'test_pearson_ic':testic,
        'test_used_for_selection':False,'returns_backtest_complete':False,'limitations':['No T+1 portfolio simulation','No fees/slippage/price-limit fills','Single supplied symbol; no claim of full-market predictive power']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--limit',type=int,default=192);args=p.parse_args()
    batch=json.loads(Path(args.input).read_text(encoding='utf-8'))
    if batch.get('dataset_kind')!='completed_session' or len(batch.get('stocks',[]))!=1:raise ValueError('one validated research symbol required')
    stock=batch['stocks'][0]
    if stock['source']!=batch['source'] or stock['session']!=batch['session']:raise ValueError('provenance mismatch')
    artifact=mine(stock,args.limit);Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(artifact,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'status':artifact['status'],'candidate_count':artifact['candidate_count']}))
if __name__=='__main__':main()
