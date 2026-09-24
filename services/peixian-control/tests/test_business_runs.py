import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from fastapi import HTTPException
from test_backend_v6 import v6
from test_control import create_user,login_user,P
from control import business_runs as runs
from control.run_scheduler import Coordinator


def setup_run(v6):
    s,app,c=v6
    u=create_user(c)
    client=login_user(app,u['username'])
    model=c.post(P+'/admin/models',json={'name':'DEMO','base_url':'http://model/v1','model_id':'demo'}).json()['id']
    c.patch(P+'/admin/users/'+u['id'],json={'model_ids':[model]})
    applied={'models':[{'id':model}],'plugins':[],'skills':[]}
    with s.tx() as db:db.execute("UPDATE runtimes SET status='ready',gate_policy='open',security_blocked=0,recovery_required=0,revision=1,applied_spec_ciphertext=? WHERE uid=?",(s.encrypt(applied),u['id']))
    user={'uid':u['id'],'role':'user','version':s.one('SELECT auth_version FROM users WHERE id=?',(u['id'],))['auth_version']}
    user['hash']=s.one('SELECT hash FROM auth WHERE uid=?',(u['id'],))['hash']
    data=runs.normalized({'text':'synthetic confidential input','model_id':model,'client_request_id':str(uuid.uuid4())})
    payload={'model':{'providerID':'peixian','modelID':model},'parts':[{'type':'text','text':data['text']}]}
    return s,app,c,client,user,data,payload,applied


def test_concurrent_admission_replay_busy_and_ownership(v6):
    s,app,c,client,user,data,payload,applied=setup_run(v6)
    try:
        def send(_):return runs.submit(s,user,'ses_demo',data,payload,applied,1)
        with ThreadPoolExecutor(max_workers=8) as pool:receipts=list(pool.map(send,range(8)))
        assert len({x['run_id'] for x in receipts})==1
        rid=receipts[0]['run_id']
        assert s.one('SELECT count(*) AS n FROM business_runs')['n']==1
        assert s.one('SELECT count(*) AS n FROM invocations')['n']==1
        with pytest.raises(HTTPException) as exc:runs.submit(s,user,'ses_demo',{**data,'text':'other'},payload,applied,1)
        assert exc.value.status_code==409
        with pytest.raises(HTTPException) as exc:runs.submit(s,user,'ses_demo',{**data,'client_request_id':str(uuid.uuid4())},payload,applied,1)
        assert exc.value.detail['code']=='session_busy'
        assert client.get(P+'/sessions/ses_demo/runs/'+rid).json()['status']=='queued'
        assert client.get(P+'/sessions/ses_demo/runs/'+rid+'/report').status_code==409
        create_user(c,'person-b');b=login_user(app,'person-b')
        try:
            for suffix in ('','/events','/evidence','/report'):assert b.get(P+'/sessions/ses_demo/runs/'+rid+suffix).status_code==404
        finally:b.__exit__(None,None,None)
        detail=c.get(P+'/admin/invocations').json()['items'][0]
        assert data['text'] not in json.dumps(detail)
        assert client.get(P+'/admin/invocations').status_code==403
        assert c.get(P+'/admin/invocations/export').content.startswith(b'\xef\xbb\xbf')
    finally:client.__exit__(None,None,None)


def test_probe_failure_can_retry_but_lost_dispatch_never_resends(v6):
    s,app,c,client,user,data,payload,applied=setup_run(v6)
    try:
        # Stop background coordinator so each network boundary is deterministic.
        c.portal.call(app.state.run_coordinator.close)
        rid=runs.submit(s,user,'ses_demo',data,payload,applied,1)['run_id']
        calls=[];phase=['probe_fail']
        def transport(request):
            calls.append((request.method,request.url.path))
            if phase[0]=='probe_fail':raise httpx.ConnectError('offline',request=request)
            if request.method=='POST':raise httpx.ReadTimeout('response lost',request=request)
            return httpx.Response(200,json={'protocol':'durable_run_v1','receipt':None})
        old=app.state.http;app.state.http=httpx.AsyncClient(transport=httpx.MockTransport(transport))
        coord=Coordinator(app)
        def step():c.portal.call(coord.step,s.one('SELECT * FROM business_runs WHERE id=?',(rid,)))
        try:
            step();assert s.one('SELECT status FROM business_runs WHERE id=?',(rid,))['status']=='queued'
            phase[0]='lost';step()
            assert s.one('SELECT status FROM business_runs WHERE id=?',(rid,))['status']=='reconciling'
            for _ in range(3):step()
            assert len([x for x in calls if x[0]=='POST'])==1
            assert s.one('SELECT state FROM run_deliveries WHERE run_id=?',(rid,))['state']=='sending'
        finally:c.portal.call(app.state.http.aclose);app.state.http=old
    finally:client.__exit__(None,None,None)


