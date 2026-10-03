import argparse
import hmac
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .core import Ledger, check_config, evaluate

ROOT=Path(__file__).resolve().parents[1]


def load_config():
    config=json.loads((ROOT/'config.json').read_text(encoding='utf-8-sig'))
    check_config(config)
    return config


def scan(input_path,db_path):
    config=load_config()
    # Source adapter publishes one fully validated file atomically. No fake feed.
    batch=json.loads(Path(input_path).read_text(encoding='utf-8-sig'))
    if batch.get('dataset_kind')!='completed_session' or not batch.get('source') or not batch.get('session'):
        raise ValueError('invalid dataset provenance')
    if not isinstance(batch.get('stocks'),list) or not batch['stocks']:
        raise ValueError('no data; scan failed')
    codes=[s.get('code') for s in batch['stocks']]
    if len(set(codes))!=len(codes):
        raise ValueError('duplicate symbols')
    ledger=Ledger(db_path)
    results=[]
    for stock in batch['stocks']:
        if stock.get('session')!=batch['session'] or stock.get('source')!=batch['source']:
            raise ValueError('inconsistent batch provenance')
        decision=evaluate(stock,config)
        snapshot={'input':stock,'config':config,'result':decision,'execution':'DISABLED'}
        ledger.decision(snapshot)
        results.append(decision)
    counts={s:sum(r['signal']==s for r in results) for s in ('ENTRY','WATCH','EXCLUDED','BLOCKED')}
    summary={'session':batch['session'],'source':batch['source'],'coverage':batch.get('coverage','supplied_subset'),'scanned':len(results),'counts':counts,'orders_submitted':0,'execution':'DISABLED'}
    ledger.event('scan_complete',summary)
    ledger.db.close()
    return summary


def serve(db_path):
    token=os.environ.get('AGENT_TOKEN','')
    if len(token)<32:
        raise ValueError('AGENT_TOKEN must contain at least 32 characters')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def reply(self,data,status=200):
            payload=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def authenticated(self):
            return hmac.compare_digest(self.headers.get('Authorization',''),f'Bearer {token}')
        def do_GET(self):
            if not self.authenticated():
                return self.reply({'error':'unauthorized'},401)
            if self.path=='/api/status':
                return self.reply({'environment':'SIMULATE','trading_enabled':False,'phase':'preflight','blockers':['data_source','futu_login','exit_lifecycle','parameters','mail_delivery'],'version':load_config()['version']})
            table={'/api/decisions':'decisions','/api/orders':'orders'}.get(self.path)
            if not table:
                return self.reply({'error':'not_found'},404)
            ledger=Ledger(db_path)
            ledger.db.row_factory=__import__('sqlite3').Row
            rows=ledger.db.execute(f'SELECT * FROM {table} ORDER BY created DESC LIMIT 50').fetchall()
            ledger.db.close()
            return self.reply([dict(r) for r in rows])
        def do_POST(self):
            if not self.authenticated():
                return self.reply({'error':'unauthorized'},401)
            # Cloud endpoint does not execute file scans or trading until live ingestion is connected.
            return self.reply({'error':'live_ingestion_not_configured','trading_enabled':False},503)
    ThreadingHTTPServer(('127.0.0.1',8080),Handler).serve_forever()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['check','scan','serve','futu-check'])
    parser.add_argument('--input')
    parser.add_argument('--db',default=str(ROOT/'state'/'ledger.sqlite3'))
    args=parser.parse_args()
    Path(args.db).parent.mkdir(parents=True,exist_ok=True)
    if args.command=='check':
        print(json.dumps({'config_valid':bool(load_config()),'environment':'SIMULATE','execution_available':False,'phase':'preflight'}))
    elif args.command=='scan':
        if not args.input:
            parser.error('--input is required')
        print(json.dumps(scan(args.input,args.db),ensure_ascii=False))
    elif args.command=='serve':
        serve(args.db)
    else:
        from .futu_gateway import FutuGateway
        gateway=FutuGateway()
        try:
            print(json.dumps(gateway.status(),default=str,ensure_ascii=False))
        finally:
            gateway.close()


if __name__=='__main__':
    main()
