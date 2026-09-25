import copy
import pytest
from fastapi import HTTPException
from test_provider_flow import provider
from test_multi_agent import multi
from test_task_spec import task_env
from test_trusted_results import enabled,v6
from test_native_tool_execution import native_candidate, ARGS, tool
from test_provider_contract_v2 import response
from control import business_runs, native_tool_gate, trusted_results
from control.theft_provider_state import ProviderState
from control.conversation_completion import finish_dismissed, VERSION


def setup_run(provider,monkeypatch):
    s=provider[0];u=provider[4]['uid'];r=native_candidate(provider,monkeypatch)
    d=native_tool_gate.prepare(s,u,'ses_multi',r['message_id'],'call-one',tool('tracks'),ARGS,1)
    native_tool_gate.approve(s,u,r['id'],'call-one',d['digest'],{'verdict':'allow','reason_code':'aligned'},1)
    state=ProviderState(s);op=state.begin(u,r['id'],1)
    state.reserve(u,r['id'],1,op,'tracks');state.dispatch(u,r['id'],1,op,'tracks')
    state.complete(u,r['id'],1,op,'tracks','completed',response('tracks'));state.finish(u,r['id'],1,op)
    snap=s.decrypt(s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(r['id'],))['request_ciphertext'])
    snap['clarification_completion_version']=VERSION
    snap.setdefault('payload',{}).setdefault('tools',{})['question']=True
    snap['native_pending_questions']={'q':{'kind':'captures','status':'rejected'}}
    from control.answer_delivery import freeze,record
    freeze(snap,r['id']);record(snap,r,'call-one')
    with s.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(s.encrypt(snap),r['id']))
    return s,u,r,snap


def messages(r):
    return [{'info':{'role':'assistant','parentID':r['message_id']},'parts':[{'type':'tool','tool':'question','state':{'status':'error','error':'The user dismissed this question'}}]}]


def test_cancel_preserves_sources_and_is_idempotent(provider,monkeypatch):
    s,u,r,snap=setup_run(provider,monkeypatch)
    assert finish_dismissed(s,r,messages(r))
    result=trusted_results.read(s,u,'ses_multi',r['id'])
    assert result['records'] and result['answer']['status']=='partial'
    assert s.one('SELECT status FROM business_runs WHERE id=?',(r['id'],))['status']=='completed'
    frozen=s.decrypt(s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(r['id'],))['request_ciphertext'])
    assert frozen['answer_delivery']['final'] and len(frozen['answer_delivery']['segments'])==2
    assert not finish_dismissed(s,r,messages(r))


@pytest.mark.parametrize('case',['unknown','cancel','error','other_parent','legacy'])
def test_no_false_completion(provider,monkeypatch,case):
    s,u,r,snap=setup_run(provider,monkeypatch);m=messages(r)
    if case=='unknown':snap['native_calls']['call-one']['status']='unknown'
    if case=='legacy':snap.pop('clarification_completion_version')
    if case=='error':m[0]['info']['error']={'name':'ProviderError'}
    if case=='other_parent':m[0]['info']['parentID']='another-message'
    with s.tx() as db:
        db.execute('UPDATE business_runs SET request_ciphertext=?,cancel_requested=? WHERE id=?',(s.encrypt(snap),int(case=='cancel'),r['id']))
    assert not finish_dismissed(s,r,m)


def test_live_sources_stable_across_appends_and_finalization(provider,monkeypatch):
    from control.live_sources import projection,reference
    from control.analysis_tasks import source
    from control.native_precheck_questions import list_spatial_sources
    s,u,r,snap=setup_run(provider,monkeypatch)
    result=projection(s,u,'ses_multi',r['id']);ref=reference(result,result['records'][0])
    assert source(s,u,'ses_multi',ref,'acceptance_real')[0]==result['records'][0]
    assert list_spatial_sources(s,u,'ses_multi',task_id=snap['native_tool_context']['task_id'])[0]['ref']==ref
    assert list_spatial_sources(s,u,'ses_multi',task_id='other-task')==[]
    snap['native_calls']['second']=copy.deepcopy(snap['native_calls']['call-one'])
    with s.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(s.encrypt(snap),r['id']))
    assert source(s,u,'ses_multi',ref,'acceptance_real')[0]['record_id']==ref['record_id']
    business_runs.set_state(s,r['id'],'completed','completed')
    assert source(s,u,'ses_multi',ref,'acceptance_real')[0]['record_id']==ref['record_id']
    with pytest.raises(HTTPException):source(s,'another-account','ses_multi',ref,'acceptance_real')
    with pytest.raises(HTTPException):source(s,u,'ses_multi',{**ref,'snapshot_id':'forged'},'acceptance_real')


