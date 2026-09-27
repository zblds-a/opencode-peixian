import asyncio
import copy
from types import SimpleNamespace

from shared import theft_provider_v2 as v
from gateway import theft_provider_execution as ex
from control import business_runs as runs
from control.facts_runtime import tool
from test_backend_v6 import v6  # noqa: F401
from test_facts_runtime import facts  # noqa: F401
from test_provider_contract_v2 import ID, KEY, LIMITS, REF

START, MIDDLE, END = '2026-08-01 00:00:00', '2026-08-16 00:00:00', '2026-09-01 00:00:00'


def track_public(count=236):
    points = []
    for i in range(count):
        day, hour = 1 + i % 31, (i * 7) % 24
        points.append({'deviceId': 'dev-%02d' % (i % 17), 'deviceName': '沛县某街道某小区东门人脸抓拍点位%02d号' % (i % 17),
                       'captureTime': '2026-08-%02d %02d:%02d:00' % (day, hour, i % 60),
                       'trackType': 0, 'trackTypeDesc': '人脸', 'lon': 116.9 + i / 1e4, 'lat': 34.7 + i / 1e4,
                       'faceStoragePath': 'http://internal/f/%d.jpg' % i})
    points.sort(key=lambda p: p['captureTime'])
    payload = {'code': 200, 'data': {'targetIdCard': ID, 'points': points,
               'segments': [{'start': START, 'end': MIDDLE, 'status': 'ok'}, {'start': MIDDLE, 'end': END, 'status': 'too_many'}]}}
    result = v.parse_response('tracks', {'person_ref': REF, 'start': START, 'end': END}, payload, LIMITS, {REF: ID})
    return v.public_result(result, KEY, 'account/session'), points


def test_track_summary_is_small_and_keeps_counts_and_segments():
    public, points = track_public()
    view = v.model_view(public)
    size = len(v.canonical(view).encode())
    assert size <= 8 * 1024 < len(v.canonical(public).encode())
    assert 'records' not in view and view['returned_count'] == 236
    assert view['coverage'] == 'partial' and view['segments'] == public['segments']
    assert sum(d['count'] for d in view['daily']) == 236 and len(view['daily']) == 31
    night = sum(1 for p in points if int(p['captureTime'][11:13]) >= 22 or int(p['captureTime'][11:13]) < 6)
    assert view['night_count'] == night
    assert view['first']['time'] == points[0]['captureTime'] and view['last']['time'] == points[-1]['captureTime']
    assert view['device_count'] == 17 and len(view['top_devices']) == 10
    assert view['top_devices'][0]['count'] >= view['top_devices'][-1]['count']
    assert view['response_snapshot_id'] == public['response_snapshot_id'] and view['note']
    assert view['first']['source_ref'].startswith(public['response_snapshot_id'] + ':')
    assert ID not in v.canonical(view) and 'http' not in v.canonical(view)
    assert len(public['records']) == 236


def test_small_non_track_result_passes_through_unchanged():
    public = {'version': v.VERSION, 'kind': 'profile', 'records': [{'source_ref': 'r:1', 'fields': {'person': {'name': 'x'}}}], 'returned_count': 1}
    assert v.model_view(public) is public
    assert v.model_view({'status': 'needs_input'}) == {'status': 'needs_input'}


def test_large_non_track_result_keeps_totals_and_fits_budget():
    records = [{'source_ref': 's:%d' % i, 'fields': {'target_name': '某' * 200, 'capture_count': i}} for i in range(400)]
    public = {'version': v.VERSION, 'kind': 'captures', 'records': records, 'returned_count': 400, 'total': 900}
    view = v.model_view(public)
    assert len(v.canonical(view).encode()) <= v.MODEL_VIEW_MAX_BYTES
    assert view['records_in_view'] == len(view['records']) <= 50
    assert view['returned_count'] == 400 and view['total'] == 900 and len(public['records']) == 400