def test_completed_without_browser_and_cancel_before_dispatch(v6):
    s,app,c,client,user,data,payload,applied=setup_run(v6)
    try:
        c.portal.call(app.state.run_coordinator.close)
        accepted=runs.submit(s,user,'ses_demo',data,payload,applied,1);rid=accepted['run_id'];mid=accepted['message_id'];posted=[]
        def transport(request):
            if request.method=='POST':posted.append(request.url.path);return httpx.Response(204)
            if request.url.path.endswith('/message'):
                return httpx.Response(200,json=[{'info':{'id':mid,'role':'user','time':{'created':1000}},'parts':[]},{'info':{'id':'msg_result','role':'assistant','time':{'created':1000,'completed':2000},'finish':'stop'},'parts':[{'type':'text','text':'not evidence'},{'type':'analysis_result','data':{'fake':True}}]}])
            return httpx.Response(200,json={'protocol':'durable_run_v1','receipt':{'id':rid,'session_id':'ses_demo','message_id':mid,'state':'finished'} if posted else None})
        old=app.state.http;app.state.http=httpx.AsyncClient(transport=httpx.MockTransport(transport))
        try:
            c.portal.call(Coordinator(app).step,s.one('SELECT * FROM business_runs WHERE id=?',(rid,)))
            row=s.one('SELECT * FROM business_runs WHERE id=?',(rid,))
            assert row['status']=='completed' and row['result_ciphertext'] is None
            assert client.get(P+'/sessions/ses_demo/runs/'+rid+'/events').json()['total']==2
            assert client.get(P+'/sessions/ses_demo/runs/'+rid+'/report').status_code==200
            other=runs.submit(s,user,'ses_demo',{**data,'client_request_id':str(uuid.uuid4())},payload,applied,1)['run_id']
            assert client.post(P+'/sessions/ses_demo/runs/'+other+'/abort').status_code==202
            c.portal.call(Coordinator(app).step,s.one('SELECT * FROM business_runs WHERE id=?',(other,)))
            assert s.one('SELECT status FROM business_runs WHERE id=?',(other,))['status']=='cancelled'
            assert len(posted)==1
        finally:c.portal.call(app.state.http.aclose);app.state.http=old
    finally:client.__exit__(None,None,None)


def test_step_updates_advance_incremental_cursor_without_duplicate_step(v6):
    s,app,c,client,user,data,payload,applied=setup_run(v6)
    try:
        rid=runs.submit(s,user,'ses_steps',data,payload,applied,1)['run_id']
        runs.event(s,rid,'tool1','plugin','调用已授权插件','running',100)
        first=client.get(P+'/sessions/ses_steps/runs/'+rid+'/events').json()['items'][0]
        runs.event(s,rid,'tool1','plugin','调用已授权插件','completed',100,102)
        changed=client.get(P+'/sessions/ses_steps/runs/'+rid+'/events?after='+str(first['sequence'])).json()['items']
        assert len(changed)==1 and changed[0]['id']==first['id'] and changed[0]['status']=='completed'
        runs.event(s,rid,'tool1','plugin','调用已授权插件','completed',100,102)
        assert s.one('SELECT count(*) AS n FROM run_events WHERE run_id=?',(rid,))['n']==1
        assert client.get(P+'/sessions/ses_steps/runs/'+rid+'/events?after='+str(changed[0]['sequence'])).json()['items']==[]
    finally:client.__exit__(None,None,None)


def test_run_freezes_canonical_evidence_and_projects_only_server_result(v6,monkeypatch):
    from test_scenario_facts import messages
    from control.run_scheduler import track_messages
    from control.run_api import attach_results
    from control.scenario_facts import PREPARE,CHECK
    monkeypatch.setattr('control.scenario_evidence.permitted',lambda store,uid:True)
    s,app,c,client,user,data,payload,applied=setup_run(v6)
    try:
        applied['plugins']=[{'id':'demo-plugin','version':'1.3.0','manifest':{'tools':[PREPARE,CHECK]}}]
        accepted=runs.submit(s,user,'ses_facts',data,payload,applied,1)
        row=runs.owned(s,user['uid'],'ses_facts',accepted['run_id'])
        values=messages();values[0]['info']['id']=row['message_id']
        for i,message in enumerate(values[1:]):message['parts'][0]['id']='part_'+str(i)
        values.append({'info':{'id':'msg_final','role':'assistant','time':{'created':1000,'completed':2000},'finish':'stop'},'parts':[{'type':'analysis_result','data':{'conclusions':['untrusted']}}]})
        assert track_messages(s,row,values,{'state':'finished'})
        saved=s.decrypt(runs.owned(s,user['uid'],'ses_facts',row['id'])['result_ciphertext'])
        assert saved['schema']=='peixian.analysis-result' and saved['source_metadata']['snapshot_id']!=saved['source_metadata']['records_snapshot_id']
        assert 'untrusted' not in json.dumps(saved)
        assert saved['conclusion_sources'] and all(x['source_ids'] for x in saved['conclusion_sources'])
        projected=attach_results(s,user['uid'],[{'info':{'id':'msg_final'},'parts':[]}])
        assert projected[0]['parts'][0]['data']==saved
        report=client.get(P+'/sessions/ses_facts/runs/'+row['id']+'/report')
        assert ('已取得的来源资料' in report.text or '本次说明未重新取数' in report.text) and report.status_code==200
    finally:client.__exit__(None,None,None)