def test_question_has_clear_cancelled_label():
    from control.execution_view import observed
    p=messages({'message_id':'m'})[0]['parts'][0]
    v=observed({},p)
    assert v['name']=='补充查询条件' and v['status']=='cancelled'
    p['state']['error']='network error'
    assert observed({},p)['status']=='failed'


def test_context_does_not_request_all_tools():
    from control.native_tool_scope import model_context
    s=model_context({'scope_version':1,'confirmed':{},'source_refs':[], 'person_case_plan':{'items':[{'kind':'tracks'}]}})
    assert '打满八类' not in s and 'person_case_plan' not in s
    assert '取消补充' in s


def test_capture_time_is_not_track_time():
    from control.native_tool_scope import resolve_arguments,arguments
    c={'confirmed':{'start':ARGS['start'],'end':ARGS['end'],'radius_m':500},'source_refs':[{'record_id':'r'}],
       'capture_scope_version':'capture-purpose-v1','capture_conditions':{}}
    assert not resolve_arguments('captures',{},c)
    with pytest.raises(HTTPException) as exc:arguments('captures',{'start':ARGS['start'],'end':ARGS['end'],'radius_m':500},c)
    assert set(exc.value.detail['field_errors'])=={'start','end','radius_m'}
    c['capture_conditions']=copy.deepcopy(c['confirmed'])
    assert arguments('captures',{},c)['start']==ARGS['start']


def test_native_binding_uses_profile_prompt():
    from control.agents.runtime import bind
    from control.agents.registry import require
    profile=require('theft-assistant');p={}
    bind(p,profile,None,[])
    assert profile.prompt in p['system']
    assert profile.data['version']=='3.4.0'
    assert '不要求八项全查' in p['system']


def test_coordinator_closes_dismissed_question_without_new_post(provider,monkeypatch):
    import httpx
    from control.run_scheduler import Coordinator
    from control.store import now
    s,u,r,snap=setup_run(provider,monkeypatch)
    app=provider[1];client=provider[2]
    client.portal.call(app.state.run_coordinator.close)
    with s.tx() as db:db.execute("UPDATE run_deliveries SET state='admitted' WHERE run_id=?",(r['id'],))
    m=messages(r);m[0]['info'].update(id='msg_question',finish='tool-calls',time={'created':1000,'completed':2000})
    m[0]['parts'][0].update(id='part_question',callID='call_question')
    values=[{'info':{'id':r['message_id'],'role':'user'},'parts':[]}]+m
    posts=[]
    def transport(req):
        if req.method=='POST':posts.append(str(req.url));return httpx.Response(500)
        if req.url.path.endswith('/message'):return httpx.Response(200,json=values)
        return httpx.Response(200,json={'protocol':'durable_run_v1','receipt':{'id':r['id'],'session_id':r['session_id'],'message_id':r['message_id'],'state':'finished'}})
    old=app.state.http;app.state.http=httpx.AsyncClient(transport=httpx.MockTransport(transport))
    try:client.portal.call(Coordinator(app).step,s.one('SELECT * FROM business_runs WHERE id=?',(r['id'],)))
    finally:client.portal.call(app.state.http.aclose);app.state.http=old
    assert posts==[]
    row=s.one('SELECT * FROM business_runs WHERE id=?',(r['id'],))
    assert row['status']=='completed'
    from control.run_outcome import project
    assert '补充查询已停止' in project(s,row)['label']
    event=s.one("SELECT * FROM run_events WHERE run_id=? AND event_key='part_question'",(r['id'],))
    assert event['status']=='cancelled' and event['name']=='补充查询条件'
