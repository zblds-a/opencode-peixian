"""Server-confirmed provider plans. All requests remain synthetic-only."""
import copy,hashlib,hmac,json,os,time
from .backend_contract import error
from .scenario_context import current
from shared.theft_provider import CATALOG,VERSION,normalize_query,request_spec,canonical,ContractError

def pid(kind):return 'peixian-theft-'+kind.replace('_','-')
def tool(kind):return 'peixian_query_'+kind

def enabled(uid):return uid in {x for x in os.getenv('PX_THEFT_PROVIDER_UIDS','').split(',') if x}
def availability(store,uid,kind,applied):
    from .capabilities import check_selection
    if not enabled(uid):error('provider_not_enabled','当前账号尚未开通新资料查询。',403)
    from .data_plugin_policy import ACTIVE_KINDS
    if not isinstance(kind,str) or kind not in ACTIVE_KINDS or kind not in CATALOG:error('provider_method_unknown','资料查询类型无效。',422)
    check_selection(store,uid,{'skill_ids':[],'plugin_ids':[pid(kind)]})
    matches=[p for p in applied.get('plugins',[]) if p['id']==pid(kind)]
    if len(matches)!=1 or matches[0].get('version')!='1.0.0' or matches[0].get('manifest',{}).get('tools')!=[tool(kind)]:error('provider_not_applied','此资料插件尚未生效。',409)
    return matches[0]
def signature(store,uid,sid,body):
    return hmac.new(store.worker_key.encode(),canonical([uid,sid,body]).encode(),hashlib.sha256).hexdigest()
def preview(store,uid,sid,body,applied,revision):
    from shared.theft_provider_v2 import VERSION as V2
    if isinstance(body,dict) and body.get('contract_version')==V2:
        from .provider_real_flow import preview as real_preview
        return real_preview(store,uid,sid,body,applied,revision)
    if not isinstance(body,dict) or set(body)!={'kind','query'}:error('provider_query_invalid','查询字段无效。',422)
    kind=body['kind'];availability(store,uid,kind,applied)
    try:q=normalize_query(kind,body['query'])
    except ContractError as exc:error(str(exc),'请补充或修正资料类型、合成对象、时间和范围。',422)
    value={'version':VERSION,'kind':kind,'query':q,'revision':revision,'generation':current(store,uid,sid)['generation'],'expires':int(time.time())+600}
    return {'plan':value,'confirmation':signature(store,uid,sid,value),'summary':CATALOG[kind][0]+'；仅执行已确认的合成范围；当前页 '+str(q['page'])+'，每页 '+str(q['page_size'])+' 条。'}
def resolve(store,uid,sid,data,applied):
    from .agents.runtime import select,session
    value=data.get('provider_query')
    if not enabled(uid) or store.schema_version()<9:
        if value is not None:error('provider_not_enabled','当前账号尚未开通新资料查询。',403)
        return None
    if value is None:return followup(store,uid,sid,data)
    if data.get('agent_id')!='theft-assistant':error('provider_agent_mismatch','请在盗窃助手会话中查询。',409)
    if not isinstance(value,dict) or set(value)!={'plan','confirmation'}:error('provider_confirmation_required','请先确认查询范围。',422)
    plan=value['plan']
    if not isinstance(plan,dict) or not isinstance(value['confirmation'],str) or not hmac.compare_digest(signature(store,uid,sid,plan),value['confirmation']):error('provider_confirmation_invalid','范围确认已失效，请重新确认。',409)
    from shared.theft_provider_v2 import VERSION as V2
    if plan.get('version')==V2:
        from .provider_real_flow import resolve as real_resolve
        return real_resolve(store,uid,sid,data,applied,plan)
    runtime=store.one('SELECT revision FROM runtimes WHERE uid=?',(uid,))
    if plan.get('version')!=VERSION or plan['expires']<int(time.time()) or not runtime or plan['revision']!=runtime['revision'] or plan['generation']!=current(store,uid,sid)['generation']:error('provider_confirmation_expired','查询确认已过期或配置已变化，请重新确认。',409)
    kind=plan['kind'];plugin=availability(store,uid,kind,applied);profile=select(uid,data);session(store,uid,sid,profile)
    context=current(store,uid,sid);context.update(scenario_id='DEMO-CASE-THEFT',effective_skill_ids=[])
    spec={'schema_version':'task-spec-v4','router_version':VERSION,'domain':'theft','query_mode':'new_query','intent':'provider_'+kind,'scenario_id':'DEMO-CASE-THEFT','target_refs':[plan['query'].get('subject') or plan['query'].get('center') or plan['query'].get('address','来源预警范围')],'target_mode':'provider_query','methods':[kind],'official_skill_ids':[],'output_types':['summary','evidence'],'direct_parent_run_id':None,'source_data_run_id':None,'context_generation':context['generation'],'agent_id':profile.id,'agent_version':profile.data['version'],'agent_profile_sha256':profile.profile_sha256}
    frozen={**copy.deepcopy(plan),'plugin_id':plugin['id'],'plugin_version':plugin['version'],'tool_id':tool(kind),'request':request_spec(kind,plan['query'])}
    return {'agent_profile':profile.snapshot(),'candidate':{'router_version':VERSION},'spec':spec,'context':context,'target':None,'local':None,'provider_plan':frozen}
