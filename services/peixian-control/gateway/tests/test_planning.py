import json
from types import SimpleNamespace
import httpx
import pytest
from fastapi import FastAPI
from gateway.planning import register


@pytest.mark.anyio
async def test_durable_planning_receipt_and_no_tools(tmp_path):
    app=FastAPI();register(app);calls=[];active=set()
    async def admit(kind,resource):active.add(resource);return resource
    def transport(request):
        body=json.loads(request.content);calls.append(body)
        assert str(request.url)=='http://model-relay:8081/v1/chat/completions'
        assert 'tools' not in body and body['stream'] is False
        assert body['max_tokens']==4096
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"action":"stop"}'}}]})
    app.state.settings=SimpleNamespace(revision=1,activity_root=tmp_path,relay_url='http://model-relay:8081')
    app.state.admission=SimpleNamespace(admit=admit,finish=active.remove,require_egress=lambda:None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as upstream:
        app.state.client=upstream
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            body={'call_id':'a'*32,'revision':1,'model_id':'allowed','system':'中文规划','input':{}}
            first=await client.post('/internal/runtime/planning',json=body)
            assert first.status_code==200
            assert (await client.post('/internal/runtime/planning',json=body)).json()==first.json()
            assert (await client.post('/internal/runtime/planning',json={**body,'model_id':'changed'})).status_code==409
    assert len(calls)==1 and not active


@pytest.mark.anyio
async def test_lost_planning_response_is_not_sent_again(tmp_path):
    app=FastAPI();register(app);calls=[];active=set()
    async def admit(kind,resource):active.add(resource);return resource
    def transport(request):calls.append(request);raise httpx.ReadTimeout('lost')
    app.state.settings=SimpleNamespace(revision=1,activity_root=tmp_path,relay_url='http://model-relay:8081')
    app.state.admission=SimpleNamespace(admit=admit,finish=active.remove,require_egress=lambda:None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as upstream:
        app.state.client=upstream
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://test') as client:
            body={'call_id':'b'*32,'revision':1,'model_id':'allowed','system':'中文规划','input':{}}
            assert (await client.post('/internal/runtime/planning',json=body)).status_code==500
            assert (await client.post('/internal/runtime/planning',json=body)).status_code==409
    assert len(calls)==1 and not active


@pytest.fixture
def anyio_backend():return "asyncio"
