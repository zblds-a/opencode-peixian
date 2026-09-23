import json
import pytest
from fastapi import HTTPException
from test_provider_flow import provider,accept,pid,tool
from test_trusted_results import enabled,v6
from test_task_spec import task_env
from test_multi_agent import multi
from test_provider_v2_execution import candidate
from test_provider_contract_v2 import ID,response
from control import native_tool_gate,native_tool_scope,trusted_results,business_runs
from control.theft_provider_state import ProviderState

TEXT='查询 990000200001010014 的轨迹，开始时间 2026-09-20 22:13:14，结束时间 2026-09-21 02:03:04'
ARGS={'person_identity':ID,'start':'2026-09-20 22:13:14','end':'2026-09-21 02:03:04'}

def native_candidate(env,monkeypatch):
    store=env[0];uid=env[4]['uid'];row,_=candidate(env,monkeypatch,'tracks')
    applied=env[-1];p=next(x for x in applied['plugins'] if x['id']==pid('tracks'))
    p['version']='3.0.0'
    with store.tx() as db:
        db.execute('INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)',(pid('tracks'),'3.0.0','轨迹资料','',json.dumps({'tools':[tool('tracks')],'connections':{'provider':{}}}),'unused','0'*64))
        db.execute('UPDATE installs SET version=? WHERE uid=? AND plugin=?',('3.0.0',uid,pid('tracks')))
        db.execute('INSERT INTO plugin_connections VALUES(?,?,?,?)',(pid('tracks'),'3.0.0','provider','police-test'))
        db.execute('UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?',(store.encrypt(applied),uid))
    snap=store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext'])
    snap.pop('provider_plan',None)
    snap['native_tool_context']=native_tool_scope.freeze_context(store,uid,'ses_multi',{'text':TEXT})
    snap['native_tool_policy']={'version':native_tool_gate.VERSION,'allowed_tools':[tool('tracks')],'revision':1}
    snap['native_calls']={}
    snap['data_environment']='acceptance_real'
    snap['task_spec']={'schema_version':'native-tools-v1','domain':'theft','agent_id':'theft-assistant','query_mode':'native','methods':[],'task_id':snap['native_tool_context']['task_id']}
    with store.tx() as db: db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(store.encrypt(snap),row['id']))
    return row

def test_native_tool_one_confirmed_call(provider,monkeypatch):
    store=provider[0];uid=provider[4]['uid'];row=native_candidate(provider,monkeypatch)
    decision=native_tool_gate.prepare(store,uid,'ses_multi',row['message_id'],'call-one',tool('tracks'),ARGS,1)
    assert decision['cached'] is False
    assert decision['review_input']['capability_name']
    assert decision['review_input']['person_identity_confirmed'] is True
    assert ID not in json.dumps(decision['review_input'])
    review=decision['review_input']
    ref=review['requested_values']['person_ref']
    assert review['identity_binding']=={'status':'matched','person_ref':ref}
    assert review['confirmed_values']['person_ref']==ref
    assert ref in review['user_request']
    assert review['requested_values']['start']==ARGS['start']
    assert review['contract_defaults']=={'track_types':[0,1,2]}
    assert review['version']=='native-intent-context-v2'
    assert native_tool_gate.approve(store,uid,row['id'],'call-one',decision['digest'],{'verdict':'allow','reason_code':'aligned'},1)['allowed']
    state=ProviderState(store);op=state.begin(uid,row['id'],1)
    assert state.reserve(uid,row['id'],1,op,'tracks')
    state.dispatch(uid,row['id'],1,op,'tracks')
    assert state.complete(uid,row['id'],1,op,'tracks','completed',response('tracks'))=='completed'
    state.finish(uid,row['id'],1,op)
    assert native_tool_gate.prepare(store,uid,'ses_multi',row['message_id'],'call-one',tool('tracks'),ARGS,1)['cached']
    business_runs.set_state(store,row['id'],'completed','completed')
    result=trusted_results.read(store,uid,'ses_multi',row['id'])
    assert result['records'] and result['data_usage']['new_call_count']==1
    assert result['narrative']['status']=='unverified'





def test_native_precheck_rejects_unconfirmed_scope(provider,monkeypatch):
    store=provider[0];uid=provider[4]['uid'];row=native_candidate(provider,monkeypatch)
    wrong={**ARGS,'end':'2026-09-21 04:03:04'}
    with pytest.raises(HTTPException) as exc:
        native_tool_gate.prepare(store,uid,'ses_multi',row['message_id'],'wrong-scope',tool('tracks'),wrong,1)
    assert exc.value.detail['code']=='scope_unconfirmed'
    assert not store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext'])['native_calls']


