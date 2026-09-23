from types import SimpleNamespace
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway import facts_execution,theft_provider_execution


def test_public_fields_never_echo_sensitive_values():
    result=facts_execution.public_scope_fields({'field_errors':{'start':'secret','person_identity':'private identity','unknown':'injection'}})
    assert set(result)=={'start','person_identity'}
    assert 'secret' not in str(result) and 'private identity' not in str(result)


def test_empty_native_args_keep_identity_check_and_field_errors(monkeypatch):
    app=FastAPI();facts_execution.register(app)
    gate=SimpleNamespace(require_egress=lambda:None,boot_id='boot')
    app.state.runtime_management=SimpleNamespace(gate=gate)
    app.state.settings=SimpleNamespace(opencode_password='test',opencode_url='http://agent',control_url='http://control',runtime_key='test',runtime_id='runtime',revision=1)
    async def get(*args,**kwargs):
        return httpx.Response(200,request=httpx.Request('GET','http://agent'),json={'info':{'role':'assistant','sessionID':'session','parentID':'user'},'parts':[{'type':'tool','callID':'call','tool':'peixian_query_tracks','state':{'input':{}}}]})
    async def post(*args,**kwargs):
        assert kwargs['json']['action']=='native_prepare'
        return httpx.Response(409,json={'detail':{'code':'scope_missing','field_errors':{'start':'private','end':'private'}}})
    app.state.client=SimpleNamespace(get=get,post=post)
    async def native(request,app,value,rpc,parent,process):
        return await rpc('native_prepare')
    monkeypatch.setattr(theft_provider_execution,'execute_native',native)
    with TestClient(app) as client:
        body={'session_id':'session','message_id':'assistant','tool':'peixian_query_tracks','args':{},'call_id':'call'}
        response=client.post('/internal/facts/execute',json=body)
        assert response.status_code==409
        detail=response.json()['detail']
        assert detail['code']=='scope_missing' and set(detail['field_errors'])=={'start','end'}
        assert detail['dispatch_status']=='not_dispatched' and 'private' not in response.text
        body['call_id']='forged'
        assert client.post('/internal/facts/execute',json=body).status_code==409
