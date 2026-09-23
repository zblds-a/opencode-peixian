import copy,json,uuid
import pytest
from fastapi import HTTPException
from test_trusted_results import enabled,v6
from test_task_spec import task_env
from test_multi_agent import multi,prepare,submit
from control.theft_provider_flow import preview,pid,tool
from control.theft_provider_state import ProviderState
from control import business_runs as runs, trusted_results
from shared.theft_provider import CATALOG,fixture_response
from control.data_plugin_policy import ACTIVE_KINDS

@pytest.fixture
def provider(enabled,monkeypatch):
    s,app,c,client,user,data,payload,applied=enabled
    monkeypatch.setenv('PX_THEFT_PROVIDER_UIDS',user['uid'])
    with s.tx() as db:
        for kind in CATALOG:
            manifest={'tools':[tool(kind)]}
            applied['plugins'].append({'id':pid(kind),'version':'1.0.0','options':{},'manifest':manifest})
            db.execute('INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)',(pid(kind),'1.0.0',kind,'',json.dumps(manifest),'unused','0'*64))
            db.execute('INSERT INTO installs(uid,plugin,version,enabled,config) VALUES(?,?,?,1,?)',(user['uid'],pid(kind),'1.0.0',s.encrypt({})))
            db.execute("INSERT INTO grants VALUES(?,'plugin',?)",(user['uid'],pid(kind)))
        db.execute('UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?',(s.encrypt(applied),user['uid']))
    return enabled

def query(kind):
    if kind in ('warning_detail','warning_logs'):return {'subject':'DEMO-PERSON-001'}
    q={'start':'2026-09-20 00:00:00','end':'2026-09-20 23:59:59'}
    if kind in ('tracks','warnings'):q['subject']='DEMO-PERSON-001'
    if kind in ('incidents','captures'):q.update(center='DEMO-LOCATION-A',radius_m=500)
    return q

def accept(env,kind='incidents',sid='ses_multi'):
    signed=preview(env[0],env[4]['uid'],sid,{'kind':kind,'query':query(kind)},env[-1],1)
    req,task=prepare(env,'theft-assistant','执行已确认资料查询',sid=sid,provider_query={k:signed[k] for k in ('plan','confirmation')})
    receipt,row,snap=submit(env,req,task,sid=sid)
    return req,receipt,row,snap

@pytest.mark.parametrize('kind',[kind for kind in ACTIVE_KINDS if kind in CATALOG])
def test_provider_frozen_receipt_result(provider,kind):
    s=provider[0];uid=provider[4]['uid'];req,receipt,row,snap=accept(provider,kind)
    assert snap['answer_policy_version']=='controlled-zh-v1'
    state=ProviderState(s);op=state.begin(uid,row['id'],1)
    assert state.reserve(uid,row['id'],1,op,kind)
    assert not state.reserve(uid,row['id'],1,op,kind)
    value=fixture_response(kind,snap['provider_plan']['query'])
    assert state.complete(uid,row['id'],1,op,kind,'completed',value)=='completed'
    state.finish(uid,row['id'],1,op)
    runs.set_state(s,row['id'],'completed','completed')
    result=trusted_results.read(s,uid,'ses_multi',row['id'])
    assert result['answer']['items'] and result['records']
    assert result['claims'][1]['verification_status']=='approved'
    assert 'deductScore' not in json.dumps(result)
    assert result['data_usage']['new_call_count']==1
    assert runs.replay(s,uid,'ses_multi',req)==receipt
    assert json.loads(s.one('SELECT actual_plugins FROM invocations WHERE run_id=?',(row['id'],))['actual_plugins'])==[pid(kind)]
    assert provider[3].get('/api/console/v1/sessions/ses_multi/runs/'+row['id']+'/report?format=html').status_code==200

@pytest.mark.parametrize('alter',['subject','kind','confirmation','foreign_session'])
def test_confirmation_tamper(provider,alter):
    signed=preview(provider[0],provider[4]['uid'],'ses_multi',{'kind':'tracks','query':query('tracks')},provider[-1],1)
    v={k:signed[k] for k in ('plan','confirmation')}
    if alter=='subject':v['plan']['query']['subject']='DEMO-PERSON-002'
    if alter=='kind':v['plan']['kind']='warnings'
    if alter=='confirmation':v['confirmation']='x'
    with pytest.raises(HTTPException):prepare(provider,'theft-assistant',provider_query=v,sid='foreign' if alter=='foreign_session' else 'ses_multi')

