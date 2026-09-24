import json
from fastapi import Depends, Request
from fastapi.responses import Response
from .backend_contract import error, require_v6, page_values
from .concurrency import blocking_endpoint
from . import business_runs as runs
from .store import now


def public(store,row):
    from .run_outcome import project
    from .theft_planner import public_question
    return {**runs.public(row),'outcome':project(store,row),'clarification':public_question(store,row)}


def evidence(store,row):
    # Caller has already verified Run ownership. Historical encrypted evidence
    # is not conditional on the old plugin remaining installed today.
    if row['evidence_ciphertext']:return {'run_id':row['id'],**store.decrypt(row['evidence_ciphertext'])}
    snapshot=store.decrypt(row['request_ciphertext'])
    if snapshot.get('facts_plan'):
        from .facts_evidence import evidence as project
        return project(snapshot,row)
    return {'run_id':row['id'],'status':'pending','cards':[],'summary':[]}


def attach_results(store,uid,values,sid=None):
    if store.schema_version()<6:return values
    for message in values:
        mid=message['info'].get('id')
        row=store.one('SELECT id,result_ciphertext FROM business_runs WHERE uid=? AND assistant_id=? AND result_ciphertext IS NOT NULL',(uid,mid))
        if row:message['parts'].append({'id':'part_run_'+row['id'],'type':'analysis_result','data':store.decrypt(row['result_ciphertext'])})
    if sid:
        known={m['info'].get('id') for m in values}
        for row in store.rows("SELECT * FROM business_runs WHERE uid=? AND session_id=? AND phase IN ('clarification','history_unavailable') ORDER BY created,id",(uid,sid)):
            snap=store.decrypt(row['request_ciphertext'])
            if not snap.get('task_response'):continue
            for mid,role,text in ((row['message_id'],'user',snap['request']['text']),(row['assistant_id'],'assistant',snap['task_response']['message'])):
                if mid in known:continue
                values.append({'info':{'id':mid,'sessionID':sid,'role':role,'parentID':row['message_id'] if role=='assistant' else None,'time':{'created':row['created']*1000,'completed':row['completed']*1000}},
                    'parts':[{'id':'part_'+mid,'type':'text','text':text}]})
                known.add(mid)
        values.sort(key=lambda m:m['info'].get('time',{}).get('created',0))
    for message in values:
        if message['info'].get('role')=='user':message['attachments']=[]
    if sid:
        from .execution_view import attach
        values=attach(store,uid,sid,values)
    if sid:
        from .controlled_answer import messages
        values=messages(store,uid,sid,values)
    return values


def cancel(store,uid,sid,rid):
    row=runs.owned(store,uid,sid,rid)
    if row['status'] not in runs.TERMINAL:runs.set_state(store,rid,'cancelling','stopping')
    return public(store,runs.owned(store,uid,sid,rid))


