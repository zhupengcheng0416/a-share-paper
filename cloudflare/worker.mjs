import {githubAuthorized,relay} from './market-data.mjs';
const headers = {'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'};
const json = (body,status=200) => new Response(JSON.stringify(body),{status,headers});
export default {
  async fetch(request,env) {
    const path = new URL(request.url).pathname;
    if(path === '/health') return json({service:'a-share-paper',environment:'ANALYSIS_ONLY',phase:env.FUTU_REFRESH_TOKEN?'real_market_email_verified':'futu_rest_authorization_preflight',budget_cny:0,trading_enabled:false,broker_authorization_configured:!!env.FUTU_REFRESH_TOKEN,a_share_rest_account:'verified_via_cloudflare',cloud_connectivity:'verified',research_engines:3,cloud_research_runner:'github_actions_verified',live_market_data:true,full_market_technical_scan:false,exclude_beijing_exchange:true,scheduled_email:true});
    if(path === '/') return new Response(`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>沪深A股云端分析</title><style>body{font:16px system-ui;background:#f3f7fc;color:#18324e;margin:8vh auto;max-width:760px;padding:24px}article{background:white;padding:36px;border-radius:16px}h1{color:#1263b4}small{color:#557}</style><article><small>ANALYSIS ONLY · 零费用约束</small><h1>沪深A股云端分析</h1><p>Cloudflare 控制端已上线。</p><p>富途 REST 云端只读连接已验证，已读取到 A 股模拟账户。当前授权范围为 quote:read。</p><p>范围：沪深A股，排除北交所；总市值 ≤ 70亿元候选。科技股行业筛选尚待核实。</p><p>已整合三个项目的研究模块：V3支撑阻力、AlphaMaster因子计算、PA_Agent价格行为依据。GitHub云端Ubuntu运行器已验证：43项Python测试及23项接口检查通过。</p><p>已接通真实选股取值和历史日线：覆盖5,216只沪深A股，首批20只完成技术分析。9月30日报告已获163邮件服务器接受；未独立核实收件箱。工作日北京时间16:35定时运行，同一交易日不重复发送。不执行下单。</p><p>每只详细分析股票新增条件买点、止损参考和1R/2R止盈价；条件不足时仅观察。研究参数尚无收益验证；新增月度、季度方案反馈，首次报告因没有历史留档而标注样本不足。每月初反馈上月，每季度初反馈上季，同一周期不重复发送。</p><p>不自动升级套餐，不启用付费行情或付费服务器。免费额度不足时暂停运行。</p></article></html>`,{headers:{'content-type':'text/html; charset=utf-8','cache-control':'no-store','content-security-policy':"default-src 'none'; style-src 'unsafe-inline'",'x-content-type-options':'nosniff'}});
    if(path==='/api/market-data'){
      if(request.method!=='POST')return json({error:'method_not_allowed'},405);
      const auth=request.headers.get('authorization')||'';
      const control=!!env.CONTROL_TOKEN&&auth===`Bearer ${env.CONTROL_TOKEN}`;
      if(!control&&!await githubAuthorized(auth.replace(/^Bearer /,'')))return json({error:'unauthorized'},401);
      if(!env.FUTU_REFRESH_TOKEN)return json({error:'quote_authorization_missing'},503);
      if(Number(request.headers.get('content-length')||0)>20000)return json({error:'request_too_large'},413);
      try {const body=await request.text();if(body.length>20000)return json({error:'request_too_large'},413);return json(await relay(JSON.parse(body),env));}
      catch(e){return json({error:'market_data_failed',detail:/^(invalid_|operation_not_allowed|quote_)/.test(e.message)?e.message:'unavailable'},502);}
    }
    if(!env.CONTROL_TOKEN || request.headers.get('authorization') !== `Bearer ${env.CONTROL_TOKEN}`) return json({error:'unauthorized'},401);
    if(path === '/api/futu/preflight') {
      if(request.method !== 'GET') return json({error:'method_not_allowed'},405);
      if(!env.FUTU_CLIENT_ID || !env.FUTU_REFRESH_TOKEN) return json({error:'futu_authorization_missing'},503);
      let step='token_refresh';
      try {
        const tokenResponse=await fetch('https://webapi.futunn.com/oauth2/token',{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'refresh_token',client_id:env.FUTU_CLIENT_ID,refresh_token:env.FUTU_REFRESH_TOKEN}),redirect:'manual',signal:AbortSignal.timeout(10000)});
        const tokenText=await tokenResponse.text();
        let token;
        try {token=JSON.parse(tokenText);} catch {return json({error:'futu_refresh_non_json',upstream_status:tokenResponse.status},502);}
        if(!tokenResponse.ok || !token.access_token) return json({error:'futu_refresh_failed'},502);
        if((token.scope||'').split(' ').includes('trade:write')) return json({error:'unexpected_trade_write_scope'},503);
        step='simulation_accounts';
        const response=await fetch('https://webapi.futunn.com/api/v1.0/sim-trade/accounts',{headers:{authorization:`Bearer ${token.access_token}`},redirect:'manual',signal:AbortSignal.timeout(10000)});
        const accountText=await response.text();
        let data;
        try {data=JSON.parse(accountText);} catch {return json({error:'futu_accounts_non_json',upstream_status:response.status},502);}
        if(!response.ok || data.ret_code!==0 || !Array.isArray(data.data?.accounts)) return json({error:'simulation_accounts_failed',broker_code:data.ret_code??null},502);
        const accounts=data.data.accounts.map(a=>({market_id:a.market_id,account_title:a.account_title}));
        return json({environment:'SIMULATE',source:'Futu REST via Cloudflare',scope:token.scope||'not_returned',accounts,a_share_account_present:accounts.some(a=>a.account_title==='A股模拟账户'),trading_enabled:false,orders_submitted:0});
      } catch(e) { return json({error:'futu_preflight_failed',step,error_type:e?.name||'unknown',diagnostic:String(e?.message||'').includes('timeout')?'timeout_api_or_network':String(e?.message||'').includes('fetch')?'fetch_error':'other'},502); }
    }
    if(!['/api/status','/api/decisions','/api/orders','/api/scan'].includes(path)) return json({error:'not_found'},404);
    const post=path==='/api/scan';
    if(request.method !== (post?'POST':'GET')) return json({error:'method_not_allowed'},405);
    if(!env.AGENT_URL || !env.AGENT_TOKEN) return json({error:'agent_not_configured',trading_enabled:false},503);
    if(!env.AGENT_URL.startsWith('https://')) return json({error:'agent_requires_https'},503);
    try {
      const r = await fetch(new URL(path,env.AGENT_URL),{method:post?'POST':'GET',headers:{authorization:`Bearer ${env.AGENT_TOKEN}`},redirect:'manual',signal:AbortSignal.timeout(15000)});
      if(r.status>=300 && r.status<400) return json({error:'agent_redirect_rejected'},502);
      return new Response(r.body,{status:r.status,headers});
    } catch { return json({error:'agent_unreachable',trading_enabled:false},503); }
  }
};