def test_native_review_rejection_and_no_replay(provider,monkeypatch):
    store=provider[0];uid=provider[4]['uid'];row=native_candidate(provider,monkeypatch)
    decision=native_tool_gate.prepare(store,uid,'ses_multi',row['message_id'],'denied-call',tool('tracks'),ARGS,1)
    assert not native_tool_gate.approve(store,uid,row['id'],'denied-call',decision['digest'],{'verdict':'clarify','reason_code':'ask_time'},1)['allowed']
    with pytest.raises(HTTPException) as exc:
        native_tool_gate.prepare(store,uid,'ses_multi',row['message_id'],'denied-call',tool('tracks'),ARGS,1)
    assert exc.value.detail['code']=='tool_call_unconfirmed'
    with pytest.raises(HTTPException): ProviderState(store).begin(uid,row['id'],1)


def test_native_review_revoked_before_dispatch(provider,monkeypatch):
    store=provider[0];uid=provider[4]['uid'];row=native_candidate(provider,monkeypatch)
    decision=native_tool_gate.prepare(store,uid,'ses_multi',row['message_id'],'revoked-call',tool('tracks'),ARGS,1)
    with store.tx() as db:
        db.execute('DELETE FROM grants WHERE uid=? AND kind=? AND resource=?',(uid,'plugin',pid('tracks')))
    with pytest.raises(HTTPException):
        native_tool_gate.approve(store,uid,row['id'],'revoked-call',decision['digest'],{'verdict':'allow','reason_code':'aligned'},1)
    snap=store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext'])
    assert snap['native_calls']['revoked-call']['status']=='review_pending'
    assert not snap.get('provider_state',{}).get('modules')


def test_changed_person_does_not_inherit_old_identity(provider,monkeypatch):
    store=provider[0];uid=provider[4]['uid'];row=native_candidate(provider,monkeypatch)
    prior=store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext'])['native_tool_context']
    continued=native_tool_scope.freeze_context(store,uid,'ses_multi',{'text':'换个人，继续查询轨迹'})
    assert continued['task_id']==prior['task_id']
    assert 'person_identity' not in continued['confirmed']
    assert not continued['source_refs']
    with pytest.raises(HTTPException):native_tool_scope.arguments('tracks',{'start':ARGS['start'],'end':ARGS['end']},continued)


def test_incident_filter_not_silently_dropped():
    context={'confirmed':{'lon':'116.1','lat':'34.1','radius_m':500},'source_refs':[],
             'current_text':'经度116.1 纬度34.1 半径500米',
             'constraints_text':'查询近期仅盗窃警情；经度116.1 纬度34.1 半径500米',
             'user_conditions':{'lon':'116.1','lat':'34.1','radius_m':500}}
    with pytest.raises(HTTPException) as exc:
        native_tool_scope.arguments('incidents',{'lon':'116.1','lat':'34.1','radius_m':500},context)
    assert exc.value.detail['code']=='unsupported_scope'


def test_native_two_distinct_tools_same_run(provider,monkeypatch):
    store=provider[0];uid=provider[4]['uid'];row=native_candidate(provider,monkeypatch)
    applied=provider[-1]
    manifest={'tools':[tool('incidents')],'connections':{'provider':{}}}
    applied['plugins']=[p for p in applied['plugins'] if p['id']!=pid('incidents')]+[{'id':pid('incidents'),'version':'3.0.0','options':{},'manifest':manifest}]
    with store.tx() as db:
        db.execute('INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)',(pid('incidents'),'3.0.0','警情资料','',json.dumps(manifest),'unused','0'*64))
        db.execute('UPDATE installs SET version=?,enabled=1 WHERE uid=? AND plugin=?',('3.0.0',uid,pid('incidents')))
        db.execute('INSERT INTO plugin_connections VALUES(?,?,?,?)',(pid('incidents'),'3.0.0','provider','police-test'))
        db.execute('UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?',(store.encrypt(applied),uid))
    snap=store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext'])
    snap['native_tool_policy']['allowed_tools'].append(tool('incidents'))
    snap['payload']['tools'][tool('incidents')]=True
    snap['native_tool_context']['confirmed'].update(lon='116.1',lat='34.1',radius_m=500)
    snap['native_tool_context']['current_text']+='；查询经度116.1纬度34.1半径500米周边警情'
    snap['native_tool_context']['constraints_text']=snap['native_tool_context']['current_text']
    with store.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(store.encrypt(snap),row['id']))
    state=ProviderState(store)
    for call,kind,args in [('track-call','tracks',ARGS),('incident-call','incidents',{'lon':'116.1','lat':'34.1','radius_m':500})]:
        item=native_tool_gate.prepare(store,uid,'ses_multi',row['message_id'],call,tool(kind),args,1)
        native_tool_gate.approve(store,uid,row['id'],call,item['digest'],{'verdict':'allow','reason_code':'aligned'},1)
        op=state.begin(uid,row['id'],1)
        assert state.reserve(uid,row['id'],1,op,kind)
        state.dispatch(uid,row['id'],1,op,kind)
        assert state.complete(uid,row['id'],1,op,kind,'completed',response(kind))=='completed'
        state.finish(uid,row['id'],1,op)
    business_runs.set_state(store,row['id'],'completed','completed')
    result=trusted_results.read(store,uid,'ses_multi',row['id'])
    assert {m['module'] for m in result['data_usage']['modules']}=={'tracks','incidents'}
    assert result['data_usage']['new_call_count']==2
    assert len(result['records'])==2