def test_unknown_never_retries_and_revoked_cannot_call(provider):
    s=provider[0];uid=provider[4]['uid'];_,_,row,snap=accept(provider,'tracks')
    state=ProviderState(s);op=state.begin(uid,row['id'],1);state.reserve(uid,row['id'],1,op,'tracks');state.finish(uid,row['id'],1,op)
    op=state.begin(uid,row['id'],1);assert not state.reserve(uid,row['id'],1,op,'tracks')
    assert state.read(uid,row['id'],1)['state']['modules']['tracks']['status']=='unknown'
    with s.tx() as db:db.execute("DELETE FROM grants WHERE uid=? AND resource=?",(uid,pid('tracks')))
    with pytest.raises(HTTPException):state.check(uid,row['id'],1,op)

def test_forged_frozen_request_rejected(provider):
    s=provider[0];_,_,row,snap=accept(provider,'tracks')
    snap['provider_plan']['request']['json']['certificateNo']='DEMO-PERSON-002'
    with s.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(s.encrypt(snap),row['id']))
    with pytest.raises(HTTPException):ProviderState(s).begin(provider[4]['uid'],row['id'],1)


def test_provider_history_does_not_requery_or_change_scope(provider):
    s=provider[0];uid=provider[4]['uid'];_,_,row,snap=accept(provider,'tracks')
    st=ProviderState(s);op=st.begin(uid,row['id'],1);st.reserve(uid,row['id'],1,op,'tracks')
    st.complete(uid,row['id'],1,op,'tracks','completed',fixture_response('tracks',snap['provider_plan']['query']));st.finish(uid,row['id'],1,op)
    runs.set_state(s,row['id'],'completed','completed')
    request,task=prepare(provider,'theft-assistant','解释已有结果');_,new,snapshot=submit(provider,request,task)
    assert new['status']=='completed' and not s.one('SELECT * FROM run_deliveries WHERE run_id=?',(new['id'],))
    result=trusted_results.read(s,uid,'ses_multi',new['id'])
    assert result['data_usage']['status']=='historical_evidence' and result['data_usage']['new_call_count']==0
    assert result['answer']['items'][1]['source_run_id']==row['id']
    request,task=prepare(provider,'theft-assistant','查另一个人今天的轨迹');_,new,_=submit(provider,request,task)
    result=trusted_results.read(s,uid,'ses_multi',new['id'])
    assert not result['records'] and result['answer']['status']=='needs_input'
    assert not s.one('SELECT * FROM run_deliveries WHERE run_id=?',(new['id'],))
    request,task=prepare(provider,'theft-assistant','解释已有结果');_,again,_=submit(provider,request,task)
    again_result=trusted_results.read(s,uid,'ses_multi',again['id'])
    assert not again_result['records']
    assert again_result['data_usage']['source_data_run_id']==new['id']


def test_provider_actual_http_admission(provider):
    import httpx
    s,app,c,client,user,data,payload,applied=provider
    old=app.state.http;calls=[]
    def upstream(req):
        calls.append(req.method)
        return httpx.Response(200,json={'protocol':'durable_run_v1','receipt':None} if '/internal/runtime/runs/' in req.url.path else {'id':'ses_provider_http','directory':'/workspace'})
    app.state.http=httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    try:
        base='/api/console/v1/sessions/ses_provider_http'
        signed=client.post(base+'/provider-query/preview',json={'kind':'incidents','query':query('incidents')})
        assert signed.status_code==200,signed.text
        body={**data,'agent_id':'theft-assistant','text':'查询已确认范围','client_request_id':str(uuid.uuid4()),'provider_query':{k:signed.json()[k] for k in ('plan','confirmation')}}
        r=client.post(base+'/messages',json=body);assert r.status_code==202,r.text
        assert client.post(base+'/messages',json=body).json()==r.json()
        snap=s.decrypt(s.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(r.json()['run_id'],))['request_ciphertext'])
        assert [k for k,v in snap['payload']['tools'].items() if v] == ['peixian_query_incidents']
        assert snap['provider_plan']['kind']=='incidents' and snap['answer_policy_version']=='controlled-zh-v1'
        assert set(calls)=={'GET'}
    finally:c.portal.call(app.state.http.aclose);app.state.http=old
