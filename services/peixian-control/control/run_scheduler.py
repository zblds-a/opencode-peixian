"""Single-control bounded dispatcher and reconciler; independent of viewers and Worker."""
import asyncio
import json
import logging
import httpx
from . import business_runs as runs
from .backend_contract import iso
from .store import now, encode


def binding(store,row):
    with store.read(snapshot=True) as db:
        runtime=db.execute('SELECT * FROM runtimes WHERE uid=?',(row['uid'],)).fetchone()
        user=db.execute('SELECT * FROM users WHERE id=?',(row['uid'],)).fetchone()
        if not runtime:return None
        allowed=user and user['active'] and user['auth_version']==row['auth_version'] and not runtime['security_blocked']
        return {'base':'http://px-'+runtime['id']+'-gateway:8080','headers':{'X-Peixian-Key':store.decrypt(runtime['spec'])['gateway_key']},'allowed':bool(allowed),'ready':runtime['status']=='ready' and runtime['gate_policy']=='open' and not runtime['recovery_required'],'revision':runtime['revision'],'maintenance':store.maintenance_status(db)['maintenance_mode']}


def mark_sending(store,rid):
    with store.tx() as db:
        if not db.execute("SELECT 1 FROM business_runs WHERE id=? AND status='queued'",(rid,)).fetchone():return False
        cursor=db.execute("UPDATE run_deliveries SET state='sending',attempted=? WHERE run_id=? AND state='pending'",(now(),rid))
        return cursor.rowcount==1


