import copy
import json
import pytest
from fastapi import HTTPException
from control import reply_presentation, answer_delivery, entity_graph, trusted_results, business_runs
from control.message_attachments import material
from test_native_tool_execution import native_candidate, ARGS
from test_provider_flow import provider, pid, tool, accept
from test_trusted_results import enabled, v6
from test_task_spec import task_env
from test_multi_agent import multi
from test_provider_contract_v2 import response
from control import native_tool_gate
from control.theft_provider_state import ProviderState


def test_document_material():
    text, meta = material('file-a', {'name':'../../a.md','status':'ready','chunks':[{'text':'hello | <script>', 'source':{'page':1}}]})
    assert meta['name']=='a.md' and meta['verified_source'] is False
    assert len(meta['content_sha256'])==64 and 'hello' in text
    from control.openapi import build_openapi
    from control.app import create_app
    from jsonschema import validate
    schema=build_openapi(create_app())['components']['schemas']['Message']['properties']['attachments']['items']
    validate({**meta,'status':'available'},schema)
    for value, code in [({'status':'parsing'},'file_not_ready'),({'status':'partial'},'file_truncated'),({'status':'ready','text':''},'file_text_empty'),({'status':'ready','chunks':['bad']},'file_parse_invalid')]:
        with pytest.raises(HTTPException) as exc:material('file-a',value)
        assert exc.value.detail['code']==code


def finished_source(env,monkeypatch):
    store=env[0];uid=env[4]['uid'];row=native_candidate(env,monkeypatch)
    snap=store.decrypt(store.one('SELECT request_ciphertext FROM business_runs WHERE id=?',(row['id'],))['request_ciphertext'])
    answer_delivery.freeze(snap,row['id'])
    with store.tx() as db:db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?',(store.encrypt(snap),row['id']))
    d=native_tool_gate.prepare(store,uid,'ses_multi',row['message_id'],'call-one',tool('tracks'),ARGS,1)
    native_tool_gate.approve(store,uid,row['id'],'call-one',d['digest'],{'verdict':'allow','reason_code':'aligned'},1)
    state=ProviderState(store);op=state.begin(uid,row['id'],1)
    state.reserve(uid,row['id'],1,op,'tracks');state.dispatch(uid,row['id'],1,op,'tracks')
    state.complete(uid,row['id'],1,op,'tracks','completed',response('tracks'));state.finish(uid,row['id'],1,op)
    return store,uid,business_runs.owned(store,uid,'ses_multi',row['id'])


