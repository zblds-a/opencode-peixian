import json
import uuid
import pytest
from fastapi import HTTPException
from control import theft_planner as planner,business_runs
from test_analysis_tasks import task_provider,original,new_task
from test_provider_flow import provider,enabled,v6,task_env,multi


def install_method(env):
    store=env[0];method=planner.SOFT_METHODS[0]
    skill={'id':'soft-method-test','name':'测试方法','content':method['content'],'version':1}
    with store.tx() as db:
        db.execute('INSERT INTO skills VALUES(?,?,?,?,?,1,1,?)',(skill['id'],env[4]['uid'],skill['name'],'测试',skill['content'],'[]'))
        env[-1]['skills'].append(skill)
        db.execute('UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?',(store.encrypt(env[-1]),env[4]['uid']))


def test_literal_slots_do_not_route_or_invent():
    values=planner.slots('经度116.1 纬度34.2 半径0.5公里，第2页，从2026-09-01 00:00:00到2026-09-02 00:00:00')
    fields={v['field']:v['value'] for v in values.values()}
    assert fields=={'lon':'116.1','lat':'34.2','radius_m':500,'page':2,'start':'2026-09-01 00:00:00','end':'2026-09-02 00:00:00'}
    with pytest.raises(HTTPException):planner.slots('半径100米 半径200米')
    with pytest.raises(HTTPException):planner.slots('半径100米',{'radius_m':200})
    assert {v['field']:v['value'] for v in planner.slots('开始时间：2026-09-01 00:00:00').values()}=={'start':'2026-09-01 00:00:00'}


def test_model_decision_cannot_enlarge_scope_or_filter():
    frozen={'capabilities':['incidents'],'text':'查询近期仅盗窃警情','slots':{},'source_refs':[]}
    proposal={'action':'query','kind':'incidents','slot_ids':{},'missing':[]}
    assert planner.decision(proposal,frozen)['action']=='clarify'
    frozen['text']='查询警情';proposal['slot_ids']={'radius_m':'invented'}
    with pytest.raises(HTTPException):planner.decision(proposal,frozen)
    proposal['kind']='night_detail'
    with pytest.raises(HTTPException):planner.decision(proposal,frozen)


def test_reservation_replay_budget_and_clarification(task_provider,monkeypatch):
    env=task_provider;store=env[0];user=env[4];original(env,monkeypatch)
    monkeypatch.setenv('PX_THEFT_PLANNER_UIDS',user['uid'])
    task=new_task(env);tid=task['analysis_task_id']
    request={'text':'帮我核对警情','client_request_id':str(uuid.uuid4()),'model_id':env[-1]['models'][0]['id']}
    call,fresh=planner.reserve(store,user,'ses_multi',tid,request,env[-1],1)
    assert fresh
    assert planner.reserve(store,user,'ses_multi',tid,request,env[-1],1)==(call,False)
    with pytest.raises(HTTPException):planner.reserve(store,user,'ses_multi',tid,{**request,'text':'别的目标'},env[-1],1)
    with pytest.raises(HTTPException):planner.reserve(store,user,'ses_multi',tid,{**request,'client_request_id':str(uuid.uuid4())},env[-1],1)
    result=planner.finish(store,user,'ses_multi',tid,call['id'],{'action':'clarify','kind':None,'slot_ids':{},'missing':['lon','lat','radius_m']})
    assert result['state']=='completed'
    receipt=planner.admit_call(store,user,'ses_multi',tid,call['id'],env[-1],1)
    assert planner.admit_call(store,user,'ses_multi',tid,call['id'],env[-1],1)==receipt
    run=business_runs.owned(store,user['uid'],'ses_multi',receipt['run_id'])
    assert run['status']=='completed'
    assert not store.one('SELECT 1 FROM run_deliveries WHERE run_id=?',(run['id'],))
    assert '请在下方回答' in store.decrypt(run['request_ciphertext'])['task_response']['message']
    question=planner.public_question(store,run)
    assert question=={'version':'theft-clarification-v1','id':call['id'],'missing':['lon','lat','radius_m']}
    with pytest.raises(HTTPException):planner.dismiss_question(store,'another-user','ses_multi',run['id'])
    assert planner.dismiss_question(store,user['uid'],'ses_multi',run['id'])=={'dismissed':True}
    assert planner.public_question(store,run) is None
    assert planner.dismiss_question(store,user['uid'],'ses_multi',run['id'])=={'dismissed':True}


