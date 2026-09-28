from types import SimpleNamespace
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.opencode_messages import is_synthetic_user, is_compaction_summary, origin_user_id
from shared.tool_failure import public
from gateway import facts_execution, theft_provider_execution
from control.app import public_messages
from control.theft_provider_result import sentence
from control import native_tool_gate
from test_native_tool_execution import native_candidate, ARGS
from test_provider_flow import provider, tool  # noqa: F401
from test_trusted_results import enabled, v6  # noqa: F401
from test_task_spec import task_env  # noqa: F401
from test_multi_agent import multi  # noqa: F401
from test_reply_alignment9 import finished_source


def compacted(user_id, final_finish='stop'):
    return [
        {'info': {'id': user_id, 'role': 'user', 'time': {'created': 1000}}, 'parts': [{'type': 'text', 'text': '确认'}]},
        {'info': {'id': 'msg_a1', 'role': 'assistant', 'parentID': user_id, 'time': {'created': 1001, 'completed': 1002}, 'finish': 'tool-calls'},
         'parts': [{'id': 'prt_1', 'type': 'tool', 'tool': tool('tracks'), 'callID': 'call-one', 'state': {'status': 'completed', 'input': ARGS}}]},
        {'info': {'id': 'msg_c', 'role': 'user', 'time': {'created': 1003}}, 'parts': [{'type': 'compaction', 'auto': True}]},
        {'info': {'id': 'msg_s', 'role': 'assistant', 'parentID': 'msg_c', 'mode': 'compaction', 'agent': 'compaction', 'summary': True,
                  'time': {'created': 1004, 'completed': 1005}, 'finish': 'stop'}, 'parts': [{'type': 'text', 'text': '## Objective'}]},
        {'info': {'id': 'msg_k', 'role': 'user', 'time': {'created': 1006}}, 'parts': [{'type': 'text', 'synthetic': True, 'text': 'Continue if you have next steps'}]},
        {'info': {'id': 'msg_a2', 'role': 'assistant', 'parentID': 'msg_k', 'time': {'created': 1007, 'completed': 1008}, 'finish': final_finish},
         'parts': [{'type': 'text', 'text': '已完成核对。'}]},
    ]


def test_synthetic_user_detection_and_origin():
    values = compacted('msg_user')
    assert [is_synthetic_user(m) for m in values] == [False, False, True, False, True, False]
    assert is_compaction_summary(values[3]) and not is_compaction_summary(values[1])
    assert origin_user_id(values, 'msg_k') == 'msg_user' and origin_user_id(values, 'msg_c') == 'msg_user'
    assert origin_user_id(values, 'msg_user') == 'msg_user' and origin_user_id(values, 'unknown') == 'unknown'
    mixed = {'info': {'role': 'user'}, 'parts': [{'type': 'text', 'synthetic': True, 'text': 'prelude'}, {'type': 'text', 'text': '问题'}]}
    assert not is_synthetic_user(mixed)


def test_public_messages_hide_compaction_turns():
    shown = public_messages(compacted('msg_user'))
    assert [m['info']['id'] for m in shown] == ['msg_user', 'msg_a1', 'msg_a2']


def test_track_messages_spans_compaction(provider, monkeypatch):
    from control.run_scheduler import track_messages
    store = provider[0]
    row = native_candidate(provider, monkeypatch)
    row = store.one('SELECT * FROM business_runs WHERE id=?', (row['id'],))
    assert track_messages(store, row, compacted(row['message_id']), {'state': 'finished'})
    done = store.one('SELECT * FROM business_runs WHERE id=?', (row['id'],))
    assert done['assistant_id'] == 'msg_a2' and done['status'] == 'completed'
    snapshot = store.decrypt(done['request_ciphertext'])
    assert 'msg_s' not in snapshot['observed_message_ids'] and 'msg_a2' in snapshot['observed_message_ids']
    assert '## Objective' not in snapshot.get('model_narrative', '')


def test_repeated_completed_call_returns_cached_result(provider, monkeypatch):
    s, uid, row = finished_source(provider, monkeypatch)
    again = native_tool_gate.prepare(s, uid, 'ses_multi', row['message_id'], 'call-two', tool('tracks'), ARGS, 1)
    assert again['cached'] is True and again['response']['kind'] == 'tracks'
    assert 'call-two' not in s.decrypt(s.one('SELECT request_ciphertext FROM business_runs WHERE id=?', (row['id'],))['request_ciphertext'])['native_calls']


def test_run_not_found_keeps_its_code():
    detail = public({'code': 'run_not_found'}, 'native_prepare', 'call')
    assert detail['code'] == 'run_not_found' and detail['dispatch_status'] == 'not_dispatched'