def test_gateway_cached_native_result_returns_summary():
    public, _ = track_public()

    async def rpc(action, **fields):
        assert action == 'native_prepare'
        return {'cached': True, 'response': copy.deepcopy(public)}
    value = {'session_id': 's', 'call_id': 'call', 'tool': 'peixian_query_tracks', 'args': {}}
    result = asyncio.run(ex._execute_native(None, None, value, rpc, 'parent', None))
    assert result == v.model_view(public) and 'records' not in result


def test_gateway_native_execute_returns_summary_but_frozen_path_stays_full():
    public, _ = track_public()
    gate = SimpleNamespace(require_egress=lambda: None)
    app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(managed_root='unused'), runtime_management=SimpleNamespace(gate=gate)))

    async def rpc(action, **fields):
        if action == 'provider_begin':
            return {'run_id': 'run', 'operation': 'op', 'plan': {'tool_id': 'peixian_query_tracks', 'kind': 'tracks'}}
        if action == 'provider_reserve':
            return {'reserved': False}
        if action == 'provider_read':
            item = {'status': 'completed', 'response': copy.deepcopy(public)}
            return {'state': {'modules': {'call': item, 'tracks': item}}}
        return {}
    native = asyncio.run(ex.execute(None, app, {'session_id': 's', 'call_id': 'call', 'tool': 'peixian_query_tracks', 'args': {'start': START}}, rpc, 'parent', None, native=True))
    assert 'records' not in native and native['returned_count'] == 236
    frozen = asyncio.run(ex.execute(None, app, {'session_id': 's', 'call_id': 'call', 'tool': 'peixian_query_tracks', 'args': {}}, rpc, 'parent', None))
    assert len(frozen['records']) == 236


def replay_run_358(facts, skill_enabled):
    from control.run_scheduler import track_messages
    s, uid, rid, _ = facts
    with s.tx() as db:
        row = db.execute('SELECT request_ciphertext FROM business_runs WHERE id=?', (rid,)).fetchone()
        snapshot = s.decrypt(row[0])
        snapshot.pop('facts_plan', None)
        snapshot['task_spec'] = snapshot.get('task_spec') or {'intent': 'person_to_case'}
        snapshot['native_tool_policy'] = {'version': 'native-provider-gate-v1', 'allowed_tools': [tool('night')]}
        snapshot.setdefault('payload', {})['tools'] = {'question': True, 'skill': False, 'peixian_load_personal_skill': skill_enabled, tool('night'): True}
        db.execute('UPDATE business_runs SET request_ciphertext=? WHERE id=?', (s.encrypt(snapshot), rid))
    row = s.one('SELECT * FROM business_runs WHERE id=?', (rid,))
    values = [{'info': {'id': row['message_id'], 'role': 'user', 'time': {'created': 1000}}, 'parts': []},
              {'info': {'id': 'msg_a', 'role': 'assistant', 'time': {'created': 1000}},
               'parts': [{'id': 'prt_skill', 'type': 'tool', 'tool': 'peixian_load_personal_skill',
                          'state': {'status': 'completed', 'input': {'skill_id': 'skill-1'}, 'time': {'start': 1000, 'end': 1100}}},
                         {'id': 'prt_question', 'type': 'tool', 'tool': 'question',
                          'state': {'status': 'running', 'input': {}, 'time': {'start': 1200}}}]}]
    track_messages(s, row, values, {tool('night'): 'plugin-night'})
    return s, rid


def test_personal_skill_load_then_question_is_not_a_plan_violation(facts):
    s, rid = replay_run_358(facts, True)
    assert s.one("SELECT 1 FROM run_events WHERE run_id=? AND event_key LIKE 'plan-denied.%'", (rid,)) is None
    assert s.one('SELECT cancel_requested FROM business_runs WHERE id=?', (rid,))['cancel_requested'] == 0


def test_personal_skill_tool_still_denied_when_not_enabled(facts):
    s, rid = replay_run_358(facts, False)
    assert s.one("SELECT status FROM run_events WHERE run_id=? AND event_key='plan-denied.prt_skill'", (rid,))['status'] == 'rejected'
    assert s.one("SELECT 1 FROM run_events WHERE run_id=? AND event_key='plan-denied.prt_question'", (rid,)) is None
