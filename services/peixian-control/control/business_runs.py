"""Durable user-level execution records. Never retry an ambiguous provider dispatch."""
import hashlib
import hmac
import json
import sqlite3
import uuid
from .backend_contract import error, iso, require_v6
from .store import ident, now, encode

TERMINAL=('completed','failed','cancelled')
ACTIVE=('queued','running','cancelling','reconciling')


def normalized(data):
    value=dict(data)
    from .agents.registry import require
    if 'agent_id' in value:require(value['agent_id'])
    if 'context_version' in value and (type(value['context_version']) is not int or value['context_version']<1):error('invalid_context_version','上下文版本必须为正整数',422)
    key=value.get('client_request_id') or str(uuid.uuid4())
    try:uuid.UUID(key)
    except (ValueError,TypeError,AttributeError):error('invalid_request_id','client_request_id 必须为UUID',422,{'client_request_id':'UUID required'})
    value['client_request_id']=key
    if value.get('mode','standard')!='standard':error('unsupported_mode','首版仅支持standard模式',422,{'mode':'standard'})
    value.setdefault('mode','standard')
    for field in ('skill_ids','plugin_ids','file_ids'):
        value.setdefault(field,[])
        if not isinstance(value[field],list) or len(value[field])>5 or any(not isinstance(x,str) for x in value[field]) or len(set(value[field]))!=len(value[field]):
            error('invalid_selection','每类最多选择五个不重复资源',422,{field:'最多五个不同ID'})
    return value


def fingerprint(store, data):
    return hmac.new(store.worker_key.encode(),json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode(),hashlib.sha256).hexdigest()


def receipt(row):
    return {'accepted':True,'run_id':row['id'],'message_id':row['message_id']}


def replay(store, uid, sid, data):
    row=store.one('SELECT * FROM business_runs WHERE uid=? AND session_id=? AND request_key=?',(uid,sid,data['client_request_id']))
    if row:
        if not hmac.compare_digest(row['request_hash'],fingerprint(store,data)):error('request_conflict','同一请求标识对应不同内容',409)
        return receipt(row)