def test_gateway_rebinds_synthetic_parent(monkeypatch):
    app = FastAPI(); facts_execution.register(app)
    gate = SimpleNamespace(require_egress=lambda: None, boot_id='boot')
    app.state.runtime_management = SimpleNamespace(gate=gate)
    app.state.settings = SimpleNamespace(opencode_password='test', opencode_url='http://agent', control_url='http://control', runtime_key='test', runtime_id='runtime', revision=1)
    listing = compacted('msg_user')
    seen = []
    async def get(url, **kwargs):
        request = httpx.Request('GET', url)
        if url.endswith('/message'):
            return httpx.Response(200, request=request, json=listing)
        return httpx.Response(200, request=request, json={'info': {'role': 'assistant', 'sessionID': 'session', 'parentID': 'msg_k'},
            'parts': [{'type': 'tool', 'callID': 'call', 'tool': 'peixian_query_tracks', 'state': {'input': {}}}]})
    async def post(url, **kwargs):
        seen.append(kwargs['json']['message_id'])
        if kwargs['json']['message_id'] != 'msg_user':
            return httpx.Response(404, json={'detail': {'code': 'run_not_found', 'message': '执行记录不存在。'}})
        return httpx.Response(200, json={'ok': True})
    app.state.client = SimpleNamespace(get=get, post=post)
    async def native(request, app, value, rpc, parent, process):
        first = await rpc('native_prepare', message_id=parent)
        second = await rpc('provider_begin', message_id=parent)
        return {'first': first, 'second': second}
    monkeypatch.setattr(theft_provider_execution, 'execute_native', native)
    with TestClient(app) as client:
        body = {'session_id': 'session', 'message_id': 'assistant', 'tool': 'peixian_query_tracks', 'args': {}, 'call_id': 'call'}
        response = client.post('/internal/facts/execute', json=body)
        assert response.status_code == 200, response.text
        assert seen == ['msg_k', 'msg_user', 'msg_user']


def test_gateway_keeps_not_found_for_real_parent(monkeypatch):
    app = FastAPI(); facts_execution.register(app)
    gate = SimpleNamespace(require_egress=lambda: None, boot_id='boot')
    app.state.runtime_management = SimpleNamespace(gate=gate)
    app.state.settings = SimpleNamespace(opencode_password='test', opencode_url='http://agent', control_url='http://control', runtime_key='test', runtime_id='runtime', revision=1)
    async def get(url, **kwargs):
        request = httpx.Request('GET', url)
        if url.endswith('/message'):
            return httpx.Response(200, request=request, json=compacted('msg_user'))
        return httpx.Response(200, request=request, json={'info': {'role': 'assistant', 'sessionID': 'session', 'parentID': 'msg_user'},
            'parts': [{'type': 'tool', 'callID': 'call', 'tool': 'peixian_query_tracks', 'state': {'input': {}}}]})
    async def post(url, **kwargs):
        return httpx.Response(404, json={'detail': {'code': 'run_not_found', 'message': '执行记录不存在。'}})
    app.state.client = SimpleNamespace(get=get, post=post)
    async def native(request, app, value, rpc, parent, process):
        return await rpc('native_prepare', message_id=parent)
    monkeypatch.setattr(theft_provider_execution, 'execute_native', native)
    with TestClient(app) as client:
        body = {'session_id': 'session', 'message_id': 'assistant', 'tool': 'peixian_query_tracks', 'args': {}, 'call_id': 'call'}
        response = client.post('/internal/facts/execute', json=body)
        assert response.status_code == 404 and response.json()['detail']['code'] == 'run_not_found'


def test_profile_sentence_renders_person_and_captures():
    fields = {'person': {'sfz': 'person-abc', 'name': '王芳', 'gender': '女', 'age': 47},
              'captures': [{'captureTime': '2026-09-18 21:37:01', 'deviceId': 'DEV-03', 'deviceName': '龙城小区南门', 'xwbq': ['夜间']},
                           {'captureTime': '2026-09-18 23:42:18', 'deviceId': 'DEV-07', 'deviceName': '火车站广场'}],
              'warning': {'warningCount': 3}}
    text = sentence('profile', fields)
    assert text.startswith('王芳（person-abc）；性别 女；年龄 47 岁；来源预警 3 条。最近 2 条抓拍：')
    lines = text.split('\n')[1:]
    assert lines == ['- 2026-09-18 23:42:18，火车站广场（DEV-07）', '- 2026-09-18 21:37:01，龙城小区南门（DEV-03）；标签 夜间']
    assert '来源未返回最近抓拍' in sentence('profile', {'person': {'name': '王芳'}, 'captures': []})
    from control.table_answer import escape
    assert escape(text).endswith('最近 2 条抓拍：2026-09-18 23:42:18，火车站广场（DEV-07）；2026-09-18 21:37:01，龙城小区南门（DEV-03）；标签 夜间')
