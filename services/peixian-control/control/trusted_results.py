"""Versioned code-owned claims; immutable terminal results, no upstream I/O."""
import copy
import hashlib
import json
import os
from datetime import datetime,timezone,timedelta
from .backend_contract import error,iso
from . import business_runs
from .trusted_narrative import review

VERSION='2.0'
LABELS={'funds':'资金流水','night':'夜间观测','portrait':'同框与同行','vehicle':'车辆记录','lookup':'明确关系','composite':'已有关系引用','calls':'通话记录'}
FIELDS=('record_id','source_type','group_ref','member_ref','co_member_ref','occurred_at','kind','direction','amount_minor','counterparty_ref','transaction_ref','device_ref','source_record_ids')


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def enabled(store,uid):
    return store.schema_version()>=9 and uid in {s.strip() for s in os.getenv('PX_TRUSTED_RESULT_V2_UIDS','').split(',') if s.strip()}


def local(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('time_zone_required')
    return parsed.astimezone(timezone(timedelta(hours=8)))


def inputs(snapshot):
    plan=snapshot.get('facts_plan');state=snapshot.get('facts_state') or {}
    if not plan:return {},[],[]
    from shared.developer_plan import validate
    from .agents.runtime import validate_execution
    from fastapi import HTTPException
    try: validate_execution(snapshot)
    except HTTPException as exc: raise ValueError('frozen_task_mismatch') from exc
    validate(plan)
    if snapshot.get('registry_snapshot')!=plan.get('registry'):raise ValueError('registry_snapshot_mismatch')
    identity=snapshot.get('agent_profile') or {}
    if identity!=plan.get('agent_profile') or plan.get('registry',{}).get('agent_id')!=identity.get('id'):raise ValueError('agent_mismatch')
    scene=plan['scenario'];valid={};records=[];invalid=[]
    for module,part in state.get('modules',{}).items():
        if module not in plan['modules']:raise ValueError('unplanned_module')
        if part.get('status')!='completed':continue
        raw=part.get('response') or {};expected=plan['records'][module]
        fields=('module','synthetic','snapshot_id','data_status','returned_count','total_count','has_more','rule_version','rule_status')
        if raw.get('synthetic') is not True or raw.get('items')!=expected.get('records') or any(raw.get(k)!=expected.get(k) for k in fields):invalid.append(module);continue
        selected=[]
        for original in raw['items']:
            subject=scene['subject_ref'];filtering=scene.get('target_filter')
            belongs=original.get('group_ref')==subject if filtering or module in ('night','lookup') else subject in (original.get('member_ref'),original.get('co_member_ref')) if module=='portrait' else original.get('member_ref')==subject
            if not belongs:continue
            if original.get('occurred_at') and not local(scene['window_start'])<=local(original['occurred_at'])<local(scene['window_end']):continue
            selected.append(original)
            record={k:copy.deepcopy(original[k]) for k in FIELDS if k in original}
            record.update(module=module,snapshot_id=raw['snapshot_id'],data_source_id='synthetic.'+module,subject_ref=subject)
            records.append(record)
        if len({v['record_id'] for v in selected})!=len(selected):raise ValueError('duplicate_source_id')
        valid[module]=selected
    return valid,records,invalid


def confirmed_inputs(snapshot,events):
    valid,records,invalid=inputs(snapshot)
    completed={e.get('capability_id','').removeprefix('peixian-records-') for e in events
        if e.get('event_key','').startswith('facts.') and e.get('step_type')=='plugin'
        and e.get('started') is not None and e.get('status')=='completed' and e.get('completed') is not None}
    unsupported=set(valid)-completed
    invalid=sorted(set(invalid)|unsupported)
    return {k:v for k,v in valid.items() if k not in unsupported},[r for r in records if r['module'] not in unsupported],invalid


def usage(row,snapshot,events,valid=None,invalid=None):
    state=snapshot.get('facts_state') or {};parts=state.get('modules') or {};plan=snapshot.get('facts_plan') or {}
    source=(snapshot.get('task_spec') or {}).get('source_data_run_id')
    reserved={e['capability_id'].removeprefix('peixian-records-') for e in events if e['event_key'].startswith('facts.') and e['step_type']=='plugin' and e.get('started') is not None and e.get('capability_id')}
    denied=any(e['step_type']=='authorization' and e['status']=='rejected' for e in events)
    known=set(valid or {});bad=set(invalid or []);modules=[]
    for module in plan.get('modules',[]):
        part=parts.get(module,{});status=part.get('status','not_started')
        if module in bad:status='rejected'
        if status=='pending' and row['status'] in business_runs.TERMINAL:status='unknown'
        modules.append({'module':module,'status':status,'reserved':module in reserved,'response_confirmed':module in known})
    statuses={m['status'] for m in modules}
    if source and snapshot.get('historical_projection') and not reserved:status='historical_evidence'
    elif denied or row.get('phase')=='rejected':status='rejected'
    elif row['status']=='cancelled':status='cancelled'
    elif known and (len(known)!=len(plan.get('modules',[])) or not state.get('table')):status='partial'
    elif bad or 'rejected' in statuses:status='rejected'
    elif 'unknown' in statuses or (reserved and row['status']=='reconciling'):status='unknown'
    elif 'pending' in statuses:status='in_flight'
    elif known and state.get('table'):status='reused_current_run' if state.get('reuse_count',0)>0 else 'confirmed'
    elif reserved:status='unknown'
    else:status='not_started'
    return {'status':status,'queried':True if known else None if reserved else False,'attempted':bool(reserved),'may_have_sent':bool(reserved),'new_call_count':len(reserved),'reuse_count':state.get('reuse_count',0),'source_data_run_id':source,'modules':modules,'basis':'durable_plugin_reservations_and_validated_responses'}


def claim(row,identity,kind,template,statement,fields,sources,rule=None):
    value={'schema':'peixian.claim','version':'1.0','type':kind,'template_id':template,'agent_id':identity['id'],'subject_refs':fields.get('subject_refs',[]),'statement':statement,'protected_fields':fields,'source_ids':sorted(set(sources)),'rule':rule,'verification_status':'approved','source_run_id':row['id']}
    return {'claim_id':'clm_'+digest(value)[:24],**value}


def build(row,snapshot,events):
    identity=snapshot.get('agent_profile') or {};task=snapshot.get('task_spec') or {};plan=snapshot.get('facts_plan') or {};state=snapshot.get('facts_state') or {};claims=[];missing=[];records=[];valid={};invalid=[]
    if not identity.get('id'):raise ValueError('result_agent_missing')
    try:valid,records,invalid=confirmed_inputs(snapshot,events)
    except (ValueError,KeyError,TypeError,IndexError):invalid=list(plan.get('modules',[]));missing.append('本轮来源或冻结执行身份无法核对，未采用相关资料。')
    use=usage(row,snapshot,events,valid,invalid)
    if invalid:missing.append('部分资料未通过当前Run来源、对象或快照核对。')
    scene=plan.get('scenario',{});table=state.get('table') or {};checked=state.get('checked') or {}
    source_ids={r['record_id'] for r in records}
    table_ok=bool(table) and all(table.get(k)==scene.get(v) for k,v in [('scenario_id','scenario_id'),('scenario_snapshot_id','snapshot_id'),('records_snapshot_id','records_snapshot_id')]) and table.get('rule_version')==plan.get('facts_rule_version')
    if table and not table_ok:missing.append('事实表版本无法与冻结资料匹配。');use['status']='rejected'
    bindings=[b for b in scene.get('rule_bindings',[]) if b['module'] in valid]
    if table_ok and table.get('rule_executions')!=bindings:table_ok=False;missing.append('确定性规则执行记录无法核对。');use['status']='rejected'
    approved={f['fact_id']:f for f in checked.get('approved',[]) if f in table.get('facts',[]) and isinstance(f,dict)}
    checked_ok=all(checked.get(k)==table.get(k) for k in ('scenario_id','scenario_snapshot_id','records_snapshot_id'))
    if not checked_ok:approved={}
    from .record_checks import verify
    proof=state.get('record_checked')
    if proof is not None and proof==verify(snapshot,events):
        approved.update({f['fact_id']:f for f in proof['approved']})
        if proof['rejected']:missing.append('部分车辆记录未通过逐条来源核对，请查看已有记录及缺失字段。')
    if table_ok:
        subject=scene['subject_ref']
        for module,rows in valid.items():
            binding=next((b for b in bindings if b['module']==module),None)
            if not binding:continue
            rule={'id':binding['rule_id'],'version':binding['version']}
            dates=sorted({local(r['occurred_at']).date().isoformat() for r in rows if r.get('occurred_at')})
            nights=sum(1 for r in rows if r.get('occurred_at') and (local(r['occurred_at']).hour>=22 or local(r['occurred_at']).hour<6))
            summary=next((x for x in table.get('summary',[]) if x.get('module')==module),{})
            if (summary.get('count'),summary.get('dates'),summary.get('night_count'))!=(len(rows),dates,nights):missing.append(LABELS[module]+'计算结果与原记录不一致。');continue
            fields={'subject_refs':[subject],'record_count':len(rows),'date_count':len(dates),'night_count':nights,'dates':dates,'timezone':'Asia/Shanghai','window_start':scene['window_start'],'window_end':scene['window_end'],'snapshot_id':scene['records_snapshot_id'],'module':module}
            claims.append(claim(row,identity,'computed',module+'.summary.v1',f"{subject}的{LABELS[module]}共{len(rows)}条原始记录，涉及{len(dates)}个北京时间自然日，其中夜间{nights}条。",fields,[r['record_id'] for r in rows],rule))
            for record in rows:
                fact=approved.get(record['record_id'])
                if not fact or not fact.get('source_ids') or record['record_id'] not in fact['source_ids']:continue
                annotations=[f for f in scene.get('facts',[]) if f.get('source_document') and record['record_id'] in f.get('source_record_ids',[]) and set(f['source_record_ids'])<=source_ids]
                allowed_sources=source_ids|{f['source_document'] for f in annotations}
                if not set(fact['source_ids'])<=allowed_sources:continue
                fields={k:copy.deepcopy(record[k]) for k in FIELDS if k in record};fields.update(subject_refs=[subject],snapshot_id=scene['records_snapshot_id'],scenario_snapshot_id=scene['snapshot_id'])
                at=local(record['occurred_at']).isoformat() if record.get('occurred_at') else '时间未提供'
                detail='来源记录'+record['record_id']
                if module=='portrait':
                    relation={'same_frame':'同框','same_trip':'明确同行','same_vehicle':'明确同乘'}.get(record.get('kind'),'无法判断');fields['observation']=record.get('kind') if record.get('kind') in ('same_frame','same_trip','same_vehicle') else 'unknown';detail=relation+'；记录主体'+record.get('member_ref','')+'，共同出现对象'+record.get('co_member_ref','')
                if module=='night':
                    states={f.get('observation') for f in annotations if f.get('observation')};observation=next(iter(states)) if len(states)==1 else 'unknown';fields['observation']=observation if observation in ('alone','accompanied') else 'unknown';detail={'alone':'明确独行观测','accompanied':'明确同行观测','unknown':'同行状态无法判断'}[fields['observation']]
                if module=='funds':
                    amount=record.get('amount_minor')
                    if type(amount) is not int:missing.append('资金金额字段无效。');continue
                    fields['amount_unit']='minor';detail=f"原始资金流水，{record.get('direction','方向未知')}，金额{amount}分，对手账户{record.get('counterparty_ref','未提供')}"
                if module=='vehicle':detail='车辆'+record['group_ref']+'，'+record.get('direction','方向未知')+'，设备'+record.get('device_ref','未提供')
                claims.append(claim(row,identity,'fact',module+'.record.v1',subject+'，'+at+'，'+detail+'。',fields,fact['source_ids']))
        for fact in scene.get('facts',[]):
            approved_fact=approved.get(fact['record_id'])
            if not approved_fact or approved_fact.get('statement')!=fact.get('description') or not set(fact.get('source_record_ids',[]))<=source_ids:continue
            sources=fact.get('source_record_ids',[])+([fact['source_document']] if fact.get('source_document') else [])
            if set(approved_fact['source_ids'])!=set(sources):continue
            claims.append(claim(row,identity,'fact','scenario.context.v1',fact['description'],{'subject_refs':[subject],'scenario_id':scene['scenario_id'],'observation':fact.get('observation','unknown'),'scenario_snapshot_id':scene['snapshot_id']},sources))
    for module in plan.get('modules',[]):
        if module not in valid:missing.append(LABELS[module]+'尚未取得有效资料，不能解释为零条或没有发生。')
    if plan and not table:missing.append('本轮尚未形成可核对的事实表。')
    missing+=scene.get('limitations',[])
    if snapshot.get('task_response'):missing.append(snapshot['task_response']['message'])
    missing=list(dict.fromkeys(missing))
    for message in missing:claims.append(claim(row,identity,'gap','data.gap.v1',message,{'subject_refs':task.get('target_refs',[]),'data_usage':use['status']},[]))
    return {'schema':'peixian.analysis-result','version':VERSION,'run_id':row['id'],'agent':copy.deepcopy(identity),'task':{k:copy.deepcopy(task.get(k)) for k in ('query_mode','intent','methods','target_refs','target_mode','scenario_id','source_data_run_id')},'data_environment':'synthetic','data_usage':use,'claims':claims,'records':records,'missing':missing,'narrative':review(snapshot.get('model_narrative'),claims,use),'versions':{'scenario_snapshot_id':scene.get('snapshot_id'),'records_snapshot_id':scene.get('records_snapshot_id'),'registry':copy.deepcopy(plan.get('registry')),'plugin_versions':{p['id']:p.get('version') for p in snapshot.get('plugins',[]) if p['id'] in plan.get('allowed_capabilities',[])}},'generated_at':iso(row.get('completed') or row['created'])}


def project(store,row,snapshot):
    if snapshot.get('native_tool_policy'):
        from .native_tool_result import project as native_project
        result = native_project(row,snapshot)
        if snapshot.get('answer_delivery'):
            from .reply_presentation import build as build_presentation
            result['presentation'] = build_presentation(result)
            result['versions']['reply_projection'] = 'source-clues-v1'
        from .table_answer import build as build_tables
        view = build_tables(result,snapshot)
        if view is not None:
            from .table_answer import markdown as table_markdown
            view['markdown'] = table_markdown(view)
            result['answer_view'] = view
        return result
    if snapshot.get('provider_plan'):
        from .theft_provider_result import project as provider_project
        return provider_project(row,snapshot)
    events=store.rows('SELECT * FROM run_events WHERE run_id=? ORDER BY sequence',(row['id'],))
    result=build(row,snapshot,events)
    projection=snapshot.get('historical_projection')
    if projection and result['data_usage']['status']=='historical_evidence':
        from .task_context import source_info,project as history_project
        source_info(store,row['uid'],row['session_id'],row['id'])
        source=business_runs.owned(store,row['uid'],row['session_id'],projection['source_data_run_id'])
        frozen=store.decrypt(source['request_ciphertext'])
        if frozen.get('agent_profile')!=snapshot.get('agent_profile'):raise ValueError('history_agent_mismatch')
        if history_project(store,source,frozen)!=projection:error('source_evidence_unavailable','历史冻结资料已变化，拒绝重新投影。',409)
        prior=store.one('SELECT * FROM run_results WHERE run_id=?',(source['id'],))
        original=checked_result(store,prior) if prior else build(source,frozen,store.rows('SELECT * FROM run_events WHERE run_id=?',(source['id'],)))
        result.update(claims=copy.deepcopy(original['claims']),records=copy.deepcopy(original['records']),missing=copy.deepcopy(original['missing']),versions=copy.deepcopy(original['versions']))
        result['narrative']=review(snapshot.get('model_narrative'),result['claims'],result['data_usage'])
    from .controlled_answer import enabled as answer_enabled, build as build_answer
    if answer_enabled(snapshot):
        result['answer']=build_answer(result,snapshot,row)
        result['narrative']={**result['narrative'],'text':None,'coverage':'原模型说明仅保留内部诊断；用户回答来自受控中文事实投影。'}
    return result


def checked_result(store,stored):
    result=store.decrypt(stored['result_ciphertext'])
    row=store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(stored['run_id'],))
    snapshot=store.decrypt(row['request_ciphertext']) if row else {}
    plan=snapshot.get('provider_plan',{})
    from shared.theft_provider_v2 import VERSION as PROVIDER_V2
    environment=snapshot.get('data_environment',plan.get('data_environment','synthetic'))
    if (environment not in ('synthetic','acceptance_real') or (environment=='acceptance_real' and plan.get('version')!=PROVIDER_V2 and not snapshot.get('native_tool_policy'))
        or digest(result)!=stored['result_digest'] or result.get('run_id')!=stored['run_id'] or result.get('version')!=VERSION or result.get('data_environment')!=environment):error('result_integrity_failed','结果完整性无法核对。',409)
    return result