def submit(store, user, sid, data, payload, applied, revision, parent=None, draft=None, trial=None, context=None, task=None, attachments=None):
    from .app import current_authority
    require_v6(store)
    identity=ident();message='msg_'+ident();timestamp=now();payload={**payload,'messageID':message}
    snapshot={'request':data,'payload':payload,'models':[x['id'] for x in applied.get('models',[])],
              'plugins':[{'id':x['id'],'version':x.get('version'),'name':x.get('manifest',{}).get('name',x['id']),'display':x.get('manifest',{}).get('display',{}),'tools':x.get('manifest',{}).get('tools',[])} for x in applied.get('plugins',[])],
              'skills':[{'id':x['id'],'name':x['name'],'version':x.get('version')} for x in applied.get('skills',[])]}
    from .app import tool_displays
    snapshot['display_secrets']=tool_displays(store,user['uid']).get('_redaction',{}).get('_secrets',[])
    from .trusted_results import enabled
    if enabled(store,user['uid']):snapshot['trusted_result_version']='2.0';snapshot['data_environment']='synthetic'
    from .record_checks import VERSION as record_check_version
    snapshot['record_check_version']=record_check_version
    if context is not None:snapshot['scenario_context']={**context,'revision':revision}
    with store.tx() as db:
        current_authority(db,user)
        row=db.execute('SELECT * FROM business_runs WHERE uid=? AND session_id=? AND request_key=?',(user['uid'],sid,data['client_request_id'])).fetchone()
        if row:
            if row['request_hash']!=fingerprint(store,data):error('request_conflict','同一请求标识对应不同内容',409)
            return receipt(row)
        from .agents import runtime as agents
        profile=agents.select(user['uid'],data)
        agents.session(store,user['uid'],sid,profile)
        if task is not None:
            from . import task_spec
            fresh = task_spec.resolve(store,user['uid'],sid,data,applied)
            if fresh.get('agent_profile')!=task.get('agent_profile'):error('agent_profile_changed','助手版本已变化，请刷新后重新确认。',409)
            if fresh != task:error('task_context_changed','任务范围或能力已变化，请刷新后重新确认。',409)
        if context is not None:
            from .scenario_context import boundary
            if boundary(store,user['uid'],sid)[0]!=context['generation']:error('scenario_context_changed','场景已被清除，请刷新后重新确认。',409)
        runtime=db.execute('SELECT * FROM runtimes WHERE uid=?',(user['uid'],)).fetchone()
        if not runtime or runtime['status']!='ready' or runtime['gate_policy']!='open' or runtime['security_blocked'] or runtime['recovery_required'] or runtime['revision']!=revision:
            error('runtime_changed','运行环境或配置已变化，请刷新后重新确认',409)
        if db.execute("SELECT 1 FROM business_runs WHERE uid=? AND session_id=? AND status IN ('queued','running','cancelling','reconciling')",(user['uid'],sid)).fetchone():error('session_busy','此会话已有未结束的执行',409)
        from .capabilities import check_selection
        selection = task_spec.admission_selection(data,task,context['effective_skill_ids']) if task is not None else ({**data,'skill_ids':context['effective_skill_ids']} if context is not None else data)
        check_selection(store,user['uid'],selection)
        if not db.execute("SELECT 1 FROM models m JOIN grants g ON g.resource=m.id AND g.kind='model' WHERE g.uid=? AND m.id=? AND m.enabled=1",(user['uid'],payload['model']['modelID'])).fetchone():error('model_unavailable','所选模型授权已变化',403)
        if agents.enabled(user['uid']):
            agents.bind(payload,profile,context,[x for x in applied.get('skills',[]) if x['id'] in (context or {}).get('effective_skill_ids',[])])
        from .native_tool_gate import enabled as native_enabled, VERSION as native_version
        native=profile.id=='theft-assistant' and native_enabled(store,user['uid']) and task is None
        if native:
            from .native_tool_scope import freeze_context
            from .data_plugin_policy import installable
            allowed=sorted({tool for p in applied.get('plugins',[]) if installable(p['id']) and p.get('version')=='3.0.0' for tool in p.get('manifest',{}).get('tools',[])})
            payload['tools']={**payload.get('tools',{}),'*':False,'question':True,**{tool:True for tool in allowed}}
            snapshot['native_tool_context']=freeze_context(store,user['uid'],sid,data)
            snapshot['native_tool_policy']={'version':native_version,'allowed_tools':allowed,'revision':revision}
            snapshot['native_calls']={}
            snapshot['task_spec']={'schema_version':'native-tools-v1','domain':'theft','agent_id':profile.id,'query_mode':'native','methods':[],'task_id':snapshot['native_tool_context']['task_id']}
            snapshot['data_environment']='acceptance_real'
        from .facts_plan import build, bind_payload
        provider=task and task.get('provider_plan')
        plan = None if provider else build(applied, context, data, task) if task and task['spec'] and task['spec']['query_mode']=='new_query' else None if task else build(applied, context, data)
        if task and task['spec'] and task['spec']['query_mode']=='new_query' and not plan and not provider:error('task_plan_unavailable','固定方法执行链尚未生效。',409)
        if plan:
            # Verify every planned dependency, not only the user's preferences.
            check_selection(store,user['uid'],{'skill_ids':context['effective_skill_ids'],'plugin_ids':plan['allowed_capabilities']})
            bind_payload(payload,plan,applied)
            snapshot['facts_plan']=plan
            snapshot['registry_snapshot']=plan['registry']
            snapshot['execution_plan']={k:plan[k] for k in ('plan_version','methods','modules','steps')}
            snapshot['allowed_capabilities']=plan['allowed_capabilities']
            snapshot['allowed_tools']=plan['allowed_tools']
        from .task_context import admit
        if task and not provider:admit(store,db,user['uid'],sid,task)
        if provider:
            from .theft_provider_flow import bind
            bind(snapshot,payload,task)
        elif task is not None:
            from .task_spec import bind
            bind(snapshot,payload,task)
        snapshot["agent_profile"]=profile.snapshot()
        from .controlled_answer import freeze as freeze_answer
        freeze_answer(snapshot,payload)
        agents.freeze(snapshot,payload,profile)
        from .message_attachments import freeze
        snapshot['attachments'] = freeze(db,user['uid'],data.get('file_ids',[]),attachments)
        # Admission freezes encrypted inputs; SQL never holds a network operation.
        db.execute("INSERT INTO business_runs(id,uid,session_id,request_key,request_hash,message_id,parent_id,status,phase,model_id,revision,auth_version,request_ciphertext,created,updated) VALUES(?,?,?,?,?,?,?,'queued','pending_dispatch',?,?,?,?,?,?)",(identity,user['uid'],sid,data['client_request_id'],fingerprint(store,data),message,parent,payload['model']['modelID'],revision,user['version'],store.encrypt(snapshot),timestamp,timestamp))
        if provider and task.get('analysis_task'):
            from .analysis_tasks import attach
            attach(store,db,user,sid,identity,task['analysis_task'],task['provider_plan'],data)
        if task and task['local']:
            response=task['local']
            phase='clarification' if task['spec']['query_mode']=='clarify' else 'history_unavailable'
            empty={'status':'empty','cards':[],'summary':[],'missing':[response['message']]}
            db.execute("UPDATE business_runs SET status='completed',phase=?,assistant_id=?,completed=?,evidence_ciphertext=? WHERE id=?",(phase,'msg_task_'+identity,timestamp,store.encrypt(empty),identity))
            event(store,identity,'task-route','routing','需要补充信息' if phase=='clarification' else '历史解释尚未开放','completed',timestamp,timestamp)
        else:
            db.execute("INSERT INTO run_deliveries(run_id,state) VALUES(?,'pending')",(identity,))
        profile=db.execute('SELECT department_id FROM user_profiles WHERE uid=?',(user['uid'],)).fetchone()
        db.execute('INSERT INTO invocations(id,run_id,uid,department_id,model_id,selected_skills,selected_plugins,query_summary,created) VALUES(?,?,?,?,?,?,?,?,?)',(ident(),identity,user['uid'],profile['department_id'] if profile else None,payload['model']['modelID'],encode(data['skill_ids']),encode(data['plugin_ids']),'技能对话' if data['skill_ids'] else '普通对话',timestamp))
        if task and task['local']:
            from .task_context import completed
            completed(store,db,identity)
        if task and task['local']:
            from .trusted_results import finalize
            finalize(store,db,identity)
        if trial:
            count=db.execute('UPDATE draft_trials SET run_id=?,session_id=? WHERE id=? AND uid=? AND run_id IS NULL',(identity,sid,trial,user['uid'])).rowcount
            if count!=1:error('trial_conflict','试运行已受理或正在核对',409)
        if draft:
            count=db.execute("UPDATE skill_drafts SET run_id=?,status='generating',updated=? WHERE id=? AND uid=? AND run_id IS NULL AND status='preparing'",(identity,timestamp,draft,user['uid'])).rowcount
            if count!=1:error('draft_conflict','草稿受理状态已变化',409)
    return {'accepted':True,'run_id':identity,'message_id':message}


