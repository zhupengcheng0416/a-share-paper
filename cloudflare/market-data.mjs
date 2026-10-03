const REPO='zhupengcheng0416/a-share-paper';
let jwksCache=null,tokenCache=null;
const decode=s=>Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0));
const parse=s=>JSON.parse(new TextDecoder().decode(decode(s)));
export async function githubAuthorized(jwt,now=Date.now()/1000){
  try {
    const parts=jwt.split('.');if(parts.length!==3)return false;
    const head=parse(parts[0]),c=parse(parts[1]);
    if(head.alg!=='RS256'||c.iss!=='https://token.actions.githubusercontent.com'||c.aud!=='a-share-market-data'
      ||c.repository!==REPO||c.ref!=='refs/heads/main'
      ||String(c.repository_id)!=='1403263803'||String(c.repository_owner_id)!=='336906782'
      ||(c.job_workflow_ref||c.workflow_ref)!==`${REPO}/.github/workflows/market.yml@refs/heads/main`
      ||!['push','schedule','workflow_dispatch'].includes(c.event_name)
      ||!Number.isFinite(c.exp)||!Number.isFinite(c.nbf)||c.exp<=now||c.nbf>now+30||c.exp-now>600)return false;
    if(!jwksCache||jwksCache.until<now){
      const r=await fetch('https://token.actions.githubusercontent.com/.well-known/jwks',{redirect:'manual',signal:AbortSignal.timeout(10000)});
      if(!r.ok)return false;jwksCache={keys:(await r.json()).keys,until:now+300};
    }
    const jwk=jwksCache.keys.find(k=>k.kid===head.kid);if(!jwk)return false;
    const key=await crypto.subtle.importKey('jwk',jwk,{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
    return await crypto.subtle.verify('RSASSA-PKCS1-v1_5',key,decode(parts[2]),new TextEncoder().encode(parts.slice(0,2).join('.')));
  }catch{return false;}
}
export function quoteRequest(input){
  const {operation}=input;
  const symbol=s=>{if(!/^(SH|SZ|BJ)\.\d{6}$/.test(s||''))throw Error('invalid_symbol');return s;};
  const date=d=>{if(!/^\d{4}-\d{2}-\d{2}$/.test(d||'')||!Number.isFinite(Date.parse(d)))throw Error('invalid_date');return d;};
  if(['snapshot','basic'].includes(operation)){
    if(!Array.isArray(input.codes)||input.codes.length<1||input.codes.length>400)throw Error('invalid_codes');
    return {path:operation==='snapshot'?'/api/v1.0/quote/snapshot':'/api/v1.0/quote/stock-basicinfo',method:'POST',body:{code_list:input.codes.map(symbol)}};
  }
  if(operation==='universe'){
    if(input.cursor&&!/^\d{1,8}$/.test(input.cursor))throw Error('invalid_cursor');
    return {path:'/api/v1.0/quote/stock-screen',method:'POST',body:{limit:300,screen_queries:[{simple_field_query:{simple_field:1,screen_value_list:[3]}}],retrieve_queries:[{simple_property:{name:2201}},{simple_property:{name:2301}},{simple_property:{name:2303}}],sort:{direction:2,simple_property:{name:2301}},...(input.cursor?{next_key:input.cursor}:{})}};
  }
  if(operation==='history'){
    const end=date(input.end),start=date(input.start);
    if(start>end||Date.parse(end)-Date.parse(start)>1100*86400000)throw Error('invalid_history_range');
    return {path:`/api/v1.0/quote/${symbol(input.code)}/history-kline?`+new URLSearchParams({start,end,ktype:'2',autype:'1',num:'370'}),method:'GET'};
  }
  if(operation==='sectors')return {path:`/api/v1.0/quote/${symbol(input.code)}/owner-plate`,method:'GET'};
  if(operation==='calendar')return {path:'/api/v1.0/quote/trading-days?'+new URLSearchParams({market:'SH',start:date(input.start),end:date(input.end)}),method:'GET'};
  throw Error('operation_not_allowed');
}
export async function relay(input,env,retried=false){
  const spec=quoteRequest(input),now=Date.now();
  if(!tokenCache||tokenCache.until<now){
    const r=await fetch('https://webapi.futunn.com/oauth2/token',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},
      body:new URLSearchParams({grant_type:'refresh_token',client_id:env.FUTU_CLIENT_ID,refresh_token:env.FUTU_REFRESH_TOKEN}),redirect:'manual',signal:AbortSignal.timeout(10000)});
    const token=await r.json();if(!r.ok||!token.access_token||!(token.scope||'').split(' ').includes('quote:read'))throw Error('quote_authorization_failed');
    tokenCache={token:token.access_token,until:now+Math.min(Number(token.expires_in)||300,300)*1000-30000};
  }
  const r=await fetch('https://webapi.futunn.com'+spec.path,{method:spec.method,headers:{authorization:`Bearer ${tokenCache.token}`,'content-type':'application/json'},
    ...(spec.body?{body:JSON.stringify(spec.body)}:{}),redirect:'manual',signal:AbortSignal.timeout(15000)});
  if(!r.ok)throw Error('quote_upstream_http_'+r.status);
  const data=await r.json();
  if(data.ret_code===-9&&!retried){tokenCache=null;return relay(input,env,true);}
  if(data.ret_code!==0)throw Error('quote_broker_code_'+data.ret_code+':'+String(data.ret_msg||'').slice(0,120));
  return {source:'Futu REST',source_url:'https://webapi.futunn.com/zh-cn/api/quote/overview',retrieved_at:new Date().toISOString(),operation:input.operation,...data};
}
