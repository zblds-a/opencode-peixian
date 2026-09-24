"""Owned task grouping and immutable source links, not another executor."""
import copy
import json
import os
import re

from .backend_contract import error,iso
from .store import ident,now
from . import business_runs,trusted_results
from shared import theft_provider_v2 as adapter

LIMIT_KEYS={'max_user_requests','max_planning_calls','max_rounds_per_task','max_data_calls','max_steps','max_locations'}


def limits():
    try:
        value=json.loads(os.getenv('PX_THEFT_TASK_LIMITS','{}'))
        if not isinstance(value,dict) or set(value)!=LIMIT_KEYS:raise ValueError()
        if any(type(v) is not int or not 1<=v<=1000 for v in value.values()) or value['max_user_requests']>40:raise ValueError()
        return value
    except (ValueError,TypeError):error('task_limits_unconfigured','任务预算尚未配置。',409)


def require(store):
    if store.schema_version()<11:error('analysis_tasks_unavailable','当前部署尚未启用任务关联。',409)


def owned(store,uid,sid,tid):
    require(store)
    if not isinstance(tid,str) or not 1<=len(tid)<=100:error('analysis_task_not_found','任务不存在。',404)
    row=store.one('SELECT * FROM analysis_tasks WHERE id=? AND uid=? AND session_id=?',(tid,uid,sid))
    if not row:error('analysis_task_not_found','任务不存在。',404)
    return row


def create(store,user,sid,data):
    from .app import current_authority
    require(store)
    if not isinstance(data,dict) or set(data)!={'goal','client_request_id','data_environment'} or not isinstance(data['goal'],str) or not 1<=len(data['goal'].strip())<=4000 or data['data_environment'] not in ('synthetic','acceptance_real'):
        error('invalid_task','请提供任务目标、环境和请求标识。',422)
    key=business_runs.normalized({'client_request_id':data['client_request_id']})['client_request_id']
    digest=business_runs.fingerprint(store,data);budget=limits()
    with store.tx() as db:
        current_authority(db,user)
        prior=db.execute('SELECT * FROM analysis_tasks WHERE uid=? AND session_id=? AND request_key=?',(user['uid'],sid,key)).fetchone()
        if prior:
            if prior['request_hash']!=digest:error('request_conflict','同一标识的任务目标不同。',409)
            return view(store,user['uid'],sid,prior['id'])
        from .scenario_context import current
        identity=ident();stamp=now()
        payload={'goal':data['goal'].strip(),'limits':budget,'generation':current(store,user['uid'],sid)['generation'],'user_requests':{},'planning_calls':[],'selected_refs':[]}
        db.execute('INSERT INTO analysis_tasks VALUES(?,?,?,?,?,?,1,1,?,?,?)',(identity,user['uid'],sid,key,digest,data['data_environment'],store.encrypt(payload),stamp,stamp))
        return view(store,user['uid'],sid,identity)


def view(store,uid,sid,tid):
    row=owned(store,uid,sid,tid);payload=store.decrypt(row['payload_ciphertext'])
    steps=[];dispatches=0;responses=0
    for entry in store.rows('SELECT s.*,r.status,r.phase,r.request_ciphertext FROM analysis_task_steps s JOIN business_runs r ON r.id=s.run_id WHERE s.task_id=? ORDER BY s.sequence',(tid,)):
        frozen=store.decrypt(entry['request_ciphertext'])
        for value in frozen.get('provider_state',{}).get('modules',{}).values():
            dispatches+=value.get('dispatch_attempts',0);responses+=value.get('response_count',0)
        steps.append({'step_id':entry['id'],'run_id':entry['run_id'],'sequence':entry['sequence'],'status':entry['status'],'phase':entry['phase'],**store.decrypt(entry['payload_ciphertext'])})
    goal=adapter.public_result(payload['goal'],store.worker_key.encode(),uid+'/'+sid)
    return {'analysis_task_id':tid,'scenario_id':tid,'session_id':sid,'goal':goal,'data_environment':row['environment'],'context_version':row['context_version'],'scope_version':row['scope_version'],'steps':steps,'selected_refs':payload['selected_refs'],'planning':[{'id':c['id'],'status':c['state'],'action':c.get('decision',{}).get('action'),'error_code':c.get('error_code') or c.get('continuation_code'),'run_id':c.get('receipt',{}).get('run_id')} for c in payload['planning_calls']],'budget':{'limits':payload['limits'],'user_requests':len(payload['user_requests']),'planning_calls':len(payload['planning_calls']),'planning_rounds':len(payload['planning_calls']),'data_steps':sum(x.get('query_mode')=='new_query' for x in steps),'data_dispatch_attempts':dispatches,'data_responses':responses},'updated_at':iso(row['updated'])}