def track_messages(store,row,values,receipt):
    snapshot=store.decrypt(row['request_ciphertext']);tools={tool:p['id'] for p in snapshot['plugins'] for tool in p['tools']}
    starts=[i for i,m in enumerate(values) if m.get('info',{}).get('id')==row['message_id']]
    if not starts:return False
    selected=values[starts[0]:];end=next((i for i,m in enumerate(selected[1:],1) if m.get('info',{}).get('role')=='user'),len(selected));selected=selected[:end]
    usertime=selected[0]['info'].get('time',{}).get('created')
    runs.event(store,row['id'],'accepted','requirement','接收请求','completed',usertime//1000 if usertime else row['created'],usertime//1000 if usertime else row['created'])
    prior=store.one('SELECT actual_plugins FROM invocations WHERE run_id=?',(row['id'],))
    actual=set(json.loads(prior['actual_plugins'])) if prior else set();assistants=[];violations=[]
    plan=snapshot.get('facts_plan')
    if not plan and snapshot.get('task_spec'):
        permitted_tools=set()
    if plan:
        from .facts_plan import HELPERS
        permitted_tools=set(plan['allowed_tools']) | set(HELPERS) | {'question'}
    if snapshot.get('provider_plan'):permitted_tools={snapshot['provider_plan']['tool_id']}
    native=snapshot.get('native_tool_policy',{})
    if native.get('version')=='native-provider-gate-v1':
        # Native runs can use earlier authorized tools after provider_plan moves
        # to a later call. Frozen authorization still bounds every observed tool.
        permitted_tools=set(native.get('allowed_tools',[])) & set(tools)
        permitted_tools|={name for name in ('question','skill','peixian_load_personal_skill') if snapshot.get('payload',{}).get('tools',{}).get(name) is True}

    for message in selected:
        info=message.get('info',{})
        if info.get('role')!='assistant':continue
        assistants.append(message)
        for part in message.get('parts',[]):
            if part.get('type')!='tool':continue
            state=part.get('state',{});tool=part.get('tool');pid=tools.get(tool)
            if (plan or snapshot.get('task_spec')) and tool not in permitted_tools:violations.append(str(part.get('id') or part.get('callID')))
            if pid:actual.add(pid)
            kind='skill' if tool=='skill' else 'plugin' if pid else 'analysis'
            timing=state.get('time',{});status={'completed':'completed','error':'failed','running':'running','pending':'pending','cancelled':'cancelled','waiting_input':'waiting_input'}.get(state.get('status'),'pending')
            try:
                _out=json.loads(state.get('output','')) if isinstance(state.get('output'),str) else state.get('output')
            except (TypeError,ValueError):
                _out={}
            if isinstance(_out,dict) and _out.get('status')=='needs_input' and status=='completed':
                status='waiting_input'
            from .execution_view import observed
            metadata=observed(snapshot,{**part,'messageID':info.get('id')})
            status=metadata['status']
            runs.event(store,row['id'],str(part.get('id') or part.get('callID')),kind,metadata['name'],status,timing.get('start')//1000 if type(timing.get('start')) is int else None,timing.get('end')//1000 if type(timing.get('end')) is int else None,metadata['capability_id'],metadata['record_count'],metadata=metadata)
    with store.tx() as db:
        db.execute('UPDATE invocations SET actual_plugins=? WHERE run_id=?',(encode(sorted(actual)),row['id']))
        latest_snapshot=store.decrypt(db.execute('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],)).fetchone()['request_ciphertext'])
        latest_snapshot['observed_message_ids']=list(dict.fromkeys(latest_snapshot.get('observed_message_ids',[])+[m['info']['id'] for m in assistants if isinstance(m.get('info',{}).get('id'),str)]))[:1000]
        db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(store.encrypt(latest_snapshot),row['id']))
    if violations:
        with store.tx() as db:
            for key in violations:runs.event(store,row['id'],'plan-denied.'+key,'authorization','发现非计划工具，停止并核对','rejected',completed=now())
            db.execute("UPDATE business_runs SET cancel_requested=1,error_code='facts_plan_violation' WHERE id=?",(row['id'],))
        row={**row,'cancel_requested':1}
    if not assistants:return False
    last=assistants[-1];info=last['info'];timing=info.get('time',{})
    finished=timing.get('completed') is not None and (info.get('finish') in ('stop','end_turn','length') or info.get('error'))
    if not finished:return False
    # Persist evidence from canonical plugin facts only, never model-authored result parts.
    from .scenario_evidence import project,permitted
    from .scenario_presentation import presentation
    if snapshot.get('provider_plan'):
        from .theft_provider_state import ProviderState
        ProviderState(store).terminate(row['uid'],row['id'],row['revision'])
    if plan and (row['cancel_requested'] or violations):
        from .facts_runtime import FactsState
        FactsState(store).terminate(row['uid'],row['id'],row['revision'])
    latest=store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))
    frozen=store.decrypt(latest['request_ciphertext'])
    if frozen.get('run_kind')=='history_explanation':
        projection=frozen.get('historical_projection') or {}
        evidence={'version':'1.0','status':'partial' if projection.get('missing') else 'complete','cards':[], 'summary':[], 'missing':projection.get('missing',[]),'source_data_run_id':projection.get('source_data_run_id'),'historical_projection_digest':projection.get('digest')}
        view=None
    elif frozen.get('facts_plan'):
        from .facts_evidence import evidence as durable_evidence
        evidence=durable_evidence(frozen,{**row,'assistant_id':info['id']})
        view=evidence.get('presentation')
        if violations:
            evidence={'version':'1.0','status':'empty','cards':[],'missing':['执行计划不一致，结果暂不可核验。']};view=None
    else:
        evidence=project(selected,permitted(store,row['uid']))
        view=presentation(evidence,selected)
    result=None
    if view:
        if view.get('diagram'): view['diagram']['run_id']=row['id']
        evidence['presentation']=view
        result={'schema':'peixian.analysis-result','version':'1.0','run_id':row['id'],'generated_at':iso(now()),'intro':'','process':view['process'],'subjects':[],'conclusions':[x['text'] for x in view['conclusions']],'evidence':view['evidence'],'next_steps':view.get('next_steps',''),'recommendations':view.get('recommendations',[]),'missing':view.get('missing',[]),'missing_details':view.get('missing_details',[]),'public_markdown':view.get('public_markdown',''),'clues':view['clues'],'conclusion_sources':view['conclusions'],'source_metadata':evidence.get('scenario',{}),'presentation_version':view['version'],'diagram':view.get('diagram')}
    failure='FactsPlanViolation' if violations else info.get('error',{}).get('name')
    status='cancelled' if failure=='MessageAbortedError' else 'failed' if failure else 'completed'
    with store.tx() as db:
        current=db.execute('SELECT status FROM business_runs WHERE id=?',(row['id'],)).fetchone()
        if current['status'] in runs.TERMINAL:return True
        if frozen.get('trusted_result_version')=='2.0':
            frozen['model_final_text']='\n'.join(p.get('text','') for p in last.get('parts',[]) if p.get('type')=='text' and isinstance(p.get('text'),str))[:60001]
            frozen['model_narrative']='\n'.join(p.get('text','') for m in assistants for p in m.get('parts',[]) if p.get('type')=='text' and isinstance(p.get('text'),str))[:60001]
            db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(store.encrypt(frozen),row['id']))
        db.execute('UPDATE business_runs SET assistant_id=?,evidence_ciphertext=?,result_ciphertext=? WHERE id=?',(info['id'],store.encrypt(evidence),store.encrypt(result) if result else None,row['id']))
        runs.set_state(store,row['id'],status,status,'model_failed' if status=='failed' else None)
    runs.event(store,row['id'],'result','result','生成结果',status,timing.get('created',0)//1000,timing['completed']//1000)
    if status=='cancelled':
        for pending in store.rows("SELECT * FROM run_events WHERE run_id=? AND status IN ('pending','running')",(row['id'],)):
            runs.event(store,row['id'],pending['event_key'],pending['step_type'],pending['name'],'cancelled',pending['started'],now(),pending['capability_id'],pending['record_count'])
    from .skill_drafts import finalize
    finalize(store,row['id'],selected)
    return True


class Coordinator:
    def __init__(self,app):
        self.app=app;self.stop=asyncio.Event();self.task=None;self.planner_task=None
    def start(self):self.task=asyncio.create_task(self.loop())
    async def close(self):
        self.stop.set()
        if self.planner_task:
            self.planner_task.cancel()
            await asyncio.gather(self.planner_task,return_exceptions=True)
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
    async def loop(self):
        while not self.stop.is_set():
            try:
                s=self.app.state.store
                await self.recover_drafts()
                if self.planner_task is None or self.planner_task.done():
                    if self.planner_task and not self.planner_task.cancelled():
                        failure=self.planner_task.exception()
                        if failure:logging.getLogger('peixian.runs').warning('planner_failure type=%s',type(failure).__name__)
                    from .theft_planner import continue_one
                    self.planner_task=asyncio.create_task(continue_one(self.app))
                rows=await self.app.state.db_work.run(s.rows,"SELECT r.*, (SELECT coalesce(max(sequence),0) FROM run_events e WHERE e.run_id=r.id) AS event_cursor FROM business_runs r JOIN run_deliveries d ON d.run_id=r.id WHERE r.status IN ('queued','running','cancelling','reconciling') AND d.next_check<=? ORDER BY d.next_check,r.created LIMIT 4",(now(),))
                await asyncio.gather(*(self.step(row) for row in rows))
            except asyncio.CancelledError:raise
            except Exception as exc:logging.getLogger('peixian.runs').warning('run_reconcile_failure type=%s',type(exc).__name__)
            try:await asyncio.wait_for(self.stop.wait(),1)
            except TimeoutError:pass
    async def recover_drafts(self):
        app=self.app;s=app.state.store;work=app.state.db_work.run
        def preparing():
            with s.tx() as db:
                db.execute("UPDATE skill_drafts SET status='failed',error_code='admission_interrupted',updated=? WHERE status='preparing' AND run_id IS NULL AND created<?",(now(),now()-300))
        await work(preparing)
        rows=await work(s.rows,"SELECT r.* FROM skill_drafts d JOIN business_runs r ON r.id=d.run_id WHERE d.status='generating' AND r.status IN ('completed','failed','cancelled') ORDER BY d.updated LIMIT 2")
        from .skill_drafts import finalize
        for row in rows:
            if row['status']!='completed':await work(finalize,s,row['id'],[]);continue
            bind=await work(binding,s,row)
            if not bind or not bind['allowed']:continue
            try:
                response=await app.state.http.get(bind['base']+'/session/'+row['session_id']+'/message',headers=bind['headers'],timeout=5)
                response.raise_for_status()
                values=[m for m in response.json() if m.get('info',{}).get('id')==row['assistant_id']]
                if values:await work(finalize,s,row['id'],values)
            except (httpx.HTTPError,ValueError,TypeError):continue

    async def step(self,row):
        app=self.app;s=app.state.store;work=app.state.db_work.run
        def defer():
            with s.tx() as db:db.execute('UPDATE run_deliveries SET next_check=? WHERE run_id=?',(now()+2,row['id']))
        await work(defer)
        dispatched=False
        try:
            bind=await work(binding,s,row)
            if not bind:return
            base=bind['base'];headers=bind['headers']
            state=await work(s.one,'SELECT * FROM run_deliveries WHERE run_id=?',(row['id'],))
            dispatched=state['state']!='pending'
            if state['state']=='pending' and row['cancel_requested']:
                await work(runs.set_state,s,row['id'],'cancelled','cancelled');return
            if state['state']=='pending' and (not bind['allowed'] or bind['revision']!=row['revision']):
                await work(runs.set_state,s,row['id'],'failed','rejected','authorization_or_configuration_changed');return
            if state['state']=='pending' and (not bind['ready'] or bind['maintenance']!='normal'):return
            if state['state']=='pending':
                probe=await app.state.http.get(base+'/internal/runtime/runs/'+row['id'],headers=headers,timeout=5);probe.raise_for_status()
                if probe.json().get('protocol')!='durable_run_v1':return
                if not await work(mark_sending,s,row['id']):return
                dispatched=True
                snapshot=s.decrypt(row['request_ciphertext'])
                # Exactly one attempt after the durable sending mark. Ambiguous outcomes only query.
                response=await app.state.http.post(base+'/session/'+row['session_id']+'/prompt_async',headers={**headers,'X-Peixian-Run-ID':row['id']},json=snapshot['payload'],timeout=15)
                if response.status_code>=400:
                    await work(runs.set_state,s,row['id'],'reconciling','confirming_admission','dispatch_unconfirmed');return
                await work(runs.set_state,s,row['id'],'running','generating')
            response=await app.state.http.get(base+'/internal/runtime/runs/'+row['id'],headers=headers,timeout=5);response.raise_for_status();receipt=response.json().get('receipt')
            if not receipt:
                await work(runs.set_state,s,row['id'],'reconciling','confirming_admission','admission_unknown');return
            if receipt.get('session_id')!=row['session_id'] or receipt.get('message_id')!=row['message_id']:
                await work(runs.set_state,s,row['id'],'reconciling','confirming_admission','receipt_mismatch');return
            def record_receipt():
                with s.tx() as db:db.execute("UPDATE run_deliveries SET state='admitted',receipt=? WHERE run_id=?",(encode(receipt),row['id']))
            await work(record_receipt)
            current=await work(s.one,'SELECT * FROM business_runs WHERE id=?',(row['id'],))
            if current['cancel_requested'] or not bind['allowed']:
                await work(runs.set_state,s,row['id'],'cancelling','stopping')
                await app.state.http.post(base+'/session/'+row['session_id']+'/abort',headers=headers,timeout=5)
                current=await work(s.one,'SELECT * FROM business_runs WHERE id=?',(row['id'],))
            response=await app.state.http.get(base+'/session/'+row['session_id']+'/message',headers=headers,timeout=10);response.raise_for_status()
            if await work(track_messages,s,current,response.json(),receipt):return
            if receipt['state']=='finished':
                from .conversation_completion import finish_dismissed
                if await work(finish_dismissed,s,current,response.json()):return
                await work(runs.set_state,s,row['id'],'cancelled' if current['cancel_requested'] else 'failed','finished_without_result','no_terminal_result')
            elif receipt['state']=='unknown':
                await work(runs.set_state,s,row['id'],'reconciling','recovery_required','agent_restarted')
            else:
                phase='generating'
                for path,waiting in [('/question','waiting_question'),('/permission','waiting_permission')]:
                    pending=await app.state.http.get(base+path,headers=headers,timeout=5);pending.raise_for_status()
                    if any(x.get('sessionID')==row['session_id'] for x in pending.json()):phase=waiting;break
                await work(runs.set_state,s,row['id'],'running',phase)
        except asyncio.CancelledError:raise
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            if dispatched:await work(runs.set_state,s,row['id'],'reconciling','confirming_state','upstream_unavailable')
        finally:
            from .skill_drafts import finalize
            await work(finalize,s,row['id'],[])
            hub=app.state.event_hubs.hubs.get(row['uid'])
            latest=await work(s.one,'SELECT status,phase,updated,error_code,(SELECT coalesce(max(sequence),0) FROM run_events WHERE run_id=business_runs.id) AS event_cursor FROM business_runs WHERE id=?',(row['id'],))
            if hub and any(latest[k]!=row.get(k) for k in latest):hub.publish({'type':'run.updated','resources':['runs','messages','sessions'],'session_id':row['session_id'],'run_id':row['id'],'updated_at':iso(now())})