@pytest.mark.anyio
async def test_model_continues_after_result_without_second_user_request(task_provider,monkeypatch):
    from types import SimpleNamespace
    import httpx
    from control.theft_provider_state import ProviderState
    from test_provider_contract_v2 import response
    env=task_provider;store=env[0];user=env[4];original(env,monkeypatch)
    monkeypatch.setenv('PX_THEFT_PLANNER_UIDS',user['uid'])
    tid=new_task(env)['analysis_task_id'];install_method(env)
    req={'text':'查询经度116.1 纬度34.2 半径500米的警情','model_id':env[-1]['models'][0]['id'],'client_request_id':str(uuid.uuid4())}
    call,_=planner.reserve(store,user,'ses_multi',tid,req,env[-1],1)
    refs={v['field']:k for k,v in call['slots'].items()}
    planner.finish(store,user,'ses_multi',tid,call['id'],{'action':'query','kind':'incidents','slot_ids':refs,'missing':[],'skill_id':planner.SOFT_METHODS[0]['id']})
    receipt=planner.admit_call(store,user,'ses_multi',tid,call['id'],env[-1],1)
    state=ProviderState(store);rid=receipt['run_id'];op=state.begin(user['uid'],rid,1)
    state.reserve(user['uid'],rid,1,op,'incidents');state.dispatch(user['uid'],rid,1,op,'incidents')
    state.complete(user['uid'],rid,1,op,'incidents','completed',response('incidents'));state.finish(user['uid'],rid,1,op)
    business_runs.set_state(store,rid,'completed','completed')
    from control.trusted_results import read
    record=read(store,user['uid'],'ses_multi',rid)['records'][0]
    named=planner.mentioned_sources(store,user['uid'],'ses_multi',tid,'继续核对 '+record['record_id'])
    assert len(named)==1 and named[0]['record_id']==record['record_id'] and named[0]['run_id']==rid
    with pytest.raises(HTTPException) as missing_source:
        planner.reserve(store,user,'ses_multi',tid,{'text':'来源记录编号：不存在的记录','model_id':env[-1]['models'][0]['id'],'client_request_id':str(uuid.uuid4())},env[-1],1)
    assert missing_source.value.detail['code']=='source_record_unavailable'
    calls=[]
    async def run(fn,*args):return fn(*args)
    def transport(request):
        body=json.loads(request.content);calls.append(body)
        assert body['input']['previous_result']['records']
        return httpx.Response(200,json={'content':json.dumps({'action':'stop','kind':None,'slot_ids':{},'missing':[]})})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        app=SimpleNamespace(state=SimpleNamespace(store=store,db_work=SimpleNamespace(run=run),http=client))
        await planner.continue_one(app)
        await planner.continue_one(app)
    assert len(calls)==1
    from control.analysis_tasks import view
    budget=view(store,user['uid'],'ses_multi',tid)['budget']
    assert budget['user_requests']==1 and budget['planning_calls']==2 and budget['data_dispatch_attempts']==1


def test_missing_and_omitted_fields_cannot_execute():
    frozen={'capabilities':['captures'],'text':'查询','slots':planner.slots('半径500米'),'source_refs':[],'skills':[{'method_id':None,'capabilities':['captures']}]}
    choice=planner.decision({'action':'query','kind':'captures','slot_ids':{'radius_m':'slot-1'},'missing':[]},frozen)
    assert choice['action']=='clarify' and 'start' in choice['missing']
    frozen={'capabilities':['incidents'],'text':'查询','slots':planner.slots('经度116.1 纬度34.2 半径500米 第2页'),'source_refs':[],'skills':[{'method_id':None,'capabilities':['incidents']}]}
    refs={v['field']:k for k,v in frozen['slots'].items() if v['field']!='page'}
    assert planner.decision({'action':'query','kind':'incidents','slot_ids':refs,'missing':[]},frozen)['action']=='clarify'


@pytest.fixture
def anyio_backend():return "asyncio"



def test_explanation_cannot_become_query_even_if_model_proposes_it():
    frozen={'capabilities':['tracks'],'text':'解释刚才的记录，不要重新查','slots':{},'source_refs':[]}
    proposal={'action':'query','kind':'tracks','slot_ids':{},'missing':[]}
    assert planner.decision(proposal,frozen)['action']=='explain'


def test_unknown_planning_keeps_count_without_automatic_retry(task_provider,monkeypatch):
    env=task_provider;store=env[0];user=env[4];original(env,monkeypatch)
    monkeypatch.setenv('PX_THEFT_PLANNER_UIDS',user['uid']);tid=new_task(env)['analysis_task_id']
    req={'text':'需要补充什么','client_request_id':str(uuid.uuid4()),'model_id':env[-1]['models'][0]['id']}
    call,_=planner.reserve(store,user,'ses_multi',tid,req,env[-1],1)
    planner.failed_call(store,user['uid'],'ses_multi',tid,call['id'],'planning_unconfirmed')
    prior,fresh=planner.reserve(store,user,'ses_multi',tid,req,env[-1],1)
    assert not fresh and prior['state']=='unknown'
    from control.analysis_tasks import view
    assert view(store,user['uid'],'ses_multi',tid)['budget']['planning_calls']==1



@pytest.mark.anyio
async def test_cancelled_planning_never_creates_data_run(task_provider,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    env=task_provider;store=env[0];user=env[4];original(env,monkeypatch)
    monkeypatch.setenv('PX_THEFT_PLANNER_UIDS',user['uid']);tid=new_task(env)['analysis_task_id']
    req={'text':'核对资料','analysis_task_id':tid,'client_request_id':str(uuid.uuid4()),'model_id':env[-1]['models'][0]['id']}
    async def work(fn,*args):return fn(*args)
    async def post(*args,**kwargs):raise asyncio.CancelledError()
    app=SimpleNamespace(state=SimpleNamespace(store=store,db_work=SimpleNamespace(run=work),http=SimpleNamespace(post=post)))
    with pytest.raises(asyncio.CancelledError):await planner.plan_message(app,user,'ses_multi',req,env[-1],1)
    from control.analysis_tasks import view
    result=view(store,user['uid'],'ses_multi',tid)
    assert result['planning'][0]['status']=='unknown'
    assert result['budget']['planning_calls']==1 and result['budget']['data_steps']==0



def test_direction_change_keeps_history_but_not_unrequested_incident_filters():
    frozen={'capabilities':['incidents'],'text':'查这个选定位置的警情','slots':{'r':{'field':'radius_m','value':500},'t':{'field':'start','value':'2026-09-20 00:00:00'}},'explicit_fields':[], 'source_refs':[{'run_id':'selected'}],'skills':[{'method_id':'method','capabilities':['incidents']}]}
    proposal={'action':'query','kind':'incidents','slot_ids':{'radius_m':'r'},'missing':[],'skill_id':'method'}
    result=planner.decision(proposal,frozen)
    assert result['action']=='query' and result['query']=={'radius_m':500,'page':1}
    frozen['explicit_fields']=['start']
    assert planner.decision(proposal,frozen)['action']=='clarify'