def source(store,uid,sid,reference,environment):
    if not isinstance(reference,dict) or set(reference)!={'run_id','result_digest','record_id','snapshot_id'}:
        error('source_reference_invalid','请明确选择来源执行及条目。',422)
    if any(not isinstance(v,str) or not 1<=len(v)<=300 for v in reference.values()):error('source_reference_invalid','来源引用字段无效。',422)
    from .live_sources import PREFIX, resolve
    if reference['result_digest'].startswith(PREFIX):
        return resolve(store,uid,sid,reference,environment)
    run=business_runs.owned(store,uid,sid,reference['run_id'])
    result=trusted_results.read(store,uid,sid,run['id'])
    if result.get('data_environment')!=environment or trusted_results.digest(result)!=reference['result_digest']:
        error('source_version_changed','来源环境或结果摘要不匹配。',409)
    records=[x for x in result.get('records',[]) if x['record_id']==reference['record_id'] and x.get('snapshot_id')==reference['snapshot_id']]
    if len(records)!=1:error('source_record_unavailable','选定来源记录不存在或不属于该快照。',409)
    if result.get('agent',{}).get('id')!='theft-assistant':error('source_agent_mismatch','来源不属于盗窃助手。',409)
    return records[0],store.decrypt(run['request_ciphertext'])


def validate_context(store,uid,sid,metadata):
    row=owned(store,uid,sid,metadata['analysis_task_id']);payload=store.decrypt(row['payload_ciphertext'])
    from .scenario_context import current
    if (row['context_version']!=metadata['context_version'] or row['scope_version']!=metadata['scope_version'] or payload['generation']!=current(store,uid,sid)['generation']):
        error('analysis_context_changed','任务范围或选择已更新，请重新读取任务。',409)
    for reference in metadata['source_refs']:source(store,uid,sid,reference,row['environment'])
    return row,payload


def freeze_step(store,uid,sid,tid,version,*,request_key,source_refs=(),direction='single_query',parent=None):
    if not isinstance(request_key,str):error('step_request_required','步骤必须提供稳定的请求标识。',422)
    if direction not in ('single_query','case_to_person','person_to_case'):error('invalid_analysis_direction','分析方向无效。',422)
    row=owned(store,uid,sid,tid)
    if type(version) is not int or version!=row['context_version']:error('analysis_context_changed','任务版本已变化。',409)
    budget=store.decrypt(row['payload_ciphertext'])['limits']
    if not isinstance(source_refs,(list,tuple)) or len(source_refs)>budget['max_locations']:error('source_selection_limit','来源选择数量超过任务限额。',422)
    if len({adapter.digest(x) for x in source_refs})!=len(source_refs):error('source_selection_duplicate','不能重复选择同一来源。',422)
    if parent:
        if not isinstance(parent,str):error('invalid_parent','父执行引用无效。',422)
        business_runs.owned(store,uid,sid,parent)
        if not store.one('SELECT 1 FROM analysis_task_steps WHERE task_id=? AND run_id=?',(tid,parent)):error('parent_task_mismatch','父执行不属于当前任务。',409)
    metadata={'analysis_task_id':tid,'context_version':version,'scope_version':row['scope_version'],'step_request_id':business_runs.normalized({'client_request_id':request_key})['client_request_id'],'source_refs':copy.deepcopy(list(source_refs)),'selected_refs':copy.deepcopy(list(source_refs)),'analysis_direction':direction,'direct_parent_run_id':parent}
    validate_context(store,uid,sid,metadata)
    return metadata


def derive(store,uid,sid,metadata,kind,query):
    """Coordinates and identities are selected from saved sources, not caller copies."""
    row,_=validate_context(store,uid,sid,metadata)
    if len(metadata['source_refs'])!=1:error('explicit_source_required','本查询步骤必须选择一个明确来源；多个位置按步骤串行。',422)
    reference=metadata['source_refs'][0]
    record,snapshot=source(store,uid,sid,reference,row['environment'])
    plan=snapshot.get('provider_plan',{})
    if plan.get('version')!=adapter.VERSION:error('source_contract_unsupported','该历史来源不能用于真实接口衔接。',409)
    entry=snapshot.get('provider_state',{}).get('modules',{}).get(plan['kind'],{})
    raw=entry.get('response',{})
    raw_records=[r for r in raw.get('records',[]) if reference['record_id']==reference['run_id']+':'+r['source_ref'] and raw.get('response_snapshot_id')==reference['snapshot_id']]
    if len(raw_records)!=1:error('source_record_unavailable','原始来源快照无法核对。',409)
    fields=raw_records[0]['fields']
    projected=adapter.public_result(fields,store.worker_key.encode(),uid+'/'+sid)
    if projected!=record['fields']:error('source_integrity_failed','来源投影与原始记录不一致。',409)
    q=copy.deepcopy(query);identities={};used=[]
    if kind in ('incidents','captures'):
        if set(q)&{'lon','lat','person_ref'}:error('source_value_override','选定来源后不能替换坐标或对象。',422)
        origin=record['module'];names=('gisX','gisY') if origin=='incidents' else ('lon','lat') if origin=='tracks' else None
        if not names:error('source_coordinates_missing','此来源没有受支持的坐标字段。',409)
        from .provider_contracts import settings
        compatibility=settings(uid).get('coordinate_compatibility',{})
        key=adapter.CATALOG[origin][3]+':'+adapter.CATALOG[kind][3]
        if compatibility.get(key) is not True:error('coordinate_contract_unconfirmed','来源与目标接口坐标兼容性尚未确认。',409)
        if any(fields.get(n) is None for n in names):error('source_coordinates_missing','来源未提供完整坐标。',409)
        q.update(lon=str(fields[names[0]]),lat=str(fields[names[1]]));used=list(names)
    elif kind in adapter.PERSON:
        if 'person_ref' in q:error('source_value_override','人员引用只能从选定来源读取。',422)
        names=[n for n in ('target_id_card','targetIdCard','idCard') if n in fields]
        if len(names)!=1:error('source_identity_missing','此条来源不能唯一确定人员。',409)
        identity=adapter.person_id(fields[names[0]]);ref=adapter.person_ref(identity,store.worker_key.encode(),uid+'/'+sid)
        q['person_ref']=ref;identities[ref]=identity;used=names
    else:error('provider_contract_unconfirmed','此接口尚未开放。',409)
    return q,identities,used