def test_newly_confirmed_filter_cannot_be_dropped():
    context={'confirmed':{'lon':'116.1','lat':'34.1','radius_m':500,'person_identity':ID},
             'source_refs':[],'current_text':'仅查询这名人员关联的警情',
             'constraints_text':'仅查询这名人员关联的警情',
             'user_conditions':{'person_identity':ID}}
    with pytest.raises(HTTPException) as exc:
        native_tool_scope.arguments('incidents',{'lon':'116.1','lat':'34.1','radius_m':500},context)
    assert exc.value.detail['code']=='unsupported_scope'


def test_native_scheduler_does_not_cancel_authorized_inflight_tool(provider,monkeypatch):
    from control.run_scheduler import track_messages
    store=provider[0];row=native_candidate(provider,monkeypatch)
    row=store.one('SELECT * FROM business_runs WHERE id=?',(row['id'],))
    values=[{'info':{'id':row['message_id'],'role':'user'},'parts':[]},
            {'info':{'id':'assistant-native','role':'assistant'},'parts':[{'id':'part-native','type':'tool','tool':tool('tracks'),'callID':'native-observed','state':{'status':'running','input':ARGS}}]}]
    assert not track_messages(store,row,values,{})
    assert store.one('SELECT cancel_requested FROM business_runs WHERE id=?',(row['id'],))['cancel_requested']==0
    values[1]['parts'][0].update(id='part-unavailable',tool='unauthorized_query')
    assert not track_messages(store,row,values,{})
    assert store.one('SELECT cancel_requested FROM business_runs WHERE id=?',(row['id'],))['cancel_requested']==1


def test_empty_review_closes_without_admitting_or_resending(provider,monkeypatch):
    store=provider[0];uid=provider[4]['uid'];row=native_candidate(provider,monkeypatch)
    p=native_tool_gate.prepare(store,uid,'ses_multi',row['message_id'],'review-empty',tool('tracks'),ARGS,1)
    native_tool_gate.review_failed(store,uid,row['id'],'review-empty',p['digest'],1)
    with pytest.raises(HTTPException):native_tool_gate.approve(store,uid,row['id'],'review-empty',p['digest'],{'verdict':'allow','reason_code':'late'},1)
    snap=store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext'])
    assert snap['native_calls']['review-empty']['dispatch_status']=='not_dispatched'
    assert 'provider_plan' not in snap


def test_display_identity_cannot_replace_raw_confirmed_parameter(provider,monkeypatch):
    store=provider[0];uid=provider[4]['uid'];row=native_candidate(provider,monkeypatch)
    wrong={**ARGS,'person_identity':'person-'+'a'*32}
    with pytest.raises(HTTPException) as exc:
        native_tool_gate.prepare(store,uid,'ses_multi',row['message_id'],'display-id',tool('tracks'),wrong,1)
    assert exc.value.detail['code']=='identity_parameter_invalid'
    snapshot=store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext'])
    assert snapshot['native_calls']=={}
    assert 'provider_plan' not in snapshot
    context=native_tool_scope.model_context(snapshot['native_tool_context'])
    assert ID in context and 'person_identity' in context
    assert '不要要求用户确认内部引用' in context


def test_review_context_redacts_other_identities_without_equating_them():
    ref='person-'+'a'*32
    value=native_tool_gate.redact('查询 '+ID+'，不要查询 990000200001010022',{ref:ID})
    assert ID not in value and '990000200001010022' not in value
    assert value.count(ref)==1 and '[其他身份已脱敏]' in value