def finalize(store,db,rid):
    if store.schema_version()<9:return
    row=dict(db.execute('SELECT * FROM business_runs WHERE id=?',(rid,)).fetchone());snapshot=store.decrypt(row['request_ciphertext'])
    if snapshot.get('trusted_result_version')!=VERSION or row['status'] not in business_runs.TERMINAL:return
    result=project(store,row,snapshot);value=digest(result)
    old=db.execute('SELECT * FROM run_results WHERE run_id=?',(rid,)).fetchone()
    if old:
        checked_result(store,old)
        if old['result_digest']!=value:error('result_digest_conflict','已保存结果与本次输入不一致，拒绝覆盖。',409)
        return
    db.execute('INSERT INTO run_results VALUES(?,?,?,?,?,?)',(rid,VERSION,store.encrypt(result),value,row['completed'],row['completed']))


def read(store,uid,sid,rid):
    row=business_runs.owned(store,uid,sid,rid);snapshot=store.decrypt(row['request_ciphertext'])
    if store.schema_version()<9 or snapshot.get('trusted_result_version')!=VERSION:return {'schema':'peixian.analysis-result','version':'legacy','run_id':rid,'status':'legacy','result':None}
    stored=store.one('SELECT * FROM run_results WHERE run_id=?',(rid,))
    if stored:return checked_result(store,stored)
    if row['status'] in business_runs.TERMINAL:error('result_not_finalized','最终结果尚未形成，请稍后读取；不会重新查询资料。',409)
    return {'schema':'peixian.analysis-result','version':VERSION,'run_id':rid,'status':'pending','data_environment':snapshot.get('data_environment',snapshot.get('provider_plan',{}).get('data_environment','synthetic')),'data_usage':data_usage(store,row,snapshot)}


def data_usage(store,row,snapshot):
    if snapshot.get("native_tool_policy"):
        from .native_tool_result import project as native_project
        return native_project(row,snapshot)["data_usage"]
    if snapshot.get("provider_plan"):
        from .theft_provider_result import project
        return project(row,snapshot)["data_usage"]
    events=store.rows('SELECT * FROM run_events WHERE run_id=?',(row['id'],))
    try:valid,records,invalid=confirmed_inputs(snapshot,events)
    except (ValueError,KeyError,TypeError,IndexError):valid={};invalid=list(snapshot.get('facts_plan',{}).get('modules',[]))
    return usage(row,snapshot,events,valid,invalid)
