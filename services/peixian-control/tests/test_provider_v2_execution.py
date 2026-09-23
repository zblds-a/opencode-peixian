import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException
from test_provider_flow import provider, enabled, v6, task_env, multi, accept, pid, tool
from test_provider_contract_v2 import ID, REF, LIMITS, query, response
from shared import theft_provider_v2 as adapter
from control.data_plugin_policy import ACTIVE_KINDS
from control import provider_contracts, business_runs, trusted_results
from control.theft_provider_state import ProviderState
from test_multi_agent import prepare,submit
from control.theft_provider_flow import preview


def candidate(env,monkeypatch,kind):
    store=env[0];uid=env[4]['uid'];_,_,row,snapshot=accept(env)
    applied=env[-1]
    manifest={'tools':[tool(kind)],'connections':{'provider':{'description':'contract test'}}}
    plugin={'id':pid(kind),'version':'2.0.0','options':{},'manifest':manifest}
    applied['plugins']=[p for p in applied['plugins'] if p['id']!=pid(kind)]+[plugin]
    with store.tx() as db:
        db.execute('INSERT INTO plugins VALUES(?,?,?,?,?,?,?,1)',(pid(kind),'2.0.0',kind,'',json.dumps(manifest),'unused','0'*64))
        db.execute('INSERT OR REPLACE INTO installs(uid,plugin,version,enabled,config) VALUES(?,?,?,1,?)',(uid,pid(kind),'2.0.0',store.encrypt({})))
        db.execute("INSERT OR IGNORE INTO grants VALUES(?,'plugin',?)",(uid,pid(kind)))
        for cid,auth in [('police-test','none'),('warning-test','bearer')]:
            db.execute('INSERT INTO connections VALUES(?,?,?,1)',(cid,json.dumps({'enabled':True,'auth_type':auth}),store.encrypt('test-only')))
        group=adapter.CATALOG[kind][3]
        db.execute('INSERT INTO plugin_connections VALUES(?,?,?,?)',(pid(kind),'2.0.0','provider',group+'-test'))
        db.execute('UPDATE runtimes SET applied_spec_ciphertext=? WHERE uid=?',(store.encrypt(applied),uid))
    config={'enabled':True,'users':[uid],'environment':'acceptance_real','acceptance_scope_confirmed':True,'limits':LIMITS,'connections':{'police':'police-test','warning':'warning-test'},'approved_bbox':[116,34,117,35],'approved_identity_hashes':[hmac.new(store.worker_key.encode(),adapter.canonical([uid,ID]).encode(),hashlib.sha256).hexdigest()]}
    monkeypatch.setenv('PX_THEFT_REAL_CONFIG',json.dumps(config))
    plan=provider_contracts.freeze(store,uid,kind,query(kind),{REF:ID},applied)
    snapshot['provider_plan']=plan
    snapshot['data_environment']='acceptance_real'
    snapshot['task_spec'].update(methods=[kind],target_refs=[REF])
    snapshot['allowed_capabilities']=[pid(kind)];snapshot['allowed_tools']=[tool(kind)]
    snapshot['payload']['tools']={'*':False,tool(kind):True}
    with store.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(store.encrypt(snapshot),row['id']))
    return row,plan


@pytest.mark.parametrize('kind',ACTIVE_KINDS)
def test_v2_receipt_encrypted_and_public_result_redacted(provider,monkeypatch,kind):
    store=provider[0];uid=provider[4]['uid'];row,plan=candidate(provider,monkeypatch,kind)
    state=ProviderState(store);op=state.begin(uid,row['id'],1)
    assert state.reserve(uid,row['id'],1,op,kind)
    state.dispatch(uid,row['id'],1,op,kind)
    assert state.complete(uid,row['id'],1,op,kind,'completed',response(kind))=='completed'
    visible=state.read(uid,row['id'],1)['state']
    assert ID not in json.dumps(visible) and 'deductScore' not in json.dumps(visible)
    state.finish(uid,row['id'],1,op);business_runs.set_state(store,row['id'],'completed','completed')
    result=trusted_results.read(store,uid,'ses_multi',row['id'])
    assert result['records'] and result['data_environment']=='acceptance_real'
    assert ID not in json.dumps(result) and 'deductScore' not in json.dumps(result)
    assert result['versions']['provider_contract']==adapter.VERSION


def test_binding_revocation_stops_reserved_query(provider,monkeypatch):
    store=provider[0];uid=provider[4]['uid'];row,_=candidate(provider,monkeypatch,'tracks')
    state=ProviderState(store);op=state.begin(uid,row['id'],1)
    state.reserve(uid,row['id'],1,op,'tracks')
    with store.tx() as db:db.execute("UPDATE connections SET revision=2 WHERE id='police-test'")
    with pytest.raises(HTTPException):state.dispatch(uid,row['id'],1,op,'tracks')
    assert state.read(uid,row['id'],1)['state']['modules']['tracks']['dispatch_attempts']==0


def test_real_gate_closed_by_default(provider,monkeypatch):
    monkeypatch.delenv('PX_THEFT_REAL_CONFIG',raising=False)
    with pytest.raises(HTTPException) as exc:provider_contracts.settings(provider[4]['uid'])
    assert exc.value.status_code==409


def test_missing_warning_connection_does_not_block_police(provider,monkeypatch):
    store=provider[0];uid=provider[4]['uid'];row,plan=candidate(provider,monkeypatch,'tracks')
    config=json.loads(__import__('os').environ['PX_THEFT_REAL_CONFIG']);del config['connections']['warning']
    monkeypatch.setenv('PX_THEFT_REAL_CONFIG',json.dumps(config))
    assert provider_contracts.freeze(store,uid,'tracks',query('tracks'),{REF:ID},provider[-1])['connection_id']=='police-test'


def test_preview_ticket_and_admission_do_not_expose_identity_to_model(provider,monkeypatch):
    store=provider[0];uid=provider[4]['uid'];row,_=candidate(provider,monkeypatch,'tracks')
    state=ProviderState(store);op=state.begin(uid,row['id'],1);state.finish(uid,row['id'],1,op)
    business_runs.set_state(store,row['id'],'failed','failed')
    q=query('tracks');q.pop('person_ref')
    signed=preview(store,uid,'ses_multi',{'kind':'tracks','query':q,'person_identity':ID,'contract_version':adapter.VERSION},provider[-1],1)
    assert ID not in json.dumps(signed)
    request,task=prepare(provider,'theft-assistant','查询 '+ID+' 的指定轨迹',provider_query={k:signed[k] for k in ('plan','confirmation')})
    provider[-2]['parts']=[{'type':'text','text':request['text']}]
    receipt,new,snapshot=submit(provider,request,task)
    assert ID not in json.dumps(snapshot['payload'])
    assert snapshot['provider_plan']['request']['json']['certificateNo']==ID
    assert business_runs.replay(store,uid,'ses_multi',request)==receipt
    with pytest.raises(HTTPException):
        prepare(provider,'theft-assistant',sid='other-session',provider_query={k:signed[k] for k in ('plan','confirmation')})