def owned(store,uid,sid,rid):
    require_v6(store)
    row=store.one('SELECT * FROM business_runs WHERE id=? AND uid=? AND session_id=?',(rid,uid,sid))
    if not row:error('run_not_found','执行记录不存在',404)
    return row


def public(row):
    return {'id':row['id'],'session_id':row['session_id'],'status':row['status'],'phase':row['phase'],'model_id':row['model_id'],'message_id':row['assistant_id'],'user_message_id':row['message_id'],'parent_run_id':row['parent_id'],'created_at':iso(row['created']),'started_at':iso(row['started']),'completed_at':iso(row['completed']),'updated_at':iso(row['updated']),'cancel_requested':bool(row['cancel_requested']),'error':{'code':row['error_code'],'message':'执行未确认或未能完成，请查看状态'} if row['error_code'] else None}


def set_state(store,rid,status,phase,code=None):
    with store.tx() as db:
        row=db.execute('SELECT status,phase,error_code,cancel_requested FROM business_runs WHERE id=?',(rid,)).fetchone()
        if not row or row['status'] in TERMINAL:return
        if row['cancel_requested'] and status not in ('cancelling','cancelled','completed','failed','reconciling'):return
        if (row['status'],row['phase'],row['error_code'])==(status,phase,code):return
        if status=='cancelling':db.execute('UPDATE business_runs SET cancel_requested=1 WHERE id=?',(rid,))
        db.execute("UPDATE business_runs SET status=?,phase=?,error_code=?,updated=?,started=CASE WHEN ? IN ('running','cancelling') THEN coalesce(started,?) ELSE started END,completed=CASE WHEN ? IN ('completed','failed','cancelled') THEN ? ELSE completed END WHERE id=?",(status,phase,code,now(),status,now(),status,now(),rid))
        if status=='completed' and not store.decrypt(db.execute('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,)).fetchone()[0]).get('provider_plan'):
            from .task_context import completed
            completed(store,db,rid)
        if status in TERMINAL:
            from .trusted_results import finalize
            finalize(store,db,rid)


def event(store,rid,key,kind,name,status,started=None,completed=None,capability=None,count=0,metadata=None):
    with store.tx() as db:
        existing=db.execute('SELECT * FROM run_events WHERE run_id=? AND event_key=?',(rid,key)).fetchone()
        # Terminal observations cannot regress when a delayed Agent snapshot arrives.
        if existing and existing['status'] in ('completed','failed','cancelled') and status in ('pending','running'):return
        metadata_changed=False
        if metadata is not None:
            run=db.execute('SELECT request_ciphertext FROM business_runs WHERE id=?',(rid,)).fetchone()
            frozen=store.decrypt(run['request_ciphertext']);steps=frozen.setdefault('public_steps',{})
            metadata_changed=steps.get(key)!=metadata
            steps[key]=metadata
            db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(store.encrypt(frozen),rid))
            if existing:
                db.execute('UPDATE run_events SET name=?,capability_id=?,input_summary=?,output_summary=? WHERE id=?',
                           (name,capability,metadata.get('input_summary',''),metadata.get('output_summary',''),existing['id']))
        if existing:
            first=existing['started'] if existing['started'] is not None else started
            if (existing['status'],existing['started'],existing['completed'],existing['record_count'])==(status,first,completed,count) and not metadata_changed:return
            sequence=db.execute('SELECT coalesce(max(sequence),0)+1 FROM run_events WHERE run_id=?',(rid,)).fetchone()[0]
            db.execute('UPDATE run_events SET sequence=?,status=?,started=?,completed=?,record_count=? WHERE id=?',(sequence,status,first,completed,count,existing['id']))
        else:
            sequence=db.execute('SELECT coalesce(max(sequence),0)+1 FROM run_events WHERE run_id=?',(rid,)).fetchone()[0]
            db.execute('INSERT INTO run_events(id,run_id,event_key,sequence,step_type,name,status,started,completed,capability_id,record_count) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(ident(),rid,key,sequence,kind,name,status,started,completed,capability,count))

        if metadata is not None:
            db.execute('UPDATE run_events SET input_summary=?,output_summary=? WHERE run_id=? AND event_key=?',
                       (metadata.get('input_summary',''),metadata.get('output_summary',''),rid,key))


def public_event(row):
    return {'id':row['id'],'sequence':row['sequence'],'step_type':row['step_type'],'name':row['name'],'status':row['status'],'started_at':iso(row['started']),'completed_at':iso(row['completed']),'elapsed_ms':max(0,(row['completed']-row['started'])*1000) if row['completed'] is not None and row['started'] is not None else None,'capability_id':row['capability_id'],'input_summary':row['input_summary'],'output_summary':row['output_summary'],'record_count':row['record_count'],'evidence_refs':json.loads(row['evidence_refs']),'error_message':'步骤未完成' if row['error_code'] else None}