def test_verified_increment_before_terminal_and_replay(provider,monkeypatch):
    s,uid,row=finished_source(provider,monkeypatch)
    first=answer_delivery.read(s,row)
    assert first['items'] and first['final'] is False
    assert all('当前展示' not in item['text'] for item in first['items'])
    assert '990000200001010014' not in json.dumps(first)
    assert answer_delivery.read(s,row,1)['items']==[]
    messages=answer_delivery.attach(s,uid,'ses_multi',[])
    assert messages==answer_delivery.attach(s,uid,'ses_multi',messages)
    business_runs.set_state(s,row['id'],'completed','completed')
    finalrow=business_runs.owned(s,uid,'ses_multi',row['id'])
    last=answer_delivery.read(s,finalrow)
    assert last['final'] and last['items']==first['items']
    result=trusted_results.read(s,uid,'ses_multi',row['id'])
    assert result['presentation']['clues']
    eid=result['presentation']['clues'][0]['evidence'][0]['id']
    detail=reply_presentation.source_detail(result,eid)
    assert detail['record']['record_id']==detail['evidence']['record_id']
    with pytest.raises(HTTPException):reply_presentation.source_detail(result,'unknown')
    graph=entity_graph.build(result,'ses_multi')
    assert graph['edges'] and all(e['type']=='source_record' for e in graph['edges'])
    assert not any(e['properties'].get('synthetic') for e in graph['edges'])
    broken=copy.deepcopy(result);broken['records'][0]['snapshot_id']='wrong'
    assert reply_presentation.build(broken)['clues']==[]
    broken=copy.deepcopy(result);broken['claims'][0]['verification_status']='unverified'
    assert reply_presentation.build(broken)['clues']==[]
    for suffix in ['answer-segments','result','sources/'+eid]:
        reply=provider[3].get('/api/console/v1/sessions/ses_multi/runs/'+row['id']+'/'+suffix)
        assert reply.status_code==200,reply.text
    from control.openapi import build_openapi
    from test_openapi import validator
    spec=build_openapi(provider[1]);validator(spec,'AnswerSegments').validate(last)
    validator(spec,'TrustedResultResponse').validate(result)
    import os
    if os.getenv('PX_ALIGNMENT_EXPORT'):
        from pathlib import Path
        out=Path(os.environ['PX_ALIGNMENT_EXPORT'])
        (out/'openapi.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2))
        (out/'contract-samples.json').write_text(json.dumps({'notice':'隔离合成契约测试生成，非真实供应方接口验收','source':'test_reply_alignment9.py','result':result,'segments_before_terminal':first,'segments_final':last,'graph':graph},ensure_ascii=False,indent=2))
    from test_control import create_user, login_user
    create_user(provider[2], 'reply-other')
    other=login_user(provider[1], 'reply-other')
    try:
        for suffix in ('answer-segments','result','graphs','sources/'+eid):
            assert other.get('/api/console/v1/sessions/ses_multi/runs/'+row['id']+'/'+suffix).status_code==404
    finally:other.__exit__(None,None,None)
    old=copy.deepcopy(result);old['versions'].pop('reply_projection')
    assert not entity_graph.build(old,'ses_multi')['edges']


def test_unknown_never_publishes():
    snap={'native_calls':{'c':{'status':'unknown'}}};answer_delivery.freeze(snap,'r')
    answer_delivery.record(snap,{'id':'r'},'c')
    assert snap['answer_delivery']['segments']==[]


def test_segments_cancelled_replay_and_cross_account(provider,monkeypatch):
    s,uid,row=finished_source(provider,monkeypatch)
    first=answer_delivery.read(s,row)
    business_runs.set_state(s,row['id'],'cancelling','stopping')
    assert not answer_delivery.read(s,business_runs.owned(s,uid,'ses_multi',row['id']))['final']
    business_runs.set_state(s,row['id'],'cancelled','cancelled')
    ended=business_runs.owned(s,uid,'ses_multi',row['id'])
    assert answer_delivery.read(s,ended)['items']==first['items']
    assert answer_delivery.read(s,ended)['final']
    with pytest.raises(HTTPException) as exc:business_runs.owned(s,'another-account','ses_multi',row['id'])
    assert exc.value.status_code==404
    assert answer_delivery.attach(s,'another-account','ses_multi',[])==[]
    with pytest.raises(HTTPException):answer_delivery.read(s,ended,999)
    with pytest.raises(HTTPException):answer_delivery.read(s,ended,-1)
    from control.run_api import public
    status=public(s,ended)
    assert status['status_authority']=='run' and status['status_revision']>=2


def test_bad_completed_response_not_zero():
    snap={'native_calls':{'c':{'status':'completed','frozen':{'kind':'tracks'},'public_response':{'version':'bad','records':[],'returned_count':0}}}}
    answer_delivery.freeze(snap,'r');answer_delivery.record(snap,{'id':'r'},'c')
    assert snap['answer_delivery']['segments']==[]


def test_native_capability_selection(provider,monkeypatch):
    from control.capabilities import catalog
    from control.native_tool_gate import enabled as native_enabled
    s=provider[0];uid=provider[4]['uid'];native_candidate(provider,monkeypatch)
    monkeypatch.setenv('PX_THEFT_NATIVE_UIDS',uid)
    items=catalog(s,uid)
    assert all('selectable_in_message' in i for i in items)
    assert all(i['selection_mode']=='unavailable' for i in items if not i['available'])


def test_delivery_rejects_unconfirmed_version_and_forged_statement():
    result={'run_id':'r','records':[{'record_id':'x','module':'tracks','snapshot_id':'s','source_run_id':'r','fields':{'deviceId':'d'}}],
            'claims':[{'type':'fact','verification_status':'unverified','statement':'fabricated','source_run_id':'r','source_ids':['x'],'protected_fields':{'record_id':'x','snapshot_id':'s','fields':{'deviceId':'d'}},'claim_id':'c'}]}
    assert reply_presentation.build(result)['clues']==[]
    result['claims'][0]['verification_status']='approved';result['claims'][0]['protected_fields']['fields']={'deviceId':'different'}
    assert reply_presentation.build(result)['clues']==[]