def attach(store,db,user,sid,rid,metadata,plan,request):
    """Called inside the same transaction as Run and delivery insertion."""
    row,payload=validate_context(store,user['uid'],sid,metadata)
    if metadata['step_request_id']!=request['client_request_id']:error('step_request_mismatch','步骤请求标识不一致。',409)
    if row['environment']!=plan.get('data_environment','synthetic'):error('task_environment_mismatch','任务环境不能在步骤中切换。',409)
    budget=payload['limits'];count=db.execute('SELECT count(*) FROM analysis_task_steps WHERE task_id=?',(row['id'],)).fetchone()[0]
    if count>=budget['max_steps'] or count>=budget['max_data_calls']:error('task_budget_exhausted','本任务查询预算已用完，保留已有结果。',429)
    key=request['client_request_id'];fingerprint=business_runs.fingerprint(store,request)
    planning=next((c for c in payload['planning_calls'] if c['request_key']==key),None)
    budget_key=planning.get('root_request_key',key) if planning else key
    if budget_key not in payload['user_requests'] and len(payload['user_requests'])>=budget['max_user_requests']:error('task_budget_exhausted','本任务请求预算已用完。',429)
    payload['user_requests'].setdefault(budget_key,fingerprint);payload['selected_refs']=metadata['selected_refs']
    links={**copy.deepcopy(metadata),'query_mode':'new_query','normalized_query':plan['query'],'input_origin':'selected_source' if metadata['source_refs'] else 'user_confirmed','source_data_run_id':metadata['source_refs'][0]['run_id'] if len(metadata['source_refs'])==1 else None,'provider_contract':plan['version'],'plugin_version':plan['plugin_version'],'connection_revision':plan.get('connection_revision')}
    db.execute('INSERT INTO analysis_task_steps VALUES(?,?,?,?,?,?,?,?)',(ident(),row['id'],rid,key,fingerprint,count+1,store.encrypt(links),now()))
    updated=db.execute('UPDATE analysis_tasks SET payload_ciphertext=?,context_version=context_version+1,updated=? WHERE id=? AND context_version=?',(store.encrypt(payload),now(),row['id'],metadata['context_version']))
    if updated.rowcount!=1:error('analysis_context_changed','任务已被另一请求更新。',409)


def check_execution(store,uid,sid,rid,metadata):
    row=owned(store,uid,sid,metadata['analysis_task_id'])
    from .scenario_context import current
    payload=store.decrypt(row['payload_ciphertext'])
    if (row['context_version']!=metadata['context_version']+1 or row['scope_version']!=metadata['scope_version'] or payload['generation']!=current(store,uid,sid)['generation']):
        error('analysis_context_changed','查询对应的任务选择或范围已变化。',409)
    if not store.one('SELECT 1 FROM analysis_task_steps WHERE task_id=? AND run_id=?',(row['id'],rid)):error('task_run_mismatch','执行未绑定当前任务。',409)
    for reference in metadata['source_refs']:source(store,uid,sid,reference,row['environment'])


def register(app):
    from fastapi import Depends,Request
    from .app import PREFIX,normal,session_owned
    from .concurrency import blocking_endpoint
    @app.post(PREFIX+'/sessions/{sid}/scenarios',status_code=201)
    async def create_task(sid:str,request:Request,user=Depends(normal)):
        await session_owned(request,user,sid)
        body=await request.json()
        return await app.state.db_work.run(create,app.state.store,user,sid,body)
    @app.get(PREFIX+'/sessions/{sid}/scenarios/{scenario_id}')
    @blocking_endpoint(app)
    def get_task(sid:str,scenario_id:str,request:Request,user=Depends(normal)):
        return view(app.state.store,user['uid'],sid,scenario_id)