def register(app):
    from .app import PREFIX,normal,body_fields
    @app.get(PREFIX+'/sessions/{sid}/runs')
    async def run_list(sid:str,request:Request,page:int=1,page_size:int=20,user=Depends(normal)):
        from .app import session_owned
        s=app.state.store;offset=page_values(page,page_size)
        def read():
            require_v6(s)
            with s.read(snapshot=True) as db:
                rows=[dict(x) for x in db.execute('SELECT * FROM business_runs WHERE uid=? AND session_id=? ORDER BY created DESC,id LIMIT ? OFFSET ?',(user['uid'],sid,page_size,offset))]
                total=db.execute('SELECT count(*) FROM business_runs WHERE uid=? AND session_id=?',(user['uid'],sid)).fetchone()[0]
            return {'items':[public(s,x) for x in rows],'total':total,'page':page,'page_size':page_size}
        value=await app.state.db_work.run(read)
        if not value['total']:await session_owned(request,user,sid)
        return value

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}')
    @blocking_endpoint(app)
    def run_get(sid:str,rid:str,request:Request,user=Depends(normal)):
        return public(app.state.store,runs.owned(app.state.store,user['uid'],sid,rid))

    @app.post(PREFIX+'/sessions/{sid}/runs/{rid}/clarification/reject')
    @blocking_endpoint(app)
    def clarification_reject(sid:str,rid:str,request:Request,user=Depends(normal)):
        from .theft_planner import dismiss_question
        return dismiss_question(app.state.store,user['uid'],sid,rid)

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/task')
    @blocking_endpoint(app)
    def run_task(sid:str,rid:str,request:Request,user=Depends(normal)):
        row=runs.owned(app.state.store,user['uid'],sid,rid)
        snapshot=app.state.store.decrypt(row['request_ciphertext'])
        return {'run_id':rid,'task_spec':snapshot.get('task_spec'),'agent_profile':snapshot.get('agent_profile'),'effective_system_prompt_sha256':snapshot.get('effective_system_prompt_sha256'),'response':snapshot.get('task_response')}

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/result')
    @blocking_endpoint(app)
    def run_result(sid:str,rid:str,request:Request,user=Depends(normal)):
        from .trusted_results import read
        from .controlled_answer import public_result
        return public_result(read(app.state.store,user['uid'],sid,rid))

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/claims')
    @blocking_endpoint(app)
    def run_claims(sid:str,rid:str,request:Request,user=Depends(normal)):
        from .trusted_results import read
        result=read(app.state.store,user['uid'],sid,rid)
        return {'run_id':rid,'result_version':result['version'],'status':result.get('status','final'),'items':result.get('claims',[])}

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/data-usage')
    @blocking_endpoint(app)
    def run_data_usage(sid:str,rid:str,request:Request,user=Depends(normal)):
        from .trusted_results import read
        result=read(app.state.store,user['uid'],sid,rid)
        return {'run_id':rid,'result_version':result['version'],'data_usage':result.get('data_usage')}

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/events')
    @blocking_endpoint(app)
    def run_events(sid:str,rid:str,request:Request,page:int=1,page_size:int=100,after:int=0,user=Depends(normal)):
        s=app.state.store;runs.owned(s,user['uid'],sid,rid);offset=page_values(page,page_size)
        if after<0:error('invalid_sequence','事件序号无效')
        rows=s.rows('SELECT * FROM run_events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ? OFFSET ?',(rid,after,page_size,offset))
        from .execution_view import event_view
        row=runs.owned(s,user['uid'],sid,rid);snapshot=s.decrypt(row['request_ciphertext'])
        return {'items':[event_view(x,snapshot) for x in rows],'total':s.one('SELECT count(*) AS n FROM run_events WHERE run_id=? AND sequence>?',(rid,after))['n'],'page':page,'page_size':page_size}

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/evidence')
    @blocking_endpoint(app)
    def run_evidence(sid:str,rid:str,request:Request,user=Depends(normal)):
        return evidence(app.state.store,runs.owned(app.state.store,user['uid'],sid,rid))

    @app.post(PREFIX+'/sessions/{sid}/runs/{rid}/abort',status_code=202)
    @blocking_endpoint(app)
    def run_abort(sid:str,rid:str,request:Request,user=Depends(normal)):
        return cancel(app.state.store,user['uid'],sid,rid)

    @app.post(PREFIX+'/sessions/{sid}/runs/{rid}/rerun',status_code=202)
    async def run_again(sid:str,rid:str,request:Request,user=Depends(normal)):
        s=app.state.store;row=await app.state.db_work.run(runs.owned,s,user['uid'],sid,rid)
        data=body_fields(await request.json(),('client_request_id','text','model_id','skill_ids','plugin_ids','file_ids','mode','agent_id','context_version'))
        if not data.get('client_request_id'):error('request_id_required','重跑必须提供新的client_request_id')
        if row['status'] not in runs.TERMINAL:error('run_active','原执行尚未结束',409)
        merged={**s.decrypt(row['request_ciphertext'])['request'],**data}
        if merged['client_request_id']==row['request_key']:error('request_id_reused','重跑需要新的请求标识',409)
        async def receive():return {'type':'http.request','body':json.dumps(merged).encode(),'more_body':False}
        forwarded=Request(request.scope,receive);forwarded.state.run_parent=rid
        endpoint=next(route.endpoint for route in app.routes if getattr(route,'name',None)=='message_send')
        return await endpoint(sid,forwarded,user)

    @app.get(PREFIX+'/sessions/{sid}/runs/{rid}/report')
    @blocking_endpoint(app)
    def run_report(sid:str,rid:str,request:Request,format:str="md",user=Depends(normal)):
        s=app.state.store;row=runs.owned(s,user['uid'],sid,rid)
        if row['status'] not in runs.TERMINAL:error('run_not_finished','执行尚未结束，暂不能导出',409)
        if format not in ('md','html'):error('report_format_invalid','仅支持 Markdown 或 HTML 报告。',422)
        from .trusted_results import read
        from .trusted_report import render
        result=read(s,user['uid'],sid,rid)
        if result['version']=='2.0' or format=='html':
            events=s.rows('SELECT name,status FROM run_events WHERE run_id=? ORDER BY sequence',(rid,))
            s.audit(user['uid'],'run.report',rid,actor_role='user')
            from .run_reviews import report_rows
            return Response(render(result,events,format,report_rows(s,user['uid'],sid,rid)),media_type=('text/html' if format=='html' else 'text/markdown')+'; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="run-{rid}.{format}"','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"})
        data=evidence(s,row);view=data.get('presentation',{});state=runs.public(row)
        lines=['# 执行报告','', '结果结构：Legacy 历史结果；未自动转换为可信 Claim。','',f"- 执行编号：{rid}",f"- 状态：{ {'completed':'已完成','failed':'未完成','cancelled':'已取消'}.get(state['status'],'状态待确认')}",f"- 创建时间：{state['created_at']}",'']
        snapshot=s.decrypt(row['request_ciphertext'])
        if snapshot.get('agent_profile'):
            agent=snapshot['agent_profile']
            lines += ['## 助手版本','',f"- Agent：{agent['id']}",f"- 版本：{agent['version']}",f"- Profile SHA256：{agent['profile_sha256']}",'']
        if snapshot.get('task_response'):lines += [snapshot['task_response']['message'],'']
        if snapshot.get('historical_projection'):
            projection=snapshot['historical_projection']
            lines += ['## 历史资料来源','', '- 原始资料执行：'+projection['source_data_run_id'], '- 冻结投影摘要：'+projection['digest'], '']
            lines += ['- '+fact['statement']+'（来源：'+', '.join(fact['source_ids'])+'）' for fact in projection['claims']]
            lines += ['- '+gap for gap in projection['missing']]
            lines += ['', '资料性质与版本：'+json.dumps(projection['versions'],ensure_ascii=False), '本次说明未重新取数。','']
        if data.get('synthetic') is True or data.get('scenario'):lines += ['资料性质：已取得的来源资料。','']
        lines += ['## 已核对结论','']+[('- '+x['text']) for x in view.get('conclusions',[])]
        if not view.get('conclusions'):lines+=['暂无可导出的已核对结论。']
        lines+=['','## 过程','']+[f"- {x['name']}：{ {'completed':'已完成','failed':'未完成','cancelled':'已取消','pending':'等待处理','running':'执行中'}.get(x['status'],'状态待确认')}" for x in s.rows('SELECT name,status FROM run_events WHERE run_id=? ORDER BY sequence',(rid,))]
        diagram=view.get('diagram') or {}
        if diagram.get('version')=='1.0':
            lines += ['', '## 事件脉络图', '', diagram.get('legend','')]
            for page in diagram.get('pages',[]):
                lines += ['', '### 第 '+str(page['number'])+' 页', '', '```mermaid', page['mermaid'], '```']
                for node in page['nodes']:
                    lines += ['- '+node['number']+'：'+(node['time'] or '时间未明确')+'；'+node['subject']+'；'+node['event']+'；来源 '+', '.join(node['source_ids'])]
        lines+=['','## 来源','']
        for clue in view.get('clues',[]):
            for item in clue.get('evidence',[]):lines.append('- '+item['label']+'：'+item['content'])
        lines+=['','## 资料缺口','']+['- '+x for x in view.get('missing',[])]
        if row['error_code']:lines+=['- 执行未正常完成；不得将未取得资料补写为结论。']
        lines+=['','## 版本','',json.dumps({k:data[k] for k in ('scenario','snapshots','rule_version') if k in data},ensure_ascii=False)]
        s.audit(user['uid'],'run.report',rid,actor_role='user')
        return Response('\n'.join(lines)+'\n',media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="run-{rid}.md"'})