def bind(snapshot,payload,task):
    from .facts_plan import HELPERS
    blocked={**payload.get('tools',{}),'*':False,'question':False,**{name:False for name in HELPERS},**{name:False for p in snapshot['plugins'] for name in p.get('tools',[])}}
    plan=task['provider_plan'];snapshot['provider_plan']=copy.deepcopy(plan)
    if task.get('analysis_task'):snapshot['analysis_task']=copy.deepcopy(task['analysis_task'])
    snapshot['task_spec']=copy.deepcopy(task['spec']);snapshot['allowed_capabilities']=[plan['plugin_id']];snapshot['allowed_tools']=[plan['tool_id']]
    snapshot['trusted_result_version']='2.0';snapshot['data_environment']=plan.get('data_environment','synthetic')
    if snapshot['data_environment']=='acceptance_real':
        import re
        # The encrypted ticket retains the supplier identity; model-facing
        # content gets no full identity or serialized private query plan.
        for part in payload.get('parts',[]):
            if part.get('type')=='text':part['text']=re.sub(r'(?<!\d)\d{17}[\dXx](?!\d)','[本轮已确认人员]',part.get('text',''))
    if task.get('local'):
        snapshot['task_response']=task['local'];snapshot['provider_followup']=task['provider_followup']
        if task.get('provider_history'):snapshot['provider_history']=copy.deepcopy(task['provider_history'])
        snapshot['allowed_tools']=[];snapshot['allowed_capabilities']=[]
        payload['tools']=blocked
        return
    payload['tools']={**blocked,plan['tool_id']:True}
    payload['system']=payload.get('system','')+'\n本轮已由用户确认范围，请仅调用一次 '+plan['tool_id']+'，参数为 {}。平台会注入确认后的查询条件。不得改换对象、自动翻页或补查其他资料；失败或未知不得重试。最终说明由代码根据来源生成简体中文。'

def register(app):
    from fastapi import Request,Depends
    from .app import PREFIX,normal,session_owned
    @app.post(PREFIX+'/sessions/{sid}/provider-query/preview')
    async def confirm(sid:str,request:Request,user=Depends(normal)):
        await session_owned(request,user,sid)
        body=await request.json()
        def prepare():
            s=app.state.store
            row=s.one('SELECT revision,applied_spec_ciphertext FROM runtimes WHERE uid=?',(user['uid'],))
            applied=s.decrypt(row['applied_spec_ciphertext']) if row and row['applied_spec_ciphertext'] else {}
            return preview(s,user['uid'],sid,body,applied,row['revision'] if row else 0)
        return await app.state.db_work.run(prepare)
    @app.get(PREFIX+'/theft-provider/capabilities')
    async def capabilities(user=Depends(normal)):
        def read():
            s=app.state.store;row=s.one('SELECT applied_spec_ciphertext FROM runtimes WHERE uid=?',(user['uid'],));applied=s.decrypt(row['applied_spec_ciphertext']) if row and row['applied_spec_ciphertext'] else {}
            from fastapi import HTTPException
            from shared import theft_provider_v2 as v2
            from .provider_contracts import binding
            items=[]
            from .data_plugin_policy import ACTIVE_KINDS
            for kind in ACTIVE_KINDS:
                definition=v2.CATALOG[kind]
                real=any(p['id']==pid(kind) and p.get('version')=='2.0.0' for p in applied.get('plugins',[]))
                reason=None
                try:
                    if real:binding(s,user['uid'],kind,applied)
                    else:availability(s,user['uid'],kind,applied)
                    available=True
                except HTTPException as exc:
                    available=False;reason=exc.detail.get('code','provider_unavailable') if isinstance(exc.detail,dict) else 'provider_unavailable'
                items.append({'kind':kind,'name':definition[0],'plugin_id':pid(kind),'available':available,'reason':reason,'data_environment':'acceptance_real' if real else 'synthetic','contract_version':v2.VERSION if real else VERSION})
            return {'items':items,'data_environment':'synthetic','contract_version':VERSION,'contract_versions':[VERSION,v2.VERSION]}
        return await app.state.db_work.run(read)


def followup(store,uid,sid,data):
    from .scenario_context import boundary
    from .agents import runtime
    from .trusted_results import read
    _,after=boundary(store,uid,sid)
    row=store.one('SELECT rowid,* FROM business_runs WHERE uid=? AND session_id=? AND rowid>? ORDER BY rowid DESC LIMIT 1',(uid,sid,after))
    if not row:return None
    snap=store.decrypt(row['request_ciphertext'])
    if not snap.get('provider_plan'):return None
    profile=runtime.select(uid,data);runtime.session(store,uid,sid,profile)
    text=data['text'].strip().rstrip('。！!？?')
    explain=text in ('继续','解释已有结果','展开依据','解释刚才的结果','查看已有资料','说明资料缺口')
    source=read(store,uid,sid,row['id']) if row['status'] in ('completed','failed','cancelled') else None
    # The latest execution is the explicit default target even when it is empty,
    # failed or only a clarification. Never silently substitute an older success.
    historical=bool(source is not None and explain)
    context=current(store,uid,sid);context.update(scenario_id='DEMO-CASE-THEFT',effective_skill_ids=[])
    spec=copy.deepcopy(snap['task_spec']);spec.update(query_mode='explain_existing' if historical else 'clarify',direct_parent_run_id=row['id'],source_data_run_id=(source.get('data_usage',{}).get('source_data_run_id') or source['run_id']) if historical else None,context_generation=context['generation'])
    msg='继续说明已有来源，没有重新取数。' if historical else '仍在盗窃资料核对会话中。请点击“盗窃资料查询”，选择对象或位置并确认时间范围；如只解释已有资料，可说“解释已有结果”。本轮尚未发起新查询。'
    return {'agent_profile':profile.snapshot(),'candidate':{'router_version':VERSION},'spec':spec,'context':context,'target':None,'local':{'code':'provider_history' if historical else 'provider_scope_required','message':msg},'provider_plan':copy.deepcopy(snap['provider_plan']),'provider_history':source if historical else None,'provider_followup':True}
